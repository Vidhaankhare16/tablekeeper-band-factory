"""Pure booking rules: validate a booking against one policy."""
from . import timeutil
from .errors import not_found, unprocessable
from .policies import accepted_terms

MAX_COMBINED_TABLES = 2


def booking_interval(restaurant, policy, naive):
    """(start, end) instants of a booking starting at local time `naive`, or the ordinary 422."""
    zone = timeutil.load_zone(restaurant["timezone"])
    start_ts, exists = timeutil.resolve_local(zone, naive)
    if not exists:
        raise unprocessable("invalid_local_time", "that local time does not exist")
    minute = naive.hour * 60 + naive.minute
    weekday = timeutil.WEEKDAYS[naive.weekday()]
    for entry in policy["opening_hours"]:
        opens, closes = timeutil.parse_clock(entry["opens"]), timeutil.parse_clock(entry["closes"])
        if entry["weekday"] == weekday and opens <= minute < closes:
            break
    else:
        raise unprocessable("outside_opening_hours", "the restaurant is closed at that time")
    if (minute - opens) % policy["slot_minutes"]:
        raise unprocessable("not_on_slot_grid", "start is not on the slot grid")
    end_ts = start_ts + policy["reservation_duration_minutes"] * 60
    closes_ts, _ = timeutil.resolve_local(zone, naive.replace(hour=closes // 60, minute=closes % 60))
    if end_ts > closes_ts:
        raise unprocessable("outside_opening_hours", "the reservation would end after closing")
    return start_ts, end_ts


def plan_booking(restaurant, policy, table_ids, party_size, naive):
    """Validate tables, time and party size; returns the values a booking would take."""
    capacities = policy["capacities"]
    if any(t not in capacities for t in table_ids):
        raise not_found("no such table at this restaurant")
    if len(table_ids) > MAX_COMBINED_TABLES:
        raise unprocessable("combination_not_allowed", "at most two tables can be combined")
    if len(table_ids) == 2:
        table_ids = next((pair for pair in restaurant["combinable"] if set(pair) == set(table_ids)), None)
        if table_ids is None:
            raise unprocessable("combination_not_allowed", "those tables are not combinable")
    start_ts, end_ts = booking_interval(restaurant, policy, naive)
    if party_size > sum(capacities[t] for t in table_ids):
        raise unprocessable("party_exceeds_capacity", "party is larger than the table capacity")
    return {"table_ids": list(table_ids), "start_ts": start_ts, "end_ts": end_ts,
            "terms": accepted_terms(policy)}
