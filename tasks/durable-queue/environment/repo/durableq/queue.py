"""Broken starter. Public and hidden tests describe the contract."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4


@dataclass
class Message:
    id: str
    body: str
    attempts: int
    lease_id: str | None


class Queue:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], int] | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.path = Path(path) if path else None
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.max_attempts = max_attempts
        self._items: list[dict] = []
        self._load()

    def enqueue(self, body: str, delay_ms: int = 0) -> str:
        now = self.clock()
        item = {
            "id": uuid4().hex,
            "body": body,
            "attempts": 0,
            "available_at": now,
            "lease_id": None,
            "lease_until": 0,
            "dead": False,
        }
        self._items.append(item)
        self._save()
        return item["id"]

    def lease(self, visibility_ms: int) -> Message | None:
        now = self.clock()
        ready = [item for item in self._items if not item["dead"]]
        if not ready:
            return None
        item = ready[-1]
        item["lease_id"] = uuid4().hex
        item["lease_until"] = now + visibility_ms
        self._save()
        return Message(item["id"], item["body"], item["attempts"], item["lease_id"])

    def ack(self, message_id: str, lease_id: str) -> None:
        self._items = [item for item in self._items if item["id"] != message_id]
        self._save()

    def nack(self, message_id: str, lease_id: str) -> None:
        for item in self._items:
            if item["id"] == message_id:
                item["lease_id"] = None
                item["lease_until"] = 0
                item["available_at"] = self.clock()
                self._save()
                return

    def ready_count(self) -> int:
        return len(self._items)

    def leased_count(self) -> int:
        return 0

    def dead_count(self) -> int:
        return 0

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._items = list(raw)

    def _save(self) -> None:
        if not self.path:
            return
        self.path.write_text(json.dumps(self._items), encoding="utf-8")
