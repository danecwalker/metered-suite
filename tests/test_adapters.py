from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metered_suite.adapters import parse_usage
from metered_suite.usage import Usage, read_sidecar, write_usage


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
        self.assertEqual(usage.cache_write, 0)
        self.assertEqual(usage.source, "cli")

    def test_claude_cache_write_and_read(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "usage": {
                    "input_tokens": 26,
                    "output_tokens": 22780,
                    "cache_creation_input_tokens": 41200,
                    "cache_read_input_tokens": 700719,
                },
            }
        )
        usage = parse_usage("claude", raw)
        self.assertEqual(usage.input, 26)
        self.assertEqual(usage.output, 22780)
        self.assertEqual(usage.cache_hit, 700719)
        self.assertEqual(usage.cache_write, 41200)

    def test_claude_model_usage_does_not_drop_writes(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 26,
                    "output_tokens": 100,
                    "cache_creation_input_tokens": 41200,
                    "cache_read_input_tokens": 700719,
                },
                "modelUsage": {
                    "claude-opus-4-6": {
                        "inputTokens": 26,
                        "outputTokens": 100,
                        "cacheReadInputTokens": 700719,
                    }
                },
            }
        )
        usage = parse_usage("claude", raw)
        self.assertEqual(usage.cache_write, 41200)
        self.assertEqual(usage.cache_hit, 700719)

    def test_claude_cache_creation_ephemeral_sum(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 1000,
                        "ephemeral_1h_input_tokens": 200,
                    },
                },
            }
        )
        usage = parse_usage("claude", raw)
        self.assertEqual(usage.cache_write, 1200)

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
        self.assertEqual(usage.cache_write, 0)

    def test_chatgpt_sums_incremental_turns(self) -> None:
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 100, "output_tokens": 10},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 40, "output_tokens": 8},
                    }
                ),
            ]
        )
        usage = parse_usage("chatgpt", lines)
        self.assertEqual(usage.input, 140)
        self.assertEqual(usage.output, 18)

    def test_chatgpt_nested_details_cache_and_thinking(self) -> None:
        raw = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 200,
                    "prompt_tokens_details": {"cached_tokens": 800},
                    "completion_tokens_details": {"reasoning_tokens": 50},
                },
            }
        )
        usage = parse_usage("chatgpt", raw)
        self.assertEqual(usage.input, 1000)
        self.assertEqual(usage.output, 200)
        self.assertEqual(usage.reasoning, 50)
        self.assertEqual(usage.cache_hit, 800)

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
        self.assertEqual(usage.cache_write, 0)

    def test_opencode_cache_write(self) -> None:
        raw = json.dumps(
            {
                "type": "step_finish",
                "part": {
                    "tokens": {
                        "input": 671,
                        "output": 8,
                        "reasoning": 40,
                        "cache": {"read": 21415, "write": 900},
                    }
                },
            }
        )
        usage = parse_usage("opencode", raw)
        self.assertEqual(usage.input, 671)
        self.assertEqual(usage.output, 8)
        self.assertEqual(usage.reasoning, 40)
        self.assertEqual(usage.cache_hit, 21415)
        self.assertEqual(usage.cache_write, 900)

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
        self.assertEqual(usage.cache_write, 0)

    def test_kimi_sums_turn_records(self) -> None:
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "type": "usage.record",
                        "scope": "turn",
                        "usage": {
                            "inputOther": 50,
                            "output": 8,
                            "inputCacheRead": 20,
                            "inputCacheCreation": 15,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "usage.record",
                        "scope": "session",
                        "usage": {
                            "inputOther": 999,
                            "output": 99,
                            "inputCacheRead": 20,
                            "inputCacheCreation": 15,
                        },
                    }
                ),
            ]
        )
        usage = parse_usage("kimi", lines)
        self.assertEqual(usage.input, 50)
        self.assertEqual(usage.output, 8)
        self.assertEqual(usage.cache_hit, 20)
        self.assertEqual(usage.cache_write, 15)

    def test_pi_last_message_usage(self) -> None:
        lines = "\n".join(
            [
                json.dumps({"type": "message_update", "usage": {"input": 1, "output": 1}}),
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {
                            "usage": {
                                "input": 400,
                                "output": 12,
                                "cacheRead": 50,
                                "cacheWrite": 30,
                                "reasoning": 7,
                            }
                        },
                    }
                ),
            ]
        )
        usage = parse_usage("pi", lines)
        self.assertEqual(usage.input, 400)
        self.assertEqual(usage.output, 12)
        self.assertEqual(usage.reasoning, 7)
        self.assertEqual(usage.cache_hit, 50)
        self.assertEqual(usage.cache_write, 30)

    def test_grok_headless_usage_and_model_usage(self) -> None:
        raw = json.dumps(
            {
                "text": "done",
                "stopReason": "end_turn",
                "usage": {
                    "input_tokens": 7210,
                    "cache_read_input_tokens": 41000,
                    "cache_creation_input_tokens": 1800,
                    "output_tokens": 1893,
                    "reasoning_tokens": 412,
                    "total_tokens": 51903,
                },
                "modelUsage": {
                    "grok-4.6": {
                        "inputTokens": 7210,
                        "outputTokens": 1893,
                        "cacheReadInputTokens": 41000,
                    }
                },
            }
        )
        usage = parse_usage("grok", raw)
        self.assertEqual(usage.input, 7210)
        self.assertEqual(usage.output, 1893)
        self.assertEqual(usage.reasoning, 412)
        self.assertEqual(usage.cache_hit, 41000)
        self.assertEqual(usage.cache_write, 1800)

    def test_qwen_thoughts_and_cached(self) -> None:
        raw = json.dumps(
            {
                "stats": {
                    "models": {
                        "qwen3.8-max-preview": {
                            "tokens": {
                                "prompt": 30000,
                                "candidates": 5000,
                                "cached": 10000,
                                "thoughts": 2000,
                            }
                        }
                    }
                }
            }
        )
        usage = parse_usage("qwen", raw)
        self.assertEqual(usage.input, 30000)
        self.assertEqual(usage.output, 5000)
        self.assertEqual(usage.reasoning, 2000)
        self.assertEqual(usage.cache_hit, 10000)

    def test_deepseek_claude_shaped_cache(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 40,
                    "reasoning_tokens": 12,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 9000,
                },
            }
        )
        usage = parse_usage("deepseek", raw)
        self.assertEqual(usage.input, 80)
        self.assertEqual(usage.output, 40)
        self.assertEqual(usage.reasoning, 12)
        self.assertEqual(usage.cache_hit, 9000)
        self.assertEqual(usage.cache_write, 500)

    def test_empty_stdout_is_not_counted(self) -> None:
        usage = parse_usage("claude", "hello from the agent")
        self.assertFalse(usage.counted())
        self.assertEqual(usage.source, "none")

    def test_sidecar_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_usage(workspace, Usage(input=3, output=1, reasoning=2, source="cli"))
            loaded = read_sidecar(workspace)
            self.assertEqual(
                loaded.as_dict(),
                {
                    "input": 3,
                    "output": 1,
                    "reasoning": 2,
                    "cacheHit": 0,
                    "cacheWrite": 0,
                },
            )


if __name__ == "__main__":
    unittest.main()
