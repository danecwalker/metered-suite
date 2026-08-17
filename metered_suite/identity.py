"""Closed harness set. Display names and list prices are not taken from main.py."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .adapters import adapter_for

HARNESSES = {
    "claude": {
        "id": "hrs_claude",
        "binaries": ("claude",),
        "sku": re.compile(r"^claude", re.I),
    },
    "chatgpt": {
        "id": "hrs_chatgpt",
        "binaries": ("codex",),
        "sku": re.compile(r"^(gpt-|o[1-9]|codex|chatgpt)", re.I),
    },
    "gemini": {
        "id": "hrs_gemini",
        "binaries": ("gemini",),
        "sku": re.compile(r"^gemini", re.I),
    },
    "grok": {
        "id": "hrs_grok",
        "binaries": ("grok",),
        "sku": re.compile(r"^grok", re.I),
    },
    "qwen": {
        "id": "hrs_qwen",
        "binaries": ("qwen", "qwen-code"),
        "sku": re.compile(r"^qwen", re.I),
    },
    "kimi": {
        "id": "hrs_kimi",
        "binaries": ("kimi",),
        "sku": re.compile(r"^(kimi|moonshot)", re.I),
    },
    "deepseek": {
        "id": "hrs_deepseek",
        "binaries": ("deepcode", "deepseek"),
        "sku": re.compile(r"^deepseek", re.I),
    },
    "opencode": {
        "id": "hrs_opencode",
        "binaries": ("opencode",),
        "sku": re.compile(r"."),
    },
    "pi": {
        "id": "hrs_pi",
        "binaries": ("pi",),
        "sku": re.compile(r"."),
    },
    "api": {
        "id": "hrs_api",
        "binaries": (),
        "sku": re.compile(r"."),
    },
    "custom": {
        "id": "hrs_custom",
        "binaries": (),
        "sku": re.compile(r"."),
    },
}

NAMED_HARNESSES = tuple(slug for slug in HARNESSES if HARNESSES[slug]["binaries"])

BLOCKED_FLAGS = {
    "--model",
    "-m",
    "--harness",
    "--agent",
    "--output-format",
    "--format",
    "--json",
    "--mode",
    "--print",
    "--prompt",
    "--single",
    "-p",
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


def pick_binary(spec: dict) -> str:
    names = spec["binaries"]
    if not names:
        raise SystemExit(
            "HARNESS api/custom cannot invent a binary. Use a named harness "
            f"({', '.join(NAMED_HARNESSES)})."
        )
    for name in names:
        if shutil.which(name):
            return name
    return names[0]


def clean_flags(_spec: dict, flags: list[str]) -> list[str]:
    blocked_bins = {
        name
        for item in HARNESSES.values()
        for name in item["binaries"]
    }
    cleaned: list[str] = []
    for flag in flags:
        if flag in BLOCKED_FLAGS or flag.startswith("--model="):
            raise SystemExit(f"FLAGS cannot include {flag}; set MODEL in main.py.")
        if os.path.basename(flag) in blocked_bins:
            raise SystemExit(f"FLAGS cannot switch harness binary ({flag}).")
        cleaned.append(flag)
    return cleaned


def build_command(
    spec: dict,
    model: str,
    flags: list[str],
    prompt: str,
    prompt_file: Path,
    effort: str = "default",
) -> list[str]:
    binary = pick_binary(spec)
    cleaned = clean_flags(spec, flags)
    adapter = adapter_for(spec["slug"])
    return adapter.command(
        binary,
        model,
        cleaned,
        prompt,
        prompt_file,
        effort,
    )
