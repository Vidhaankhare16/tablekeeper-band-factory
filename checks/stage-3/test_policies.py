"""Booking policies and accepted terms (ledger L3.20-L3.39)."""
import datetime as dt
import pytest
from conftest import (call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, new_key, local, login,
                      slots, publish, publish_ok, policy, terms, history, mgr_world, add_days, weekday_name, iso, burst, WEEKDAYS, body)

P0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
      "opening_hours": all_week("18:00", "23:00"), "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def two_managed():
    fx = fixture(restaurants=[restaurant(managers=["u_ada", "u_bob"], combinable=[["t_1", "t_2"], ["t_2", "t_3"]]),
                              restaurant("r_two", name="Zwei", managers=["u_ada"], tables=[{"id": "t_x1", "label": "X1", "capacity": 4}])])
    reset(fx)
    return login("ada@example.com"), login("bob@example.com"), login("cy@example.com"), safe_date()


def pol2(eff, **o):
    p = policy(eff, capacities={"t_x1": 6})
    p.update(o)
    return p


# ---- permissions (L3.20) -------------------------------------------------------------------

def test_L3_20_manager_check_403_401_404():
    m = mgr_world()
    p = policy(m.date)
    check(publish(m.bob, "r_anker", p), 403, "L3.20", "forbidden")
    check(publish(m.cy, "r_anker", p), 403, "L3.20", "forbidden")
    check(publish(m.ada, "r_two", pol2(m.date)), 403, "L3.20", "forbidden")          # r_two declares no managers (default [])
    check(call("POST", "/restaurants/r_anker/policies", json=p, key=new_key()), 401, "L3.20", "unauthenticated")
    check(call("POST", "/restaurants/r_anker/policies", json=p, key=new_key(), token="junk"), 401, "L3.20", "unauthenticated")
    check(publish(m.ada, "r_ghost", p), 404, "L3.20", "not_found")
    check(publish(m.bob, "r_ghost", p), 404, "L3.20", "not_found")
    assert call("GET", "/restaurants/r_anker/policies").json == {"policies": []}, "[L3.20] refused publications leave no policy"
    check(publish(m.ada, "r_anker", p), 201, "L3.20")


def test_L3_20_default_managers_is_empty_and_multiple_managers_allowed():
    reset(fixture(restaurants=[restaurant()]))                                       # no manager_user_ids at all
    a = login("ada@example.com")
    check(publish(a, "r_anker", policy(safe_date())), 403, "L3.20", "forbidden")
    ada, bob, cy, d = two_managed()
    check(publish(ada, "r_anker", policy(d)), 201, "L3.20")
    check(publish(bob, "r_anker", policy(d, reservation_duration_minutes=60)), 201, "L3.20")
    check(publish(cy, "r_anker", policy(d)), 403, "L3.20", "forbidden")
    check(publish(bob, "r_two", pol2(d)), 403, "L3.20", "forbidden")


def test_L3_20_idempotency_key_required_and_ranged():
    m = mgr_world()
    p = policy(m.date)
    check(m.ada.post("/restaurants/r_anker/policies", json=p), 400, "L3.20", "missing_idempotency_key")
    check(m.ada.post("/restaurants/r_anker/policies", json=p, key=""), 400, "L3.20", "missing_idempotency_key")
    check(publish(m.ada, "r_anker", p, key="x" * 256), 422, "L3.20", "validation_failed")
    check(publish(m.ada, "r_anker", p, key="x" * 255), 201, "L3.20")
    check(m.ada.post("/restaurants/r_anker/policies", raw="{bad", key=new_key()), 400, "L3.20", "malformed_request")
    check(m.ada.post("/restaurants/r_anker/policies", raw="[1]", key=new_key()), 400, "L3.20", "malformed_request")
    assert len(call("GET", "/restaurants/r_anker/policies").json["policies"]) == 1


# ---- versions, replay, validation (L3.21-L3.24) --------------------------------------------

def test_L3_21_response_and_version_allocation_per_restaurant():
    ada, bob, cy, d = two_managed()
    p1, p2 = policy(d, reservation_duration_minutes=100), policy(add_days(d, 1), slot_minutes=15)
    r = publish(ada, "r_anker", p1)
    j = check(r, 201, "L3.21")
    assert j["policy_version"] == 1 and all(j[k] == v for k, v in p1.items()), f"[L3.21] the supplied policy plus policy_version: {j}"
    assert check(publish(ada, "r_anker", p2), 201, "L3.21")["policy_version"] == 2
    assert check(publish(ada, "r_two", pol2(d)), 201, "L3.21")["policy_version"] == 1, "[L3.21] versions are per restaurant"
    assert check(publish(bob, "r_anker", policy(d)), 201, "L3.21")["policy_version"] == 3
    assert check(publish(ada, "r_two", pol2(d)), 201, "L3.21")["policy_version"] == 2


def test_L3_22_replay_reuse_and_failures_allocate_no_version():
    m = mgr_world()
    d = m.date
    p, key = policy(d, reservation_duration_minutes=100), new_key()
    first = check(publish(m.ada, "r_anker", p, key), 201, "L3.22")
    assert check(publish(m.ada, "r_anker", p, key), 200, "L3.22") == first, "[L3.22] replay returns the original 201 body with 200"
    assert check(m.ada.post("/restaurants/r_anker/policies", raw=__import__("json").dumps(dict(reversed(list(p.items())))), key=key), 200, "L3.22") == first
    check(publish(m.ada, "r_anker", policy(d, slot_minutes=15), key), 409, "L3.22", "idempotency_key_reuse")
    check(publish(m.ada, "r_anker", {"effective_from": "garbage"}, key), 409, "L3.22", "idempotency_key_reuse")     # §7 precedence
    bad = new_key()
    check(publish(m.ada, "r_anker", policy(d, slot_minutes=0), bad), 422, "L3.22", "validation_failed")
    check(publish(m.bob, "r_anker", policy(d), new_key()), 403, "L3.22", "forbidden")
    check(publish(m.ada, "r_ghost", policy(d), new_key()), 404, "L3.22", "not_found")
    nxt = check(publish(m.ada, "r_anker", policy(d, slot_minutes=15), bad), 201, "L3.22")       # failed key = first use
    assert nxt["policy_version"] == 2, f"[L3.22] failed writes and replays allocate no version: got {nxt['policy_version']}"
    assert [x["policy_version"] for x in call("GET", "/restaurants/r_anker/policies").json["policies"]] == [1, 2]


def test_L3_22_other_users_same_key_is_independent():
    ada, bob, cy, d = two_managed()
    check(publish(ada, "r_anker", policy(d), "shared"), 201, "L3.22")
    j = check(publish(bob, "r_anker", policy(d, slot_minutes=15), "shared"), 201, "L3.22")
    assert j["policy_version"] == 2


def test_L3_22_concurrent_identical_publications_exactly_one_version():
    m = mgr_world()
    p, key = policy(m.date, reservation_duration_minutes=77), new_key()
    out = burst(30, lambda i: publish(m.ada, "r_anker", p, key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 29 + [201], f"[L3.22] exactly one 201 and the rest 200: {codes.count(201)}x201 {sorted(set(codes))}"
    assert all(r.json == out[0].json for r in out) and out[0].json["policy_version"] == 1
    assert len(call("GET", "/restaurants/r_anker/policies").json["policies"]) == 1


def test_L3_22_concurrent_distinct_publications_get_distinct_consecutive_versions():
    m = mgr_world()
    out = burst(30, lambda i: publish(m.ada, "r_anker", policy(add_days(m.date, i), reservation_duration_minutes=10 + i)))
    assert all(r.status == 201 for r in out), [r.status for r in out]
    assert sorted(r.json["policy_version"] for r in out) == list(range(1, 31)), "[L3.21/L3.22] versions 1..30, each exactly once"
    listed = call("GET", "/restaurants/r_anker/policies").json["policies"]
    assert [x["policy_version"] for x in listed] == list(range(1, 31)), "[L3.25] listed in publication order = version order"


STRICT_422 = {
    "effective_from not a date": {"effective_from": "2026-02-30"}, "effective_from 9-28": {"effective_from": "2026-9-28"},
    "effective_from empty": {"effective_from": ""}, "effective_from dmy": {"effective_from": "28-09-2026"},
    "effective_from datetime": {"effective_from": "2026-09-28T00:00"}, "effective_from month 13": {"effective_from": "2026-13-01"},
    "slot 0": {"slot_minutes": 0}, "slot 1441": {"slot_minutes": 1441}, "slot -1": {"slot_minutes": -1}, "slot true": {"slot_minutes": True},
    "slot false": {"slot_minutes": False}, "slot float": {"slot_minutes": 30.5},
    "duration 0": {"reservation_duration_minutes": 0}, "duration 1441": {"reservation_duration_minutes": 1441},
    "duration true": {"reservation_duration_minutes": True}, "duration float": {"reservation_duration_minutes": 90.5},
    "cutoff -1": {"cancellation_cutoff_minutes": -1}, "cutoff 10081": {"cancellation_cutoff_minutes": 10081},
    "cutoff true": {"cancellation_cutoff_minutes": True}, "cutoff float": {"cancellation_cutoff_minutes": 0.5},
    "duplicate weekday": {"opening_hours": [{"weekday": "mon", "opens": "18:00", "closes": "20:00"}, {"weekday": "mon", "opens": "21:00", "closes": "23:00"}]},
    "bad weekday": {"opening_hours": [{"weekday": "xyz", "opens": "18:00", "closes": "20:00"}]},
    "opens == closes": {"opening_hours": [{"weekday": "mon", "opens": "18:00", "closes": "18:00"}]},
    "closes before opens": {"opening_hours": [{"weekday": "mon", "opens": "20:00", "closes": "18:00"}]},
    "time 25:00": {"opening_hours": [{"weekday": "mon", "opens": "18:00", "closes": "25:00"}]},
    "time 9:00": {"opening_hours": [{"weekday": "mon", "opens": "9:00", "closes": "20:00"}]},
    "time with seconds": {"opening_hours": [{"weekday": "mon", "opens": "18:00:00", "closes": "20:00"}]},
    "capacities missing table": {"capacities": {"t_1": 2, "t_2": 4}}, "capacities extra table": {"capacities": {"t_1": 2, "t_2": 4, "t_3": 6, "t_4": 2}},
    "capacities unknown instead": {"capacities": {"t_1": 2, "t_2": 4, "t_9": 6}}, "capacities empty": {"capacities": {}},
    "capacity 0": {"capacities": {"t_1": 0, "t_2": 4, "t_3": 6}}, "capacity 101": {"capacities": {"t_1": 2, "t_2": 101, "t_3": 6}},
    "capacity true": {"capacities": {"t_1": True, "t_2": 4, "t_3": 6}}, "capacity float": {"capacities": {"t_1": 2.5, "t_2": 4, "t_3": 6}},
    "capacity negative": {"capacities": {"t_1": -2, "t_2": 4, "t_3": 6}},
}


@pytest.mark.parametrize("name", sorted(STRICT_422))
def test_L3_23_invalid_policy_is_422_and_changes_nothing(name):
    m = mgr_world()
    d = m.date
    check(publish(m.ada, "r_anker", policy(d, **STRICT_422[name])), 422, f"L3.23 ({name})", "validation_failed")
    assert call("GET", "/restaurants/r_anker/policies").json == {"policies": []}, f"[L3.23] {name}: no policy stored"
    assert publish_ok(m.ada, "r_anker", policy(d))["policy_version"] == 1, f"[L3.23] {name}: no version consumed"


@pytest.mark.parametrize("field", ["effective_from", "slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes",
                                   "opening_hours", "capacities"])
def test_L3_23_every_field_is_required(field):
    m = mgr_world()
    p = policy(m.date)
    del p[field]
    check(publish(m.ada, "r_anker", p), 422, f"L3.23 (missing {field})", "validation_failed")
    assert publish_ok(m.ada, "r_anker", policy(m.date))["policy_version"] == 1


@pytest.mark.parametrize("name,patch", [("slot string", {"slot_minutes": "30"}), ("duration list", {"reservation_duration_minutes": [90]}),
                                        ("cutoff string", {"cancellation_cutoff_minutes": "120"}), ("hours object", {"opening_hours": {"mon": 1}}),
                                        ("hours string", {"opening_hours": "always"}), ("capacities list", {"capacities": [2, 4, 6]}),
                                        ("capacities string", {"capacities": "x"}), ("capacity string", {"capacities": {"t_1": "2", "t_2": 4, "t_3": 6}}),
                                        ("effective number", {"effective_from": 20260928}), ("hours item string", {"opening_hours": ["mon"]})])
def test_L3_23_wrong_json_types_are_rejected_without_effect(name, patch):
    # READING P1: §5 says a field of the wrong JSON type is 400 malformed_request, §policies says invalid policy is 422; both are accepted.
    m = mgr_world()
    r = publish(m.ada, "r_anker", policy(m.date, **patch))
    assert r.status in (400, 422) and r.json["error"]["code"] in ("malformed_request", "validation_failed"), f"[L3.23] {name}: {r!r}"
    assert (r.status == 400) == (r.json["error"]["code"] == "malformed_request")
    assert call("GET", "/restaurants/r_anker/policies").json == {"policies": []}


def test_L3_23_boundary_values_are_valid():
    m = mgr_world()
    ok = [{"slot_minutes": 1}, {"slot_minutes": 1440}, {"reservation_duration_minutes": 1}, {"reservation_duration_minutes": 1440},
          {"cancellation_cutoff_minutes": 0}, {"cancellation_cutoff_minutes": 10080}, {"capacities": {"t_1": 1, "t_2": 1, "t_3": 1}},
          {"capacities": {"t_1": 100, "t_2": 100, "t_3": 100}}, {"effective_from": "2028-02-29"}, {"effective_from": "1999-01-01"},
          {"opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:59"} for d in WEEKDAYS]},
          {"opening_hours": [{"weekday": "mon", "opens": "00:00", "closes": "00:01"}]}]
    for i, o in enumerate(ok, 1):
        j = check(publish(m.ada, "r_anker", policy(m.date, **o)), 201, f"L3.23 boundary {o}")
        assert j["policy_version"] == i


def test_L3_24_unknown_fields_ignored_and_structure_cannot_change():
    m = mgr_world()
    d = m.date
    p = policy(d, junk=[1, 2], timezone="Asia/Tokyo", name="Hijacked", combinable=[["t_1", "t_3"]], manager_user_ids=["u_cy"],
               tables=[{"id": "t_9", "label": "9", "capacity": 50}], id="r_other")
    check(publish(m.ada, "r_anker", p), 201, "L3.24")
    det = call("GET", "/restaurants/r_anker").json
    src = m.fx["restaurants"][0]
    assert det["timezone"] == "Europe/Berlin" and det["name"] == "Zum Anker" and [t["id"] for t in det["tables"]] == ["t_1", "t_2", "t_3"] \
        and det.get("combinable") == [["t_1", "t_2"], ["t_2", "t_3"]], f"[L3.24] table ids, labels, timezone and combinations cannot change: {det}"
    assert call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2").json["timezone"] == "Europe/Berlin"
    check(publish(m.cy, "r_anker", policy(d)), 403, "L3.24", "forbidden")        # managers list not changed either
    check(book(m.ada, d, "19:00", "t_2", 3), 201, "L3.24")
    check(m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_3"], "starts_at_local": f"{d}T21:00", "party_size": 4},
                     key=new_key()), 422, "L3.24", "combination_not_allowed")


# ---- listing and detail (L3.25-L3.27) ------------------------------------------------------

def test_L3_25_listing_is_public_ordered_and_omits_policy_zero():
    m = mgr_world()
    d = m.date
    assert check(call("GET", "/restaurants/r_anker/policies"), 200, "L3.25") == {"policies": []}, "[L3.25] policy 0 is omitted"
    ps = [policy(add_days(d, 10), reservation_duration_minutes=100), policy(add_days(d, 5), reservation_duration_minutes=60),
          policy(add_days(d, 5), reservation_duration_minutes=70)]
    for p in ps:
        publish_ok(m.ada, "r_anker", p)
    r = call("GET", "/restaurants/r_anker/policies")                                   # no token
    j = check(r, 200, "L3.25")
    assert [x["policy_version"] for x in j["policies"]] == [1, 2, 3], "[L3.25] publication order (not effective-date order)"
    for x, p in zip(j["policies"], ps):
        assert all(x[k] == v for k, v in p.items()), f"[L3.25] each entry has the published policy: {x}"
    check(call("GET", "/restaurants/ghost/policies"), 404, "L3.25", "not_found")
    assert call("GET", "/restaurants/r_two/policies").json == {"policies": []}, "[L3.25] policies are per restaurant"
    assert check(m.bob.get("/restaurants/r_anker/policies"), 200, "L3.25") == j


def test_L3_26_restaurant_detail_keeps_the_original_fixture_configuration():
    m = mgr_world()
    before = call("GET", "/restaurants/r_anker").json
    publish_ok(m.ada, "r_anker", policy(m.date, slot_minutes=15, reservation_duration_minutes=45, cancellation_cutoff_minutes=5,
                                        capacities={"t_1": 9, "t_2": 9, "t_3": 9}, opening_hours=[{"weekday": "mon", "opens": "10:00", "closes": "11:00"}]))
    assert call("GET", "/restaurants/r_anker").json == before, "[L3.26] the ordinary restaurant detail still returns the original fixture configuration"
    assert call("GET", "/restaurants").json["restaurants"][0] == {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin"} or \
        call("GET", "/restaurants").json["restaurants"][0]["id"] == "r_anker"


# ---- selection (L3.27-L3.28) ---------------------------------------------------------------

def dur(j):
    return int((iso(j["ends_at"]) - iso(j["starts_at"])).total_seconds() // 60)


def test_L3_27_selection_out_of_order_publication_and_ties():
    m = mgr_world()
    d = m.date
    publish_ok(m.ada, "r_anker", policy(add_days(d, 10), reservation_duration_minutes=100))      # v1
    publish_ok(m.ada, "r_anker", policy(add_days(d, 5), reservation_duration_minutes=60))        # v2 (published later, effective earlier)
    publish_ok(m.ada, "r_anker", policy(add_days(d, 5), reservation_duration_minutes=70))        # v3 ties v2 on the date: v3 wins
    expect = [(0, 0, 90), (3, 0, 90), (4, 0, 90), (5, 3, 70), (6, 3, 70), (9, 3, 70), (10, 1, 100), (11, 1, 100), (40, 1, 100)]
    for off, ver, minutes in expect:
        j = book_ok(m.bob if off % 2 else m.cy, add_days(d, off), "19:00", "t_3", 6)
        assert j["accepted_terms"]["policy_version"] == ver and dur(j) == minutes, \
            f"[L3.27] start date +{off}d: greatest effective_from <= date, ties choose greatest version -> v{ver} ({minutes} min), got v{j['accepted_terms']['policy_version']} {dur(j)} min"
        assert j["accepted_terms"]["reservation_duration_minutes"] == minutes


def test_L3_27_effective_date_is_the_local_start_date_not_utc_or_creation_date():
    reset(fixture(users=[user("ada")], restaurants=[restaurant("r_ny", timezone="America/New_York", managers=["u_ada"],
                                                                hours=all_week("00:00", "23:30"))]))
    a = login("ada@example.com")
    d = safe_date()
    pol = policy(d, opening_hours=all_week("00:00", "23:30"), reservation_duration_minutes=60)
    publish_ok(a, "r_ny", pol)
    # 22:00 New York on date d is already d+1 in UTC; the booking's *local* start date is d => the policy applies
    j = check(a.post("/reservations", json={"restaurant_id": "r_ny", "table_id": "t_1", "starts_at_local": f"{d}T22:00", "party_size": 2},
                     key=new_key()), 201, "L3.27")
    assert j["accepted_terms"]["policy_version"] == 1 and dur(j) == 60, "[L3.27] selection by the booking's LOCAL start date"
    j0 = check(a.post("/reservations", json={"restaurant_id": "r_ny", "table_id": "t_1", "starts_at_local": f"{add_days(d, -1)}T22:00", "party_size": 2},
                      key=new_key()), 201, "L3.27")
    assert j0["accepted_terms"]["policy_version"] == 0 and dur(j0) == 90


def test_L3_27_same_date_policy_supersedes_without_touching_accepted_reservations():
    m = mgr_world()
    d = m.date
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=60))                     # v1
    old = book_ok(m.bob, d, "19:00", "t_3", 6)
    assert old["accepted_terms"]["policy_version"] == 1 and dur(old) == 60
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=120))                    # v2, same date: supersedes for future decisions
    new = book_ok(m.cy, d, "19:00", "t_2", 4)
    assert new["accepted_terms"]["policy_version"] == 2 and dur(new) == 120
    again = m.bob.get(f"/reservations/{old['reference']}").json
    assert again == old, "[L3.27] a new same-date policy does not change an accepted reservation (terms, end time, revision)"
    assert history(m.bob, old["reference"])[0]["accepted_terms"] == old["accepted_terms"]


def test_L3_27_effective_dates_in_the_past_apply_without_editing_bookings():
    m = mgr_world()
    d = m.date
    before = book_ok(m.bob, d, "19:00", "t_3", 6)
    publish_ok(m.ada, "r_anker", policy("2020-01-01", reservation_duration_minutes=45))
    publish_ok(m.ada, "r_anker", policy("2019-01-01", reservation_duration_minutes=33))          # later publication, older date: lower priority
    assert m.bob.get(f"/reservations/{before['reference']}").json == before, "[L3.27] publication never retroactively edits a booking"
    assert len(history(m.bob, before["reference"])) == 1
    nb = book_ok(m.cy, d, "21:00", "t_3", 6)
    assert nb["accepted_terms"]["policy_version"] == 1 and dur(nb) == 45
    past = book_ok(m.cy, "2020-06-01", "19:00", "t_3", 6)
    assert past["accepted_terms"]["policy_version"] == 1 and dur(past) == 45, "[L3.27] a past date >= effective_from uses it (past bookings are legal)"
    older = book_ok(m.cy, "2019-06-01", "19:00", "t_3", 6)
    assert older["accepted_terms"]["policy_version"] == 2 and dur(older) == 33
    oldest = book_ok(m.cy, "2018-06-01", "19:00", "t_3", 6)
    assert oldest["accepted_terms"]["policy_version"] == 0 and dur(oldest) == 90, "[L3.27] before every effective_from => policy 0"


def test_L3_28_availability_and_booking_follow_the_selected_policy():
    m = mgr_world()
    d = m.date
    wd = weekday_name(d)
    other = [x for x in WEEKDAYS if x != wd][0]
    # policy: grid 45, duration 60, only opens on one other weekday on the date => d closed
    publish_ok(m.ada, "r_anker", policy(d, slot_minutes=45, reservation_duration_minutes=60, opening_hours=[{"weekday": other, "opens": "18:00", "closes": "23:00"}]))
    j = call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2").json
    assert j["slots"] == [], "[L3.28] the selected policy's opening hours close the day"
    check(book(m.ada, d, "19:00", "t_2", 2), 422, "L3.28", "outside_opening_hours")
    d2 = add_days(d, 1)
    publish_ok(m.ada, "r_anker", policy(d2, slot_minutes=45, reservation_duration_minutes=60, opening_hours=all_week("18:00", "22:30"),
                                        capacities={"t_1": 2, "t_2": 3, "t_3": 6}))
    j = call("GET", f"/availability?restaurant_id=r_anker&date={d2}&party_size=3").json
    starts = [s["starts_at_local"][-5:] for s in j["slots"]]
    assert starts == ["18:00", "18:45", "19:30", "20:15", "21:00"], f"[L3.28] 45-minute grid from opens, slot+60 <= closes 22:30 (21:00 ok, 21:45 not): {starts}"
    check(book(m.ada, d2, "19:00", "t_2", 3), 422, "L3.28", "not_on_slot_grid")                  # was on the policy-0 grid
    j1 = check(book(m.ada, d2, "19:30", "t_2", 3), 201, "L3.28")
    assert dur(j1) == 60 and j1["accepted_terms"]["capacities"] == {"t_1": 2, "t_2": 3, "t_3": 6}
    check(book(m.ada, d2, "19:30", "t_1", 2), 201, "L3.28")
    check(book(m.bob, d2, "21:00", "t_2", 4), 422, "L3.28", "party_exceeds_capacity")             # t_2 capacity is 3 under the policy
    check(book(m.bob, d2, "21:30", "t_2", 3), 422, "L3.28", "not_on_slot_grid")
    # the shorter duration shows in occupancy: a 60-minute booking at 19:30 ends 20:30, so 20:15 overlaps but 21:00 does not
    s = {x["starts_at_local"][-5:]: x for x in call("GET", f"/availability?restaurant_id=r_anker&date={d2}&party_size=3").json["slots"]}
    assert "t_2" not in s["20:15"]["available_table_ids"] and "t_2" in s["21:00"]["available_table_ids"]


def test_L3_28_combinations_use_the_policy_capacities():
    m = mgr_world()
    d = m.date
    publish_ok(m.ada, "r_anker", policy(d, capacities={"t_1": 1, "t_2": 1, "t_3": 6}))
    s = {x["starts_at_local"][-5:]: x for x in call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2").json["slots"]}
    opts = s["19:00"]["available_options"]
    assert {"table_ids": ["t_1", "t_2"], "capacity": 2} in opts and {"table_ids": ["t_2", "t_3"], "capacity": 7} in opts \
        and {"table_ids": ["t_1"], "capacity": 1} not in opts, f"[L3.28] combination capacity is the sum of the selected policy's capacities: {opts}"
    check(m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{d}T19:00", "party_size": 3},
                     key=new_key()), 422, "L3.28", "party_exceeds_capacity")
    j = check(m.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{d}T19:00", "party_size": 2},
                         key=new_key()), 201, "L3.28")
    assert j["accepted_terms"]["capacities"] == {"t_1": 1, "t_2": 1, "t_3": 6}


# ---- accepted terms snapshot (L3.29) ----------------------------------------------------------

def test_L3_29_every_reservation_response_carries_revision_and_complete_terms():
    m = mgr_world()
    d = m.date
    j = book_ok(m.ada, d, "19:00", "t_2", 4)
    assert j["revision"] == 1 and j["accepted_terms"] == P0, f"[L3.29] revision 1 and the policy-0 snapshot of the whole fixture rules: {j.get('accepted_terms')}"
    assert set(j["accepted_terms"]) == {"policy_version", "slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes",
                                        "opening_hours", "capacities"}, "[L3.29] snapshot excludes effective_from"
    p = policy(add_days(d, 1), opening_hours=[{"weekday": "mon", "opens": "17:00", "closes": "22:00"}] + [x for x in all_week("18:00", "23:00") if x["weekday"] != "mon"],
               capacities={"t_1": 3, "t_2": 5, "t_3": 7})
    publish_ok(m.ada, "r_anker", p)
    k = book_ok(m.ada, add_days(d, 1), "19:00", "t_3", 7)
    assert k["accepted_terms"] == terms(p, 1) and k["revision"] == 1
    for r in (m.ada.get(f"/reservations/{k['reference']}").json, m.ada.get("/reservations").json["reservations"][0]):
        assert r["revision"] == 1 and r["accepted_terms"] == terms(p, 1), "[L3.29] GET and list carry them too"
    c = check(m.ada.post(f"/reservations/{k['reference']}/cancel"), 200, "L3.29")
    assert c["revision"] == 2 and c["accepted_terms"] == terms(p, 1)


def test_L3_29_seeded_bookings_start_at_revision_one_under_policy_zero():
    rs = [{"id": "res_s", "reference": "SEED77", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
           "starts_at_local": "2030-01-09T19:00", "party_size": 4},
          {"id": "res_c", "reference": "SEED78", "user_id": "u_ada", "restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
           "starts_at_local": "2030-01-10T19:00", "party_size": 5, "status": "cancelled"}]
    reset(fixture(restaurants=[restaurant(managers=["u_ada"], combinable=[["t_1", "t_2"]])], reservations=rs))
    a = login("ada@example.com")
    for ref in ("SEED77", "SEED78"):
        j = check(a.get(f"/reservations/{ref}"), 200, "L3.29")
        assert j["revision"] == 1 and j["accepted_terms"] == P0, f"[L3.29] seeded {ref}: {j.get('revision')} {j.get('accepted_terms')}"
        d = check(a.get(f"/reservations/{ref}/decision"), 200, "L3.29")
        assert d["revision"] == 1 and d["accepted_terms"] == P0
        assert check(a.get(f"/reservations/{ref}/history"), 200, "L3.29")["reference"] == ref


def test_L3_29_replayed_responses_stay_the_original_revision_and_terms():
    m = mgr_world()
    d = m.date
    key = new_key()
    b = body(d, "19:00", "t_2", 4)
    first = check(m.ada.post("/reservations", json=b, key=key), 201, "L3.29")
    publish_ok(m.ada, "r_anker", policy(d, reservation_duration_minutes=120))
    check(m.ada.patch(f"/reservations/{first['reference']}", json={"party_size": 3}), 200, "L3.29")
    m.ada.post(f"/reservations/{first['reference']}/cancel")
    rep = check(m.ada.post("/reservations", json=b, key=key), 200, "L3.29")
    assert rep == first and rep["revision"] == 1 and rep["accepted_terms"]["policy_version"] == 0 and rep["status"] == "confirmed", \
        "[L3.29] responses to old idempotency keys remain the original response, including the original revision and terms"
