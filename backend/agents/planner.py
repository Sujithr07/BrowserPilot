import os
from dotenv import load_dotenv
from groq import Groq
from backend.schemas import TaskPlan, StepResult

load_dotenv()

_PLAN_SYSTEM = """You are a web task planner. Given a user goal, decompose it into a sequence of browser steps. Each step must use one of these tools:
    navigate (go to URL), click (click element), type_text (type into field),
    extract (extract visible text from page), search (open a search results page for a query).
    Prefer navigating directly to well-known sites (e.g. https://en.wikipedia.org/wiki/<Topic>) over searching.
    When you must search, use the search tool — never plan to type into a search engine's box.
    Return ONLY valid JSON matching this schema, no other text:
    {
      "goal": "...",
      "estimated_steps": N,
      "steps": [
        {"step_number": 1, "tool": "navigate", "target": "https://...",
         "instruction": "...", "expected_outcome": "..."},
        ...
      ]
    }"""


def _parse_plan(json_str: str) -> TaskPlan:
    if json_str.startswith("```"):
        json_str = json_str.strip("```").strip()
        if json_str.startswith("json"):
            json_str = json_str[4:].strip()
    try:
        return TaskPlan.model_validate_json(json_str)
    except Exception as e:
        raise ValueError(f"Failed to parse plan JSON: {json_str}") from e


async def plan_task(goal: str) -> TaskPlan:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": goal},
        ],
        temperature=0.2,
    )
    return _parse_plan(response.choices[0].message.content)


async def replan_task(
    goal: str,
    successful_results: list[StepResult],
    failed_results: list[StepResult],
) -> TaskPlan:
    """Generate a recovery plan focused only on what failed, given what already succeeded."""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    success_ctx = "\n".join(
        f"  Step {r.step_number}: {r.observation}" for r in successful_results
    ) or "  (none)"

    failure_ctx = "\n".join(
        f"  Step {r.step_number} failed — {r.error or r.observation}"
        for r in failed_results
    )

    user_content = (
        f"Original goal: {goal}\n\n"
        f"Steps already completed:\n{success_ctx}\n\n"
        f"Steps that failed:\n{failure_ctx}\n\n"
        f"Generate a concise recovery plan to complete the goal from this state. "
        f"Do not repeat steps that already succeeded. "
        f"Try alternative approaches for what failed (different URLs, selectors, or strategies)."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    return _parse_plan(response.choices[0].message.content)


if __name__ == "__main__":
    import asyncio
    
    async def test():
        plan = await plan_task("Find the current price of the iPhone 16 on Amazon")
        print(plan.model_dump_json(indent=2))
    
    asyncio.run(test())
