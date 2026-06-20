"""Bracket lookup helpers for IRS Pub 15-T and NY/NYC withholding tables."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

BracketRow = tuple[Decimal, Decimal, Decimal, Decimal, Decimal]


def _d(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def bracket_withholding(net_wages: Decimal, rows: Sequence[BracketRow]) -> Decimal:
    """Apply NY/NYC Method II: (net - col3) * col4 + col5."""
    wages = _d(net_wages)
    if wages <= 0:
        return Decimal("0")
    for at_least, less_than, subtract, rate, base in rows:
        if wages >= at_least and wages < less_than:
            return (wages - subtract) * rate + base
    if rows:
        at_least, _, subtract, rate, base = rows[-1]
        if wages >= at_least:
            return (wages - subtract) * rate + base
    return Decimal("0")


def annual_bracket_tax(annual_wages: Decimal, rows: Sequence[BracketRow]) -> Decimal:
    """Apply IRS Pub 15-T percentage method annual schedules."""
    wages = _d(annual_wages)
    if wages <= 0:
        return Decimal("0")
    for at_least, less_than, base, rate, excess_over in rows:
        if wages >= at_least and wages < less_than:
            return base + (wages - excess_over) * rate
    if rows:
        at_least, _, base, rate, excess_over = rows[-1]
        if wages >= at_least:
            return base + (wages - excess_over) * rate
    return Decimal("0")


def q2(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
