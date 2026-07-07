"""GPT-5.1 client wrapper.

Centralizes every call to OpenAI so the rest of the app never touches the SDK directly.
Provides JSON-mode calls with retries, consistent error handling, and lightweight logging.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI

from ai_accountant.config import OPENAI_MODEL, get_api_key

logger = logging.getLogger(__name__)

# Robust default system prompt applied to EVERY call unless explicitly overridden.
# This is the project's guardrail against fabrication and free-form output.
DEFAULT_SYSTEM = (
    "You are the reasoning layer inside an AI Accountant that produces auditable financial "
    "statements. You MUST obey these rules on every response:\n"
    "1. Use ONLY the data given in the user message. Never invent, guess, or recall figures, "
    "account names, securities, classifications, or values that are not explicitly present.\n"
    "2. You receive lightweight PROFILES (column headers and a few sample rows), never full "
    "datasets. Do not assume anything about rows you were not shown.\n"
    "3. NEVER compute, sum, or transform monetary amounts — your job is classification, "
    "routing, and column mapping only. The application does all arithmetic deterministically.\n"
    "4. If the information is insufficient, return null / \"unknown\" for that field rather than "
    "fabricating a plausible answer. Prefer being conservatively unsure over confidently wrong.\n"
    "5. Output EXACTLY one valid JSON object matching the requested schema — no prose, no "
    "markdown fences, no commentary before or after.\n"
    "6. Be deterministic: given the same input, return the same output."
)


class LLMError(RuntimeError):
    """Raised when the LLM call fails after retries or returns unusable output."""


class LLMClient:
    """Thin wrapper around the OpenAI client for this app's needs.

    The whole app depends on this one class, so swapping models or the underlying API
    (e.g. chat.completions -> responses) is a single-file change.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        key = "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"
        if not key:
            raise LLMError("No OpenAI API key provided (set OPENAI_API_KEY or pass one in).")
        self._client = OpenAI(api_key=key)
        self.model = model or OPENAI_MODEL

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Call the model and parse a JSON object from the response.

        A robust system prompt (DEFAULT_SYSTEM) is always applied unless `system` overrides it.
        Uses JSON response mode. Retries transient failures and JSON parse errors with simple
        backoff. Raises LLMError if it cannot return a dict.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system or DEFAULT_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                return json.loads(content)
            except json.JSONDecodeError as exc:
                last_err = exc
                logger.warning("LLM returned non-JSON (attempt %s/%s)", attempt, max_retries)
            except Exception as exc:  # noqa: BLE001 - surface as LLMError below
                last_err = exc
                logger.warning("LLM call failed (attempt %s/%s): %s", attempt, max_retries, exc)
            time.sleep(min(2 ** attempt, 8))

        raise LLMError(f"LLM call failed after {max_retries} attempts: {last_err}")
