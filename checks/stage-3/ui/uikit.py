"""Browser fixtures and helpers for the stage-2 UI checks (headless Chromium via Playwright)."""
from __future__ import annotations

import os
import re
import sys
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import (BASE, PW, call, check, fixture, login, new_key, reset, restaurant, safe_date,  # noqa: E402,F401
                      all_week, user)

CHROME = os.environ.get("TK_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
PREV_URL = os.environ.get("TK_PREV_URL", "http://127.0.0.1:8081").rstrip("/")
PAIRS = [["t_1", "t_2"], ["t_2", "t_3"]]


def T(name):
    return f"[data-testid='{name}']"


_BROWSER = {}


def _launch():
    """One shared Chromium for the whole run (the fixture below is imported into several test modules)."""
    if "b" not in _BROWSER:
        import atexit
        from playwright import sync_api as p
        d = p.sync_playwright().start()
        b = d.chromium.launch(executable_path=CHROME if os.path.exists(CHROME) else None,
                              args=["--no-sandbox", f"--unsafely-treat-insecure-origin-as-secure={BASE}"])
        _BROWSER["b"], _BROWSER["d"] = b, d

        def close():
            try:
                b.close(); d.stop()
            except Exception:  # noqa: BLE001
                pass
        atexit.register(close)
    return _BROWSER["b"]


@pytest.fixture
def pw_browser():
    return _launch()


@pytest.fixture
def page(pw_browser):
    ctx = pw_browser.new_context(base_url=BASE, viewport={"width": 1280, "height": 800})
    ctx.set_default_timeout(10_000)
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture
def mobile(pw_browser):
    ctx = pw_browser.new_context(base_url=BASE, viewport={"width": 375, "height": 812}, device_scale_factor=2, has_touch=True)
    ctx.set_default_timeout(10_000)
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture
def browser_ctx(pw_browser):
    def make(**kw):
        ctx = pw_browser.new_context(base_url=BASE, **kw)
        ctx.set_default_timeout(10_000)
        return ctx
    return make


class Seed:
    pass


@pytest.fixture
def seeded():
    """Default UI world: r_anker (tables 1,2,3 = cap 2,4,6; pairs 1+2 (6) and 2+3 (10)), r_two, Ada/Bob/Cy."""
    o = Seed()
    o.fx = fixture(restaurants=[restaurant(combinable=PAIRS),
                                restaurant("r_two", name="Zwei", tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])])
    reset(o.fx)
    o.date, o.date2 = safe_date(), safe_date(1)
    o.api_ada, o.api_bob = login("ada@example.com"), login("bob@example.com")
    return o


def log_in(page, email="ada@example.com", password=PW, ok=True):
    page.goto("/login")
    page.fill(T("login-email"), email)
    page.fill(T("login-password"), password)
    page.click(T("login-submit"))
    if ok:
        page.wait_for_selector(T("current-user"))


def do_search(page, date, party, rid="r_anker", goto=True, wait=True):
    if goto:
        page.goto("/")
    page.select_option(T("restaurant-select"), rid)
    page.fill(T("date-input"), date)
    page.fill(T("party-size-input"), str(party))
    page.click(T("search-button"))
    if wait:
        page.wait_for_selector(f"{T('availability-grid')}, {T('no-slots')}")


def cells(page):
    """{testid-suffix: data-available} for every grid cell, e.g. {'t_2-19:00': True, 't_1+t_2-19:00': False}."""
    return page.evaluate("""() => Object.fromEntries([...document.querySelectorAll("[data-testid^='slot-']")]
        .map(e => [e.getAttribute('data-testid').slice(5), e.getAttribute('data-available')]))""")


def wait_cell(page, suffix, available, timeout=10_000):
    page.wait_for_selector(f"{T('slot-' + suffix)}[data-available='{'true' if available else 'false'}']", timeout=timeout)


def open_form(page, suffix):
    page.click(T("slot-" + suffix))
    page.wait_for_selector(T("booking-form"))


def book_ui(page, suffix, date, party, rid="r_anker"):
    do_search(page, date, party, rid)
    open_form(page, suffix)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    return page.text_content(T("confirmation-reference")).strip()


def lookup(page, ref):
    page.goto("/lookup")
    page.fill(T("lookup-reference-input"), ref)
    page.click(T("lookup-submit"))


def lose_bookings(page, commit=True, count=1, forward_to=None):
    """Intercept POST /reservations: record key+body; for the first `count` calls, optionally let the server commit
    (or forward to another server), then drop the response."""
    log = []

    def h(route):
        req = route.request
        if req.method == "POST" and urllib.parse.urlparse(req.url).path == "/reservations":
            n = len(log) + 1
            log.append({"n": n, "key": req.headers.get("idempotency-key"), "body": req.post_data_json})
            if n <= count:
                if commit:
                    if forward_to:
                        route.fetch(url=forward_to + "/reservations")
                    else:
                        route.fetch()
                route.abort("connectionreset")
                return
        route.continue_()
    page.route("**/reservations", h)
    return log


def record_bookings(page):
    log = []

    def h(route):
        req = route.request
        if req.method == "POST" and urllib.parse.urlparse(req.url).path == "/reservations":
            log.append({"key": req.headers.get("idempotency-key"), "body": req.post_data_json})
        route.continue_()
    page.route("**/reservations", h)
    return log


def tables_of(body):
    if "table_ids" in body:
        return sorted(body["table_ids"])
    return [body["table_id"]]


def hold_availability(page, match):
    held = []

    def h(route):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(route.request.url).query))
        if match(q):
            held.append(route)
        else:
            route.continue_()
    page.route("**/availability*", h)
    return held


def my_reservations(api_client):
    return api_client.get("/reservations").json["reservations"]
