"""Broken starter. Public and hidden tests describe the contract."""

from __future__ import annotations

from typing import Any


class PatchError(Exception):
    pass


def apply(doc: Any, ops: list[dict]) -> Any:
    cur = doc
    for op in ops:
        path = str(op.get("path") or "").strip("/")
        key = path.split("/")[-1] if path else ""
        kind = op.get("op")
        if kind == "replace" and isinstance(cur, dict) and key:
            cur[key] = op.get("value")
        elif kind == "add" and isinstance(cur, dict) and key:
            cur[key] = op.get("value")
        elif kind == "remove" and isinstance(cur, dict) and key in cur:
            del cur[key]
        elif kind == "test":
            continue
        else:
            raise PatchError("bad op")
    return cur
