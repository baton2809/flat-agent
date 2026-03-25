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

## 7.7 Retry логика для LLM (tenacity)

**Решение:** `tenacity` с exponential backoff для всех GigaChat-вызовов.

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=False,          # после 3 попыток → fallback, не исключение
)
def _call_gigachat_with_retry(messages, temperature):
    return _gigachat_client.chat(messages, temperature=temperature)
```

| Параметр | Значение | Обоснование |
|---|---|---|
| Попытки | 3 | Баланс: не блокируем надолго, но даём шанс восстановиться |
| Backoff | 2–10 сек, exponential | Не перегружаем API при временном сбое |
| retry_if | ConnectionError, TimeoutError | Только сетевые ошибки; логические ошибки не ретраим |
| После 3 попыток | → `_generate_fallback()` | Бот работает даже если GigaChat недоступен |

---

## 7.8 Circuit Breaker для внешних API

**Проблема:** при деградации DDG или GigaChat каждый запрос ждёт полный timeout (30 сек). При 10 одновременных пользователях — блокировка всего процесса.

**Решение:** простой in-process circuit breaker на основе счётчика ошибок.

```python
from collections import deque
import time

class CircuitBreaker:
    """open/half-open/closed state machine."""
    def __init__(self, failure_threshold=5, window_sec=60, recovery_sec=30):
        self.failures = deque()      # timestamps ошибок в окне
        self.threshold = failure_threshold
        self.window = window_sec
        self.recovery = recovery_sec
        self.opened_at = None
        self.state = "closed"        # closed → open → half-open → closed

    def record_failure(self):
        now = time.monotonic()
        self.failures.append(now)
        # убираем старые ошибки за пределами окна
        while self.failures and self.failures[0] < now - self.window:
            self.failures.popleft()
        if len(self.failures) >= self.threshold:
            self.state = "open"
            self.opened_at = now

    def is_open(self):
        if self.state == "open":
            if time.monotonic() - self.opened_at > self.recovery:
                self.state = "half-open"
                return False         # один пробный запрос
            return True
        return False

    def record_success(self):
        self.failures.clear()
        self.state = "closed"
```

| Сервис | threshold | window | recovery | Fallback при open |
|---|---|---|---|---|
| GigaChat | 5 ошибок | 60 сек | 30 сек | `_generate_fallback()` (keyword) |
| DDG | 3 ошибки | 60 сек | 60 сек | "Поиск временно недоступен" |
| ЦБ РФ | 3 ошибки | 300 сек | 120 сек | TTL-кэш; если кэш пуст → user message |

**Инстанцирование:** module-level singleton (один `CircuitBreaker` на процесс на сервис).

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

### 8.4 Rate Limiting

**Проблема:** один пользователь может исчерпать GigaChat-бюджет (~2000 руб/мес) через flood.

**Решение: FastAPI middleware** (in-memory, без Redis, достаточно для PoC):

```python
from collections import defaultdict, deque
import time

class RateLimitMiddleware:
    def __init__(self, app, max_requests: int = 30, window_sec: int = 60):
        self.app = app
        self.max_req = max_requests
        self.window = window_sec
        self._counters: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/api/v1/chat":
            ip = scope["client"][0]
            now = time.monotonic()
            q = self._counters[ip]
            while q and q[0] < now - self.window:
                q.popleft()
            if len(q) >= self.max_req:
                # 429 Too Many Requests
                await send({"type": "http.response.start", "status": 429, ...})
                return
            q.append(now)
        await self.app(scope, receive, send)
```

**Telegram throttling** (в `bot.py`):

```python
_tg_counters: dict[int, deque] = defaultdict(deque)
TG_MAX_MSG = 20  # сообщений
TG_WINDOW = 60   # секунд

def _is_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    q = _tg_counters[user_id]
    while q and q[0] < now - TG_WINDOW:
        q.popleft()
    if len(q) >= TG_MAX_MSG:
        return True
    q.append(now)
    return False
```

| Лимит | Значение | Где |
|---|---|---|
| FastAPI `/api/v1/chat` | 30 req/60 сек на IP | `RateLimitMiddleware` |
| Telegram | 20 msg/60 сек на user_id | `bot.py` handler |
| Ответ при превышении | 429 / "Слишком много запросов, подождите минуту" | HTTP / Telegram |

### 8.5 Telegram Webhook Secret Validation

**Проблема:** без проверки X-Telegram-Bot-Api-Secret-Token любой может слать боту фейковые сообщения.

**Sequence:**

```
Telegram → POST /webhook/telegram
           Headers: X-Telegram-Bot-Api-Secret-Token: <SECRET>
                │
                ▼
        main.py: @app.post("/webhook/telegram")
                │
                ├─ secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
                ├─ expected = settings.TELEGRAM_WEBHOOK_SECRET
                ├─ if not hmac.compare_digest(secret, expected):
                │      raise HTTPException(403, "Forbidden")
                │
                └─ application.update_queue.put_nowait(Update(...))
```

```python
import hmac

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(secret, settings.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}
```

**`hmac.compare_digest`** — защита от timing attack (не простое `==`).

### 8.6 Auth для /api/v1/chat

**Проблема:** открытый endpoint — любой может вызвать и потратить GigaChat-бюджет.

**Решение: API Key через заголовок** (минимально достаточно для PoC):

```python
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_api_key(key: str = Depends(api_key_header)):
    if not hmac.compare_digest(key, settings.API_KEY):
        raise HTTPException(403, "Invalid API key")
    return key

@app.post("/api/v1/chat", dependencies=[Depends(verify_api_key)])
async def chat(...):
    ...
```

`API_KEY` хранится в `.env`, длина ≥32 символа.

### 8.7 Graceful Shutdown

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown — дожимаем текущие запросы
    if hasattr(app.state, "graph"):
        # закрываем SQLite соединения
        app.state.graph.checkpointer.conn.close()
    if hasattr(app.state, "application"):
        await app.state.application.stop()
    logger.info("Shutdown complete")
```

FastAPI lifespan автоматически дожидается завершения активных запросов перед вызовом shutdown-блока (при использовании `uvicorn --timeout-graceful-shutdown 30`).

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
