import os
import json
import uuid
from datetime import datetime
from groq import Groq
from backend.schemas import TaskPlan, StepResult, TaskReport, TaskTool


class VerifierAgent:
    """Verifies task completion and generates a final report using Groq API."""
    
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
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
        
        # Collect all extracted data from successful steps
        combined_data = {}
        for result in step_results:
            if result.success and result.extracted_data:
                combined_data.update(result.extracted_data)
        
        # Build summary string
        summary_lines = []
        for result in step_results:
            status = "✓" if result.success else "✗"
            summary_lines.append(f"Step {result.step_number}: {status} - {result.observation}")
        summary = "\n".join(summary_lines)
        
        # Call Groq for verification
        prompt = f"""You are verifying whether a web automation task was completed.
Original goal: {goal}
Steps executed:
{summary}
Extracted data: {json.dumps(combined_data, indent=2)}

Was the goal achieved? Write a concise final answer summarising what was accomplished and any key data extracted. If the goal was not achieved, explain what failed. Be specific and helpful."""
        
        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        final_answer = response.choices[0].message.content
        
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
