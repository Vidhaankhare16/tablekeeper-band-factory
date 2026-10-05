"""POST/GET/cancel/PATCH reservations and cutoff (ledger L1.1-L1.3, L1.17-L1.18, L1.58-L1.81)."""
import datetime as dt
import re
import pytest
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, local, slots, \
    avail_ids, new_key, body, login, instant, iso, PW

PAST = "2020-01-08"  # a Wednesday long ago


def test_L1_58_create_shape_and_values(w):
    d = w.date
    r = book(w.ada, d, "19:00", "t_2", 4)
    j = check(r, 201, "L1.58")
    assert j["restaurant_id"] == "r_anker" and j["table_id"] == "t_2" and j["party_size"] == 4
    assert j["status"] == "confirmed" and j["starts_at_local"] == f"{d}T19:00", f"[L1.58] {j}"
    assert isinstance(j["reservation_id"], str) and j["reservation_id"]
    s, e = iso(j["starts_at"]), iso(j["ends_at"])
    assert e - s == dt.timedelta(minutes=90), f"[L1.58] ends_at = starts_at + 90 min: {j}"
    assert s.utcoffset() in (dt.timedelta(hours=1), dt.timedelta(hours=2)) and s.replace(tzinfo=None).isoformat(timespec="minutes") == f"{d}T19:00"
    assert iso(j["created_at"]).utcoffset() is not None
    assert abs((dt.datetime.now(dt.timezone.utc) - instant(j["created_at"])).total_seconds()) < 3600, "[L1.58] created_at ~ now"
    assert set(j) >= {"reservation_id", "reference", "restaurant_id", "table_id", "party_size", "status", "starts_at_local",
                      "starts_at", "ends_at", "created_at"}


def test_L1_60_reference_format_unique_stable(w):
    refs = []
    for i, at in enumerate(["18:00", "19:30", "21:00"]):
        for t in ("t_1", "t_2", "t_3"):
            refs.append(book_ok(w.ada if i % 2 else w.bob, w.date, at, t, 2)["reference"])
    assert len(set(refs)) == len(refs), "[L1.60] references unique"
    for r in refs:
        assert re.fullmatch(r"[A-Z0-9]{6,12}", r), f"[L1.60] reference must be 6-12 of A-Z0-9, got {r!r}"
    j = book_ok(w.ada, safe_date(1), "20:00", "t_1", 2)
    ref = j["reference"]
    assert w.ada.get(f"/reservations/{ref}").json == j, "[L1.60] same reference on read"
    w.ada.patch(f"/reservations/{ref}", json={"party_size": 1})
    w.ada.post(f"/reservations/{ref}/cancel")
    assert w.ada.get(f"/reservations/{ref}").json["reference"] == ref, "[L1.60] reference never changes"


def test_L1_61_table_unavailable_and_overlap_boundaries(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")  # [19:00, 20:30)
    for at in ("18:00", "18:30", "19:00", "19:30", "20:00"):
        check(book(w.bob, d, at, "t_2"), 409, "L1.1/L1.61", "table_unavailable")
    check(book(w.bob, d, "20:30", "t_2"), 201, "L1.2")      # starts exactly when the other ends
    check(book(w.bob, d, "21:00", "t_3", 6), 201, "L1.2")
    # earlier neighbour: ends exactly at 19:00
    reset(fixture()); a = login("ada@example.com"); b = login("bob@example.com")
    check(book(a, d, "18:00", "t_2"), 201, "L1.2")           # [18:00,19:30)
    check(book(b, d, "19:30", "t_2"), 201, "L1.2")           # starts when first ends
    check(book(b, d, "19:00", "t_2"), 409, "L1.61", "table_unavailable")
    check(book(b, d, "19:00", "t_3", 6), 201, "L1.1")        # other table unaffected


def test_L1_61_unavailable_does_not_block_other_users_tables_or_days(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")
    check(book(w.bob, safe_date(1), "19:00", "t_2"), 201, "L1.61")
    check(book(w.bob, d, "19:00", "t_1", 2), 201, "L1.61")


def test_L1_3_rejected_requests_create_nothing(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")
    before = w.bob.get("/reservations").json
    for r in (book(w.bob, d, "19:30", "t_2"), book(w.bob, d, "19:15", "t_1", 2), book(w.bob, d, "22:00", "t_1", 2),
              book(w.bob, d, "19:00", "t_1", 3), book(w.bob, d, "19:00", "t_1", 0), book(w.bob, d, "19:00", "nope", 2)):
        assert 400 <= r.status < 500
    assert w.bob.get("/reservations").json == before == {"reservations": []}, "[L1.3] no partial bookings"
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_3"], "[L1.3] occupancy unchanged by rejected requests"


def test_L1_62_not_on_slot_grid(w):
    for at in ("18:15", "19:01", "19:29", "20:45", "18:59"):
        check(book(w.ada, w.date, at, "t_2"), 422, "L1.62", "not_on_slot_grid")


def test_L1_62_grid_is_anchored_at_opening_time():
    reset(fixture(restaurants=[restaurant(slot=30, dur=60, hours=all_week("18:15", "22:15"))]))
    a = login("ada@example.com"); d = safe_date()
    check(book(a, d, "18:15", "t_2"), 201, "L1.62")
    check(book(a, d, "19:15", "t_2"), 201, "L1.62")
    check(book(a, d, "20:00", "t_2"), 422, "L1.62", "not_on_slot_grid")   # on the hour but not on the 18:15 grid
    check(book(a, d, "20:15", "t_2"), 201, "L1.62")
    check(book(a, d, "21:15", "t_2"), 201, "L1.63")                        # ends exactly at closes 22:15
    check(book(a, d, "21:45", "t_2"), 422, "L1.63", "outside_opening_hours")  # would end 22:45 > closes


def test_L1_63_outside_opening_hours(w):
    d = w.date
    check(book(w.ada, d, "17:30", "t_2"), 422, "L1.63", "outside_opening_hours")   # before opening, on grid
    check(book(w.ada, d, "00:00", "t_2"), 422, "L1.63", "outside_opening_hours")
    check(book(w.ada, d, "21:30", "t_2"), 201, "L1.63")                              # ends exactly at closes
    check(book(w.ada, d, "22:00", "t_3", 6), 422, "L1.63", "outside_opening_hours")  # would end 23:30 > 23:00
    check(book(w.ada, d, "22:30", "t_3", 6), 422, "L1.63", "outside_opening_hours")
    check(book(w.ada, d, "23:00", "t_3", 6), 422, "L1.63", "outside_opening_hours")
    check(book(w.ada, d, "23:30", "t_3", 6), 422, "L1.63", "outside_opening_hours")


def test_L1_63_closed_day_is_outside_opening_hours():
    d = safe_date()
    wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[dt.date.fromisoformat(d).weekday()]
    other = "mon" if wd != "mon" else "tue"
    reset(fixture(restaurants=[restaurant(hours=[{"weekday": other, "opens": "18:00", "closes": "23:00"}])]))
    a = login("ada@example.com")
    check(book(a, d, "19:00"), 422, "L1.16/L1.63", "outside_opening_hours")  # no entry for that weekday => closed


def test_L1_64_party_exceeds_capacity(w):
    check(book(w.ada, w.date, "19:00", "t_1", 3), 422, "L1.64", "party_exceeds_capacity")
    check(book(w.ada, w.date, "19:00", "t_2", 5), 422, "L1.64", "party_exceeds_capacity")
    check(book(w.ada, w.date, "19:00", "t_3", 7), 422, "L1.64", "party_exceeds_capacity")
    check(book(w.ada, w.date, "19:00", "t_1", 2), 201, "L1.64")                      # == capacity is fine
    check(book(w.ada, w.date, "19:00", "t_3", 1), 201, "L1.64")                      # under capacity is fine
    check(book(w.ada, w.date, "19:00", "t_2", 1000000), 422, "L1.64", "party_exceeds_capacity")


def test_L1_65_party_size_below_one_or_not_integer(w):
    for p in (0, -1, -100, 1.5, "2", True, None):
        r = book(w.ada, w.date, "19:00", "t_2", p)
        if p is None:
            assert r.status in (400, 422), f"[L1.65] null party_size is rejected, got {r!r}"
        else:
            check(r, 422, "L1.65", "validation_failed")
    check(book(w.ada, w.date, "19:00", "t_2", 1), 201, "L1.65")


def test_L1_67_not_found_cases(w):
    check(book(w.ada, w.date, rid="ghost"), 404, "L1.67", "not_found")
    check(book(w.ada, w.date, table="t_nope"), 404, "L1.67", "not_found")
    check(book(w.ada, w.date, table="t_x1", rid="r_anker"), 404, "L1.67", "not_found")   # table of r_two
    check(book(w.ada, w.date, table="t_1", rid="r_two"), 404, "L1.67", "not_found")
    check(book(w.ada, w.date, table="t_x1", rid="r_two", party=4), 201, "L1.67")
    assert w.ada.get("/reservations").json["reservations"].__len__() == 1


def test_L1_66_67_precedence_notfound_before_field_rules(w):
    # READING R2: unknown restaurant/table (404) is reported before time/capacity rules about it.
    check(book(w.ada, w.date, "19:15", "t_nope", 99), 404, "L1.67", "not_found")


def test_L1_68_list_my_reservations_order(w):
    assert w.ada.get("/reservations").json == {"reservations": []}, "[L1.68] empty list shape"
    d1, d2 = safe_date(), safe_date(1)
    a = book_ok(w.ada, d2, "20:00", "t_1", 2)
    b = book_ok(w.ada, d1, "19:00", "t_1", 2)
    c = book_ok(w.ada, d2, "18:00", "t_2", 2)
    e = book_ok(w.ada, d1, "21:00", "t_2", 2)
    other = book_ok(w.bob, d1, "20:00", "t_3", 2)
    w.ada.post(f"/reservations/{e['reference']}/cancel")
    r = w.ada.get("/reservations")
    j = check(r, 200, "L1.68")["reservations"]
    refs = [x["reference"] for x in j]
    assert refs == [a["reference"], c["reference"], e["reference"], b["reference"]], \
        f"[L1.68] starts_at descending, cancelled included, only the caller's: {refs}"
    assert {x["status"] for x in j} == {"confirmed", "cancelled"}
    assert other["reference"] not in refs
    assert j[2]["status"] == "cancelled" and set(j[0]) >= {"reservation_id", "reference", "status", "starts_at", "ends_at"}
    assert [x["reference"] for x in w.bob.get("/reservations").json["reservations"]] == [other["reference"]]
    assert j[0] == a, "[L1.68] list entry has the same shape/values as the create response"


def test_L1_68_order_by_instant_not_string_across_restaurants():
    # starts_at descending is by instant: NY 19:00 (23:00Z) is later than Berlin 22:00 (20:00Z) the same date
    ny = restaurant("r_ny", timezone="America/New_York", hours=all_week("12:00", "23:30"))
    be = restaurant("r_be", hours=all_week("12:00", "23:30"), tables=[{"id": "t_b", "label": "b", "capacity": 4}])
    reset(fixture(restaurants=[ny, be]))
    a = login("ada@example.com"); d = safe_date()
    x = book_ok(a, d, "22:00", "t_b", 2, "r_be")     # 20:00Z
    y = book_ok(a, d, "19:00", "t_2", 2, "r_ny")     # 23:00Z
    assert [r["reference"] for r in a.get("/reservations").json["reservations"]] == [y["reference"], x["reference"]], \
        "[L1.68] order by starts_at instant, descending"


def test_L1_69_get_one_and_visibility(w):
    j = book_ok(w.ada, w.date)
    assert check(w.ada.get(f"/reservations/{j['reference']}"), 200, "L1.69") == j
    check(w.bob.get(f"/reservations/{j['reference']}"), 404, "L1.69", "not_found")
    check(w.ada.get("/reservations/ZZZZZZ"), 404, "L1.69", "not_found")


def test_L1_70_cancel_basics_and_frees_table(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2")
    assert avail_ids(d, "19:00", 4) == ["t_3"]
    r = w.ada.post(f"/reservations/{j['reference']}/cancel")
    c = check(r, 200, "L1.70")
    assert c["status"] == "cancelled" and c["reference"] == j["reference"], f"[L1.70] {r!r}"
    for k in ("reservation_id", "restaurant_id", "table_id", "party_size", "starts_at_local", "starts_at", "ends_at", "created_at"):
        assert c[k] == j[k], f"[L1.70] cancel keeps {k}"
    assert avail_ids(d, "19:00", 4) == ["t_2", "t_3"], "[L1.71] cancel frees the table immediately"
    assert avail_ids(d, "20:00", 4) == ["t_2", "t_3"]
    check(book(w.bob, d, "19:30", "t_2"), 201, "L1.71")          # and it can be rebooked
    assert w.ada.get(f"/reservations/{j['reference']}").json["status"] == "cancelled"


def test_L1_72_cancel_twice_ok(w):
    j = book_ok(w.ada, w.date)
    first = check(w.ada.post(f"/reservations/{j['reference']}/cancel"), 200, "L1.72")
    second = check(w.ada.post(f"/reservations/{j['reference']}/cancel"), 200, "L1.72")
    assert first == second and second["status"] == "cancelled", "[L1.72] current state returned"


def test_L1_74_cancel_not_callers_is_404(w):
    j = book_ok(w.ada, w.date)
    check(w.bob.post(f"/reservations/{j['reference']}/cancel"), 404, "L1.74", "not_found")
    check(w.bob.post("/reservations/NOPE99/cancel"), 404, "L1.74", "not_found")
    assert w.ada.get(f"/reservations/{j['reference']}").json["status"] == "confirmed", "[L1.74] untouched"


def test_L1_18_past_booking_allowed_cutoff_still_applies(w):
    j = check(book(w.ada, PAST, "19:00"), 201, "L1.18")
    assert j["starts_at_local"] == f"{PAST}T19:00" and j["status"] == "confirmed"
    check(w.ada.post(f"/reservations/{j['reference']}/cancel"), 409, "L1.73/L1.18", "cutoff_passed")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 2}), 409, "L1.77/L1.18", "cutoff_passed")
    assert w.ada.get(f"/reservations/{j['reference']}").json["status"] == "confirmed", "[L1.73] stays confirmed"
    assert avail_ids(PAST, "19:00", 4) == ["t_3"], "[L1.55] past dates are available/occupied like any other"


def test_L1_73_cutoff_zero_past_start():
    reset(fixture(restaurants=[restaurant(cutoff=0)]))
    a = login("ada@example.com")
    j = book_ok(a, PAST)
    check(a.post(f"/reservations/{j['reference']}/cancel"), 409, "L1.73", "cutoff_passed")
    j2 = book_ok(a, safe_date())
    check(a.post(f"/reservations/{j2['reference']}/cancel"), 200, "L1.73")


def _cutoff_world(margin_note=""):
    """UTC restaurant open all day, 5-minute grid, whose cutoff ends exactly at 12:00 UTC on a coming day."""
    now = dt.datetime.now(dt.timezone.utc)
    t0 = (now + dt.timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
    cutoff = int((t0 - now).total_seconds() // 60)
    r = restaurant("r_cut", timezone="UTC", slot=5, dur=30, cutoff=cutoff, hours=all_week("00:00", "23:59"),
                   tables=[{"id": "tc1", "label": "1", "capacity": 4}, {"id": "tc2", "label": "2", "capacity": 4},
                           {"id": "tc3", "label": "3", "capacity": 4}])
    reset(fixture(restaurants=[r]))
    return t0, login("ada@example.com")


def _at(t0, minutes):
    return (t0 + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


def test_L1_73_cutoff_boundary_cancel():
    t0, a = _cutoff_world()
    # start 10 min after the cutoff instant (now+cutoff) -> more than cutoff away -> cancellable
    ok = a.post("/reservations", json={"restaurant_id": "r_cut", "table_id": "tc1", "starts_at_local": _at(t0, 10),
                                       "party_size": 2}, key=new_key()).json
    near = a.post("/reservations", json={"restaurant_id": "r_cut", "table_id": "tc2", "starts_at_local": _at(t0, -10),
                                         "party_size": 2}, key=new_key()).json
    check(a.post(f"/reservations/{near['reference']}/cancel"), 409, "L1.73", "cutoff_passed")
    check(a.post(f"/reservations/{ok['reference']}/cancel"), 200, "L1.73")
    assert a.get(f"/reservations/{near['reference']}").json["status"] == "confirmed"


def test_L1_77_cutoff_boundary_patch_measured_against_current_start():
    t0, a = _cutoff_world()
    mk = lambda tbl, m: a.post("/reservations", json={"restaurant_id": "r_cut", "table_id": tbl,
                                                      "starts_at_local": _at(t0, m), "party_size": 2}, key=new_key()).json
    near, far = mk("tc1", -10), mk("tc2", 10)
    # the near booking cannot be amended, even to a far-away time
    check(a.patch(f"/reservations/{near['reference']}", json={"starts_at_local": _at(t0, 600)}), 409, "L1.77", "cutoff_passed")
    # the far booking can be amended, even *to* a time inside the cutoff window (measured against the current start)
    j = check(a.patch(f"/reservations/{far['reference']}", json={"starts_at_local": _at(t0, -20)}), 200, "L1.77")
    assert j["starts_at_local"] == _at(t0, -20)
    # now its current start is inside the cutoff -> further changes and cancel are refused
    check(a.patch(f"/reservations/{far['reference']}", json={"party_size": 1}), 409, "L1.77", "cutoff_passed")
    check(a.post(f"/reservations/{far['reference']}/cancel"), 409, "L1.73", "cutoff_passed")


def test_L1_17_seeded_reservations():
    rs = [{"id": "res_s1", "reference": "SEED01", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
           "starts_at_local": "2020-01-09T19:00", "party_size": 4},
          {"id": "res_s2", "reference": "SEED02", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_3",
           "starts_at_local": "2020-01-09T20:30", "party_size": 5}]
    reset(fixture(reservations=rs))
    a, b = login("ada@example.com"), login("bob@example.com")
    j = check(a.get("/reservations/SEED01"), 200, "L1.17")
    assert j["reservation_id"] == "res_s1" and j["reference"] == "SEED01" and j["status"] == "confirmed" \
        and j["table_id"] == "t_2" and j["starts_at"] == "2020-01-09T19:00:00+01:00" \
        and j["ends_at"] == "2020-01-09T20:30:00+01:00", f"[L1.17] {j}"
    check(b.get("/reservations/SEED01"), 404, "L1.17", "not_found")
    assert [x["reference"] for x in b.get("/reservations").json["reservations"]] == ["SEED02"]
    assert avail_ids("2020-01-09", "19:00", 4) == ["t_3"], "[L1.17] seeded booking occupies its table"
    assert avail_ids("2020-01-09", "20:30", 4) == ["t_2"], "[L1.17] t_3 taken at 20:30 by the seed"
    check(book(b, "2020-01-09", "19:30", "t_2"), 409, "L1.1/L1.17", "table_unavailable")
    check(book(b, "2020-01-09", "20:30", "t_2"), 201, "L1.2")
    check(a.post("/reservations/SEED01/cancel"), 409, "L1.18", "cutoff_passed")  # past => inside cutoff
    # the seeded reference stays unique: new references never collide with it
    assert book_ok(a, safe_date(), "19:00")["reference"] != "SEED01"


# ---- PATCH ---------------------------------------------------------------------------------

def test_L1_75_patch_each_field_alone(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2", 4)
    ref = j["reference"]
    p = check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200, "L1.75")
    assert p["party_size"] == 3 and p["table_id"] == "t_2" and p["starts_at_local"] == f"{d}T19:00"
    p = check(w.ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 200, "L1.75")
    assert p["table_id"] == "t_3" and p["party_size"] == 3 and p["starts_at_local"] == f"{d}T19:00"
    p = check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T20:30"}), 200, "L1.75")
    assert p["starts_at_local"] == f"{d}T20:30" and p["table_id"] == "t_3"
    assert iso(p["ends_at"]) - iso(p["starts_at"]) == dt.timedelta(minutes=90) and p["starts_at"].startswith(f"{d}T20:30:00")
    p = check(w.ada.patch(f"/reservations/{ref}", json={"table_id": "t_1", "party_size": 2, "starts_at_local": f"{d}T18:00"}),
              200, "L1.75")
    assert (p["table_id"], p["party_size"], p["starts_at_local"]) == ("t_1", 2, f"{d}T18:00")
    assert w.ada.get(f"/reservations/{ref}").json == p, "[L1.75] GET shows the amended booking"


def test_L1_81_identity_survives_patch(w):
    j = book_ok(w.ada, w.date)
    p = check(w.ada.patch(f"/reservations/{j['reference']}", json={"table_id": "t_3", "starts_at_local": f"{w.date}T20:00",
                                                                   "party_size": 5}), 200, "L1.81")
    for k in ("reference", "reservation_id", "created_at", "restaurant_id", "status"):
        assert p[k] == j[k], f"[L1.81] {k} must survive an amendment"
    assert [x["reference"] for x in w.ada.get("/reservations").json["reservations"]] == [j["reference"]], "[L1.81] no duplicate"


def test_L1_79_patch_releases_old_and_reserves_new(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": f"{d}T21:00", "table_id": "t_3"}), 200, "L1.79")
    assert avail_ids(d, "19:00", 4) == ["t_2", "t_3"], "[L1.79] old slot released"
    assert avail_ids(d, "21:00", 4) == ["t_2"], "[L1.79] new slot reserved"
    check(book(w.bob, d, "19:00", "t_2"), 201, "L1.79")
    check(book(w.bob, d, "21:00", "t_3", 6), 409, "L1.79", "table_unavailable")


def test_L1_79_patch_may_overlap_own_old_interval(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": f"{d}T19:30"}), 200, "L1.79")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": f"{d}T19:30", "party_size": 2}), 200, "L1.79")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"starts_at_local": f"{d}T19:00"}), 200, "L1.79")


def test_L1_80_failed_patch_changes_nothing(w):
    d = w.date
    a = book_ok(w.ada, d, "19:00", "t_2")
    b = book_ok(w.bob, d, "19:00", "t_3", 5)
    ref = a["reference"]
    bad = [({"table_id": "t_3"}, 409, "table_unavailable"),
           ({"starts_at_local": f"{d}T19:15"}, 422, "not_on_slot_grid"),
           ({"starts_at_local": f"{d}T22:00"}, 422, "outside_opening_hours"),
           ({"party_size": 5}, 422, "party_exceeds_capacity"),
           ({"party_size": 0}, 422, "validation_failed"),
           ({"party_size": "3"}, 422, "validation_failed"),
           ({"starts_at_local": f"{d}T19:00:00"}, 422, "validation_failed"),
           ({"table_id": "t_nope"}, 404, "not_found"),
           ({"table_id": "t_x1"}, 404, "not_found"),
           ({"table_id": "t_3", "starts_at_local": f"{d}T21:00"}, 201, None)]
    for patch, st, code in bad[:-1]:
        check(w.ada.patch(f"/reservations/{ref}", json=patch), st, "L1.76/L1.80", code)
    # one valid field combined with one invalid field must not apply the valid one (no partial amendment)
    check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 2, "starts_at_local": f"{d}T19:15"}), 422, "L1.80",
          "not_on_slot_grid")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T18:00", "table_id": "t_3"}), 409, "L1.80",
          "table_unavailable")
    assert w.ada.get(f"/reservations/{ref}").json == a, "[L1.80] original booking unchanged"
    assert avail_ids(d, "19:00", 4) == [], "[L1.80] occupancy unchanged"
    assert avail_ids(d, "19:00", 2) == ["t_1"] and avail_ids(d, "18:00", 4) == [], "[L1.80] no stray occupancy"
    assert w.bob.get(f"/reservations/{b['reference']}").json == b


def test_L1_76_patch_error_codes_like_post(w):
    d = w.date
    j = book_ok(w.ada, d, "19:00", "t_2")
    ref = j["reference"]
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T19:15"}), 422, "L1.76", "not_on_slot_grid")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T17:30"}), 422, "L1.76", "outside_opening_hours")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T21:30"}), 200, "L1.76")  # ends at closes
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T22:00"}), 422, "L1.76", "outside_opening_hours")
    check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 5}), 422, "L1.76", "party_exceeds_capacity")
    check(w.ada.patch(f"/reservations/{ref}", json={"table_id": "t_1"}), 422, "L1.76", "party_exceeds_capacity")  # party 4 > 2
    for v in (0, -3, 2.5, True, "2"):
        check(w.ada.patch(f"/reservations/{ref}", json={"party_size": v}), 422, "L1.76", "validation_failed")
    for v in (5, ["x"], {"a": 1}):
        check(w.ada.patch(f"/reservations/{ref}", json={"table_id": v}), 400, "L1.76/L1.20", "malformed_request")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": 5}), 400, "L1.76/L1.20", "malformed_request")
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": "nonsense"}), 422, "L1.76", "validation_failed")
    # taking another booking's slot
    other = book_ok(w.bob, d, "19:00", "t_3", 2)
    check(w.ada.patch(f"/reservations/{ref}", json={"starts_at_local": f"{d}T19:00", "table_id": "t_3"}), 409, "L1.76",
          "table_unavailable")


def test_L1_76_patch_no_idempotency_key_needed_and_not_found(w):
    j = book_ok(w.ada, w.date)
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 2}), 200, "L1.75")  # no key header at all
    check(w.bob.patch(f"/reservations/{j['reference']}", json={"party_size": 2}), 404, "L1.69/L1.76", "not_found")
    check(w.ada.patch("/reservations/NOPE12", json={"party_size": 2}), 404, "L1.76", "not_found")
    assert w.ada.get(f"/reservations/{j['reference']}").json["party_size"] == 2
    unchanged = w.ada.get(f"/reservations/{j['reference']}").json
    check(w.bob.patch(f"/reservations/{j['reference']}", json={"table_id": "t_3"}), 404, "L1.76", "not_found")
    assert w.ada.get(f"/reservations/{j['reference']}").json == unchanged


def test_L1_78_patch_cancelled_is_409(w):
    j = book_ok(w.ada, w.date)
    w.ada.post(f"/reservations/{j['reference']}/cancel")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 2}), 409, "L1.78", "reservation_cancelled")
    check(w.ada.patch(f"/reservations/{j['reference']}", json={"table_id": "t_3"}), 409, "L1.78", "reservation_cancelled")
    assert w.ada.get(f"/reservations/{j['reference']}").json["status"] == "cancelled"
    assert avail_ids(w.date, "19:00", 4) == ["t_2", "t_3"], "[L1.78] amending a cancelled booking must not re-occupy"


def test_L1_66_patch_into_nonexistent_time_is_invalid_local_time():
    reset(fixture(restaurants=[restaurant(hours=all_week("00:00", "23:30"))]))
    a = login("ada@example.com")
    j = book_ok(a, safe_date(), "19:00", "t_2")
    check(a.patch(f"/reservations/{j['reference']}", json={"starts_at_local": "2027-03-28T02:30"}), 422, "L1.66",
          "invalid_local_time")
