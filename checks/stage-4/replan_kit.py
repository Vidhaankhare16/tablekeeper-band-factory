"""Helpers and a brute-force oracle for the stage-4 seating-change (replan) checks."""
from __future__ import annotations

import datetime as dt
import itertools
from zoneinfo import ZoneInfo

from conftest import call, check, new_key, iso, instant, restaurant, all_week, user, fixture, reset, login, add_days, safe_date

TZ = ZoneInfo("Europe/Berlin")


def inst(date, hhmm, tz=TZ):
    """An RFC 3339 instant with an explicit offset for a local time at the restaurant."""
    h, m = hhmm.split(":")
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time(int(h), int(m)), tzinfo=tz).isoformat()


def replan(c, rid, table_id, frm, to, key=None, **extra):
    b = {"table_id": table_id, "from": frm, "to": to}
    b.update(extra)
    return c.post(f"/restaurants/{rid}/replans", json=b, key=new_key() if key is None else key)


def plan_ok(c, rid, table_id, frm, to):
    r = replan(c, rid, table_id, frm, to)
    assert r.status == 201, f"[L4.2] preview should be 201: {r!r}"
    return r.json


def apply_plan(c, rid, plan_id, key=None, body=None):
    return c.post(f"/restaurants/{rid}/replans/{plan_id}/apply", json={} if body is None else body, key=new_key() if key is None else key)


def apply_ok(c, rid, plan_id):
    r = apply_plan(c, rid, plan_id)
    assert r.status == 201, f"[L4.20] apply should be 201: {r!r}"
    return r.json


def rev(c, rid="r_anker", table="t_1"):
    """The restaurant revision, observed through a throw-away preview of a closure in the year 2001 (no bookings there)."""
    r = replan(c, rid, table, "2001-01-01T00:00:00+00:00", "2001-01-01T01:00:00+00:00")
    assert r.status == 201, f"[L4.30] probe preview should be 201: {r!r}"
    assert r.json["assignments"] == []
    return r.json["restaurant_revision"]


def overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


class Oracle:
    """Brute-force optimum of the three-level objective for one restaurant state (the specification, executable)."""

    def __init__(self, tables, pairs, bookings, closures, new_closure):
        self.tables = [t["id"] for t in tables]                       # fixture order
        self.pairs = [tuple(p) for p in pairs]                        # declared order
        self.options = [(t,) for t in self.tables] + self.pairs       # rank = index
        self.bookings = bookings                                      # dicts: reference, party, start, end, tables(tuple), caps(dict), status
        self.closures = closures                                      # (table, start, end) previously applied
        self.new = new_closure                                        # (table, start, end)

    def considered(self):
        out = [b for b in self.bookings if b["status"] == "confirmed" and overlaps(b["start"], b["end"], self.new[1], self.new[2])]
        return sorted(out, key=lambda b: b["reference"])

    def fixed(self):
        cons = {b["reference"] for b in self.considered()}
        return [b for b in self.bookings if b["status"] == "confirmed" and b["reference"] not in cons]

    def feasible_options(self, b):
        res = []
        for rank, opt in enumerate(self.options):
            cap = sum(b["caps"][t] for t in opt)
            if cap < b["party"]:
                continue
            ok = True
            for (ct, c0, c1) in self.closures + [self.new]:
                if ct in opt and overlaps(b["start"], b["end"], c0, c1):
                    ok = False
            for f in self.fixed():
                if set(f["tables"]) & set(opt) and overlaps(b["start"], b["end"], f["start"], f["end"]):
                    ok = False
            if ok:
                res.append((rank, opt, cap))
        return res

    def solve(self):
        cons = self.considered()
        cands = [self.feasible_options(b) for b in cons]
        best = None
        for combo in itertools.product(*cands) if cons else [()]:
            bad = False
            for i in range(len(cons)):
                for j in range(i + 1, len(cons)):
                    if set(combo[i][1]) & set(combo[j][1]) and overlaps(cons[i]["start"], cons[i]["end"], cons[j]["start"], cons[j]["end"]):
                        bad = True
            if bad:
                continue
            moved = sum(1 for b, c in zip(cons, combo) if set(c[1]) != set(b["tables"]))
            unused = sum(c[2] - b["party"] for b, c in zip(cons, combo))
            key = (moved, unused, tuple(c[0] for c in combo))
            if best is None or key < best[0]:
                best = (key, combo)
        if best is None:
            return None
        (moved, unused, ranks), combo = best
        return {"moved": moved, "unused": unused,
                "assignments": [{"reference": b["reference"], "table_ids": list(c[1]), "changed": set(c[1]) != set(b["tables"])} for b, c in zip(cons, combo)]}


def snapshot_world(client_by_user, rid, tables, pairs, closures, new_closure):
    """Read every booking of the restaurant from the owners' lists and build an Oracle."""
    bks = []
    for c in client_by_user:
        for r in c.get("/reservations").json["reservations"]:
            if r["restaurant_id"] != rid:
                continue
            bks.append({"reference": r["reference"], "party": r["party_size"], "start": iso(r["starts_at"]), "end": iso(r["ends_at"]),
                        "tables": tuple(r["table_ids"]), "caps": r["accepted_terms"]["capacities"], "status": r["status"]})
    return Oracle(tables, pairs, bks, closures, new_closure)


def normalise(assignments):
    return [{"reference": a["reference"], "table_ids": list(a["table_ids"]), "changed": a["changed"]} for a in assignments]
