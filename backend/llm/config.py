"""LLM configuration — model selection registry and active provider mapping.
"""
from __future__ import annotations

import os
from settings import settings

# Active provider: load from settings (which checks environment), defaulting to "groq"
PROVIDER = getattr(settings, "provider", os.getenv("PROVIDER", "groq")).lower()

PROVIDER_MODELS = {
    "groq": {
        "main_agent": "llama-3.3-70b-versatile",
        "lead_intent": "llama-3.1-8b-instant",
    },
    "openai": {
        "main_agent": "gpt-4.1-mini",
        "lead_intent": "gpt-4.1-nano",
    }
}

# Resolve active models based on the selected provider
if PROVIDER not in PROVIDER_MODELS:
    # Fallback to groq if an invalid/unknown provider is specified
    active_provider = "groq"
else:
    active_provider = PROVIDER

MAIN_AGENT_MODEL = PROVIDER_MODELS[active_provider]["main_agent"]
LEAD_INTENT_MODEL = PROVIDER_MODELS[active_provider]["lead_intent"]
PROMPT_GUARD_MODEL = "meta-llama/llama-prompt-guard-2-86m"  # Always meta-llama/llama-prompt-guard-2-86m on Groq

# Legacy aliases for backward compatibility
MODEL = MAIN_AGENT_MODEL
JSON_MODEL = LEAD_INTENT_MODEL
