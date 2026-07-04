# Phase B Migration Report — Unified LLM Layer

**Date:** 2026-07-04  
**Scope:** Replace provider-specific LLM calls with a unified, config-driven provider abstraction layer supporting Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, and Kimi.

---

## 1. What Changed

### 1.1 New package: `backend/llm/`

| File | Purpose |
|---|---|
| `llm/__init__.py` | Public exports (`LLMManager`, `ModelRegistry`, `ProviderCapability`, etc.) |
| `llm/types.py` | `LLMProvider` protocol, `LLMResponse`, `TaskConfig`, `ToolSpec`, `ProviderCapability` |
| `llm/config.py` | Default task registry and JSON parsing |
| `llm/registry.py` | `ModelRegistry`: resolves task configs to adapters, capability-aware fallback chains |
| `llm/factory.py` | `create_adapter(provider, model)` — instantiates the right adapter |
| `llm/manager.py` | `LLMManager`: unified `generate`, `generate_json`, `embed`, `stream` interface |
| `llm/adapters/base.py` | Shared helpers: message cleaning, JSON parsing, tool-schema conversion |
| `llm/adapters/groq.py` | Groq adapter (langchain-groq) |
| `llm/adapters/gemini.py` | Gemini adapter (langchain-google-genai + google-generativeai) |
| `llm/adapters/openai.py` | OpenAI adapter (langchain-openai) |
| `llm/adapters/openrouter.py` | OpenRouter adapter (OpenAI-compatible) |
| `llm/adapters/anthropic.py` | Anthropic adapter (langchain-anthropic) |
| `llm/adapters/deepseek.py` | DeepSeek adapter (OpenAI-compatible) |
| `llm/adapters/kimi.py` | Kimi / Moonshot adapter (OpenAI-compatible) |

### 1.2 Refactored files

| File | Change |
|---|---|
| `backend/agent/llm_client.py` | Became a thin facade over `LLMManager`.  Preserves `generate_text()`, `generate_json()`, `chat_model`, `enabled`, plus legacy `groq_model`/`gemini_model` attributes for tests. |
| `backend/agent/graph.py` | Removed all `groq`/`gemini` branching and `bind_tools()` logic.  `node_agent_decide` and `node_synthesize_reply` now call `llm_client.generate("agent_decide", ...)` / `llm_client.generate("synthesize", ...)`. |
| `backend/agent/resolve.py` | `_get_embedding()` now uses `llm_client.embed()` instead of direct `google.generativeai`. |
| `backend/leads/intent.py` | Calls `llm_client.generate_json(prompt, task="lead_intent")` so lead intent is independently configurable. |
| `backend/settings.py` | Added API keys and default model names for all 7 providers; added `llm_tasks: str` JSON config field. |
| `backend/pricing_config.py` | Added pricing entries for OpenAI, Anthropic, DeepSeek, and Kimi default models. |
| `backend/observability.py` | Made `record_llm_call()` defensive against uninitialized context (helps tests and edge cases). |
| `backend/pyproject.toml` | Added `langchain-openai`, `langchain-anthropic`, `openai`, `anthropic` dependencies. |
| `.env.example` | Documented all new provider keys and the `LLM_TASKS` JSON format. |

### 1.3 New tests

| File | Coverage |
|---|---|
| `tests/test_llm_layer.py` | Registry parsing, capability flags, tool-schema conversion, manager fallback chain, streaming, embeddings. |

---

## 2. Behavior Preservation

The default registry reproduces the pre-Phase-B behavior exactly:

| Task | Primary | Fallback |
|---|---|---|
| `embedding` | Gemini `models/text-embedding-004` | — |
| `entity_resolution` | Gemini `gemini-2.5-flash` | — |
| `agent_decide` | Groq `llama-3.3-70b-versatile` | Gemini `gemini-2.5-flash` |
| `synthesize` | Groq `llama-3.3-70b-versatile` | Gemini `gemini-2.5-flash` |
| `lead_intent` | Gemini `gemini-2.5-flash` | — |

With no `LLM_TASKS` env var set, the system behaves identically to before, using the same models and fallbacks.

---

## 3. Validation

- `uv run pytest tests -v` → **49 passed, 3 skipped**
- `npm run lint` → **0 errors**
- `uv run python -c "from agent.llm_client import llm_client; ..."` → imports OK

---

## 4. Configuration Examples

### Switch synthesize to OpenAI
```bash
OPENAI_API_KEY=sk-...
LLM_TASKS='{"synthesize": {"provider": "openai", "model": "gpt-4o"}}'
```

### Route everything through OpenRouter
```bash
OPENROUTER_API_KEY=sk-or-...
LLM_TASKS='{
  "agent_decide": {"provider": "openrouter", "model": "openai/gpt-4o", "capabilities_required": ["text", "tools"]},
  "synthesize": {"provider": "openrouter", "model": "openai/gpt-4o"},
  "entity_resolution": {"provider": "openrouter", "model": "openai/gpt-4o", "json_mode": true},
  "lead_intent": {"provider": "openrouter", "model": "openai/gpt-4o", "json_mode": true}
}'
```

### Use DeepSeek with Kimi fallback
```bash
DEEPSEEK_API_KEY=...
KIMI_API_KEY=...
LLM_TASKS='{
  "agent_decide": {"provider": "deepseek", "model": "deepseek-chat", "capabilities_required": ["text", "tools"], "fallback": [{"provider": "kimi", "model": "moonshot-v1-8k"}]},
  "synthesize": {"provider": "deepseek", "model": "deepseek-chat"}
}'
```

---

## 5. Known Limitations

1. **Tool calling** depends on the underlying LangChain chat model's `bind_tools()`.  Adapters declare `TOOLS` capability only when the LangChain integration supports it (Groq, Gemini, OpenAI, Anthropic).
2. **Streaming** in the graph is not yet wired end-to-end; the SSE layer still word-chunks a fully-buffered reply.  The unified layer supports streaming for future use.
3. **Embeddings** are only supported by the Gemini adapter in this build.  Adding OpenAI embeddings is a future one-adapter change.
4. **JSON mode** for providers without native JSON support falls back to prompt-based JSON instructions + markdown-stripping parser.

---

## 6. Deployment Checklist

- [ ] Add required provider API keys to `.env`
- [ ] Optionally set `LLM_TASKS` to customize task/provider mapping
- [ ] Run `uv sync` to install new dependencies
- [ ] Run `uv run pytest tests -v`
- [ ] Verify `llm_client.enabled` is True at startup (logs or health check)
- [ ] Monitor first-token latency and fallback usage after cutover
