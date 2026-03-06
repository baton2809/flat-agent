"""General chat node for consultations."""

import logging
import re
from datetime import date, timedelta
from typing import Dict
from langchain_core.messages import AIMessage, HumanMessage
from agent.state import AgentState
from agent.memory import memory_manager
from agent.direct_llm_call import llm_call_direct, create_dialog
from agent.tools.cbr_tool import get_current_rate, get_cbr_data
from agent.exceptions import LLMError
from agent.error_handler import user_message_for_error

logger = logging.getLogger(__name__)

_MONTHS_RU = {
    'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4,
    'ма': 5, 'июн': 6, 'июл': 7, 'август': 8,
    'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12,
}


def _parse_date_from_message(message: str) -> date:
    """Extract a target date from the user message.

    Handles: сегодня, завтра, послезавтра, 'на 20 февраля', '20.02', '20.02.2026'.
    Returns today if no recognizable date is found.
    """
    msg = message.lower()

    if 'послезавтра' in msg:
        return date.today() + timedelta(days=2)
    if 'завтра' in msg:
        return date.today() + timedelta(days=1)
    if 'сегодня' in msg or 'сейчас' in msg or 'текущ' in msg:
        return date.today()

    # "на 20 февраля" or "20 февраля"
    m = re.search(r'\b(\d{1,2})\s+([а-яё]+)', msg)
    if m:
        day = int(m.group(1))
        month_word = m.group(2)
        for stem, num in _MONTHS_RU.items():
            if month_word.startswith(stem):
                try:
                    return date(date.today().year, num, day)
                except ValueError:
                    pass

    # "DD.MM" or "DD.MM.YYYY"
    m = re.search(r'\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b', msg)
    if m:
        try:
            year = int(m.group(3)) if m.group(3) else date.today().year
            return date(year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return date.today()


def chat_node(state: AgentState) -> Dict:
    """Handle general consultation requests using direct LLM calls."""
    messages = state.get('messages', [])
    user_id = state.get('user_id', '')

    last_user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_message = msg.content
            break

    if _is_cbr_request(last_user_message):
        return _handle_cbr_request(last_user_message)

    memory_context = memory_manager.get_memory_context(user_id) if user_id else ""
    user_name = memory_manager.get_user_name(user_id) if user_id else None
    name_line = (
        f"Ты общаешься с пользователем по имени {user_name}. "
        f"Обращайся к нему по имени {user_name}.\n"
    ) if user_name else ""
    memory_section = f"\n{memory_context}" if memory_context else ""

    system_prompt = f"""Ты FlatAgent - Telegram-бот по недвижимости в России. Твоё имя FlatAgent.
{name_line}
Ты умеешь:
- Считать ипотеку (ежемесячный платеж, переплата, общая стоимость)
- Сравнивать первичку и вторичку
- Искать информацию о рынке недвижимости, районах, новостройках
- Отвечать на вопросы о покупке, аренде, документах и юридических аспектах

ОГРАНИЧЕНИЯ:
- Отвечай ТОЛЬКО на вопросы, связанные с недвижимостью. Если вопрос про другое (автомобили, акции, путешествия и т.д.) - вежливо откажись и предложи задать вопрос по теме
- Никогда не предполагай город пользователя самостоятельно - если город важен для ответа, спроси его

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Используй только **жирный** и *курсив* (Telegram Markdown)
- НЕ используй ### заголовки, > цитаты, --- разделители
- Выделяй важную информацию **жирным**
- Используй простые списки с дефисами

Отвечай только на русском языке. Будь конкретным и профессиональным.{memory_section}"""

    previous_messages = []
    recent_messages = messages[-10:] if len(messages) > 10 else messages

    for msg in recent_messages:
        if isinstance(msg, HumanMessage):
            previous_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            previous_messages.append({"role": "assistant", "content": msg.content})

    try:
        dialog = create_dialog(system_prompt, last_user_message, previous_messages[:-1] if previous_messages else None)
        response_content = llm_call_direct(dialog, temperature=0.3)
        new_message = AIMessage(content=response_content)

    except LLMError as e:
        logger.error("chat_node llm call failed: %s", e)
        new_message = AIMessage(content=user_message_for_error(e))
    except Exception as e:
        logger.error("chat_node unexpected error: %s", e)
        new_message = AIMessage(content=user_message_for_error(e))

    return {"messages": [new_message]}


def _is_cbr_request(message: str) -> bool:
    """Check if the message is requesting CBR data (key rate or currency exchange rates)."""
    from agent.nodes.router import _is_cbr_request as _router_cbr_check
    return _router_cbr_check(message.lower())


_CURRENCY_STEMS = ('дол', 'дал', 'евр', 'юан', 'usd', 'eur', 'cny')


def _is_currency_in_message(message_lower: str) -> bool:
    """Check if message mentions currency rates (including common typos)."""
    if any(k in message_lower for k in [
        'курс валют', 'курс доллар', 'курс евро', 'курс юан',
        'курс usd', 'курс eur', 'курс cny', 'курс на сегодня',
        'курсы валют',
    ]):
        return True
    # "курс" + exact currency word
    if 'курс' in message_lower and any(
        w in message_lower for w in ['валют', 'доллар', 'евро', 'юань', 'usd', 'eur', 'cny']
    ):
        return True
    # "курс" + typo-tolerant stem matching
    if 'курс' in message_lower:
        for word in message_lower.split():
            if any(word.startswith(stem) for stem in _CURRENCY_STEMS):
                return True
    return False


def _handle_cbr_request(message: str) -> Dict:
    """Handle CBR data requests (key rate and currency exchange rates)."""
    message_lower = message.lower()

    is_rate_request = any(keyword in message_lower for keyword in [
        'ключевая ставка', 'ставка цб', 'ставка центрального банка',
        'центральный банк ставка', 'ставка банка россии', 'цб ставка'
    ]) or (('цб' in message_lower or 'центральный банк' in message_lower) and 'ставка' in message_lower)

    is_currency_request = _is_currency_in_message(message_lower)

    try:
        target_date = _parse_date_from_message(message)

        if is_rate_request and is_currency_request:
            cbr_data = get_cbr_data(target_date)
            response = f"**Актуальная информация от ЦБ РФ:**\n\n{cbr_data}"

        elif is_rate_request:
            rate_info = get_current_rate()
            rate_match = re.search(r'(\d+(?:[.,]\d+)?)', rate_info)
            if rate_match:
                rate_value = rate_match.group(1)
                response = f"**Ключевая ставка ЦБ РФ: {rate_value}%**\n\nДанные получены с сайта cbr.ru"
            else:
                response = f"**Ключевая ставка ЦБ РФ:**\n{rate_info}"

        elif is_currency_request:
            cbr_data = get_cbr_data(target_date)
            lines = cbr_data.split('\n')
            date_line = next((l for l in lines if 'Курсы валют' in l), "")
            currency_lines = [l for l in lines if ('USD' in l or 'EUR' in l or 'CNY' in l)]
            if currency_lines:
                header = date_line if date_line else "Актуальные курсы валют ЦБ РФ"
                response = f"**{header.strip()}**\n" + '\n'.join(currency_lines)
            else:
                response = cbr_data
        else:
            rate_info = get_current_rate()
            response = f"**Ключевая ставка ЦБ РФ:**\n{rate_info}"

    except Exception as e:
        logger.error("cbr request failed: %s", e)
        response = user_message_for_error(e)

    new_message = AIMessage(content=response)
    return {"messages": [new_message]}
