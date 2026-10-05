"""Product quality: viewports, labels, focus, contrast, states, human-readable labels (ledger L2.17)."""
import pytest
from uikit import *  # noqa: F401,F403

NOSCROLL = "() => ({sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth, iw: window.innerWidth})"

CONTRAST_JS = """
() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(s => parseFloat(s));
                       return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                     return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const blend = (top, bottom) => ({r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a),
                                   b: top.b * top.a + bottom.b * (1 - top.a), a: 1});
  const bgOf = el => { let layers = []; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
      let base = {r: 255, g: 255, b: 255, a: 1}; for (const l of layers.reverse()) base = blend(l, base); return base; };
  const out = [];
  const els = [...document.querySelectorAll('h1,h2,h3,p,label,button,a,span,td,th,li,input,select,[data-testid]')];
  for (const el of els) {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0) || el.tagName === 'INPUT' || el.tagName === 'SELECT';
    if (!own) continue;
    const fg = parse(cs.color); const bg = bgOf(el); if (!fg || !bg) continue;
    const f = blend(fg, bg); const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize); const bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    if (ratio < need) out.push({tag: el.tagName, id: el.getAttribute('data-testid'), text: (el.textContent || '').trim().slice(0, 30),
                                ratio: Math.round(ratio * 100) / 100, need, disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true'});
  }
  return out;
}
"""

LABELS_JS = """
() => [...document.querySelectorAll('input,select,textarea')].filter(e => e.type !== 'hidden').map(e => {
  const r = e.getBoundingClientRect(); const visible = r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
  let text = '';
  if (e.labels && e.labels.length) text = [...e.labels].map(l => l.textContent.trim()).join(' ');
  if (!text && e.getAttribute('aria-labelledby')) text = e.getAttribute('aria-labelledby').split(' ').map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim();
  if (!text) text = (e.getAttribute('aria-label') || '').trim();
  return {id: e.getAttribute('data-testid') || e.name || e.id, visible, text};
}).filter(x => x.visible)
"""


def no_hscroll(pg, where):
    m = pg.evaluate(NOSCROLL)
    assert m["sw"] <= m["iw"] + 1 and m["bw"] <= m["iw"] + 1, f"[L2.17] horizontal page scroll at {where}: {m}"


@pytest.mark.parametrize("fx_name", ["page", "mobile"])
def test_L2_17_no_horizontal_scroll_on_every_screen_and_flow(seeded, request, fx_name):
    pg = request.getfixturevalue(fx_name)
    vp = pg.viewport_size["width"]
    for route in ("/", "/login", "/signup", "/lookup"):
        pg.goto(route)
        pg.wait_for_load_state("load")
        no_hscroll(pg, f"{route} @ {vp}px")
    log_in(pg)
    no_hscroll(pg, f"signed-in header @ {vp}px")
    do_search(pg, seeded.date, 2)
    no_hscroll(pg, f"availability grid (singles) @ {vp}px")
    do_search(pg, seeded.date, 6)
    no_hscroll(pg, f"availability grid (with combination cells) @ {vp}px")
    open_form(pg, "t_1+t_2-19:00")
    no_hscroll(pg, f"booking form (combination) @ {vp}px")
    pg.click(T("booking-submit"))
    pg.wait_for_selector(T("confirmation"))
    no_hscroll(pg, f"confirmation @ {vp}px")
    ref = pg.text_content(T("confirmation-reference")).strip()
    # error / uncertain states
    pg.click(T("slot-t_3-20:30"))
    pg.wait_for_function("document.querySelector(\"[data-testid='booking-summary']\").textContent.includes('3')")
    pg.fill(T("booking-party-size"), "9")
    pg.click(T("booking-submit"))
    pg.wait_for_selector(T("booking-error"))
    no_hscroll(pg, f"booking error @ {vp}px")
    pg.fill(T("booking-party-size"), "5")
    lose_bookings(pg, commit=False, count=1)
    pg.click(T("booking-submit"))
    pg.wait_for_selector(T("booking-uncertain"))
    no_hscroll(pg, f"booking uncertain @ {vp}px")
    lookup(pg, ref)
    pg.wait_for_selector(T("reservation-detail"))
    no_hscroll(pg, f"lookup detail @ {vp}px")
    lookup(pg, "NOPE12")
    pg.wait_for_selector(T("reservation-error"))
    no_hscroll(pg, f"lookup error @ {vp}px")
    pg.goto("/login")
    pg.click(T("logout-button"))
    pg.fill(T("login-email"), "ada@example.com")
    pg.fill(T("login-password"), "bad password")
    pg.click(T("login-submit"))
    pg.wait_for_selector(T("auth-error"))
    no_hscroll(pg, f"auth error @ {vp}px")


def test_L2_17_core_controls_are_usable_at_375px(seeded, mobile):
    log_in(mobile)
    do_search(mobile, seeded.date, 4)
    for sel in ("slot-t_2-19:00",):
        box = mobile.locator(T(sel)).bounding_box()
        assert box and box["x"] >= -1 and box["x"] + box["width"] <= 376, f"[L2.17] {sel} must be fully reachable without scrolling sideways: {box}"
        assert box["height"] >= 24 and box["width"] >= 24, f"[L2.17] tap target too small: {box}"
    mobile.click(T("slot-t_2-19:00"))
    mobile.wait_for_selector(T("booking-form"))
    for tid in ("booking-submit", "booking-party-size", "booking-summary"):
        mobile.locator(T(tid)).scroll_into_view_if_needed()
        box = mobile.locator(T(tid)).bounding_box()
        assert box["x"] >= -1 and box["x"] + box["width"] <= 376, f"[L2.17] {tid} within the 375px viewport: {box}"
    mobile.click(T("booking-submit"))
    mobile.wait_for_selector(T("confirmation"))
    mobile.locator(T("confirmation-reference")).scroll_into_view_if_needed()
    assert mobile.locator(T("confirmation-reference")).is_visible()


@pytest.mark.parametrize("route", ["/", "/login", "/signup", "/lookup"])
def test_L2_17_inputs_have_visible_labels(seeded, page, route):
    page.goto(route)
    page.wait_for_load_state("load")
    items = page.evaluate(LABELS_JS)
    assert items, f"[L2.17] {route} has inputs"
    for it in items:
        assert it["text"], f"[L2.17] input {it['id']!r} on {route} needs a visible label (label/aria-label), not just a placeholder"


def test_L2_17_booking_form_inputs_labelled(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    for it in page.evaluate(LABELS_JS):
        assert it["text"], f"[L2.17] input {it['id']!r} needs a label"


def test_L2_17_keyboard_focus_is_apparent(seeded, page):
    page.goto("/login")
    for tid in ("login-email", "login-password", "login-submit"):
        loc = page.locator(T(tid))
        before = page.evaluate("(s) => { const e = document.querySelector(s); const c = getComputedStyle(e); "
                               "return [c.outlineStyle, c.outlineWidth, c.boxShadow, c.borderColor, c.backgroundColor].join('|'); }", T(tid))
        loc.focus()
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        assert page.evaluate("(s) => document.activeElement === document.querySelector(s)", T(tid)), "setup: focus moved by keyboard"
        after = page.evaluate("(s) => { const e = document.querySelector(s); const c = getComputedStyle(e); "
                              "return {o: c.outlineStyle, w: parseFloat(c.outlineWidth), bs: c.boxShadow, sig: [c.outlineStyle, c.outlineWidth, c.boxShadow, c.borderColor, c.backgroundColor].join('|')}; }", T(tid))
        visible_outline = after["o"] not in ("none", "hidden") and after["w"] > 0
        assert visible_outline or after["bs"] != "none" or after["sig"] != before, \
            f"[L2.17] keyboard focus on {tid} must be apparent (outline/shadow/border change): {after}"


def test_L2_17_grid_cells_are_keyboard_operable_or_buttons(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    info = page.evaluate("""() => { const e = document.querySelector("[data-testid='slot-t_2-19:00']");
        return {tag: e.tagName, tab: e.tabIndex, role: e.getAttribute('role'), btn: !!e.closest('button,a,[role=button]')}; }""")
    assert info["tag"] in ("BUTTON", "A") or info["tab"] >= 0 or info["btn"], f"[L2.17] available cells must be focusable controls: {info}"


@pytest.mark.parametrize("route", ["/", "/login", "/signup", "/lookup"])
def test_L2_17_text_contrast_on_screens(seeded, page, route):
    page.goto(route)
    page.wait_for_load_state("load")
    bad = [b for b in page.evaluate(CONTRAST_JS) if not b["disabled"]]
    assert not bad, f"[L2.17] text/control contrast below WCAG AA on {route}: {bad[:6]}"


def test_L2_17_contrast_grid_form_and_feedback(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    open_form(page, "t_1+t_2-19:00")
    bad = [b for b in page.evaluate(CONTRAST_JS) if not b["disabled"] and not (b["id"] or "").startswith("slot-")]
    assert not bad, f"[L2.17] contrast on grid/form: {bad[:6]}"
    cell_bad = [b for b in page.evaluate(CONTRAST_JS) if (b["id"] or "").startswith("slot-") and not b["disabled"]]
    page.fill(T("booking-party-size"), "9")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    bad = [b for b in page.evaluate(CONTRAST_JS) if not b["disabled"] and not (b["id"] or "").startswith("slot-")]
    assert not bad, f"[L2.17] contrast with the error state shown: {bad[:6]}"
    page.fill(T("booking-party-size"), "6")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    bad = [b for b in page.evaluate(CONTRAST_JS) if not b["disabled"] and not (b["id"] or "").startswith("slot-")]
    assert not bad, f"[L2.17] contrast with the confirmation shown: {bad[:6]}"


SIG_JS = """(s) => { const e = document.querySelector(s); if (!e) return null; const c = getComputedStyle(e);
  return {color: c.color, bg: c.backgroundColor, border: c.borderTopColor + '/' + c.borderTopWidth, op: c.opacity, cur: c.cursor,
          deco: c.textDecorationLine, shadow: c.boxShadow, cls: e.className, aria: [e.getAttribute('aria-pressed'), e.getAttribute('aria-selected'), e.getAttribute('aria-disabled'), e.disabled].join(','), weight: c.fontWeight}; }"""


def test_L2_17_available_and_unavailable_cells_look_different(seeded, page):
    seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{seeded.date}T19:00", "party_size": 4}, key=new_key())
    log_in(page)
    do_search(page, seeded.date, 4)
    free = page.evaluate(SIG_JS, T("slot-t_3-19:00"))
    busy = page.evaluate(SIG_JS, T("slot-t_2-19:00"))
    visual = ("color", "bg", "border", "op", "deco", "shadow", "weight")
    assert any(free[k] != busy[k] for k in visual), f"[L2.17] available and unavailable cells must be visually distinct: {free} vs {busy}"
    t_free = page.text_content(T("slot-t_3-19:00")).strip()
    assert t_free, "[L2.17] cells carry a visible label"


def test_L2_17_selected_cell_is_distinct_and_booking_states_are_distinct(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    other = page.evaluate(SIG_JS, T("slot-t_3-19:00"))
    page.click(T("slot-t_3-19:00"))
    page.wait_for_selector(T("booking-form"))
    selected = page.evaluate(SIG_JS, T("slot-t_3-19:00"))
    assert selected != other and any(selected[k] != other[k] for k in ("color", "bg", "border", "shadow", "weight", "deco", "aria", "cls")), \
        f"[L2.17] the selected cell must be visibly distinct (style/class/aria change): {other} -> {selected}"
    page.fill(T("booking-party-size"), "9")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    err = page.evaluate(SIG_JS, T("booking-error"))
    page.fill(T("booking-party-size"), "6")
    lose_bookings(page, commit=True, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    unc = page.evaluate(SIG_JS, T("booking-uncertain"))
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    ok = page.evaluate(SIG_JS, T("confirmation"))
    for a, b, na, nb in ((err, unc, "refused", "uncertain"), (err, ok, "refused", "successful"), (unc, ok, "uncertain", "successful")):
        assert any(a[k] != b[k] for k in ("color", "bg", "border", "shadow")), f"[L2.17] {na} and {nb} states must be visually distinct: {a} vs {b}"


def test_L2_17_human_readable_labels_not_technical_ids(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    for k in ("t_2-19:00", "t_1+t_2-19:00"):
        txt = page.text_content(T("slot-" + k))
        assert "t_" not in txt and "+t" not in txt, f"[L2.17] cell {k} must show human table labels, not ids: {txt!r}"
    combo = page.text_content(T("slot-t_1+t_2-19:00"))
    assert "1" in combo and "2" in combo, f"[L2.17/L2.31] combination cells name their tables: {combo!r}"
    opts = page.eval_on_selector_all(f"{T('restaurant-select')} option", "els => els.map(e => [e.value, e.textContent.trim()])")
    assert ["r_anker", "Zum Anker"] in [list(o) for o in opts] or any(v == "r_anker" and "Zum Anker" in t for v, t in opts), \
        f"[L2.17] restaurant options use ids as values and names as text: {opts}"
    open_form(page, "t_1+t_2-19:00")
    s = page.text_content(T("booking-summary"))
    assert "t_1" not in s and "t_2" not in s, f"[L2.17] summary free of technical ids: {s!r}"
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    for tid in ("confirmation-details", "confirmation-tables"):
        assert "t_1" not in page.text_content(T(tid)) and "t_2" not in page.text_content(T(tid)), f"[L2.17] {tid} free of ids"
    assert "Zum Anker" in page.text_content(T("confirmation-details"))


def test_L2_17_loading_state_while_searching(seeded, page):
    do_search(page, seeded.date, 2)
    held = hold_availability(page, lambda q: q.get("party_size") == "3")
    before = page.evaluate("document.body.innerText")
    page.fill(T("party-size-input"), "3")
    page.click(T("search-button"))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(50)
    page.wait_for_timeout(300)
    state = page.evaluate("""(before) => { const t = document.body.innerText; const b = document.querySelector("[data-testid='search-button']");
        return {text: /load|search|wait|updat|fetch|…|\\.\\.\\./i.test(t.replace(before, '')), busy: !!document.querySelector('[aria-busy=true],[data-loading],[data-state=loading],progress,[role=progressbar],.loading,.spinner'),
                disabled: b.disabled || b.getAttribute('aria-disabled') === 'true' || b.getAttribute('aria-busy') === 'true', changed: t !== before}; }""", before)
    assert state["text"] or state["busy"] or state["disabled"] or state["changed"], f"[L2.17] a visible loading state while the search is pending: {state}"
    held[0].continue_()
    page.wait_for_function("() => !document.querySelector('[aria-busy=true],[data-loading],.loading,.spinner')")
    assert cells(page)


def test_L2_17_search_failure_shows_an_error_state(seeded, page):
    do_search(page, seeded.date, 2)
    page.route("**/availability*", lambda route: route.abort("connectionreset"))
    page.fill(T("party-size-input"), "3")
    page.click(T("search-button"))
    page.wait_for_timeout(800)
    text = page.evaluate("document.body.innerText").lower()
    stale = cells(page)
    ok_msg = any(w in text for w in ("error", "couldn", "could not", "failed", "unable", "try again", "problem", "went wrong", "unavailable", "offline", "network"))
    assert ok_msg, "[L2.17] a failed search must say so (error state), not silently keep or blank the grid"
    page.unroute("**/availability*")
    page.click(T("search-button"))
    page.wait_for_function("() => document.querySelector(\"[data-testid='slot-t_3-19:00']\") !== null")


def test_L2_17_empty_state_has_text_and_signed_out_prompt(seeded, page):
    page.goto("/")
    page.wait_for_selector(T("search-button"))
    assert page.query_selector(T("availability-grid")) is None or True
    do_search(page, seeded.date, 2)
    page.click(T("slot-t_2-19:00"))
    page.wait_for_selector(f"{T('auth-error')}, {T('login-submit')}")
    if page.query_selector(T("auth-error")):
        assert page.text_content(T("auth-error")).strip(), "[L2.17] signed-out prompt is a readable message"
    no_hscroll(page, "signed-out prompt")


def test_L2_17_headings_and_page_titles(seeded, page):
    titles = set()
    for route in ("/", "/login", "/signup", "/lookup"):
        page.goto(route)
        page.wait_for_load_state("load")
        t = page.title().strip()
        assert t, f"[L2.17] {route} needs a <title>"
        titles.add(t)
        assert page.query_selector("h1, h2, [role=heading]") is not None, f"[L2.17] {route} has a visible heading"
        assert page.evaluate("document.documentElement.lang") , "[L2.17] <html lang> is set"
