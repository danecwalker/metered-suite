from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TASKS = [
    {
        "dir": ROOT / "tasks" / "durable-queue",
        "package": "durableq",
        "module": "queue.py",
        "import_ok": "from durableq import Queue",
    },
    {
        "dir": ROOT / "tasks" / "rate-limit",
        "package": "ratelimit",
        "module": "limiter.py",
        "import_ok": "from ratelimit import Limiter",
    },
    {
        "dir": ROOT / "tasks" / "json-patch",
        "package": "jsonpatch",
        "module": "patch.py",
        "import_ok": "from jsonpatch import apply",
    },
]


class OfficialTaskTests(unittest.TestCase):
    def test_starter_fails_and_solution_passes_each_job(self) -> None:
        for spec in TASKS:
            with self.subTest(task=spec["dir"].name):
                self._check_task(spec)

    def _check_task(self, spec: dict) -> None:
        task = spec["dir"]
        repo = task / "environment" / "repo"
        solution = task / "solution" / "solve.py"
        hidden = task / "tests"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            shutil.copytree(repo, dest, dirs_exist_ok=True)
            shutil.copy2(hidden / "test_hidden.py", dest / "test_hidden.py")
            self.assertNotEqual(self._run_hidden(dest), 0, spec["dir"].name)
            self.assertNotEqual(self._run_public(dest), 0, spec["dir"].name)
            shutil.copy2(solution, dest / spec["package"] / spec["module"])
            self.assertEqual(self._run_hidden(dest), 0, spec["dir"].name)
            self.assertEqual(self._run_public(dest), 0, spec["dir"].name)

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


if __name__ == "__main__":
    unittest.main()
