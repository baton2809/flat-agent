"""Unit tests for router node fast-path heuristics."""

import pytest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage

from agent.nodes.router import (
    router_node,
    _is_direct_chat_query,
    _is_cbr_request,
    _is_direct_search_query,
    _is_mortgage_followup,
    _last_ai_was_mortgage,
)
from agent.state import AgentState


class TestIsChatQuery:
    @pytest.mark.parametrize("msg", [
        "привет",
        "Здравствуйте",
        "ты кто",
        "что ты умеешь",
        "спасибо",
        "как выбрать квартиру",
        "как проверить застройщика",
        "что такое эскроу",
        "стоит ли покупать",
        "какие документы нужны",
    ])
    def test_chat_patterns_match(self, msg):
        assert _is_direct_chat_query(msg) is True

    @pytest.mark.parametrize("msg", [
        "рассчитай ипотеку 5 млн",
        "найди квартиру в москве",
        "сравни ЖК А и ЖК Б",
        "квартиры рядом с метро",
    ])
    def test_non_chat_patterns_do_not_match(self, msg):
        assert _is_direct_chat_query(msg) is False


class TestIsCbrRequest:
    @pytest.mark.parametrize("msg", [
        "ключевая ставка",
        "ставка цб",
        "курс доллар",
        "курс евро",
        "курс юань",
        "доллар сегодня",
        "какой курс доллара",
        "курсы валют",
        "цб ставка",
    ])
    def test_cbr_patterns_match(self, msg):
        assert _is_cbr_request(msg.lower()) is True

    @pytest.mark.parametrize("msg", [
        "ипотека 5 млн",
        "найди квартиру",
        "привет",
        "ключевая + 3% на ипотеку",
    ])
    def test_non_cbr_patterns_do_not_match(self, msg):
        assert _is_cbr_request(msg.lower()) is False


class TestIsSearchQuery:
    @pytest.mark.parametrize("msg", [
        "найди квартиру в москве",
        "найти студию рядом с метро",
        "поищи однушку в химках",
        "новостройки в подольске",
        "квартиры в купчино до 5 миллионов",
        "квартиры рядом с метро сокольники",
    ])
    def test_search_patterns_match(self, msg):
        assert _is_direct_search_query(msg) is True

    @pytest.mark.parametrize("msg", [
        "рассчитай ипотеку 5 млн",
        "ипотека на квартиру в москве",
        "привет",
    ])
    def test_non_search_patterns_do_not_match(self, msg):
        assert _is_direct_search_query(msg) is False


_MORTGAGE_RESPONSE = (
    "Расчет ипотеки:\n"
    "Сумма кредита: 5,000,000 руб.\n"
    "Ежемесячный платеж: 65,839.48 руб.\n"
    "Переплата: 10,801,474.99 руб."
)


class TestMortgageFollowup:
    def _msgs(self, user_text):
        return [
            HumanMessage(content="посчитай ипотеку 5 млн 15% 20 лет"),
            AIMessage(content=_MORTGAGE_RESPONSE),
            HumanMessage(content=user_text),
        ]

    def test_last_ai_was_mortgage_true(self):
        msgs = [AIMessage(content=_MORTGAGE_RESPONSE)]
        assert _last_ai_was_mortgage(msgs) is True

    def test_last_ai_was_mortgage_false_when_no_ai(self):
        msgs = [HumanMessage(content="привет")]
        assert _last_ai_was_mortgage(msgs) is False

    def test_last_ai_was_mortgage_false_when_different_content(self):
        msgs = [AIMessage(content="Добрый день! Чем могу помочь?")]
        assert _last_ai_was_mortgage(msgs) is False

    @pytest.mark.parametrize("user_msg", [
        "а если такое же только вторичка",
        "а если те же условия но на первичку",
        "посчитай такое же",
        "а если аналогично но другой срок",
        "и для вторичного рынка",
        "а если для вторичной квартиры",
    ])
    def test_followup_patterns_match(self, user_msg):
        msgs = self._msgs(user_msg)
        assert _is_mortgage_followup(user_msg, msgs) is True

    @pytest.mark.parametrize("user_msg", [
        "что лучше первичка или вторичка",
        "сравни первичку и вторичку",
        "первичка vs вторичка - в чём разница",
        "найди квартиру",
        "привет",
    ])
    def test_compare_or_unrelated_not_followup(self, user_msg):
        msgs = self._msgs(user_msg)
        assert _is_mortgage_followup(user_msg, msgs) is False

    def test_no_followup_when_no_prior_mortgage(self):
        msgs = [
            HumanMessage(content="привет"),
            AIMessage(content="Добрый день!"),
            HumanMessage(content="а если такое же только вторичка"),
        ]
        assert _is_mortgage_followup("а если такое же только вторичка", msgs) is False


class TestRouterNode:
    def _state(self, *messages):
        return AgentState(messages=list(messages), route=None, user_id="test")

    def test_empty_messages_returns_chat(self):
        state = AgentState(messages=[], route=None, user_id="test")
        result = router_node(state)
        assert result["route"] == "chat"

    def test_whitespace_message_returns_chat(self):
        state = self._state(HumanMessage(content="   "))
        result = router_node(state)
        assert result["route"] == "chat"

    def test_greeting_goes_to_chat(self):
        state = self._state(HumanMessage(content="привет"))
        result = router_node(state)
        assert result["route"] == "chat"

    def test_cbr_rate_goes_to_chat(self):
        state = self._state(HumanMessage(content="какая ключевая ставка?"))
        result = router_node(state)
        assert result["route"] == "chat"

    def test_search_query_goes_to_search(self):
        state = self._state(HumanMessage(content="найди квартиру в москве"))
        result = router_node(state)
        assert result["route"] == "search"

    def test_mortgage_followup_goes_to_mortgage(self):
        state = self._state(
            HumanMessage(content="5 млн 15% 20 лет"),
            AIMessage(content=_MORTGAGE_RESPONSE),
            HumanMessage(content="а если такое же только вторичка"),
        )
        result = router_node(state)
        assert result["route"] == "mortgage"

    @patch("agent.nodes.router._classify_by_llm", return_value="mortgage")
    def test_llm_fallback_used_for_ambiguous_query(self, mock_llm):
        state = self._state(HumanMessage(content="хочу взять кредит на жильё"))
        result = router_node(state)
        mock_llm.assert_called_once()
        assert result["route"] == "mortgage"

    @patch("agent.nodes.router.llm_call_direct", side_effect=Exception("timeout"))
    def test_llm_failure_defaults_to_chat(self, mock_llm):
        # Patch llm_call_direct inside _classify_by_llm so the try/except inside catches it
        state = self._state(HumanMessage(content="что-то непонятное"))
        result = router_node(state)
        assert result["route"] == "chat"
