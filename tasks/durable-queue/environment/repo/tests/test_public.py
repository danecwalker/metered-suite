import tempfile
import unittest
from pathlib import Path

from durableq import Queue


class PublicQueueTests(unittest.TestCase):
    def test_lease_is_oldest_ready(self) -> None:
        t = [1000]
        q = Queue(clock=lambda: t[0])
        first = q.enqueue("a")
        t[0] = 1001
        second = q.enqueue("b")
        got = q.lease(100)
        self.assertIsNotNone(got)
        self.assertEqual(got.id, first)
        self.assertEqual(got.body, "a")
        self.assertNotEqual(got.id, second)

    def test_ack_requires_lease_id(self) -> None:
        t = [1000]
        q = Queue(clock=lambda: t[0])
        q.enqueue("a")
        msg = q.lease(100)
        q.ack(msg.id, "wrong-lease")
        self.assertEqual(q.leased_count(), 1)
        self.assertIsNone(q.lease(10))
        t[0] = 1101
        again = q.lease(10)
        self.assertIsNotNone(again)
        self.assertEqual(again.id, msg.id)

    def test_delay_then_lease(self) -> None:
        t = [1000]
        q = Queue(clock=lambda: t[0])
        q.enqueue("later", delay_ms=50)
        self.assertIsNone(q.lease(10))
        t[0] = 1060
        got = q.lease(10)
        self.assertIsNotNone(got)
        self.assertEqual(got.body, "later")

    def test_visibility_expires_and_counts_attempt(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0], max_attempts=5)
        q.enqueue("job")
        first = q.lease(20)
        self.assertIsNotNone(first)
        self.assertEqual(q.ready_count(), 0)
        self.assertEqual(q.leased_count(), 1)
        t[0] = 21
        second = q.lease(20)
        self.assertIsNotNone(second)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.attempts, 1)

    def test_nack_increments_attempts(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0], max_attempts=5)
        q.enqueue("job")
        msg = q.lease(100)
        q.nack(msg.id, msg.lease_id)
        again = q.lease(100)
        self.assertIsNotNone(again)
        self.assertEqual(again.id, msg.id)
        self.assertEqual(again.attempts, 1)

    def test_dead_after_max_attempts(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0], max_attempts=3)
        q.enqueue("poison")
        for _ in range(3):
            msg = q.lease(10)
            self.assertIsNotNone(msg)
            q.nack(msg.id, msg.lease_id)
        self.assertIsNone(q.lease(10))
        self.assertEqual(q.dead_count(), 1)
        self.assertEqual(q.ready_count(), 0)

    def test_persist_leased_message(self) -> None:
        t = [0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.json"
            q1 = Queue(path, clock=lambda: t[0], max_attempts=5)
            mid = q1.enqueue("keep")
            leased = q1.lease(40)
            self.assertEqual(leased.id, mid)
            q2 = Queue(path, clock=lambda: t[0], max_attempts=5)
            self.assertEqual(q2.leased_count(), 1)
            q2.ack(leased.id, leased.lease_id)
            q3 = Queue(path, clock=lambda: t[0], max_attempts=5)
            self.assertIsNone(q3.lease(10))
            self.assertEqual(q3.ready_count(), 0)


if __name__ == "__main__":
    unittest.main()
