import os
import base64
import json
import asyncio
import hashlib
import google.generativeai as genai

from backend.browser import BrowserManager
from backend.schemas import TaskPlan, StepResult, TaskTool


class ExecutorAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self.browser = BrowserManager()

    async def execute_plan(self, plan: TaskPlan) -> list[StepResult]:
        results = []
        task_id = hashlib.md5(plan.goal.encode()).hexdigest()[:8]

        try:
            await self.browser.start()
        except Exception as e:
            for step in plan.steps:
                results.append(
                    StepResult(
                        step_number=step.step_number,
                        success=False,
                        observation="",
                        extracted_data={},
                        screenshot_path=None,
                        error=f"Browser failed to start: {e}",
                    )
                )
            return results

        for i, step in enumerate(plan.steps):
            step_num = i + 1
            screenshot_path = f"screenshots/{task_id}_{step_num}.png"
            success = True
            error_msg = None
            observation = ""
            extracted_data = {}

            try:
                if step.tool == TaskTool.navigate:
                    await self.browser.navigate(step.target)
                elif step.tool == TaskTool.click:
                    await self.browser.click(step.target)
                elif step.tool == TaskTool.type_text:
                    await self.browser.type_text(step.target, step.instruction)
                elif step.tool == TaskTool.extract:
                    observation = await self.browser.extract_text()
                elif step.tool == TaskTool.search:
                    await self.browser.search(step.target)
                elif step.tool == TaskTool.scroll:
                    await self.browser.scroll()
                else:
                    raise ValueError(f"Unknown tool: {step.tool}")
            except Exception as e:
                success = False
                error_msg = str(e)
                observation = error_msg

            try:
                await self.browser.take_screenshot(screenshot_path)
            except Exception as e:
                if not error_msg:
                    error_msg = f"Screenshot failed: {e}"
                success = False
                screenshot_path = None

            if success and screenshot_path and os.path.exists(screenshot_path):
                try:
                    with open(screenshot_path, "rb") as f:
                        image_bytes = f.read()
                    base64_image = base64.b64encode(image_bytes).decode("utf-8")

                    prompt_text = (
                        f"Look at this browser screenshot. The intended action was: {step.instruction}\n"
                        f"The expected outcome was: {step.expected_outcome}\n"
                        f"Did this step succeed? What do you see on screen?\n"
                        f'Reply in JSON: {{"success": true/false, "observation": "what you see", '
                        f'"extracted_data": {{}}}}'
                    )

                    response = self.model.generate_content(
                        [
                            {"mime_type": "image/png", "data": base64_image},
                            prompt_text,
                        ]
                    )

                    response_text = response.text
                    json_text = response_text
                    if "```json" in json_text:
                        json_text = json_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in json_text:
                        json_text = json_text.split("```")[1].split("```")[0].strip()

                    parsed = json.loads(json_text)
                    success = parsed.get("success", success)
                    observation = parsed.get("observation", observation)
                    extracted_data = parsed.get("extracted_data", extracted_data)
                except Exception as e:
                    observation = f"Gemini analysis failed: {e}"

            results.append(
                StepResult(
                    step_number=step.step_number,
                    success=success,
                    observation=observation,
                    extracted_data=extracted_data,
                    screenshot_path=screenshot_path,
                    error=error_msg,
                )
            )

        try:
            await self.browser.stop()
        except Exception:
            pass

        return results
