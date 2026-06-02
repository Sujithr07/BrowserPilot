from backend.agents.planner import plan_task, replan_task
from backend.agents.executor import ExecutorAgent
from backend.agents.verifier import VerifierAgent
from backend.schemas import TaskReport
from backend.db import save_task


class PlannerAgent:
    async def plan(self, goal: str):
        return await plan_task(goal)

    async def replan(self, goal: str, successful, failed):
        return await replan_task(goal, successful, failed)


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
        approval_callback=None,
    ) -> TaskReport:
        async def emit(event_type, data):
            if progress_callback is not None:
                await progress_callback(event_type, data)

        # Step 1: Plan
        plan = await self.planner.plan(goal)
        await emit("planned", plan.model_dump())

        # Step 2: Execute
        results = await self.executor.execute_plan(plan, approval_callback=approval_callback)
        for result in results:
            await emit("step_done", result.model_dump())

        # Step 3: Re-plan once if the last step failed (task ended on a failure,
        # not on task_complete which always leaves the last step as success)
        failed = [r for r in results if not r.success]
        if failed and not results[-1].success:
            successful = [r for r in results if r.success]
            recovery_plan = await self.planner.replan(goal, successful, failed)
            await emit("replanned", recovery_plan.model_dump())

            recovery_results = await self.executor.execute_plan(
                recovery_plan,
                approval_callback=approval_callback,
                step_offset=len(results),
            )
            for result in recovery_results:
                await emit("step_done", result.model_dump())

            # Merge: keep successful originals + all recovery results
            results = successful + recovery_results

        # Step 4: Verify
        report = await self.verifier.verify_and_report(goal, plan, results)
        report.task_id = task_id

        # Step 5: Save
        await save_task(report)

        return report
