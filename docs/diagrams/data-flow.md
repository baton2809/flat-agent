# Data Flow Diagram — FlatAgent

Как данные проходят через систему, что хранится, что логируется.

```mermaid
flowchart LR
    subgraph INPUT["Входные данные"]
        USER_MSG["Сообщение пользователя\n(text)"]
        USER_CSV["CSV файл\n(прайс-лист застройщика)"]
        USER_ID["user_id\n(Telegram chat_id)"]
    end

    subgraph PROCESSING["Обработка (LangGraph)"]
        direction TB
        ROUTER_P["router_node\n[Классификация намерения]"]
        MEM_P["memory_extraction_node\n[Извлечение фактов]"]
        PROC_P["processing node\n[mortgage|compare|search|chat]"]
    end

    subgraph LLM_CALLS["LLM вызовы (GigaChat)"]
        LLM_ROUTE["Роутер:\nRouteDecision\ntemp=0.0\nfunction calling"]
        LLM_MEM["Memory:\nФакт или 'нет'\ntemp не задан"]
        LLM_GEN["Generation:\nОтвет пользователю\ntemp=0.3"]
    end

    subgraph EXTERNAL["Внешние данные"]
        CBR_DATA["ЦБ РФ:\nКлючевая ставка %\nКурсы USD/EUR/CNY"]
        DDG_DATA["DuckDuckGo:\nТоп-5 объявлений\nи новостей"]
    end

    subgraph STORAGE["Хранилище (SQLite: checkpoints.db)"]
        CHECKPOINTS["checkpoints\n(LangGraph SqliteSaver)\nВся история диалога\nper thread_id=user_id"]
        USER_MEMORY["user_memory\n(user_id, fact)\nБюджет, имя, предпочтения\nПерсистентно между сессиями"]
        CBR_CACHE["Process-level cache\n_rate_cache (TTL 1ч)\n_cbr_cache (TTL 1ч)\nВ памяти процесса"]
    end

    subgraph LOGS["Логи (logs/*.log)"]
        LOG_ROUTE["INFO: routing to: mortgage_node\n[router.py]"]
        LOG_TOOL["INFO: tool call cbr_tool/search_tool\n+ params + status\n[cbr_tool.py, search_tool.py]"]
        LOG_MEM["INFO: stored fact for user X\n[memory.py]"]
        LOG_REQ["INFO: request/response\nuser_id + preview 100 chars\n[routes.py, bot.py]"]
        LOG_WARN["WARN: LLM fallback activated\n[llm_wrapper.py, router.py]"]
        LOG_ERR["ERROR: exception + stack trace\n[all nodes/tools]"]
        LOG_DEBUG["DEBUG: full prompts, raw API responses\n[llm_wrapper.py — dev only]"]
    end

    subgraph NOT_LOGGED["НЕ логируется"]
        NL1["Полные ответы GigaChat"]
        NL2["Содержимое user_memory"]
        NL3["Credentials / токены"]
    end

    subgraph OUTPUT["Выходные данные"]
        TG_ANSWER["Telegram reply_text\n(Markdown → fallback plain)"]
        JSON_ANSWER["JSON ChatResponse\n{response: str}"]
        TG_PHOTO["Telegram reply_photo\n(CSV chart PNG)"]
    end

    %% Input flow
    USER_MSG --> ROUTER_P
    USER_ID --> MEM_P
    USER_MSG --> MEM_P
    USER_CSV --> PROC_P

    %% Processing flow
    ROUTER_P --> LLM_ROUTE
    ROUTER_P --> MEM_P
    MEM_P --> LLM_MEM
    MEM_P --> PROC_P
    PROC_P --> LLM_GEN

    %% External data flow
    PROC_P --> CBR_DATA
    PROC_P --> DDG_DATA
    CBR_DATA --> CBR_CACHE
    CBR_CACHE --> PROC_P

    %% Storage writes
    ROUTER_P -.->|read/write| CHECKPOINTS
    MEM_P -.->|INSERT OR IGNORE| USER_MEMORY
    PROC_P -.->|read/write| CHECKPOINTS
    PROC_P -.->|read| USER_MEMORY

    %% Logging
    ROUTER_P --> LOG_ROUTE
    PROC_P --> LOG_TOOL
    MEM_P --> LOG_MEM
    PROC_P --> LOG_REQ
    LLM_GEN --> LOG_WARN
    PROC_P --> LOG_ERR
    LLM_GEN --> LOG_DEBUG

    %% Output
    PROC_P --> TG_ANSWER
    PROC_P --> JSON_ANSWER
    PROC_P --> TG_PHOTO
```

## Детализация: что хранится

### SQLite: checkpoints (LangGraph)

```
thread_id = user_id (Telegram chat_id)
    └── checkpoint_id (UUID)
        └── messages: [HumanMessage, AIMessage, ...]
        └── route: str
        └── user_id: str

Retention: keep_per_thread=5 (cleanup_old_checkpoints)
Size target: ≤100 KB per user
WAL mode: да
```

### SQLite: user_memory

```
user_id TEXT  ← Telegram числовой ID (не имя пользователя)
fact    TEXT  ← "Пользователь <факт>" (одно предложение)
UNIQUE(user_id, fact)  ← дедупликация

Примеры фактов:
- "Пользователя зовут Алексей"
- "Бюджет пользователя: 8 млн"
- "Пользователь упомянул семью: жена и двое детей"
- "Пользователь ищет квартиру в Митино"

Удаление: /forget или /start → DELETE WHERE user_id = ?
```

### Process-level cache (не персистируется)

```
_rate_cache: ("Ключевая ставка ЦБ РФ: 21.0% (с 25.10.2024)", timestamp)
_cbr_cache: {"2024-10-25": ("Курсы валют...", timestamp)}
_llm_instance: GigaChatWrapper singleton
_client: GigaChat SDK client singleton
```

## Детализация: что логируется vs что нет

| Данные | Логируется | Уровень | Причина |
|---|---|---|---|
| user_id + routing decision | Да | INFO | Диагностика роутинга |
| Имя инструмента + параметры | Да | INFO | Аудит tool calls |
| Статус вызова LLM (успех/ошибка) | Да | INFO/ERROR | Мониторинг доступности |
| Количество токенов GigaChat | Нет (TODO) | — | Контроль бюджета |
| Preview ответа (100 символов) | Да | INFO | Базовая диагностика |
| Полный ответ GigaChat | Нет | — | Приватность |
| Содержимое user_memory | Нет | — | Персональные данные |
| Credentials, токены | Нет | — | Безопасность |
| Full prompts (raw) | Только DEBUG | DEBUG | Dev-only |
| HTTP latency per node | Нет (TODO) | — | Нужен для SLO мониторинга |
| Error stack traces | Да | ERROR | Отладка |
| Нестандартно длинные сообщения >2000 | Да | WARN | Potential injection detection |

## Data Sensitivity Classification

| Тип данных | Класс чувствительности | Хранение | Передача 3-м лицам |
|---|---|---|---|
| Telegram user_id (числовой) | Публичный идентификатор | SQLite local | Нет |
| Факты из диалога (имя, бюджет) | Персональные данные | SQLite local | Нет |
| Тексты сообщений | Персональные данные | SQLite (checkpoints) | GigaChat API |
| CSV данные застройщика | Пользовательский контент | Temp файл (удаляется) | Нет |
| Ключевая ставка ЦБ | Публичные данные | Process cache | Нет |
| Результаты поиска DDG | Публичные данные | Не хранятся | Нет |
