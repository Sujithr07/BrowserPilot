import asyncio
import json
import uuid
import contextlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.crew import AgentFlowCrew
from backend.db import init_db, get_task
from backend.agents.executor import _observation_cache
from backend import metrics
from backend.logging_config import configure_logging, get_logger

configure_logging()
log = get_logger("agentflow.api")

app = FastAPI(title="AgentFlow")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-process (USE_QUEUE=0) transport state ────────────────────────────────────
# Used only when the job queue is disabled: the crew runs in this process and
# streams over these in-memory maps (legacy behavior, no Redis required).
active_tasks: dict[str, str] = {}
websocket_connections: dict[str, WebSocket] = {}
approval_futures: dict[str, asyncio.Future] = {}


@app.on_event("startup")
async def startup():
    await init_db()
    if config.USE_QUEUE:
        # Lazy imports so the app still boots without redis/arq installed when
        # USE_QUEUE=0 (pure in-process dev).
        from arq import create_pool
        from arq.connections import RedisSettings
        from backend.events import EventBus

        app.state.arq = await create_pool(RedisSettings.from_dsn(config.REDIS_URL))
        app.state.bus = EventBus(config.REDIS_URL)
        log.info("api.startup", extra={"mode": "queue", "redis": config.REDIS_URL})
    else:
        app.state.arq = None
        app.state.bus = None
        log.info("api.startup", extra={"mode": "in-process"})


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown: release Redis connections (uvicorn calls this on SIGTERM)."""
    arq = getattr(app.state, "arq", None)
    if arq is not None:
        await arq.aclose()
    bus = getattr(app.state, "bus", None)
    if bus is not None:
        await bus.close()
    log.info("api.shutdown")


@app.post("/run-task")
async def run_task(body: dict):
    goal = body.get("goal")
    task_id = body.get("task_id") or str(uuid.uuid4())[:8]

    if config.USE_QUEUE:
        # Enqueue and return immediately; the worker runs the crew. _job_id=task_id
        # dedupes so the same task can't be double-queued.
        await app.state.arq.enqueue_job("run_task_job", goal, task_id, _job_id=task_id)
        log.info("task.enqueued", extra={"task_id": task_id, "goal": goal})
        return {"task_id": task_id, "status": "queued"}

    # ── Legacy in-process path ──────────────────────────────────────────────
    await _run_task_in_process(goal, task_id)
    return {"task_id": task_id, "status": "started"}


async def _run_task_in_process(goal: str, task_id: str):
    """USE_QUEUE=0: run the crew here and stream over the in-memory socket map."""
    crew = AgentFlowCrew()

    async def progress_callback(event_type: str, data: dict):
        ws = websocket_connections.get(task_id)
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send_json({"event": event_type, "data": data})

    async def approval_callback(step_info: dict) -> bool:
        ws = websocket_connections.get(task_id)
        if ws is None:
            return False
        with contextlib.suppress(Exception):
            await ws.send_json({"event": "approval_required", "data": step_info})
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        approval_futures[task_id] = future
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=config.APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            approval_futures.pop(task_id, None)
            return False

    async def run_background():
        try:
            report = await crew.run_task(goal, task_id, progress_callback, approval_callback)
            ws = websocket_connections.get(task_id)
            if ws is not None:
                with contextlib.suppress(Exception):
                    await ws.send_json({"event": "completed", "data": report.model_dump()})
        except Exception as e:
            ws = websocket_connections.get(task_id)
            if ws is not None:
                with contextlib.suppress(Exception):
                    await ws.send_json({"event": "error", "data": {"message": str(e)}})
        finally:
            active_tasks.pop(task_id, None)

    asyncio.create_task(run_background())
    active_tasks[task_id] = "running"


@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()
    if config.USE_QUEUE:
        await _ws_queue_bridge(websocket, task_id)
    else:
        await _ws_in_process(websocket, task_id)


async def _ws_queue_bridge(websocket: WebSocket, task_id: str):
    """Bridge a socket to the worker: Redis events -> WS, WS approvals -> Redis."""
    bus = app.state.bus
    async with bus.subscribe_events(task_id) as events:

        async def forward():
            async for evt in events:
                with contextlib.suppress(Exception):
                    await websocket.send_json(evt)

        fwd = asyncio.create_task(forward())
        try:
            while True:
                raw = await websocket.receive_text()
                with contextlib.suppress(json.JSONDecodeError):
                    msg = json.loads(raw)
                    if msg.get("type") == "approval_response":
                        await bus.send_approval(task_id, bool(msg.get("approved", False)))
        except WebSocketDisconnect:
            pass
        finally:
            fwd.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fwd


async def _ws_in_process(websocket: WebSocket, task_id: str):
    """Legacy in-memory socket handling (USE_QUEUE=0)."""
    websocket_connections[task_id] = websocket
    try:
        while True:
            raw = await websocket.receive_text()
            with contextlib.suppress(json.JSONDecodeError, Exception):
                msg = json.loads(raw)
                if msg.get("type") == "approval_response" and task_id in approval_futures:
                    future = approval_futures.pop(task_id)
                    if not future.done():
                        future.set_result(bool(msg.get("approved", False)))
    except WebSocketDisconnect:
        pass
    finally:
        websocket_connections.pop(task_id, None)
        # Auto-deny any pending approval when the connection closes.
        if task_id in approval_futures:
            future = approval_futures.pop(task_id)
            if not future.done():
                future.set_result(False)


@app.get("/replay/{task_id}")
async def replay_task(task_id: str):
    task = await get_task(task_id)
    if task is None:
        return {"error": "Task not found"}, 404
    return task


@app.get("/health")
async def health():
    total = _observation_cache.hits + _observation_cache.misses
    g = metrics.global_summary()
    health_doc = {
        "status": "ok",
        "mode": "queue" if config.USE_QUEUE else "in-process",
        "pool_size": config.BROWSER_POOL_SIZE,
        "worker_concurrency": config.WORKER_CONCURRENCY,
        "metrics_enabled": metrics.METRICS_ENABLED,
        "vision_cache": {
            "lru_hits": _observation_cache.hits,
            "lru_misses": _observation_cache.misses,
            "lru_size": len(_observation_cache._store),
            "lru_hit_rate": round(_observation_cache.hits / total, 3) if total else 0.0,
        },
        # Headline cost/usage so a liveness probe doubles as a spend check.
        "totals": {"cost_usd": g["cost_usd"], "total_tokens": g["total_tokens"]},
    }
    # In queue mode, surface Redis reachability so the probe reflects the backbone.
    if config.USE_QUEUE:
        try:
            await app.state.arq.ping()
            health_doc["redis"] = "ok"
        except Exception as e:
            health_doc["status"] = "degraded"
            health_doc["redis"] = f"unreachable: {e}"
    return health_doc


@app.get("/metrics")
async def get_metrics(task_id: str | None = None):
    """
    Aggregated observability metrics. Without a query param, returns the global
    process-wide aggregate; with ?task_id=<id>, returns that task's summary.
    Combines LLM token/cost/latency with the _ObservationCache (LRU) counters.
    """
    total = _observation_cache.hits + _observation_cache.misses
    cache = {
        "lru_hits": _observation_cache.hits,
        "lru_misses": _observation_cache.misses,
        "lru_size": len(_observation_cache._store),
        "lru_hit_rate": round(_observation_cache.hits / total, 3) if total else 0.0,
    }
    if task_id:
        return {"task_id": task_id, "metrics": metrics.task_summary(task_id), "vision_cache": cache}
    return {"global": metrics.global_summary(), "vision_cache": cache}
