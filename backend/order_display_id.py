"""Shared order display identifier: BAGID-OI-MMDDYYYY (EDD).

Display / search only. Database identity remains ``order_instance_id``.
Never use the formatted string as a primary key or action payload id.

Fallback when EDD is unavailable (do not invent a date):
  ``{BAG_ID}-OI-{order_instance_id}``
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# Bare bag + -OI- + 8-digit EDD (MMDDYYYY)
_DISPLAY_ID_RE = re.compile(
    r"^([A-Za-z0-9]+)-OI-(\d{8})$",
    re.IGNORECASE,
)
# Fallback when EDD missing: BAG-OI-<numeric oi>
_FALLBACK_ID_RE = re.compile(
    r"^([A-Za-z0-9]+)-OI-(\d{1,18})$",
    re.IGNORECASE,
)


def _parse_edd(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{8}", s):
        try:
            mm, dd, yyyy = int(s[0:2]), int(s[2:4]), int(s[4:8])
            return date(yyyy, mm, dd)
        except ValueError:
            return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def format_order_display_id(
    bag_id: Any,
    order_instance_id: Any,
    *,
    estimated_delivery_date: Any = None,
    edd: Any = None,
) -> str | None:
    """Format user-facing order id. Prefer EDD; else BAG-OI-<oi>."""
    bag = str(bag_id or "").strip().upper()
    if not bag:
        return None
    try:
        oi = int(order_instance_id)
    except (TypeError, ValueError):
        oi = 0
    if oi <= 0:
        return None
    edd_date = _parse_edd(estimated_delivery_date if estimated_delivery_date is not None else edd)
    if edd_date is not None:
        return f"{bag}-OI-{edd_date.strftime('%m%d%Y')}"
    return f"{bag}-OI-{oi}"


def parse_order_display_id(raw: Any) -> dict[str, Any] | None:
    """Parse a display id into bag_id + optional edd / order_instance_id hint.

    Returns None when the string is not a display-id form (caller should treat
    as bare bag / free text).
    """
    s = str(raw or "").strip()
    if not s or "-OI-" not in s.upper():
        return None
    m = _DISPLAY_ID_RE.fullmatch(s)
    if m:
        bag = m.group(1).upper()
        edd_raw = m.group(2)
        edd = _parse_edd(edd_raw)
        return {
            "bag_id": bag,
            "edd_mmddyyyy": edd_raw,
            "estimated_delivery_date": edd,
            "order_instance_id": None,
            "form": "edd",
        }
    m2 = _FALLBACK_ID_RE.fullmatch(s)
    if m2:
        bag = m2.group(1).upper()
        token = m2.group(2)
        # Prefer EDD only when exactly 8 digits AND a valid calendar date.
        if len(token) == 8:
            edd = _parse_edd(token)
            if edd is not None:
                return {
                    "bag_id": bag,
                    "edd_mmddyyyy": token,
                    "estimated_delivery_date": edd,
                    "order_instance_id": None,
                    "form": "edd",
                }
        try:
            oi = int(token)
        except ValueError:
            return None
        if oi <= 0:
            return None
        return {
            "bag_id": bag,
            "edd_mmddyyyy": None,
            "estimated_delivery_date": None,
            "order_instance_id": oi,
            "form": "oi_fallback",
        }
    return None


def attach_order_display_id(row: dict[str, Any]) -> dict[str, Any]:
    """Mutate-and-return row with ``order_display_id`` when OI is known."""
    if not isinstance(row, dict):
        return row
    disp = format_order_display_id(
        row.get("bag_id"),
        row.get("order_instance_id"),
        estimated_delivery_date=row.get("estimated_delivery_date")
        or row.get("edd")
        or row.get("date_clean"),
    )
    if disp:
        row["order_display_id"] = disp
    return row
