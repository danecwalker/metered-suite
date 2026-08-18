import unittest

from durableq import Queue


class PublicQueueTests(unittest.TestCase):
    def test_lease_is_oldest_ready(self) -> None:
        t = [1000]
        q = Queue(clock=lambda: t[0])
        first = q.enqueue("a")
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
        again = q.lease(100)
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


if __name__ == "__main__":
    unittest.main()
