"""Seating changes after a table closure: replans (ledger L4.1-L4.45)."""
import random
import time
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, new_key, local, login, history, add_days, iso,
                      burst, publish_ok, policy, WEEKDAYS)
from replan_kit import (inst, replan, plan_ok, apply_plan, apply_ok, rev, Oracle, snapshot_world, normalise, overlaps)

D = "2020-01-14"                       # a Tuesday in the past: bookings in the past are legal; cutoffs must not stop operator repairs
PAIRS6 = [["t_1", "t_2"], ["t_3", "t_4"], ["t_2", "t_3"], ["t_5", "t_6"]]
CAPS6 = (2, 2, 4, 4, 6, 8)


def tabs(caps):
    return [{"id": f"t_{i + 1}", "label": str(i + 1), "capacity": c} for i, c in enumerate(caps)]


class RW:
    pass


def rworld(caps=CAPS6, pairs=PAIRS6, date=D, managers=("u_ada",), dur=90, cutoff=120, reservations=None):
    users = [user("ada"), user("bob"), user("cy")]
    reset(fixture(users=users, restaurants=[
        restaurant(tables=tabs(caps), combinable=[list(p) for p in pairs], managers=list(managers), hours=all_week("12:00", "23:30"), dur=dur, cutoff=cutoff),
        restaurant("r_two", name="Zwei", managers=["u_ada"], tables=[{"id": "t_x1", "label": "X1", "capacity": 4}, {"id": "t_x2", "label": "X2", "capacity": 4}],
                   combinable=[["t_x1", "t_x2"]], hours=all_week("12:00", "23:30"))], reservations=reservations))
    w = RW()
    w.ada, w.bob, w.cy = login("ada@example.com"), login("bob@example.com"), login("cy@example.com")
    w.d = date
    w.caps, w.pairs = caps, [list(p) for p in pairs]
    w.tables = tabs(caps)
    return w


def bk(c, w, at, tids, party, date=None, rid="r_anker"):
    r = c.post("/reservations", json={"restaurant_id": rid, "table_ids": list(tids), "starts_at_local": local(date or w.d, at), "party_size": party}, key=new_key())
    assert r.status == 201, f"setup booking {tids} {at} party {party} failed: {r!r}"
    return r.json


def closure(w, table, f="18:00", t="23:00", date=None):
    return table, inst(date or w.d, f), inst(date or w.d, t)


def pv(w, table, f="18:00", t="23:00", c=None, date=None):
    tb, a, b = closure(w, table, f, t, date)
    return plan_ok(c or w.ada, "r_anker", tb, a, b)


def world_state(w, clients=None):
    cl = clients or [w.ada, w.bob, w.cy]
    out = []
    for c in cl:
        lst = c.get("/reservations").json["reservations"]
        out.append((lst, [history(c, r["reference"]) for r in lst], [c.get(f"/reservations/{r['reference']}/decision").json for r in lst]))
    return out


# ---- access, validation, idempotency (L4.1-L4.4) --------------------------------------------

def test_L4_1_manager_checks_401_404_403():
    w = rworld()
    f, t = inst(w.d, "18:00"), inst(w.d, "23:00")
    check(call("POST", "/restaurants/r_anker/replans", json={"table_id": "t_2", "from": f, "to": t}, key=new_key()), 401, "L4.1", "unauthenticated")
    check(call("POST", "/restaurants/r_anker/replans", json={"table_id": "t_2", "from": f, "to": t}, key=new_key(), token="junk"), 401, "L4.1", "unauthenticated")
    check(replan(w.bob, "r_anker", "t_2", f, t), 403, "L4.1", "forbidden")
    check(replan(w.cy, "r_anker", "t_2", f, t), 403, "L4.1", "forbidden")
    check(replan(w.ada, "r_ghost", "t_2", f, t), 404, "L4.1", "not_found")
    check(replan(w.bob, "r_ghost", "t_2", f, t), 404, "L4.1", "not_found")
    check(replan(w.ada, "r_anker", "t_ghost", f, t), 404, "L4.1", "not_found")
    check(replan(w.ada, "r_anker", "t_x1", f, t), 404, "L4.1", "not_found")                     # a table of another restaurant
    check(replan(w.ada, "r_anker", "t_2", f, t), 201, "L4.1")
    pl = plan_ok(w.ada, "r_two", "t_x1", f, t)
    assert pl["assignments"] == []


def test_L4_2_key_required_and_ranged():
    w = rworld()
    f, t = inst(w.d, "18:00"), inst(w.d, "23:00")
    b = {"table_id": "t_2", "from": f, "to": t}
    check(w.ada.post("/restaurants/r_anker/replans", json=b), 400, "L4.2", "missing_idempotency_key")
    check(w.ada.post("/restaurants/r_anker/replans", json=b, key=""), 400, "L4.2", "missing_idempotency_key")
    check(w.ada.post("/restaurants/r_anker/replans", json=b, key="k" * 256), 422, "L4.2", "validation_failed")
    check(w.ada.post("/restaurants/r_anker/replans", json=b, key="k" * 255), 201, "L4.2")
    check(w.ada.post("/restaurants/r_anker/replans", raw="{bad", key=new_key()), 400, "L4.2", "malformed_request")
    check(w.ada.post("/restaurants/r_anker/replans", raw="[1]", key=new_key()), 400, "L4.2", "malformed_request")
    check(w.ada.post("/restaurants/r_anker/replans", json={**b, "junk": 1, "extra": [1]}, key=new_key()), 201, "L4.2")      # unknown fields ignored


@pytest.mark.parametrize("name,frm,to", [
    ("from == to", "2020-01-14T18:00:00+01:00", "2020-01-14T18:00:00+01:00"),
    ("from after to", "2020-01-14T19:00:00+01:00", "2020-01-14T18:00:00+01:00"),
    ("same instant other offsets", "2020-01-14T18:00:00+01:00", "2020-01-14T17:00:00+00:00"),
    ("from no offset", "2020-01-14T18:00:00", "2020-01-14T19:00:00+01:00"),
    ("to no offset", "2020-01-14T18:00:00+01:00", "2020-01-14T19:00:00"),
    ("local minute format", "2020-01-14T18:00", "2020-01-14T19:00"),
    ("date only", "2020-01-14", "2020-01-15"),
    ("garbage", "yesterday", "tomorrow"),
    ("empty", "", ""),
    ("bad month", "2020-13-14T18:00:00+01:00", "2020-13-14T19:00:00+01:00"),
    ("bad offset", "2020-01-14T18:00:00+25:00", "2020-01-14T19:00:00+01:00"),
])
def test_L4_3_invalid_interval_is_422(name, frm, to):
    w = rworld()
    check(replan(w.ada, "r_anker", "t_2", frm, to), 422, f"L4.3 ({name})", "validation_failed")


def test_L4_3_missing_and_wrong_typed_fields():
    w = rworld()
    f, t = inst(w.d, "18:00"), inst(w.d, "23:00")
    for b in ({"from": f, "to": t}, {"table_id": "t_2", "to": t}, {"table_id": "t_2", "from": f}, {}):
        check(w.ada.post("/restaurants/r_anker/replans", json=b, key=new_key()), 422, "L4.3", "validation_failed")
    for b in ({"table_id": 2, "from": f, "to": t}, {"table_id": "t_2", "from": 20200114, "to": t}, {"table_id": ["t_2"], "from": f, "to": t},
              {"table_id": "t_2", "from": f, "to": None}):
        r = w.ada.post("/restaurants/r_anker/replans", json=b, key=new_key())
        assert r.status in (400, 422), f"[L4.3] wrong JSON types are rejected (400 malformed_request per §5 or 422): {r!r}"   # READING Q1
    check(replan(w.ada, "r_anker", "t_2", "2020-01-14T18:00:00Z", "2020-01-14T19:00:00Z"), 201, "L4.3")                   # Z is an explicit offset


def test_L4_4_replay_reuse_and_failed_keys():
    w = rworld()
    bk(w.bob, w, "19:00", ["t_2"], 2)
    f, t = inst(w.d, "18:00"), inst(w.d, "23:00")
    key = new_key()
    first = check(replan(w.ada, "r_anker", "t_2", f, t, key), 201, "L4.4")
    again = check(replan(w.ada, "r_anker", "t_2", f, t, key), 200, "L4.4")
    assert again == first, "[L4.4] replay of a successful preview returns the original response (same plan_id) with 200"
    raw = '{"to": "%s", "from": "%s",   "table_id": "t_2"}' % (t, f)
    assert check(w.ada.post("/restaurants/r_anker/replans", raw=raw, key=key), 200, "L4.4") == first
    check(replan(w.ada, "r_anker", "t_3", f, t, key), 409, "L4.4", "idempotency_key_reuse")
    check(w.ada.post("/restaurants/r_anker/replans", json={"nonsense": 1}, key=key), 409, "L4.4", "idempotency_key_reuse")      # §7: before validation
    bad = new_key()
    check(replan(w.ada, "r_anker", "t_2", t, f, bad), 422, "L4.4", "validation_failed")
    ok = check(replan(w.ada, "r_anker", "t_2", f, t, bad), 201, "L4.4")                                                          # failed key = first use
    assert ok["plan_id"] != first["plan_id"], "[L4.4] a new preview is a new plan"
    check(replan(w.bob, "r_anker", "t_2", f, t, key), 403, "L4.4", "forbidden")                                                  # keys are per user, and bob is no manager


# ---- optimality against a brute-force oracle (L4.5-L4.8) -----------------------------------------

def gen_scenario(w, rng):
    """Create 2-6 random bookings (single or declared pair) on D, then return a random closure."""
    users = [w.ada, w.bob, w.cy]
    starts = [f"{h:02d}:{m:02d}" for h in range(12, 22) for m in (0, 30)]
    options = [[f"t_{i + 1}"] for i in range(6)] + [list(p) for p in w.pairs]
    made = []
    tries = 0
    target = rng.randint(2, 6)
    while len(made) < target and tries < 60:
        tries += 1
        at = rng.choice(starts)
        opt = rng.choice(options)
        cap = sum(w.caps[int(t[2:]) - 1] for t in opt)
        party = rng.randint(max(1, cap - 3), cap)
        r = users[rng.randrange(3)].post("/reservations", json={"restaurant_id": "r_anker", "table_ids": opt, "starts_at_local": local(w.d, at), "party_size": party}, key=new_key())
        if r.status == 201:
            made.append(r.json)
    tb = f"t_{rng.randint(1, 6)}"
    a = rng.choice(starts[:14])
    ai = starts.index(a)
    b = starts[min(len(starts) - 1, ai + rng.randint(1, 6))]
    return made, tb, a, b


def oracle_for(w, tb, a, b, closures=()):
    return snapshot_world([w.ada, w.bob, w.cy], "r_anker", w.tables, w.pairs, list(closures), (tb, __import__("datetime").datetime.fromisoformat(inst(w.d, a)), __import__("datetime").datetime.fromisoformat(inst(w.d, b))))


@pytest.mark.parametrize("seed", range(30))
def test_L4_5_plan_equals_the_brute_force_optimum(seed):
    w = rworld()
    rng = random.Random(1000 + seed)
    made, tb, a, b = gen_scenario(w, rng)
    orc = oracle_for(w, tb, a, b)
    want = orc.solve()
    pre = world_state(w)
    r = replan(w.ada, "r_anker", tb, inst(w.d, a), inst(w.d, b))
    if want is None:
        check(r, 409, f"L4.8 (seed {seed})", "no_feasible_plan")
    else:
        j = check(r, 201, f"L4.5 (seed {seed})")
        assert normalise(j["assignments"]) == want["assignments"], \
            f"[L4.5/L4.7] seed {seed}: closure {tb} {a}-{b}; expected the optimal plan {want['assignments']} (moved {want['moved']}, unused {want['unused']}), got {j['assignments']} (moved {j['moved_count']}, unused {j['unused_seats']})"
        assert j["moved_count"] == want["moved"] and j["unused_seats"] == want["unused"], f"[L4.5] seed {seed}: counters {j['moved_count']}/{j['unused_seats']} vs {want['moved']}/{want['unused']}"
        assert [x["reference"] for x in j["assignments"]] == sorted(x["reference"] for x in j["assignments"]), "[L4.9] assignments in reference order"
        assert j["moved_count"] == sum(1 for x in j["assignments"] if x["changed"])
    assert world_state(w) == pre, f"[L4.12] seed {seed}: a preview (or its refusal) changes no booking, revision or history"


def test_L4_5_oracle_scenarios_cover_feasible_infeasible_and_moving_plans():
    feas = infeas = moving = 0
    for seed in range(30):
        w = rworld()
        made, tb, a, b = gen_scenario(w, random.Random(1000 + seed))
        want = oracle_for(w, tb, a, b).solve()
        if want is None:
            infeas += 1
        else:
            feas += 1
            moving += want["moved"] > 0
    assert feas >= 10 and infeas >= 1 and moving >= 5, f"[L4.5] scenario mix too thin to be a real test: feasible {feas}, infeasible {infeas}, with moves {moving}"


# ---- explicit minimisation levels (L4.6-L4.7) ---------------------------------------------------

def test_L4_6_level_one_fewest_changed_bookings_beats_fewer_unused_seats():
    w = rworld(caps=(6, 2, 4, 4, 2, 8), pairs=[["t_1", "t_2"], ["t_3", "t_4"], ["t_2", "t_3"], ["t_5", "t_6"]])
    a = bk(w.ada, w, "19:00", ["t_3"], 4)          # on the closed table
    b = bk(w.bob, w, "19:00", ["t_4"], 2)          # could move to t_2 (unused 0) freeing t_4 for A (unused 0): 2 moves, 0 unused
    j = pv(w, "t_3", "18:00", "23:00")
    got = {x["reference"]: x for x in j["assignments"]}
    assert j["moved_count"] == 1 and got[a["reference"]]["table_ids"] == ["t_1"] and got[a["reference"]]["changed"] and not got[b["reference"]]["changed"], \
        f"[L4.6] one changed booking (A -> t_1, 2 unused seats) beats two changed bookings with 0 unused: {j}"
    assert j["unused_seats"] == (6 - 4) + (4 - 2)


def test_L4_6_level_two_fewest_unused_seats_beats_option_rank():
    w = rworld(caps=(6, 2, 4, 4, 2, 8))
    a = bk(w.ada, w, "19:00", ["t_3"], 2)          # closed table; options: t_1 (cap 6, rank 0, unused 4), t_2 (cap 2, rank 1, unused 0)
    j = pv(w, "t_3", "18:00", "23:00")
    assert normalise(j["assignments"]) == [{"reference": a["reference"], "table_ids": ["t_2"], "changed": True}] and j["unused_seats"] == 0, \
        f"[L4.6] total unused seats is minimised before the rank vector: {j}"


def test_L4_6_level_three_rank_vector_in_reference_order():
    w = rworld()
    a = bk(w.ada, w, "19:00", ["t_3"], 3)          # closed t_3 (cap 4): options t_4 (rank 3, unused 1) and pair [t_1,t_2] (rank 6, unused 1)
    j = pv(w, "t_3", "18:00", "23:00")
    assert j["assignments"][0]["table_ids"] == ["t_4"] and j["unused_seats"] == 1, f"[L4.6] singles rank before pairs: {j}"
    w = rworld()
    a = bk(w.ada, w, "19:00", ["t_3", "t_4"], 6)    # pair booking on a closed member: [t_3,t_4]; alternatives pair [t_5,t_6] (cap 14) or t_5 (6, unused 0)
    j = pv(w, "t_4", "18:00", "23:00")
    assert j["assignments"][0]["table_ids"] == ["t_5"] and j["unused_seats"] == 0 and j["moved_count"] == 1, f"[L4.6] {j}"


def test_L4_7_pairs_rank_in_declared_order_and_assignment_table_ids_in_declared_order():
    # declared pairs list the ids in non-fixture order; singles are all unusable (closed / occupied / too small)
    w = rworld(caps=(2, 2, 2, 2, 6, 8), pairs=[["t_4", "t_3"], ["t_2", "t_1"]])
    a = bk(w.ada, w, "19:00", ["t_5"], 4)
    bk(w.bob, w, "19:00", ["t_6"], 8)
    j = pv(w, "t_5", "18:00", "23:00")
    got = {x["reference"]: x for x in j["assignments"]}
    assert got[a["reference"]]["table_ids"] == ["t_4", "t_3"], \
        f"[L4.7] pairs are ranked in declared order ([t_4,t_3] is declared first) and table_ids follow the declared order: {j}"
    w = rworld(caps=(2, 2, 2, 2, 6, 8), pairs=[["t_2", "t_1"], ["t_4", "t_3"]])
    a = bk(w.ada, w, "19:00", ["t_5"], 4)
    bk(w.bob, w, "19:00", ["t_6"], 8)
    j = pv(w, "t_5", "18:00", "23:00")
    assert {x["reference"]: x for x in j["assignments"]}[a["reference"]]["table_ids"] == ["t_2", "t_1"], f"[L4.7] {j}"


def test_L4_7_each_booking_uses_its_own_accepted_terms_capacities():
    w = rworld(caps=(4, 4, 4, 4, 4, 4), pairs=[])
    a = bk(w.ada, w, "19:00", ["t_1"], 4)                             # accepted under policy 0 (t_2 has capacity 4)
    publish_ok(w.ada, "r_anker", policy(w.d, opening_hours=all_week("12:00", "23:30"), capacities={"t_1": 4, "t_2": 1, "t_3": 1, "t_4": 4, "t_5": 1, "t_6": 1}))
    b = bk(w.bob, w, "19:00", ["t_4"], 4)                             # accepted under policy 1: t_2, t_3, t_5, t_6 only seat 1
    pl = pv(w, "t_1", "18:00", "23:00")
    got = {x["reference"]: x["table_ids"] for x in pl["assignments"]}
    assert got[a["reference"]] != ["t_1"]
    assert got[a["reference"]] in (["t_2"], ["t_3"], ["t_5"], ["t_6"]), f"[L4.7] booking A (policy-0 terms, every table seats 4) takes the lowest ranked free table: {pl}"
    pl2 = pv(w, "t_4", "18:00", "23:00")
    got2 = {x["reference"]: x["table_ids"] for x in pl2["assignments"]}
    assert got2[b["reference"]] == ["t_1"] or got2[b["reference"]] != ["t_4"], f"[L4.7] {pl2}"
    assert got2[b["reference"]] not in (["t_2"], ["t_3"], ["t_5"], ["t_6"]), \
        f"[L4.7] booking B was accepted under a policy where t_2/t_3/t_5/t_6 seat only 1, so it cannot move there: {pl2}"


def test_L4_8_no_feasible_plan_is_409_and_changes_nothing():
    w = rworld(caps=(4, 4, 2, 2, 2, 2), pairs=[])
    bk(w.ada, w, "19:00", ["t_1"], 4)
    bk(w.bob, w, "19:00", ["t_2"], 4)
    pre = world_state(w)
    r0 = rev(w.ada)
    check(replan(w.ada, "r_anker", "t_1", inst(w.d, "18:00"), inst(w.d, "23:00")), 409, "L4.8", "no_feasible_plan")
    assert world_state(w) == pre and rev(w.ada) == r0, "[L4.8] a refused preview changes nothing (no revision, no closure, no stored effect)"


def test_L4_8_cancelled_bookings_are_not_considered_and_unrelated_bookings_stay():
    seeded = [{"id": "res_cx", "reference": "CANCEL", "user_id": "u_cy", "restaurant_id": "r_anker", "table_ids": ["t_6"], "starts_at_local": local(D, "21:00"),
               "party_size": 8, "status": "cancelled"}]
    w = rworld(reservations=seeded)
    a = bk(w.ada, w, "19:00", ["t_2"], 2)
    b = bk(w.bob, w, "19:00", ["t_5"], 6)
    c = bk(w.cy, w, "19:00", ["t_2"], 2, date=add_days(w.d, 1))                               # another day: not overlapping the closure
    j = pv(w, "t_2", "18:00", "23:00")
    refs = [x["reference"] for x in j["assignments"]]
    assert a["reference"] in refs and c["reference"] not in refs, "[L4.9] only confirmed bookings overlapping the interval are considered"
    # every confirmed booking overlapping the interval is considered, even one not on the closed table
    assert b["reference"] in refs and next(x for x in j["assignments"] if x["reference"] == b["reference"])["changed"] is False, \
        f"[L4.9] 'Consider every confirmed booking at this restaurant overlapping that interval': {j}"
    assert len(refs) == 2 and "CANCEL" not in refs, "[L4.9] cancelled bookings are not considered"


def test_L4_9_interval_is_half_open_and_uses_booking_intervals():
    w = rworld()
    a = bk(w.ada, w, "19:00", ["t_2"], 2)           # [19:00, 20:30)
    for f, t, considered in (("17:00", "19:00", False), ("20:30", "22:00", False), ("17:00", "19:01", True), ("20:29", "22:00", True), ("19:30", "19:45", True)):
        j = pv(w, "t_2", f, t)
        assert (a["reference"] in [x["reference"] for x in j["assignments"]]) == considered, f"[L4.9] closure [{f},{t}) vs booking [19:00,20:30): considered={considered}: {j}"
    j = pv(w, "t_2", "18:00", "23:00")
    assert j["closure"]["table_id"] == "t_2" and iso(j["closure"]["from"]) == iso(inst(w.d, "18:00")) and iso(j["closure"]["to"]) == iso(inst(w.d, "23:00"))


def test_L4_9_response_shape_and_ordering():
    w = rworld()
    refs = [bk(w.ada, w, "19:00", ["t_2"], 2), bk(w.bob, w, "19:00", ["t_3"], 3), bk(w.cy, w, "20:00", ["t_6"], 8), bk(w.ada, w, "19:00", ["t_5"], 5)]
    j = pv(w, "t_3", "18:00", "23:00")
    assert set(j) == {"plan_id", "restaurant_revision", "closure", "assignments", "moved_count", "unused_seats"}, f"[L4.9] {sorted(j)}"
    assert isinstance(j["plan_id"], str) and j["plan_id"] and isinstance(j["restaurant_revision"], int)
    assert set(j["closure"]) >= {"table_id", "from", "to"}
    assert [x["reference"] for x in j["assignments"]] == sorted(r["reference"] for r in refs)
    assert all(set(x) == {"reference", "table_ids", "changed"} and isinstance(x["changed"], bool) for x in j["assignments"])


def test_L4_10_closed_table_never_hosts_a_considered_booking_and_no_overlap_among_assignments():
    w = rworld()
    for i, at in enumerate(("18:00", "18:30", "19:00", "19:30", "20:00")):
        bk([w.ada, w.bob, w.cy][i % 3], w, at, [f"t_{(i % 6) + 1}"], 1 + (i % 2))
    j = pv(w, "t_2", "18:00", "23:00")
    used = {}
    for x in j["assignments"]:
        assert "t_2" not in x["table_ids"], f"[L4.10] nobody may be assigned the closed table: {x}"
    snap = {}
    for c in (w.ada, w.bob, w.cy):
        for r in c.get("/reservations").json["reservations"]:
            snap[r["reference"]] = r
    for i, x in enumerate(j["assignments"]):
        for y in j["assignments"][i + 1:]:
            if set(x["table_ids"]) & set(y["table_ids"]):
                assert not overlaps(iso(snap[x["reference"]]["starts_at"]), iso(snap[x["reference"]]["ends_at"]),
                                    iso(snap[y["reference"]]["starts_at"]), iso(snap[y["reference"]]["ends_at"])), f"[L4.10] conflicting assignments {x} {y}"


def test_L4_10_fixed_bookings_and_previous_closures_constrain_the_plan():
    w = rworld(caps=(4, 4, 4, 4, 2, 2), pairs=[])
    a = bk(w.ada, w, "18:30", ["t_1"], 4)                             # [18:30,20:00) overlaps closure [18:00,19:00)
    fixed = bk(w.bob, w, "19:30", ["t_2"], 4)                          # [19:30,21:00): does not overlap the closure => fixed, but overlaps A's interval
    j = pv(w, "t_1", "18:00", "19:00")
    got = {x["reference"]: x for x in j["assignments"]}
    assert list(got) == [a["reference"]], "[L4.9] the booking outside the closure interval is fixed, not considered"
    assert got[a["reference"]]["table_ids"] in (["t_3"], ["t_4"]) and got[a["reference"]]["table_ids"] != ["t_2"], \
        f"[L4.10] the plan must avoid the fixed booking on t_2 (overlaps A's [18:30,20:00)): {j}"
    assert got[a["reference"]]["table_ids"] == ["t_3"]
    apply_ok(w.ada, "r_anker", j["plan_id"])
    # a second closure: t_3 closed [18:00,22:00); A (now on t_3) must go elsewhere but not t_1 (closed earlier, overlapping A) nor t_2
    j2 = pv(w, "t_3", "18:00", "22:00")
    got2 = {x["reference"]: x for x in j2["assignments"]}
    assert got2[a["reference"]]["table_ids"] == ["t_4"], f"[L4.10] previously applied closures constrain later plans: {j2}"
    assert got2[fixed["reference"]]["table_ids"] == ["t_2"] and not got2[fixed["reference"]]["changed"], "[L4.9] the second closure also overlaps the former fixed booking, which is considered and stays"


def test_L4_11_diners_cutoffs_do_not_block_repairs_and_booking_fields_are_preserved():
    w = rworld()
    a = bk(w.bob, w, "19:00", ["t_2"], 2)                              # in the past, so far inside its cancellation cutoff
    check(w.bob.post(f"/reservations/{a['reference']}/cancel"), 409, "L4.11", "cutoff_passed")
    j = pv(w, "t_2", "18:00", "23:00")
    assert j["moved_count"] == 1
    out = apply_ok(w.ada, "r_anker", j["plan_id"])
    r = out["reservations"][0]
    for k in ("reference", "reservation_id", "party_size", "starts_at_local", "starts_at", "ends_at", "created_at", "status", "accepted_terms", "restaurant_id"):
        assert r[k] == a[k], f"[L4.11] a repair keeps {k}"
    assert r["table_ids"] != ["t_2"] and r["revision"] == 2


def test_L4_12_preview_is_side_effect_free():
    w = rworld()
    bk(w.ada, w, "19:00", ["t_2"], 2)
    bk(w.bob, w, "19:00", ["t_3", "t_4"], 7)
    pre = world_state(w)
    av = lambda: [call("GET", f"/availability?restaurant_id=r_anker&date={w.d}&party_size={p}&explain=true").json for p in (1, 3, 6)]
    a0, r0 = av(), rev(w.ada)
    for tb in ("t_2", "t_3", "t_1"):
        pv(w, tb, "18:00", "23:00")
    assert world_state(w) == pre and av() == a0, "[L4.12] preview stores only a plan: no closure, occupancy, reservation revision or history changes"
    assert rev(w.ada) == r0, "[L4.12] previews do not increment the restaurant revision"
    # and a preview does not stop a diner booking the 'closed' table
    r = w.cy.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": local(w.d, "19:00"), "party_size": 2}, key=new_key())
    assert r.status == 201


def test_L4_13_planning_limits_are_respected_or_refused_with_422_planning_limit():
    caps = (2, 2, 2, 2, 2, 2, 2, 2)
    w = rworld(caps=caps, pairs=[["t_1", "t_2"], ["t_3", "t_4"], ["t_5", "t_6"], ["t_7", "t_8"]])
    for i in range(7):
        bk([w.ada, w.bob, w.cy][i % 3], w, "19:00", [f"t_{i + 1}"], 2)
    t0 = time.time()
    r = replan(w.ada, "r_anker", "t_1", inst(w.d, "18:00"), inst(w.d, "23:00"))
    assert time.time() - t0 < 5, "[L4.13] a plan request must answer within the 5 s per-request timeout"
    assert r.status in (201, 409, 422), f"[L4.13] {r!r}"
    if r.status == 422:
        check(r, 422, "L4.13", "planning_limit")
    # within limits (6 tables, 4 pairs, 6 bookings) it must plan
    w = rworld()
    for i in range(6):
        bk([w.ada, w.bob, w.cy][i % 3], w, "19:00", [f"t_{i + 1}"], 1)
    t0 = time.time()
    r = replan(w.ada, "r_anker", "t_6", inst(w.d, "18:00"), inst(w.d, "23:00"))
    assert time.time() - t0 < 5 and r.status in (201, 409), f"[L4.13] 6 tables, 4 pairs, 6 bookings are within the supported size: {r!r}"
