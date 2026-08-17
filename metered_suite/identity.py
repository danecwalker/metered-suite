"""Closed harness set. Display names and list prices are not taken from main.py."""

from __future__ import annotations

import os
import re

HARNESSES = {
    "claude": {
        "id": "hrs_claude",
        "binaries": ("claude",),
        "sku": re.compile(r"^claude", re.I),
        "prefix": ["-p", "--model", "{model}"],
    },
    "chatgpt": {
        "id": "hrs_chatgpt",
        "binaries": ("codex",),
        "sku": re.compile(r"^(gpt-|o[1-9]|codex|chatgpt)", re.I),
        "prefix": ["exec", "--model", "{model}"],
    },
    "grok": {
        "id": "hrs_grok",
        "binaries": ("grok",),
        "sku": re.compile(r"^grok", re.I),
        "prefix": ["--model", "{model}"],
    },
    "qwen": {
        "id": "hrs_qwen",
        "binaries": ("qwen", "qwen-code"),
        "sku": re.compile(r"^qwen", re.I),
        "prefix": ["--model", "{model}"],
    },
    "pi": {
        "id": "hrs_pi",
        "binaries": ("pi",),
        "sku": re.compile(r"."),
        "prefix": ["--model", "{model}"],
    },
    "opencode": {
        "id": "hrs_opencode",
        "binaries": ("opencode",),
        "sku": re.compile(r"."),
        "prefix": ["--model", "{model}"],
    },
    "api": {
        "id": "hrs_api",
        "binaries": (),
        "sku": re.compile(r"."),
        "prefix": [],
    },
    "custom": {
        "id": "hrs_custom",
        "binaries": (),
        "sku": re.compile(r"."),
        "prefix": [],
    },
}

BLOCKED_FLAGS = {
    "--model",
    "-m",
    "--harness",
    "--agent",
}


def resolve_harness(slug: str) -> dict:
    key = slug.strip().lower()
    spec = HARNESSES.get(key)
    if not spec:
        allowed = ", ".join(sorted(HARNESSES))
        raise SystemExit(f"HARNESS must be one of: {allowed}")
    return {"slug": key, **spec}


def sku_fits(spec: dict, sku: str) -> bool:
    return bool(spec["sku"].search(sku.strip()))


def build_command(spec: dict, model: str, flags: list[str]) -> list[str]:
    binaries = spec["binaries"]
    if not binaries:
        raise SystemExit(
            "HARNESS api/custom cannot invent a binary. Use a named harness "
            "(claude, chatgpt, grok, qwen, pi, opencode)."
        )
    cleaned: list[str] = []
    for flag in flags:
        if flag in BLOCKED_FLAGS or flag.startswith("--model="):
            raise SystemExit(f"FLAGS cannot include {flag}; set MODEL in main.py.")
        if os.path.basename(flag) in {name for names in (
            item["binaries"] for item in HARNESSES.values()
        ) for name in names}:
            raise SystemExit(f"FLAGS cannot switch harness binary ({flag}).")
        cleaned.append(flag)
    command = [binaries[0], *spec["prefix"], *cleaned, "{prompt}"]
    return [model if part == "{model}" else part for part in command]
