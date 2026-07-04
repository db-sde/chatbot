"""Unified LLM abstraction types and protocols.

This module is intentionally dependency-light: it defines the contract that
all provider adapters must satisfy so the rest of the application can call
LLMs without knowing which vendor is underneath.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from langchain_core.messages import BaseMessage


class ProviderCapability(Flag):
    """Capabilities a provider adapter may expose."""

    TEXT = auto()
    JSON = auto()
    TOOLS = auto()
    STREAM = auto()
    EMBEDDINGS = auto()


@dataclass
class ToolSpec:
    """Provider-agnostic tool definition used by the unified layer."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """Normalized response from any provider adapter."""

    content: str = ""
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None


@dataclass
class TaskConfig:
    """Configuration for a single LLM task (provider + model + behavior)."""

    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None
    json_mode: bool = False
    timeout_seconds: float = 60.0
    capabilities_required: ProviderCapability = ProviderCapability.TEXT
    fallback: list[TaskConfig] = field(default_factory=list)


@runtime_checkable
class LLMProvider(Protocol):
    """Every provider adapter must implement this protocol."""

    name: str
    capabilities: ProviderCapability

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
        ...

    async def stream(
        self,
        *,
        messages: list[BaseMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def get_chat_model(self) -> Any:
        """Return a LangChain-compatible chat model for direct LangGraph use."""
        ...
