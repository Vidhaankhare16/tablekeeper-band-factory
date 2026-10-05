import json
import unittest

from app.errors import ApiError
from app.service import Service

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HOURS = [{"weekday": d, "opens": "12:00", "closes": "23:00"} for d in DAYS]
FIXTURE = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse"},
              {"id": "u_bob", "email": "bob@example.com", "password": "correct horse"}],
    "restaurants": [{
        "id": "r", "name": "R", "timezone": "Europe/Berlin", "slot_minutes": 30,
        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
        "opening_hours": HOURS, "manager_user_ids": ["u_ada"],
        "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
                   {"id": "t_3", "label": "3", "capacity": 4}],
        "combinable": [["t_1", "t_2"]]}],
}
NOW = 1_700_000_000
POLICY = {"effective_from": "2030-02-01", "slot_minutes": 60, "reservation_duration_minutes": 120,
          "cancellation_cutoff_minutes": 30, "opening_hours": HOURS,
          "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def body(**kw):
    return json.dumps(kw).encode()


class Stage3Test(unittest.TestCase):
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

    def book(self, at="2030-01-10T19:00", tables=("t_2",), party=2, auth=None):
        return self.svc.create_reservation(auth or self.ada, self.key(), body(
            restaurant_id="r", table_ids=list(tables), starts_at_local=at, party_size=party))[1]

    def patch(self, ref, auth=None, **kw):
        return self.svc.amend(auth or self.ada, ref, body(**kw))[1]

    def publish(self, auth=None, **overrides):
        return self.svc.publish_policy(auth or self.ada, "r", self.key(), body(**{**POLICY, **overrides}))

    def code(self, call):
        with self.assertRaises(ApiError) as caught:
            call()
        return caught.exception.code

    def test_explain_reports_every_table_and_rule(self):
        self.book(tables=("t_2",), party=2)
        query = {"restaurant_id": "r", "date": "2030-01-10", "party_size": "3", "explain": "true"}
        slot = next(s for s in self.svc.availability(query)[1]["slots"] if s["starts_at_local"].endswith("19:00"))
        self.assertEqual([e["table_id"] for e in slot["explain"]], ["t_1", "t_2", "t_3"])
        self.assertEqual([[r["holds"] for r in e["rules"]] for e in slot["explain"]],
                         [[False, True], [True, False], [True, True]])
        self.assertEqual([e["table_id"] for e in slot["explain"] if e["available"]], slot["available_table_ids"])
        plain = self.svc.availability({k: v for k, v in query.items() if k != "explain"})[1]["slots"][0]
        self.assertNotIn("explain", plain)
        for bad in ("false", "1", ""):
            self.assertEqual(self.code(lambda: self.svc.availability({**query, "explain": bad})), "validation_failed")

    def test_history_records_only_real_changes(self):
        ref = self.book()["reference"]
        self.patch(ref, party_size=2)  # no-op
        self.patch(ref, table_id="t_3", party_size=3)
        self.patch(ref, table_ids=["t_1", "t_2"], party_size=2)
        self.patch(ref, table_ids=["t_2", "t_1"])  # same set, no-op
        self.svc.cancel(self.ada, ref)
        entries = self.svc.get_history(self.ada, ref)[1]["entries"]
        self.assertEqual([e["seq"] for e in entries], [1, 2, 3, 4])
        self.assertEqual([e["event"] for e in entries], ["created", "changed", "changed", "cancelled"])
        self.assertEqual(entries[0]["changes"][0], {"field": "table_id", "from": None, "to": "t_2"})
        self.assertEqual([c["field"] for c in entries[1]["changes"]], ["table_id", "party_size"])
        self.assertEqual(entries[2]["changes"][0], {"field": "table_ids", "from": ["t_3"], "to": ["t_1", "t_2"]})
        self.assertEqual([e["revision"] for e in entries], [1, 2, 3, 4])
        self.assertEqual(self.svc.get_decision(self.ada, ref)[1]["revision"], 4)

    def test_history_and_decision_hide_other_users_and_anonymous(self):
        ref = self.book()["reference"]
        for read in (self.svc.get_history, self.svc.get_decision):
            for auth in (self.bob, None, "Bearer nope"):
                self.assertEqual(self.code(lambda: read(auth, ref)), "not_found")

    def test_policy_publication_rules(self):
        self.assertEqual(self.code(lambda: self.publish(auth=self.bob)), "forbidden")
        self.assertEqual(self.code(lambda: self.publish(auth="Bearer x")), "unauthenticated")
        self.assertEqual(self.code(lambda: self.publish(capacities={"t_1": 2})), "validation_failed")
        self.assertEqual(self.code(lambda: self.publish(slot_minutes=True)), "validation_failed")
        status, first = self.svc.publish_policy(self.ada, "r", "same", body(**POLICY))
        self.assertEqual((status, first["policy_version"]), (201, 1))
        self.assertEqual(self.svc.publish_policy(self.ada, "r", "same", body(**POLICY)), (200, first))
        self.assertEqual(self.publish()[1]["policy_version"], 2)
        self.assertEqual(len(self.svc.list_policies("r")[1]["policies"]), 2)

    def test_booking_uses_the_policy_of_its_start_date(self):
        self.publish()
        old = self.book(at="2030-01-31T19:00")
        new = self.book(at="2030-02-01T19:00", party=6, tables=("t_3",))
        self.assertEqual((old["accepted_terms"]["policy_version"], new["accepted_terms"]["policy_version"]), (0, 1))
        self.assertTrue(new["ends_at"].startswith("2030-02-01T21:00"))
        self.assertEqual(self.code(lambda: self.book(at="2030-02-02T19:30")), "not_on_slot_grid")
        slots = self.svc.availability({"restaurant_id": "r", "date": "2030-02-01", "party_size": "6",
                                       "explain": "true"})[1]["slots"]
        self.assertEqual(slots[0]["explain"][2]["policy_version"], 1)
        self.assertTrue(all(s["starts_at_local"][-2:] == "00" for s in slots))

    def test_amendment_order_and_terms_swap(self):
        ref = self.book(at="2030-01-31T19:00")["reference"]
        self.publish()
        self.assertEqual(self.code(lambda: self.patch(ref, expected_revision=2, party_size=3)), "stale_revision")
        self.assertEqual(self.code(lambda: self.patch(ref, expected_revision=0)), "validation_failed")
        self.assertEqual(self.code(lambda: self.patch(ref, starts_at_local="2030-02-01T19:30")), "not_on_slot_grid")
        moved = self.patch(ref, expected_revision=1, starts_at_local="2030-02-01T19:00")
        self.assertEqual((moved["revision"], moved["accepted_terms"]["policy_version"]), (2, 1))
        self.assertTrue(moved["ends_at"].startswith("2030-02-01T21:00"))
        self.assertEqual(self.patch(ref, starts_at_local="2030-02-01T19:00")["revision"], 2)
        self.svc.clock = lambda: moved_start(moved) - 20 * 60
        self.assertEqual(self.code(lambda: self.svc.cancel(self.ada, ref)), "cutoff_passed")

    def test_series_adoption_and_exceptions(self):
        anchor = self.book(at="2030-01-10T19:00")
        key = self.key()
        request = body(anchor_reference=anchor["reference"], count=3, interval_weeks=2)
        status, series = self.svc.create_series(self.ada, key, request)
        self.assertEqual((status, [o["reservation"]["starts_at_local"] for o in series["occurrences"]]),
                         (201, ["2030-01-10T19:00", "2030-01-24T19:00", "2030-02-07T19:00"]))
        self.assertEqual(series["occurrences"][0]["reservation"], anchor)
        self.assertEqual(self.svc.create_series(self.ada, key, request), (200, series))
        self.assertEqual(self.code(lambda: self.svc.create_series(self.ada, self.key(), request)), "already_in_series")
        second = series["occurrences"][1]["reference"]
        self.patch(second, party_size=3)
        self.svc.cancel(self.ada, series["occurrences"][2]["reference"])
        current = self.svc.get_series(self.ada, series["series_id"])[1]
        self.assertEqual((current["revision"], [o["exception"] for o in current["occurrences"]]),
                         (3, [False, True, False]))
        self.assertEqual(self.code(lambda: self.svc.get_series(self.bob, series["series_id"])), "not_found")
        self.assertEqual(len(self.svc.list_reservations(self.ada)[1]["reservations"]), 3)

    def test_failed_adoption_leaves_nothing_behind(self):
        anchor = self.book(at="2030-01-10T19:00")
        self.book(at="2030-01-24T19:00", auth=self.bob)  # blocks occurrence 2 of 3
        request = body(anchor_reference=anchor["reference"], count=3, interval_weeks=2)
        self.assertEqual(self.code(lambda: self.svc.create_series(self.ada, "x", request)), "table_unavailable")
        self.assertEqual(len(self.svc.list_reservations(self.ada)[1]["reservations"]), 1)
        self.assertEqual(self.svc.get_history(self.ada, anchor["reference"])[1]["entries"][0]["seq"], 1)
        for bad in (dict(count=1), dict(count=True), dict(interval_weeks=5)):
            payload = {"anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1, **bad}
            self.assertEqual(self.code(lambda: self.svc.create_series(self.ada, self.key(), body(**payload))),
                             "validation_failed")

    def test_moves_use_individual_amendment_semantics(self):
        a, b = self.book(tables=("t_2",)), self.book(tables=("t_3",))
        batch = body(moves=[{"reference": a["reference"], "table_id": "t_3", "expected_revision": 1},
                            {"reference": b["reference"], "table_id": "t_2"}])
        status, result = self.svc.moves(self.ada, "m", batch)
        self.assertEqual((status, [r["revision"] for r in result["reservations"]]), (201, [2, 2]))
        stale = body(moves=[{"reference": a["reference"], "party_size": 3, "expected_revision": 1}])
        self.assertEqual(self.code(lambda: self.svc.moves(self.ada, "m2", stale)), "stale_revision")
        noop = body(moves=[{"reference": a["reference"]}])
        self.assertEqual(self.svc.moves(self.ada, "m3", noop)[1]["reservations"][0]["revision"], 2)

    def test_stage_2_state_is_upgraded_on_import(self):
        record = self.book()
        state = self.svc.export_state()[1]
        for reservation in state["state"]["reservations"]:
            for key in ("revision", "terms", "history", "series_id", "series_index"):
                del reservation[key]
        for restaurant in state["state"]["restaurants"]:
            for key in ("manager_user_ids", "policies", "revision"):
                del restaurant[key]
        del state["state"]["series"], state["state"]["next_series"]
        self.svc.import_state(json.dumps(state).encode())
        view = self.svc.get_reservation(self.ada, record["reference"])[1]
        self.assertEqual((view["revision"], view["accepted_terms"]["policy_version"]), (1, 0))
        entries = self.svc.get_history(self.ada, record["reference"])[1]["entries"]
        self.assertEqual([e["event"] for e in entries], ["created"])


def moved_start(view):
    from datetime import datetime
    return int(datetime.fromisoformat(view["starts_at"]).timestamp())


if __name__ == "__main__":
    unittest.main()
