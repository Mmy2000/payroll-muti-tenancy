"""Splitting a loan into monthly installments. Pure: no database.

PayRole (Loans/views.py `_split_instalments`): equal installments rounded down to the cent, the
remainder on the last one, so the installments always add up to the loan exactly.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")


def split(amount: Decimal, count: int) -> list[Decimal]:
    if count < 1:
        raise ValueError("at least one installment")
    each = (amount / count).quantize(CENT, rounding=ROUND_DOWN)
    return [each] * (count - 1) + [amount - each * (count - 1)]
