"""Domain rules. Every operation runs inside one lock, so each state change is serialized."""
import copy
import json
import re
import secrets
import threading
import time
from datetime import timedelta

from . import timeutil
from .booking_rules import plan_booking
from .errors import (ApiError, conflict, malformed_request, missing_idempotency_key, not_found,
                     unauthenticated, validation_failed)
from .history import amendment_changes, append_entry, creation_changes
from .passwords import hash_password, verify_password
from .policies import parse_policy, select_policy
from .state import State, state_from_fixture

TRACK = "tablekeeper"
FORMAT_VERSION = 1
MAX_IDEMPOTENCY_KEY = 255
MAX_MOVES = 8
REFERENCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
REFERENCE_LENGTH = 6
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_DIGITS = re.compile(r"[0-9]{1,18}", re.ASCII)
_INTERNAL_RESTAURANT_FIELDS = ("manager_user_ids", "policies", "revision")
_BOOKING_STRING_FIELDS = ("restaurant_id", "starts_at_local")
MIN_SERIES_COUNT, MAX_SERIES_COUNT = 2, 12
MAX_INTERVAL_WEEKS = 4


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


def _check_table_field_types(body):
    if "table_id" in body and not isinstance(body["table_id"], str):
        raise malformed_request("table_id must be a string")
    if "table_ids" in body and not (isinstance(body["table_ids"], list)
                                    and all(isinstance(t, str) for t in body["table_ids"])):
        raise malformed_request("table_ids must be a list of strings")


def _requested_tables(body):
    """The table ids a request names (None when it names none); `table_id` is a set of one."""
    if "table_id" in body and "table_ids" in body:
        raise validation_failed("send table_id or table_ids, not both")
    tables = [body["table_id"]] if "table_id" in body else body.get("table_ids")
    if tables is not None and (not tables or len(set(tables)) != len(tables)):
        raise validation_failed("table_ids must be a non-empty list without duplicates")
    return tables


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

    # ---- restaurants, policies and availability ----

    def list_restaurants(self):
        with self.lock:
            return 200, {"restaurants": [
                {"id": r["id"], "name": r["name"], "timezone": r["timezone"]}
                for r in self.state.restaurants.values()]}

    def get_restaurant(self, restaurant_id):
        with self.lock:
            restaurant = self._restaurant(restaurant_id)
            return 200, {k: v for k, v in restaurant.items() if k not in _INTERNAL_RESTAURANT_FIELDS}

    def list_policies(self, restaurant_id):
        with self.lock:
            return 200, {"policies": copy.deepcopy(self._restaurant(restaurant_id)["policies"])}

    def publish_policy(self, authorization, restaurant_id, idempotency_key, raw):
        path = f"/restaurants/{restaurant_id}/policies"
        with self.lock:
            user_id = self.authenticate(authorization)
            restaurant = self._restaurant(restaurant_id)
            if user_id not in restaurant["manager_user_ids"]:
                raise ApiError(403, "forbidden", "only managers can publish policies")
            body = parse_object(raw)
            return self._idempotent(user_id, "POST", path, idempotency_key, body,
                                    lambda: self._publish(restaurant, body))

    def _publish(self, restaurant, body):
        try:
            policy = parse_policy(body, [t["id"] for t in restaurant["tables"]])
        except ValueError as error:
            raise validation_failed(str(error))
        policy["policy_version"] = len(restaurant["policies"]) + 1
        restaurant["policies"].append(policy)
        restaurant["revision"] += 1
        return copy.deepcopy(policy)

    def availability(self, query):
        restaurant_id, date_text, party_text = (query.get(k) for k in ("restaurant_id", "date", "party_size"))
        if not restaurant_id or not date_text or not party_text:
            raise validation_failed("restaurant_id, date and party_size are required")
        date = timeutil.parse_date(date_text)
        if date is None:
            raise validation_failed("date must be YYYY-MM-DD")
        if not _DIGITS.fullmatch(party_text) or int(party_text) < 1:
            raise validation_failed("party_size must be a positive integer")
        if "explain" in query and query["explain"] != "true":
            raise validation_failed("explain must be true")
        with self.lock:
            restaurant = self._restaurant(restaurant_id)
            policy = select_policy(restaurant, date_text)
            slots = self._slots(restaurant, policy, date, int(party_text), "explain" in query)
        return 200, {"restaurant_id": restaurant_id, "date": date_text,
                     "timezone": restaurant["timezone"], "slots": slots}

    def _slots(self, restaurant, policy, date, party_size, explain):
        zone = timeutil.load_zone(restaurant["timezone"])
        duration = policy["reservation_duration_minutes"] * 60
        weekday = timeutil.WEEKDAYS[date.weekday()]
        taken = {}
        for res in self.state.reservations.values():
            if res["restaurant_id"] == restaurant["id"] and res["status"] == "confirmed":
                for table_id in res["table_ids"]:
                    taken.setdefault(table_id, []).append((res["start_ts"], res["end_ts"]))
        capacities = policy["capacities"]
        slots, seen = [], set()
        for entry in sorted((h for h in policy["opening_hours"] if h["weekday"] == weekday),
                            key=lambda h: timeutil.parse_clock(h["opens"])):
            opens, closes = timeutil.parse_clock(entry["opens"]), timeutil.parse_clock(entry["closes"])
            closes_ts, _ = timeutil.resolve_local(zone, date.replace(hour=closes // 60, minute=closes % 60))
            for minute in range(opens, closes, policy["slot_minutes"]):
                naive = date.replace(hour=minute // 60, minute=minute % 60)
                start_ts, exists = timeutil.resolve_local(zone, naive)
                local = timeutil.format_local(naive)
                if not exists or local in seen or start_ts + duration > closes_ts:
                    continue
                seen.add(local)
                free = {t["id"]: not any(s < start_ts + duration and start_ts < e
                                         for s, e in taken.get(t["id"], ()))
                        for t in restaurant["tables"]}
                fits = {t: party_size <= capacities[t] for t in free}
                singles = [[t] for t in free if fits[t] and free[t]]
                pairs = [pair for pair in restaurant["combinable"]
                         if sum(capacities[t] for t in pair) >= party_size and all(free[t] for t in pair)]
                slot = {"starts_at_local": local, "starts_at": timeutil.to_rfc3339(start_ts, zone),
                        "available_table_ids": [ids[0] for ids in singles],
                        "available_options": [
                            {"table_ids": ids, "capacity": sum(capacities[t] for t in ids)}
                            for ids in singles + pairs]}
                if explain:
                    slot["explain"] = [
                        {"table_id": t, "policy_version": policy["policy_version"],
                         "available": fits[t] and free[t],
                         "rules": [{"rule": "capacity", "holds": fits[t]},
                                   {"rule": "no_overlap", "holds": free[t]}]} for t in free]
                slots.append(slot)
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
        _check_table_field_types(body)
        if "party_size" not in body:
            raise validation_failed("party_size is required")
        requested = _requested_tables(body)
        if requested is None:
            raise validation_failed("table_id or table_ids is required")
        party_size = _valid_party_size(body["party_size"])
        naive = _valid_local_start(body["starts_at_local"])
        restaurant = self._restaurant(body["restaurant_id"])
        plan = self._plan(restaurant, requested, party_size, naive)
        self._require_free(restaurant["id"], plan["table_ids"], plan["start_ts"], plan["end_ts"], ignore=())
        record = self._new_reservation(user_id, restaurant, plan, party_size, naive)
        restaurant["revision"] += 1
        return self._view(record)

    def _plan(self, restaurant, table_ids, party_size, naive):
        policy = select_policy(restaurant, timeutil.format_local(naive)[:10])
        return plan_booking(restaurant, policy, table_ids, party_size, naive)

    def _new_reservation(self, user_id, restaurant, plan, party_size, naive):
        record = {"id": self.state.allocate_reservation_id(), "reference": self._new_reference(),
                  "user_id": user_id, "restaurant_id": restaurant["id"], "table_ids": plan["table_ids"],
                  "party_size": party_size, "status": "confirmed",
                  "starts_at_local": timeutil.format_local(naive), "start_ts": plan["start_ts"],
                  "end_ts": plan["end_ts"], "created_at": timeutil.utc_now_rfc3339(self.clock()),
                  "revision": 1, "terms": plan["terms"], "history": [],
                  "series_id": None, "series_index": None}
        append_entry(record, record["created_at"], "created",
                     creation_changes(record["table_ids"], record["starts_at_local"], party_size))
        self.state.add_reservation(record)
        return record

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

    def get_history(self, authorization, reference):
        with self.lock:
            record = self._owned_or_hidden(authorization, reference)
            return 200, {"reference": reference, "entries": copy.deepcopy(record["history"])}

    def get_decision(self, authorization, reference):
        with self.lock:
            record = self._owned_or_hidden(authorization, reference)
            return 200, {"reference": reference, "revision": record["revision"],
                         "accepted_terms": copy.deepcopy(record["terms"])}

    def cancel(self, authorization, reference):
        with self.lock:
            record = self._owned(self.authenticate(authorization), reference)
            if record["status"] != "cancelled":
                self._require_before_cutoff(record)
                record["status"] = "cancelled"
                record["revision"] += 1
                append_entry(record, self._now(), "cancelled", [])
                self.state.restaurants[record["restaurant_id"]]["revision"] += 1
                self._touch_series([record], mark_exceptions=False)
            return 200, self._view(record)

    def amend(self, authorization, reference, raw):
        with self.lock:
            user_id = self.authenticate(authorization)
            changes = self._parse_changes(parse_object(raw))
            record = self._owned(user_id, reference)
            plan = self._prepare_change(record, changes)
            if plan is not None:
                self._require_free(record["restaurant_id"], plan["table_ids"], plan["start_ts"],
                                   plan["end_ts"], ignore=(record["id"],))
                self._apply_change(record, plan)
                self.state.restaurants[record["restaurant_id"]]["revision"] += 1
                self._touch_series([record], mark_exceptions=True)
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
        plans = [self._prepare_change(record, change) for record, change in zip(records, changes)]
        resulting = [plan or record for record, plan in zip(records, plans)]
        listed = {r["id"] for r in records}
        restaurant_id = records[0]["restaurant_id"]
        for index, plan in enumerate(plans):
            if plan is None:
                continue
            self._require_free(restaurant_id, plan["table_ids"], plan["start_ts"], plan["end_ts"],
                               ignore=listed)
            for other_index, other in enumerate(resulting):
                if other_index != index and set(other["table_ids"]) & set(plan["table_ids"]) \
                        and other["start_ts"] < plan["end_ts"] and plan["start_ts"] < other["end_ts"]:
                    raise conflict("table_unavailable", "moves overlap each other")
        changed = [(record, plan) for record, plan in zip(records, plans) if plan is not None]
        for record, plan in changed:
            self._apply_change(record, plan)
        if changed:
            self.state.restaurants[restaurant_id]["revision"] += 1
            self._touch_series([record for record, _ in changed], mark_exceptions=True)
        return {"reservations": [self._view(r) for r in records]}

    # ---- series ----

    def create_series(self, authorization, idempotency_key, raw):
        path = "/series"
        with self.lock:
            user_id = self.authenticate(authorization)
            body = parse_object(raw)
            return self._idempotent(user_id, "POST", path, idempotency_key, body,
                                    lambda: self._adopt(user_id, body))

    def get_series(self, authorization, series_id):
        with self.lock:
            try:
                user_id = self.authenticate(authorization)
            except ApiError:
                raise not_found("no such series")
            series = self.state.series.get(series_id)
            if series is None or series["user_id"] != user_id:
                raise not_found("no such series")
            return 200, self._series_view(series)

    def _adopt(self, user_id, body):
        if not isinstance(body.get("anchor_reference"), str):
            raise validation_failed("anchor_reference is required")
        count, interval = body.get("count"), body.get("interval_weeks")
        for value, low, high, what in ((count, MIN_SERIES_COUNT, MAX_SERIES_COUNT, "count"),
                                       (interval, 1, MAX_INTERVAL_WEEKS, "interval_weeks")):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise validation_failed(f"{what} must be an integer from {low} to {high}")
        anchor = self._owned(user_id, body["anchor_reference"])
        if anchor["status"] == "cancelled":
            raise conflict("reservation_cancelled", "the anchor is cancelled")
        if anchor["series_id"] is not None:
            raise conflict("already_in_series", "the reservation already belongs to a series")
        self._require_before_cutoff(anchor)
        restaurant = self.state.restaurants[anchor["restaurant_id"]]
        first = timeutil.parse_local_datetime(anchor["starts_at_local"])
        plans = []
        for index in range(1, count):
            naive = first + timedelta(weeks=index * interval)
            plan = self._plan(restaurant, anchor["table_ids"], anchor["party_size"], naive)
            self._require_free(restaurant["id"], plan["table_ids"], plan["start_ts"], plan["end_ts"],
                               ignore=())
            plans.append((naive, plan))
        series_id = self.state.allocate_series_id()
        occurrences = [{"index": 0, "reference": anchor["reference"], "exception": False}]
        anchor["series_id"], anchor["series_index"] = series_id, 0
        for index, (naive, plan) in enumerate(plans, start=1):
            record = self._new_reservation(user_id, restaurant, plan, anchor["party_size"], naive)
            record["series_id"], record["series_index"] = series_id, index
            occurrences.append({"index": index, "reference": record["reference"], "exception": False})
        series = {"id": series_id, "user_id": user_id, "restaurant_id": restaurant["id"],
                  "interval_weeks": interval, "revision": 1, "occurrences": occurrences}
        self.state.series[series_id] = series
        restaurant["revision"] += 1
        return self._series_view(series)

    def _series_view(self, series):
        return {"series_id": series["id"], "revision": series["revision"],
                "interval_weeks": series["interval_weeks"],
                "occurrences": [
                    {**occurrence, "reservation": self._view(
                        self.state.reservations[self.state.by_reference[occurrence["reference"]]])}
                    for occurrence in series["occurrences"]]}

    def _touch_series(self, records, mark_exceptions):
        """Bump the revision of each series the records belong to, once per series."""
        touched = {}
        for record in records:
            if record["series_id"] is not None:
                touched.setdefault(record["series_id"], []).append(record)
        for series_id, members in touched.items():
            series = self.state.series[series_id]
            series["revision"] += 1
            if mark_exceptions:
                for record in members:
                    series["occurrences"][record["series_index"]]["exception"] = True

    # ---- shared helpers ----

    def _now(self):
        return timeutil.utc_now_rfc3339(self.clock())

    def _restaurant(self, restaurant_id):
        restaurant = self.state.restaurants.get(restaurant_id)
        if restaurant is None:
            raise not_found("no such restaurant")
        return restaurant

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

    def _owned_or_hidden(self, authorization, reference):
        """The caller's reservation; 404 for everyone else, signed in or not."""
        try:
            user_id = self.authenticate(authorization)
        except ApiError:
            raise not_found("no such reservation")
        return self._owned(user_id, reference)

    def _require_before_cutoff(self, record):
        cutoff = record["terms"]["cancellation_cutoff_minutes"] * 60
        if record["start_ts"] - self.clock() <= cutoff:
            raise conflict("cutoff_passed", "the booking is within its cancellation cutoff")

    @staticmethod
    def _parse_changes(body):
        if "starts_at_local" in body and not isinstance(body["starts_at_local"], str):
            raise malformed_request("starts_at_local must be a string")
        _check_table_field_types(body)
        expected = body.get("expected_revision")
        if "expected_revision" in body and (isinstance(expected, bool) or not isinstance(expected, int)
                                            or expected < 1):
            raise validation_failed("expected_revision must be a positive integer")
        return {k: body[k] for k in ("table_id", "table_ids", "starts_at_local", "party_size",
                                     "expected_revision") if k in body}

    def _prepare_change(self, record, changes):
        """Check an amendment in the order the rules give; returns the new values, or None for a no-op.

        Nothing is modified.
        """
        if "expected_revision" in changes and changes["expected_revision"] != record["revision"]:
            raise conflict("stale_revision", "the reservation has changed since that revision")
        if record["status"] == "cancelled":
            raise conflict("reservation_cancelled", "the reservation is cancelled")
        self._require_before_cutoff(record)
        party_size = _valid_party_size(changes["party_size"]) if "party_size" in changes \
            else record["party_size"]
        naive = _valid_local_start(changes["starts_at_local"]) if "starts_at_local" in changes \
            else timeutil.parse_local_datetime(record["starts_at_local"])
        requested = _requested_tables(changes)
        if party_size == record["party_size"] and timeutil.format_local(naive) == record["starts_at_local"] \
                and (requested is None or set(requested) == set(record["table_ids"])):
            return None
        restaurant = self.state.restaurants[record["restaurant_id"]]
        plan = self._plan(restaurant, requested or record["table_ids"], party_size, naive)
        return {**plan, "party_size": party_size, "starts_at_local": timeutil.format_local(naive)}

    def _apply_change(self, record, plan):
        changes = amendment_changes(record, plan)
        record.update({k: plan[k] for k in ("table_ids", "party_size", "start_ts", "end_ts",
                                            "starts_at_local", "terms")})
        record["revision"] += 1
        append_entry(record, self._now(), "changed", changes)

    def _require_free(self, restaurant_id, table_ids, start_ts, end_ts, ignore):
        """409 when a confirmed booking other than those in `ignore` overlaps any of the tables."""
        for res in self.state.reservations.values():
            if res["restaurant_id"] == restaurant_id and res["status"] == "confirmed" \
                    and res["id"] not in ignore and set(res["table_ids"]) & set(table_ids) \
                    and res["start_ts"] < end_ts and start_ts < res["end_ts"]:
                raise conflict("table_unavailable", "a table is taken for an overlapping interval")

    def _view(self, record):
        zone = timeutil.load_zone(self.state.restaurants[record["restaurant_id"]]["timezone"])
        tables = record["table_ids"]
        view = {"reservation_id": record["id"], "reference": record["reference"],
                "restaurant_id": record["restaurant_id"], "table_ids": list(tables)}
        if len(tables) == 1:
            view["table_id"] = tables[0]
        return {**view, "party_size": record["party_size"], "status": record["status"],
                "starts_at_local": record["starts_at_local"],
                "starts_at": timeutil.to_rfc3339(record["start_ts"], zone),
                "ends_at": timeutil.to_rfc3339(record["end_ts"], zone),
                "created_at": record["created_at"], "revision": record["revision"],
                "accepted_terms": copy.deepcopy(record["terms"])}
