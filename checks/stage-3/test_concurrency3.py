"""Stage-3 concurrency: results equal some serial order and invariants hold at every read (ledger L3.96-L3.99)."""
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login, publish,
                      publish_ok, policy, terms, history, mgr_world, add_days, iso, burst, body)
from test_series import adopt, adopt_ok, gs, occ_by_index
from test_amend3 import mins


def consistent_explain(j):
    for s in j["slots"]:
        assert [e["table_id"] for e in s["explain"]] == ["t_1", "t_2", "t_3"], "[L3.96] every table once, fixture order"
        for e in s["explain"]:
            assert [r["rule"] for r in e["rules"]] == ["capacity", "no_overlap"] and e["available"] == all(r["holds"] for r in e["rules"]), f"[L3.96] {e}"
        assert [e["table_id"] for e in s["explain"] if e["available"]] == s["available_table_ids"], "[L3.96] explain agrees with available_table_ids at this read"
        assert [o["table_ids"][0] for o in s["available_options"] if len(o["table_ids"]) == 1] == s["available_table_ids"]


def test_L3_96_explain_reads_are_consistent_while_bookings_race():
    users = [user(f"c{i:02d}") for i in range(30)]
    reset(fixture(users=users, restaurants=[restaurant()]))
    cl = burst(30, lambda i: login(f"c{i:02d}@example.com"))
    d = safe_date()
    starts = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]

    def op(i):
        if i < 30:
            return book(cl[i], d, starts[i % 8], ["t_1", "t_2", "t_3"][i % 3], 2)
        return call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size={1 + i % 6}&explain=true")
    out = burst(60, op)
    assert all(r.status in (201, 409, 200) for r in out), f"[L3.96] {sorted({r.status for r in out})}"
    for r in out[30:]:
        consistent_explain(r.json)
    final = call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=1&explain=true").json
    consistent_explain(final)
    booked = [x for r in out[:30] if r.status == 201 for x in [r.json]]
    for s in final["slots"]:
        st = iso(s["starts_at"])
        for e in s["explain"]:
            busy = any(b["table_id"] == e["table_id"] and iso(b["starts_at"]).timestamp() < st.timestamp() + 5400 and st.timestamp() < iso(b["ends_at"]).timestamp() for b in booked)
            assert e["rules"][1]["holds"] == (not busy), f"[L3.5] no_overlap at {s['starts_at_local']} for {e['table_id']} disagrees with the bookings"


def test_L3_97_publication_races_with_bookings_each_booking_sees_one_whole_policy():
    users = [user(f"c{i:02d}") for i in range(40)]
    reset(fixture(users=users, restaurants=[restaurant(managers=["u_c00"])]))
    cl = burst(40, lambda i: login(f"c{i:02d}@example.com"))
    d = safe_date()
    pols = [policy("2000-01-01", reservation_duration_minutes=30 + 10 * k, cancellation_cutoff_minutes=10 + k, capacities={"t_1": 2 + k, "t_2": 4, "t_3": 6})
            for k in range(1, 6)]

    def op(i):
        if i < 5:
            return publish(cl[0], "r_anker", pols[i])
        return book(cl[i], add_days(d, i), "19:00", "t_1", 2)
    out = burst(40, op)
    assert all(r.status == 201 for r in out), f"[L3.97] {[r.status for r in out if r.status != 201]}"
    versions = sorted(r.json["policy_version"] for r in out[:5])
    assert versions == [1, 2, 3, 4, 5]
    snaps = {0: terms(policy("x"), 0)}
    snaps[0]["opening_hours"] = all_week("18:00", "23:00")
    for r in out[:5]:
        snaps[r.json["policy_version"]] = terms({k: v for k, v in r.json.items() if k != "policy_version"}, r.json["policy_version"])
    for r in out[5:]:
        j = r.json
        t = j["accepted_terms"]
        assert t == snaps[t["policy_version"]], f"[L3.97] a booking's accepted_terms is exactly one whole published policy (or policy 0): {t}"
        assert mins(j) == t["reservation_duration_minutes"], "[L3.97] the end time matches the accepted duration"
    # later bookings all see the final selection: ties on 2000-01-01 choose the greatest version
    last = book_ok(cl[1], add_days(d, 50), "19:00", "t_2", 2)
    assert last["accepted_terms"]["policy_version"] == 5


def test_L3_98_concurrent_batches_and_patches_on_one_series_keep_revision_equal_to_changes():
    m = mgr_world()
    anchor = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    s = adopt_ok(m.ada, anchor["reference"], 6, 1)
    refs = [o["reference"] for o in s["occurrences"]]

    def op(i):
        r = refs[1 + i % 5]
        if i % 3 == 0:
            return m.ada.patch(f"/reservations/{r}", json={"party_size": 1 + i % 4})
        if i % 3 == 1:
            return m.ada.post("/reservation-moves", json={"moves": [{"reference": r, "party_size": 1 + (i % 4)}]}, key=new_key())
        return m.ada.post(f"/reservations/{r}/cancel") if i % 9 == 2 else m.ada.patch(f"/reservations/{r}", json={})
    out = burst(45, op)
    assert all(r.status in (200, 201, 409) for r in out), f"[L3.98] {sorted({r.status for r in out})}"
    g = gs(m.ada, s["series_id"]).json
    changes = 0
    cancels = 0
    for o in g["occurrences"]:
        e = history(m.ada, o["reference"])
        assert o["reservation"]["revision"] == len(e), f"[L3.98] occurrence revision == recorded history entries: {o['index']}"
        changes += sum(1 for x in e if x["event"] == "changed")
        cancels += sum(1 for x in e if x["event"] == "cancelled")
        if o["index"] == 0:
            assert o["exception"] is False
        assert o["exception"] == any(x["event"] == "changed" for x in e), f"[L3.98] exception flag == has a real change: {o['index']}"
    assert g["revision"] >= 1 + max(changes, 1) - 1 and g["revision"] <= 1 + changes + cancels, \
        f"[L3.98] series revision {g['revision']} must lie between 1+(#occurrences changed, once per batch) and 1+(#changes+#cancels)={1 + changes + cancels}"
    assert g["revision"] >= 1 + cancels, "[L3.98] every real cancellation bumped the series revision once"


def test_L3_99_series_adoption_races_with_a_booking_on_the_target_slot():
    m = mgr_world()
    d = m.date
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    target = add_days(d, 21)

    def op(i):
        if i == 0:
            return adopt(m.ada, anchor["reference"], 4, 1)
        return book(m.bob, target, "19:00", "t_2", 4, key=new_key()) if i == 1 else book(m.cy, add_days(d, 100 + i), "19:00", "t_1", 2)
    out = burst(12, op)
    ser, steal = out[0], out[1]
    assert (ser.status, steal.status) in ((201, 409), (409, 201)), f"[L3.99] adoption and the competing booking serialize: {ser.status}/{steal.status}"
    lst = m.ada.get("/reservations").json["reservations"]
    if ser.status == 201:
        assert len(lst) == 4 and steal.json["error"]["code"] == "table_unavailable"
    else:
        assert ser.json["error"]["code"] == "table_unavailable" and len(lst) == 1, "[L3.99] a failed adoption leaves nothing"
