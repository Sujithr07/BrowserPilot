"""
WebVoyager-style LLM-as-judge.

Scores an agent's final answer against a reference by calling
`reasoning_completion()` — so the judge rides the SAME provider fallback chain
machinery as the rest of AgentFlow. The chain it uses is independently
configurable via the JUDGE_MODELS env var, so the judge can be a different (and
ideally stronger / more neutral) model than the agent under test.

    JUDGE_MODELS="github/gpt-4o-mini,groq/llama-3.3-70b-versatile"

When JUDGE_MODELS is unset it defaults to the agent's REASONING_MODELS chain.
All API keys are read from the environment by the LiteLLM layer (backend/llm.py).
"""
from backend.llm import reasoning_completion, REASONING_MODELS, _chain

# Judge chain: own env var, falling back to the agent's reasoning chain.
JUDGE_MODELS = _chain("JUDGE_MODELS", REASONING_MODELS)

_JUDGE_SYSTEM = """You are a strict, impartial evaluator for a web-navigation agent (WebVoyager-style).
You are given a task QUESTION, a REFERENCE answer, and the agent's RESPONSE.
Decide whether the RESPONSE correctly and sufficiently answers the QUESTION.

Guidelines:
- Judge on semantic correctness, not exact wording or formatting.
- The REFERENCE may be approximate (distances, durations, ingredient lists, "about X").
  Accept any RESPONSE that is consistent with the reference.
- A RESPONSE that is empty, says it could not complete the task, hit a CAPTCHA/login,
  or contradicts the reference is a FAILURE.
- Extra correct detail is fine; partial-but-correct answers to the core question pass.

Output format (exactly two lines):
Line 1: a single word — SUCCESS or FAILURE
Line 2: one short sentence giving the reason."""


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Parse the judge's two-line reply into (success, reason)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return False, "judge returned empty response"
    verdict = lines[0].upper()
    # Be lenient about where the keyword lands, but FAILURE wins ties.
    success = "SUCCESS" in verdict and "FAIL" not in verdict
    reason = lines[1] if len(lines) > 1 else lines[0]
    return success, reason[:300]


def judge(
    question: str,
    answer_reference: str,
    final_answer: str,
    models: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Return (success, reason). Never raises — a judge/provider failure is reported
    as a FAILURE with the error as the reason, so one bad call can't abort a run.
    """
    user = (
        f"QUESTION:\n{question}\n\n"
        f"REFERENCE answer:\n{answer_reference}\n\n"
        f"AGENT RESPONSE:\n{final_answer or '(the agent produced no answer)'}\n\n"
        "Verdict:"
    )
    try:
        resp = reasoning_completion(
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            models=models or JUDGE_MODELS,
        )
        text = resp.choices[0].message.content or ""
    except Exception as e:
        return False, f"judge error: {e}"
    return _parse_verdict(text)
