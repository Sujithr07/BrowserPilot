"""
Centralized, env-configurable runtime settings.

All knobs that scale the system (pool size, worker concurrency, Redis, queue
toggle, headless) live here so the API process, the worker, and docker-compose
read the same source of truth. Provider API keys are NOT here — those stay in
backend/llm.py via LiteLLM's env convention.
"""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# Number of pre-warmed Chromium contexts in the BrowserPool (worker side).
BROWSER_POOL_SIZE = _int("BROWSER_POOL_SIZE", 2)

# Max jobs the arq worker runs at once. Defaults to the pool size so we never
# have more in-flight tasks than browser contexts to lend them.
WORKER_CONCURRENCY = _int("WORKER_CONCURRENCY", BROWSER_POOL_SIZE)

# Redis connection used by both the arq queue and the WS event bus.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# When true, POST /run-task enqueues onto arq and the WS bridges over Redis
# pub/sub. When false (no Redis in dev), the API runs the crew in-process and
# streams over the in-memory connection map (legacy behavior).
USE_QUEUE = _bool("USE_QUEUE", True)

# Headful by default (less bot-detectable). docker-compose sets BROWSER_HEADLESS=1
# because containers have no display.
BROWSER_HEADLESS = _bool("BROWSER_HEADLESS", False)

# Seconds a caller waits to lease a browser from the pool before giving up.
POOL_ACQUIRE_TIMEOUT = float(os.getenv("POOL_ACQUIRE_TIMEOUT", "120"))

# How long the worker blocks on a human approval decision before denying.
APPROVAL_TIMEOUT_S = float(os.getenv("APPROVAL_TIMEOUT_S", "300"))

# Hard ceiling arq gives a single job before killing it (browser tasks are long).
JOB_TIMEOUT_S = _int("JOB_TIMEOUT_S", 600)
