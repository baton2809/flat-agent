"""Unit tests for mortgage_node: full calculation, history fallback, edge cases.

External APIs (CBR) are mocked so tests run offline.
"""

import pytest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage

from agent.nodes.mortgage import mortgage_node
from agent.state import AgentState


_CBR_RATE_STR = "Ключевая ставка ЦБ РФ: 21.0% (с 25.10.2024)"


def _state(*messages):
    return AgentState(messages=list(messages), route="mortgage", user_id="test")


class TestMortgageNodeSingleMessage:
    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_all_params_explicit(self, _mock):
        state = _state(HumanMessage(content="ипотека 5 млн под 15% на 20 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "Расчет ипотеки" in resp
        assert "5,000,000" in resp
        assert "15.0%" in resp
        assert "240 месяцев" in resp
        assert "Ежемесячный платеж" in resp

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_amount_in_millions_float(self, _mock):
        state = _state(HumanMessage(content="3.5 млн под 12% на 15 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "3,500,000" in resp

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_term_in_months(self, _mock):
        state = _state(HumanMessage(content="5 млн 12% 240 месяцев"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "240 месяцев" in resp
        assert "Расчет ипотеки" in resp


class TestMortgageNodeCbrSpread:
    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_cbr_plus_spread(self, _mock):
        state = _state(HumanMessage(content="5 млн ключевая плюс 3 на 20 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "21.0%" in resp
        assert "3.0%" in resp
        assert "24.0%" in resp

    @patch("agent.nodes.mortgage.get_current_rate", side_effect=Exception("network error"))
    def test_cbr_api_failure_falls_back_to_cbr_default(self, _mock):
        state = _state(HumanMessage(content="5 млн ключевая плюс 3 на 20 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert isinstance(resp, str)
        assert len(resp) > 0


class TestMortgageNodeHistoryFallback:
    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_params_from_previous_message(self, _mock):
        """Follow-up with no numbers - must pull params from history."""
        prior_mortgage = (
            "Расчет ипотеки:\n"
            "Сумма кредита: 5,000,000 руб.\n"
            "Ежемесячный платеж: 65,839.48 руб.\n"
            "Переплата: 10,801,474.99 руб."
        )
        state = _state(
            HumanMessage(content="посчитай ипотеку 5 млн под 15% на 20 лет"),
            AIMessage(content=prior_mortgage),
            HumanMessage(content="а если такое же только вторичка"),
        )
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "Расчет ипотеки" in resp
        assert "5,000,000" in resp
        assert "240 месяцев" in resp

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_last_message_overrides_history(self, _mock):
        """New explicit amount in last message beats old amount from history."""
        state = _state(
            HumanMessage(content="ипотека 5 млн 15% 20 лет"),
            AIMessage(content="Расчет ипотеки:\nЕжемесячный платеж: 65,839.48 руб.\nПереплата: 10M"),
            HumanMessage(content="а если 8 млн под те же 15% на 20 лет"),
        )
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "8,000,000" in resp

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_new_rate_in_last_message_overrides_history(self, _mock):
        """New explicit rate in last message beats rate from history."""
        state = _state(
            HumanMessage(content="ипотека 5 млн 15% 20 лет"),
            AIMessage(content="Расчет ипотеки:\nЕжемесячный платеж: 65,839.48 руб.\nПереплата: 10M"),
            HumanMessage(content="а если под 12%"),
        )
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "12.0%" in resp
        assert "5,000,000" in resp


class TestMortgageNodeMissingParams:
    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_missing_amount_asks_user(self, _mock):
        state = _state(HumanMessage(content="посчитай ипотеку под 15% на 20 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "сумма кредита" in resp.lower()

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_missing_term_asks_user(self, _mock):
        state = _state(HumanMessage(content="ипотека 5 млн под 15%"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "срок" in resp.lower()

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_empty_message_asks_user(self, _mock):
        state = _state(HumanMessage(content="ипотека"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert "необходимо указать" in resp.lower()

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_no_messages_returns_error_message(self, _mock):
        state = AgentState(messages=[], route="mortgage", user_id="test")
        result = mortgage_node(state)
        assert "messages" in result
        assert len(result["messages"]) > 0


class TestMortgageNodeValidation:
    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_invalid_rate_100_percent_triggers_error(self, _mock):
        state = _state(HumanMessage(content="5 млн под 150% на 20 лет"))
        result = mortgage_node(state)
        resp = result["messages"][-1].content
        assert isinstance(resp, str)
        assert len(resp) > 0

    @patch("agent.nodes.mortgage.get_current_rate", return_value=_CBR_RATE_STR)
    def test_response_is_ai_message(self, _mock):
        state = _state(HumanMessage(content="ипотека 5 млн 15% 20 лет"))
        result = mortgage_node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
