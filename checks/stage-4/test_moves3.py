"""Collective moves under policies and agreements (ledger L3.70-L3.79)."""
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login,
                      slots, publish_ok, policy, terms, history, mgr_world, add_days, iso, burst, body, avail_ids)
from test_series import adopt_ok, gs, occ_by_index, mins


def mv(c, moves, key=None):
    return c.post("/reservation-moves", json={"moves": moves}, key=new_key() if key is None else key)


def snap(c, *refs):
    return [(c.get(f"/reservations/{r}").json, history(c, r), c.get(f"/reservations/{r}/decision").json) for r in refs]


def test_L3_70_real_change_adopts_policy_one_revision_one_history_entry():
    m = mgr_world()
    d = m.date
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    b = book_ok(m.ada, d, "19:00", "t_2", 4)
    c = book_ok(m.ada, d, "19:00", "t_3", 6)
    p1 = policy(d, reservation_duration_minutes=120, cancellation_cutoff_minutes=45)
    publish_ok(m.ada, "r_anker", p1)
    r = mv(m.ada, [{"reference": a["reference"], "starts_at_local": local(d, "20:00"), "table_id": "t_1"},
                   {"reference": b["reference"]},                                                      # no-op
                   {"reference": c["reference"], "party_size": 5, "table_id": "t_3"}])
    j = check(r, 201, "L3.70")["reservations"]
    assert [x["reference"] for x in j] == [a["reference"], b["reference"], c["reference"]], "[L3.70] input order including unchanged items"
    assert j[0]["revision"] == 2 and j[0]["accepted_terms"] == terms(p1, 1) and mins(j[0]) == 120 and j[0]["starts_at_local"] == local(d, "20:00"), f"[L3.70] {j[0]}"
    assert j[1] == b and j[1]["revision"] == 1 and j[1]["accepted_terms"]["policy_version"] == 0 and mins(j[1]) == 90, "[L3.70] a no-op retains its terms, end time, revision"
    assert j[2]["revision"] == 2 and j[2]["accepted_terms"]["policy_version"] == 1 and j[2]["party_size"] == 5
    ha, hb, hc = (history(m.ada, x["reference"]) for x in (a, b, c))
    assert [e["event"] for e in ha] == ["created", "changed"] and ha[1]["changes"] == [{"field": "starts_at_local", "from": local(d, "19:00"), "to": local(d, "20:00")}] \
        and ha[1]["revision"] == 2 and ha[1]["accepted_terms"] == terms(p1, 1), f"[L3.70] {ha}"
    assert len(hb) == 1, "[L3.70] a no-op records no history"
    assert hc[1]["changes"] == [{"field": "party_size", "from": 6, "to": 5}] and hc[1]["revision"] == 2
    for x in j:
        assert m.ada.get(f"/reservations/{x['reference']}").json == x


def test_L3_71_old_accepted_cutoff_first_then_resulting_policy_validation():
    m = mgr_world()
    d = m.date
    old = book_ok(m.ada, "2020-01-08", "19:00", "t_2", 4)
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    s0 = snap(m.ada, old["reference"], a["reference"])
    check(mv(m.ada, [{"reference": old["reference"], "table_id": "t_3"}]), 409, "L3.71", "cutoff_passed")
    check(mv(m.ada, [{"reference": a["reference"], "table_id": "t_3", "party_size": 3}, {"reference": old["reference"], "table_id": "t_3"}]), 409, "L3.71", "cutoff_passed")
    check(mv(m.ada, [{"reference": old["reference"], "party_size": 99, "starts_at_local": local(d, "19:15")}]), 409, "L3.71", "cutoff_passed")  # cutoff precedes other changes
    assert snap(m.ada, old["reference"], a["reference"]) == s0
    # resulting fields are validated against the policy of the resulting date: shrink capacities, then try a time-only move
    publish_ok(m.ada, "r_anker", policy(d, capacities={"t_1": 1, "t_2": 4, "t_3": 6}))
    check(mv(m.ada, [{"reference": a["reference"], "starts_at_local": local(d, "20:00")}]), 422, "L3.71", "party_exceeds_capacity")
    assert snap(m.ada, old["reference"], a["reference"]) == s0


def test_L3_72_expected_revision_per_move_and_error_order():
    m = mgr_world()
    d = m.date
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    b = book_ok(m.ada, d, "19:00", "t_2", 4)
    s0 = snap(m.ada, a["reference"], b["reference"])
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 1, "expected_revision": 5}]), 409, "L3.72", "stale_revision")
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 1, "expected_revision": 1}, {"reference": b["reference"], "party_size": 3, "expected_revision": 2}]),
          409, "L3.72", "stale_revision")
    for bad in (0, -1, "1", True, 1.5, [1]):
        check(mv(m.ada, [{"reference": a["reference"], "party_size": 1, "expected_revision": bad}]), 422, "L3.72", "validation_failed")
    # input order decides: item 1 invalid (422) precedes item 2 stale (409), and vice versa
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 9}, {"reference": b["reference"], "party_size": 3, "expected_revision": 9}]),
          422, "L3.72", "party_exceeds_capacity")
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 1, "expected_revision": 9}, {"reference": b["reference"], "party_size": 99}]),
          409, "L3.72", "stale_revision")
    assert snap(m.ada, a["reference"], b["reference"]) == s0, "[L3.72] failures change nothing"
    j = check(mv(m.ada, [{"reference": a["reference"], "party_size": 1, "expected_revision": 1}, {"reference": b["reference"], "expected_revision": 1}]), 201, "L3.72")["reservations"]
    assert j[0]["revision"] == 2 and j[1]["revision"] == 1, "[L3.72] a no-op with the right expected_revision is fine"
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 2, "expected_revision": 1}]), 409, "L3.72", "stale_revision")


def test_L3_73_noop_only_batch_changes_nothing():
    m = mgr_world()
    d = m.date
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    b = book_ok(m.ada, d, "19:00", "t_2", 4)
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=30))
    s0 = snap(m.ada, a["reference"], b["reference"])
    j = check(mv(m.ada, [{"reference": a["reference"], "table_id": "t_1"}, {"reference": b["reference"], "party_size": 4, "starts_at_local": local(d, "19:00")}]),
              201, "L3.73")["reservations"]
    assert j == [a, b] and snap(m.ada, a["reference"], b["reference"]) == s0, "[L3.73] no-op moves retain all existing values, terms, revision, history"


def series3(m):
    anchor = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    return adopt_ok(m.ada, anchor["reference"], 4, 1)


def test_L3_74_series_revision_once_per_affected_series_and_exceptions():
    m = mgr_world()
    s = series3(m)
    other_anchor = book_ok(m.ada, add_days(m.date, 1), "19:00", "t_3", 6)
    s2 = adopt_ok(m.ada, other_anchor["reference"], 3, 1)
    solo = book_ok(m.ada, add_days(m.date, 2), "19:00", "t_1", 2)
    o1, o2 = s["occurrences"][1]["reference"], s["occurrences"][2]["reference"]
    p1 = s2["occurrences"][1]["reference"]
    r = mv(m.ada, [{"reference": o1, "party_size": 3}, {"reference": o2, "party_size": 2}, {"reference": s["occurrences"][3]["reference"]},        # 2 real + 1 no-op in series 1
                   {"reference": p1, "party_size": 5}, {"reference": solo["reference"], "party_size": 1}])                                          # 1 real in series 2, one non-series
    check(r, 201, "L3.74")
    g1, g2 = gs(m.ada, s["series_id"]).json, gs(m.ada, s2["series_id"]).json
    assert g1["revision"] == 2, f"[L3.74] each affected series revision increases once for the whole batch (two changed occurrences): {g1['revision']}"
    assert [o["exception"] for o in g1["occurrences"]] == [False, True, True, False], "[L3.74] each changed occurrence becomes a permanent exception; the no-op does not"
    assert g2["revision"] == 2 and [o["exception"] for o in g2["occurrences"]] == [False, True, False]
    assert occ_by_index(g1)[1]["reservation"]["revision"] == 2 and occ_by_index(g1)[3]["reservation"]["revision"] == 1
    # a later batch touching the series again bumps it once more
    check(mv(m.ada, [{"reference": o1, "party_size": 4}, {"reference": o2, "party_size": 4}]), 201, "L3.74")
    assert gs(m.ada, s["series_id"]).json["revision"] == 3


def test_L3_75_failed_batch_and_replay_change_no_revisions_histories_or_flags():
    m = mgr_world()
    s = series3(m)
    refs = [o["reference"] for o in s["occurrences"]]
    block = book_ok(m.bob, add_days(m.date, 14), "19:00", "t_3", 6)
    pre = (gs(m.ada, s["series_id"]).json, snap(m.ada, *refs))
    bad = [{"reference": refs[1], "party_size": 3}, {"reference": refs[2], "table_id": "t_3"}]            # item 2 collides with bob on t_3
    key = new_key()
    check(m.ada.post("/reservation-moves", json={"moves": bad}, key=key), 409, "L3.75", "table_unavailable")
    assert (gs(m.ada, s["series_id"]).json, snap(m.ada, *refs)) == pre, "[L3.75] a failed batch changes no revision, history or exception flag"
    good = {"moves": [{"reference": refs[1], "party_size": 3}, {"reference": refs[3], "party_size": 3}]}
    first = check(m.ada.post("/reservation-moves", json=good, key=key), 201, "L3.75")             # same key, failed before => first use
    cur = (gs(m.ada, s["series_id"]).json, snap(m.ada, *refs))
    assert cur[0]["revision"] == 2
    m.ada.patch(f"/reservations/{refs[1]}", json={"party_size": 1})
    cur = (gs(m.ada, s["series_id"]).json, snap(m.ada, *refs))
    rep = check(m.ada.post("/reservation-moves", json=good, key=key), 200, "L3.75")
    assert rep == first, "[L3.75/L1.110] replays return the original response"
    assert (gs(m.ada, s["series_id"]).json, snap(m.ada, *refs)) == cur, "[L3.75] a replay changes no revisions, histories or exception flags"


def test_L3_76_cancelled_and_unowned_in_a_batch():
    m = mgr_world()
    d = m.date
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    b = book_ok(m.ada, d, "19:00", "t_2", 4)
    t = book_ok(m.bob, d, "19:00", "t_3", 6)
    m.ada.post(f"/reservations/{b['reference']}/cancel")
    s0 = snap(m.ada, a["reference"], b["reference"])
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 1}, {"reference": b["reference"], "party_size": 1}]), 409, "L3.76", "reservation_cancelled")
    check(mv(m.ada, [{"reference": a["reference"], "party_size": 1}, {"reference": t["reference"], "party_size": 1}]), 404, "L3.76", "not_found")
    assert snap(m.ada, a["reference"], b["reference"]) == s0


def test_L3_77_replay_keeps_original_revisions_after_later_amendments():
    m = mgr_world()
    d = m.date
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    key = new_key()
    body_ = {"moves": [{"reference": a["reference"], "party_size": 1}]}
    first = check(m.ada.post("/reservation-moves", json=body_, key=key), 201, "L3.77")
    assert first["reservations"][0]["revision"] == 2
    m.ada.patch(f"/reservations/{a['reference']}", json={"party_size": 2})
    m.ada.post(f"/reservations/{a['reference']}/cancel")
    rep = check(m.ada.post("/reservation-moves", json=body_, key=key), 200, "L3.77")
    assert rep == first and rep["reservations"][0]["revision"] == 2 and rep["reservations"][0]["status"] == "confirmed"


def test_L3_78_policy_change_inside_a_batch_across_dates():
    m = mgr_world()
    d, d2 = m.date, add_days(m.date, 5)
    a = book_ok(m.ada, d, "19:00", "t_1", 2)
    b = book_ok(m.ada, d, "19:00", "t_2", 4)
    p = publish_ok(m.ada, "r_anker", policy(d2, reservation_duration_minutes=45, capacities={"t_1": 2, "t_2": 4, "t_3": 6}))
    j = check(mv(m.ada, [{"reference": a["reference"], "starts_at_local": local(d2, "19:00")}, {"reference": b["reference"], "starts_at_local": local(d2, "19:00")}]),
              201, "L3.78")["reservations"]
    assert all(x["accepted_terms"]["policy_version"] == 1 and mins(x) == 45 and x["revision"] == 2 for x in j), "[L3.78] each moved booking adopts the resulting date's policy"
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_2", "t_3"], "[L3.78] old occupancy released together"


def test_L3_79_batch_of_eight_changes_each_gets_one_entry():
    m = mgr_world()
    refs = [book_ok(m.ada, add_days(m.date, i), "19:00", "t_1", 2)["reference"] for i in range(8)]
    j = check(mv(m.ada, [{"reference": r, "party_size": 1} for r in refs]), 201, "L3.79")["reservations"]
    assert len(j) == 8 and all(x["revision"] == 2 for x in j)
    for r in refs:
        e = history(m.ada, r)
        assert [x["event"] for x in e] == ["created", "changed"] and e[1]["changes"] == [{"field": "party_size", "from": 2, "to": 1}]
