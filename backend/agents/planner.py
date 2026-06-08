from backend.llm import reasoning_completion
from backend.schemas import TaskPlan, StepResult, TaskDecomposition

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
    response = reasoning_completion(
        messages=[
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": goal},
        ],
        temperature=0.2,
    )
    return _parse_plan(response.choices[0].message.content)


_DECOMPOSE_SYSTEM = """You are a web task planner that decides whether a goal can be split into INDEPENDENT subtasks runnable AT THE SAME TIME in separate browser sessions.

Split ONLY when subtasks do not depend on each other's results. Good splits:
- "Compare X on site A and site B" -> one branch per site
- "Get the weather in Paris, Tokyo and NYC" -> one branch per city
- "Summarise these 3 unrelated articles" -> one branch per article
Do NOT split a sequential flow where one step needs the previous step's result
(e.g. log in -> open account -> read balance), or a single-page lookup.

Each branch is a SELF-CONTAINED sub-goal with its own steps. Each step uses one of:
    navigate (go to URL), click (click element), type_text (type into field),
    extract (extract visible text), search (open a search results page).
Prefer navigating directly to well-known sites over searching.

Return ONLY valid JSON, no other text:
{
  "parallel": true,
  "branches": [
    {"goal": "<sub-goal>", "estimated_steps": N,
     "steps": [{"step_number": 1, "tool": "navigate", "target": "https://...",
                "instruction": "...", "expected_outcome": "..."}]}
  ]
}
If the goal is NOT splittable, set "parallel": false and return EXACTLY ONE branch
whose goal is the full original goal."""


def _parse_decomposition(json_str: str) -> TaskDecomposition:
    """Parse the decomposition JSON; on any failure return an empty decomposition
    so the caller can fall back to a normal single-plan run."""
    s = json_str.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.startswith("json"):
            s = s[4:].strip()
    try:
        dec = TaskDecomposition.model_validate_json(s)
    except Exception:
        return TaskDecomposition(parallel=False, branches=[])
    # Drop empty branches; a real parallel split needs >= 2 viable branches.
    dec.branches = [b for b in dec.branches if b.goal and b.goal.strip()]
    if len(dec.branches) < 2:
        dec.parallel = False
    return dec


async def decompose_task(goal: str) -> TaskDecomposition:
    """Ask the planner whether `goal` splits into independent parallel branches.

    Returns a TaskDecomposition. When it can't be split (or parsing fails) the
    result has parallel=False and 0-or-1 branches; the crew then runs the normal
    sequential path.
    """
    response = reasoning_completion(
        messages=[
            {"role": "system", "content": _DECOMPOSE_SYSTEM},
            {"role": "user", "content": goal},
        ],
        temperature=0.2,
    )
    return _parse_decomposition(response.choices[0].message.content)


async def replan_task(
    goal: str,
    successful_results: list[StepResult],
    failed_results: list[StepResult],
) -> TaskPlan:
    """Generate a recovery plan focused only on what failed, given what already succeeded."""
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

    response = reasoning_completion(
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
