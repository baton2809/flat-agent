"""Intent router: fast-path heuristics + single structured LLM call."""

import logging
from typing import Dict, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage
from agent.state import AgentState
from agent.direct_llm_call import llm_call_direct, create_dialog

logger = logging.getLogger(__name__)

_ROUTE = Literal["mortgage", "compare", "search", "chat"]


class RouteDecision(BaseModel):
    """Structured routing decision returned by the LLM classifier."""

    route: _ROUTE = Field(
        description=(
            "mortgage - ипотека, кредит, расчёт платежа, ставки; "
            "compare - сравнение вариантов, что лучше, первичка vs вторичка; "
            "search - найти квартиру, новостройки, конкретный ЖК, цены в районе; "
            "chat - консультация, документы, советы, юридические вопросы"
        )
    )
    reasoning: str = Field(default="", description="Краткое обоснование выбора")


_SYSTEM_PROMPT = (
    "Ты маршрутизатор запросов для ассистента по недвижимости. "
    "Определи намерение пользователя и выбери одну категорию."
)

_CLASSIFY_PROMPT = """\
Запрос пользователя: «{message}»

Категории:
• mortgage - ипотека, кредит, расчёт ежемесячного платежа, ставка ЦБ в контексте займа
• compare  - явное сравнение вариантов («лучше», «или», «vs», первичка vs вторичка)
• search   - поиск/подбор квартиры, запрос цен по городу или ЖК, новостройки
• chat     - консультация, юридические вопросы, документы, общие советы

Выбери категорию."""

_MORTGAGE_CALC_MARKERS = ("Расчет ипотеки", "Ежемесячный платеж", "Переплата")
_MORTGAGE_FOLLOWUP_KW = (
    "такое же", "аналогич", "те же",
    "вторичк", "вторичн",
    "первичк", "первичн",
    "другой срок", "другую ставку", "другую сумму",
)
_COMPARE_EXPLICIT = (" или ", " vs ", "лучше", "хуже", "разница", "отличие", "сравни")


def _last_ai_was_mortgage(messages) -> bool:
    """Return True if the most recent AI message contains a mortgage calculation result."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return any(m in msg.content for m in _MORTGAGE_CALC_MARKERS)
    return False


def _is_mortgage_followup(last_message: str, messages) -> bool:
    """Return True when user is refining a previous mortgage request, not comparing options."""
    if not _last_ai_was_mortgage(messages):
        return False
    msg = last_message.lower()
    has_followup = any(kw in msg for kw in _MORTGAGE_FOLLOWUP_KW)
    has_compare = any(kw in msg for kw in _COMPARE_EXPLICIT)
    return has_followup and not has_compare


def router_node(state: AgentState) -> Dict:
    """Route the latest user message to the correct processing node.

    Strategy:
    1. Fast-path: deterministic rules for greetings, CBR queries, clear search patterns.
       No LLM call - zero latency.
    2. Structured LLM call: single GigaChat call returning RouteDecision.
       Falls back to 'chat' on any error.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"route": "chat"}

    last_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    if not last_message.strip():
        return {"route": "chat"}

    if _is_direct_chat_query(last_message):
        logger.debug("fast-path chat: %r", last_message[:60])
        return {"route": "chat"}

    if _is_cbr_request(last_message.lower()):
        logger.debug("fast-path chat (cbr): %r", last_message[:60])
        return {"route": "chat"}

    if _is_direct_search_query(last_message):
        logger.debug("fast-path search: %r", last_message[:60])
        return {"route": "search"}

    if _is_mortgage_followup(last_message, messages):
        logger.debug("fast-path mortgage (follow-up): %r", last_message[:60])
        return {"route": "mortgage"}

    route = _classify_by_llm(last_message)
    logger.debug("llm route: %r -> %s", last_message[:60], route)
    return {"route": route}


def _is_direct_chat_query(message: str) -> bool:
    """Return True for messages that should go straight to chat without LLM."""
    msg = message.lower().strip()
    patterns = (
        # bot identity
        "ты кто", "кто ты", "что ты умеешь", "что ты можешь",
        "как тебя зовут", "твоё имя", "твое имя",
        "расскажи о себе", "представься",
        # user memory
        "как меня зовут", "что ты знаешь обо мне", "ты меня помнишь",
        # greetings / closings
        "привет", "здравствуй", "здравствуйте", "добрый день",
        "добрый вечер", "доброе утро", "хай", "hello",
        "спасибо", "благодарю", "пока", "до свидания",
        # consultation starters that LLM normalization misroutes
        "как проверить", "как оформить", "как выбрать", "как снизить",
        "как получить", "как узнать", "как избежать",
        "зачем нужен", "зачем нужна", "для чего нужен", "нужен ли",
        "что такое", "что означает", "что нужно", "какие документы",
        "стоит ли", "имеет смысл покупать",
    )
    return any(p in msg for p in patterns)


_CURRENCY_STEMS = ("дол", "дал", "евр", "юан", "usd", "eur", "cny")


def _is_cbr_request(msg: str) -> bool:
    """Return True if the message is about CBR key rate or currency exchange."""
    explicit = (
        "ключевая ставка", "ставка цб", "ставка центрального банка",
        "ставка банка России", "цб ставка",
        "курс валют", "курс доллар", "курс евро", "курс юан",
        "курс usd", "курс eur", "курс cny",
        "доллар сегодня", "евро сегодня", "юань сегодня",
        "какой курс", "курс на сегодня", "текущий курс", "курсы валют",
    )
    if any(kw in msg for kw in explicit):
        return True

    is_cbr = "цб" in msg or "центральный банк" in msg or "центробанк" in msg
    if is_cbr and ("ставк" in msg or "ключев" in msg):
        return True

    if "курс" in msg and any(w in msg for w in ("валют", "доллар", "евро", "юань")):
        return True

    if "курс" in msg:
        for word in msg.split():
            if any(word.startswith(stem) for stem in _CURRENCY_STEMS):
                return True

    return False


def _is_direct_search_query(message: str) -> bool:
    """Return True for clear apartment search queries that need no LLM."""
    msg = message.lower().strip()

    if any(msg.startswith(s) for s in ("найди", "найти", "поищи", "ищу квартир", "покажи квартир")):
        return True

    # "квартиры в [city] [price]" without loan terms
    loan_terms = ("ипотек", "кредит", "рассчита", "посчитай", "платеж")
    has_property = "квартир" in msg or "апартамент" in msg
    has_location = any(p in msg for p in (" в ", " рядом", " у ", "в москве", "в спб"))
    if has_property and has_location and not any(t in msg for t in loan_terms):
        return True

    if msg.startswith("новостройки") and not any(t in msg for t in loan_terms):
        return True

    # Price dynamics - needs web search, not compare node
    re_words = ("метр", "квартир", "недвижимост", "новостройк", "вторичк")
    dyn_words = ("вырос", "упал", "снизил", "вырастет", "упадет", "изменил",
                 "динамик", "тренд", "рост цен", "падение цен")
    if any(w in msg for w in re_words) and any(w in msg for w in dyn_words):
        return True

    return False


def _classify_by_llm(message: str) -> _ROUTE:
    """Call GigaChat once and return a validated route.

    Uses function-calling so the model cannot return free text.
    Falls back to 'chat' on any error or unexpected response.
    """
    dialog = create_dialog(
        system_prompt=_SYSTEM_PROMPT,
        user_message=_CLASSIFY_PROMPT.format(message=message),
    )

    try:
        result = llm_call_direct(dialog, structure=RouteDecision, temperature=0.0)

        if isinstance(result, dict):
            route = result.get("route", "chat")
            reasoning = result.get("reasoning", "")
        elif isinstance(result, RouteDecision):
            route = result.route
            reasoning = result.reasoning
        else:
            logger.warning("unexpected llm classifier response type: %s", type(result))
            return "chat"

        if route not in ("mortgage", "compare", "search", "chat"):
            logger.warning("llm returned unknown route %r, defaulting to chat", route)
            return "chat"

        logger.debug("llm classified as %r: %s", route, reasoning)
        return route

    except Exception as exc:
        logger.warning("llm classification failed: %s - defaulting to chat", exc)
        return "chat"
