"""TTY helpers: colour, ticks, and a stderr spinner."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def color_enabled(stream: TextIO | None = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, *codes: str, stream: TextIO | None = None) -> str:
    if not codes or not color_enabled(stream):
        return text
    return "".join(codes) + text + _RESET


def dim(text: str) -> str:
    return paint(text, _DIM)


def bold(text: str) -> str:
    return paint(text, _BOLD)


def green(text: str) -> str:
    return paint(text, _GREEN)


def red(text: str) -> str:
    return paint(text, _RED)


def yellow(text: str) -> str:
    return paint(text, _YELLOW)


def cyan(text: str) -> str:
    return paint(text, _CYAN)


class Spinner:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.enabled = color_enabled(self.stream)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._label = ""
        self._lock = threading.Lock()
        self._started = 0.0
        self._visible = False

    def start(self, label: str) -> None:
        self._label = label
        self._started = time.monotonic()
        if not self.enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def set_label(self, label: str) -> None:
        self._label = label

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout=0.4)
        self._thread = None
        self._clear()

    def pause(self) -> None:
        self._clear()

    def _clear(self) -> None:
        if not self.enabled or not self._visible:
            self._visible = False
            return
        try:
            self.stream.write("\r\033[K")
            self.stream.flush()
        except OSError:
            pass
        self._visible = False

    def _run(self) -> None:
        index = 0
        while not self._stop.wait(0.08):
            elapsed = max(0, int(time.monotonic() - self._started))
            frame = _FRAMES[index % len(_FRAMES)]
            line = f"  {frame} {self._label}  {elapsed}s"
            try:
                self.stream.write("\r\033[K" + paint(line, _CYAN, stream=self.stream))
                self.stream.flush()
                self._visible = True
            except OSError:
                return
            index += 1
        self._clear()


_spinner = Spinner()


def log(message: str) -> None:
    _spinner.pause()
    print(message, flush=True)


def set_spin_label(label: str) -> None:
    _spinner.set_label(label)


@contextmanager
def spin(label: str) -> Iterator[Spinner]:
    _spinner.start(label)
    try:
        yield _spinner
    finally:
        _spinner.stop()
