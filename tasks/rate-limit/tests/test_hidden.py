"""Held-out verifier. Not copied into the agent workspace."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ratelimit import Limiter


class HiddenLimiterTests(unittest.TestCase):
    def test_window_edge_is_exclusive(self) -> None:
        t = [200]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("k", limit=1, window_ms=40))
        t[0] = 239
        self.assertFalse(lim.allow("k", limit=1, window_ms=40))
        t[0] = 240
        self.assertTrue(lim.allow("k", limit=1, window_ms=40))

    def test_remaining_does_not_record(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertEqual(lim.remaining("k", limit=3, window_ms=80), 3)
        self.assertTrue(lim.allow("k", limit=3, window_ms=80))
        self.assertEqual(lim.remaining("k", limit=3, window_ms=80), 2)
        self.assertEqual(lim.remaining("k", limit=3, window_ms=80), 2)

    def test_token_bucket_cost_and_cap(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.token_bucket("k", rate_per_sec=2.0, burst=5, cost=4))
        self.assertFalse(lim.token_bucket("k", rate_per_sec=2.0, burst=5, cost=4))
        t[0] = 500
        self.assertFalse(lim.token_bucket("k", rate_per_sec=2.0, burst=5, cost=4))
        t[0] = 1500
        self.assertTrue(lim.token_bucket("k", rate_per_sec=2.0, burst=5, cost=4))

    def test_window_and_bucket_do_not_share_state(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("same", limit=1, window_ms=1000))
        self.assertTrue(lim.token_bucket("same", rate_per_sec=1.0, burst=1))
        self.assertFalse(lim.allow("same", limit=1, window_ms=1000))
        self.assertFalse(lim.token_bucket("same", rate_per_sec=1.0, burst=1))

    def test_reset_clears_bucket_only_for_that_key(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.token_bucket("a", rate_per_sec=1.0, burst=1))
        self.assertTrue(lim.token_bucket("b", rate_per_sec=1.0, burst=1))
        lim.reset("a")
        self.assertTrue(lim.token_bucket("a", rate_per_sec=1.0, burst=1))
        self.assertFalse(lim.token_bucket("b", rate_per_sec=1.0, burst=1))

    def test_persist_bucket_across_processes(self) -> None:
        t = [0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lim.json"
            first = Limiter(path, clock=lambda: t[0])
            self.assertTrue(first.token_bucket("ip", rate_per_sec=1.0, burst=1))
            second = Limiter(path, clock=lambda: t[0])
            self.assertFalse(second.token_bucket("ip", rate_per_sec=1.0, burst=1))
            t[0] = 1000
            third = Limiter(path, clock=lambda: t[0])
            self.assertTrue(third.token_bucket("ip", rate_per_sec=1.0, burst=1))


if __name__ == "__main__":
    unittest.main()
