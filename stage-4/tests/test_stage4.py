import json
import unittest

from app.errors import ApiError
from app.service import Service

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FIXTURE = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse"},
              {"id": "u_bob", "email": "bob@example.com", "password": "correct horse"}],
    "restaurants": [{
        "id": "r", "name": "R", "timezone": "Europe/Berlin", "slot_minutes": 30,
        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": d, "opens": "12:00", "closes": "23:00"} for d in DAYS],
        "manager_user_ids": ["u_ada"],
        "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
                   {"id": "t_3", "label": "3", "capacity": 4}],
        "combinable": [["t_1", "t_2"]]},
        {"id": "other", "name": "O", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "12:00", "closes": "23:00"} for d in DAYS],
         "manager_user_ids": ["u_ada"], "tables": [{"id": "o_1", "label": "1", "capacity": 4}]}],
}
NOW = 1_700_000_000
CLOSURE = {"table_id": "t_2", "from": "2030-01-10T19:00:00+01:00", "to": "2030-01-10T20:00:00+01:00"}


def body(**kw):
    return json.dumps(kw).encode()


class Stage4Test(unittest.TestCase):
    def setUp(self):
        self.svc = Service(clock=lambda: NOW)
        self.svc.reset(json.dumps(FIXTURE).encode())
        self.ada = self.login("ada")
        self.bob = self.login("bob")
        self.n = 0

    def login(self, name):
        return "Bearer " + self.svc.login(body(email=f"{name}@example.com", password="correct horse"))[1]["token"]

    def key(self):
        self.n += 1
        return f"k{self.n}"

    def book(self, table, party, at="2030-01-10T19:00", auth=None):
        return self.svc.create_reservation(auth or self.ada, self.key(), body(
            restaurant_id="r", table_id=table, starts_at_local=at, party_size=party))[1]

    def preview(self, **overrides):
        return self.svc.preview_replan(self.ada, "r", self.key(), body(**{**CLOSURE, **overrides}))

    def apply(self, plan_id, key=None):
        return self.svc.apply_replan(self.ada, "r", plan_id, key or self.key(), b"{}")

    def revision(self):
        return self.svc.state.restaurants["r"]["revision"]

    def code(self, call):
        with self.assertRaises(ApiError) as caught:
            call()
        return caught.exception.code

    def test_preview_is_optimal_and_changes_nothing(self):
        a = self.book("t_2", 4)
        b = self.book("t_3", 2)
        before = self.revision()
        status, plan = self.preview()
        self.assertEqual(status, 201)
        self.assertEqual(plan["restaurant_revision"], before)
        by_ref = {x["reference"]: x for x in plan["assignments"]}
        self.assertEqual(by_ref[a["reference"]]["table_ids"], ["t_3"])
        self.assertEqual(by_ref[b["reference"]]["table_ids"], ["t_1"])
        self.assertEqual((plan["moved_count"], plan["unused_seats"]), (2, 0))
        self.assertEqual([x["reference"] for x in plan["assignments"]], sorted(by_ref))
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.svc.get_reservation(self.ada, a["reference"])[1], a)

    def test_apply_moves_bookings_and_records_the_closure(self):
        a = self.book("t_2", 4)
        plan = self.preview()[1]
        status, applied = self.apply(plan["plan_id"], "apply-key")
        self.assertEqual((status, applied["restaurant_revision"]), (201, plan["restaurant_revision"] + 1))
        moved = applied["reservations"][0]
        self.assertEqual((moved["table_ids"], moved["revision"], moved["starts_at"], moved["accepted_terms"]),
                         (["t_3"], 2, a["starts_at"], a["accepted_terms"]))
        entry = self.svc.get_history(self.ada, a["reference"])[1]["entries"][-1]
        self.assertEqual((entry["event"], entry["plan_id"], entry["changes"]),
                         ("reassigned", plan["plan_id"], [{"field": "table_ids", "from": ["t_2"], "to": ["t_3"]}]))
        self.assertEqual(self.svc.apply_replan(self.ada, "r", plan["plan_id"], "apply-key", b"{}"), (200, applied))
        self.assertEqual(self.code(lambda: self.apply(plan["plan_id"])), "plan_already_applied")
        self.assertEqual(self.code(lambda: self.book("t_2", 2, at="2030-01-10T19:30")), "table_unavailable")
        slot = next(s for s in self.svc.availability({"restaurant_id": "r", "date": "2030-01-10",
                                                      "party_size": "2", "explain": "true"})[1]["slots"]
                    if s["starts_at_local"].endswith("19:00"))
        self.assertNotIn("t_2", slot["available_table_ids"])
        self.assertEqual([o["table_ids"] for o in slot["available_options"]], [["t_1"]])
        self.assertEqual(slot["explain"][1]["rules"][1], {"rule": "no_overlap", "holds": False})

    def test_stale_foreign_and_permission_rules(self):
        self.book("t_2", 4)
        plan = self.preview()[1]
        self.book("t_1", 2, at="2030-01-11T19:00")  # intervening revision
        self.assertEqual(self.code(lambda: self.apply(plan["plan_id"])), "stale_plan")
        other = self.svc.preview_replan(self.ada, "other", self.key(), body(
            table_id="o_1", **{"from": CLOSURE["from"], "to": CLOSURE["to"]}))[1]
        self.assertEqual(self.code(lambda: self.apply(other["plan_id"])), "not_found")
        self.assertEqual(self.code(lambda: self.svc.preview_replan(self.bob, "r", "x", body(**CLOSURE))), "forbidden")
        self.assertEqual(self.code(lambda: self.preview(table_id="nope")), "not_found")
        self.assertEqual(self.code(lambda: self.preview(to=CLOSURE["from"])), "validation_failed")
        self.assertEqual(self.code(lambda: self.preview(**{"from": "2030-01-10T19:00:00"})), "validation_failed")

    def test_no_feasible_plan_and_planning_limit(self):
        self.book("t_2", 4)
        self.book("t_3", 4)
        self.assertEqual(self.code(lambda: self.preview()), "no_feasible_plan")
        self.assertEqual(self.revision(), 2)

    def test_planning_limit(self):
        tables = [{"id": f"x{i}", "label": str(i), "capacity": 4} for i in range(7)]
        fixture = json.loads(json.dumps(FIXTURE))
        fixture["restaurants"][0]["tables"] = tables
        fixture["restaurants"][0]["combinable"] = []
        self.svc.reset(json.dumps(fixture).encode())
        ada = self.login("ada")
        self.assertEqual(self.code(lambda: self.svc.preview_replan(
            ada, "r", "k", body(**{**CLOSURE, "table_id": "x0"}))), "planning_limit")

    def test_unneeded_bookings_stay_put(self):
        a = self.book("t_3", 4)
        plan = self.preview()[1]
        self.assertEqual((plan["moved_count"], plan["assignments"][0]["changed"], plan["assignments"][0]["table_ids"]),
                         (0, False, ["t_3"]))

    def test_series_amend_changes_clock_time_and_skips_exceptions(self):
        anchor = self.book("t_2", 4)
        series = self.svc.create_series(self.ada, "s", body(anchor_reference=anchor["reference"],
                                                           count=3, interval_weeks=1))[1]
        second = series["occurrences"][1]["reference"]
        self.svc.amend(self.ada, second, body(party_size=3))  # exception
        before = self.revision()
        status, amended = self.svc.amend_series(self.ada, series["series_id"], "a1", body(
            expected_revision=2, from_index=0, local_time="20:00"))
        self.assertEqual(status, 201)
        times = [o["reservation"]["starts_at_local"] for o in amended["occurrences"]]
        self.assertEqual(times, ["2030-01-10T20:00", "2030-01-17T19:00", "2030-01-24T20:00"])
        self.assertEqual((amended["revision"], self.revision()), (3, before + 1))
        self.assertEqual([o["exception"] for o in amended["occurrences"]], [False, True, False])
        self.assertEqual(self.svc.amend_series(self.ada, series["series_id"], "a1", body(
            expected_revision=2, from_index=0, local_time="20:00")), (200, amended))
        self.assertEqual(self.code(lambda: self.svc.amend_series(self.ada, series["series_id"], "a2", body(
            expected_revision=2, from_index=0, local_time="21:00"))), "stale_revision")
        status, same = self.svc.amend_series(self.ada, series["series_id"], "a3", body(
            expected_revision=3, from_index=0, local_time="20:00"))
        self.assertEqual((status, same["revision"], self.revision()), (201, 3, before + 1))
        self.assertEqual(self.code(lambda: self.svc.amend_series(self.bob, series["series_id"], "a4", body(
            expected_revision=3, from_index=0, local_time="20:00"))), "not_found")
        self.assertEqual(self.code(lambda: self.svc.amend_series(self.ada, series["series_id"], "a5", body(
            expected_revision=3, from_index=3, local_time="20:00"))), "validation_failed")

    def test_series_amend_conflict_changes_nothing(self):
        anchor = self.book("t_2", 4)
        series = self.svc.create_series(self.ada, "s", body(anchor_reference=anchor["reference"],
                                                           count=3, interval_weeks=1))[1]
        self.book("t_2", 2, at="2030-01-24T20:30", auth=self.bob)
        revision = self.revision()
        self.assertEqual(self.code(lambda: self.svc.amend_series(self.ada, series["series_id"], "a", body(
            expected_revision=1, from_index=0, local_time="20:00"))), "table_unavailable")
        self.assertEqual(self.revision(), revision)
        current = self.svc.get_series(self.ada, series["series_id"])[1]
        self.assertEqual(current["occurrences"][0]["reservation"]["starts_at_local"], "2030-01-10T19:00")
        self.assertEqual(current["revision"], 1)

    def test_plan_application_preserves_exception_flags_and_bumps_series_once(self):
        anchor = self.book("t_2", 4)
        series = self.svc.create_series(self.ada, "s", body(anchor_reference=anchor["reference"],
                                                           count=2, interval_weeks=1))[1]
        plan = self.preview()[1]
        self.apply(plan["plan_id"])
        current = self.svc.get_series(self.ada, series["series_id"])[1]
        self.assertEqual((current["revision"], [o["exception"] for o in current["occurrences"]]), (2, [False, False]))

    def test_export_import_keeps_plans_closures_and_revision(self):
        self.book("t_2", 4)
        plan = self.preview()[1]
        _, applied = self.apply(plan["plan_id"], "keep")
        exported = self.svc.export_state()[1]
        self.svc.reset(b"{}")
        self.svc.import_state(json.dumps(exported).encode())
        self.assertEqual(self.svc.apply_replan(self.ada, "r", plan["plan_id"], "keep", b"{}"), (200, applied))
        self.assertEqual(self.revision(), applied["restaurant_revision"])
        self.assertEqual(self.code(lambda: self.book("t_2", 2, at="2030-01-10T19:30")), "table_unavailable")

    def test_older_exports_get_series_dates_and_revisions(self):
        anchor = self.book("t_2", 4)
        series = self.svc.create_series(self.ada, "s", body(anchor_reference=anchor["reference"],
                                                           count=2, interval_weeks=2))[1]
        state = self.svc.export_state()[1]
        for item in state["state"]["series"]:
            del item["anchor_date"]
        for restaurant in state["state"]["restaurants"]:
            del restaurant["revision"], restaurant["closures"]
        del state["state"]["plans"], state["state"]["next_plan"]
        self.svc.import_state(json.dumps(state).encode())
        self.assertEqual(self.svc.state.series[series["series_id"]]["anchor_date"], "2030-01-10")
        self.assertEqual(self.revision(), 2)


if __name__ == "__main__":
    unittest.main()
