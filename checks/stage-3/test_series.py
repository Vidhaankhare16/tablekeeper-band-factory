"""Recurring reservations / series (ledger L3.50-L3.69)."""
import datetime as dt
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login,
                      slots, publish_ok, policy, terms, history, mgr_world, add_days, iso, burst, body, avail_ids, weekday_name, WEEKDAYS)

PAIRS = [["t_1", "t_2"], ["t_2", "t_3"]]


def adopt(c, ref, count=3, weeks=1, key=None):
    return c.post("/series", json={"anchor_reference": ref, "count": count, "interval_weeks": weeks}, key=new_key() if key is None else key)


def adopt_ok(c, ref, count=3, weeks=1):
    r = adopt(c, ref, count, weeks)
    assert r.status == 201, f"[L3.52] adoption should be 201: {r!r}"
    return r.json


def gs(c, sid):
    return c.get(f"/series/{sid}")


def occ_by_index(s):
    return {o["index"]: o for o in s["occurrences"]}


def night_world(tz="Europe/Berlin"):
    reset(fixture(restaurants=[restaurant(timezone=tz, hours=all_week("00:00", "23:30"), combinable=PAIRS, managers=["u_ada"])]))
    return login("ada@example.com"), login("bob@example.com")


# ---- request validation (L3.50) ------------------------------------------------------------

def test_L3_50_auth_key_and_body_shape():
    m = mgr_world()
    j = book_ok(m.ada, m.date)
    b = {"anchor_reference": j["reference"], "count": 3, "interval_weeks": 1}
    check(call("POST", "/series", json=b, key=new_key()), 401, "L3.50", "unauthenticated")
    check(call("POST", "/series", json=b, key=new_key(), token="junk"), 401, "L3.50", "unauthenticated")
    check(m.ada.post("/series", json=b), 400, "L3.50", "missing_idempotency_key")
    check(m.ada.post("/series", json=b, key=""), 400, "L3.50", "missing_idempotency_key")
    check(m.ada.post("/series", json=b, key="k" * 256), 422, "L3.50", "validation_failed")
    check(m.ada.post("/series", raw="{bad", key=new_key()), 400, "L3.50", "malformed_request")
    check(m.ada.post("/series", raw="[1]", key=new_key()), 400, "L3.50", "malformed_request")
    check(m.ada.post("/series", json={**b, "extra": 1}, key=new_key()), 201, "L3.50")             # unknown fields ignored


@pytest.mark.parametrize("name,patch,codes", [
    ("count 1", {"count": 1}, (422,)), ("count 0", {"count": 0}, (422,)), ("count 13", {"count": 13}, (422,)), ("count -3", {"count": -3}, (422,)),
    ("count true", {"count": True}, (422,)), ("count false", {"count": False}, (422,)), ("count float", {"count": 2.5}, (422,)),
    ("interval 0", {"interval_weeks": 0}, (422,)), ("interval 5", {"interval_weeks": 5}, (422,)), ("interval -1", {"interval_weeks": -1}, (422,)),
    ("interval true", {"interval_weeks": True}, (422,)), ("interval float", {"interval_weeks": 1.5}, (422,)),
    ("count string", {"count": "3"}, (400, 422)), ("interval string", {"interval_weeks": "1"}, (400, 422)), ("count list", {"count": [3]}, (400, 422)),
    ("anchor number", {"anchor_reference": 12345}, (400, 422)), ("anchor null", {"anchor_reference": None}, (400, 422)),
    ("anchor missing", {"anchor_reference": None, "_del": "anchor_reference"}, (422,)),
    ("count missing", {"_del": "count"}, (422,)), ("interval missing", {"_del": "interval_weeks"}, (422,)),
])
def test_L3_50_invalid_values(name, patch, codes):
    m = mgr_world()
    j = book_ok(m.ada, m.date)
    b = {"anchor_reference": j["reference"], "count": 3, "interval_weeks": 1}
    patch = dict(patch)
    d = patch.pop("_del", None)
    b.update({k: v for k, v in patch.items() if not (d and k == d)})
    if d:
        b.pop(d, None)
    r = m.ada.post("/series", json=b, key=new_key())
    assert r.status in codes, f"[L3.50] {name}: expected {codes}, got {r!r}"
    assert r.json["error"]["code"] in ("validation_failed", "malformed_request") and (r.status == 400) == (r.json["error"]["code"] == "malformed_request")
    assert len(m.ada.get("/reservations").json["reservations"]) == 1, "[L3.50] nothing created"
    assert check(adopt(m.ada, j["reference"], 2, 1), 201, "L3.50")["interval_weeks"] == 1       # anchor was not adopted by the failed request


def test_L3_50_boundaries_count_and_interval():
    m = mgr_world()
    d = m.date
    for i, (c, w) in enumerate([(2, 1), (12, 4), (12, 1), (2, 4)]):
        j = book_ok(m.ada, add_days(d, i), "19:00", "t_1", 2)
        s = adopt_ok(m.ada, j["reference"], c, w)
        assert len(s["occurrences"]) == c and s["interval_weeks"] == w
        want = [add_days(add_days(d, i), k * w * 7) for k in range(c)]
        assert [o["reservation"]["starts_at_local"] for o in s["occurrences"]] == [f"{x}T19:00" for x in want], \
            f"[L3.51] occurrence i starts on the anchor's local date + i*interval_weeks*7 days at the same clock time"


def test_L3_50_anchor_errors():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d)
    theirs = book_ok(m.bob, d, "19:00", "t_3", 6)
    check(adopt(m.ada, "NOPE99"), 404, "L3.50", "not_found")
    check(adopt(m.ada, theirs["reference"]), 404, "L3.50", "not_found")
    check(adopt(m.cy, j["reference"]), 404, "L3.50", "not_found")
    c = book_ok(m.ada, d, "21:00", "t_1", 2)
    m.ada.post(f"/reservations/{c['reference']}/cancel")
    check(adopt(m.ada, c["reference"]), 409, "L3.50", "reservation_cancelled")
    old = book_ok(m.ada, "2020-01-08", "19:00", "t_2", 4)
    check(adopt(m.ada, old["reference"]), 409, "L3.50", "cutoff_passed")
    s = adopt_ok(m.ada, j["reference"], 3, 1)
    check(adopt(m.ada, j["reference"], 3, 1), 409, "L3.50", "already_in_series")                 # new key, same anchor
    check(adopt(m.ada, j["reference"], 2, 2), 409, "L3.50", "already_in_series")
    gen = s["occurrences"][1]["reference"]
    check(adopt(m.ada, gen, 2, 1), 409, "L3.50", "already_in_series")                             # a generated occurrence is adopted too
    check(adopt(m.bob, j["reference"]), 404, "L3.50", "not_found")


def test_L3_50_anchor_must_satisfy_its_accepted_cutoff():
    reset(fixture(restaurants=[restaurant("r_utc", timezone="UTC", slot=30, dur=30, cutoff=10080, hours=all_week("00:00", "23:30"))]))
    a = login("ada@example.com")
    near = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=3)).isoformat()
    j = book_ok(a, near, "12:00", "t_1", 2, "r_utc")                     # accepted cutoff: 7 days, so a 3-day-out anchor is inside it
    check(adopt(a, j["reference"]), 409, "L3.50", "cutoff_passed")
    assert len(a.get("/reservations").json["reservations"]) == 1


# ---- creation (L3.51-L3.54) ----------------------------------------------------------------

def test_L3_51_shape_dates_and_anchor_is_occurrence_zero():
    m = mgr_world()
    d = m.date
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    pre = (m.ada.get(f"/reservations/{anchor['reference']}").json, history(m.ada, anchor["reference"]))
    r = adopt(m.ada, anchor["reference"], 4, 2)
    s = check(r, 201, "L3.51")
    assert set(s) == {"series_id", "revision", "interval_weeks", "occurrences"} and isinstance(s["series_id"], str) and s["series_id"] \
        and s["revision"] == 1 and s["interval_weeks"] == 2, f"[L3.51] {sorted(s)}"
    occ = s["occurrences"]
    assert [o["index"] for o in occ] == [0, 1, 2, 3], "[L3.51] all count occurrences in index order"
    for o in occ:
        assert set(o) == {"index", "reference", "exception", "reservation"} and o["exception"] is False and o["reservation"]["reference"] == o["reference"]
    assert occ[0]["reservation"] == anchor and occ[0]["reference"] == anchor["reference"], \
        "[L3.51] occurrence zero is the anchor itself: reference, identity, revision, terms, timestamps unchanged"
    assert (m.ada.get(f"/reservations/{anchor['reference']}").json, history(m.ada, anchor["reference"])) == pre, "[L3.51] anchor history unchanged"
    refs = [o["reference"] for o in occ]
    ids = [o["reservation"]["reservation_id"] for o in occ]
    assert len(set(refs)) == 4 and len(set(ids)) == 4, "[L3.51] distinct ordinary references and identities"
    for i, o in enumerate(occ):
        r_ = o["reservation"]
        want = add_days(d, i * 14)
        assert r_["starts_at_local"] == f"{want}T19:00" and r_["table_id"] == "t_2" and r_["table_ids"] == ["t_2"] and r_["party_size"] == 4 \
            and r_["status"] == "confirmed" and r_["revision"] == 1 and r_["accepted_terms"] == anchor["accepted_terms"], f"[L3.51] occurrence {i}: {r_}"
        assert mins(r_) == 90
    assert check(gs(m.ada, s["series_id"]), 200, "L3.51") == s, "[L3.51] GET /series/{id} returns this shape with current states"
    lst = m.ada.get("/reservations").json["reservations"]
    assert {x["reference"] for x in lst} == set(refs) and len(lst) == 4, "[L3.51] occurrences appear in ordinary reservation lists"
    for i, o in enumerate(occ[1:], 1):
        assert avail_ids(add_days(d, i * 14), "19:00", 4) == ["t_3"], "[L3.51] occurrences occupy their tables"
        e = history(m.ada, o["reference"])
        assert len(e) == 1 and e[0]["event"] == "created" and e[0]["revision"] == 1 and e[0]["changes"][0] == {"field": "table_id", "from": None, "to": "t_2"}, \
            f"[L3.51] ordinary histories: {e}"
        assert m.ada.get(f"/reservations/{o['reference']}").json == o["reservation"]
        assert m.bob.get(f"/reservations/{o['reference']}").status == 404


def mins(r):
    return int((iso(r["ends_at"]) - iso(r["starts_at"])).total_seconds() // 60)


def test_L3_52_owner_only_reads():
    m = mgr_world()
    s = adopt_ok(m.ada, book_ok(m.ada, m.date)["reference"], 2, 1)
    check(gs(m.bob, s["series_id"]), 404, "L3.52", "not_found")
    check(call("GET", f"/series/{s['series_id']}"), 404, "L3.52", "not_found")
    check(call("GET", f"/series/{s['series_id']}", headers={"Authorization": "Bearer junk"}), 404, "L3.52", "not_found")
    check(gs(m.ada, "nope"), 404, "L3.52", "not_found")
    check(call("GET", "/series/nope"), 404, "L3.52", "not_found")
    check(gs(m.ada, s["series_id"]), 200, "L3.52")


def test_L3_53_anchor_with_combination_replicates_the_pair():
    m = mgr_world()
    d = m.date
    anchor = check(m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{d}T19:00", "party_size": 6},
                              key=new_key()), 201, "L3.53")
    s = adopt_ok(m.ada, anchor["reference"], 3, 1)
    for o in s["occurrences"]:
        r = o["reservation"]
        assert sorted(r["table_ids"]) == ["t_1", "t_2"] and "table_id" not in r and r["party_size"] == 6, f"[L3.53] same table selection and party: {r}"
    e = history(m.ada, s["occurrences"][1]["reference"])
    assert e[0]["changes"][0] == {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]}, f"[L3.53/L3.80] pair creation names table_ids: {e[0]['changes']}"
    assert avail_ids(add_days(d, 7), "19:00", 1) == ["t_3"]


# ---- per-occurrence policy and ordinary rules (L3.54-L3.57) --------------------------------

def test_L3_54_each_occurrence_selects_its_dates_policy():
    m = mgr_world()
    d = m.date
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    publish_ok(m.ada, "r_anker", policy(add_days(d, 14), reservation_duration_minutes=60))        # applies from occurrence 2 (interval 1w)
    s = adopt_ok(m.ada, anchor["reference"], 4, 1)
    occ = s["occurrences"]
    assert [o["reservation"]["accepted_terms"]["policy_version"] for o in occ] == [0, 0, 1, 1]
    assert [mins(o["reservation"]) for o in occ] == [90, 90, 60, 60], "[L3.54] each generated occurrence independently selects its date's policy, including duration"
    assert occ[2]["reservation"]["accepted_terms"] == terms(policy(add_days(d, 14), reservation_duration_minutes=60), 1)
    assert occ[0]["reservation"] == anchor, "[L3.51] the anchor keeps its own terms"


def test_L3_54_failures_are_all_or_nothing_and_first_failing_occurrence_decides():
    m = mgr_world()
    d = m.date
    wd = lambda n: weekday_name(add_days(d, n))
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    # occurrence 1: taken by someone else (409); occurrence 2: closed by policy (422) -> index order => 409
    book_ok(m.bob, add_days(d, 7), "19:00", "t_2", 4)
    other = [x for x in WEEKDAYS if x != wd(14)][0]
    publish_ok(m.ada, "r_anker", policy(add_days(d, 14), opening_hours=[{"weekday": other, "opens": "18:00", "closes": "23:00"}]))
    snapshot = lambda: (m.ada.get("/reservations").json, m.bob.get("/reservations").json,
                        history(m.ada, anchor["reference"]), m.ada.get(f"/reservations/{anchor['reference']}/decision").json)
    pre = snapshot()
    check(adopt(m.ada, anchor["reference"], 4, 1), 409, "L3.54", "table_unavailable")
    assert snapshot() == pre, "[L3.54] no partial series, reservations, histories survive a failure"
    # swap the roles: occurrence 1 closed (422), occurrence 2 taken (409) => 422 first
    m2 = mgr_world()
    a2 = book_ok(m2.ada, d, "19:00", "t_2", 4)
    other1 = [x for x in WEEKDAYS if x != wd(7)][0]
    publish_ok(m2.ada, "r_anker", policy(add_days(d, 7), opening_hours=[{"weekday": other1, "opens": "18:00", "closes": "23:00"}]))
    publish_ok(m2.ada, "r_anker", policy(add_days(d, 8), opening_hours=all_week("18:00", "23:00")))
    book_ok(m2.bob, add_days(d, 14), "19:00", "t_2", 4)
    check(adopt(m2.ada, a2["reference"], 4, 1), 422, "L3.54", "outside_opening_hours")
    assert len(m2.ada.get("/reservations").json["reservations"]) == 1


@pytest.mark.parametrize("name,pol,code", [
    ("capacity", dict(capacities={"t_1": 2, "t_2": 3, "t_3": 6}), "party_exceeds_capacity"),
    ("grid", dict(slot_minutes=45), "not_on_slot_grid"),
    ("hours end", dict(opening_hours=all_week("18:00", "20:00")), "outside_opening_hours"),
])
def test_L3_54_ordinary_rules_apply_to_each_generated_occurrence(name, pol, code):
    m = mgr_world()
    d = m.date
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    publish_ok(m.ada, "r_anker", policy(add_days(d, 7), **pol))
    pre = m.ada.get("/reservations").json
    check(adopt(m.ada, anchor["reference"], 3, 1), 422, f"L3.54 ({name})", code)
    assert m.ada.get("/reservations").json == pre
    assert m.ada.get(f"/reservations/{anchor['reference']}/decision").json["revision"] == 1
    check(adopt(m.ada, anchor["reference"], 2, 4), 422, f"L3.54 ({name})", code)       # not already_in_series: the failed adoption left no claim behind


def test_L3_55_nonexistent_local_time_rejects_the_whole_adoption():
    a, b = night_world("Europe/Berlin")
    anchor = book_ok(a, "2028-03-19", "02:30", "t_1", 2)                         # Sunday; next Sunday 2028-03-26 has no 02:30 in Berlin
    pre = a.get("/reservations").json
    check(adopt(a, anchor["reference"], 3, 1), 422, "L3.55", "invalid_local_time")
    check(adopt(a, anchor["reference"], 12, 1), 422, "L3.55", "invalid_local_time")
    assert a.get("/reservations").json == pre and len(history(a, anchor["reference"])) == 1, "[L3.55] all-or-nothing"
    assert check(adopt(a, anchor["reference"], 2, 2), 201, "L3.55")["occurrences"][1]["reservation"]["starts_at_local"] == "2028-04-02T02:30"
    a, b = night_world("America/New_York")
    anchor = book_ok(a, "2028-03-05", "02:30", "t_1", 2)                         # NY: 2028-03-12 02:30 does not exist
    check(adopt(a, anchor["reference"], 2, 1), 422, "L3.55", "invalid_local_time")
    assert len(a.get("/reservations").json["reservations"]) == 1


def test_L3_55_repeated_local_time_uses_the_first_occurrence():
    a, b = night_world("Europe/Berlin")
    anchor = book_ok(a, "2028-10-22", "02:30", "t_1", 2)                         # 2028-10-29 02:30 happens twice in Berlin
    s = adopt_ok(a, anchor["reference"], 2, 1)
    r = s["occurrences"][1]["reservation"]
    assert r["starts_at_local"] == "2028-10-29T02:30" and r["starts_at"] == "2028-10-29T02:30:00+02:00" and r["ends_at"] == "2028-10-29T03:00:00+01:00", \
        f"[L3.55] repeated times use stage 1's first-occurrence rule, and duration is absolute: {r}"
    a, b = night_world("America/New_York")
    anchor = book_ok(a, "2028-10-29", "01:30", "t_1", 2)                         # 2028-11-05 01:30 happens twice in New York
    s = adopt_ok(a, anchor["reference"], 2, 1)
    assert s["occurrences"][1]["reservation"]["starts_at"] == "2028-11-05T01:30:00-04:00", "[L3.55] first occurrence (EDT)"


# ---- exceptions and revisions (L3.56-L3.60) ----------------------------------------------

def series_of(m, count=4, weeks=1, at="19:00", table="t_2", party=4):
    anchor = book_ok(m.ada, m.date, at, table, party)
    return adopt_ok(m.ada, anchor["reference"], count, weeks)


def test_L3_56_real_patch_marks_exception_and_bumps_series_revision_once():
    m = mgr_world()
    s = series_of(m)
    sid, occ = s["series_id"], s["occurrences"]
    r2 = occ[2]["reference"]
    check(m.ada.patch(f"/reservations/{r2}", json={"party_size": 3}), 200, "L3.56")
    g = check(gs(m.ada, sid), 200, "L3.56")
    assert g["revision"] == 2, "[L3.56] a real individual PATCH increments the series revision once"
    o = occ_by_index(g)
    assert [o[i]["exception"] for i in range(4)] == [False, False, True, False], "[L3.56] marks that occurrence permanently"
    assert o[2]["reservation"]["party_size"] == 3 and o[2]["reservation"]["revision"] == 2 and o[2]["reference"] == r2, "[L3.56] references/indices never change"
    # a PATCH changing date and table keeps index and reference
    d5 = add_days(m.date, 3)
    check(m.ada.patch(f"/reservations/{r2}", json={"starts_at_local": f"{d5}T20:00", "table_id": "t_3"}), 200, "L3.56")
    g = gs(m.ada, sid).json
    o = occ_by_index(g)
    assert g["revision"] == 3 and o[2]["reference"] == r2 and o[2]["reservation"]["starts_at_local"] == f"{d5}T20:00" and o[2]["reservation"]["table_id"] == "t_3" \
        and o[2]["exception"] is True, "[L3.56] each real amendment bumps the series revision once; the flag stays true"
    # no-op and failed PATCHes change neither
    r1 = occ[1]["reference"]
    check(m.ada.patch(f"/reservations/{r1}", json={}), 200, "L3.56")
    check(m.ada.patch(f"/reservations/{r1}", json={"party_size": 4}), 200, "L3.56")
    check(m.ada.patch(f"/reservations/{r1}", json={"party_size": 99}), 422, "L3.56", "party_exceeds_capacity")
    check(m.ada.patch(f"/reservations/{r1}", json={"party_size": 2, "expected_revision": 5}), 409, "L3.56", "stale_revision")
    check(m.bob.patch(f"/reservations/{r1}", json={"party_size": 2}), 404, "L3.56", "not_found")
    g2 = gs(m.ada, sid).json
    assert g2 == g, "[L3.56] a no-op or a failed PATCH changes neither the series revision nor any exception flag"
    # expected_revision works on occurrences
    check(m.ada.patch(f"/reservations/{r1}", json={"party_size": 2, "expected_revision": 1}), 200, "L3.56")
    g3 = gs(m.ada, sid).json
    assert g3["revision"] == 4 and occ_by_index(g3)[1]["exception"] is True


def test_L3_57_cancel_bumps_series_revision_once_without_exception():
    m = mgr_world()
    s = series_of(m)
    sid, occ = s["series_id"], s["occurrences"]
    r3 = occ[3]["reference"]
    check(m.ada.post(f"/reservations/{r3}/cancel"), 200, "L3.57")
    g = gs(m.ada, sid).json
    o = occ_by_index(g)
    assert g["revision"] == 2 and len(g["occurrences"]) == 4, "[L3.57] cancellation increments the series revision once, retaining the cancelled occurrence"
    assert o[3]["reservation"]["status"] == "cancelled" and o[3]["exception"] is False and o[3]["reference"] == r3, "[L3.57] cancelled but not an exception"
    check(m.ada.post(f"/reservations/{r3}/cancel"), 200, "L3.57")
    assert gs(m.ada, sid).json == g, "[L3.57] repeated cancel does nothing"
    check(m.ada.patch(f"/reservations/{r3}", json={"party_size": 2}), 409, "L3.57", "reservation_cancelled")
    check(m.ada.patch(f"/reservations/{r3}", json={}), 409, "L3.57", "reservation_cancelled")
    assert gs(m.ada, sid).json == g, "[L3.57] a refused PATCH of a cancelled occurrence changes nothing"
    assert avail_ids(add_days(m.date, 3), "19:00", 4) == ["t_2", "t_3"], "[L3.57] the cancelled occurrence frees its table"


def test_L3_58_cancelling_or_changing_the_anchor_does_not_touch_siblings():
    m = mgr_world()
    s = series_of(m)
    sid, occ = s["series_id"], s["occurrences"]
    anchor = occ[0]["reference"]
    check(m.ada.post(f"/reservations/{anchor}/cancel"), 200, "L3.58")
    g = gs(m.ada, sid).json
    o = occ_by_index(g)
    assert o[0]["reservation"]["status"] == "cancelled" and all(o[i]["reservation"]["status"] == "confirmed" for i in (1, 2, 3)), \
        "[L3.58] cancelling the anchor does not cancel its siblings"
    assert g["revision"] == 2 and not any(x["exception"] for x in g["occurrences"])
    m2 = mgr_world()
    s2 = series_of(m2)
    check(m2.ada.patch(f"/reservations/{s2['occurrences'][0]['reference']}", json={"party_size": 2}), 200, "L3.58")
    g = gs(m2.ada, s2["series_id"]).json
    assert occ_by_index(g)[0]["exception"] is True and g["revision"] == 2, "[L3.56/L3.58] a real PATCH of the anchor marks index 0"


def test_L3_59_cutoff_and_revision_checks_apply_to_occurrences():
    reset(fixture(restaurants=[restaurant("r_utc", timezone="UTC", slot=30, dur=30, cutoff=10080, hours=all_week("00:00", "23:30"))]))
    a = login("ada@example.com")
    far = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)).isoformat()
    anchor = book_ok(a, far, "12:00", "t_1", 2, "r_utc")
    s = adopt_ok(a, anchor["reference"], 3, 1)
    # 1w, 2w after a 30-day-out anchor are still > 7 days away: editable. Make one inside the window by moving the *anchor* of nothing: use stale check
    r1 = s["occurrences"][1]["reference"]
    check(a.patch(f"/reservations/{r1}", json={"party_size": 3, "expected_revision": 9}), 409, "L3.59", "stale_revision")
    g = gs(a, s["series_id"]).json
    assert g["revision"] == 1 and all(o["exception"] is False for o in g["occurrences"])


def test_L3_60_series_reads_are_current_states_and_survive_cancelled_everything():
    m = mgr_world()
    s = series_of(m, 3, 1)
    for o in s["occurrences"]:
        m.ada.post(f"/reservations/{o['reference']}/cancel")
    g = gs(m.ada, s["series_id"]).json
    assert g["revision"] == 4 and [o["reservation"]["status"] for o in g["occurrences"]] == ["cancelled"] * 3 and g["revision"] == 1 + 3


# ---- replay and concurrency (L3.61-L3.63) --------------------------------------------------

def test_L3_61_replay_returns_the_original_and_changes_no_counter():
    m = mgr_world()
    d = m.date
    anchor = book_ok(m.ada, d, "19:00", "t_2", 4)
    key = new_key()
    b = {"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}
    first = check(m.ada.post("/series", json=b, key=key), 201, "L3.61")
    m.ada.patch(f"/reservations/{first['occurrences'][1]['reference']}", json={"party_size": 2})
    m.ada.post(f"/reservations/{first['occurrences'][2]['reference']}/cancel")
    cur = gs(m.ada, first["series_id"]).json
    assert cur["revision"] == 3
    for _ in range(2):
        rep = check(m.ada.post("/series", json=b, key=key), 200, "L3.61")
        assert rep == first and rep["revision"] == 1 and all(o["exception"] is False for o in rep["occurrences"]), \
            "[L3.61] replays return the original series response, even after later changes"
    assert gs(m.ada, first["series_id"]).json == cur, "[L3.61] a replay changes no counter or flag"
    assert len(m.ada.get("/reservations").json["reservations"]) == 3
    check(m.ada.post("/series", json={**b, "count": 4}, key=key), 409, "L3.61", "idempotency_key_reuse")
    check(m.ada.post("/series", json={"anchor_reference": "x", "count": 99}, key=key), 409, "L3.61", "idempotency_key_reuse")
    check(m.bob.post("/series", json=b, key=key), 404, "L3.61", "not_found")                          # keys are per user
    raw = '{"interval_weeks":1,  "count":3, "anchor_reference":"%s"}' % anchor["reference"]
    assert check(m.ada.post("/series", raw=raw, key=key), 200, "L3.61") == first


def test_L3_61_failed_adoption_key_is_reusable():
    m = mgr_world()
    anchor = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    key = new_key()
    check(m.ada.post("/series", json={"anchor_reference": anchor["reference"], "count": 1, "interval_weeks": 1}, key=key), 422, "L3.61", "validation_failed")
    check(m.ada.post("/series", json={"anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1}, key=key), 201, "L3.61")


def test_L3_62_concurrent_identical_adoptions_create_one_series():
    m = mgr_world()
    anchor = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    key = new_key()
    b = {"anchor_reference": anchor["reference"], "count": 8, "interval_weeks": 1}
    out = burst(30, lambda i: m.ada.post("/series", json=b, key=key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 29 + [201], f"[L3.62] exactly one 201, the rest 200: {codes.count(201)}x201 {sorted(set(codes))}"
    assert all(r.json == out[0].json for r in out) and len(out[0].json["occurrences"]) == 8
    assert len(m.ada.get("/reservations").json["reservations"]) == 8, "[L3.62] the operation takes effect once"


def test_L3_62_concurrent_adoptions_of_one_anchor_with_distinct_keys():
    m = mgr_world()
    anchor = book_ok(m.ada, m.date, "19:00", "t_2", 4)
    out = burst(30, lambda i: adopt(m.ada, anchor["reference"], 5, 1 + i % 4))
    codes = [r.status for r in out]
    assert codes.count(201) == 1 and codes.count(409) == 29, f"[L3.62] one adoption wins, the rest are already_in_series: {sorted(set(codes))}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L3.62", "already_in_series")
    assert len(m.ada.get("/reservations").json["reservations"]) == 5


def test_L3_63_concurrent_adoptions_competing_for_the_same_slots():
    m = mgr_world()
    d = m.date
    a1 = book_ok(m.ada, d, "19:00", "t_2", 4)
    a2 = book_ok(m.bob, add_days(d, 0), "19:00", "t_3", 4)
    # same occurrences' tables differ, so both succeed; then two anchors fight for the very same future slot via a PATCH-built clash
    out = burst(2, lambda i: adopt(m.ada if i == 0 else m.bob, (a1 if i == 0 else a2)["reference"], 6, 1))
    assert all(r.status == 201 for r in out)
    r1 = m.ada.get("/reservations").json["reservations"]
    r2 = m.bob.get("/reservations").json["reservations"]
    seen = set()
    for r in r1 + r2:
        for t in r["table_ids"]:
            k = (t, r["starts_at_local"])
            assert k not in seen, f"[L3.63/L1.1] double booking {k}"
            seen.add(k)
