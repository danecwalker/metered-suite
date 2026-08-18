"""Normalized token usage. Adapters write this as usage.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INPUT_KEYS = (
    "input",
    "input_tokens",
    "inputTokens",
    "prompt_tokens",
    "promptTokens",
    "prompt",
    "promptTokenCount",
    "input_other",
    "inputOther",
)

OUTPUT_KEYS = (
    "output",
    "output_tokens",
    "outputTokens",
    "completion_tokens",
    "completionTokens",
    "candidates",
    "candidatesTokenCount",
    "completion",
)

REASONING_KEYS = (
    "reasoning",
    "reasoning_tokens",
    "reasoningTokens",
    "reasoning_output_tokens",
    "reasoningOutputTokens",
    "thinking",
    "thinking_tokens",
    "thinkingTokens",
    "thoughts",
    "thoughts_tokens",
    "thoughtsTokenCount",
)

CACHE_KEYS = (
    "cacheHit",
    "cache_hit",
    "cached_input_tokens",
    "cachedInputTokens",
    "cache_read_input_tokens",
    "cacheReadInputTokens",
    "cache_read_tokens",
    "cacheReadTokens",
    "cachedReadTokens",
    "cached_read_tokens",
    "cached_tokens",
    "cachedTokens",
    "cachedContentTokenCount",
    "input_cache_read",
    "inputCacheRead",
    "cached",
    "cache_read",
    "cacheRead",
)

CACHE_WRITE_KEYS = (
    "cacheWrite",
    "cache_write",
    "cache_creation_input_tokens",
    "cacheCreationInputTokens",
    "cache_creation_tokens",
    "cacheCreationTokens",
    "cache_write_input_tokens",
    "cacheWriteInputTokens",
    "cache_write_tokens",
    "cacheWriteTokens",
    "input_cache_write",
    "inputCacheWrite",
    "input_cache_creation",
    "inputCacheCreation",
)

NESTED_USAGE_KEYS = (
    "prompt_tokens_details",
    "promptTokensDetails",
    "input_tokens_details",
    "inputTokensDetails",
    "completion_tokens_details",
    "completionTokensDetails",
    "output_tokens_details",
    "outputTokensDetails",
    "cache_creation",
    "cacheCreation",
)

EPHEMERAL_WRITE_KEYS = (
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
    "ephemeral5mInputTokens",
    "ephemeral1hInputTokens",
)


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


def first_int(obj: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in obj:
            number = as_int(obj[key])
            if number:
                return number
    return 0


def _flatten_usage(obj: dict[str, Any]) -> dict[str, Any]:
    flat = dict(obj)
    cache_obj = obj.get("cache") if isinstance(obj.get("cache"), dict) else {}
    for key, value in cache_obj.items():
        if key not in flat:
            flat[key] = value
    for key in NESTED_USAGE_KEYS:
        inner = obj.get(key)
        if not isinstance(inner, dict):
            continue
        for nested_key, value in inner.items():
            if nested_key not in flat:
                flat[nested_key] = value
    return flat


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


def usage_from_fields(obj: dict[str, Any], *, source: str = "cli") -> Usage:
    flat = _flatten_usage(obj)
    cache_obj = obj.get("cache") if isinstance(obj.get("cache"), dict) else {}
    cache_hit = first_int(flat, CACHE_KEYS) or first_int(
        cache_obj, ("read", "hit", "cached", "cache_read")
    )
    cache_write = first_int(flat, CACHE_WRITE_KEYS) or first_int(
        cache_obj, ("write", "creation", "create", "cache_write")
    )
    if not cache_write:
        creation = obj.get("cache_creation") or obj.get("cacheCreation")
        if isinstance(creation, dict):
            cache_write = sum(as_int(creation.get(key)) for key in EPHEMERAL_WRITE_KEYS)
    usage = Usage(
        input=first_int(flat, INPUT_KEYS),
        output=first_int(flat, OUTPUT_KEYS),
        reasoning=first_int(flat, REASONING_KEYS),
        cache_hit=cache_hit,
        cache_write=cache_write,
        source=source,
    )
    if not usage.counted():
        return Usage()
    return usage


def usage_from_mapping(obj: Any, *, source: str = "cli") -> Usage:
    if not isinstance(obj, dict):
        return Usage()
    for key in (
        "usage",
        "tokens",
        "token_usage",
        "tokenUsage",
        "usageMetadata",
        "usage_metadata",
    ):
        inner = obj.get(key)
        if isinstance(inner, dict):
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
