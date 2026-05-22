import os
import json
import hashlib
import PIL.Image
from google import genai
from google.genai import types

from backend.browser import BrowserManager
from backend.schemas import TaskPlan, StepResult, TaskTool


class ExecutorAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"
        self.browser = BrowserManager()

    async def _observe_page(self, screenshot_path: str, step) -> dict:
        """
        Send the screenshot to Gemini Vision and get a structured observation.
        Returns a dict with observation, visual success flag, extracted data, and any issue detected.
        Falls back gracefully if vision fails.
        """
        try:
            image = PIL.Image.open(screenshot_path)

            prompt = f"""You are a browser automation agent reviewing a screenshot taken after executing a step.

Step context:
- Tool used: {step.tool}
- Target: {step.target}
- Instruction: {step.instruction}
- Expected outcome: {step.expected_outcome}

Analyze the screenshot and respond with ONLY a valid JSON object (no markdown fences, no explanation):
{{
  "observation": "1-2 sentences describing exactly what is visible on screen right now",
  "step_succeeded_visually": true or false,
  "extracted_data": {{}},
  "issue": null
}}

Rules:
- "observation": describe the actual page content visible — page title, main content, any forms, results, errors
- "step_succeeded_visually": true if the screen matches the expected outcome, false if you see an error page, CAPTCHA, login wall, wrong page, or blocked content
- "extracted_data": include any useful information visible — prices, search results, article text, product names, error messages, headings
- "issue": null if everything looks correct; otherwise a short description of the problem (e.g. "CAPTCHA detected", "404 error page", "login required", "rate limited")"""

            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, image],
            )
            text = response.text.strip()

            # Strip markdown code fences if model wrapped the JSON
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

            return json.loads(text)

        except json.JSONDecodeError:
            # Vision responded but output wasn't valid JSON — use raw text as observation
            raw = response.text.strip()[:400] if "response" in dir() else "Page state observed"
            return {
                "observation": raw,
                "step_succeeded_visually": None,
                "extracted_data": {},
                "issue": None,
            }
        except Exception as e:
            # Vision call failed entirely — return empty fallback, don't crash the pipeline
            return {
                "observation": "",
                "step_succeeded_visually": None,
                "extracted_data": {},
                "issue": f"Vision unavailable: {e}",
            }

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

            # Execute the browser action
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

            # Take screenshot (always attempt, even on action failure)
            try:
                await self.browser.take_screenshot(screenshot_path)
            except Exception as e:
                screenshot_path = None
                if not error_msg:
                    error_msg = f"Screenshot failed: {e}"
                    success = False

            # Vision observation — run on every step that has a screenshot
            if screenshot_path and os.path.exists(screenshot_path):
                vision = await self._observe_page(screenshot_path, step)

                # Use vision's description as the canonical observation
                if vision["observation"]:
                    observation = vision["observation"]

                # Merge any data Gemini extracted from the page
                if vision.get("extracted_data"):
                    extracted_data = vision["extracted_data"]

                # If the action appeared to succeed but Gemini sees a clear failure on screen,
                # override the success flag so the verifier and frontend know
                if success and vision.get("step_succeeded_visually") is False:
                    success = False
                    issue = vision.get("issue") or "Visual check: step did not succeed as expected"
                    error_msg = issue

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
