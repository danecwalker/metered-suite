"""Reference solution. Held out from the agent. Not used at grade time."""

from __future__ import annotations

import copy
from typing import Any


class PatchError(Exception):
    pass


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PatchError("path must start with /")
    return [_unescape(part) for part in pointer[1:].split("/")]


def _walk(doc: Any, tokens: list[str]) -> Any:
    cur = doc
    for token in tokens:
        if isinstance(cur, list):
            try:
                index = int(token)
            except ValueError as error:
                raise PatchError("array index must be an integer") from error
            if index < 0 or index >= len(cur):
                raise PatchError("array index out of range")
            cur = cur[index]
        elif isinstance(cur, dict):
            if token not in cur:
                raise PatchError("missing key")
            cur = cur[token]
        else:
            raise PatchError("cannot walk")
    return cur


def _set(doc: Any, tokens: list[str], value: Any, *, add: bool) -> Any:
    if not tokens:
        return value
    parent = _walk(doc, tokens[:-1])
    last = tokens[-1]
    if isinstance(parent, list):
        if last == "-":
            if not add:
                raise PatchError("replace cannot append")
            parent.append(value)
            return doc
        try:
            index = int(last)
        except ValueError as error:
            raise PatchError("array index must be an integer") from error
        if add:
            if index < 0 or index > len(parent):
                raise PatchError("array index out of range")
            parent.insert(index, value)
        else:
            if index < 0 or index >= len(parent):
                raise PatchError("array index out of range")
            parent[index] = value
        return doc
    if isinstance(parent, dict):
        if not add and last not in parent:
            raise PatchError("missing key")
        parent[last] = value
        return doc
    raise PatchError("cannot set")


def _remove(doc: Any, tokens: list[str]) -> Any:
    if not tokens:
        raise PatchError("cannot remove the root")
    parent = _walk(doc, tokens[:-1])
    last = tokens[-1]
    if isinstance(parent, list):
        try:
            index = int(last)
        except ValueError as error:
            raise PatchError("array index must be an integer") from error
        if index < 0 or index >= len(parent):
            raise PatchError("array index out of range")
        del parent[index]
        return doc
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError("missing key")
        del parent[last]
        return doc
    raise PatchError("cannot remove")


def apply(doc: Any, ops: list[dict]) -> Any:
    cur = copy.deepcopy(doc)
    for op in ops:
        kind = op.get("op")
        tokens = _tokens(str(op.get("path")))
        if kind == "test":
            if _walk(cur, tokens) != op.get("value"):
                raise PatchError("test failed")
        elif kind == "remove":
            cur = _remove(cur, tokens)
        elif kind == "replace":
            _walk(cur, tokens)
            cur = _set(cur, tokens, op.get("value"), add=False)
        elif kind == "add":
            cur = _set(cur, tokens, op.get("value"), add=True)
        else:
            raise PatchError(f"unsupported op {kind}")
    return cur
