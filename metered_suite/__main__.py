from __future__ import annotations

import json
import sys
from pathlib import Path

from .recipe import RECIPE_NAME, get_recipe, init_recipes, load_recipes, recipe_path
from .run import run_suite
from .tasks import suite_lock

ROOT = Path(__file__).resolve().parent.parent
_RESERVED = {"init", "lock", "help", "-h", "--help"}


def _recipe_names(root: Path) -> list[str]:
    path = recipe_path(root)
    if not path.exists():
        return []
    try:
        return sorted(load_recipes(root))
    except SystemExit:
        return []


def _help(root: Path | None = None) -> str:
    here = root or ROOT
    names = _recipe_names(here)
    if names:
        harness_line = f"  harnesses in {RECIPE_NAME}: {', '.join(names)}\n"
        sample = names[0]
        example = f"  python3 -m metered_suite {sample} --model <sku> --effort max\n"
    else:
        harness_line = f"  no {RECIPE_NAME} yet. Run init first.\n"
        example = "  python3 -m metered_suite <harness> --model <sku> --effort max\n"
    return (
        "metered-suite - official jobs for Metered pricing.\n"
        "\n"
        "  python3 -m metered_suite init\n"
        "  python3 -m metered_suite <harness> --model <sku> [--effort LEVEL]\n"
        "  python3 -m metered_suite lock\n"
        "\n"
        f"{harness_line}"
        "  --effort        none | low | medium | high | xhigh | max | default\n"
        "  --max-attempts  0 = keep the same checkout until the job passes\n"
        "  --timeout       seconds per attempt (default 2700)\n"
        "\n"
        f"Approve flags live in {RECIPE_NAME}. Pass only harness, model, and effort.\n"
        "\n"
        "Examples:\n"
        "  python3 -m metered_suite init\n"
        f"{example}"
    )


def _take(argv: list[str], index: int) -> tuple[str, int]:
    if index >= len(argv):
        raise SystemExit(_help())
    return argv[index], index + 1


def parse_run(argv: list[str]) -> dict:
    if not argv:
        raise SystemExit(_help())
    harness = argv[0]
    if harness in _RESERVED:
        raise SystemExit(_help())
    model = ""
    effort = "default"
    max_attempts = 0
    timeout = 45 * 60
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--model":
            model, index = _take(argv, index + 1)
        elif token.startswith("--model="):
            model = token.split("=", 1)[1]
            index += 1
        elif token == "--effort":
            effort, index = _take(argv, index + 1)
        elif token.startswith("--effort="):
            effort = token.split("=", 1)[1]
            index += 1
        elif token == "--max-attempts":
            raw, index = _take(argv, index + 1)
            max_attempts = int(raw)
        elif token.startswith("--max-attempts="):
            max_attempts = int(token.split("=", 1)[1])
            index += 1
        elif token == "--timeout":
            raw, index = _take(argv, index + 1)
            timeout = int(raw)
        elif token.startswith("--timeout="):
            timeout = int(token.split("=", 1)[1])
            index += 1
        else:
            raise SystemExit(_help())
    if not model:
        raise SystemExit(_help())
    return {
        "HARNESS": harness,
        "MODEL": model,
        "EFFORT": effort,
        "MAX_ATTEMPTS": max_attempts,
        "TIMEOUT_SEC": timeout,
    }


def main(argv: list[str] | None = None, *, root: Path | None = None) -> None:
    here = root or ROOT
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_help(here), end="", flush=True)
        return
    if args[0] == "init":
        path, found, missing = init_recipes(here)
        print(f"wrote {path}", flush=True)
        if found:
            print("  ready: " + ", ".join(found), flush=True)
        if missing:
            print("  not on PATH: " + ", ".join(missing), flush=True)
        return
    if args[0] == "lock":
        lock = suite_lock()
        path = here / "lock.json"
        path.write_text(json.dumps(lock, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}  {lock['suiteVersion']}  {lock['suiteHash'][:16]}…", flush=True)
        return
    get_recipe(here, args[0])
    run_suite(here, parse_run(args))


if __name__ == "__main__":
    main()
