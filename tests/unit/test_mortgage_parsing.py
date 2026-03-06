"""Unit tests for mortgage parameter parsing helpers."""

import pytest
from agent.nodes.mortgage import _parse_amount_from, _parse_term_from, _parse_simple_rate_from


class TestParseAmount:
    @pytest.mark.parametrize("text,expected", [
        ("5 млн", 5_000_000),
        ("5 миллионов", 5_000_000),
        ("5.5 млн", 5_500_000),
        ("3,5 миллиона", 3_500_000),
        ("500 тыс", 500_000),
        ("500 тысяч", 500_000),
        ("5000000 руб", 5_000_000),
        ("5000000₽", 5_000_000),
    ])
    def test_valid_amounts(self, text, expected):
        assert _parse_amount_from(text) == expected

    @pytest.mark.parametrize("text", [
        "под 15%",
        "срок 20 лет",
        "привет",
        "",
    ])
    def test_no_amount_returns_none(self, text):
        assert _parse_amount_from(text) is None


class TestParseTerm:
    @pytest.mark.parametrize("text,expected", [
        ("20 лет", 240),
        ("15 лет", 180),
        ("1 год", 12),
        ("240 месяцев", 240),
        ("12 месяцев", 12),
        ("36 мес", 36),
    ])
    def test_valid_terms(self, text, expected):
        assert _parse_term_from(text) == expected

    @pytest.mark.parametrize("text", [
        "5 млн",
        "под 15%",
        "привет",
        "",
    ])
    def test_no_term_returns_none(self, text):
        assert _parse_term_from(text) is None


class TestParseSimpleRate:
    @pytest.mark.parametrize("text,expected", [
        ("15%", 15.0),
        ("под 12%", 12.0),
        ("ставке 10", 10.0),
        ("ставке 10.5", 10.5),
        ("ставка 7,5", 7.5),
        ("под 16,5%", 16.5),
    ])
    def test_valid_rates(self, text, expected):
        assert _parse_simple_rate_from(text) == expected

    @pytest.mark.parametrize("text", [
        "5 млн",
        "20 лет",
        "привет",
        "",
    ])
    def test_no_rate_returns_none(self, text):
        assert _parse_simple_rate_from(text) is None
