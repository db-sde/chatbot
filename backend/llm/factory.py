"""Factory that instantiates provider adapters from settings."""
from __future__ import annotations

from typing import Any

from settings import settings

from llm.adapters.anthropic import AnthropicAdapter
from llm.adapters.deepseek import DeepSeekAdapter
from llm.adapters.gemini import GeminiAdapter
from llm.adapters.groq import GroqAdapter
from llm.adapters.kimi import KimiAdapter
from llm.adapters.openai import OpenAIAdapter
from llm.adapters.openrouter import OpenRouterAdapter
from llm.types import LLMProvider


def create_adapter(provider: str, model: str, **extra: Any) -> LLMProvider | None:
    """Create a provider adapter by name if the corresponding API key is set."""
    provider = provider.lower()

    if provider == "groq":
        if not settings.groq_api_key:
            return None
        return GroqAdapter(api_key=settings.groq_api_key, model=model, **extra)

    if provider == "gemini":
        if not settings.gemini_api_key:
            return None
        return GeminiAdapter(
            api_key=settings.gemini_api_key,
            model=model,
            embedding_model=settings.gemini_embedding_model,
            **extra,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            return None
        return OpenAIAdapter(
            api_key=settings.openai_api_key,
            model=model,
            base_url=settings.openai_base_url,
            **extra,
        )

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            return None
        return OpenRouterAdapter(
            api_key=settings.openrouter_api_key,
            model=model,
            base_url=settings.openrouter_base_url,
            **extra,
        )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            return None
        return AnthropicAdapter(api_key=settings.anthropic_api_key, model=model, **extra)

    if provider == "deepseek":
        if not settings.deepseek_api_key:
            return None
        return DeepSeekAdapter(
            api_key=settings.deepseek_api_key,
            model=model,
            base_url=settings.deepseek_base_url,
            **extra,
        )

    if provider == "kimi":
        if not settings.kimi_api_key:
            return None
        return KimiAdapter(
            api_key=settings.kimi_api_key,
            model=model,
            base_url=settings.kimi_base_url,
            **extra,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
