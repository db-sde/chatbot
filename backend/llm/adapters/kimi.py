"""Kimi (Moonshot) adapter — OpenAI-compatible with a custom base URL."""
from __future__ import annotations

from llm.adapters.openai import OpenAIAdapter


class KimiAdapter(OpenAIAdapter):
    """Kimi / Moonshot adapter; set KIMI_API_KEY and KIMI_MODEL."""

    name = "kimi"

    def __init__(self, api_key: str, model: str, **extra) -> None:
        base_url = extra.pop("base_url", "https://api.moonshot.cn/v1")
        super().__init__(api_key=api_key, model=model, base_url=base_url, **extra)
