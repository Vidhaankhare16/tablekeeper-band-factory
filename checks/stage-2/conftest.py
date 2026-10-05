"""Black-box helpers for the Tablekeeper stage-1 acceptance checks.

Only the public HTTP interface of the running service is used. The base address comes from
the environment variable TK_BASE_URL (default http://127.0.0.1:8080).
"""
from __future__ import annotations

import datetime as dt
import http.client
import json as _json
import os
import threading
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import pytest

BASE = os.environ.get("TK_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
_u = urllib.parse.urlparse(BASE)
HOST, PORT = _u.hostname, _u.port or 80
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PW = "correct horse"


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body
        self.text = body.decode("utf-8", "replace")
        try:
            self.json = _json.loads(self.text) if self.text.strip() else None
        except ValueError:
            self.json = None

    def __repr__(self):
        return f"<{self.status} {self.text[:300]}>"


def call(method, path, *, json=None, raw=None, token=None, key=None, headers=None, timeout=9.0):
    h = {"Accept": "application/json"}
    body = None
    if raw is not None:
        body = raw if isinstance(raw, bytes) else raw.encode()
        h["Content-Type"] = "application/json"
    elif json is not None:
        body = _json.dumps(json).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
    finally:
        c.close()


class Client:
    def __init__(self, token=None, user_id=None):
        self.token, self.user_id = token, user_id

    def req(self, method, path, **kw):
        kw.setdefault("token", self.token)
        return call(method, path, **kw)

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, **kw): return self.req("POST", path, **kw)
    def patch(self, path, **kw): return self.req("PATCH", path, **kw)


def new_key():
    return "k-" + uuid.uuid4().hex


def check(resp, status, lid, code=None):
    """Assert status (and error code); the message quotes the ledger id."""
    assert resp.status == status, f"[{lid}] expected HTTP {status}{' '+code if code else ''}, got {resp!r}"
    if code is not None:
        e = resp.json.get("error") if isinstance(resp.json, dict) else None
        assert isinstance(e, dict) and e.get("code") == code, f"[{lid}] expected error code {code}, got {resp!r}"
    return resp.json


def assert_error_shape(resp, lid="L1.19"):
    e = resp.json.get("error") if isinstance(resp.json, dict) else None
    assert isinstance(e, dict) and isinstance(e.get("code"), str) and e["code"] and isinstance(e.get("message"), str), \
        f"[{lid}] 4xx/5xx body must be {{error:{{code,message}}}}, got {resp!r}"


def reset(fixture):
    r = call("POST", "/_test/reset", json=fixture, timeout=10.5)
    assert r.status == 204, f"[L1.7] reset must be 204, got {r!r}"
    return r


def login(email, password=PW):
    r = call("POST", "/auth/login", json={"email": email, "password": password})
    assert r.status == 200, f"[L1.33] login of {email} failed: {r!r}"
    return Client(r.json["token"], r.json["user_id"])


def burst(n, fn):
    """Run fn(i) for i in range(n) with all n requests released together (n in flight)."""
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait(timeout=20)
        try:
            return fn(i)
        except Exception as e:  # noqa: BLE001
            return e
    with ThreadPoolExecutor(max_workers=n) as ex:
        out = list(ex.map(run, range(n)))
    errs = [o for o in out if isinstance(o, Exception)]
    assert not errs, f"[L1.14] requests failed/timed out under concurrency: {errs[:3]!r}"
    return out


# ---- fixtures / dates --------------------------------------------------------------------

def all_week(opens="18:00", closes="23:00"):
    return [{"weekday": d, "opens": opens, "closes": closes} for d in WEEKDAYS]


def restaurant(rid="r_anker", *, name="Zum Anker", timezone="Europe/Berlin", slot=30, dur=90, cutoff=120,
               hours=None, tables=None, combinable=None):
    r = _restaurant(rid, name, timezone, slot, dur, cutoff, hours, tables)
    if combinable is not None:
        r["combinable"] = combinable
    return r


def _restaurant(rid, name, timezone, slot, dur, cutoff, hours, tables):
    return {"id": rid, "name": name, "timezone": timezone, "slot_minutes": slot,
            "reservation_duration_minutes": dur, "cancellation_cutoff_minutes": cutoff,
            "opening_hours": all_week() if hours is None else hours,
            "tables": tables if tables is not None else [
                {"id": "t_1", "label": "1", "capacity": 2},
                {"id": "t_2", "label": "2", "capacity": 4},
                {"id": "t_3", "label": "3", "capacity": 6}]}


def user(n, name=None):
    return {"id": f"u_{n}", "email": f"{n}@example.com", "password": PW, "display_name": name or n.title()}


def fixture(users=None, restaurants=None, reservations=None):
    return {"users": [user("ada"), user("bob"), user("cy")] if users is None else users,
            "restaurants": [restaurant(), restaurant("r_two", name="Zwei", tables=[
                {"id": "t_x1", "label": "X1", "capacity": 4}])] if restaurants is None else restaurants,
            "reservations": reservations or []}


_TRANSITIONS = {dt.date(2026, 3, 29), dt.date(2026, 10, 25), dt.date(2026, 3, 8), dt.date(2026, 11, 1)}


def safe_date(offset=0):
    """The (offset+1)-th calendar date, counting from >=20 days ahead, that is not in Mar/Apr/Oct/Nov (no DST day)."""
    d = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=20)
    n = 0
    while True:
        if d.month not in (3, 4, 10, 11):
            if n == offset:
                return d.isoformat()
            n += 1
        d += dt.timedelta(days=1)


def local(date, hhmm):
    return f"{date}T{hhmm}"


def body(date, at="19:00", table="t_2", party=4, rid="r_anker"):
    return {"restaurant_id": rid, "table_id": table, "starts_at_local": local(date, at), "party_size": party}


def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def instant(s):
    return iso(s).astimezone(dt.timezone.utc)


def book(c, date=None, at="19:00", table="t_2", party=4, rid="r_anker", key=None, **extra):
    b = body(date or safe_date(), at, table, party, rid)
    b.update(extra)
    return c.post("/reservations", json=b, key=new_key() if key is None else key)


def book_ok(c, *a, **kw):
    r = book(c, *a, **kw)
    assert r.status == 201, f"[L1.58] booking should succeed: {r!r}"
    return r.json


def slots(date, party=2, rid="r_anker"):
    r = call("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}")
    assert r.status == 200, f"[L1.52] availability failed: {r!r}"
    return {s["starts_at_local"]: s for s in r.json["slots"]}, r.json


def avail_ids(date, at, party=2, rid="r_anker"):
    s, _ = slots(date, party, rid)
    return s[local(date, at)]["available_table_ids"] if local(date, at) in s else None


class World:
    pass


@pytest.fixture
def w():
    fx = fixture()
    reset(fx)
    o = World()
    o.fx, o.date = fx, safe_date()
    o.ada, o.bob, o.cy = login("ada@example.com"), login("bob@example.com"), login("cy@example.com")
    return o


@pytest.fixture
def reset_fx():
    return reset
