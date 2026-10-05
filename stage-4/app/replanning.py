"""Exact seating planner: reassign bookings around a table closure."""
import re
from datetime import datetime

from . import timeutil

MAX_TABLES, MAX_PAIRS, MAX_BOOKINGS = 6, 4, 6
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})", re.ASCII)


def parse_instant(text):
    """An RFC 3339 instant with an explicit offset as Unix seconds, or None."""
    if not _INSTANT.fullmatch(text):
        return None
    try:
        instant = datetime.fromisoformat(text)
        if not timeutil.MIN_YEAR <= instant.year <= timeutil.MAX_YEAR:
            return None
        return int(instant.timestamp())
    except (ValueError, OverflowError):
        return None


def overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def options_of(restaurant):
    """Every single table then every declared pair, in rank order."""
    return [(t["id"],) for t in restaurant["tables"]] + [tuple(pair) for pair in restaurant["combinable"]]


def best_assignment(bookings, options, blocked):
    """The assignment of every booking minimizing (changed, unused seats, option ranks).

    bookings: dicts with reference, party_size, start_ts, end_ts, capacities, table_ids, sorted by
    reference. options: table tuples, rank = index. blocked(booking, tables) is True when the tables
    conflict with anything other than the other considered bookings. Returns a list of option
    indices, or None when no assignment is feasible.
    """
    candidates = []
    for booking in bookings:
        current = set(booking["table_ids"])
        found = []
        for rank, tables in enumerate(options):
            capacity = sum(booking["capacities"][t] for t in tables)
            if capacity >= booking["party_size"] and not blocked(booking, tables):
                found.append((rank, set(tables), capacity - booking["party_size"], set(tables) != current))
        if not found:
            return None
        candidates.append(found)
    best = {"key": None, "ranks": None}
    chosen = []

    def clashes(index, tables):
        return any(overlaps(bookings[index]["start_ts"], bookings[index]["end_ts"],
                            bookings[other]["start_ts"], bookings[other]["end_ts"]) and tables & chosen[other][1]
                   for other in range(index))

    def search(index, changed, unused):
        if best["key"] is not None and (changed, unused) > best["key"][:2]:
            return
        if index == len(bookings):
            key = (changed, unused, tuple(c[0] for c in chosen))
            if best["key"] is None or key < best["key"]:
                best["key"], best["ranks"] = key, [c[0] for c in chosen]
            return
        for rank, tables, spare, differs in candidates[index]:
            if clashes(index, tables):
                continue
            chosen.append((rank, tables))
            search(index + 1, changed + differs, unused + spare)
            chosen.pop()

    search(0, 0, 0)
    return best["ranks"]
