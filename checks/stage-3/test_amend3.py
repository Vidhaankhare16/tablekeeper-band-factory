"""Amendments, cancellation, revisions and expected_revision under policies (ledger L3.40-L3.49)."""
import datetime as dt
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login,
                      slots, publish_ok, policy, terms, history, mgr_world, add_days, iso, burst, body, avail_ids)


def utc_world(cutoff=120):
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in (1, 2, 3)]
    reset(fixture(restaurants=[restaurant("r_utc", timezone="UTC", slot=30, dur=30, cutoff=cutoff, hours=all_week("00:00", "23:30"),
                                          tables=tables, managers=["u_ada"])]))
    return login("ada@example.com"), login("bob@example.com")


def upol(eff, **o):
    p = policy(eff, slot_minutes=30, reservation_duration_minutes=30, opening_hours=all_week("00:00", "23:30"),
               capacities={"t_1": 4, "t_2": 4, "t_3": 4})
    p.update(o)
    return p


def near(days=3):
    return (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=days)).isoformat()


def ub(c, date, at="12:00", table="t_1", party=2):
    return book_ok(c, date, at, table, party, "r_utc")


def mins(j):
    return int((iso(j["ends_at"]) - iso(j["starts_at"])).total_seconds() // 60)


def patch(c, ref, **kw):
    return c.patch(f"/reservations/{ref}", json=kw)


# ---- adoption on real amendment (L3.40) ----------------------------------------------------

def test_L3_40_real_amendment_adopts_new_policy_and_bumps_revision_once():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    assert j["accepted_terms"]["policy_version"] == 0 and mins(j) == 90 and j["revision"] == 1
    p1 = policy(d, reservation_duration_minutes=120, cancellation_cutoff_minutes=30)
    publish_ok(m.ada, "r_anker", p1)
    assert m.ada.get(f"/reservations/{j['reference']}").json == j, "[L3.40] publication changes nothing yet"
    a = check(patch(m.ada, j["reference"], party_size=3), 200, "L3.40")
    assert a["revision"] == 2 and a["accepted_terms"] == terms(p1, 1) and mins(a) == 120, \
        f"[L3.40] a real amendment atomically replaces accepted terms and end time and increments the revision once: {a}"
    assert iso(a["starts_at"]) == iso(j["starts_at"]) and a["reference"] == j["reference"] and a["created_at"] == j["created_at"]
    assert m.ada.get(f"/reservations/{j['reference']}").json == a
    assert m.ada.get(f"/reservations/{j['reference']}/decision").json["revision"] == 2
    e = history(m.ada, j["reference"])
    assert [x["revision"] for x in e] == [1, 2] and e[1]["accepted_terms"] == terms(p1, 1) and e[0]["accepted_terms"] == j["accepted_terms"]
    b = check(patch(m.ada, j["reference"], table_id="t_3"), 200, "L3.40")
    assert b["revision"] == 3 and b["accepted_terms"]["policy_version"] == 1


def test_L3_40_amendment_to_another_date_adopts_that_dates_policy():
    m = mgr_world()
    d, d2 = m.date, add_days(m.date, 6)
    p1 = publish_ok(m.ada, "r_anker", policy(d2, reservation_duration_minutes=45))
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    a = check(patch(m.ada, j["reference"], starts_at_local=local(d2, "19:00")), 200, "L3.40")
    assert a["accepted_terms"]["policy_version"] == 1 and mins(a) == 45 and a["revision"] == 2, "[L3.40] the policy of the *resulting* start date"
    back = check(patch(m.ada, j["reference"], starts_at_local=local(d, "20:00")), 200, "L3.40")
    assert back["accepted_terms"]["policy_version"] == 0 and mins(back) == 90 and back["revision"] == 3, \
        "[L3.40] moving back to a date under policy 0 adopts policy 0 again"
    assert avail_ids(d2, "19:00", 4) == ["t_2", "t_3"], "[L3.40] occupancy released at the old date"


def test_L3_40_all_resulting_fields_are_validated_against_the_new_policy():
    m = mgr_world()
    d = m.date
    wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[dt.date.fromisoformat(d).weekday()]
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    snap = (m.ada.get(f"/reservations/{ref}").json, history(m.ada, ref))
    # capacity: t_2 shrinks to 3, the booking's party (4) is carried into the resulting state, so even a pure time change fails
    publish_ok(m.ada, "r_anker", policy(d, capacities={"t_1": 2, "t_2": 3, "t_3": 6}))
    check(patch(m.ada, ref, starts_at_local=local(d, "20:00")), 422, "L3.40", "party_exceeds_capacity")
    check(patch(m.ada, ref, table_id="t_3"), 200, "L3.40")                       # moving to a table that fits works
    check(patch(m.ada, ref, table_id="t_2", party_size=3), 200, "L3.40")
    # grid: a 45-minute grid makes 19:00 off-grid (18:00, 18:45, 19:30 ...), so even a party change must fail
    d2 = add_days(d, 1)
    k = book_ok(m.ada, d2, "19:00", "t_3", 4)
    publish_ok(m.ada, "r_anker", policy(d2, slot_minutes=45))
    check(patch(m.ada, k["reference"], party_size=2), 422, "L3.40", "not_on_slot_grid")
    check(patch(m.ada, k["reference"], starts_at_local=local(d2, "19:30")), 200, "L3.40")
    # opening hours: the policy closes that weekday
    d3 = add_days(d, 2)
    other = [x for x in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") if x != ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[dt.date.fromisoformat(d3).weekday()]][0]
    z = book_ok(m.ada, d3, "19:30", "t_3", 4)       # 19:30 is on the 18:00+45 grid inherited from the d+1 policy
    publish_ok(m.ada, "r_anker", policy(d3, opening_hours=[{"weekday": other, "opens": "18:00", "closes": "23:00"}]))
    check(patch(m.ada, z["reference"], party_size=3), 422, "L3.40", "outside_opening_hours")
    assert m.ada.get(f"/reservations/{z['reference']}").json == z and len(history(m.ada, z["reference"])) == 1, "[L3.43] failed amendments change nothing"


def test_L3_41_failed_amendments_change_nothing_at_all():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    other = book_ok(m.bob, d, "19:00", "t_3", 6)
    ref = j["reference"]
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=100))
    snap = (m.ada.get(f"/reservations/{ref}").json, history(m.ada, ref), m.ada.get(f"/reservations/{ref}/decision").json,
            call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=1").json)
    for kw, st, code in ((dict(table_id="t_3"), 409, "table_unavailable"), (dict(party_size=9), 422, "party_exceeds_capacity"),
                         (dict(starts_at_local=local(d, "19:15")), 422, "not_on_slot_grid"), (dict(party_size=0), 422, "validation_failed"),
                         (dict(table_id="t_ghost"), 404, "not_found"), (dict(starts_at_local=local(d, "23:00")), 422, "outside_opening_hours"),
                         (dict(table_id="t_3", party_size=2, starts_at_local=local(d, "20:00")), 409, "table_unavailable")):
        check(patch(m.ada, ref, **kw), st, f"L3.41 {kw}", code)
    check(patch(m.bob, ref, party_size=2), 404, "L3.41", "not_found")
    assert (m.ada.get(f"/reservations/{ref}").json, history(m.ada, ref), m.ada.get(f"/reservations/{ref}/decision").json,
            call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=1").json) == snap, \
        "[L3.41] record, history, decision, revision, terms, end time and occupancy are all unchanged by failed amendments"
    assert m.bob.get(f"/reservations/{other['reference']}").json == other


def test_L3_42_noop_amendment_retains_terms_end_time_revision_and_history():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=120, capacities={"t_1": 1, "t_2": 1, "t_3": 1}))
    for kw in ({}, {"party_size": 4}, {"table_id": "t_2", "starts_at_local": local(d, "19:00"), "party_size": 4}):
        r = check(patch(m.ada, ref, **kw), 200, f"L3.42 {kw}")
        assert r == j, f"[L3.42] a no-op retains terms (policy 0 despite the newer policy), end time and revision, and succeeds even though policy 1 would reject it: {r}"
    assert len(history(m.ada, ref)) == 1 and m.ada.get(f"/reservations/{ref}/decision").json["revision"] == 1


def test_L3_42_noop_still_requires_a_confirmed_editable_booking():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    m.ada.post(f"/reservations/{j['reference']}/cancel")
    check(patch(m.ada, j["reference"]), 409, "L3.42", "reservation_cancelled")
    check(patch(m.ada, j["reference"], party_size=4), 409, "L3.42", "reservation_cancelled")
    check(patch(m.bob, j["reference"], party_size=4), 404, "L3.42", "not_found")
    check(patch(m.ada, "NOPE12"), 404, "L3.42", "not_found")
    # READING P2: "editable" includes the cutoff: a no-op on a booking inside its accepted cutoff is refused like any amendment.
    old = book_ok(m.ada, "2020-01-08", "19:00", "t_2", 4)
    check(patch(m.ada, old["reference"]), 409, "L3.42", "cutoff_passed")
    check(patch(m.ada, old["reference"], party_size=4), 409, "L3.42", "cutoff_passed")


# ---- cutoff on accepted terms (L3.43-L3.44) ------------------------------------------------

def test_L3_43_cancel_uses_the_accepted_cutoff_not_the_current_policy():
    a, b = utc_world(cutoff=120)
    d = near(3)
    j = ub(a, d)                                                        # accepted under policy 0: cutoff 120 min
    publish_ok(a, "r_utc", upol("2020-01-01", cancellation_cutoff_minutes=10080))            # v1: 7 days, applies to later bookings
    c = check(a.post(f"/reservations/{j['reference']}/cancel"), 200, "L3.43")
    assert c["status"] == "cancelled" and c["revision"] == 2, "[L3.43] cancel checks the accepted cutoff (120), so 3 days out it is allowed"
    k = ub(a, d, "13:00", "t_2")                                                         # accepted under v1: cutoff 10080 min (7 days)
    assert k["accepted_terms"]["policy_version"] == 1 and k["accepted_terms"]["cancellation_cutoff_minutes"] == 10080
    check(a.post(f"/reservations/{k['reference']}/cancel"), 409, "L3.43", "cutoff_passed")
    publish_ok(a, "r_utc", upol("2020-01-01", cancellation_cutoff_minutes=0))                # v2: cutoff 0 for new bookings
    check(a.post(f"/reservations/{k['reference']}/cancel"), 409, "L3.43", "cutoff_passed")   # still the accepted (v1) cutoff
    check(patch(a, k["reference"], party_size=3), 409, "L3.43", "cutoff_passed")
    check(patch(a, k["reference"], starts_at_local=local(d, "14:00"), party_size=99), 409, "L3.43", "cutoff_passed")  # cutoff before validation
    assert a.get(f"/reservations/{k['reference']}").json == k and len(history(a, k["reference"])) == 1
    z = ub(a, d, "15:00", "t_3")
    assert z["accepted_terms"]["policy_version"] == 2
    check(a.post(f"/reservations/{z['reference']}/cancel"), 200, "L3.43")


def test_L3_43_cutoff_is_measured_against_the_current_start_after_an_amendment():
    a, b = utc_world(cutoff=120)
    d, far = near(3), near(30)
    publish_ok(a, "r_utc", upol("2020-01-01", cancellation_cutoff_minutes=10080))
    k = ub(a, far, "13:00", "t_2")
    m1 = check(patch(a, k["reference"], starts_at_local=local(d, "13:00")), 200, "L3.43")      # old accepted cutoff was fine: 30 days out
    assert m1["revision"] == 2
    check(a.post(f"/reservations/{k['reference']}/cancel"), 409, "L3.43", "cutoff_passed")      # now 3 days out with a 7-day accepted cutoff


def test_L3_44_cancel_increments_revision_once_and_repeats_do_not():
    m = mgr_world()
    j = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    ref = j["reference"]
    c1 = check(m.ada.post(f"/reservations/{ref}/cancel"), 200, "L3.44")
    c2 = check(m.ada.post(f"/reservations/{ref}/cancel"), 200, "L3.44")
    c3 = check(m.ada.post(f"/reservations/{ref}/cancel"), 200, "L3.44")
    assert c1["revision"] == c2["revision"] == c3["revision"] == 2 and c1 == c2 == c3, "[L3.44] cancel increments revision once; repeated cancel does not"
    e = history(m.ada, ref)
    assert [x["event"] for x in e] == ["created", "cancelled"] and e[1]["revision"] == 2
    assert e[1]["accepted_terms"] == j["accepted_terms"]
    check(m.bob.post(f"/reservations/{ref}/cancel"), 404, "L3.44", "not_found")


# ---- expected_revision (L3.45) --------------------------------------------------------------

def test_L3_45_stale_revision_is_409_before_cutoff_and_validation():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    check(patch(m.ada, ref, party_size=3, expected_revision=2), 409, "L3.45", "stale_revision")
    check(patch(m.ada, ref, party_size=3, expected_revision=99), 409, "L3.45", "stale_revision")
    check(patch(m.ada, ref, party_size=99, expected_revision=2), 409, "L3.45", "stale_revision")             # before validation
    check(patch(m.ada, ref, starts_at_local="garbage", expected_revision=5), 409, "L3.45", "stale_revision")
    assert m.ada.get(f"/reservations/{ref}").json == j
    r = check(patch(m.ada, ref, party_size=3, expected_revision=1), 200, "L3.45")
    assert r["revision"] == 2 and r["party_size"] == 3
    check(patch(m.ada, ref, party_size=2, expected_revision=1), 409, "L3.45", "stale_revision")
    r = check(patch(m.ada, ref, party_size=2, expected_revision=2), 200, "L3.45")
    assert r["revision"] == 3
    r = check(patch(m.ada, ref, party_size=2, expected_revision=3), 200, "L3.45")        # a no-op with the right revision still succeeds
    assert r["revision"] == 3
    old = book_ok(m.ada, "2020-01-08", "19:00", "t_2", 4)
    check(patch(m.ada, old["reference"], party_size=2, expected_revision=7), 409, "L3.45", "stale_revision")     # stale beats cutoff
    check(patch(m.ada, old["reference"], party_size=2, expected_revision=1), 409, "L3.45", "cutoff_passed")
    check(patch(m.bob, ref, party_size=2, expected_revision=99), 404, "L3.45", "not_found")                       # not the caller's: still 404


@pytest.mark.parametrize("bad", [0, -1, -100, "1", "x", True, False, 1.5, [1], {"a": 1}, 1e9 + 0.5])
def test_L3_45_invalid_expected_revision_is_422(bad):
    m = mgr_world()
    j = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    check(patch(m.ada, j["reference"], party_size=3, expected_revision=bad), 422, "L3.45", "validation_failed")
    assert m.ada.get(f"/reservations/{j['reference']}").json == j, "[L3.45] nothing applied"


def test_L3_45_omitted_expected_revision_keeps_stage1_semantics_and_unknown_fields_are_ignored():
    m = mgr_world()
    j = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    check(patch(m.ada, j["reference"], party_size=3, whatever=[1], revision=99, accepted_terms={"x": 1}, status="cancelled"), 200, "L3.45")
    g = m.ada.get(f"/reservations/{j['reference']}").json
    assert g["revision"] == 2 and g["status"] == "confirmed" and g["accepted_terms"] == j["accepted_terms"], \
        "[L3.45] 'revision', 'accepted_terms' and 'status' in a PATCH body are ordinary unknown fields and are ignored"


def test_L3_45_concurrent_amendments_with_one_revision_at_most_one_wins():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_3", 1)
    ref = j["reference"]
    variants = [dict(party_size=p) for p in (2, 3, 4, 5, 6)] + [dict(starts_at_local=local(d, t)) for t in ("18:00", "18:30", "19:30", "20:00", "20:30", "21:00")]
    out = burst(len(variants) * 3, lambda i: patch(m.ada, ref, expected_revision=1, **variants[i % len(variants)]))
    codes = [r.status for r in out]
    assert codes.count(200) == 1 and codes.count(409) == len(out) - 1, f"[L3.45] at most one real change succeeds per revision: {sorted(set(codes))} 200x{codes.count(200)}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L3.45", "stale_revision")
    g = m.ada.get(f"/reservations/{ref}").json
    assert g["revision"] == 2 and len(history(m.ada, ref)) == 2, "[L3.45] revision bumped exactly once"
    win = [r.json for r in out if r.status == 200][0]
    assert win == g


def test_L3_46_concurrent_unversioned_amendments_keep_history_and_revision_consistent():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_3", 1)
    ref = j["reference"]
    variants = [dict(party_size=p) for p in (1, 2, 3, 4, 5, 6)] + [dict(starts_at_local=local(d, t)) for t in ("18:00", "19:00", "19:30", "20:00")] \
        + [dict(table_id=t) for t in ("t_1", "t_2", "t_3")] + [dict()]
    out = burst(50, lambda i: patch(m.ada, ref, **variants[i % len(variants)]))
    assert all(r.status in (200, 422, 409) for r in out), f"[L3.46] {sorted({r.status for r in out})}"
    g = m.ada.get(f"/reservations/{ref}").json
    e = history(m.ada, ref)
    assert [x["seq"] for x in e] == list(range(1, len(e) + 1)), "[L3.46] gapless seq under concurrency"
    assert g["revision"] == len(e) == e[-1]["revision"], f"[L3.46] revision == number of recorded changes: revision {g['revision']}, entries {len(e)}"
    assert [x["revision"] for x in e] == list(range(1, len(e) + 1))
    cur = {"table_id": g["table_id"], "starts_at_local": g["starts_at_local"], "party_size": g["party_size"]}
    # replaying the changes forward reproduces the final record (no lost or phantom changes)
    state = {}
    for x in e:
        for c in x["changes"]:
            assert state.get(c["field"]) == c["from"], f"[L3.46] each change's 'from' is the previous 'to': {c} vs {state}"
            state[c["field"]] = c["to"]
    assert state == cur, f"[L3.46] history replays to the final record: {state} vs {cur}"


def test_L3_46_concurrent_cancel_and_amendments():
    m = mgr_world()
    d = m.date
    ref = book_ok(m.ada, d, "19:00", "t_3", 1)["reference"]
    out = burst(40, lambda i: m.ada.post(f"/reservations/{ref}/cancel") if i % 4 == 0 else patch(m.ada, ref, party_size=1 + (i % 6)))
    assert all(r.status in (200, 409) for r in out), f"[L3.46] {sorted({r.status for r in out})}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L3.46", "reservation_cancelled")
    g = m.ada.get(f"/reservations/{ref}").json
    e = history(m.ada, ref)
    assert g["status"] == "cancelled" and e[-1]["event"] == "cancelled" and [x["event"] for x in e].count("cancelled") == 1, "[L3.44/L3.46] exactly one cancelled entry, last"
    assert g["revision"] == len(e), "[L3.46] revision == entries"
