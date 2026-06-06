# Scaling: Browser Pool + Job Queue

AgentFlow can run two ways behind the **same external API** (`POST /run-task`,
`WS /ws/task/{id}`), selected by `USE_QUEUE`:

| Mode | `USE_QUEUE` | How it runs | Needs Redis |
|------|-------------|-------------|-------------|
| In-process (legacy) | `0` | API process runs the crew in a background task; streams over an in-memory socket map; one browser per task | No |
| Queued (scalable) | `1` (default) | `POST /run-task` enqueues onto **arq**; a **worker** runs the crew on a pre-warmed **BrowserPool**; progress fans back over **Redis pub/sub** | Yes |

```
                 enqueue            af:events:{id} (pub/sub)
  client ──HTTP──► API ──arq──► Redis ──► worker ──► AgentFlowCrew
     ▲   WS /ws/task/{id}          ▲          │            │ leases
     └──────────────────────────────┘         │            ▼
        API subscribes to af:events:{id}       │      BrowserPool (N contexts)
        and forwards to the socket.            │
        Approvals: WS ─► af:approval:{id} ─────┘ (worker is blocked awaiting it)
```

## Components

- **`pool.py` — BrowserPool / LeasedBrowser.** Launches one Chromium and
  pre-warms `BROWSER_POOL_SIZE` **contexts** (isolated sessions, shared process).
  `async with pool.acquire() as browser:` lends a warmed context and resets it
  (clear cookies + `about:blank`) on return. All Playwright calls go through one
  shared `_ProactorLoopThread`, so Windows subprocess launch keeps working under
  uvicorn/arq Selector loops. `LeasedBrowser` and the standalone `BrowserManager`
  share the same `_PageSession` action API, so pooled and per-task paths behave
  identically.

- **`worker.py` — arq worker.** Consumes `run_task_job(goal, task_id)`. Leases a
  browser, runs `AgentFlowCrew(browser=...)`, and publishes `planned/step_done/
  metrics/completed/error` (and `approval_required`) to `af:events:{task_id}`.
  Concurrency is bounded twice: arq `max_jobs` (= `WORKER_CONCURRENCY`, default =
  pool size) **and** `pool.acquire()` blocking — never more tasks than contexts.

- **`events.py` — EventBus.** Thin Redis pub/sub wrapper. Forward channel
  `af:events:{id}` carries progress; reverse channel `af:approval:{id}` carries
  the human approval decision back to the blocked worker. `wait_approval` accepts
  an `after_subscribe` hook so the worker subscribes *before* publishing the
  prompt — no missed/raced replies.

- **`resilience.py` — retry + circuit breaker.** Wraps the **network layer only**
  (`browser.navigate`): the `networkidle → domcontentloaded` fallback is now a
  retried, breaker-protected op. Page actions (click/type) are **not** retried
  (Playwright already auto-waits, and a bad selector would burn another timeout).
  LLM retries/fallback stay in LiteLLM (`llm.py`) — deliberately not duplicated.

## Graceful shutdown (SIGTERM)

- **Worker:** arq installs SIGTERM/SIGINT handlers → stops pulling new jobs,
  lets in-flight jobs **drain**, then `on_shutdown` closes the pooled browsers and
  Redis. `docker-compose` sets `stop_grace_period: 60s` so a long task can finish.
  `max_tries = 1`: a failed job is terminal (no expensive auto re-run).
- **API:** uvicorn's SIGTERM triggers the FastAPI shutdown event, which closes the
  arq pool and the event bus.

## Configuration (`backend/config.py`, all env-overridable)

| Env | Default | Meaning |
|-----|---------|---------|
| `USE_QUEUE` | `1` | Queue mode (Redis) vs in-process |
| `REDIS_URL` | `redis://localhost:6379` | Queue + event bus |
| `BROWSER_POOL_SIZE` | `2` | Pre-warmed contexts per worker |
| `WORKER_CONCURRENCY` | = pool size | arq `max_jobs` |
| `BROWSER_HEADLESS` | `0` | `1` in containers (no display) |
| `POOL_ACQUIRE_TIMEOUT` | `120` | Seconds to wait for a free context |
| `APPROVAL_TIMEOUT_S` | `300` | Worker wait for a human decision |
| `JOB_TIMEOUT_S` | `600` | arq hard job ceiling |
| `NAV_RETRY_ATTEMPTS` / `NAV_BREAKER_THRESHOLD` / `NAV_BREAKER_RESET_S` | `2` / `8` / `20` | navigation resilience |
| `LOG_LEVEL` | `INFO` | structured (JSON) log level |

Provider API keys (`GROQ_API_KEY`, …) are unchanged — read by `llm.py` via LiteLLM.

## Run locally

```bash
# Full stack (Redis + API + worker), headless worker:
docker compose up --build
docker compose up --scale worker=3        # more workers

# No Redis? In-process mode keeps the same API:
USE_QUEUE=0 uvicorn backend.main:app --reload
```

`GET /health` reports `mode`, `pool_size`, `worker_concurrency`, and (queue mode)
Redis reachability.
