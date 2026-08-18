import tempfile
import unittest
from pathlib import Path

from ratelimit import Limiter


class PublicLimiterTests(unittest.TestCase):
    def test_sliding_window_allows_then_blocks(self) -> None:
        t = [1000]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("a", limit=2, window_ms=100))
        self.assertTrue(lim.allow("a", limit=2, window_ms=100))
        self.assertFalse(lim.allow("a", limit=2, window_ms=100))
        self.assertEqual(lim.remaining("a", limit=2, window_ms=100), 0)

    def test_sliding_window_expires_old_hits(self) -> None:
        t = [1000]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("a", limit=1, window_ms=50))
        self.assertFalse(lim.allow("a", limit=1, window_ms=50))
        t[0] = 1051
        self.assertTrue(lim.allow("a", limit=1, window_ms=50))

    def test_keys_are_independent(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("a", limit=1, window_ms=100))
        self.assertTrue(lim.allow("b", limit=1, window_ms=100))
        self.assertFalse(lim.allow("a", limit=1, window_ms=100))

    def test_token_bucket_burst_then_refill(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.token_bucket("ip", rate_per_sec=1.0, burst=2))
        self.assertTrue(lim.token_bucket("ip", rate_per_sec=1.0, burst=2))
        self.assertFalse(lim.token_bucket("ip", rate_per_sec=1.0, burst=2))
        t[0] = 1000
        self.assertTrue(lim.token_bucket("ip", rate_per_sec=1.0, burst=2))

    def test_reset_clears_window(self) -> None:
        t = [0]
        lim = Limiter(clock=lambda: t[0])
        self.assertTrue(lim.allow("a", limit=1, window_ms=1000))
        lim.reset("a")
        self.assertTrue(lim.allow("a", limit=1, window_ms=1000))

    def test_persist_window_hits(self) -> None:
        t = [0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lim.json"
            first = Limiter(path, clock=lambda: t[0])
            self.assertTrue(first.allow("user", limit=1, window_ms=500))
            second = Limiter(path, clock=lambda: t[0])
            self.assertFalse(second.allow("user", limit=1, window_ms=500))


if __name__ == "__main__":
    unittest.main()
