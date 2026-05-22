import os
import json
import hashlib
import PIL.Image
from google import genai
from groq import Groq

from backend.browser import BrowserManager
from backend.schemas import TaskPlan, StepResult

# ─────────────────────────────────────────────────────────────────────────────
# Formal JSON-schema tool definitions for Groq function calling.
# The LLM selects from these on every step based on what it observes on screen.
# ─────────────────────────────────────────────────────────────────────────────
BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate the browser to a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL including https://",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an element on the page using a CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector for the element to click "
                            "(e.g. 'button[type=submit]', 'a.nav-link', '#search-btn')"
                        ),
                    }
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text into an input field or textarea.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for the input field",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type",
                    },
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_text",
            "description": "Extract all visible text from the current page for reading content.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search Google for a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the page down to reveal more content.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": (
                "Signal that the task has been fully completed. "
                "Call this when you have achieved the goal or gathered all required information. "
                "Also call this if you hit an unresolvable obstacle (CAPTCHA, login required, page not found)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished and any key data found",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are a browser automation agent. Use the provided tools to complete the user's goal step by step.

After each tool call you will receive a visual observation describing what is currently on screen.
Use those observations to decide what to do next — adapt if the page looks different from what you expected.

Rules:
- Always navigate to a page before trying to click or type on it
- Use search() to find pages when you do not know the exact URL
- Use extract_text() when you need to read content from the page
- Call task_complete() when the goal is fully achieved OR when you hit an obstacle you cannot overcome
- Do not repeat the exact same failing action more than twice"""


class ExecutorAgent:
    def __init__(self):
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY environment variable is not set")

        # Gemini Vision — observes each screenshot after an action
        self.vision_client = genai.Client(api_key=gemini_key)
        self.vision_model = "gemini-2.0-flash"

        # Groq — drives the agentic tool-calling loop
        self.groq = Groq(api_key=groq_key)

        self.browser = BrowserManager()

    # ─────────────────────────────────────────────────────────────────────────
    # Vision observation
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_page(self, screenshot_path: str, context: dict) -> dict:
        """
        Send the screenshot to Gemini Vision and return a structured observation.
        context keys: tool, target, instruction, expected_outcome
        Returns a fallback dict on any error so the pipeline never crashes.
        """
        try:
            image = PIL.Image.open(screenshot_path)

            prompt = f"""You are a browser automation agent reviewing a screenshot taken after executing a step.

Step context:
- Tool used: {context.get('tool', '')}
- Target: {context.get('target', '')}
- Instruction: {context.get('instruction', '')}
- Expected outcome: {context.get('expected_outcome', 'Action completes successfully')}

Analyze the screenshot and respond with ONLY a valid JSON object (no markdown fences, no explanation):
{{
  "observation": "1-2 sentences describing exactly what is visible on screen right now",
  "step_succeeded_visually": true or false,
  "extracted_data": {{}},
  "issue": null
}}

Rules:
- "observation": describe the actual page content — title, main content, forms, results, errors
- "step_succeeded_visually": true if the screen matches the expected outcome; false for error pages, CAPTCHAs, login walls, wrong pages
- "extracted_data": include any useful information visible — prices, search results, article text, product names, headings
- "issue": null if everything looks correct; otherwise a short description (e.g. "CAPTCHA detected", "404 error page", "login required")"""

            response = self.vision_client.models.generate_content(
                model=self.vision_model,
                contents=[prompt, image],
            )
            text = response.text.strip()

            # Strip markdown code fences if the model wrapped the JSON
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

            return json.loads(text)

        except json.JSONDecodeError:
            raw = response.text.strip()[:400] if "response" in dir() else "Page state observed"
            return {"observation": raw, "step_succeeded_visually": None, "extracted_data": {}, "issue": None}
        except Exception as e:
            return {"observation": "", "step_succeeded_visually": None, "extracted_data": {}, "issue": f"Vision unavailable: {e}"}

    # ─────────────────────────────────────────────────────────────────────────
    # Tool dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_tool_call(self, tool_name: str, args: dict) -> str:
        """Dispatch a Groq tool call to the browser and return a text result."""
        if tool_name == "navigate":
            await self.browser.navigate(args["url"])
            return f"Navigated to {args['url']}"
        elif tool_name == "click":
            await self.browser.click(args["selector"])
            return f"Clicked: {args['selector']}"
        elif tool_name == "type_text":
            await self.browser.type_text(args["selector"], args["text"])
            return f"Typed '{args['text']}' into {args['selector']}"
        elif tool_name == "extract_text":
            return await self.browser.extract_text()
        elif tool_name == "search":
            await self.browser.search(args["query"])
            return f"Searched Google for: {args['query']}"
        elif tool_name == "scroll":
            await self.browser.scroll()
            return "Scrolled down the page"
        elif tool_name == "task_complete":
            return args.get("summary", "Task completed")
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    # ─────────────────────────────────────────────────────────────────────────
    # Main agentic loop
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_plan(self, plan: TaskPlan) -> list[StepResult]:
        """
        Run an agentic tool-calling loop driven by Groq function calling.
        The LLM picks each browser tool dynamically based on the visual
        observation returned after every action, rather than following a
        pre-written script.
        """
        results = []
        task_id = hashlib.md5(plan.goal.encode()).hexdigest()[:8]

        try:
            await self.browser.start()
        except Exception as e:
            return [
                StepResult(
                    step_number=1,
                    success=False,
                    observation="",
                    extracted_data={},
                    screenshot_path=None,
                    error=f"Browser failed to start: {e}",
                )
            ]

        # Give the LLM the goal and the planner's suggested steps as loose guidance
        plan_summary = "\n".join(
            f"{i + 1}. {step.instruction}" for i, step in enumerate(plan.steps)
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Goal: {plan.goal}\n\n"
                    f"Suggested steps (treat as guidance — adapt based on what you see):\n"
                    f"{plan_summary}\n\n"
                    f"Begin executing."
                ),
            },
        ]

        MAX_STEPS = 15

        for step_num in range(1, MAX_STEPS + 1):
            screenshot_path = f"screenshots/{task_id}_{step_num}.png"
            success = True
            error_msg = None
            observation = ""
            extracted_data = {}
            tool_name = "unknown"
            tool_args = {}

            try:
                # ── 1. Ask Groq which tool to call next ──────────────────────
                response = self.groq.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=BROWSER_TOOLS,
                    tool_choice="required",   # LLM must call a tool every turn
                    temperature=0.1,
                )

                message = response.choices[0].message

                if not message.tool_calls:
                    # Shouldn't happen with tool_choice="required", but guard it
                    break

                tool_call = message.tool_calls[0]
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                # ── 2. Handle task_complete — stop before any browser action ─
                if tool_name == "task_complete":
                    observation = tool_args.get("summary", "Task completed")
                    messages.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [{
                            "id": tool_call.id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": tool_call.function.arguments},
                        }],
                    })
                    messages.append({"role": "tool", "content": observation, "tool_call_id": tool_call.id})
                    break

                # ── 3. Execute the chosen browser action ─────────────────────
                try:
                    tool_result = await self._execute_tool_call(tool_name, tool_args)
                except Exception as e:
                    success = False
                    error_msg = str(e)
                    tool_result = f"Error: {e}"

                # ── 4. Take screenshot ────────────────────────────────────────
                try:
                    await self.browser.take_screenshot(screenshot_path)
                except Exception as e:
                    screenshot_path = None
                    if not error_msg:
                        error_msg = f"Screenshot failed: {e}"
                        success = False

                # ── 5. Vision observation — primary source of truth ───────────
                if screenshot_path and os.path.exists(screenshot_path):
                    target = (
                        tool_args.get("url")
                        or tool_args.get("selector")
                        or tool_args.get("query")
                        or ""
                    )
                    vision = await self._observe_page(
                        screenshot_path,
                        {
                            "tool": tool_name,
                            "target": target,
                            "instruction": f"{tool_name}({json.dumps(tool_args)})",
                            "expected_outcome": "Action completes and page updates",
                        },
                    )

                    if vision["observation"]:
                        observation = vision["observation"]
                    if vision.get("extracted_data"):
                        extracted_data = vision["extracted_data"]
                    # Visual failure overrides action success
                    if success and vision.get("step_succeeded_visually") is False:
                        success = False
                        error_msg = vision.get("issue") or "Visual check: step did not succeed"
                else:
                    observation = tool_result

                # ── 6. Feed observation back into the conversation ────────────
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [{
                        "id": tool_call.id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": tool_call.function.arguments},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "content": observation or tool_result,
                    "tool_call_id": tool_call.id,
                })

            except Exception as e:
                success = False
                error_msg = str(e)
                observation = f"Unexpected error at step {step_num}: {e}"
                screenshot_path = None

            results.append(
                StepResult(
                    step_number=step_num,
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
