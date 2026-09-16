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


def _oi_int(raw: Any) -> int:
    try:
        oid = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return oid if oid > 0 else 0


def load_estimated_delivery_by_order_instance(
    cursor,
    order_instance_ids: list[int],
) -> dict[int, date]:
    """EDD from the OI's service cycle. Missing EDD is omitted (never invented)."""
    ids = sorted({_oi_int(i) for i in order_instance_ids if _oi_int(i)})
    if not ids or cursor is None:
        return {}
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "rinse_order_instances"):
        return {}
    if not table_exists(cursor, "rinse_wf_service_cycles"):
        return {}
    if not table_has_column(cursor, "rinse_wf_service_cycles", "estimated_delivery_date"):
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT oi.order_instance_id, cyc.estimated_delivery_date
        FROM rinse_order_instances oi
        LEFT JOIN rinse_wf_service_cycles cyc
          ON cyc.id = oi.source_cycle_id
        WHERE oi.order_instance_id IN ({placeholders})
        """,
        tuple(ids),
    )
    out: dict[int, date] = {}
    for row in cursor.fetchall() or []:
        oid = _oi_int(row.get("order_instance_id"))
        edd = _parse_edd(row.get("estimated_delivery_date"))
        if oid and edd is not None:
            out[oid] = edd
    return out


def fill_unique_open_wf_order_instance(cursor, organization_id: int, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set order_instance_id only when a bag has exactly one open WF OI.

    Display enrichment. Does not create, merge, or close order instances.
    """
    missing = []
    for row in rows or []:
        if not isinstance(row, dict) or _oi_int(row.get("order_instance_id")):
            continue
        bag = str(row.get("bag_id") or "").strip().upper()
        if bag:
            missing.append(bag)
    if not missing or cursor is None:
        return rows
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_order_instances"):
        return rows
    placeholders = ",".join(["%s"] * len(sorted(set(missing))))
    cursor.execute(
        f"""
        SELECT bag_id, order_instance_id
        FROM rinse_order_instances
        WHERE organization_id = %s
          AND service_type = 'WF'
          AND completed_at IS NULL
          AND bag_id IN ({placeholders})
        """,
        (int(organization_id), *sorted(set(missing))),
    )
    by_bag: dict[str, list[int]] = {}
    for rec in cursor.fetchall() or []:
        bag = str(rec.get("bag_id") or "").strip().upper()
        oid = _oi_int(rec.get("order_instance_id"))
        if bag and oid:
            by_bag.setdefault(bag, []).append(oid)
    for row in rows:
        if not isinstance(row, dict) or _oi_int(row.get("order_instance_id")):
            continue
        bag = str(row.get("bag_id") or "").strip().upper()
        oids = by_bag.get(bag) or []
        if len(oids) == 1:
            row["order_instance_id"] = oids[0]
        elif len(oids) > 1:
            row["order_instance_ambiguous"] = True
    return rows


def filter_orders_for_display_query(
    orders: list[dict[str, Any]],
    parsed: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Keep OIs that match a parsed display id. Bare bag search passes parsed=None."""
    if not parsed:
        return list(orders or [])
    want_oi = parsed.get("order_instance_id")
    want_edd = parsed.get("estimated_delivery_date")
    kept: list[dict[str, Any]] = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        oid = _oi_int(order.get("order_instance_id"))
        if want_oi:
            if oid == int(want_oi):
                kept.append(order)
            continue
        if want_edd is not None:
            display = str(order.get("order_display_id") or "")
            suffix = f"-OI-{want_edd.strftime('%m%d%Y')}"
            if display.upper().endswith(suffix):
                kept.append(order)
    return kept


def attach_display_order_instances_for_day(
    cursor,
    organization_id: int,
    rows: list[dict[str, Any]],
    selected_date_et: Any,
) -> list[dict[str, Any]]:
    """Display-only OI attach for a selected ET day.

    Prefers an OI completed on that ET date. Otherwise uses the unique open WF OI.
    Multiple matches set ``order_instance_ambiguous`` and ``orders`` and do not pick one.
    Does not create, merge, or close order instances.
    """
    if not rows or cursor is None:
        return rows
    day = _parse_edd(selected_date_et)
    missing_bags = sorted(
        {
            str(row.get("bag_id") or "").strip().upper()
            for row in rows
            if isinstance(row, dict)
            and str(row.get("bag_id") or "").strip()
            and not _oi_int(row.get("order_instance_id"))
        }
    )
    if not missing_bags:
        return rows
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_order_instances"):
        return rows
    placeholders = ",".join(["%s"] * len(missing_bags))
    cursor.execute(
        f"""
        SELECT oi.bag_id, oi.order_instance_id, oi.completed_at, oi.service_type,
               cyc.estimated_delivery_date
        FROM rinse_order_instances oi
        LEFT JOIN rinse_wf_service_cycles cyc ON cyc.id = oi.source_cycle_id
        WHERE oi.organization_id = %s AND oi.bag_id IN ({placeholders})
        """,
        (int(organization_id), *missing_bags),
    )
    fetched = cursor.fetchall()
    if not isinstance(fetched, list):
        return rows
    from backend.rinse_scan_time import system_datetime_to_et

    by_bag: dict[str, list[dict[str, Any]]] = {}
    for rec in fetched:
        if not isinstance(rec, dict):
            continue
        bag = str(rec.get("bag_id") or "").strip().upper()
        oid = _oi_int(rec.get("order_instance_id"))
        if not bag or not oid:
            continue
        completed_et = system_datetime_to_et(rec.get("completed_at"))
        by_bag.setdefault(bag, []).append(
            {
                "bag_id": bag,
                "order_instance_id": oid,
                "service_type": rec.get("service_type"),
                "completed_date_et": completed_et.date().isoformat() if completed_et else None,
                "estimated_delivery_date": (
                    _parse_edd(rec.get("estimated_delivery_date")).isoformat()
                    if _parse_edd(rec.get("estimated_delivery_date"))
                    else None
                ),
                "open": rec.get("completed_at") is None,
            }
        )
    for row in rows:
        if not isinstance(row, dict) or _oi_int(row.get("order_instance_id")):
            continue
        bag = str(row.get("bag_id") or "").strip().upper()
        candidates = list(by_bag.get(bag) or [])
        if day is not None:
            day_key = day.isoformat()
            completed_today = [c for c in candidates if c.get("completed_date_et") == day_key]
            if completed_today:
                candidates = completed_today
            else:
                candidates = [c for c in candidates if c.get("open") and str(c.get("service_type") or "").upper() == "WF"]
        else:
            candidates = [c for c in candidates if c.get("open")]
        if len(candidates) == 1:
            chosen = candidates[0]
            row["order_instance_id"] = chosen["order_instance_id"]
            if chosen.get("estimated_delivery_date"):
                row["estimated_delivery_date"] = chosen["estimated_delivery_date"]
        elif len(candidates) > 1:
            row["order_instance_ambiguous"] = True
            row["orders"] = [
                {
                    "bag_id": c["bag_id"],
                    "order_instance_id": c["order_instance_id"],
                    "estimated_delivery_date": c.get("estimated_delivery_date"),
                }
                for c in candidates
            ]
    stamp_order_display_ids(cursor, rows)
    nested = [
        order
        for row in rows
        if isinstance(row, dict)
        for order in (row.get("orders") or [])
        if isinstance(order, dict)
    ]
    if nested:
        stamp_order_display_ids(cursor, nested)
    return rows


def stamp_order_display_ids(cursor, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach EDD + ``order_display_id`` for rows that already have an OI.

    Does not choose or create an order_instance_id. Display string stays metadata.
    """
    if not rows:
        return rows
    need = [
        _oi_int(r.get("order_instance_id"))
        for r in rows
        if isinstance(r, dict) and not r.get("estimated_delivery_date") and not r.get("edd")
    ]
    edd_by_oi = load_estimated_delivery_by_order_instance(cursor, need)
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = _oi_int(row.get("order_instance_id"))
        existing = row.get("estimated_delivery_date")
        parsed_existing = _parse_edd(existing) if existing else None
        if parsed_existing is not None:
            row["estimated_delivery_date"] = parsed_existing.isoformat()
        elif oid and not row.get("edd"):
            edd = edd_by_oi.get(oid)
            if edd is not None:
                row["estimated_delivery_date"] = edd.isoformat()
        attach_order_display_id(row)
    return rows
