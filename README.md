# Metered suite

Official jobs for [Metered](https://github.com/danecwalker/metered). Harbor-shaped: you clone this repo, point `main.py` at your harness, and we score the frozen tasks. The site ranks **finished work**, not `$/1M` stickers.

## Run

```bash
git clone https://github.com/danecwalker/metered-suite
cd metered-suite
```

Edit **only** `main.py`:

- `HARNESS` — `claude`, `chatgpt`, `grok`, `qwen`, `pi`, `opencode`
- `MODEL` — the SKU (must fit that harness; Claude SKUs cannot be filed as ChatGPT)
- `EFFORT` and `FLAGS` (extra CLI flags only — not a different binary)

Display names, lab, and list prices come from Metered’s catalog when you upload. High-reputation accounts can file a run for a SKU that is not on the catalog yet. An admin still screens every run.

Then:

```bash
python3 -m metered_suite
```

That writes `out/<model>-<harness>-<effort>.metered.json`. Upload it at `/eval` on Metered.

Do not edit `tasks/` or `metered_suite/`. Those files are the official jobs. The sealed package hashes them. A swapped prompt or edited total fails verification.

## What is official

Five tasks. Each one asks for an `answer.json`. Hidden expected values live next to the instruction. After your harness exits, the runner re-scores that file. Metered’s website re-scores it again against the same lock.

`$ / M ET` still needs every task to pass **and** real token counts. If your harness writes `usage.json` in the task workspace (`input`, `output`, `reasoning`, `cacheHit`), those numbers go in the bill. If it does not, the package can still verify as a pass/fail — it cannot rank as cheap.

## Maintainers

```bash
python3 -m metered_suite lock
```

Copy `lock.json` into the Metered repo as `src/features/eval/official-lock.json`.
