"""Same hashing as Metered's TypeScript evaluator. Do not drift."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

EVAL_FORMAT = "metered-eval/1"
EVALUATOR_VERSION = "0.3.0"
SUITE_VERSION = "work-2026.08-py4"
CHARS_PER_MU = 4


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


def sha256_utf8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return sha256_utf8(normalize_text(text))


def stable_stringify(value: Any) -> str:
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(stable_stringify(item) for item in value) + "]"
    keys = sorted(value.keys())
    inner = ",".join(
        f"{json.dumps(key, ensure_ascii=True)}:{stable_stringify(value[key])}"
        for key in keys
    )
    return "{" + inner + "}"


def integrity_of(value: Any) -> str:
    return sha256_utf8(stable_stringify(value))


def character_count(text: str) -> int:
    return len(normalize_text(text))


def metered_units(chars: int) -> float:
    return chars / CHARS_PER_MU
