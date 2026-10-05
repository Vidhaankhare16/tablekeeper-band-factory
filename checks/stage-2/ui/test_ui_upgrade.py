"""Existing clients after an upgrade: a stage-1 export imported into the stage-2 service (ledger L2.16, L2.32)."""
import json
import pytest
from uikit import *  # noqa: F401,F403
from conftest import Client, call


def prev(method, path, **kw):
    import conftest
    kw.setdefault("timeout", 10.5)
    h = http_call_to(PREV_URL, method, path, **kw)
    return h


def http_call_to(base, method, path, json=None, raw=None, token=None, key=None, timeout=9.0):
    import http.client, urllib.parse
    u = urllib.parse.urlparse(base)
    import json as _j
    hdr = {"Accept": "application/json"}
    body = None
    if json is not None:
        body = _j.dumps(json).encode(); hdr["Content-Type"] = "application/json"
    if token: hdr["Authorization"] = f"Bearer {token}"
    if key is not None: hdr["Idempotency-Key"] = key
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=hdr)
        r = c.getresponse()
        from conftest import Resp
        return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
    finally:
        c.close()


@pytest.fixture
def old():
    """The accepted stage-1 service, seeded with the plain fixture (Ada, Bob, r_anker 3 tables)."""
    try:
        r = http_call_to(PREV_URL, "GET", "/health")
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"[L2.16] the accepted stage-1 service is not reachable at {PREV_URL} (run checks/stage-2/prev_up.sh): {e}")
    assert r.status == 200
    fx = fixture(restaurants=[restaurant(), restaurant("r_two", name="Zwei", tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])])
    assert http_call_to(PREV_URL, "POST", "/_test/reset", json=fx).status == 204
    o = Seed()
    o.fx, o.date = fx, safe_date()
    tok = http_call_to(PREV_URL, "POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).json
    o.token, o.user_id = tok["token"], tok["user_id"]
    return o


def old_book(o, table="t_2", at="19:00", party=4, key=None):
    r = http_call_to(PREV_URL, "POST", "/reservations", token=o.token, key=key or new_key(),
                     json={"restaurant_id": "r_anker", "table_id": table, "starts_at_local": f"{o.date}T{at}", "party_size": party})
    assert r.status == 201, r
    return r.json


def upgrade(o=None):
    """export from the stage-1 service, import into the stage-2 service (the thing under test)."""
    e = http_call_to(PREV_URL, "GET", "/_test/export")
    assert e.status == 200, f"stage-1 export failed: {e!r}"
    r = call("POST", "/_test/import", json=e.json, timeout=10.5)
    assert r.status == 204, f"[L2.16] stage-2 must accept an unchanged stage-1 export (204), got {r!r}"
    return e.json


def token_storage_key(browser_ctx):
    """Discover where the UI keeps its session by signing in through the UI on a scratch stage-2 state."""
    reset(fixture(restaurants=[restaurant(combinable=PAIRS)]))
    ctx = browser_ctx(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    log_in(pg)
    tok = call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).json["token"]
    found = pg.evaluate("""() => { const out = []; for (const st of ['localStorage', 'sessionStorage']) { const s = window[st];
        for (let i = 0; i < s.length; i++) out.push([st, s.key(i), s.getItem(s.key(i))]); } return out; }""")
    cookies = ctx.cookies()
    ctx.close()
    return found, cookies


def injected_context(browser_ctx, found, token):
    """A browser context whose stored UI session is the one the UI wrote at sign-in, but carrying `token`."""
    ctx = injected_context(browser_ctx, found, old.token)
    pg = ctx.new_page()
    pg.goto("/")
    pg.wait_for_selector(T("current-user"))
    do_search(pg, old.date, 4, goto=False)
    open_form(pg, "t_2-19:00")
    log = lose_bookings(pg, commit=True, count=1, forward_to=PREV_URL)       # the commit happens on the OLD service
    pg.click(T("booking-submit"))
    pg.wait_for_selector(T("booking-uncertain"))
    assert pg.query_selector(T("confirmation")) is None and pg.query_selector(T("booking-error")) is None
    committed = http_call_to(PREV_URL, "GET", "/reservations", token=old.token).json["reservations"]
    new_ref = [r["reference"] for r in committed if r["reference"] != ref0]
    assert len(new_ref) == 1, "setup: the booking committed on the stage-1 service"
    upgrade(old)                                              # E1: upgrade completes between browser requests
    assert pg.query_selector(T("booking-form")) is not None and pg.input_value(T("booking-party-size")) == "4", "[L2.16] the form survives"
    pg.click(T("booking-submit"))                              # same key + body, now answered by the stage-2 service
    pg.wait_for_selector(T("confirmation"))
    assert pg.text_content(T("confirmation-reference")).strip() == new_ref[0], "[L2.16] the original confirmation is recovered after import"
    assert log[1]["key"] == log[0]["key"] and log[1]["body"] == log[0]["body"], f"[L2.16] retry identity unchanged: {log}"
    assert pg.query_selector(T("booking-uncertain")) is None and pg.query_selector(T("booking-error")) is None
    t = pg.text_content(T("confirmation-tables"))
    assert "2" in t, f"[L2.16/L2.31] confirmation-tables is filled from a replayed stage-1 receipt (table_id fallback): {t!r}"
    assert "Zum Anker" in pg.text_content(T("confirmation-details")) and "19:00" in pg.text_content(T("confirmation-details"))
    mine = call("GET", "/reservations", token=old.token).json["reservations"]
    assert len(mine) == 2 and sorted(r["reference"] for r in mine) == sorted([ref0, new_ref[0]]), "[L2.16] exactly one new booking"
    assert "Ada" in pg.text_content(T("current-user")), "[L2.16] still signed in"
    ctx.close()


def test_L2_32_api_level_stage1_receipts_and_tokens_after_import(old):
    key = new_key()
    b = old_book(old, "t_2", "19:00", 4, key=key)
    cancelled = old_book(old, "t_1", "21:00", 2)
    http_call_to(PREV_URL, "POST", f"/reservations/{cancelled['reference']}/cancel", token=old.token)
    failed_key = new_key()
    r = http_call_to(PREV_URL, "POST", "/reservations", token=old.token, key=failed_key,
                     json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{old.date}T19:30", "party_size": 4})
    assert r.status == 409
    mv_key = new_key()
    mv = http_call_to(PREV_URL, "POST", "/reservation-moves", token=old.token, key=mv_key,
                      json={"moves": [{"reference": b["reference"], "table_id": "t_3", "party_size": 5}]})
    assert mv.status == 201
    sg = http_call_to(PREV_URL, "POST", "/auth/signup", json={"email": "old@example.com", "password": "old-password", "display_name": "Old"}).json
    upgrade(old)
    bod = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{old.date}T19:00", "party_size": 4}
    rep = call("POST", "/reservations", json=bod, token=old.token, key=key)
    assert rep.status == 200, f"[L2.32] stage-1 receipts are honoured: {rep!r}"
    for k, v in b.items():
        assert rep.json.get(k) == v, f"[L2.32] replay keeps the original response field {k}: {rep.json}"
    assert rep.json.get("table_ids", [rep.json["table_id"]]) in (["t_2"],), "[L2.32] table_ids, when present, matches"
    again = call("POST", "/reservation-moves", json={"moves": [{"reference": b["reference"], "table_id": "t_3", "party_size": 5}]},
                 token=old.token, key=mv_key)
    assert again.status == 200 and [x["reference"] for x in again.json["reservations"]] == [b["reference"]], f"[L2.32] {again!r}"
    ok = call("POST", "/reservations", json={**bod, "starts_at_local": f"{old.date}T20:30", "table_id": "t_1", "party_size": 2},
              token=old.token, key=failed_key)
    assert ok.status == 201, f"[L2.32] failed keys reusable: {ok!r}"
    assert call("GET", "/reservations", token=sg["token"]).status == 200, "[L2.32] tokens of accounts created at stage 1 still work"
    assert call("POST", "/auth/login", json={"email": "old@example.com", "password": "old-password"}).status == 200
    got = call("GET", f"/reservations/{b['reference']}", token=old.token).json
    assert got["reference"] == b["reference"] and got["reservation_id"] == b["reservation_id"] and got["created_at"] == b["created_at"], "[L2.32]"
    assert got["table_ids"] == ["t_3"] and got["table_id"] == "t_3" and got["party_size"] == 5
    assert call("GET", f"/reservations/{cancelled['reference']}", token=old.token).json["status"] == "cancelled"
    bob = call("POST", "/auth/login", json={"email": "bob@example.com", "password": PW}).json
    assert call("GET", f"/reservations/{b['reference']}", token=bob["token"]).status == 404
    s = call("GET", f"/availability?restaurant_id=r_anker&date={old.date}&party_size=1").json["slots"]
    at = {x["starts_at_local"][-5:]: x for x in s}
    assert "t_3" not in at["19:00"]["available_table_ids"] and "t_2" in at["19:00"]["available_table_ids"], "[L2.32] occupancy migrated"
    assert at["19:00"]["available_options"], "[L2.32] available_options exist for imported restaurants"
    assert call("GET", "/restaurants/r_anker").json.get("combinable", []) == [], "[L2.32] restaurants default to no combinations"
    # new combos impossible on an imported restaurant without declared pairs
    r = call("POST", "/reservations", json={**bod, "table_id": None, "table_ids": ["t_1", "t_2"], "starts_at_local": f"{old.date}T21:00", "party_size": 6},
             token=old.token, key=new_key())
    r2 = call("POST", "/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{old.date}T21:00", "party_size": 6},
              token=old.token, key=new_key())
    assert r2.status == 422 and r2.json["error"]["code"] == "combination_not_allowed"
