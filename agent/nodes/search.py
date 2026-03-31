"""Search node: thin LangGraph wrapper around search_tool."""

import logging
import re
from typing import Dict
from langchain_core.messages import AIMessage, HumanMessage
from agent.state import AgentState
from agent.tools.search_tool import search_real_estate, format_search_results
from agent.error_handler import node_error_response

logger = logging.getLogger(__name__)

_NAME_PREFIX_RE = re.compile(
    r'^\s*(?:меня зовут|я|мне|зовут)\s+\w+[,.]?\s*',
    re.IGNORECASE,
)


def _clean_search_query(message: str) -> str:
    """Strip self-introduction prefix so it doesn't pollute the search query."""
    return _NAME_PREFIX_RE.sub("", message).strip()


def search_node(state: AgentState) -> Dict:
    """Handle web search requests."""
    messages = state.get('messages', [])

    last_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    search_query = _clean_search_query(last_message)

    try:
        logger.info("search query: %r", search_query[:80])
        results = search_real_estate(search_query)

        if results:
            response = format_search_results(search_query, results)
        else:
            response = """К сожалению, по вашему запросу ничего не найдено.

*Попробуйте:*
- Уточнить район (например: "квартиры в Химках")
- Указать тип жилья ("новостройки", "вторичка")
- Добавить бюджет ("до 10 млн", "от 5 до 8 млн")

Или задайте общий вопрос про недвижимость - я помогу с *консультацией*."""

    except Exception as e:
        return node_error_response(e, __name__)

    return {"messages": [AIMessage(content=response)]}
