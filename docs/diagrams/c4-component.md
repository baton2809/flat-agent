# C4 Component Diagram — LangGraph Agent Core

Внутреннее устройство ядра агента.

> Укрупнённая архитектурная схема (7 смысловых компонентов). Задача — объяснить интерфейсы между блоками, а не перечислить файлы.

```mermaid
C4Component
    title LangGraph Agent — Component Diagram (архитектурный уровень)

    System_Ext(gigachat_api, "GigaChat API")
    System_Ext(cbr_api, "ЦБ РФ API")
    System_Ext(ddg_api, "DuckDuckGo")
    ContainerDb(sqlite, "SQLite WAL", "checkpoints + user_memory")

    Container_Boundary(agent_core, "LangGraph Agent Core") {

        Component(orchestrator, "Orchestrator", "graph.py + state.py", "StateGraph: router→memory→[mortgage|compare|search|chat]→END.\nAgentState: {messages, route, user_id}.\nSqliteSaver checkpoints. Tenacity retry. Circuit breakers.")

        Component(router, "Router", "nodes/router.py", "Intent classification.\nFast-path: 20+ heuristics, 0 LLM, ~40% запросов.\nLLM-path: RouteDecision (function calling, temp=0.0).\nFallback: route='chat' при любой ошибке.")

        Component(memory, "Memory", "memory.py + memory_extraction.py", "Extraction: LLM-primary → regex fallback.\nStorage: SQLite user_memory (UNIQUE facts).\nRetrieval: get_memory_context() → system prompt injection.\nCleanup: scheduled 24h + keep_per_thread=5.")

        Component(processing, "Processing Nodes", "nodes/mortgage|compare|search|chat.py", "mortgage: regex + CBR + аннуитетная формула (LLM не вычисляет).\ncompare: LLM (temp=0.3) + шаблонный fallback.\nsearch: DDG + relevance filter + LLM format.\nchat: CBR fast-path + memory ctx + LLM (temp=0.3).\nВсе узлы: sliding window messages[-10:].")

        Component(llm_gateway, "LLM Gateway", "llm_wrapper.py + direct_llm_call.py", "Единая точка вызова GigaChat.\nStructured: function calling → RouteDecision/FactExtraction.\nPlain: generation (compare, search, chat).\nFallback: keyword-based ответы при недоступности.\nCircuit breaker (5 ошибок/60с → open 30с).")

        Component(tools, "Tool Layer", "tools/cbr|mortgage_calc|search|csv.py", "cbr_tool: TTL-кэш 1ч + stale fallback + circuit breaker.\nmortgage_calc: аннуитет + валидация (max 100М/30лет).\nsearch_tool: DDG 12с timeout + circuit breaker + relevance filter.\ncsv_analysis: OLS регрессия + выбросы + Plotly (max 10К строк).")

        Component(error_handling, "Error Handling", "error_handler.py + exceptions.py", "Иерархия: FlatAgentError → LLMError | ExternalAPIError | ValidationError.\nnode_error_response(): exception → user-facing AIMessage.\nВсе nodes оборачивают logic в try/except → error_handler.")
    }

    Rel(orchestrator, router, "entry point → route decision", "LangGraph node")
    Rel(orchestrator, memory, "after router: extract + store facts", "LangGraph edge")
    Rel(orchestrator, processing, "conditional dispatch by route", "LangGraph conditional edge")
    Rel(orchestrator, sqlite, "checkpoints read/write", "SqliteSaver / WAL")

    Rel(router, llm_gateway, "RouteDecision (function calling)", "structured output")
    Rel(memory, llm_gateway, "fact extraction (plain text)", "plain generation")
    Rel(memory, sqlite, "user_memory CRUD (thread-local)", "SQLite WAL")

    Rel(processing, llm_gateway, "compare/search/chat generation", "plain generation")
    Rel(processing, tools, "cbr rate, mortgage calc, DDG search, csv", "Python call")
    Rel(processing, error_handling, "node_error_response(exc, node)", "Python")

    Rel(llm_gateway, gigachat_api, "function calling + chat completions", "HTTPS / OAuth2")
    Rel(tools, cbr_api, "GET key rate + currencies", "HTTPS / TTL-cached")
    Rel(tools, ddg_api, "text search ru-ru", "HTTPS / circuit-breaker")
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
