import json
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Text, Integer, Float, select

from backend.schemas import TaskReport

DATABASE_URL = "sqlite+aiosqlite:///./agentflow.db"

Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True)
    goal = Column(String)
    status = Column(String)
    plan_json = Column(Text)
    results_json = Column(Text)
    final_answer = Column(Text)
    created_at = Column(String)
    # Previously dropped on save — now persisted so a replayed task is complete.
    total_steps = Column(Integer)
    successful_steps = Column(Integer)
    metrics_json = Column(Text)
    # Full fidelity: the entire TaskReport serialized, so get_task can rebuild it
    # exactly even as the schema grows. The columns above stay for queryability.
    report_json = Column(Text)


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Columns added after the original schema shipped. SQLAlchemy's create_all does
# not ALTER existing tables, so we add any missing column to an existing DB.
_ADDED_COLUMNS = {
    "total_steps": "INTEGER",
    "successful_steps": "INTEGER",
    "metrics_json": "TEXT",
    "report_json": "TEXT",
}


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migration for pre-existing agentflow.db files.
        rows = await conn.exec_driver_sql("PRAGMA table_info(tasks)")
        existing = {row[1] for row in rows.fetchall()}
        for name, sql_type in _ADDED_COLUMNS.items():
            if name not in existing:
                await conn.exec_driver_sql(
                    f"ALTER TABLE tasks ADD COLUMN {name} {sql_type}"
                )


async def save_task(report: TaskReport):
    async with async_session() as session:
        task = Task(
            id=report.task_id,
            goal=report.goal,
            status=report.status,
            plan_json=report.plan.model_dump_json(),
            results_json=json.dumps([r.model_dump() for r in report.step_results]),
            final_answer=report.final_answer,
            created_at=report.created_at,
            total_steps=report.total_steps,
            successful_steps=report.successful_steps,
            metrics_json=report.metrics.model_dump_json(),
            report_json=report.model_dump_json(),
        )
        # merge() upserts so re-saving a task id (e.g. after replay) won't crash.
        await session.merge(task)
        await session.commit()


async def list_tasks(limit: int = 50) -> list[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(Task.id, Task.goal, Task.status, Task.created_at)
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        return [
            {"task_id": r.id, "goal": r.goal, "status": r.status, "created_at": r.created_at}
            for r in result.fetchall()
        ]


async def get_task(task_id: str) -> dict | None:
    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return None
        # Prefer the full serialized report when present (newer rows); fall back
        # to assembling from columns for rows written before report_json existed.
        if task.report_json:
            return json.loads(task.report_json)
        return {
            "task_id": task.id,
            "goal": task.goal,
            "status": task.status,
            "plan": json.loads(task.plan_json) if task.plan_json else None,
            "step_results": json.loads(task.results_json) if task.results_json else [],
            "final_answer": task.final_answer,
            "created_at": task.created_at,
            "total_steps": task.total_steps,
            "successful_steps": task.successful_steps,
            "metrics": json.loads(task.metrics_json) if task.metrics_json else {},
        }
