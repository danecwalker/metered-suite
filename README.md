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

One Harbor-shaped job (`durable-queue`), in the style of [DeepSWE](https://deepswe.datacurve.ai) ([arXiv:2607.07946](https://arxiv.org/abs/2607.07946)): a real repo, a written-from-scratch prompt, and a hidden verifier.

Same two-container split as DeepSWE v1.1 / Pier:

1. **Agent.** Workspace is copied out of `metered-suite-agent:py2` (repo + `base` commit only). Hidden tests and the reference solution never enter that tree. On Linux the harness CLI runs inside that container. On macOS the official CLIs are Darwin binaries, so the process stays on the host, jailed to that checkout; it still cannot see the grader.
2. **Verifier.** After the CLI exits we collect a git patch and apply it in `metered-suite-verify:py2` with `--network none`. Held-out tests run there. The site re-scores the verifier JSON (`ok`, `reward`) against the lock.

`$ / MU` needs the job to pass **and** real token counts from the harness adapter. Zero usage is not a $0 rank.

Docker is required. The first run builds the two images. Set `METERED_REBUILD=1` to rebuild them.

Optional in `main.py`: `TIMEOUT_SEC` (default 45 minutes per attempt) and `MAX_ATTEMPTS`. `MAX_ATTEMPTS = 0` (the default) keeps the same checkout and calls the harness again until the hidden verifier passes. A positive number is a hard cap. After each attempt the last patch and hidden-test log land in `out/<task>.last/`. `$ / MU` is only defined on a pass.

While the harness is running the suite prints file writes, short CLI events, and a `still running` heartbeat so a long think is not a silent hang.

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
