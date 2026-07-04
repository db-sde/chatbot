"""DeepSeek adapter — OpenAI-compatible with a custom base URL."""
from __future__ import annotations

from llm.adapters.openai import OpenAIAdapter


class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek adapter; set DEEPSEEK_API_KEY and DEEPSEEK_MODEL."""

    name = "deepseek"

    def __init__(self, api_key: str, model: str, **extra) -> None:
        base_url = extra.pop("base_url", "https://api.deepseek.com")
        super().__init__(api_key=api_key, model=model, base_url=base_url, **extra)
