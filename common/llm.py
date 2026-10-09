"""Optional LLM adapter (Anthropic Claude via the official `anthropic` SDK).

Disabled unless LLM_PROVIDER=anthropic. Every caller must have a deterministic
fallback: any error, refusal or missing credential raises LLMUnavailable and the
caller keeps its deterministic result. The model only ever rephrases evidence it
is given; it never receives database access or tools.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-opus-5-5"
# Models that support the server-side refusal fallback ("default" routing by refusal category).
_SERVER_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")


class LLMUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


def llm_enabled() -> bool:
    return os.environ.get("LLM_PROVIDER", "none").strip().lower() == "anthropic"


def model_name() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL


def complete(system: str, user: str, max_tokens: int = 4000, effort: str = "medium") -> LLMResult:
    if not llm_enabled():
        raise LLMUnavailable("LLM_PROVIDER is not 'anthropic'")
    try:
        import anthropic
    except ImportError as exc:  # optional dependency
        raise LLMUnavailable("anthropic SDK not installed") from exc

    model = model_name()
    client = anthropic.Anthropic(timeout=90.0, max_retries=2)  # credentials resolved from the environment
    request = dict(model=model, max_tokens=max_tokens, system=system,
                   messages=[{"role": "user", "content": user}], output_config={"effort": effort})
    try:
        if model.startswith(_SERVER_FALLBACK_MODELS):
            # Opt into Anthropic's server-side refusal fallback (routed by refusal category).
            response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
        else:
            response = client.messages.create(**request)
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("authentication failed (check ANTHROPIC_API_KEY)") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("rate limited") from exc
    except anthropic.BadRequestError as exc:
        raise LLMUnavailable(f"bad request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"API error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("connection error") from exc

    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise LLMUnavailable(f"model declined (refusal category: {category})")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMUnavailable(f"empty response (stop_reason={response.stop_reason})")
    usage = getattr(response, "usage", None)
    return LLMResult(text, response.model, response.stop_reason, getattr(usage, "input_tokens", None),
                     getattr(usage, "output_tokens", None))
