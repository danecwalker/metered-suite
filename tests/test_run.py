from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from metered_suite.identity import build_command, resolve_harness
from metered_suite.run import (
    _command_preview,
    _follow_up_prompt,
    _log_verifier_report,
    _verifier_brief,
    run_suite,
)
from metered_suite.tasks import OfficialTask


class VerifierBriefTests(unittest.TestCase):
    def test_lists_failed_hidden_tests(self) -> None:
        text = _verifier_brief(
            '{"ok":false,"reward":0,"failed":2,"errors":["test_visibility","test_persist"]}'
        )
        self.assertIn("test_visibility", text)
        self.assertIn("test_persist", text)

    def test_report_logs_each_hidden_test(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            _log_verifier_report(
                {
                    "ok": False,
                    "passedTests": ["test_delay_does_not_steal_older_ready"],
                    "failedTests": ["test_visibility_timeout_restores_and_counts_attempt"],
                    "details": ["AssertionError: 0 != 1"],
                }
            )
        text = buf.getvalue()
        self.assertIn("    pass  test_delay_does_not_steal_older_ready", text)
        self.assertIn("    fail  test_visibility_timeout_restores_and_counts_attempt", text)
        self.assertIn("AssertionError: 0 != 1", text)
        self.assertIn("verifier 1/2 hidden tests", text)

    def test_follow_up_prompt_is_actionable(self) -> None:
        task = OfficialTask(
            id="queue",
            label="queue",
            prompt="Fix the queue",
            prompt_hash="c",
            expected={"ok": True},
            work_chars=10,
        )
        previous = json.dumps(
            {
                "ok": False,
                "failedTests": ["test_nack_then_poison"],
                "passedTests": ["test_delay_does_not_steal_older_ready"],
                "details": ["AssertionError: 0 != 1"],
            }
        )
        text = _follow_up_prompt(task, 2, previous)
        self.assertIn("Same checkout", text)
        self.assertIn("python3 -m unittest discover -s tests -v", text)
        self.assertIn("test_nack_then_poison", text)
        self.assertIn("increments attempts", text)
        self.assertIn("already passed", text)
        self.assertNotIn("SECRET", text)
        reset = _follow_up_prompt(task, 3, previous, reset=True)
        self.assertIn("fresh checkout", reset)


class CommandPreviewTests(unittest.TestCase):
    def test_skips_grok_prompt_keeps_model(self) -> None:
        prompt = "Write answer.json\nSECRET_PROMPT_BODY"
        cmd = build_command(
            resolve_harness("grok"),
            "grok-4.6",
            ["--always-approve"],
            prompt,
            Path("instruction.md"),
            "xhigh",
        )
        preview = _command_preview(cmd, prompt)
        self.assertTrue(preview.startswith("grok "))
        self.assertIn("--model grok-4.6", preview)
        self.assertNotIn("SECRET_PROMPT_BODY", preview)
        self.assertNotIn("Write answer.json", preview)

    def test_skips_short_positional_prompt(self) -> None:
        prompt = "short prompt"
        cmd = build_command(
            resolve_harness("claude"),
            "claude-opus-4-6",
            ["--dangerously-skip-permissions"],
            prompt,
            Path("instruction.md"),
            "high",
        )
        preview = _command_preview(cmd, prompt)
        self.assertIn("claude --print --model claude-opus-4-6", preview)
        self.assertNotIn("short prompt", preview)


class RunProgressTests(unittest.TestCase):
    def test_progress_lines_and_usage(self) -> None:
        tasks = [
            OfficialTask(
                id="normalize",
                label="normalize",
                prompt="Write answer.json\nSECRET_PROMPT_BODY",
                prompt_hash="a",
                expected={"ok": True},
                work_chars=10,
            ),
            OfficialTask(
                id="fertility",
                label="fertility",
                prompt="Another secret prompt",
                prompt_hash="b",
                expected={"ok": True},
                work_chars=10,
            ),
        ]

        def fake_run(command, cwd=None, **kwargs):
            name = Path(command[0]).name if command else ""
            if name == "git":
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            Path(cwd, "answer.json").write_text('{"ok": true}', encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {"input": 10, "output": 2, "reasoning": 1, "cacheHit": 3}
                ),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                'HARNESS = "grok"\nMODEL = "grok-4.6"\nEFFORT = "xhigh"\nMAX_ATTEMPTS = 2\n',
                encoding="utf-8",
            )
            buf = StringIO()
            with (
                patch("metered_suite.run.load_tasks", return_value=tasks),
                patch("metered_suite.run.subprocess.run", side_effect=fake_run),
                redirect_stdout(buf),
            ):
                path = run_suite(root)

            text = buf.getvalue()
            self.assertIn("grok  grok-4.6  xhigh  2 tasks  2", text)
            self.assertIn("task 1/2  normalize", text)
            self.assertIn("task 2/2  fertility", text)
            self.assertIn("  attempt 1/2", text)
            self.assertIn("  grok --single --model grok-4.6", text)
            self.assertIn("  exit 0  in=10 out=2 reasoning=1 cacheHit=3", text)
            self.assertIn("normalize: pass after 1 attempt(s)", text)
            self.assertIn("fertility: pass after 1 attempt(s)", text)
            self.assertIn(f"wrote {path}", text)
            self.assertIn("passed 2/2", text)
            self.assertNotIn("SECRET_PROMPT_BODY", text)
            self.assertNotIn("Another secret prompt", text)
            self.assertNotIn("—", text)
            self.assertNotIn("$ / M ET", text)

    def test_timeout_and_mu_warning(self) -> None:
        tasks = [
            OfficialTask(
                id="fertility",
                label="fertility",
                prompt="secret task prompt",
                prompt_hash="b",
                expected={"ok": True},
                work_chars=10,
            ),
        ]

        def fake_run(command, cwd=None, timeout=None, **kwargs):
            name = Path(command[0]).name if command else ""
            if name == "git":
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            raise subprocess.TimeoutExpired(command, timeout or 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                'HARNESS = "grok"\nMODEL = "grok-4.6"\nEFFORT = "xhigh"\nMAX_ATTEMPTS = 1\n',
                encoding="utf-8",
            )
            buf = StringIO()
            with (
                patch("metered_suite.run.load_tasks", return_value=tasks),
                patch("metered_suite.run.subprocess.run", side_effect=fake_run),
                redirect_stdout(buf),
            ):
                run_suite(root)

            text = buf.getvalue()
            self.assertIn("  timeout", text)
            self.assertIn(
                "fertility: fail after 1 attempt(s) - no token usage from the CLI; this task cannot define $ / MU",
                text,
            )
            self.assertIn("Metered will not rank it as $ / MU.", text)
            self.assertNotIn("—", text)
            self.assertNotIn("$ / M ET", text)
            self.assertNotIn("secret task prompt", text)

    def test_keeps_same_checkout_until_pass(self) -> None:
        tasks = [
            OfficialTask(
                id="queue",
                label="queue",
                prompt="Fix the queue",
                prompt_hash="c",
                expected={"ok": True},
                work_chars=10,
            ),
        ]
        seen: list[Path] = []

        def fake_run(command, cwd=None, **kwargs):
            name = Path(command[0]).name if command else ""
            if name == "git":
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            path = Path(cwd)
            seen.append(path)
            answer = path / "answer.json"
            if not answer.exists():
                answer.write_text('{"ok": false}', encoding="utf-8")
            else:
                answer.write_text('{"ok": true}', encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"input": 4, "output": 1, "reasoning": 0, "cacheHit": 0}),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                'HARNESS = "grok"\nMODEL = "grok-4.6"\nEFFORT = "xhigh"\nMAX_ATTEMPTS = 0\n',
                encoding="utf-8",
            )
            buf = StringIO()
            with (
                patch("metered_suite.run.load_tasks", return_value=tasks),
                patch("metered_suite.run.subprocess.run", side_effect=fake_run),
                redirect_stdout(buf),
            ):
                run_suite(root)

            text = buf.getvalue()
            self.assertIn("until pass", text)
            self.assertIn("  attempt 1/until pass", text)
            self.assertIn("  attempt 2/until pass", text)
            self.assertIn("  same checkout, continuing until pass", text)
            self.assertIn("queue: pass after 2 attempt(s)", text)
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[0], seen[1])
            self.assertNotIn("Fix the queue", text)


if __name__ == "__main__":
    unittest.main()
