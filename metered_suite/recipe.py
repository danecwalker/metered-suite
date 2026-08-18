"""Local harness recipes. Not part of the official lock.

`python3 -m metered_suite init` writes harness.yaml from binaries on PATH.
The run path only reads that file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

RECIPE_NAME = "harness.yaml"

# Metered catalog ids for the sealed package. Not invoke recipes.
CATALOG_IDS = {
    "claude": "hrs_claude",
    "chatgpt": "hrs_chatgpt",
    "gemini": "hrs_gemini",
    "grok": "hrs_grok",
    "qwen": "hrs_qwen",
    "kimi": "hrs_kimi",
    "deepseek": "hrs_deepseek",
    "opencode": "hrs_opencode",
    "pi": "hrs_pi",
    "api": "hrs_api",
    "custom": "hrs_custom",
}

# Seed used only by init. Edit harness.yaml after that; do not keep this in sync
# unless you want nicer first-run defaults.
_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "claude",
        "aliases": ("claude-code",),
        "slug": "claude",
        "bins": ("claude", "claude-code"),
        "argv": [
            "{bin}",
            "--print",
            "--model",
            "{model}",
            "--output-format",
            "json",
            "--effort",
            "{effort}",
            "--dangerously-skip-permissions",
            "{prompt}",
        ],
    },
    {
        "name": "codex",
        "aliases": ("chatgpt",),
        "slug": "chatgpt",
        "bins": ("codex",),
        "argv": [
            "{bin}",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--model",
            "{model}",
            "-c",
            "model_reasoning_effort={effort}",
            "--dangerously-bypass-approvals-and-sandbox",
            "{prompt}",
        ],
    },
    {
        "name": "gemini",
        "slug": "gemini",
        "bins": ("gemini",),
        "argv": [
            "{bin}",
            "--prompt",
            "{prompt}",
            "--model",
            "{model}",
            "--output-format",
            "json",
            "--yolo",
        ],
    },
    {
        "name": "grok",
        "slug": "grok",
        "bins": ("grok",),
        "argv": [
            "{bin}",
            "--single",
            "{prompt}",
            "--model",
            "{model}",
            "--output-format",
            "json",
            "--reasoning-effort",
            "{effort}",
            "--always-approve",
        ],
    },
    {
        "name": "qwen",
        "aliases": ("qwen-code",),
        "slug": "qwen",
        "bins": ("qwen", "qwen-code"),
        "argv": [
            "{bin}",
            "--prompt",
            "{prompt}",
            "--model",
            "{model}",
            "--output-format",
            "stream-json",
            "--yolo",
        ],
    },
    {
        "name": "kimi",
        "slug": "kimi",
        "bins": ("kimi",),
        "argv": [
            "{bin}",
            "--prompt",
            "{prompt}",
            "--model",
            "{model}",
            "--output-format",
            "stream-json",
        ],
    },
    {
        "name": "deepseek",
        "aliases": ("deepcode",),
        "slug": "deepseek",
        "bins": ("deepcode", "deepseek"),
        "argv": [
            "{bin}",
            "--print",
            "--model",
            "{model}",
            "--output-format",
            "json",
            "--yolo",
            "{prompt}",
        ],
    },
    {
        "name": "opencode",
        "slug": "opencode",
        "bins": ("opencode",),
        "argv": [
            "{bin}",
            "run",
            "--model",
            "{model}",
            "--variant",
            "{effort}",
            "--format",
            "json",
            "{prompt}",
        ],
    },
    {
        "name": "pi",
        "slug": "pi",
        "bins": ("pi",),
        "argv": [
            "{bin}",
            "--mode",
            "json",
            "--model",
            "{model}",
            "--thinking",
            "{effort}",
            "{prompt}",
        ],
    },
]

_EFFORT_FLAGS = {"--effort", "--reasoning-effort", "--variant", "--thinking"}


def template_keys(tmpl: dict[str, Any]) -> tuple[str, ...]:
    aliases = tuple(tmpl.get("aliases") or ())
    return (str(tmpl["name"]),) + tuple(str(item) for item in aliases)


def recipe_path(root: Path) -> Path:
    return root / RECIPE_NAME


def catalog_id(slug: str) -> str:
    return CATALOG_IDS.get(slug, "hrs_custom")


def parse_recipes(text: str) -> dict[str, dict[str, Any]]:
    recipes: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw.startswith((" ", "\t")):
            current = line.rstrip(":").strip()
            recipes[current] = {}
            continue
        if current is None:
            continue
        key, _, value = line.strip().partition(":")
        key = key.strip()
        value = value.strip()
        if key == "argv":
            recipes[current][key] = json.loads(value)
        else:
            recipes[current][key] = value
    return recipes


def dump_recipes(recipes: dict[str, dict[str, Any]], missing: list[str] | None = None) -> str:
    lines = [
        "# Local harness recipes. Not part of the official lock.",
        f"# Written by python3 -m metered_suite init. Edit argv here if flags change.",
        "",
    ]
    for name, rec in recipes.items():
        lines.append(f"{name}:")
        lines.append(f"  slug: {rec['slug']}")
        lines.append(f"  bin: {rec['bin']}")
        lines.append(f"  argv: {json.dumps(rec['argv'], ensure_ascii=True)}")
        lines.append("")
    if missing:
        lines.append("# Not on PATH. Uncomment and edit after you install them.")
        for name in missing:
            tmpl = next(item for item in _TEMPLATES if item["name"] == name)
            argv = json.dumps(tmpl["argv"], ensure_ascii=True)
            for key in template_keys(tmpl):
                lines.append(f"# {key}:")
                lines.append(f"#   slug: {tmpl['slug']}")
                lines.append(f"#   bin: {tmpl['bins'][0]}")
                lines.append(f"#   argv: {argv}")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_recipes(root: Path) -> dict[str, dict[str, Any]]:
    path = recipe_path(root)
    if not path.exists():
        raise SystemExit(
            f"No {RECIPE_NAME}. Run this first:\n"
            f"  python3 -m metered_suite init"
        )
    recipes = parse_recipes(path.read_text(encoding="utf-8"))
    if not recipes:
        raise SystemExit(
            f"{RECIPE_NAME} is empty. Run:\n"
            f"  python3 -m metered_suite init"
        )
    return recipes


def get_recipe(root: Path, name: str) -> dict[str, Any]:
    recipes = load_recipes(root)
    key = name.strip()
    if key not in recipes:
        known = ", ".join(sorted(recipes))
        raise SystemExit(
            f"{key} is not in {RECIPE_NAME}. Known: {known}\n"
            f"Edit {RECIPE_NAME} or run: python3 -m metered_suite init"
        )
    rec = recipes[key]
    slug = str(rec.get("slug") or key)
    return {
        "name": key,
        "slug": slug,
        "id": catalog_id(slug),
        "bin": str(rec.get("bin") or ""),
        "argv": list(rec.get("argv") or []),
    }


def render_argv(
    argv: list[str],
    *,
    binary: str,
    model: str,
    prompt: str,
    prompt_file: Path,
    effort: str = "default",
) -> list[str]:
    level = (effort or "default").strip().lower()
    drop_effort = level in {"", "default"}
    mapping = {
        "{bin}": binary,
        "{model}": model,
        "{prompt}": prompt,
        "{prompt_file}": str(prompt_file),
        "{effort}": level,
    }
    out: list[str] = []
    skip = False
    for index, item in enumerate(argv):
        if skip:
            skip = False
            continue
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if drop_effort:
            if item in _EFFORT_FLAGS:
                if nxt and not nxt.startswith("-"):
                    skip = True
                continue
            if item == "-c" and "{effort}" in nxt:
                skip = True
                continue
            if "{effort}" in item and item != "{effort}":
                continue
        rendered = item
        for token, value in mapping.items():
            rendered = rendered.replace(token, value)
        out.append(rendered)
    if not out:
        raise SystemExit("Recipe argv is empty.")
    return out


def build_command(
    root: Path,
    name: str,
    model: str,
    prompt: str,
    prompt_file: Path,
    effort: str = "default",
) -> list[str]:
    rec = get_recipe(root, name)
    binary = str(rec.get("bin") or "")
    if not binary:
        raise SystemExit(
            f"{name} has no bin in {RECIPE_NAME}. Edit that file or run:\n"
            f"  python3 -m metered_suite init"
        )
    if not rec["argv"]:
        raise SystemExit(f"{name} has an empty argv in {RECIPE_NAME}.")
    return render_argv(
        rec["argv"],
        binary=binary,
        model=model,
        prompt=prompt,
        prompt_file=prompt_file,
        effort=effort,
    )


def init_recipes(root: Path, *, path_env: str | None = None) -> tuple[Path, list[str], list[str]]:
    path = recipe_path(root)
    found: dict[str, dict[str, Any]] = {}
    if path.exists():
        found = parse_recipes(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    for tmpl in _TEMPLATES:
        keys = template_keys(tmpl)
        chosen = ""
        for bin_name in tmpl["bins"]:
            if shutil.which(bin_name, path=path_env):
                chosen = bin_name
                break
        if not chosen:
            if not any(key in found for key in keys):
                missing.append(tmpl["name"])
            continue
        argv = [chosen if item == "{bin}" else item for item in tmpl["argv"]]
        rec = {
            "slug": tmpl["slug"],
            "bin": chosen,
            "argv": argv,
        }
        for key in keys:
            if key not in found:
                found[key] = dict(rec)
    path.write_text(dump_recipes(found, missing), encoding="utf-8")
    return path, sorted(found), missing
