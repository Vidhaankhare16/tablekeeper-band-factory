"""Idempotency (ledger L1.21, L1.25, L1.30, L1.41-L1.47)."""
import json
import pytest
from conftest import call, check, reset, fixture, safe_date, book, book_ok, body, new_key, burst, avail_ids, local, login


def test_L1_21_missing_or_empty_key_is_400(w):
    check(w.ada.post("/reservations", json=body(w.date)), 400, "L1.21", "missing_idempotency_key")
    check(w.ada.post("/reservations", json=body(w.date), key=""), 400, "L1.21", "missing_idempotency_key")
    check(w.ada.post("/reservation-moves", json={"moves": [{"reference": "ABCDEF"}]}), 400, "L1.21", "missing_idempotency_key")
    check(w.ada.post("/reservation-moves", json={"moves": [{"reference": "ABCDEF"}]}, key=""), 400, "L1.21",
          "missing_idempotency_key")
    assert w.ada.get("/reservations").json == {"reservations": []}, "[L1.21] nothing created"


def test_L1_43_missing_key_beats_field_validation(w):
    # §7: idempotency is resolved before endpoint-specific field validation.
    check(w.ada.post("/reservations", json=body(w.date, party=0)), 400, "L1.43", "missing_idempotency_key")
    check(w.ada.post("/reservations", json={}), 400, "L1.43", "missing_idempotency_key")


def test_L1_43_malformed_body_precedes_key_check(w):
    # READING R3: "After the body has been parsed as a JSON object and the caller authenticated" => parse errors first.
    check(w.ada.post("/reservations", raw="{bad"), 400, "L1.43", "malformed_request")
    check(w.ada.post("/reservations", raw="[1]"), 400, "L1.43", "malformed_request")


def test_L1_30_key_length_boundaries(w):
    d = w.date
    check(book(w.ada, d, "18:00", "t_1", 2, key="k"), 201, "L1.30")
    check(book(w.ada, d, "19:30", "t_1", 2, key="K" * 255), 201, "L1.30")
    check(book(w.ada, d, "21:00", "t_1", 2, key="x" * 256), 422, "L1.30", "validation_failed")
    check(book(w.ada, d, "21:00", "t_1", 2, key="x" * 1000), 422, "L1.30", "validation_failed")
    check(w.ada.post("/reservation-moves", json={"moves": [{"reference": "AAAAAA"}]}, key="y" * 256), 422, "L1.30",
          "validation_failed")
    assert len(w.ada.get("/reservations").json["reservations"]) == 2, "[L1.30] rejected key created nothing"


def test_L1_44_first_use_replay_and_reuse(w):
    d, key = w.date, new_key()
    first = w.ada.post("/reservations", json=body(d), key=key)
    j = check(first, 201, "L1.44")
    replay = w.ada.post("/reservations", json=body(d), key=key)
    assert check(replay, 200, "L1.44") == j, "[L1.44] replay body identical to the original response"
    for _ in range(3):
        assert check(w.ada.post("/reservations", json=body(d), key=key), 200, "L1.44") == j
    assert len(w.ada.get("/reservations").json["reservations"]) == 1, "[L1.44] replays create no duplicate"
    for change in ({"party_size": 3}, {"table_id": "t_3"}, {"starts_at_local": f"{d}T19:30"}, {"restaurant_id": "r_two"}):
        check(w.ada.post("/reservations", json={**body(d), **change}, key=key), 409, "L1.25", "idempotency_key_reuse")
    assert len(w.ada.get("/reservations").json["reservations"]) == 1, "[L1.25] reuse created nothing"


def test_L1_45_same_body_means_same_json_value(w):
    d, key = w.date, new_key()
    j = check(w.ada.post("/reservations", json=body(d), key=key), 201, "L1.45")
    reordered = ('{ "party_size" : 4 ,\n "starts_at_local":"%sT19:00",  "table_id":"t_2",\t"restaurant_id":"r_anker" }' % d)
    assert check(w.ada.post("/reservations", raw=reordered, key=key), 200, "L1.45") == j, "[L1.45] key order/whitespace irrelevant"
    check(w.ada.post("/reservations", json={**body(d), "extra": 1}, key=key), 409, "L1.45", "idempotency_key_reuse")


def test_L1_43_reuse_with_invalid_new_body_is_409(w):
    d, key = w.date, new_key()
    check(w.ada.post("/reservations", json=body(d), key=key), 201, "L1.43")
    check(w.ada.post("/reservations", json=body(d, party="four"), key=key), 409, "L1.43", "idempotency_key_reuse")
    check(w.ada.post("/reservations", json={"nonsense": True}, key=key), 409, "L1.43", "idempotency_key_reuse")
    check(w.ada.post("/reservations", json=body(d, table="t_nope"), key=key), 409, "L1.43", "idempotency_key_reuse")
    check(w.ada.post("/reservations", json=body(d, at="19:15"), key=key), 409, "L1.43", "idempotency_key_reuse")


def test_L1_44_failed_request_key_is_reusable(w):
    d = w.date
    key = new_key()
    check(w.ada.post("/reservations", json=body(d, party=9), key=key), 422, "L1.44", "party_exceeds_capacity")
    check(w.ada.post("/reservations", json=body(d, party=9), key=key), 422, "L1.44", "party_exceeds_capacity")  # still first use
    j = check(w.ada.post("/reservations", json=body(d, party=4), key=key), 201, "L1.44")  # different body, same key
    assert check(w.ada.post("/reservations", json=body(d, party=4), key=key), 200, "L1.44") == j
    k2 = new_key()
    check(w.ada.post("/reservations", json=body(d, table="t_nope"), key=k2), 404, "L1.44", "not_found")
    check(w.ada.post("/reservations", json=body(d, at="19:15"), key=k2), 422, "L1.44", "not_on_slot_grid")
    check(w.ada.post("/reservations", json=body(d, at="20:00", table="t_3", party=6), key=k2), 201, "L1.44")
    k3 = new_key()
    check(w.bob.post("/reservations", json=body(d, at="19:30"), key=k3), 409, "L1.44", "table_unavailable")
    w.ada.post(f"/reservations/{j['reference']}/cancel")
    check(w.bob.post("/reservations", json=body(d, at="19:30"), key=k3), 201, "L1.44")  # 409 earlier => first use now


def test_L1_41_key_is_scoped_per_user(w):
    d, key = w.date, "shared-key"
    ja = check(w.ada.post("/reservations", json=body(d, table="t_2"), key=key), 201, "L1.41")
    jb = check(w.bob.post("/reservations", json=body(d, table="t_3", party=5), key=key), 201, "L1.41")
    assert ja["reference"] != jb["reference"]
    # same key AND same body from another user is not a replay of the first user's request
    r = w.cy.post("/reservations", json=body(d, table="t_2"), key=key)
    check(r, 409, "L1.41", "table_unavailable")
    # each user's own replay returns their own original
    assert check(w.bob.post("/reservations", json=body(d, table="t_3", party=5), key=key), 200, "L1.41") == jb
    assert check(w.ada.post("/reservations", json=body(d, table="t_2"), key=key), 200, "L1.41") == ja
    check(w.bob.post("/reservations", json=body(d, table="t_2"), key=key), 409, "L1.41", "idempotency_key_reuse")


def test_L1_41_keys_are_case_sensitive_exact_strings(w):
    d = w.date
    check(w.ada.post("/reservations", json=body(d, at="18:00", table="t_2"), key="Abc"), 201, "L1.41")
    check(w.ada.post("/reservations", json=body(d, at="20:00", table="t_2"), key="abc"), 201, "L1.41")


def test_L1_42_same_key_other_path_is_not_a_replay(w):
    d, key = w.date, new_key()
    j = check(w.ada.post("/reservations", json=body(d), key=key), 201, "L1.42")
    r = w.ada.post("/reservation-moves", json={"moves": [{"reference": j["reference"], "table_id": "t_3"}]}, key=key)
    moved = check(r, 201, "L1.42")        # fresh first use on a different path: 201, not 200/409
    assert moved["reservations"][0]["table_id"] == "t_3"
    # and in the other direction
    key2 = new_key()
    m = check(w.ada.post("/reservation-moves", json={"moves": [{"reference": j["reference"], "party_size": 2}]}, key=key2),
              201, "L1.42")
    k = check(w.ada.post("/reservations", json=body(d, at="21:00", table="t_2"), key=key2), 201, "L1.42")
    assert k["reference"] != j["reference"]


def test_L1_47_replay_returns_original_after_changes(w):
    d, key = w.date, new_key()
    j = check(w.ada.post("/reservations", json=body(d), key=key), 201, "L1.47")
    w.ada.patch(f"/reservations/{j['reference']}", json={"party_size": 2, "starts_at_local": f"{d}T21:00"})
    r = w.ada.post("/reservations", json=body(d), key=key)
    assert check(r, 200, "L1.47") == j, "[L1.47] replay returns the *original* response after an amendment"
    w.ada.post(f"/reservations/{j['reference']}/cancel")
    assert check(w.ada.post("/reservations", json=body(d), key=key), 200, "L1.47") == j, "[L1.47] ...and after cancellation"
    assert avail_ids(d, "19:00", 4) == ["t_2", "t_3"], "[L1.47] replay makes no further state change (does not re-book)"
    assert [x["status"] for x in w.ada.get("/reservations").json["reservations"]] == ["cancelled"]
    # replay is still a replay if someone else has since taken the slot
    check(book(w.bob, d, "19:00", "t_2"), 201, "L1.47")
    assert check(w.ada.post("/reservations", json=body(d), key=key), 200, "L1.47") == j


def test_L1_46_concurrent_identical_requests_exactly_one_201(w):
    d, key = w.date, new_key()
    out = burst(50, lambda i: w.ada.post("/reservations", json=body(d), key=key))
    codes = sorted(r.status for r in out)
    assert codes == [200] * 49 + [201], f"[L1.46] exactly one 201, the rest 200: {sorted(set(codes))} {codes.count(201)}x201"
    created = [r.json for r in out if r.status == 201][0]
    assert all(r.json == created for r in out), "[L1.46] all responses carry the same body"
    lst = w.ada.get("/reservations").json["reservations"]
    assert len(lst) == 1 and lst[0]["reference"] == created["reference"], "[L1.46] the operation takes effect only once"
    assert avail_ids(d, "19:00", 4) == ["t_3"]


def test_L1_46_concurrent_same_key_different_bodies(w):
    d, key = w.date, new_key()
    bodies = [body(d, at="19:00", table="t_2"), body(d, at="19:00", table="t_3", party=5)]
    out = burst(50, lambda i: w.ada.post("/reservations", json=bodies[i % 2], key=key))
    c = [r.status for r in out]
    assert c.count(201) == 1, f"[L1.46] a key can be first-used once: {sorted(c)}"
    assert set(c) <= {200, 201, 409}, f"[L1.46] {sorted(set(c))}"
    winner = [r.json for r in out if r.status == 201][0]
    for r in out:
        if r.status == 409:
            check(r, 409, "L1.25", "idempotency_key_reuse")
        elif r.status == 200:
            assert r.json == winner
    assert len(w.ada.get("/reservations").json["reservations"]) == 1
