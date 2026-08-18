"""Live progress while a harness CLI is running."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

_SKIP_DIR = {".git", ".tmp", "_grade", "__pycache__"}
_SKIP_NAME = {"instruction.md", "seatbelt.sb", ".DS_Store"}
_WATCH_EVERY = 1.0
_HEARTBEAT_EVERY = 15.0
_SNIPPET_GAP = 0.4


def _default_log(message: str) -> None:
    from .term import dim, log

    log(dim(f"  {message}"))


def _one_line(text: str, limit: int = 96) -> str:
    line = " ".join((text or "").split())
    if len(line) <= limit:
        return line
    return line[: limit - 3] + "..."


def _rel(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return path.name


def _tool_name(obj: dict) -> str:
    for key in ("tool_name", "toolName", "name", "tool"):
        value = obj.get(key)
        if isinstance(value, str) and value and value not in {"assistant", "user", "system"}:
            return value
    nested = obj.get("tool_call") or obj.get("toolCall") or obj.get("function")
    if isinstance(nested, dict):
        value = nested.get("name") or nested.get("tool")
        if isinstance(value, str) and value:
            return value
    return ""


def _tool_target(obj: dict) -> str:
    for key in ("file_path", "filePath", "path", "filename", "command", "cmd"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value).name if key.endswith("path") or key == "filename" else _one_line(value, 64)
    inp = obj.get("input") or obj.get("arguments") or obj.get("args")
    if isinstance(inp, dict):
        for key in ("file_path", "filePath", "path", "target_file", "command"):
            value = inp.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value).name if "path" in key or key == "target_file" else _one_line(value, 64)
    return ""


def event_snippet(obj: object) -> str | None:
    if not isinstance(obj, dict):
        return None
    kind = str(obj.get("type") or obj.get("event") or obj.get("kind") or "")
    subtype = str(obj.get("subtype") or obj.get("status") or "")
    lower = kind.lower()

    if lower in {"error", "turn.failed", "stream_error"}:
        message = obj.get("message") or obj.get("error") or subtype
        if isinstance(message, dict):
            message = message.get("message") or message.get("error")
        return f"cli error {_one_line(str(message or kind))}"

    tool = _tool_name(obj)
    target = _tool_target(obj)
    if tool or lower in {"tool_use", "tool_call", "tool", "function_call", "tool_request"}:
        name = tool or "tool"
        return f"{name} {target}".strip()

    content = obj.get("content") or obj.get("message")
    if isinstance(content, dict):
        nested_tool = _tool_name(content)
        if nested_tool:
            return f"{nested_tool} {_tool_target(content)}".strip()
        text = content.get("content") or content.get("text")
        if isinstance(text, str) and text.strip() and lower in {"assistant", "message"}:
            return f"model {_one_line(text, 72)}"
        if isinstance(content.get("content"), list):
            for block in content["content"]:
                if isinstance(block, dict):
                    snippet = event_snippet(block)
                    if snippet:
                        return snippet

    if lower in {"assistant", "message"} and isinstance(obj.get("text"), str):
        return f"model {_one_line(str(obj['text']), 72)}"

    if lower == "result":
        if obj.get("is_error") or obj.get("isError"):
            err = obj.get("result") or obj.get("errors") or obj.get("error") or "is_error"
            if isinstance(err, list):
                err = err[0] if err else "is_error"
            return f"cli error {_one_line(str(err))}"
        return f"cli result {subtype or 'done'}".strip()
    if lower == "system":
        return f"cli {subtype or 'system'}"
    if lower in {"turn.completed", "turn.started", "item.completed"}:
        return f"cli {kind}"
    return None


def line_snippet(line: str) -> str | None:
    text = (line or "").strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list) and parsed:
            parsed = parsed[-1]
        return event_snippet(parsed)
    if text.startswith("\x1b") or set(text) <= {" ", ".", "-", "/", "|", "\\"}:
        return None
    if len(text) > 400:
        return None
    return _one_line(text, 96)


def _watch_snapshot(root: Path) -> dict[Path, tuple[int, int]]:
    found: dict[Path, tuple[int, int]] = {}
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR for part in path.parts):
            continue
        if path.name in _SKIP_NAME:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found[path] = (int(stat.st_mtime_ns), stat.st_size)
    return found


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def run_command(
    command: list[str],
    *,
    cwd: Path | None,
    env: dict | None,
    timeout: int,
    log: LogFn | None = None,
    watch: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, keep stdout/stderr, and print short live progress."""
    emit = log or _default_log
    started = time.monotonic()
    last_note = started
    last_snippet = ""
    lock = threading.Lock()
    stop = threading.Event()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    watched = {"prev": _watch_snapshot(watch) if watch is not None else {}}

    def note(message: str) -> None:
        nonlocal last_note, last_snippet
        text = (message or "").strip()
        if not text:
            return
        now = time.monotonic()
        with lock:
            if text == last_snippet and now - last_note < 2:
                return
            if now - last_note < _SNIPPET_GAP and text == last_snippet:
                return
            last_note = now
            last_snippet = text
            emit(text)

    def reader(stream, bucket: list[str]) -> None:
        try:
            for raw in iter(stream.readline, ""):
                bucket.append(raw)
                snippet = line_snippet(raw)
                if snippet:
                    note(snippet)
        except OSError:
            return

    def report_writes() -> None:
        if watch is None:
            return
        current = _watch_snapshot(watch)
        previous = watched["prev"]
        for path, meta in current.items():
            if previous.get(path) != meta:
                note(f"wrote {_rel(watch, path)}")
        for path in previous:
            if path not in current:
                note(f"removed {_rel(watch, path)}")
        watched["prev"] = current

    def watcher() -> None:
        if watch is None:
            return
        while not stop.wait(_WATCH_EVERY):
            report_writes()

    def heartbeat() -> None:
        from .term import color_enabled, set_spin_label

        while not stop.wait(_HEARTBEAT_EVERY):
            elapsed = _format_elapsed(time.monotonic() - started)
            if color_enabled(sys.stderr):
                set_spin_label(f"harness {elapsed}")
                continue
            idle = time.monotonic() - last_note
            if idle >= _HEARTBEAT_EVERY - 0.5:
                note(f"still running {elapsed}")

    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    threads = [
        threading.Thread(target=reader, args=(proc.stdout, stdout_parts), daemon=True),
        threading.Thread(target=reader, args=(proc.stderr, stderr_parts), daemon=True),
        threading.Thread(target=watcher, daemon=True),
        threading.Thread(target=heartbeat, daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    finally:
        stop.set()
        report_writes()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        for thread in threads:
            thread.join(timeout=1)

    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, proc.returncode or 0, stdout, stderr)
