"""
arq worker: consumes `run_task_job` from Redis and runs AgentFlowCrew against a
pre-warmed BrowserPool, fanning progress events back to the API over Redis.

Concurrency is bounded twice over: arq's `max_jobs` (== WORKER_CONCURRENCY,
default = pool size) caps in-flight jobs, and `pool.acquire()` blocks if every
context is busy — so we never run more tasks than we have warmed contexts.

Run:  arq backend.worker.WorkerSettings

Graceful shutdown: arq installs SIGTERM/SIGINT handlers that stop pulling new
jobs and let in-flight jobs finish (drain); `on_shutdown` then closes the pooled
browsers and the Redis bus.
"""
from arq.connections import RedisSettings

from backend import config
from backend.crew import AgentFlowCrew
from backend.db import init_db
from backend.events import EventBus
from backend.pool import BrowserPool
from backend.logging_config import get_logger

log = get_logger("agentflow.worker")


async def run_task_job(ctx: dict, goal: str, task_id: str) -> dict:
    """One queued task: lease a browser, run the crew, stream events to Redis."""
    bus: EventBus = ctx["bus"]
    pool: BrowserPool = ctx["pool"]
    log.info("job.start", extra={"task_id": task_id, "goal": goal})

    async def progress_callback(event_type: str, data: dict):
        await bus.publish_event(task_id, event_type, data)

    async def approval_callback(step_info: dict) -> bool:
        # Subscribe first, then publish the prompt (see wait_approval docstring),
        # then block for the human decision up to the timeout.
        async def _emit_prompt():
            await bus.publish_event(task_id, "approval_required", step_info)

        resp = await bus.wait_approval(
            task_id, timeout=config.APPROVAL_TIMEOUT_S, after_subscribe=_emit_prompt
        )
        approved = bool(resp and resp.get("approved"))
        log.info("job.approval", extra={"task_id": task_id, "approved": approved})
        return approved

    try:
        # Lease a warmed context; the pool resets and reclaims it on exit.
        async with pool.acquire() as browser:
            crew = AgentFlowCrew(browser=browser)
            report = await crew.run_task(
                goal, task_id, progress_callback, approval_callback
            )
        await bus.publish_event(task_id, "completed", report.model_dump())
        log.info("job.done", extra={"task_id": task_id, "status": report.status})
        return {"task_id": task_id, "status": report.status}
    except Exception as e:
        log.exception("job.error", extra={"task_id": task_id})
        # Surface the failure to the waiting WebSocket too.
        await bus.publish_event(task_id, "error", {"message": str(e)})
        raise


async def startup(ctx: dict):
    log.info("worker.startup", extra={
        "pool_size": config.BROWSER_POOL_SIZE,
        "concurrency": config.WORKER_CONCURRENCY,
    })
    await init_db()
    ctx["bus"] = EventBus(config.REDIS_URL)
    pool = BrowserPool(config.BROWSER_POOL_SIZE)
    await pool.start()
    ctx["pool"] = pool


async def shutdown(ctx: dict):
    # Reached after arq has drained in-flight jobs on SIGTERM/SIGINT.
    log.info("worker.shutdown")
    pool: BrowserPool = ctx.get("pool")
    if pool is not None:
        await pool.stop()
    bus: EventBus = ctx.get("bus")
    if bus is not None:
        await bus.close()


class WorkerSettings:
    functions = [run_task_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(config.REDIS_URL)
    # Bound concurrency to the warmed-context count (or WORKER_CONCURRENCY).
    max_jobs = config.WORKER_CONCURRENCY
    # Browser tasks are long; give a job generous headroom before arq kills it.
    job_timeout = config.JOB_TIMEOUT_S
    # Do NOT auto-retry a failed job: a browser task is expensive and the
    # browser/network (resilience.py) and LLM (LiteLLM) layers already retry
    # internally. A job-level failure is terminal — re-running would re-spend quota.
    max_tries = 1
