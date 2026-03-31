"""Centralized error handling utilities for FlatAgent nodes."""

import logging
from langchain_core.messages import AIMessage

from agent.exceptions import FlatAgentError, LLMError, ExternalAPIError, ValidationError

_USER_MESSAGES: dict = {
    LLMError: "Сервис временно недоступен. Попробуйте повторить запрос через минуту.",
    ExternalAPIError: "Не удалось получить актуальные данные. Попробуйте позже.",
    ValidationError: "Некорректные параметры. Проверьте введённые значения и повторите запрос.",
}

_FALLBACK_MESSAGE = "Произошла ошибка при обработке запроса. Попробуйте ещё раз."


def user_message_for_error(exc: Exception) -> str:
    """Return a Russian user-facing message for the given exception type."""
    for exc_type, msg in _USER_MESSAGES.items():
        if isinstance(exc, exc_type):
            return msg
    return _FALLBACK_MESSAGE


def node_error_response(exc: Exception, node: str) -> dict:
    """Log the error and return a node response dict with an AIMessage."""
    logging.getLogger(node).error("error in %s: %s", node, exc)
    return {"messages": [AIMessage(content=user_message_for_error(exc))]}
