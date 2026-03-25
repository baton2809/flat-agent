# Spec: Agent / Orchestrator

## Модуль

`agent/graph.py`, `agent/state.py`, `agent/nodes/router.py`, `agent/nodes/memory_extraction.py`

---

## Граф (LangGraph StateGraph)

```
entry: router
router → memory_extraction         (все маршруты)
memory_extraction → mortgage_node  (route == "mortgage")
memory_extraction → compare_node   (route == "compare")
memory_extraction → search_node    (route == "search")
memory_extraction → chat_node      (route == "chat")
[mortgage|compare|search|chat]_node → END
```

### State schema

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # аккумулируются
    route: str        # mortgage | compare | search | chat
    user_id: str      # Telegram chat_id или API user_id
```

### Checkpointing

- `SqliteSaver(conn)` — персистентный чекпоинт
- `conn = sqlite3.connect(db_path, check_same_thread=False)`
- `PRAGMA journal_mode=WAL` — non-blocking reads
- `thread_id = user_id` — изоляция контекста per user

---

## Router Node

### Стратегия (двухуровневая)

**Уровень 1 — Fast-path (детерминированный, 0 LLM-вызовов):**

| Паттерн | Маршрут | Примеры |
|---|---|---|
| Приветствия, "ты кто", "что умеешь" | chat | "привет", "расскажи о себе" |
| CBR запросы | chat | "ключевая ставка", "курс доллара", "курс EUR" |
| Явный поиск | search | "найди", "новостройки в Мытищах", price dynamics |
| Mortgage follow-up | mortgage | Предыдущий AI-ответ содержит "Ежемесячный платеж" + уточняющий запрос |

**Уровень 2 — LLM-path (GigaChat function calling):**

```python
RouteDecision(
    route: Literal["mortgage", "compare", "search", "chat"],
    reasoning: str  # краткое обоснование
)
# temperature=0.0, max_tokens=1024
```

Post-validation: `if route not in ("mortgage", "compare", "search", "chat") → "chat"`

### Fallback chain

```
GigaChat function call
    ↓ (ошибка/timeout)
route = "chat"  ← безопасный дефолт
```

### Stop conditions

- Router всегда завершается (нет retry loops)
- Максимум 1 LLM-вызов в router_node
- Timeout GigaChat = 30 сек (SDK default)

---

## Memory Extraction Node

- Выполняется **после router, до processing** — для всех маршрутов
- Вызывает `memory_manager.extract_and_store_facts(user_id, last_message)`
- Не добавляет сообщений в state (side-effect only)
- Не блокирует основной flow при ошибке: исключения логируются, выполнение продолжается

### Retry / fallback

```
LLM extraction
    ↓ (LLMError или пустой ответ)
Regex extraction (имя, бюджет, семья, работа)
    ↓ (нет паттерна)
Ничего не сохраняем — ОК
```

---

## [Агентский трек] Правила качества

| Правило | Реализация |
|---|---|
| Роутер не может вернуть невалидный маршрут | function calling + post-validation |
| Роутер не использует вариативность | temperature=0.0 |
| Fallback безопасен | route="chat" — всегда обработает запрос |
| Eval coverage | `eval/run_eval.py` — 20 labeled cases, цель ≥90% |
| Context-aware routing | `_is_mortgage_followup()` проверяет AI-контекст |

### Retry / Fallback для роутера (решение)

**Паттерн: tenacity с exponential backoff**

```python
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, after_log
)
import logging

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    after=after_log(logger, logging.WARNING),
    reraise=False,
)
def _call_router_llm(messages: list) -> RouteDecision | None:
    """Возвращает RouteDecision или None после 3 неудачных попыток."""
    return llm_call_with_functions(messages, temperature=0.0)
```

**Fallback chain после исчерпания попыток:**
```
attempt 1 → ConnectionError → wait 2s
attempt 2 → ConnectionError → wait 4s
attempt 3 → ConnectionError → reraise=False → return None
    ↓
route = "chat"  ← всегда безопасный дефолт
```

`enhanced_router.py` из `__pycache__` — **удалить**. Функциональность покрыта текущим `router.py` + tenacity.

### Eval для memory extraction (план)

Нет labeled dataset — качество неизмеримо. **Минимальный план:**

```json
// eval/test_memory.json  (5 кейсов, достаточно для старта)
[
  {"input": "Меня зовут Алексей", "expected_fact": "Пользователя зовут Алексей", "should_extract": true},
  {"input": "Мой бюджет 8 млн", "expected_fact": "Бюджет пользователя: 8 млн", "should_extract": true},
  {"input": "Расскажи про ипотеку", "expected_fact": null, "should_extract": false},
  {"input": "У меня жена и двое детей", "expected_fact": "Пользователь упомянул семью", "should_extract": true},
  {"input": "Какой курс доллара?", "expected_fact": null, "should_extract": false}
]
```

Метрика: `recall = extracted_correctly / should_extract_total`. Цель ≥85%.

---

## [Инфраструктурный трек] Надёжность

| Параметр | Значение |
|---|---|
| SQLite WAL mode | Читатели не блокируют писателей |
| `check_same_thread=False` | Единое соединение для LangGraph (не thread-local) |
| Thread-local connections в LongTermMemory | Отдельные соединения per thread для `user_memory` |
| Checkpoint cleanup | `keep_per_thread=5` + `VACUUM` + `WAL checkpoint TRUNCATE` |
| Одновременные запросы | LangGraph `thread_id` изолирует контекст per user |

### Graceful Shutdown (решение)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    app.state.graph = build_graph()
    yield
    # --- shutdown ---
    # LangGraph не имеет async close; закрываем SQLite соединение явно
    conn = app.state.graph.checkpointer.conn
    if conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    logger.info("Graph checkpointer closed, shutdown complete")
```

Uvicorn: `--timeout-graceful-shutdown 30` — ждёт завершения активных запросов.

### SQLite мониторинг (решение)

```python
import os

def get_db_stats(db_path: str) -> dict:
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM checkpoints"
        ).fetchone()[0]
    if size_mb > 100:
        logger.critical("DB size exceeded 100MB: %.1fMB", size_mb)
    elif size_mb > 50:
        logger.warning("DB size warning: %.1fMB", size_mb)
    return {"size_mb": round(size_mb, 2), "checkpoint_count": count}
```

Вызов: при `/api/v1/health` + при каждом `cleanup_old_checkpoints()`.

**Алерт-пороги:** >50 MB = WARNING, >100 MB = CRITICAL → в `/health` ответ.
