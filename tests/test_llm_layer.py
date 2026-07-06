"""Unit tests for the simplified LLM provider layer.

These tests exercise the utility helpers in llm.provider without making
any real API calls.  Provider-level generate/stream are not tested here
because they require live keys — smoke-tested manually instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from llm.provider import (
    LLMResponse,
    ToolSpec,
    append_json_system_message,
    clean_messages,
    langchain_tools_to_specs,
    llm_response_to_ai_message,
    safe_parse_json,
    to_langchain_messages,
    tool_specs_to_openai_schema,
)


# ---------------------------------------------------------------------------
# safe_parse_json
# ---------------------------------------------------------------------------

def test_safe_parse_json_strips_fences():
    assert safe_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert safe_parse_json('{"b": 2}') == {"b": 2}
    assert safe_parse_json("not json") == {}


def test_safe_parse_json_empty_string():
    assert safe_parse_json("") == {}


# ---------------------------------------------------------------------------
# tool_specs_to_openai_schema
# ---------------------------------------------------------------------------

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
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "get_fee"
    assert schemas[0]["function"]["parameters"]["required"] == ["university_slug"]


# ---------------------------------------------------------------------------
# llm_response_to_ai_message
# ---------------------------------------------------------------------------

def test_llm_response_to_ai_message_plain():
    response = LLMResponse(content="hi")
    msg = llm_response_to_ai_message(response)
    assert isinstance(msg, AIMessage)
    assert msg.content == "hi"


def test_llm_response_to_ai_message_with_tool_calls():
    response = LLMResponse(content="hi", tool_calls=[{"name": "t", "args": {}, "id": "tc1"}])
    msg = llm_response_to_ai_message(response)
    assert isinstance(msg, AIMessage)
    assert len(msg.tool_calls) == 1


# ---------------------------------------------------------------------------
# langchain_tools_to_specs
# ---------------------------------------------------------------------------

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
# to_langchain_messages
# ---------------------------------------------------------------------------

def test_to_langchain_messages_from_string():
    msgs = to_langchain_messages("hello")
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "hello"


def test_to_langchain_messages_from_list():
    original = [HumanMessage(content="hi")]
    msgs = to_langchain_messages(original)
    assert msgs == original


# ---------------------------------------------------------------------------
# append_json_system_message
# ---------------------------------------------------------------------------

def test_append_json_system_message_adds_instruction():
    msgs = [HumanMessage(content="extract")]
    result = append_json_system_message(msgs)
    assert isinstance(result[0], SystemMessage)
    assert "JSON" in result[0].content


def test_append_json_system_message_extends_existing_system():
    msgs = [SystemMessage(content="You are helpful."), HumanMessage(content="go")]
    result = append_json_system_message(msgs)
    assert isinstance(result[0], SystemMessage)
    assert "You are helpful." in result[0].content
    assert "JSON" in result[0].content


def test_append_json_system_message_no_duplicate():
    instruction = (
        "You must respond with a single valid JSON object. "
        "Do not wrap the JSON in markdown code fences and do not add explanatory text."
    )
    msgs = [SystemMessage(content=f"pre\n\n{instruction}"), HumanMessage(content="q")]
    result = append_json_system_message(msgs)
    # Should not duplicate the instruction
    assert result[0].content.count("JSON object") == 1


# ---------------------------------------------------------------------------
# clean_messages
# ---------------------------------------------------------------------------

def test_clean_messages_stringifies_tool_message_content():
    msg = ToolMessage(content={"key": "value"}, tool_call_id="tc1")
    cleaned = clean_messages([msg])
    assert isinstance(cleaned[0].content, str)
    assert "key" in cleaned[0].content


def test_clean_messages_passthrough_human():
    msg = HumanMessage(content="hello")
    cleaned = clean_messages([msg])
    assert cleaned[0] is msg
