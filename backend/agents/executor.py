import os
import re
import json
import hashlib
from collections import OrderedDict

from backend.browser import BrowserManager, SHOT_EXT
from backend.llm import reasoning_completion, vision_completion
from backend.schemas import TaskPlan, StepResult
from backend import metrics
from backend.logging_config import get_logger

log = get_logger("agentflow.executor")


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

# Set-of-Marks grounding toggle. When on, each step annotates the page with
# numbered boxes and exposes click_mark/type_mark so the model picks a NUMBER
# instead of inventing a CSS selector. Default on; set SOM_ENABLED=0 to A/B test
# against the legacy selector-only behaviour.
SOM_ENABLED = os.getenv("SOM_ENABLED", "1").lower() in ("1", "true", "yes", "on")

# Tools whose outcome is already fully known from their text result, so a vision
# pass adds 3-5s of VLM latency with no new information. extract_text returns the
# page text, search/scroll just reposition. Clicks, typing, and navigation still
# get a visual check — that's where a wrong mark or a failed action shows up.
SKIP_VISION_TOOLS = {"extract_text", "search", "scroll"}

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

# Set-of-Marks tools. Appended to BROWSER_TOOLS only when SOM_ENABLED, so the
# model is offered numbered clicking exactly when the overlay/mark list exists.
# The legacy click/type_text selector tools stay available as a fallback.
SOM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click_mark",
            "description": (
                "Click an element by its Set-of-Marks number. Prefer this over "
                "click: the number is the label drawn on the element in the latest "
                "screenshot and listed under 'Interactable elements'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mark_id": {
                        "type": "integer",
                        "description": "The number label of the element to click",
                    }
                },
                "required": ["mark_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_mark",
            "description": (
                "Type text into an element by its Set-of-Marks number. Prefer this "
                "over type_text — pick the number of the input/textarea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mark_id": {
                        "type": "integer",
                        "description": "The number label of the input to type into",
                    },
                    "text": {"type": "string", "description": "The text to type"},
                },
                "required": ["mark_id", "text"],
            },
        },
    },
]

if SOM_ENABLED:
    BROWSER_TOOLS = BROWSER_TOOLS + SOM_TOOLS


def _format_marks(marks: dict) -> str:
    """Render the mark mapping as a compact numbered list for the LLM prompt.

    Includes a region tag (header/footer) and the href so the model can tell a
    main-content result/product link from navigation, category, and footer chrome.
    """
    if not marks:
        return "Interactable elements: none detected on screen."
    lines = []
    for mid, m in sorted(marks.items(), key=lambda kv: int(kv[0])):
        label = f"[{mid}] <{m['tag']}> {m['text']}".rstrip()
        region = m.get("region")
        if region and region != "main":
            label += f" (in page {region})"
        href = m.get("href")
        if href:
            label += f" -> {href}"
        lines.append(label)
    return (
        "Interactable elements (call click_mark/type_mark with the number):\n"
        + "\n".join(lines)
    )


RISKY_ACTIONS = ["delete", "purchase", "confirm", "send"]

# Groq's Llama models occasionally emit a tool call as a raw text blob instead of
# a structured tool_calls object, e.g.:
#     <function=navigate{"url": "https://..."}</function>
# The API then rejects the whole request with a 400 `tool_use_failed`, exposing
# the offending text under error['failed_generation']. We recover by parsing the
# function name + JSON args back out of that blob.
_FAILED_GEN_RE = re.compile(r"<function=([A-Za-z_]\w*)\s*(\{.*?\})\s*</?function>", re.DOTALL)


def _extract_failed_generation(err: Exception) -> str | None:
    """Pull error['failed_generation'] out of a Groq tool_use_failed exception."""
    body = getattr(err, "body", None)
    if isinstance(body, dict):
        gen = body.get("error", {}).get("failed_generation")
        if gen:
            return gen
    # Fall back to scraping the stringified error if the SDK didn't expose .body
    match = re.search(r"'failed_generation':\s*'(.*?)'\}\}", str(err), re.DOTALL)
    return match.group(1) if match else None


def _parse_failed_generation(generation: str) -> tuple[str, dict] | None:
    """Parse '<function=name{json}>' into (name, args). Returns None if unparseable."""
    match = _FAILED_GEN_RE.search(generation)
    if not match:
        return None
    name, raw_args = match.group(1), match.group(2)
    try:
        return name, json.loads(raw_args)
    except json.JSONDecodeError:
        return None

# Fixed system instruction sent with every vision call.
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
- Prefer navigating directly to well-known sites (e.g. https://en.wikipedia.org/wiki/<Topic>) instead of going through a search engine
- To find information, use the search() tool — do NOT navigate to google.com and type into its box (that search box is unreliable to automate). search() opens a clean results page.
- After search(), use extract_text() to read the results, then navigate() to the most relevant result URL
- Use extract_text() whenever you need to read content from the page (this is how you collect the requested data)
- If the goal asks for specific information or content, you MUST call extract_text() on the relevant page to capture it BEFORE calling task_complete() — loading the page is not enough
- Call task_complete() when the goal is fully achieved OR when you hit an obstacle you cannot overcome
- Do not repeat the exact same failing action more than twice — try a different approach instead"""

# Extra clause only added when Set-of-Marks is on: steer the model to the
# number-based tools instead of guessing CSS selectors.
SOM_SYSTEM_CLAUSE = """

Set-of-Marks grounding is ENABLED. After each action the screenshot is annotated
with numbered boxes over every clickable element, and the observation lists them
as "[number] <tag> text (in page region) -> href". To interact, prefer
click_mark(mark_id) and type_mark(mark_id, text) using those NUMBERS — do not
invent CSS selectors. Only fall back to click(selector)/type_text(selector) if the
element you need has no number. Mark numbers are only valid for the most recent
observation.

Choosing the right mark:
- Read each element's text and href and pick the one that matches your CURRENT
  sub-goal. Never pick a number just because it exists.
- To click a search result or product, choose a MAIN-content element. Avoid marks
  tagged "(in page header)" or "(in page footer)" — those are the navigation and
  category bars (e.g. "Mac Desktops", "Bestsellers"), sign-in, cart, and site
  chrome, not results. On shopping sites a product link's href usually contains
  the product path (e.g. "/dp/", "/p/", "/itm").
- Ignore "Sponsored"/ad listings unless the goal explicitly asks for them.
- Do NOT re-click or re-type into a field you have already filled. After typing a
  query into a search box, submit it by clicking the search/submit button or a
  matching suggestion — never click the same search box again. If search results
  are already visible, click the result/product link directly."""

if SOM_ENABLED:
    SYSTEM_PROMPT = SYSTEM_PROMPT + SOM_SYSTEM_CLAUSE


class ExecutorAgent:
    def __init__(self, browser=None):
        # Both the reasoning loop and vision now go through the provider-agnostic
        # LiteLLM layer (backend/llm.py), which handles model selection, API keys,
        # and automatic fallback across free-tier providers on quota/429 errors.
        #
        # `browser` lets a caller inject a pooled LeasedBrowser; when None we own a
        # standalone BrowserManager and manage its start/stop ourselves. A pooled
        # browser is already started and is reset/returned by the pool, so we must
        # NOT start or stop it here.
        self._owns_browser = browser is None
        self.browser = browser or BrowserManager()

    # ─────────────────────────────────────────────────────────────────────────
    # Vision observation
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_page(self, screenshot_path: str, context: dict) -> dict:
        """
        Send the screenshot to Gemini Vision and return a structured observation.
        context keys: tool, target, instruction, expected_outcome
        Returns a fallback dict on any error so the pipeline never crashes.

        Caching: a client-side LRU (identical screenshots skip the API entirely)
        sits in front of the call. The VLM call itself goes through the LiteLLM
        vision chain, which fails over to the next provider on a quota/429 error.
        """
        cached = _observation_cache.get(screenshot_path, context)
        if cached is not None:
            # A cache hit is a vision API call we avoided — record the saving.
            metrics.record_cache_hit("vision")
            return cached

        # Variable part — only the step-specific context changes per call.
        # When SoM is on, the screenshot carries numbered boxes; passing the same
        # mark list helps the VLM tie its description to those numbers.
        marks_block = context.get("marks", "")
        step_prompt = (
            f"Step context:\n"
            f"- Tool used: {context.get('tool', '')}\n"
            f"- Target: {context.get('target', '')}\n"
            f"- Instruction: {context.get('instruction', '')}\n"
            f"- Expected outcome: {context.get('expected_outcome', 'Action completes successfully')}\n"
            + (f"\nThe screenshot is annotated with numbered boxes:\n{marks_block}\n" if marks_block else "")
            + "\nAnalyze the screenshot above and respond with ONLY valid JSON, no markdown."
        )

        raw_text = ""
        try:
            raw_text = vision_completion(screenshot_path, VISION_SYSTEM, step_prompt)
            text = raw_text.strip()

            # Strip markdown code fences if the model wrapped the JSON
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

            raw = json.loads(text)

            # Normalise to the internal schema used by the rest of the pipeline.
            # VISION_SYSTEM uses {"success", "observation", "extracted_data"};
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
            observation = raw_text.strip()[:400] or "Page state observed"
            return {"observation": observation, "step_succeeded_visually": None, "extracted_data": {}, "issue": None}
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
        elif tool_name == "click_mark":
            await self.browser.click_mark(args["mark_id"])
            return f"Clicked mark [{args['mark_id']}]"
        elif tool_name == "type_mark":
            await self.browser.type_mark(args["mark_id"], args["text"])
            return f"Typed '{args['text']}' into mark [{args['mark_id']}]"
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
    # Tool selection (with tool_use_failed recovery)
    # ─────────────────────────────────────────────────────────────────────────

    def _request_tool_call(self, messages: list) -> dict | None:
        """
        Ask Groq which tool to call next.

        Groq's Llama models sometimes return a malformed tool call as plain text,
        which the API rejects with a 400 `tool_use_failed`. When that happens we
        parse the offending generation out of the error and reconstruct the call
        ourselves, so a recoverable formatting glitch doesn't fail the whole step.

        Returns a normalized dict {name, args, id, content, arguments}, or None
        when the model declined to call a tool.
        """
        try:
            response = reasoning_completion(
                messages=messages,
                tools=BROWSER_TOOLS,
                tool_choice="required",   # LLM must call a tool every turn
                temperature=0.1,
            )
        except Exception as e:
            generation = _extract_failed_generation(e)
            parsed = _parse_failed_generation(generation) if generation else None
            if not parsed:
                raise
            name, args = parsed
            return {
                "name": name,
                "args": args,
                "id": f"recovered_{hashlib.md5(generation.encode()).hexdigest()[:8]}",
                "content": None,
                "arguments": json.dumps(args),
            }

        message = response.choices[0].message
        if not message.tool_calls:
            return None

        tool_call = message.tool_calls[0]
        # A no-argument tool (extract_text, scroll, …) may come back as `null`
        # or empty; normalise anything that isn't an object to {} so callers can
        # always `.get(...)` safely.
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return {
            "name": tool_call.function.name,
            "args": args,
            "id": tool_call.id,
            "content": message.content,
            "arguments": json.dumps(args),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Main agentic loop
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_plan(
        self,
        plan: TaskPlan,
        approval_callback=None,
        step_offset: int = 0,
    ) -> list[StepResult]:
        """
        Run an agentic tool-calling loop driven by Groq function calling.
        step_offset shifts step numbers so re-plan steps continue from where the
        original execution left off (e.g. offset=5 means steps start at 6).
        """
        results = []
        task_id = hashlib.md5(plan.goal.encode()).hexdigest()[:8]

        # Only start a browser we own; a pooled/injected browser is already running.
        if self._owns_browser:
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

        # Step cap. Defaults to 15; the eval harness lowers/raises it via env so a
        # task can't loop forever. Read per-call so a runner can set it at startup.
        MAX_STEPS = int(os.getenv("EXECUTOR_MAX_STEPS", "15"))
        # Trim message history to avoid exceeding Groq's token limit on long tasks.
        # Keep system message + user goal, then only recent steps to fit budget.
        # After every step, trim to last ~6-8 exchanges if we approach the limit.
        HISTORY_WINDOW = 8

        for step_num in range(1, MAX_STEPS + 1):
            actual_step = step_num + step_offset
            screenshot_path = f"screenshots/{task_id}_{actual_step}.{SHOT_EXT}"
            success = True
            error_msg = None
            observation = ""
            extracted_data = {}
            tool_name = "unknown"
            tool_args = {}

            try:
                # ── 1. Ask Groq which tool to call next ──────────────────────
                call = self._request_tool_call(messages)

                if call is None:
                    # Shouldn't happen with tool_choice="required", but guard it
                    break

                tool_name = call["name"]
                tool_args = call["args"]

                # Assistant turn that records the chosen tool call — reused below
                # when feeding the observation back into the conversation.
                assistant_msg = {
                    "role": "assistant",
                    "content": call["content"],
                    "tool_calls": [{
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": tool_name, "arguments": call["arguments"]},
                    }],
                }

                # ── 2. Handle task_complete — stop before any browser action ─
                if tool_name == "task_complete":
                    observation = tool_args.get("summary", "Task completed")
                    messages.append(assistant_msg)
                    messages.append({"role": "tool", "content": observation, "tool_call_id": call["id"]})
                    break

                # ── 3. Risky action gate — pause and wait for human approval ─
                instruction_str = f"{tool_name}({json.dumps(tool_args)})"
                if approval_callback and any(word in instruction_str.lower() for word in RISKY_ACTIONS):
                    approved = await approval_callback({
                        "step_number": actual_step,
                        "tool": tool_name,
                        "args": tool_args,
                        "instruction": instruction_str,
                    })
                    if not approved:
                        results.append(StepResult(
                            step_number=actual_step,
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

                # extract_text returns the page's actual text content — capture it
                # as extracted data so it reaches the verifier/final report. Vision
                # data (below) is merged on top rather than replacing it.
                if tool_name == "extract_text" and success:
                    extracted_data = {"page_text": tool_result[:4000]}

                # ── 5. Take screenshot (annotated with SoM marks if enabled) ──
                # annotate() draws numbered boxes, screenshots, then strips them,
                # returning {mark_id: {...}} for the next turn's click_mark/type_mark.
                marks = {}
                try:
                    if SOM_ENABLED:
                        marks = await self.browser.annotate(screenshot_path)
                    else:
                        await self.browser.take_screenshot(screenshot_path)
                except Exception as e:
                    # The browser action already ran above; losing the post-action
                    # screenshot only costs us the vision observation. Degrade
                    # gracefully (observation falls back to the tool result) instead
                    # of flipping a successful action to failed. Only surface the
                    # screenshot error when the action itself hadn't already failed.
                    screenshot_path = None
                    log.warning("annotate/screenshot failed at step %s: %s", actual_step, e)

                # ── 6. Vision observation — primary source of truth ───────────
                # Skip the VLM for tools whose result is already textual (saves a
                # 3-5s round-trip). We still annotate above so the next step has a
                # fresh mark list; we just don't pay for a visual check here.
                if (
                    screenshot_path
                    and os.path.exists(screenshot_path)
                    and tool_name not in SKIP_VISION_TOOLS
                ):
                    target = (
                        tool_args.get("url")
                        or tool_args.get("selector")
                        or tool_args.get("query")
                        or (f"mark {tool_args['mark_id']}" if "mark_id" in tool_args else "")
                    )
                    vision = await self._observe_page(
                        screenshot_path,
                        {
                            "tool": tool_name,
                            "target": target,
                            "instruction": f"{tool_name}({json.dumps(tool_args)})",
                            "expected_outcome": "Action completes and page updates",
                            # Included so the cache key changes with the mark set and
                            # the VLM is told which numbers are on screen.
                            "marks": _format_marks(marks) if SOM_ENABLED else "",
                        },
                    )

                    if vision["observation"]:
                        observation = vision["observation"]
                    if vision.get("extracted_data"):
                        # Merge so an extract_text() payload isn't clobbered by vision
                        extracted_data = {**extracted_data, **vision["extracted_data"]}
                    # Visual failure overrides action success
                    if success and vision.get("step_succeeded_visually") is False:
                        success = False
                        error_msg = vision.get("issue") or "Visual check: step did not succeed"
                else:
                    observation = tool_result

                # ── 7. Feed observation back into the conversation ────────────
                # Append the SoM mark list so the NEXT reasoning_completion call
                # sees which numbers are available and can pick one.
                tool_content = observation or tool_result
                if SOM_ENABLED and marks:
                    tool_content = f"{tool_content}\n\n{_format_marks(marks)}"
                messages.append(assistant_msg)
                messages.append({
                    "role": "tool",
                    "content": tool_content,
                    "tool_call_id": call["id"],
                })

                # Trim message history to avoid Groq token limit on long tasks.
                # Keep system + user goal, then only recent steps (HISTORY_WINDOW exchanges).
                if len(messages) > 2 + HISTORY_WINDOW * 2:
                    # messages[0] = system, messages[1] = user goal, rest = exchanges
                    messages = messages[:2] + messages[-(HISTORY_WINDOW * 2):]

            except Exception as e:
                success = False
                error_msg = str(e)
                observation = f"Unexpected error at step {actual_step}: {e}"
                screenshot_path = None

            results.append(
                StepResult(
                    step_number=actual_step,
                    success=success,
                    observation=observation,
                    extracted_data=extracted_data,
                    screenshot_path=screenshot_path,
                    error=error_msg,
                )
            )

        # Only tear down a browser we own; the pool resets and reuses its own.
        if self._owns_browser:
            try:
                await self.browser.stop()
            except Exception:
                pass

        return results
