"""Search grid, booking form, confirmation, lookup, combinations (ledger L2.10-L2.15, L2.31)."""
import re
import pytest
from uikit import *  # noqa: F401,F403

SLOTS = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
SINGLES = ["t_1", "t_2", "t_3"]


def api_availability(date, party, rid="r_anker"):
    r = call("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}")
    return r.json["slots"]


def expected_cells(date, party, rid="r_anker"):
    out = {}
    for s in api_availability(date, party, rid):
        hm = s["starts_at_local"][-5:]
        for t in call("GET", f"/restaurants/{rid}").json["tables"]:
            out[f"{t['id']}-{hm}"] = t["id"] in s["available_table_ids"]
        for o in s["available_options"]:
            if len(o["table_ids"]) == 2:
                out[f"{'+'.join(o['table_ids'])}-{hm}"] = True
    return out


def test_L2_10_grid_cells_match_availability_for_several_party_sizes(seeded, page):
    seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{seeded.date}T19:00",
                                              "party_size": 4}, key=new_key())
    seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{seeded.date}T20:30",
                                              "party_size": 5}, key=new_key())
    for party in (1, 2, 3, 4, 5, 6, 7, 10, 11):
        do_search(page, seeded.date, party)
        got = cells(page)
        want = expected_cells(seeded.date, party)
        singles = {k: v for k, v in got.items() if "+" not in k}
        assert set(singles) == {f"{t}-{h}" for t in SINGLES for h in SLOTS}, \
            f"[L2.10] one cell per table per slot (3 tables x 8 slots), got {sorted(singles)[:5]}.."
        for k, v in singles.items():
            assert v in ("true", "false"), f"[L2.10] data-available must be true|false, got {v!r} on {k}"
            assert (v == "true") == want[k], f"[L2.10] party {party}: cell {k} data-available={v}, API says {want[k]}"
        for k, v in got.items():
            if "+" in k:
                assert v in ("true", "false")
                if v == "true":
                    assert want.get(k) is True, f"[L2.31] party {party}: combination cell {k} is available but the API offers no such option"
        for k, v in want.items():
            if "+" in k:
                assert got.get(k) == "true", f"[L2.31] party {party}: available combination {k} must have a cell with data-available=true; got {got.get(k)!r}"


def test_L2_10_grid_for_other_restaurant_uses_its_own_tables(seeded, page):
    do_search(page, seeded.date, 2, "r_two")
    got = cells(page)
    assert set(got) == {f"t_x1-{h}" for h in SLOTS}, f"[L2.10] only the searched restaurant's tables: {sorted(got)}"
    assert all(v == "true" for v in got.values())


def test_L2_10_closed_day_shows_no_slots(page):
    reset(fixture(restaurants=[restaurant(hours=[{"weekday": "mon", "opens": "18:00", "closes": "23:00"}])]))
    d = safe_date()
    import datetime as dt
    day = dt.date.fromisoformat(d)
    while day.weekday() == 0:
        day += dt.timedelta(days=1)
    do_search(page, day.isoformat(), 2)
    assert page.query_selector(T("no-slots")) is not None and page.is_visible(T("no-slots")), "[L2.10] no-slots shown on a closed day"
    assert page.query_selector(T("availability-grid")) is None, "[L2.10] no-slots is shown *instead of* the grid"
    assert page.text_content(T("no-slots")).strip(), "[L2.10] no-slots carries text"
    assert not cells(page), "[L2.10] no cells on a closed day"


def test_L2_10_grid_replaced_by_no_slots_and_back(seeded, page):
    do_search(page, seeded.date, 2)
    assert cells(page)
    import datetime as dt
    reset(fixture(restaurants=[restaurant(hours=[{"weekday": "mon", "opens": "18:00", "closes": "23:00"}], combinable=PAIRS)]))
    day = dt.date.fromisoformat(seeded.date)
    while day.weekday() == 0:
        day += dt.timedelta(days=1)
    do_search(page, day.isoformat(), 2, goto=False)
    page.wait_for_selector(T("no-slots"))
    assert page.query_selector(T("availability-grid")) is None
    mon = day
    while mon.weekday() != 0:
        mon += dt.timedelta(days=1)
    do_search(page, mon.isoformat(), 2, goto=False)
    page.wait_for_selector(T("availability-grid"))
    assert page.query_selector(T("no-slots")) is None, "[L2.10] no-slots disappears once the grid is shown"


def test_L2_10_party_too_big_for_anything_still_shows_grid_with_all_false(seeded, page):
    do_search(page, seeded.date, 11)
    assert page.query_selector(T("availability-grid")) is not None and page.query_selector(T("no-slots")) is None
    assert all(v == "false" for k, v in cells(page).items() if "+" not in k)


def test_L2_11_available_cell_opens_form_unavailable_does_nothing(seeded, page):
    seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{seeded.date}T19:00",
                                              "party_size": 4}, key=new_key())
    log_in(page)
    do_search(page, seeded.date, 4)
    page.click(T("slot-t_2-19:00"), force=True)
    page.wait_for_timeout(300)
    assert page.query_selector(T("booking-form")) is None, "[L2.11] an unavailable cell must not open the form"
    page.click(T("slot-t_3-19:00"))
    page.wait_for_selector(T("booking-form"))
    s = page.text_content(T("booking-summary"))
    assert "3" in s and "19:00" in s, f"[L2.12] summary names the table label and local start time: {s!r}"
    page.click(T("slot-t_2-19:00"), force=True)
    page.wait_for_timeout(300)
    assert "3" in page.text_content(T("booking-summary")), "[L2.11] clicking an unavailable cell leaves the form untouched"


def test_L2_11_signed_out_click_shows_auth_error_or_login(seeded, page):
    do_search(page, seeded.date, 4)
    page.click(T("slot-t_2-19:00"))
    page.wait_for_selector(f"{T('auth-error')}, {T('login-submit')}")
    assert page.query_selector(T("confirmation")) is None
    assert call("GET", "/restaurants").status == 200 and seeded.api_ada.get("/reservations").json == {"reservations": []}, \
        "[L2.11] nothing booked while signed out"


def test_L2_12_booking_flow_reaches_confirmation(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    summary = page.text_content(T("booking-summary"))
    assert "2" in summary and "19:00" in summary, f"[L2.12] {summary!r}"
    assert page.input_value(T("booking-party-size")) == "4", "[L2.12] party size is pre-filled from the search"
    assert page.query_selector(T("confirmation")) is None and page.query_selector(T("booking-error")) is None
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    ref = page.text_content(T("confirmation-reference"))
    assert ref == ref.strip() and re.fullmatch(r"[A-Z0-9]{6,12}", ref), f"[L2.14] confirmation-reference is exactly the reference: {ref!r}"
    d = page.text_content(T("confirmation-details"))
    for x in ("Zum Anker", "2", "19:00"):
        assert x in d, f"[L2.14] confirmation-details must contain {x!r}: {d!r}"
    res = my_reservations(seeded.api_ada)
    assert len(res) == 1 and res[0]["reference"] == ref and res[0]["table_ids"] == ["t_2"] and res[0]["party_size"] == 4 \
        and res[0]["starts_at_local"] == f"{seeded.date}T19:00" and res[0]["restaurant_id"] == "r_anker", f"[L2.12/L2.14] {res}"
    assert page.query_selector(T("booking-form")) is not None, "[L2.13] the booking form stays on screen after success"
    assert page.query_selector(T("booking-error")) is None


def test_L2_12_party_size_edit_is_used(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    page.fill(T("booking-party-size"), "3")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert my_reservations(seeded.api_ada)[0]["party_size"] == 3, "[L2.12] the form's party size, not the search's, is booked"


def test_L2_13_double_submit_replays_and_changed_field_is_new(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 4)
    open_form(page, "t_2-19:00")
    log = record_bookings(page)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    first = page.text_content(T("confirmation-reference")).strip()
    for _ in range(2):
        page.click(T("booking-submit"))
        page.wait_for_timeout(500)
        assert page.query_selector(T("booking-error")) is None, "[L2.13] the second submit was refused instead of replayed"
        assert page.text_content(T("confirmation-reference")).strip() == first, "[L2.13] same reference again"
    assert len(log) >= 2 and len({l["key"] for l in log}) == 1 and all(l["body"] == log[0]["body"] for l in log), \
        f"[L2.13/L1.44] every resubmit of the unchanged form sends the same Idempotency-Key and body: {log}"
    assert len(my_reservations(seeded.api_ada)) == 1, "[L2.13] one booking"
    page.fill(T("booking-party-size"), "2")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert log[-1]["key"] != log[0]["key"] and log[-1]["body"]["party_size"] == 2, "[L2.13] changing a field = a new request, new key"
    assert len(my_reservations(seeded.api_ada)) == 1


def test_L2_13_new_slot_after_success_is_a_new_booking(seeded, page):
    log_in(page)
    ref1 = book_ui(page, "t_2-19:00", seeded.date, 4)
    page.click(T("slot-t_3-19:00"))
    page.wait_for_function("document.querySelector(\"[data-testid='booking-summary']\").textContent.includes('3')")
    page.click(T("booking-submit"))
    page.wait_for_function("document.querySelector(\"[data-testid='confirmation-reference']\") && "
                           f"document.querySelector(\"[data-testid='confirmation-reference']\").textContent.trim() !== '{ref1}'")
    assert len(my_reservations(seeded.api_ada)) == 2


def test_L2_12_booked_slot_unavailable_on_next_search_and_other_user_sees_it(seeded, page):
    log_in(page)
    book_ui(page, "t_2-19:00", seeded.date, 4)
    do_search(page, seeded.date, 4)
    assert page.get_attribute(T("slot-t_2-19:00"), "data-available") == "false"
    assert page.get_attribute(T("slot-t_2-18:30"), "data-available") == "false", "[L1.2] overlapping slot too"
    assert page.get_attribute(T("slot-t_2-20:30"), "data-available") == "true", "[L1.2] half-open"


def test_L2_15_lookup_found_cancel_and_frees_slot(seeded, page):
    log_in(page)
    ref = book_ui(page, "t_2-19:00", seeded.date, 4)
    lookup(page, ref)
    page.wait_for_selector(T("reservation-detail"))
    assert page.text_content(T("reservation-status")) == "confirmed", "[L2.15] status text is exactly confirmed"
    assert "2" in page.text_content(T("reservation-tables"))
    assert page.query_selector(T("reservation-error")) is None
    page.click(T("reservation-cancel-button"))
    page.wait_for_selector(T("reservation-cancel-button"), state="detached")
    assert page.text_content(T("reservation-status")) == "cancelled", "[L2.15] updated without a manual reload"
    assert seeded.api_ada.get(f"/reservations/{ref}").json["status"] == "cancelled"
    do_search(page, seeded.date, 4)
    assert page.get_attribute(T("slot-t_2-19:00"), "data-available") == "true", "[L1.71] cancel frees the slot"
    lookup(page, ref)
    page.wait_for_selector(T("reservation-detail"))
    assert page.text_content(T("reservation-status")) == "cancelled" and page.query_selector(T("reservation-cancel-button")) is None, \
        "[L2.15] reservation-cancel-button absent once cancelled"


def test_L2_15_lookup_errors(seeded, page):
    log_in(page)
    lookup(page, "ZZZZZZ")
    page.wait_for_selector(T("reservation-error"))
    assert page.text_content(T("reservation-error")).strip() and page.query_selector(T("reservation-detail")) is None
    other = seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{seeded.date}T19:00",
                                                       "party_size": 4}, key=new_key()).json["reference"]
    lookup(page, other)
    page.wait_for_selector(T("reservation-error"))
    assert page.query_selector(T("reservation-detail")) is None, "[L2.15] another diner's booking must not be shown"
    mine = seeded.api_ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{seeded.date}T19:00",
                                                      "party_size": 4}, key=new_key()).json["reference"]
    page.fill(T("lookup-reference-input"), mine)
    page.click(T("lookup-submit"))
    page.wait_for_selector(T("reservation-detail"))
    assert page.query_selector(T("reservation-error")) is None, "[L2.15] the error goes away when a lookup succeeds"
    page.fill(T("lookup-reference-input"), "NOPE12")
    page.click(T("lookup-submit"))
    page.wait_for_selector(T("reservation-error"))
    assert page.query_selector(T("reservation-detail")) is None, "[L2.15] stale detail is not left behind after a failed lookup"


def test_L2_15_cancel_refused_flow(page):
    reset(fixture(restaurants=[restaurant(combinable=PAIRS)], reservations=[
        {"id": "res_old", "reference": "OLDONE", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
         "starts_at_local": "2020-01-09T19:00", "party_size": 4}]))
    log_in(page)
    lookup(page, "OLDONE")
    page.wait_for_selector(T("reservation-detail"))
    page.click(T("reservation-cancel-button"))
    page.wait_for_selector(T("reservation-error"))
    assert page.text_content(T("reservation-status")) == "confirmed", "[L2.15] a refused cancel leaves the status confirmed"
    assert page.query_selector(T("reservation-cancel-button")) is not None
    assert login("ada@example.com").get("/reservations/OLDONE").json["status"] == "confirmed"


# ---- combinations ---------------------------------------------------------------------------

def test_L2_31_combo_booking_flow(seeded, page):
    log_in(page)
    do_search(page, seeded.date, 6)
    assert page.get_attribute(T("slot-t_1+t_2-19:00"), "data-available") == "true", "[L2.31] combination cell, ids in combinable order"
    page.click(T("slot-t_1+t_2-19:00"))
    page.wait_for_selector(T("booking-form"))
    s = page.text_content(T("booking-summary"))
    assert "1" in s and "2" in s and "19:00" in s, f"[L2.31] booking-summary must name every table: {s!r}"
    assert "t_1" not in s and "t_2" not in s, f"[L2.31] human labels, not technical ids: {s!r}"
    assert page.input_value(T("booking-party-size")) == "6"
    log = record_bookings(page)
    page.click(T("booking-submit"))
    page.wait_for_selector(T("confirmation"))
    assert tables_of(log[0]["body"]) == ["t_1", "t_2"], f"[L2.31] request carries both tables: {log[0]['body']}"
    assert "table_id" not in log[0]["body"] or "table_ids" not in log[0]["body"]
    ref = page.text_content(T("confirmation-reference")).strip()
    t = page.text_content(T("confirmation-tables"))
    assert "1" in t and "2" in t, f"[L2.31] confirmation-tables names every table: {t!r}"
    d = page.text_content(T("confirmation-details"))
    assert "Zum Anker" in d and "19:00" in d
    res = my_reservations(seeded.api_ada)[0]
    assert res["reference"] == ref and sorted(res["table_ids"]) == ["t_1", "t_2"] and "table_id" not in res
    lookup(page, ref)
    page.wait_for_selector(T("reservation-detail"))
    rt = page.text_content(T("reservation-tables"))
    assert "1" in rt and "2" in rt, f"[L2.31] reservation-tables names every table: {rt!r}"
    do_search(page, seeded.date, 6)
    for k in ("t_1+t_2-19:00", "t_2+t_3-19:00", "t_1-19:00", "t_2-19:00"):
        assert page.get_attribute(T("slot-" + k), "data-available") == "false", f"[L2.31] {k} must be unavailable after the combo booking"
    assert page.get_attribute(T("slot-t_3-19:00"), "data-available") == "true"


def test_L2_31_single_booking_unchanged_by_combinations(seeded, page):
    log_in(page)
    ref = book_ui(page, "t_3-19:00", seeded.date, 5)
    assert "3" in page.text_content(T("confirmation-tables"))
    res = my_reservations(seeded.api_ada)[0]
    assert res["table_ids"] == ["t_3"] and res["table_id"] == "t_3" and res["reference"] == ref
    lookup(page, ref)
    page.wait_for_selector(T("reservation-detail"))
    assert "3" in page.text_content(T("reservation-tables"))


def test_L2_31_cancel_combo_frees_both_tables(seeded, page):
    log_in(page)
    ref = book_ui(page, "t_2+t_3-19:00", seeded.date, 8)
    do_search(page, seeded.date, 1)
    assert page.get_attribute(T("slot-t_2-19:00"), "data-available") == "false" and page.get_attribute(T("slot-t_3-19:00"), "data-available") == "false"
    lookup(page, ref)
    page.wait_for_selector(T("reservation-cancel-button"))
    page.click(T("reservation-cancel-button"))
    page.wait_for_selector(T("reservation-cancel-button"), state="detached")
    do_search(page, seeded.date, 1)
    for t in SINGLES:
        assert page.get_attribute(T(f"slot-{t}-19:00"), "data-available") == "true", f"[L2.31] {t} freed"
    assert page.get_attribute(T("slot-t_2+t_3-19:00"), "data-available") == "true"


def test_L2_31_combination_cell_not_available_when_member_busy_and_never_for_undeclared_pair(seeded, page):
    seeded.api_bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{seeded.date}T19:00",
                                              "party_size": 2}, key=new_key())
    do_search(page, seeded.date, 6)
    got = cells(page)
    assert got.get("t_1+t_2-19:00") in (None, "false"), f"[L2.31] pair with a busy member is not available: {got.get('t_1+t_2-19:00')!r}"
    assert got.get("t_2+t_3-19:00") == "true"
    assert not any(k.startswith("t_1+t_3-") or k.startswith("t_3+t_1-") for k in got if got[k] == "true"), "[L2.31] undeclared pair"
    assert not any(k.startswith("t_2+t_1-") or k.startswith("t_3+t_2-") for k in got), "[L2.31] ids in combinable order only"
    do_search(page, seeded.date, 11)
    assert all(v != "true" for k, v in cells(page).items()), "[L2.31] nothing fits 11"
