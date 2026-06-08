import json
import uuid
from datetime import datetime
from backend.llm import reasoning_completion
from backend.schemas import TaskPlan, StepResult, TaskReport


# Caps to keep the verifier prompt small. The merged extracted_data (esp. multiple
# extract_text page dumps) used to push this single call past 14k tokens, which
# helped exhaust the daily quota. Trim hard — the verifier only needs the gist.
_MAX_OBS_CHARS = 300       # per-step observation line in the summary
_MAX_VALUE_CHARS = 800     # per extracted_data value
_MAX_DATA_CHARS = 3000     # total extracted_data blob in the prompt


def _truncate(text, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


class VerifierAgent:
    """Verifies task completion and generates a final report.

    Routes through the LiteLLM layer (backend.llm) so a rate-limited / quota'd
    primary provider transparently fails over to the next model — the verifier
    used to call Groq directly with no fallback, so a 429 here failed the whole
    task even though execution had succeeded.
    """

    async def verify_and_report(
        self,
        goal: str,
        plan: TaskPlan,
        step_results: list[StepResult]
    ) -> TaskReport:
        """
        Verify whether a web automation task was completed and generate a report.
        
        Args:
            goal: The original user goal
            plan: The execution plan that was used
            step_results: Results of each executed step
            
        Returns:
            TaskReport with verification status and final answer
        """
        # Count successful steps
        successful_steps = sum(1 for result in step_results if result.success)
        total_steps = len(step_results)
        
        # Collect all extracted data from successful steps, truncating each value
        # and the whole blob so a few large page dumps can't blow up the prompt.
        combined_data = {}
        for result in step_results:
            if result.success and result.extracted_data:
                for k, v in result.extracted_data.items():
                    combined_data[k] = _truncate(v, _MAX_VALUE_CHARS)
        data_blob = _truncate(json.dumps(combined_data, indent=2, default=str), _MAX_DATA_CHARS)

        # Build summary string (observations trimmed — full text lives in the data)
        summary_lines = []
        for result in step_results:
            status = "✓" if result.success else "✗"
            summary_lines.append(
                f"Step {result.step_number}: {status} - {_truncate(result.observation, _MAX_OBS_CHARS)}"
            )
        summary = "\n".join(summary_lines)

        prompt = f"""You are verifying whether a web automation task was completed.
Original goal: {goal}
Steps executed:
{summary}
Extracted data: {data_blob}

Was the goal achieved? Write a concise final answer summarising what was accomplished and any key data extracted. If the goal was not achieved, explain what failed. Be specific and helpful."""

        # Through the LiteLLM layer: automatic provider fallback on 429/quota, and
        # usage is recorded inside reasoning_completion (no manual metrics here).
        # If EVERY provider is exhausted we still return a report built from the
        # data already gathered, rather than erroring the whole task at the finish.
        try:
            response = reasoning_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            final_answer = response.choices[0].message.content
        except Exception as e:
            final_answer = (
                "Automated summary unavailable (the language model could not be reached: "
                f"{e}). Raw data gathered during the task:\n{data_blob}"
            )
        
        # Determine status
        if successful_steps == total_steps:
            status = "completed"
        elif successful_steps > 0:
            status = "partial"
        else:
            status = "failed"
        
        # Build TaskReport
        report = TaskReport(
            task_id=str(uuid.uuid4())[:8],
            goal=goal,
            status=status,
            plan=plan,
            step_results=step_results,
            final_answer=final_answer,
            total_steps=total_steps,
            successful_steps=successful_steps,
            created_at=datetime.utcnow().isoformat()
        )
        
        return report
