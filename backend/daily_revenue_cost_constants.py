"""Constants for Daily Revenue & Cost module."""

from __future__ import annotations

# Entry workflow states (extensible for approval flow)
ENTRY_STATUS_OPEN = "open"
ENTRY_STATUS_LOCKED = "locked"
ENTRY_STATUS_SUBMITTED = "submitted"
ENTRY_STATUS_APPROVED = "approved"
ENTRY_STATUS_REJECTED = "rejected"
ENTRY_STATUSES = frozenset(
    {ENTRY_STATUS_OPEN, ENTRY_STATUS_LOCKED, ENTRY_STATUS_SUBMITTED, ENTRY_STATUS_APPROVED, ENTRY_STATUS_REJECTED}
)

# Integration source systems
SOURCE_MANUAL = "manual"
SOURCE_WORKLOAD = "workload"
SOURCE_PRODUCTIVITY = "productivity"
SOURCE_PAYROLL = "payroll"
SOURCE_POS = "pos"
SOURCE_STRIPE = "stripe"
SOURCE_CLEANCLOUD = "cleancloud"
SOURCE_ACCOUNTING = "accounting"

BILLING_PER_LB = "per_lb"
BILLING_FLAT = "flat"
BILLING_HYBRID = "hybrid"

DEFAULT_COMMERCIAL_ACCOUNTS = [
    "DHS - Clarkson",
    "DHS - Skillman",
    "DHS - Auburn",
    "DHS - Bedford",
]

DEFAULT_WF_TIERS = [
    {"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.00},
    {"tier_number": 2, "max_lbs": None, "rate_per_lb": 0.95},
]

# Line keys — stable identifiers for integrations
LK_SELF_SERVICE_CASH = "revenue.self_service.cash"
LK_SELF_SERVICE_CARD = "revenue.self_service.card"
LK_DROP_OFF_CASH = "revenue.drop_off.cash"
LK_DROP_OFF_CARD = "revenue.drop_off.card"
LK_RINSE_WF_POUNDS = "revenue.rinse_wf.pounds"
LK_RINSE_WF_AMOUNT = "revenue.rinse_wf.amount"
LK_RINSE_HD_ORDERS = "revenue.rinse_hd.orders"
LK_RINSE_HD_AMOUNT = "revenue.rinse_hd.amount"
LK_RINSE_WI_ORDERS = "revenue.rinse_wi.orders"
LK_RINSE_WI_AMOUNT = "revenue.rinse_wi.amount"
LK_PAYROLL_TOTAL = "payroll.total"
LK_PAYROLL_TAX = "payroll.tax"
LK_COST_RENT = "cost.fixed.rent"
LK_COST_INSURANCE = "cost.fixed.insurance"
LK_COST_PROPERTY_TAX = "cost.fixed.property_tax"
LK_COST_ELECTRICITY = "cost.variable.electricity"
LK_COST_WATER = "cost.variable.water"
LK_COST_GAS = "cost.variable.gas"
LK_COST_SUPPLIES = "cost.variable.supplies"
LK_COST_MAINTENANCE = "cost.variable.maintenance"
LK_COST_ADJUSTMENTS = "cost.variable.adjustments"


def commercial_pounds_key(account_id: int) -> str:
    return f"revenue.commercial.{account_id}.pounds"


def commercial_amount_key(account_id: int) -> str:
    return f"revenue.commercial.{account_id}.amount"


FIXED_COST_KEYS = (LK_COST_RENT, LK_COST_INSURANCE, LK_COST_PROPERTY_TAX)
VARIABLE_COST_KEYS = (
    LK_COST_ELECTRICITY,
    LK_COST_WATER,
    LK_COST_GAS,
    LK_COST_SUPPLIES,
    LK_COST_MAINTENANCE,
    LK_COST_ADJUSTMENTS,
)
