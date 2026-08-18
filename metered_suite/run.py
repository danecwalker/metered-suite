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
from .sandbox import (
    SandboxError,
    collect_patch,
    describe_sandbox,
    grade_patch,
    run_agent,
    seed_workspace,
)
from .score import score_json
from .seal import seal_package
from .tasks import OfficialTask, load_tasks, suite_lock
from .usage import Usage, read_sidecar, write_usage


def _slug(name: str) -> str:
    out = []
    for char in name.lower():
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "model"


def _log(message: str) -> None:
    print(message, flush=True)


def _command_preview(command: list[str], prompt: str = "") -> str:
    """Short argv for progress. Never include the prompt body."""
    if not command:
        return ""
    prompt_flags = {"--prompt", "--single", "-p"}
    parts: list[str] = []
    skip_next = False
    for index, arg in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if index == 0:
            parts.append(os.path.basename(arg))
            continue
        if prompt and arg == prompt:
            continue
        if arg in prompt_flags:
            parts.append(arg)
            nxt = command[index + 1] if index + 1 < len(command) else ""
            if nxt and not nxt.startswith("-"):
                skip_next = True
            continue
        if arg.startswith("--prompt=") or arg.startswith("--single="):
            parts.append(arg.split("=", 1)[0])
            continue
        if "\n" in arg or len(arg) > 96:
            continue
        parts.append(arg)
    return " ".join(parts)


def _usage_brief(usage: Usage) -> str:
    return (
        f"in={usage.input} out={usage.output} "
        f"reasoning={usage.reasoning} cacheHit={usage.cache_hit}"
    )


def _one_line(text: str, limit: int = 220) -> str:
    line = " ".join((text or "").split())
    if len(line) <= limit:
        return line
    return line[: limit - 3] + "..."


def _cli_error_brief(stdout: str, stderr: str) -> str:
    from .usage import json_blobs

    for blob in json_blobs(stderr) + json_blobs(stdout):
        if not isinstance(blob, dict):
            continue
        kind = str(blob.get("type") or "")
        if kind in {"error", "turn.failed"}:
            message = blob.get("message") or blob.get("error") or blob
            if isinstance(message, dict):
                message = message.get("message") or message.get("error") or message
            text = _one_line(str(message))
            if text:
                return text
        payload = blob.get("payload")
        if isinstance(payload, dict) and payload.get("type") in {"error", "stream_error"}:
            text = _one_line(str(payload.get("message") or payload))
            if text:
                return text
    for raw in (stderr, stdout):
        for line in reversed((raw or "").splitlines()):
            text = _one_line(line.strip())
            if text:
                return text
    return ""


def _load_user_config(root: Path) -> dict:
    namespace: dict = {}
    exec((root / "main.py").read_text(encoding="utf-8"), namespace)
    required = ["HARNESS", "MODEL", "EFFORT"]
    missing = [key for key in required if key not in namespace]
    if missing:
        raise SystemExit(f"main.py is missing: {', '.join(missing)}")
    return namespace


def _init_workspace(workspace: Path) -> None:
    if (workspace / ".git").exists():
        return
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


def _score_attempt(task: OfficialTask, workspace: Path) -> str:
    if task.task_dir is None:
        return _read_output(workspace)
    try:
        patch = collect_patch(workspace)
        _log(f"  collected patch ({len(patch.splitlines())} lines)")
        _log("  verifier starting (docker, no network)")
        report = grade_patch(task.task_dir, patch, workspace / "_grade")
    except SandboxError as error:
        _log(f"  sandbox: {error}")
        return json.dumps({"ok": False, "reward": 0, "failed": 1, "error": str(error)})
    _log_verifier_report(report)
    return json.dumps(report, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _log_verifier_report(report: dict) -> None:
    passed = [str(item) for item in (report.get("passedTests") or [])]
    failed = [str(item) for item in (report.get("failedTests") or report.get("errors") or [])]
    for name in passed:
        _log(f"    pass  {name}")
    for name in failed:
        _log(f"    fail  {name}")
    for detail in report.get("details") or []:
        _log(f"    {_one_line(str(detail), 160)}")
    if report.get("error") and not failed:
        _log(f"    {_one_line(str(report['error']))}")
    total = len(passed) + len(failed)
    if total:
        _log(f"  verifier {len(passed)}/{total} hidden tests")
    elif report.get("ok"):
        _log("  verifier pass")
    else:
        _log("  verifier fail")


def _verifier_brief(output: str) -> str:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return _one_line(output)
    if not isinstance(data, dict):
        return ""
    failed = data.get("failedTests") or data.get("errors")
    if isinstance(failed, list) and failed:
        return "failed " + ", ".join(str(item) for item in failed[:8])
    err = data.get("error")
    if err:
        return _one_line(str(err))
    return ""


def _attempt_label(max_attempts: int) -> str:
    return "until pass" if max_attempts <= 0 else str(max_attempts)


def _follow_up_prompt(task: OfficialTask, attempt: int, previous: str) -> str:
    why = _verifier_brief(previous)
    extra = f"Failed checks: {why}\n" if why else ""
    return (
        f"{task.prompt}\n\n---\n"
        f"Attempt {attempt}. Same checkout as last time. Do not start over.\n"
        "The hidden verifier still fails. A complete finish is required.\n"
        f"{extra}"
        f"Previous verifier output:\n{previous}\n"
        "Fix the existing code until the hidden verifier returns "
        '{"ok":true,"reward":1,"failed":0}.\n'
    )


def _keep_attempt(out_dir: Path, task_id: str, attempt: int, workspace: Path, output: str) -> None:
    dest = out_dir / f"{task_id}.last"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "reward.json").write_text(output + ("" if output.endswith("\n") else "\n"), encoding="utf-8")
    (dest / "attempt.txt").write_text(f"{attempt}\n", encoding="utf-8")
    incoming = workspace / "_grade" / "in" / "changes.patch"
    log = workspace / "_grade" / "out" / "unittest.log"
    if incoming.exists():
        shutil.copy2(incoming, dest / "changes.patch")
    if log.exists():
        shutil.copy2(log, dest / "unittest.log")


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
    max_attempts = int(cfg["MAX_ATTEMPTS"]) if cfg.get("MAX_ATTEMPTS") is not None else 0
    timeout_sec = int(cfg.get("TIMEOUT_SEC") or 45 * 60)
    spec = resolve_harness(str(cfg["HARNESS"]))
    sku = str(cfg["MODEL"]).strip()
    if not sku_fits(spec, sku):
        raise SystemExit(
            f"MODEL {sku} cannot be filed under the {spec['slug']} harness."
        )
    effort = str(cfg.get("EFFORT") or "default")
    _log(
        f"{spec['slug']}  {sku}  {effort}  {len(tasks)} tasks  "
        f"{_attempt_label(max_attempts)}  timeout {timeout_sec}s"
    )

    for index, task in enumerate(tasks, start=1):
        usage = Usage()
        output = ""
        attempts = 0
        passed = False
        workspace: Path | None = None
        _log(f"task {index}/{len(tasks)}  {task.id}")
        try:
            attempt = 0
            while True:
                attempt += 1
                if max_attempts > 0 and attempt > max_attempts:
                    break
                attempts = attempt
                _log(f"  attempt {attempt}/{_attempt_label(max_attempts)}")
                if workspace is None:
                    workspace = Path(tempfile.mkdtemp(prefix=f"metered-{task.id}-"))
                    if task.task_dir is not None:
                        try:
                            seed_workspace(task.task_dir, workspace)
                        except SandboxError as error:
                            raise SystemExit(f"sandbox: {error}") from error
                    _init_workspace(workspace)
                prompt = (
                    task.prompt
                    if attempt == 1
                    else _follow_up_prompt(task, attempt, output)
                )
                prompt_file = workspace / "instruction.md"
                prompt_file.write_text(prompt, encoding="utf-8")
                flags = list(cfg.get("FLAGS") or [])
                command = build_command(
                    spec,
                    sku,
                    flags,
                    prompt,
                    prompt_file,
                    effort,
                )
                _log(f"  {_command_preview(command, prompt)}")
                if task.task_dir is not None and attempt == 1:
                    _log(f"  sandbox {describe_sandbox(command)}")
                env = os.environ.copy()
                env["METERED_TASK"] = task.id
                env["METERED_WORKSPACE"] = str(workspace)
                env["METERED_ATTEMPT"] = str(attempt)
                stdout = ""
                stderr = ""
                timed_out = False
                exit_code: int | None = None
                try:
                    if task.task_dir is not None:
                        proc = run_agent(
                            command,
                            workspace=workspace,
                            env=env,
                            timeout=timeout_sec,
                            task_dir=task.task_dir,
                        )
                    else:
                        proc = subprocess.run(
                            command,
                            cwd=workspace,
                            env=env,
                            check=False,
                            timeout=timeout_sec,
                            capture_output=True,
                            text=True,
                        )
                    stdout = proc.stdout or ""
                    stderr = proc.stderr or ""
                    exit_code = proc.returncode
                except FileNotFoundError as error:
                    raise SystemExit(
                        f"harness command not found: {command[0]}\n"
                        "Install that CLI, or change HARNESS in main.py."
                    ) from error
                except subprocess.TimeoutExpired as error:
                    timed_out = True
                    stdout = (error.stdout or "") if isinstance(error.stdout, str) else ""
                    stderr = (error.stderr or "") if isinstance(error.stderr, str) else ""
                turn_usage = _collect_usage(spec["slug"], stdout, stderr, workspace)
                usage = usage.add(turn_usage)
                if timed_out:
                    status = "  timeout"
                else:
                    status = f"  exit {exit_code}"
                if turn_usage.counted():
                    status = f"{status}  {_usage_brief(turn_usage)}"
                hint = _cli_error_brief(stdout, stderr)
                if hint and (timed_out or exit_code not in {0, None} or not turn_usage.counted()):
                    status = f"{status}  {hint}"
                _log(status)
                output = _score_attempt(task, workspace)
                passed = score_json(output, task.expected)
                if task.task_dir is not None:
                    _keep_attempt(root / "out", task.id, attempt, workspace, output)
                if passed:
                    break
                if max_attempts > 0 and attempt >= max_attempts:
                    break
                _log("  same checkout, continuing until pass")
        finally:
            if workspace is not None:
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
            note = " - no token usage from the CLI; this task cannot define $ / MU"
        _log(f"{task.id}: {'pass' if passed else 'fail'} after {attempts} attempt(s){note}")

    finished = datetime.now(timezone.utc).isoformat()
    stack = {
        "modelName": sku,
        "modelSlug": _slug(sku),
        "lab": "",
        "harnessId": spec["id"],
        "harnessSlug": spec["slug"],
        "provider": "",
        "sku": sku,
        "setting": effort,
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
    _log(f"wrote {path}")
    _log(f"passed {pkg['totals']['passed']}/{pkg['totals']['tasks']}")
    billed = (
        int(pkg["totals"]["input"])
        + int(pkg["totals"]["output"])
        + int(pkg["totals"]["reasoning"])
    )
    if billed <= 0:
        _log(
            "warning: package has no token counts. "
            "Metered will not rank it as $ / MU."
        )
    return path
