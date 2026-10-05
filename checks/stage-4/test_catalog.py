"""Restaurants and availability (ledger L1.4, L1.16, L1.48-L1.57)."""
import pytest
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book_ok, local, slots, \
    avail_ids, new_key, body, login, Client


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def expected(opens, closes, slot, dur):
    o = int(opens[:2]) * 60 + int(opens[3:])
    c = int(closes[:2]) * 60 + int(closes[3:])
    out, t = [], o
    while t + dur <= c:
        out.append(hm(t))
        t += slot
    return out


def test_L1_48_list_restaurants(w):
    r = call("GET", "/restaurants")
    j = check(r, 200, "L1.48")
    got = {x["id"]: x for x in j["restaurants"]}
    assert list(got) == ["r_anker", "r_two"], f"[L1.48] restaurants in fixture order: {r!r}"
    assert got["r_anker"] == {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin"} or \
        (got["r_anker"]["name"] == "Zum Anker" and got["r_anker"]["timezone"] == "Europe/Berlin"), f"[L1.48] {r!r}"
    reset(fixture(restaurants=[]))
    assert call("GET", "/restaurants").json == {"restaurants": []}, "[L1.48] empty list shape"


def test_L1_49_restaurant_detail_in_fixture_shape(w):
    r = call("GET", "/restaurants/r_anker")
    j = check(r, 200, "L1.49")
    src = w.fx["restaurants"][0]
    for k in ("id", "name", "timezone", "slot_minutes", "reservation_duration_minutes",
              "cancellation_cutoff_minutes", "opening_hours"):
        assert j[k] == src[k], f"[L1.49] {k}: expected {src[k]!r}, got {j.get(k)!r}"
    assert [t["id"] for t in j["tables"]] == ["t_1", "t_2", "t_3"], "[L1.49] tables in fixture order"
    assert [(t["id"], t["label"], t["capacity"]) for t in j["tables"]] == \
        [(t["id"], t["label"], t["capacity"]) for t in src["tables"]], "[L1.49] table fields"


def test_L1_49_opening_hours_preserved_in_order():
    hours = [{"weekday": "fri", "opens": "18:00", "closes": "23:30"}, {"weekday": "thu", "opens": "17:15", "closes": "22:45"}]
    reset(fixture(restaurants=[restaurant(hours=hours)]))
    assert call("GET", "/restaurants/r_anker").json["opening_hours"] == hours, "[L1.49] opening_hours as supplied"


def test_L1_50_unknown_restaurant_404(w):
    check(call("GET", "/restaurants/nope"), 404, "L1.50", "not_found")


def test_L1_51_availability_params_required(w):
    base = {"restaurant_id": "r_anker", "date": w.date, "party_size": "2"}
    for missing in base:
        q = "&".join(f"{k}={v}" for k, v in base.items() if k != missing)
        check(call("GET", f"/availability?{q}"), 422, "L1.51", "validation_failed")
    check(call("GET", "/availability"), 422, "L1.51", "validation_failed")


@pytest.mark.parametrize("d", ["2026-02-30", "2026-9-24", "garbage", "2026-09-24T18:00", "24-09-2026", "2026-13-01", "",
                               "2026-00-10", "20260924"])
def test_L1_27_invalid_date_422(w, d):
    check(call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2"), 422, "L1.27", "validation_failed")


def test_L1_27_leap_day_valid(w):
    check(call("GET", "/availability?restaurant_id=r_anker&date=2028-02-29&party_size=2"), 200, "L1.27")
    check(call("GET", "/availability?restaurant_id=r_anker&date=2027-02-29&party_size=2"), 422, "L1.27",
          "validation_failed")


@pytest.mark.parametrize("p", ["0", "-1", "-0", "abc", "1e9", "4.0", "+4", "2,5"])
def test_L1_27_party_size_query_invalid(w, p):
    check(call("GET", f"/availability?restaurant_id=r_anker&date={w.date}&party_size={p.replace('+', '%2B')}"), 422,
          "L1.27/L1.29", "validation_failed")


def test_L1_50_availability_unknown_restaurant_404(w):
    check(call("GET", f"/availability?restaurant_id=ghost&date={w.date}&party_size=2"), 404, "L1.50", "not_found")


def test_L1_52_availability_shape(w):
    d = "2026-09-24"
    r = call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=4")
    j = check(r, 200, "L1.52")
    assert j["restaurant_id"] == "r_anker" and j["date"] == d and j["timezone"] == "Europe/Berlin", f"[L1.52] {r!r}"
    s = j["slots"][0]
    assert {k: s[k] for k in ("starts_at_local", "starts_at", "available_table_ids")} == {
        "starts_at_local": "2026-09-24T18:00", "starts_at": "2026-09-24T18:00:00+02:00",
        "available_table_ids": ["t_2", "t_3"]}, f"[L1.52] first slot: {s}"
    assert [x["starts_at_local"] for x in j["slots"]] == sorted(x["starts_at_local"] for x in j["slots"]), \
        "[L1.54] slots ascending"


def test_L1_54_slot_grid_default(w):
    s, j = slots("2026-09-24")
    assert [k[-5:] for k in s] == expected("18:00", "23:00", 30, 90), f"[L1.54] slots: {list(s)}"
    assert [k[-5:] for k in s][-1] == "21:30", "[L1.54] last slot ends exactly at closes (<=)"


@pytest.mark.parametrize("opens,closes,slot,dur", [
    ("18:00", "23:30", 30, 90), ("17:10", "22:00", 20, 60), ("18:15", "21:15", 45, 45), ("10:00", "10:59", 15, 45),
    ("10:00", "11:30", 30, 90), ("10:00", "11:29", 30, 90), ("09:00", "21:00", 60, 120), ("00:00", "23:59", 7, 53),
    ("08:00", "09:00", 30, 90)])
def test_L1_54_slot_rule_variants(opens, closes, slot, dur):
    reset(fixture(restaurants=[restaurant(slot=slot, dur=dur, hours=all_week(opens, closes))]))
    s, _ = slots("2026-09-24")
    assert [k[-5:] for k in s] == expected(opens, closes, slot, dur), \
        f"[L1.54] slot={slot} dur={dur} {opens}-{closes}: got {[k[-5:] for k in s]}"


def test_L1_54_per_weekday_hours_and_closed_day_16_57():
    # 2026-09-24 is Thursday, 2026-09-25 Friday, 2026-09-26 Saturday (no entry => closed)
    hours = [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}, {"weekday": "fri", "opens": "18:00", "closes": "23:30"}]
    reset(fixture(restaurants=[restaurant(hours=hours)]))
    s, _ = slots("2026-09-24"); assert [k[-5:] for k in s][-1] == "21:30"
    s, _ = slots("2026-09-25"); assert [k[-5:] for k in s][-1] == "22:00", "[L1.54] Friday closes 23:30"
    r = call("GET", "/availability?restaurant_id=r_anker&date=2026-09-26&party_size=2")
    j = check(r, 200, "L1.57")
    assert j["slots"] == [] and j["date"] == "2026-09-26", f"[L1.57]/[L1.16] closed day returns slots []: {r!r}"
    assert call("GET", "/availability?restaurant_id=r_anker&date=2026-09-27&party_size=2").json["slots"] == [], \
        "[L1.16] a day with no entry is closed (Sunday)"


def test_L1_55_availability_by_party_size(w):
    d = "2026-09-24"
    assert avail_ids(d, "19:00", 1) == ["t_1", "t_2", "t_3"], "[L1.55] fixture order, capacity>=1"
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_2", "t_3"], "[L1.55] capacity == party qualifies"
    assert avail_ids(d, "19:00", 3) == ["t_2", "t_3"]
    assert avail_ids(d, "19:00", 4) == ["t_2", "t_3"]
    assert avail_ids(d, "19:00", 5) == ["t_3"]
    assert avail_ids(d, "19:00", 6) == ["t_3"]
    assert avail_ids(d, "19:00", 7) == [], "[L1.56] party too large: slot still appears with empty list"
    s, _ = slots(d, 7)
    assert len(s) == 8 and all(v["available_table_ids"] == [] for v in s.values()), "[L1.56] all slots present, empty"


def test_L1_55_fixture_order_not_sorted_order():
    tables = [{"id": "t_z", "label": "Z", "capacity": 4}, {"id": "t_a", "label": "A", "capacity": 4},
              {"id": "t_m", "label": "M", "capacity": 4}]
    reset(fixture(restaurants=[restaurant(tables=tables)]))
    assert avail_ids("2026-09-24", "19:00", 2) == ["t_z", "t_a", "t_m"], "[L1.55] in fixture order"


def test_L1_2_L1_55_half_open_overlap_in_availability(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")  # occupies [19:00, 20:30)
    exp = {"18:00": False, "18:30": True, "19:00": True, "19:30": True, "20:00": True, "20:30": False, "21:00": False}
    # 18:00 slot occupies [18:00,19:30) overlaps 19:00; 20:30 slot starts when the booking ends -> free
    taken = {"18:00", "18:30", "19:00", "19:30", "20:00"}
    for at in ("18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"):
        ids = avail_ids(d, at, 4)
        if at in taken:
            assert ids == ["t_3"], f"[L1.2] {at} overlaps [19:00,20:30): t_2 must be unavailable, got {ids}"
        else:
            assert ids == ["t_2", "t_3"], f"[L1.2] {at} does not overlap (half-open): t_2 must be free, got {ids}"


def test_L1_55_other_tables_and_other_days_unaffected(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_3"], "[L1.55] only the booked table disappears"
    nxt = safe_date(1)
    assert avail_ids(nxt, "19:00", 4) == ["t_2", "t_3"], "[L1.55] other days unaffected"


def test_L1_4_restaurants_have_own_settings():
    r1 = restaurant("r_a", slot=30, dur=90, hours=all_week("18:00", "23:00"))
    r2 = restaurant("r_b", slot=15, dur=60, hours=all_week("12:00", "14:00"), tables=[{"id": "t_b", "label": "B", "capacity": 8}])
    reset(fixture(restaurants=[r1, r2]))
    a, _ = slots("2026-09-24", 2, "r_a"); b, _ = slots("2026-09-24", 2, "r_b")
    assert [k[-5:] for k in a] == expected("18:00", "23:00", 30, 90), "[L1.4] restaurant A grid"
    assert [k[-5:] for k in b] == ["12:00", "12:15", "12:30", "12:45", "13:00"], "[L1.4] restaurant B grid (own settings)"
    assert avail_ids("2026-09-24", "12:00", 8, "r_b") == ["t_b"] and avail_ids("2026-09-24", "18:00", 8, "r_a") == []
    # a booking at one restaurant never shows up as occupancy at another (same table label elsewhere)
    r3 = restaurant("r_c", tables=[{"id": "t_c", "label": "1", "capacity": 4}])
    reset(fixture(restaurants=[restaurant("r_a"), r3]))
    ada = login("ada@example.com")
    book_ok(ada, "2026-09-24", "19:00", "t_c", 4, "r_c")
    assert avail_ids("2026-09-24", "19:00", 2, "r_a") == ["t_1", "t_2", "t_3"], "[L1.4] restaurants independent"


def test_L1_52_availability_timezone_is_restaurants():
    reset(fixture(restaurants=[restaurant("r_ny", timezone="America/New_York", hours=all_week("18:00", "23:00"))]))
    s, j = slots("2026-09-24", 2, "r_ny")
    assert j["timezone"] == "America/New_York"
    assert s["2026-09-24T18:00"]["starts_at"] == "2026-09-24T18:00:00-04:00", "[L1.52] NY summer offset -04:00"
    reset(fixture(restaurants=[restaurant("r_ny", timezone="America/New_York", hours=all_week("18:00", "23:00"))]))
    s, _ = slots("2026-12-24", 2, "r_ny")
    assert s["2026-12-24T18:00"]["starts_at"] == "2026-12-24T18:00:00-05:00", "[L1.86] NY winter offset -05:00"
    s, _ = slots("2026-12-24", 2, "r_ny")
    reset(fixture())
    s, _ = slots("2026-12-24")
    assert s["2026-12-24T18:00"]["starts_at"] == "2026-12-24T18:00:00+01:00", "[L1.86] Berlin winter offset +01:00"


def test_L1_53_slot_starts_at_local_goes_into_post_unchanged(w):
    for k in ("18:00", "19:30", "21:00"):
        s, _ = slots(w.date, 2)
        slot = s[local(w.date, k)]
        r = w.ada.post("/reservations", json={"restaurant_id": "r_anker", "table_id": slot["available_table_ids"][0],
                                              "starts_at_local": slot["starts_at_local"], "party_size": 2}, key=new_key())
        j = check(r, 201, "L1.53")
        assert j["starts_at_local"] == slot["starts_at_local"] and j["starts_at"] == slot["starts_at"], f"[L1.53] {j} vs slot {slot}"
