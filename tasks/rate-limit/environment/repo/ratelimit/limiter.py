"""Broken starter. Public and hidden tests describe the contract."""

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

    def allow(self, key: str, *, limit: int, window_ms: int) -> bool:
        now = int(time.time() * 1000)
        hits = self._hits.setdefault(key, [])
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def remaining(self, key: str, *, limit: int, window_ms: int) -> int:
        return limit

    def token_bucket(
        self,
        key: str,
        *,
        rate_per_sec: float,
        burst: int,
        cost: int = 1,
    ) -> bool:
        tokens, _last = self._buckets.get(key, (float(burst), 0))
        if tokens <= 0:
            return False
        self._buckets[key] = (tokens - 1, 0)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._hits = {key: list(value) for key, value in raw.items()}

    def _save(self) -> None:
        if not self.path:
            return
        self.path.write_text(json.dumps(self._hits), encoding="utf-8")
