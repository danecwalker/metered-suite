from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from metered_suite.__main__ import _help, main, parse_run
from metered_suite.recipe import RECIPE_NAME, dump_recipes


class CliTests(unittest.TestCase):
    def test_codex_model_and_effort(self) -> None:
        cfg = parse_run(
            ["codex", "--model", "gpt-5.6-sol", "--effort", "max"]
        )
        self.assertEqual(cfg["HARNESS"], "codex")
        self.assertEqual(cfg["MODEL"], "gpt-5.6-sol")
        self.assertEqual(cfg["EFFORT"], "max")
        self.assertNotIn("FLAGS", cfg)
        self.assertEqual(cfg["MAX_ATTEMPTS"], 0)

    def test_rejects_extra_cli_flags(self) -> None:
        with self.assertRaises(SystemExit):
            parse_run(
                ["qwen", "--model", "deepseek-v4-flash-0731", "--args", "--yolo"]
            )

    def test_help_without_recipe_requires_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _help(Path(tmp))
        self.assertIn("python3 -m metered_suite init", text)
        self.assertIn(f"no {RECIPE_NAME} yet", text)
        self.assertNotIn("harnesses:", text)
        self.assertNotIn("chatgpt, claude", text)

    def test_help_lists_recipe_keys_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RECIPE_NAME).write_text(
                dump_recipes(
                    {
                        "mycli": {
                            "slug": "custom",
                            "bin": "mycli",
                            "argv": ["mycli", "{prompt}"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            text = _help(root)
        self.assertIn(f"harnesses in {RECIPE_NAME}: mycli", text)
        self.assertIn("python3 -m metered_suite mycli --model <sku>", text)
        self.assertNotIn("chatgpt, claude", text)

    def test_run_without_init_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buf = StringIO()
            with redirect_stdout(buf), self.assertRaises(SystemExit) as err:
                main(["grok", "--model", "grok-4.6"], root=root)
            self.assertIn("init", str(err.exception))
            self.assertIn(RECIPE_NAME, str(err.exception))

    def test_init_then_unknown_harness_lists_ready_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            grok = bin_dir / "grok"
            grok.write_text("#!/bin/sh\n", encoding="utf-8")
            grok.chmod(0o755)
            old_path = os_environ_path(bin_dir)
            try:
                buf = StringIO()
                with redirect_stdout(buf):
                    main(["init"], root=root)
                text = buf.getvalue()
                self.assertIn("ready: grok", text)
                with self.assertRaises(SystemExit) as err:
                    main(["windsurf", "--model", "x"], root=root)
                self.assertIn("windsurf is not in", str(err.exception))
                self.assertIn("grok", str(err.exception))
            finally:
                restore_path(old_path)


def os_environ_path(bindir: Path) -> str | None:
    import os

    previous = os.environ.get("PATH")
    os.environ["PATH"] = str(bindir)
    return previous


def restore_path(previous: str | None) -> None:
    import os

    if previous is None:
        os.environ.pop("PATH", None)
    else:
        os.environ["PATH"] = previous


if __name__ == "__main__":
    unittest.main()
