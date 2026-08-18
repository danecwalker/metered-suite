"""Harbor-shaped adapter per harness: build the CLI argv, parse that tool's usage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .usage import (
    Usage,
    best_usage,
    json_blobs,
    pick_richer,
    usage_from_fields,
    usage_from_mapping,
)

CommandFn = Callable[[str, str, list[str], str, Path, str], list[str]]
ParseFn = Callable[[str, str, Path], Usage]


@dataclass(frozen=True)
class Adapter:
    slug: str
    command: CommandFn
    parse: ParseFn


def _effort_or_empty(effort: str) -> str:
    return (effort or "").strip().lower()


def _claude_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--print", "--model", model, "--output-format", "json"]
    level = _effort_or_empty(effort)
    if level and level != "default":
        cmd.extend(["--effort", level])
    cmd.extend(flags)
    cmd.append(prompt)
    return cmd


def _chatgpt_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "exec", "--json", "--skip-git-repo-check", "--model", model]
    level = _effort_or_empty(effort)
    if level and level != "default":
        cmd.extend(["-c", f"model_reasoning_effort={level}"])
    cmd.extend(flags)
    cmd.append(prompt)
    return cmd


def _gemini_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--prompt", prompt, "--model", model, "--output-format", "json"]
    cmd.extend(flags)
    return cmd


def _grok_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--single", prompt, "--model", model, "--output-format", "json"]
    level = _effort_or_empty(effort)
    if level and level != "default":
        cmd.extend(["--reasoning-effort", level])
    cmd.extend(flags)
    return cmd


def _qwen_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--prompt", prompt, "--model", model, "--output-format", "stream-json"]
    cmd.extend(flags)
    return cmd


def _kimi_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [
        binary,
        "--prompt",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
    ]
    cmd.extend(flags)
    return cmd


def _deepseek_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--print", "--model", model, "--output-format", "json"]
    cmd.extend(flags)
    cmd.append(prompt)
    return cmd


def _opencode_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "run", "--model", model, "--format", "json"]
    level = _effort_or_empty(effort)
    if level and level != "default":
        cmd.extend(["--variant", level])
    cmd.extend(flags)
    cmd.append(prompt)
    return cmd


def _pi_command(
    binary: str, model: str, flags: list[str], prompt: str, prompt_file: Path, effort: str
) -> list[str]:
    cmd = [binary, "--mode", "json", "--model", model]
    level = _effort_or_empty(effort)
    thinking = {
        "none": "off",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "max": "max",
    }.get(level)
    if thinking:
        cmd.extend(["--thinking", thinking])
    cmd.extend(flags)
    cmd.append(prompt)
    return cmd


def _blobs(stdout: str, stderr: str) -> list[Any]:
    return json_blobs(stdout) + json_blobs(stderr)


def _last_typed(blobs: list[Any], types: set[str], pick: Callable[[dict], Usage]) -> Usage:
    last = Usage()
    for blob in blobs:
        if isinstance(blob, dict) and blob.get("type") in types:
            parsed = pick(blob)
            if parsed.counted():
                last = parsed
    return last


def parse_claude(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    last = Usage()
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        if blob.get("type") not in {"result", None} and "usage" not in blob:
            continue
        parsed = usage_from_mapping(blob)
        models = blob.get("modelUsage") or blob.get("model_usage")
        if isinstance(models, dict):
            summed = Usage(source="cli")
            for item in models.values():
                if isinstance(item, dict):
                    summed = summed.add(usage_from_fields(item, source="cli"))
            parsed = pick_richer(parsed, summed)
        if parsed.counted():
            last = parsed
    return last if last.counted() else best_usage(blobs)


def parse_chatgpt(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    last = _last_typed(
        blobs, {"turn.completed"}, lambda blob: usage_from_mapping(blob.get("usage") or blob)
    )
    if last.counted():
        return last
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        payload = blob.get("payload") if blob.get("type") == "event_msg" else blob
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "token_count":
            continue
        info = payload.get("info") if isinstance(payload.get("info"), dict) else payload
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        parsed = usage_from_mapping(total or info or payload)
        if parsed.counted():
            last = parsed
    return last if last.counted() else best_usage(blobs)


def _stats_models(obj: dict[str, Any]) -> Usage:
    stats = obj.get("stats")
    if not isinstance(stats, dict):
        return Usage()
    models = stats.get("models")
    total = Usage(source="cli")
    if isinstance(models, dict):
        for item in models.values():
            if not isinstance(item, dict):
                continue
            tokens = item.get("tokens") if isinstance(item.get("tokens"), dict) else item
            total = total.add(usage_from_fields(tokens, source="cli"))
        if total.counted():
            return total
    tokens = stats.get("tokens")
    if isinstance(tokens, dict):
        return usage_from_fields(tokens, source="cli")
    return usage_from_mapping(stats)


def parse_gemini(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    last = Usage()
    for blob in blobs:
        if isinstance(blob, dict):
            parsed = _stats_models(blob)
            if parsed.counted():
                last = parsed
    return last if last.counted() else best_usage(blobs)


def parse_grok(stdout: str, stderr: str, workspace: Path) -> Usage:
    parsed = parse_claude(stdout, stderr, workspace)
    return parsed if parsed.counted() else best_usage(_blobs(stdout, stderr))


def parse_qwen(stdout: str, stderr: str, workspace: Path) -> Usage:
    return parse_gemini(stdout, stderr, workspace)


def parse_kimi(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    turn_total = Usage(source="cli")
    session_last = Usage()
    saw_turn = False
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        kind = str(blob.get("type") or "")
        parsed = usage_from_mapping(blob)
        if not parsed.counted():
            continue
        scope = str(blob.get("scope") or blob.get("level") or "").lower()
        session = scope in {"session", "total", "cumulative"} or kind.endswith("session")
        if session:
            session_last = parsed
            continue
        if kind in {"usage.record", "usage_record", "StatusUpdate"} or "usage" in blob:
            turn_total = turn_total.add(parsed)
            saw_turn = True
    if saw_turn and turn_total.counted():
        return turn_total
    if session_last.counted():
        return session_last
    return best_usage(blobs)


def parse_deepseek(stdout: str, stderr: str, workspace: Path) -> Usage:
    parsed = parse_claude(stdout, stderr, workspace)
    return parsed if parsed.counted() else best_usage(_blobs(stdout, stderr))


def parse_opencode(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    total = Usage(source="cli")
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        kind = blob.get("type")
        part = blob.get("part") if isinstance(blob.get("part"), dict) else {}
        if kind in {"step_finish", "step-finish"} or part.get("type") in {
            "step-finish",
            "step_finish",
        }:
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else None
            if tokens:
                total = total.add(usage_from_fields(tokens, source="cli"))
    return total if total.counted() else best_usage(blobs)


def parse_pi(stdout: str, stderr: str, workspace: Path) -> Usage:
    blobs = _blobs(stdout, stderr)
    last = Usage()
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        if blob.get("type") not in {
            "message_update",
            "message_end",
            "turn_end",
            "agent_end",
        }:
            continue
        parsed = usage_from_mapping(blob)
        message = blob.get("message")
        if isinstance(message, dict):
            nested = usage_from_mapping(message)
            if nested.counted():
                parsed = nested
        if parsed.counted():
            last = parsed
    return last if last.counted() else best_usage(blobs)


ADAPTERS: dict[str, Adapter] = {
    "claude": Adapter("claude", _claude_command, parse_claude),
    "chatgpt": Adapter("chatgpt", _chatgpt_command, parse_chatgpt),
    "gemini": Adapter("gemini", _gemini_command, parse_gemini),
    "grok": Adapter("grok", _grok_command, parse_grok),
    "qwen": Adapter("qwen", _qwen_command, parse_qwen),
    "kimi": Adapter("kimi", _kimi_command, parse_kimi),
    "deepseek": Adapter("deepseek", _deepseek_command, parse_deepseek),
    "opencode": Adapter("opencode", _opencode_command, parse_opencode),
    "pi": Adapter("pi", _pi_command, parse_pi),
}


def adapter_for(slug: str) -> Adapter:
    spec = ADAPTERS.get(slug)
    if not spec:
        allowed = ", ".join(sorted(ADAPTERS))
        raise SystemExit(f"No usage adapter for harness {slug}. Known: {allowed}")
    return spec


def parse_usage(slug: str, stdout: str, stderr: str = "", workspace: Path | None = None) -> Usage:
    return adapter_for(slug).parse(stdout, stderr, workspace or Path("."))
