"""Public LLM client facade.

This module is kept as the single import point for the rest of the application
(agent nodes, tools, lead scoring).  Internally it delegates to the unified
`llm` layer introduced in Phase B, so no caller needs to know which provider is
actually serving a request.

The legacy attributes (`groq_model`, `gemini_model`, `groq_chat`, `gemini_chat`,
`chat_model`) are preserved as compatibility shims so existing tests and
monkeypatches continue to work.
"""
from __future__ import annotations

import logging
from typing import Any


from llm import LLMManager, ModelRegistry
from llm.types import LLMResponse, ToolSpec

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
    """Thin facade over the unified LLM layer."""

    def __init__(self) -> None:
        self._manager = LLMManager(ModelRegistry(settings.llm_tasks))
        self._enabled = self._manager.has_task("agent_decide") or self._manager.has_task("entity_resolution")

        # Legacy attributes are stored as plain instance attributes so existing
        # tests and monkeypatches continue to work.  They are derived from the
        # unified registry, not hard-coded provider logic.
        self.groq_model = self._legacy_adapter("groq")
        self.gemini_model = self._legacy_adapter("gemini")
        self.groq_chat = self._legacy_chat_model("groq")
        self.gemini_chat = self._legacy_chat_model("gemini")
        self.chat_model = self._primary_chat_model()

    def _legacy_adapter(self, provider_name: str) -> Any | None:
        """Return the named provider adapter from the registry if available."""
        for task in ("agent_decide", "synthesize", "entity_resolution", "embedding"):
            try:
                cfg, adapter = self._manager.registry.get_primary_provider(task)
                if cfg.provider == provider_name:
                    return adapter
            except Exception:
                continue
        return None

    def _legacy_chat_model(self, provider_name: str) -> Any | None:
        """Return the named provider's LangChain chat model if available."""
        adapter = self._legacy_adapter(provider_name)
        if adapter is None:
            return None
        try:
            return adapter.get_chat_model()
        except Exception:
            return None

    def _primary_chat_model(self) -> Any | None:
        """Return the primary chat model for the agent_decide task."""
        try:
            return self._manager.get_chat_model("agent_decide")
        except RuntimeError:
            return None

    # ------------------------------------------------------------------
    # Backward-compatible attributes
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Public methods used by application code
    # ------------------------------------------------------------------
    async def generate_text(self, prompt: str) -> str:
        """Generate plain text from a prompt (used by entity resolution / lead intent)."""
        try:
            response = await self._manager.generate("entity_resolution", prompt)
            if isinstance(response, LLMResponse):
                return response.content
            # Defensive: drain stream if misconfigured.
            text = ""
            async for chunk in response:
                text += chunk
            return text
        except Exception as exc:
            logger.warning("generate_text failed: %s", exc)
            return ""

    async def generate_json(self, prompt: str, *, task: str = "entity_resolution") -> dict[str, Any]:
        """Generate a JSON object from a prompt."""
        try:
            return await self._manager.generate_json(task, prompt)
        except Exception as exc:
            logger.warning("generate_json failed: %s", exc)
            return {}

    async def generate(
        self,
        task: str,
        prompt: str | list[Any],
        *,
        tools: list[ToolSpec] | None = None,
        stream: bool = False,
        json_mode: bool = False,
    ):
        """Unified generate interface for any registered task."""
        return await self._manager.generate(
            task,
            prompt,
            tools=tools,
            stream=stream,
            json_mode=json_mode,
        )

    async def stream(self, task: str, prompt: str | list[Any]):
        """Stream text chunks for any registered task."""
        return self._manager.generate(task, prompt, stream=True)


llm_client = LLMClient()


# ---------------------------------------------------------------------------
# Convenience re-exports so existing imports keep working
# ---------------------------------------------------------------------------
def mark_llm_start() -> None:
    """Re-export observability helper for callers that import it from here."""
    from observability import mark_llm_start as _mark

    _mark()


def mark_first_token() -> None:
    """Re-export observability helper for callers that import it from here."""
    from observability import mark_first_token as _mark

    _mark()


def record_llm_call_duration(duration_ms: int) -> None:
    """Re-export observability helper for callers that import it from here."""
    from observability import record_llm_call_duration as _record

    _record(duration_ms)
