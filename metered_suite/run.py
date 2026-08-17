from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .adapters import adapter_for
from .hash import SUITE_VERSION
from .identity import build_command, resolve_harness, sku_fits
from .score import score_json
from .seal import seal_package
from .tasks import load_tasks, suite_lock
from .usage import Usage, read_sidecar, write_usage


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


def _init_workspace(workspace: Path) -> None:
    git = shutil.which("git")
    if not git:
        return
    subprocess.run(
        [git, "init"],
        cwd=workspace,
        check=False,
        capture_output=True,
        timeout=10,
    )


def _read_output(workspace: Path) -> str:
    for name in ("answer.json", "out.json"):
        path = workspace / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _collect_usage(slug: str, stdout: str, stderr: str, workspace: Path) -> Usage:
    parsed = adapter_for(slug).parse(stdout, stderr, workspace)
    if parsed.counted():
        write_usage(workspace, parsed)
        return parsed
    sidecar = read_sidecar(workspace)
    if sidecar.counted():
        return sidecar
    write_usage(workspace, Usage())
    return Usage()


def run_suite(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent
    cfg = _load_user_config(root)
    tasks = load_tasks()
    lock = suite_lock(tasks)
    started = datetime.now(timezone.utc).isoformat()
    raw_tasks: list[dict] = []
    max_attempts = int(cfg.get("MAX_ATTEMPTS") or 3)
    spec = resolve_harness(str(cfg["HARNESS"]))
    sku = str(cfg["MODEL"]).strip()
    if not sku_fits(spec, sku):
        raise SystemExit(
            f"MODEL {sku} cannot be filed under the {spec['slug']} harness."
        )

    for task in tasks:
        usage = Usage()
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
                _init_workspace(workspace)
                flags = list(cfg.get("FLAGS") or [])
                command = build_command(
                    spec,
                    sku,
                    flags,
                    prompt,
                    prompt_file,
                    str(cfg.get("EFFORT") or "default"),
                )
                env = os.environ.copy()
                env["METERED_TASK"] = task.id
                env["METERED_WORKSPACE"] = str(workspace)
                stdout = ""
                stderr = ""
                try:
                    proc = subprocess.run(
                        command,
                        cwd=workspace,
                        env=env,
                        check=False,
                        timeout=60 * 20,
                        capture_output=True,
                        text=True,
                    )
                    stdout = proc.stdout or ""
                    stderr = proc.stderr or ""
                except FileNotFoundError as error:
                    raise SystemExit(
                        f"harness command not found: {command[0]}\n"
                        "Install that CLI, or change HARNESS in main.py."
                    ) from error
                except subprocess.TimeoutExpired as error:
                    stdout = (error.stdout or "") if isinstance(error.stdout, str) else ""
                    stderr = (error.stderr or "") if isinstance(error.stderr, str) else ""
                turn_usage = _collect_usage(spec["slug"], stdout, stderr, workspace)
                usage = usage.add(turn_usage)
                output = _read_output(workspace)
                passed = score_json(output, task.expected)
                if passed:
                    break
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
        raw_tasks.append(
            {
                "id": task.id,
                "output": output,
                "usage": usage.as_dict(),
                "attempts": attempts,
                "providerUsage": {"source": usage.source} if usage.counted() else None,
            }
        )
        note = ""
        if not usage.counted():
            note = " — no token usage from the CLI; this task cannot define $ / M ET"
        print(f"{task.id}: {'pass' if passed else 'fail'} after {attempts} attempt(s){note}")

    finished = datetime.now(timezone.utc).isoformat()
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
    billed = (
        int(pkg["totals"]["input"])
        + int(pkg["totals"]["output"])
        + int(pkg["totals"]["reasoning"])
    )
    if billed <= 0:
        print(
            "warning: package has no token counts. "
            "Metered will not rank it as $ / M ET."
        )
    return path
