"""Normalized token usage. Keys are classified by meaning, not a vendor list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_WRAPPER = {
    "usage",
    "tokens",
    "tokenusage",
    "usagemetadata",
    "tokencounts",
    "tokencount",
    "tokenstats",
}

_SKIP_EXACT = {
    "ok",
    "failed",
    "reward",
    "status",
    "type",
    "id",
    "name",
    "event",
    "kind",
    "scope",
    "level",
    "model",
    "error",
}


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_hit: int = 0
    cache_write: int = 0
    source: str = "none"

    def billed(self) -> int:
        return self.input + self.output + self.reasoning

    def counted(self) -> bool:
        return self.billed() + self.cache_hit + self.cache_write > 0

    def add(self, other: Usage) -> Usage:
        if not other.counted():
            return self
        if not self.counted():
            return other
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            reasoning=self.reasoning + other.reasoning,
            cache_hit=self.cache_hit + other.cache_hit,
            cache_write=self.cache_write + other.cache_write,
            source=self.source if self.source != "none" else other.source,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "cacheHit": self.cache_hit,
            "cacheWrite": self.cache_write,
        }

    def score(self) -> int:
        return self.billed() + self.cache_hit + self.cache_write


def as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return max(0, int(value.strip()))
    return 0


def fold_key(name: Any) -> str:
    text = _CAMEL.sub(r"\1_\2", str(name or ""))
    return _NON_ALNUM.sub("", text.lower())


def classify_key(name: Any, parent: Any = "") -> str | None:
    """Map a field name to input / output / reasoning / cache_hit / cache_write."""
    folded = fold_key(name)
    parent_fold = fold_key(parent)
    if not folded or folded in _SKIP_EXACT:
        return None
    if folded.endswith("id") or folded.endswith("ms"):
        return None
    if "total" in folded and "input" not in folded and "output" not in folded and "prompt" not in folded:
        return None

    cache_parent = parent_fold == "cache" or parent_fold.startswith("cache")
    if "ephemeral" in folded:
        return "cache_write"
    if cache_parent or "cache" in folded or folded == "cached" or folded.startswith("cached"):
        if any(word in folded for word in ("write", "creation", "create", "store")):
            return "cache_write"
        if cache_parent and any(word in folded for word in ("write", "creation", "create", "store")):
            return "cache_write"
        if cache_parent and folded in {"write", "creation", "create", "store"}:
            return "cache_write"
        if cache_parent and folded in {"read", "hit", "cached"}:
            return "cache_hit"
        return "cache_hit"

    if any(word in folded for word in ("reason", "think", "thought")):
        return "reasoning"

    if (
        folded in {"input", "prompt", "promptevalcount"}
        or folded.startswith("input")
        or (
            ("input" in folded or "prompt" in folded)
            and ("token" in folded or "count" in folded)
        )
    ):
        return "input"

    if (
        folded in {"output", "completion", "candidates", "evalcount"}
        or folded.startswith("output")
        or (
            any(word in folded for word in ("output", "completion", "candidate", "generated"))
            and ("token" in folded or "count" in folded)
        )
    ):
        return "output"
    return None


def _should_lift(name: Any) -> bool:
    folded = fold_key(name)
    return any(word in folded for word in ("cache", "detail", "token", "usage", "ephemeral"))


def _flatten_usage(obj: dict[str, Any], parent: str = "") -> list[tuple[str, str, Any]]:
    """Yield (parent, key, value) including one-level nested usage-shaped dicts."""
    rows: list[tuple[str, str, Any]] = []
    for key, value in obj.items():
        rows.append((parent, str(key), value))
        if isinstance(value, dict) and _should_lift(key):
            rows.extend(_flatten_usage(value, str(key)))
    return rows


def pick_richer(left: Usage, right: Usage) -> Usage:
    """Keep the fuller spend object. modelUsage often omits cache writes."""
    if not left.counted():
        return right
    if not right.counted():
        return left
    if left.score() != right.score():
        return left if left.score() > right.score() else right
    if left.cache_write != right.cache_write:
        return left if left.cache_write > right.cache_write else right
    if left.reasoning != right.reasoning:
        return left if left.reasoning > right.reasoning else right
    return left


def _numeric(value: Any) -> int:
    """Int, {tokens|count|total|value: N}, or a list of token ids."""
    number = as_int(value)
    if number:
        return number
    if isinstance(value, dict):
        for key in ("tokens", "token", "count", "total", "value", "amount", "n"):
            number = as_int(value.get(key))
            if number:
                return number
        return 0
    if isinstance(value, list) and value and all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return len(value)
    return 0


def usage_from_fields(obj: dict[str, Any], *, source: str = "cli") -> Usage:
    buckets = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_hit": 0,
        "cache_write": 0,
    }
    for parent, key, value in _flatten_usage(obj):
        field = classify_key(key, parent)
        if field is None:
            continue
        number = _numeric(value)
        if number > buckets[field]:
            buckets[field] = number
    # Ephemeral cache writes are additive slices of one write, not alternatives.
    writes = [
        as_int(value)
        for parent, key, value in _flatten_usage(obj)
        if not isinstance(value, dict) and "ephemeral" in fold_key(key)
    ]
    if len(writes) > 1:
        buckets["cache_write"] = max(buckets["cache_write"], sum(writes))
    usage = Usage(
        input=buckets["input"],
        output=buckets["output"],
        reasoning=buckets["reasoning"],
        cache_hit=buckets["cache_hit"],
        cache_write=buckets["cache_write"],
        source=source,
    )
    if not usage.counted():
        return Usage()
    return usage


def usage_from_mapping(obj: Any, *, source: str = "cli") -> Usage:
    if not isinstance(obj, dict):
        return Usage()
    for key, inner in obj.items():
        if isinstance(inner, dict) and fold_key(key) in _WRAPPER:
            parsed = usage_from_fields(inner, source=source)
            if parsed.counted():
                return parsed
    return usage_from_fields(obj, source=source)


def json_blobs(text: str) -> list[Any]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        pass
    blobs: list[Any] = []
    decoder = json.JSONDecoder()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        idx = 0
        while idx < len(line):
            while idx < len(line) and line[idx] not in "{[":
                idx += 1
            if idx >= len(line):
                break
            try:
                value, end = decoder.raw_decode(line, idx)
            except json.JSONDecodeError:
                break
            blobs.append(value)
            idx = end
    return blobs


def best_usage(blobs: list[Any]) -> Usage:
    """Pick the largest usage-like object. Avoids double-counting nested copies."""
    best = Usage()
    best_score = -1

    def walk(node: Any) -> None:
        nonlocal best, best_score
        if isinstance(node, dict):
            parsed = usage_from_mapping(node)
            score = parsed.score()
            if score > best_score:
                best = parsed
                best_score = score
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for blob in blobs:
        walk(blob)
    return best


def read_sidecar(workspace: Path) -> Usage:
    path = workspace / "usage.json"
    if not path.exists():
        return Usage()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Usage()
    if not isinstance(data, dict):
        return Usage()
    parsed = usage_from_fields(data, source="sidecar")
    return parsed if parsed.counted() else Usage()


def write_usage(workspace: Path, usage: Usage) -> None:
    (workspace / "usage.json").write_text(
        json.dumps(usage.as_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
