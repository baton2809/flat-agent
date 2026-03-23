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
| chat_node sliding window | messages[-10:] | Soft limit в коде |
| mortgage/compare nodes | Весь messages | Нет explicit sliding window |
| max_tokens per LLM call | 1024 | `_MAX_TOKENS` в direct_llm_call.py |

**Gap:** sliding window реализован только в chat_node. Mortgage и compare передают полную историю.

### Cleanup policy

```python
cleanup_old_checkpoints(keep_per_thread: int = 5):
    DELETE checkpoints WHERE NOT IN top-5 per thread_id
    DELETE checkpoint_blobs WHERE orphaned
    DELETE checkpoint_writes WHERE orphaned
    PRAGMA wal_checkpoint(TRUNCATE)
    VACUUM
```

- Вызов: вручную или при старте приложения (нет scheduled trigger — Gap)

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

**Gap (высокий приоритет):** Нет eval-набора для memory extraction. Неизвестно, насколько хорошо LLM извлекает факты на практике.

---

## [Инфраструктурный трек] Надёжность памяти

| Параметр | Значение |
|---|---|
| SQLite WAL mode | `PRAGMA journal_mode=WAL` при старте |
| Thread-safe connections | `threading.local()` в `LongTermMemory` — per-thread соединения |
| Connection для checkpoints | `check_same_thread=False` — одно соединение для LangGraph |
| VACUUM после cleanup | Предотвращает рост файла БД |
| Мониторинг размера БД | Нет (Gap) |

**Gap:** Нет мониторинга размера `checkpoints.db`. При интенсивном использовании без периодического cleanup БД может разрастись. Нужен scheduled cleanup + alert при размере > N MB.
