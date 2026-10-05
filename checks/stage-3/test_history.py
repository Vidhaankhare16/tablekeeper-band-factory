"""Reservation history and decision (ledger L3.10-L3.19)."""
import re
import pytest
from conftest import (call, check, reset, fixture, restaurant, safe_date, book, book_ok, new_key, local, login, history, mgr_world,
                      add_days, iso, publish_ok, policy, terms, slots)


def test_L3_10_created_entry_names_all_three_fields_from_null(w):
    j = book_ok(w.ada, w.date, "19:00", "t_2", 4)
    r = w.ada.get(f"/reservations/{j['reference']}/history")
    body = check(r, 200, "L3.10")
    assert body["reference"] == j["reference"] and list(body) == ["reference", "entries"] or set(body) == {"reference", "entries"}, f"[L3.10] {r!r}"
    e = body["entries"]
    assert len(e) == 1 and e[0]["seq"] == 1 and e[0]["event"] == "created", f"[L3.10] {e}"
    assert e[0]["changes"] == [{"field": "table_id", "from": None, "to": "t_2"},
                               {"field": "starts_at_local", "from": None, "to": f"{w.date}T19:00"},
                               {"field": "party_size", "from": None, "to": 4}], f"[L3.10] created names all three fields, each from null: {e[0]['changes']}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)", e[0]["at"]), f"[L3.10/L1.10] at has an explicit offset: {e[0]['at']}"
    assert e[0]["revision"] == 1 and e[0]["accepted_terms"] == j["accepted_terms"], "[L3.18] entry carries revision and accepted_terms"


def test_L3_11_seq_is_gapless_and_at_is_monotone(w):
    j = book_ok(w.ada, w.date, "19:00", "t_2", 4)
    ref = j["reference"]
    ops = [{"table_id": "t_3"}, {"party_size": 5}, {"starts_at_local": f"{w.date}T20:00"}, {"table_id": "t_2", "party_size": 3},
           {"starts_at_local": f"{w.date}T18:00", "table_id": "t_3", "party_size": 6}]
    for o in ops:
        check(w.ada.patch(f"/reservations/{ref}", json=o), 200, "L3.11")
    w.ada.post(f"/reservations/{ref}/cancel")
    e = history(w.ada, ref)
    assert [x["seq"] for x in e] == list(range(1, len(ops) + 3)), f"[L3.11] seq starts at 1 and increases by exactly 1: {[x['seq'] for x in e]}"
    assert [x["event"] for x in e] == ["created"] + ["changed"] * len(ops) + ["cancelled"]
    ats = [iso(x["at"]) for x in e]
    assert ats == sorted(ats), "[L3.11] entries are in seq order, which is also at order"


def test_L3_12_changed_names_only_changed_fields_in_canonical_order(w):
    d = w.date
    ref = book_ok(w.ada, d, "19:00", "t_2", 4)["reference"]
    cases = [({"party_size": 3}, [{"field": "party_size", "from": 4, "to": 3}]),
             ({"table_id": "t_3"}, [{"field": "table_id", "from": "t_2", "to": "t_3"}]),
             ({"starts_at_local": f"{d}T20:00"}, [{"field": "starts_at_local", "from": f"{d}T19:00", "to": f"{d}T20:00"}]),
             ({"party_size": 4, "table_id": "t_2", "starts_at_local": f"{d}T21:00"},       # given in "wrong" order
              [{"field": "table_id", "from": "t_3", "to": "t_2"}, {"field": "starts_at_local", "from": f"{d}T20:00", "to": f"{d}T21:00"},
               {"field": "party_size", "from": 3, "to": 4}]),
             ]
    for patch, want in cases:
        check(w.ada.patch(f"/reservations/{ref}", json=patch), 200, "L3.12")
        assert history(w.ada, ref)[-1]["changes"] == want, f"[L3.12] {patch}: changed names only the fields that changed, in table_id, starts_at_local, party_size order"
    n = len(history(w.ada, ref))
    # an unchanged field in the same PATCH is not named
    check(w.ada.patch(f"/reservations/{ref}", json={"table_id": "t_2", "party_size": 2}), 200, "L3.12")
    last = history(w.ada, ref)[-1]
    assert len(history(w.ada, ref)) == n + 1 and last["changes"] == [{"field": "party_size", "from": 4, "to": 2}], f"[L3.12] {last}"


def test_L3_13_noop_patch_records_nothing_but_succeeds(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    before = history(w.ada, ref)
    for patch in ({"table_id": "t_2"}, {"party_size": 4}, {"starts_at_local": f"{d}T19:00"},
                  {"table_id": "t_2", "party_size": 4, "starts_at_local": f"{d}T19:00"}, {}, {"unknown": 1}, {"table_ids": ["t_2"]}):
        r = w.ada.patch(f"/reservations/{ref}", json=patch)
        check(r, 200, f"L3.13 {patch}")
        assert r.json == w.ada.get(f"/reservations/{ref}").json and r.json["revision"] == 1, f"[L3.13] a no-op leaves revision 1: {r.json}"
    assert history(w.ada, ref) == before, "[L3.13] a no-op PATCH records no entry at all"
    assert w.ada.get(f"/reservations/{ref}").json == j


def test_L3_14_cancelled_entry_has_empty_changes_and_nothing_follows(w):
    j = book_ok(w.ada, w.date)
    ref = j["reference"]
    c = check(w.ada.post(f"/reservations/{ref}/cancel"), 200, "L3.14")
    e = history(w.ada, ref)
    assert [x["event"] for x in e] == ["created", "cancelled"] and e[1]["changes"] == [], f"[L3.14] {e}"
    check(w.ada.post(f"/reservations/{ref}/cancel"), 200, "L3.14")           # second cancel
    check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 2}), 409, "L3.14", "reservation_cancelled")
    check(w.ada.patch(f"/reservations/{ref}", json={}), 409, "L3.14", "reservation_cancelled")
    assert history(w.ada, ref) == e, "[L3.14] nothing follows cancelled; repeated cancel records nothing"
    assert w.ada.get(f"/reservations/{ref}/history").status == 200, "[L3.14] a cancelled reservation still has its history"


def test_L3_15_replayed_post_records_nothing_and_failures_record_nothing(w):
    d, key = w.date, new_key()
    b = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{d}T19:00", "party_size": 4}
    first = check(w.ada.post("/reservations", json=b, key=key), 201, "L3.15")
    ref = first["reference"]
    before = history(w.ada, ref)
    for _ in range(3):
        assert check(w.ada.post("/reservations", json=b, key=key), 200, "L3.15") == first, "[L3.15] replay = original response"
    assert history(w.ada, ref) == before and len(before) == 1, "[L3.15] a replay does not re-run the operation or record anything"
    check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 9}), 422, "L3.15", "party_exceeds_capacity")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T19:15"}), 422, "L3.15", "not_on_slot_grid")
    check(w.bob.patch(f"/reservations/{ref}", json={"party_size": 2}), 404, "L3.15", "not_found")
    assert history(w.ada, ref) == before, "[L3.15] failed amendments record nothing"
    assert w.ada.get(f"/reservations/{ref}").json == first


def test_L3_16_history_is_owner_only_404_for_everyone_else(w):
    j = book_ok(w.ada, w.date)
    ref = j["reference"]
    for path in (f"/reservations/{ref}/history", f"/reservations/{ref}/decision"):
        check(w.bob.get(path), 404, "L3.16", "not_found")
        check(call("GET", path), 404, "L3.16", "not_found")                                  # unauthenticated: 404, not 401
        check(call("GET", path, headers={"Authorization": "Bearer junk"}), 404, "L3.16", "not_found")
        check(w.ada.get(path), 200, "L3.16")
        check(w.ada.get(path.replace(ref, "NOPE99")), 404, "L3.16", "not_found")
        check(call("GET", path.replace(ref, "NOPE99")), 404, "L3.16", "not_found")
    other = call("GET", f"/reservations/{ref}/history").json
    own_missing = w.bob.get(f"/reservations/{ref}/history").json
    unknown = w.bob.get("/reservations/NOPE99/history").json
    assert other["error"]["code"] == own_missing["error"]["code"] == unknown["error"]["code"] == "not_found", "[L3.16] the same 404 for all"


def test_L3_16_managers_do_not_gain_access_to_other_diners_history():
    m = mgr_world()
    j = book_ok(m.bob, m.date)
    check(m.ada.get(f"/reservations/{j['reference']}/history"), 404, "L3.16", "not_found")     # Ada manages r_anker
    check(m.ada.get(f"/reservations/{j['reference']}/decision"), 404, "L3.16", "not_found")
    check(m.ada.get(f"/reservations/{j['reference']}"), 404, "L3.16", "not_found")


def test_L3_17_decision_endpoint_shape_current_and_after_cancel(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    r = w.ada.get(f"/reservations/{ref}/decision")
    dj = check(r, 200, "L3.17")
    assert set(dj) == {"reference", "revision", "accepted_terms"} and dj["reference"] == ref and dj["revision"] == 1 \
        and dj["accepted_terms"] == j["accepted_terms"], f"[L3.17] {dj}"
    w.ada.patch(f"/reservations/{ref}", json={"party_size": 3})
    assert w.ada.get(f"/reservations/{ref}/decision").json["revision"] == 2
    w.ada.post(f"/reservations/{ref}/cancel")
    dj = check(w.ada.get(f"/reservations/{ref}/decision"), 200, "L3.17")
    assert dj["revision"] == 3 and dj["accepted_terms"] == j["accepted_terms"], "[L3.17] decision survives cancellation (and cancel bumped the revision once)"
    w.ada.post(f"/reservations/{ref}/cancel")
    assert w.ada.get(f"/reservations/{ref}/decision").json["revision"] == 3, "[L3.17] repeated cancel does not bump the revision"
    assert w.ada.get(f"/reservations/{ref}").json["revision"] == 3


def test_L3_18_every_entry_carries_resulting_revision_and_complete_terms():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    p1 = policy(d, reservation_duration_minutes=120, cancellation_cutoff_minutes=30)
    v1 = publish_ok(m.ada, "r_anker", p1)
    check(m.ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200, "L3.18")      # adopts policy 1
    m.ada.post(f"/reservations/{ref}/cancel")
    e = history(m.ada, ref)
    t0, t1 = j["accepted_terms"], terms(p1, 1)
    assert t0["policy_version"] == 0 and t1["policy_version"] == 1
    assert [x["revision"] for x in e] == [1, 2, 3], f"[L3.18] resulting revisions: {[x['revision'] for x in e]}"
    assert [x["accepted_terms"] for x in e] == [t0, t1, t1], "[L3.18] old entries never acquire newer terms; each carries the complete terms of that moment"
    assert e[0]["accepted_terms"] == t0 and m.ada.get(f"/reservations/{ref}").json["accepted_terms"] == t1


def test_L3_19_sequence_under_equal_timestamps_is_total(w):
    ref = book_ok(w.ada, w.date, "19:00", "t_2", 4)["reference"]
    for p in (1, 2, 3, 4, 3, 2, 1):
        w.ada.patch(f"/reservations/{ref}", json={"party_size": p})
    e = history(w.ada, ref)
    assert [x["seq"] for x in e] == list(range(1, len(e) + 1)), "[L3.19] total order even if writes share a second"
    assert [x["revision"] for x in e] == list(range(1, len(e) + 1)), "[L3.19] revision equals seq for a lone reservation"
    assert len(e) == 1 + 7, "[L3.19] each of the seven PATCHes changes the party size (4,1,2,3,4,3,2,1), so seven changed entries follow created"
