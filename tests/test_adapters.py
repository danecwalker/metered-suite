from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metered_suite.adapters import parse_usage
from metered_suite.identity import build_command, resolve_harness, sku_fits
from metered_suite.usage import Usage, read_sidecar, write_usage


class CommandTests(unittest.TestCase):
    def test_claude_injects_json_output_and_effort(self) -> None:
        spec = resolve_harness("claude")
        cmd = build_command(
            spec,
            "claude-opus-4-6",
            ["--dangerously-skip-permissions"],
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

    def test_chatgpt_is_codex_exec_json(self) -> None:
        cmd = build_command(
            resolve_harness("chatgpt"),
            "gpt-5.4",
            [],
            "prompt",
            Path("instruction.md"),
            "medium",
        )
        self.assertEqual(cmd[:4], ["codex", "exec", "--json", "--skip-git-repo-check"])
        self.assertIn("model_reasoning_effort=medium", cmd)

    def test_qwen_uses_stream_json_and_yolo(self) -> None:
        cmd = build_command(
            resolve_harness("qwen"),
            "qwen3.8-max-preview",
            ["--yolo"],
            "prompt",
            Path("instruction.md"),
            "max",
        )
        self.assertEqual(cmd[0], "qwen")
        self.assertIn("stream-json", cmd)
        self.assertIn("--yolo", cmd)
        self.assertIn("qwen3.8-max-preview", cmd)

    def test_kimi_uses_stream_json(self) -> None:
        cmd = build_command(
            resolve_harness("kimi"),
            "kimi-k2.5",
            ["--yolo"],
            "prompt",
            Path("instruction.md"),
            "default",
        )
        self.assertEqual(cmd[0], "kimi")
        self.assertIn("stream-json", cmd)
        self.assertIn("--yolo", cmd)

    def test_blocked_output_format_flag(self) -> None:
        with self.assertRaises(SystemExit):
            build_command(
                resolve_harness("claude"),
                "claude-opus-4-6",
                ["--output-format", "text"],
                "p",
                Path("instruction.md"),
                "default",
            )


class IdentityTests(unittest.TestCase):
    def test_sku_lock(self) -> None:
        self.assertTrue(sku_fits(resolve_harness("claude"), "claude-opus-4-6"))
        self.assertFalse(sku_fits(resolve_harness("chatgpt"), "claude-opus-4-6"))
        self.assertTrue(sku_fits(resolve_harness("chatgpt"), "gpt-5.4"))
        self.assertTrue(sku_fits(resolve_harness("gemini"), "gemini-2.5-pro"))
        self.assertFalse(sku_fits(resolve_harness("gemini"), "claude-opus-4-6"))
        self.assertTrue(sku_fits(resolve_harness("kimi"), "kimi-k2.5"))
        self.assertTrue(sku_fits(resolve_harness("kimi"), "moonshot-v1"))
        self.assertTrue(sku_fits(resolve_harness("deepseek"), "deepseek-v4-pro"))
        self.assertFalse(sku_fits(resolve_harness("deepseek"), "gpt-5.4"))
        self.assertTrue(sku_fits(resolve_harness("opencode"), "gpt-5.4"))

    def test_unknown_harness(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_harness("windsurf")

    def test_api_cannot_invent_a_binary(self) -> None:
        with self.assertRaises(SystemExit) as err:
            build_command(
                resolve_harness("api"),
                "gpt-5.4",
                [],
                "p",
                Path("instruction.md"),
                "default",
            )
        self.assertIn("cannot invent a binary", str(err.exception))


class ParseTests(unittest.TestCase):
    def test_claude_result_usage(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "result": "ok",
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 80,
                    "cache_read_input_tokens": 400,
                },
            }
        )
        usage = parse_usage("claude", raw)
        self.assertEqual(usage.input, 1200)
        self.assertEqual(usage.output, 80)
        self.assertEqual(usage.cache_hit, 400)
        self.assertEqual(usage.source, "cli")

    def test_chatgpt_last_turn_completed(self) -> None:
        lines = "\n".join(
            [
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 5,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 24763,
                            "cached_input_tokens": 24448,
                            "output_tokens": 122,
                            "reasoning_output_tokens": 9,
                        },
                    }
                ),
            ]
        )
        usage = parse_usage("chatgpt", lines)
        self.assertEqual(usage.input, 24763)
        self.assertEqual(usage.output, 122)
        self.assertEqual(usage.reasoning, 9)
        self.assertEqual(usage.cache_hit, 24448)

    def test_chatgpt_token_count_event(self) -> None:
        raw = json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 120000,
                            "cached_input_tokens": 8000,
                            "output_tokens": 40,
                            "reasoning_output_tokens": 12,
                        }
                    },
                },
            }
        )
        usage = parse_usage("chatgpt", raw)
        self.assertEqual(usage.input, 120000)
        self.assertEqual(usage.output, 40)
        self.assertEqual(usage.reasoning, 12)
        self.assertEqual(usage.cache_hit, 8000)

    def test_opencode_sums_step_finish(self) -> None:
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "type": "step_finish",
                        "part": {
                            "tokens": {
                                "input": 671,
                                "output": 8,
                                "reasoning": 2,
                                "cache": {"read": 100, "write": 0},
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "step_finish",
                        "part": {
                            "tokens": {
                                "input": 10,
                                "output": 4,
                                "reasoning": 0,
                                "cache": {"read": 5, "write": 0},
                            }
                        },
                    }
                ),
            ]
        )
        usage = parse_usage("opencode", lines)
        self.assertEqual(usage.input, 681)
        self.assertEqual(usage.output, 12)
        self.assertEqual(usage.reasoning, 2)
        self.assertEqual(usage.cache_hit, 105)

    def test_gemini_sums_per_model_stats(self) -> None:
        raw = json.dumps(
            {
                "response": "done",
                "stats": {
                    "models": {
                        "gemini-2.5-pro": {
                            "tokens": {
                                "prompt": 24939,
                                "candidates": 20,
                                "cached": 21263,
                                "thoughts": 154,
                            }
                        },
                        "gemini-2.5-flash": {
                            "tokens": {
                                "prompt": 100,
                                "candidates": 10,
                                "cached": 0,
                                "thoughts": 0,
                            }
                        },
                    }
                },
            }
        )
        usage = parse_usage("gemini", raw)
        self.assertEqual(usage.input, 25039)
        self.assertEqual(usage.output, 30)
        self.assertEqual(usage.reasoning, 154)
        self.assertEqual(usage.cache_hit, 21263)

    def test_kimi_sums_turn_records(self) -> None:
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "type": "usage.record",
                        "scope": "turn",
                        "usage": {"inputOther": 50, "output": 8, "inputCacheRead": 20},
                    }
                ),
                json.dumps(
                    {
                        "type": "usage.record",
                        "scope": "session",
                        "usage": {"inputOther": 999, "output": 99, "inputCacheRead": 20},
                    }
                ),
            ]
        )
        usage = parse_usage("kimi", lines)
        self.assertEqual(usage.input, 50)
        self.assertEqual(usage.output, 8)
        self.assertEqual(usage.cache_hit, 20)

    def test_pi_last_message_usage(self) -> None:
        lines = "\n".join(
            [
                json.dumps({"type": "message_update", "usage": {"input": 1, "output": 1}}),
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {"usage": {"input": 400, "output": 12, "cacheRead": 50}},
                    }
                ),
            ]
        )
        usage = parse_usage("pi", lines)
        self.assertEqual(usage.input, 400)
        self.assertEqual(usage.output, 12)
        self.assertEqual(usage.cache_hit, 50)

    def test_empty_stdout_is_not_counted(self) -> None:
        usage = parse_usage("claude", "hello from the agent")
        self.assertFalse(usage.counted())
        self.assertEqual(usage.source, "none")

    def test_sidecar_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_usage(workspace, Usage(input=3, output=1, reasoning=2, source="cli"))
            loaded = read_sidecar(workspace)
            self.assertEqual(loaded.as_dict(), {"input": 3, "output": 1, "reasoning": 2, "cacheHit": 0})


if __name__ == "__main__":
    unittest.main()
