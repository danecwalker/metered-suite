from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metered_suite.sandbox import (
    AGENT_IMAGE,
    VERIFY_IMAGE,
    _seatbelt_profile,
    describe_sandbox,
    ensure_images,
    grade_patch,
    is_linux_binary,
    seed_workspace,
)


ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "tasks" / "durable-queue"


class BinaryTests(unittest.TestCase):
    def test_elf_is_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tool"
            path.write_bytes(b"\x7fELF" + b"\x00" * 16)
            path.chmod(0o755)
            self.assertTrue(is_linux_binary(str(path)))

    def test_macho_is_not_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tool"
            path.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 16)
            path.chmod(0o755)
            self.assertFalse(is_linux_binary(str(path)))

    def test_describe_darwin_host_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grok"
            path.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 16)
            path.chmod(0o755)
            text = describe_sandbox([str(path)])
            self.assertIn("docker-verifier", text)
            self.assertNotIn("docker-agent +", text)


class SeatbeltTests(unittest.TestCase):
    def test_profile_allows_workspace_denies_hidden_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "work"
            workspace.mkdir()
            profile = _seatbelt_profile(workspace, TASK)
            self.assertIn(str(workspace), profile)
            self.assertIn(str(TASK / "tests"), profile)
            self.assertIn(str(TASK / "solution"), profile)
            self.assertIn("(deny file-read*", profile)
            self.assertIn("(allow file-write*", profile)


class EnsureImagesTests(unittest.TestCase):
    def test_skips_build_when_images_exist(self) -> None:
        with patch("metered_suite.sandbox._image_exists", return_value=True), patch(
            "metered_suite.sandbox._docker"
        ) as docker:
            ensure_images(TASK, force=False)
            docker.assert_not_called()

    def test_builds_when_forced(self) -> None:
        with patch("metered_suite.sandbox._image_exists", return_value=True), patch(
            "metered_suite.sandbox._docker"
        ) as docker:
            docker.return_value = subprocess.CompletedProcess(["docker"], 0)
            ensure_images(TASK, force=True)
            tags = [call.args[2] for call in docker.call_args_list]
            self.assertIn(AGENT_IMAGE, tags)
            self.assertIn(VERIFY_IMAGE, tags)


class SeedWorkspaceTests(unittest.TestCase):
    def test_copies_from_agent_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ws"

            def fake_docker(*args, **kwargs):
                if args[:1] == ("create",):
                    return subprocess.CompletedProcess(args, 0, stdout="cid123\n", stderr="")
                if args[:1] == ("cp",):
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "durableq").mkdir()
                    (dest / ".git" / "info").mkdir(parents=True)
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with (
                patch("metered_suite.sandbox.ensure_images"),
                patch("metered_suite.sandbox._docker", side_effect=fake_docker),
            ):
                seed_workspace(TASK, dest)
            exclude = (dest / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            self.assertIn("instruction.md", exclude)
            self.assertIn("_grade/", exclude)


class DockerGradeTests(unittest.TestCase):
    def test_starter_fails_and_solution_passes(self) -> None:
        if shutil_which_docker() is None:
            self.skipTest("docker not available")
        solution = (TASK / "solution" / "solve.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            empty = grade_patch(TASK, "", work / "empty")
            self.assertFalse(empty.get("ok"))
            self.assertEqual(empty.get("reward"), 0)
            self.assertTrue(empty.get("errors") or empty.get("error"))
            from metered_suite.sandbox import collect_patch

            seeded = work / "seeded"
            seed_workspace(TASK, seeded)
            (seeded / "durableq" / "queue.py").write_text(solution, encoding="utf-8")
            real_patch = collect_patch(seeded)
            self.assertTrue(real_patch)
            passed = grade_patch(TASK, real_patch, work / "solved")
            self.assertEqual(passed.get("ok"), True)
            self.assertEqual(passed.get("reward"), 1)
            self.assertEqual(passed.get("failed"), 0)


def shutil_which_docker() -> str | None:
    import shutil

    return shutil.which("docker")


if __name__ == "__main__":
    unittest.main()
