from __future__ import annotations

import json
import logging
from typing import Any

import groq
from groq import AsyncGroq
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
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
        self.groq_model = None
        self.groq_chat = None
        self.gemini_model = None
        self.gemini_chat = None
        
        # 1. Initialize Groq if key exists
        if settings.groq_api_key:
            self.groq_model = AsyncGroq(api_key=settings.groq_api_key)
            self.groq_chat = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=settings.groq_api_key,
                temperature=0,
            )

        # 2. Initialize Gemini if key exists
        if settings.gemini_api_key:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            self.gemini_model = genai.GenerativeModel("gemini-2.5-flash")
            self.gemini_chat = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
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

    async def generate_text(self, prompt: str) -> str:
        if not self.enabled:
            return ""

        # Try Groq first
        if self.groq_model:
            try:
                response = await self.groq_model.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="llama-3.3-70b-versatile",
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                logger.warning("Groq generate_text failed, trying Gemini fallback: %s", exc)

        # Try Gemini second
        if self.gemini_model:
            try:
                response = await self.gemini_model.generate_content_async(prompt)
                return response.text or ""
            except Exception as exc:
                logger.warning("Gemini generate_text failed: %s", exc)

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
