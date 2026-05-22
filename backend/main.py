from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from backend.crew import AgentFlowCrew
from backend.db import init_db, get_task
from backend.agents.executor import _observation_cache
import asyncio
import json
import uuid

app = FastAPI(title="AgentFlow")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active tasks and their websocket connections
active_tasks = {}
websocket_connections = {}
# Pending approval futures per task — executor awaits these until frontend responds
approval_futures: dict[str, asyncio.Future] = {}


@app.on_event("startup")
async def startup():
    await init_db()


@app.post("/run-task")
async def run_task(body: dict):
    goal = body.get("goal")
    task_id = body.get("task_id") or str(uuid.uuid4())[:8]
    
    crew = AgentFlowCrew()
    
    async def progress_callback(event_type: str, data: dict):
        if task_id in websocket_connections:
            ws = websocket_connections[task_id]
            try:
                await ws.send_json({"event": event_type, "data": data})
            except:
                pass

    async def approval_callback(step_info: dict) -> bool:
        """Send approval_required event, wait up to 5 min for frontend response."""
        if task_id not in websocket_connections:
            return False
        ws = websocket_connections[task_id]
        try:
            await ws.send_json({"event": "approval_required", "data": step_info})
        except Exception:
            return False
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        approval_futures[task_id] = future
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=300.0)
        except asyncio.TimeoutError:
            approval_futures.pop(task_id, None)
            return False

    async def run_background():
        try:
            report = await crew.run_task(goal, task_id, progress_callback, approval_callback)
            # Send completion event
            if task_id in websocket_connections:
                ws = websocket_connections[task_id]
                try:
                    await ws.send_json({"event": "completed", "data": report.model_dump()})
                except:
                    pass
        except Exception as e:
            # Send error event
            if task_id in websocket_connections:
                ws = websocket_connections[task_id]
                try:
                    await ws.send_json({"event": "error", "data": {"message": str(e)}})
                except:
                    pass
        finally:
            # Clean up
            if task_id in active_tasks:
                del active_tasks[task_id]
    
    # Start background task
    asyncio.create_task(run_background())
    active_tasks[task_id] = "running"
    
    return {"task_id": task_id, "status": "started"}


@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()
    websocket_connections[task_id] = websocket

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "approval_response" and task_id in approval_futures:
                    future = approval_futures.pop(task_id)
                    if not future.done():
                        future.set_result(bool(msg.get("approved", False)))
            except (json.JSONDecodeError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if task_id in websocket_connections:
            del websocket_connections[task_id]
        # Auto-deny any pending approval when connection closes
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
    return {
        "status": "ok",
        "vision_cache": {
            "lru_hits": _observation_cache.hits,
            "lru_misses": _observation_cache.misses,
            "lru_size": len(_observation_cache._store),
            "lru_hit_rate": round(_observation_cache.hits / total, 3) if total else 0.0,
        },
    }
