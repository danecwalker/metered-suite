from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
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
from .term import bold, cyan, dim, format_elapsed, green, log as _log, red, spin, yellow
from .usage import Usage, read_sidecar, write_usage


def _slug(name: str) -> str:
    out = []
    for char in name.lower():
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "model"


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
        if blob.get("is_error") or blob.get("isError") or kind in {"error", "turn.failed"}:
            message = (
                blob.get("result")
                or blob.get("message")
                or blob.get("error")
                or blob.get("errors")
                or kind
            )
            if isinstance(message, dict):
                message = message.get("message") or message.get("error") or message
            if isinstance(message, list) and message:
                message = message[0]
            text = _one_line(str(message))
            if text:
                reason = blob.get("stop_reason") or blob.get("stopReason")
                if reason:
                    text = f"{text} ({reason})"
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
        _log(dim(f"  collected patch ({len(patch.splitlines())} lines)"))
        _log(cyan("  verifier starting (docker, no network)"))
        with spin("verifier"):
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
        _log(green(f"    ✓ pass  {name}"))
    for name in failed:
        _log(red(f"    ✗ fail  {name}"))
    for detail in report.get("details") or []:
        _log(dim(f"    {_one_line(str(detail), 160)}"))
    if report.get("error") and not failed:
        _log(red(f"    {_one_line(str(report['error']))}"))
    total = len(passed) + len(failed)
    if total:
        line = f"  verifier {len(passed)}/{total} hidden tests"
        _log(green(line) if not failed else red(line))
    elif report.get("ok"):
        _log(green("  ✓ verifier pass"))
    else:
        _log(red("  ✗ verifier fail"))


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


_FAIL_HINTS = {
    "test_visibility_timeout_restores_and_counts_attempt": (
        "After lease, ready_count must be 0 and leased_count 1. When the "
        "visibility window ends, the same message is ready again and attempts + 1."
    ),
    "test_nack_then_poison": (
        "nack with a matching lease_id increments attempts. After max_attempts "
        "failed nacks or expiries, lease returns None and dead_count increases."
    ),
    "test_persist_across_processes": (
        "A new Queue(path=...) must reload leased state (leased_count and lease_id). "
        "ack on that reloaded queue deletes the message."
    ),
    "test_delay_does_not_steal_older_ready": (
        "lease the oldest ready message (available_at, then id). A delayed newer "
        "message must not be leased before an older ready one."
    ),
    "test_visibility_expires_and_counts_attempt": (
        "Visibility expiry must restore the message and increment attempts."
    ),
    "test_nack_increments_attempts": (
        "nack with the active lease_id increments attempts."
    ),
    "test_dead_after_max_attempts": (
        "After max_attempts failed attempts the message is dead and not leaseable."
    ),
    "test_persist_leased_message": (
        "Disk state must include the active lease, not only the body list."
    ),
}


def _parse_report(previous: str) -> dict:
    try:
        data = json.loads(previous)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _follow_up_prompt(
    task: OfficialTask,
    attempt: int,
    previous: str,
    *,
    reset: bool = False,
) -> str:
    report = _parse_report(previous)
    failed = [
        str(item)
        for item in (report.get("failedTests") or report.get("errors") or [])
    ]
    passed = [str(item) for item in (report.get("passedTests") or [])]
    details = [str(item) for item in (report.get("details") or [])]
    lines = [task.prompt, "", "---", f"Attempt {attempt}."]
    if reset:
        lines.append(
            "Previous turn made no progress, so this is a fresh checkout. "
            "Implement the full contract. Do not hardcode fixtures."
        )
    else:
        lines.append(
            "Same checkout as last time. Keep the files you already changed. "
            "Do not start over from scratch."
        )
    lines.append(
        "First make the public tests green: python3 -m unittest discover -s tests -v"
    )
    lines.append(
        "Then stop. Hidden tests use different numbers than the public ones."
    )
    if passed:
        lines.append("Hidden tests that already passed: " + ", ".join(passed))
    if failed:
        lines.append("Hidden tests that still fail:")
        for name in failed[:8]:
            hint = _FAIL_HINTS.get(name, "Re-read that required behavior in the prompt.")
            lines.append(f"- {name}: {hint}")
    if details:
        lines.append("Last assertion lines:")
        for item in details[:6]:
            lines.append(f"- {_one_line(item, 140)}")
    if report.get("error") and not failed:
        lines.append(f"Verifier error: {_one_line(str(report['error']))}")
    lines.append(
        "A complete finish is required. The hidden verifier must return "
        '{"ok":true,"reward":1,"failed":0}.'
    )
    return "\n".join(lines) + "\n"


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
    t0 = time.monotonic()
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
        bold(
            f"{spec['slug']}  {sku}  {effort}  {len(tasks)} tasks  "
            f"{_attempt_label(max_attempts)}  timeout {timeout_sec}s"
        )
    )
    _log(
        dim(
            f"suite {SUITE_VERSION}  {lock['suiteHash'][:12]}  "
            f"{lock['workMu']} MU  docker grades hidden tests"
        )
    )

    for index, task in enumerate(tasks, start=1):
        usage = Usage()
        output = ""
        attempts = 0
        passed = False
        workspace: Path | None = None
        last_sig: tuple | None = None
        reset_next = False
        _log(f"task {index}/{len(tasks)}  {task.id}")
        try:
            attempt = 0
            while True:
                attempt += 1
                if max_attempts > 0 and attempt > max_attempts:
                    break
                attempts = attempt
                _log(bold(f"  attempt {attempt}/{_attempt_label(max_attempts)}"))
                if workspace is None:
                    workspace = Path(tempfile.mkdtemp(prefix=f"metered-{task.id}-"))
                    _log(cyan(f"  sandbox dir  {workspace}"))
                    _log(dim(f"  inspect with:  ls {workspace} && git -C {workspace} diff"))
                    if task.task_dir is not None:
                        try:
                            with spin("seeding sandbox from docker"):
                                seed_workspace(task.task_dir, workspace)
                        except SandboxError as error:
                            raise SystemExit(f"sandbox: {error}") from error
                    _init_workspace(workspace)
                else:
                    _log(cyan(f"  sandbox dir  {workspace}"))
                prompt = (
                    task.prompt
                    if attempt == 1
                    else _follow_up_prompt(
                        task, attempt, output, reset=reset_next
                    )
                )
                reset_next = False
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
                _log(dim(f"  {_command_preview(command, prompt)}"))
                if task.task_dir is not None and attempt == 1:
                    _log(dim(f"  mode {describe_sandbox(command)}"))
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
                        with spin("harness"):
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
                    status = yellow("  timeout")
                elif exit_code == 0:
                    status = dim(f"  exit {exit_code}")
                else:
                    status = yellow(f"  exit {exit_code}")
                if turn_usage.counted():
                    status = f"{status}  {dim(_usage_brief(turn_usage))}"
                hint = _cli_error_brief(stdout, stderr)
                if hint and (timed_out or exit_code not in {0, None} or not turn_usage.counted()):
                    status = f"{status}  {red(hint)}"
                _log(status)
                output = _score_attempt(task, workspace)
                passed = score_json(output, task.expected)
                if task.task_dir is not None:
                    _keep_attempt(root / "out", task.id, attempt, workspace, output)
                if passed:
                    break
                if max_attempts > 0 and attempt >= max_attempts:
                    break
                try:
                    report = json.loads(output)
                except json.JSONDecodeError:
                    report = {}
                failed = tuple(
                    str(item)
                    for item in (
                        (report.get("failedTests") if isinstance(report, dict) else None)
                        or (report.get("errors") if isinstance(report, dict) else None)
                        or []
                    )
                )
                patch_path = workspace / "_grade" / "in" / "changes.patch"
                patch_sig = (
                    patch_path.read_bytes() if patch_path.exists() else b""
                )
                sig = (hash(patch_sig), failed)
                if last_sig == sig:
                    _log(yellow("  no progress, new checkout"))
                    shutil.rmtree(workspace, ignore_errors=True)
                    workspace = None
                    reset_next = True
                    last_sig = None
                else:
                    last_sig = sig
                    _log(yellow("  same checkout, continuing until pass"))
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
        summary = f"{task.id}: {'pass' if passed else 'fail'} after {attempts} attempt(s){note}"
        _log(green(f"✓ {summary}") if passed else red(f"✗ {summary}"))

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
    _log_run_summary(pkg, path, raw_tasks, time.monotonic() - t0)
    return path


def _log_run_summary(pkg: dict, path: Path, raw_tasks: list[dict], elapsed: float) -> None:
    totals = pkg["totals"]
    attempts = sum(int(task.get("attempts") or 0) for task in raw_tasks)
    complete = int(totals["passed"]) == int(totals["tasks"])
    _log("")
    _log(bold("summary"))
    result = f"{totals['passed']}/{totals['tasks']} passed"
    _log(green(f"  {result}") if complete else red(f"  {result}"))
    _log(f"  time      {format_elapsed(elapsed)}")
    _log(f"  attempts  {attempts}")
    _log(
        f"  tokens    in={totals['input']} out={totals['output']} "
        f"reasoning={totals['reasoning']} cacheHit={totals['cacheHit']}"
    )
    _log(cyan(f"  wrote     {path}"))
    billed = int(totals["input"]) + int(totals["output"]) + int(totals["reasoning"])
    if billed <= 0:
        _log(
            yellow(
                "  warning   no token counts. Metered will not rank this as $ / MU."
            )
        )
    elif not complete:
        _log(yellow("  warning   incomplete. $ / MU needs every official task to pass."))
