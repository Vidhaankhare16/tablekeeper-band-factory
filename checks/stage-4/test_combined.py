"""Stage 2 API: combined tables (ledger L2.20-L2.30, L2.34)."""
import datetime as dt
import pytest
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, body, new_key, \
    burst, avail_ids, local, login, slots, iso, PW

PAIRS = [["t_1", "t_2"], ["t_2", "t_3"]]


def cbody(d, ids, at="19:00", party=6, rid="r_anker", **extra):
    b = {"restaurant_id": rid, "table_ids": ids, "starts_at_local": local(d, at), "party_size": party}
    b.update(extra)
    return b


def cpost(c, d, ids, at="19:00", party=6, key=None, **extra):
    return c.post("/reservations", json=cbody(d, ids, at, party, **extra), key=new_key() if key is None else key)


def cok(c, d, ids, at="19:00", party=6):
    r = cpost(c, d, ids, at, party)
    assert r.status == 201, f"[L2.25] combination booking should succeed: {r!r}"
    return r.json


@pytest.fixture
def cw():
    class W: pass
    o = W()
    o.fx = fixture(restaurants=[restaurant(combinable=PAIRS)])
    reset(o.fx)
    o.date = safe_date()
    o.ada, o.bob, o.cy = login("ada@example.com"), login("bob@example.com"), login("cy@example.com")
    return o


def opts(d, at, party, rid="r_anker"):
    s, _ = slots(d, party, rid)
    return s[local(d, at)]["available_options"]


def test_L2_20_restaurant_detail_exposes_combinable(cw):
    j = call("GET", "/restaurants/r_anker").json
    assert j.get("combinable") == PAIRS, f"[L2.20] GET /restaurants/{{id}} shows combinable in the fixture's shape: {j.get('combinable')!r}"
    reset(fixture())
    j = call("GET", "/restaurants/r_anker").json
    assert j.get("combinable", []) == [], "[L2.20] restaurant without the field has no combinations"
    assert opts(safe_date(), "19:00", 2) == [{"table_ids": ["t_1"], "capacity": 2}, {"table_ids": ["t_2"], "capacity": 4},
                                              {"table_ids": ["t_3"], "capacity": 6}], "[L2.24] no pairs declared => singles only"


def test_L2_24_available_options_shape_order_and_capacity(cw):
    d = cw.date
    o = opts(d, "19:00", 1)
    assert o == [{"table_ids": ["t_1"], "capacity": 2}, {"table_ids": ["t_2"], "capacity": 4}, {"table_ids": ["t_3"], "capacity": 6},
                 {"table_ids": ["t_1", "t_2"], "capacity": 6}, {"table_ids": ["t_2", "t_3"], "capacity": 10}], \
        f"[L2.24] singles first in fixture order, then pairs in combinable order, capacity>=party: {o}"
    assert opts(d, "19:00", 5) == [{"table_ids": ["t_3"], "capacity": 6}, {"table_ids": ["t_1", "t_2"], "capacity": 6},
                                   {"table_ids": ["t_2", "t_3"], "capacity": 10}], "[L2.24] party 5"
    assert opts(d, "19:00", 6) == [{"table_ids": ["t_3"], "capacity": 6}, {"table_ids": ["t_1", "t_2"], "capacity": 6},
                                   {"table_ids": ["t_2", "t_3"], "capacity": 10}], "[L2.24] capacity == party qualifies (boundary)"
    assert opts(d, "19:00", 7) == [{"table_ids": ["t_2", "t_3"], "capacity": 10}], "[L2.24] only the big pair for 7"
    assert opts(d, "19:00", 10) == [{"table_ids": ["t_2", "t_3"], "capacity": 10}], "[L2.24] sum boundary"
    assert opts(d, "19:00", 11) == [], "[L2.24] nothing fits 11; slot still present"
    s, _ = slots(d, 11)
    assert len(s) == 8 and all(v["available_options"] == [] and v["available_table_ids"] == [] for v in s.values())


def test_L2_24_available_table_ids_stays_singles_only(cw):
    d = cw.date
    s, _ = slots(d, 5)
    assert s[local(d, "19:00")]["available_table_ids"] == ["t_3"], "[L2.24] available_table_ids unchanged: single tables only"
    s, _ = slots(d, 3)
    assert s[local(d, "19:00")]["available_table_ids"] == ["t_2", "t_3"]
    for v in s.values():
        assert [o["table_ids"][0] for o in v["available_options"] if len(o["table_ids"]) == 1] == v["available_table_ids"], \
            "[L2.24] the singles in available_options equal available_table_ids"


def test_L2_24_options_exclude_pairs_with_a_busy_member_and_overlaps(cw):
    d = cw.date
    book_ok(cw.ada, d, "19:00", "t_1", 2)           # busy t_1 [19:00,20:30)
    o = opts(d, "19:00", 3)
    assert {tuple(x["table_ids"]) for x in o} == {("t_2",), ("t_3",), ("t_2", "t_3")}, f"[L2.24] pair with busy member is gone: {o}"
    assert {tuple(x["table_ids"]) for x in opts(d, "20:30", 3)} == {("t_2",), ("t_3",), ("t_1", "t_2"), ("t_2", "t_3")}, \
        "[L2.24] half-open: free again at 20:30"
    assert {tuple(x["table_ids"]) for x in opts(d, "18:00", 3)} == {("t_2",), ("t_3",), ("t_2", "t_3")}, "[L2.24] overlap from the left"
    assert {tuple(x["table_ids"]) for x in opts(d, "21:00", 3)} == {("t_2",), ("t_3",), ("t_1", "t_2"), ("t_2", "t_3")}


def test_L2_29_combination_occupies_both_tables_full_duration(cw):
    d = cw.date
    j = cok(cw.ada, d, ["t_1", "t_2"], "19:00", 6)
    assert sorted(j["table_ids"]) == ["t_1", "t_2"] and "table_id" not in j, f"[L2.25] two tables: table_ids only, no table_id: {j}"
    for t, p in (("t_1", 2), ("t_2", 4)):
        for at in ("18:00", "18:30", "19:00", "19:30", "20:00"):
            check(book(cw.bob, d, at, t, p), 409, "L2.29", "table_unavailable")
        check(book(cw.bob, d, "20:30", t, p), 201, "L2.29")        # half-open: free when the combo ends
    # t_3 was never part of it
    check(book(cw.bob, d, "19:00", "t_3", 6), 201, "L2.29")
    assert iso(j["ends_at"]) - iso(j["starts_at"]) == dt.timedelta(minutes=90)


def test_L2_29_any_member_busy_blocks_combination_and_nothing_is_booked(cw):
    d = cw.date
    book_ok(cw.bob, d, "19:30", "t_2", 4)           # [19:30, 21:00)
    for ids in (["t_1", "t_2"], ["t_2", "t_1"], ["t_2", "t_3"]):
        check(cpost(cw.ada, d, ids, "19:00", 6), 409, "L2.26/L2.29", "table_unavailable")
    check(cpost(cw.ada, d, ["t_1", "t_2"], "18:30", 6), 409, "L2.26", "table_unavailable")
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_3"] and cw.ada.get("/reservations").json == {"reservations": []}, \
        "[L2.26/L1.3] a refused combination books nothing, not even its free member"
    check(cpost(cw.ada, d, ["t_1", "t_2"], "21:00", 6), 201, "L2.29")


def test_L2_25_table_id_still_accepted_and_responses_carry_table_ids(cw):
    d = cw.date
    a = book_ok(cw.ada, d, "19:00", "t_2", 4)
    assert a["table_ids"] == ["t_2"] and a["table_id"] == "t_2", f"[L2.25] set of one carries both table_ids and table_id: {a}"
    b = check(cpost(cw.ada, d, ["t_3"], "21:00", 6), 201, "L2.25")
    assert b["table_ids"] == ["t_3"] and b["table_id"] == "t_3", f"[L2.25] table_ids with one member behaves as table_id: {b}"
    for ref in (a["reference"], b["reference"]):
        g = cw.ada.get(f"/reservations/{ref}").json
        assert g["table_ids"] == [g["table_id"]]
    lst = cw.ada.get("/reservations").json["reservations"]
    assert all("table_ids" in x for x in lst) and all(("table_id" in x) == (len(x["table_ids"]) == 1) for x in lst), \
        "[L2.25] list entries follow the same rule"


def test_L2_25_combo_response_shape_get_list_and_replay(cw):
    d = cw.date
    key = new_key()
    r = cw.ada.post("/reservations", json=cbody(d, ["t_2", "t_3"], "19:00", 8), key=key)
    j = check(r, 201, "L2.25")
    assert sorted(j["table_ids"]) == ["t_2", "t_3"] and "table_id" not in j and j["party_size"] == 8 and j["status"] == "confirmed"
    assert cw.ada.get(f"/reservations/{j['reference']}").json == j
    assert cw.ada.get("/reservations").json["reservations"][0] == j
    assert check(cw.ada.post("/reservations", json=cbody(d, ["t_2", "t_3"], "19:00", 8), key=key), 200, "L2.25") == j
    check(cw.ada.post("/reservations", json=cbody(d, ["t_3", "t_2"], "19:00", 8), key=key), 409, "L2.25", "idempotency_key_reuse")


def test_L2_25_both_table_id_and_table_ids_is_422(cw):
    d = cw.date
    r = cw.ada.post("/reservations", json=cbody(d, ["t_1", "t_2"], table_id="t_1"), key=new_key())
    check(r, 422, "L2.25", "validation_failed")
    check(cw.ada.post("/reservations", json={**cbody(d, ["t_2"], "19:00", 4), "table_id": "t_2"}, key=new_key()), 422, "L2.25", "validation_failed")
    assert cw.ada.get("/reservations").json == {"reservations": []}


def test_L2_26_combination_not_allowed(cw):
    d = cw.date
    check(cpost(cw.ada, d, ["t_1", "t_3"], "19:00", 8), 422, "L2.21/L2.26", "combination_not_allowed")  # non-transitive
    check(cpost(cw.ada, d, ["t_3", "t_1"], "19:00", 8), 422, "L2.21/L2.26", "combination_not_allowed")
    check(cpost(cw.ada, d, ["t_1", "t_2", "t_3"], "19:00", 8), 422, "L2.26", "combination_not_allowed")  # three
    check(cpost(cw.ada, d, ["t_1", "t_2", "t_3"], "19:00", 12), 422, "L2.26", "combination_not_allowed")
    assert cw.ada.get("/reservations").json == {"reservations": []}, "[L2.26] nothing booked"
    # the same pair is acceptable in either order
    check(cpost(cw.ada, d, ["t_2", "t_1"], "19:00", 6), 201, "L2.21")


def test_L2_21_pair_not_listed_even_if_sizes_would_fit():
    reset(fixture(restaurants=[restaurant(combinable=[["t_1", "t_2"]])]))
    a = login("ada@example.com"); d = safe_date()
    check(cpost(a, d, ["t_2", "t_3"], "19:00", 7), 422, "L2.21", "combination_not_allowed")   # sizes 4+6 fit, pair undeclared
    check(cpost(a, d, ["t_1", "t_3"], "19:00", 7), 422, "L2.21", "combination_not_allowed")
    assert opts(d, "19:00", 7) == [], "[L2.21] undeclared pairs are never offered (party 7: t_3 alone is 6)"
    reset(fixture())     # no combinable at all
    a = login("ada@example.com")
    check(cpost(a, d, ["t_1", "t_2"], "19:00", 6), 422, "L2.21", "combination_not_allowed")


def test_L2_26_party_exceeds_summed_capacity(cw):
    d = cw.date
    check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 7), 422, "L2.22/L2.26", "party_exceeds_capacity")    # 2+4=6
    check(cpost(cw.ada, d, ["t_2", "t_3"], "19:00", 11), 422, "L2.22/L2.26", "party_exceeds_capacity")   # 4+6=10
    check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 6), 201, "L2.22")
    check(cpost(cw.bob, d, ["t_2", "t_3"], "21:00", 10), 201, "L2.22")
    check(cpost(cw.bob, d, ["t_3"], "19:00", 7), 422, "L2.22", "party_exceeds_capacity")        # single, tables_ids form


def test_L2_26_duplicate_table_id_in_set(cw):
    d = cw.date
    check(cpost(cw.ada, d, ["t_1", "t_1"], "19:00", 2), 422, "L2.26", "validation_failed")
    check(cpost(cw.ada, d, ["t_2", "t_2"], "19:00", 2), 422, "L2.26", "validation_failed")
    assert cw.ada.get("/reservations").json == {"reservations": []}


def test_L2_26_table_ids_shape_errors(cw):
    d = cw.date
    check(cpost(cw.ada, d, [], "19:00", 2), 422, "L2.26", "validation_failed")     # READING: empty set = invalid value
    check(cw.ada.post("/reservations", json=cbody(d, "t_1", "19:00", 2), key=new_key()), 400, "L2.26/L1.20", "malformed_request")
    check(cw.ada.post("/reservations", json=cbody(d, [1, 2], "19:00", 2), key=new_key()), 400, "L2.26/L1.20", "malformed_request")
    check(cw.ada.post("/reservations", json=cbody(d, {"a": 1}, "19:00", 2), key=new_key()), 400, "L2.26/L1.20", "malformed_request")
    b = cbody(d, ["t_1"], "19:00", 2); del b["table_ids"]
    check(cw.ada.post("/reservations", json=b, key=new_key()), 422, "L2.26/L1.26", "validation_failed")   # neither given


def test_L2_26_unknown_or_foreign_table_in_set_is_404(cw):
    d = cw.date
    check(cpost(cw.ada, d, ["t_1", "t_nope"], "19:00", 2), 404, "L2.26/L1.67", "not_found")
    check(cpost(cw.ada, d, ["t_nope", "t_2"], "19:00", 2), 404, "L2.26/L1.67", "not_found")
    check(cpost(cw.ada, d, ["t_1", "t_x1"], "19:00", 2), 404, "L2.26/L1.67", "not_found")   # t_x1 belongs to r_two
    check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 2, rid="r_ghost"), 404, "L2.26/L1.67", "not_found")


def test_L2_26_other_validation_rules_still_apply_to_combinations(cw):
    d = cw.date
    check(cpost(cw.ada, d, ["t_1", "t_2"], "19:15", 6), 422, "L2.26/L1.62", "not_on_slot_grid")
    check(cpost(cw.ada, d, ["t_1", "t_2"], "22:00", 6), 422, "L2.26/L1.63", "outside_opening_hours")
    check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 0), 422, "L2.26/L1.65", "validation_failed")
    check(cw.ada.post("/reservations", json=cbody(d, ["t_1", "t_2"]), key=""), 400, "L2.26/L1.21", "missing_idempotency_key")


def test_L2_26_failed_key_reusable_for_combos(cw):
    d, key = cw.date, new_key()
    check(cpost(cw.ada, d, ["t_1", "t_3"], "19:00", 6, key=key), 422, "L2.26/L1.44", "combination_not_allowed")
    j = check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 6, key=key), 201, "L2.26/L1.44")
    assert check(cpost(cw.ada, d, ["t_1", "t_2"], "19:00", 6, key=key), 200, "L2.26") == j


def test_L2_23_seeded_reservations_status_and_table_ids():
    rs = [{"id": "res_a", "reference": "SEEDAA", "user_id": "u_ada", "restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
           "starts_at_local": "2020-01-09T19:00", "party_size": 6},
          {"id": "res_b", "reference": "SEEDBB", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_3",
           "starts_at_local": "2020-01-09T19:00", "party_size": 5, "status": "cancelled"},
          {"id": "res_c", "reference": "SEEDCC", "user_id": "u_bob", "restaurant_id": "r_anker", "table_ids": ["t_3"],
           "starts_at_local": "2020-01-10T19:00", "party_size": 5, "status": "confirmed"},
          {"id": "res_d", "reference": "SEEDDD", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_2",
           "starts_at_local": "2020-01-10T21:00", "party_size": 3}]
    reset(fixture(restaurants=[restaurant(combinable=PAIRS)], reservations=rs))
    a, b = login("ada@example.com"), login("bob@example.com")
    r1 = a.get("/reservations/SEEDAA").json
    assert r1["status"] == "confirmed" and sorted(r1["table_ids"]) == ["t_1", "t_2"] and "table_id" not in r1, f"[L2.23] {r1}"
    r2 = a.get("/reservations/SEEDBB").json
    assert r2["status"] == "cancelled" and r2["table_ids"] == ["t_3"] and r2["table_id"] == "t_3", f"[L2.23] {r2}"
    r3 = b.get("/reservations/SEEDCC").json
    assert r3["status"] == "confirmed" and r3["table_ids"] == ["t_3"] and r3["table_id"] == "t_3", f"[L2.23] {r3}"
    r4 = b.get("/reservations/SEEDDD").json
    assert r4["status"] == "confirmed" and r4["table_ids"] == ["t_2"], f"[L2.23] default status is confirmed: {r4}"
    # occupancy: the seeded combination occupies t_1 and t_2; the cancelled one occupies nothing
    s, _ = slots("2020-01-09", 1)
    assert s["2020-01-09T19:00"]["available_table_ids"] == ["t_3"], "[L2.23] cancelled seed frees t_3; combo seed holds t_1,t_2"
    assert {tuple(o["table_ids"]) for o in s["2020-01-09T19:00"]["available_options"]} == {("t_3",)}
    s, _ = slots("2020-01-10", 1)
    assert s["2020-01-10T19:00"]["available_table_ids"] == ["t_1", "t_2"]
    assert {tuple(o["table_ids"]) for o in s["2020-01-10T19:00"]["available_options"]} == {("t_1",), ("t_2",), ("t_1", "t_2")}
    assert [x["reference"] for x in a.get("/reservations").json["reservations"]] == ["SEEDAA", "SEEDBB"] or \
        {x["reference"] for x in a.get("/reservations").json["reservations"]} == {"SEEDAA", "SEEDBB"}, "[L2.23] cancelled seeds are listed"


# ---- PATCH ----------------------------------------------------------------------------------

def test_L2_27_patch_table_ids_single_to_combo_and_back(cw):
    d = cw.date
    j = book_ok(cw.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    p = check(cw.ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_1", "t_2"], "party_size": 6}), 200, "L2.27")
    assert sorted(p["table_ids"]) == ["t_1", "t_2"] and "table_id" not in p and p["party_size"] == 6
    assert p["reference"] == ref and p["reservation_id"] == j["reservation_id"] and p["created_at"] == j["created_at"], "[L1.81]"
    assert avail_ids(d, "19:00", 1) == ["t_3"], "[L2.27] both tables now occupied"
    p = check(cw.ada.patch(f"/reservations/{ref}", json={"table_id": "t_3", "party_size": 5}), 200, "L2.27")
    assert p["table_ids"] == ["t_3"] and p["table_id"] == "t_3"
    assert avail_ids(d, "19:00", 1) == ["t_1", "t_2"], "[L2.27] combination members released"
    p = check(cw.ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_2", "t_3"], "party_size": 9}), 200, "L2.27")
    assert sorted(p["table_ids"]) == ["t_2", "t_3"]
    p = check(cw.ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_1"], "party_size": 2}), 200, "L2.27")
    assert p["table_ids"] == ["t_1"] and p["table_id"] == "t_1"
    assert cw.ada.get(f"/reservations/{ref}").json == p


def test_L2_27_patch_error_codes(cw):
    d = cw.date
    j = cok(cw.ada, d, ["t_1", "t_2"], "19:00", 6)
    ref = j["reference"]
    other = book_ok(cw.bob, d, "19:00", "t_3", 6)
    cases = [({"table_ids": ["t_1", "t_3"]}, 422, "combination_not_allowed"),
             ({"table_ids": ["t_1", "t_2", "t_3"]}, 422, "combination_not_allowed"),
             ({"table_ids": ["t_2", "t_3"], "party_size": 6}, 409, "table_unavailable"),
             ({"table_ids": ["t_2", "t_2"]}, 422, "validation_failed"),
             ({"table_ids": ["t_1", "t_2"], "table_id": "t_1"}, 422, "validation_failed"),
             ({"party_size": 7}, 422, "party_exceeds_capacity"),
             ({"table_ids": ["t_1"]}, 422, "party_exceeds_capacity"),        # party 6 > 2
             ({"table_ids": ["t_1", "t_nope"]}, 404, "not_found"),
             ({"table_ids": "t_1"}, 400, "malformed_request"),
             ({"table_ids": [3]}, 400, "malformed_request"),
             ({"table_ids": []}, 422, "validation_failed")]
    for patch, st, code in cases:
        check(cw.ada.patch(f"/reservations/{ref}", json=patch), st, f"L2.27 {patch}", code)
    assert cw.ada.get(f"/reservations/{ref}").json == j, "[L1.80/L2.27] failed amendments leave the combination intact"
    assert avail_ids(d, "19:00", 1) == [], "[L2.27] occupancy unchanged (t_1,t_2 mine, t_3 bob's)"
    assert cw.bob.get(f"/reservations/{other['reference']}").json == other


def test_L2_27_patch_combo_time_move_checks_every_member(cw):
    d = cw.date
    j = cok(cw.ada, d, ["t_1", "t_2"], "19:00", 6)
    book_ok(cw.bob, d, "21:00", "t_1", 2)                         # t_1 busy [21:00,22:30)
    check(cw.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": local(d, "21:00")}), 409, "L2.27", "table_unavailable")
    check(cw.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": local(d, "19:30")}), 200, "L2.27")   # own overlap ok
    check(cw.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": local(d, "18:00")}), 200, "L2.27")


def test_L2_27_cancel_frees_every_table(cw):
    d = cw.date
    j = cok(cw.ada, d, ["t_2", "t_3"], "19:00", 10)
    assert avail_ids(d, "19:00", 1) == ["t_1"]
    c = check(cw.ada.post(f"/reservations/{j['reference']}/cancel"), 200, "L2.27")
    assert c["status"] == "cancelled" and sorted(c["table_ids"]) == ["t_2", "t_3"] and "table_id" not in c
    assert avail_ids(d, "19:00", 1) == ["t_1", "t_2", "t_3"], "[L2.27] cancelling frees every table in the set"
    assert {tuple(o["table_ids"]) for o in opts(d, "19:00", 7)} == {("t_2", "t_3")}
    check(book(cw.bob, d, "19:00", "t_2", 4), 201, "L2.27")
    check(book(cw.bob, d, "19:00", "t_3", 6), 201, "L2.27")


def test_L2_27_cancelled_combo_cannot_be_amended(cw):
    j = cok(cw.ada, cw.date, ["t_1", "t_2"], "19:00", 6)
    cw.ada.post(f"/reservations/{j['reference']}/cancel")
    check(cw.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 5}), 409, "L2.27", "reservation_cancelled")
    assert avail_ids(cw.date, "19:00", 1) == ["t_1", "t_2", "t_3"]


def test_L2_27_cutoff_applies_to_combinations():
    reset(fixture(restaurants=[restaurant(combinable=PAIRS)]))
    a = login("ada@example.com")
    j = check(cpost(a, "2020-01-08", ["t_1", "t_2"], "19:00", 6), 201, "L1.18")
    check(a.post(f"/reservations/{j['reference']}/cancel"), 409, "L2.27", "cutoff_passed")
    check(a.patch(f"/reservations/{j['reference']}", json={"table_ids": ["t_2", "t_3"]}), 409, "L2.27", "cutoff_passed")


# ---- moves ----------------------------------------------------------------------------------

def mv(c, moves, key=None):
    return c.post("/reservation-moves", json={"moves": moves}, key=new_key() if key is None else key)


def test_L2_28_moves_accept_table_ids(cw):
    d = cw.date
    a = book_ok(cw.ada, d, "19:00", "t_1", 2)
    b = book_ok(cw.ada, d, "19:00", "t_3", 6)
    j = check(mv(cw.ada, [{"reference": a["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6},
                          {"reference": b["reference"], "table_ids": ["t_3"]}]), 201, "L2.28")["reservations"]
    assert sorted(j[0]["table_ids"]) == ["t_1", "t_2"] and "table_id" not in j[0] and j[0]["party_size"] == 6
    assert j[1]["table_ids"] == ["t_3"] and j[1]["table_id"] == "t_3" and j[1]["party_size"] == 6
    assert avail_ids(d, "19:00", 1) == []
    assert [x["reference"] for x in j] == [a["reference"], b["reference"]]


def test_L2_28_resulting_bookings_must_not_share_a_table(cw):
    d = cw.date
    a = book_ok(cw.ada, d, "19:00", "t_1", 2)
    b = book_ok(cw.ada, d, "19:00", "t_3", 6)
    snap = cw.ada.get("/reservations").json
    # combo [t_1,t_2] and combo [t_2,t_3] share t_2 at the same time
    check(mv(cw.ada, [{"reference": a["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6},
                      {"reference": b["reference"], "table_ids": ["t_2", "t_3"], "party_size": 8}]), 409, "L2.28", "table_unavailable")
    # combo overlaps a single in the same batch
    check(mv(cw.ada, [{"reference": a["reference"], "table_ids": ["t_2", "t_3"], "party_size": 6}]), 409, "L2.28", "table_unavailable")
    assert cw.ada.get("/reservations").json == snap, "[L2.28] nothing changed"
    # same combo for two bookings at *different* non-overlapping times is fine
    c = book_ok(cw.ada, d, "21:00", "t_1", 2)
    j = check(mv(cw.ada, [{"reference": a["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6},
                          {"reference": c["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6}]), 201, "L2.28")
    assert len(j["reservations"]) == 2


def test_L2_28_moves_overlap_with_unlisted_and_swap_of_combo_and_single(cw):
    d = cw.date
    combo = cok(cw.ada, d, ["t_1", "t_2"], "19:00", 6)
    single = book_ok(cw.ada, d, "19:00", "t_3", 6)
    other = book_ok(cw.bob, d, "21:00", "t_3", 6)
    # listed move onto a table held by an unlisted booking
    check(mv(cw.ada, [{"reference": combo["reference"], "table_ids": ["t_2", "t_3"], "party_size": 6, "starts_at_local": local(d, "21:00")}]),
          409, "L2.28", "table_unavailable")
    # swap: combo -> [t_2,t_3] while single -> t_1: resulting set is conflict-free
    j = check(mv(cw.ada, [{"reference": combo["reference"], "table_ids": ["t_2", "t_3"], "party_size": 6},
                          {"reference": single["reference"], "table_ids": ["t_1"], "party_size": 2}]), 201, "L2.28")["reservations"]
    assert sorted(j[0]["table_ids"]) == ["t_2", "t_3"] and j[1]["table_ids"] == ["t_1"]
    # error codes via moves
    check(mv(cw.ada, [{"reference": single["reference"], "table_ids": ["t_1", "t_3"]}]), 422, "L2.28", "combination_not_allowed")
    check(mv(cw.ada, [{"reference": single["reference"], "table_ids": ["t_1", "t_2", "t_3"]}]), 422, "L2.28", "combination_not_allowed")
    check(mv(cw.ada, [{"reference": single["reference"], "table_ids": ["t_1", "t_1"]}]), 422, "L2.28", "validation_failed")
    check(mv(cw.ada, [{"reference": single["reference"], "table_ids": ["t_1", "t_2"], "table_id": "t_1"}]), 422, "L2.28", "validation_failed")
    check(mv(cw.ada, [{"reference": single["reference"], "table_ids": ["t_1"], "party_size": 3}]), 422, "L2.28", "party_exceeds_capacity")
    assert cw.bob.get(f"/reservations/{other['reference']}").json == other


def test_L2_28_moves_replay_and_atomicity_with_combos(cw):
    d = cw.date
    a = book_ok(cw.ada, d, "19:00", "t_1", 2)
    b = book_ok(cw.ada, d, "19:00", "t_3", 6)
    key = new_key()
    bad = {"moves": [{"reference": a["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6},
                     {"reference": b["reference"], "table_ids": ["t_2", "t_3"], "party_size": 6}]}
    check(cw.ada.post("/reservation-moves", json=bad, key=key), 409, "L2.28", "table_unavailable")
    assert avail_ids(d, "19:00", 1) == ["t_2"], "[L2.28] failed batch changed nothing"
    good = {"moves": [{"reference": a["reference"], "table_ids": ["t_1", "t_2"], "party_size": 6}]}
    first = check(cw.ada.post("/reservation-moves", json=good, key=key), 201, "L2.28")
    cw.ada.post(f"/reservations/{a['reference']}/cancel")
    assert check(cw.ada.post("/reservation-moves", json=good, key=key), 200, "L2.28") == first
    assert cw.ada.get(f"/reservations/{a['reference']}").json["status"] == "cancelled", "[L1.110] replay changes nothing"


# ---- concurrency ---------------------------------------------------------------------------

def users_cw(n):
    us = [user(f"c{i:02d}") for i in range(n)]
    reset(fixture(users=us, restaurants=[restaurant(combinable=PAIRS)]))
    return burst(n, lambda i: login(f"c{i:02d}@example.com"))


def test_L2_30_combo_vs_singles_race_serializes():
    cl = users_cw(50)
    d = safe_date()

    def op(i):
        k = i % 5
        if k == 0: return cpost(cl[i], d, ["t_1", "t_2"], "19:00", 6)
        if k == 1: return cpost(cl[i], d, ["t_2", "t_3"], "19:00", 8)
        if k == 2: return book(cl[i], d, "19:00", "t_2", 4)
        if k == 3: return book(cl[i], d, "19:30", "t_1", 2)
        return book(cl[i], d, "19:00", "t_3", 6)
    out = burst(50, op)
    assert all(r.status in (201, 409) for r in out), f"[L2.30] {sorted({r.status for r in out})}"
    res = []
    for c in cl:
        res += c.get("/reservations").json["reservations"]
    assert len(res) == sum(r.status == 201 for r in out) and len(res) >= 1, "[L2.30/L1.3] one booking per 201"
    occ = {}
    for r in res:
        for t in r["table_ids"]:
            occ.setdefault(t, []).append((iso(r["starts_at"]), iso(r["ends_at"]), r["reference"]))
    for t, v in occ.items():
        v.sort()
        for (s1, e1, a), (s2, e2, b) in zip(v, v[1:]):
            assert e1 <= s2, f"[L2.30] reservations {a} and {b} overlap on {t}"
    s, _ = slots(d, 1)
    for k, v in s.items():     # availability agrees with the bookings
        st = iso(v["starts_at"])
        busy = {t for t, iv in occ.items() if any(a < st + dt.timedelta(minutes=90) and st < e for a, e, _ in iv)}
        for o in v["available_options"]:
            assert not (set(o["table_ids"]) & busy), f"[L2.30] option {o} offered at {k} although {busy} busy"
        assert v["available_table_ids"] == [t for t in ("t_1", "t_2", "t_3") if t not in busy], f"[L2.24] singles at {k}"


def test_L2_30_fifty_identical_combo_requests_one_booking():
    cl = users_cw(2)
    d, key = safe_date(), new_key()
    out = burst(50, lambda i: cpost(cl[0], d, ["t_1", "t_2"], "19:00", 6, key=key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 49 + [201], f"[L2.30/L1.46] {codes.count(201)}x201 {sorted(set(codes))}"
    first = [r.json for r in out if r.status == 201][0]
    assert all(r.json == first for r in out), "[L1.46] identical bodies"
    assert len(cl[0].get("/reservations").json["reservations"]) == 1


def test_L2_30_concurrent_amend_into_same_combo():
    cl = users_cw(30)
    d = safe_date()
    mine = [book_ok(cl[i], safe_date(i + 1), "19:00", "t_1", 2) for i in range(30)]
    out = burst(30, lambda i: cl[i].patch(f"/reservations/{mine[i]['reference']}",
                                          json={"table_ids": ["t_1", "t_2"], "party_size": 6, "starts_at_local": local(d, "19:00")}))
    codes = [r.status for r in out]
    assert codes.count(200) == 1 and codes.count(409) == 29, f"[L2.30] exactly one amendment takes the pair: {sorted(set(codes))}"
    w = codes.index(200)
    for i in range(30):
        g = cl[i].get(f"/reservations/{mine[i]['reference']}").json
        assert (sorted(g["table_ids"]) == ["t_1", "t_2"]) == (i == w), f"[L1.80/L2.30] booking {i}: {g}"


def test_L2_34_export_import_keeps_combinations_and_options():
    reset(fixture(restaurants=[restaurant(combinable=PAIRS)]))
    a = login("ada@example.com"); d = safe_date()
    key = new_key()
    j = check(cpost(a, d, ["t_1", "t_2"], "19:00", 6, key=key), 201, "L2.34")
    E = call("GET", "/_test/export", timeout=10.5).json
    reset(fixture())
    r = call("POST", "/_test/import", json=E, timeout=10.5)
    assert r.status == 204, f"[L2.34] {r!r}"
    assert call("GET", "/restaurants/r_anker").json.get("combinable") == PAIRS, "[L2.34] combinable restored"
    assert a.get(f"/reservations/{j['reference']}").json == j, "[L2.34] combo reservation restored exactly"
    assert check(cpost(a, d, ["t_1", "t_2"], "19:00", 6, key=key), 200, "L2.34") == j, "[L2.34] receipt restored"
    assert {tuple(o["table_ids"]) for o in opts(d, "19:00", 1)} == {("t_3",)}, "[L2.34] restored combo still occupies t_1 and t_2"
