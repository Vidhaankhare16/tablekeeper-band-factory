"""Upgrade: exports of the accepted stage-1 and stage-2 services imported into the stage-3 service (ledger L3.90-L3.99)."""
import http.client
import json as _json
import os
import urllib.parse
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, new_key, local, login, Resp, PW, add_days,
                      publish, policy, history, iso)

PREV1 = os.environ.get("TK_PREV_URL", "http://127.0.0.1:8081").rstrip("/")
PREV2 = os.environ.get("TK_PREV2_URL", "http://127.0.0.1:8082").rstrip("/")
P0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
      "opening_hours": all_week("18:00", "23:00"), "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def old(base, method, path, json=None, token=None, key=None, timeout=10.5):
    u = urllib.parse.urlparse(base)
    h = {"Accept": "application/json"}
    body = None
    if json is not None:
        body = _json.dumps(json).encode(); h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
    finally:
        c.close()


def need(base):
    try:
        assert old(base, "GET", "/health").status == 200
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"[L3.90] the accepted earlier-stage service is not reachable at {base} (see checks/stage-3/prev_up.sh): {e}")


def upgrade(base):
    e = old(base, "GET", "/_test/export")
    assert e.status == 200, f"export from the earlier stage failed: {e!r}"
    r = call("POST", "/_test/import", json=e.json, timeout=10.5)
    assert r.status == 204, f"[L3.90] a stage-3 service must accept an unchanged export of the earlier stage (204), got {r!r}"
    return e.json


def bd(d, at="19:00", table="t_2", party=4, rid="r_anker"):
    return {"restaurant_id": rid, "table_id": table, "starts_at_local": local(d, at), "party_size": party}


def build_world(base, stage):
    fx_r = restaurant(combinable=[["t_1", "t_2"], ["t_2", "t_3"]]) if stage == 2 else restaurant()
    fx = fixture(restaurants=[fx_r, restaurant("r_two", name="Zwei", tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])])
    assert old(base, "POST", "/_test/reset", json=fx).status == 204
    ada = old(base, "POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).json
    bob = old(base, "POST", "/auth/login", json={"email": "bob@example.com", "password": PW}).json
    sue = old(base, "POST", "/auth/signup", json={"email": "sue@example.com", "password": "sue-secret-pw", "display_name": "Sue"}).json
    d, d2 = safe_date(), safe_date(1)
    o = {"fx": fx, "ada": ada["token"], "bob": bob["token"], "sue": sue["token"], "d": d, "d2": d2, "keys": {}, "bodies": {}, "first": {}}
    def mk(name, tok, b):
        key = new_key()
        r = old(base, "POST", "/reservations", json=b, token=tok, key=key)
        assert r.status == 201, r
        o["keys"][name], o["bodies"][name], o["first"][name] = key, b, r.json
        return r.json
    mk("a1", o["ada"], bd(d, "19:00", "t_2", 4))
    mk("a2", o["ada"], bd(d2, "20:00", "t_3", 5))
    mk("b1", o["bob"], bd(d, "19:00", "t_3", 6))
    mk("s1", o["sue"], bd(d2, "18:00", "t_1", 2))
    if stage == 2:
        key = new_key()
        b = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": local(add_days(d, 3), "19:00"), "party_size": 6}
        r = old(base, "POST", "/reservations", json=b, token=o["ada"], key=key)
        assert r.status == 201, r
        o["keys"]["pair"], o["bodies"]["pair"], o["first"]["pair"] = key, b, r.json
    cx = mk("cx", o["ada"], bd(add_days(d, 4), "19:00", "t_1", 2))
    old(base, "POST", f"/reservations/{cx['reference']}/cancel", token=o["ada"])
    o["failed_key"] = new_key()
    assert old(base, "POST", "/reservations", json=bd(d, "19:30", "t_2", 4), token=o["bob"], key=o["failed_key"]).status == 409
    o["mk"] = new_key()
    o["mv_body"] = {"moves": [{"reference": o["first"]["a2"]["reference"], "table_id": "t_2", "party_size": 4}]}
    mv = old(base, "POST", "/reservation-moves", json=o["mv_body"], token=o["ada"], key=o["mk"])
    assert mv.status == 201, mv
    o["mv"] = mv.json
    return o


@pytest.mark.parametrize("stage,base_name", [(1, "PREV1"), (2, "PREV2")])
def test_L3_90_accounts_tokens_references_and_receipts_survive(stage, base_name):
    base = PREV1 if stage == 1 else PREV2
    need(base)
    o = build_world(base, stage)
    upgrade(base)
    # sessions and accounts
    for who in ("ada", "bob", "sue"):
        check(call("GET", "/reservations", token=o[who]), 200, "L3.90")
    for email, pw in (("ada@example.com", PW), ("bob@example.com", PW), ("sue@example.com", "sue-secret-pw")):
        check(call("POST", "/auth/login", json={"email": email, "password": pw}), 200, "L3.90")
    # confirmation links: every old reference opens for its owner and only for them
    for name, tok in (("a1", o["ada"]), ("a2", o["ada"]), ("b1", o["bob"]), ("s1", o["sue"]), ("cx", o["ada"])):
        old_r = o["first"][name]
        g = check(call("GET", f"/reservations/{old_r['reference']}", token=tok), 200, "L3.90")
        for k, v in old_r.items():
            if name == "a2" and k in ("table_id", "table_ids", "party_size"):
                continue                    # a2 was moved by the batch after creation
            if k in ("status",):
                continue
            assert g.get(k) == v, f"[L3.90] imported {name}.{k}: expected {v!r}, got {g.get(k)!r}"
        assert g["revision"] == 1 and g["accepted_terms"] == P0 and g["table_ids"] == ([g["table_id"]] if "table_id" in g else g["table_ids"]), \
            f"[L3.91] imported reservations are revision 1 under policy 0: {g.get('revision')} {g.get('accepted_terms')}"
        check(call("GET", f"/reservations/{old_r['reference']}", token=o["sue" if tok != o["sue"] else "ada"]), 404, "L3.90", "not_found")
    assert check(call("GET", f"/reservations/{o['first']['cx']['reference']}", token=o["ada"]), 200, "L3.90")["status"] == "cancelled"
    # original idempotent responses survive verbatim; failed keys stay reusable
    for name in ("a1", "b1", "s1"):
        tok = o["ada"] if name == "a1" else o["bob"] if name == "b1" else o["sue"]
        rep = check(call("POST", "/reservations", json=o["bodies"][name], token=tok, key=o["keys"][name]), 200, "L3.90")
        assert rep == o["first"][name], f"[L3.90] replay of an old key returns the original response (original revision/terms-free body): {rep}"
    rep = check(call("POST", "/reservation-moves", json=o["mv_body"], token=o["ada"], key=o["mk"]), 200, "L3.90")
    assert rep == o["mv"], "[L3.90] batch receipts survive"
    check(call("POST", "/reservations", json={**o["bodies"]["a1"], "party_size": 3}, token=o["ada"], key=o["keys"]["a1"]), 409, "L3.90", "idempotency_key_reuse")
    j = check(call("POST", "/reservations", json=bd(o["d"], "21:00", "t_2", 4), token=o["bob"], key=o["failed_key"]), 201, "L3.90")
    assert j["revision"] == 1 and j["accepted_terms"] == P0
    if stage == 2:
        pr = o["first"]["pair"]
        g = check(call("GET", f"/reservations/{pr['reference']}", token=o["ada"]), 200, "L3.90")
        assert sorted(g["table_ids"]) == ["t_1", "t_2"] and "table_id" not in g and g["revision"] == 1
        assert call("GET", "/restaurants/r_anker").json["combinable"] == [["t_1", "t_2"], ["t_2", "t_3"]], "[L3.90] combinations survive"
        assert check(call("POST", "/reservations", json=o["bodies"]["pair"], token=o["ada"], key=o["keys"]["pair"]), 200, "L3.90") == pr
    else:
        assert call("GET", "/restaurants/r_anker").json.get("combinable", []) == []


@pytest.mark.parametrize("stage", [1, 2])
def test_L3_91_history_decision_and_amendment_of_imported_reservations(stage):
    base = PREV1 if stage == 1 else PREV2
    need(base)
    o = build_world(base, stage)
    upgrade(base)
    ref = o["first"]["a1"]["reference"]
    dec = check(call("GET", f"/reservations/{ref}/decision", token=o["ada"]), 200, "L3.91")
    assert dec == {"reference": ref, "revision": 1, "accepted_terms": P0}, f"[L3.91] {dec}"
    h = check(call("GET", f"/reservations/{ref}/history", token=o["ada"]), 200, "L3.91")
    assert h["reference"] == ref and isinstance(h["entries"], list)
    n = len(h["entries"])
    assert [e["seq"] for e in h["entries"]] == list(range(1, n + 1)) and all(e["revision"] == 1 for e in h["entries"]), "[L3.91] contiguous history of the imported record"
    check(call("GET", f"/reservations/{ref}/history", token=o["bob"]), 404, "L3.91", "not_found")
    check(call("GET", f"/reservations/{ref}/history"), 404, "L3.91", "not_found")
    from conftest import Client
    ada = Client(o["ada"])
    j = check(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200, "L3.91")
    assert j["revision"] == 2 and j["accepted_terms"] == P0, f"[L3.91] a real amendment of an imported booking bumps the revision once: {j}"
    h2 = check(ada.get(f"/reservations/{ref}/history"), 200, "L3.91")["entries"]
    assert len(h2) == n + 1 and h2[-1]["event"] == "changed" and h2[-1]["seq"] == n + 1 and h2[-1]["revision"] == 2 \
        and h2[-1]["changes"] == [{"field": "party_size", "from": 4, "to": 3}], f"[L3.91] {h2[-1]}"
    check(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200, "L3.91")
    assert len(check(ada.get(f"/reservations/{ref}/history"), 200, "L3.91")["entries"]) == n + 1, "[L3.91] no-op records nothing"
    c = check(ada.post(f"/reservations/{ref}/cancel"), 200, "L3.91")
    assert c["revision"] == 3


@pytest.mark.parametrize("stage", [1, 2])
def test_L3_92_adoption_works_on_imported_reservations(stage):
    base = PREV1 if stage == 1 else PREV2
    need(base)
    o = build_world(base, stage)
    upgrade(base)
    from conftest import Client
    ada = Client(o["ada"])
    ref = o["first"]["a1"]["reference"]
    s = check(ada.post("/series", json={"anchor_reference": ref, "count": 3, "interval_weeks": 1}, key=new_key()), 201, "L3.92")
    occ = s["occurrences"]
    assert occ[0]["reference"] == ref and occ[0]["reservation"]["revision"] == 1 and occ[0]["reservation"]["accepted_terms"] == P0 \
        and occ[0]["reservation"]["reservation_id"] == o["first"]["a1"]["reservation_id"], f"[L3.92] the imported booking is occurrence zero, unchanged: {occ[0]}"
    assert [x["reservation"]["starts_at_local"] for x in occ] == [local(add_days(o["d"], 7 * i), "19:00") for i in range(3)]
    assert all(x["reservation"]["accepted_terms"]["policy_version"] == 0 for x in occ)
    check(ada.post("/series", json={"anchor_reference": ref, "count": 3, "interval_weeks": 1}, key=new_key()), 409, "L3.92", "already_in_series")
    if stage == 2:
        pr = o["first"]["pair"]["reference"]
        s2 = check(ada.post("/series", json={"anchor_reference": pr, "count": 2, "interval_weeks": 1}, key=new_key()), 201, "L3.92")
        assert sorted(s2["occurrences"][1]["reservation"]["table_ids"]) == ["t_1", "t_2"]
    bob = Client(o["bob"])
    check(bob.post("/series", json={"anchor_reference": ref, "count": 2, "interval_weeks": 1}, key=new_key()), 404, "L3.92", "not_found")


def test_L3_93_policies_after_upgrade_imported_restaurants_have_no_managers_and_old_bookings_keep_policy_zero():
    need(PREV1)
    o = build_world(PREV1, 1)
    upgrade(PREV1)
    from conftest import Client
    ada = Client(o["ada"])
    check(publish(ada, "r_anker", policy(o["d"])), 403, "L3.93", "forbidden")                    # no manager_user_ids in a stage-1 export => []
    j = check(ada.post("/reservations", json=bd(o["d"], "21:00", "t_1", 2), key=new_key()), 201, "L3.93")
    assert j["accepted_terms"] == P0 and j["revision"] == 1
    assert call("GET", "/restaurants/r_anker/policies").json == {"policies": []}
    e = call("GET", f"/availability?restaurant_id=r_anker&date={o['d']}&party_size=2&explain=true").json
    assert all(x["policy_version"] == 0 for s in e["slots"] for x in s["explain"]), "[L3.93] imported restaurants decide by policy 0"
    # re-importing the same export restores it again and is repeatable
    ex = old(PREV1, "GET", "/_test/export").json
    for _ in range(2):
        assert call("POST", "/_test/import", json=ex, timeout=10.5).status == 204
    assert call("GET", f"/reservations/{o['first']['a1']['reference']}", token=o["ada"]).json["revision"] == 1


def test_L3_94_stage3_own_export_import_round_trip_keeps_everything():
    m_fx = fixture(restaurants=[restaurant(managers=["u_ada"], combinable=[["t_1", "t_2"], ["t_2", "t_3"]])])
    reset(m_fx)
    ada, bob = login("ada@example.com"), login("bob@example.com")
    d = safe_date()
    p1 = policy(d, reservation_duration_minutes=100)
    key_p = new_key()
    pub = check(publish(ada, "r_anker", p1, key_p), 201, "L3.94")
    key_b = new_key()
    b = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": local(d, "19:00"), "party_size": 6}
    j = check(ada.post("/reservations", json=b, key=key_b), 201, "L3.94")
    ada.patch(f"/reservations/{j['reference']}", json={"party_size": 5})
    other = check(ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(d, "21:00"), "party_size": 6}, key=new_key()), 201, "L3.94")
    sk = new_key()
    sb = {"anchor_reference": other["reference"], "count": 3, "interval_weeks": 1}
    s = check(ada.post("/series", json=sb, key=sk), 201, "L3.94")
    ada.patch(f"/reservations/{s['occurrences'][1]['reference']}", json={"party_size": 2})
    mk = new_key()
    mvb = {"moves": [{"reference": s["occurrences"][2]["reference"], "party_size": 3}]}
    mv = check(ada.post("/reservation-moves", json=mvb, key=mk), 201, "L3.94")
    E = call("GET", "/_test/export", timeout=10.5).json
    pre = {"list": ada.get("/reservations").json, "hist": [history(ada, r["reference"]) for r in ada.get("/reservations").json["reservations"]],
           "series": ada.get(f"/series/{s['series_id']}").json, "policies": call("GET", "/restaurants/r_anker/policies").json,
           "dec": ada.get(f"/reservations/{j['reference']}/decision").json}
    reset(fixture(users=[user("zed")], restaurants=[restaurant("r_z", name="Z")]))
    assert call("POST", "/_test/import", json=E, timeout=10.5).status == 204
    post = {"list": ada.get("/reservations").json, "hist": [history(ada, r["reference"]) for r in ada.get("/reservations").json["reservations"]],
            "series": ada.get(f"/series/{s['series_id']}").json, "policies": call("GET", "/restaurants/r_anker/policies").json,
            "dec": ada.get(f"/reservations/{j['reference']}/decision").json}
    assert post == pre, "[L3.94] reservations, histories, revisions, terms, series, exceptions and policies all survive an export/import round trip"
    assert check(publish(ada, "r_anker", p1, key_p), 200, "L3.94") == pub, "[L3.94] policy receipts survive and no version is allocated"
    assert check(ada.post("/reservations", json=b, key=key_b), 200, "L3.94")["revision"] == 1
    assert check(ada.post("/series", json=sb, key=sk), 200, "L3.94") == s
    assert check(ada.post("/reservation-moves", json=mvb, key=mk), 200, "L3.94") == mv
    assert check(publish(ada, "r_anker", policy(add_days(d, 1)), new_key()), 201, "L3.94")["policy_version"] == 2, "[L3.94] version counter restored"
    bob_ref = check(bob.post("/reservations", json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": local(add_days(d, 30), "19:00"), "party_size": 2}, key=new_key()), 201, "L3.94")
    refs = {r["reference"] for r in pre["list"]["reservations"]}
    assert bob_ref["reference"] not in refs, "[L3.94] new references never collide with restored ones"
    check(call("GET", f"/series/{s['series_id']}", token=bob.token), 404, "L3.94", "not_found")
