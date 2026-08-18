from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from metered_suite.live import event_snippet, line_snippet, run_command


class SnippetTests(unittest.TestCase):
    def test_tool_write(self) -> None:
        text = event_snippet(
            {
                "type": "tool_use",
                "name": "write_file",
                "input": {"file_path": "durableq/queue.py"},
            }
        )
        self.assertEqual(text, "write_file queue.py")

    def test_result_and_error(self) -> None:
        self.assertEqual(event_snippet({"type": "result", "subtype": "success"}), "cli result success")
        self.assertIn("boom", event_snippet({"type": "error", "message": "boom"}) or "")
        err = event_snippet(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "auth failed",
                "usage": {"input_tokens": 0},
            }
        )
        self.assertIn("cli error", err or "")
        self.assertIn("auth failed", err or "")

    def test_json_line(self) -> None:
        self.assertEqual(
            line_snippet('{"type":"system","subtype":"session_start"}'),
            "cli session_start",
        )
        self.assertIsNone(line_snippet(""))


class RunCommandTests(unittest.TestCase):
    def test_streams_write_and_keeps_output(self) -> None:
        notes: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "work.py"
            script.write_text(
                "import time\nfrom pathlib import Path\n"
                "Path('hello.txt').write_text('ok')\n"
                "time.sleep(0.2)\n"
                "print('{\"type\":\"result\",\"subtype\":\"success\"}')\n",
                encoding="utf-8",
            )
            proc = run_command(
                [sys.executable, str(script)],
                cwd=root,
                env=None,
                timeout=10,
                log=notes.append,
                watch=root,
            )
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"type":"result"', proc.stdout.replace(" ", ""))
        joined = " ".join(notes)
        self.assertIn("hello.txt", joined)
        self.assertIn("cli result success", joined)

    def test_timeout_raises(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            run_command(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                cwd=None,
                env=None,
                timeout=1,
                log=lambda _msg: None,
            )


if __name__ == "__main__":
    unittest.main()
