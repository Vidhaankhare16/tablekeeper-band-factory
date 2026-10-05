"""Amending recurring reservations: POST /series/{id}/amend (ledger L4.50-L4.64)."""
import datetime as dt
import time
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, new_key, local, login, history, add_days, iso,
                      burst, publish_ok, policy, terms, mgr_world, book_ok, avail_ids)
from replan_kit import inst, replan, plan_ok, apply_plan, apply_ok, rev
from test_series import adopt_ok, gs, occ_by_index, night_world


def amend(c, sid, expected_revision=None, from_index=0, local_time="20:00", key=None, raw=None, **extra):
    b = {"expected_revision": 1 if expected_revision is None else expected_revision, "from_index": from_index, "local_time": local_time}
    b.update(extra)
    return c.post(f"/series/{sid}/amend", json=b, key=new_key() if key is None else key)


def swd(count=4, weeks=1, party=4, table="t_2", at="19:00"):
    m = mgr_world()
    anchor = book_ok(m.ada, m.date, at, table, party)
    s = adopt_ok(m.ada, anchor["reference"], count, weeks)
    m.s, m.sid, m.refs = s, s["series_id"], [o["reference"] for o in s["occurrences"]]
    return m


def snap(m):
    return (gs(m.ada, m.sid).json, [history(m.ada, r) for r in m.refs], rev(m.ada))


# ---- access and validation (L4.50-L4.51) ------------------------------------------------------------

def test_L4_50_access_key_and_unknown_series():
    m = swd()
    b = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    check(call("POST", f"/series/{m.sid}/amend", json=b, key=new_key()), 401, "L4.50", "unauthenticated")
    check(call("POST", f"/series/{m.sid}/amend", json=b, key=new_key(), token="junk"), 401, "L4.50", "unauthenticated")
    check(amend(m.bob, m.sid), 404, "L4.50", "not_found")                                    # another owner's series
    check(amend(m.ada, "nope"), 404, "L4.50", "not_found")
    check(call("POST", "/series/nope/amend", json=b, key=new_key()), 401, "L4.50", "unauthenticated")
    check(m.ada.post(f"/series/{m.sid}/amend", json=b), 400, "L4.50", "missing_idempotency_key")
    check(m.ada.post(f"/series/{m.sid}/amend", json=b, key=""), 400, "L4.50", "missing_idempotency_key")
    check(m.ada.post(f"/series/{m.sid}/amend", json=b, key="k" * 256), 422, "L4.50", "validation_failed")
    check(m.ada.post(f"/series/{m.sid}/amend", raw="{bad", key=new_key()), 400, "L4.50", "malformed_request")
    check(m.ada.post(f"/series/{m.sid}/amend", raw="[1]", key=new_key()), 400, "L4.50", "malformed_request")
    check(amend(m.ada, m.sid, junk=[1], other=None), 201, "L4.50")                           # unknown fields ignored


@pytest.mark.parametrize("name,patch,strict", [
    ("revision 0", {"expected_revision": 0}, True), ("revision -1", {"expected_revision": -1}, True), ("revision true", {"expected_revision": True}, True),
    ("revision false", {"expected_revision": False}, True), ("revision float", {"expected_revision": 1.5}, True),
    ("revision string", {"expected_revision": "1"}, False), ("revision list", {"expected_revision": [1]}, False),
    ("revision missing", {"_del": "expected_revision"}, True),
    ("index -1", {"from_index": -1}, True), ("index == count", {"from_index": 4}, True), ("index 99", {"from_index": 99}, True),
    ("index true", {"from_index": True}, True), ("index float", {"from_index": 1.5}, True), ("index string", {"from_index": "1"}, False),
    ("index missing", {"_del": "from_index"}, True),
    ("time 24:00", {"local_time": "24:00"}, True), ("time 8:00", {"local_time": "8:00"}, True), ("time seconds", {"local_time": "20:00:00"}, True),
    ("time 20:60", {"local_time": "20:60"}, True), ("time empty", {"local_time": ""}, True), ("time words", {"local_time": "evening"}, True),
    ("time offset", {"local_time": "20:00+01:00"}, True), ("time 7pm", {"local_time": "7pm"}, True), ("time number", {"local_time": 2000}, False),
    ("time missing", {"_del": "local_time"}, True),
])
def test_L4_51_invalid_input_is_422(name, patch, strict):
    m = swd()
    b = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    patch = dict(patch)
    d = patch.pop("_del", None)
    b.update(patch)
    if d:
        b.pop(d)
    r = m.ada.post(f"/series/{m.sid}/amend", json=b, key=new_key())
    ok = (422,) if strict else (400, 422)
    assert r.status in ok, f"[L4.51] {name}: expected {ok}, got {r!r}"        # READING Q2: wrong JSON types may be 400 malformed_request
    assert r.json["error"]["code"] in ("validation_failed", "malformed_request")
    assert snap(m)[0]["revision"] == 1 and all(o["reservation"]["revision"] == 1 for o in gs(m.ada, m.sid).json["occurrences"]), "[L4.51] nothing changed"


def test_L4_51_boundary_times_and_indices_are_valid():
    m = swd(count=3)
    check(amend(m.ada, m.sid, 1, 2, "19:00"), 201, "L4.51")                  # last valid index, a no-op time
    ok = night_world()
    anchor = book_ok(ok[0], "2028-05-01", "12:00", "t_1", 2)
    s = adopt_ok(ok[0], anchor["reference"], 2, 1)
    check(amend(ok[0], s["series_id"], 1, 0, "00:00"), 201, "L4.51")
    check(amend(ok[0], s["series_id"], 2, 0, "22:00"), 201, "L4.51")


def test_L4_51_stale_revision_before_any_occurrence_validation_but_after_input_validation():
    m = swd()
    s0 = snap(m)
    check(amend(m.ada, m.sid, 2, 0, "19:15"), 409, "L4.51", "stale_revision")           # would be not_on_slot_grid for every occurrence
    check(amend(m.ada, m.sid, 9, 0, "23:30"), 409, "L4.51", "stale_revision")           # would be outside_opening_hours
    check(amend(m.ada, m.sid, 2, 1, "20:00"), 409, "L4.51", "stale_revision")
    check(amend(m.ada, m.sid, 1, 0, "19:15"), 422, "L4.51", "not_on_slot_grid")
    check(amend(m.ada, m.sid, 2, 0, "25:00"), 422, "L4.51", "validation_failed")        # READING A1: input validation precedes the revision comparison
    assert snap(m) == s0, "[L4.51] refusals change nothing"


# ---- success (L4.52-L4.54) ---------------------------------------------------------------------------------

def test_L4_52_eligible_set_exceptions_and_cancelled_are_skipped():
    m = swd(count=5)
    m.ada.patch(f"/reservations/{m.refs[2]}", json={"party_size": 3})                       # exception
    m.ada.post(f"/reservations/{m.refs[3]}/cancel")                                         # cancelled
    g0 = gs(m.ada, m.sid).json
    assert g0["revision"] == 3
    h0 = {r: history(m.ada, r) for r in m.refs}
    cur0 = {o["index"]: o["reservation"] for o in g0["occurrences"]}
    r0 = rev(m.ada)
    out = check(amend(m.ada, m.sid, 3, 1, "20:30"), 201, "L4.52")
    assert out == gs(m.ada, m.sid).json, "[L4.52] returns the current series response"
    oc = occ_by_index(out)
    assert out["revision"] == 4 and out["interval_weeks"] == 1, "[L4.52] the series revision increases once for the entire operation"
    for i in (1, 4):
        r = oc[i]["reservation"]
        assert r["starts_at_local"] == f"{add_days(m.date, 7 * i)}T20:30", f"[L4.52] occurrence {i} keeps its scheduled date and takes the new clock time: {r['starts_at_local']}"
        assert r["revision"] == cur0[i]["revision"] + 1 and r["reference"] == cur0[i]["reference"] and r["party_size"] == cur0[i]["party_size"] \
            and r["table_ids"] == cur0[i]["table_ids"] and r["reservation_id"] == cur0[i]["reservation_id"] and r["created_at"] == cur0[i]["created_at"]
        assert (iso(r["ends_at"]) - iso(r["starts_at"])).total_seconds() == 5400
        h = history(m.ada, m.refs[i])
        assert len(h) == len(h0[m.refs[i]]) + 1 and h[-1]["event"] == "changed" and h[-1]["revision"] == r["revision"] \
            and h[-1]["changes"] == [{"field": "starts_at_local", "from": cur0[i]["starts_at_local"], "to": r["starts_at_local"]}], f"[L4.52] one ordinary changed entry: {h[-1]}"
    for i in (0, 2, 3):
        assert oc[i]["reservation"] == cur0[i] and history(m.ada, m.refs[i]) == h0[m.refs[i]], f"[L4.52] occurrence {i} (before from_index / exception / cancelled) is untouched"
    assert [o["exception"] for o in out["occurrences"]] == [False, False, True, False, False], "[L4.52/L4.61] series amendments do not mark exceptions; existing flags stay"
    assert rev(m.ada) == r0 + 1, "[L4.52] the restaurant revision increases once for the entire operation"


def test_L4_53_noops_retain_terms_and_nothing_is_counted():
    m = swd(count=3)
    s0 = snap(m)
    out = check(amend(m.ada, m.sid, 1, 0, "19:00"), 201, "L4.53")            # every eligible occurrence already starts at 19:00
    assert out == s0[0] and snap(m) == s0, "[L4.53] all-no-op: success without changing any revision, history or counter"
    # empty eligible set: the only eligible occurrence is cancelled
    m.ada.post(f"/reservations/{m.refs[2]}/cancel")
    s1 = snap(m)
    out = check(amend(m.ada, m.sid, s1[0]["revision"], 2, "21:00"), 201, "L4.53")
    assert out == s1[0] and snap(m) == s1, "[L4.53] empty eligible set succeeds without changing revisions"
    # mixed: one occurrence already at the target time
    out = check(amend(m.ada, m.sid, s1[0]["revision"], 0, "20:00"), 201, "L4.53")
    s2 = snap(m)
    assert s2[0]["revision"] == s1[0]["revision"] + 1
    out = check(amend(m.ada, m.sid, s2[0]["revision"], 0, "20:00"), 201, "L4.53")
    assert snap(m) == s2, "[L4.53] repeating the same amendment is a no-op"
    m.ada.patch(f"/reservations/{m.refs[1]}", json={"starts_at_local": f"{add_days(m.date, 7)}T20:00"})        # a no-op PATCH is not an exception
    assert gs(m.ada, m.sid).json["revision"] == s2[0]["revision"]


def test_L4_54_each_real_change_adopts_the_policy_of_its_resulting_date():
    m = swd(count=4)
    d2 = add_days(m.date, 14)
    p = policy(d2, reservation_duration_minutes=60, cancellation_cutoff_minutes=15)
    publish_ok(m.ada, "r_anker", p)
    old = [o["reservation"] for o in gs(m.ada, m.sid).json["occurrences"]]
    out = check(amend(m.ada, m.sid, 1, 0, "20:00"), 201, "L4.54")
    oc = occ_by_index(out)
    for i in (0, 1):
        assert oc[i]["reservation"]["accepted_terms"] == old[i]["accepted_terms"] and (iso(oc[i]["reservation"]["ends_at"]) - iso(oc[i]["reservation"]["starts_at"])).total_seconds() == 5400
    for i in (2, 3):
        r = oc[i]["reservation"]
        assert r["accepted_terms"] == terms(p, 1) and (iso(r["ends_at"]) - iso(r["starts_at"])).total_seconds() == 3600 and r["revision"] == 2, \
            f"[L4.54] occurrences {i} adopt the policy for their resulting start date (terms and end time replaced, revision +1 once): {r}"
        assert history(m.ada, m.refs[i])[-1]["accepted_terms"] == terms(p, 1)
    assert oc[0]["reservation"]["revision"] == 2


def test_L4_54_policy_of_the_resulting_date_can_refuse_the_new_time():
    m = swd(count=4)
    publish_ok(m.ada, "r_anker", policy(add_days(m.date, 21), opening_hours=all_week("18:00", "20:00")))           # occurrence 3 must end by 20:00
    s0 = snap(m)
    check(amend(m.ada, m.sid, 1, 0, "20:00"), 422, "L4.54", "outside_opening_hours")
    assert snap(m) == s0, "[L4.54/L4.55] a refused amendment changes no history, revision or counter"
    m2 = swd(count=4)
    publish_ok(m2.ada, "r_anker", policy(add_days(m2.date, 14), slot_minutes=45))                              # grid 18:00, 18:45, 19:30, 20:15 from occurrence 2 on
    s0 = snap(m2)
    check(amend(m2.ada, m2.sid, 1, 0, "20:00"), 422, "L4.54", "not_on_slot_grid")                              # 20:00 is on the 30-minute grid only
    assert snap(m2) == s0
    check(amend(m2.ada, m2.sid, 1, 0, "19:30"), 201, "L4.54")


# ---- failures and precedence (L4.55) ---------------------------------------------------------------------------

def test_L4_55_occupancy_conflicts_are_409_and_atomic():
    m = swd(count=4)
    book_ok(m.bob, add_days(m.date, 14), "20:30", "t_2", 2)                    # overlaps occurrence 2's new slot [20:00,21:30) but not its current [19:00,20:30)
    s0 = snap(m)
    check(amend(m.ada, m.sid, 1, 0, "20:00"), 409, "L4.55", "table_unavailable")
    assert snap(m) == s0, "[L4.55] on failure histories and all revisions remain unchanged"
    key = new_key()
    check(amend(m.ada, m.sid, 1, 0, "20:00", key=key), 409, "L4.55", "table_unavailable")
    check(amend(m.ada, m.sid, 1, 3, "20:00", key=key), 201, "L4.55")            # the failed key is reusable (first use) with another body


def test_L4_55_conflict_with_unchanged_occurrences_and_closures():
    m = swd(count=3)
    # exception occurrence 2 is moved onto occurrence 1's day at 20:00 (same table): unchanged by the amendment, but it blocks occurrence 1's new time
    d1 = add_days(m.date, 7)
    check(m.ada.patch(f"/reservations/{m.refs[2]}", json={"starts_at_local": f"{d1}T20:30"}), 200, "L4.55")
    s0 = snap(m)
    check(amend(m.ada, m.sid, s0[0]["revision"], 0, "20:00"), 409, "L4.55", "table_unavailable")
    assert snap(m) == s0
    m2 = swd(count=3)
    for_day = add_days(m2.date, 14)
    pl = plan_ok(m2.ada, "r_anker", "t_2", inst(for_day, "20:00"), inst(for_day, "21:00"))
    # the closure is on a table with bookings overlapping it: occurrence 2 (19:00-20:30) is considered and moved
    apply_ok(m2.ada, "r_anker", pl["plan_id"])
    moved = gs(m2.ada, m2.sid).json
    tabs2 = occ_by_index(moved)[2]["reservation"]["table_ids"]
    assert tabs2 != ["t_2"]
    s1 = snap(m2)
    pl2 = plan_ok(m2.ada, "r_anker", "t_2", inst(add_days(m2.date, 7), "20:15"), inst(add_days(m2.date, 7), "22:30"))
    apply_ok(m2.ada, "r_anker", pl2["plan_id"])
    g = gs(m2.ada, m2.sid).json
    check(amend(m2.ada, m2.sid, g["revision"], 0, "21:00"), 201, "L4.55")      # moved occurrences keep a free table: amendment succeeds
    # a closure that does not touch the current booking but covers the new time blocks the amendment (table_unavailable, atomic)
    m3 = swd(count=3)
    day = add_days(m3.date, 7)
    apply_ok(m3.ada, "r_anker", plan_ok(m3.ada, "r_anker", "t_2", inst(day, "21:00"), inst(day, "23:00"))["plan_id"])
    assert occ_by_index(gs(m3.ada, m3.sid).json)[1]["reservation"]["table_ids"] == ["t_2"], "setup: the booking ends at 20:30 and is not considered"
    s3 = snap(m3)
    check(amend(m3.ada, m3.sid, s3[0]["revision"], 0, "21:30"), 409, "L4.55", "table_unavailable")
    assert snap(m3) == s3


def test_L4_55_non_occupancy_errors_take_precedence_in_occurrence_index_order():
    m = swd(count=4)
    d = lambda i: add_days(m.date, 7 * i)
    book_ok(m.bob, d(1), "20:30", "t_2", 2)                                          # occurrence 1: occupancy conflict with the new time
    publish_ok(m.ada, "r_anker", policy(d(2), opening_hours=all_week("18:00", "20:00")))        # occurrences 2 and 3: outside opening hours
    s0 = snap(m)
    check(amend(m.ada, m.sid, 1, 0, "20:00"), 422, "L4.55", "outside_opening_hours")           # not table_unavailable
    publish_ok(m.ada, "r_anker", policy(d(1), slot_minutes=45, opening_hours=all_week("18:00", "23:00")))   # occurrence 1: off-grid (19:30 -> 18:00,18:45,19:30 is ON grid; use 20:00)
    s0 = snap(m)
    r = amend(m.ada, m.sid, s0[0]["revision"], 0, "20:00")
    check(r, 422, "L4.55", "not_on_slot_grid")                                                 # occurrence 1 comes before occurrence 2 in index order
    assert snap(m) == s0


def test_L4_56_nonexistent_and_repeated_local_times_follow_dst():
    a, b = night_world("Europe/Berlin")
    anchor = book_ok(a, "2028-03-19", "20:00", "t_1", 2)
    s = adopt_ok(a, anchor["reference"], 3, 1)                                      # 03-19, 03-26 (spring forward), 04-02
    sid = s["series_id"]
    s0 = (gs(a, sid).json, [history(a, o["reference"]) for o in s["occurrences"]])
    check(amend(a, sid, 1, 0, "02:30"), 422, "L4.56", "invalid_local_time")
    assert (gs(a, sid).json, [history(a, o["reference"]) for o in s["occurrences"]]) == s0, "[L4.56] all-or-nothing"
    check(amend(a, sid, 1, 2, "02:30"), 201, "L4.56")
    a, b = night_world("Europe/Berlin")
    anchor = book_ok(a, "2028-10-22", "20:00", "t_1", 2)
    s = adopt_ok(a, anchor["reference"], 2, 1)                                      # 10-22, 10-29 (fall back)
    out = check(amend(a, s["series_id"], 1, 0, "02:30"), 201, "L4.56")
    r = occ_by_index(out)[1]["reservation"]
    assert r["starts_at"] == "2028-10-29T02:30:00+02:00" and r["ends_at"] == "2028-10-29T03:00:00+01:00", f"[L4.56] repeated time = first occurrence, duration absolute: {r}"


# ---- replay and counters (L4.57-L4.59) -----------------------------------------------------------------------

def test_L4_57_replay_returns_the_original_even_after_further_edits_and_changes_no_counter():
    m = swd(count=4)
    key = new_key()
    b = {"expected_revision": 1, "from_index": 1, "local_time": "20:00"}
    first = check(m.ada.post(f"/series/{m.sid}/amend", json=b, key=key), 201, "L4.57")
    m.ada.patch(f"/reservations/{m.refs[1]}", json={"party_size": 3})
    m.ada.post(f"/reservations/{m.refs[2]}/cancel")
    check(amend(m.ada, m.sid, 4, 3, "21:00"), 201, "L4.57")
    cur = snap(m)
    for _ in range(2):
        assert check(m.ada.post(f"/series/{m.sid}/amend", json=b, key=key), 200, "L4.57") == first, "[L4.57] replay returns the original response with 200"
    assert snap(m) == cur, "[L4.57] a replay changes no counter, history or revision"
    check(m.ada.post(f"/series/{m.sid}/amend", json={**b, "local_time": "21:30"}, key=key), 409, "L4.57", "idempotency_key_reuse")
    check(m.ada.post(f"/series/{m.sid}/amend", json={"junk": 1}, key=key), 409, "L4.57", "idempotency_key_reuse")
    raw = '{"local_time":"20:00",  "from_index":1, "expected_revision": 1}'
    assert check(m.ada.post(f"/series/{m.sid}/amend", raw=raw, key=key), 200, "L4.57") == first
    check(m.bob.post(f"/series/{m.sid}/amend", json=b, key=key), 404, "L4.57", "not_found")


def test_L4_58_amending_does_not_mark_exceptions_and_individual_edits_after_do():
    m = swd(count=3)
    check(amend(m.ada, m.sid, 1, 0, "20:00"), 201, "L4.58")
    g = gs(m.ada, m.sid).json
    assert [o["exception"] for o in g["occurrences"]] == [False, False, False]
    m.ada.patch(f"/reservations/{m.refs[1]}", json={"party_size": 3})
    g = gs(m.ada, m.sid).json
    assert [o["exception"] for o in g["occurrences"]] == [False, True, False] and g["revision"] == 3
    out = check(amend(m.ada, m.sid, 3, 0, "20:30"), 201, "L4.58")
    assert occ_by_index(out)[1]["reservation"]["starts_at_local"].endswith("T20:00"), "[L4.52] an exception occurrence is skipped even by later amendments"
    assert occ_by_index(out)[0]["reservation"]["starts_at_local"].endswith("T20:30") and occ_by_index(out)[2]["reservation"]["starts_at_local"].endswith("T20:30")


def test_L4_59_series_amendment_with_a_combination_selection_and_party_sizes():
    m = mgr_world()
    anchor = m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": local(m.date, "19:00"), "party_size": 6}, key=new_key()).json
    s = adopt_ok(m.ada, anchor["reference"], 3, 2)
    out = check(amend(m.ada, s["series_id"], 1, 0, "20:30"), 201, "L4.59")
    for o in out["occurrences"]:
        r = o["reservation"]
        assert sorted(r["table_ids"]) == ["t_1", "t_2"] and "table_id" not in r and r["party_size"] == 6 and r["starts_at_local"].endswith("T20:30")
        e = history(m.ada, o["reference"])[-1]
        assert e["event"] == "changed" and e["changes"][0]["field"] == "starts_at_local", "[L4.59/L3.81] a time-only change names only starts_at_local"
    assert [o["reservation"]["starts_at_local"][:10] for o in out["occurrences"]] == [add_days(m.date, 14 * i) for i in range(3)]


# ---- concurrency (L4.60) ----------------------------------------------------------------------------------------

def test_L4_60_concurrent_amendments_from_one_revision_at_most_one_real_change():
    m = swd(count=4)
    times = ["18:30", "19:30", "20:00", "20:30", "21:00", "21:30", "18:00", "21:15"]
    out = burst(24, lambda i: amend(m.ada, m.sid, 1, 0, times[i % 6]))
    codes = [r.status for r in out]
    assert codes.count(409) >= 18 and codes.count(201) >= 1, f"[L4.60] {sorted(set(codes))}"
    winners = [r for r in out if r.status == 201]
    assert len(winners) <= 6 and len(winners) >= 1
    g = gs(m.ada, m.sid).json
    assert g["revision"] == 2, f"[L4.60] the series revision increased exactly once: {g['revision']}"
    stamps = {o["reservation"]["starts_at_local"][-5:] for o in g["occurrences"]}
    assert len(stamps) == 1, f"[L4.60] all occurrences share the single winning clock time: {stamps}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L4.60", "stale_revision")
    assert all(len(history(m.ada, ref)) == 2 for ref in m.refs)


def test_L4_60_identical_requests_with_one_key_apply_once():
    m = swd(count=4)
    key = new_key()
    out = burst(20, lambda i: amend(m.ada, m.sid, 1, 0, "20:00", key=key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 19 + [201], f"[L4.60/L1.46] {codes}"
    assert all(r.json == out[0].json for r in out)
    assert gs(m.ada, m.sid).json["revision"] == 2 and all(len(history(m.ada, r)) == 2 for r in m.refs)


def test_L4_60_amendment_races_with_individual_edits_and_bookings():
    m = swd(count=4)

    def op(i):
        if i % 4 == 0:
            return amend(m.ada, m.sid, 1, 0, "20:00")
        if i % 4 == 1:
            return m.ada.patch(f"/reservations/{m.refs[1 + i % 3]}", json={"party_size": 1 + i % 4})
        if i % 4 == 2:
            return m.bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": local(add_days(m.date, 7 * (i % 4)), "20:00"), "party_size": 2}, key=new_key())
        return m.ada.post(f"/reservations/{m.refs[3]}/cancel") if i % 8 == 3 else amend(m.ada, m.sid, 2, 0, "21:00")
    out = burst(32, op)
    assert all(r.status in (200, 201, 409, 422) for r in out), sorted({r.status for r in out})
    g = gs(m.ada, m.sid).json
    seen = {}
    for cl in (m.ada, m.bob):
        for r in cl.get("/reservations").json["reservations"]:
            if r["status"] == "confirmed":
                for t in r["table_ids"]:
                    for o in seen.get(t, []):
                        assert not (iso(o["starts_at"]) < iso(r["ends_at"]) and iso(r["starts_at"]) < iso(o["ends_at"])), f"[L4.60/L1.1] overlap on {t}"
                    seen.setdefault(t, []).append(r)
    for o in g["occurrences"]:
        h = history(m.ada, o["reference"])
        assert o["reservation"]["revision"] == len(h), "[L4.60] revision == recorded history entries under concurrency"


# ---- the cutoff of the old accepted terms (slow: waits for a cutoff to pass) ---------------------------------------------

def test_L4_61_old_accepted_cutoff_is_checked_first_in_index_order():
    reset(fixture(restaurants=[restaurant("r_utc", timezone="UTC", slot=1, dur=30, cutoff=10080, hours=all_week("00:00", "23:59"))]))
    a = login("ada@example.com")
    now = dt.datetime.now(dt.timezone.utc)
    start = (now + dt.timedelta(days=7, minutes=3)).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    d0, t0 = start.strftime("%Y-%m-%d"), start.strftime("%H:%M")
    anchor = book_ok(a, d0, t0, "t_1", 2, "r_utc")
    s = adopt_ok(a, anchor["reference"], 3, 1)                                         # occurrence 0 is just outside its 7-day cutoff
    sid = s["series_id"]
    refs = [o["reference"] for o in s["occurrences"]]
    # while still outside the cutoff everything works and occurrence 1.. are far away
    wait = (start - dt.timedelta(days=7) - dt.datetime.now(dt.timezone.utc)).total_seconds() + 2
    assert 0 < wait < 400, f"setup: waiting {wait:.0f}s for the cutoff of occurrence 0 to pass"
    time.sleep(wait)
    s0 = (gs(a, sid).json, [history(a, r) for r in refs])
    check(amend(a, sid, 1, 0, "10:00"), 409, "L4.61", "cutoff_passed")             # occurrence 0 is now inside its accepted cutoff
    check(amend(a, sid, 1, 0, "23:45"), 409, "L4.61", "cutoff_passed")             # cutoff (index 0) precedes occurrence 1's outside_opening_hours
    check(amend(a, sid, 2, 0, "10:00"), 409, "L4.61", "stale_revision")            # stale before any occurrence's cutoff
    check(amend(a, sid, 1, 1, "23:45"), 422, "L4.61", "outside_opening_hours")
    assert (gs(a, sid).json, [history(a, r) for r in refs]) == s0, "[L4.61] failures change nothing"
    out = check(amend(a, sid, 1, 1, "10:00"), 201, "L4.61")                         # later occurrences are still editable
    assert occ_by_index(out)[0]["reservation"]["starts_at_local"].endswith(t0) and occ_by_index(out)[1]["reservation"]["starts_at_local"].endswith("T10:00")
    check(a.post(f"/reservations/{refs[0]}/cancel"), 409, "L4.61", "cutoff_passed")
