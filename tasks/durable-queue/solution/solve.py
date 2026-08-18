"""Reference solution. Held out from the agent. Not used at grade time."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
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
            "available_at": now + max(0, int(delay_ms)),
            "lease_id": None,
            "lease_until": 0,
            "dead": False,
        }
        self._items.append(item)
        self._save()
        return item["id"]

    def _expire(self, now: int) -> None:
        for item in self._items:
            if item["dead"] or not item["lease_id"]:
                continue
            if item["lease_until"] <= now:
                item["lease_id"] = None
                item["lease_until"] = 0
                item["attempts"] += 1
                item["available_at"] = now
                if item["attempts"] >= self.max_attempts:
                    item["dead"] = True

    def lease(self, visibility_ms: int) -> Message | None:
        now = self.clock()
        self._expire(now)
        ready = [
            item
            for item in self._items
            if not item["dead"]
            and not item["lease_id"]
            and item["available_at"] <= now
        ]
        if not ready:
            return None
        ready.sort(key=lambda item: (item["available_at"], item["id"]))
        item = ready[0]
        item["lease_id"] = uuid4().hex
        item["lease_until"] = now + max(1, int(visibility_ms))
        self._save()
        return Message(item["id"], item["body"], item["attempts"], item["lease_id"])

    def ack(self, message_id: str, lease_id: str) -> None:
        now = self.clock()
        self._expire(now)
        kept = []
        for item in self._items:
            if item["id"] == message_id and item["lease_id"] == lease_id:
                continue
            kept.append(item)
        self._items = kept
        self._save()

    def nack(self, message_id: str, lease_id: str) -> None:
        now = self.clock()
        self._expire(now)
        for item in self._items:
            if item["id"] == message_id and item["lease_id"] == lease_id:
                item["lease_id"] = None
                item["lease_until"] = 0
                item["attempts"] += 1
                item["available_at"] = now
                if item["attempts"] >= self.max_attempts:
                    item["dead"] = True
                self._save()
                return

    def ready_count(self) -> int:
        now = self.clock()
        self._expire(now)
        return sum(
            1
            for item in self._items
            if not item["dead"] and not item["lease_id"] and item["available_at"] <= now
        )

    def leased_count(self) -> int:
        now = self.clock()
        self._expire(now)
        return sum(1 for item in self._items if not item["dead"] and item["lease_id"])

    def dead_count(self) -> int:
        now = self.clock()
        self._expire(now)
        return sum(1 for item in self._items if item["dead"])

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        self._items = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items), encoding="utf-8")
