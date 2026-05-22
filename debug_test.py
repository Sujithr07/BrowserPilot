import asyncio
import os
from dotenv import load_dotenv
load_dotenv()


async def debug():
    print("=== API Keys ===")
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    print(f"Groq:   {'✓ Found' if groq_key else '✗ MISSING'}")
    print(f"Gemini: {'✓ Found' if gemini_key else '✗ MISSING'}")

    print("\n=== Schemas ===")
    from backend.schemas import TaskPlan, TaskStep, TaskTool
    step = TaskStep(
        step_number=1, tool=TaskTool.navigate,
        target="https://example.com",
        instruction="test", expected_outcome="test",
    )
    print("✓ Schemas import OK")

    print("\n=== Playwright Browser ===")
    from backend.browser import BrowserManager
    bm = BrowserManager()
    try:
        await bm.start()
        await bm.navigate("https://example.com")
        os.makedirs("screenshots", exist_ok=True)
        path = await bm.take_screenshot("screenshots/debug_test.png")
        text = await bm.extract_text()
        await bm.stop()
        print(f"✓ Browser OK — extracted {len(text)} chars, screenshot at {path}")
    except Exception as e:
        print(f"✗ Browser FAILED: {type(e).__name__}: {e}")

    print("\n=== Groq Planner ===")
    if groq_key:
        from backend.agents.planner import plan_task
        try:
            plan = await plan_task("Go to example.com and describe it")
            print(f"✓ Planner OK — created {len(plan.steps)} steps")
        except Exception as e:
            print(f"✗ Planner FAILED: {type(e).__name__}: {e}")
    else:
        print("✗ Skipped (no Groq key)")

    print("\n=== Groq Tool Calling ===")
    if groq_key:
        from groq import Groq
        from backend.agents.executor import BROWSER_TOOLS
        try:
            client = Groq(api_key=groq_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a browser agent. Use the tools provided."},
                    {"role": "user", "content": "Navigate to https://example.com"},
                ],
                tools=BROWSER_TOOLS,
                tool_choice="required",
                temperature=0.1,
            )
            tc = response.choices[0].message.tool_calls
            if tc:
                print(f"✓ Tool calling OK — LLM called: {tc[0].function.name}({tc[0].function.arguments})")
            else:
                print("✗ Tool calling: no tool_calls in response")
        except Exception as e:
            print(f"✗ Tool calling FAILED: {type(e).__name__}: {e}")
    else:
        print("✗ Skipped (no Groq key)")

    print("\n=== Gemini Vision (google-genai SDK) ===")
    if gemini_key and os.path.exists("screenshots/debug_test.png"):
        try:
            from google import genai
            import PIL.Image
            client = genai.Client(api_key=gemini_key)
            image = PIL.Image.open("screenshots/debug_test.png")
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=["What do you see in this screenshot? Reply in one sentence.", image],
            )
            print(f"✓ Gemini Vision OK — {response.text.strip()[:120]}")
        except Exception as e:
            print(f"✗ Gemini Vision FAILED: {type(e).__name__}: {e}")
    else:
        print("✗ Skipped (no key or no screenshot — run browser test first)")

    print("\n=== Done ===")


asyncio.run(debug())
