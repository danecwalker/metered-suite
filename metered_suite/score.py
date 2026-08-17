from __future__ import annotations

import json
import re
from typing import Any


def values_match(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual or expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= 1e-6
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def extract_json_object(text: str) -> dict[str, Any] | None:
    trimmed = text.strip()
    candidates = [trimmed]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", trimmed, re.I)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    first = trimmed.find("{")
    last = trimmed.rfind("}")
    if first >= 0 and last > first:
        candidates.append(trimmed[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def score_json(output: str, expected: dict[str, Any]) -> bool:
    got = extract_json_object(output)
    if not got:
        return False
    return all(key in got and values_match(value, got[key]) for key, value in expected.items())
