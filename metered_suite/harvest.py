"""Generic usage harvest. No per-harness parsers.

Order:
  1. stdout + stderr JSON (including SSE ``data:`` lines)
  2. workspace/usage.json sidecar
  3. session transcripts the CLI left in the checkout

Across those sources we keep the richer object. We never add two sources
together, so a session file that repeats the stream cannot double-count.

Inside one stream we classify records as a session total or a turn/step.
Turn records are summed when they look incremental, otherwise the last
wins. Session totals take the last / richest. If both exist, we keep the
richer, except Kimi-style ``usage.record`` session rows which duplicate
turns and are ignored when turns are present.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from .usage import (
    Usage,
    fold_key,
    json_blobs,
    pick_richer,
    read_sidecar,
    usage_from_fields,
    usage_from_mapping,
    write_usage,
)

TURN_TYPES = {
    "turn.completed",
    "turn_completed",
    "step_finish",
    "step-finish",
    "step_complete",
    "step-complete",
    "message_update",
    "usage.record",
    "usage_record",
}

SESSION_TYPES = {
    "result",
    "token_count",
    "message_end",
    "turn_end",
    "agent_end",
    "session",
    "session_end",
    "final",
}

TURN_SCOPES = {"turn", "step", "delta", "increment", "item"}
SESSION_SCOPES = {"session", "total", "cumulative", "run", "overall"}

SKIP_DIR_NAMES = {
    ".git",
    "_grade",
    "node_modules",
    "__pycache__",
    ".tmp",
    ".venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
}
SESSION_SUFFIXES = {".json", ".jsonl"}
MAX_SESSION_FILES = 48
MAX_SESSION_BYTES = 2_000_000


def _kind(obj: dict[str, Any]) -> str:
    raw_type = str(obj.get("type") or obj.get("event") or obj.get("kind") or "")
    payload = obj.get("payload")
    if isinstance(payload, dict) and payload.get("type"):
        raw_type = str(payload.get("type"))
    scope = str(obj.get("scope") or obj.get("level") or "").lower()
    if scope in SESSION_SCOPES:
        return "session"
    if scope in TURN_SCOPES:
        return "turn"
    if raw_type in SESSION_TYPES:
        return "session"
    if raw_type in TURN_TYPES:
        return "turn"
    if raw_type.endswith("session") or raw_type.endswith("total"):
        return "session"
    return "unknown"


def _blobs(text: str) -> list[Any]:
    blobs = json_blobs(text)
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            blobs.extend(json_blobs(stripped[5:]))
    return blobs


def _iter_dicts(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def _is_group_key(name: Any) -> bool:
    folded = fold_key(name)
    if folded in {"models", "modelusage", "modelstats"}:
        return True
    return folded.startswith("model") and ("usage" in folded or "stat" in folded)


def _group_sum(obj: dict[str, Any], *, source: str) -> Usage:
    for key, models in obj.items():
        if not _is_group_key(key) or not isinstance(models, dict) or not models:
            continue
        total = Usage(source=source)
        for item in models.values():
            if not isinstance(item, dict):
                continue
            tokens = item.get("tokens") if isinstance(item.get("tokens"), dict) else item
            total = total.add(usage_from_fields(tokens, source=source))
        if total.counted():
            return total
    return Usage()


def _record_usage(obj: dict[str, Any], *, source: str) -> Usage:
    parsed = usage_from_mapping(obj, source=source)
    if parsed.counted():
        return parsed
    part = obj.get("part")
    if isinstance(part, dict):
        parsed = usage_from_mapping(part, source=source)
        if parsed.counted():
            return parsed
    message = obj.get("message")
    if isinstance(message, dict):
        parsed = usage_from_mapping(message, source=source)
        if parsed.counted():
            return parsed
    payload = obj.get("payload")
    if isinstance(payload, dict):
        info = payload.get("info") if isinstance(payload.get("info"), dict) else payload
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        parsed = usage_from_mapping(total or info or payload, source=source)
        if parsed.counted():
            return parsed
    return Usage()


def harvest_blobs(blobs: list[Any], *, source: str = "cli") -> Usage:
    turns: list[Usage] = []
    sessions: list[Usage] = []
    turn_family = False
    session_record_family = False
    grouped: list[Usage] = []
    group_children: set[int] = set()

    for blob in blobs:
        for obj in _iter_dicts(blob):
            for key, models in obj.items():
                if not _is_group_key(key) or not isinstance(models, dict):
                    continue
                for item in models.values():
                    if isinstance(item, dict):
                        group_children.add(id(item))
                        tokens = item.get("tokens")
                        if isinstance(tokens, dict):
                            group_children.add(id(tokens))

    for blob in blobs:
        for obj in _iter_dicts(blob):
            group = _group_sum(obj, source=source)
            if group.counted():
                grouped.append(group)
            if id(obj) in group_children:
                continue
            parsed = _record_usage(obj, source=source)
            if not parsed.counted():
                continue
            kind = _kind(obj)
            raw_type = str(obj.get("type") or "")
            if kind == "turn":
                turns.append(parsed)
                if raw_type in {"usage.record", "usage_record"}:
                    turn_family = True
            elif kind == "session":
                sessions.append(parsed)
                if raw_type in {"usage.record", "usage_record"}:
                    session_record_family = True
            else:
                sessions.append(parsed)

    turn_usage = _aggregate_turns(turns)
    session_usage = Usage()
    for item in sessions:
        session_usage = pick_richer(session_usage, item)
    for item in grouped:
        session_usage = pick_richer(session_usage, item)

    if turn_family and session_record_family:
        return turn_usage if turn_usage.counted() else session_usage
    return pick_richer(turn_usage, session_usage)


def _aggregate_turns(turns: list[Usage]) -> Usage:
    if not turns:
        return Usage()
    if len(turns) == 1:
        return turns[0]
    if all(turns[index + 1].input >= turns[index].input for index in range(len(turns) - 1)):
        return turns[-1]
    total = Usage(source=turns[0].source)
    for item in turns:
        total = total.add(item)
    return total


def harvest_text(stdout: str = "", stderr: str = "", *, source: str = "cli") -> Usage:
    return harvest_blobs(_blobs(stdout) + _blobs(stderr), source=source)


def _looks_like_session_name(path: Path) -> bool:
    folded = fold_key(path.stem)
    return any(word in folded for word in ("session", "usage", "token", "transcript", "rollout"))


def _session_files(workspace: Path) -> list[Path]:
    if not workspace.exists():
        return []
    found: list[Path] = []
    for path in workspace.iterdir():
        if path.is_file() and path.suffix.lower() in SESSION_SUFFIXES and _looks_like_session_name(path):
            found.append(path)
    roots = [
        path
        for path in workspace.iterdir()
        if path.is_dir() and path.name.startswith(".") and path.name not in SKIP_DIR_NAMES
    ]
    for root in roots:
        for path in root.rglob("*"):
            if len(found) >= MAX_SESSION_FILES:
                return found
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.name == "usage.json" and path.parent == workspace:
                continue
            if path.suffix.lower() not in SESSION_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_SESSION_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)
    return found


def _recent_home_session_files(since: float) -> list[Path]:
    """Recent JSON/JSONL under $HOME/.*, depth-limited. Last resort only."""
    home = Path.home()
    if not home.is_dir() or since <= 0:
        return []
    found: list[Path] = []
    slack = since - 2
    max_depth = 4
    try:
        entries = list(home.iterdir())
    except OSError:
        return []
    for root in entries:
        if len(found) >= MAX_SESSION_FILES:
            break
        if not root.is_dir() or not root.name.startswith(".") or root.name in SKIP_DIR_NAMES:
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                rel = Path(dirpath).relative_to(root)
                if len(rel.parts) >= max_depth:
                    dirnames[:] = []
                dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
                for name in filenames:
                    path = Path(dirpath) / name
                    if path.suffix.lower() not in SESSION_SUFFIXES:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    if stat.st_mtime < slack or stat.st_size > MAX_SESSION_BYTES:
                        continue
                    found.append(path)
                    if len(found) >= MAX_SESSION_FILES:
                        return found
        except OSError:
            continue
    return found


def harvest_sessions(workspace: Path | None, *, since: float | None = None) -> Usage:
    if workspace is None and since is None:
        return Usage()
    best = Usage()
    paths = _session_files(workspace) if workspace is not None else []
    if since:
        paths.extend(_recent_home_session_files(since))
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = harvest_text(text, source="session")
        best = pick_richer(best, parsed)
    return best


def harvest(
    stdout: str = "",
    stderr: str = "",
    workspace: Path | None = None,
    *,
    persist: bool = False,
    since: float | None = None,
) -> Usage:
    stream = harvest_text(stdout, stderr, source="cli")
    sidecar = read_sidecar(workspace) if workspace is not None else Usage()
    local = harvest_sessions(workspace)
    chosen = pick_richer(pick_richer(stream, sidecar), local)
    if not chosen.counted() and since:
        chosen = pick_richer(chosen, harvest_sessions(None, since=since))
    if persist and workspace is not None:
        write_usage(workspace, chosen if chosen.counted() else Usage())
    return chosen
