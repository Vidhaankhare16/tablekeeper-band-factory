"""Booking policies: the dated rules a restaurant publishes and the terms a booking accepts."""
import copy

from . import timeutil

POLICY_FIELDS = ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes",
                 "opening_hours", "capacities")


def base_policy(restaurant):
    """Policy 0: the rules of the original fixture."""
    return {"policy_version": 0, "effective_from": None,
            "slot_minutes": restaurant["slot_minutes"],
            "reservation_duration_minutes": restaurant["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": restaurant["cancellation_cutoff_minutes"],
            "opening_hours": restaurant["opening_hours"],
            "capacities": {t["id"]: t["capacity"] for t in restaurant["tables"]}}


def select_policy(restaurant, date_text):
    """The policy for a local start date: greatest effective_from not after it, then greatest version."""
    chosen = None
    for policy in restaurant["policies"]:
        if policy["effective_from"] <= date_text and (
                chosen is None or (policy["effective_from"], policy["policy_version"])
                > (chosen["effective_from"], chosen["policy_version"])):
            chosen = policy
    return chosen or base_policy(restaurant)


def accepted_terms(policy):
    """The snapshot a reservation carries: the whole policy except `effective_from`."""
    return {"policy_version": policy["policy_version"],
            **copy.deepcopy({field: policy[field] for field in POLICY_FIELDS})}


def parse_opening_hours(value, unique_weekdays=False):
    if not isinstance(value, list):
        raise ValueError("opening_hours must be a list")
    hours, weekdays = [], set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("invalid opening hours entry")
        opens, closes = timeutil.parse_clock(entry.get("opens")), timeutil.parse_clock(entry.get("closes"))
        weekday = entry.get("weekday")
        if weekday not in timeutil.WEEKDAYS or opens is None or closes is None or opens >= closes:
            raise ValueError("invalid opening hours entry")
        if unique_weekdays and weekday in weekdays:
            raise ValueError("duplicate weekday in opening hours")
        weekdays.add(weekday)
        hours.append({"weekday": weekday, "opens": entry["opens"], "closes": entry["closes"]})
    return hours


def _bounded_int(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{what} must be an integer from {low} to {high}")
    return value


def parse_policy(raw, table_ids):
    """A complete policy (without its version), validated. Raises ValueError when invalid."""
    if not isinstance(raw, dict):
        raise ValueError("a policy must be an object")
    effective_from = raw.get("effective_from")
    if not isinstance(effective_from, str) or timeutil.parse_date(effective_from) is None:
        raise ValueError("effective_from must be a YYYY-MM-DD date")
    capacities = raw.get("capacities")
    if not isinstance(capacities, dict) or set(capacities) != set(table_ids):
        raise ValueError("capacities must name exactly the restaurant's tables")
    return {"effective_from": effective_from,
            "slot_minutes": _bounded_int(raw.get("slot_minutes"), 1, 1440, "slot_minutes"),
            "reservation_duration_minutes": _bounded_int(
                raw.get("reservation_duration_minutes"), 1, 1440, "reservation_duration_minutes"),
            "cancellation_cutoff_minutes": _bounded_int(
                raw.get("cancellation_cutoff_minutes"), 0, 10080, "cancellation_cutoff_minutes"),
            "opening_hours": parse_opening_hours(raw.get("opening_hours"), unique_weekdays=True),
            "capacities": {t: _bounded_int(capacities[t], 1, 100, "capacity") for t in table_ids}}
