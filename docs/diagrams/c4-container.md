# C4 Container Diagram — FlatAgent

Frontend / backend, orchestrator, retriever, tool layer, storage, observability.

```mermaid
C4Container
    title FlatAgent — Container Diagram

    Person(user, "Пользователь", "Покупатель квартиры")

    System_Ext(telegram_api, "Telegram Bot API")
    System_Ext(gigachat_api, "GigaChat API", "LLM: routing, generation, extraction")
    System_Ext(cbr_api, "ЦБ РФ API", "Ключевая ставка, курсы валют")
    System_Ext(ddg_api, "DuckDuckGo", "Поиск объявлений недвижимости")

    System_Boundary(flatagent, "FlatAgent") {

        Container(frontend, "Frontend Layer", "Telegram Bot + FastAPI", "Точки входа: Telegram polling/webhook, REST /chat. Rate limiting, webhook secret validation, API key auth.")

        Container(orchestrator, "Orchestrator", "LangGraph StateGraph", "Граф: router → memory_extraction → [mortgage|compare|search|chat] → END. Tenacity retry, circuit breakers. SqliteSaver checkpointing.")

        Container(llm_gateway, "LLM Gateway", "GigaChat SDK + LangChain", "Единая точка доступа к GigaChat. Function calling (structured output), plain generation, keyword fallback при недоступности.")

        Container(tool_layer, "Tool Layer", "Python + httpx + ddgs", "cbr_tool: ЦБ РФ + TTL-кэш + stale fallback\nmortgage_calc: аннуитетная формула\nsearch_tool: DDG + circuit breaker (12s timeout)\ncsv_analysis: OLS + Plotly")

        ContainerDb(storage, "Storage", "SQLite WAL", "checkpoints: история диалога (per user, keep=5)\nuser_memory: факты о пользователе (UNIQUE)")

        Container(observability, "Observability", "Python logging + Prometheus", "JSON-логи (INFO/WARN/ERROR)\nPrometheus метрики: request_total, llm_calls_total, fallback_total, db_size_bytes\nGET /metrics, GET /api/v1/health (sqlite+gigachat+cbr_cache)")
    }

    Rel(user, frontend, "Telegram / HTTPS POST /chat", "Telegram / JSON")
    Rel(frontend, telegram_api, "webhook setup + replies", "HTTPS")

    Rel(frontend, orchestrator, "invoke(AgentState, config)", "Python / ThreadPoolExecutor")

    Rel(orchestrator, llm_gateway, "routing + extraction + generation", "Python")
    Rel(orchestrator, tool_layer, "cbr, calc, search, csv", "Python")
    Rel(orchestrator, storage, "checkpoints R/W, user_memory CRUD", "SQLite WAL")

    Rel(llm_gateway, gigachat_api, "function calling + chat completions", "HTTPS / OAuth2")
    Rel(tool_layer, cbr_api, "GET key rate + currencies", "HTTPS")
    Rel(tool_layer, ddg_api, "text search ru-ru", "HTTPS")

    Rel(orchestrator, observability, "structured logs + metrics", "Python")
    Rel(frontend, observability, "rate limit hits, request latency", "Python")
```

## Описание контейнеров

| Контейнер | Технология | Роль | Fallback |
|---|---|---|---|
| Frontend Layer | Telegram Bot + FastAPI | Точки входа, rate limiting, auth | Polling ↔ webhook |
| Orchestrator | LangGraph StateGraph | Граф переходов, retry, checkpointing | route="chat" |
| LLM Gateway | GigaChat SDK | Structured output + generation | keyword fallback |
| Tool Layer | Python + httpx + ddgs | ЦБ РФ, поиск, расчёт, CSV | TTL-кэш, circuit breaker |
| Storage | SQLite WAL | Checkpoints + user memory | Критическая зависимость |
| Observability | logging + Prometheus | Логи, метрики, health check | — |
