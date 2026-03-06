"""API routes for FlatAgent."""

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)

router = APIRouter()

agent_graph = None


class ChatRequest(BaseModel):
    message: str
    user_id: str


class ChatResponse(BaseModel):
    response: str


class HealthResponse(BaseModel):
    status: str
    agent: str


def set_agent_graph(graph):
    global agent_graph
    agent_graph = graph
    logger.info("agent graph set")


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", agent="FlatAgent")


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    try:
        if not agent_graph:
            raise HTTPException(status_code=500, detail="Агент не инициализирован")

        logger.info("request from user %s: %s", request.user_id, request.message)

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

    except Exception as exc:
        logger.error("error processing request: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
