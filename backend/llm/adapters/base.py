"""Base utilities shared by all provider adapters."""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from llm.types import LLMResponse, ToolSpec

logger = logging.getLogger(__name__)


def to_langchain_messages(prompt: str | list[BaseMessage]) -> list[BaseMessage]:
    """Normalize a plain string prompt or message list to LangChain messages."""
    if isinstance(prompt, str):
        return [HumanMessage(content=prompt)]
    return list(prompt)


def tool_specs_to_openai_schema(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
    """Convert unified ToolSpec list to OpenAI-compatible function schema."""
    if not tools:
        return []

    result: list[dict[str, Any]] = []
    for tool in tools:
        schema = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters,
                    "required": tool.required,
                    "additionalProperties": False,
                },
            },
        }
        result.append(schema)
    return result


def extract_response_metadata(msg: AIMessage) -> dict[str, Any]:
    """Extract normalized metadata from a LangChain AIMessage."""
    meta = getattr(msg, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or {}

    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")

    return {
        "model_name": meta.get("model_name"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "finish_reason": meta.get("finish_reason"),
    }


def langchain_to_llm_response(msg: AIMessage) -> LLMResponse:
    """Convert a LangChain AIMessage to a normalized LLMResponse."""
    meta = extract_response_metadata(msg)
    return LLMResponse(
        content=str(msg.content) if msg.content else "",
        model_name=meta.get("model_name"),
        input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"),
        total_tokens=meta.get("total_tokens"),
        tool_calls=[dict(tc) for tc in (msg.tool_calls or [])],
        finish_reason=meta.get("finish_reason"),
    )


def safe_parse_json(text: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON; return {} on failure."""
    stripped = (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON response: %s", stripped[:200])
        return {}


def append_json_system_message(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Append a system instruction forcing raw JSON output."""
    instruction = (
        "You must respond with a single valid JSON object. "
        "Do not wrap the JSON in markdown code fences and do not add explanatory text."
    )
    # Avoid duplicating the instruction.
    if messages and isinstance(messages[0], SystemMessage):
        existing = str(messages[0].content)
        if instruction not in existing:
            messages = [
                SystemMessage(content=f"{existing}\n\n{instruction}"),
                *messages[1:],
            ]
    else:
        messages = [SystemMessage(content=instruction), *messages]
    return messages


def langchain_tools_to_specs(tools: list[Any]) -> list[ToolSpec]:
    """Convert LangChain @tool functions to unified ToolSpec objects."""
    specs: list[ToolSpec] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", "unknown")
        description = getattr(tool, "description", "") or ""
        args_schema = getattr(tool, "args_schema", None)
        parameters: dict[str, Any] = {}
        required: list[str] = []
        if args_schema is not None:
            try:
                schema = args_schema.model_json_schema()
                parameters = schema.get("properties", {})
                required = schema.get("required", [])
            except Exception:
                pass
        specs.append(ToolSpec(name=name, description=description, parameters=parameters, required=required))
    return specs


def llm_response_to_ai_message(response: LLMResponse) -> AIMessage:
    """Convert a normalized LLMResponse back to a LangChain AIMessage."""
    kwargs: dict[str, Any] = {"content": response.content}
    if response.tool_calls:
        kwargs["tool_calls"] = response.tool_calls
    return AIMessage(**kwargs)


def clean_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Sanitize messages so all providers can consume them."""
    cleaned: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if not isinstance(content, str):
                try:
                    content = json.dumps(content)
                except Exception:
                    content = str(content)
            cleaned.append(
                ToolMessage(
                    content=content,
                    name=getattr(msg, "name", None),
                    tool_call_id=msg.tool_call_id,
                    status=getattr(msg, "status", "success"),
                    artifact=getattr(msg, "artifact", None),
                )
            )
        else:
            cleaned.append(msg)
    return cleaned
