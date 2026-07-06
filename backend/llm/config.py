"""Configuration helpers for the unified LLM layer.

Task configs can be supplied either programmatically or via a JSON env var
(LLM_TASKS).  The default registry reproduces the pre-Phase-B behavior so
that existing deployments continue to work without any config changes.
"""
from __future__ import annotations

import json
from typing import Any

from llm.types import ProviderCapability, TaskConfig


DEFAULT_TASKS: dict[str, dict[str, Any]] = {
    "entity_resolution": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "json_mode": True,
        "capabilities_required": ["text", "json"],
    },
    "agent_decide": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "capabilities_required": ["text", "tools"],
        "fallback": [
            {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "capabilities_required": ["text", "tools"],
            }
        ],
    },
    "synthesize": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "capabilities_required": ["text"],
        "fallback": [
            {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "capabilities_required": ["text"],
            }
        ],
    },
    "lead_intent": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "json_mode": True,
        "capabilities_required": ["text", "json"],
    },
}


def _capability_from_names(names: list[str]) -> ProviderCapability:
    mapping = {
        "text": ProviderCapability.TEXT,
        "json": ProviderCapability.JSON,
        "tools": ProviderCapability.TOOLS,
        "stream": ProviderCapability.STREAM,
        "embeddings": ProviderCapability.EMBEDDINGS,
    }
    caps = ProviderCapability(0)
    for name in names:
        if name in mapping:
            caps |= mapping[name]
    return caps if caps else ProviderCapability.TEXT


def _parse_task_config(raw: dict[str, Any]) -> TaskConfig:
    caps = raw.get("capabilities_required", ["text"])
    if isinstance(caps, str):
        caps = [c.strip() for c in caps.split(",")]

    fallback_raw = raw.get("fallback", [])
    fallback = [_parse_task_config(f) for f in fallback_raw]

    return TaskConfig(
        provider=raw["provider"].lower(),
        model=raw["model"],
        temperature=float(raw.get("temperature", 0.0)),
        max_tokens=raw.get("max_tokens"),
        json_mode=bool(raw.get("json_mode", False)),
        timeout_seconds=float(raw.get("timeout_seconds", 60.0)),
        capabilities_required=_capability_from_names(caps),
        fallback=fallback,
    )


def build_task_registry(config_json: str | None) -> dict[str, TaskConfig]:
    """Build a task-name -> TaskConfig map from JSON or defaults."""
    if config_json:
        try:
            parsed = json.loads(config_json)
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = {}

    # Always seed defaults first, then let explicit config override.
    registry = {name: _parse_task_config(cfg) for name, cfg in DEFAULT_TASKS.items()}
    for name, raw in parsed.items():
        registry[name] = _parse_task_config(raw)

    return registry
