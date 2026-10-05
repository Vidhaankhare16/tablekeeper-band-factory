"""Restaurant-local time handling. All instants are integer Unix seconds (UTC)."""
import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_YEAR, MAX_YEAR = 1900, 2200

_LOCAL_DATETIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", re.ASCII)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
_CLOCK = re.compile(r"(\d{2}):(\d{2})", re.ASCII)


@lru_cache(maxsize=None)
def load_zone(name):
    """The IANA zone called `name`, or None when it is not a valid zone name."""
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def _checked(parts):
    try:
        value = datetime(*parts)
    except ValueError:
        return None
    return value if MIN_YEAR <= value.year <= MAX_YEAR else None


def parse_local_datetime(text):
    """A bare `YYYY-MM-DDTHH:MM` as a naive datetime, or None."""
    match = _LOCAL_DATETIME.fullmatch(text)
    return _checked(map(int, match.groups())) if match else None


def parse_date(text):
    match = _DATE.fullmatch(text)
    return _checked(map(int, match.groups())) if match else None


def parse_clock(text):
    """`HH:MM` as minutes after local midnight, or None."""
    if not isinstance(text, str):
        return None
    match = _CLOCK.fullmatch(text)
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    return hours * 60 + minutes if hours < 24 and minutes < 60 else None


def format_local(naive):
    return naive.strftime("%Y-%m-%dT%H:%M")


def resolve_local(zone, naive):
    """Instant of a local wall-clock time, and whether that time exists.

    A repeated time resolves to its first occurrence. A time inside a spring-forward gap
    does not exist (the returned instant is then only a placeholder).
    """
    instant = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    exists = instant.astimezone(zone).replace(tzinfo=None) == naive
    return int(instant.timestamp()), exists


def to_rfc3339(timestamp, zone):
    return datetime.fromtimestamp(timestamp, zone).isoformat(timespec="seconds")


def utc_now_rfc3339(timestamp):
    return to_rfc3339(int(timestamp), UTC)
