"""LLM provider abstraction.

Application code depends only on `LLMProvider.complete(LLMRequest) -> LLMResponse`.
Adding a provider = one class + one registry entry. Providers return structured
JSON validated against `request.json_schema` when one is given.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderNotConfigured(ProviderError):
    pass


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    system: str
    messages: list[ChatTurn]
    model: str
    max_output_tokens: int = 8000
    effort: str = "medium"
    json_schema: dict[str, Any] | None = None
    # Hints for the offline mock provider only (real providers read everything from system/messages).
    mock_context: list[str] = field(default_factory=list)
    mock_task: str = "answer"


@dataclass
class LLMResponse:
    text: str
    data: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str
    refused: bool = False
    latency_ms: int = 0


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


def _parse_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# Anthropic (Claude) — official SDK, structured output via output_config.format
# ---------------------------------------------------------------------------
# Models that accept the server-side refusal fallback ("default" routing).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=settings.AI_REQUEST_TIMEOUT_SECONDS, max_retries=2)

    def complete(self, request: LLMRequest) -> LLMResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "output_config": {"effort": request.effort},
        }
        if request.json_schema:
            kwargs["output_config"]["format"] = {"type": "json_schema", "schema": request.json_schema}
        if request.model in _FALLBACK_MODELS:
            # On a safety decline the API retries on a suitable fallback model in the same call.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        started = time.monotonic()
        try:
            response = self._client.beta.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key.") from exc
        except (anthropic.BadRequestError, anthropic.NotFoundError, anthropic.PermissionDeniedError) as exc:
            raise ProviderError(f"Anthropic request invalid: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached.", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic error {exc.status_code}.", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise ProviderError("Could not reach Anthropic.", retryable=True) from exc
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        refused = response.stop_reason == "refusal"
        return LLMResponse(
            text=text,
            data=None if refused else _parse_json(text) if request.json_schema else None,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason or "",
            refused=refused,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


# ---------------------------------------------------------------------------
# OpenAI — official SDK, Chat Completions with strict JSON schema
# ---------------------------------------------------------------------------
class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key, timeout=settings.AI_REQUEST_TIMEOUT_SECONDS, max_retries=2)

    def complete(self, request: LLMRequest) -> LLMResponse:
        import openai

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}]
            + [{"role": m.role, "content": m.content} for m in request.messages],
            "max_completion_tokens": request.max_output_tokens,
        }
        if re.match(r"^(gpt-5|gpt-6|o\d)", request.model):
            kwargs["reasoning_effort"] = request.effort
        if request.json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "resolveai_output", "strict": True, "schema": request.json_schema},
            }
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise ProviderError("OpenAI rejected the API key.") from exc
        except (openai.BadRequestError, openai.NotFoundError, openai.PermissionDeniedError) as exc:
            raise ProviderError(f"OpenAI request invalid: {exc.message}") from exc
        except openai.RateLimitError as exc:
            raise ProviderError("OpenAI rate limit reached.", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI error {exc.status_code}.", retryable=exc.status_code >= 500) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not reach OpenAI.", retryable=True) from exc
        choice = response.choices[0]
        refused = bool(getattr(choice.message, "refusal", None))
        text = choice.message.content or ""
        return LLMResponse(
            text=text,
            data=None if refused else _parse_json(text) if request.json_schema else None,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            model=response.model,
            stop_reason=choice.finish_reason or "",
            refused=refused,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


# ---------------------------------------------------------------------------
# Mock — offline and deterministic (development, tests, demos)
# ---------------------------------------------------------------------------
class MockProvider:
    """Answers from the best retrieved passage; hands off when nothing relevant is found."""

    name = "mock"

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if request.mock_task == "summary":
            data: dict[str, Any] = {
                "summary": f"Customer asked: {last_user[:160]}. {len(request.messages)} message(s) so far."
            }
        elif request.mock_context:
            passage = request.mock_context[0].replace("\n", " ")
            sentences = re.split(r"(?<=[.!?])\s+", passage)
            answer = " ".join(sentences[:2]).strip()
            if answer.startswith("Q:") and " A: " in answer:
                answer = answer.split(" A: ", 1)[1]
            data = {
                "answer": answer[:600],
                "confidence": 0.82,
                "needs_human": False,
                "reason": "",
                "tool_name": "",
                "tool_arguments_json": "{}",
            }
        else:
            data = {
                "answer": "I'm not sure about that, so let me get a teammate to help.",
                "confidence": 0.2,
                "needs_human": True,
                "reason": "no relevant knowledge",
                "tool_name": "",
                "tool_arguments_json": "{}",
            }
        text = json.dumps(data)
        prompt_chars = len(request.system) + sum(len(m.content) for m in request.messages)
        return LLMResponse(
            text=text,
            data=data,
            input_tokens=max(1, prompt_chars // 4),
            output_tokens=max(1, len(text) // 4),
            model=request.model or "mock-1",
            stop_reason="end_turn",
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def get_provider(name: str) -> LLMProvider:
    """Resolve a provider. Without an API key, dev/test fall back to the mock provider
    (AI_ALLOW_MOCK_FALLBACK); production raises ProviderNotConfigured instead."""
    if name == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicProvider(settings.ANTHROPIC_API_KEY)
    if name == "openai" and settings.OPENAI_API_KEY:
        return OpenAIProvider(settings.OPENAI_API_KEY)
    if name == "mock" or settings.AI_ALLOW_MOCK_FALLBACK:
        return MockProvider()
    raise ProviderNotConfigured(f"{name} is not configured (set {name.upper()}_API_KEY).")


def provider_status() -> dict[str, dict[str, Any]]:
    return {
        "anthropic": {"configured": bool(settings.ANTHROPIC_API_KEY)},
        "openai": {"configured": bool(settings.OPENAI_API_KEY)},
        "mock": {"configured": True},
        "mock_fallback_enabled": {"configured": settings.AI_ALLOW_MOCK_FALLBACK},
    }
