# AgentFlow Eval Harness

WebVoyager-style evaluation: run `AgentFlowCrew` over a dataset of web tasks,
score each with an LLM-as-judge, and produce a Markdown report.

## Layout

| File | Purpose |
|------|---------|
| `dataset.jsonl` | ~50 tasks across Wikipedia, Allrecipes, GitHub, arXiv, Google Maps. Rows: `{id, web_name, question, answer_reference}` |
| `runner.py` | Async harness: bounded concurrency, per-task timeout + step cap, progress bar |
| `judge.py` | LLM-as-judge via `reasoning_completion()`; chain set by `JUDGE_MODELS` |
| `report.py` | Renders `results/REPORT.md` from `results/results.jsonl` |
| `results/` | Output: `results.jsonl`, `meta.json`, `REPORT.md` |

## Run

```bash
make eval                 # full dataset (live), writes results/REPORT.md
make eval-smoke           # 3-task CI smoke subset (live)
make eval-mock            # harness self-test: no keys, no browser, no network
make eval-report          # re-render REPORT.md from the last results

# or directly:
python -m eval.runner --report
python -m eval.runner --smoke --concurrency 1 --report
python -m eval.runner --mock --report
python -m eval.runner --dataset path/to/custom.jsonl --concurrency 8 --limit 10
```

## Configuration (env or CLI flag; CLI wins)

| Env | Flag | Default | Meaning |
|-----|------|---------|---------|
| `EVAL_DATASET` | `--dataset` | `eval/dataset.jsonl` | dataset path |
| `EVAL_CONCURRENCY` | `--concurrency` | `4` | max simultaneous tasks |
| `EVAL_TIMEOUT` | `--timeout` | `180` | per-task seconds |
| `EVAL_MAX_STEPS` | `--max-steps` | `15` | executor step cap (sets `EXECUTOR_MAX_STEPS`) |
| `EVAL_RESULTS_DIR` | `--results-dir` | `eval/results` | output directory |
| `JUDGE_MODELS` | — | `REASONING_MODELS` | judge fallback chain |

All provider API keys (`GROQ_API_KEY`, `GEMINI_API_KEY`, …) are read from the
environment / `.env` by `backend/llm.py` — the harness adds no new key handling.

## Scoring

The judge calls `reasoning_completion(models=JUDGE_MODELS)` with the question,
reference answer, and the agent's `final_answer`, and returns `SUCCESS`/`FAILURE`
plus a one-line reason. Because it reuses `reasoning_completion`, the judge gets
the same provider-fallback behavior as the agent, but on an independently
configurable chain — set `JUDGE_MODELS` to a stronger/neutral model than the one
under test.

## Notes

- Each task runs its own `AgentFlowCrew` (and browser); concurrency bounds how
  many run at once. The agent's browser launches **headful** — in CI, run under
  `xvfb-run` (see `.github/workflows/eval.yml`).
- `mock` mode produces deterministic fake outcomes so CI can validate the harness
  wiring without keys, a browser, or network. A mock `REPORT.md` is clearly
  labeled as a self-test, not a real eval.
- SQLite is written by `crew.run_task`; very high concurrency may hit
  `database is locked` — lower `--concurrency` if so.
