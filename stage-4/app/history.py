"""Reservation history entries and the field changes they record."""
import copy


def _table_field(old, new):
    if old is not None and len(old) == 1 and len(new) == 1:
        return {"field": "table_id", "from": old[0], "to": new[0]}
    if old is None and len(new) == 1:
        return {"field": "table_id", "from": None, "to": new[0]}
    return {"field": "table_ids", "from": None if old is None else list(old), "to": list(new)}


def creation_changes(table_ids, starts_at_local, party_size):
    return [_table_field(None, table_ids),
            {"field": "starts_at_local", "from": None, "to": starts_at_local},
            {"field": "party_size", "from": None, "to": party_size}]


def amendment_changes(old, new):
    """The fields that differ between two {table_ids, starts_at_local, party_size} values."""
    changes = []
    if set(old["table_ids"]) != set(new["table_ids"]):
        changes.append(_table_field(old["table_ids"], new["table_ids"]))
    for field in ("starts_at_local", "party_size"):
        if old[field] != new[field]:
            changes.append({"field": field, "from": old[field], "to": new[field]})
    return changes


def append_entry(record, at, event, changes):
    """Append the next entry, stamped with the record's current revision and terms."""
    record["history"].append({"seq": len(record["history"]) + 1, "at": at, "event": event,
                              "changes": changes, "revision": record["revision"],
                              "accepted_terms": copy.deepcopy(record["terms"])})
