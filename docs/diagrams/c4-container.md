# C4 Container Diagram — FlatAgent

Frontend / backend, orchestrator, retriever, tool layer, storage, observability.

```mermaid
C4Container
    title FlatAgent — Container Diagram

    Person(user, "Пользователь")

    System_Ext(telegram_api, "Telegram Bot API")
    System_Ext(gigachat_api, "GigaChat API")
    System_Ext(cbr_api, "ЦБ РФ API")
    System_Ext(ddg_api, "DuckDuckGo")

    System_Boundary(flatagent, "FlatAgent") {

        Container(tg_bot, "Telegram Bot", "Python / python-telegram-bot", "Обрабатывает входящие сообщения и документы. /start, /forget, text, CSV. Polling или webhook режим.")

        Container(fastapi, "FastAPI App", "Python / FastAPI + uvicorn", "REST API: GET /health, POST /chat. Принимает запросы от Telegram webhook и внешних клиентов.")

        Container(langgraph, "LangGraph Agent", "Python / LangGraph StateGraph", "Оркестрирует выполнение запроса через граф узлов: router → memory_extraction → [mortgage|compare|search|chat] → END")

        Container(router, "Router Node", "Python / GigaChat function calling", "Fast-path heuristics (0 LLM) + structured LLM call (RouteDecision). Temperature=0.0.")

        Container(nodes, "Processing Nodes", "Python", "mortgage_node: regex + formula\ncompare_node: LLM + fallback templates\nsearch_node: DDG + LLM format\nchat_node: LLM + memory context + CBR fast-path")

        Container(memory_node, "Memory Extraction", "Python / LLM + regex", "Извлекает факты о пользователе из каждого сообщения. LLM-primary, regex-fallback.")

        Container(tools, "Tool Layer", "Python", "cbr_tool: HTTP→ЦБ РФ, TTL-кэш\nmortgage_calc: аннуитетная формула\nsearch_tool: DDG + relevance filter\ncsv_analysis: OLS regression + Plotly")

        ContainerDb(sqlite, "SQLite", "SQLite WAL", "checkpoints: LangGraph история диалога\nuser_memory: долгосрочные факты о пользователе")

        Container(llm_wrapper, "GigaChatWrapper", "Python / BaseChatModel", "Обёртка LangChain. Keyword-based fallback при недоступности GigaChat.")

        Container(direct_llm, "DirectLLMCall", "Python / GigaChat SDK", "Прямые вызовы GigaChat: function calling для структурированного вывода (router, memory), plain text для generation (compare, search, chat).")
    }

    Rel(user, tg_bot, "Telegram messages / documents", "Telegram protocol")
    Rel(user, fastapi, "POST /chat, GET /health", "HTTPS JSON")

    Rel(tg_bot, langgraph, "invoke(state, config)", "Python call")
    Rel(fastapi, langgraph, "run_in_executor → invoke()", "Python async + thread pool")

    Rel(langgraph, router, "entry point", "LangGraph node")
    Rel(router, direct_llm, "classify intent (function calling)", "Python call")
    Rel(langgraph, memory_node, "after router", "LangGraph edge")
    Rel(memory_node, direct_llm, "extract facts", "Python call")
    Rel(langgraph, nodes, "dispatch by route", "LangGraph conditional edge")

    Rel(nodes, tools, "cbr_tool, mortgage_calc, search_tool, csv_analysis", "Python call")
    Rel(nodes, llm_wrapper, "compare, chat responses", "LangChain invoke()")
    Rel(nodes, direct_llm, "search format, compare", "Python call")

    Rel(tools, cbr_api, "GET key rate + currencies", "HTTPS")
    Rel(tools, ddg_api, "text search ru-ru", "HTTPS")

    Rel(direct_llm, gigachat_api, "chat completions + function calling", "HTTPS / OAuth2")
    Rel(llm_wrapper, gigachat_api, "chat completions", "HTTPS / OAuth2")

    Rel(langgraph, sqlite, "read/write checkpoints (SqliteSaver)", "SQLite WAL")
    Rel(memory_node, sqlite, "INSERT OR IGNORE user_memory", "SQLite WAL")
    Rel(nodes, sqlite, "get_memory_context(), get_user_name()", "SQLite WAL")

    Rel(tg_bot, telegram_api, "reply_text, reply_photo", "HTTPS")
    Rel(fastapi, telegram_api, "webhook response", "HTTPS")
```

## Описание контейнеров

| Контейнер | Технология | Роль |
|---|---|---|
| Telegram Bot | python-telegram-bot | Интерфейс пользователя (основной), обработка документов |
| FastAPI App | FastAPI + uvicorn | REST API, Telegram webhook endpoint, healthcheck |
| LangGraph Agent | LangGraph StateGraph | Оркестратор: граф переходов, state management, checkpointing |
| Router Node | GigaChat function calling | Intent classification, 0 LLM для fast-path |
| Memory Extraction | LLM + regex | Cross-session facts extraction per user |
| Processing Nodes | Python + LLM | Domain logic: ипотека, сравнение, поиск, консультация |
| Tool Layer | Python + httpx + ddgs | Внешние данные: ЦБ РФ, поиск, расчёты, CSV |
| GigaChatWrapper | LangChain BaseChatModel | LangChain-compatible LLM с keyword fallback |
| DirectLLMCall | GigaChat SDK | Structured output (function calling), plain generation |
| SQLite | SQLite WAL | Persistence: checkpoints + user memory |
