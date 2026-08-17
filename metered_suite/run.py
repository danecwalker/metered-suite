from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .hash import SUITE_VERSION
from .identity import build_command, resolve_harness, sku_fits
from .score import score_json
from .seal import seal_package
from .tasks import load_tasks, suite_lock


def _slug(name: str) -> str:
    out = []
    for char in name.lower():
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "model"


def _load_user_config(root: Path) -> dict:
    namespace: dict = {}
    exec((root / "main.py").read_text(encoding="utf-8"), namespace)
    required = ["HARNESS", "MODEL", "EFFORT"]
    missing = [key for key in required if key not in namespace]
    if missing:
        raise SystemExit(f"main.py is missing: {', '.join(missing)}")
    return namespace


def _render_command(command: list[str] | str, prompt: str, prompt_file: Path, cfg: dict) -> list[str]:
    mapping = {
        "{prompt}": prompt,
        "{prompt_file}": str(prompt_file),
        "{model}": str(cfg.get("MODEL", "")),
        "{effort}": str(cfg.get("EFFORT", "")),
        "{task_id}": prompt_file.parent.name,
    }
    if isinstance(command, str):
        rendered = command
        for key, value in mapping.items():
            rendered = rendered.replace(key, value)
        return ["bash", "-lc", rendered]
    return [mapping.get(part, part) for part in command]


def _read_usage(workspace: Path) -> dict:
    path = workspace / "usage.json"
    if not path.exists():
        return {"input": 0, "output": 0, "reasoning": 0, "cacheHit": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "input": int(data.get("input") or 0),
        "output": int(data.get("output") or 0),
        "reasoning": int(data.get("reasoning") or data.get("thinking") or 0),
        "cacheHit": int(data.get("cacheHit") or data.get("cache_hit") or 0),
    }


def _read_output(workspace: Path) -> str:
    for name in ("answer.json", "out.json"):
        path = workspace / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def run_suite(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent
    cfg = _load_user_config(root)
    tasks = load_tasks()
    lock = suite_lock(tasks)
    started = datetime.now(timezone.utc).isoformat()
    raw_tasks: list[dict] = []
    max_attempts = int(cfg.get("MAX_ATTEMPTS") or 3)

    for task in tasks:
        usage = {"input": 0, "output": 0, "reasoning": 0, "cacheHit": 0}
        output = ""
        attempts = 0
        passed = False
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            workspace = Path(tempfile.mkdtemp(prefix=f"metered-{task.id}-"))
            try:
                prompt_file = workspace / "instruction.md"
                prompt = task.prompt
                if attempt > 1:
                    prompt = (
                        f"{task.prompt}\n\n---\nAttempt {attempt}. "
                        "The previous answer.json failed the official check.\n"
                        f"Previous answer:\n{output}\n"
                    )
                prompt_file.write_text(prompt, encoding="utf-8")
                spec = resolve_harness(str(cfg["HARNESS"]))
                flags = list(cfg.get("FLAGS") or [])
                command = _render_command(
                    build_command(spec, str(cfg["MODEL"]), flags),
                    prompt,
                    prompt_file,
                    cfg,
                )
                env = os.environ.copy()
                env["METERED_TASK"] = task.id
                env["METERED_WORKSPACE"] = str(workspace)
                try:
                    subprocess.run(
                        command,
                        cwd=workspace,
                        env=env,
                        check=False,
                        timeout=60 * 20,
                    )
                except FileNotFoundError as error:
                    raise SystemExit(
                        f"harness command not found: {command[0]}\n"
                        "Install that CLI, or change HARNESS in main.py."
                    ) from error
                except subprocess.TimeoutExpired:
                    pass
                output = _read_output(workspace)
                turn_usage = _read_usage(workspace)
                usage = {
                    key: usage[key] + turn_usage[key] for key in usage
                }
                passed = score_json(output, task.expected)
                if passed:
                    break
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
        raw_tasks.append(
            {
                "id": task.id,
                "output": output,
                "usage": usage,
                "attempts": attempts,
                "providerUsage": None,
            }
        )
        print(f"{task.id}: {'pass' if passed else 'fail'} after {attempts} attempt(s)")

    finished = datetime.now(timezone.utc).isoformat()
    spec = resolve_harness(str(cfg["HARNESS"]))
    sku = str(cfg["MODEL"]).strip()
    if not sku_fits(spec, sku):
        raise SystemExit(
            f"MODEL {sku} cannot be filed under the {spec['slug']} harness."
        )
    stack = {
        "modelName": sku,
        "modelSlug": _slug(sku),
        "lab": "",
        "harnessId": spec["id"],
        "harnessSlug": spec["slug"],
        "provider": "",
        "sku": sku,
        "setting": str(cfg["EFFORT"]),
        "listInput": 0,
        "listOutput": 0,
    }
    pkg = seal_package(
        suite_version=SUITE_VERSION,
        suite_hash=lock["suiteHash"],
        stack=stack,
        started_at=started,
        finished_at=finished,
        raw_tasks=raw_tasks,
        official=tasks,
    )
    out_dir = root / "out"
    out_dir.mkdir(exist_ok=True)
    name = f"{stack['modelSlug']}-{stack['harnessSlug']}-{stack['setting']}.metered.json"
    path = out_dir / name
    path.write_text(json.dumps(pkg, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    print(f"passed {pkg['totals']['passed']}/{pkg['totals']['tasks']}")
    return path
