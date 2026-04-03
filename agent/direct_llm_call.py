"""Direct LLM call for structured output (function calling) via GigaChat SDK."""

import logging
from typing import List, Dict, Any, Optional
from gigachat import GigaChat
from gigachat.models import (
    Chat,
    Function,
    FunctionParameters,
    Messages,
    MessagesRole,
)
from pydantic import BaseModel
from config import get_settings
from agent.exceptions import LLMError

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1024

_client: Optional[GigaChat] = None


def _get_client() -> GigaChat:
    global _client
    if _client is None:
        s = get_settings()
        _client = GigaChat(
            credentials=s.gigachat_credentials,
            verify_ssl_certs=s.gigachat_verify_ssl,
            scope=s.gigachat_scope,
            model=s.gigachat_model,
        )
        logger.info("direct llm client initialized (verify_ssl=%s)", s.gigachat_verify_ssl)
    return _client


def llm_call_direct(
    dialog: List[Dict[str, str]],
    structure: Optional[BaseModel] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
) -> Any:
    """Call GigaChat directly for structured (function-calling) or plain responses.

    Args:
        dialog: List of messages with 'role' and 'content' keys.
        structure: Optional Pydantic model for structured output via function calling.
        model: GigaChat model name.
        temperature: Generation temperature.

    Returns:
        Parsed structure dict, plain string, or fallback on error.
    """
    if model is None:
        model = get_settings().gigachat_model

    roles_dict = {
        "system": MessagesRole.SYSTEM,
        "user": MessagesRole.USER,
        "assistant": MessagesRole.ASSISTANT,
    }

    gigachat_messages = [
        Messages(role=roles_dict[m["role"]], content=m["content"]) for m in dialog
    ]

    try:
        client = _get_client()

        if structure:
            schema = structure.model_json_schema()
            answer_function = Function(
                name="llm_answer",
                description="Используй эту функцию для формирования ответа пользователю",
                parameters=FunctionParameters(
                    type=schema["type"],
                    properties=schema["properties"],
                    required=schema["required"],
                ),
            )
            chat = Chat(
                messages=gigachat_messages,
                temperature=temperature,
                max_tokens=_MAX_TOKENS,
                functions=[answer_function],
                function_call=answer_function,
            )
            response = client.chat(chat).choices[0]
            if response.finish_reason != "function_call":
                logger.warning("function call expected but not received, falling back to text")
                return response.message.content
            return response.message.function_call.arguments

        chat = Chat(
            messages=gigachat_messages,
            temperature=temperature,
            max_tokens=_MAX_TOKENS,
        )
        return client.chat(chat).choices[0].message.content

    except Exception as exc:
        logger.error("direct llm call failed: %s (%s)", exc, type(exc).__name__)
        if structure:
            return {"error": "LLM call failed", "fallback": True}
        raise LLMError(str(exc)) from exc


def create_dialog(
    system_prompt: str,
    user_message: str,
    previous_messages: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Build a dialog list for llm_call_direct."""
    dialog: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if previous_messages:
        dialog.extend(previous_messages)
    dialog.append({"role": "user", "content": user_message})
    return dialog
