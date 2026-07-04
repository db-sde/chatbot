"""Task-based model registry with capability-aware fallback chains."""
from __future__ import annotations

import logging
from typing import Any

from llm.config import build_task_registry
from llm.factory import create_adapter
from llm.types import LLMProvider, ProviderCapability, TaskConfig

logger = logging.getLogger(__name__)


class ModelRegistry:
    """Holds task configs and resolves them to provider adapters on demand."""

    def __init__(self, config_json: str | None = None) -> None:
        self.tasks = build_task_registry(config_json)

    def get_task_config(self, task_name: str) -> TaskConfig:
        if task_name not in self.tasks:
            raise KeyError(f"Unknown LLM task: {task_name}")
        return self.tasks[task_name]

    def list_tasks(self) -> list[str]:
        return sorted(self.tasks.keys())

    def resolve_chain(self, task_name: str) -> list[tuple[TaskConfig, LLMProvider]]:
        """Return a list of (config, adapter) tuples for the task and its fallbacks.

        Entries with missing API keys or insufficient capabilities are skipped.
        """
        config = self.get_task_config(task_name)
        chain: list[tuple[TaskConfig, LLMProvider]] = []

        for cfg in [config, *config.fallback]:
            adapter = create_adapter(cfg.provider, cfg.model, timeout=cfg.timeout_seconds)
            if adapter is None:
                logger.debug("Skipping %s for task %s: adapter not available", cfg.provider, task_name)
                continue
            if not adapter.capabilities & cfg.capabilities_required:
                logger.warning(
                    "Provider %s lacks required capabilities %s for task %s",
                    cfg.provider, cfg.capabilities_required, task_name
                )
                continue
            chain.append((cfg, adapter))

        return chain

    def has_provider_for_task(self, task_name: str) -> bool:
        return bool(self.resolve_chain(task_name))

    def get_primary_provider(self, task_name: str) -> tuple[TaskConfig, LLMProvider] | None:
        chain = self.resolve_chain(task_name)
        return chain[0] if chain else None
