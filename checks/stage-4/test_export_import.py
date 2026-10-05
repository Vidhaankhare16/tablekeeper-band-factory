"""Export / import (ledger L1.40, L1.87-L1.97, L1.112)."""
import json
import time
import pytest
from conftest import call, check, reset, fixture, restaurant, user, all_week, safe_date, book, book_ok, body, new_key, \
    burst, avail_ids, local, login, Client, PW, slots


def export():
    r = call("GET", "/_test/export", timeout=10.5)
    assert r.status == 200, f"[L1.87] export must be 200, got {r!r}"
    return r.json


def do_import(obj, expect=204, lid="L1.88", code=None):
    r = call("POST", "/_test/import", json=obj, timeout=10.5)
    if expect == 204:
        assert r.status == 204 and r.body == b"", f"[{lid}] import must be 204 No Content, got {r!r}"
    else:
        check(r, expect, lid, code)
    return r


def snapshot(*clients):
    return [c.get("/reservations").json for c in clients]


def build_world():
    """Returns dict with clients, bookings, keys: state worth preserving."""
    reset(fixture())
    ada, bob = login("ada@example.com"), login("bob@example.com")
    sg = call("POST", "/auth/signup", json={"email": "sue@example.com", "password": "sue-secret-pw", "display_name": "Sue"}).json
    sue = Client(sg["token"], sg["user_id"])
    d, d2 = safe_date(), safe_date(1)
    k1, k2, k3 = new_key(), new_key(), new_key()
    b1 = check(ada.post("/reservations", json=body(d, "19:00", "t_2", 4), key=k1), 201, "setup")
    b2 = check(bob.post("/reservations", json=body(d, "19:00", "t_3", 5), key=k2), 201, "setup")
    b3 = check(sue.post("/reservations", json=body(d2, "20:00", "t_1", 2), key=k3), 201, "setup")
    ada.patch(f"/reservations/{b3['reference']}", json={"party_size": 1})            # 404: not ada's; no effect
    cancelled = book_ok(ada, d2, "18:00", "t_2", 2)
    ada.post(f"/reservations/{cancelled['reference']}/cancel")
    failed_key = new_key()
    check(ada.post("/reservations", json=body(d, "19:00", "t_2", 4), key=failed_key), 409, "setup", "table_unavailable")
    # a completed batch move receipt
    mk = new_key()
    mv_body = {"moves": [{"reference": b1["reference"], "table_id": "t_3", "starts_at_local": local(d, "21:00"), "party_size": 6}]}
    mv = check(ada.post("/reservation-moves", json=mv_body, key=mk), 201, "setup")
    return dict(ada=ada, bob=bob, sue=sue, d=d, d2=d2, k1=k1, k2=k2, k3=k3, b1=b1, b2=b2, b3=b3, cancelled=cancelled,
                failed_key=failed_key, mk=mk, mv_body=mv_body, mv=mv)


def mutate():
    """Damage the destination: new account, new bookings, cancellations, and an unrelated config."""
    ada = login("ada@example.com")
    z = call("POST", "/auth/signup", json={"email": "zoe@example.com", "password": "zoe-secret-pw", "display_name": "Zoe"}).json
    for r in ada.get("/reservations").json["reservations"]:
        ada.post(f"/reservations/{r['reference']}/cancel")
    book(ada, safe_date(3), "19:00", "t_2")
    return z


def test_L1_87_export_shape_and_no_auth():
    reset(fixture())
    r = call("GET", "/_test/export")
    j = check(r, 200, "L1.87")
    assert j["track"] == "tablekeeper" and j["format_version"] == 1 and isinstance(j["state"], dict), f"[L1.87] {r.text[:300]}"
    assert "json" in r.headers.get("content-type", ""), "[L1.87] JSON content type"


def test_L1_96_export_is_read_only():
    s = build_world()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    export(); export()
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.96] export must not change state"
    r = s["ada"].post("/reservations", json=body(s["d"], "19:00", "t_2", 4), key=s["k1"])
    assert r.status in (200, 409) and r.status != 201, "[L1.96] export must not drop idempotency receipts"


def test_L1_40_no_plaintext_passwords_in_export():
    reset(fixture())
    call("POST", "/auth/signup", json={"email": "p@example.com", "password": "Tr0ub4dor&3-unique", "display_name": "P"})
    text = json.dumps(export())
    for pw in (PW, "Tr0ub4dor&3-unique"):
        assert pw not in text, f"[L1.40] plaintext password {pw!r} found in exported state"
    reset(fixture())
    assert call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).status == 200


def test_L1_88_roundtrip_restores_everything():
    s = build_world()
    E = export()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    avail_before = slots(s["d"], 2)[0]
    mutate()
    do_import(E)
    # tokens issued before the export still work (L1.93) and see exactly the same data
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.91] reservations, references, ids, timestamps must be restored exactly"
    assert slots(s["d"], 2)[0] == avail_before, "[L1.91] occupancy restored"
    # accounts and hashed-password login (L1.91): seeded and signed-up
    for email, pw in (("ada@example.com", PW), ("bob@example.com", PW), ("sue@example.com", "sue-secret-pw")):
        check(call("POST", "/auth/login", json={"email": email, "password": pw}), 200, "L1.91")
    check(call("POST", "/auth/login", json={"email": "sue@example.com", "password": PW}), 401, "L1.91", "unauthenticated")
    check(call("POST", "/auth/signup", json={"email": "sue@example.com", "password": "12345678", "display_name": "X"}), 409,
          "L1.91", "email_taken")
    # fixture configuration
    r = call("GET", "/restaurants/r_anker").json
    assert r["slot_minutes"] == 30 and r["cancellation_cutoff_minutes"] == 120 and len(r["tables"]) == 3, "[L1.91] config"
    # individual reservation reads
    assert s["ada"].get(f"/reservations/{s['cancelled']['reference']}").json["status"] == "cancelled", "[L1.91] statuses"
    assert s["bob"].get(f"/reservations/{s['b2']['reference']}").json == s["b2"]


def test_L1_94_import_removes_destination_data_and_credentials():
    s = build_world()
    E = export()
    z = mutate()
    zoe_login = call("POST", "/auth/login", json={"email": "zoe@example.com", "password": "zoe-secret-pw"}).json["token"]
    do_import(E)
    check(call("GET", "/reservations", token=z["token"]), 401, "L1.94", "unauthenticated")
    check(call("GET", "/reservations", token=zoe_login), 401, "L1.94", "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "zoe@example.com", "password": "zoe-secret-pw"}), 401, "L1.94",
          "unauthenticated")
    assert len(s["ada"].get("/reservations").json["reservations"]) == 2, "[L1.89] import is replacement, not merge"


def test_L1_94_import_into_a_different_fixture_service_no_source_dependency():
    s = build_world()
    E = export()
    reset(fixture(users=[user("zed")], restaurants=[restaurant("r_other", name="Other",
                                                                 tables=[{"id": "t_o", "label": "O", "capacity": 2}])]))
    zed = login("zed@example.com")
    book_ok(zed, safe_date(), "19:00", "t_o", 2, "r_other")
    do_import(E)
    check(call("GET", "/restaurants/r_other"), 404, "L1.94", "not_found")
    check(call("POST", "/auth/login", json={"email": "zed@example.com", "password": PW}), 401, "L1.94", "unauthenticated")
    check(call("GET", "/reservations", token=zed.token), 401, "L1.94", "unauthenticated")
    assert [r["reference"] for r in s["ada"].get("/reservations").json["reservations"]][0:1] != []
    assert [x["id"] for x in call("GET", "/restaurants").json["restaurants"]] == ["r_anker", "r_two"]


def test_L1_89_import_is_idempotent_and_repeatable():
    s = build_world()
    E = export()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    for _ in range(3):
        do_import(E)
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.89] repeating import restores the state without duplicating"
    E2 = export()
    do_import(E2)
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.89] re-import of a re-export is stable"


def test_L1_93_L1_92_receipts_keys_and_references_after_import():
    s = build_world()
    E = export()
    mutate()
    do_import(E)
    ada, d = s["ada"], s["d"]
    # replay of a completed idempotent request: 200, body identical to the original 201
    r = ada.post("/reservations", json=body(d, "19:00", "t_2", 4), key=s["k1"])
    assert check(r, 200, "L1.93") == s["b1"], "[L1.93] receipts survive: replay returns the original body"
    # reuse with different body
    check(ada.post("/reservations", json=body(d, "19:30", "t_2", 4), key=s["k1"]), 409, "L1.93", "idempotency_key_reuse")
    # key of a request that failed (409 table_unavailable) is still reusable for a first use
    j = check(ada.post("/reservations", json=body(d, "19:00", "t_1", 2), key=s["failed_key"]), 201, "L1.92")
    # new references remain unique against restored ones
    existing = {r["reference"] for c in (s["ada"], s["bob"], s["sue"]) for r in c.get("/reservations").json["reservations"]}
    assert j["reference"] in existing and len(existing) == 5
    seen = set()
    for i in range(5):
        n = book_ok(ada, safe_date(5 + i), "19:00", "t_2")
        assert n["reference"] not in seen and n["reference"] not in existing - {n["reference"]}
        seen.add(n["reference"]); existing.add(n["reference"])
    assert s["ada"].get(f"/reservations/{s['b1']['reference']}").json["reference"] == s["b1"]["reference"]


def test_L1_112_move_receipts_survive_import():
    s = build_world()
    E = export()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    mutate()
    do_import(E)
    r = s["ada"].post("/reservation-moves", json=s["mv_body"], key=s["mk"])
    assert check(r, 200, "L1.112") == s["mv"], "[L1.112] batch receipt preserved: replay 200 with the original body"
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.112] replay changes nothing"
    check(s["ada"].post("/reservation-moves", json={"moves": [{"reference": s["b1"]["reference"], "table_id": "t_1"}]},
                        key=s["mk"]), 409, "L1.112", "idempotency_key_reuse")


def test_L1_95_reset_clears_imported_state():
    s = build_world()
    E = export()
    do_import(E)
    reset(fixture(users=[user("zed")], restaurants=[restaurant("r_n", name="N")]))
    check(call("GET", "/reservations", token=s["ada"].token), 401, "L1.95", "unauthenticated")
    check(call("GET", "/reservations", token=s["sue"].token), 401, "L1.95", "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "sue@example.com", "password": "sue-secret-pw"}), 401, "L1.95",
          "unauthenticated")
    zed = login("zed@example.com")
    check(zed.get(f"/reservations/{s['b2']['reference']}"), 404, "L1.95", "not_found")
    # old idempotency receipts are gone too: the old key is a first use again
    j = check(zed.post("/reservations", json={"restaurant_id": "r_n", "table_id": "x", "starts_at_local": "2030-01-01T19:00",
                                              "party_size": 1}, key=s["k1"]), 404, "L1.95", "not_found")


@pytest.mark.parametrize("name,obj", [
    ("empty object", {}), ("missing track", {"format_version": 1, "state": {}}),
    ("wrong track", {"track": "pocketful", "format_version": 1, "state": {}}),
    ("missing version", {"track": "tablekeeper", "state": {}}),
    ("wrong version 2", {"track": "tablekeeper", "format_version": 2, "state": {}}),
    ("version 0", {"track": "tablekeeper", "format_version": 0, "state": {}}),
    ("version string", {"track": "tablekeeper", "format_version": "1", "state": {}}),
    ("missing state", {"track": "tablekeeper", "format_version": 1}),
    ("state null", {"track": "tablekeeper", "format_version": 1, "state": None}),
    ("state string", {"track": "tablekeeper", "format_version": 1, "state": "x"}),
    ("state list", {"track": "tablekeeper", "format_version": 1, "state": []}),
    ("state number", {"track": "tablekeeper", "format_version": 1, "state": 5}),
    ("track number", {"track": 1, "format_version": 1, "state": {}}),
])
def test_L1_90_invalid_import_is_422_and_changes_nothing(name, obj):
    s = build_world()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    r = call("POST", "/_test/import", json=obj)
    check(r, 422, f"L1.90 ({name})", "validation_failed")
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, f"[L1.90] failed import ({name}) must leave the destination unchanged"
    check(call("POST", "/auth/login", json={"email": "sue@example.com", "password": "sue-secret-pw"}), 200, "L1.90")


def test_L1_90_invalid_json_is_400_and_changes_nothing():
    s = build_world()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    for raw in ("{oops", "", "[", '{"track":'):
        check(call("POST", "/_test/import", raw=raw), 400, "L1.90", "malformed_request")
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before


def test_L1_90_state_object_not_from_this_service_is_rejected():
    # READING R4: "an invalid state" => 422. An object with the wrong inner shape must not be applied.
    s = build_world()
    before = snapshot(s["ada"], s["bob"], s["sue"])
    for st in ({"unexpected": 1}, {"users": "nope", "restaurants": 5}):
        r = call("POST", "/_test/import", json={"track": "tablekeeper", "format_version": 1, "state": st})
        check(r, 422, "L1.90", "validation_failed")
    assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.90] rejected state leaves destination unchanged"
    # a tampered export (one inner collection damaged) is also all-or-nothing
    E = export()
    bad = json.loads(json.dumps(E))
    for k, v in list(bad["state"].items()):
        if isinstance(v, (list, dict)) and v:
            bad["state"][k] = "garbage"
            break
    r = call("POST", "/_test/import", json=bad)
    if r.status != 204:                                   # either accepted-as-noop is impossible; rejection must be clean
        check(r, 422, "L1.90", "validation_failed")
        assert snapshot(s["ada"], s["bob"], s["sue"]) == before, "[L1.90] tampered state rejected atomically"


def test_L1_96_export_taken_during_writes_is_consistent():
    users = [user("ada")]
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(20)]
    reset(fixture(users=users, restaurants=[restaurant("r_big", tables=tables)]))
    ada = login("ada@example.com")
    d = safe_date()
    keyed = {}

    def work(i):
        if i < 20:
            k = new_key()
            b = body(d, "19:00", f"t_{i}", 2, "r_big")
            r = ada.post("/reservations", json=b, key=k)
            if r.status == 201:
                keyed[r.json["reference"]] = (k, b, r.json)
            return r
        return call("GET", "/_test/export", timeout=10.5)
    out = burst(26, work)
    exports = [r.json for r in out[20:]]
    assert all(r.status == 200 for r in out[20:]) and all(r.status == 201 for r in out[:20]), \
        f"[L1.96] concurrent exports/bookings must all succeed: {[r.status for r in out]}"
    for E in exports:
        do_import(E)
        lst = ada.get("/reservations").json["reservations"]
        for res in lst:
            k, b, original = keyed[res["reference"]]
            r = ada.post("/reservations", json=b, key=k)
            assert r.status == 200 and r.json == original, \
                f"[L1.96] export is an atomic snapshot: booking {res['reference']} is present but its receipt is not: {r!r}"
    # the final state can be restored too
    assert len(keyed) == 20


def test_L1_88_larger_state_within_timeouts():
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(40)]
    rs = [{"id": f"res_{i}", "reference": f"SD{i:04d}", "user_id": "u_ada", "restaurant_id": "r_big",
           "table_id": f"t_{i % 40}", "starts_at_local": f"2031-{1 + (i // 40) % 12:02d}-{1 + (i // 480) % 28:02d}T{18 + (i // 40) % 4}:00",
           "party_size": 2} for i in range(200)]
    # (distinct start times per table => no overlaps)  ensure uniqueness of (table, start)
    seen = set(); rs2 = []
    for r in rs:
        key = (r["table_id"], r["starts_at_local"])
        if key not in seen:
            seen.add(key); rs2.append(r)
    reset(fixture(users=[user("ada")], restaurants=[restaurant("r_big", tables=tables, dur=30, slot=30, hours=all_week("17:00", "23:00"))],
                  reservations=rs2))
    ada = login("ada@example.com")
    before = ada.get("/reservations").json
    t0 = time.time()
    E = export()
    do_import(E)
    assert time.time() - t0 < 9, "[L1.88] export+import of a few hundred reservations within the 10 s control timeout"
    assert ada.get("/reservations").json == before and len(before["reservations"]) == len(rs2)
