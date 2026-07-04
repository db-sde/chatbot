# Phase B Provider Compatibility Report

**Date:** 2026-07-04  
**Scope:** Verify which capabilities each supported provider exposes through the unified LLM layer.

---

## 1. Capability Matrix

| Provider | Text | JSON | Tools | Stream | Embeddings | Notes |
|---|---|---|---|---|---|---|
| **Groq** | ✅ | ✅ | ✅ | ✅ | ❌ | Fast inference; tool calling via `langchain-groq`. |
| **Gemini** | ✅ | ✅ | ✅ | ✅ | ✅ | Embeddings via `google-generativeai`; native JSON mime type. |
| **OpenAI** | ✅ | ✅ | ✅ | ✅ | ❌* | `langchain-openai`; embeddings support is a future adapter change. |
| **OpenRouter** | ✅ | ✅ | ✅ | ✅ | ❌ | OpenAI-compatible base URL; model IDs are `provider/model`. |
| **Anthropic** | ✅ | ✅ | ✅ | ✅ | ❌ | `langchain-anthropic`; requires `max_tokens` default. |
| **DeepSeek** | ✅ | ✅ | ✅ | ✅ | ❌ | OpenAI-compatible base URL `https://api.deepseek.com`. |
| **Kimi (Moonshot)** | ✅ | ✅ | ✅ | ✅ | ❌ | OpenAI-compatible base URL `https://api.moonshot.cn/v1`. |

*OpenAI embeddings are not exposed in this adapter but can be added without touching callers.

---

## 2. Task-to-Capability Mapping

| Task | Required Capabilities | Suitable Providers |
|---|---|---|
| `embedding` | `EMBEDDINGS` | Gemini |
| `entity_resolution` | `TEXT + JSON` | Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, Kimi |
| `agent_decide` | `TEXT + TOOLS` | Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, Kimi |
| `synthesize` | `TEXT` | All |
| `lead_intent` | `TEXT + JSON` | Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, Kimi |

The registry skips any fallback entry whose adapter lacks the required capabilities.

---

## 3. API Key / Environment Variables

| Provider | Required Key | Optional Base URL |
|---|---|---|
| Groq | `GROQ_API_KEY` | — |
| Gemini | `GEMINI_API_KEY` | — |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` |
| OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_BASE_URL` (default set) |
| Anthropic | `ANTHROPIC_API_KEY` | — |
| DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` (default set) |
| Kimi | `KIMI_API_KEY` | `KIMI_BASE_URL` (default set) |

---

## 4. Model Name Conventions

| Provider | Example Model ID |
|---|---|
| Groq | `llama-3.3-70b-versatile` |
| Gemini | `gemini-2.5-flash` |
| OpenAI | `gpt-4o-mini`, `gpt-4o` |
| OpenRouter | `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet` |
| Anthropic | `claude-3-5-sonnet-20241022` |
| DeepSeek | `deepseek-chat`, `deepseek-reasoner` |
| Kimi | `moonshot-v1-8k`, `moonshot-v1-32k` |

---

## 5. Backward Compatibility

| Surface | Status | Notes |
|---|---|---|
| `agent.llm_client.llm_client.generate_text(prompt)` | ✅ Preserved | Now delegates to unified layer; still patchable in tests. |
| `agent.llm_client.llm_client.generate_json(prompt)` | ✅ Preserved | Accepts optional `task` kwarg. |
| `agent.llm_client.llm_client.chat_model` | ✅ Preserved | Returns primary `agent_decide` chat model. |
| `agent.llm_client.llm_client.enabled` | ✅ Preserved | True when any required task has a usable provider. |
| `agent.llm_client.llm_client.groq_model` | ✅ Preserved | Legacy shim for tests. |
| `agent.llm_client.llm_client.gemini_model` | ✅ Preserved | Legacy shim for tests. |
| LangGraph state schema | ✅ Unchanged | Still uses `BaseMessage` / `ToolMessage`. |
| Database schema | ✅ Unchanged | No migrations required. |
| `.env` variables before Phase B | ✅ Unchanged | `GROQ_API_KEY`, `GEMINI_API_KEY`, model names still work. |

---

## 6. Configuration-Only Provider Switching

The following changes are now achievable by editing `.env` only — **no code changes**:

| Goal | Configuration |
|---|---|
| Change Groq model | `GROQ_MODEL_NAME=...` |
| Change Gemini model | `GEMINI_MODEL_NAME=...` |
| Move synthesis from Groq to OpenAI | `LLM_TASKS={"synthesize": {"provider": "openai", "model": "gpt-4o"}}` |
| Add Gemini fallback to agent_decide | `LLM_TASKS={"agent_decide": {"provider": "groq", "model": "llama-3.3-70b-versatile", "fallback": [{"provider": "gemini", "model": "gemini-2.5-flash"}]}}` |
| Use OpenRouter for all chat tasks | Set `OPENROUTER_API_KEY` and override each task in `LLM_TASKS` |
| Disable a provider | Remove its API key from `.env` |

---

## 7. Tested Combinations

The unit test suite validates:

- Default registry with Groq primary / Gemini fallback
- Custom registry overrides via `LLM_TASKS` JSON
- Manager fallback chain with fake adapters
- JSON parsing and tool-schema conversion
- Streaming and embedding interfaces

All existing graph/tool/unit tests continue to pass.
