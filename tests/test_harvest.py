from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metered_suite.adapters import parse_usage
from metered_suite.harvest import harvest, harvest_sessions, harvest_text
from metered_suite.usage import Usage, classify_key


def _dump(*objs: dict) -> str:
    return "\n".join(json.dumps(obj) for obj in objs)


class HarvestCliShapesTests(unittest.TestCase):
    """Every live CLI dialect we have seen must round-trip through harvest."""

    def test_claude_result_and_ephemeral_writes(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "type": "result",
                    "usage": {
                        "input_tokens": 26,
                        "output_tokens": 100,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 1000,
                            "ephemeral_1h_input_tokens": 200,
                        },
                        "cache_read_input_tokens": 50,
                    },
                    "modelUsage": {
                        "claude-opus-5": {
                            "inputTokens": 26,
                            "outputTokens": 100,
                            "cacheReadInputTokens": 50,
                        }
                    },
                }
            )
        )
        self.assertEqual(usage.input, 26)
        self.assertEqual(usage.output, 100)
        self.assertEqual(usage.cache_hit, 50)
        self.assertEqual(usage.cache_write, 1200)

    def test_codex_cumulative_turns_take_last(self) -> None:
        usage = harvest_text(
            _dump(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                },
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 24763, "output_tokens": 122},
                },
            )
        )
        self.assertEqual(usage.input, 24763)
        self.assertEqual(usage.output, 122)

    def test_codex_incremental_turns_sum(self) -> None:
        usage = harvest_text(
            _dump(
                {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}},
                {"type": "turn.completed", "usage": {"input_tokens": 40, "output_tokens": 8}},
            )
        )
        self.assertEqual(usage.input, 140)
        self.assertEqual(usage.output, 18)

    def test_codex_session_token_count(self) -> None:
        usage = harvest_text(
            json.dumps(
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
        )
        self.assertEqual(usage.input, 120000)
        self.assertEqual(usage.reasoning, 12)
        self.assertEqual(usage.cache_hit, 8000)

    def test_opencode_sums_steps(self) -> None:
        usage = harvest_text(
            _dump(
                {
                    "type": "step_finish",
                    "part": {"tokens": {"input": 671, "output": 8, "cache": {"read": 100, "write": 0}}},
                },
                {
                    "type": "step_finish",
                    "part": {"tokens": {"input": 10, "output": 4, "cache": {"read": 5, "write": 900}}},
                },
            )
        )
        self.assertEqual(usage.input, 681)
        self.assertEqual(usage.output, 12)
        self.assertEqual(usage.cache_hit, 105)
        self.assertEqual(usage.cache_write, 900)

    def test_gemini_sums_every_model(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "stats": {
                        "models": {
                            "pro": {"tokens": {"prompt": 100, "candidates": 2, "thoughts": 3, "cached": 10}},
                            "flash": {"tokens": {"prompt": 50, "candidates": 1, "thoughts": 1, "cached": 0}},
                        }
                    }
                }
            )
        )
        self.assertEqual(usage.input, 150)
        self.assertEqual(usage.output, 3)
        self.assertEqual(usage.reasoning, 4)
        self.assertEqual(usage.cache_hit, 10)

    def test_kimi_prefers_turn_records_over_session_duplicate(self) -> None:
        usage = harvest_text(
            _dump(
                {
                    "type": "usage.record",
                    "scope": "turn",
                    "usage": {"inputOther": 50, "output": 8, "inputCacheRead": 20, "inputCacheCreation": 15},
                },
                {
                    "type": "usage.record",
                    "scope": "session",
                    "usage": {"inputOther": 999, "output": 99, "inputCacheRead": 20, "inputCacheCreation": 15},
                },
            )
        )
        self.assertEqual(usage.input, 50)
        self.assertEqual(usage.output, 8)
        self.assertEqual(usage.cache_write, 15)

    def test_pi_last_message_end(self) -> None:
        usage = harvest_text(
            _dump(
                {"type": "message_update", "usage": {"input": 1, "output": 1}},
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
                },
            )
        )
        self.assertEqual(usage.input, 400)
        self.assertEqual(usage.reasoning, 7)
        self.assertEqual(usage.cache_write, 30)

    def test_grok_keeps_writes_when_model_usage_omits_them(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "usage": {
                        "input_tokens": 7210,
                        "output_tokens": 1893,
                        "reasoning_tokens": 412,
                        "cache_read_input_tokens": 41000,
                        "cache_creation_input_tokens": 1800,
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
        )
        self.assertEqual(usage.cache_write, 1800)
        self.assertEqual(usage.reasoning, 412)

    def test_qwen_thoughts(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "stats": {
                        "models": {
                            "qwen3.8-max": {
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
        )
        self.assertEqual(usage.reasoning, 2000)
        self.assertEqual(usage.cache_hit, 10000)

    def test_parse_usage_is_harness_agnostic(self) -> None:
        raw = json.dumps({"type": "result", "usage": {"input_tokens": 9, "output_tokens": 2}})
        self.assertEqual(parse_usage("claude", raw).input, parse_usage("kimi", raw).input)


class HarvestMessyStreamsTests(unittest.TestCase):
    def test_sse_data_prefix(self) -> None:
        text = 'event: usage\ndata: {"usage":{"input_tokens":11,"output_tokens":3}}\n'
        usage = harvest_text(text)
        self.assertEqual(usage.input, 11)
        self.assertEqual(usage.output, 3)

    def test_json_buried_in_log_line(self) -> None:
        text = 'info ready {"input":4,"output":1,"reasoning":2} done'
        usage = harvest_text(text)
        self.assertEqual(usage.input, 4)
        self.assertEqual(usage.reasoning, 2)

    def test_stderr_counts_when_stdout_is_empty(self) -> None:
        usage = harvest(stdout="", stderr=json.dumps({"input_tokens": 8, "output_tokens": 1}))
        self.assertEqual(usage.input, 8)

    def test_plain_text_is_not_usage(self) -> None:
        usage = harvest_text("compiling...\nok")
        self.assertFalse(usage.counted())

    def test_does_not_treat_test_counts_as_tokens(self) -> None:
        usage = harvest_text('{"ok":true,"failed":0,"reward":1,"passedTests":["a"]}')
        self.assertFalse(usage.counted())

    def test_ollama_eval_counts(self) -> None:
        usage = harvest_text(json.dumps({"prompt_eval_count": 120, "eval_count": 40}))
        self.assertEqual(usage.input, 120)
        self.assertEqual(usage.output, 40)

    def test_openai_details_nested(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 200,
                        "prompt_tokens_details": {"cached_tokens": 800},
                        "completion_tokens_details": {"reasoning_tokens": 50},
                    }
                }
            )
        )
        self.assertEqual(usage.cache_hit, 800)
        self.assertEqual(usage.reasoning, 50)


class HarvestSidecarAndSessionTests(unittest.TestCase):
    def test_sidecar_wins_when_stream_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "usage.json").write_text(
                json.dumps({"input": 70, "output": 3, "reasoning": 1, "cacheHit": 4, "cacheWrite": 5}),
                encoding="utf-8",
            )
            usage = harvest(stdout="", workspace=workspace)
            self.assertEqual(usage.input, 70)
            self.assertEqual(usage.cache_write, 5)

    def test_richer_stream_beats_thin_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "usage.json").write_text(
                json.dumps({"input": 1, "output": 1}),
                encoding="utf-8",
            )
            usage = harvest(
                stdout=json.dumps({"input_tokens": 500, "output_tokens": 20, "cache_read_input_tokens": 9}),
                workspace=workspace,
            )
            self.assertEqual(usage.input, 500)
            self.assertEqual(usage.cache_hit, 9)

    def test_home_dotdir_written_during_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            folder = home / ".newcli" / "sessions"
            folder.mkdir(parents=True)
            payload = json.dumps({"usage": {"input_tokens": 77, "output_tokens": 3}}) + "\n"
            (folder / "latest.jsonl").write_text(payload, encoding="utf-8")
            started = (folder / "latest.jsonl").stat().st_mtime - 1
            with patch("metered_suite.harvest.Path.home", return_value=home):
                usage = harvest_sessions(None, since=started)
            self.assertEqual(usage.input, 77)
            self.assertEqual(usage.output, 3)

    def test_unknown_dotdir_is_still_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            folder = workspace / ".amp-cli" / "logs"
            folder.mkdir(parents=True)
            (folder / "run.jsonl").write_text(
                json.dumps({"usage": {"input_tokens": 42, "output_tokens": 6}}) + "\n",
                encoding="utf-8",
            )
            usage = harvest_sessions(workspace)
            self.assertEqual(usage.input, 42)
            self.assertEqual(usage.output, 6)

    def test_session_jsonl_is_last_resort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            claude = workspace / ".claude" / "projects" / "run"
            claude.mkdir(parents=True)
            (claude / "session.jsonl").write_text(
                _dump(
                    {"type": "assistant"},
                    {
                        "type": "result",
                        "usage": {
                            "input_tokens": 321,
                            "output_tokens": 44,
                            "cache_read_input_tokens": 12,
                            "cache_creation_input_tokens": 7,
                        },
                    },
                ),
                encoding="utf-8",
            )
            usage = harvest_sessions(workspace)
            self.assertEqual(usage.input, 321)
            self.assertEqual(usage.output, 44)
            self.assertEqual(usage.cache_hit, 12)
            self.assertEqual(usage.cache_write, 7)

    def test_session_does_not_double_count_the_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            stream = {
                "type": "result",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            }
            folder = workspace / ".codex"
            folder.mkdir()
            (folder / "rollout.jsonl").write_text(json.dumps(stream) + "\n", encoding="utf-8")
            usage = harvest(stdout=json.dumps(stream), workspace=workspace)
            self.assertEqual(usage.input, 100)
            self.assertEqual(usage.output, 10)

    def test_session_used_when_cli_printed_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "session.json").write_text(
                json.dumps({"usage": {"input_tokens": 88, "output_tokens": 9, "reasoning_tokens": 3}}),
                encoding="utf-8",
            )
            usage = harvest(stdout="done", workspace=workspace)
            self.assertEqual(usage.input, 88)
            self.assertEqual(usage.reasoning, 3)

    def test_persist_writes_usage_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            harvest(
                stdout=json.dumps({"input_tokens": 5, "output_tokens": 1}),
                workspace=workspace,
                persist=True,
            )
            saved = json.loads((workspace / "usage.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["input"], 5)
            self.assertEqual(saved["output"], 1)

    def test_ignores_grade_and_git_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            decoy = workspace / "_grade" / "out"
            decoy.mkdir(parents=True)
            (decoy / "reward.json").write_text(
                json.dumps({"input_tokens": 99999, "output_tokens": 99999}),
                encoding="utf-8",
            )
            usage = harvest_sessions(workspace)
            self.assertFalse(usage.counted())


class ClassifyKeyTests(unittest.TestCase):
    def test_any_spelling_of_input(self) -> None:
        for name in (
            "input",
            "inputTokens",
            "input_tokens",
            "INPUT",
            "prompt",
            "promptTokenCount",
            "nPromptTokens",
            "prompt_eval_count",
        ):
            self.assertEqual(classify_key(name), "input", name)

    def test_cache_write_is_not_input(self) -> None:
        self.assertEqual(classify_key("cache_creation_input_tokens"), "cache_write")
        self.assertEqual(classify_key("cacheWriteInputTokens"), "cache_write")
        self.assertEqual(classify_key("ephemeral_5m_input_tokens"), "cache_write")

    def test_cache_read_under_short_names(self) -> None:
        self.assertEqual(classify_key("read", "cache"), "cache_hit")
        self.assertEqual(classify_key("write", "cache"), "cache_write")
        self.assertEqual(classify_key("cached_tokens"), "cache_hit")

    def test_ignores_totals_and_ids(self) -> None:
        self.assertIsNone(classify_key("total_tokens"))
        self.assertIsNone(classify_key("request_id"))
        self.assertIsNone(classify_key("failed"))


class HarvestNeverMissesFieldsTests(unittest.TestCase):
    def test_unknown_casing_still_counts(self) -> None:
        usage = harvest_text(json.dumps({"InputTokens": 5, "OutputTokens": 1, "Thinking": 2}))
        self.assertEqual(usage.input, 5)
        self.assertEqual(usage.output, 1)
        self.assertEqual(usage.reasoning, 2)

    def test_nested_tokens_object(self) -> None:
        usage = harvest_text(json.dumps({"input": {"tokens": 5}, "output": {"count": 2}}))
        self.assertEqual(usage.input, 5)
        self.assertEqual(usage.output, 2)

    def test_token_id_list_under_classified_key(self) -> None:
        usage = harvest_text(json.dumps({"input": [11, 12, 13, 14], "output_tokens": 2}))
        self.assertEqual(usage.input, 4)
        self.assertEqual(usage.output, 2)

    def test_spellings_that_were_never_on_a_vendor_list(self) -> None:
        usage = harvest_text(
            json.dumps({"nPromptTokens": 15, "numCompletionTokens": 4, "thoughtTokenCount": 6})
        )
        self.assertEqual(usage.input, 15)
        self.assertEqual(usage.output, 4)
        self.assertEqual(usage.reasoning, 6)

    def test_all_five_buckets(self) -> None:
        usage = harvest_text(
            json.dumps(
                {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "reasoning_tokens": 3,
                    "cache_read_input_tokens": 8,
                    "cache_creation_input_tokens": 2,
                }
            )
        )
        self.assertEqual(
            usage.as_dict(),
            {"input": 10, "output": 4, "reasoning": 3, "cacheHit": 8, "cacheWrite": 2},
        )
        self.assertEqual(usage.score(), 27)

    def test_zero_is_not_usage(self) -> None:
        usage = harvest_text(json.dumps({"input_tokens": 0, "output_tokens": 0}))
        self.assertFalse(usage.counted())
        self.assertEqual(usage.source, "none")


if __name__ == "__main__":
    unittest.main()
