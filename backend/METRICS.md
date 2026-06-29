# Metrics & Observability

records token usage, USD cost, latency, and vision-cache effectiveness
for every task — **without changing tool selection, model outputs, or the
fallback chain.** Metrics are read *after* each LLM call returns; they never feed
back into a decision.

## Toggle

```bash
METRICS_ENABLED=1   # default — record metrics
METRICS_ENABLED=0   # zero overhead: every metrics entry point returns on line 1
```

When disabled, no response is inspected, `litellm.completion_cost` is never
called, no lock is taken, and no per-task state is allocated. (Verified by
`tests/test_metrics.py::test_record_call_is_noop_when_disabled`, which passes a
response object that raises on *any* attribute access — nothing
touches it while disabled.)

## What is measured and how

| Field | Source | Notes |
|-------|--------|-------|
| `input_tokens` / `output_tokens` / `total_tokens` | `response.usage.prompt_tokens` / `.completion_tokens` / `.total_tokens` | Summed across every call in the task |
| `cost_usd` | `litellm.completion_cost(completion_response=response)` | LiteLLM's price table, per call. Models it can't price contribute `$0` |
| `reasoning_calls` / `vision_calls` | call site (`reasoning_completion` vs `vision_completion`) | `vision_calls` = vision API calls **actually sent** |
| `vision_cache_hits` | `_ObservationCache` hit in `executor._observe_page` | A vision call we did **not** make |
| `vision_cache_hit_rate` | `hits / (hits + vision_calls)` | Fraction of vision observations served from cache |
| `vision_cost_saved_usd` | `hits × running-average vision call cost` | Early hits (before any priced vision call) are valued at `$0`, not guessed |
| `llm_latency_s` / `avg_latency_s` / `latency_s_max` | `time.perf_counter()` around `litellm.completion(...)` | Wall-clock, per call |
| `served_by` / `primary_provider` | `response.model` | **Which model in the fallback chain actually served the call** — e.g. shows when Groq was rate-limited and GitHub GPT-4o-mini took over |

### How task attribution works

LLM functions (`reasoning_completion`, `vision_completion`) did **not** grow a
`task_id` parameter — that would touch the fallback signatures. Instead
`crew.run_task` binds a `contextvars.ContextVar` for the duration of the task:

```
crew.run_task(task_id)            # metrics.set_task(task_id)
  └─ planner / executor / verifier
        └─ llm.py                 # metrics.record_call(...) reads the ContextVar
```

This is async-safe and also correct across the executor's dedicated Proactor
thread. Calls made outside any task still count toward the **global** aggregate.

### Coverage note

The **verifier** still calls Groq via its own SDK rather than the LiteLLM layer.
To keep per-task cost complete, its single call is recorded explicitly in
`verifier.py` (observe-only — the call itself is unchanged). Everything else goes
through `backend/llm.py`.

## Where the numbers surface

- **WebSocket** — `crew` emits a `metrics` event when the task finishes, so the
  frontend can show `cost: $0.00x, vision cache hit-rate: NN%, served by: <provider>`.
  The `completed` event's `report.metrics` carries the same data.
- **`GET /metrics`** — global aggregate; `GET /metrics?task_id=<id>` for one task.
  Both include the LRU `vision_cache` counters.
- **`GET /health`** — adds `metrics_enabled` plus headline `totals.cost_usd` /
  `totals.total_tokens`, so a liveness probe doubles as a spend check.
- **Persistence** — `db.py` stores the full `TaskReport` (including `metrics`) in
  `report_json`, plus `total_steps` / `successful_steps` / `metrics_json` columns
  that were previously dropped on save. Existing DBs are migrated in `init_db()`
  via idempotent `ALTER TABLE ADD COLUMN`.

## Example run

Goal: *"Find the current price of the iPhone 16."* — 1 plan call, 4 executor
steps, 3 vision observations (with 2 served from the `_ObservationCache`), and 1
verifier call. Costs are real `litellm.completion_cost` values for
`groq/llama-3.3-70b-versatile` and `gemini/gemini-2.5-flash`.

`GET /metrics?task_id=demo-7f3a`:

```json
{
  "task_id": "demo-7f3a",
  "metrics": {
    "input_tokens": 11100,
    "output_tokens": 1070,
    "total_tokens": 12170,
    "cost_usd": 0.007002,
    "reasoning_calls": 6,
    "vision_calls": 3,
    "vision_cache_hits": 2,
    "vision_cache_hit_rate": 0.4,
    "vision_cost_saved_usd": 0.00121,
    "llm_latency_s": 8.87,
    "avg_latency_s": 0.986,
    "latency_s_max": 1.61,
    "errors": 0,
    "served_by": {
      "groq/llama-3.3-70b-versatile": 6,
      "gemini/gemini-2.5-flash": 3
    },
    "primary_provider": "groq/llama-3.3-70b-versatile"
  },
  "vision_cache": { "lru_hits": 2, "lru_misses": 3, "lru_size": 3, "lru_hit_rate": 0.4 }
}
```

Per-task WebSocket summary the frontend renders:

> **cost: $0.0070** · **vision cache hit-rate: 40%** · **served by: groq/llama-3.3-70b-versatile**

Reading it: 5 vision observations were needed but only **3** hit the API — the
LRU served the other 2, saving an estimated **$0.0012**. All reasoning went to
Groq (no fallback was triggered this run); had Groq been rate-limited, `served_by`
would also list `github/gpt-4o-mini`.

## Adding a new metric

1. Add the field to `_new_agg()` and update it in `record_call` / `record_cache_hit`.
2. Surface it in `_summarize()`.
3. If it should reach the report/DB, add it to `TaskMetrics` in `schemas.py`
   (it then persists automatically via `report_json` / `metrics_json`).
