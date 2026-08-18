You are in a checkout of `ratelimit`, a small in-process rate limiter.

The public unit tests fail. Fix the library so this exits 0:

```
python3 -m unittest discover -s tests -v
```

Do not edit files under `tests/`. After you exit, a hidden verifier runs in a fresh container on a git patch of your work. Hardcoding the public fixtures will fail.

Required behavior:

- `Limiter(path=None, clock=None)` stores state in memory. If `path` is set, state must survive a new `Limiter(path=...)` process.
- Time comes from the optional `clock` callable (milliseconds). Tests inject it. Do not call `time.time` if `clock` was provided.
- `allow(key, limit, window_ms)` is a sliding window. It returns True and records a hit when this key has fewer than `limit` hits with timestamp in `(now - window_ms, now]`. Otherwise it returns False and records nothing.
- Hits exactly `window_ms` old are outside the window and do not count.
- `remaining(key, limit, window_ms)` is how many more `allow` calls would succeed now. It does not record a hit.
- `token_bucket(key, rate_per_sec, burst, cost=1)` is a token bucket. The bucket starts full at `burst`. It refills at `rate_per_sec` tokens per second, capped at `burst`. A call costs `cost` tokens. Return True and spend if the bucket has at least `cost`, else return False and do not spend.
- Sliding-window state and token-bucket state for the same key are independent.
- `reset(key)` clears both kinds of state for that key only.

Run `python3 -m unittest discover -s tests -v` until those public tests pass. A hidden verifier then grades a git patch in a fresh container. Hidden cases use different numbers and timings. Hardcoding the public fixtures will fail.
