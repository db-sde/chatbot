"""High-level LLM manager used by the rest of the application.

The manager exposes a single interface for every LLM task.  Callers specify a
task name (e.g. "synthesize") and the manager picks the right provider/model
from the registry, walks the fallback chain on failure, records observability,
and returns normalized responses.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, AsyncIterator

from langchain_core.messages import BaseMessage, HumanMessage

from llm.adapters.base import safe_parse_json, to_langchain_messages
from llm.registry import ModelRegistry
from llm.types import LLMProvider, LLMResponse, ProviderCapability, TaskConfig, ToolSpec
from observability import (
    mark_first_token,
    mark_llm_start,
    record_llm_call,
    record_llm_call_duration,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_MAX_DELAY = 8.0   # seconds


class LLMManager:
    """Unified LLM interface."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _execute_with_fallbacks(
        self,
        task_name: str,
        operation: str,
        call_fn,
    ) -> LLMResponse:
        """Run an operation against the fallback chain with retries."""
        chain = self.registry.resolve_chain(task_name)
        if not chain:
            raise RuntimeError(f"No provider available for task {task_name}")

        mark_llm_start()
        t_start = time.perf_counter()
        last_error: Exception | None = None

        for cfg, adapter in chain:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    logger.debug("%s task=%s provider=%s attempt=%d", operation, task_name, cfg.provider, attempt)
                    result: LLMResponse = await call_fn(cfg, adapter)
                    mark_first_token()
                    duration_ms = int((time.perf_counter() - t_start) * 1000)
                    record_llm_call_duration(duration_ms)
                    self._record_usage(result)
                    return result
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "%s failed for task=%s provider=%s attempt=%d: %s",
                        operation, task_name, cfg.provider, attempt, exc
                    )
                    if attempt < _MAX_RETRIES:
                        delay = min(_BASE_DELAY * (2 ** (attempt - 1)) + random.random(), _MAX_DELAY)
                        await asyncio.sleep(delay)

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        record_llm_call_duration(duration_ms)
        raise RuntimeError(f"All providers failed for task {task_name}: {last_error}")

    def _record_usage(self, response: LLMResponse) -> None:
        """Best-effort token/cost recording from normalized metadata."""
        metadata: dict[str, Any] = {
            "model_name": response.model_name,
            "token_usage": {
                "input_tokens": response.input_tokens or 0,
                "output_tokens": response.output_tokens or 0,
                "total_tokens": response.total_tokens or 0,
            },
        }
        record_llm_call(metadata)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def generate(
        self,
        task_name: str,
        prompt: str | list[BaseMessage],
        *,
        tools: list[ToolSpec] | None = None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> LLMResponse | AsyncIterator[str]:
        """Generate a response for the given task.

        Set stream=True to receive an async iterator of content chunks.
        """
        messages = to_langchain_messages(prompt)

        if stream:
            return self._stream(task_name, messages, tools=tools)

        return await self._execute_with_fallbacks(
            task_name,
            "generate",
            lambda cfg, adapter: adapter.generate(
                messages=messages,
                tools=tools,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                json_mode=json_mode or cfg.json_mode,
            ),
        )

    async def _stream(
        self,
        task_name: str,
        messages: list[BaseMessage],
        *,
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[str]:
        """Internal streaming helper that walks the fallback chain."""
        chain = self.registry.resolve_chain(task_name)
        if not chain:
            raise RuntimeError(f"No provider available for task {task_name}")

        mark_llm_start()
        t_start = time.perf_counter()
        last_error: Exception | None = None

        for cfg, adapter in chain:
            try:
                stream_iter = adapter.stream(
                    messages=messages,
                    tools=tools,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )
                first = True
                async for chunk in stream_iter:
                    if first:
                        mark_first_token()
                        first = False
                    yield chunk
                duration_ms = int((time.perf_counter() - t_start) * 1000)
                record_llm_call_duration(duration_ms)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("stream failed for task=%s provider=%s: %s", task_name, cfg.provider, exc)

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        record_llm_call_duration(duration_ms)
        raise RuntimeError(f"All providers failed for stream task {task_name}: {last_error}")

    async def generate_json(
        self,
        task_name: str,
        prompt: str | list[BaseMessage],
        *,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate and parse a JSON response for the given task."""
        response = await self.generate(task_name, prompt, json_mode=True)
        if isinstance(response, AsyncIterator):
            # Streaming is not meaningful for JSON mode; drain it defensively.
            text = ""
            async for chunk in response:
                text += chunk
            return safe_parse_json(text)
        return safe_parse_json(response.content)

    async def embed(self, task_name: str, text: str) -> list[float]:
        """Generate embeddings for a single text."""
        chain = self.registry.resolve_chain(task_name)
        if not chain:
            raise RuntimeError(f"No provider available for task {task_name}")

        for cfg, adapter in chain:
            if not adapter.capabilities & ProviderCapability.EMBEDDINGS:
                continue
            try:
                embeddings = await adapter.embed([text])
                return embeddings[0] if embeddings else []
            except Exception as exc:  # noqa: BLE001
                logger.warning("embed failed for task=%s provider=%s: %s", task_name, cfg.provider, exc)

        raise RuntimeError(f"No embedding provider available for task {task_name}")

    def get_chat_model(self, task_name: str) -> Any:
        """Return a LangChain chat model for direct use by LangGraph.

        Falls back through the task chain and returns the first available model.
        """
        chain = self.registry.resolve_chain(task_name)
        if not chain:
            raise RuntimeError(f"No provider available for task {task_name}")
        return chain[0][1].get_chat_model()

    def has_task(self, task_name: str) -> bool:
        return self.registry.has_provider_for_task(task_name)
