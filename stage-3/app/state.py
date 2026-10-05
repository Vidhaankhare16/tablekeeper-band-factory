"""The complete service state, its fixture loader and its export/import form."""
import copy
import re
import time

from . import timeutil
from .errors import validation_failed
from .history import append_entry, creation_changes
from .passwords import hash_password
from .policies import accepted_terms, base_policy, parse_opening_hours, parse_policy

MAX_ID_LENGTH = 64
STATUSES = ("confirmed", "cancelled")
_REFERENCE = re.compile(r"[A-Z0-9]{6,12}", re.ASCII)


class State:
    def __init__(self):
        self.users = {}          # user id -> {id, email, display_name, password_hash}
        self.user_by_email = {}  # lower-cased email -> user id
        self.tokens = {}         # bearer token -> user id
        self.restaurants = {}    # restaurant id -> fixture-shaped dict
        self.reservations = {}   # reservation id -> reservation record
        self.by_reference = {}   # reference -> reservation id
        self.series = {}         # series id -> series record
        self.receipts = {}       # (user id, method, path, key) -> {"body", "response"}
        self.next_user = 1
        self.next_reservation = 1
        self.next_series = 1

    def allocate_user_id(self):
        while f"u_{self.next_user}" in self.users:
            self.next_user += 1
        user_id = f"u_{self.next_user}"
        self.next_user += 1
        return user_id

    def allocate_reservation_id(self):
        while f"res_{self.next_reservation}" in self.reservations:
            self.next_reservation += 1
        reservation_id = f"res_{self.next_reservation}"
        self.next_reservation += 1
        return reservation_id

    def allocate_series_id(self):
        while f"ser_{self.next_series}" in self.series:
            self.next_series += 1
        series_id = f"ser_{self.next_series}"
        self.next_series += 1
        return series_id

    def add_user(self, user):
        self.users[user["id"]] = user
        self.user_by_email[user["email"].lower()] = user["id"]

    def add_reservation(self, record):
        self.reservations[record["id"]] = record
        self.by_reference[record["reference"]] = record["id"]

    # ---- export / import ----

    def dump(self):
        return copy.deepcopy({
            "users": list(self.users.values()),
            "tokens": self.tokens,
            "restaurants": list(self.restaurants.values()),
            "reservations": list(self.reservations.values()),
            "series": list(self.series.values()),
            "receipts": [
                {"user_id": uid, "method": method, "path": path, "key": key,
                 "body": rec["body"], "response": rec["response"]}
                for (uid, method, path, key), rec in self.receipts.items()
            ],
            "next_user": self.next_user,
            "next_reservation": self.next_reservation,
            "next_series": self.next_series,
        })

    @classmethod
    def load(cls, dumped):
        """Rebuild a state from `dump()` output; raises ApiError(422) when it is invalid."""
        state = cls()
        try:
            _load_dump(state, _expect_object(dumped, "state"))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise validation_failed(f"invalid state: {exc}")
        return state


def _load_dump(state, dumped):
    for user in _expect_list(dumped["users"], "users"):
        user = _expect_object(user, "user")
        _require_strings(user, "id", "email", "display_name", "password_hash")
        state.add_user({k: user[k] for k in ("id", "email", "display_name", "password_hash")})
    for restaurant in _expect_list(dumped["restaurants"], "restaurants"):
        normalized = normalize_restaurant(restaurant)
        state.restaurants[normalized["id"]] = normalized
    for record in _expect_list(dumped["reservations"], "reservations"):
        record = _expect_object(record, "reservation")
        _require_strings(record, "id", "reference", "user_id", "restaurant_id",
                         "status", "starts_at_local", "created_at")
        for field in ("party_size", "start_ts", "end_ts"):
            _require_int(record, field)
        if record["status"] not in STATUSES or record["restaurant_id"] not in state.restaurants:
            raise ValueError("invalid reservation")
        restaurant = state.restaurants[record["restaurant_id"]]
        table_ids = _table_ids(record)
        if not {t["id"] for t in restaurant["tables"]}.issuperset(table_ids):
            raise ValueError("reservation on unknown table")
        loaded = {**{k: record[k] for k in RESERVATION_FIELDS}, "table_ids": table_ids,
                  "series_id": record.get("series_id"), "series_index": record.get("series_index")}
        if "revision" in record:  # written by a stage-3 service; earlier exports lack these
            _require_int(record, "revision")
            if not isinstance(record["terms"], dict) or not isinstance(record["history"], list):
                raise ValueError("invalid revision, terms or history")
            loaded.update({k: record[k] for k in ("revision", "terms", "history")})
        else:
            add_stage_3_defaults(loaded, restaurant)
        state.add_reservation(loaded)
    for series in _expect_list(dumped.get("series", []), "series"):
        series = _expect_object(series, "series")
        _require_strings(series, "id", "user_id", "restaurant_id")
        _require_int(series, "interval_weeks")
        _require_int(series, "revision")
        for occurrence in _expect_list(series["occurrences"], "occurrences"):
            _require_int(_expect_object(occurrence, "occurrence"), "index")
            _require_strings(occurrence, "reference")
            if not isinstance(occurrence["exception"], bool) or occurrence["reference"] not in state.by_reference:
                raise ValueError("invalid occurrence")
        state.series[series["id"]] = {k: series[k] for k in
                                      ("id", "user_id", "restaurant_id", "interval_weeks", "revision",
                                       "occurrences")}
    for token, user_id in _expect_object(dumped["tokens"], "tokens").items():
        if user_id not in state.users:
            raise ValueError("token of unknown user")
        state.tokens[token] = user_id
    for receipt in _expect_list(dumped["receipts"], "receipts"):
        receipt = _expect_object(receipt, "receipt")
        _require_strings(receipt, "user_id", "method", "path", "key", "body")
        if "response" not in receipt:
            raise ValueError("receipt without response")
        state.receipts[(receipt["user_id"], receipt["method"], receipt["path"], receipt["key"])] = {
            "body": receipt["body"], "response": receipt["response"]}
    state.next_user = _require_int(dumped, "next_user")
    state.next_reservation = _require_int(dumped, "next_reservation")
    state.next_series = _require_int(dumped, "next_series") if "next_series" in dumped else 1


def add_stage_3_defaults(record, restaurant):
    """Give a reservation without revision data (seeded, or from an earlier stage) revision 1,
    policy-0 terms and a `created` history entry."""
    record["revision"] = 1
    record["terms"] = accepted_terms(base_policy(restaurant))
    record["history"] = []
    append_entry(record, record["created_at"], "created",
                 creation_changes(record["table_ids"], record["starts_at_local"], record["party_size"]))


RESERVATION_FIELDS = ("id", "reference", "user_id", "restaurant_id", "party_size",
                      "status", "starts_at_local", "start_ts", "end_ts", "created_at")


def _table_ids(raw):
    """The table set of a reservation: `table_ids`, or `table_id` as a set of one (stage 1 form)."""
    if "table_ids" in raw and "table_id" not in raw:
        tables = raw["table_ids"]
        if isinstance(tables, list) and 1 <= len(tables) <= 2 and len(set(tables)) == len(tables) \
                and all(isinstance(t, str) and t and len(t) <= MAX_ID_LENGTH for t in tables):
            return list(tables)
    elif "table_id" in raw and "table_ids" not in raw:
        _require_id(raw, "table_id")
        return [raw["table_id"]]
    raise ValueError("a reservation needs table_id, or table_ids with one or two distinct ids")


def _expect_object(value, what):
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object")
    return value


def _expect_list(value, what):
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list")
    return value


def _require_strings(obj, *fields):
    for field in fields:
        if not isinstance(obj[field], str):
            raise ValueError(f"{field} must be a string")


def _require_int(obj, field):
    value = obj[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


# ---- fixtures ----

def normalize_restaurant(raw):
    """The fixture-shaped restaurant dict, validated. Raises ValueError when invalid."""
    raw = _expect_object(raw, "restaurant")
    _require_id(raw, "id")
    if timeutil.load_zone(raw["timezone"]) is None:
        raise ValueError("unknown timezone")
    for field, minimum in (("slot_minutes", 1), ("reservation_duration_minutes", 1),
                           ("cancellation_cutoff_minutes", 0)):
        if _require_int(raw, field) < minimum:
            raise ValueError(f"{field} out of range")
    hours = parse_opening_hours(raw["opening_hours"])
    tables = []
    seen = set()
    for table in _expect_list(raw["tables"], "tables"):
        table = _expect_object(table, "table")
        _require_id(table, "id")
        if table["id"] in seen or _require_int(table, "capacity") < 0:
            raise ValueError("invalid table")
        seen.add(table["id"])
        label = table.get("label", table["id"])
        tables.append({"id": table["id"], "label": label if isinstance(label, str) else str(label),
                       "capacity": table["capacity"]})
    combinable = []
    for pair in _expect_list(raw.get("combinable", []), "combinable"):
        if not (isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]
                and all(isinstance(t, str) and t in seen for t in pair)):
            raise ValueError("combinable entries are pairs of distinct tables of the restaurant")
        combinable.append(list(pair))
    managers = raw.get("manager_user_ids", [])
    if not isinstance(managers, list) or not all(isinstance(m, str) for m in managers):
        raise ValueError("manager_user_ids must be a list of user ids")
    policies = []
    for version, policy in enumerate(_expect_list(raw.get("policies", []), "policies"), start=1):
        if _require_int(_expect_object(policy, "policy"), "policy_version") != version:
            raise ValueError("policy versions must count up from 1")
        policies.append({**parse_policy(policy, [t["id"] for t in tables]), "policy_version": version})
    revision = _require_int(raw, "revision") if "revision" in raw else 0
    name = raw.get("name", raw["id"])
    return {"id": raw["id"], "name": name if isinstance(name, str) else str(name),
            "timezone": raw["timezone"], "slot_minutes": raw["slot_minutes"],
            "reservation_duration_minutes": raw["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": raw["cancellation_cutoff_minutes"],
            "opening_hours": hours, "tables": tables, "combinable": combinable,
            "manager_user_ids": list(managers), "policies": policies, "revision": revision}


def _require_id(obj, field):
    value = obj[field]
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH:
        raise ValueError(f"{field} must be a non-empty string of at most {MAX_ID_LENGTH} characters")


def state_from_fixture(fixture):
    """Build a complete new state from a reset fixture. Raises ApiError(422) when invalid.

    Hashes passwords, so callers run it outside the state lock.
    """
    try:
        state = State()
        fixture = _expect_object(fixture, "fixture")
        for raw in _expect_list(fixture.get("users", []), "users"):
            _load_fixture_user(state, _expect_object(raw, "user"))
        for raw in _expect_list(fixture.get("restaurants", []), "restaurants"):
            restaurant = normalize_restaurant(raw)
            if restaurant["id"] in state.restaurants:
                raise ValueError("duplicate restaurant id")
            state.restaurants[restaurant["id"]] = restaurant
        for raw in _expect_list(fixture.get("reservations", []), "reservations"):
            _load_fixture_reservation(state, _expect_object(raw, "reservation"))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise validation_failed(f"invalid fixture: {exc}")
    return state


def _load_fixture_user(state, raw):
    _require_strings(raw, "email", "password")
    user_id = raw["id"] if "id" in raw else state.allocate_user_id()
    if not isinstance(user_id, str) or not user_id or len(user_id) > MAX_ID_LENGTH:
        raise ValueError("invalid user id")
    display_name = raw.get("display_name", raw["email"].split("@")[0])
    if user_id in state.users or raw["email"].lower() in state.user_by_email \
            or not isinstance(display_name, str):
        raise ValueError("duplicate or invalid user")
    state.add_user({"id": user_id, "email": raw["email"], "display_name": display_name,
                    "password_hash": hash_password(raw["password"])})


def _load_fixture_reservation(state, raw):
    for field in ("id", "reference", "user_id", "restaurant_id"):
        _require_id(raw, field)
    table_ids = _table_ids(raw)
    _require_strings(raw, "starts_at_local")
    party_size = _require_int(raw, "party_size")
    status = raw.get("status", "confirmed")
    restaurant = state.restaurants[raw["restaurant_id"]]
    naive = timeutil.parse_local_datetime(raw["starts_at_local"])
    created_at = raw.get("created_at", timeutil.utc_now_rfc3339(time.time()))
    if not _REFERENCE.fullmatch(raw["reference"]):
        raise ValueError("reference must be 6 to 12 characters of A-Z0-9")
    if naive is None or status not in STATUSES or not isinstance(created_at, str) \
            or raw["id"] in state.reservations or raw["reference"] in state.by_reference \
            or not {t["id"] for t in restaurant["tables"]}.issuperset(table_ids):
        raise ValueError("invalid or duplicate seeded reservation")
    start_ts, _ = timeutil.resolve_local(timeutil.load_zone(restaurant["timezone"]), naive)
    end_ts = start_ts + restaurant["reservation_duration_minutes"] * 60
    if status == "confirmed" and any(
            other["status"] == "confirmed" and other["restaurant_id"] == raw["restaurant_id"]
            and set(other["table_ids"]) & set(table_ids) and other["start_ts"] < end_ts and start_ts < other["end_ts"]
            for other in state.reservations.values()):
        raise ValueError("seeded reservations overlap on a table")
    record = {
        "id": raw["id"], "reference": raw["reference"], "user_id": raw["user_id"],
        "restaurant_id": raw["restaurant_id"], "table_ids": table_ids,
        "party_size": party_size, "status": status,
        "starts_at_local": timeutil.format_local(naive), "start_ts": start_ts,
        "end_ts": end_ts, "created_at": created_at, "series_id": None, "series_index": None}
    add_stage_3_defaults(record, restaurant)
    state.add_reservation(record)
