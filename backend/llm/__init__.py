"""Unified LLM layer for DegreeBaba.

Public exports:
    LLMManager          — high-level task-based interface
    ModelRegistry       — task registry with fallback chains
    LLMProvider         — provider adapter protocol
    ProviderCapability  — capability flags
    TaskConfig          — per-task configuration
    ToolSpec            — provider-agnostic tool schema
    LLMResponse         — normalized response
"""
from __future__ import annotations

from llm.adapters.base import safe_parse_json
from llm.manager import LLMManager
from llm.registry import ModelRegistry
from llm.types import LLMProvider, LLMResponse, ProviderCapability, TaskConfig, ToolSpec

__all__ = [
    "LLMManager",
    "ModelRegistry",
    "LLMProvider",
    "LLMResponse",
    "ProviderCapability",
    "TaskConfig",
    "ToolSpec",
    "safe_parse_json",
]
