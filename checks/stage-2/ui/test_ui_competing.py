"""Out-of-order responses, 409 refresh, lost responses and retries (ledger L2.3-L2.8), singles and combinations."""
import json
import re
import pytest
from uikit import *  # noqa: F401,F403


def steal(api_client, table_ids, date, at="19:00", party=2, rid="r_anker"):
    key = "table_ids" if len(table_ids) > 1 else "table_id"
    val = table_ids if len(table_ids) > 1 else table_ids[0]
    r = api_client.post("/reservations", json={"restaurant_id": rid, key: val, "starts_at_local": f"{date}T{at}", "party_size": party},
                        key=new_key())
    assert r.status == 201, f"setup: could not take {table_ids} over the API: {r!r}"
    return r.json


# ---- out-of-order searches (L2.3) ---------------------------------------------------------

def test_L2_3_late_response_for_search_A_does_not_replace_B(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)            # an initial grid is on screen
    held = hold_availability(page, lambda q: q.get("party_size") == "2")
    page.fill(T("party-size-input"), "2")
    page.click(T("search-button"))             # search A (party 2): response is held back
    page.wait_for_function("window.__a = 1; true")
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "setup: search A request was not issued"
    page.fill(T("party-size-input"), "6")      # search B (party 6)
    page.click(T("search-button"))
    page.wait_for_timeout(600)                 # B responds immediately (not matched by the hold)
    b_cells = cells(page)
    assert b_cells["t_3-19:00"] == "true" and b_cells["t_1-19:00"] == "false" and b_cells["t_2-19:00"] == "false", \
        f"[L2.3] grid must describe search B (party 6): {b_cells.get('t_1-19:00')},{b_cells.get('t_2-19:00')},{b_cells.get('t_3-19:00')}"
    open_form(page, "t_3-19:00")
    assert page.input_value(T("booking-party-size")) == "6"
    held[0].continue_()                        # A finally arrives
    page.wait_for_timeout(800)
    after = cells(page)
    assert after == b_cells, "[L2.3] a late response must not restore A's results (grid changed after the late response)"
    assert page.query_selector(T("booking-form")) is not None, "[L2.3] the booking form must not be dropped by the late response"
    assert "3" in page.text_content(T("booking-summary")) and page.input_value(T("booking-party-size")) == "6", \
        "[L2.3] the booking form still describes B"
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    r = my_reservations(seeded.api_ada)[0]
    assert r["table_ids"] == ["t_3"] and r["party_size"] == 6, f"[L2.3] what is booked is what B showed: {r}"


def test_L2_3_late_response_other_restaurant_labels(seeded, page):
    do_search(page, seeded.date, 2, "r_anker", wait=True)
    held = hold_availability(page, lambda q: q.get("restaurant_id") == "r_two")
    page.select_option(T("restaurant-select"), "r_two")
    page.click(T("search-button"))             # A: Zwei (held)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "setup: search A request was not issued"
    page.select_option(T("restaurant-select"), "r_anker")
    page.fill(T("date-input"), seeded.date2)
    page.click(T("search-button"))             # B: Zum Anker, other date
    page.wait_for_timeout(600)
    before = cells(page)
    assert "t_1-19:00" in before and "t_x1-19:00" not in before, "setup: B's grid is showing"
    held[0].continue_()
    page.wait_for_timeout(800)
    assert cells(page) == before, "[L2.3] table labels/cells must still describe B after A's late response"
    assert page.input_value(T("date-input")) == seeded.date2 and page.input_value(T("restaurant-select")) == "r_anker"


def test_L2_3_late_A_after_B_for_a_closed_day(page):
    import datetime as dt
    reset(fixture(restaurants=[restaurant(hours=[{"weekday": "mon", "opens": "18:00", "closes": "23:00"}], combinable=PAIRS)]))
    day = dt.date.fromisoformat(safe_date())
    while day.weekday() == 0:
        day += dt.timedelta(days=1)
    mon = day
    while mon.weekday() != 0:
        mon += dt.timedelta(days=1)
    do_search(page, mon.isoformat(), 2)
    held = hold_availability(page, lambda q: q.get("date") == mon.isoformat())
    page.fill(T("date-input"), mon.isoformat())
    page.click(T("search-button"))                # A: monday (open) held
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(50)
    page.fill(T("date-input"), day.isoformat())
    page.click(T("search-button"))                # B: closed day
    page.wait_for_selector(T("no-slots"))
    held[0].continue_()
    page.wait_for_timeout(800)
    assert page.query_selector(T("no-slots")) is not None and page.query_selector(T("availability-grid")) is None, \
        "[L2.3] the late grid of A must not replace B's no-slots"


def test_L2_3_late_response_with_combo_options(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 2)
    held = hold_availability(page, lambda q: q.get("party_size") == "2")
    page.fill(T("party-size-input"), "2")
    page.click(T("search-button"))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(50)
    page.fill(T("party-size-input"), "9")      # B: only the t_2+t_3 pair fits 9
    page.click(T("search-button"))
    page.wait_for_selector(f"{T('slot-t_2+t_3-19:00')}[data-available='true']")
    open_form(page, "t_2+t_3-19:00")
    held[0].continue_()
    page.wait_for_timeout(800)
    assert page.get_attribute(T("slot-t_2+t_3-19:00"), "data-available") == "true"
    s = page.text_content(T("booking-summary"))
    assert "2" in s and "3" in s and page.input_value(T("booking-party-size")) == "9", f"[L2.3/L2.7] combination form intact: {s!r}"


# ---- 409 refresh (L2.4) -------------------------------------------------------------------

def test_L2_4_conflict_shows_booking_error_refreshes_and_preserves_form(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    page.fill(T("booking-party-size"), "3")
    steal(seeded.api_bob, ["t_2"], seeded.date, "19:30", 4)        # overlaps [19:00,20:30)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert page.text_content(T("booking-error")).strip(), "[L2.4] booking-error has text"
    assert page.query_selector(T("confirmation")) is None, "[L2.4] no confirmation for that attempt"
    assert page.query_selector(T("booking-uncertain")) is None, "[L2.4] a confirmed rejection is not 'uncertain'"
    wait_cell(page, "t_2-19:00", False)                            # availability refreshed
    wait_cell(page, "t_2-20:00", False)
    assert page.query_selector(T("booking-form")) is not None, "[L2.4] form preserved"
    assert page.input_value(T("booking-party-size")) == "3", "[L2.4] inputs preserved"
    assert "2" in page.text_content(T("booking-summary")) and "19:00" in page.text_content(T("booking-summary")), "[L2.4] selection preserved"
    assert my_reservations(seeded.api_ada) == [], "[L2.4] nothing booked"
    # the diner can change the choice and succeed
    page.click(T("slot-t_3-19:00"))
    page.wait_for_function("document.querySelector(\"[data-testid='booking-summary']\").textContent.includes('3')")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert page.query_selector(T("booking-error")) is None, "[L2.4] booking-error is cleared by a success"
    assert my_reservations(seeded.api_ada)[0]["table_ids"] == ["t_3"]


def test_L2_4_retrying_same_conflicting_choice_stays_refused(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    steal(seeded.api_bob, ["t_2"], seeded.date, "19:00", 4)
    log = record_bookings(page)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    page.click(T("booking-submit"))
    page.wait_for_timeout(500)
    assert page.query_selector(T("booking-error")) is not None and page.query_selector(T("confirmation")) is None
    assert len(my_reservations(seeded.api_ada)) == 0


def test_L2_4_conflict_on_combination_refreshes_and_preserves(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    open_form(page, "t_1+t_2-19:00")
    steal(seeded.api_bob, ["t_2"], seeded.date, "19:00", 4)         # one member taken
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert page.query_selector(T("confirmation")) is None
    wait_cell(page, "t_2-19:00", False)
    for k in ("t_2+t_3-19:00",):
        assert cells(page).get(k) in (None, "false"), f"[L2.4/L2.7] {k} refreshed to unavailable"
    assert cells(page).get("t_1+t_2-19:00") in (None, "false")
    assert page.query_selector(T("booking-form")) is not None and page.input_value(T("booking-party-size")) == "6"
    s = page.text_content(T("booking-summary"))
    assert "1" in s and "2" in s, f"[L2.4/L2.7] the combination selection is preserved: {s!r}"
    assert [r for r in my_reservations(seeded.api_ada)] == [], "[L1.3] the refused combination booked nothing, not even t_1"
    assert seeded.api_bob.get("/reservations").json["reservations"].__len__() == 1


# ---- lost responses (L2.5, L2.6, L2.8) ----------------------------------------------------

def test_L2_5_lost_response_after_commit_then_retry_returns_original(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    log = lose_bookings(page, commit=True, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    assert page.text_content(T("booking-uncertain")).strip(), "[L2.5] booking-uncertain text is nonempty"
    assert page.query_selector(T("booking-error")) is None, "[L2.5] no booking-error for an uncertain outcome"
    assert page.query_selector(T("confirmation")) is None, "[L2.8] no confirmation manufactured"
    assert page.query_selector(T("booking-form")) is not None and page.input_value(T("booking-party-size")) == "4", "[L2.5] form unchanged"
    committed = my_reservations(seeded.api_ada)
    assert len(committed) == 1, "setup: the booking did commit on the server"
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert page.text_content(T("confirmation-reference")).strip() == committed[0]["reference"], "[L2.5] the original reference is shown"
    assert page.query_selector(T("booking-uncertain")) is None and page.query_selector(T("booking-error")) is None, \
        "[L2.5] a successful retry removes uncertainty/error elements"
    assert len(log) == 2 and log[0]["key"] and log[1]["key"] == log[0]["key"] and log[1]["body"] == log[0]["body"], \
        f"[L2.5/L1.44] retry must use the same Idempotency-Key and body: {log}"
    assert len(my_reservations(seeded.api_ada)) == 1, "[L2.5] still exactly one booking"
    d = page.text_content(T("confirmation-details"))
    assert "Zum Anker" in d and "19:00" in d


def test_L2_5_lost_response_before_commit_retry_books(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    log = lose_bookings(page, commit=False, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    assert my_reservations(seeded.api_ada) == [], "setup: request never reached the server"
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert page.query_selector(T("booking-uncertain")) is None
    assert log[1]["key"] == log[0]["key"] and log[1]["body"] == log[0]["body"]
    assert len(my_reservations(seeded.api_ada)) == 1


def test_L2_5_two_lost_responses_in_a_row_then_success(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    log = lose_bookings(page, commit=True, count=2)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    page.click(T("booking-submit"))
    page.wait_for_timeout(600)
    assert page.query_selector(T("booking-uncertain")) is not None and page.query_selector(T("booking-error")) is None \
        and page.query_selector(T("confirmation")) is None, "[L2.5] still uncertain after a second lost response"
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert len({l["key"] for l in log}) == 1 and len(log) == 3 and all(l["body"] == log[0]["body"] for l in log)
    assert len(my_reservations(seeded.api_ada)) == 1


def test_L2_5_changing_a_field_after_uncertainty_is_a_new_request(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    log = lose_lost = lose_bookings(page, commit=True, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    page.fill(T("booking-party-size"), "3")
    page.click(T("booking-submit"))
    page.wait_for_selector(f"{T('booking-error')}, {T('confirmation')}")
    assert log[1]["key"] != log[0]["key"] and log[1]["body"]["party_size"] == 3, "[L2.5] a changed form is a new request with a new key"
    assert len(my_reservations(seeded.api_ada)) == 1, "[L2.5] no second booking"


def test_L2_6_confirmed_rejection_uses_booking_error_not_uncertain(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    page.fill(T("booking-party-size"), "9")                      # exceeds table capacity (server says 422)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert page.query_selector(T("booking-uncertain")) is None and page.query_selector(T("confirmation")) is None
    assert my_reservations(seeded.api_ada) == []
    page.fill(T("booking-party-size"), "4")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert page.query_selector(T("booking-error")) is None


def test_L2_6_uncertain_then_confirmed_rejection_swaps_message(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    lose_bookings(page, commit=False, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    steal(seeded.api_bob, ["t_2"], seeded.date, "19:00", 4)
    page.click(T("booking-submit"))                              # the retry is now definitively refused
    page.wait_for_selector(T("booking-error"))
    assert page.query_selector(T("booking-uncertain")) is None, "[L2.6] a confirmed rejection replaces the uncertainty"
    assert page.query_selector(T("confirmation")) is None


def test_L2_8_no_confirmation_from_cached_data(seeded, page):
    """After a lost response the UI must not 'guess' success, even though availability changed."""
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    lose_bookings(page, commit=True, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    page.wait_for_timeout(1000)
    assert page.query_selector(T("confirmation")) is None and page.query_selector(T("confirmation-reference")) is None, \
        "[L2.8] no confirmation until the server answers"


# ---- combinations through the same flows (L2.7) -----------------------------------------

def test_L2_7_combo_lost_response_retry_same_key_body(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    open_form(page, "t_1+t_2-19:00")
    log = lose_bookings(page, commit=True, count=1)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-uncertain"))
    assert page.query_selector(T("booking-error")) is None and page.query_selector(T("confirmation")) is None
    assert len(my_reservations(seeded.api_ada)) == 1
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    ref = my_reservations(seeded.api_ada)[0]["reference"]
    assert page.text_content(T("confirmation-reference")).strip() == ref
    assert log[1]["key"] == log[0]["key"] and log[1]["body"] == log[0]["body"] and tables_of(log[0]["body"]) == ["t_1", "t_2"]
    t = page.text_content(T("confirmation-tables"))
    assert "1" in t and "2" in t
    assert page.query_selector(T("booking-uncertain")) is None and page.query_selector(T("booking-error")) is None
    assert len(my_reservations(seeded.api_ada)) == 1


def test_L2_7_combo_double_submit_replays(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 8)
    open_form(page, "t_2+t_3-19:00")
    log = record_bookings(page)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    first = page.text_content(T("confirmation-reference")).strip()
    page.click(T("booking-submit"))
    page.wait_for_timeout(500)
    assert page.text_content(T("confirmation-reference")).strip() == first and page.query_selector(T("booking-error")) is None
    assert len({l["key"] for l in log}) == 1 and len(my_reservations(seeded.api_ada)) == 1


def test_L2_7_combo_changed_party_after_success_is_new_request(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 8)
    open_form(page, "t_2+t_3-19:00")
    log = record_bookings(page)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    page.fill(T("booking-party-size"), "7")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))      # the pair is now ours/taken
    assert log[-1]["key"] != log[0]["key"] and len(my_reservations(seeded.api_ada)) == 1


def test_L2_7_combo_confirmed_rejection_party_too_big(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    open_form(page, "t_1+t_2-19:00")
    page.fill(T("booking-party-size"), "7")          # pair capacity is 6
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert page.query_selector(T("booking-uncertain")) is None and my_reservations(seeded.api_ada) == []
