# C4 Component Diagram — LangGraph Agent Core

Внутреннее устройство ядра агента.

> 7 смысловых компонентов. Задача — показать интерфейсы между блоками, а не перечислить файлы.

```mermaid
flowchart TD
    subgraph EXT["Внешние системы"]
        direction LR
        GC["GigaChat API"]
        CBR_E["ЦБ РФ API"]
        DDG_E["DuckDuckGo"]
        DB_E[("SQLite WAL")]
    end

    subgraph AGENT["LangGraph Agent Core"]
        direction TB

        ORCH_C["Orchestrator\ngraph.py + state.py\n─────────────────\nStateGraph · AgentState\nSqliteSaver · tenacity retry\ncircuit breakers"]

        ROUTER_C["Router\nnodes/router.py\n─────────────────\nFast-path: 20+ паттернов, 0 LLM, ~40%\nLLM-path: RouteDecision temp=0.0\nFallback: route='chat'"]

        MEM_C["Memory\nmemory.py + memory_extraction.py\n─────────────────\nExtraction: LLM → regex fallback\nStorage: SQLite UNIQUE facts\nCleanup: scheduled 24h"]

        PROC_C["Processing Nodes\nmortgage · compare · search · chat\n─────────────────\nmortgage: regex+CBR+аннуитет\ncompare/search/chat: LLM temp=0.3\nВсе: sliding window messages-10"]

        LLM_C["LLM Gateway\nllm_wrapper.py + direct_llm_call.py\n─────────────────\nFunction calling (structured output)\nPlain generation\nKeyword fallback · CB: 5/60s→30s"]

        TOOLS_C["Tool Layer\ncbr · mortgage_calc · search · csv\n─────────────────\ncbr: TTL-кэш 1ч + stale fallback\nmortgage: max 100М/30лет\nDDG: 12s + circuit breaker\ncsv: OLS + Plotly, max 10К строк"]

        ERR_C["Error Handling\nerror_handler.py + exceptions.py\n─────────────────\nLLMError · ExternalAPIError\nValidationError\nnode_error_response → AIMessage"]
    end

    ORCH_C -->|"entry point"| ROUTER_C
    ORCH_C -->|"after router\n(все маршруты)"| MEM_C
    ORCH_C -->|"dispatch по route"| PROC_C
    ORCH_C <-->|"SqliteSaver\ncheckpoints"| DB_E

    ROUTER_C -->|"RouteDecision\nfunction calling"| LLM_C

    MEM_C -->|"fact extraction\nplain text"| LLM_C
    MEM_C <-->|"user_memory CRUD\nthread-local"| DB_E

    PROC_C -->|"generation\ntemp=0.3"| LLM_C
    PROC_C -->|"cbr rate · calc\nDDG · csv"| TOOLS_C
    PROC_C -->|"при ошибке"| ERR_C

    LLM_C <-->|"function calling\nchat completions"| GC
    TOOLS_C <-->|"GET ставка + курсы\nTTL-cached"| CBR_E
    TOOLS_C <-->|"text search ru-ru\ncircuit-breaker"| DDG_E
```

## Интерфейсы между компонентами

| От | К | Интерфейс | Fallback |
|---|---|---|---|
| Orchestrator | Router | `router_node(state) → state` | route="chat" |
| Orchestrator | Memory | `memory_extraction_node(state) → state` | silent skip |
| Orchestrator | Processing | `*_node(state) → state` | `node_error_response()` |
| Router | LLM Gateway | `llm_call_direct(dialog, RouteDecision, temp=0)` | route="chat" |
| Processing | LLM Gateway | `llm_call_direct(dialog, temp=0.3)` | keyword/template |
| Processing | Tool Layer | `get_current_rate()`, `calculate_mortgage()`, `search_real_estate()` | ExternalAPIError |
| LLM Gateway | GigaChat API | HTTPS OAuth2, function calling / plain | keyword fallback |
| Tool Layer | CBR API | HTTPS 10s timeout | stale cache |
| Tool Layer | DDG | HTTPS 12s timeout, circuit breaker | ExternalAPIError |
