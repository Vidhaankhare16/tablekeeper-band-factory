"""Routes, navigation, signup/login (ledger L2.1, L2.2, L2.9)."""
import pytest
from uikit import *  # noqa: F401,F403


@pytest.mark.parametrize("route,anchor", [("/", "search-button"), ("/signup", "signup-submit"),
                                          ("/login", "login-submit"), ("/lookup", "lookup-submit")])
def test_L2_1_routes_return_html_and_are_directly_navigable(seeded, page, route, anchor):
    r = call("GET", route)
    assert r.status == 200, f"[L2.1] GET {route} must be 200, got {r.status}"
    ct = r.headers.get("content-type", "").lower()
    assert "text/html" in ct, f"[L2.1] {route} must return HTML (not application/json), got {ct!r}"
    assert "<html" in r.text.lower() or "<!doctype" in r.text.lower() or "<div" in r.text.lower(), "[L2.1] HTML body"
    page.goto(route)
    page.wait_for_selector(T(anchor), state="attached")
    assert page.is_visible(T(anchor)), f"[L2.1] {anchor} must be visible on {route}"


def test_L2_1_routes_with_query_and_trailing_slash_do_not_break_api(seeded, page):
    assert call("GET", "/health").json == {"status": "ok"}
    assert call("GET", "/restaurants").status == 200 and "json" in call("GET", "/restaurants").headers["content-type"]
    r = call("GET", "/lookup?x=1")
    assert r.status == 200 and "html" in r.headers.get("content-type", "").lower(), "[L2.1] query string ignored on screen routes"


def test_L2_2_screens_reachable_through_the_ui(seeded, page):
    for route in ("/", "/login", "/signup", "/lookup"):
        page.goto(route)
        for target in ("/", "/login", "/signup", "/lookup"):
            if target == route:
                continue
            assert page.query_selector(f"a[href='{target}']") is not None, \
                f"[L2.2] consistent navigation: {route} must link to {target}"
    page.goto("/")
    page.click("a[href='/login']")
    page.wait_for_selector(T("login-submit"))
    page.click("a[href='/signup']")
    page.wait_for_selector(T("signup-submit"))
    page.click("a[href='/lookup']")
    page.wait_for_selector(T("lookup-submit"))
    page.click("a[href='/']")
    page.wait_for_selector(T("search-button"))


def test_L2_9_login_logout_and_current_user_everywhere(seeded, page):
    log_in(page)
    assert "Ada" in page.text_content(T("current-user"))
    for route in ("/", "/lookup", "/login", "/signup"):
        page.goto(route)
        page.wait_for_selector(T("current-user"))
        assert "Ada" in page.text_content(T("current-user")), f"[L2.9] current-user must show the display name on {route}"
        assert page.is_visible(T("current-user")) and page.is_visible(T("logout-button")), f"[L2.9] visible on {route}"
    page.click(T("logout-button"))
    page.wait_for_selector(T("current-user"), state="detached")
    assert page.query_selector(T("logout-button")) is None or not page.is_visible(T("logout-button"))


def test_L2_9_signed_in_state_persists_across_reload_and_tabs(seeded, page):
    log_in(page)
    page.reload()
    page.wait_for_selector(T("current-user"))
    page.goto("/lookup")
    page.wait_for_selector(T("current-user"))
    tab2 = page.context.new_page()
    tab2.goto("/")
    tab2.wait_for_selector(T("current-user"))
    assert "Ada" in tab2.text_content(T("current-user")), "[L2.9] same browser profile stays signed in"
    page.click(T("logout-button"))
    page.reload()
    page.wait_for_load_state("load")
    page.wait_for_timeout(300)
    assert page.query_selector(T("current-user")) is None, "[L2.9] logout survives a reload"


def test_L2_9_signed_out_by_default_no_current_user_no_error(seeded, page):
    for route in ("/", "/login", "/signup", "/lookup"):
        page.goto(route)
        page.wait_for_load_state("load")
        assert page.query_selector(T("current-user")) is None, f"[L2.9] current-user only when signed in ({route})"
        assert page.query_selector(T("auth-error")) is None, f"[L2.9] auth-error present only when there is one ({route})"


def test_L2_9_signup_creates_account_and_signs_in(seeded, page):
    page.goto("/signup")
    page.fill(T("signup-email"), "newbie@example.com")
    page.fill(T("signup-password"), "a-long-password")
    page.fill(T("signup-display-name"), "Nia")
    page.click(T("signup-submit"))
    page.wait_for_selector(T("current-user"))
    assert "Nia" in page.text_content(T("current-user"))
    assert page.query_selector(T("auth-error")) is None
    r = call("POST", "/auth/login", json={"email": "newbie@example.com", "password": "a-long-password"})
    assert r.status == 200 and r.json["display_name"] == "Nia", f"[L2.9] the account really exists on the server: {r!r}"
    page.click(T("logout-button"))
    log_in(page, "newbie@example.com", "a-long-password")
    assert "Nia" in page.text_content(T("current-user"))


@pytest.mark.parametrize("email,pw,name", [("ada@example.com", "a-long-password", "Dup"), ("x@example.com", "short", "S"),
                                           ("not-an-email", "a-long-password", "E"), ("a@", "a-long-password", "E")])
def test_L2_9_signup_errors_show_auth_error(seeded, page, email, pw, name):
    page.goto("/signup")
    page.fill(T("signup-email"), email)
    page.fill(T("signup-password"), pw)
    page.fill(T("signup-display-name"), name)
    page.click(T("signup-submit"))
    page.wait_for_selector(T("auth-error"))
    assert page.text_content(T("auth-error")).strip(), "[L2.9] auth-error has text"
    assert page.query_selector(T("current-user")) is None, "[L2.9] a failed signup does not sign in"


def test_L2_9_signup_error_clears_after_success(seeded, page):
    page.goto("/signup")
    page.fill(T("signup-email"), "ada@example.com")
    page.fill(T("signup-password"), "a-long-password")
    page.fill(T("signup-display-name"), "Dup")
    page.click(T("signup-submit"))
    page.wait_for_selector(T("auth-error"))
    page.fill(T("signup-email"), "fresh@example.com")
    page.click(T("signup-submit"))
    page.wait_for_selector(T("current-user"))
    assert page.query_selector(T("auth-error")) is None, "[L2.9] auth-error present only when there is one"


@pytest.mark.parametrize("email,pw", [("ada@example.com", "wrong password"), ("ghost@example.com", "correct horse")])
def test_L2_9_login_errors_show_auth_error(seeded, page, email, pw):
    log_in(page, email, pw, ok=False)
    page.wait_for_selector(T("auth-error"))
    assert page.text_content(T("auth-error")).strip()
    assert page.query_selector(T("current-user")) is None
    log_in(page)    # then success removes the error
    assert page.query_selector(T("auth-error")) is None, "[L2.9] auth-error gone after success"


def test_L2_9_login_by_enter_key_and_keyboard(seeded, page):
    page.goto("/login")
    page.fill(T("login-email"), "bob@example.com")
    page.fill(T("login-password"), PW)
    page.press(T("login-password"), "Enter")
    page.wait_for_selector(T("current-user"))
    assert "Bob" in page.text_content(T("current-user")), "[L2.9] a form submits with Enter"
