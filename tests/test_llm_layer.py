"""Unit tests for the unified LLM layer introduced in Phase B.

These tests do not require real provider API keys; they exercise the registry,
adapter conversion helpers, and the LLMManager fallback logic with fake adapters.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from langchain_core.messages import AIMessage, HumanMessage

from llm import LLMManager, ModelRegistry, ProviderCapability
from llm.adapters.base import (
    langchain_tools_to_specs,
    llm_response_to_ai_message,
    safe_parse_json,
    tool_specs_to_openai_schema,
)
from llm.config import build_task_registry
from llm.types import LLMResponse, TaskConfig, ToolSpec


class FakeAdapter:
    """In-memory provider adapter for testing."""

    name = "fake"
    capabilities = ProviderCapability.TEXT | ProviderCapability.JSON | ProviderCapability.TOOLS

    def __init__(self, response: LLMResponse | Exception | None = None) -> None:
        self.response = response or LLMResponse(content="hello")
        self.calls: list[dict[str, Any]] = []

    async def generate(self, *, messages, tools=None, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def stream(self, *, messages, tools=None, **kwargs) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        for token in self.response.content.split():
            yield token + " "

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def get_chat_model(self):
        return self


class FakeEmbeddingAdapter(FakeAdapter):
    name = "fake-embedding"
    capabilities = ProviderCapability.EMBEDDINGS


class AlwaysFailAdapter(FakeAdapter):
    name = "fail"
    capabilities = ProviderCapability.TEXT

    async def generate(self, *, messages, tools=None, **kwargs) -> LLMResponse:
        raise RuntimeError("always fails")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_safe_parse_json_strips_fences():
    assert safe_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert safe_parse_json('{"b": 2}') == {"b": 2}
    assert safe_parse_json("not json") == {}


def test_tool_specs_to_openai_schema():
    specs = [
        ToolSpec(
            name="get_fee",
            description="Get fee",
            parameters={"university_slug": {"type": "string"}},
            required=["university_slug"],
        )
    ]
    schemas = tool_specs_to_openai_schema(specs)
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "get_fee"


def test_llm_response_to_ai_message():
    response = LLMResponse(content="hi", tool_calls=[{"name": "t", "args": {}, "id": "tc1"}])
    msg = llm_response_to_ai_message(response)
    assert isinstance(msg, AIMessage)
    assert msg.content == "hi"
    assert len(msg.tool_calls) == 1


def test_langchain_tools_to_specs():
    from langchain_core.tools import tool

    @tool
    def demo_tool(x: int) -> int:
        """Demo tool."""
        return x

    specs = langchain_tools_to_specs([demo_tool])
    assert specs[0].name == "demo_tool"
    assert "x" in specs[0].parameters


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_default_registry_tasks():
    registry = ModelRegistry()
    assert set(registry.list_tasks()) == {
        "entity_resolution",
        "agent_decide",
        "synthesize",
        "lead_intent",
    }


def test_custom_registry_override():
    registry = ModelRegistry('{"synthesize": {"provider": "openai", "model": "gpt-4o"}}')
    cfg = registry.get_task_config("synthesize")
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o"


def test_capability_parsing():
    cfg = build_task_registry('{"t": {"provider": "openai", "model": "gpt-4o", "capabilities_required": "text,tools,stream"}}')
    assert cfg["t"].capabilities_required == (ProviderCapability.TEXT | ProviderCapability.TOOLS | ProviderCapability.STREAM)


# ---------------------------------------------------------------------------
# Manager fallback chain
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_factory(monkeypatch):
    """Allow tests to inject fake adapters by provider name."""
    adapters: dict[str, Any] = {}

    def fake_create_adapter(provider, model, **extra):
        return adapters.get(provider)

    import llm.registry as registry_mod
    monkeypatch.setattr(registry_mod, "create_adapter", fake_create_adapter)
    return adapters


def _make_registry():
    primary = TaskConfig(provider="fake-primary", model="m1")
    fallback = TaskConfig(provider="fake-fallback", model="m2")
    registry = ModelRegistry.__new__(ModelRegistry)
    registry.tasks = {"test_task": primary}
    primary.fallback = [fallback]
    return registry


@pytest.mark.asyncio
async def test_manager_uses_primary_when_successful(patch_factory):
    adapters = patch_factory
    adapters["fake-primary"] = FakeAdapter(LLMResponse(content="primary"))
    adapters["fake-fallback"] = FakeAdapter(LLMResponse(content="fallback"))

    manager = LLMManager(_make_registry())
    response = await manager.generate("test_task", "hello")
    assert response.content == "primary"
    assert adapters["fake-primary"].calls
    assert not adapters["fake-fallback"].calls


@pytest.mark.asyncio
async def test_manager_falls_back_on_failure(patch_factory):
    adapters = patch_factory
    adapters["fake-primary"] = FakeAdapter(RuntimeError("primary failed"))
    adapters["fake-fallback"] = FakeAdapter(LLMResponse(content="fallback"))

    manager = LLMManager(_make_registry())
    response = await manager.generate("test_task", "hello")
    assert response.content == "fallback"
    assert adapters["fake-primary"].calls
    assert adapters["fake-fallback"].calls


@pytest.mark.asyncio
async def test_manager_generate_json(patch_factory):
    adapters = patch_factory
    adapters["fake-primary"] = FakeAdapter(LLMResponse(content='{"ok": true}'))

    manager = LLMManager(_make_registry())
    result = await manager.generate_json("test_task", "extract")
    assert result == {"ok": True}



@pytest.mark.asyncio
async def test_manager_stream(patch_factory):
    adapters = patch_factory
    adapters["fake-primary"] = FakeAdapter(LLMResponse(content="hello world"))

    manager = LLMManager(_make_registry())
    chunks = []
    async for chunk in await manager.generate("test_task", "hi", stream=True):
        chunks.append(chunk)
    assert "".join(chunks).strip() == "hello world"
