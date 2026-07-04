# Phase B Rollback Plan

**Date:** 2026-07-04  
**Scope:** Step-by-step instructions to revert the unified LLM layer if critical issues are discovered in production.

---

## 1. Pre-Rollback Safety

Before rolling back:

1. Capture current metrics (p95 latency, error rate, cost per turn, fallback usage).
2. Identify the failing provider/task from logs.
3. Consider a **configuration-only mitigation first**:
   - Switch the failing task to a different provider via `LLM_TASKS`.
   - Remove the failing provider's API key to force fallback.
   - Increase `timeout_seconds` for the failing task.

Only proceed with code rollback if a config fix is not sufficient.

---

## 2. Configuration-Only Rollback (Recommended First Step)

The fastest way to revert behavior is to restore the pre-Phase-B default task assignment in `.env`:

```bash
# Remove any custom LLM_TASKS so defaults take over
LLM_TASKS=

# Keep only Groq + Gemini keys as before
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

This makes the system behave exactly like pre-Phase-B without touching code.

---

## 3. Code Rollback (if configuration is insufficient)

### 3.1 Files to restore from git

If the repository is clean, the fastest rollback is:

```bash
git checkout HEAD -- backend/agent/graph.py
                        backend/agent/llm_client.py
                        backend/agent/resolve.py
                        backend/leads/intent.py
                        backend/settings.py
                        backend/pricing_config.py
                        backend/observability.py
                        backend/pyproject.toml
                        .env.example
```

### 3.2 Files to delete

```bash
rm -rf backend/llm
rm -f tests/test_llm_layer.py
rm -f docs/PHASE_B_*.md
```

### 3.3 Reinstall dependencies

```bash
cd backend
uv sync
```

### 3.4 Verify rollback

```bash
uv run pytest tests -v
npm run lint
```

---

## 4. Partial Rollback Options

### 4.1 Disable a single problematic provider

Remove that provider's API key from `.env`.  The registry will skip it and use the next fallback.

### 4.2 Revert only the graph nodes to direct LangChain usage

Keep the unified layer but make `node_agent_decide` use `llm_client.chat_model.bind_tools(TOOLS).ainvoke(...)` again.  This isolates the change while retaining the registry/fallback benefits for other tasks.

### 4.3 Revert only embedding to direct Gemini

Restore the direct `google.generativeai` call in `agent/resolve.py` while keeping the rest of the unified layer.

---

## 5. Rollback Verification Checklist

- [ ] `uv run pytest tests -v` → 37+ passed, 3 skipped
- [ ] `npm run lint` → 0 errors
- [ ] `uv run python -c "from agent.llm_client import llm_client; print(llm_client.enabled)"` → True (with valid keys)
- [ ] Send a test chat message through the widget and confirm a normal response
- [ ] Confirm no `llm/` imports remain in active code paths

---

## 6. Rollback Communication

If a rollback is performed:

1. Document the trigger (error message, metric threshold, provider outage).
2. Preserve the `LLM_TASKS` value and any relevant logs for post-mortem.
3. File a ticket to re-attempt the migration with the identified fix.

---

## 7. Risk Summary

| Risk | Likelihood | Mitigation |
|---|---|---|
| Provider-specific bug in new adapter | Low | Use config-only provider switch first. |
| Test regression from changed monkeypatch surface | Low | Tests were updated and pass; rollback restores old test code. |
| Dependency install failure | Low | `uv sync` handles new packages; rollback removes them. |
| Performance regression | Low | Default behavior unchanged; monitor p95 latency. |
