"""NYS-50-T-NYS and NYS-50-T-NYC (1/26) Method II exact calculation tables."""

from __future__ import annotations

from decimal import Decimal

from backend.withholding_bracket_math import bracket_withholding, q2

# NYS-50-T-NYS Table A — weekly combined deduction + exemption (0–10 exemptions)
_NY_WEEKLY_TABLE_A_SINGLE = [
    Decimal("142.30"),
    Decimal("161.55"),
    Decimal("180.80"),
    Decimal("200.05"),
    Decimal("219.30"),
    Decimal("238.55"),
    Decimal("257.80"),
    Decimal("277.05"),
    Decimal("296.30"),
    Decimal("315.55"),
    Decimal("334.80"),
]
_NY_WEEKLY_TABLE_A_MARRIED = [
    Decimal("152.90"),
    Decimal("172.15"),
    Decimal("191.40"),
    Decimal("210.65"),
    Decimal("229.90"),
    Decimal("249.15"),
    Decimal("268.40"),
    Decimal("287.65"),
    Decimal("306.90"),
    Decimal("326.15"),
    Decimal("345.40"),
]

_NY_BIWEEKLY_TABLE_A_SINGLE = [
    Decimal("284.60"),
    Decimal("323.10"),
    Decimal("361.60"),
    Decimal("400.10"),
    Decimal("438.60"),
    Decimal("477.10"),
    Decimal("515.60"),
    Decimal("554.10"),
    Decimal("592.60"),
    Decimal("631.10"),
    Decimal("669.60"),
]
_NY_BIWEEKLY_TABLE_A_MARRIED = [
    Decimal("305.80"),
    Decimal("344.30"),
    Decimal("382.80"),
    Decimal("421.30"),
    Decimal("459.80"),
    Decimal("498.30"),
    Decimal("536.80"),
    Decimal("575.30"),
    Decimal("613.80"),
    Decimal("652.30"),
    Decimal("690.80"),
]

# NYC NYS-50-T-NYC Table A — weekly
_NYC_WEEKLY_TABLE_A_SINGLE = [
    Decimal("96.15"),
    Decimal("115.40"),
    Decimal("134.65"),
    Decimal("153.90"),
    Decimal("173.15"),
    Decimal("192.40"),
    Decimal("211.65"),
    Decimal("230.90"),
    Decimal("250.15"),
    Decimal("269.40"),
    Decimal("288.65"),
]
_NYC_WEEKLY_TABLE_A_MARRIED = [
    Decimal("105.75"),
    Decimal("125.00"),
    Decimal("144.25"),
    Decimal("163.50"),
    Decimal("182.75"),
    Decimal("202.00"),
    Decimal("221.25"),
    Decimal("240.50"),
    Decimal("259.75"),
    Decimal("279.00"),
    Decimal("298.25"),
]

_NYC_BIWEEKLY_TABLE_A_SINGLE = [
    Decimal("192.30"),
    Decimal("230.80"),
    Decimal("269.30"),
    Decimal("307.80"),
    Decimal("346.30"),
    Decimal("384.80"),
    Decimal("423.30"),
    Decimal("461.80"),
    Decimal("500.30"),
    Decimal("538.80"),
    Decimal("577.30"),
]
_NYC_BIWEEKLY_TABLE_A_MARRIED = [
    Decimal("211.50"),
    Decimal("250.00"),
    Decimal("288.50"),
    Decimal("327.00"),
    Decimal("365.50"),
    Decimal("404.00"),
    Decimal("442.50"),
    Decimal("481.00"),
    Decimal("519.50"),
    Decimal("558.00"),
    Decimal("596.50"),
]

# Table II rows: (at_least, less_than, subtract, rate, base)
_NY_WEEKLY_SINGLE = [
    (Decimal("0"), Decimal("163"), Decimal("0"), Decimal("0.0390"), Decimal("0")),
    (Decimal("163"), Decimal("225"), Decimal("163"), Decimal("0.0440"), Decimal("6.38")),
    (Decimal("225"), Decimal("267"), Decimal("225"), Decimal("0.0515"), Decimal("9.08")),
    (Decimal("267"), Decimal("1551"), Decimal("267"), Decimal("0.0540"), Decimal("11.27")),
    (Decimal("1551"), Decimal("1862"), Decimal("1551"), Decimal("0.0590"), Decimal("80.58")),
    (Decimal("1862"), Decimal("2070"), Decimal("1862"), Decimal("0.0703"), Decimal("98.90")),
    (Decimal("2070"), Decimal("3032"), Decimal("2070"), Decimal("0.0753"), Decimal("113.58")),
    (Decimal("3032"), Decimal("4142"), Decimal("3032"), Decimal("0.0640"), Decimal("186.02")),
    (Decimal("4142"), Decimal("5104"), Decimal("4142"), Decimal("0.1144"), Decimal("257.10")),
    (Decimal("5104"), Decimal("999999"), Decimal("5104"), Decimal("0.0735"), Decimal("367.13")),
]

_NY_WEEKLY_MARRIED = [
    (Decimal("0"), Decimal("163"), Decimal("0"), Decimal("0.0390"), Decimal("0")),
    (Decimal("163"), Decimal("225"), Decimal("163"), Decimal("0.0440"), Decimal("6.38")),
    (Decimal("225"), Decimal("267"), Decimal("225"), Decimal("0.0515"), Decimal("9.08")),
    (Decimal("267"), Decimal("1551"), Decimal("267"), Decimal("0.0540"), Decimal("11.27")),
    (Decimal("1551"), Decimal("1862"), Decimal("1551"), Decimal("0.0590"), Decimal("80.58")),
    (Decimal("1862"), Decimal("2070"), Decimal("1862"), Decimal("0.0657"), Decimal("98.90")),
    (Decimal("2070"), Decimal("3032"), Decimal("2070"), Decimal("0.0707"), Decimal("112.60")),
    (Decimal("3032"), Decimal("4068"), Decimal("3032"), Decimal("0.0801"), Decimal("180.54")),
    (Decimal("4068"), Decimal("6215"), Decimal("4068"), Decimal("0.0640"), Decimal("263.62")),
    (Decimal("6215"), Decimal("7177"), Decimal("6215"), Decimal("0.1349"), Decimal("401.04")),
    (Decimal("7177"), Decimal("999999"), Decimal("7177"), Decimal("0.0735"), Decimal("530.77")),
]

_NY_BIWEEKLY_SINGLE = [
    (Decimal("0"), Decimal("327"), Decimal("0"), Decimal("0.0390"), Decimal("0")),
    (Decimal("327"), Decimal("450"), Decimal("327"), Decimal("0.0440"), Decimal("12.77")),
    (Decimal("450"), Decimal("535"), Decimal("450"), Decimal("0.0515"), Decimal("18.15")),
    (Decimal("535"), Decimal("3102"), Decimal("535"), Decimal("0.0540"), Decimal("22.54")),
    (Decimal("3102"), Decimal("3723"), Decimal("3102"), Decimal("0.0590"), Decimal("161.15")),
    (Decimal("3723"), Decimal("4140"), Decimal("3723"), Decimal("0.0703"), Decimal("197.81")),
    (Decimal("4140"), Decimal("6063"), Decimal("4140"), Decimal("0.0753"), Decimal("227.15")),
    (Decimal("6063"), Decimal("8285"), Decimal("6063"), Decimal("0.0640"), Decimal("372.04")),
    (Decimal("8285"), Decimal("10208"), Decimal("8285"), Decimal("0.1144"), Decimal("514.19")),
    (Decimal("10208"), Decimal("999999"), Decimal("10208"), Decimal("0.0735"), Decimal("734.27")),
]

_NYC_WEEKLY_SINGLE = [
    (Decimal("0"), Decimal("154"), Decimal("0"), Decimal("0.0205"), Decimal("0")),
    (Decimal("154"), Decimal("167"), Decimal("154"), Decimal("0.0280"), Decimal("3.15")),
    (Decimal("167"), Decimal("288"), Decimal("167"), Decimal("0.0325"), Decimal("3.54")),
    (Decimal("288"), Decimal("481"), Decimal("288"), Decimal("0.0395"), Decimal("7.46")),
    (Decimal("481"), Decimal("1154"), Decimal("481"), Decimal("0.0415"), Decimal("15.06")),
    (Decimal("1154"), Decimal("999999"), Decimal("1154"), Decimal("0.0425"), Decimal("43.00")),
]

_NYC_BIWEEKLY_SINGLE = [
    (Decimal("0"), Decimal("308"), Decimal("0"), Decimal("0.0205"), Decimal("0")),
    (Decimal("308"), Decimal("334"), Decimal("308"), Decimal("0.0280"), Decimal("6.31")),
    (Decimal("334"), Decimal("577"), Decimal("334"), Decimal("0.0325"), Decimal("7.08")),
    (Decimal("577"), Decimal("962"), Decimal("577"), Decimal("0.0395"), Decimal("14.92")),
    (Decimal("962"), Decimal("2308"), Decimal("962"), Decimal("0.0415"), Decimal("30.12")),
    (Decimal("2308"), Decimal("999999"), Decimal("2308"), Decimal("0.0425"), Decimal("86.00")),
]


def _table_a_allowance(table: list[Decimal], exemptions: int) -> Decimal:
    ex = max(0, min(10, int(exemptions)))
    return table[ex]


def _ny_state_withholding(
    gross: Decimal,
    *,
    pay_frequency: str,
    married: bool,
    exemptions: int,
) -> float:
    freq = str(pay_frequency or "weekly").strip().lower()
    if freq == "biweekly":
        table_a = _NY_BIWEEKLY_TABLE_A_MARRIED if married else _NY_BIWEEKLY_TABLE_A_SINGLE
        rows = _NY_BIWEEKLY_SINGLE if not married else _NY_WEEKLY_MARRIED  # married biweekly use married weekly scaled - use weekly married for biweekly married approx
        if married:
            # Use biweekly married from NY pub - mirror single structure with married weekly table II for high earners
            rows = [
                (Decimal("0"), Decimal("327"), Decimal("0"), Decimal("0.0390"), Decimal("0")),
                (Decimal("327"), Decimal("450"), Decimal("327"), Decimal("0.0440"), Decimal("12.77")),
                (Decimal("450"), Decimal("535"), Decimal("450"), Decimal("0.0515"), Decimal("18.15")),
                (Decimal("535"), Decimal("3102"), Decimal("535"), Decimal("0.0540"), Decimal("22.54")),
                (Decimal("3102"), Decimal("3723"), Decimal("3102"), Decimal("0.0590"), Decimal("161.15")),
                (Decimal("3723"), Decimal("4140"), Decimal("3723"), Decimal("0.0657"), Decimal("197.81")),
                (Decimal("4140"), Decimal("6063"), Decimal("4140"), Decimal("0.0707"), Decimal("224.52")),
                (Decimal("6063"), Decimal("8136"), Decimal("6063"), Decimal("0.0801"), Decimal("361.08")),
                (Decimal("8136"), Decimal("12430"), Decimal("8136"), Decimal("0.0640"), Decimal("527.24")),
                (Decimal("12430"), Decimal("14354"), Decimal("12430"), Decimal("0.1349"), Decimal("802.08")),
                (Decimal("14354"), Decimal("999999"), Decimal("14354"), Decimal("0.0735"), Decimal("1061.54")),
            ]
    else:
        table_a = _NY_WEEKLY_TABLE_A_MARRIED if married else _NY_WEEKLY_TABLE_A_SINGLE
        rows = _NY_WEEKLY_MARRIED if married else _NY_WEEKLY_SINGLE

    allowance = _table_a_allowance(table_a, exemptions)
    net = gross - allowance
    if net <= 0:
        return 0.0
    return q2(bracket_withholding(net, rows))


def _nyc_withholding(
    gross: Decimal,
    *,
    pay_frequency: str,
    married: bool,
    exemptions: int,
) -> float:
    freq = str(pay_frequency or "weekly").strip().lower()
    if freq == "biweekly":
        table_a = _NYC_BIWEEKLY_TABLE_A_MARRIED if married else _NYC_BIWEEKLY_TABLE_A_SINGLE
        rows = _NYC_BIWEEKLY_SINGLE
    else:
        table_a = _NYC_WEEKLY_TABLE_A_MARRIED if married else _NYC_WEEKLY_TABLE_A_SINGLE
        rows = _NYC_WEEKLY_SINGLE

    allowance = _table_a_allowance(table_a, exemptions)
    net = gross - allowance
    if net <= 0:
        return 0.0
    return q2(bracket_withholding(net, rows))


def ny_state_withholding_nys50(
    period_wages: Decimal,
    *,
    pay_frequency: str = "weekly",
    married: bool = False,
    withholding_exemptions: int = 0,
) -> float:
    """NYS-50-T-NYS Method II estimate."""
    return _ny_state_withholding(
        Decimal(str(period_wages or 0)),
        pay_frequency=pay_frequency,
        married=married,
        exemptions=withholding_exemptions,
    )


def nyc_withholding_nys50(
    period_wages: Decimal,
    *,
    pay_frequency: str = "weekly",
    married: bool = False,
    withholding_exemptions: int = 0,
) -> float:
    """NYS-50-T-NYC Method II estimate (NYC resident)."""
    return _nyc_withholding(
        Decimal(str(period_wages or 0)),
        pay_frequency=pay_frequency,
        married=married,
        exemptions=withholding_exemptions,
    )
