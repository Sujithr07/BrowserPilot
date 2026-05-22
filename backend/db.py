import json
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Text, select

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


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
        )
        session.add(task)
        await session.commit()


async def get_task(task_id: str) -> dict | None:
    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return None
        return {
            "id": task.id,
            "goal": task.goal,
            "status": task.status,
            "plan_json": task.plan_json,
            "results_json": task.results_json,
            "final_answer": task.final_answer,
            "created_at": task.created_at,
        }
