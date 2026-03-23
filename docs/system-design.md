# System Design: FlatAgent

> Трек: **Агентский + Инфраструктурный** (оба трека одновременно).
> Агентский акцент: качество LLM-взаимодействий, контроль вывода, защиты и fallback.
> Инфраструктурный акцент: надёжность, мониторинг, защиты при недоступности внешних API.

---

## 1. Ключевые архитектурные решения

| Решение | Выбор | Обоснование |
|---|---|---|
| Оркестратор | LangGraph StateGraph | Явный граф переходов, детерминированный control flow, SQLite checkpointing |
| LLM | GigaChat (Sber) | Российская юрисдикция, нет блокировок, поддержка function calling |
| Роутинг | Fast-path heuristics → structured LLM call | Детерминированные правила экономят 1 LLM-вызов на ~40% запросов |
| Структурированный вывод роутера | GigaChat function calling (`RouteDecision`) | Роутер не может вернуть free-text; невалидный маршрут физически невозможен |
| Ипотечный расчёт | Детерминированная аннуитетная формула | LLM не участвует в вычислениях → расхождение ≤1% гарантировано |
| Персистентность | SQLite WAL mode | Без внешних зависимостей, достаточно для PoC, thread-safe через WAL |
| Долгосрочная память | LLM extraction + regex fallback → `user_memory` | LLM как primary, regex как safety net при недоступности |
| Serving | FastAPI + Telegram bot (polling/webhook) | Единый Python-процесс, минимальная инфраструктура |
| Eval | Offline routing eval (20 labeled cases) | Измеримое качество роутинга до деплоя, цель ≥90% |
| Fallback при падении GigaChat | Keyword-based шаблонные ответы | Бот отвечает даже без LLM, пользователь не видит 500 |

---

## 2. Список модулей и их роли

```
sberuniversity/
├── config.py                    # Settings (pydantic-settings), LLM singleton (lru_cache)
├── main.py                      # FastAPI app + lifespan + Telegram webhook endpoint
├── agent/
│   ├── graph.py                 # Сборка LangGraph StateGraph, SqliteSaver checkpointer
│   ├── state.py                 # AgentState TypedDict: messages, route, user_id
│   ├── llm_wrapper.py           # GigaChatWrapper (BaseChatModel) + keyword fallback
│   ├── direct_llm_call.py       # GigaChat SDK: function calling + plain text calls
│   ├── memory.py                # LongTermMemory: SQLite user_memory + LLM/regex extraction
│   ├── error_handler.py         # node_error_response(): exception → user-facing AIMessage
│   ├── exceptions.py            # FlatAgentError / LLMError / ExternalAPIError / ValidationError
│   └── nodes/
│       ├── router.py            # Fast-path heuristics → LLM RouteDecision (function calling)
│       ├── mortgage.py          # Regex parsing + CBR rate lookup + formula
│       ├── compare.py           # LLM сравнение + шаблонные fallback по категориям
│       ├── search.py            # DuckDuckGo + relevance filter + LLM форматирование
│       ├── chat.py              # CBR fast-path + memory context + LLM consultation
│       └── memory_extraction.py # Thin wrapper → memory_manager.extract_and_store_facts()
├── agent/tools/
│   ├── cbr_tool.py              # ЦБ РФ: ключевая ставка + курсы валют (TTL-кэш 1ч)
│   ├── mortgage_calc.py         # Аннуитетная формула с валидацией параметров
│   ├── search_tool.py           # DDG: query enhancement + relevance filter + LLM format
│   └── csv_analysis.py          # OLS-регрессия + Plotly для прайс-листов застройщика
├── api/
│   └── routes.py                # FastAPI: GET /health, POST /chat
├── telegram_bot/
│   └── bot.py                   # Telegram: /start, /forget, text, document (CSV)
└── eval/
    ├── run_eval.py              # Offline routing accuracy evaluation + tabulate report
    └── test_cases.json          # 20 labeled тест-кейсов (mortgage/compare/search/chat)
```

---

## 3. Основной workflow выполнения задачи

```
Пользователь → Telegram message / POST /chat
        │
        ▼
[router_node]
  ├─ Fast-path (детерминированный, 0 LLM-вызовов, ~40% запросов):
  │    ├─ Приветствия, "что ты умеешь", "расскажи о себе" → chat
  │    ├─ "ключевая ставка", "курс доллара/евро/юаня" → chat (CBR path)
  │    ├─ "найди", "новостройки в...", price dynamics → search
  │    └─ Mortgage follow-up (предыдущий AI-ответ содержал расчёт) → mortgage
  └─ LLM-path (GigaChat function calling, temperature=0.0):
       ├─ RouteDecision{route: mortgage|compare|search|chat, reasoning}
       └─ Fallback при любой ошибке: route = "chat"
        │
        ▼
[memory_extraction_node]  ← выполняется для ВСЕХ маршрутов
  ├─ LLM: "содержит ли сообщение факт? → Пользователь <факт>"
  ├─ Fallback regex: имя, бюджет (млн), семья, работа
  └─ SQLite: INSERT OR IGNORE → user_memory(user_id, fact)
        │
        ▼ (dispatch по state.route)
  ┌─────┬──────────┬────────┬──────┐
[mortgage] [compare] [search] [chat]
  │          │          │       │
  │          │          │       ├─ CBR fast-path если запрос о ставке/курсе
  │          │          │       ├─ memory_context injection в system prompt
  │          │          │       └─ LLM (temperature=0.3), sliding window 10 msg
  │          │          │
  │          │          ├─ enhance_query + DuckDuckGo (max 12 results)
  │          │          ├─ filter_relevant_results (whitelist + term score)
  │          │          └─ LLM format (temperature=0.3) + fallback text
  │          │
  │          └─ LLM сравнение (temperature=0.3)
  │               └─ Fallback шаблоны: первичка/вторичка, центр/спальный район
  │
  ├─ regex parsing (сумма, ставка, срок)
  ├─ CBR rate API (если ставка не указана явно, +2% спред)
  ├─ Аннуитетная формула (детерминировано)
  └─ Сканирование истории сообщений для заполнения пропущенных параметров
        │
        ▼
[END] → AIMessage → Telegram reply (parse_mode=Markdown, split >4096) / JSON response
```

**LLM-вызовов на запрос:**
| Маршрут | Роутер | Memory | Processing | Итого |
|---|---|---|---|---|
| Fast-path (chat/search/mortgage) | 0 | 1 | 0–1 | 1–2 |
| LLM-path | 1 | 1 | 1 | 3 |
| Mortgage (без LLM в processing) | 0–1 | 1 | 0 | 1–2 |

---

## 4. State / Memory / Context Handling

### 4.1 Краткосрочная память (session)

| Параметр | Значение |
|---|---|
| Хранилище | SQLite, `checkpoints` table (LangGraph SqliteSaver) |
| SQLite режим | WAL (Write-Ahead Logging) — читатели не блокируют писателей |
| State schema | `AgentState = {messages: Annotated[list, add_messages], route: str, user_id: str}` |
| Reducer | `add_messages` — история аккумулируется, не перезаписывается |
| thread_id | `user_id` = Telegram `chat_id` или API `user_id` |
| Sliding window | chat_node передаёт `messages[-10:]` в LLM (только последние 10 сообщений) |
| Cleanup | `cleanup_old_checkpoints(keep_per_thread=5)` + VACUUM + WAL checkpoint |
| Размер | ≤100 KB на пользователя |

### 4.2 Долгосрочная память (cross-session)

| Параметр | Значение |
|---|---|
| Хранилище | SQLite, `user_memory(user_id TEXT, fact TEXT, UNIQUE)` |
| Индекс | `idx_user_memory_user_id` |
| Формат факта | `"Пользователь <факт>"` — одно предложение |
| Извлечение (primary) | LLM: system prompt "Определи факт или ответь 'нет'" |
| Извлечение (fallback) | Regex паттерны: имя, бюджет (млн), семья, работа |
| Дедупликация | `INSERT OR IGNORE` + `UNIQUE(user_id, fact)` constraint |
| Инъекция в промпт | `"Факты о пользователе:\n- ..."` в system prompt chat_node |
| Удаление | `/forget` команда или `/start` → `DELETE WHERE user_id = ?` |
| 152-ФЗ | Только числовой Telegram ID; нет паспортных данных, СНИЛС, счетов |

### 4.3 Process-level cache (in-memory)

| Источник | Переменная | TTL | Thread-safety |
|---|---|---|---|
| ЦБ РФ ключевая ставка | `_rate_cache: (str, float)` | 3600 сек | `time.monotonic()` check |
| ЦБ РФ курсы валют | `_cbr_cache: {date: (str, float)}` | 3600 сек | `time.monotonic()` check |
| LLM (GigaChatWrapper) | `_llm_instance` | lifetime процесса | `lru_cache(maxsize=1)` |
| GigaChat direct client | `_client` | lifetime процесса | module-level singleton |

---

## 5. Retrieval-контур

FlatAgent использует **live web search** вместо RAG-вектора — данные рынка недвижимости слишком динамичны для статичного индекса.

```
search_node
    │
    ├─ enhance_real_estate_query(query)
    │    ├─ Добавляет "недвижимость купить" если нет real-estate терминов
    │    ├─ Раскрывает ЖК → "жилой комплекс" для лучшего поиска
    │    └─ Добавляет "названия список объектов" для запросов о ЖК
    │
    ├─ DuckDuckGo DDGS.text(region="ru-ru", max_results=12, safesearch="moderate")
    │    └─ Retry с timelimit="y" если первый запрос вернул 0 результатов
    │
    ├─ filter_relevant_results()
    │    ├─ Whitelist: cian.ru, avito.ru, domclick.ru, realty.yandex.ru, bn.ru...
    │    ├─ Term scoring: ≥2 real-estate термина из 20 → relevant
    │    ├─ Anti-spam: фильтр "ЖК РФ" (Жилищный Кодекс), SEO-лендинги
    │    └─ Graceful degradation: всё отфильтровано → top-3 raw results
    │
    └─ format_search_results() → LLM (temperature=0.3)
         ├─ System prompt: запрет _подчёркивания_, ### заголовков; требование конкретных объектов
         ├─ Validates: len(response) > 50 chars
         └─ Fallback: шаблонный нумерованный список из raw результатов

CSV-анализ (отдельный путь, документ из Telegram):
    ├─ OLS регрессия: цена ~ площадь (statsmodels)
    ├─ Выявление выбросов (±2σ от линии регрессии)
    └─ Plotly chart → PNG → Telegram reply_photo
```

**Ограничения retrieval:**
- Нет официального API ЦИАН/Авито (не в scope PoC)
- DuckDuckGo без API-ключа: возможен soft rate limit при высокой нагрузке
- Актуальность — зависит от индекса DDG (обычно 1–7 дней)

---

## 6. Tool / API интеграции

| Инструмент | Endpoint / SDK | Timeout | Retry | Fallback |
|---|---|---|---|---|
| GigaChat LLM | `gigachat` SDK, GIGACHAT_API_B2B | 30 сек | Нет (нужен) | Keyword-based шаблонные ответы |
| GigaChat function calling | `gigachat` SDK, `Function` + `FunctionCall` | 30 сек | Нет (нужен) | `route = "chat"` |
| ЦБ РФ ключевая ставка | `httpx GET cbr.ru/hd_base/KeyRate/` | 10 сек | Нет | TTL-кэш + ExternalAPIError |
| ЦБ РФ курсы валют | `httpx GET cbr.ru/scripts/XML_daily.asp` | 10 сек | Нет | ExternalAPIError → user message |
| DuckDuckGo | `DDGS().text()`, region=ru-ru | библ. default | 1 retry с timelimit | Пустой список → human fallback |
| Telegram Bot API | `python-telegram-bot` | framework | Нет | polling как fallback для webhook |
| SQLite | file `checkpoints.db`, WAL | N/A | N/A | Критическая зависимость |

---

## 7. [Агентский трек] Качество LLM, Fallback и Guardrails

### 7.1 Routing quality

| Механизм | Реализация | Гарантия |
|---|---|---|
| Structured output | Function calling → `RouteDecision{route, reasoning}` | Невалидный маршрут физически невозможен |
| Temperature=0 | `llm_call_direct(dialog, temperature=0.0)` | Детерминированный выбор |
| Validation после LLM | `if route not in (mortgage, compare, search, chat)` → "chat" | Double-check |
| Fast-path heuristics | ~20 детерминированных паттернов | 0 LLM-вызовов, ~40% запросов |
| Context-aware routing | `_is_mortgage_followup()` проверяет content предыдущего AI-сообщения | Нет ложных сравнений |
| Error fallback | `except Exception → route = "chat"` | Безопасный default |
| Eval coverage | 20 labeled cases, `eval/run_eval.py` | Измеримость: цель ≥90% |

### 7.2 Calculation accuracy

| Механизм | Реализация |
|---|---|
| Детерминированный расчёт | Аннуитетная формула в `mortgage_calc.py` — LLM не участвует |
| Input validation | `amount > 0`, `0 < rate ≤ 100`, `term_months > 0` → `ValidationError` |
| LLM только для форматирования | GigaChat получает готовые числа, форматирует текст |
| Context scan | Сканирование истории сообщений для заполнения пропущенных параметров |

### 7.3 Memory extraction quality

| Механизм | Реализация |
|---|---|
| LLM-primary | Prompt: "Пользователь <факт>" или "нет" — жёсткий output format |
| Regex fallback | Паттерны: имя, бюджет, семья, работа — работают без LLM |
| Дедупликация | `INSERT OR IGNORE` + `UNIQUE(user_id, fact)` |
| Name resolution | Regex в `get_user_name()` с несколькими паттернами ("зовут", "имя", "представился") |

### 7.4 Response quality

| Node | Temperature | Guardrail |
|---|---|---|
| router | 0.0 | Structured output (function calling) |
| memory_extraction | — | Через `extract_and_store_facts()` |
| mortgage | 0 (детерм.) | Нет LLM в вычислениях |
| compare | 0.3 | Fallback шаблоны по категориям (первичка/вторичка, центр/спальный) |
| search (format) | 0.3 | len > 50, fallback шаблон, обязательные ссылки на ЦИАН/Авито/ДомКлик |
| chat | 0.3 | Domain restriction ("только вопросы о недвижимости"), sliding window 10 msg |

### 7.5 Prompt Injection Guardrails

| Механизм | Описание |
|---|---|
| Role separation | `create_dialog(system_prompt, user_message)` — system vs user строго разделены |
| Tool results as data | DDG результаты и CSV передаются в user-часть контекста, не в system instructions |
| Node isolation | Каждый node получает только нужный контекст, не весь стек |
| No write tools | GigaChat не имеет инструментов для записи файлов, выполнения команд, HTTP-запросов |
| Domain restriction | chat_node system prompt: "отвечай ТОЛЬКО на вопросы о недвижимости" |
| Log anomalies | Сообщения >2000 символов логируются (governance.md) |

### 7.6 Failure Modes

| Сценарий | Детект | Поведение |
|---|---|---|
| GigaChat недоступен | `except Exception` в `_generate()` | Keyword fallback; бот работает |
| Function call не вернул structured | `finish_reason != "function_call"` | Text content → route="chat" |
| LLM вернул короткий ответ | `len(response) < 50` (search) / `< 100` (compare) | LLMError → fallback шаблон |
| ЦБ РФ недоступен | `except Exception` → `ExternalAPIError` | TTL-кэш (1ч) или user message |
| DDG недоступен | `except Exception` → `ExternalAPIError` | "Не удалось получить данные" |
| Невалидные параметры ипотеки | `ValidationError` | "Некорректные параметры. Проверьте значения" |
| Нерелевантный запрос | router → "chat" | Ответ в рамках домена недвижимости |
| Ответ >4096 символов | `len(text) > 4096` | Split на части по 4096 символов |
| Telegram Markdown fail | `except Exception` в `reply_text` | Retry без `parse_mode='Markdown'` |

---

## 8. [Инфраструктурный трек] Надёжность и мониторинг

### 8.1 Защиты при недоступности внешних API

```
GigaChat недоступен:
  GigaChatWrapper._generate() → except → _generate_fallback()
  → keyword-based ответ (mortgage/compare/search/chat topics)
  → бот не падает, пользователь получает осмысленный ответ

ЦБ РФ API недоступен:
  get_current_rate() → except ExternalAPIError
  → в mortgage_node: продолжение без CBR ставки (просит пользователя указать вручную)
  → в chat_node: user_message_for_error(ExternalAPIError) → "Не удалось получить данные"
  → при следующем запросе: TTL-кэш в течение 1 часа

DuckDuckGo недоступен:
  search_real_estate() → ExternalAPIError
  → search_node → node_error_response() → "Не удалось получить актуальные данные"

SQLite недоступен:
  Критическая зависимость — нет fallback. Нужен мониторинг.
```

### 8.2 Resource management

| Параметр | Значение | Механизм |
|---|---|---|
| SQLite WAL mode | `PRAGMA journal_mode=WAL` при инициализации | Параллельные reads без блокировки writes |
| Thread-local connections | `threading.local()` в `LongTermMemory` | Нет race conditions на соединениях |
| Checkpoint cleanup | `keep_per_thread=5` + VACUUM + WAL checkpoint truncate | Ограничение роста БД |
| CBR cache | `time.monotonic()` проверка (не `datetime`) | Монотонный, нет проблем DST |
| LLM singleton | `lru_cache(maxsize=1)` в `get_settings()` | Один инстанс GigaChat на процесс |
| CSV temp files | `tempfile.NamedTemporaryFile` + `finally: os.unlink` | Нет утечки файлов |
| Telegram split | `max_length = 4096` | Не превышаем лимит Telegram API |

### 8.3 Что логируется

| Уровень | Что | Где |
|---|---|---|
| INFO | Routing decision (`routing to: mortgage_node`) | `graph.py`, `router.py` |
| INFO | Tool calls (cbr_tool, search_tool) с параметрами | `cbr_tool.py`, `search_tool.py` |
| INFO | Request/response (user_id, preview 100 символов) | `routes.py`, `bot.py` |
| INFO | Memory facts stored (`stored fact for user X`) | `memory.py` |
| INFO | Graph compilation, checkpoint events | `graph.py` |
| WARN | LLM fallback activated | `llm_wrapper.py`, `router.py`, `search_tool.py` |
| WARN | Markdown parsing failed | `bot.py` |
| ERROR | External API failures (GigaChat, CBR, DDG) | все nodes/tools |
| ERROR | Stack traces | все nodes через `traceback.format_exc()` |
| DEBUG | Полные промпты, raw API responses | `llm_wrapper.py` (только dev) |

**Что НЕ логируется:** полные ответы GigaChat, содержимое `user_memory`, credentials и токены.

### 8.4 Gap Analysis — что нужно добавить

**Агентский трек:**
| Gap | Приоритет |
|---|---|
| Eval для memory extraction (нет labeled dataset) | Высокий |
| Eval для compare/chat/search nodes | Средний |
| Explicit sliding window в mortgage/compare nodes (сейчас только в chat) | Средний |
| Retry logic для GigaChat (exponential backoff, 3 попытки) | Высокий |
| Second LLM fallback (если GigaChat полностью down) | Средний |

**Инфраструктурный трек:**
| Gap | Приоритет |
|---|---|
| Rate limiting middleware (FastAPI) — 30 req/min на IP | Высокий |
| Rate limiting Telegram — 20 msg/min на user_id | Высокий |
| Telegram webhook secret validation (`X-Telegram-Bot-Api-Secret-Token`) | Высокий |
| Prometheus metrics / structured logging (latency per node, error rate) | Средний |
| Health check для GigaChat в `/api/v1/health` | Средний |
| SQLite мониторинг (размер БД, количество checkpoints) | Средний |
| Graceful shutdown (дожать текущие запросы перед остановкой) | Низкий |

---

## 9. Технические и операционные ограничения (SLO)

### 9.1 Latency

| Сценарий | p95 цель | Как обеспечивается |
|---|---|---|
| Fast-path запрос (0 LLM) | ≤1 сек | Только regex + SQLite |
| Расчёт ипотеки (1 LLM) | ≤5 сек | Детерминированный расчёт + 1 GigaChat call |
| Chat/Compare (1 LLM) | ≤5 сек | 1 GigaChat call, temperature=0.3 |
| Search + format (DDG + 1 LLM) | ≤15 сек | DDG latency + 1 GigaChat call |
| p99 (любой запрос) | ≤30 сек | GigaChat timeout = 30 сек |

### 9.2 Лимиты системы

| Параметр | Значение | Источник |
|---|---|---|
| Контекст GigaChat Pro | 32K токенов | GigaChat API |
| max_tokens per call | 1024 | `_MAX_TOKENS` в `direct_llm_call.py` |
| Sliding window | 10 сообщений | `chat_node` (messages[-10:]) |
| DDG results | max 12 → ≤5 после фильтрации | `search_tool.py` |
| CSV размер | Telegram file limit = 20 MB | `telegram_bot/bot.py` |
| Checkpoint retention | 5 per thread | `cleanup_old_checkpoints()` |
| Одновременных пользователей | ~10 | Single process, SQLite WAL |
| CBR cache TTL | 3600 сек | `_RATE_CACHE_TTL` |
| Ответ Telegram | 4096 символов (split) | `max_length = 4096` |

### 9.3 Операционные параметры

| Параметр | Значение |
|---|---|
| Python | 3.13 (тестировался также на 3.11) |
| Инфраструктура | Single VPS, 2 CPU / 4 GB RAM |
| БД | Один файл `checkpoints.db`, не шардируется |
| Секреты | `.env`: GIGACHAT_CREDENTIALS, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET |
| SSL | `gigachat_verify_ssl` — отключается для корпоративных прокси через `.env` |
| Telegram режим | webhook (prod, требует публичный IP) или polling (dev) |
| Бюджет GigaChat | ~2000 руб/месяц (PoC трафик) |
| Uptime цель | ≥99% в период демо |
