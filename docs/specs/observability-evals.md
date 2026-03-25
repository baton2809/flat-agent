# Spec: Observability / Evals

---

## Текущее состояние логирования

### Что логируется сейчас

| Событие | Уровень | Модуль | Пример |
|---|---|---|---|
| Routing decision | INFO | graph.py, router.py | `routing to: mortgage_node` |
| Post-memory routing | INFO | graph.py | `post-memory routing to: mortgage_node` |
| LLM request (кол-во сообщений, модель) | INFO | llm_wrapper.py | `sending request to gigachat: 3 messages, model GigaChat` |
| Tool call: CBR | INFO | cbr_tool.py | HTTP request + status |
| Tool call: DDG | INFO | search_tool.py | `search query: "новостройки в Мытищах"` |
| Memory fact stored | INFO | memory.py | `stored fact for user 123456: Пользователя зовут Алексей` |
| Request received | INFO | routes.py, bot.py | `request from user 123456: посчитай ипотеку...` |
| Response preview | INFO | routes.py, bot.py | `response for user 123456: Расчет ипотеки:...` |
| LLM fallback activated | WARN | llm_wrapper.py, router.py | `using fallback response generation` |
| Markdown parsing failed | WARN | bot.py | `markdown parsing failed: ..., sending as plain text` |
| External API failure | ERROR | cbr_tool.py, search_tool.py | `error fetching CBR data: ...` |
| LLM error | ERROR | llm_wrapper.py | `error calling gigachat: ... (HTTPError)` |
| Full stack trace | ERROR | bot.py | `traceback: ...` |
| Full prompts, raw responses | DEBUG | llm_wrapper.py | только dev окружение |

### Что НЕ логируется (намеренно)

| Данные | Причина |
|---|---|
| Полные ответы GigaChat | Конфиденциальность |
| Содержимое user_memory | Персональные данные |
| Credentials, API токены | Безопасность |
| Количество токенов GigaChat | Gap — нужно для контроля бюджета |
| Latency per LangGraph node | Gap — нужно для SLO мониторинга |
| HTTP latency к внешним API | Gap |

### Хранение логов

```
logs/
├── bot.log          # Telegram bot events
├── flat_agent.log   # Main agent events
└── main.log         # FastAPI app events

Rotation: по 10 MB, retention 7 дней (governance.md)
Format: %(asctime)s - %(name)s - %(levelname)s - %(message)s
```

---

## Eval система (текущая)

### Routing Eval (`eval/run_eval.py`)

```python
# Pipeline:
test_cases = load_test_cases("test_cases.json")  # 20 labeled cases
metrics, results = evaluate_router(test_cases)
print_results(metrics, results)   # tabulate report
save_results(metrics, results, "eval_results.json")
```

**Метрики:**
- `overall_accuracy` — % правильных маршрутов (цель ≥90%)
- `route_accuracy[mortgage|compare|search|chat]` — per-route accuracy
- `avg_latency_ms` — среднее время роутинга
- `min/max latency_ms` — latency stats

**Состав test_cases.json (20 кейсов):**

| Route | Кол-во | Примеры |
|---|---|---|
| mortgage | 5 | "Посчитай ипотеку на 8 млн под 19%", "Рассчитай кредит 7 млн на 15 лет" |
| compare | 5 | "Сравни вторичка 9 млн vs первичка 11 млн", "Что лучше: первичка или вторичка" |
| search | 5 | "Найди новостройки в Мытищах", "Какие цены на квартиры в Москве" |
| chat | 5 | "Как оформить ипотеку с плохой КИ", "Что такое эскроу счет" |

**Запуск:**
```bash
cd eval && python run_eval.py
# Выводит tabulate-таблицу + сохраняет eval_results.json
```

---

## Eval система (расширенная)

### Routing Eval (`eval/run_eval.py`) — реализован

20 кейсов, цель ≥90%. Запуск: `python eval/run_eval.py`.

### Memory Extraction Eval (`eval/test_memory.json`) — создать

```json
[
  {
    "input": "Меня зовут Алексей",
    "should_extract": true,
    "expected_contains": "Алексей",
    "method": "llm_or_regex"
  },
  {
    "input": "Мой бюджет 8 млн рублей",
    "should_extract": true,
    "expected_contains": "8 млн",
    "method": "llm_or_regex"
  },
  {
    "input": "У меня жена и двое детей",
    "should_extract": true,
    "expected_contains": "семью",
    "method": "llm_or_regex"
  },
  {
    "input": "Расскажи про ипотеку",
    "should_extract": false,
    "expected_contains": null,
    "method": "none"
  },
  {
    "input": "Какой курс доллара?",
    "should_extract": false,
    "expected_contains": null,
    "method": "none"
  }
]
```

Метрика: `recall = правильно_извлечено / should_extract_total`. Цель ≥85%.
Запуск: `python eval/run_memory_eval.py` (скрипт аналогичен `run_eval.py`).

### Mortgage Accuracy Eval (`eval/test_mortgage.json`) — создать

```json
[
  {
    "amount": 8000000,
    "annual_rate": 19.0,
    "term_months": 240,
    "expected_monthly": 153456,
    "source": "Сбербанк калькулятор",
    "tolerance_pct": 1.0
  },
  {
    "amount": 5000000,
    "annual_rate": 16.0,
    "term_months": 180,
    "expected_monthly": 76297,
    "source": "ВТБ калькулятор",
    "tolerance_pct": 1.0
  },
  {
    "amount": 3000000,
    "annual_rate": 0.0,
    "term_months": 120,
    "expected_monthly": 25000,
    "source": "edge case: rate=0",
    "tolerance_pct": 0.0
  }
]
```

Метрика: `|actual - expected| / expected * 100 ≤ tolerance_pct`. Цель: все кейсы ≤1%.
Запуск: `python eval/run_mortgage_eval.py`.

---

## [Инфраструктурный трек] Мониторинг

### Метрики Prometheus (схема инструментации)

```python
from prometheus_client import Counter, Histogram, Gauge

# --- Request metrics ---
request_total = Counter(
    "flatagent_request_total",
    "Total requests processed",
    labelnames=["route"]           # mortgage | compare | search | chat
)
request_duration = Histogram(
    "flatagent_request_duration_seconds",
    "End-to-end request latency",
    labelnames=["route"],
    buckets=[0.5, 1, 2, 5, 10, 15, 30]
)

# --- LLM metrics ---
llm_calls_total = Counter(
    "flatagent_llm_calls_total",
    "GigaChat API calls",
    labelnames=["node", "status"]  # node: router/memory/compare/search/chat; status: ok/error/fallback
)
llm_duration = Histogram(
    "flatagent_llm_duration_seconds",
    "GigaChat call latency",
    labelnames=["node"],
    buckets=[0.5, 1, 2, 5, 10, 30]
)

# --- External API ---
external_errors = Counter(
    "flatagent_external_api_errors_total",
    "External API failures",
    labelnames=["service"]         # gigachat | cbr | duckduckgo
)
circuit_breaker_state = Gauge(
    "flatagent_circuit_breaker_open",
    "Circuit breaker state (1=open)",
    labelnames=["service"]
)

# --- Infrastructure ---
fallback_total = Counter(
    "flatagent_fallback_total",
    "Fallback activations",
    labelnames=["type"]            # llm_keyword | regex_memory | template_compare | template_search
)
db_size_bytes = Gauge("flatagent_db_size_bytes", "checkpoints.db size")
memory_facts_total = Gauge("flatagent_memory_facts_total", "Total facts in user_memory")
rate_limit_hits = Counter("flatagent_rate_limit_hits_total", "Rate limit rejections", labelnames=["channel"])
```

**Endpoint:** `GET /metrics` (prometheus_client `make_asgi_app()`)

| Метрика | Тип | Labelnames | Цель |
|---|---|---|---|
| `flatagent_request_total` | Counter | route | — |
| `flatagent_request_duration_seconds` | Histogram | route | p95 ≤15с |
| `flatagent_llm_calls_total` | Counter | node, status | error < 50% |
| `flatagent_llm_duration_seconds` | Histogram | node | p95 ≤10с |
| `flatagent_external_api_errors_total` | Counter | service | <10/мин |
| `flatagent_circuit_breaker_open` | Gauge | service | 0 в норме |
| `flatagent_fallback_total` | Counter | type | llm < 20% |
| `flatagent_db_size_bytes` | Gauge | — | <500 MB |

### Alerting (рекомендуемые пороги)

| Alert | Условие | Severity |
|---|---|---|
| LLM недоступен | `llm_calls_total{status=error}` > 50% за 5 мин | Critical |
| Высокая latency | `p95(request_duration_seconds)` > 15 сек | Warning |
| DDG degradation | `external_api_errors_total{service=duckduckgo}` > 10/мин | Warning |
| БД большой размер | `db_size_bytes` > 500 MB | Warning |
| Высокий fallback rate | `fallback_total{type=llm}` > 20% за 10 мин | Warning |

### Health Check (решение)

**Реализация:**

```python
@app.get("/api/v1/health")
async def health():
    import os, time
    components = {}

    # SQLite
    try:
        db_path = str(settings.db_path)
        size_mb = os.path.getsize(db_path) / 1024 / 1024
        components["sqlite"] = {"status": "ok", "size_mb": round(size_mb, 1)}
        if size_mb > 100:
            components["sqlite"]["status"] = "warning"
    except Exception as e:
        components["sqlite"] = {"status": "error", "detail": str(e)}

    # GigaChat (circuit breaker state — без реального вызова)
    cb_open = _gigachat_cb.is_open()
    components["gigachat"] = {
        "status": "error" if cb_open else "ok",
        "circuit_breaker": "open" if cb_open else "closed"
    }

    # CBR cache
    if _rate_cache:
        age_s = time.monotonic() - _rate_cache[1]
        components["cbr_cache"] = {
            "status": "stale" if age_s > 3600 else "fresh",
            "age_seconds": int(age_s)
        }
    else:
        components["cbr_cache"] = {"status": "empty"}

    overall = "ok"
    if any(c.get("status") == "error" for c in components.values()):
        overall = "degraded"

    return {"status": overall, "components": components, "uptime_seconds": int(time.monotonic())}
```

**Пример ответа:**
```json
{
  "status": "ok",
  "components": {
    "sqlite": {"status": "ok", "size_mb": 12.4},
    "gigachat": {"status": "ok", "circuit_breaker": "closed"},
    "cbr_cache": {"status": "fresh", "age_seconds": 823}
  },
  "uptime_seconds": 14400
}
```

### Structured Logging (решение)

**Текущий формат (plain text):**
```
2024-01-15 10:23:45 - agent.router - INFO - routing to: mortgage_node
```

**Целевой формат (JSON, парсится ELK/Loki без regex):**
```json
{
  "timestamp": "2024-01-15T10:23:45.123Z",
  "level": "INFO",
  "logger": "agent.router",
  "event": "routing_decision",
  "route": "mortgage",
  "user_id": "123456",
  "method": "llm_path",
  "latency_ms": 342,
  "request_id": "req-abc123"
}
```

**Реализация через `python-json-logger`:**

```python
from pythonjsonlogger import jsonlogger

handler = logging.FileHandler("logs/flat_agent.log")
handler.setFormatter(jsonlogger.JsonFormatter(
    "%(timestamp)s %(level)s %(name)s %(message)s"
))
logging.getLogger().addHandler(handler)
```

Поля, которые должны быть в каждом event:

| Поле | Тип | Всегда | Описание |
|---|---|---|---|
| `event` | str | Да | Машинный идентификатор события |
| `user_id` | str | Да | Telegram ID (не имя) |
| `request_id` | str | Да | UUID per request для correlation |
| `route` | str | Нет | routing decision |
| `node` | str | Нет | LangGraph node name |
| `latency_ms` | int | Нет | Время выполнения шага |
| `status` | str | Нет | ok/error/fallback |

### Distributed Tracing (будущее)

При масштабировании на несколько инстансов — OpenTelemetry tracing:
- `trace_id` per user request
- Span per LangGraph node
- Span per LLM call
- Span per external API call
