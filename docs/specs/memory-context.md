# Spec: Memory / Context

## Архитектура памяти

FlatAgent использует **два уровня памяти** и **один уровень кэша**:

```
┌─────────────────────────────────────────────┐
│  Session context (краткосрочная)            │
│  SQLite: checkpoints (LangGraph)            │
│  Область: один диалог (thread_id=user_id)   │
├─────────────────────────────────────────────┤
│  Long-term facts (долгосрочная)             │
│  SQLite: user_memory                        │
│  Область: все сессии пользователя           │
├─────────────────────────────────────────────┤
│  Process cache (эфемерная)                  │
│  In-memory: CBR rates                       │
│  Область: жизнь процесса (TTL 1ч)           │
└─────────────────────────────────────────────┘
```

---

## Session Context (LangGraph Checkpoints)

### Schema

```
SQLite table: checkpoints (создаётся LangGraph SqliteSaver)
  thread_id        TEXT  ← user_id (Telegram chat_id)
  checkpoint_ns    TEXT
  checkpoint_id    TEXT
  parent_ns        TEXT
  type             TEXT
  checkpoint       BLOB  ← AgentState сериализованный
  metadata         BLOB

Дополнительные таблицы: checkpoint_blobs, checkpoint_writes
```

### AgentState

```python
messages: Annotated[Sequence[BaseMessage], add_messages]
# Reducer: add_messages — новые сообщения добавляются, не перезаписывают
# Типы: HumanMessage (user), AIMessage (bot)

route: str   # "mortgage" | "compare" | "search" | "chat"
user_id: str # Telegram chat_id
```

### Context budget

| Компонент | Размер | Ограничение |
|---|---|---|
| GigaChat Pro контекст | 32K токенов | Hard limit API |
| chat_node sliding window | messages[-10:] | Реализовано |
| mortgage_node sliding window | messages[-10:] | **Добавить** — сейчас полная история |
| compare_node sliding window | messages[-10:] | **Добавить** — сейчас полная история |
| max_tokens per LLM call | 1024 | `_MAX_TOKENS` в direct_llm_call.py |

**Решение для mortgage/compare:** применить тот же паттерн что в chat_node:

```python
# В mortgage_node и compare_node (единый хелпер):
def _get_context_messages(state: AgentState, window: int = 10) -> list:
    """Последние N сообщений для передачи в LLM."""
    return list(state["messages"])[-window:]
```

Это гарантирует, что ни один node не передаёт в LLM больше 10 сообщений истории.

### Cleanup policy

```python
cleanup_old_checkpoints(keep_per_thread: int = 5):
    DELETE checkpoints WHERE NOT IN top-5 per thread_id
    DELETE checkpoint_blobs WHERE orphaned
    DELETE checkpoint_writes WHERE orphaned
    PRAGMA wal_checkpoint(TRUNCATE)
    VACUUM
```

- Вызов: при старте приложения + **scheduled trigger каждые 24 часа**

**Scheduled cleanup (решение):**

```python
import asyncio

async def scheduled_cleanup(graph, interval_hours: int = 24):
    """Фоновая задача: cleanup + мониторинг размера БД."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            cleanup_old_checkpoints(keep_per_thread=5)
            stats = get_db_stats(settings.DB_PATH)
            logger.info("Scheduled cleanup done: %s", stats)
            # Алерт если БД большая
            if stats["size_mb"] > 50:
                logger.warning("DB size alert: %.1fMB", stats["size_mb"])
        except Exception:
            logger.exception("Scheduled cleanup failed")

# В lifespan:
asyncio.create_task(scheduled_cleanup(app.state.graph))
```

**Алерт-пороги:**
| Размер `checkpoints.db` | Действие |
|---|---|
| < 50 MB | OK |
| 50–100 MB | WARNING в логах |
| > 100 MB | CRITICAL + `/health` возвращает `"db_status": "critical"` |

---

## Long-term Facts (user_memory)

### Schema

```sql
CREATE TABLE IF NOT EXISTS user_memory (
    user_id  TEXT NOT NULL,
    fact     TEXT NOT NULL,
    UNIQUE(user_id, fact)
);
CREATE INDEX IF NOT EXISTS idx_user_memory_user_id ON user_memory(user_id);
```

### Memory policy

| Правило | Реализация |
|---|---|
| Хранится только то, что пользователь сказал сам | LLM извлекает только из HumanMessage |
| Дедупликация | `INSERT OR IGNORE` + `UNIQUE` constraint |
| Минимальная длина факта | `len(line) > 15` в LLM extraction |
| Формат | `"Пользователь <факт>"` — одно предложение |
| Удаление | `/forget` → `DELETE WHERE user_id = ?` |

### Extraction pipeline

```
1. LLM (primary):
   System: "Ты помощник по извлечению фактов"
   User: "Определи, содержит ли сообщение факт... Если нет - ответь 'нет'"

   Validation:
   ├── text.lower().startswith("нет") or len(text) < 10 → return False
   └── Берём первую строку где "пользовател" in line.lower() and len > 15

2. Regex fallback (при LLM ошибке):
   ├── "меня зовут X" / "зовут X" / "мое имя X" / "называй меня X"
   │   → "Пользователя зовут {X.capitalize()}"
   ├── "N млн/миллион"
   │   → "Бюджет пользователя: N млн"
   ├── "семья" / "жена" / "муж" / "дети" / "ребёнок"
   │   → "Пользователь упомянул семью: {message[:120]}"
   └── "работаю" / "работает"
       → "Пользователь упомянул работу: {message[:120]}"
```

### Context injection

```python
# В chat_node:
memory_context = memory_manager.get_memory_context(user_id)
# → "Факты о пользователе:\n- Пользователя зовут Алексей\n- Бюджет: 8 млн"

user_name = memory_manager.get_user_name(user_id)
# Regex паттерны: "зовут X", "имя X", "представился как X", "назвал себя X"
# → Имя инжектируется в system prompt: "Обращайся к нему по имени {name}"
```

### 152-ФЗ соответствие

| Аспект | Статус |
|---|---|
| Хранимые данные | Только Telegram числовой user_id + факты из диалога |
| Паспортные данные, СНИЛС, счета | Не хранятся |
| Передача третьим лицам | Нет |
| Право на удаление | `/forget` команда реализована |
| Деперсонализация | Telegram user_id — числовой, не имя |

---

## Process-level Cache

### ЦБ РФ данные

```python
_rate_cache: Optional[Tuple[str, float]] = None   # (result_str, monotonic_time)
_cbr_cache: dict[str, Tuple[str, float]] = {}     # {date_iso: (result_str, monotonic_time)}
_RATE_CACHE_TTL = 3600  # секунд
```

- `time.monotonic()` — монотонный таймер, нет проблем с DST и системным временем
- **Не персистируется** — сбрасывается при перезапуске процесса
- **Gap:** При ExternalAPIError нет fallback на устаревший кэш (нужно вернуть stale данные с пометкой)

### LLM Singleton

```python
# config.py
_llm_instance = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = GigaChatWrapper(...)
    return _llm_instance

get_settings = lru_cache(maxsize=1)(Settings)
```

---

## [Агентский трек] Качество памяти

| Метрика | Цель | Текущий статус |
|---|---|---|
| Memory extraction recall | ≥85% | Нет автоматического измерения (Gap) |
| Дедупликация фактов | 100% | `UNIQUE` constraint — гарантировано |
| Name resolution accuracy | — | 4 regex паттерна, нет eval |
| Факты не перезаписываются | — | `INSERT OR IGNORE` |

**Eval план (решение):** `eval/test_memory.json` — 5 размеченных кейсов:

```json
[
  {"input": "Меня зовут Алексей", "should_extract": true, "expected_contains": "Алексей"},
  {"input": "Мой бюджет 8 млн рублей", "should_extract": true, "expected_contains": "8 млн"},
  {"input": "У меня жена и двое детей", "should_extract": true, "expected_contains": "семью"},
  {"input": "Расскажи про ипотеку", "should_extract": false, "expected_contains": null},
  {"input": "Какой курс доллара?", "should_extract": false, "expected_contains": null}
]
```

Метрика: `recall = правильно_извлечено / всего_должны_извлечься`. Цель ≥85%.
Запуск: `python eval/run_memory_eval.py` (аналог `run_eval.py` для роутинга).

---

## [Инфраструктурный трек] Надёжность памяти

| Параметр | Значение |
|---|---|
| SQLite WAL mode | `PRAGMA journal_mode=WAL` при старте |
| Thread-safe connections | `threading.local()` в `LongTermMemory` — per-thread соединения |
| Connection для checkpoints | `check_same_thread=False` — одно соединение для LangGraph |
| VACUUM после cleanup | Предотвращает рост файла БД |
| Мониторинг размера БД | Нет (Gap) |

**Мониторинг размера БД (решение):**

```python
def get_db_stats(db_path: str) -> dict:
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
    return {"size_mb": round(size_mb, 2), "checkpoint_count": count}
```

Вызывается в `/api/v1/health`. Пороги: >50MB = WARNING, >100MB = CRITICAL.
Scheduled cleanup каждые 24ч (см. секцию Cleanup policy выше).
