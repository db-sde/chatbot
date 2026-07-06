"""LLM configuration — the ONLY file to edit when switching providers.

To switch providers, change PROVIDER and MODEL, then restart the server.
"""
from __future__ import annotations

# Active provider: "groq" or "deepseek"
PROVIDER = "groq"

# Main model for chat / agent decision turns
MODEL = "llama-3.3-70b-versatile"

# Model used for JSON extraction tasks (entity_resolution, lead_intent)
# Must support response_format={"type": "json_object"}
JSON_MODEL = "llama-3.3-70b-versatile"
