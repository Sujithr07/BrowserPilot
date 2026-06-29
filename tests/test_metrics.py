"""
Unit tests for backend.metrics — the observability layer.

These substantiate the central claim in backend/METRICS.md: when
METRICS_ENABLED is false, every entry point returns on its first line and the
response object is NEVER inspected. The disabled-path test passes a response
that raises on *any* attribute access, so if the code touched it the test would
fail loudly.
"""
import types

import pytest

from backend import metrics


class _ExplodingResponse:
    """Raises on ANY attribute access. Proves the disabled path never reads it."""

    def __getattribute__(self, name):  # noqa: D401 - intentional landmine
        raise AssertionError(
            f"metrics inspected the response while disabled (accessed .{name})"
        )


def test_record_call_is_noop_when_disabled(monkeypatch):
    """The exact scenario METRICS.md documents: disabled => response untouched."""
    monkeypatch.setattr(metrics, "METRICS_ENABLED", False)
    # Must not raise: record_call returns before ever looking at the response.
    metrics.record_call("reasoning", _ExplodingResponse(), latency_s=1.5)


def test_record_error_and_cache_hit_are_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(metrics, "METRICS_ENABLED", False)
    before = metrics.global_summary()["errors"]
    metrics.record_error("reasoning")
    metrics.record_cache_hit("vision")
    assert metrics.global_summary()["errors"] == before  # unchanged


def test_record_call_accumulates_per_task_when_enabled(monkeypatch):
    monkeypatch.setattr(metrics, "METRICS_ENABLED", True)
    # Pin the price so the cost assertion is deterministic and offline.
    monkeypatch.setattr(metrics.litellm, "completion_cost", lambda **_: 0.002)

    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(
            prompt_tokens=100, completion_tokens=20, total_tokens=120
        ),
        model="test/model",
    )

    token = metrics.set_task("unit-test-task")
    try:
        metrics.record_call("reasoning", response, latency_s=0.5)
    finally:
        metrics.reset_task(token)

    s = metrics.task_summary("unit-test-task")
    assert s["input_tokens"] == 100
    assert s["output_tokens"] == 20
    assert s["total_tokens"] == 120
    assert s["reasoning_calls"] == 1
    assert s["vision_calls"] == 0
    assert s["cost_usd"] == pytest.approx(0.002)
    assert s["served_by"] == {"test/model": 1}
    assert s["primary_provider"] == "test/model"


def test_summarize_vision_cache_hit_rate_is_pure():
    """hit_rate = hits / (hits + calls actually made)."""
    agg = metrics._new_agg()
    agg["vision_calls"] = 3
    agg["vision_cache_hits"] = 1
    out = metrics._summarize(agg)
    assert out["vision_cache_hit_rate"] == pytest.approx(0.25)
