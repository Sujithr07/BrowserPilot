"""
Provider-agnostic LLM layer built on LiteLLM.

Every model call in AgentFlow goes through here instead of talking to a single
vendor SDK. Two ordered fallback chains are defined — one for the reasoning /
tool-calling loop, one for vision — so when a provider returns a rate-limit
(429) or any error, LiteLLM transparently fails over to the next model in the
chain. This is what keeps the app running once a free-tier quota is exhausted.

Model names use LiteLLM's "provider/model" convention, e.g.
    groq/llama-3.3-70b-versatile
    github/gpt-4o-mini
    openrouter/deepseek/deepseek-chat
    gemini/gemini-2.5-flash
LiteLLM reads each provider's key from the matching env var automatically
(GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, GITHUB_API_KEY,
CEREBRAS_API_KEY, ...). See .env.example.

Both chains are overridable at runtime with a comma-separated env var:
    REASONING_MODELS="groq/llama-3.3-70b-versatile,github/gpt-4o-mini"
    VISION_MODELS="gemini/gemini-2.5-flash,github/gpt-4o-mini"
"""
import os
import time
import base64
import logging

import litellm
from dotenv import load_dotenv

from backend import metrics

load_dotenv()

logger = logging.getLogger("agentflow.llm")

# Drop params a given provider doesn't support (e.g. tool_choice="required" on
# models that lack it) instead of erroring. Keep LiteLLM's own logging quiet.
litellm.drop_params = True
litellm.suppress_debug_info = True


def _chain(env_var: str, default: list[str]) -> list[str]:
    """Read a comma-separated model chain from env, else use the default."""
    raw = os.getenv(env_var)
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return default


# Reasoning / tool-calling chain. Primary first, fallbacks after.
# NOTE: every model used for the executor's tool-calling loop must support
# function calling — Groq Llama-3.3, GPT-4o-mini, and DeepSeek all do.
REASONING_MODELS = _chain(
    "REASONING_MODELS",
    [
        "groq/llama-3.3-70b-versatile",
        "github/gpt-4o-mini",
        "cerebras/gpt-oss-120b",
    ],
)

# Vision chain. All entries must be multimodal (accept image input).
VISION_MODELS = _chain(
    "VISION_MODELS",
    [
        "gemini/gemini-2.5-flash",
        "openrouter/qwen/qwen-2.5-vl-72b-instruct",
        "github/gpt-4o-mini",
    ],
)


def _split(models: list[str]) -> tuple[str, list[str]]:
    """Return (primary, fallbacks) from a chain, tolerating a single-entry chain."""
    if not models:
        raise ValueError("Model chain is empty — set REASONING_MODELS / VISION_MODELS")
    return models[0], models[1:]


def reasoning_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.2,
    models: list[str] | None = None,
):
    """
    Text / tool-calling completion with automatic provider fallback.

    Returns the raw LiteLLM response (OpenAI-shaped): use
    response.choices[0].message.content / .tool_calls just like the OpenAI SDK.

    `models` overrides the chain for this one call (primary + fallbacks) without
    touching the global REASONING_MODELS — e.g. the eval judge runs on its own
    JUDGE_MODELS chain. Defaults to REASONING_MODELS when omitted.
    """
    primary, fallbacks = _split(models or REASONING_MODELS)
    kwargs: dict = {
        "model": primary,
        "messages": messages,
        "temperature": temperature,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if fallbacks:
        kwargs["fallbacks"] = fallbacks

    # Time around the call; record usage/cost/provider AFTER it returns. This is
    # purely observational — it does not touch kwargs, tools, or the fallback set.
    _t0 = time.perf_counter()
    try:
        response = litellm.completion(**kwargs)
    except Exception:
        metrics.record_error("reasoning")
        raise
    metrics.record_call("reasoning", response, time.perf_counter() - _t0)
    logger.debug("reasoning served by %s", getattr(response, "model", "?"))
    return response


def vision_completion(
    image_path: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> str:
    """
    Multimodal completion: send a local screenshot + prompt to a VLM with
    automatic provider fallback. Returns the model's text content.

    The image is inlined as a base64 data URL, which LiteLLM normalises to each
    provider's native image format.
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    # Match the data-URL MIME to the actual file so providers that trust the
    # declared type don't mis-decode (screenshots are JPEG by default now).
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ],
        },
    ]

    primary, fallbacks = _split(VISION_MODELS)
    kwargs: dict = {
        "model": primary,
        "messages": messages,
        "temperature": temperature,
    }
    if fallbacks:
        kwargs["fallbacks"] = fallbacks

    _t0 = time.perf_counter()
    try:
        response = litellm.completion(**kwargs)
    except Exception:
        metrics.record_error("vision")
        raise
    metrics.record_call("vision", response, time.perf_counter() - _t0)
    logger.debug("vision served by %s", getattr(response, "model", "?"))
    return response.choices[0].message.content or ""
