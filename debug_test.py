import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

async def debug():
    print("=== API Keys ===")
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    print(f"Groq: {'✓ Found' if groq_key else '✗ MISSING'}")
    print(f"Gemini: {'✓ Found' if gemini_key else '✗ MISSING'}")

    print("\n=== Schemas ===")
    from backend.schemas import TaskPlan, TaskStep, TaskTool
    step = TaskStep(step_number=1, tool=TaskTool.navigate,
                    target="https://example.com",
                    instruction="test", expected_outcome="test")
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

    print("\n=== Gemini Vision ===")
    if gemini_key and os.path.exists("screenshots/debug_test.png"):
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            with open("screenshots/debug_test.png", "rb") as f:
                img_data = f.read()
            import base64
            base64_image = base64.b64encode(img_data).decode("utf-8")
            response = model.generate_content([
                "What do you see in this screenshot? Reply in one sentence.",
                {"mime_type": "image/png", "data": base64_image}
            ])
            print(f"✓ Gemini OK — {response.text[:100]}")
        except Exception as e:
            print(f"✗ Gemini FAILED: {type(e).__name__}: {e}")
    else:
        print("✗ Skipped (no key or no screenshot)")

    print("\n=== Done ===")

asyncio.run(debug())
