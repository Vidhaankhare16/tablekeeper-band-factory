import json
import threading
import unittest

from app.errors import ApiError
from app.service import Service

FIXTURE = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
              {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob"}],
    "restaurants": [
        {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
         "opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:30"} for d in
                           ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
         "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]},
        {"id": "r_ny", "name": "NY", "timezone": "America/New_York", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
         "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "05:00"},
                           {"weekday": "sun", "opens": "18:00", "closes": "23:00"}],
         "tables": [{"id": "n_1", "label": "1", "capacity": 4}]}],
    "reservations": [],
}
NOW = 1_700_000_000  # 2023-11-14, long before every booking below


def body(**kw):
    return json.dumps(kw).encode()


def book(table="t_2", at="2030-01-10T19:00", party=4, restaurant="r_anker"):
    return body(restaurant_id=restaurant, table_id=table, starts_at_local=at, party_size=party)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.svc = Service(clock=lambda: NOW)
        self.svc.reset(json.dumps(FIXTURE).encode())
        self.token = self.svc.login(body(email="ada@example.com", password="correct horse"))[1]["token"]
        self.auth = f"Bearer {self.token}"
        self.n = 0

    def create(self, raw, key=None):
        self.n += 1
        return self.svc.create_reservation(self.auth, key or f"k{self.n}", raw)

    def code(self, call):
        with self.assertRaises(ApiError) as caught:
            call()
        return caught.exception.code

    def test_half_open_interval(self):
        self.create(book(at="2030-01-10T19:00"))
        self.assertEqual(self.create(book(at="2030-01-10T20:30"))[0], 201)
        self.assertEqual(self.code(lambda: self.create(book(at="2030-01-10T20:00"))), "table_unavailable")

    def test_concurrent_identical_requests_yield_one_booking(self):
        results = []
        def go():
            results.append(self.svc.create_reservation(self.auth, "same", book())[0])
        threads = [threading.Thread(target=go) for _ in range(30)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [200] * 29 + [201])
        self.assertEqual(len(self.svc.list_reservations(self.auth)[1]["reservations"]), 1)

    def test_concurrent_distinct_keys_never_double_book(self):
        outcomes = []
        def go(i):
            try:
                outcomes.append(self.svc.create_reservation(self.auth, f"k{i}", book())[0])
            except ApiError as error:
                outcomes.append(error.status)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(outcomes), [201] + [409] * 29)

    def test_idempotency_rules(self):
        first = self.create(book(), key="a")
        self.assertEqual(self.create(book(), key="a"), (200, first[1]))
        self.assertEqual(self.code(lambda: self.create(book(at="2030-01-10T22:00"), key="a")), "idempotency_key_reuse")
        self.assertEqual(self.code(lambda: self.svc.create_reservation(self.auth, "", b"{}")), "missing_idempotency_key")
        self.assertEqual(self.code(lambda: self.create(book(party=0), key="b")), "validation_failed")
        self.assertEqual(self.create(book(at="2030-01-11T19:00", party=2, table="t_1"), key="b")[0], 201)

    def test_dst(self):
        ny = lambda at: book(table="n_1", at=at, restaurant="r_ny", party=2)
        self.assertEqual(self.code(lambda: self.create(ny("2026-03-08T02:30"))), "invalid_local_time")
        view = self.create(ny("2026-11-01T01:30"))[1]
        self.assertEqual((view["starts_at"], view["ends_at"]), ("2026-11-01T01:30:00-04:00", "2026-11-01T02:00:00-05:00"))
        slots = self.svc.availability({"restaurant_id": "r_ny", "date": "2026-11-01", "party_size": "2"})[1]["slots"]
        locals_ = [s["starts_at_local"] for s in slots]
        self.assertEqual(locals_.count("2026-11-01T01:30"), 1)
        gap = self.svc.availability({"restaurant_id": "r_ny", "date": "2026-03-08", "party_size": "2"})[1]["slots"]
        self.assertNotIn("2026-03-08T02:00", [s["starts_at_local"] for s in gap])

    def test_cancel_frees_table_and_respects_cutoff(self):
        ref = self.create(book())[1]["reference"]
        self.assertEqual(self.svc.cancel(self.auth, ref)[1]["status"], "cancelled")
        self.assertEqual(self.svc.cancel(self.auth, ref)[0], 200)
        self.assertEqual(self.create(book())[0], 201)
        ref = self.create(book(at="2030-01-12T19:00"))[1]["reference"]
        start = 1894471200  # 2030-01-12T19:00+01:00
        self.svc.clock = lambda: start - 120 * 60
        self.assertEqual(self.code(lambda: self.svc.cancel(self.auth, ref)), "cutoff_passed")
        self.assertEqual(self.code(lambda: self.svc.amend(self.auth, ref, body(party_size=2))), "cutoff_passed")
        self.svc.clock = lambda: start - 121 * 60
        self.assertEqual(self.svc.cancel(self.auth, ref)[1]["status"], "cancelled")

    def test_amend_failure_changes_nothing(self):
        a = self.create(book(at="2030-01-10T19:00"))[1]
        self.create(book(at="2030-01-10T22:00"))
        patch = lambda **kw: self.svc.amend(self.auth, a["reference"], body(**kw))
        self.assertEqual(self.code(lambda: patch(starts_at_local="2030-01-10T21:30")), "table_unavailable")
        self.assertEqual(self.code(lambda: patch(starts_at_local="2030-01-10T19:10")), "not_on_slot_grid")
        self.assertEqual(self.code(lambda: patch(table_id="t_1")), "party_exceeds_capacity")
        self.assertEqual(self.svc.get_reservation(self.auth, a["reference"])[1], a)
        moved = patch(starts_at_local="2030-01-10T17:00")[1]
        self.assertEqual((moved["reference"], moved["reservation_id"]), (a["reference"], a["reservation_id"]))

    def test_moves_swap_and_rollback(self):
        a = self.create(book(table="t_1", party=2))[1]
        b = self.create(book(table="t_2", party=2))[1]
        swap = body(moves=[{"reference": a["reference"], "table_id": "t_2"},
                           {"reference": b["reference"], "table_id": "t_1"}])
        status, result = self.svc.moves(self.auth, "m1", swap)
        self.assertEqual((status, [r["table_id"] for r in result["reservations"]]), (201, ["t_2", "t_1"]))
        self.assertEqual(self.svc.moves(self.auth, "m1", swap), (200, result))
        bad = body(moves=[{"reference": a["reference"], "starts_at_local": "2030-01-10T17:00"},
                          {"reference": b["reference"], "party_size": 3}])
        self.assertEqual(self.code(lambda: self.svc.moves(self.auth, "m2", bad)), "party_exceeds_capacity")
        self.assertEqual(self.svc.get_reservation(self.auth, a["reference"])[1]["starts_at_local"], "2030-01-10T19:00")
        clash = body(moves=[{"reference": a["reference"], "table_id": "t_1"}])
        self.assertEqual(self.code(lambda: self.svc.moves(self.auth, "m3", clash)), "table_unavailable")

    def test_other_users_reservations_are_invisible(self):
        ref = self.create(book())[1]["reference"]
        bob = "Bearer " + self.svc.login(body(email="bob@example.com", password="correct horse"))[1]["token"]
        self.assertEqual(self.code(lambda: self.svc.get_reservation(bob, ref)), "not_found")
        self.assertEqual(self.code(lambda: self.svc.cancel(bob, ref)), "not_found")

    def test_export_import_keeps_tokens_receipts_and_bookings(self):
        first = self.create(book(), key="keep")
        exported = self.svc.export_state()[1]
        self.svc.reset(b"{}")
        self.assertEqual(self.code(lambda: self.svc.list_reservations(self.auth)), "unauthenticated")
        self.svc.import_state(json.dumps(exported).encode())
        self.assertEqual(self.create(book(), key="keep"), (200, first[1]))
        self.assertEqual(self.svc.login(body(email="ada@example.com", password="correct horse"))[0], 200)
        broken = dict(exported, format_version=2)
        self.assertEqual(self.code(lambda: self.svc.import_state(json.dumps(broken).encode())), "validation_failed")


if __name__ == "__main__":
    unittest.main()
