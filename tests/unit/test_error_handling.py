"""Unit tests for error handler and exception hierarchy.

Covers the most common failure modes in LLM agents:
- LLM call failure (timeout, API error)
- External API failure (CBR, search)
- Validation errors from bad user input
- Unknown / unexpected exceptions
"""

import pytest
from langchain_core.messages import AIMessage

from agent.exceptions import LLMError, ExternalAPIError, ValidationError, FlatAgentError
from agent.error_handler import node_error_response


class TestExceptionHierarchy:
    def test_llm_error_is_flat_agent_error(self):
        assert issubclass(LLMError, FlatAgentError)

    def test_external_api_error_is_flat_agent_error(self):
        assert issubclass(ExternalAPIError, FlatAgentError)

    def test_validation_error_is_flat_agent_error(self):
        assert issubclass(ValidationError, FlatAgentError)

    def test_can_catch_all_via_base(self):
        for cls in (LLMError, ExternalAPIError, ValidationError):
            with pytest.raises(FlatAgentError):
                raise cls("test")


class TestNodeErrorResponse:
    def _response_text(self, exc):
        result = node_error_response(exc, "test_node")
        msgs = result.get("messages", [])
        assert len(msgs) == 1
        assert isinstance(msgs[0], AIMessage)
        return msgs[0].content

    def test_llm_error_message_in_russian(self):
        text = self._response_text(LLMError("giga timeout"))
        assert "временно недоступен" in text.lower() or "недоступ" in text.lower()

    def test_external_api_error_message_in_russian(self):
        text = self._response_text(ExternalAPIError("cbr unreachable"))
        assert "данные" in text.lower() or "позже" in text.lower()

    def test_validation_error_message_in_russian(self):
        text = self._response_text(ValidationError("bad amount"))
        assert "параметр" in text.lower() or "некорректн" in text.lower()

    def test_generic_exception_has_fallback_message(self):
        text = self._response_text(Exception("unexpected crash"))
        assert isinstance(text, str)
        assert len(text) > 0

    def test_response_always_has_messages_key(self):
        for exc in (LLMError("x"), ExternalAPIError("x"), ValidationError("x"), Exception("x")):
            result = node_error_response(exc, "node")
            assert "messages" in result

    def test_no_english_in_llm_error_response(self):
        text = self._response_text(LLMError("error"))
        assert any('\u0400' <= c <= '\u04FF' for c in text)

    def test_no_english_in_api_error_response(self):
        text = self._response_text(ExternalAPIError("error"))
        assert any('\u0400' <= c <= '\u04FF' for c in text)


class TestCommonAgentFailureModes:
    """Ensure agent nodes don't crash on typical runtime errors."""

    def test_mortgage_node_handles_cbr_api_down(self):
        from unittest.mock import patch
        from agent.nodes.mortgage import mortgage_node
        from agent.state import AgentState

        state = AgentState(
            messages=[],
            route="mortgage",
            user_id="test",
        )
        with patch("agent.nodes.mortgage.get_current_rate", side_effect=Exception("CBR down")):
            result = mortgage_node(state)
        assert "messages" in result
        assert isinstance(result["messages"][-1], AIMessage)

    def test_mortgage_node_handles_zero_division(self):
        from agent.nodes.mortgage import mortgage_node
        from langchain_core.messages import HumanMessage
        from agent.state import AgentState
        from unittest.mock import patch

        state = AgentState(
            messages=[HumanMessage(content="ипотека 5 млн под 0% на 20 лет")],
            route="mortgage",
            user_id="test",
        )
        with patch("agent.nodes.mortgage.get_current_rate", return_value="Ключевая ставка ЦБ РФ: 21.0%"):
            result = mortgage_node(state)
        assert "messages" in result
        assert isinstance(result["messages"][-1], AIMessage)

    def test_router_node_handles_empty_state(self):
        from agent.nodes.router import router_node
        from agent.state import AgentState

        state = AgentState(messages=[], route=None, user_id="test")
        result = router_node(state)
        assert result["route"] in ("mortgage", "compare", "search", "chat")

    def test_router_node_handles_non_human_only_messages(self):
        from agent.nodes.router import router_node
        from agent.state import AgentState

        state = AgentState(
            messages=[AIMessage(content="Добрый день!")],
            route=None,
            user_id="test",
        )
        result = router_node(state)
        assert result["route"] == "chat"
