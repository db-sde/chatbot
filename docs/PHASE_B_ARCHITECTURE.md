# Phase B Architecture — Unified LLM Layer

## Component Diagram (Mermaid)

```mermaid
flowchart TB
    subgraph Application
        direction TB
        G[agent/graph.py
           LangGraph nodes]
        R[agent/resolve.py
           entity resolution]
        LI[leads/intent.py
           lead classifier]
        OC[observability.py
           metrics]
    end

    subgraph "LLM Facade"
        direction TB
        LC[agent/llm_client.py
           LLMClient]
    end

    subgraph "Unified LLM Layer"
        direction TB
        LM[llm/manager.py
           LLMManager]
        MR[llm/registry.py
           ModelRegistry]
        LF[llm/factory.py
           create_adapter]
        LT[llm/types.py
           protocols + capabilities]
    end

    subgraph "Provider Adapters"
        direction TB
        GA[llm/adapters/groq.py]
        GM[llm/adapters/gemini.py]
        OA[llm/adapters/openai.py]
        OR[llm/adapters/openrouter.py]
        AN[llm/adapters/anthropic.py]
        DS[llm/adapters/deepseek.py]
        KI[llm/adapters/kimi.py]
    end

    subgraph "Vendor SDKs"
        direction TB
        VG[groq / langchain-groq]
        VGM[google-generativeai /
            langchain-google-genai]
        VO[openai / langchain-openai]
        VA[anthropic / langchain-anthropic]
    end

    G -->|generate('agent_decide', ...)| LC
    G -->|generate('synthesize', ...)| LC
    R -->|generate_json() / embed()| LC
    LI -->|generate_json(task='lead_intent')| LC
    LC -->|delegate| LM
    LM -->|resolve_chain(task)| MR
    MR -->|create_adapter(provider, model)| LF
    LF --> GA & GM & OA & OR & AN & DS & KI
    GA --> VG
    GM --> VGM
    OA --> VO
    OR --> VO
    AN --> VA
    DS --> VO
    KI --> VO
    LM -.->|record_llm_call / duration| OC
```

## Call Flow for One Chat Turn

```mermaid
sequenceDiagram
    participant U as User
    participant Gr as LangGraph
    participant LC as LLMClient
    participant LM as LLMManager
    participant MR as ModelRegistry
    participant Ad as Adapter
    participant Pr as Provider API

    U->>Gr: POST /chat
    Gr->>Gr: resolve_entities
    Gr->>LC: llm_client.generate_json(prompt)
    LC->>LM: generate_json('entity_resolution', prompt)
    LM->>MR: resolve_chain('entity_resolution')
    MR-->>LM: [(gemini, adapter)]
    LM->>Ad: adapter.generate(json_mode=True)
    Ad->>Pr: API call
    Pr-->>Ad: JSON text
    Ad-->>LM: LLMResponse
    LM-->>LC: parsed dict
    LC-->>Gr: entities

    Gr->>Gr: agent_decide
    Gr->>LC: llm_client.generate('agent_decide', messages, tools)
    LC->>LM: generate('agent_decide', ...)
    LM->>MR: resolve_chain('agent_decide')
    MR-->>LM: [(groq, adapter), (gemini, fallback)]
    LM->>Ad: primary.generate(tools=...)
    Ad->>Pr: API call
    Pr-->>Ad: AIMessage + tool_calls
    Ad-->>LM: LLMResponse(tool_calls=[...])
    LM-->>LC: LLMResponse
    LC-->>Gr: AIMessage

    alt primary fails
        LM->>Ad: fallback.generate(...)
        Ad->>Pr: API call
        Pr-->>Ad: response
        Ad-->>LM: LLMResponse
    end

    Gr->>Gr: execute_tools
    Gr->>Gr: synthesize_reply
    Gr->>LC: llm_client.generate('synthesize', messages)
    LC->>LM: generate('synthesize', ...)
    LM->>Ad: adapter.generate(...)
    Ad->>Pr: API call
    Pr-->>Ad: text
    Ad-->>LM: LLMResponse
    LM-->>LC: LLMResponse
    LC-->>Gr: reply text
```

## Registry / Fallback Chain

```mermaid
flowchart LR
    A[LLM_TASKS JSON] --> B(ModelRegistry)
    B --> C{task}
    C --> D[agent_decide]
    C --> E[synthesize]
    C --> F[entity_resolution]
    C --> G[lead_intent]
    C --> H[embedding]
    D --> I[primary: groq llama-3.3-70b]
    I --> J[fallback: gemini-2.5-flash]
    E --> K[primary: groq llama-3.3-70b]
    K --> L[fallback: gemini-2.5-flash]
    F --> M[primary: gemini-2.5-flash]
    G --> N[primary: gemini-2.5-flash]
    H --> O[primary: gemini text-embedding-004]
```

## Key Design Decisions

1. **Adapter Protocol** — every provider implements `generate`, `stream`, `embed`, and `get_chat_model`.  Capabilities are declared as flags so the registry can skip unsuitable providers.
2. **Task Registry** — tasks (agent_decide, synthesize, entity_resolution, lead_intent, embedding) are configured independently.  Each task has its own provider/model and optional fallback chain.
3. **Fallback Chain** — `LLMManager._execute_with_fallbacks()` retries each provider up to 3× with exponential backoff, then moves to the next configured fallback.
4. **LangGraph Integration** — graph nodes call the unified `generate()` interface and convert the normalized `LLMResponse` back to LangChain `AIMessage` objects so the rest of the LangGraph machinery (ToolNode, add_messages) works unchanged.
5. **Backward Compatibility** — `agent/llm_client.py` keeps the same public methods (`generate_text`, `generate_json`, `chat_model`, `enabled`) so existing callers and tests keep working.
