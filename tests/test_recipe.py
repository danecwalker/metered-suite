from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from metered_suite.identity import sku_fits
from metered_suite.recipe import (
    RECIPE_NAME,
    build_command,
    dump_recipes,
    get_recipe,
    init_recipes,
    load_recipes,
    parse_recipes,
    render_argv,
)


def _bindir(root: Path, names: list[str]) -> str:
    bindir = root / "bin"
    bindir.mkdir()
    for name in names:
        path = bindir / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(bindir)


class ParseDumpTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        recipes = {
            "grok": {
                "slug": "grok",
                "bin": "grok",
                "argv": ["grok", "--single", "{prompt}", "--model", "{model}"],
            }
        }
        parsed = parse_recipes(dump_recipes(recipes))
        self.assertEqual(parsed["grok"]["slug"], "grok")
        self.assertEqual(parsed["grok"]["bin"], "grok")
        self.assertEqual(parsed["grok"]["argv"][0], "grok")

    def test_comments_are_not_recipes(self) -> None:
        text = dump_recipes({}, missing=["kimi"])
        self.assertIn("# kimi:", text)
        self.assertEqual(parse_recipes(text), {})


class RenderTests(unittest.TestCase):
    def test_drops_default_effort_flags(self) -> None:
        argv = [
            "claude",
            "--model",
            "{model}",
            "--effort",
            "{effort}",
            "--dangerously-skip-permissions",
            "{prompt}",
        ]
        out = render_argv(
            argv,
            binary="claude",
            model="claude-opus-4-6",
            prompt="do it",
            prompt_file=Path("instruction.md"),
            effort="default",
        )
        self.assertEqual(
            out,
            [
                "claude",
                "--model",
                "claude-opus-4-6",
                "--dangerously-skip-permissions",
                "do it",
            ],
        )

    def test_keeps_named_effort(self) -> None:
        argv = [
            "grok",
            "--single",
            "{prompt}",
            "--model",
            "{model}",
            "--reasoning-effort",
            "{effort}",
            "--always-approve",
        ]
        out = render_argv(
            argv,
            binary="grok",
            model="grok-4.6",
            prompt="SECRET",
            prompt_file=Path("instruction.md"),
            effort="xhigh",
        )
        self.assertEqual(out[0], "grok")
        self.assertIn("xhigh", out)
        self.assertIn("--always-approve", out)
        self.assertIn("SECRET", out)

    def test_drops_codex_effort_config(self) -> None:
        argv = [
            "codex",
            "exec",
            "--model",
            "{model}",
            "-c",
            "model_reasoning_effort={effort}",
            "{prompt}",
        ]
        out = render_argv(
            argv,
            binary="codex",
            model="gpt-5.6-sol",
            prompt="p",
            prompt_file=Path("instruction.md"),
            effort="default",
        )
        self.assertEqual(out, ["codex", "exec", "--model", "gpt-5.6-sol", "p"])


class InitTests(unittest.TestCase):
    def test_writes_only_bins_on_path_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_env = _bindir(root, ["codex", "qwen-code"])
            path, found, missing = init_recipes(root, path_env=path_env)
            self.assertTrue(path.exists())
            self.assertIn("codex", found)
            self.assertIn("chatgpt", found)
            self.assertIn("qwen", found)
            self.assertIn("qwen-code", found)
            self.assertIn("grok", missing)
            recipes = load_recipes(root)
            self.assertEqual(recipes["chatgpt"]["slug"], "chatgpt")
            self.assertEqual(recipes["codex"]["bin"], "codex")
            self.assertEqual(recipes["qwen"]["bin"], "qwen-code")
            self.assertEqual(recipes["qwen-code"]["slug"], "qwen")
            self.assertIn("# grok:", path.read_text(encoding="utf-8"))

    def test_keeps_existing_argv_on_reinit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_env = _bindir(root, ["grok"])
            init_recipes(root, path_env=path_env)
            recipes = load_recipes(root)
            recipes["grok"]["argv"] = ["grok", "--custom", "{prompt}"]
            (root / RECIPE_NAME).write_text(dump_recipes(recipes), encoding="utf-8")
            init_recipes(root, path_env=path_env)
            kept = load_recipes(root)
            self.assertEqual(kept["grok"]["argv"], ["grok", "--custom", "{prompt}"])

    def test_load_requires_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit) as err:
                load_recipes(root)
            self.assertIn("init", str(err.exception))

    def test_empty_file_requires_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RECIPE_NAME).write_text("# nothing\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as err:
                load_recipes(root)
            self.assertIn("init", str(err.exception))

    def test_unknown_name_lists_recipe_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RECIPE_NAME).write_text(
                dump_recipes(
                    {
                        "grok": {
                            "slug": "grok",
                            "bin": "grok",
                            "argv": ["grok"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as err:
                get_recipe(root, "windsurf")
            self.assertIn("windsurf", str(err.exception))
            self.assertIn("grok", str(err.exception))
            self.assertNotIn("windsurf", load_recipes(root))


class CommandTests(unittest.TestCase):
    def test_claude_from_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RECIPE_NAME).write_text(
                dump_recipes(
                    {
                        "claude": {
                            "slug": "claude",
                            "bin": "claude",
                            "argv": [
                                "claude",
                                "--print",
                                "--model",
                                "{model}",
                                "--output-format",
                                "json",
                                "--effort",
                                "{effort}",
                                "--dangerously-skip-permissions",
                                "{prompt}",
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            cmd = build_command(
                root,
                "claude",
                "claude-opus-4-6",
                "Write answer.json",
                Path("instruction.md"),
                "high",
            )
            self.assertEqual(cmd[0], "claude")
            self.assertIn("--output-format", cmd)
            self.assertIn("json", cmd)
            self.assertIn("--effort", cmd)
            self.assertIn("high", cmd)
            self.assertIn("--dangerously-skip-permissions", cmd)
            self.assertIn("Write answer.json", cmd)

    def test_chatgpt_name_uses_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_env = _bindir(root, ["codex"])
            init_recipes(root, path_env=path_env)
            cmd = build_command(
                root,
                "chatgpt",
                "gpt-5.4",
                "prompt",
                Path("instruction.md"),
                "medium",
            )
            self.assertEqual(cmd[:4], ["codex", "exec", "--json", "--skip-git-repo-check"])
            self.assertIn("model_reasoning_effort=medium", cmd)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", cmd)

    def test_kimi_has_no_yolo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_env = _bindir(root, ["kimi"])
            init_recipes(root, path_env=path_env)
            cmd = build_command(
                root,
                "kimi",
                "kimi-k2.5",
                "prompt",
                Path("instruction.md"),
                "default",
            )
            self.assertEqual(cmd[0], "kimi")
            self.assertIn("stream-json", cmd)
            self.assertNotIn("--yolo", cmd)
            self.assertNotIn("--auto", cmd)

    def test_empty_bin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RECIPE_NAME).write_text(
                dump_recipes(
                    {
                        "api": {
                            "slug": "api",
                            "bin": "",
                            "argv": ["{bin}", "{prompt}"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as err:
                build_command(
                    root,
                    "api",
                    "gpt-5.4",
                    "p",
                    Path("instruction.md"),
                    "default",
                )
            self.assertIn("no bin", str(err.exception))


class SkuTests(unittest.TestCase):
    def test_any_nonempty_sku(self) -> None:
        self.assertTrue(sku_fits("claude-opus-4-6"))
        self.assertTrue(sku_fits("deepseek-v4-flash-0731"))
        self.assertFalse(sku_fits(""))
        self.assertFalse(sku_fits("   "))


if __name__ == "__main__":
    unittest.main()
