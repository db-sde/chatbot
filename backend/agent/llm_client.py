from __future__ import annotations

import json
import logging
from typing import Any

import groq
from groq import AsyncGroq
from langchain_groq import ChatGroq
from settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are DegreeBaba's AI assistant. You ONLY answer questions about "
    "universities, courses, fees, eligibility, admission process, "
    "specialisations, and placement data available in DegreeBaba's catalog. "
    "For anything else, politely decline. Never generate SQL. "
    "Use the provided tools to retrieve data — do not invent facts."
)


class LLMClient:
    def __init__(self) -> None:
        self.enabled = bool(settings.groq_api_key)
        if self.enabled:
            # Used for simple generate_text / generate_json calls (entity extraction)
            self.model = AsyncGroq(api_key=settings.groq_api_key)
            # Used by the LangGraph agent for tool-calling
            self.chat_model: ChatGroq | None = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=settings.groq_api_key,
                temperature=0,
            )
        else:
            self.model = None
            self.chat_model = None

    async def generate_text(self, prompt: str) -> str:
        if not self.model:
            return ""
        try:
            response = await self.model.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
            )
            return response.choices[0].message.content or ""
        except groq.RateLimitError:
            logger.warning("Groq rate limit hit — falling back to local extraction.")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Groq generate_text failed: %s", exc)
            return ""

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        text = await self.generate_text(prompt)
        if not text:
            return {}
        stripped = (
            text.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {}


llm_client = LLMClient()
