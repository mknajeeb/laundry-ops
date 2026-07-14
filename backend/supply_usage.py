"""Supply usage reporting: orders, doses, and ounces by first-weight ET day."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_after_ts,
    events_on_or_after,
    first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor,
    ts_valid,
)
from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start
from backend.rinse_scan_purpose import is_split_load_purpose, is_weight_entry_purpose
from backend.rinse_special_instructions import (
    STANDARD_INTERPRETATION,
    format_special_instructions_display,
    interpret_special_instructions,
    _classify_part,
    _parts_for_interpretation,
)
from backend.rinse_washing_chronology import extract_washing_rows_from_events
from backend.supply_usage_settings import (
    DEFAULT_DOSAGES,
    DEFAULT_MAPPING_RULES,
    SUPPLY_DOSAGE_KEYS,
    get_supply_usage_dosages,
    get_supply_usage_mapping_rules,
    mapping_rules_for_display,
)
from backend.ta_helpers import table_exists, table_has_column

SUPPLY_USAGE_PRODUCTS: tuple[str, ...] = SUPPLY_DOSAGE_KEYS

_PORTAL_UI_NOISE_RE = re.compile(
    r"(?:vendor\s+notes|vendor\s+price|add\s+new\s+item|split\s+ticket|processed|save\b)",
    re.I,
)
_SPLIT_ORDER_RE = re.compile(r"\bsplit[\s-]order\b", re.I)


def mapping_rules_display(rules: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    if rules is None:
        rules = DEFAULT_MAPPING_RULES
    return mapping_rules_for_display(rules)


def _tokens_from_raw(raw: str | None) -> set[str]:
    tokens: set[str] = set()
    for part in _parts_for_interpretation(raw):
        kind = _classify_part(part)
        if kind and kind != "UNKNOWN":
            tokens.add(kind)
    return tokens


def _rule_matches(raw: str | None, rule: Mapping[str, Any]) -> bool:
    if rule.get("default"):
        return False
    requires = set(rule.get("requires") or [])
    excludes = set(rule.get("excludes") or [])
    if requires:
        tokens = _tokens_from_raw(raw)
        if not requires <= tokens:
            return False
        if excludes and (excludes & tokens):
            return False
        return True
    pattern = str(rule.get("instructions") or "").strip()
    if not pattern or pattern.lower() == "none / default":
        return False
    return pattern.lower() in str(raw or "").lower()


def _supplies_from_rules(
    raw: str | None,
    rules: Sequence[Mapping[str, Any]],
) -> list[str]:
    for rule in rules:
        if rule.get("default"):
            continue
        if _rule_matches(raw, rule):
            return list(rule.get("supplies") or [])
    for rule in rules:
        if rule.get("default"):
            return list(rule.get("supplies") or ["Tide"])
    return ["Tide"]


def supplies_for_usage(
    raw: str | None,
    rules: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Map special instructions to Phase 1 supply product names.

    Uses configurable mapping rules (token-based defaults or substring patterns).
    """
    rule_list = list(rules or DEFAULT_MAPPING_RULES)
    parsed = interpret_special_instructions(raw)
    supplies = _supplies_from_rules(raw, rule_list)
    hypo = "All Free & Clear" in supplies and "Tide" not in supplies
    fab = "Downy" in supplies
    oxic = "OxiClean" in supplies

    if hypo:
        interpretation = parsed.get("supply_interpretation") or "Hypoallergenic soap"
        if oxic and "OxiClean" not in interpretation:
            interpretation = f"{interpretation} + OxiClean"
    elif fab and oxic:
        interpretation = "Soap + softener + OxiClean"
    elif fab:
        interpretation = "Soap + softener"
    elif oxic:
        interpretation = "Soap + OxiClean"
    else:
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


def detect_split_order(
    *texts: str | None,
    has_split_load_scan: bool = False,
) -> bool:
    """
    Detect portal “split order” wording (informational only for Supply Usage).

    Supply Usage dosing never uses this for processing_units. ``has_split_load_scan``
    is retained for callers/tests but must not drive Supply Usage quantities.
    """
    if has_split_load_scan:
        return True
    for text in texts:
        if not str(text or "").strip():
            continue
        cleaned = _strip_portal_ui_noise(str(text))
        if _SPLIT_ORDER_RE.search(cleaned):
            return True
        if _SPLIT_ORDER_RE.search(str(text)):
            return True
    return False


def si_expects_split_order(*texts: str | None) -> bool:
    """True when special-instruction text mentions Split Order (never from scans)."""
    return detect_split_order(*texts, has_split_load_scan=False)


def split_order_multiplier(
    *texts: str | None,
    has_split_load_scan: bool = False,
) -> int:
    return 2 if detect_split_order(*texts, has_split_load_scan=has_split_load_scan) else 1


def processing_units_from_split_confirmation(*, split_confirmed: bool) -> int:
    """Live processing-unit count: 1 until dual washer loads confirm the split."""
    return 2 if split_confirmed else 1


def processing_units_from_washer_loads(
    events_after_first_weight: Sequence[Mapping[str, Any]],
    *,
    bag_id: str,
) -> dict[str, Any]:
    """
    Canonical split evidence for Supply Usage.

    Reuses washing chronology: distinct post-first-weight ``start-cleaning`` scans
    at washer racks (W-*). One wash load → 1 unit; two loads → 2 units.

    ``split-load`` purpose alone is NOT used — it co-occurs with normal add-photos
    completion on most bags and is not a dedicated split-confirm action.
    """
    bid = normalize_bag_id(bag_id) or str(bag_id or "").strip()
    enriched: list[dict[str, Any]] = []
    for ev in events_after_first_weight:
        row = dict(ev)
        if not row.get("bag_id"):
            row["bag_id"] = bid
        enriched.append(row)
    wash_rows = extract_washing_rows_from_events(enriched)
    racks = sorted(
        {
            str(r.get("washer_rack") or "").strip()
            for r in wash_rows
            if str(r.get("washer_rack") or "").strip()
        }
    )
    load_count = len(wash_rows)
    split_confirmed = load_count >= 2
    latest_ts = None
    if wash_rows:
        latest_ts = max(
            (_as_naive_et(r.get("timestamp_et")) for r in wash_rows),
            default=None,
        )
    return {
        "processing_units": processing_units_from_split_confirmation(
            split_confirmed=split_confirmed
        ),
        "split_confirmed": split_confirmed,
        "washer_load_count": load_count,
        "washer_racks": racks,
        "latest_washer_load_et": latest_ts,
    }


def _display_special_instructions(raw: str | None) -> str | None:
    """Customer SI column only — never supply defaults like 'Standard soap'."""
    display = format_special_instructions_display(raw)
    if not display:
        return None
    if display.strip().casefold() == STANDARD_INTERPRETATION.casefold():
        return None
    return display


def _as_naive_et(ts: datetime | None) -> datetime | None:
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is not None:
        return ts.replace(tzinfo=None)
    return ts


def _events_with_naive_et_wall(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Copy events with scanned_at_parsed coerced to naive ET wall time."""
    out: list[dict[str, Any]] = []
    for ev in events:
        row = dict(ev)
        naive = _as_naive_et(event_ts(row))
        if naive is not None:
            row["scanned_at_parsed"] = naive
        out.append(row)
    return out


def first_weight_on_et_day(
    events: Sequence[Mapping[str, Any]],
    selected_date_et: date,
) -> dict[str, Any] | None:
    """
    Current-lifecycle first weight membership for an ET calendar day.

    Reuses lifecycle_anchor + first_weight_after_anchor. Repeat-trip bags use
    the first weight after the latest sent-to-vendor, not the bag's first weight ever.
    """
    tl = gaming_events_from_records(_events_with_naive_et_wall(events))
    anchor_ts, _ = lifecycle_anchor(tl)
    if anchor_ts is None:
        return None
    anchored = events_on_or_after(tl, anchor_ts)
    _, first_weight_ts = first_weight_after_anchor(anchored)
    first_weight_ts = _as_naive_et(first_weight_ts)
    anchor_ts = _as_naive_et(anchor_ts)
    if first_weight_ts is None or anchor_ts is None:
        return None

    day_start = naive_et_day_start(selected_date_et)
    day_end_excl = naive_et_day_end_exclusive(selected_date_et)
    if not (day_start <= first_weight_ts < day_end_excl):
        return None

    post_weight = events_after_ts(anchored, first_weight_ts)
    # Informational only — not used for unit confirmation.
    split_load_events = [
        ev
        for ev in post_weight
        if is_split_load_purpose(ev.get("purpose")) and ts_valid(event_ts(ev))
    ]
    bag_hint = ""
    for ev in events:
        bag_hint = normalize_bag_id(ev.get("bag_id")) or str(ev.get("bag_id") or "").strip()
        if bag_hint:
            break
    washer = processing_units_from_washer_loads(post_weight, bag_id=bag_hint)
    return {
        "lifecycle_anchor_et": anchor_ts,
        "first_weight_et": first_weight_ts,
        "split_confirmed": bool(washer["split_confirmed"]),
        "latest_split_scan_et": washer.get("latest_washer_load_et"),
        "latest_washer_load_et": washer.get("latest_washer_load_et"),
        "processing_units": int(washer["processing_units"]),
        "washer_load_count": int(washer["washer_load_count"]),
        "washer_racks": list(washer.get("washer_racks") or []),
        "split_load_scan_count": len(split_load_events),
        "has_split_load_scan": bool(split_load_events),
    }


def _order_row_from_staging(
    row: Mapping[str, Any],
    *,
    mapping_rules: Sequence[Mapping[str, Any]],
    processing_units: int = 1,
    split_confirmed: bool = False,
    first_weight_et: datetime | None = None,
    lifecycle_anchor_et: datetime | None = None,
    latest_split_scan_et: datetime | None = None,
    washer_load_count: int | None = None,
    washer_racks: Sequence[str] | None = None,
    has_split_load_scan: bool = False,
) -> dict[str, Any]:
    raw = row.get("special_instructions_raw")
    mapped = supplies_for_usage(raw, mapping_rules)
    ticket_id = str(row.get("ticket_id") or row.get("bag_id") or "").strip()
    units = max(1, int(processing_units or 1))
    supplies = list(mapped["supplies_used"])
    doses_by_supply = {s: units for s in supplies}
    racks = [str(r).strip() for r in (washer_racks or []) if str(r).strip()]
    confirmed = bool(split_confirmed)
    # Informational only: SI "Split Order" may mark pending expectation; never affects doses.
    expects_split = si_expects_split_order(
        raw,
        row.get("supply_interpretation"),
        row.get("notes"),
        mapped.get("supply_interpretation"),
    )
    pending = (not confirmed) and expects_split
    if confirmed:
        split_status = "confirmed"
    elif pending:
        split_status = "pending"
    else:
        split_status = "unresolved"
    return {
        "order_id": ticket_id,
        "ticket_id": ticket_id,
        "customer": row.get("name_clean") or row.get("customer"),
        "special_instructions": _display_special_instructions(raw),
        "special_instructions_raw": raw,
        "supply_interpretation": mapped.get("supply_interpretation"),
        "split_order": units > 1,
        "split_confirmed": confirmed,
        "split_pending": pending,
        "split_status": split_status,
        "split_load_scan": bool(has_split_load_scan),
        "multiplier": units,
        "processing_units": units,
        "washer_load_count": int(washer_load_count or 0),
        "washer_racks": racks,
        "supplies_used": supplies,
        "estimated_doses": sum(doses_by_supply.values()),
        "doses_by_supply": doses_by_supply,
        "special_instruction_review": mapped.get("special_instruction_review"),
        "date_clean": row.get("date_clean"),
        "service_type": row.get("service_type"),
        "source": row.get("_source") or "orders_staging",
        "first_weight_et": first_weight_et.isoformat(sep=" ") if first_weight_et else None,
        "lifecycle_anchor_et": (
            lifecycle_anchor_et.isoformat(sep=" ") if lifecycle_anchor_et else None
        ),
        "latest_split_scan_et": (
            latest_split_scan_et.isoformat(sep=" ") if latest_split_scan_et else None
        ),
        "latest_washer_load_et": (
            latest_split_scan_et.isoformat(sep=" ") if latest_split_scan_et else None
        ),
    }


def _load_bag_ids_with_weight_entry_on_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> list[str]:
    """Candidate bags that have a weight-entry scan touching the ET day window."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    day_start = naive_et_day_start(selected_date_et)
    day_end_excl = naive_et_day_end_exclusive(selected_date_et)
    cursor.execute(
        """
        SELECT bag_id, purpose
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
        """,
        (int(organization_id), day_start, day_end_excl),
    )
    bag_ids: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if not is_weight_entry_purpose(row.get("purpose")):
            continue
        # Keep stored casing so subsequent bag_id IN (...) loads match the table.
        bid = str(row.get("bag_id") or "").strip()
        if bid:
            bag_ids.add(bid)
    return sorted(bag_ids)


def _load_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    from backend.rinse_shift_analysis import _load_scan_events_for_bags as _load

    return _load(cursor, int(organization_id), list(bag_ids))


def _bags_with_first_weight_on_et_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, dict[str, Any]]:
    """bag_id → first-weight membership for the selected ET day."""
    candidates = _load_bag_ids_with_weight_entry_on_day(
        cursor, organization_id, selected_date_et
    )
    if not candidates:
        return {}
    events_by_bag = _load_scan_events_for_bags(cursor, organization_id, candidates)
    out: dict[str, dict[str, Any]] = {}
    for bid in candidates:
        events = events_by_bag.get(bid) or events_by_bag.get(normalize_bag_id(bid)) or []
        membership = first_weight_on_et_day(events, selected_date_et)
        if membership:
            key = normalize_bag_id(bid) or bid.upper()
            out[key] = membership
    return out


def _upload_batches_pk(cursor) -> str:
    if table_has_column(cursor, "upload_batches", "id"):
        return "id"
    if table_has_column(cursor, "upload_batches", "batch_id"):
        return "batch_id"
    return "id"


def _load_approved_upload_orders_by_tickets(
    cursor,
    organization_id: int,
    ticket_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Approved upload rows for tickets (row_status eligibility only; not day filter)."""
    if not ticket_ids:
        return []
    if not table_exists(cursor, "upload_batch_rows") or not table_exists(cursor, "upload_batches"):
        return []
    if not table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        return []
    ub_pk = _upload_batches_pk(cursor)
    has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
    has_si = table_has_column(cursor, "upload_batch_rows", "special_instructions_raw")
    normalized = sorted({normalize_bag_id(t) for t in ticket_ids if normalize_bag_id(t)})
    if not normalized:
        return []
    cols = [
        "ubr.date_clean",
        "ubr.name_clean",
        "ubr.service_type",
        "ubr.ticket_id",
        "ubr.row_status",
    ]
    if has_si:
        cols.extend(
            [
                "ubr.special_instructions_raw",
                "ubr.supply_interpretation",
                "ubr.special_instruction_review",
            ]
        )
    placeholders = ", ".join(["%s"] * len(normalized))
    org_clause = " AND ub.organization_id = %s" if has_ub_org else ""
    args: list[Any] = list(normalized)
    if has_ub_org:
        args.append(int(organization_id))
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM upload_batch_rows ubr
        INNER JOIN upload_batches ub ON ub.{ub_pk} = ubr.upload_batch_id
        WHERE UPPER(TRIM(ubr.ticket_id)) IN ({placeholders})
          AND ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')
          {org_clause}
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


def _load_staging_orders_by_tickets(
    cursor,
    organization_id: int,
    ticket_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not ticket_ids:
        return []
    if not table_exists(cursor, "orders_staging"):
        return []
    if not table_has_column(cursor, "orders_staging", "ticket_id"):
        return []
    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_si = table_has_column(cursor, "orders_staging", "special_instructions_raw")
    normalized = sorted({normalize_bag_id(t) for t in ticket_ids if normalize_bag_id(t)})
    if not normalized:
        return []
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
    placeholders = ", ".join(["%s"] * len(normalized))
    where = [f"UPPER(TRIM(ticket_id)) IN ({placeholders})"]
    args: list[Any] = list(normalized)
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


def _load_approved_order_metadata(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """ticket_id (normalized) → metadata; staging wins over approved upload rows."""
    by_ticket: dict[str, dict[str, Any]] = {}
    for row in _load_approved_upload_orders_by_tickets(cursor, organization_id, bag_ids):
        tid = normalize_bag_id(row.get("ticket_id"))
        if tid:
            by_ticket[tid] = row
    for row in _load_staging_orders_by_tickets(cursor, organization_id, bag_ids):
        tid = normalize_bag_id(row.get("ticket_id"))
        if tid:
            by_ticket[tid] = row
    return by_ticket


def _load_split_load_bag_ids(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> set[str]:
    """
    Deprecated lifetime split-load helper.

    Supply Usage now resolves split confirmation per lifecycle in
    ``first_weight_on_et_day``.
    """
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    normalized = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not normalized:
        return set()
    placeholders = ", ".join(["%s"] * len(normalized))
    cursor.execute(
        f"""
        SELECT bag_id, purpose
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND UPPER(TRIM(bag_id)) IN ({placeholders})
        """,
        (int(organization_id), *normalized),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bag = normalize_bag_id(row.get("bag_id"))
        if bag and is_split_load_purpose(row.get("purpose")):
            out.add(bag)
    return out


def load_orders_for_supply_usage(
    cursor,
    organization_id: int,
    target_date: date,
    *,
    mapping_rules: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Orders whose current-lifecycle first weight falls on the selected ET day.

    Requires an approved upload/staging metadata row. Processing units come from
    lifecycle-scoped split-load scan confirmation only (not portal SI text).
    """
    rules = list(mapping_rules or get_supply_usage_mapping_rules(cursor, organization_id))
    membership = _bags_with_first_weight_on_et_day(cursor, organization_id, target_date)
    if not membership:
        return []
    meta_by_ticket = _load_approved_order_metadata(
        cursor, organization_id, list(membership.keys())
    )
    orders: list[dict[str, Any]] = []
    for bag_id, fw in membership.items():
        meta = meta_by_ticket.get(bag_id)
        if not meta:
            continue
        orders.append(
            _order_row_from_staging(
                meta,
                mapping_rules=rules,
                processing_units=int(fw.get("processing_units") or 1),
                split_confirmed=bool(fw.get("split_confirmed")),
                first_weight_et=fw.get("first_weight_et"),
                lifecycle_anchor_et=fw.get("lifecycle_anchor_et"),
                latest_split_scan_et=fw.get("latest_washer_load_et")
                or fw.get("latest_split_scan_et"),
                washer_load_count=int(fw.get("washer_load_count") or 0),
                washer_racks=list(fw.get("washer_racks") or []),
                has_split_load_scan=bool(fw.get("has_split_load_scan")),
            )
        )
    return orders


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
            doses = int(
                doses_by_supply.get(supply)
                or row.get("processing_units")
                or row.get("multiplier")
                or 1
            )
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
    mapping_rules = get_supply_usage_mapping_rules(cursor, organization_id)
    order_rows = load_orders_for_supply_usage(
        cursor, organization_id, target_date, mapping_rules=mapping_rules
    )
    order_rows.sort(key=lambda r: (str(r.get("customer") or "").lower(), str(r.get("order_id") or "")))
    return {
        "date_et": target_date.isoformat(),
        "data_source": (
            "first_weight_et day (lifecycle_anchor + first_weight_after_anchor) "
            "+ approved ACCEPTED/OVERRIDDEN metadata "
            "(staging preferred on duplicate ticket_id); "
            "processing_units from post-first-weight washer start-cleaning loads "
            "(2 units when ≥2 distinct W-racks; split-load purpose is informational only)"
        ),
        "summary": _summary_counts(order_rows),
        "usage_by_supply": _usage_by_supply(order_rows, dosages),
        "orders": order_rows,
        "dosage_settings": dosages,
        "mapping_rules": mapping_rules_display(mapping_rules),
    }
