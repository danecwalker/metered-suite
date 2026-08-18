"""Usage harvest entry point. Command argv lives in harness.yaml."""

from __future__ import annotations

from pathlib import Path

from .harvest import harvest
from .usage import Usage


def parse_usage(slug: str, stdout: str, stderr: str = "", workspace: Path | None = None) -> Usage:
    del slug
    return harvest(stdout, stderr, workspace, persist=False)
