# Metered suite

Official jobs for [Metered](https://github.com/danecwalker/metered). Harbor-shaped: you clone this repo, point `main.py` at your harness, and we score the frozen tasks. The site ranks **finished work**, not `$/1M` stickers.

## Run

```bash
git clone https://github.com/danecwalker/metered-suite
cd metered-suite
```

Edit **only** `main.py`:

- `HARNESS` — `claude`, `chatgpt`, `gemini`, `grok`, `qwen`, `kimi`, `deepseek`, `opencode`, `pi`
- `MODEL` — the SKU (must fit that harness; Claude SKUs cannot be filed as ChatGPT)
- `EFFORT` and `FLAGS` (extra CLI flags only — not a different binary, not `--model`)

Each named harness has a small adapter. The runner execs that CLI with that tool’s JSON/JSONL flag, parses token usage, and writes `usage.json` itself. Display names, lab, and list prices come from Metered’s catalog when you upload. High-reputation accounts can file a run for a SKU that is not on the catalog yet. An admin still screens every run.

Then:

```bash
python3 -m metered_suite
```

That writes `out/<model>-<harness>-<effort>.metered.json`. Upload it at `/eval` on Metered.

Do not edit `tasks/` or `metered_suite/`. Those files are the official jobs. The sealed package hashes them. A swapped prompt or edited total fails verification.

## What is official

Five tasks. Each one asks for an `answer.json`. Hidden expected values live next to the instruction. After your harness exits, the runner re-scores that file. Metered’s website re-scores it again against the same lock.

`$ / M ET` needs every task to pass **and** real token counts from the harness adapter. Zero usage is not a $0 rank.

| HARNESS | Binary | How we count tokens |
| --- | --- | --- |
| `claude` | `claude` | `claude --print --output-format json` → `result.usage` |
| `chatgpt` | `codex` | `codex exec --json` → last `turn.completed.usage` |
| `gemini` | `gemini` | `gemini --output-format json` → `stats.models.*.tokens` |
| `grok` | `grok` | `grok --single --output-format json` |
| `qwen` | `qwen` / `qwen-code` | `qwen --output-format json` (Gemini-CLI-shaped stats) |
| `kimi` | `kimi` | `kimi --prompt --output-format stream-json` → turn `usage.record` |
| `deepseek` | `deepcode` / `deepseek` | print + JSON usage, Claude- or OpenAI-shaped |
| `opencode` | `opencode` | `opencode run --format json` → sum `step_finish.part.tokens` |
| `pi` | `pi` | `pi --mode json` → last `message_end` usage |

`api` and `custom` cannot invent a binary. Put extra permission flags in `FLAGS` (for example `--dangerously-skip-permissions`). Do not set `--model` there.

## Maintainers

```bash
python3 -m unittest discover -s tests -v
python3 -m metered_suite lock
```

Copy `lock.json` into the Metered repo as `src/features/eval/official-lock.json`.
