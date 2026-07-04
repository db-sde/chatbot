"""OpenRouter adapter — OpenAI-compatible with a custom base URL."""
from __future__ import annotations

from llm.adapters.openai import OpenAIAdapter


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter adapter; set OPENROUTER_API_KEY and OPENROUTER_MODEL."""

    name = "openrouter"

    def __init__(self, api_key: str, model: str, **extra) -> None:
        base_url = extra.pop("base_url", "https://openrouter.ai/api/v1")
        super().__init__(api_key=api_key, model=model, base_url=base_url, **extra)
