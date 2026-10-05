"""Concurrency invariants (ledger L1.1, L1.3, L1.14, L1.46, L1.79, L1.80)."""
import random
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, body, new_key, \
    burst, avail_ids, local, login, iso, slots

N = 50


def users_fx(n, tables=1, **kw):
    us = [user(f"c{i:02d}") for i in range(n)]
    ts = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(tables)]
    reset(fixture(users=us, restaurants=[restaurant("r_c", tables=ts, **kw)]))
    return burst(n, lambda i: login(f"c{i:02d}@example.com"))


def all_reservations(clients):
    out = []
    for c in clients:
        out += c.get("/reservations").json["reservations"]
    return out


def assert_no_overlap(res, lid="L1.1"):
    by = {}
    for r in res:
        if r["status"] == "confirmed":
            by.setdefault((r["restaurant_id"], r["table_id"]), []).append((iso(r["starts_at"]), iso(r["ends_at"]), r["reference"]))
    for k, v in by.items():
        v.sort()
        for (s1, e1, a), (s2, e2, b) in zip(v, v[1:]):
            assert e1 <= s2, f"[{lid}] confirmed reservations {a} and {b} overlap on table {k}"


def test_L1_1_fifty_users_one_table_one_slot():
    cl = users_fx(N)
    d = safe_date()
    out = burst(N, lambda i: book(cl[i], d, "19:00", "t_0", 2, "r_c"))
    codes = [r.status for r in out]
    assert codes.count(201) == 1 and codes.count(409) == N - 1, f"[L1.1] exactly one of {N} may win: {sorted(set(codes))} 201x{codes.count(201)}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L1.1", "table_unavailable")
    res = all_reservations(cl)
    assert len(res) == 1, "[L1.3] rejected requests left no bookings behind"
    assert_no_overlap(res)
    s, _ = slots(d, 2, "r_c")
    assert s[local(d, "19:00")]["available_table_ids"] == []


def test_L1_1_overlapping_start_times_never_double_book():
    cl = users_fx(N)
    d = safe_date()
    starts = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    out = burst(N, lambda i: book(cl[i], d, starts[i % len(starts)], "t_0", 2, "r_c"))
    assert all(r.status in (201, 409) for r in out), f"[L1.1/L1.14] {sorted({r.status for r in out})}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L1.1", "table_unavailable")
    res = all_reservations(cl)
    assert len(res) == sum(r.status == 201 for r in out) >= 1, "[L1.3] one reservation per 201, none for 409"
    assert_no_overlap(res)
    # availability agrees with the winners
    s, _ = slots(d, 2, "r_c")
    for k, v in s.items():
        slot_start = iso(v["starts_at"])
        busy = any(iso(r["starts_at"]) < slot_start + (iso(r["ends_at"]) - iso(r["starts_at"])) and slot_start < iso(r["ends_at"])
                   for r in res)
        assert (v["available_table_ids"] == []) == busy, f"[L1.55] availability at {k} disagrees with bookings"


def test_L1_1_many_tables_all_slots_filled_exactly():
    cl = users_fx(N, tables=5)
    d = safe_date()
    # 50 requests over 5 tables at one slot: exactly 5 succeed, whichever tables they pick
    out = burst(N, lambda i: book(cl[i], d, "19:00", f"t_{i % 5}", 2, "r_c"))
    codes = [r.status for r in out]
    assert codes.count(201) == 5 and codes.count(409) == 45, f"[L1.1] one winner per table: {sorted(set(codes))}"
    assert len({r.json["table_id"] for r in out if r.status == 201}) == 5
    assert_no_overlap(all_reservations(cl))


def test_L1_14_fifty_in_flight_mixed_reads_no_5xx_and_fast(w):
    d = w.date
    book_ok(w.ada, d, "19:00", "t_2")
    def op(i):
        k = i % 5
        if k == 0: return call("GET", "/health")
        if k == 1: return call("GET", f"/availability?restaurant_id=r_anker&date={d}&party_size=2")
        if k == 2: return w.ada.get("/reservations")
        if k == 3: return call("GET", "/restaurants/r_anker")
        return call("POST", "/auth/login", json={"email": "bob@example.com", "password": "correct horse"})
    out = burst(N, op)
    assert all(r.status == 200 for r in out), f"[L1.14] all 50 concurrent requests succeed within the timeout: {[r.status for r in out]}"


def test_L1_14_fifty_concurrent_signups_and_logins():
    reset(fixture())
    out = burst(N, lambda i: call("POST", "/auth/signup", json={"email": f"s{i}@x.io", "password": "12345678", "display_name": f"S{i}"}))
    assert all(r.status == 201 for r in out), f"[L1.14] {[r.status for r in out]}"
    assert len({r.json["user_id"] for r in out}) == N and len({r.json["token"] for r in out}) == N
    out2 = burst(N, lambda i: call("POST", "/auth/login", json={"email": f"s{i}@x.io", "password": "12345678"}))
    assert all(r.status == 200 for r in out2) and [r.json["user_id"] for r in out2] == [r.json["user_id"] for r in out]


def test_L1_80_L1_79_concurrent_patches_onto_one_slot():
    cl = users_fx(N, tables=1)
    d = safe_date()
    # each user holds a booking on its own day; all try to amend onto the same slot of day d
    days = [safe_date(i + 1) for i in range(N)]
    mine = [book_ok(cl[i], days[i], "19:00", "t_0", 2, "r_c") for i in range(N)]
    out = burst(N, lambda i: cl[i].patch(f"/reservations/{mine[i]['reference']}", json={"starts_at_local": local(d, "19:00")}))
    codes = [r.status for r in out]
    assert codes.count(200) == 1 and codes.count(409) == N - 1, f"[L1.79] exactly one amendment may take the slot: {sorted(set(codes))}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L1.79", "table_unavailable")
    winner = codes.index(200)
    for i, c in enumerate(cl):
        now = c.get(f"/reservations/{mine[i]['reference']}").json
        want = local(d, "19:00") if i == winner else local(days[i], "19:00")
        assert now["starts_at_local"] == want and now["reference"] == mine[i]["reference"], f"[L1.80] booking {i} wrong: {now}"
    assert avail_ids(days[winner], "19:00", 2, "r_c") == ["t_0"], "[L1.79] the winner's old slot was released"
    assert_no_overlap(all_reservations(cl))


def test_L1_71_concurrent_cancel_and_rebook_cycles():
    cl = users_fx(10)
    d = safe_date()
    first = book_ok(cl[0], d, "19:00", "t_0", 2, "r_c")
    def op(i):
        if i == 0:
            return cl[0].post(f"/reservations/{first['reference']}/cancel")
        return book(cl[i], d, "19:00", "t_0", 2, "r_c")
    out = burst(10, op)
    assert out[0].status == 200 and all(r.status in (201, 409) for r in out[1:]), f"[L1.71] {[r.status for r in out]}"
    assert sum(r.status == 201 for r in out[1:]) <= 1, "[L1.1] at most one rebooking can win the freed slot"
    assert_no_overlap(all_reservations(cl))


def test_L1_46_fifty_distinct_keys_distinct_slots_all_succeed_unique_refs():
    tables = 25
    cl = users_fx(N, tables=tables)
    d = safe_date()
    out = burst(N, lambda i: book(cl[i], d, "19:00" if i < 25 else "21:00", f"t_{i % 25}", 2, "r_c"))
    # t_i at 19:00 for i<25, same tables at 21:00 for i>=25 -> [19:00,20:30) vs [21:00,22:30): no overlap
    assert all(r.status == 201 for r in out), f"[L1.46] {[r.status for r in out]}"
    refs = [r.json["reference"] for r in out]
    assert len(set(refs)) == N and len({r.json["reservation_id"] for r in out}) == N, "[L1.60] unique references/ids under load"
