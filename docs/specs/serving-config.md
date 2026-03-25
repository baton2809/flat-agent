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

### Rate Limiting (решение)

**FastAPI Middleware** (`main.py`):

```python
from collections import defaultdict, deque
import time

class RateLimitMiddleware:
    """In-memory rate limiter. Достаточно для single-process PoC."""
    def __init__(self, app, max_requests: int = 30, window_sec: int = 60):
        self.app = app
        self.max_req = max_requests
        self.window = window_sec
        self._buckets: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/api/v1/chat":
            client_ip = (scope.get("client") or ["unknown"])[0]
            now = time.monotonic()
            bucket = self._buckets[client_ip]
            while bucket and bucket[0] < now - self.window:
                bucket.popleft()
            if len(bucket) >= self.max_req:
                response = Response("Too Many Requests", status_code=429)
                await response(scope, receive, send)
                return
            bucket.append(now)
        await self.app(scope, receive, send)

app.add_middleware(RateLimitMiddleware, max_requests=30, window_sec=60)
```

**Telegram throttling** (`telegram_bot/bot.py`):

```python
_tg_buckets: dict[int, deque] = defaultdict(deque)

async def _check_telegram_rate(user_id: int, update: Update) -> bool:
    now = time.monotonic()
    bucket = _tg_buckets[user_id]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 20:
        await update.message.reply_text("Слишком много запросов. Подождите минуту.")
        return False
    bucket.append(now)
    return True
```

### Webhook Secret Validation (решение)

```python
import hmac

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = settings.telegram_webhook_secret
    # hmac.compare_digest защищает от timing attack
    if expected and not hmac.compare_digest(secret.encode(), expected.encode()):
        logger.warning("Webhook secret mismatch from %s", request.client.host)
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}
```

TELEGRAM_WEBHOOK_SECRET задаётся при регистрации webhook:
```python
await bot.set_webhook(url=webhook_url, secret_token=settings.telegram_webhook_secret)
```

### API Auth для /api/v1/chat (решение)

```python
from fastapi.security import APIKeyHeader
import hmac

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_api_key(key: str | None = Depends(api_key_scheme)):
    expected = settings.api_key  # из .env: API_KEY=random_32chars
    if not expected:
        return  # если не задан — dev режим без auth
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="Invalid API key")

@app.post("/api/v1/chat", dependencies=[Depends(require_api_key)])
async def chat_endpoint(...):
    ...
```

`API_KEY` добавляется в `.env` и `.env.example`.

### Thread Pool Size (решение)

```python
import concurrent.futures

# В lifespan: создаём ограниченный пул
executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=10,         # ~10 concurrent users для single VPS
    thread_name_prefix="agent-worker"
)
app.state.executor = executor

# В chat endpoint:
result = await loop.run_in_executor(
    app.state.executor,     # вместо None (default unbounded pool)
    lambda: agent_graph.invoke(input_state, config)
)

# В shutdown:
app.state.executor.shutdown(wait=True, cancel_futures=False)
```

### Graceful Shutdown (решение)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.graph = build_graph(str(settings.db_path))
    app.state.executor = ThreadPoolExecutor(max_workers=10)
    yield
    # shutdown — uvicorn --timeout-graceful-shutdown 30 ждёт in-flight запросы
    app.state.executor.shutdown(wait=True, cancel_futures=False)
    conn = getattr(app.state.graph.checkpointer, "conn", None)
    if conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    logger.info("FlatAgent graceful shutdown complete")
```
