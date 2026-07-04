"""Google Gemini adapter for the unified LLM layer."""
from __future__ import annotations

from typing import Any, AsyncIterator

from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from llm.adapters.base import (
    append_json_system_message,
    clean_messages,
    langchain_to_llm_response,
    tool_specs_to_openai_schema,
)
from llm.types import LLMProvider, LLMResponse, ProviderCapability, ToolSpec


class GeminiAdapter(LLMProvider):
    """Gemini adapter via langchain-google-genai + google-generativeai."""

    name = "gemini"
    capabilities = (
        ProviderCapability.TEXT
        | ProviderCapability.JSON
        | ProviderCapability.TOOLS
        | ProviderCapability.STREAM
        | ProviderCapability.EMBEDDINGS
    )

    def __init__(self, api_key: str, model: str, embedding_model: str | None = None, **extra: Any) -> None:
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model or "models/text-embedding-004"
        self.extra = extra
        self._chat_model: ChatGoogleGenerativeAI | None = None
        self._genai_module: Any = None

    def _get_chat_model(self, temperature: float = 0.0, max_tokens: int | None = None) -> ChatGoogleGenerativeAI:
        return ChatGoogleGenerativeAI(
            model=self.model,
            google_api_key=self.api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self.extra.get("timeout", 60.0),
        )

    @property
    def chat_model(self) -> ChatGoogleGenerativeAI:
        if self._chat_model is None:
            self._chat_model = self._get_chat_model()
        return self._chat_model

    def get_chat_model(self) -> ChatGoogleGenerativeAI:
        return self.chat_model

    def _genai(self) -> Any:
        """Lazy import google.generativeai to avoid import-time side effects."""
        if self._genai_module is None:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._genai_module = genai
        return self._genai_module

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
            try:
                model = model.bind(response_mime_type="application/json")
            except Exception:
                pass

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
        genai = self._genai()
        result = genai.embed_content(
            model=self.embedding_model,
            contents=texts if len(texts) > 1 else texts[0],
        )
        embeddings = result.get("embedding")
        if embeddings is None:
            return []
        # Normalise single vs batch return shape.
        if isinstance(texts, str) or len(texts) == 1:
            return [embeddings]
        return embeddings
