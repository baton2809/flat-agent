"""Mortgage calculation node."""

import re
from typing import Dict
from langchain_core.messages import AIMessage, HumanMessage
from agent.state import AgentState
from agent.tools.mortgage_calc import calculate_mortgage
from agent.tools.cbr_tool import get_current_rate
from agent.exceptions import ValidationError
from agent.error_handler import node_error_response

_CBR_RATE_SPREAD_PCT = 2.0


def _parse_amount_from(text: str):
    """Return loan amount in rubles parsed from text, or None."""
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:млн|миллион|тысяч|тыс|руб|₽)', text.lower())
    if not match:
        return None
    val = float(match.group(1).replace(',', '.'))
    tl = text.lower()
    if any(w in tl for w in ('млн', 'миллион')):
        return val * 1_000_000
    if any(w in tl for w in ('тыс', 'тысяч')):
        return val * 1_000
    return val


def _parse_term_from(text: str):
    """Return loan term in months parsed from text, or None."""
    match = re.search(r'(\d+)\s*(?:год|лет|мес|месяц)', text.lower())
    if not match:
        return None
    val = int(match.group(1))
    return val * 12 if any(w in text.lower() for w in ('год', 'лет')) else val


def _parse_simple_rate_from(text: str):
    """Return interest rate from text, or None. Does not perform CBR lookup."""
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', text)
    if match:
        return float(match.group(1).replace(',', '.'))
    match = re.search(
        r'(?:ставк[еуа]|под|процент(?:ов|ная)?(?:\s+ставка)?)\s+(\d+(?:[.,]\d+)?)',
        text.lower(),
    )
    if match:
        return float(match.group(1).replace(',', '.'))
    return None


def mortgage_node(state: AgentState) -> Dict:
    """Handle mortgage calculation requests."""
    messages = list(state.get('messages', []))[-10:]  # sliding window — не передаём в LLM >10 сообщений
    
    last_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break
    
    amount_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:млн|миллион|тысяч|тыс|rub|rubles|руб|₽)', last_message.lower())
    rate_match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', last_message)
    term_match = re.search(r'(\d+)\s*(?:month|months|year|years|мес|месяц|год|лет)', last_message.lower())
    
    amount = None
    if amount_match:
        amount_str = amount_match.group(1).replace(',', '.').replace(' ', '')
        amount = float(amount_str)
        if any(word in last_message.lower() for word in ['млн', 'миллион']):
            amount = amount * 1000000
        elif any(word in last_message.lower() for word in ['тыс', 'тысяч']):
            amount = amount * 1000
    
    rate = None
    user_specified_rate = None
    cbr_rate_used = None

    if rate_match:
        rate = float(rate_match.group(1).replace(',', '.'))
        user_specified_rate = rate
    else:
        # "ключевая плюс 3 процента" / "ключевая + 3%"
        cbr_spread_match = re.search(
            r'ключев[а-я]*\s+(?:плюс|\+)\s*(\d+(?:[.,]\d+)?)',
            last_message.lower()
        )
        if cbr_spread_match:
            spread = float(cbr_spread_match.group(1).replace(',', '.'))
            try:
                cbr_info = get_current_rate()
                cbr_num = re.search(r'(\d+(?:[.,]\d+)?)', cbr_info)
                if cbr_num:
                    cbr_rate_used = float(cbr_num.group(1).replace(',', '.'))
                    rate = cbr_rate_used + spread
                    user_specified_rate = rate
            except Exception:
                pass
        else:
            # Try to parse rate written without % sign: "ставке 10", "под 10", "10 процент"
            rate_word_match = re.search(
                r'(?:ставк[еуа]|под|процент(?:ов|ная)?(?:\s+ставка)?)\s+(\d+(?:[.,]\d+)?)',
                last_message.lower()
            )
            if rate_word_match:
                rate = float(rate_word_match.group(1).replace(',', '.'))
                user_specified_rate = rate
            else:
                try:
                    current_rate_info = get_current_rate()
                    rate_match_cbr = re.search(r'(\d+(?:[.,]\d+)?)', current_rate_info)
                    if rate_match_cbr:
                        rate = float(rate_match_cbr.group(1).replace(',', '.')) + _CBR_RATE_SPREAD_PCT
                except Exception:
                    pass
    
    term = None
    if term_match:
        term_value = int(term_match.group(1))
        if any(word in last_message.lower() for word in ['year', 'years', 'год', 'лет']):
            term = term_value * 12
        else:
            term = term_value

    # If any param is still missing, scan older messages (newest first) to fill gaps
    if not amount or not term or (user_specified_rate is None and cbr_rate_used is None):
        for msg in reversed(messages):
            if not isinstance(msg, HumanMessage) or msg.content == last_message:
                continue
            if not amount:
                amount = _parse_amount_from(msg.content)
            if not term:
                term = _parse_term_from(msg.content)
            if user_specified_rate is None and cbr_rate_used is None:
                r = _parse_simple_rate_from(msg.content)
                if r is not None:
                    rate = r
                    user_specified_rate = r
            if amount and term and user_specified_rate is not None:
                break

    if amount and rate and term:
        try:
            result = calculate_mortgage(amount, rate, term)
            if cbr_rate_used is not None:
                spread = rate - cbr_rate_used
                rate_line = f"ключевая {cbr_rate_used}% + {spread}% = {rate}%"
            else:
                display_rate = user_specified_rate if user_specified_rate is not None else rate
                rate_line = f"{display_rate}%"
            response = f"""Расчет ипотеки:
Сумма кредита: {amount:,.0f} руб.
Процентная ставка: {rate_line}
Срок: {term} месяцев ({term//12} лет)

Результаты:
Ежемесячный платеж: {result['monthly_payment']:,.2f} руб.
Общая сумма выплат: {result['total_payment']:,.2f} руб.
Переплата: {result['overpayment']:,.2f} руб.
Процент переплаты: {result['overpayment_percent']:.1f}%"""
            new_message = AIMessage(content=response)
        except ValueError as e:
            return node_error_response(ValidationError(str(e)), __name__)
        except Exception as e:
            return node_error_response(e, __name__)
    else:
        missing = []
        if not amount:
            missing.append("сумма кредита")
        if not rate:
            missing.append("процентная ставка")
        if not term:
            missing.append("срок кредита в месяцах")
        
        response = f"Для расчета ипотеки необходимо указать: {', '.join(missing)}. Пожалуйста, предоставьте эту информацию."
        new_message = AIMessage(content=response)
    
    return {"messages": [new_message]}