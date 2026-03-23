# Spec: Serving / Config

## Точки входа

| Режим | Файл | Команда | Когда использовать |
|---|---|---|---|
| Telegram polling | `telegram_bot/bot.py` | `python telegram_bot/bot.py` | Dev, нет публичного IP |
| FastAPI + webhook | `main.py` | `uvicorn main:app --host 0.0.0.0 --port 8000` | Production |
| FastAPI только API | `main.py` | То же, без Telegram token | API-only режим |

---

## Конфигурация (config.py)

### Settings (pydantic-settings)

```python
class Settings(BaseSettings):
    # GigaChat
    gigachat_credentials: str           # Required, base64 auth token
    gigachat_scope: str = "GIGACHAT_API_B2B"
    gigachat_model: str = "GigaChat"    # или "GigaChat-Pro"
    gigachat_verify_ssl: bool = True    # False для корпоративных прокси

    # Telegram
    telegram_bot_token: str             # Required
    telegram_webhook_secret: str = ""   # Для webhook security

    # Serving
    webhook_url: str = ""               # https://yourdomain.com/webhook
    host: str = "0.0.0.0"
    port: int = 8000

    # Storage
    db_path: Path = Path("checkpoints.db")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
```

### Валидация при старте

```python
@field_validator("gigachat_credentials")
def credentials_must_not_be_empty(cls, v) → str:
    if not v.strip(): raise ValueError("GIGACHAT_CREDENTIALS is required")

@field_validator("telegram_bot_token")
def token_must_not_be_empty(cls, v) → str:
    if not v.strip(): raise ValueError("TELEGRAM_BOT_TOKEN is required")
```

Приложение **не стартует** при отсутствии обязательных переменных.

### .env файл (пример: .env.example)

```env
GIGACHAT_CREDENTIALS=your_base64_credentials_here
GIGACHAT_SCOPE=GIGACHAT_API_B2B
GIGACHAT_MODEL=GigaChat
GIGACHAT_VERIFY_SSL=true

TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_WEBHOOK_SECRET=random_secret_for_webhook_security

WEBHOOK_URL=https://yourdomain.com
HOST=0.0.0.0
PORT=8000

DB_PATH=checkpoints.db
```

### LLM Singleton

```python
# get_settings() → lru_cache(maxsize=1) — Settings создаётся один раз
# get_llm() → _llm_instance — GigaChatWrapper создаётся один раз при первом вызове
```

---

## FastAPI Application (main.py)

### Lifecycle

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup:
    graph = build_graph(str(settings.db_path))  # SQLite + LangGraph
    set_agent_graph(graph)                        # routes.py reference
    # Webhook setup если webhook_url задан
    yield
    # Shutdown: нет explicit cleanup (Gap)
```

### Endpoints

| Method | Path | Auth | Описание |
|---|---|---|---|
| GET | `/api/v1/health` | Нет | `{"status": "ok", "agent": "FlatAgent"}` |
| POST | `/api/v1/chat` | Нет (Gap) | `{message, user_id}` → `{response}` |
| POST | `/webhook` | Telegram secret | Telegram Bot API webhook handler |

### Chat endpoint implementation

```python
POST /api/v1/chat
Body: {message: str, user_id: str}

# Выполнение через thread pool (не блокирует event loop):
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(
    None,
    lambda: agent_graph.invoke(input_state, config)
)
```

---

## Telegram Bot (telegram_bot/bot.py)

### Handlers

| Handler | Trigger | Действие |
|---|---|---|
| `CommandHandler("start")` | `/start` | Очистить user_memory + welcome message |
| `CommandHandler("forget")` | `/forget` | Очистить user_memory + подтверждение |
| `MessageHandler(Document.ALL)` | Любой файл | Если CSV → csv_analysis; иначе — ошибка |
| `MessageHandler(TEXT & ~COMMAND)` | Текстовое сообщение | → LangGraph invoke → reply |

### Telegram-специфика

```python
# Chat action (typing indicator)
await update.message.chat.send_action(action="typing")

# Split длинных ответов
max_length = 4096
for i in range(0, len(text), max_length):
    await update.message.reply_text(text[i:i+max_length], parse_mode='Markdown')

# Fallback при Markdown ошибке
except Exception as markdown_error:
    await update.message.reply_text(text)  # plain text
```

### Версии моделей GigaChat

| Модель | Контекст | Скорость | Качество | Стоимость |
|---|---|---|---|---|
| `GigaChat` | 8K | Быстрая | Базовое | Низкая |
| `GigaChat-Pro` | 32K | Медленнее | Высокое | Выше |
| `GigaChat-Max` | 128K | Медленнее | Максимальное | Высокая |

Конфигурируется через `GIGACHAT_MODEL` в `.env`. Смена без перезапуска — не поддерживается (singleton).

---

## [Агентский трек] Конфигурация качества

| Параметр | Значение | Где задаётся |
|---|---|---|
| Router temperature | 0.0 | `llm_call_direct(..., temperature=0.0)` в router.py |
| Generation temperature | 0.3 | `llm_call_direct(..., temperature=0.3)` в compare/search/chat |
| max_tokens | 1024 | `_MAX_TOKENS` в direct_llm_call.py |
| Model version | `GigaChat` (default) | `GIGACHAT_MODEL` в .env |

**Gap:** Нет возможности менять temperature/model per request без перезапуска.

---

## [Инфраструктурный трек] Надёжность serving

### Что реализовано

| Механизм | Статус |
|---|---|
| Startup validation (credentials) | Реализовано |
| `run_in_executor` для sync LangGraph в async FastAPI | Реализовано |
| CSV temp file cleanup в finally | Реализовано |
| Telegram Markdown fallback | Реализовано |
| Polling fallback для dev | Реализовано |

### Gaps (требуют доработки)

| Gap | Приоритет | Описание |
|---|---|---|
| Rate limiting middleware | Высокий | 30 req/min на IP для `/api/v1/chat` |
| Telegram rate limit per user | Высокий | 20 msg/min на user_id |
| Webhook secret validation | Высокий | Валидация `X-Telegram-Bot-Api-Secret-Token` header не реализована полностью |
| API authentication | Высокий | `/api/v1/chat` открыт без auth (любой может вызвать) |
| Graceful shutdown | Средний | Нет `app.state.graph` cleanup при остановке |
| Health check GigaChat | Средний | `/health` не проверяет доступность GigaChat |
| Thread pool size | Средний | `run_in_executor(None, ...)` — default pool, нет limits |
| Process restart policy | Низкий | Нет supervisor (systemd/pm2) в PoC |
