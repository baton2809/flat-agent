"""Mortgage calculator tool."""


def calculate_mortgage(amount: float, annual_rate: float, term_months: int) -> dict:
    """Calculate mortgage payment parameters.

    Args:
        amount: Loan amount in rubles (must be > 0).
        annual_rate: Annual interest rate, e.g. 15.0 for 15% (must be in range 0..100).
        term_months: Loan term in months (must be > 0).

    Returns:
        Dictionary with monthly_payment, total_payment, overpayment, overpayment_percent.

    Raises:
        ValueError: If any parameter is out of valid range.
    """
    if amount <= 0:
        raise ValueError(f"сумма кредита должна быть больше 0, получено: {amount}")
    if not (0 < annual_rate <= 100):
        raise ValueError(f"процентная ставка должна быть от 0 до 100, получено: {annual_rate}")
    if term_months <= 0:
        raise ValueError(f"срок кредита должен быть больше 0 месяцев, получено: {term_months}")

    monthly_rate = annual_rate / 12 / 100

    if monthly_rate == 0:
        monthly_payment = amount / term_months
    else:
        monthly_payment = (
            amount * (monthly_rate * (1 + monthly_rate) ** term_months)
            / ((1 + monthly_rate) ** term_months - 1)
        )

    total_payment = monthly_payment * term_months
    overpayment = total_payment - amount
    overpayment_percent = (overpayment / amount) * 100

    return {
        "monthly_payment": round(monthly_payment, 2),
        "total_payment": round(total_payment, 2),
        "overpayment": round(overpayment, 2),
        "overpayment_percent": round(overpayment_percent, 1),
    }
