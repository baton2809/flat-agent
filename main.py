"""FlatAgent application entry point."""

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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


_RATE_LIMIT = 20
_RATE_WINDOW = 60

_rate_counters: dict = defaultdict(lambda: [0, 0.0])


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        count, window_start = _rate_counters[client_ip]
        if now - window_start >= _RATE_WINDOW:
            _rate_counters[client_ip] = [1, now]
        else:
            if count >= _RATE_LIMIT:
                logger.warning("rate limit exceeded for %s", client_ip)
                return Response(
                    content=f'{{"detail":"Too many requests. Limit: {_RATE_LIMIT} per minute."}}',
                    status_code=429,
                    media_type="application/json",
                )
            _rate_counters[client_ip][0] += 1

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("initializing FlatAgent...")

    try:
        s = get_settings()
        agent_graph = build_graph(str(s.db_path))
        set_agent_graph(agent_graph)
        logger.info("agent graph initialized successfully")

        if s.telegram_bot_token:
            logger.info("telegram bot token configured - bot can be started via manage.sh")
        else:
            logger.info("telegram bot token not configured")

        from agent.memory import memory_manager
        asyncio.get_event_loop().run_in_executor(
            None, lambda: memory_manager.cleanup_old_checkpoints(30)
        )

    except Exception as exc:
        logger.error("initialization error: %s", exc)
        raise

    yield

    logger.info("shutting down FlatAgent...")


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
    webhook_secret = get_settings().telegram_webhook_secret
    if webhook_secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != webhook_secret:
            logger.warning("invalid webhook secret token from %s", request.client)
            return Response(content='{"status":"forbidden"}', status_code=403, media_type="application/json")

    try:
        from telegram_bot import process_webhook
        data = await request.json()
        logger.info("received webhook from telegram")
        await process_webhook(data)
        return {"status": "ok"}
    except Exception as exc:
        logger.error("webhook processing error: %s", exc)
        return {"status": "error", "message": str(exc)}


def main():
    s = get_settings()
    logger.info("starting FlatAgent on %s:%s", s.host, s.port)
    uvicorn.run(
        "main:app",
        host=s.host,
        port=s.port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
