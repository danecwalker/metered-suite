from __future__ import annotations

from typing import Any

from .hash import (
    EVAL_FORMAT,
    EVALUATOR_VERSION,
    content_hash,
    integrity_of,
)
from .score import score_json
from .tasks import OfficialTask


def seal_package(
    *,
    suite_version: str,
    suite_hash: str,
    stack: dict[str, Any],
    started_at: str,
    finished_at: str,
    raw_tasks: list[dict[str, Any]],
    official: list[OfficialTask],
) -> dict[str, Any]:
    by_id = {task.id: task for task in official}
    tasks: list[dict[str, Any]] = []
    for raw in raw_tasks:
        spec = by_id[raw["id"]]
        output = raw.get("output") or ""
        passed = score_json(output, spec.expected)
        tasks.append(
            {
                "id": spec.id,
                "promptHash": spec.prompt_hash,
                "output": output,
                "outputHash": content_hash(output),
                "usage": {
                    "input": int(raw.get("usage", {}).get("input") or 0),
                    "output": int(raw.get("usage", {}).get("output") or 0),
                    "reasoning": int(raw.get("usage", {}).get("reasoning") or 0),
                    "cacheHit": int(raw.get("usage", {}).get("cacheHit") or 0),
                },
                "providerUsage": raw.get("providerUsage"),
                "passed": passed,
                "check": "extract-json",
                "attempts": max(1, int(raw.get("attempts") or 1)),
            }
        )
    totals = {
        "tasks": len(tasks),
        "passed": sum(1 for task in tasks if task["passed"]),
        "input": sum(task["usage"]["input"] for task in tasks),
        "output": sum(task["usage"]["output"] for task in tasks),
        "reasoning": sum(task["usage"]["reasoning"] for task in tasks),
        "cacheHit": sum(task["usage"]["cacheHit"] for task in tasks),
    }
    draft = {
        "format": EVAL_FORMAT,
        "evaluator": {"name": "metered", "version": EVALUATOR_VERSION},
        "suiteVersion": suite_version,
        "suiteHash": suite_hash,
        "stack": stack,
        "run": {"startedAt": started_at, "finishedAt": finished_at, "tasks": tasks},
        "totals": totals,
    }
    return {**draft, "integrity": integrity_of(draft)}
