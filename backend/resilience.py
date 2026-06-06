"""
Reusable async retry + circuit-breaker utility for the network/browser layer.

Scope: this guards *transport-flaky* operations — Playwright navigations and
page actions that can fail transiently (timeouts, navigation aborts, renderer
hiccups). It is deliberately NOT used for LLM calls: provider retries and
fallback are already handled by LiteLLM in backend/llm.py, and duplicating them
here would double-retry and distort the metrics layer.

Two primitives, composed by `call_resilient`:
  * RetryPolicy  — bounded retries with exponential backoff + jitter, restricted
                   to a whitelist of exception types.
  * CircuitBreaker — after N consecutive failures the circuit OPENS and calls
                   fail fast (CircuitBreakerOpen) for a cooldown, then HALF-OPENs
                   to probe recovery. Protects a wedged browser/site from being
                   hammered by every queued task.
"""
import asyncio
import random
import time
from dataclasses import dataclass, field

from backend.logging_config import get_logger

log = get_logger("agentflow.resilience")


@dataclass
class RetryPolicy:
    attempts: int = 3                       # total tries (1 = no retry)
    base_delay: float = 0.5                 # seconds before the 2nd try
    max_delay: float = 8.0
    backoff: float = 2.0                    # delay multiplier per retry
    jitter: float = 0.2                     # +/- fraction randomization
    retry_on: tuple[type[BaseException], ...] = (Exception,)

    def delay_for(self, attempt: int) -> float:
        """Backoff delay before `attempt` (1-indexed retry number)."""
        raw = min(self.base_delay * (self.backoff ** (attempt - 1)), self.max_delay)
        return raw * (1 + random.uniform(-self.jitter, self.jitter))


class CircuitBreakerOpen(Exception):
    """Raised when a call is rejected because the breaker is OPEN."""


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5              # consecutive failures to trip OPEN
    reset_timeout: float = 30.0             # seconds OPEN before HALF_OPEN probe
    _failures: int = field(default=0, init=False)
    _state: str = field(default="closed", init=False)   # closed | open | half_open
    _opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> str:
        return self._state

    async def allow(self) -> None:
        """Raise CircuitBreakerOpen if calls are currently blocked."""
        async with self._lock:
            if self._state == "open":
                if time.monotonic() - self._opened_at >= self.reset_timeout:
                    self._state = "half_open"
                    log.info("circuit.half_open", extra={"breaker": self.name})
                else:
                    raise CircuitBreakerOpen(f"{self.name} circuit is open")

    async def record_success(self) -> None:
        async with self._lock:
            if self._state != "closed":
                log.info("circuit.closed", extra={"breaker": self.name})
            self._failures = 0
            self._state = "closed"

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            # A failed probe in half_open, or hitting the threshold, opens it.
            if self._state == "half_open" or self._failures >= self.failure_threshold:
                if self._state != "open":
                    log.warning(
                        "circuit.open",
                        extra={"breaker": self.name, "failures": self._failures},
                    )
                self._state = "open"
                self._opened_at = time.monotonic()


async def call_resilient(
    fn,
    *,
    policy: RetryPolicy,
    breaker: CircuitBreaker | None = None,
    name: str = "",
):
    """
    Run `fn` (a zero-arg coroutine factory) with retries and an optional breaker.

    `fn` is called fresh on each attempt so dispatched coroutines are rebuilt.
    Re-raises the last error after exhausting attempts; raises CircuitBreakerOpen
    immediately when the breaker is open (this is NOT retried).
    """
    last_exc: BaseException | None = None
    for attempt in range(1, policy.attempts + 1):
        if breaker is not None:
            await breaker.allow()   # CircuitBreakerOpen propagates (fail fast)
        try:
            result = await fn()
            if breaker is not None:
                await breaker.record_success()
            return result
        except policy.retry_on as exc:
            last_exc = exc
            if breaker is not None:
                await breaker.record_failure()
            if attempt >= policy.attempts:
                log.warning(
                    "retry.exhausted",
                    extra={"op": name, "attempts": attempt, "error": str(exc)},
                )
                raise
            delay = policy.delay_for(attempt)
            log.info(
                "retry.attempt",
                extra={"op": name, "attempt": attempt, "next_delay_s": round(delay, 2),
                       "error": str(exc)},
            )
            await asyncio.sleep(delay)
    # Unreachable, but keeps type-checkers happy.
    raise last_exc  # type: ignore[misc]
