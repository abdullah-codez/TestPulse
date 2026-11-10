"""
TestPulse — Resilient LLM Router
Wraps litellm.completion with tiered model failover, rate-limit & quota handling,
and structured Pydantic parsing with code-fence cleanup.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from pydantic import BaseModel

from testpulse.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def clean_json_code_fences(text: str) -> str:
    """
    Strips markdown code fences (```json ... ``` or ``` ... ```) or extracts
    the outermost valid JSON object/array substring.
    """
    raw = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: extract substring between first '{' and last '}'
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return raw[first_brace : last_brace + 1].strip()

    return raw


def parse_structured_output(content: str, schema: type[T]) -> T:
    """
    Parses LLM response content into the specified Pydantic schema,
    cleaning markdown code fences and handling json formatting anomalies.
    """
    cleaned = clean_json_code_fences(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"Failed to parse JSON from LLM response: {err}\nResponse content:\n{content}"
        ) from err
    return schema.model_validate(data)


def _normalize_model_name(model: str) -> str:
    """Ensures model has an explicit provider prefix when using OpenRouter."""
    m = model.strip()
    if "/" in m and not m.startswith(
        ("openrouter/", "openai/", "anthropic/", "ollama/", "azure/", "gemini/", "vertex_ai/")
    ):
        return f"openrouter/{m}"
    return m


def _is_failover_error(exc: Exception) -> bool:
    """True if exception represents rate-limit (429), service unavailable (503), or timeout."""
    if isinstance(exc, (RateLimitError, ServiceUnavailableError, Timeout, TimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code in (429, 503):
        return True
    err_str = str(exc).lower()
    return "429" in err_str or "rate limit" in err_str or "503" in err_str or "timeout" in err_str


class LLMRouter:
    """
    Resilient LLM gateway with tiered failover and structured output parsing.

    Sequentially attempts models in the tier. If a 429, 503, or timeout occurs,
    waits `wait_seconds` (default 2s) and automatically fails over to the next model.
    """

    def __init__(
        self,
        tier1_models: list[str] | None = None,
        tier2_models: list[str] | None = None,
        wait_seconds: float = 2.0,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.tier1_models = tier1_models or settings.tier1_models
        self.tier2_models = tier2_models or settings.tier2_models
        self.wait_seconds = wait_seconds
        self.api_key = api_key or settings.openrouter_api_key or None
        self.timeout = timeout or settings.llm_timeout_seconds

    def complete(
        self,
        messages: list[dict[str, str]],
        models: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Executes a completion request across the candidate model list sequentially.
        Fails over to the next model on HTTP 429, 503, or timeout.
        """
        candidate_models = models or self.tier1_models
        if not candidate_models:
            raise ValueError("No LLM models configured in candidate list.")

        last_error: Exception | None = None

        for idx, raw_model in enumerate(candidate_models):
            model = _normalize_model_name(raw_model)
            try:
                call_kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "timeout": self.timeout,
                    **kwargs,
                }
                if self.api_key:
                    call_kwargs["api_key"] = self.api_key
                if response_format:
                    call_kwargs["response_format"] = response_format

                response = litellm.completion(**call_kwargs)
                return response

            except (RateLimitError, ServiceUnavailableError, Timeout, APIConnectionError, APIError, Exception) as exc:
                last_error = exc
                if _is_failover_error(exc) and idx < len(candidate_models) - 1:
                    logger.warning(
                        "Model '%s' failed with %s (%s). Failing over in %.1fs to '%s'...",
                        model,
                        type(exc).__name__,
                        exc,
                        self.wait_seconds,
                        candidate_models[idx + 1],
                    )
                    if self.wait_seconds > 0:
                        time.sleep(self.wait_seconds)
                    continue

                if not _is_failover_error(exc):
                    # Non-recoverable error (e.g. invalid request structure)
                    raise

        raise RuntimeError(
            f"All LLM models in tier failed: {candidate_models}. Last error: {last_error}"
        ) from last_error

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        models: list[str] | None = None,
        **kwargs: Any,
    ) -> T:
        """
        Requests completion and parses the response into the specified Pydantic schema.
        Cleans markdown code fences and returns a validated schema instance.
        """
        # Pass json_object response format when supported
        response_format = {"type": "json_object"}
        response = self.complete(
            messages=messages,
            models=models,
            response_format=response_format,
            **kwargs,
        )

        content: str = ""
        try:
            choices = getattr(response, "choices", [])
            if choices:
                content = getattr(choices[0].message, "content", "") or ""
            elif isinstance(response, dict) and "choices" in response:
                content = response["choices"][0]["message"]["content"]
        except (IndexError, KeyError, AttributeError) as err:
            raise ValueError(f"Unexpected response format from LLM completion: {response}") from err

        return parse_structured_output(content, schema)
