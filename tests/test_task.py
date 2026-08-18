from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "tasks" / "durable-queue"
REPO = TASK / "environment" / "repo"
SOLUTION = TASK / "solution" / "solve.py"
HIDDEN = TASK / "tests"


class DurableQueueTaskTests(unittest.TestCase):
    def test_starter_fails_hidden_and_solution_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            shutil.copytree(REPO, dest, dirs_exist_ok=True)
            shutil.copy2(HIDDEN / "test_hidden.py", dest / "test_hidden.py")
            self.assertNotEqual(self._run_hidden(dest), 0)
            self.assertNotEqual(self._run_public(dest), 0)
            shutil.copy2(SOLUTION, dest / "durableq" / "queue.py")
            self.assertEqual(self._run_hidden(dest), 0)
            self.assertEqual(self._run_public(dest), 0)

    def _run_hidden(self, dest: Path) -> int:
        import subprocess

        return subprocess.run(
            [sys.executable, "-m", "unittest", "test_hidden", "-v"],
            cwd=dest,
            capture_output=True,
        ).returncode

    def _run_public(self, dest: Path) -> int:
        import subprocess

        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=dest,
            capture_output=True,
        ).returncode
