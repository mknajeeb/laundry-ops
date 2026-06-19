"""Supply usage reporting (Phase 1): orders, doses, and ounces by ET date."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

from backend.rinse_special_instructions import (
    _TOKEN_FAB,
    _TOKEN_HYPO,
    _TOKEN_OXIC,
    _classify_part,
    _split_instruction_parts,
    interpret_special_instructions,
)
from backend.supply_usage_settings import (
    DEFAULT_DOSAGES,
    SUPPLY_DOSAGE_KEYS,
    get_supply_usage_dosages,
)
from backend.ta_helpers import table_exists, table_has_column

SUPPLY_USAGE_PRODUCTS: tuple[str, ...] = SUPPLY_DOSAGE_KEYS

_MAPPING_RULES: tuple[dict[str, str], ...] = (
    {"instructions": "None / default", "supplies": "Tide"},
    {"instructions": "Fabric Softener", "supplies": "Tide + Downy"},
    {"instructions": "Fabric Softener + OxiClean", "supplies": "Tide + Downy + OxiClean"},
    {"instructions": "OxiClean only", "supplies": "Tide + OxiClean"},
    {"instructions": "Hypoallergenic (variations)", "supplies": "All Free & Clear only"},
    {"instructions": "Hypo + OxiClean", "supplies": "All Free & Clear + OxiClean"},
)

_PORTAL_UI_NOISE_RE = re.compile(
    r"(?:vendor\s+notes|vendor\s+price|add\s+new\s+item|split\s+ticket|processed|save\b)",
    re.I,
)
_SPLIT_ORDER_RE = re.compile(r"\bsplit[\s-]order\b", re.I)


def mapping_rules_display() -> list[dict[str, str]]:
    return [dict(r) for r in _MAPPING_RULES]


def _tokens_from_raw(raw: str | None) -> set[str]:
    tokens: set[str] = set()
    for part in _split_instruction_parts(str(raw or "")):
        kind = _classify_part(part)
        if kind and kind != "UNKNOWN":
            tokens.add(kind)
    return tokens


def supplies_for_usage(raw: str | None) -> dict[str, Any]:
    """
    Map special instructions to Phase 1 supply product names.

    Uses rinse_special_instructions tokenization; hypo routes to All Free & Clear.
    """
    parsed = interpret_special_instructions(raw)
    tokens = _tokens_from_raw(raw)
    hypo = _TOKEN_HYPO in tokens
    fab = _TOKEN_FAB in tokens
    oxic = _TOKEN_OXIC in tokens

    if hypo:
        supplies = ["All Free & Clear"]
        if oxic:
            supplies.append("OxiClean")
        interpretation = parsed.get("supply_interpretation") or "Hypoallergenic soap"
        if oxic and "OxiClean" not in interpretation:
            interpretation = f"{interpretation} + OxiClean"
    elif fab and oxic:
        supplies = ["Tide", "Downy", "OxiClean"]
        interpretation = "Soap + softener + OxiClean"
    elif fab:
        supplies = ["Tide", "Downy"]
        interpretation = "Soap + softener"
    elif oxic:
        supplies = ["Tide", "OxiClean"]
        interpretation = "Soap + OxiClean"
    else:
        supplies = ["Tide"]
        interpretation = parsed.get("supply_interpretation") or "Standard soap"

    return {
        "special_instructions_raw": parsed.get("special_instructions_raw"),
        "supply_interpretation": interpretation,
        "supplies_used": supplies,
        "special_instruction_review": bool(parsed.get("special_instruction_review")),
    }


def _strip_portal_ui_noise(text: str) -> str:
    parts = re.split(r"[;\n|]+", text)
    kept: list[str] = []
    for part in parts:
        p = re.sub(r"\s+", " ", part).strip()
        if not p:
            continue
        if _PORTAL_UI_NOISE_RE.search(p) and not _SPLIT_ORDER_RE.search(p):
            continue
        kept.append(p)
    return "; ".join(kept)


def detect_split_order(*texts: str | None) -> bool:
    """True when order labels/tags include a split-order marker (multiplier 2)."""
    for text in texts:
        if not str(text or "").strip():
            continue
        cleaned = _strip_portal_ui_noise(str(text))
        if _SPLIT_ORDER_RE.search(cleaned):
            return True
        if _SPLIT_ORDER_RE.search(str(text)):
            return True
    return False


def split_order_multiplier(*texts: str | None) -> int:
    return 2 if detect_split_order(*texts) else 1


def _display_special_instructions(raw: str | None) -> str | None:
    if not str(raw or "").strip():
        return None
    cleaned = _strip_portal_ui_noise(str(raw))
    return cleaned or None


def _order_row_from_staging(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("special_instructions_raw")
    mapped = supplies_for_usage(raw)
    ticket_id = str(row.get("ticket_id") or row.get("bag_id") or "").strip()
    split_texts = (
        raw,
        row.get("supply_interpretation"),
        row.get("notes"),
        row.get("name_clean"),
    )
    multiplier = split_order_multiplier(*split_texts)
    supplies = list(mapped["supplies_used"])
    doses_by_supply = {s: multiplier for s in supplies}
    return {
        "order_id": ticket_id,
        "ticket_id": ticket_id,
        "customer": row.get("name_clean") or row.get("customer"),
        "special_instructions": _display_special_instructions(raw),
        "special_instructions_raw": raw,
        "supply_interpretation": mapped.get("supply_interpretation"),
        "split_order": multiplier > 1,
        "multiplier": multiplier,
        "supplies_used": supplies,
        "estimated_doses": sum(doses_by_supply.values()),
        "doses_by_supply": doses_by_supply,
        "special_instruction_review": mapped.get("special_instruction_review"),
        "date_clean": row.get("date_clean"),
        "service_type": row.get("service_type"),
        "source": row.get("_source") or "orders_staging",
    }


def _load_staging_orders(cursor, organization_id: int, target_date: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, "orders_staging"):
        return []
    if not table_has_column(cursor, "orders_staging", "ticket_id"):
        return []
    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_si = table_has_column(cursor, "orders_staging", "special_instructions_raw")
    cols = [
        "ticket_id",
        "name_clean",
        "date_clean",
        "service_type",
    ]
    if has_si:
        cols.extend(
            [
                "special_instructions_raw",
                "supply_interpretation",
                "special_instruction_review",
            ]
        )
    where = ["date_clean = %s", "ticket_id IS NOT NULL", "TRIM(ticket_id) != ''"]
    args: list[Any] = [target_date]
    if has_org:
        where.append("organization_id = %s")
        args.append(int(organization_id))
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM orders_staging
        WHERE {" AND ".join(where)}
        ORDER BY name_clean, ticket_id
        """,
        tuple(args),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            item = dict(row)
            item["_source"] = "orders_staging"
            out.append(item)
    return out


def _load_upload_batch_orders(cursor, organization_id: int, target_date: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, "upload_batch_rows") or not table_exists(cursor, "upload_batches"):
        return []
    has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
    has_ticket = table_has_column(cursor, "upload_batch_rows", "ticket_id")
    has_si = table_has_column(cursor, "upload_batch_rows", "special_instructions_raw")
    cols = [
        "ubr.date_clean",
        "ubr.name_clean",
        "ubr.service_type",
    ]
    if has_ticket:
        cols.append("ubr.ticket_id")
    if has_si:
        cols.extend(
            [
                "ubr.special_instructions_raw",
                "ubr.supply_interpretation",
                "ubr.special_instruction_review",
            ]
        )
    org_clause = " AND ub.organization_id = %s" if has_ub_org else ""
    args: list[Any] = [target_date]
    if has_ub_org:
        args.append(int(organization_id))
    ticket_clause = ""
    if has_ticket:
        ticket_clause = " AND ubr.ticket_id IS NOT NULL AND TRIM(ubr.ticket_id) != ''"
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM upload_batch_rows ubr
        INNER JOIN upload_batches ub ON ub.id = ubr.upload_batch_id
        WHERE ubr.date_clean = %s{org_clause}{ticket_clause}
        ORDER BY ubr.name_clean, ubr.ticket_id
        """,
        tuple(args),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            item = dict(row)
            item["_source"] = "upload_batch_rows"
            out.append(item)
    return out


def load_orders_for_supply_usage(
    cursor,
    organization_id: int,
    target_date: date,
) -> list[dict[str, Any]]:
    """Orders for ET date; staging wins over upload batch rows on ticket_id."""
    by_ticket: dict[str, dict[str, Any]] = {}
    for row in _load_upload_batch_orders(cursor, organization_id, target_date):
        tid = str(row.get("ticket_id") or "").strip().upper()
        if tid:
            by_ticket[tid] = row
    for row in _load_staging_orders(cursor, organization_id, target_date):
        tid = str(row.get("ticket_id") or "").strip().upper()
        if tid:
            by_ticket[tid] = row
    return [_order_row_from_staging(r) for r in by_ticket.values()]


def _summary_counts(order_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "orders_analyzed": len(order_rows),
        "split_orders": 0,
        "tide_orders": 0,
        "downy_orders": 0,
        "oxiclean_orders": 0,
        "hypo_orders": 0,
    }
    for row in order_rows:
        supplies = set(row.get("supplies_used") or [])
        if row.get("split_order"):
            counts["split_orders"] += 1
        if "Tide" in supplies:
            counts["tide_orders"] += 1
        if "Downy" in supplies:
            counts["downy_orders"] += 1
        if "OxiClean" in supplies:
            counts["oxiclean_orders"] += 1
        if "All Free & Clear" in supplies:
            counts["hypo_orders"] += 1
    return counts


def _usage_by_supply(
    order_rows: Sequence[Mapping[str, Any]],
    dosages: Mapping[str, float],
) -> dict[str, dict[str, float | int]]:
    usage: dict[str, dict[str, float | int]] = {
        name: {"orders": 0, "doses": 0, "ounces": 0.0} for name in SUPPLY_USAGE_PRODUCTS
    }
    for row in order_rows:
        doses_by_supply = row.get("doses_by_supply") or {}
        supplies = row.get("supplies_used") or []
        for supply in supplies:
            if supply not in usage:
                continue
            doses = int(doses_by_supply.get(supply) or row.get("multiplier") or 1)
            usage[supply]["orders"] += 1
            usage[supply]["doses"] += doses
            oz_per = float(dosages.get(supply) or DEFAULT_DOSAGES.get(supply) or 0)
            usage[supply]["ounces"] = round(float(usage[supply]["ounces"]) + doses * oz_per, 2)
    return usage


def build_supply_usage_report(
    cursor,
    organization_id: int,
    target_date: date,
) -> dict[str, Any]:
    dosages = get_supply_usage_dosages(cursor, organization_id)
    order_rows = load_orders_for_supply_usage(cursor, organization_id, target_date)
    order_rows.sort(key=lambda r: (str(r.get("customer") or "").lower(), str(r.get("order_id") or "")))
    return {
        "date_et": target_date.isoformat(),
        "data_source": "orders_staging + upload_batch_rows (date_clean, staging preferred on duplicate ticket_id)",
        "summary": _summary_counts(order_rows),
        "usage_by_supply": _usage_by_supply(order_rows, dosages),
        "orders": order_rows,
        "dosage_settings": dosages,
        "mapping_rules": mapping_rules_display(),
    }
