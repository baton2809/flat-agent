"""Memory extraction node for long-term user memory."""

import logging
from typing import Dict
from langchain_core.messages import HumanMessage
from agent.state import AgentState
from agent.memory import memory_manager

logger = logging.getLogger(__name__)

_GREETING_PREFIXES = (
    "привет", "здравствуй", "здравствуйте", "добрый день",
    "добрый вечер", "доброе утро", "хай", "hello",
    "спасибо", "благодарю", "пока", "до свидания",
)

_SHORT_MESSAGE_THRESHOLD = 15


def _is_trivial_message(message: str) -> bool:
    """Return True for short or greeting messages that contain no extractable facts."""
    stripped = message.strip().lower()
    if len(stripped) <= _SHORT_MESSAGE_THRESHOLD:
        return True
    return any(stripped.startswith(p) for p in _GREETING_PREFIXES)


def memory_extraction_node(state: AgentState) -> Dict:
    """Extract and store important facts from user messages."""
    messages = state.get("messages", [])
    user_id = state.get("user_id", "")

    if not user_id or not messages:
        return {}

    last_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    if not last_message.strip():
        return {}

    if _is_trivial_message(last_message):
        logger.debug("skipping memory extraction for trivial message")
        return {}

    try:
        fact_extracted = memory_manager.extract_and_store_facts(user_id, last_message)
        if fact_extracted:
            logger.info("extracted and stored fact for user %s", user_id)
    except Exception as exc:
        logger.error("error in memory extraction for user %s: %s", user_id, exc)

    return {}
