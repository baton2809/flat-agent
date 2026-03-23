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

### Gaps (требуют доработки)

- [ ] Retry с exponential backoff для GigaChat в роутере (сейчас нет retry)
- [ ] `enhanced_router.py` — есть в `__pycache__` ветки, не в `main`; нужно решить: удалить или включить
- [ ] Eval для memory extraction (нет labeled dataset)

---

## [Инфраструктурный трек] Надёжность

| Параметр | Значение |
|---|---|
| SQLite WAL mode | Читатели не блокируют писателей |
| `check_same_thread=False` | Единое соединение для LangGraph (не thread-local) |
| Thread-local connections в LongTermMemory | Отдельные соединения per thread для `user_memory` |
| Checkpoint cleanup | `keep_per_thread=5` + `VACUUM` + `WAL checkpoint TRUNCATE` |
| Одновременные запросы | LangGraph `thread_id` изолирует контекст per user |

### Gaps (требуют доработки)

- [ ] Graceful shutdown: дожать текущие `invoke()` перед остановкой процесса
- [ ] SQLite мониторинг: размер файла, количество checkpoints — нет алертов
- [ ] Connection pool для высокой нагрузки (>10 concurrent users)
