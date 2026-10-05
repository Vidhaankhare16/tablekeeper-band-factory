"""Existing screens reflect an applied seating plan (ledger L4.70-L4.73)."""
import datetime as dt
import pytest
from uikit import *  # noqa: F401,F403
from conftest import add_days, publish_ok, policy, history
from replan_kit import inst, replan, plan_ok, apply_ok


def world():
    reset(fixture(restaurants=[restaurant(combinable=PAIRS, managers=["u_ada"])]))
    return login("ada@example.com"), login("bob@example.com"), safe_date()


def book_api(c, d, at, tids, party):
    r = c.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": tids, "starts_at_local": f"{d}T{at}", "party_size": party}, key=new_key())
    assert r.status == 201, r
    return r.json


def close(ada, d, table, f, t):
    p = plan_ok(ada, "r_anker", table, inst(d, f), inst(d, t))
    return p, apply_ok(ada, "r_anker", p["plan_id"])


def test_L4_70_lookup_shows_the_new_tables_after_an_applied_plan(page):
    ada, bob, d = world()
    mine = book_api(bob, d, "19:00", ["t_2"], 3)
    log_in(page, "bob@example.com")
    lookup(page, mine["reference"])
    page.wait_for_selector(T("reservation-detail"))
    assert "2" in page.text_content(T("reservation-tables")) and page.text_content(T("reservation-status")) == "confirmed"
    plan, out = close(ada, d, "t_2", "18:00", "23:00")
    new = out["reservations"][0]["table_ids"]
    assert new != ["t_2"]
    labels = {"t_1": "1", "t_3": "3"}
    page.click(T("lookup-submit"))                                             # look the reference up again on the same screen
    page.wait_for_function("document.querySelector(\"[data-testid='reservation-tables']\") !== null")
    page.wait_for_timeout(300)
    txt = page.text_content(T("reservation-tables"))
    want = [labels[t] for t in new]
    assert all(x in txt for x in want) and "2" not in txt.replace("20", ""), f"[L4.70] lookup shows the new tables {new}, not the old one: {txt!r}"
    assert page.text_content(T("reservation-status")) == "confirmed", "[L4.70] the booking is still confirmed"
    details = page.text_content(T("reservation-detail"))
    assert "19:00" in details, "[L4.70] the booking time is unchanged"
    lookup(page, mine["reference"])
    page.wait_for_selector(T("reservation-detail"))
    txt2 = page.text_content(T("reservation-tables"))
    assert all(x in txt2 for x in want), "[L4.70] a fresh lookup shows the same"


def test_L4_71_grid_cells_for_the_closed_table_and_its_pairs_are_unavailable(page):
    ada, bob, d = world()
    close(ada, d, "t_2", "19:30", "21:00")                                      # slots whose 90-minute interval overlaps [19:30,21:00): 18:30 .. 20:30
    do_search(page, d, 1)
    got = cells(page)
    inside = ("18:30", "19:00", "19:30", "20:00", "20:30")
    outside = ("18:00", "21:00", "21:30")
    for at in inside:
        for k in (f"t_2-{at}", f"t_1+t_2-{at}", f"t_2+t_3-{at}"):
            assert got[k] == "false", f"[L4.71] {k} must be unavailable (closure [19:30,21:00) vs slot interval): {got.get(k)!r}"
        assert got[f"t_1-{at}"] == "true" and got[f"t_3-{at}"] == "true", f"[L4.71] other tables stay available at {at}"
    for at in outside:
        for k in (f"t_2-{at}", f"t_1+t_2-{at}", f"t_2+t_3-{at}"):
            assert got[k] == "true", f"[L4.71] {k} is outside the closure: {got.get(k)!r}"
    page.click(T("slot-t_2-19:00"), force=True)
    page.wait_for_timeout(300)
    assert page.query_selector(T("booking-form")) is None, "[L4.71] clicking a closed cell opens nothing"
    # the grid agrees with the API for several party sizes
    for party in (1, 4, 7):
        do_search(page, d, party)
        g = cells(page)
        for s in call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size={party}").json["slots"]:
            hm = s["starts_at_local"][-5:]
            for t in ("t_1", "t_2", "t_3"):
                assert g[f"{t}-{hm}"] == ("true" if t in s["available_table_ids"] else "false")


def test_L4_72_an_open_booking_form_meets_the_closure_with_409_and_refreshes(page):
    ada, bob, d = world()
    log_in(page, "bob@example.com")
    do_search(page, d, 2)
    open_form(page, "t_2-19:00")
    close(ada, d, "t_2", "18:00", "23:00")
    page.click(T("booking-submit"))
    page.wait_for_selector(T("booking-error"))
    assert page.query_selector(T("confirmation")) is None and page.query_selector(T("booking-uncertain")) is None
    wait_cell(page, "t_2-19:00", False)
    wait_cell(page, "t_1+t_2-19:00", False)
    assert page.query_selector(T("booking-form")) is not None and page.input_value(T("booking-party-size")) == "2", "[L4.72] the form is preserved"
    assert bob.get("/reservations").json == {"reservations": []}


def test_L4_73_a_booking_made_in_the_ui_can_be_repaired_and_the_confirmation_reference_still_resolves(page):
    ada, bob, d = world()
    log_in(page, "bob@example.com")
    ref = book_ui(page, "t_2-19:00", d, 3)
    plan, out = close(ada, d, "t_2", "18:00", "23:00")
    assert [x["reference"] for x in out["reservations"]] == [ref]
    lookup(page, ref)
    page.wait_for_selector(T("reservation-detail"))
    assert page.text_content(T("reservation-status")) == "confirmed"
    mine = bob.get(f"/reservations/{ref}").json
    assert mine["revision"] == 2 and mine["accepted_terms"]["policy_version"] == 0
    h = history(bob, ref)
    assert [e["event"] for e in h] == ["created", "reassigned"] and h[1]["plan_id"] == plan["plan_id"]
    txt = page.text_content(T("reservation-tables"))
    assert ("1" in txt or "3" in txt) and not txt.strip().startswith("2"), f"[L4.73] {txt!r}"
