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

## Gap Analysis: что нужно добавить

### [Агентский трек] Missing evals

| Eval | Статус | Приоритет | Описание |
|---|---|---|---|
| Routing eval | Реализован | — | 20 кейсов, `eval/run_eval.py` |
| Memory extraction eval | Отсутствует | Высокий | Нет labeled dataset; неизвестно recall LLM extraction |
| Mortgage calc accuracy | Отсутствует | Высокий | Сравнение с банковскими калькуляторами (цель ≤1%) |
| Search relevance eval | Отсутствует | Средний | Человеческая оценка топ-5 результатов |
| Compare quality eval | Отсутствует | Средний | Оценка полноты и корректности сравнения |
| Chat domain restriction eval | Отсутствует | Средний | Процент off-topic ответов (цель ≤5%) |
| Fallback rate tracking | Отсутствует | Средний | % активации LLM fallback per day |
| End-to-end latency per scenario | Отсутствует | Средний | p95/p99 latency для каждого маршрута |

### Предложение: Memory Extraction Eval

```python
# eval/test_memory.json (нужно создать):
[
  {
    "message": "Меня зовут Алексей, ищу квартиру в Митино",
    "expected_facts": ["Пользователя зовут Алексей", "Митино"],
    "expected_no_fact": false
  },
  {
    "message": "Посчитай ипотеку 8 млн на 20 лет",
    "expected_facts": [],
    "expected_no_fact": true
  }
]
```

### Предложение: Mortgage Accuracy Eval

```python
# eval/test_mortgage.json:
[
  {
    "amount": 8_000_000,
    "annual_rate": 19.0,
    "term_months": 240,
    "expected_monthly": 153_456.78,  # из Сбербанк калькулятора
    "tolerance_pct": 1.0
  }
]
```

---

## [Инфраструктурный трек] Что нужно добавить

### Метрики (Prometheus / structured logging)

| Метрика | Тип | Описание | Приоритет |
|---|---|---|---|
| `flatagent_request_total{route}` | Counter | Кол-во запросов per route | Высокий |
| `flatagent_request_duration_seconds{route}` | Histogram | Latency per route | Высокий |
| `flatagent_llm_calls_total{node, status}` | Counter | LLM вызовы: success/error/fallback | Высокий |
| `flatagent_llm_duration_seconds{node}` | Histogram | Latency GigaChat calls | Высокий |
| `flatagent_external_api_errors_total{service}` | Counter | Ошибки CBR/DDG | Высокий |
| `flatagent_fallback_total{type}` | Counter | LLM fallback, regex fallback | Средний |
| `flatagent_db_size_bytes` | Gauge | Размер checkpoints.db | Средний |
| `flatagent_memory_facts_total` | Gauge | Кол-во фактов в user_memory | Средний |
| `flatagent_cbr_cache_hits_total` | Counter | TTL-кэш hit/miss | Низкий |

### Alerting (рекомендуемые пороги)

| Alert | Условие | Severity |
|---|---|---|
| LLM недоступен | `llm_calls_total{status=error}` > 50% за 5 мин | Critical |
| Высокая latency | `p95(request_duration_seconds)` > 15 сек | Warning |
| DDG degradation | `external_api_errors_total{service=duckduckgo}` > 10/мин | Warning |
| БД большой размер | `db_size_bytes` > 500 MB | Warning |
| Высокий fallback rate | `fallback_total{type=llm}` > 20% за 10 мин | Warning |

### Health Check улучшение

**Сейчас:**
```json
GET /api/v1/health → {"status": "ok", "agent": "FlatAgent"}
```

**Нужно:**
```json
GET /api/v1/health → {
    "status": "ok|degraded|down",
    "components": {
        "gigachat": "ok|error",
        "sqlite": "ok|error",
        "cbr_cache": "fresh|stale|error"
    },
    "uptime_seconds": 3600
}
```

### Structured Logging (предложение)

```python
import structlog

logger = structlog.get_logger()

# Вместо:
logger.info("routing to: %s_node", route)

# Нужно:
logger.info("routing_decision",
    route=route,
    user_id=user_id,
    method="fast_path|llm",
    latency_ms=latency
)
```

Это позволит парсить логи в ELK/Loki без regex.

### Distributed Tracing (будущее)

При масштабировании на несколько инстансов — OpenTelemetry tracing:
- `trace_id` per user request
- Span per LangGraph node
- Span per LLM call
- Span per external API call
