import os
import json
import hashlib
from collections import OrderedDict
import PIL.Image
from google import genai
from groq import Groq

from backend.browser import BrowserManager
from backend.schemas import TaskPlan, StepResult


# ─────────────────────────────────────────────────────────────────────────────
# LRU cache for Gemini Vision observations.
# Keyed by sha256(screenshot bytes) + sha256(context JSON) so identical page
# states never trigger a redundant API call, even across separate task runs.
# ─────────────────────────────────────────────────────────────────────────────
class _ObservationCache:
    def __init__(self, maxsize: int = 64):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._maxsize = maxsize
        self.hits = 0
        self.misses = 0

    def _key(self, screenshot_path: str, context: dict) -> str | None:
        try:
            with open(screenshot_path, "rb") as f:
                img_hash = hashlib.sha256(f.read()).hexdigest()
            ctx_hash = hashlib.sha256(
                json.dumps(context, sort_keys=True).encode()
            ).hexdigest()
            return f"{img_hash}:{ctx_hash}"
        except Exception:
            return None

    def get(self, screenshot_path: str, context: dict) -> dict | None:
        key = self._key(screenshot_path, context)
        if key and key in self._store:
            self._store.move_to_end(key)
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def set(self, screenshot_path: str, context: dict, value: dict) -> None:
        key = self._key(screenshot_path, context)
        if key is None:
            return
        if key in self._store:
            self._store.move_to_end(key)
        else:
            if len(self._store) >= self._maxsize:
                self._store.popitem(last=False)
        self._store[key] = value


_observation_cache = _ObservationCache(maxsize=64)

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

RISKY_ACTIONS = ["submit", "delete", "purchase", "confirm", "send"]

# Fixed system instruction sent with every vision call.
# Registered as a CachedContent at init so Gemini can reuse it across calls
# without re-processing the tokens each time.
VISION_SYSTEM = """You are a web automation validator. Analyze this screenshot and answer:
1. Did the step succeed? (true/false)
2. What do you see on the page? (description)
3. Extract any requested data? (as JSON)
Reply ONLY in JSON format: {"success": bool, "observation": str, "extracted_data": {}}"""

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
        self.vision_model = "gemini-2.0-flash-001"

        # Try to register the fixed system instruction as a CachedContent so
        # Gemini reuses it across calls without re-processing its tokens.
        # Falls back to None when the API rejects the cache (e.g. minimum-token
        # requirement not met), in which case we send system_instruction inline.
        self._vision_cache_name: str | None = self._create_vision_cache()

        # Groq — drives the agentic tool-calling loop
        self.groq = Groq(api_key=groq_key)

        self.browser = BrowserManager()

    def _create_vision_cache(self) -> str | None:
        try:
            cache = self.vision_client.caches.create(
                model=self.vision_model,
                config=genai.types.CreateCachedContentConfig(
                    system_instruction=VISION_SYSTEM,
                    ttl="300s",
                ),
            )
            return cache.name
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Vision observation
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_page(self, screenshot_path: str, context: dict) -> dict:
        """
        Send the screenshot to Gemini Vision and return a structured observation.
        context keys: tool, target, instruction, expected_outcome
        Returns a fallback dict on any error so the pipeline never crashes.

        Two caching layers:
        1. Client-side LRU (identical screenshots skip the API entirely).
        2. Server-side CachedContent: VISION_SYSTEM is registered once and
           reused by name so Gemini never re-processes those tokens.
           Falls back to inline system_instruction when the cache is unavailable.
        """
        cached = _observation_cache.get(screenshot_path, context)
        if cached is not None:
            return cached

        try:
            image = PIL.Image.open(screenshot_path)

            # Variable part — only the step-specific context changes per call.
            step_prompt = (
                f"Step context:\n"
                f"- Tool used: {context.get('tool', '')}\n"
                f"- Target: {context.get('target', '')}\n"
                f"- Instruction: {context.get('instruction', '')}\n"
                f"- Expected outcome: {context.get('expected_outcome', 'Action completes successfully')}\n\n"
                f"Analyze the screenshot above and respond with ONLY valid JSON, no markdown."
            )

            # Build config: prefer the registered CachedContent, fall back to
            # passing VISION_SYSTEM inline as system_instruction.
            if self._vision_cache_name:
                config = genai.types.GenerateContentConfig(
                    cached_content=self._vision_cache_name,
                )
            else:
                config = genai.types.GenerateContentConfig(
                    system_instruction=VISION_SYSTEM,
                )

            response = self.vision_client.models.generate_content(
                model=self.vision_model,
                contents=[image, step_prompt],
                config=config,
            )
            text = response.text.strip()

            # Strip markdown code fences if the model wrapped the JSON
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

            raw = json.loads(text)

            # Normalise to the internal schema used by the rest of the pipeline.
            # The new VISION_SYSTEM uses {"success", "observation", "extracted_data"};
            # map "success" → "step_succeeded_visually" for backward compatibility.
            result = {
                "observation": raw.get("observation", ""),
                "step_succeeded_visually": raw.get("success", raw.get("step_succeeded_visually")),
                "extracted_data": raw.get("extracted_data", {}),
                "issue": raw.get("issue"),
            }
            _observation_cache.set(screenshot_path, context, result)
            return result

        except json.JSONDecodeError:
            raw_text = response.text.strip()[:400] if "response" in dir() else "Page state observed"
            return {"observation": raw_text, "step_succeeded_visually": None, "extracted_data": {}, "issue": None}
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

    async def execute_plan(self, plan: TaskPlan, approval_callback=None) -> list[StepResult]:
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

                # ── 3. Risky action gate — pause and wait for human approval ─
                instruction_str = f"{tool_name}({json.dumps(tool_args)})"
                if approval_callback and any(word in instruction_str.lower() for word in RISKY_ACTIONS):
                    approved = await approval_callback({
                        "step_number": step_num,
                        "tool": tool_name,
                        "args": tool_args,
                        "instruction": instruction_str,
                    })
                    if not approved:
                        results.append(StepResult(
                            step_number=step_num,
                            success=False,
                            observation="Action denied by user",
                            extracted_data={},
                            screenshot_path=None,
                            error="User denied execution of risky action",
                        ))
                        break

                # ── 4. Execute the chosen browser action ─────────────────────
                try:
                    tool_result = await self._execute_tool_call(tool_name, tool_args)
                except Exception as e:
                    success = False
                    error_msg = str(e)
                    tool_result = f"Error: {e}"

                # ── 5. Take screenshot ────────────────────────────────────────
                try:
                    await self.browser.take_screenshot(screenshot_path)
                except Exception as e:
                    screenshot_path = None
                    if not error_msg:
                        error_msg = f"Screenshot failed: {e}"
                        success = False

                # ── 6. Vision observation — primary source of truth ───────────
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

                # ── 7. Feed observation back into the conversation ────────────
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
