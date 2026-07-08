"""LLM configuration — the ONLY file to edit when switching providers.

To switch providers, change PROVIDER and MODEL, then restart the server.
"""
from __future__ import annotations

# Active provider: "groq" or "deepseek"
PROVIDER = "groq"

# Unified model selection architecture
MAIN_AGENT_MODEL = "llama-3.3-70b-versatile"
LEAD_INTENT_MODEL = "llama-3.1-8b-instant"
PROMPT_GUARD_MODEL = "meta-llama/llama-prompt-guard-2-86m"

# Legacy aliases for backward compatibility
MODEL = MAIN_AGENT_MODEL
JSON_MODEL = LEAD_INTENT_MODEL

