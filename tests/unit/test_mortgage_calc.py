"""Unit tests for the mortgage calculation formula."""

import pytest
from agent.tools.mortgage_calc import calculate_mortgage


class TestCalculateMortgage:
    def test_standard_calculation(self):
        result = calculate_mortgage(5_000_000, 15.0, 240)
        assert result["monthly_payment"] == pytest.approx(65839.48, rel=1e-3)
        assert result["total_payment"] == pytest.approx(15801474.99, rel=1e-3)
        assert result["overpayment"] == pytest.approx(10801474.99, rel=1e-3)
        assert result["overpayment_percent"] == pytest.approx(216.0, rel=1e-2)

    def test_short_term(self):
        result = calculate_mortgage(1_000_000, 12.0, 12)
        assert result["monthly_payment"] > 0
        assert result["total_payment"] > 1_000_000
        # Overpayment for 1 year should be small
        assert result["overpayment_percent"] < 15

    def test_low_rate(self):
        result = calculate_mortgage(3_000_000, 1.0, 60)
        assert result["monthly_payment"] > 0
        # Nearly zero overpayment at 1% for 5 years
        assert result["overpayment_percent"] < 5

    def test_result_keys_present(self):
        result = calculate_mortgage(2_000_000, 10.0, 120)
        assert "monthly_payment" in result
        assert "total_payment" in result
        assert "overpayment" in result
        assert "overpayment_percent" in result

    def test_total_equals_monthly_times_term(self):
        result = calculate_mortgage(4_000_000, 13.0, 180)
        expected_total = result["monthly_payment"] * 180
        assert result["total_payment"] == pytest.approx(expected_total, rel=1e-6)

    def test_overpayment_equals_total_minus_principal(self):
        principal = 6_000_000
        result = calculate_mortgage(principal, 14.0, 300)
        assert result["overpayment"] == pytest.approx(
            result["total_payment"] - principal, rel=1e-6
        )

    def test_zero_amount_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(0, 15.0, 240)

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(-1_000_000, 15.0, 240)

    def test_zero_rate_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(5_000_000, 0, 240)

    def test_rate_over_100_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(5_000_000, 101.0, 240)

    def test_zero_term_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(5_000_000, 15.0, 0)

    def test_negative_term_raises(self):
        with pytest.raises(ValueError):
            calculate_mortgage(5_000_000, 15.0, -1)
