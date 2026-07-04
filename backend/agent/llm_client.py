from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Callable

from groq import AsyncGroq
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from settings import settings

from observability import (
    mark_first_token,
    mark_llm_start,
    record_llm_call_duration,
)

logger = logging.getLogger(__name__)

# Retry configuration for LLM calls
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_MAX_DELAY = 8.0   # seconds

SYSTEM_PROMPT = (
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


class LLMClient:
    def __init__(self) -> None:
        self.groq_model = None
        self.groq_chat = None
        self.gemini_model = None
        self.gemini_chat = None
        
        # 1. Initialize Groq if key exists
        if settings.groq_api_key:
            self.groq_model = AsyncGroq(api_key=settings.groq_api_key)
            self.groq_chat = ChatGroq(
                model=settings.groq_model_name,
                api_key=settings.groq_api_key,
                temperature=0,
            )

        # 2. Initialize Gemini if key exists
        if settings.gemini_api_key:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            self.gemini_model = genai.GenerativeModel(settings.gemini_model_name)
            self.gemini_chat = ChatGoogleGenerativeAI(
                model=settings.gemini_model_name,
                google_api_key=settings.gemini_api_key,
                temperature=0,
            )

        self.enabled = bool(self.groq_model or self.gemini_model)

        # 3. Build the primary with fallbacks
        if self.groq_chat and self.gemini_chat:
            self.chat_model = self.groq_chat.with_fallbacks([self.gemini_chat])
        elif self.groq_chat:
            self.chat_model = self.groq_chat
        elif self.gemini_chat:
            self.chat_model = self.gemini_chat
        else:
            self.chat_model = None

    async def _try_groq(self, prompt: str) -> str | None:
        if not self.groq_model:
            return None
        response = await self.groq_model.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.groq_model_name,
        )
        return response.choices[0].message.content or ""

    async def _try_gemini(self, prompt: str) -> str | None:
        if not self.gemini_model:
            return None
        response = await self.gemini_model.generate_content_async(prompt)
        return response.text or ""

    async def generate_text(self, prompt: str) -> str:
        if not self.enabled:
            return ""

        mark_llm_start()
        t_start = time.perf_counter()

        providers: list[tuple[str, Callable[[str], Any]]] = [
            ("groq", self._try_groq),
            ("gemini", self._try_gemini),
        ]

        last_error: Exception | None = None
        for provider_name, provider_fn in providers:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    result = await provider_fn(prompt)
                    if result is not None:
                        mark_first_token()
                        duration_ms = int((time.perf_counter() - t_start) * 1000)
                        record_llm_call_duration(duration_ms)
                        return result
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "%s generate_text attempt %d/%d failed: %s",
                        provider_name, attempt, _MAX_RETRIES, exc
                    )
                    if attempt < _MAX_RETRIES:
                        delay = min(_BASE_DELAY * (2 ** (attempt - 1)) + random.random(), _MAX_DELAY)
                        await asyncio.sleep(delay)

        if last_error:
            logger.error("All LLM providers failed for generate_text: %s", last_error)
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        record_llm_call_duration(duration_ms)
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
