"""LLM client facade — the single import point for all application code.

graph.py, resolve.py, and leads/intent.py all import from here.  Nothing
in the application code needs to know which provider is active — that lives
in llm/config.py.

Public surface (preserved from the old architecture):
  SYSTEM_PROMPT   — str
  llm_client      — LLMClient singleton
  LLMClient.enabled          — bool
  LLMClient.generate(...)    — returns LLMResponse
  LLMClient.generate_json(prompt, *, task=...) — returns dict
  LLMClient.generate_text(prompt)              — returns str
  mark_llm_start / mark_first_token / record_llm_call_duration  (re-exports)
"""
from __future__ import annotations

import logging
from typing import Any
from llm.provider import (
    LLMResponse,
    ToolSpec,
    generate,
    generate_json as _generate_json,
    to_langchain_messages,
)

from langchain_core.messages import BaseMessage

from llm import config
from settings import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are DegreeBaba's AI assistant. "
    "You help students with universities, courses, fees, eligibility, admissions, "
    "specialisations, placements, rankings, and comparisons available in DegreeBaba's catalog. "
    "You may naturally greet users, acknowledge thanks, and respond politely to conversational messages — "
    "no tools are needed for simple greetings or acknowledgements. "
    "Use the provided tools whenever factual catalog information is required. "
    "Never invent facts or generate SQL. "
    "For topics clearly outside education and DegreeBaba's scope, politely redirect "
    "the user back to university and course related questions."
)

SYSTEM_PROMPT = _SYSTEM_PROMPT


class LLMClient:
    """Thin facade that keeps the rest of the app provider-agnostic."""

    @property
    def enabled(self) -> bool:
        """True only when the active provider's API key is configured."""
        provider = config.PROVIDER.lower()
        if provider == "groq":
            return bool(settings.groq_api_key)
        if provider == "deepseek":
            return bool(settings.deepseek_api_key)
        return False

    async def generate(
        self,
        task: str,
        prompt: str | list[BaseMessage],
        *,
        tools: list[ToolSpec] | None = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Execute a non-streaming LLM call. The `task` argument is kept for
        API compatibility but is no longer used for routing."""
        messages = to_langchain_messages(prompt)
        return await generate(messages, tools=tools, json_mode=json_mode)

    async def generate_json(
        self,
        prompt: str,
        *,
        task: str = "entity_resolution",
    ) -> dict[str, Any]:
        """Generate a JSON-mode response. `task` is kept for API compatibility."""
        try:
            messages = to_langchain_messages(prompt)
            return await _generate_json(messages)
        except Exception as exc:
            logger.warning("generate_json failed: %s", exc)
            return {}


    async def generate_text(self, prompt: str) -> str:
        """Generate plain text from a prompt (used by entity resolution)."""
        try:
            messages = to_langchain_messages(prompt)
            response = await generate(messages)
            return response.content
        except Exception as exc:
            logger.warning("generate_text failed: %s", exc)
            return ""

    @property
    def chat_model(self):
        from llm.provider import get_chat_model
        return get_chat_model()


llm_client = LLMClient()


# ---------------------------------------------------------------------------
# Observability re-exports (kept so graph.py can import from here if needed)
# ---------------------------------------------------------------------------
def mark_llm_start() -> None:
    from observability import mark_llm_start as _mark
    _mark()


def mark_first_token() -> None:
    from observability import mark_first_token as _mark
    _mark()


def record_llm_call_duration(duration_ms: int) -> None:
    from observability import record_llm_call_duration as _record
    _record(duration_ms)
