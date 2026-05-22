from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from backend.crew import AgentFlowCrew
from backend.db import init_db, get_task
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


@app.on_event("startup")
async def startup():
    await init_db()


@app.post("/run-task")
async def run_task(body: dict):
    goal = body.get("goal")
    task_id = body.get("task_id") or str(uuid.uuid4())[:8]
    
    crew = AgentFlowCrew()
    
    async def progress_callback(event_type: str, data: dict):
        # Send progress to connected websocket if any
        if task_id in websocket_connections:
            ws = websocket_connections[task_id]
            try:
                await ws.send_json({"event": event_type, "data": data})
            except:
                pass
    
    async def run_background():
        try:
            report = await crew.run_task(goal, task_id, progress_callback)
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
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if task_id in websocket_connections:
            del websocket_connections[task_id]


@app.get("/replay/{task_id}")
async def replay_task(task_id: str):
    task = await get_task(task_id)
    if task is None:
        return {"error": "Task not found"}, 404
    return task


@app.get("/health")
async def health():
    return {"status": "ok"}
