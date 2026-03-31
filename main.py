"""FlatAgent application entry point."""

import asyncio
import concurrent.futures
import hmac
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app, CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings
from agent import build_graph
from api import router as api_router, set_agent_graph

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/flat_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_RATE_LIMIT = 30   # requests per window (per IP)
_RATE_WINDOW = 60  # seconds

_rate_buckets: dict = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        bucket = _rate_buckets[client_ip]
        # evict timestamps outside the window
        _rate_buckets[client_ip] = [t for t in bucket if now - t < _RATE_WINDOW]
        bucket = _rate_buckets[client_ip]

        if len(bucket) >= _RATE_LIMIT:
            logger.warning("rate limit exceeded for %s", client_ip)
            return Response(
                content=f'{{"detail":"Too many requests. Limit: {_RATE_LIMIT}/min."}}',
                status_code=429,
                media_type="application/json",
            )

        _rate_buckets[client_ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Scheduled cleanup
# ---------------------------------------------------------------------------

async def _scheduled_cleanup(interval_hours: int = 24) -> None:
    """Background task: cleanup old checkpoints + log DB size every 24h."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            from agent.memory import memory_manager
            memory_manager.cleanup_old_checkpoints(keep_per_thread=5)
            logger.info("scheduled cleanup completed")
        except Exception:
            logger.exception("scheduled cleanup failed")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("initializing FlatAgent...")

    s = get_settings()

    # Bounded thread pool — ~10 concurrent users on single VPS
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=10,
        thread_name_prefix="agent-worker",
    )
    app.state.executor = executor

    try:
        agent_graph = build_graph(str(s.db_path))
        set_agent_graph(agent_graph)
        app.state.graph = agent_graph
        logger.info("agent graph initialized successfully")

        # One-time cleanup at startup
        from agent.memory import memory_manager
        executor.submit(memory_manager.cleanup_old_checkpoints, 5)

        # Scheduled cleanup every 24h
        asyncio.create_task(_scheduled_cleanup(interval_hours=24))

    except Exception as exc:
        logger.error("initialization error: %s", exc)
        raise

    yield

    # Graceful shutdown
    logger.info("shutting down FlatAgent...")
    executor.shutdown(wait=True, cancel_futures=False)

    conn = getattr(getattr(app.state, "graph", None), "checkpointer", None)
    if conn:
        raw_conn = getattr(conn, "conn", None)
        if raw_conn:
            try:
                raw_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                raw_conn.close()
            except Exception:
                pass

    logger.info("FlatAgent shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FlatAgent API",
    description="Помощник по недвижимости на основе GigaChat и LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1", tags=["api"])


@app.get("/")
async def root():
    return {
        "name": "FlatAgent",
        "version": "1.0.0",
        "description": "Помощник по недвижимости",
        "endpoints": {
            "health": "/api/v1/health",
            "chat": "/api/v1/chat",
        },
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram Bot API webhook receiver.

    Validates X-Telegram-Bot-Api-Secret-Token using hmac.compare_digest
    to prevent timing attacks.
    """
    s = get_settings()
    webhook_secret = s.telegram_webhook_secret
    if webhook_secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(
            token.encode("utf-8"),
            webhook_secret.encode("utf-8"),
        ):
            logger.warning(
                "webhook secret mismatch from %s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        from telegram_bot import process_webhook
        data = await request.json()
        logger.info("received webhook from telegram")
        await process_webhook(data)
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("webhook processing error: %s", exc)
        return {"status": "error", "message": str(exc)}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint.

    Updates circuit breaker gauges and DB size before returning metrics.
    """
    import os
    from agent.circuit_breaker import gigachat_cb, cbr_cb, ddg_cb
    from agent.metrics import circuit_breaker_open, db_size_bytes

    circuit_breaker_open.labels(service="gigachat").set(1 if gigachat_cb.is_open() else 0)
    circuit_breaker_open.labels(service="cbr").set(1 if cbr_cb.is_open() else 0)
    circuit_breaker_open.labels(service="ddg").set(1 if ddg_cb.is_open() else 0)

    try:
        s = get_settings()
        db_size_bytes.set(os.path.getsize(str(s.db_path)))
    except OSError:
        pass

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main():
    s = get_settings()
    logger.info("starting FlatAgent on %s:%s", s.host, s.port)
    uvicorn.run(
        "main:app",
        host=s.host,
        port=s.port,
        reload=False,
        log_level="info",
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
