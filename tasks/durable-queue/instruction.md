You are in a checkout of `durableq`, a small durable work queue.

The public unit tests fail. Fix the library so this exits 0:

```
python3 -m unittest discover -s tests -v
```

Do not edit files under `tests/`. After you exit, a hidden verifier runs in a fresh container on a git patch of your work. Hardcoding the public fixtures will fail.

Required behavior:

- `Queue.enqueue(body, delay_ms=0)` returns a message id and stores the body. `delay_ms` keeps the message unleaseable until that many milliseconds have passed.
- `Queue.lease(visibility_ms)` returns the oldest ready message (`available_at`, then `id`) whose `available_at <= now`, or `None`. The message stays invisible until `now + visibility_ms`. If that window ends without `ack`, the message becomes ready again and `attempts` increases by 1.
- `Queue.ack(id, lease_id)` deletes the message only when `lease_id` matches the active lease.
- `Queue.nack(id, lease_id)` returns the message to ready immediately and increases `attempts` by 1, only when `lease_id` matches.
- After `max_attempts` failed attempts (visibility expiry or nack), the message is dead: `lease` must not return it. `dead_count()` reports how many are dead.
- `ready_count()` is messages that can be leased now. `leased_count()` is currently invisible messages.
- If the queue was constructed with a `path`, state must survive a new `Queue(path=...)` process.
- Time comes from the optional `clock` callable (milliseconds). Tests inject it. Do not call `time.time` if `clock` was provided.

Public tests cover a subset of this. The hidden verifier covers the rest.
