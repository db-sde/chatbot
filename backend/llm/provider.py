"""Direct LLM execution layer.

This file owns everything: data models, helper utilities, and the three
public async functions that the rest of the application calls.

To add a new provider later, add an elif branch inside _get_client().
No other file needs to change.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from llm import config
from observability import mark_first_token, mark_llm_start, record_llm_call, record_llm_call_duration
from settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Provider-agnostic tool definition."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """Normalised response from any LLM call."""

    content: str
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Client factory — the only place provider names are referenced
# ---------------------------------------------------------------------------

def validate_provider_config() -> None:
    """Validate active provider environment keys at startup."""
    provider = config.PROVIDER.lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("PROVIDER=openai but OPENAI_API_KEY is not configured.")
    elif provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("PROVIDER=groq but GROQ_API_KEY is not configured.")
    elif provider == "deepseek":
        if not settings.deepseek_api_key:
            raise RuntimeError("PROVIDER=deepseek but DEEPSEEK_API_KEY is not configured.")
    else:
        raise RuntimeError(f"Unknown PROVIDER configuration: {provider!r}")


def _get_client(
    *,
    model_name: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float = 60.0,
    streaming: bool = True,
) -> Any:
    """Return a configured LangChain chat client for the active provider."""
    provider = config.PROVIDER.lower()
    
    if model_name:
        model = model_name
    else:
        model = config.JSON_MODEL if json_mode else config.MODEL

    # Prompt Guard is hosted on Groq; automatically route it to Groq if the model matches
    if model == config.PROMPT_GUARD_MODEL or (model and "prompt-guard" in model):
        provider = "groq"

    if provider == "groq":
        from langchain_groq import ChatGroq  # noqa: PLC0415
        client = ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            streaming=streaming,
        )
        if json_mode:
            client = client.bind(response_format={"type": "json_object"})
        return client

    if provider == "openai":
        from langchain_openai import ChatOpenAI  # noqa: PLC0415
        client = ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            streaming=streaming,
            stream_usage=True,  # Ensure usage_metadata is populated even in streaming mode
        )
        if json_mode:
            client = client.bind(response_format={"type": "json_object"})
        return client

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI  # noqa: PLC0415
        client = ChatOpenAI(
            model=model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url or "https://api.deepseek.com",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            streaming=streaming,
            stream_usage=True,  # Ensure usage_metadata is populated even in streaming mode
        )
        if json_mode:
            client = client.bind(response_format={"type": "json_object"})
        return client

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        "Edit config.PROVIDER in backend/llm/config.py."
    )


def get_chat_model(model_name: str | None = None, *, streaming: bool = True) -> Any:
    """Return a chat model instance (no tools bound, no json_mode)."""
    return _get_client(model_name=model_name, streaming=streaming)


def get_lead_intent_model() -> Any:
    """Return the configured ChatModel instance for lead intent classification (non-streaming)."""
    return _get_client(model_name=config.LEAD_INTENT_MODEL, json_mode=True, streaming=False)


def get_prompt_guard_model() -> Any:
    """Return the configured ChatModel instance for prompt guard classification (non-streaming)."""
    return _get_client(model_name=config.PROMPT_GUARD_MODEL, streaming=False)



# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------

async def generate(
    messages: list[BaseMessage],
    *,
    model_name: str | None = None,
    tools: list[ToolSpec] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> LLMResponse:
    """Execute a single non-streaming LLM call and return a normalised response."""
    client = _get_client(model_name=model_name, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens, streaming=False)

    if json_mode:
        messages = append_json_system_message(messages)
    if tools:
        client = client.bind_tools(tool_specs_to_openai_schema(tools))

    mark_llm_start()
    t_start = time.perf_counter()
    try:
        response: AIMessage = await client.ainvoke(clean_messages(messages))
        mark_first_token()

        # Extract tokens: prefer usage_metadata (streaming + batch) then
        # response_metadata['token_usage'] (batch-only, raw OpenAI field names).
        input_tok = 0
        output_tok = 0
        total_tok = 0

        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            input_tok = usage_meta.get("input_tokens") or 0
            output_tok = usage_meta.get("output_tokens") or 0
            total_tok = usage_meta.get("total_tokens") or (input_tok + output_tok)

        if input_tok == 0:
            meta = getattr(response, "response_metadata", {}) or {}
            usage = meta.get("token_usage") or {}
            input_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            output_tok = usage.get("completion_tokens") or usage.get("output_tokens") or 0
            total_tok = usage.get("total_tokens") or (input_tok + output_tok)

        active_model = model_name or (config.JSON_MODEL if json_mode else config.MODEL)

        record_llm_call({
            "model_name": active_model,
            "token_usage": {
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "total_tokens": total_tok,
            },
        })
        record_llm_call_duration(int((time.perf_counter() - t_start) * 1000))

        return LLMResponse(
            content=str(response.content) if response.content else "",
            model_name=active_model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=total_tok,
            tool_calls=[dict(tc) for tc in (response.tool_calls or [])],
        )
    except Exception:
        record_llm_call_duration(int((time.perf_counter() - t_start) * 1000))
        raise


async def generate_json(
    messages: list[BaseMessage],
    *,
    model_name: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Execute a JSON-mode call and return a parsed dict (empty dict on failure)."""
    response = await generate(messages, model_name=model_name, temperature=temperature, json_mode=True)
    return safe_parse_json(response.content)


async def stream(
    messages: list[BaseMessage],
    *,
    model_name: str | None = None,
    tools: list[ToolSpec] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Stream response tokens from the active LLM provider."""
    client = _get_client(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
    if tools:
        client = client.bind_tools(tool_specs_to_openai_schema(tools))

    mark_llm_start()
    t_start = time.perf_counter()
    first = True
    try:
        async for chunk in client.astream(clean_messages(messages)):
            if first:
                mark_first_token()
                first = False
            yield str(chunk.content)
        record_llm_call_duration(int((time.perf_counter() - t_start) * 1000))
    except Exception:
        record_llm_call_duration(int((time.perf_counter() - t_start) * 1000))
        raise


# ---------------------------------------------------------------------------
# Helper utilities (previously in adapters/base.py and types.py)
# ---------------------------------------------------------------------------

def tool_specs_to_openai_schema(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """Convert ToolSpec list to the OpenAI function-calling schema format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": t.required,
                    "additionalProperties": False,
                },
            },
        }
        for t in tools
    ]


def langchain_tools_to_specs(tools: list[Any]) -> list[ToolSpec]:
    """Convert LangChain @tool functions into ToolSpec objects."""
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
    """Convert a normalised LLMResponse back to a LangChain AIMessage."""
    kwargs: dict[str, Any] = {"content": response.content}
    if response.tool_calls:
        kwargs["tool_calls"] = response.tool_calls
    return AIMessage(**kwargs)


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
        logger.debug("Failed to parse JSON response: %s", stripped[:200])
        return {}


def append_json_system_message(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Prepend/extend a system message instructing raw JSON output."""
    instruction = (
        "You must respond with a single valid JSON object. "
        "Do not wrap the JSON in markdown code fences and do not add explanatory text."
    )
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


def clean_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Sanitise a message list so all providers can consume it."""
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


def to_langchain_messages(prompt: str | list[BaseMessage]) -> list[BaseMessage]:
    """Normalise a plain string or message list to a LangChain message list."""
    if isinstance(prompt, str):
        return [HumanMessage(content=prompt)]
    return list(prompt)
