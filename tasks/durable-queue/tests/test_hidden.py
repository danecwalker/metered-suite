"""Held-out verifier. Not copied into the agent workspace."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from durableq import Queue


class HiddenQueueTests(unittest.TestCase):
    def test_visibility_timeout_restores_and_counts_attempt(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0], max_attempts=3)
        q.enqueue("job")
        first = q.lease(50)
        self.assertIsNotNone(first)
        self.assertEqual(q.ready_count(), 0)
        self.assertEqual(q.leased_count(), 1)
        t[0] = 51
        second = q.lease(50)
        self.assertIsNotNone(second)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.attempts, 1)

    def test_nack_then_poison(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0], max_attempts=2)
        q.enqueue("poison")
        a = q.lease(100)
        q.nack(a.id, a.lease_id)
        b = q.lease(100)
        self.assertEqual(b.attempts, 1)
        q.nack(b.id, b.lease_id)
        self.assertIsNone(q.lease(100))
        self.assertEqual(q.dead_count(), 1)
        self.assertEqual(q.ready_count(), 0)

    def test_persist_across_processes(self) -> None:
        t = [0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.json"
            q1 = Queue(path, clock=lambda: t[0], max_attempts=3)
            mid = q1.enqueue("keep")
            leased = q1.lease(80)
            self.assertEqual(leased.id, mid)
            q2 = Queue(path, clock=lambda: t[0], max_attempts=3)
            self.assertEqual(q2.leased_count(), 1)
            q2.ack(leased.id, leased.lease_id)
            q3 = Queue(path, clock=lambda: t[0], max_attempts=3)
            self.assertIsNone(q3.lease(10))
            self.assertEqual(q3.ready_count(), 0)

    def test_delay_does_not_steal_older_ready(self) -> None:
        t = [0]
        q = Queue(clock=lambda: t[0])
        older = q.enqueue("old")
        q.enqueue("new", delay_ms=100)
        got = q.lease(10)
        self.assertEqual(got.id, older)
        t[0] = 120
        got2 = q.lease(10)
        self.assertEqual(got2.body, "new")


if __name__ == "__main__":
    unittest.main()
