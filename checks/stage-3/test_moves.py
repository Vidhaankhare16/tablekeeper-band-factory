"""Atomic reservation moves (ledger L1.98-L1.113)."""
import datetime as dt
import pytest
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, body, new_key, \
    burst, avail_ids, local, login, slots

PAST = "2020-01-08"


def mv(c, moves, key=None):
    return c.post("/reservation-moves", json={"moves": moves}, key=new_key() if key is None else key)


def get(c, ref):
    return c.get(f"/reservations/{ref}").json


def three(w, at="19:00", party=2):
    """ada: one booking on each of t_1, t_2, t_3 at the same time."""
    return [book_ok(w.ada, w.date, at, t, party) for t in ("t_1", "t_2", "t_3")]


def test_L1_98_auth_required(w):
    a = book_ok(w.ada, w.date)
    check(call("POST", "/reservation-moves", json={"moves": [{"reference": a["reference"], "table_id": "t_3"}]},
               key=new_key()), 401, "L1.98", "unauthenticated")
    check(call("POST", "/reservation-moves", json={"moves": [{"reference": a["reference"]}]}, key=new_key(),
               token="bogus"), 401, "L1.98", "unauthenticated")
    check(w.ada.post("/reservation-moves", json={"moves": [{"reference": a["reference"], "table_id": "t_3"}]}), 400, "L1.98",
          "missing_idempotency_key")
    assert get(w.ada, a["reference"])["table_id"] == "t_2"


def test_L1_99_shape_errors_are_422(w):
    r1 = book_ok(w.ada, w.date, "19:00", "t_2")["reference"]
    r2 = book_ok(w.ada, w.date, "19:00", "t_3")["reference"]
    bad = [("empty list", {"moves": []}), ("missing moves", {}), ("duplicate refs", {"moves": [{"reference": r1}, {"reference": r1}]}),
           ("duplicate refs with different fields", {"moves": [{"reference": r1, "table_id": "t_3"}, {"reference": r1, "table_id": "t_1"}]}),
           ("item without reference", {"moves": [{"table_id": "t_1"}]}),
           ("reference number", {"moves": [{"reference": 5}]}),
           ("reference null", {"moves": [{"reference": None}]}),
           ("reference list", {"moves": [{"reference": [r1]}]}),
           ("item string", {"moves": [r1]}), ("item null", {"moves": [None]}), ("item number", {"moves": [3]}),
           ("item list", {"moves": [[r1]]})]
    for name, b in bad:
        check(w.ada.post("/reservation-moves", json=b, key=new_key()), 422, f"L1.99 ({name})", "validation_failed")
    # READING R5: a non-array `moves` is an "invalid shape" => 422 (endpoint rule wins over the generic wrong-type 400)
    for name, v in (("string", "x"), ("object", {"a": 1}), ("null", None), ("number", 4)):
        check(w.ada.post("/reservation-moves", json={"moves": v}, key=new_key()), 422, f"L1.99 (moves {name})",
              "validation_failed")
    # body that is not an object is a parse-level error
    check(w.ada.post("/reservation-moves", raw="[1]", key=new_key()), 400, "L1.20", "malformed_request")
    check(w.ada.post("/reservation-moves", raw="{x", key=new_key()), 400, "L1.20", "malformed_request")
    assert get(w.ada, r1)["table_id"] == "t_2" and get(w.ada, r2)["table_id"] == "t_3"


def test_L1_99_one_to_eight_moves(w):
    refs = []
    for i in range(9):
        refs.append(book_ok(w.ada, safe_date(i), "19:00", "t_2", 2)["reference"])
    nine = [{"reference": r, "table_id": "t_3"} for r in refs]
    check(w.ada.post("/reservation-moves", json={"moves": nine}, key=new_key()), 422, "L1.99", "validation_failed")
    assert all(get(w.ada, r)["table_id"] == "t_2" for r in refs), "[L1.99] nothing applied for 9 moves"
    eight = nine[:8]
    j = check(w.ada.post("/reservation-moves", json={"moves": eight}, key=new_key()), 201, "L1.99")
    assert [x["reference"] for x in j["reservations"]] == refs[:8] and all(x["table_id"] == "t_3" for x in j["reservations"])
    one = check(w.ada.post("/reservation-moves", json={"moves": [{"reference": refs[8], "table_id": "t_3"}]}, key=new_key()),
                201, "L1.99")
    assert len(one["reservations"]) == 1


def test_L1_100_unknown_and_foreign_references_404(w):
    mine = book_ok(w.ada, w.date, "19:00", "t_2")
    theirs = book_ok(w.bob, w.date, "19:00", "t_3", 5)
    check(mv(w.ada, [{"reference": "NOPE99", "table_id": "t_1"}]), 404, "L1.100", "not_found")
    check(mv(w.ada, [{"reference": mine["reference"], "table_id": "t_1"}, {"reference": "NOPE99"}]), 404, "L1.100", "not_found")
    check(mv(w.ada, [{"reference": theirs["reference"], "table_id": "t_1"}]), 404, "L1.100", "not_found")
    check(mv(w.ada, [{"reference": mine["reference"], "table_id": "t_1"}, {"reference": theirs["reference"], "table_id": "t_3"}]),
          404, "L1.100", "not_found")
    assert get(w.ada, mine["reference"]) == mine and get(w.bob, theirs["reference"]) == theirs, "[L1.100] nothing changed"


def test_L1_100_different_restaurants_422(w):
    a = book_ok(w.ada, w.date, "19:00", "t_2", 4, "r_anker")
    b = book_ok(w.ada, w.date, "19:00", "t_x1", 4, "r_two")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_3"}, {"reference": b["reference"]}]), 422, "L1.100",
          "validation_failed")
    check(mv(w.ada, [{"reference": b["reference"]}, {"reference": a["reference"]}]), 422, "L1.100", "validation_failed")
    assert get(w.ada, a["reference"]) == a and get(w.ada, b["reference"]) == b


def test_L1_101_partial_items_retain_other_fields(w):
    d = w.date
    a = book_ok(w.ada, d, "19:00", "t_2", 4)
    b = book_ok(w.ada, d, "19:00", "t_3", 5)
    j = check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_1", "party_size": 2},
                         {"reference": b["reference"], "starts_at_local": local(d, "21:00")}]), 201, "L1.101")["reservations"]
    assert (j[0]["table_id"], j[0]["party_size"], j[0]["starts_at_local"]) == ("t_1", 2, local(d, "19:00")), f"[L1.101] {j[0]}"
    assert (j[1]["table_id"], j[1]["party_size"], j[1]["starts_at_local"]) == ("t_3", 5, local(d, "21:00")), f"[L1.101] {j[1]}"
    assert j[1]["starts_at"].startswith(f"{d}T21:00:00") and (dt.datetime.fromisoformat(j[1]["ends_at"]) -
                                                               dt.datetime.fromisoformat(j[1]["starts_at"])) == dt.timedelta(minutes=90)
    c = check(mv(w.ada, [{"reference": a["reference"], "party_size": 1, "bogus": [1, 2], "status": "cancelled",
                          "reference_id": "x", "created_at": "2000-01-01T00:00:00+00:00", "user_id": "u_bob"}]), 201, "L1.101")
    x = c["reservations"][0]
    assert x["party_size"] == 1 and x["status"] == "confirmed" and x["created_at"] == a["created_at"], \
        f"[L1.101/L1.102] unknown fields ignored; identity/owner/creation time never change: {x}"
    assert get(w.ada, a["reference"]) == x
    assert get(w.bob, a["reference"]) is not None and w.bob.get(f"/reservations/{a['reference']}").status == 404, "[L1.102] owner unchanged"


def test_L1_102_identity_never_changes(w):
    a = three(w)
    j = check(mv(w.ada, [{"reference": a[0]["reference"], "table_id": "t_2"}, {"reference": a[1]["reference"], "table_id": "t_3"},
                         {"reference": a[2]["reference"], "table_id": "t_1"}]), 201, "L1.102")["reservations"]
    for before, after in zip(a, j):
        for k in ("reference", "reservation_id", "created_at", "restaurant_id", "status"):
            assert before[k] == after[k], f"[L1.102] {k} must not change"
    assert [x["reference"] for x in w.ada.get("/reservations").json["reservations"]].__len__() == 3


def test_L1_113_swap_rotation_and_time_swaps_validate_resulting_state(w):
    d = w.date
    a = three(w)                                             # t_1, t_2, t_3 all at 19:00
    j = check(mv(w.ada, [{"reference": a[0]["reference"], "table_id": "t_2"}, {"reference": a[1]["reference"], "table_id": "t_3"},
                         {"reference": a[2]["reference"], "table_id": "t_1"}]), 201, "L1.113")["reservations"]
    assert [x["table_id"] for x in j] == ["t_2", "t_3", "t_1"], "[L1.113] a rotation is valid: only the resulting state matters"
    # swap times on the same table: A [19:00,20:30) B [20:30,22:00)  ->  A [20:30..) B [19:00..)
    reset(fixture()); ada = login("ada@example.com")
    x = book_ok(ada, d, "19:00", "t_2", 2); y = book_ok(ada, d, "20:30", "t_2", 2)
    j = check(mv(ada, [{"reference": x["reference"], "starts_at_local": local(d, "20:30")},
                       {"reference": y["reference"], "starts_at_local": local(d, "19:00")}]), 201, "L1.113")["reservations"]
    assert [v["starts_at_local"] for v in j] == [local(d, "20:30"), local(d, "19:00")]
    assert avail_ids(d, "19:00", 2) == ["t_1", "t_3"] and avail_ids(d, "21:00", 2) == ["t_1", "t_3"]
    # half-open boundary inside a batch: slide A to start exactly when B ends
    j = check(mv(ada, [{"reference": y["reference"], "starts_at_local": local(d, "18:00")},
                       {"reference": x["reference"], "starts_at_local": local(d, "19:30")}]), 201, "L1.2/L1.113")["reservations"]
    assert [v["starts_at_local"] for v in j] == [local(d, "18:00"), local(d, "19:30")]


def test_L1_106_overlap_among_resulting_bookings_is_409(w):
    d = w.date
    a, b, _ = three(w)
    r = mv(w.ada, [{"reference": a["reference"], "table_id": "t_3"}, {"reference": b["reference"], "table_id": "t_3"}])
    check(r, 409, "L1.106", "table_unavailable")
    for x in (a, b):
        assert get(w.ada, x["reference"]) == x, "[L1.106/L1.108] nothing changed"
    # overlap but not identical start: [19:00,20:30) vs [20:00,21:30) on one table
    check(book(w.ada, d, "21:00", "t_1", 2), 201, "setup")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_1", "starts_at_local": local(d, "20:00")}]), 409,
          "L1.106", "table_unavailable")


def test_L1_106_overlap_with_unlisted_booking_is_409(w):
    d = w.date
    a = book_ok(w.ada, d, "19:00", "t_2", 2)
    mine_other = book_ok(w.ada, d, "19:00", "t_1", 2)
    bobs = book_ok(w.bob, d, "19:00", "t_3", 6)
    ada_unlisted = book_ok(w.ada, safe_date(1), "19:00", "t_3", 6)
    for target, start in (("t_3", "19:00"), ("t_3", "18:00"), ("t_3", "20:00")):
        check(mv(w.ada, [{"reference": a["reference"], "table_id": target, "starts_at_local": local(d, start)}]), 409,
              "L1.106", "table_unavailable")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_1"}]), 409, "L1.106", "table_unavailable")  # my own unlisted
    # touching (half-open) is fine
    j = check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_3", "starts_at_local": local(d, "20:30"),
                          "party_size": 2}]), 201, "L1.2/L1.106")
    assert j["reservations"][0]["starts_at_local"] == local(d, "20:30")


def test_L1_107_unchanged_listed_bookings_keep_occupancy(w):
    d = w.date
    a, b, _ = three(w)
    check(mv(w.ada, [{"reference": a["reference"]}, {"reference": b["reference"], "table_id": "t_1"}]), 409, "L1.107",
          "table_unavailable")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_1"}, {"reference": b["reference"], "table_id": "t_1"}]), 409,
          "L1.107", "table_unavailable")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_2"}, {"reference": b["reference"], "table_id": "t_2"}]), 409,
          "L1.107", "table_unavailable")      # a moves onto b's table while b is *also* in the batch but stays there
    assert avail_ids(d, "19:00", 2) == [], "[L1.107] occupancy unchanged"


def test_L1_108_all_or_nothing_including_retry_keys(w):
    d = w.date
    a, b, c = three(w)
    key = new_key()
    snap = w.ada.get("/reservations").json
    bad = [{"reference": a["reference"], "table_id": "t_1", "starts_at_local": local(d, "21:00")},     # valid move
           {"reference": b["reference"], "table_id": "t_3"}]                                           # collides with c
    check(w.ada.post("/reservation-moves", json={"moves": bad}, key=key), 409, "L1.108", "table_unavailable")
    assert w.ada.get("/reservations").json == snap, "[L1.108] reservation records unchanged"
    assert avail_ids(d, "21:00", 2) == ["t_1", "t_2", "t_3"], "[L1.108] the valid first move left no occupancy behind"
    assert avail_ids(d, "19:00", 2) == [], "[L1.108] original occupancy intact"
    good = [bad[0], {"reference": b["reference"], "table_id": "t_2", "starts_at_local": local(d, "21:00"), "party_size": 1}]
    j = check(w.ada.post("/reservation-moves", json={"moves": good}, key=key), 201, "L1.108")   # failed key is a first use
    assert j["reservations"][0]["starts_at_local"] == local(d, "21:00")
    assert check(w.ada.post("/reservation-moves", json={"moves": good}, key=key), 200, "L1.110") == j


@pytest.mark.parametrize("name,items,status,code", [
    ("capacity", [{"table_id": "t_1", "party_size": 3}], 422, "party_exceeds_capacity"),
    ("grid", [{"starts_at_local": "{d}T19:15"}], 422, "not_on_slot_grid"),
    ("hours", [{"starts_at_local": "{d}T22:30"}], 422, "outside_opening_hours"),
    ("party zero", [{"party_size": 0}], 422, "validation_failed"),
    ("party string", [{"party_size": "2"}], 422, "validation_failed"),
    ("bad time format", [{"starts_at_local": "{d}T19:00:00"}], 422, "validation_failed"),
    ("unknown table", [{"table_id": "t_nope"}], 404, "not_found"),
    ("other restaurant's table", [{"table_id": "t_x1"}], 404, "not_found"),
])
def test_L1_101_ordinary_amendment_codes(w, name, items, status, code):
    d = w.date
    a = book_ok(w.ada, d, "19:00", "t_2", 2)
    it = {"reference": a["reference"]}
    for k, v in items[0].items():
        it[k] = v.replace("{d}", d) if isinstance(v, str) else v
    check(mv(w.ada, [it]), status, f"L1.101/L1.76 ({name})", code)
    assert get(w.ada, a["reference"]) == a


def test_L1_103_cancelled_is_409(w):
    a = book_ok(w.ada, w.date, "19:00", "t_2", 2)
    b = book_ok(w.ada, w.date, "19:00", "t_3", 2)
    w.ada.post(f"/reservations/{a['reference']}/cancel")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_1"}]), 409, "L1.103", "reservation_cancelled")
    check(mv(w.ada, [{"reference": b["reference"], "table_id": "t_1"}, {"reference": a["reference"]}]), 409, "L1.103",
          "reservation_cancelled")
    assert get(w.ada, b["reference"]) == b, "[L1.103/L1.108] the other move was not applied"
    assert avail_ids(w.date, "19:00", 2) == ["t_1", "t_2"], "[L1.103] cancelled booking not revived"


def test_L1_104_each_bookings_cutoff_applies(w):
    old = book_ok(w.ada, PAST, "19:00", "t_2", 2)
    new = book_ok(w.ada, w.date, "19:00", "t_2", 2)
    check(mv(w.ada, [{"reference": old["reference"], "table_id": "t_3"}]), 409, "L1.104", "cutoff_passed")
    check(mv(w.ada, [{"reference": new["reference"], "table_id": "t_3"}, {"reference": old["reference"], "table_id": "t_3"}]),
          409, "L1.104", "cutoff_passed")
    check(mv(w.ada, [{"reference": old["reference"], "table_id": "t_3"}, {"reference": new["reference"], "table_id": "t_3"}]),
          409, "L1.104", "cutoff_passed")
    assert get(w.ada, new["reference"]) == new and get(w.ada, old["reference"]) == old


def test_L1_105_errors_in_input_order_cutoff_first(w):
    d = w.date
    old = book_ok(w.ada, PAST, "19:00", "t_2", 2)
    a = book_ok(w.ada, d, "19:00", "t_2", 2)
    c = book_ok(w.ada, d, "19:00", "t_3", 2)
    w.ada.post(f"/reservations/{c['reference']}/cancel")
    # first failing item (input order) decides
    check(mv(w.ada, [{"reference": a["reference"], "party_size": 9}, {"reference": c["reference"]}]), 422, "L1.105",
          "party_exceeds_capacity")
    check(mv(w.ada, [{"reference": c["reference"]}, {"reference": a["reference"], "party_size": 9}]), 409, "L1.105",
          "reservation_cancelled")
    check(mv(w.ada, [{"reference": a["reference"], "starts_at_local": local(d, "19:15")},
                     {"reference": old["reference"], "table_id": "t_1"}]), 422, "L1.105", "not_on_slot_grid")
    check(mv(w.ada, [{"reference": old["reference"], "table_id": "t_1"},
                     {"reference": a["reference"], "starts_at_local": local(d, "19:15")}]), 409, "L1.105", "cutoff_passed")
    # for ONE booking the cutoff precedes its other (field) errors
    check(mv(w.ada, [{"reference": old["reference"], "party_size": 99, "starts_at_local": local(d, "19:15")}]), 409, "L1.105",
          "cutoff_passed")


def test_L1_106_non_occupancy_errors_beat_occupancy_errors(w):
    d = w.date
    a, b, c = three(w)
    # item 1 collides (occupancy), item 2 has a grid error (non-occupancy) => the grid error is reported
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_2"}, {"reference": b["reference"], "starts_at_local": local(d, "19:10")}]),
          422, "L1.106", "not_on_slot_grid")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_2"}, {"reference": b["reference"], "party_size": 99}]),
          422, "L1.106", "party_exceeds_capacity")
    w.ada.post(f"/reservations/{c['reference']}/cancel")
    check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_2"}, {"reference": c["reference"]}]), 409, "L1.106",
          "reservation_cancelled")


def test_L1_109_response_shape_order_and_unchanged_items(w):
    d = w.date
    a, b, c = three(w)
    r = mv(w.ada, [{"reference": c["reference"], "starts_at_local": local(d, "21:00")}, {"reference": a["reference"]},
                   {"reference": b["reference"], "party_size": 1}])
    j = check(r, 201, "L1.109")
    assert list(j) == ["reservations"] and [x["reference"] for x in j["reservations"]] == [c["reference"], a["reference"], b["reference"]], \
        f"[L1.109] input order, including unchanged items: {r!r}"
    assert j["reservations"][1] == a, "[L1.111] unchanged item is returned as it was"
    for x in j["reservations"]:
        assert get(w.ada, x["reference"]) == x, "[L1.109] response equals stored state"
    assert j["reservations"][0]["starts_at_local"] == local(d, "21:00") and j["reservations"][2]["party_size"] == 1


def test_L1_111_noop_moves_retain_values(w):
    d = w.date
    a = book_ok(w.ada, d, "19:00", "t_2", 3)
    j = check(mv(w.ada, [{"reference": a["reference"]}]), 201, "L1.111")["reservations"][0]
    assert j == a
    j = check(mv(w.ada, [{"reference": a["reference"], "table_id": "t_2", "starts_at_local": local(d, "19:00"), "party_size": 3}]),
              201, "L1.111")["reservations"][0]
    assert j == a, "[L1.111] explicit same values change nothing"
    assert avail_ids(d, "19:00", 4) == ["t_3"]


def test_L1_110_replay_is_original_even_after_changes(w):
    d = w.date
    a, b, _ = three(w)
    key = new_key()
    b1 = {"moves": [{"reference": a["reference"], "table_id": "t_2"}, {"reference": b["reference"], "table_id": "t_1"}]}
    first = check(w.ada.post("/reservation-moves", json=b1, key=key), 201, "L1.110")
    assert check(w.ada.post("/reservation-moves", json=b1, key=key), 200, "L1.110") == first
    w.ada.patch(f"/reservations/{a['reference']}", json={"party_size": 1, "starts_at_local": local(d, "21:00")})
    w.ada.post(f"/reservations/{b['reference']}/cancel")
    state = w.ada.get("/reservations").json
    r = w.ada.post("/reservation-moves", json=b1, key=key)
    assert check(r, 200, "L1.110") == first, "[L1.110] replay returns the original response, not current state"
    assert w.ada.get("/reservations").json == state, "[L1.110] replay makes no state change"
    # key order / whitespace irrelevant
    raw = '{"moves": [ {"table_id":"t_2","reference":"%s"} , {"table_id":"t_1","reference":"%s"} ]}' % (a["reference"], b["reference"])
    assert check(w.ada.post("/reservation-moves", raw=raw, key=key), 200, "L1.110") == first
    check(w.ada.post("/reservation-moves", json={"moves": [{"reference": a["reference"]}]}, key=key), 409, "L1.110",
          "idempotency_key_reuse")
    # idempotency precedes field validation: used key + invalid body => 409
    check(w.ada.post("/reservation-moves", json={"moves": []}, key=key), 409, "L1.43", "idempotency_key_reuse")
    check(w.ada.post("/reservation-moves", json={"nonsense": 1}, key=key), 409, "L1.43", "idempotency_key_reuse")


def test_L1_41_move_keys_scoped_per_user(w):
    a = book_ok(w.ada, w.date, "19:00", "t_2", 2)
    b = book_ok(w.bob, w.date, "19:00", "t_3", 2)
    key = "same-key"
    ja = check(w.ada.post("/reservation-moves", json={"moves": [{"reference": a["reference"], "table_id": "t_1"}]}, key=key),
               201, "L1.41")
    jb = check(w.bob.post("/reservation-moves", json={"moves": [{"reference": b["reference"], "table_id": "t_1"}]}, key=key),
               409, "L1.41", "table_unavailable")
    jb = check(w.bob.post("/reservation-moves", json={"moves": [{"reference": b["reference"], "table_id": "t_2"}]}, key=key),
               201, "L1.41")
    assert jb["reservations"][0]["table_id"] == "t_2" and ja["reservations"][0]["table_id"] == "t_1"


def test_L1_46_concurrent_identical_move_requests_apply_once(w):
    d = w.date
    a, b, c = three(w)
    key = new_key()
    b1 = {"moves": [{"reference": a["reference"], "table_id": "t_2", "starts_at_local": local(d, "21:00")},
                    {"reference": b["reference"], "table_id": "t_3"}, {"reference": c["reference"], "table_id": "t_1"}]}
    out = burst(50, lambda i: w.ada.post("/reservation-moves", json=b1, key=key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 49 + [201], f"[L1.46] exactly one 201 and 49 replays: {codes.count(201)}x201 {sorted(set(codes))}"
    first = [r.json for r in out if r.status == 201][0]
    assert all(r.json == first for r in out)
    assert [x["table_id"] for x in w.ada.get("/reservations").json["reservations"]].count("t_3") == 1
    assert avail_ids(d, "21:00", 2) == ["t_1", "t_3"] and avail_ids(d, "19:00", 2) == ["t_2"]


def test_L1_1_competing_batches_one_winner():
    users = [user(f"m{i:02d}") for i in range(20)]
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(21)]
    reset(fixture(users=users, restaurants=[restaurant("r_big", tables=tables)]))
    clients = [login(f"m{i:02d}@example.com") for i in range(20)]
    d = safe_date()
    mine = [book_ok(c, d, "19:00", f"t_{i}", 2, "r_big") for i, c in enumerate(clients)]
    out = burst(20, lambda i: mv(clients[i], [{"reference": mine[i]["reference"], "table_id": "t_20"}]))
    codes = [r.status for r in out]
    assert codes.count(201) == 1 and codes.count(409) == 19, f"[L1.1/L1.106] exactly one batch may take t_20: {sorted(codes)}"
    for r in out:
        if r.status == 409:
            check(r, 409, "L1.106", "table_unavailable")
    winner = codes.index(201)
    for i, c in enumerate(clients):
        now = get(c, mine[i]["reference"])
        assert now["table_id"] == ("t_20" if i == winner else f"t_{i}"), f"[L1.108] loser {i} must be untouched: {now}"
    s, _ = slots(d, 2, "r_big")
    free = s[local(d, "19:00")]["available_table_ids"]
    assert free == [f"t_{winner}"], f"[L1.1] only the winner's old table is free: {free}"
