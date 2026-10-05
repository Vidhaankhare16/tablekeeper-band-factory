"""Upgrade: exports of the accepted stage-1, stage-2 and stage-3 services imported into the stage-4 service (ledger L4.80-L4.89)."""
import os
import pytest
from conftest import (Client, call, check, reset, fixture, restaurant, user, all_week, safe_date, new_key, local, login, PW, add_days,
                      publish, policy, history, iso, terms)
from test_upgrade3 import old, need, upgrade, build_world, bd, P0, PREV1, PREV2
from replan_kit import inst, replan, plan_ok, apply_plan, apply_ok, rev
from test_series import occ_by_index

PREV3 = os.environ.get("TK_PREV3_URL", "http://127.0.0.1:8083").rstrip("/")


@pytest.mark.parametrize("stage", [1, 2])
def test_L4_80_older_exports_stay_valid_and_their_reservations_can_be_adopted_and_amended(stage):
    base = PREV1 if stage == 1 else PREV2
    need(base)
    o = build_world(base, stage)
    upgrade(base)
    ada = Client(o["ada"])
    for name in ("a1", "b1", "s1"):
        tok = o["ada"] if name == "a1" else o["bob"] if name == "b1" else o["sue"]
        rep = check(call("POST", "/reservations", json=o["bodies"][name], token=tok, key=o["keys"][name]), 200, "L4.80")
        assert rep == o["first"][name], "[L4.80] earlier receipts are verbatim"
    assert call("POST", "/reservation-moves", json=o["mv_body"], token=o["ada"], key=o["mk"]).json == o["mv"]
    ref = o["first"]["a1"]["reference"]
    s = check(ada.post("/series", json={"anchor_reference": ref, "count": 4, "interval_weeks": 1}, key=new_key()), 201, "L4.80")
    sid = s["series_id"]
    out = check(ada.post(f"/series/{sid}/amend", json={"expected_revision": 1, "from_index": 1, "local_time": "20:30"}, key=new_key()), 201, "L4.80")
    oc = occ_by_index(out)
    assert oc[0]["reservation"]["starts_at_local"].endswith("T19:00") and all(oc[i]["reservation"]["starts_at_local"].endswith("T20:30") for i in (1, 2, 3))
    assert [x["reservation"]["starts_at_local"][:10] for x in out["occurrences"]] == [add_days(o["d"], 7 * i) for i in range(4)], "[L4.80] scheduled dates from the imported anchor"
    assert out["revision"] == 2 and all(x["exception"] is False for x in out["occurrences"])
    h = history(ada, oc[1]["reference"])
    assert h[-1]["event"] == "changed" and h[-1]["accepted_terms"] == P0
    for r in (ref,):
        assert Client(o["bob"]).get(f"/reservations/{r}").status == 404


def stage3_world():
    need(PREV3)
    fx = fixture(restaurants=[restaurant(managers=["u_ada"], combinable=[["t_1", "t_2"], ["t_2", "t_3"]]),
                              restaurant("r_two", name="Zwei", managers=["u_ada"], tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])])
    assert old(PREV3, "POST", "/_test/reset", json=fx).status == 204
    ada = old(PREV3, "POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).json["token"]
    bob = old(PREV3, "POST", "/auth/login", json={"email": "bob@example.com", "password": PW}).json["token"]
    d = safe_date()
    o = {"ada": ada, "bob": bob, "d": d, "keys": {}}

    def post(path, body, tok=ada, key=None):
        k = key or new_key()
        r = old(PREV3, "POST", path, json=body, token=tok, key=k)
        assert r.status in (200, 201), f"stage-3 setup {path}: {r!r}"
        return r.json, k

    def patch(ref, body, tok=ada):
        r = old(PREV3, "PATCH", f"/reservations/{ref}", json=body, token=tok)
        assert r.status == 200, r
        return r.json
    pol, o["pol_key"] = post("/restaurants/r_anker/policies", policy(add_days(d, 21), reservation_duration_minutes=60))
    anchor, o["anchor_key"] = post("/reservations", bd(d, "19:00", "t_2", 4))
    s, o["series_key"] = post("/series", {"anchor_reference": anchor["reference"], "count": 5, "interval_weeks": 1})
    refs = [x["reference"] for x in s["occurrences"]]
    patch(refs[0], {"party_size": 3})                                           # the anchor itself becomes an exception
    patch(refs[2], {"starts_at_local": f"{add_days(d, 14)}T21:00", "table_id": "t_3"})   # moved occurrence (exception)
    old(PREV3, "POST", f"/reservations/{refs[3]}/cancel", token=ada)             # cancelled occurrence
    o.update(pol=pol, anchor=anchor, series_id=s["series_id"], refs=refs, series_body={"anchor_reference": anchor["reference"], "count": 5, "interval_weeks": 1})
    o["series_final"] = old(PREV3, "GET", f"/series/{s['series_id']}", token=ada).json
    solo, o["solo_key"] = post("/reservations", bd(add_days(d, 1), "19:00", "t_3", 6, "r_anker"))
    o["solo"] = solo
    return o


def test_L4_81_imported_series_with_moved_and_cancelled_occurrences():
    o = stage3_world()
    pre_series = o["series_final"]
    assert pre_series["revision"] == 4
    upgrade(PREV3)
    ada = Client(o["ada"])
    sid = o["series_id"]
    g = check(ada.get(f"/series/{sid}"), 200, "L4.81")
    assert g == pre_series, "[L4.81] an imported series reads exactly as it did before the upgrade (flags, revision, states)"
    assert [x["exception"] for x in g["occurrences"]] == [True, False, True, False, False]
    check(Client(o["bob"]).get(f"/series/{sid}"), 404, "L4.81", "not_found")
    # replays of earlier receipts
    assert check(call("POST", "/series", json=o["series_body"], token=o["ada"], key=o["series_key"]), 200, "L4.81")["revision"] == 1, "[L4.81] original series response, original revision"
    assert check(call("POST", "/restaurants/r_anker/policies", json=policy(add_days(o["d"], 21), reservation_duration_minutes=60), token=o["ada"], key=o["pol_key"]), 200, "L4.81") == o["pol"]
    # amendment: cancelled (index 3) and exception (0, 2) occurrences are skipped; scheduled dates come from the imported agreement
    out = check(ada.post(f"/series/{sid}/amend", json={"expected_revision": 4, "from_index": 0, "local_time": "20:30"}, key=new_key()), 201, "L4.81")
    oc = occ_by_index(out)
    assert oc[1]["reservation"]["starts_at_local"] == f"{add_days(o['d'], 7)}T20:30" and oc[4]["reservation"]["starts_at_local"] == f"{add_days(o['d'], 28)}T20:30"
    assert oc[0]["reservation"] == occ_by_index(pre_series)[0]["reservation"] and oc[2]["reservation"] == occ_by_index(pre_series)[2]["reservation"] \
        and oc[3]["reservation"] == occ_by_index(pre_series)[3]["reservation"], "[L4.81] exception and cancelled occurrences untouched"
    assert out["revision"] == 5 and [x["exception"] for x in out["occurrences"]] == [True, False, True, False, False]
    assert oc[4]["reservation"]["accepted_terms"]["policy_version"] == 1 and (iso(oc[4]["reservation"]["ends_at"]) - iso(oc[4]["reservation"]["starts_at"])).total_seconds() == 3600, \
        "[L4.81] the policy of the occurrence's resulting date is adopted"


def test_L4_82_restaurant_revision_and_plans_work_on_imported_state():
    o = stage3_world()
    upgrade(PREV3)
    ada = Client(o["ada"])
    r0 = rev(ada)
    assert isinstance(r0, int) and r0 >= 0
    b = call("POST", "/reservations", json=bd(add_days(o["d"], 2), "19:00", "t_1", 2), token=o["ada"], headers={"Idempotency-Key": new_key()})
    assert b.status == 201 and rev(ada) == r0 + 1, "[L4.82] imported restaurants count revisions from the imported value"
    # a closure on the moved occurrence's table and day: the imported occurrence moves, keeping its exception flag and series identity
    g0 = ada.get(f"/series/{o['series_id']}").json
    occ2 = occ_by_index(g0)[2]["reservation"]
    day = occ2["starts_at_local"][:10]
    p = plan_ok(ada, "r_anker", "t_3", inst(day, "20:00"), inst(day, "23:00"))
    assert o["refs"][2] in [x["reference"] for x in p["assignments"]]
    out = apply_ok(ada, "r_anker", p["plan_id"])
    assert out["restaurant_revision"] == r0 + 2
    g1 = ada.get(f"/series/{o['series_id']}").json
    assert g1["revision"] == g0["revision"] + 1 and [x["exception"] for x in g1["occurrences"]] == [x["exception"] for x in g0["occurrences"]], \
        "[L4.82] a plan moving an imported series member raises the series revision once and keeps the flags"
    n = occ_by_index(g1)[2]["reservation"]
    assert n["table_ids"] != ["t_3"] and n["accepted_terms"] == occ2["accepted_terms"] and n["starts_at_local"] == occ2["starts_at_local"] and n["reference"] == occ2["reference"]
    assert history(ada, n["reference"])[-1]["event"] == "reassigned"


def test_L4_83_stage4_export_import_round_trip_keeps_plans_closures_and_receipts():
    reset(fixture(restaurants=[restaurant(managers=["u_ada"], combinable=[["t_1", "t_2"], ["t_2", "t_3"]])]))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    d = safe_date()
    held = bob.post("/reservations", json=bd(d, "19:00", "t_2", 3), key=new_key()).json
    anchor = bob.post("/reservations", json=bd(d, "21:00", "t_3", 6), key=new_key()).json
    s = bob.post("/series", json={"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}, key=new_key()).json
    p_applied = plan_ok(ada, "r_anker", "t_2", inst(d, "18:00"), inst(d, "21:00"))
    ak = new_key()
    applied = check(apply_plan(ada, "r_anker", p_applied["plan_id"], ak), 201, "L4.83")
    ck = new_key()
    pk = new_key()
    pending = check(replan(ada, "r_anker", "t_1", inst(add_days(d, 3), "18:00"), inst(add_days(d, 3), "20:00"), pk), 201, "L4.83")
    sk = new_key()
    amended = check(bob.post(f"/series/{s['series_id']}/amend", json={"expected_revision": 1, "from_index": 1, "local_time": "20:00"}, key=sk), 201, "L4.83")
    E = call("GET", "/_test/export", timeout=10.5).json
    before = {"r": rev(ada), "res": bob.get("/reservations").json, "series": bob.get(f"/series/{s['series_id']}").json,
              "h": history(bob, held["reference"])}
    reset(fixture(users=[user("zed")], restaurants=[restaurant("r_z", name="Z")]))
    assert call("POST", "/_test/import", json=E, timeout=10.5).status == 204
    ada, bob = login("ada@example.com"), Client(bob.token)
    assert rev(ada) == before["r"] and bob.get("/reservations").json == before["res"] and bob.get(f"/series/{s['series_id']}").json == before["series"] \
        and history(bob, held["reference"]) == before["h"], "[L4.83] revisions, reservations, series and histories survive"
    assert check(apply_plan(ada, "r_anker", p_applied["plan_id"], ak), 200, "L4.83") == applied, "[L4.83] apply receipts survive"
    check(apply_plan(ada, "r_anker", p_applied["plan_id"]), 409, "L4.83", "plan_already_applied")
    assert check(replan(ada, "r_anker", "t_1", inst(add_days(d, 3), "18:00"), inst(add_days(d, 3), "20:00"), pk), 200, "L4.83") == pending, "[L4.83] preview receipts survive"
    assert check(bob.post(f"/series/{s['series_id']}/amend", json={"expected_revision": 1, "from_index": 1, "local_time": "20:00"}, key=sk), 200, "L4.83") == amended
    # the closure is still in force; a stored, unapplied plan can still be applied if its revision still matches
    check(call("POST", "/reservations", json=bd(d, "19:00", "t_2", 2), token=bob.token, headers={"Idempotency-Key": new_key()}), 409, "L4.83", "table_unavailable")
    r = apply_plan(ada, "r_anker", pending["plan_id"])
    assert r.status in (201, 409), f"[L4.83] {r!r}"                                  # READING Q3: plan survival is not asserted beyond a clean answer
    if r.status == 409:
        check(r, 409, "L4.83", "stale_plan")
