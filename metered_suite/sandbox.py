"""DeepSWE / Harbor / Pier sandbox.

Two containers, same split as DeepSWE v1.1
(https://deepswe.datacurve.ai/blog/deepswe-v1-1, arXiv:2607.07946):

  Agent
    Official repo only. No hidden tests. No gold history past `base`.
    Network stays up so the harness CLI can reach the lab API (Pier).
    Resource-capped. No docker.sock. Not privileged.

  Verifier
    Fresh image. Apply the collected git patch. Run held-out tests.
    `--network none`.

Metered still measures *your* harness (Claude Code, Codex, Grok, …),
not mini-swe-agent. Those CLIs are Darwin binaries on a Mac and cannot
exec inside Docker Desktop's Linux VM. So:

  Linux ELF CLI  -> the process runs inside the agent container
  Darwin CLI     -> the process stays on the host, jailed to the
                    Docker-seeded workspace; grade is still Docker

The grade is never "trust the agent's machine."
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .live import run_command

AGENT_IMAGE = "metered-suite-agent:py2"
VERIFY_IMAGE = "metered-suite-verify:py2.1"

_API_ENV_PREFIXES = (
    "ANTHROPIC",
    "OPENAI",
    "XAI",
    "GROK",
    "GOOGLE",
    "GEMINI",
    "DASHSCOPE",
    "MOONSHOT",
    "KIMI",
    "DEEPSEEK",
    "OPENROUTER",
    "CLAUDE",
    "CODEX",
    "QWEN",
    "PI_CODING",
)

_CONFIG_DIRS = (
    ".claude",
    ".codex",
    ".grok",
    ".config",
    ".local",
    ".kimi-code",
    ".qwen",
    ".npm",
)

_SECRET_DENY = (".ssh", ".aws", ".gnupg", ".netrc")


class SandboxError(RuntimeError):
    pass


def _docker(*args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    if shutil.which("docker") is None:
        raise SandboxError("docker is required to grade the official job")
    return subprocess.run(["docker", *args], check=check, **kwargs)


def _image_exists(tag: str) -> bool:
    proc = _docker("image", "inspect", tag, check=False, capture_output=True)
    return proc.returncode == 0


def is_linux_binary(path: str) -> bool:
    candidate = shutil.which(path) or path
    try:
        with open(candidate, "rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def describe_sandbox(command: list[str]) -> str:
    if command and is_linux_binary(command[0]):
        return "docker-agent + docker-verifier"
    if sys.platform == "darwin":
        return "host-cli (darwin) + docker-verifier"
    return "host-cli + docker-verifier"


def ensure_images(task_dir: Path, force: bool | None = None) -> None:
    if force is None:
        force = os.environ.get("METERED_REBUILD") == "1"
    env = task_dir / "environment"
    if force or not _image_exists(AGENT_IMAGE):
        _docker(
            "build",
            "-t",
            AGENT_IMAGE,
            "-f",
            str(env / "Dockerfile"),
            str(env),
        )
    if force or not _image_exists(VERIFY_IMAGE):
        _docker(
            "build",
            "-t",
            VERIFY_IMAGE,
            "-f",
            str(env / "Dockerfile.verify"),
            str(task_dir),
        )


def seed_workspace(task_dir: Path, dest: Path) -> None:
    """Copy /workspace out of the agent image. Hidden tests stay out."""
    ensure_images(task_dir)
    dest.mkdir(parents=True, exist_ok=True)
    created = _docker("create", AGENT_IMAGE, capture_output=True, text=True)
    cid = (created.stdout or "").strip()
    if not cid:
        raise SandboxError("docker create produced no container id")
    try:
        _docker("cp", f"{cid}:/workspace/.", f"{dest}/", capture_output=True)
    finally:
        _docker("rm", "-f", cid, check=False, capture_output=True)

    git_info = dest / ".git" / "info"
    git_info.mkdir(parents=True, exist_ok=True)
    exclude = git_info / "exclude"
    extra = "instruction.md\n_grade/\n.tmp/\n"
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if extra not in current:
        exclude.write_text(current + extra, encoding="utf-8")


def collect_patch(workspace: Path) -> str:
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=False, capture_output=True)
    proc = subprocess.run(
        ["git", "diff", "--cached", "--binary"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


def _verifier_timeout() -> int:
    raw = os.environ.get("METERED_VERIFY_TIMEOUT", "120")
    try:
        return max(30, int(raw))
    except ValueError:
        return 120


def grade_patch(task_dir: Path, patch: str, work: Path) -> dict:
    ensure_images(task_dir)
    incoming = work / "in"
    outgoing = work / "out"
    incoming.mkdir(parents=True, exist_ok=True)
    outgoing.mkdir(parents=True, exist_ok=True)
    (incoming / "changes.patch").write_text(patch, encoding="utf-8")
    try:
        _docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{incoming}:/in:ro",
            "-v",
            f"{outgoing}:/out",
            VERIFY_IMAGE,
            timeout=_verifier_timeout(),
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as error:
        raise SandboxError("verifier timed out") from error
    except subprocess.CalledProcessError as error:
        raise SandboxError(
            f"verifier container failed: {(error.stderr or error.stdout or '')[-400:]}"
        ) from error
    reward = outgoing / "reward.json"
    if not reward.exists():
        return {"ok": False, "reward": 0, "failed": 1}
    data = json.loads(reward.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"ok": False, "reward": 0, "failed": 1}
    return data


def _is_api_env(key: str) -> bool:
    for prefix in _API_ENV_PREFIXES:
        if key == prefix or key.startswith(prefix + "_"):
            return True
    return False


def _resolved_command(command: list[str]) -> list[str]:
    if not command:
        return command
    found = shutil.which(command[0])
    if found:
        return [found, *command[1:]]
    return command


def _run_in_agent_container(
    command: list[str],
    workspace: Path,
    env: dict,
    timeout: int,
) -> subprocess.CompletedProcess:
    binary = Path(command[0]).resolve()
    inner = [f"/opt/metered-cli/{binary.name}", *command[1:]]
    args: list[str] = [
        "run",
        "--rm",
        "--network",
        "bridge",
        "--memory",
        os.environ.get("METERED_AGENT_MEMORY", "4g"),
        "--cpus",
        os.environ.get("METERED_AGENT_CPUS", "2"),
        "--pids-limit",
        "512",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-w",
        "/workspace",
        "-v",
        f"{workspace}:/workspace",
        "-v",
        f"{binary}:/opt/metered-cli/{binary.name}:ro",
    ]
    for key, value in env.items():
        if _is_api_env(key) and value:
            args.extend(["-e", f"{key}={value}"])
    home = Path.home()
    for rel in _CONFIG_DIRS:
        host = home / rel
        if host.exists():
            args.extend(["-v", f"{host}:/root/{rel}"])
    args.append(AGENT_IMAGE)
    args.extend(inner)
    return run_command(
        ["docker", *args],
        cwd=None,
        env=os.environ.copy(),
        timeout=timeout,
        watch=workspace,
    )


def _seatbelt_profile(workspace: Path, task_dir: Path | None) -> str:
    home = Path.home()
    allow_write = [
        workspace,
        Path("/tmp"),
        Path("/private/tmp"),
        Path("/var/folders"),
        Path("/private/var/folders"),
    ]
    for rel in _CONFIG_DIRS:
        allow_write.append(home / rel)
    allow_write.append(home / "Library" / "Caches")
    allow_write.append(home / "Library" / "Application Support")
    allow_write.append(home / "Library" / "Logs")
    deny_read = []
    if task_dir is not None:
        deny_read.append(task_dir / "tests")
        deny_read.append(task_dir / "solution")
    for rel in _SECRET_DENY:
        deny_read.append(home / rel)

    def subpath(path: Path) -> str:
        return f'(subpath "{path}")'

    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
    ]
    for path in allow_write:
        lines.append(f"(allow file-write* {subpath(path)})")
    for path in deny_read:
        lines.append(f"(deny file-read* {subpath(path)})")
    return "\n".join(lines) + "\n"


def _run_host_jail(
    command: list[str],
    workspace: Path,
    env: dict,
    timeout: int,
    task_dir: Path | None,
) -> subprocess.CompletedProcess:
    tmp = workspace / ".tmp"
    tmp.mkdir(exist_ok=True)
    run_env = dict(env)
    run_env["TMPDIR"] = str(tmp)
    sandbox = shutil.which("sandbox-exec")
    if sandbox and os.environ.get("METERED_HOST_JAIL", "1") != "0":
        profile = tmp / "seatbelt.sb"
        profile.write_text(_seatbelt_profile(workspace, task_dir), encoding="utf-8")
        jailed = [sandbox, "-f", str(profile), *command]
        proc = run_command(
            jailed,
            cwd=workspace,
            env=run_env,
            timeout=timeout,
            watch=workspace,
        )
        text = (proc.stderr or "") + (proc.stdout or "")
        if "sandbox-exec:" in text and proc.returncode != 0:
            return run_command(
                command,
                cwd=workspace,
                env=run_env,
                timeout=timeout,
                watch=workspace,
            )
        return proc
    return run_command(
        command,
        cwd=workspace,
        env=run_env,
        timeout=timeout,
        watch=workspace,
    )


def run_agent(
    command: list[str],
    workspace: Path,
    env: dict,
    timeout: int,
    task_dir: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run the harness CLI as isolated as this host allows."""
    command = _resolved_command(command)
    force_host = os.environ.get("METERED_SANDBOX") == "host"
    force_docker = os.environ.get("METERED_SANDBOX") == "docker"
    linux = bool(command) and is_linux_binary(command[0])
    if task_dir is not None and (force_docker or (linux and not force_host)):
        ensure_images(task_dir)
        try:
            return _run_in_agent_container(command, workspace, env, timeout)
        except subprocess.TimeoutExpired:
            raise
        except SandboxError:
            if force_docker:
                raise
    return _run_host_jail(command, workspace, env, timeout, task_dir)
