"""Anthropic adapter for the unified LLM layer."""
from __future__ import annotations

from typing import Any, AsyncIterator

from langchain_core.messages import BaseMessage
from langchain_anthropic import ChatAnthropic

from llm.adapters.base import (
    append_json_system_message,
    clean_messages,
    langchain_to_llm_response,
    tool_specs_to_openai_schema,
)
from llm.types import LLMProvider, LLMResponse, ProviderCapability, ToolSpec


class AnthropicAdapter(LLMProvider):
    """Anthropic adapter via langchain-anthropic."""

    name = "anthropic"
    capabilities = ProviderCapability.TEXT | ProviderCapability.JSON | ProviderCapability.TOOLS | ProviderCapability.STREAM

    def __init__(self, api_key: str, model: str, **extra: Any) -> None:
        self.api_key = api_key
        self.model = model
        self.extra = extra
        self._chat_model: ChatAnthropic | None = None

    def _get_chat_model(self, temperature: float = 0.0, max_tokens: int | None = None) -> ChatAnthropic:
        # Anthropic requires a max_tokens default; use a sensible fallback.
        return ChatAnthropic(
            model=self.model,
            anthropic_api_key=self.api_key,
            temperature=temperature,
            max_tokens=max_tokens or 4096,
            timeout=self.extra.get("timeout", 60.0),
        )

    @property
    def chat_model(self) -> ChatAnthropic:
        if self._chat_model is None:
            self._chat_model = self._get_chat_model()
        return self._chat_model

    def get_chat_model(self) -> ChatAnthropic:
        return self.chat_model

    async def generate(
        self,
        *,
        messages: list[BaseMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        model = self._get_chat_model(temperature=temperature, max_tokens=max_tokens)
        msgs = clean_messages(messages)

        if json_mode:
            msgs = append_json_system_message(msgs)

        if tools:
            tool_schemas = tool_specs_to_openai_schema(tools)
            model = model.bind_tools(tool_schemas)

        response = await model.ainvoke(msgs)
        return langchain_to_llm_response(response)

    async def stream(
        self,
        *,
        messages: list[BaseMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        model = self._get_chat_model(temperature=temperature, max_tokens=max_tokens)
        if tools:
            tool_schemas = tool_specs_to_openai_schema(tools)
            model = model.bind_tools(tool_schemas)

        async for chunk in model.astream(clean_messages(messages)):
            yield str(chunk.content)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Anthropic does not support embeddings in this adapter")
