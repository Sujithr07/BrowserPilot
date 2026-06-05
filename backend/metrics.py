"""
Observability layer: per-task and global LLM usage / cost / latency metrics.

Design goals
------------
* OBSERVE ONLY. Nothing here changes tool selection, the fallback chain, or any
  model output. It reads `response.usage`, `response.model`, and
  `litellm.completion_cost(response)` AFTER a call has already happened.
* ZERO OVERHEAD WHEN DISABLED. Every public entry point returns on the first
  line when METRICS_ENABLED is false — no locking, no cost computation, no dict
  growth. Toggle with the env flag `METRICS_ENABLED=0`.
* TASK ATTRIBUTION WITHOUT SIGNATURE CHANGES. The "current" task id flows through
  a ContextVar that crew.run_task sets for the duration of a task, so llm.py and
  the executor can record against the right task without every function growing a
  task_id parameter.

Aggregates tracked, per task and globally:
  - input / output / total tokens
  - USD cost (summed per call from litellm.completion_cost)
  - reasoning vs. vision call counts
  - vision API calls actually MADE vs. _ObservationCache hits, plus an estimate
    of the dollars those hits saved (hits x running average vision call cost)
  - latency: total + max per call
  - which provider in the fallback chain actually served each call (response.model)
"""
import os
import threading
from contextvars import ContextVar

import litellm

# Read once at import. Disabled => every entry point below is an immediate no-op.
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "1").lower() in ("1", "true", "yes", "on")

# The task currently executing on this async context. crew.run_task sets/resets it.
# Default None => calls outside a task still count toward the global aggregate only.
_current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)

# Aggregates are mutated from the executor's Proactor thread and the request loop,
# so guard them with a plain lock. Contention is negligible (a few ops per call).
_lock = threading.Lock()


def _new_agg() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "reasoning_calls": 0,
        "vision_calls": 0,        # vision API calls actually sent (cache misses)
        "vision_cost_usd": 0.0,   # subset of cost_usd spent on vision (for avg)
        "vision_cache_hits": 0,
        "vision_cost_saved_usd": 0.0,
        "latency_s_total": 0.0,
        "latency_s_max": 0.0,
        "errors": 0,
        "served_by": {},          # provider/model string -> call count
    }


_global: dict = _new_agg()
_tasks: dict[str, dict] = {}


# ── Task context helpers (called by crew.run_task) ──────────────────────────────

def set_task(task_id: str):
    """Bind the current async context to task_id. Returns a token for reset_task."""
    return _current_task_id.set(task_id)


def reset_task(token) -> None:
    if token is not None:
        _current_task_id.reset(token)


def _task_agg(task_id: str | None) -> dict | None:
    if not task_id:
        return None
    agg = _tasks.get(task_id)
    if agg is None:
        agg = _new_agg()
        _tasks[task_id] = agg
    return agg


# ── Recording (called by llm.py / verifier after a real call) ───────────────────

def _usage_tokens(response) -> tuple[int, int, int]:
    """Pull (prompt, completion, total) tokens from an OpenAI-shaped response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or (prompt + completion)
    return prompt, completion, total


def record_call(kind: str, response, latency_s: float) -> None:
    """
    Record one completed LLM call. `kind` is "reasoning" or "vision".

    Best-effort: any failure to read usage/cost is swallowed so metrics never
    break a real task. Does nothing when METRICS_ENABLED is false.
    """
    if not METRICS_ENABLED:
        return
    try:
        prompt_t, completion_t, total_t = _usage_tokens(response)
        # completion_cost reads the provider+model off the response and applies
        # LiteLLM's price table. Returns 0.0 for models it can't price.
        try:
            cost = float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:
            cost = 0.0
        model = getattr(response, "model", None) or "unknown"
        is_vision = kind == "vision"

        task_id = _current_task_id.get()
        with _lock:
            for agg in (a for a in (_global, _task_agg(task_id)) if a is not None):
                agg["input_tokens"] += prompt_t
                agg["output_tokens"] += completion_t
                agg["total_tokens"] += total_t
                agg["cost_usd"] += cost
                agg["latency_s_total"] += latency_s
                agg["latency_s_max"] = max(agg["latency_s_max"], latency_s)
                agg["served_by"][model] = agg["served_by"].get(model, 0) + 1
                if is_vision:
                    agg["vision_calls"] += 1
                    agg["vision_cost_usd"] += cost
                    agg["reasoning_calls"] += 0
                else:
                    agg["reasoning_calls"] += 1
    except Exception:
        # Observability must never crash the pipeline it observes.
        pass


def record_error(kind: str) -> None:
    """Count a call that raised (e.g. all providers in the chain failed)."""
    if not METRICS_ENABLED:
        return
    task_id = _current_task_id.get()
    with _lock:
        for agg in (a for a in (_global, _task_agg(task_id)) if a is not None):
            agg["errors"] += 1


def record_cache_hit(kind: str = "vision") -> None:
    """
    Record an _ObservationCache hit (a vision call we DIDN'T make). The dollar
    saving is estimated as the running average cost of an actual vision call,
    so early hits (before any priced vision call) are valued at $0 rather than
    guessed.
    """
    if not METRICS_ENABLED:
        return
    task_id = _current_task_id.get()
    with _lock:
        # Average over the GLOBAL vision history — more stable than per-task.
        avg = (
            _global["vision_cost_usd"] / _global["vision_calls"]
            if _global["vision_calls"]
            else 0.0
        )
        for agg in (a for a in (_global, _task_agg(task_id)) if a is not None):
            agg["vision_cache_hits"] += 1
            agg["vision_cost_saved_usd"] += avg


# ── Summaries (called by crew / the HTTP endpoints) ─────────────────────────────

def _summarize(agg: dict) -> dict:
    """Derive reporting fields from a raw aggregate. Pure; takes a copy's values."""
    vision_total = agg["vision_calls"] + agg["vision_cache_hits"]
    hit_rate = round(agg["vision_cache_hits"] / vision_total, 3) if vision_total else 0.0
    calls = agg["reasoning_calls"] + agg["vision_calls"]
    primary = max(agg["served_by"].items(), key=lambda kv: kv[1])[0] if agg["served_by"] else ""
    return {
        "input_tokens": agg["input_tokens"],
        "output_tokens": agg["output_tokens"],
        "total_tokens": agg["total_tokens"],
        "cost_usd": round(agg["cost_usd"], 6),
        "reasoning_calls": agg["reasoning_calls"],
        "vision_calls": agg["vision_calls"],
        "vision_cache_hits": agg["vision_cache_hits"],
        "vision_cache_hit_rate": hit_rate,
        "vision_cost_saved_usd": round(agg["vision_cost_saved_usd"], 6),
        "llm_latency_s": round(agg["latency_s_total"], 3),
        "latency_s_max": round(agg["latency_s_max"], 3),
        "avg_latency_s": round(agg["latency_s_total"] / calls, 3) if calls else 0.0,
        "errors": agg["errors"],
        "served_by": dict(agg["served_by"]),
        "primary_provider": primary,
    }


def task_summary(task_id: str) -> dict:
    """Reporting summary for one task. Empty (zeroed) summary if untracked."""
    with _lock:
        agg = _tasks.get(task_id)
        return _summarize(agg if agg is not None else _new_agg())


def global_summary() -> dict:
    """Process-wide aggregate plus the number of distinct tasks seen."""
    with _lock:
        summary = _summarize(_global)
        summary["tasks_tracked"] = len(_tasks)
        summary["enabled"] = METRICS_ENABLED
        return summary
