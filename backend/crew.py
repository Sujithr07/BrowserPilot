import asyncio
from datetime import datetime

from backend.agents.planner import plan_task, replan_task, decompose_task
from backend.agents.executor import ExecutorAgent
from backend.agents.verifier import VerifierAgent
from backend.schemas import TaskPlan, StepResult, TaskReport, TaskMetrics
from backend.db import save_task
from backend import config, metrics

# Step-number stride between branches so their steps/screenshots never collide in
# the merged report or in the progress stream (branch i steps start at i*STRIDE+1).
_BRANCH_STRIDE = 1000


class PlannerAgent:
    async def plan(self, goal: str):
        return await plan_task(goal)

    async def decompose(self, goal: str):
        return await decompose_task(goal)

    async def replan(self, goal: str, successful, failed):
        return await replan_task(goal, successful, failed)


class AgentFlowCrew:
    def __init__(self, browser=None):
        # `browser` (a pooled LeasedBrowser) is injected by the worker so the crew
        # reuses a pre-warmed context instead of launching its own. When None the
        # executor falls back to a standalone per-task BrowserManager.
        #
        # For PARALLEL tasks, branch 0 runs on this primary executor/browser while
        # each extra branch gets its OWN standalone BrowserManager. That keeps the
        # shared BrowserPool out of the fan-out, so branches can never contend for
        # or deadlock on it.
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent(browser=browser)
        self.verifier = VerifierAgent()

    async def run_task(
        self,
        goal: str,
        task_id: str,
        progress_callback=None,
        approval_callback=None,
        cancel_event=None,
    ) -> TaskReport:
        # Serialize progress emits: parallel branches call this concurrently and a
        # WebSocket / pub/sub sink can't be written from two tasks at once.
        emit_lock = asyncio.Lock()

        async def emit(event_type, data):
            if progress_callback is not None:
                async with emit_lock:
                    await progress_callback(event_type, data)

        # Bind every LLM call made during this task to task_id so backend.metrics
        # attributes tokens/cost/latency correctly. The contextvar is copied into
        # each branch's asyncio task, so per-branch calls are attributed too.
        _metrics_token = metrics.set_task(task_id)
        try:
            # Step 1: Plan — try to split the goal into independent parallel branches.
            branches = await self._build_branches(goal)
            combined_plan = self._combine_plans(goal, branches)
            await emit("planned", combined_plan.model_dump())

            # Step 2/3: Execute (+ replan once on failure), parallel or sequential.
            if len(branches) > 1:
                results = await self._run_parallel(
                    branches, approval_callback, emit, cancel_event=cancel_event,
                    task_id=task_id,
                )
            else:
                results = await self._run_branch(
                    self.executor, branches[0], approval_callback, emit,
                    step_offset=0, cancel_event=cancel_event, task_id=task_id,
                )

            # Stopped by the user: skip the verifier (another LLM call) and persist
            # a partial report from whatever steps completed.
            if cancel_event is not None and cancel_event.is_set():
                report = self._build_stopped_report(goal, task_id, combined_plan, results)
                summary = metrics.task_summary(task_id)
                report.metrics = TaskMetrics(**{
                    k: v for k, v in summary.items() if k in TaskMetrics.model_fields
                })
                await emit("metrics", summary)
                await save_task(report)
                return report

            # Step 4: Verify over the original goal and the merged results.
            report = await self.verifier.verify_and_report(goal, combined_plan, results)
            report.task_id = task_id

            # Step 5: Attach metrics + emit a per-task summary for the frontend.
            summary = metrics.task_summary(task_id)
            report.metrics = TaskMetrics(**{
                k: v for k, v in summary.items() if k in TaskMetrics.model_fields
            })
            await emit("metrics", summary)

            # Step 6: Save (full report, including metrics, persisted by db.py)
            await save_task(report)

            return report
        finally:
            metrics.reset_task(_metrics_token)

    def _build_stopped_report(self, goal, task_id, plan, results) -> TaskReport:
        """Assemble a report for a user-stopped run from the partial results,
        without invoking the verifier (so a Stop never spends more tokens)."""
        successful = sum(1 for r in results if r.success)
        return TaskReport(
            task_id=task_id,
            goal=goal,
            status="stopped",
            plan=plan,
            step_results=results,
            final_answer="Task stopped by the user before completion.",
            total_steps=len(results),
            successful_steps=successful,
            created_at=datetime.utcnow().isoformat(),
        )

    # ── Planning ──────────────────────────────────────────────────────────────
    async def _build_branches(self, goal: str) -> list[TaskPlan]:
        """Return the branches to execute. Multiple => run in parallel; one =>
        the normal sequential path. Falls back to a single plan on any failure."""
        if config.PARALLEL_ENABLED:
            try:
                dec = await self.planner.decompose(goal)
                if dec.parallel and len(dec.branches) >= 2:
                    return dec.branches[: config.MAX_PARALLEL_BRANCHES]
                if len(dec.branches) == 1:
                    return dec.branches
            except Exception:
                pass  # fall through to a plain single plan
        return [await self.planner.plan(goal)]

    def _combine_plans(self, goal: str, branches: list[TaskPlan]) -> TaskPlan:
        """Merge branch plans into one plan for the report/verifier and the
        'planned' event. Purely for display — execution uses the branches. Steps
        are renumbered 1..N so the plan preview reads cleanly (the live step
        events carry the real per-branch numbers + a branch tag)."""
        steps = []
        n = 1
        for b in branches:
            for s in b.steps:
                steps.append(s.model_copy(update={"step_number": n}))
                n += 1
        estimated = sum(b.estimated_steps for b in branches) or len(steps) or 1
        return TaskPlan(goal=goal, steps=steps, estimated_steps=estimated)

    async def _emit_steps(self, results, branch, emit):
        """Tag each result with its 1-based branch (when parallel) so the tag
        persists into the saved report, then stream it to the UI."""
        for result in results:
            if branch is not None:
                result.branch = branch + 1
            await emit("step_done", result.model_dump())

    # ── Execution ───────────────────────────────────────────────────────────--
    async def _run_branch(
        self, executor, plan, approval_callback, emit, step_offset=0, branch=None,
        cancel_event=None, task_id=None,
    ) -> list[StepResult]:
        """Execute one plan, emit each step, and replan once if it ends on a
        failure. This is the original sequential pipeline, factored out so both
        the single-branch and per-branch parallel paths share it. `branch` (a
        0-based index, or None for a single-branch task) tags the emitted steps.
        `task_id` names the screenshots; step_offset keeps branches from colliding."""
        results = await executor.execute_plan(
            plan, approval_callback=approval_callback, step_offset=step_offset,
            cancel_event=cancel_event, task_id=task_id,
        )
        await self._emit_steps(results, branch, emit)

        # Re-plan once if the last step failed (task_complete always leaves the
        # last step as success, so this only fires on a genuine dead end). Skip the
        # recovery (an LLM call + more steps) entirely if the user has stopped.
        stopped = cancel_event is not None and cancel_event.is_set()
        failed = [r for r in results if not r.success]
        if failed and results and not results[-1].success and not stopped:
            successful = [r for r in results if r.success]
            recovery_plan = await self.planner.replan(plan.goal, successful, failed)
            await emit("replanned", recovery_plan.model_dump())
            recovery_results = await executor.execute_plan(
                recovery_plan,
                approval_callback=approval_callback,
                step_offset=step_offset + len(results),
                cancel_event=cancel_event,
                task_id=task_id,
            )
            await self._emit_steps(recovery_results, branch, emit)
            results = successful + recovery_results
        return results

    async def _run_parallel(
        self, branches, approval_callback, emit, cancel_event=None, task_id=None
    ) -> list[StepResult]:
        """Run branches concurrently and merge their step results. Branch 0 uses
        the primary executor; extra branches get standalone browsers so the pool
        is never contended. A branch crashing doesn't sink the others."""
        async def run_one(i, branch):
            executor = self.executor if i == 0 else ExecutorAgent(browser=None)
            return await self._run_branch(
                executor, branch, approval_callback, emit,
                step_offset=i * _BRANCH_STRIDE, branch=i, cancel_event=cancel_event,
                task_id=task_id,
            )

        branch_results = await asyncio.gather(
            *(run_one(i, b) for i, b in enumerate(branches)),
            return_exceptions=True,
        )

        merged: list[StepResult] = []
        for i, br in enumerate(branch_results):
            if isinstance(br, Exception):
                merged.append(StepResult(
                    step_number=i * _BRANCH_STRIDE + 1,
                    success=False,
                    observation="",
                    extracted_data={},
                    screenshot_path=None,
                    error=f"Branch {i + 1} ({branches[i].goal}) failed: {br}",
                ))
            else:
                merged.extend(br)
        return merged
