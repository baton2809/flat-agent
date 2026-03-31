"""API routes for FlatAgent."""

import asyncio
import hmac
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)

router = APIRouter()

agent_graph = None

# ---------------------------------------------------------------------------
# API Key auth
# ---------------------------------------------------------------------------

_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Depends(_api_key_scheme)) -> None:
    """Validate X-API-Key header using constant-time comparison.

    If API_KEY is not set in config → dev mode, auth is skipped.
    """
    from config import get_settings
    expected = get_settings().api_key
    if not expected:
        return  # dev mode — no auth required
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    user_id: str


class ChatResponse(BaseModel):
    response: str


class HealthResponse(BaseModel):
    status: str
    components: dict = {}


# ---------------------------------------------------------------------------
# Graph reference
# ---------------------------------------------------------------------------

def set_agent_graph(graph):
    global agent_graph
    agent_graph = graph
    logger.info("agent graph set")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    from config import get_settings
    from agent.circuit_breaker import gigachat_cb
    from agent.tools.cbr_tool import _rate_cache

    s = get_settings()
    components: dict = {}

    # SQLite
    try:
        db_path = str(s.db_path)
        size_mb = os.path.getsize(db_path) / 1024 / 1024
        db_status = "warning" if size_mb > 50 else "ok"
        if size_mb > 100:
            db_status = "critical"
        components["sqlite"] = {"status": db_status, "size_mb": round(size_mb, 1)}
    except Exception as e:
        components["sqlite"] = {"status": "error", "detail": str(e)}

    # GigaChat circuit breaker
    cb_open = gigachat_cb.is_open()
    components["gigachat"] = {
        "status": "degraded" if cb_open else "ok",
        "circuit_breaker": gigachat_cb.state,
    }

    # CBR cache
    if _rate_cache:
        age_s = time.monotonic() - _rate_cache[1]
        components["cbr_cache"] = {
            "status": "stale" if age_s > 3600 else "fresh",
            "age_seconds": int(age_s),
        }
    else:
        components["cbr_cache"] = {"status": "empty"}

    overall = "ok"
    if any(c.get("status") in ("error", "critical") for c in components.values()):
        overall = "degraded"
    elif any(c.get("status") in ("warning", "stale", "degraded") for c in components.values()):
        overall = "warning"

    return HealthResponse(status=overall, components=components)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    try:
        if not agent_graph:
            raise HTTPException(status_code=500, detail="Агент не инициализирован")

        logger.info("request from user %s: %s", request.user_id, request.message[:100])

        config = {"configurable": {"thread_id": request.user_id}}
        input_state = {
            "messages": [HumanMessage(content=request.message)],
            "user_id": request.user_id,
            "route": None,
        }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: agent_graph.invoke(input_state, config)
        )

        ai_messages = [msg for msg in result.get("messages", []) if isinstance(msg, AIMessage)]

        if not ai_messages:
            raise HTTPException(status_code=500, detail="Агент не вернул ответ")

        response_text = ai_messages[-1].content
        logger.info("response for user %s: %s...", request.user_id, response_text[:100])

        return ChatResponse(response=response_text)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("error processing request: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
