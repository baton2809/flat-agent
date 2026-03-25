# C4 Container Diagram — FlatAgent

Frontend / backend, orchestrator, retriever, tool layer, storage, observability.

```mermaid
flowchart TD
    USER["Пользователь\nПокупатель квартиры"]

    subgraph EXT_TOP["Внешние сервисы"]
        direction LR
        TG_API["Telegram Bot API"]
        GC_API["GigaChat API\nLLM: routing · generation · extraction"]
        CBR_API["ЦБ РФ API\nКлючевая ставка, курсы"]
        DDG_API["DuckDuckGo\nПоиск объявлений"]
    end

    subgraph FLAT["FlatAgent"]
        direction TB

        FE["Frontend Layer\n─────────────────────\nTelegram Bot + FastAPI\nRate limiting · Webhook HMAC auth · API key"]

        ORCH["Orchestrator\n─────────────────────\nLangGraph StateGraph\nrouter → memory → nodes → END\nTenacity retry · Circuit breakers · SqliteSaver"]

        LLM["LLM Gateway\n─────────────────────\nGigaChat SDK + LangChain\nFunction calling (structured output)\nPlain generation · Keyword fallback"]

        TOOLS["Tool Layer\n─────────────────────\ncbr_tool: TTL-кэш 1ч + stale fallback\nmortgage_calc: аннуитетная формула\nsearch_tool: DDG 12s + circuit breaker\ncsv_analysis: OLS + Plotly"]

        DB[("Storage\n─────────────────────\nSQLite WAL\ncheckpoints: история диалога\nuser_memory: факты о пользователе")]

        OBS["Observability\n─────────────────────\nJSON-логи INFO/WARN/ERROR\nPrometheus: /metrics\nHealth check: /api/v1/health"]
    end

    USER -->|"Telegram сообщения / CSV"| FE
    USER -->|"HTTPS POST /chat"| FE

    FE <-->|"webhook + replies"| TG_API
    FE -->|"invoke AgentState\nThreadPoolExecutor max=10"| ORCH

    ORCH -->|"routing + extraction\n+ generation"| LLM
    ORCH -->|"cbr · calc · search · csv"| TOOLS
    ORCH <-->|"checkpoints R/W\nuser_memory CRUD"| DB
    ORCH -->|"structured logs + metrics"| OBS
    FE -->|"rate limit events\nrequest latency"| OBS

    LLM <-->|"function calling\nchat completions\nHTTPS OAuth2"| GC_API
    TOOLS <-->|"GET ставка + курсы"| CBR_API
    TOOLS <-->|"text search ru-ru"| DDG_API
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
