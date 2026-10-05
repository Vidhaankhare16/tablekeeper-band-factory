"""Time zones and DST (ledger L1.59, L1.66, L1.82-L1.86). Past/arbitrary dates are legal (§4)."""
import datetime as dt
import pytest
from conftest import call, check, reset, fixture, restaurant, all_week, book, book_ok, slots, avail_ids, local, iso, \
    instant, login, new_key, body

BERLIN_SPRING, BERLIN_FALL = "2026-03-29", "2026-10-25"
NY_SPRING, NY_FALL = "2026-03-08", "2026-11-01"
Z = dt.timezone.utc


def world(tz, rid="r_z", **kw):
    reset(fixture(restaurants=[restaurant(rid, timezone=tz, hours=all_week("00:00", "23:30"),
                                          tables=[{"id": "tz1", "label": "1", "capacity": 4},
                                                  {"id": "tz2", "label": "2", "capacity": 4}], **kw)]))
    return login("ada@example.com")


def bk(a, date, at, table="tz1", party=2, key=None):
    return book(a, date, at, table, party, "r_z", key=key)


def times(date, tz):
    s, j = slots(date, 2, "r_z")
    return [k[-5:] for k in s], s


# ---- spring forward --------------------------------------------------------------------------

@pytest.mark.parametrize("tz,date,gap", [("Europe/Berlin", BERLIN_SPRING, ["02:00", "02:30"]),
                                         ("America/New_York", NY_SPRING, ["02:00", "02:30"])])
def test_L1_82_skipped_hour_not_in_availability_and_not_bookable(tz, date, gap):
    a = world(tz)
    ts, s = times(date, tz)
    for g in gap:
        assert g not in ts, f"[L1.82] nonexistent local time {g} must not appear in availability on {date}"
    for ok in ("00:00", "01:00", "01:30", "03:00", "03:30", "04:00", "12:00", "22:00"):
        assert ok in ts, f"[L1.82] {ok} exists on {date} and must appear"
    for g in gap:
        check(bk(a, date, g), 422, "L1.82/L1.66", "invalid_local_time")
    assert a.get("/reservations").json == {"reservations": []}, "[L1.66] nothing created"
    check(bk(a, date, "03:00"), 201, "L1.82")


@pytest.mark.parametrize("tz,date,pre,post", [("Europe/Berlin", BERLIN_SPRING, "+01:00", "+02:00"),
                                              ("America/New_York", NY_SPRING, "-05:00", "-04:00")])
def test_L1_86_offsets_across_spring_forward(tz, date, pre, post):
    a = world(tz)
    ts, s = times(date, tz)
    assert s[f"{date}T01:30"]["starts_at"] == f"{date}T01:30:00{pre}", f"[L1.86] {s[f'{date}T01:30']}"
    assert s[f"{date}T03:00"]["starts_at"] == f"{date}T03:00:00{post}", f"[L1.86] {s[f'{date}T03:00']}"
    assert s[f"{date}T12:00"]["starts_at"] == f"{date}T12:00:00{post}"
    assert s[f"{date}T00:00"]["starts_at"] == f"{date}T00:00:00{pre}"
    j = check(bk(a, date, "03:00"), 201, "L1.86")
    assert j["starts_at"] == f"{date}T03:00:00{post}" and j["starts_at_local"] == f"{date}T03:00"


@pytest.mark.parametrize("tz,date,pre,post", [("Europe/Berlin", BERLIN_SPRING, "+01:00", "+02:00"),
                                              ("America/New_York", NY_SPRING, "-05:00", "-04:00")])
def test_L1_84_duration_is_absolute_across_spring_forward(tz, date, pre, post):
    a = world(tz)
    # 01:30 (pre-offset) + 90 real minutes: 01:30 -> (02:00 skipped) -> wall clock reads 04:00 after the jump
    j = check(bk(a, date, "01:30"), 201, "L1.84")
    assert j["starts_at"] == f"{date}T01:30:00{pre}" and j["ends_at"] == f"{date}T04:00:00{post}", \
        f"[L1.84] 90 absolute minutes from 01:30 ends at 04:00 local after the spring jump: {j}"
    assert iso(j["ends_at"]) - iso(j["starts_at"]) == dt.timedelta(minutes=90)
    # occupancy is absolute: the booking ends at 04:00 local; a booking at 03:30 (30 real min earlier) overlaps, 04:00 doesn't
    check(bk(a, date, "03:30"), 409, "L1.84", "table_unavailable")
    check(bk(a, date, "04:00"), 201, "L1.2")
    # 00:30 + 90 min real = 03:00 local-after-jump wall? (00:30 pre -> 02:00 pre == 03:00 post) ends at 03:00 local
    j2 = check(bk(a, date, "00:30", table="tz2"), 201, "L1.84")
    assert j2["ends_at"] == f"{date}T03:00:00{post}", f"[L1.84] 00:30+90min crosses the jump: {j2}"
    assert instant(j2["ends_at"]) - instant(j2["starts_at"]) == dt.timedelta(minutes=90)


def test_L1_84_occupancy_across_gap_berlin():
    a = world("Europe/Berlin")
    d = BERLIN_SPRING
    check(bk(a, d, "01:00"), 201, "L1.84")           # 00:00Z..01:30Z i.e. ends 03:30 local (post)
    check(bk(a, d, "03:00"), 409, "L1.84", "table_unavailable")   # 03:00 local = 01:00Z -> overlaps
    check(bk(a, d, "03:30"), 201, "L1.2")             # 03:30 local = 01:30Z == end -> free


# ---- fall back -------------------------------------------------------------------------------

@pytest.mark.parametrize("tz,date,rep,first,second", [("Europe/Berlin", BERLIN_FALL, ["02:00", "02:30"], "+02:00", "+01:00"),
                                                      ("America/New_York", NY_FALL, ["01:00", "01:30"], "-04:00", "-05:00")])
def test_L1_83_repeated_hour_listed_once_first_occurrence(tz, date, rep, first, second):
    a = world(tz)
    ts, s = times(date, tz)
    for r in rep:
        assert ts.count(r) == 1, f"[L1.83] repeated local time {r} must appear exactly once on {date}, got {ts.count(r)}"
        assert s[f"{date}T{r}"]["starts_at"] == f"{date}T{r}:00{first}", \
            f"[L1.83] must resolve to the first occurrence (offset {first}): {s[f'{date}T{r}']}"
    assert len(ts) == len(set(ts)), "[L1.83] no duplicate slots"
    j = check(bk(a, date, rep[0]), 201, "L1.83")
    assert j["starts_at"] == f"{date}T{rep[0]}:00{first}", f"[L1.83] booking resolves to first occurrence: {j}"


def test_L1_83_second_occurrence_not_bookable_berlin():
    a = world("Europe/Berlin")
    d = BERLIN_FALL
    j = check(bk(a, d, "02:30"), 201, "L1.83")        # first occurrence 02:30+02:00 = 00:30Z .. 02:00Z (=03:00 CET)
    assert j["starts_at"] == f"{d}T02:30:00+02:00" and j["ends_at"] == f"{d}T03:00:00+01:00", f"[L1.84] {j}"
    # the string 02:30 cannot be used again for the *second* 02:30 (01:30Z): it still means the first occurrence
    check(bk(a, d, "02:30"), 409, "L1.83", "table_unavailable")
    # 03:00 local is 02:00Z == the end of the booking above (half-open) -> free
    check(bk(a, d, "03:00"), 201, "L1.2")


def test_L1_84_duration_absolute_fall_back_berlin():
    a = world("Europe/Berlin")
    d = BERLIN_FALL
    j = check(bk(a, d, "01:30"), 201, "L1.84")        # 01:30+02:00 = 23:30Z(24th); +90 = 01:00Z = 02:00 CET
    assert j["starts_at"] == f"{d}T01:30:00+02:00" and j["ends_at"] == f"{d}T02:00:00+01:00", \
        f"[L1.84] a 90-minute booking at 01:30 on a fall-back night ends at local 02:00 (+01:00), not 03:00: {j}"
    assert instant(j["ends_at"]) - instant(j["starts_at"]) == dt.timedelta(minutes=90)
    # next free instant is 01:00Z == 02:00 CET. 02:00 resolves to its FIRST occurrence (00:00Z) which overlaps.
    check(bk(a, d, "02:00"), 409, "L1.83/L1.84", "table_unavailable")
    # but other table is free
    check(bk(a, d, "02:00", table="tz2"), 201, "L1.83")


def test_L1_84_duration_absolute_fall_back_new_york():
    a = world("America/New_York")
    d = NY_FALL
    j = check(bk(a, d, "00:30"), 201, "L1.84")        # 00:30 EDT = 04:30Z; +90 = 06:00Z = 01:00 EST
    assert j["starts_at"] == f"{d}T00:30:00-04:00" and j["ends_at"] == f"{d}T01:00:00-05:00", f"[L1.84] {j}"
    k = check(bk(a, d, "01:00", table="tz2"), 201, "L1.83")   # first 01:00 EDT = 05:00Z; +90 = 06:30Z = 01:30 EST
    assert k["starts_at"] == f"{d}T01:00:00-04:00" and k["ends_at"] == f"{d}T01:30:00-05:00", f"[L1.84] {k}"
    check(bk(a, d, "01:00"), 409, "L1.83/L1.84", "table_unavailable")  # first 01:00 EDT (05:00Z) overlaps 04:30Z..06:00Z
    check(bk(a, d, "02:00"), 201, "L1.2")             # 02:00 EST = 07:00Z free


def test_L1_83_everything_after_fall_back_has_standard_offset():
    a = world("Europe/Berlin")
    ts, s = times(BERLIN_FALL, "Europe/Berlin")
    assert s[f"{BERLIN_FALL}T03:00"]["starts_at"] == f"{BERLIN_FALL}T03:00:00+01:00", "[L1.86] 03:00 is after the change"
    assert s[f"{BERLIN_FALL}T01:30"]["starts_at"] == f"{BERLIN_FALL}T01:30:00+02:00"
    assert s[f"{BERLIN_FALL}T22:00"]["starts_at"] == f"{BERLIN_FALL}T22:00:00+01:00"
    assert len(ts) == 45, f"[L1.83] 00:00..22:00 half-hours (45 slots) with the repeated hour listed once: {len(ts)}"


def test_L1_82_spring_slot_count():
    world("Europe/Berlin")
    ts, _ = times(BERLIN_SPRING, "Europe/Berlin")
    want = [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 22 * 60 + 1, 30) if m not in (120, 150)]
    assert ts == want, f"[L1.82] 00:00..22:00 minus the skipped 02:00 and 02:30 (43 slots), ascending: {ts}"


@pytest.mark.parametrize("tz", ["Europe/Berlin", "America/New_York"])
def test_L1_85_ordinary_days_unaffected(tz):
    a = world(tz)
    ts, s = times("2026-06-15", tz)
    assert "02:00" in ts and "02:30" in ts and ts.count("01:30") == 1
    off = "+02:00" if tz == "Europe/Berlin" else "-04:00"
    assert s["2026-06-15T02:00"]["starts_at"] == f"2026-06-15T02:00:00{off}"
    ts, s = times("2026-01-15", tz)
    assert s["2026-01-15T12:00"]["starts_at"] == f"2026-01-15T12:00:00{'+01:00' if tz == 'Europe/Berlin' else '-05:00'}"


def test_L1_59_local_time_resolved_in_restaurant_zone_not_server_zone():
    a = world("America/New_York")
    j = check(bk(a, "2026-07-01", "19:00"), 201, "L1.59")
    assert j["starts_at"] == "2026-07-01T19:00:00-04:00" and instant(j["starts_at"]) == dt.datetime(2026, 7, 1, 23, 0, tzinfo=Z)
    reset(fixture(restaurants=[restaurant("r_z", timezone="Asia/Kolkata", hours=all_week("10:00", "20:00"),
                                          tables=[{"id": "tz1", "label": "1", "capacity": 4}])]))
    a = login("ada@example.com")
    j = check(bk(a, "2026-07-01", "10:30"), 201, "L1.59")
    assert j["starts_at"] == "2026-07-01T10:30:00+05:30", "[L1.59] half-hour zone offsets are honoured"


def test_L1_86_us_and_eu_transition_weeks_differ():
    # 2026-03-15: US already on DST (since 03-08), EU not yet (03-29) -> offsets -04:00 vs +01:00
    a = world("America/New_York")
    _, s = times("2026-03-15", "America/New_York")
    assert s["2026-03-15T12:00"]["starts_at"] == "2026-03-15T12:00:00-04:00"
    world("Europe/Berlin")
    _, s = times("2026-03-15", "Europe/Berlin")
    assert s["2026-03-15T12:00"]["starts_at"] == "2026-03-15T12:00:00+01:00"
    # 2026-10-28: EU already back (10-25), US not yet (11-01) -> +01:00 vs -04:00
    _, s = times("2026-10-28", "Europe/Berlin")
    assert s["2026-10-28T12:00"]["starts_at"] == "2026-10-28T12:00:00+01:00"
    world("America/New_York")
    _, s = times("2026-10-28", "America/New_York")
    assert s["2026-10-28T12:00"]["starts_at"] == "2026-10-28T12:00:00-04:00"
