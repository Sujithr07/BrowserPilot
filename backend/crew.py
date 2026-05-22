from backend.agents.planner import plan_task
from backend.agents.executor import ExecutorAgent
from backend.agents.verifier import VerifierAgent
from backend.schemas import TaskReport
from backend.db import save_task


class PlannerAgent:
    async def plan(self, goal: str):
        return await plan_task(goal)


class AgentFlowCrew:
    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.verifier = VerifierAgent()

    async def run_task(
        self,
        goal: str,
        task_id: str,
        progress_callback=None,
    ) -> TaskReport:
        # Step 1: Plan
        plan = await self.planner.plan(goal)
        if progress_callback is not None:
            await progress_callback("planned", plan.model_dump())

        # Step 2: Execute
        results = await self.executor.execute_plan(plan)
        for result in results:
            if progress_callback is not None:
                await progress_callback("step_done", result.model_dump())

        # Step 3: Verify
        report = await self.verifier.verify_and_report(goal, plan, results)
        report.task_id = task_id

        # Step 4: Save
        await save_task(report)

        return report
