"""Combined-table history and terms (ledger L3.80-L3.85)."""
import pytest
from conftest import (call, check, reset, fixture, restaurant, safe_date, book_ok, new_key, local, login, history, mgr_world, add_days,
                      publish_ok, policy, terms, body)


def pair_post(c, d, ids, at="19:00", party=6):
    return c.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ids, "starts_at_local": local(d, at), "party_size": party}, key=new_key())


def test_L3_80_pair_creation_names_table_ids_from_null_in_declared_order():
    m = mgr_world()
    d = m.date
    for i, ids in enumerate((["t_1", "t_2"], ["t_3", "t_2"])):                      # second one is a reversed input of the pair [t_2,t_3]
        j = check(pair_post(m.ada, add_days(d, i), ids, party=6), 201, "L3.80")
        e = history(m.ada, j["reference"])
        want = ["t_1", "t_2"] if i == 0 else ["t_2", "t_3"]
        assert e[0]["changes"] == [{"field": "table_ids", "from": None, "to": want},
                                   {"field": "starts_at_local", "from": None, "to": local(add_days(d, i), "19:00")},
                                   {"field": "party_size", "from": None, "to": 6}], \
            f"[L3.80] for a pair, table_ids replaces the table_id change; set order is the declared combination order: {e[0]['changes']}"


def test_L3_81_changes_involving_a_pair_use_complete_table_ids_lists():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 3)
    ref = j["reference"]
    steps = [({"table_ids": ["t_2", "t_1"], "party_size": 5}, [{"field": "table_ids", "from": ["t_2"], "to": ["t_1", "t_2"]}, {"field": "party_size", "from": 3, "to": 5}]),
             ({"table_ids": ["t_3", "t_2"]}, [{"field": "table_ids", "from": ["t_1", "t_2"], "to": ["t_2", "t_3"]}]),
             ({"table_id": "t_3", "party_size": 4}, [{"field": "table_ids", "from": ["t_2", "t_3"], "to": ["t_3"]}, {"field": "party_size", "from": 5, "to": 4}]),   # pair -> single still names table_ids
             ({"table_id": "t_2"}, [{"field": "table_id", "from": "t_3", "to": "t_2"}]),                                         # single -> single keeps table_id
             ({"table_ids": ["t_1"], "party_size": 2}, [{"field": "table_id", "from": "t_2", "to": "t_1"}, {"field": "party_size", "from": 4, "to": 2}])]
    for patch, want in steps:
        check(m.ada.patch(f"/reservations/{ref}", json=patch), 200, f"L3.81 {patch}")
        assert history(m.ada, ref)[-1]["changes"] == want, f"[L3.81] {patch}: expected {want}, got {history(m.ada, ref)[-1]['changes']}"
    assert [x["revision"] for x in history(m.ada, ref)] == [1, 2, 3, 4, 5, 6]


def test_L3_82_reversed_pair_is_not_an_amendment_on_its_own():
    m = mgr_world()
    d = m.date
    j = check(pair_post(m.ada, d, ["t_1", "t_2"], party=6), 201, "L3.82")
    ref = j["reference"]
    before = history(m.ada, ref)
    for ids in (["t_2", "t_1"], ["t_1", "t_2"]):
        r = check(m.ada.patch(f"/reservations/{ref}", json={"table_ids": ids}), 200, "L3.82")
        assert r["revision"] == 1 and r == m.ada.get(f"/reservations/{ref}").json == j, "[L3.82] same set => no-op: revision, terms, end time kept"
    assert history(m.ada, ref) == before, "[L3.82] no history entry"
    check(m.ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_2", "t_1"], "party_size": 4}), 200, "L3.82")
    e = history(m.ada, ref)
    assert len(e) == 2 and e[1]["changes"] == [{"field": "party_size", "from": 6, "to": 4}], f"[L3.82] only the real change is named: {e[1]['changes']}"
    # same through moves
    r = call("POST", "/reservation-moves", json={"moves": [{"reference": ref, "table_ids": ["t_2", "t_1"]}]}, token=m.ada.token, headers={"Idempotency-Key": new_key()})
    assert r.status == 201 and r.json["reservations"][0]["revision"] == 2 and len(history(m.ada, ref)) == 2, "[L3.82] reversed pair is a no-op in a move too"


def test_L3_84_amending_a_pair_adopts_the_new_terms():
    m = mgr_world()
    d = m.date
    j = check(pair_post(m.ada, d, ["t_1", "t_2"], party=6), 201, "L3.84")
    p1 = policy(d, capacities={"t_1": 1, "t_2": 2, "t_3": 6}, reservation_duration_minutes=60)
    publish_ok(m.ada, "r_anker", p1)
    check(m.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 4}), 422, "L3.84", "party_exceeds_capacity")      # 1+2 = 3 under the policy
    ok = check(m.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 3}), 200, "L3.84")
    assert ok["accepted_terms"] == terms(p1, 1) and ok["revision"] == 2 and sorted(ok["table_ids"]) == ["t_1", "t_2"]
    e = history(m.ada, j["reference"])
    assert e[1]["changes"] == [{"field": "party_size", "from": 6, "to": 3}] and e[1]["accepted_terms"] == terms(p1, 1)
    # availability options use the policy sum too (a free day under the same policy: pair capacity is 1+2 = 3)
    s = {x["starts_at_local"][-5:]: x for x in call("GET", f"/availability?restaurant_id=r_anker&date={add_days(d, 1)}&party_size=1").json["slots"]}
    assert {"table_ids": ["t_1", "t_2"], "capacity": 3} in s["19:00"]["available_options"], "[L3.84/L3.28] pair capacity is the sum of the selected policy's capacities"
