"""Reference solution. Held out from the agent. Not used at grade time."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable


class Limiter:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.path = Path(path) if path else None
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._hits: dict[str, list[int]] = {}
        self._buckets: dict[str, tuple[float, int]] = {}
        self._load()

    def _now(self) -> int:
        return int(self.clock())

    def _prune(self, key: str, now: int, window_ms: int) -> list[int]:
        cutoff = now - int(window_ms)
        hits = [stamp for stamp in self._hits.get(key, []) if stamp > cutoff]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def allow(self, key: str, *, limit: int, window_ms: int) -> bool:
        now = self._now()
        hits = self._prune(key, now, window_ms)
        if len(hits) >= int(limit):
            self._save()
            return False
        hits.append(now)
        self._hits[key] = hits
        self._save()
        return True

    def remaining(self, key: str, *, limit: int, window_ms: int) -> int:
        now = self._now()
        hits = self._prune(key, now, window_ms)
        left = max(0, int(limit) - len(hits))
        self._save()
        return left

    def token_bucket(
        self,
        key: str,
        *,
        rate_per_sec: float,
        burst: int,
        cost: int = 1,
    ) -> bool:
        now = self._now()
        cap = float(burst)
        tokens, last = self._buckets.get(key, (cap, now))
        elapsed = max(0, now - last) / 1000.0
        tokens = min(cap, tokens + elapsed * float(rate_per_sec))
        spend = float(cost)
        if tokens < spend:
            self._buckets[key] = (tokens, now)
            self._save()
            return False
        self._buckets[key] = (tokens - spend, now)
        self._save()
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
        self._buckets.pop(key, None)
        self._save()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._hits = {
            key: [int(stamp) for stamp in value]
            for key, value in (raw.get("hits") or {}).items()
        }
        self._buckets = {
            key: (float(item[0]), int(item[1]))
            for key, item in (raw.get("buckets") or {}).items()
        }

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"hits": self._hits, "buckets": self._buckets}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
