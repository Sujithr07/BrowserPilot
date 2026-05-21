import os
from dotenv import load_dotenv
from groq import Groq
from backend.schemas import TaskPlan, TaskStep, TaskTool

load_dotenv()


async def plan_task(goal: str) -> TaskPlan:
    """
    Decompose a user's natural language goal into a structured TaskPlan using Groq API.
    
    Args:
        goal: The user's goal in plain English
        
    Returns:
        TaskPlan with decomposed steps
        
    Raises:
        ValueError: If JSON parsing fails
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    system_prompt = """You are a web task planner. Given a user goal, decompose it into a sequence of browser steps. Each step must use one of these tools:
    navigate (go to URL), click (click element), type_text (type into field),
    extract (extract visible text from page), search (search on google).
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
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal}
        ],
        temperature=0.2
    )
    
    json_str = response.choices[0].message.content
    
    # Strip markdown code blocks if present
    if json_str.startswith("```"):
        json_str = json_str.strip("```").strip()
        if json_str.startswith("json"):
            json_str = json_str[4:].strip()
    
    try:
        task_plan = TaskPlan.model_validate_json(json_str)
    except Exception as e:
        raise ValueError(f"Failed to parse JSON response: {json_str}") from e
    
    return task_plan


if __name__ == "__main__":
    import asyncio
    
    async def test():
        plan = await plan_task("Find the current price of the iPhone 16 on Amazon")
        print(plan.model_dump_json(indent=2))
    
    asyncio.run(test())
