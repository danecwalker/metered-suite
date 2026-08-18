# Metered suite

Official jobs for [Metered](https://github.com/danecwalker/metered). Harbor-shaped: you clone this repo, run your harness from the CLI, and we score the frozen tasks. The site ranks **finished work**, not `$/1M` stickers.

## Run

```bash
git clone https://github.com/danecwalker/metered-suite
cd metered-suite
python3 -m metered_suite init
python3 -m metered_suite <harness> --model <sku> --effort <level>
```

`init` writes local `harness.yaml` from CLIs on PATH. A run refuses to start until that file exists. Help lists only the keys in that file. Edit argv there if flags change. The file is not part of the official lock.

Examples after init, using names that landed in your `harness.yaml`:

```bash
python3 -m metered_suite --help
python3 -m metered_suite codex --model gpt-5.6-sol --effort max
python3 -m metered_suite qwen --model deepseek-v4-flash-0731 --effort max
python3 -m metered_suite grok --model grok-4.6 --effort xhigh
```

`codex` is the ChatGPT harness. Any named harness may drive any SKU. The published row is model × harness.

The runner execs the argv from `harness.yaml`, then harvests token usage and writes `usage.json`. Display names, lab, and list prices come from Metered's catalog when you upload.

That writes `out/<model>-<harness>-<effort>.metered.json`. Upload it at `/eval` on Metered.

Do not edit `tasks/` or `metered_suite/`. Those files are the official jobs. The sealed package hashes them. A swapped prompt or edited total fails verification.

```bash
python3 -m metered_suite --help
```

## What is official

Three Harbor-shaped jobs, in the style of [DeepSWE](https://deepswe.datacurve.ai) ([arXiv:2607.07946](https://arxiv.org/abs/2607.07946)): a real repo, a written-from-scratch prompt, and a hidden verifier.

| Id | Job |
| --- | --- |
| `queue` | Durable work queue |
| `jsonpatch` | RFC 6902 subset (`add` / `remove` / `replace` / `test`) |
| `ratelimit` | Sliding window and token bucket |

Same two-container split as DeepSWE v1.1 / Pier:

1. **Agent.** Workspace is copied out of `metered-suite-agent:py4.<task>` (repo + `base` commit only). Hidden tests and the reference solution never enter that tree. On Linux the harness CLI runs inside that container. On macOS the official CLIs are Darwin binaries, so the process stays on the host, jailed to that checkout; it still cannot see the grader.
2. **Verifier.** After the CLI exits we collect a git patch and apply it in `metered-suite-verify:py4.<task>` with `--network none`. Held-out tests run there. The site re-scores the verifier JSON (`ok`, `reward`) against the lock.

`$ / MU` needs every official job to pass **and** real token counts from the harvest. Zero usage is not a $0 rank.

Docker is required. The first run of each job builds its images. Set `METERED_REBUILD=1` to rebuild them.

`--max-attempts 0` (the default) keeps the same checkout and calls the harness again until the hidden verifier passes. A positive number is a hard cap. `--timeout` is seconds per attempt (default 2700). After each attempt the last patch and hidden-test log land in `out/<task>.last/`.

While the harness is running the suite prints the sandbox path, file writes, short CLI events, a spinner, and coloured pass/fail marks. No extra packages. `NO_COLOR=1` turns the colour off.

Tokens are not parsed per harness. After the CLI exits the suite harvests `input`, `output`, `reasoning`, `cacheHit`, and `cacheWrite` from stdout, stderr, `usage.json`, then session files under `.claude`, `.codex`, `.grok`, and similar. Session totals and turn/step events are classified so we do not double-count.

Approve flags such as `--yolo` live in `harness.yaml`. Do not pass them on the CLI. If a CLI is missing, install it and run `init` again, or uncomment that block in the file.

## Maintainers

```bash
python3 -m unittest discover -s tests -v
python3 -m metered_suite lock
```

Copy `lock.json` into the Metered repo as `src/features/eval/official-lock.json`.
