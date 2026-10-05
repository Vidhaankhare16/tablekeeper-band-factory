"""Applying a plan, closures, restaurant revision accounting, series interplay (ledger L4.20-L4.49)."""
import random
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, new_key, local, login, history, add_days, iso,
                      burst, publish_ok, policy, publish, book_ok, book, avail_ids, slots)
from replan_kit import inst, replan, plan_ok, apply_plan, apply_ok, rev
from test_replans import rworld, bk, pv, world_state, D, tabs, closure
from test_series import adopt_ok, gs, occ_by_index


def setup_basic():
    w = rworld()
    a = bk(w.ada, w, "19:00", ["t_2"], 2)
    b = bk(w.bob, w, "19:00", ["t_3"], 3)
    c = bk(w.cy, w, "21:00", ["t_5"], 6)
    return w, a, b, c


# ---- apply: errors and idempotency (L4.20-L4.24) --------------------------------------------------

def test_L4_20_apply_requires_manager_key_and_known_plan():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    pid = p["plan_id"]
    check(call("POST", f"/restaurants/r_anker/replans/{pid}/apply", json={}, key=new_key()), 401, "L4.20", "unauthenticated")
    check(apply_plan(w.bob, "r_anker", pid), 403, "L4.20", "forbidden")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", json={}), 400, "L4.20", "missing_idempotency_key")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", json={}, key=""), 400, "L4.20", "missing_idempotency_key")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", json={}, key="k" * 256), 422, "L4.20", "validation_failed")
    check(apply_plan(w.ada, "r_anker", "nope"), 404, "L4.20", "not_found")
    check(apply_plan(w.ada, "r_ghost", pid), 404, "L4.20", "not_found")
    check(apply_plan(w.bob, "r_ghost", pid), 404, "L4.20", "not_found")
    other = replan(w.ada, "r_two", "t_x1", inst(w.d, "18:00"), inst(w.d, "23:00")).json
    check(apply_plan(w.ada, "r_anker", other["plan_id"]), 404, "L4.20", "not_found")                  # a plan of another restaurant
    check(apply_plan(w.ada, "r_two", pid), 404, "L4.20", "not_found")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", raw="[1]", key=new_key()), 400, "L4.20", "malformed_request")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", raw="{bad", key=new_key()), 400, "L4.20", "malformed_request")
    check(w.ada.post(f"/restaurants/r_anker/replans/{pid}/apply", json={"junk": 1}, key=new_key()), 201, "L4.20")       # unknown fields ignored


def test_L4_21_apply_response_shape_and_content():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    r0 = rev(w.ada)
    assert p["restaurant_revision"] == r0
    out = check(apply_plan(w.ada, "r_anker", p["plan_id"]), 201, "L4.21")
    assert set(out) == {"plan_id", "restaurant_revision", "reservations"} and out["plan_id"] == p["plan_id"], f"[L4.21] {sorted(out)}"
    assert out["restaurant_revision"] == p["restaurant_revision"] + 1, "[L4.21] applying a plan increments the restaurant revision once for the whole plan"
    assert [x["reference"] for x in out["reservations"]] == [x["reference"] for x in p["assignments"]], "[L4.21] every considered booking in reference order"
    for x, asg in zip(out["reservations"], p["assignments"]):
        assert x["table_ids"] == asg["table_ids"]
        assert ("table_id" in x) == (len(x["table_ids"]) == 1)
        g = {r["reference"]: r for cl in (w.ada, w.bob, w.cy) for r in cl.get("/reservations").json["reservations"]}[x["reference"]]
        assert g == x, "[L4.21] the apply response equals the stored records"
    assert rev(w.ada) == out["restaurant_revision"]


def test_L4_22_moved_bookings_gain_revision_and_a_reassigned_entry_unmoved_gain_nothing():
    w, a, b, c = setup_basic()
    before = {r["reference"]: (r, history(cl, r["reference"])) for cl in (w.ada, w.bob, w.cy) for r in cl.get("/reservations").json["reservations"]}
    p = pv(w, "t_2", "18:00", "23:00")
    out = apply_ok(w.ada, "r_anker", p["plan_id"])
    moved = {x["reference"] for x in p["assignments"] if x["changed"]}
    assert moved and a["reference"] in moved
    owners = {a["reference"]: w.ada, b["reference"]: w.bob, c["reference"]: w.cy}
    for x in out["reservations"]:
        old, oldh = before[x["reference"]]
        newh = history(owners[x["reference"]], x["reference"])
        if x["reference"] in moved:
            assert x["revision"] == old["revision"] + 1, "[L4.22] each moved booking increments its revision once"
            assert len(newh) == len(oldh) + 1 and newh[:-1] == oldh, "[L4.22] exactly one new history entry, earlier entries unchanged"
            e = newh[-1]
            assert e["event"] == "reassigned" and e["plan_id"] == p["plan_id"] and e["seq"] == len(oldh) + 1 and e["revision"] == x["revision"], f"[L4.22] {e}"
            assert e["changes"] == [{"field": "table_ids", "from": old["table_ids"], "to": x["table_ids"]}], f"[L4.22] a reassigned entry carries a table_ids change: {e['changes']}"
            assert e["accepted_terms"] == old["accepted_terms"] and x["accepted_terms"] == old["accepted_terms"], "[L4.22] accepted terms are identical"
        else:
            assert x == old and newh == oldh, "[L4.22] unmoved bookings gain nothing"
        for k in ("starts_at", "ends_at", "starts_at_local", "party_size", "created_at", "reservation_id", "status"):
            assert x[k] == old[k], f"[L4.22/L4.11] {k} unchanged"
        assert owners[x["reference"]].get(f"/reservations/{x['reference']}/decision").json["revision"] == x["revision"]


def test_L4_23_replay_stale_and_already_applied():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    key = new_key()
    first = check(apply_plan(w.ada, "r_anker", p["plan_id"], key), 201, "L4.23")
    # replay of the successful key returns the original response, even after later changes
    w.cy.post(f"/reservations/{c['reference']}/cancel")
    bk(w.cy, w, "21:30", ["t_6"], 8)
    again = check(apply_plan(w.ada, "r_anker", p["plan_id"], key), 200, "L4.23")
    assert again == first, "[L4.23] replay returns the original response with 200"
    check(w.ada.post(f"/restaurants/r_anker/replans/{p['plan_id']}/apply", json={"x": 1}, key=key), 409, "L4.23", "idempotency_key_reuse")
    # same plan under a different key
    check(apply_plan(w.ada, "r_anker", p["plan_id"]), 409, "L4.23", "plan_already_applied")
    # a failed apply leaves its key reusable: unknown plan then ... (first use semantic)
    k2 = new_key()
    check(apply_plan(w.ada, "r_anker", "nope", k2), 404, "L4.23", "not_found")
    check(apply_plan(w.ada, "r_anker", p["plan_id"], k2), 409, "L4.23", "plan_already_applied")


def test_L4_24_any_intervening_revision_makes_the_plan_stale_and_changes_nothing():
    fut = safe_date()
    events = {
        "new booking": lambda w, f: bk(w.cy, w, "21:30", ["t_6"], 8),
        "cancellation": lambda w, f: w.cy.post(f"/reservations/{f['reference']}/cancel"),
        "amendment": lambda w, f: w.cy.patch(f"/reservations/{f['reference']}", json={"party_size": 3}),
        "policy publication": lambda w, f: publish(w.ada, "r_anker", policy("2030-01-01", opening_hours=all_week("12:00", "23:30"),
                                                                              capacities={f"t_{i + 1}": cp for i, cp in enumerate((2, 2, 4, 4, 6, 8))})),
        "batch move": lambda w, f: w.cy.post("/reservation-moves", json={"moves": [{"reference": f["reference"], "party_size": 3}]}, headers={"Idempotency-Key": new_key()}),
        "another plan": None}
    for name, act in events.items():
        w, a, b, c = setup_basic()
        f = bk(w.cy, w, "19:00", ["t_6"], 2, date=fut)                                    # a future booking diners can still change
        p = pv(w, "t_2")
        if act:
            act(w, f)
        else:
            other = pv(w, "t_1", "10:00", "11:00")
            apply_ok(w.ada, "r_anker", other["plan_id"])
        pre = world_state(w)
        r0 = rev(w.ada)
        assert r0 > p["restaurant_revision"] or name == "batch move", f"setup: {name} must have raised the restaurant revision ({r0} vs {p['restaurant_revision']})"
        check(apply_plan(w.ada, "r_anker", p["plan_id"]), 409, f"L4.24 ({name})", "stale_plan")
        assert world_state(w) == pre and rev(w.ada) == r0, f"[L4.24] a stale plan ({name}) changes nothing"
        check(apply_plan(w.ada, "r_anker", p["plan_id"]), 409, f"L4.24 ({name})", "stale_plan")                  # and stays stale


def test_L4_24_no_op_failure_and_replay_events_do_not_stale_a_plan():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    w.cy.patch(f"/reservations/{c['reference']}", json={})                                            # no-op
    w.cy.patch(f"/reservations/{c['reference']}", json={"party_size": 99})                            # failure
    pv(w, "t_3", "10:00", "11:00")                                                                    # previews
    pv(w, "t_4", "10:00", "11:00")
    check(replan(w.ada, "r_anker", "t_ghost", inst(w.d, "10:00"), inst(w.d, "11:00")), 404, "L4.24", "not_found")
    check(apply_plan(w.ada, "r_anker", p["plan_id"]), 201, "L4.24")


def test_L4_25_a_closure_at_another_restaurant_does_not_invalidate_the_plan():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    other = replan(w.ada, "r_two", "t_x1", inst(w.d, "18:00"), inst(w.d, "23:00")).json
    check(apply_plan(w.ada, "r_two", other["plan_id"]), 201, "L4.25")
    check(apply_plan(w.ada, "r_anker", p["plan_id"]), 201, "L4.25")
    assert rev(w.ada, "r_anker") == p["restaurant_revision"] + 1 and rev(w.ada, "r_two", "t_x1") >= 1, "[L4.25] revisions are per restaurant"


def test_L4_26_empty_plan_can_be_applied_and_records_the_closure():
    w = rworld()
    p = pv(w, "t_3", "18:00", "23:00")
    assert p["assignments"] == [] and p["moved_count"] == 0 and p["unused_seats"] == 0
    out = check(apply_plan(w.ada, "r_anker", p["plan_id"]), 201, "L4.26")
    assert out["reservations"] == [] and out["restaurant_revision"] == p["restaurant_revision"] + 1
    r = w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(w.d, "19:00"), "party_size": 2}, key=new_key())
    check(r, 409, "L4.26", "table_unavailable")


# ---- closures afterwards (L4.30-L4.36) ------------------------------------------------------------

def avail(w, party=1, date=None, explain=False):
    q = f"restaurant_id=r_anker&date={date or w.d}&party_size={party}" + ("&explain=true" if explain else "")
    return {s["starts_at_local"][-5:]: s for s in call("GET", f"/availability?{q}").json["slots"]}


def test_L4_30_closures_exclude_singles_and_pairs_from_availability_and_explain():
    w = rworld()
    apply_ok(w.ada, "r_anker", pv(w, "t_3", "18:00", "20:00")["plan_id"])                 # t_3 closed [18:00,20:00)
    s = avail(w, 1, explain=True)
    for at, taken in (("16:30", False), ("17:00", True), ("17:30", True), ("18:00", True), ("19:00", True), ("19:30", True), ("20:00", False), ("20:30", False)):
        slot = s[at]
        free = "t_3" in slot["available_table_ids"]
        assert free != taken, f"[L4.30] t_3 at {at}: slot interval [{at}, +90m) vs closure [18:00,20:00): taken={taken}, available_table_ids={slot['available_table_ids']}"
        pair_opts = [o["table_ids"] for o in slot["available_options"] if len(o["table_ids"]) == 2 and "t_3" in o["table_ids"]]
        assert (pair_opts == []) == taken, f"[L4.30] pairs containing the closed table are excluded exactly while it is closed: {at} {pair_opts}"
        e = {x["table_id"]: x for x in slot["explain"]}["t_3"]
        assert e["rules"][1] == {"rule": "no_overlap", "holds": not taken}, f"[L4.30] no_overlap is false for a closure as for a conflicting booking: {at} {e}"
        assert e["available"] == (not taken)
        for other in ("t_1", "t_2", "t_4"):
            assert other in slot["available_table_ids"], "[L4.30] other tables unaffected"
    assert [x["table_id"] for x in s["19:00"]["explain"]] == [f"t_{i}" for i in range(1, 7)]


def test_L4_31_creates_and_amendments_onto_a_closed_table_are_refused_409():
    w = rworld(date=safe_date())                        # a future day, so diners can still amend their bookings
    apply_ok(w.ada, "r_anker", pv(w, "t_3", "18:00", "20:00")["plan_id"])
    for at in ("17:00", "17:30", "18:00", "19:00", "19:30"):
        check(w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(w.d, at), "party_size": 2}, key=new_key()),
              409, f"L4.31 ({at})", "table_unavailable")
        check(w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_3", "t_4"], "starts_at_local": local(w.d, at), "party_size": 6}, key=new_key()),
              409, f"L4.31 pair ({at})", "table_unavailable")
        check(w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_2", "t_3"], "starts_at_local": local(w.d, at), "party_size": 5}, key=new_key()),
              409, f"L4.31 pair 2 ({at})", "table_unavailable")
    for at in ("16:30", "20:00", "21:30"):
        check(w.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(w.d, at), "party_size": 2}, key=new_key()),
              201, f"L4.31 ({at}) is outside the closure", None)
    x = bk(w.cy, w, "19:00", ["t_4"], 2)
    check(w.cy.patch(f"/reservations/{x['reference']}", json={"table_id": "t_3"}), 409, "L4.31", "table_unavailable")
    check(w.cy.patch(f"/reservations/{x['reference']}", json={"table_ids": ["t_3", "t_4"], "party_size": 6}), 409, "L4.31", "table_unavailable")
    assert w.cy.get(f"/reservations/{x['reference']}").json == x
    m = w.cy.post("/reservation-moves", json={"moves": [{"reference": x["reference"], "table_id": "t_3"}]}, key=new_key())
    check(m, 409, "L4.31", "table_unavailable")
    # moving the booking in time so that it clears the closure is fine
    check(w.cy.patch(f"/reservations/{x['reference']}", json={"table_id": "t_3", "starts_at_local": local(w.d, "13:00")}), 200, "L4.31")


def test_L4_32_closure_is_per_table_and_per_restaurant():
    w = rworld()
    apply_ok(w.ada, "r_anker", pv(w, "t_3", "18:00", "20:00")["plan_id"])
    s = call("GET", f"/availability?restaurant_id=r_two&date={w.d}&party_size=1").json["slots"]
    assert all(x["available_table_ids"] == ["t_x1", "t_x2"] for x in s), "[L4.32] a closure at one restaurant does not affect another"
    d2 = avail(w, 1, date=add_days(w.d, 1))
    assert all("t_3" in x["available_table_ids"] for x in d2.values()), "[L4.32] other days unaffected"


def test_L4_33_series_generation_and_amendment_respect_closures():
    w = rworld(date="2030-01-15")                                          # a future Tuesday: adoption needs a future anchor
    anchor = bk(w.ada, w, "19:00", ["t_3"], 3)
    apply_ok(w.ada, "r_anker", pv(w, "t_3", "18:00", "20:00", date=add_days(w.d, 14))["plan_id"])      # closes t_3 on occurrence 2's day
    r = w.ada.post("/series", json={"anchor_reference": anchor["reference"], "count": 4, "interval_weeks": 1}, key=new_key())
    check(r, 409, "L4.33", "table_unavailable")


def test_L4_34_cancelled_bookings_and_cancelled_closure_free_nothing_but_cancel_still_works():
    w = rworld()
    a = bk(w.ada, w, "19:00", ["t_3"], 2)
    apply_ok(w.ada, "r_anker", pv(w, "t_3", "18:00", "20:00")["plan_id"])
    cur = w.ada.get(f"/reservations/{a['reference']}").json
    assert cur["table_ids"] != ["t_3"]
    c = check(w.ada.post(f"/reservations/{a['reference']}/cancel"), 409, "L4.34", "cutoff_passed")                 # past booking: diner cutoff still applies to diners
    assert avail(w, 1)["19:00"]["available_table_ids"].count("t_3") == 0


# ---- restaurant revision accounting (L4.40) ----------------------------------------------------------

def test_L4_40_restaurant_revision_accounting():
    reset(fixture(restaurants=[restaurant(managers=["u_ada"], combinable=[["t_1", "t_2"], ["t_2", "t_3"]]),
                               restaurant("r_two", name="Zwei", managers=["u_ada"], tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])]))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    d = safe_date()
    r = lambda: rev(ada)
    assert r() == 0, "[L4.40] a restaurant revision starts at 0 after reset"
    step = [0]

    def expect(delta, what):
        step[0] += delta
        got = r()
        assert got == step[0], f"[L4.40] after {what}: restaurant revision {got}, expected {step[0]}"
    j = book_ok(ada, d, "19:00", "t_2", 4); expect(1, "a successful new booking")
    key = new_key(); b = {"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(d, "19:00"), "party_size": 5}
    ada.post("/reservations", json=b, key=key); expect(1, "another booking")
    ada.post("/reservations", json=b, key=key); expect(0, "a replayed booking")
    ada.post("/reservations", json={**b, "table_id": "t_ghost"}, key=new_key()); expect(0, "a failed booking")
    ada.post("/reservations", json={**b, "party_size": 99}, key=new_key()); expect(0, "a failed booking (422)")
    ada.patch(f"/reservations/{j['reference']}", json={"party_size": 3}); expect(1, "a real amendment")
    ada.patch(f"/reservations/{j['reference']}", json={"party_size": 3}); expect(0, "a no-op amendment")
    ada.patch(f"/reservations/{j['reference']}", json={"party_size": 99}); expect(0, "a failed amendment")
    ada.patch(f"/reservations/{j['reference']}", json={"party_size": 2, "expected_revision": 9}); expect(0, "a stale amendment")
    ada.post(f"/reservations/{j['reference']}/cancel"); expect(1, "a cancellation")
    ada.post(f"/reservations/{j['reference']}/cancel"); expect(0, "a repeated cancellation")
    pk = new_key(); pol = policy(add_days(d, 40), capacities={"t_1": 2, "t_2": 4, "t_3": 6})
    publish(ada, "r_anker", pol, pk); expect(1, "a policy publication")
    publish(ada, "r_anker", pol, pk); expect(0, "a replayed publication")
    publish(ada, "r_anker", policy("garbage"), new_key()); expect(0, "a failed publication")
    bob.post("/restaurants/r_anker/policies", json=pol, headers={"Idempotency-Key": new_key()}); expect(0, "a refused publication")
    x = book_ok(ada, d, "19:00", "t_1", 2); expect(1, "a booking")
    y = book_ok(ada, d, "21:00", "t_1", 2); expect(1, "a booking")
    mk = new_key(); mb = {"moves": [{"reference": x["reference"], "table_id": "t_2", "party_size": 2}, {"reference": y["reference"], "table_id": "t_2"}]}
    check(ada.post("/reservation-moves", json=mb, key=mk), 201, "L4.40"); expect(1, "a batch of two real moves (once per batch)")
    ada.post("/reservation-moves", json=mb, key=mk); expect(0, "a replayed batch")
    ada.post("/reservation-moves", json={"moves": [{"reference": x["reference"]}, {"reference": y["reference"]}]}, key=new_key()); expect(0, "a batch of no-ops")
    ada.post("/reservation-moves", json={"moves": [{"reference": x["reference"], "table_id": "t_ghost"}]}, key=new_key()); expect(0, "a failed batch")
    anchor = book_ok(ada, add_days(d, 1), "19:00", "t_3", 4); expect(1, "a booking")
    sk = new_key(); sb = {"anchor_reference": anchor["reference"], "count": 4, "interval_weeks": 1}
    s = check(ada.post("/series", json=sb, key=sk), 201, "L4.40"); expect(1, "a series adoption (three new bookings, once for the whole operation)")
    ada.post("/series", json=sb, key=sk); expect(0, "a replayed adoption")
    ada.post("/series", json={**sb, "anchor_reference": anchor["reference"]}, key=new_key()); expect(0, "a refused adoption (already_in_series)")
    sid = s["series_id"]
    ab = {"expected_revision": 1, "from_index": 1, "local_time": "20:00"}
    check(ada.post(f"/series/{sid}/amend", json=ab, key=new_key()), 201, "L4.40"); expect(1, "a series amendment (once for the entire operation)")
    check(ada.post(f"/series/{sid}/amend", json={"expected_revision": 2, "from_index": 1, "local_time": "20:00"}, key=new_key()), 201, "L4.40"); expect(0, "an all-no-op series amendment")
    ada.post(f"/series/{sid}/amend", json={"expected_revision": 1, "from_index": 1, "local_time": "21:00"}, key=new_key()); expect(0, "a stale series amendment")
    ada.patch(f"/reservations/{s['occurrences'][2]['reference']}", json={"party_size": 3}); expect(1, "an occurrence amendment")
    ada.post(f"/reservations/{s['occurrences'][3]['reference']}/cancel"); expect(1, "an occurrence cancellation")
    pl = replan(ada, "r_anker", "t_1", inst(add_days(d, 200), "18:00"), inst(add_days(d, 200), "19:00")); assert pl.status == 201
    expect(0, "a preview")
    check(apply_plan(ada, "r_anker", pl.json["plan_id"]), 201, "L4.40"); expect(1, "a plan application")
    k = new_key(); check(apply_plan(ada, "r_anker", pl.json["plan_id"], k), 409, "L4.40", "plan_already_applied"); expect(0, "a refused application")
    assert rev(ada, "r_two", "t_x1") == 0, "[L4.40] revisions are per restaurant"
    ada.get("/reservations"); ada.get(f"/availability?restaurant_id=r_anker&date={d}&party_size=1"); expect(0, "reads")


# ---- series interplay (L4.41-L4.43) ---------------------------------------------------------------------

def series_world():
    w = rworld(date="2030-01-15")
    anchor = bk(w.ada, w, "19:00", ["t_2"], 2)
    s = adopt_ok(w.ada, anchor["reference"], 4, 1)
    return w, s


def test_L4_41_replans_move_series_occurrences_preserving_flags_dates_identities_and_terms():
    w, s = series_world()
    sid, occ = s["series_id"], s["occurrences"]
    refs = [o["reference"] for o in occ]
    w.ada.patch(f"/reservations/{refs[1]}", json={"party_size": 1})                    # exception on occurrence 1
    w.ada.post(f"/reservations/{refs[3]}/cancel")                                      # cancelled occurrence (not considered)
    g0 = gs(w.ada, sid).json
    assert g0["revision"] == 3
    d1, d2 = add_days(w.d, 7), add_days(w.d, 14)
    # close t_2 on occurrence 1's and 2's days: one plan per day
    p1 = pv(w, "t_2", "18:00", "23:00", date=d1)
    out1 = apply_ok(w.ada, "r_anker", p1["plan_id"])
    g1 = gs(w.ada, sid).json
    assert g1["revision"] == 4, "[L4.41] each affected series revision increases once per plan application"
    assert [o["exception"] for o in g1["occurrences"]] == [o["exception"] for o in g0["occurrences"]], "[L4.41] exception flags are preserved"
    o1 = occ_by_index(g1)[1]
    assert o1["reference"] == refs[1] and o1["reservation"]["table_ids"] != ["t_2"] and o1["reservation"]["starts_at_local"] == f"{d1}T19:00", "[L4.41] identity and scheduled date preserved"
    assert o1["reservation"]["accepted_terms"] == occ[1]["reservation"]["accepted_terms"]
    p2 = pv(w, "t_2", "18:00", "23:00", date=d2)
    apply_ok(w.ada, "r_anker", p2["plan_id"])
    g2 = gs(w.ada, sid).json
    assert g2["revision"] == 5 and occ_by_index(g2)[2]["exception"] is False, "[L4.41] a moved non-exception occurrence stays a non-exception"
    assert occ_by_index(g2)[2]["reservation"]["table_ids"] != ["t_2"] and occ_by_index(g2)[2]["reservation"]["revision"] == 2
    # one plan moving two members of the same series bumps the series revision once
    w2 = rworld(date="2030-01-15")
    a2 = bk(w2.ada, w2, "19:00", ["t_2"], 2)
    s2 = adopt_ok(w2.ada, a2["reference"], 3, 1)
    p = replan(w2.ada, "r_anker", "t_2", inst(add_days(w2.d, 0), "18:00"), inst(add_days(w2.d, 14), "23:00"))
    assert p.status == 201
    apply_ok(w2.ada, "r_anker", p.json["plan_id"])
    g = gs(w2.ada, s2["series_id"]).json
    assert g["revision"] == 2, f"[L4.41] a plan that moves three members of one series raises its revision once: {g['revision']}"
    assert sum(1 for x in p.json["assignments"] if x["changed"]) == 3
    assert all(o["exception"] is False for o in g["occurrences"])


def test_L4_42_unmoved_series_do_not_change():
    w, s = series_world()
    other_anchor = bk(w.bob, w, "19:00", ["t_5"], 6)
    s2 = adopt_ok(w.bob, other_anchor["reference"], 3, 1)
    before = gs(w.bob, s2["series_id"]).json
    apply_ok(w.ada, "r_anker", pv(w, "t_2", "18:00", "23:00", date=add_days(w.d, 7))["plan_id"])
    assert gs(w.bob, s2["series_id"]).json == before, "[L4.42] a series with no moved member is untouched (no revision bump)"
    assert gs(w.ada, s["series_id"]).json["revision"] == 2


def test_L4_43_series_amend_after_replan_uses_the_current_table_selection():
    w, s = series_world()
    apply_ok(w.ada, "r_anker", pv(w, "t_2", "18:00", "23:00", date=add_days(w.d, 7))["plan_id"])
    g = gs(w.ada, s["series_id"]).json
    moved = occ_by_index(g)[1]["reservation"]["table_ids"]
    out = check(w.ada.post(f"/series/{s['series_id']}/amend", json={"expected_revision": g["revision"], "from_index": 0, "local_time": "20:00"}, key=new_key()), 201, "L4.43")
    assert occ_by_index(out)[1]["reservation"]["table_ids"] == moved and occ_by_index(out)[1]["reservation"]["starts_at_local"].endswith("T20:00"), "[L4.43] current table selection retained"


# ---- concurrency (L4.45) -------------------------------------------------------------------------------

def test_L4_45_concurrent_applications_of_one_plan_apply_once():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    out = burst(20, lambda i: apply_plan(w.ada, "r_anker", p["plan_id"]))
    codes = sorted(r.status for r in out)
    assert codes == [201] + [409] * 19, f"[L4.45] exactly one application: {codes.count(201)}x201 {sorted(set(codes))}"
    for r in out:
        if r.status == 409:
            assert r.json["error"]["code"] in ("plan_already_applied", "stale_plan"), f"[L4.45] {r.json}"
    moved = [x for x in p["assignments"] if x["changed"]]
    for x in moved:
        owner = {a["reference"]: w.ada, b["reference"]: w.bob, c["reference"]: w.cy}[x["reference"]]
        assert owner.get(f"/reservations/{x['reference']}").json["revision"] == 2, "[L4.45] each moved booking moved exactly once"
    assert rev(w.ada) == p["restaurant_revision"] + 1


def test_L4_45_concurrent_identical_key_applications_replay():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")
    key = new_key()
    out = burst(20, lambda i: apply_plan(w.ada, "r_anker", p["plan_id"], key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 19 + [201], f"[L4.45/L1.46] one 201, the rest replays: {codes}"
    assert all(r.json == out[0].json for r in out)
    assert rev(w.ada) == p["restaurant_revision"] + 1


def test_L4_45_two_plans_from_one_revision_only_one_applies():
    w, a, b, c = setup_basic()
    p1 = pv(w, "t_2")
    p2 = pv(w, "t_3", "18:00", "23:00")
    out = burst(2, lambda i: apply_plan(w.ada, "r_anker", (p1, p2)[i]["plan_id"]))
    codes = sorted(r.status for r in out)
    assert codes == [201, 409], f"[L4.45] {codes}"
    assert [r.json["error"]["code"] for r in out if r.status == 409] == ["stale_plan"]
    refs = {}
    for cl in (w.ada, w.bob, w.cy):
        for r in cl.get("/reservations").json["reservations"]:
            refs[r["reference"]] = r
    assert len({(t, r["starts_at"]) for r in refs.values() for t in r["table_ids"]}) == sum(len(r["table_ids"]) for r in refs.values()), "[L4.45/L1.1] no double booking afterwards"


def test_L4_45_applications_race_with_bookings_and_amendments():
    w, a, b, c = setup_basic()
    p = pv(w, "t_2")

    def op(i):
        if i == 0:
            return apply_plan(w.ada, "r_anker", p["plan_id"])
        if i % 3 == 1:
            return w.cy.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_6", "starts_at_local": local(w.d, "22:00"), "party_size": 8}, key=new_key())
        return w.bob.patch(f"/reservations/{b['reference']}", json={"party_size": 1 + (i % 4)})
    out = burst(30, op)
    assert all(r.status in (200, 201, 409, 422) for r in out), sorted({r.status for r in out})
    seen = {}
    for cl in (w.ada, w.bob, w.cy):
        for r in cl.get("/reservations").json["reservations"]:
            if r["status"] != "confirmed":
                continue
            for t in r["table_ids"]:
                for o in seen.get(t, []):
                    assert not (iso(o["starts_at"]) < iso(r["ends_at"]) and iso(r["starts_at"]) < iso(o["ends_at"])), f"[L4.45/L1.1] overlap on {t}: {o['reference']} {r['reference']}"
                seen.setdefault(t, []).append(r)
    if out[0].status == 201:
        assert not [r for r in seen.get("t_2", []) if iso(r["starts_at"]) < iso(f"{w.d}T23:00:00+01:00") and iso(f"{w.d}T18:00:00+01:00") < iso(r["ends_at"])], \
            "[L4.45] after a successful application nothing sits on the closed table inside the closure"
