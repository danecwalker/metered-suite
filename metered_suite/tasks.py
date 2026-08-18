from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .hash import character_count, content_hash, integrity_of, metered_units, SUITE_VERSION

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"


@dataclass(frozen=True)
class OfficialTask:
    id: str
    label: str
    prompt: str
    prompt_hash: str
    expected: dict
    work_chars: int
    task_dir: Path | None = None

    @property
    def expected_json_text(self) -> str:
        return json.dumps(self.expected, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _walk_text(root: Path) -> str:
    parts: list[str] = []
    if not root.exists():
        return ""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    return "\n".join(parts)


def load_tasks() -> list[OfficialTask]:
    tasks: list[OfficialTask] = []
    for folder in sorted(p for p in TASKS_DIR.iterdir() if p.is_dir()):
        instruction = (folder / "instruction.md").read_text(encoding="utf-8")
        expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
        expected_text = json.dumps(expected, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        repo = folder / "environment" / "repo"
        work_chars = (
            character_count(instruction)
            + character_count(expected_text)
            + character_count(_walk_text(repo))
        )
        tasks.append(
            OfficialTask(
                id=folder.name.split("-", 1)[-1],
                label=(folder / "label.txt").read_text(encoding="utf-8").strip()
                if (folder / "label.txt").exists()
                else folder.name,
                prompt=instruction,
                prompt_hash=content_hash(instruction),
                expected=expected,
                work_chars=work_chars,
                task_dir=folder,
            )
        )
    if not tasks:
        raise SystemExit("no official tasks under tasks/")
    return tasks


def suite_lock(tasks: list[OfficialTask] | None = None) -> dict:
    tasks = tasks or load_tasks()
    body = [
        {
            "id": task.id,
            "promptHash": task.prompt_hash,
            "check": "extract-json",
            "expectedKeys": sorted(task.expected.keys()),
            "expectedJson": task.expected,
            "mustInclude": None,
        }
        for task in tasks
    ]
    work_chars = sum(task.work_chars for task in tasks)
    return {
        "suiteVersion": SUITE_VERSION,
        "suiteHash": integrity_of(body),
        "workChars": work_chars,
        "workMu": metered_units(work_chars),
        "tasks": [
            {
                "id": task.id,
                "label": task.label,
                "prompt": task.prompt,
                "promptHash": task.prompt_hash,
                "check": "extract-json",
                "expectedKeys": sorted(task.expected.keys()),
                "expectedJson": task.expected,
                "mustInclude": None,
                "workChars": task.work_chars,
            }
            for task in tasks
        ],
    }
