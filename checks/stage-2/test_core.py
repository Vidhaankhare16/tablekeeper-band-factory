"""Runtime contract, conventions, errors, auth (ledger L1.4-L1.40)."""
import json
import re
import pytest
from conftest import *  # noqa: F401,F403
from conftest import call, check, reset, fixture, restaurant, user, login, Client, new_key, burst, \
    assert_error_shape, safe_date, book, book_ok, body, local, instant, iso, PW


def test_L1_6_health():
    r = call("GET", "/health")
    assert r.status == 200 and r.json == {"status": "ok"}, f"[L1.6] GET /health must be 200 {{status:ok}}, got {r!r}"


def test_L1_7_reset_204_empty_and_repeatable():
    for _ in range(3):
        r = call("POST", "/_test/reset", json=fixture())
        assert r.status == 204 and r.body == b"", f"[L1.7] reset must be 204 No Content, got {r!r}"


def test_L1_7_reset_replaces_all_state(w):
    d = w.date
    ref = book_ok(w.ada, d)["reference"]
    old_token = w.ada.token
    reset(fixture(users=[user("zed")], restaurants=[restaurant("r_new", name="Neu")]))
    assert call("GET", "/restaurants/r_anker").status == 404, "[L1.7] old restaurant must be gone after reset"
    r = call("GET", "/restaurants")
    assert [x["id"] for x in r.json["restaurants"]] == ["r_new"], f"[L1.7] only the new fixture may be visible: {r!r}"
    check(call("GET", "/reservations", token=old_token), 401, "L1.7", "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW}), 401, "L1.7", "unauthenticated")
    z = login("zed@example.com")
    assert z.get("/reservations").json == {"reservations": []}, "[L1.7] reservations must be cleared"
    check(z.get(f"/reservations/{ref}"), 404, "L1.7", "not_found")


def test_L1_8_reset_needs_no_auth():
    assert call("POST", "/_test/reset", json=fixture()).status == 204, "[L1.8] reset needs no authentication"


def test_L1_9_json_content_type(w):
    for r in (call("GET", "/health"), call("GET", "/restaurants"), w.ada.get("/reservations"),
              call("GET", "/restaurants/nope")):
        ct = r.headers.get("content-type", "").lower().replace(" ", "")
        assert ct.startswith("application/json") and "charset=utf-8" in ct, \
            f"[L1.9] responses are application/json; charset=utf-8, got {ct!r}"


def test_L1_10_timestamps_have_explicit_offset(w):
    j = book_ok(w.ada, w.date)
    for f in ("starts_at", "ends_at", "created_at"):
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)", j[f]), \
            f"[L1.10] {f} must be RFC 3339 with explicit offset, got {j[f]!r}"
    assert j["starts_at"].endswith(("+01:00", "+02:00")), f"[L1.10] Berlin offset expected, got {j['starts_at']}"
    s, _ = __import__("conftest").slots(w.date)
    assert re.search(r"[+-]\d\d:\d\d$", s[local(w.date, "19:00")]["starts_at"]), "[L1.10] slot starts_at needs offset"


def test_L1_11_unknown_body_fields_ignored(w):
    r = book(w.ada, w.date, junk={"a": [1]}, other=None)
    check(r, 201, "L1.11")
    check(call("POST", "/auth/signup", json={"email": "n@x.io", "password": "longenough", "display_name": "N", "zzz": 1}),
          201, "L1.11")
    check(call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW, "zzz": 1}), 200, "L1.11")
    ref = r.json["reference"]
    check(w.ada.patch(f"/reservations/{ref}", json={"party_size": 3, "junk": 1}), 200, "L1.11")


def test_L1_12_unknown_query_params_ignored(w):
    check(call("GET", "/restaurants?foo=bar&x=1"), 200, "L1.12")
    check(call("GET", "/restaurants/r_anker?foo=bar"), 200, "L1.12")
    check(call("GET", f"/availability?restaurant_id=r_anker&date={w.date}&party_size=2&foo=bar"), 200, "L1.12")
    check(w.ada.get("/reservations?foo=bar"), 200, "L1.12")


def test_L1_13_ids_max_64_chars_in_fixture_and_generated(w):
    long_t, long_r, long_u = "t" * 64, "r" * 64, "u" * 64
    reset(fixture(users=[{**user("longid"), "id": long_u}],
                  restaurants=[restaurant(long_r, tables=[{"id": long_t, "label": "L", "capacity": 4}])]))
    c = login("longid@example.com")
    assert c.user_id == long_u, "[L1.13] 64-char ids supplied by fixture must be kept"
    d = safe_date()
    j = book_ok(c, d, table=long_t, rid=long_r)
    assert len(j["reservation_id"]) <= 64 and j["table_id"] == long_t and j["restaurant_id"] == long_r, \
        f"[L1.13] ids ≤64 chars: {j}"
    sg = call("POST", "/auth/signup", json={"email": "gen@x.io", "password": "longenough", "display_name": "G"})
    assert len(sg.json["user_id"]) <= 64, "[L1.13] generated user ids ≤64 chars"
    assert isinstance(j["reservation_id"], str)


def test_L1_15_seeded_user_login_immediately():
    reset(fixture())
    r = call("POST", "/auth/login", json={"email": "bob@example.com", "password": PW})
    j = check(r, 200, "L1.15")
    assert j["user_id"] == "u_bob" and j["display_name"] == "Bob" and j["token"], f"[L1.15] {r!r}"


# ---- errors ---------------------------------------------------------------------------------

def test_L1_19_error_body_shape(w):
    cases = [call("GET", "/restaurants/nope"), call("GET", "/reservations"),
             call("POST", "/auth/login", json={"email": "x@y.zz", "password": "nope"}),
             w.ada.post("/reservations", json=body(w.date)),
             w.ada.post("/reservations", raw="{not json", key=new_key()),
             call("GET", "/availability?restaurant_id=r_anker")]
    for r in cases:
        assert 400 <= r.status < 500, f"[L1.19] expected a 4xx, got {r!r}"
        assert_error_shape(r)


def test_L1_20_malformed_bodies_are_400(w):
    for path, hdr in (("/reservations", new_key()), ("/reservation-moves", new_key())):
        for raw in ("{not json", "", "[1,2]", "42", '"str"', "null"):
            check(w.ada.post(path, raw=raw, key=hdr), 400, "L1.20", "malformed_request")
    check(call("POST", "/auth/signup", raw="{oops"), 400, "L1.20", "malformed_request")
    check(call("POST", "/auth/login", raw="{oops"), 400, "L1.20", "malformed_request")
    ref = book_ok(w.ada, w.date)["reference"]
    check(w.ada.patch(f"/reservations/{ref}", raw="{oops"), 400, "L1.20", "malformed_request")
    check(w.ada.patch(f"/reservations/{ref}", raw="[1]"), 400, "L1.20", "malformed_request")


@pytest.mark.parametrize("field,val", [("restaurant_id", 5), ("table_id", ["t_2"]), ("starts_at_local", 20260924),
                                       ("restaurant_id", True), ("table_id", {"a": 1}), ("starts_at_local", None)])
def test_L1_20_wrong_json_type_is_400(w, field, val):
    b = body(w.date)
    b[field] = val
    check(w.ada.post("/reservations", json=b, key=new_key()), 400, "L1.20/L1.28", "malformed_request")


def test_L1_20_wrong_type_in_auth_fields():
    check(call("POST", "/auth/signup", json={"email": 5, "password": "longenough", "display_name": "x"}),
          400, "L1.20", "malformed_request")
    check(call("POST", "/auth/signup", json={"email": "a@b.cc", "password": 12345678, "display_name": "x"}),
          400, "L1.20", "malformed_request")
    check(call("POST", "/auth/login", json={"email": "a@b.cc", "password": ["x"]}), 400, "L1.20", "malformed_request")


def test_L1_26_missing_required_fields_are_422(w):
    for f in ("restaurant_id", "table_id", "starts_at_local", "party_size"):
        b = body(w.date)
        del b[f]
        check(w.ada.post("/reservations", json=b, key=new_key()), 422, "L1.26", "validation_failed")
    check(w.ada.post("/reservations", json={}, key=new_key()), 422, "L1.26", "validation_failed")
    check(call("POST", "/auth/signup", json={"password": "longenough", "display_name": "x"}), 422, "L1.26",
          "validation_failed")
    check(call("POST", "/auth/login", json={"email": "ada@example.com"}), 422, "L1.26", "validation_failed")


@pytest.mark.parametrize("val", ["4", "four", True, False, 0, -1, 2.5, 1e9 + 0.5])
def test_L1_28_party_size_invalid_values_are_422(w, val):
    check(w.ada.post("/reservations", json=body(w.date, party=val), key=new_key()), 422, "L1.28/L1.65",
          "validation_failed")


@pytest.mark.parametrize("s", ["2026-09-24T19:00:00", "2026-09-24T19:00Z", "2026-09-24T19:00+02:00",
                               "2026-09-24 19:00", "2026-9-24T19:00", "2026-09-24T7:00", "2026-09-24",
                               "19:00", "", "2026-02-30T19:00", "2026-09-24T24:00", "2026-09-24T19:60",
                               "2026-13-01T19:00", "tomorrow", " 2026-09-24T19:00", "2026-09-24T19:00 "])
def test_L1_28_starts_at_local_must_be_bare_local(w, s):
    b = body(w.date)
    b["starts_at_local"] = s
    check(w.ada.post("/reservations", json=b, key=new_key()), 422, "L1.28", "validation_failed")


@pytest.mark.parametrize("q", ["party_size=1e9", "party_size=4.0", "party_size=%2B4", "party_size=+4", "party_size=-1",
                               "party_size=0", "party_size=abc", "party_size=", "party_size=0x4", "party_size=4%20",
                               "party_size=2.5"])
def test_L1_29_integer_query_params_plain_digits(w, q):
    r = call("GET", f"/availability?restaurant_id=r_anker&date={w.date}&{q}")
    check(r, 422, "L1.29", "validation_failed")


def test_L1_31_no_5xx_on_garbage(w):
    junk = ["\x00", "é" * 500, "😀", "a" * 5000, "-1", "../..", "%00"]
    seen = []
    from urllib.parse import quote
    for j in junk:
        q = quote(j)
        seen += [call("GET", f"/restaurants/{q}"), call("GET", f"/availability?restaurant_id={q}&date={q}&party_size={q}"),
                 w.ada.get(f"/reservations/{q}"), w.ada.post(f"/reservations/{q}/cancel"),
                 w.ada.patch(f"/reservations/{q}", json={"party_size": j}),
                 w.ada.post("/reservations", json={"restaurant_id": j, "table_id": j, "starts_at_local": j,
                                                   "party_size": j}, key=new_key()),
                 w.ada.post("/reservation-moves", json={"moves": [{"reference": j, "table_id": j}]}, key=new_key()),
                 call("POST", "/auth/signup", json={"email": j, "password": j, "display_name": j}),
                 call("POST", "/auth/login", json={"email": j, "password": j}),
                 call("POST", "/_test/import", json={"track": j, "format_version": j, "state": j})]
    seen += [call("GET", "/nope"), call("DELETE", "/reservations"), call("PUT", "/health"),
             w.ada.post("/reservations", json=body(w.date), key="k" * 4000)]
    for r in seen:
        assert r.status < 500, f"[L1.31] no request may produce 5xx, got {r!r}"
        if r.status >= 400:
            assert_error_shape(r)


# ---- auth -----------------------------------------------------------------------------------

def test_L1_32_signup_shape_and_usable_token():
    reset(fixture())
    r = call("POST", "/auth/signup", json={"email": "new@example.com", "password": "12345678", "display_name": "Nia"})
    j = check(r, 201, "L1.32")
    assert j["display_name"] == "Nia" and isinstance(j["user_id"], str) and isinstance(j["token"], str) and j["token"], \
        f"[L1.32] {r!r}"
    assert set(j) >= {"user_id", "display_name", "token"}
    check(call("GET", "/reservations", token=j["token"]), 200, "L1.32")
    l = check(call("POST", "/auth/login", json={"email": "new@example.com", "password": "12345678"}), 200, "L1.33")
    assert l["user_id"] == j["user_id"] and l["display_name"] == "Nia", f"[L1.33] login shape {l}"


def test_L1_34_email_taken():
    reset(fixture())
    s = {"email": "dup@example.com", "password": "12345678", "display_name": "D"}
    check(call("POST", "/auth/signup", json=s), 201, "L1.34")
    check(call("POST", "/auth/signup", json=s), 409, "L1.34", "email_taken")
    check(call("POST", "/auth/signup", json={**s, "password": "another-pass"}), 409, "L1.34", "email_taken")
    check(call("POST", "/auth/signup", json={"email": "ada@example.com", "password": "12345678", "display_name": "A2"}),
          409, "L1.34", "email_taken")


def test_L1_35_password_length_boundary():
    reset(fixture())
    check(call("POST", "/auth/signup", json={"email": "p7@x.io", "password": "1234567", "display_name": "x"}), 422,
          "L1.35", "validation_failed")
    check(call("POST", "/auth/signup", json={"email": "p8@x.io", "password": "12345678", "display_name": "x"}), 201,
          "L1.35")
    check(call("POST", "/auth/signup", json={"email": "p0@x.io", "password": "", "display_name": "x"}), 422, "L1.35",
          "validation_failed")
    # a rejected signup must not consume the email
    check(call("POST", "/auth/signup", json={"email": "p7@x.io", "password": "12345678", "display_name": "x"}), 201,
          "L1.35")


def test_L1_35_password_length_counts_characters():
    reset(fixture())
    check(call("POST", "/auth/signup", json={"email": "u8@x.io", "password": "ééééééé", "display_name": "x"}), 422,
          "L1.35", "validation_failed")  # 7 characters (14 bytes)
    check(call("POST", "/auth/signup", json={"email": "u9@x.io", "password": "éééééééé", "display_name": "x"}), 201,
          "L1.35")  # 8 characters


@pytest.mark.parametrize("email", ["plain", "a@", "@b.com", "", "a b@c.com", "a@@b.com"])
def test_L1_36_email_form(email):
    reset(fixture())
    check(call("POST", "/auth/signup", json={"email": email, "password": "12345678", "display_name": "x"}), 422,
          "L1.36", "validation_failed")


def test_L1_37_login_failures_are_401():
    reset(fixture())
    check(call("POST", "/auth/login", json={"email": "ada@example.com", "password": "wrong password"}), 401, "L1.37",
          "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "ghost@example.com", "password": PW}), 401, "L1.37",
          "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW.upper()}), 401, "L1.37",
          "unauthenticated")
    check(call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW + " "}), 401, "L1.37",
          "unauthenticated")


def test_L1_38_protected_endpoints_require_token(w):
    ref = book_ok(w.ada, w.date)["reference"]
    k = new_key()
    for method, path, kw in [("GET", "/reservations", {}), ("GET", f"/reservations/{ref}", {}),
                             ("POST", f"/reservations/{ref}/cancel", {}), ("PATCH", f"/reservations/{ref}", {"json": {}}),
                             ("POST", "/reservations", {"json": body(w.date), "key": k}),
                             ("POST", "/reservation-moves", {"json": {"moves": [{"reference": ref}]}, "key": k})]:
        check(call(method, path, **kw), 401, "L1.38", "unauthenticated")


@pytest.mark.parametrize("hdr", ["Bearer", "Bearer ", "Bearer not-a-real-token", "Basic YWRhOnB3", "token", "bearer",
                                 "Bearer a b"])
def test_L1_22_malformed_or_unknown_token_is_401(w, hdr):
    r = call("GET", "/reservations", headers={"Authorization": hdr})
    check(r, 401, "L1.22", "unauthenticated")


def test_L1_22_401_precedes_missing_key_reading(w):
    # READING R1: authentication is checked before idempotency header handling (§7: "...and the caller authenticated").
    r = call("POST", "/reservations", json=body(w.date))
    check(r, 401, "L1.22", "unauthenticated")


def test_L1_38_public_endpoints_need_no_token(w):
    check(call("GET", "/restaurants"), 200, "L1.38")
    check(call("GET", "/restaurants/r_anker"), 200, "L1.38")
    check(call("GET", f"/availability?restaurant_id=r_anker&date={w.date}&party_size=2"), 200, "L1.38")
    # and a bad token on a public endpoint is not an error
    check(call("GET", "/restaurants", headers={"Authorization": "Bearer junk"}), 200, "L1.38")


def test_L1_39_multiple_tokens_and_sessions(w):
    t = [call("POST", "/auth/login", json={"email": "ada@example.com", "password": PW}).json["token"] for _ in range(3)]
    sg = call("POST", "/auth/signup", json={"email": "m@x.io", "password": "12345678", "display_name": "M"}).json
    t2 = call("POST", "/auth/login", json={"email": "m@x.io", "password": "12345678"}).json["token"]
    assert len({*t, w.ada.token}) == 4, "[L1.39] each login should yield a usable token; tokens must differ"
    for tok in (*t, w.ada.token, sg["token"], t2):
        check(call("GET", "/reservations", token=tok), 200, "L1.39")
    # logging in again must not invalidate earlier tokens
    for tok in t:
        assert call("GET", "/reservations", token=tok).status == 200, "[L1.39] earlier tokens stay valid"


def test_L1_39_concurrent_logins_distinct_valid_tokens(w):
    out = burst(20, lambda i: call("POST", "/auth/login", json={"email": "bob@example.com", "password": PW}))
    toks = []
    for r in out:
        check(r, 200, "L1.39")
        toks.append(r.json["token"])
    assert len(set(toks)) == 20, "[L1.39] concurrent sessions each have a token"
    for t in toks[:5]:
        assert call("GET", "/reservations", token=t).status == 200


def test_L1_39_concurrent_duplicate_signup_exactly_one_201():
    reset(fixture())
    out = burst(20, lambda i: call("POST", "/auth/signup", json={"email": "race@x.io", "password": "12345678",
                                                                  "display_name": "R"}))
    codes = sorted(r.status for r in out)
    assert codes == [201] + [409] * 19, f"[L1.34] exactly one concurrent signup may win: {codes}"
