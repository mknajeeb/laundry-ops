"""Canonical payroll worker categories, labels, and payment-recorded helpers.

Try Out is a first-class category (not W-2, 1099, or Temp). Vendor-paid
workflows follow Temp / 1099. Do not infer Try Out from the substring TEMP.
"""

from __future__ import annotations

import re
from typing import Any, Optional

WORKER_CATEGORIES = ("w2", "contractor_1099", "temp", "tryout", "system")

CATEGORY_LABELS = {
    "w2": "W-2 Employee",
    "contractor_1099": "1099 Contractor",
    "temp": "Temp / One-Time",
    "tryout": "Try Out",
    "system": "System user (not on payroll)",
}

VENDOR_RECEIPT_CATEGORIES = frozenset({"temp", "contractor_1099", "tryout"})
SKIP_ACCOUNTANT_CATEGORIES = VENDOR_RECEIPT_CATEGORIES

PAYMENT_RECORDED_PAID = "paid"
PAYMENT_RECORDED_UNPAID = "unpaid"

# Display names for the Finalize Payment vendor picker. Existing "Washmate Inc"
# rows stay as-is; UI may show "Washmate".
PAYMENT_VENDOR_DISPLAY = (
    ("veewash", "VeeWash"),
    ("washmate", "Washmate"),
)

_TRYOUT_CODES = frozenset({"EC_TRYOUT"})
_TEMP_CODES = frozenset({"EC_TEMP"})
_W2_CODES = frozenset({"EC_W2", "WASHPRO_W2"})
_1099_CODES = frozenset({"EC_1099", "WASHMATE_1099", "WASHPRO_1099"})
_SYSTEM_CODES = frozenset({"EC_SYSTEM"})


def category_label(code: Optional[str]) -> str:
    key = str(code or "").strip()
    return CATEGORY_LABELS.get(key, key or "")


def is_vendor_receipt_category(worker_category: Optional[str]) -> bool:
    return str(worker_category or "").strip() in VENDOR_RECEIPT_CATEGORIES


def skips_accountant_review(worker_category: Optional[str]) -> bool:
    return is_vendor_receipt_category(worker_category)


def classify_employment_category(code: Optional[str], name: Optional[str] = None) -> str:
    """Map an employment_categories row to a payroll worker_category.

    Try Out is checked before Temp because 'TRYOUT' contains 'TEMP'.
    """
    code_u = str(code or "").upper().strip()
    name_blob = f"{name or ''} {code_u.lower()}".lower()
    if code_u in _SYSTEM_CODES:
        return "system"
    if _is_tryout(code_u, name_blob):
        return "tryout"
    if code_u in _TEMP_CODES:
        return "temp"
    if code_u in _1099_CODES:
        return "contractor_1099"
    if code_u in _W2_CODES:
        return "w2"
    if "1099" in code_u or "CONTRACTOR" in code_u or re.search(
        r"\b1099\b|contractor|independent|\bic\b", name_blob
    ):
        return "contractor_1099"
    if _is_temp_not_tryout(code_u, name_blob):
        return "temp"
    if re.search(r"W[\s_-]*2|\bW2\b", code_u) or re.search(r"\bw[\s-]*2\b", name_blob):
        return "w2"
    return "w2"


def _is_tryout(code_u: str, name_blob: str) -> bool:
    if code_u in _TRYOUT_CODES:
        return True
    if "TRYOUT" in code_u or "TRY_OUT" in code_u or "TRY-OUT" in code_u:
        return True
    return bool(re.search(r"\btry\s*out\b|\btryout\b", name_blob))


def _is_temp_not_tryout(code_u: str, name_blob: str) -> bool:
    if _is_tryout(code_u, name_blob):
        return False
    if "TEMP" in code_u:
        return True
    return bool(re.search(r"\btemp\b|temporary|seasonal", name_blob))


def convert_tryout_targets() -> tuple[str, ...]:
    return ("temp", "w2", "contractor_1099")


def normalize_payment_recorded(value: Any) -> Optional[str]:
    key = str(value or "").strip().lower()
    if key in (PAYMENT_RECORDED_PAID, PAYMENT_RECORDED_UNPAID):
        return key
    return None


def line_payment_recorded(
    line: Optional[dict] = None,
    details: Optional[dict] = None,
    batch: Optional[dict] = None,
) -> str:
    """Paid vs Unpaid for a finalized payment record.

    Explicit settlement.payment_recorded / line.payment_status=='unpaid' wins.
    Legacy rows without the field keep prior behavior: a paid/closed batch
    counts as paid so existing finalized payroll is unchanged.
    """
    details = details if isinstance(details, dict) else {}
    settlement = details.get("settlement") if isinstance(details.get("settlement"), dict) else {}
    explicit = normalize_payment_recorded(settlement.get("payment_recorded"))
    if explicit:
        return explicit
    line = line or {}
    ps = str(line.get("payment_status") or "").strip().lower()
    if ps == PAYMENT_RECORDED_UNPAID:
        return PAYMENT_RECORDED_UNPAID
    if ps == PAYMENT_RECORDED_PAID:
        return PAYMENT_RECORDED_PAID
    batch_st = str((batch or {}).get("status") or "").strip().lower()
    if batch_st in ("paid", "closed"):
        return PAYMENT_RECORDED_PAID
    return ps or "pending"


def is_payment_recorded_unpaid(
    line: Optional[dict] = None,
    details: Optional[dict] = None,
    batch: Optional[dict] = None,
) -> bool:
    return line_payment_recorded(line, details, batch) == PAYMENT_RECORDED_UNPAID


def is_payment_recorded_paid(
    line: Optional[dict] = None,
    details: Optional[dict] = None,
    batch: Optional[dict] = None,
) -> bool:
    return line_payment_recorded(line, details, batch) == PAYMENT_RECORDED_PAID


def payment_vendor_display_name(name: Optional[str]) -> str:
    raw = str(name or "").strip()
    key = raw.lower()
    if "veewash" in key:
        return "VeeWash"
    if "washmate" in key:
        return "Washmate"
    return raw


def is_payment_vendor_name(name: Optional[str]) -> bool:
    key = str(name or "").strip().lower()
    return "veewash" in key or "washmate" in key
