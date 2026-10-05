"""Availability explanations (ledger L3.1-L3.9)."""
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login,
                      slots, publish_ok, policy, mgr_world, add_days, weekday_name)

D = "2026-09-24"      # a Thursday; availability accepts any calendar date


def explain(date=D, party=4, rid="r_anker", extra=""):
    r = call("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}&explain=true{extra}")
    assert r.status == 200, f"[L3.3] explain request failed: {r!r}"
    return r.json


def by_start(j):
    return {s["starts_at_local"][-5:]: s for s in j["slots"]}


@pytest.mark.parametrize("v", ["false", "1", "", "True", "TRUE", "yes", "0", "t", "truee", " true", "true "])
def test_L3_1_explain_only_accepts_true(w, v):
    r = call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=4&explain={v.replace(' ', '%20')}")
    check(r, 422, "L3.1", "validation_failed")


def test_L3_1_explain_true_ok_and_no_explain_param_ok(w):
    check(call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=4&explain=true"), 200, "L3.1")
    check(call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=4"), 200, "L3.1")


def test_L3_2_without_explain_no_explanation_fields(w):
    j = call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=4").json
    assert j["slots"], "setup"
    for s in j["slots"]:
        assert set(s) == {"starts_at_local", "starts_at", "available_table_ids", "available_options"}, \
            f"[L3.2] without explain the slot keeps the stage-1/2 shape; got keys {sorted(s)}"
    assert set(j) == {"restaurant_id", "date", "timezone", "slots"}


def test_L3_3_with_explain_every_slot_has_one_extra_field(w):
    j = explain()
    for s in j["slots"]:
        assert set(s) == {"starts_at_local", "starts_at", "available_table_ids", "available_options", "explain"}, \
            f"[L3.3] explain adds exactly one field: {sorted(s)}"
    plain = call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=4").json
    for a, b in zip(plain["slots"], j["slots"]):
        assert {k: v for k, v in b.items() if k != "explain"} == a, "[L3.3] other slot values are the same with and without explain"


def test_L3_3_every_table_once_in_fixture_order_available_or_not(w):
    tables = [{"id": "t_z", "label": "Z", "capacity": 6}, {"id": "t_a", "label": "A", "capacity": 2}, {"id": "t_m", "label": "M", "capacity": 4}]
    reset(fixture(restaurants=[restaurant(tables=tables)]))
    for party in (1, 3, 5, 7):
        for s in explain(party=party)["slots"]:
            assert [e["table_id"] for e in s["explain"]] == ["t_z", "t_a", "t_m"], \
                f"[L3.3] every table exactly once, in fixture (not sorted) order, party {party}: {s['explain']}"
            assert [e["table_id"] for e in s["explain"] if e["available"]] == s["available_table_ids"], "[L3.5]"


def test_L3_4_both_rules_reported_in_order_for_every_table(w):
    w.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{D}T19:00", "party_size": 2}, key=new_key())
    j = explain(party=3)       # t_1 (cap 2) is too small AND busy at 19:00
    s = by_start(j)["19:00"]
    got = {e["table_id"]: e for e in s["explain"]}
    assert [r for r in got["t_1"]["rules"]] == [{"rule": "capacity", "holds": False}, {"rule": "no_overlap", "holds": False}], \
        f"[L3.4] a table excluded by both reports both false: {got['t_1']}"
    assert got["t_2"]["rules"] == [{"rule": "capacity", "holds": True}, {"rule": "no_overlap", "holds": True}] and got["t_2"]["available"] is True
    for sl in j["slots"]:
        for e in sl["explain"]:
            assert [r["rule"] for r in e["rules"]] == ["capacity", "no_overlap"], f"[L3.4] rule order: {e}"
            assert all(set(r) == {"rule", "holds"} and isinstance(r["holds"], bool) for r in e["rules"])
            assert set(e) == {"table_id", "policy_version", "available", "rules"}, f"[L3.4] entry keys: {sorted(e)}"
    assert got["t_1"]["available"] is False


def test_L3_4_rules_are_independent(w):
    # t_3 (cap 6) busy at 19:00: capacity holds for party 4, no_overlap does not.
    w.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{D}T19:00", "party_size": 6}, key=new_key())
    s = by_start(explain(party=4))["19:00"]
    e = {x["table_id"]: x for x in s["explain"]}
    assert [r["holds"] for r in e["t_3"]["rules"]] == [True, False] and e["t_3"]["available"] is False, f"[L3.4] {e['t_3']}"
    assert [r["holds"] for r in e["t_1"]["rules"]] == [False, True] and e["t_1"]["available"] is False, f"[L3.4] free but too small: {e['t_1']}"
    assert [r["holds"] for r in e["t_2"]["rules"]] == [True, True] and e["t_2"]["available"] is True
    assert s["available_table_ids"] == ["t_2"]


def test_L3_5_available_iff_both_hold_across_all_slots_and_parties(w):
    w.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{D}T20:00", "party_size": 4}, key=new_key())
    w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{D}T18:00", "party_size": 6}, key=new_key())
    for party in range(1, 9):
        for s in explain(party=party)["slots"]:
            for e in s["explain"]:
                assert e["available"] == all(r["holds"] for r in e["rules"]), f"[L3.5] available == (both hold): party {party} {e}"
            assert [e["table_id"] for e in s["explain"] if e["available"]] == s["available_table_ids"], \
                f"[L3.5] available explanations are exactly available_table_ids, party {party}"


def test_L3_5_half_open_in_no_overlap(w):
    w.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{D}T19:00", "party_size": 4}, key=new_key())
    j = by_start(explain(party=4))
    for at, expect in (("18:00", False), ("18:30", False), ("19:00", False), ("20:00", False), ("20:30", True), ("21:00", True)):
        e = {x["table_id"]: x for x in j[at]["explain"]}["t_2"]
        assert e["rules"][1] == {"rule": "no_overlap", "holds": expect}, f"[L3.5/L1.2] no_overlap at {at} should be {expect}: {e}"


def test_L3_5_combination_reservation_breaks_no_overlap_on_both_members():
    m = mgr_world()
    check(m.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_2", "t_3"], "starts_at_local": f"{m.date}T21:00",
                                            "party_size": 9}, key=new_key()), 201, "L3.5")
    s = by_start(explain(m.date, 1))["21:00"]
    e = {x["table_id"]: x for x in s["explain"]}
    assert [x["holds"] for x in e["t_2"]["rules"]] == [True, False] and [x["holds"] for x in e["t_3"]["rules"]] == [True, False], \
        "[L3.5] a pair booking breaks no_overlap on both members"
    assert [x["holds"] for x in e["t_1"]["rules"]] == [True, True] and s["available_table_ids"] == ["t_1"]


def test_L3_5_cancelled_reservation_does_not_break_no_overlap():
    reset(fixture(restaurants=[restaurant(combinable=[["t_1", "t_2"], ["t_2", "t_3"]])]))
    a = login("ada@example.com"); d = safe_date()
    r = book_ok(a, d, "19:00", "t_2", 4)
    a.post(f"/reservations/{r['reference']}/cancel")
    e = {x["table_id"]: x for x in by_start(explain(d, 4))["19:00"]["explain"]}["t_2"]
    assert e["available"] is True and e["rules"][1]["holds"] is True, "[L3.5] cancelled bookings never block"


def test_L3_6_empty_slots_still_have_full_explain_and_closed_day_has_none(w):
    j = explain(party=7)
    assert len(j["slots"]) == 8
    for s in j["slots"]:
        assert s["available_table_ids"] == [] and len(s["explain"]) == 3 and all(e["available"] is False for e in s["explain"]), \
            f"[L3.6] a slot with no available table still appears with a full explain: {s}"
        assert all([r["holds"] for r in e["rules"]][0] is False for e in s["explain"])
    reset(fixture(restaurants=[restaurant(hours=[{"weekday": "thu", "opens": "18:00", "closes": "23:00"}])]))
    j = explain("2026-09-26", 2)       # Saturday: closed
    assert j["slots"] == [], "[L3.6] a closed day still returns slots []"


def test_L3_6_explain_public_unknown_restaurant_and_missing_params(w):
    check(call("GET", f"/availability?restaurant_id=ghost&date={D}&party_size=2&explain=true"), 404, "L3.6", "not_found")
    check(call("GET", f"/availability?restaurant_id=r_anker&party_size=2&explain=true"), 422, "L3.6", "validation_failed")
    check(call("GET", f"/availability?restaurant_id=r_anker&date={D}&explain=true"), 422, "L3.6", "validation_failed")
    check(call("GET", f"/availability?restaurant_id=r_anker&date={D}&party_size=1e9&explain=true"), 422, "L3.6", "validation_failed")


def test_L3_7_policy_version_defaults_to_zero_and_follows_the_selected_policy():
    m = mgr_world()
    d = m.date
    j = explain(d, 2)
    assert all(e["policy_version"] == 0 for s in j["slots"] for e in s["explain"]), "[L3.7] policy 0 before any publication"
    v1 = publish_ok(m.ada, "r_anker", policy(add_days(d, 3), reservation_duration_minutes=60))
    v2 = publish_ok(m.ada, "r_anker", policy(add_days(d, 6), reservation_duration_minutes=45))
    assert (v1["policy_version"], v2["policy_version"]) == (1, 2)
    for date, ver in ((d, 0), (add_days(d, 2), 0), (add_days(d, 3), 1), (add_days(d, 5), 1), (add_days(d, 6), 2), (add_days(d, 30), 2)):
        j = explain(date, 2)
        assert j["slots"] and all(e["policy_version"] == ver for s in j["slots"] for e in s["explain"]), \
            f"[L3.7] {date} must be decided by policy {ver}"


def test_L3_8_explain_uses_policy_capacities_and_duration():
    m = mgr_world()
    d = m.date
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=120, capacities={"t_1": 5, "t_2": 1, "t_3": 6}))
    j = explain(d, 4)
    s0 = by_start(j)["18:00"]
    e = {x["table_id"]: x for x in s0["explain"]}
    assert [r["holds"] for r in e["t_1"]["rules"]][0] is True, "[L3.8] capacity uses the policy's capacities (t_1 is now 5)"
    assert [r["holds"] for r in e["t_2"]["rules"]][0] is False, "[L3.8] ...and t_2 is now 1"
    assert s0["available_table_ids"] == ["t_1", "t_3"]
    # 120-minute duration: the last slot is 21:00 (21:00 + 120 = 23:00), not 21:30
    assert [x[-5:] for x in [s["starts_at_local"] for s in j["slots"]]][-1] == "21:00", "[L3.8] slot + policy duration <= closes"
    m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{d}T21:00", "party_size": 6}, key=new_key())
    j = by_start(explain(d, 4))
    e = {x["table_id"]: x for x in j["19:00"]["explain"]}
    assert e["t_3"]["rules"][1]["holds"] is True, "[L3.8] 19:00+120 ends exactly when the 21:00 booking starts: no overlap"
    e = {x["table_id"]: x for x in j["19:30"]["explain"]}
    assert e["t_3"]["rules"][1]["holds"] is False, "[L3.8] 19:30+120 overlaps the 21:00 booking (policy duration used for the slot interval)"
