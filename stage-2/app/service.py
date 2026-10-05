"""Domain rules. Every operation runs inside one lock, so each state change is serialized."""
import json
import re
import secrets
import threading
import time

from . import timeutil
from .errors import (conflict, malformed_request, missing_idempotency_key, not_found,
                     unauthenticated, unprocessable, validation_failed)
from .passwords import hash_password, verify_password
from .state import State, state_from_fixture

TRACK = "tablekeeper"
FORMAT_VERSION = 1
MAX_IDEMPOTENCY_KEY = 255
MAX_MOVES = 8
REFERENCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
REFERENCE_LENGTH = 6
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_DIGITS = re.compile(r"[0-9]{1,18}", re.ASCII)
_BOOKING_STRING_FIELDS = ("restaurant_id", "table_id", "starts_at_local")


def parse_object(raw):
    """A request body as a JSON object (400 when it is not one)."""
    def refuse_constant(name):
        raise ValueError(name)
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant)
    except (ValueError, RecursionError):
        raise malformed_request("body is not valid JSON")
    if not isinstance(value, dict):
        raise malformed_request("body must be a JSON object")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_strings(body, *fields):
    for field in fields:
        if field in body and not isinstance(body[field], str):
            raise malformed_request(f"{field} must be a string")
    for field in fields:
        if field not in body:
            raise validation_failed(f"{field} is required")


def _valid_party_size(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise validation_failed("party_size must be an integer of at least 1")
    return value


def _valid_local_start(value):
    naive = timeutil.parse_local_datetime(value)
    if naive is None:
        raise validation_failed("starts_at_local must be a local YYYY-MM-DDTHH:MM")
    return naive


class Service:
    def __init__(self, clock=time.time):
        self.lock = threading.Lock()
        self.clock = clock
        self.state = State()

    # ---- test control ----

    def reset(self, raw):
        state = state_from_fixture(parse_object(raw))  # hashes passwords outside the lock
        with self.lock:
            self.state = state
        return 204, None

    def export_state(self):
        with self.lock:
            dumped = self.state.dump()
        return 200, {"track": TRACK, "format_version": FORMAT_VERSION, "state": dumped}

    def import_state(self, raw):
        body = parse_object(raw)
        if body.get("track") != TRACK or body.get("format_version") != FORMAT_VERSION \
                or isinstance(body.get("format_version"), bool) or "state" not in body:
            raise validation_failed("export must carry track 'tablekeeper', format_version 1 and state")
        state = State.load(body["state"])
        with self.lock:
            self.state = state
        return 204, None

    # ---- authentication ----

    def signup(self, raw):
        body = parse_object(raw)
        _require_strings(body, "email", "password")
        if "display_name" in body and not isinstance(body["display_name"], str):
            raise malformed_request("display_name must be a string")
        email, password = body["email"], body["password"]
        if not _EMAIL.fullmatch(email):
            raise validation_failed("email must look like local@domain")
        if len(password) < 8:
            raise validation_failed("password must have at least 8 characters")
        display_name = body.get("display_name", email.split("@")[0])
        password_hash = hash_password(password)
        with self.lock:
            state = self.state
            if email.lower() in state.user_by_email:
                raise conflict("email_taken", "email already registered")
            user = {"id": state.allocate_user_id(), "email": email, "display_name": display_name,
                    "password_hash": password_hash}
            state.add_user(user)
            return 201, self._issue_token(user)

    def login(self, raw):
        body = parse_object(raw)
        _require_strings(body, "email", "password")
        with self.lock:
            user_id = self.state.user_by_email.get(body["email"].lower())
            user = self.state.users.get(user_id)
        if user is None or not verify_password(body["password"], user["password_hash"]):
            raise unauthenticated("wrong email or password")
        with self.lock:
            if self.state.users.get(user["id"]) is not user:
                raise unauthenticated("wrong email or password")
            return 200, self._issue_token(user)

    def _issue_token(self, user):
        token = secrets.token_urlsafe(32)
        self.state.tokens[token] = user["id"]
        return {"user_id": user["id"], "display_name": user["display_name"], "token": token}

    def authenticate(self, authorization):
        """The user id behind an `Authorization: Bearer` header. Caller holds the lock."""
        parts = (authorization or "").split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] not in self.state.tokens:
            raise unauthenticated()
        return self.state.tokens[parts[1]]

    # ---- restaurants and availability (public) ----

    def list_restaurants(self):
        with self.lock:
            return 200, {"restaurants": [
                {"id": r["id"], "name": r["name"], "timezone": r["timezone"]}
                for r in self.state.restaurants.values()]}

    def get_restaurant(self, restaurant_id):
        with self.lock:
            restaurant = self.state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            return 200, dict(restaurant)

    def availability(self, query):
        restaurant_id, date_text, party_text = (query.get(k) for k in ("restaurant_id", "date", "party_size"))
        if not restaurant_id or not date_text or not party_text:
            raise validation_failed("restaurant_id, date and party_size are required")
        date = timeutil.parse_date(date_text)
        if date is None:
            raise validation_failed("date must be YYYY-MM-DD")
        if not _DIGITS.fullmatch(party_text) or int(party_text) < 1:
            raise validation_failed("party_size must be a positive integer")
        party_size = int(party_text)
        with self.lock:
            restaurant = self.state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            slots = self._slots(restaurant, date, party_size)
        return 200, {"restaurant_id": restaurant_id, "date": date_text,
                     "timezone": restaurant["timezone"], "slots": slots}

    def _slots(self, restaurant, date, party_size):
        zone = timeutil.load_zone(restaurant["timezone"])
        duration = restaurant["reservation_duration_minutes"] * 60
        weekday = timeutil.WEEKDAYS[date.weekday()]
        taken = {}
        for res in self.state.reservations.values():
            if res["restaurant_id"] == restaurant["id"] and res["status"] == "confirmed":
                taken.setdefault(res["table_id"], []).append((res["start_ts"], res["end_ts"]))
        fitting = [t["id"] for t in restaurant["tables"] if t["capacity"] >= party_size]
        slots, seen = [], set()
        for entry in sorted((h for h in restaurant["opening_hours"] if h["weekday"] == weekday),
                            key=lambda h: timeutil.parse_clock(h["opens"])):
            opens, closes = timeutil.parse_clock(entry["opens"]), timeutil.parse_clock(entry["closes"])
            closes_ts, _ = timeutil.resolve_local(zone, date.replace(hour=closes // 60, minute=closes % 60))
            for minute in range(opens, closes, restaurant["slot_minutes"]):
                naive = date.replace(hour=minute // 60, minute=minute % 60)
                start_ts, exists = timeutil.resolve_local(zone, naive)
                local = timeutil.format_local(naive)
                if not exists or local in seen or start_ts + duration > closes_ts:
                    continue
                seen.add(local)
                free = [t for t in fitting
                        if not any(s < start_ts + duration and start_ts < e for s, e in taken.get(t, ()))]
                slots.append({"starts_at_local": local, "starts_at": timeutil.to_rfc3339(start_ts, zone),
                              "available_table_ids": free})
        return slots

    # ---- reservations ----

    def create_reservation(self, authorization, idempotency_key, raw):
        path = "/reservations"
        with self.lock:
            user_id = self.authenticate(authorization)
            body = parse_object(raw)
            return self._idempotent(user_id, "POST", path, idempotency_key, body,
                                    lambda: self._create(user_id, body))

    def _create(self, user_id, body):
        _require_strings(body, *_BOOKING_STRING_FIELDS)
        if "party_size" not in body:
            raise validation_failed("party_size is required")
        party_size = _valid_party_size(body["party_size"])
        naive = _valid_local_start(body["starts_at_local"])
        restaurant = self.state.restaurants.get(body["restaurant_id"])
        if restaurant is None:
            raise not_found("no such restaurant")
        table_id, _, start_ts, end_ts = self._resolve_booking(
            restaurant, body["table_id"], party_size, naive, None)
        self._require_free(restaurant["id"], table_id, start_ts, end_ts, ignore=())
        record = {"id": self.state.allocate_reservation_id(), "reference": self._new_reference(),
                  "user_id": user_id, "restaurant_id": restaurant["id"], "table_id": table_id,
                  "party_size": party_size, "status": "confirmed",
                  "starts_at_local": timeutil.format_local(naive), "start_ts": start_ts,
                  "end_ts": end_ts, "created_at": timeutil.utc_now_rfc3339(self.clock())}
        self.state.add_reservation(record)
        return self._view(record)

    def _new_reference(self):
        while True:
            reference = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
            if reference not in self.state.by_reference:
                return reference

    def list_reservations(self, authorization):
        with self.lock:
            user_id = self.authenticate(authorization)
            mine = [r for r in self.state.reservations.values() if r["user_id"] == user_id]
            mine.sort(key=lambda r: r["start_ts"], reverse=True)
            return 200, {"reservations": [self._view(r) for r in mine]}

    def get_reservation(self, authorization, reference):
        with self.lock:
            return 200, self._view(self._owned(self.authenticate(authorization), reference))

    def cancel(self, authorization, reference):
        with self.lock:
            record = self._owned(self.authenticate(authorization), reference)
            if record["status"] != "cancelled":
                self._require_before_cutoff(record)
                record["status"] = "cancelled"
            return 200, self._view(record)

    def amend(self, authorization, reference, raw):
        with self.lock:
            user_id = self.authenticate(authorization)
            changes = self._parse_changes(parse_object(raw))
            record = self._owned(user_id, reference)
            plan = self._plan_amendment(record, changes)
            self._require_free(record["restaurant_id"], plan["table_id"], plan["start_ts"], plan["end_ts"],
                               ignore=(record["id"],))
            record.update(plan)
            return 200, self._view(record)

    def moves(self, authorization, idempotency_key, raw):
        path = "/reservation-moves"
        with self.lock:
            user_id = self.authenticate(authorization)
            body = parse_object(raw)
            return self._idempotent(user_id, "POST", path, idempotency_key, body,
                                    lambda: self._move(user_id, body))

    def _move(self, user_id, body):
        moves = body.get("moves")
        if not isinstance(moves, list) or not 1 <= len(moves) <= MAX_MOVES:
            raise validation_failed(f"moves must be a list of 1 to {MAX_MOVES} objects")
        references = []
        for move in moves:
            if not isinstance(move, dict) or not isinstance(move.get("reference"), str):
                raise validation_failed("each move needs a string reference")
            references.append(move["reference"])
        if len(set(references)) != len(references):
            raise validation_failed("references must be distinct")
        changes = [self._parse_changes(move) for move in moves]
        records = [self._owned(user_id, reference) for reference in references]
        if len({r["restaurant_id"] for r in records}) != 1:
            raise validation_failed("all bookings must belong to the same restaurant")
        plans = [self._plan_amendment(record, change) for record, change in zip(records, changes)]
        listed = {r["id"] for r in records}
        for index, plan in enumerate(plans):
            self._require_free(records[0]["restaurant_id"], plan["table_id"], plan["start_ts"], plan["end_ts"],
                               ignore=listed)
            for other in plans[:index]:
                if other["table_id"] == plan["table_id"] and \
                        other["start_ts"] < plan["end_ts"] and plan["start_ts"] < other["end_ts"]:
                    raise conflict("table_unavailable", "moves overlap each other")
        for record, plan in zip(records, plans):
            record.update(plan)
        return {"reservations": [self._view(r) for r in records]}

    # ---- shared helpers ----

    def _idempotent(self, user_id, method, path, key, body, produce):
        """Run `produce` once per (user, method, path, key); a replay returns the first response."""
        if not key:
            raise missing_idempotency_key()
        if len(key) > MAX_IDEMPOTENCY_KEY:
            raise validation_failed("Idempotency-Key must be 1 to 255 characters")
        receipt_id = (user_id, method, path, key)
        canonical = _canonical(body)
        receipt = self.state.receipts.get(receipt_id)
        if receipt is not None:
            if receipt["body"] != canonical:
                raise conflict("idempotency_key_reuse", "key already used with a different body")
            return 200, receipt["response"]
        response = produce()
        self.state.receipts[receipt_id] = {"body": canonical, "response": response}
        return 201, response

    def _owned(self, user_id, reference):
        record = self.state.reservations.get(self.state.by_reference.get(reference))
        if record is None or record["user_id"] != user_id:
            raise not_found("no such reservation")
        return record

    def _require_before_cutoff(self, record):
        restaurant = self.state.restaurants[record["restaurant_id"]]
        cutoff = restaurant["cancellation_cutoff_minutes"] * 60
        if record["start_ts"] - self.clock() <= cutoff:
            raise conflict("cutoff_passed", "the booking is within its cancellation cutoff")

    @staticmethod
    def _parse_changes(body):
        for field in ("table_id", "starts_at_local"):
            if field in body and not isinstance(body[field], str):
                raise malformed_request(f"{field} must be a string")
        return {k: body[k] for k in ("table_id", "starts_at_local", "party_size") if k in body}

    def _plan_amendment(self, record, changes):
        """The new values of `record` after `changes`; nothing is modified."""
        if record["status"] == "cancelled":
            raise conflict("reservation_cancelled", "the reservation is cancelled")
        self._require_before_cutoff(record)
        party_size = _valid_party_size(changes["party_size"]) if "party_size" in changes \
            else record["party_size"]
        naive = _valid_local_start(changes["starts_at_local"]) if "starts_at_local" in changes else None
        restaurant = self.state.restaurants[record["restaurant_id"]]
        table_id, party_size, start_ts, end_ts = self._resolve_booking(
            restaurant, changes.get("table_id", record["table_id"]), party_size, naive, record)
        return {"table_id": table_id, "party_size": party_size, "start_ts": start_ts, "end_ts": end_ts,
                "starts_at_local": timeutil.format_local(naive) if naive else record["starts_at_local"]}

    def _resolve_booking(self, restaurant, table_id, party_size, naive, existing):
        """Validate a booking against its restaurant; returns (table, party, start, end).

        `naive` is None for an amendment that keeps the current time (`existing`).
        """
        table = next((t for t in restaurant["tables"] if t["id"] == table_id), None)
        if table is None:
            raise not_found("no such table at this restaurant")
        if naive is None:
            start_ts, end_ts = existing["start_ts"], existing["end_ts"]
        else:
            start_ts, end_ts = self._slot(restaurant, naive)
        if party_size > table["capacity"]:
            raise unprocessable("party_exceeds_capacity", "party is larger than the table capacity")
        return table_id, party_size, start_ts, end_ts

    @staticmethod
    def _slot(restaurant, naive):
        zone = timeutil.load_zone(restaurant["timezone"])
        start_ts, exists = timeutil.resolve_local(zone, naive)
        if not exists:
            raise unprocessable("invalid_local_time", "that local time does not exist")
        minute = naive.hour * 60 + naive.minute
        weekday = timeutil.WEEKDAYS[naive.weekday()]
        for entry in restaurant["opening_hours"]:
            opens, closes = timeutil.parse_clock(entry["opens"]), timeutil.parse_clock(entry["closes"])
            if entry["weekday"] == weekday and opens <= minute < closes:
                break
        else:
            raise unprocessable("outside_opening_hours", "the restaurant is closed at that time")
        if (minute - opens) % restaurant["slot_minutes"]:
            raise unprocessable("not_on_slot_grid", "start is not on the slot grid")
        end_ts = start_ts + restaurant["reservation_duration_minutes"] * 60
        closes_ts, _ = timeutil.resolve_local(zone, naive.replace(hour=closes // 60, minute=closes % 60))
        if end_ts > closes_ts:
            raise unprocessable("outside_opening_hours", "the reservation would end after closing")
        return start_ts, end_ts

    def _require_free(self, restaurant_id, table_id, start_ts, end_ts, ignore):
        """409 when a confirmed booking other than those in `ignore` overlaps the table."""
        for res in self.state.reservations.values():
            if res["restaurant_id"] == restaurant_id and res["table_id"] == table_id and res["status"] == "confirmed" and res["id"] not in ignore \
                    and res["start_ts"] < end_ts and start_ts < res["end_ts"]:
                raise conflict("table_unavailable", "the table is taken for an overlapping interval")

    def _view(self, record):
        zone = timeutil.load_zone(self.state.restaurants[record["restaurant_id"]]["timezone"])
        return {"reservation_id": record["id"], "reference": record["reference"],
                "restaurant_id": record["restaurant_id"], "table_id": record["table_id"],
                "party_size": record["party_size"], "status": record["status"],
                "starts_at_local": record["starts_at_local"],
                "starts_at": timeutil.to_rfc3339(record["start_ts"], zone),
                "ends_at": timeutil.to_rfc3339(record["end_ts"], zone),
                "created_at": record["created_at"]}
