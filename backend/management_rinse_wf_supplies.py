"""Management Rinse WF Supplies (Phase B).

Population = exact canonical Management WF day-bag membership for the selected
ET date + ALL / RUSH / NON-RUSH scope.

Confirmed supply totals use finalized canonical split only:
  Not Split → 1 load · Split → 2 loads
Unresolved PENDING / REVIEW_REQUIRED orders are provisional — never folded into
confirmed 1× totals.

Product Master drives average dose, effective-dated package price, and cost/dose.
Standalone Supply Usage (first-weight) is unchanged.
"""

from __future__ import annotations

import json
import time
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_shift_day import (
    _matches_segment_filters,
    _segment_filters,
)
from backend.rinse_wf_canonical_split import (
    evaluate_day_wf_splits,
    supply_day_finalizable,
)
from backend.supply_product_constants import LEGACY_REPORT_KEYS, SUPPLY_TYPE_LABELS
from backend.supply_product_mapping import (
    active_products_by_supply_type,
    default_mapping_rules,
    normalize_mapping_rule,
    project_rules_with_active_products,
)
from backend.supply_product_master import list_supply_products
from backend.supply_usage import (
    _load_approved_order_metadata,
    _order_row_from_staging,
)
from backend.supply_usage_settings import (
    KEY_SUPPLY_USAGE_MAPPING_RULES,
    get_supply_usage_mapping_rules,
)

SCOPE_ALL = "all"
SCOPE_RUSH = "rush"
SCOPE_NON_RUSH = "non_rush"
_SCOPE_LABELS = {
    SCOPE_ALL: "ALL",
    SCOPE_RUSH: "RUSH",
    SCOPE_NON_RUSH: "NON-RUSH",
}
_SCOPE_SEGMENT = {
    SCOPE_ALL: "wf",
    SCOPE_RUSH: "wf_rush",
    SCOPE_NON_RUSH: "wf_non_rush",
}

# In-process workset: membership + order rows + products for summary/detail reuse.
# Same TTL family as management_today supply summary (live 120s / closed 600s).
_WF_SUPPLY_WORKSET_CACHE: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}
_WORKSET_TTL_LIVE_SEC = 120.0
_WORKSET_TTL_CLOSED_SEC = 600.0


def normalize_rush_scope(raw: Any) -> str:
    v = str(raw or SCOPE_ALL).strip().lower().replace("-", "_")
    if v in (SCOPE_RUSH, "wf_rush"):
        return SCOPE_RUSH
    if v in (SCOPE_NON_RUSH, "nonrush", "wf_non_rush"):
        return SCOPE_NON_RUSH
    return SCOPE_ALL


def clear_wf_supply_workset(
    organization_id: int | None = None,
    date_et: date | str | None = None,
) -> None:
    if organization_id is None and date_et is None:
        _WF_SUPPLY_WORKSET_CACHE.clear()
        return
    org = int(organization_id) if organization_id is not None else None
    day_key = (
        date_et.isoformat()
        if isinstance(date_et, date)
        else (str(date_et) if date_et else None)
    )
    for key in list(_WF_SUPPLY_WORKSET_CACHE):
        if org is not None and key[0] != org:
            continue
        if day_key is not None and key[1] != day_key:
            continue
        _WF_SUPPLY_WORKSET_CACHE.pop(key, None)


def _money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.01")))
    except Exception:
        return None


def _qty(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.0001")))
    except Exception:
        return None


def _load_day_bags_slim_for_supply(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    """Membership columns only — no bag_snapshot LONGTEXT, no DDL on read."""
    try:
        cursor.execute(
            """
            SELECT bag_id, service_type, rush_status,
                   pre_weight_lbs, post_weight_lbs, weight_lbs
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND shift_date_et = %s
            ORDER BY bag_id
            """,
            (int(organization_id), selected_date_et),
        )
    except Exception:
        return []
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def management_wf_supply_membership(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
) -> list[dict[str, Any]]:
    """Canonical Management WF day-bag rows for the selected scope."""
    scope = normalize_rush_scope(rush_scope)
    service, rush = _segment_filters(_SCOPE_SEGMENT[scope])
    bags = _load_day_bags_slim_for_supply(
        cursor, int(organization_id), selected_date_et
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bag in bags or []:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid or bid in seen:
            continue
        if not _matches_segment_filters(bag, service=service, rush=rush):
            continue
        seen.add(bid)
        out.append(dict(bag))
    out.sort(key=lambda b: str(b.get("bag_id") or ""))
    return out


def _load_si_metadata_fast(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """SI metadata without INFORMATION_SCHEMA probes (known production columns).

    Staging first (wins for mapping). Upload fill only for tickets still missing —
    avoids the heavy upload_batch_rows join when staging already covers membership.
    """
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    if not ids:
        return {}
    by_ticket: dict[str, dict[str, Any]] = {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cursor.execute(
            f"""
            SELECT ticket_id, name_clean, date_clean, service_type,
                   special_instructions_raw, supply_interpretation,
                   special_instruction_review
            FROM orders_staging
            WHERE UPPER(TRIM(ticket_id)) IN ({ph})
              AND organization_id = %s
            ORDER BY name_clean, ticket_id
            """,
            (*ids, int(organization_id)),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            tid = normalize_bag_id(row.get("ticket_id"))
            if tid:
                item = dict(row)
                item["_source"] = "orders_staging"
                by_ticket[tid] = item
    except Exception:
        return _load_approved_order_metadata(cursor, organization_id, ids)

    missing = [tid for tid in ids if tid not in by_ticket]
    if not missing:
        return by_ticket

    mph = ",".join(["%s"] * len(missing))
    try:
        cursor.execute(
            f"""
            SELECT ubr.date_clean, ubr.name_clean, ubr.service_type, ubr.ticket_id,
                   ubr.row_status, ubr.special_instructions_raw,
                   ubr.supply_interpretation, ubr.special_instruction_review
            FROM upload_batch_rows ubr
            INNER JOIN upload_batches ub ON ub.batch_id = ubr.upload_batch_id
            WHERE UPPER(TRIM(ubr.ticket_id)) IN ({mph})
              AND ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')
              AND ub.organization_id = %s
            ORDER BY ubr.name_clean, ubr.ticket_id
            """,
            (*missing, int(organization_id)),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            tid = normalize_bag_id(row.get("ticket_id"))
            if tid and tid not in by_ticket:
                item = dict(row)
                item["_source"] = "upload_batch_rows"
                by_ticket[tid] = item
    except Exception:
        # Staging rows already kept; fill gaps via legacy path if upload schema differs.
        legacy = _load_approved_order_metadata(cursor, organization_id, missing)
        for tid, row in legacy.items():
            by_ticket.setdefault(tid, row)
    return by_ticket


def _mapping_rules_for_products(
    cursor,
    organization_id: int,
    products: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project mapping rules using an already-loaded product list (no re-list)."""
    products_by_type = active_products_by_supply_type(list(products))
    raw = None
    try:
        cursor.execute(
            "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
            (int(organization_id), KEY_SUPPLY_USAGE_MAPPING_RULES),
        )
        row = cursor.fetchone()
        if isinstance(row, dict):
            raw = row.get("svalue")
        elif row:
            raw = row[0]
    except Exception:
        raw = None

    if not raw:
        rules = default_mapping_rules(products_by_type=products_by_type or None)
    else:
        try:
            parsed = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if not isinstance(parsed, list):
            rules = default_mapping_rules(products_by_type=products_by_type or None)
        else:
            out: list[dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict):
                    norm = normalize_mapping_rule(
                        item, products_by_type=products_by_type or None
                    )
                    if norm:
                        out.append(norm)
            rules = out or default_mapping_rules(
                products_by_type=products_by_type or None
            )

    if products_by_type:
        return project_rules_with_active_products(
            rules, products_by_type=products_by_type
        )
    return rules


def membership_bag_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            normalize_bag_id(r.get("bag_id"))
            for r in rows
            if normalize_bag_id(r.get("bag_id"))
        }
    )


def _meta_for_bag(
    bag: Mapping[str, Any],
    meta_by_ticket: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    bid = normalize_bag_id(bag.get("bag_id")) or str(bag.get("bag_id") or "").strip()
    meta = meta_by_ticket.get(bid)
    if meta:
        return dict(meta)
    snap = bag.get("bag_snapshot") if isinstance(bag.get("bag_snapshot"), Mapping) else {}
    return {
        "ticket_id": bid,
        "name_clean": (
            bag.get("customer_name")
            or (snap or {}).get("customer_name")
            or (snap or {}).get("name_clean")
        ),
        "special_instructions_raw": (snap or {}).get("special_instructions_raw"),
        "supply_interpretation": (snap or {}).get("supply_interpretation"),
        "service_type": bag.get("service_type") or "WF",
        "_source": "management_wf_day_bag",
    }


def load_orders_for_management_wf_supplies(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
    mapping_rules: Sequence[Mapping[str, Any]] | None = None,
    membership: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Build supply order rows for Management WF membership.

    Returns (order_rows, population_bag_ids). Every membership bag is included
    in population; mapping falls back to default detergent when SI metadata is
    missing.

    Split math is unchanged — ``evaluate_day_wf_splits`` / ``evaluate_bag_split``.
    Events are loaded slim (no raw_json) and purpose-filtered for the Supply
    hot path only — no full scan timelines.
    """
    rules = list(
        mapping_rules
        if mapping_rules is not None
        else get_supply_usage_mapping_rules(cursor, organization_id)
    )
    if membership is None:
        membership = management_wf_supply_membership(
            cursor, organization_id, selected_date_et, rush_scope=rush_scope
        )
    bag_ids = membership_bag_ids(membership)
    if not bag_ids:
        return [], []

    meta_by_ticket = _load_si_metadata_fast(cursor, organization_id, bag_ids)
    evaluations = evaluate_day_wf_splits(
        cursor,
        organization_id,
        selected_date_et,
        bag_ids,
        slim_events=True,
    )
    by_id = {
        normalize_bag_id(b.get("bag_id")): b
        for b in membership
        if normalize_bag_id(b.get("bag_id"))
    }

    orders: list[dict[str, Any]] = []
    for bid in bag_ids:
        bag = by_id.get(bid) or {"bag_id": bid}
        split_ev = evaluations.get(bid) or {
            "processing_units": 1,
            "canonical_split": False,
            "split_finalized": True,
            "state": "CONFIRMED_NOT_SPLIT",
            "washer_load_count": 0,
            "washer_racks": [],
            "split_marker_present": False,
        }
        finalized = bool(split_ev.get("split_finalized"))
        units = int(split_ev.get("processing_units") or 1)
        # Confirmed totals only — unresolved never count as silent 1×.
        confirmed_units = units if finalized else 0
        row = _order_row_from_staging(
            _meta_for_bag(bag, meta_by_ticket),
            mapping_rules=rules,
            processing_units=units,
            split_confirmed=split_ev.get("canonical_split") is True,
            lifecycle_anchor_et=split_ev.get("lifecycle_anchor_et"),
            latest_split_scan_et=split_ev.get("latest_washer_load_et"),
            washer_load_count=int(split_ev.get("washer_load_count") or 0),
            washer_racks=list(split_ev.get("washer_racks") or []),
            has_split_load_scan=bool(split_ev.get("split_marker_present")),
            split_state=split_ev.get("state"),
            canonical_split=split_ev.get("canonical_split"),
            split_finalized=finalized,
            review_reason=split_ev.get("review_reason"),
        )
        row["rush_status"] = bag.get("rush_status") or bag.get("rush_flag")
        row["confirmed_for_supply"] = finalized
        row["confirmed_processing_units"] = confirmed_units
        if finalized:
            row["confirmed_doses_by_supply"] = {
                s: confirmed_units for s in (row.get("supplies_used") or [])
            }
        else:
            row["confirmed_doses_by_supply"] = {}
            row["provisional_load_min"] = 1
            row["provisional_load_max"] = 2
        orders.append(row)
    return orders, bag_ids


def _active_products_as_of(cursor, organization_id: int, as_of: date) -> list[dict[str, Any]]:
    try:
        products = list_supply_products(
            cursor, int(organization_id), active_only=True, as_of=as_of
        )
    except Exception:
        products = []
    if products:
        return products
    return [
        {
            "id": None,
            "legacy_report_key": key,
            "brand": key,
            "product_name": key,
            "average_dose": None,
            "dose_unit": "oz",
            "package_unit": "oz",
            "cost_per_dose": None,
            "purchase_price_per_package": None,
            "is_active": True,
        }
        for key in LEGACY_REPORT_KEYS
    ]


def _display_product_name(product: Mapping[str, Any], legacy: str) -> str:
    name = str(product.get("product_name") or "").strip()
    brand = str(product.get("brand") or "").strip()
    if name:
        return name
    if brand:
        return brand
    return legacy


def _product_usage_cards(
    order_rows: Sequence[Mapping[str, Any]],
    products: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for product in products:
        legacy = str(product.get("legacy_report_key") or "").strip()
        if not legacy:
            continue
        orders_using = 0
        confirmed_loads = 0
        not_split_orders = 0
        split_orders = 0
        for row in order_rows:
            supplies = set(row.get("supplies_used") or [])
            if legacy not in supplies:
                continue
            if not row.get("confirmed_for_supply"):
                continue
            orders_using += 1
            units = int(
                (row.get("confirmed_doses_by_supply") or {}).get(legacy)
                or row.get("confirmed_processing_units")
                or 0
            )
            confirmed_loads += units
            if units >= 2 or row.get("canonical_split") is True:
                split_orders += 1
            else:
                not_split_orders += 1
        avg_dose = _qty(product.get("average_dose"))
        cost_per_dose = _money(product.get("cost_per_dose"))
        qty = None
        if avg_dose is not None:
            qty = round(confirmed_loads * float(avg_dose), 4)
        est_cost = None
        if cost_per_dose is not None:
            est_cost = round(confirmed_loads * float(cost_per_dose), 2)
        supply_type = str(product.get("supply_type") or "")
        cards.append(
            {
                "product_id": product.get("id"),
                "legacy_report_key": legacy,
                "supply_type": supply_type,
                "supply_type_label": (
                    product.get("supply_type_label")
                    or SUPPLY_TYPE_LABELS.get(supply_type, supply_type)
                ),
                "label": _display_product_name(product, legacy),
                "brand": product.get("brand"),
                "product_name": product.get("product_name"),
                "vendor": product.get("vendor"),
                "package_qty": product.get("package_qty"),
                "package_unit": product.get("package_unit"),
                "orders_using": orders_using,
                "confirmed_loads": confirmed_loads,
                "confirmed_doses": confirmed_loads,
                "not_split_orders": not_split_orders,
                "split_orders": split_orders,
                "quantity_used": qty,
                "quantity_unit": product.get("dose_unit") or product.get("package_unit") or "oz",
                "average_dose": avg_dose,
                "cost_per_dose": cost_per_dose,
                "estimated_cost": est_cost,
                "price_as_of": product.get("price_as_of") or product.get("as_of"),
                "purchase_price_per_package": _money(
                    product.get("purchase_price_per_package")
                ),
                "doses_per_package": product.get("doses_per_package"),
            }
        )
    cards.sort(
        key=lambda c: (
            -(float(c["estimated_cost"]) if c.get("estimated_cost") is not None else -1.0),
            str(c.get("label") or ""),
        )
    )
    return cards


def _provisional_load_range(order_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    unresolved = [r for r in order_rows if not r.get("confirmed_for_supply")]
    n = len(unresolved)
    return {
        "unresolved_orders": n,
        "additional_loads_min": n * 1,
        "additional_loads_max": n * 2,
    }


def _provisional_cost_range(
    order_rows: Sequence[Mapping[str, Any]],
    products: Sequence[Mapping[str, Any]],
    *,
    confirmed_total: float | None,
) -> dict[str, Any]:
    """Confirmed cost + unresolved as 1× (min) or 2× (max) of mapped products."""
    cost_by_legacy: dict[str, float] = {}
    for p in products:
        legacy = str(p.get("legacy_report_key") or "").strip()
        cpd = _money(p.get("cost_per_dose"))
        if legacy and cpd is not None:
            cost_by_legacy[legacy] = float(cpd)
    if confirmed_total is None or not cost_by_legacy:
        return {
            "potential_final_cost_min": None,
            "potential_final_cost_max": None,
        }
    add_min = 0.0
    add_max = 0.0
    for row in order_rows:
        if row.get("confirmed_for_supply"):
            continue
        bag_cost = 0.0
        for legacy in row.get("supplies_used") or []:
            bag_cost += float(cost_by_legacy.get(str(legacy), 0.0))
        add_min += bag_cost * 1
        add_max += bag_cost * 2
    return {
        "potential_final_cost_min": round(float(confirmed_total) + add_min, 2),
        "potential_final_cost_max": round(float(confirmed_total) + add_max, 2),
    }


def _bag_weight(bag: Mapping[str, Any], field: str) -> float | None:
    val = bag.get(field)
    if val is None and isinstance(bag.get("bag_snapshot"), Mapping):
        val = (bag.get("bag_snapshot") or {}).get(field)
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _confirmed_population_pounds(
    membership: Sequence[Mapping[str, Any]],
    order_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """POST (preferred) / PRE lbs for bags with confirmed supply only — cost/lb scope."""
    confirmed_ids = {
        normalize_bag_id(r.get("order_id") or r.get("bag_id"))
        for r in order_rows
        if r.get("confirmed_for_supply")
        and normalize_bag_id(r.get("order_id") or r.get("bag_id"))
    }
    pre_sum = 0.0
    post_sum = 0.0
    pre_n = 0
    post_n = 0
    for bag in membership or []:
        bid = normalize_bag_id(bag.get("bag_id"))
        if not bid or bid not in confirmed_ids:
            continue
        pre = _bag_weight(bag, "pre_weight_lbs")
        post = _bag_weight(bag, "post_weight_lbs")
        if pre is not None:
            pre_sum += pre
            pre_n += 1
        if post is not None:
            post_sum += post
            post_n += 1
    lbs = None
    basis = None
    if post_n > 0:
        lbs = round(post_sum, 1)
        basis = "confirmed_post_weight_lbs"
    elif pre_n > 0:
        lbs = round(pre_sum, 1)
        basis = "confirmed_pre_weight_lbs"
    return {
        "pounds": lbs,
        "pounds_basis": basis,
        "pounds_available": lbs is not None and lbs > 0,
        "pre_weight_lbs": round(pre_sum, 1) if pre_n else None,
        "post_weight_lbs": round(post_sum, 1) if post_n else None,
        "pre_weight_bag_count": pre_n,
        "post_weight_bag_count": post_n,
        "pounds_scope": "confirmed_supply_orders",
    }


def _build_cost_dashboard(
    *,
    selected_date_et: date,
    cards: Sequence[Mapping[str, Any]],
    population_orders: int,
    confirmed_orders: int,
    confirmed_loads: int,
    pending_split_reviews: int,
    total_cost: float | None,
    pounds_info: Mapping[str, Any],
    potential_cost_min: float | None,
    potential_cost_max: float | None,
) -> dict[str, Any]:
    total_doses = sum(int(c.get("confirmed_doses") or 0) for c in cards)
    total_qty = 0.0
    qty_any = False
    for c in cards:
        if c.get("quantity_used") is not None:
            total_qty += float(c.get("quantity_used") or 0)
            qty_any = True
    units = sorted(
        {
            str(c.get("quantity_unit") or "oz").strip() or "oz"
            for c in cards
            if c.get("quantity_unit")
        }
    )
    quantity_unit = units[0] if len(units) == 1 else ("oz" if not units else "mixed")

    lbs = pounds_info.get("pounds")
    cost_per_order = None
    cost_per_load = None
    cost_per_lb = None
    if total_cost is not None and confirmed_orders > 0:
        cost_per_order = round(float(total_cost) / confirmed_orders, 4)
    if total_cost is not None and confirmed_loads > 0:
        cost_per_load = round(float(total_cost) / confirmed_loads, 4)
    if (
        total_cost is not None
        and pounds_info.get("pounds_available")
        and lbs is not None
        and float(lbs) > 0
    ):
        cost_per_lb = round(float(total_cost) / float(lbs), 4)

    return {
        "period_grain": "day",
        "period_start_et": selected_date_et.isoformat(),
        "period_end_et": selected_date_et.isoformat(),
        "total_supply_cost": total_cost,
        "total_doses": total_doses,
        "total_quantity_used": round(total_qty, 4) if qty_any else None,
        "quantity_unit": quantity_unit,
        "workload_orders": int(population_orders),
        "unique_orders": int(population_orders),
        "confirmed_orders": int(confirmed_orders),
        "confirmed_supply_orders": int(confirmed_orders),
        "confirmed_loads": int(confirmed_loads),
        "pending_split_reviews": int(pending_split_reviews),
        "pounds": lbs,
        "pounds_basis": pounds_info.get("pounds_basis"),
        "pounds_available": bool(pounds_info.get("pounds_available")),
        "pounds_scope": pounds_info.get("pounds_scope") or "confirmed_supply_orders",
        "potential_final_cost_min": potential_cost_min,
        "potential_final_cost_max": potential_cost_max,
        "kpis": {
            "cost_per_order": cost_per_order,
            "cost_per_load": cost_per_load,
            "cost_per_lb": cost_per_lb,
            "orders_basis": "confirmed_unique_orders",
            "loads_basis": "confirmed_canonical_processing_units",
            "pounds_basis": pounds_info.get("pounds_basis"),
            "pounds_scope": "confirmed_supply_orders",
        },
    }


def _build_summary_from_rows(
    *,
    selected_date_et: date,
    scope: str,
    membership: Sequence[Mapping[str, Any]],
    order_rows: Sequence[Mapping[str, Any]],
    population_ids: Sequence[str],
    products: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    cards = _product_usage_cards(order_rows, products)
    pounds_info = _confirmed_population_pounds(membership, order_rows)

    evaluations = {
        str(r.get("order_id") or ""): {
            "state": r.get("split_state"),
            "split_finalized": bool(r.get("split_finalized")),
        }
        for r in order_rows
        if r.get("order_id")
    }
    fin = supply_day_finalizable(evaluations)
    pending_reviews = int(fin.get("split_review_count") or 0) + int(
        fin.get("split_pending_count") or 0
    )
    provisional = _provisional_load_range(order_rows)
    confirmed_orders = sum(1 for r in order_rows if r.get("confirmed_for_supply"))
    confirmed_loads = sum(
        int(r.get("confirmed_processing_units") or 0)
        for r in order_rows
        if r.get("confirmed_for_supply")
    )
    cost_available = any(c.get("cost_per_dose") is not None for c in cards)
    total_cost = None
    if cost_available:
        total_cost = round(
            sum(
                float(c.get("estimated_cost") or 0)
                for c in cards
                if c.get("estimated_cost") is not None
            ),
            2,
        )
    pot = _provisional_cost_range(
        order_rows, products, confirmed_total=total_cost
    )

    dashboard = _build_cost_dashboard(
        selected_date_et=selected_date_et,
        cards=cards,
        population_orders=len(population_ids),
        confirmed_orders=confirmed_orders,
        confirmed_loads=confirmed_loads,
        pending_split_reviews=pending_reviews,
        total_cost=total_cost,
        pounds_info=pounds_info,
        potential_cost_min=pot.get("potential_final_cost_min"),
        potential_cost_max=pot.get("potential_final_cost_max"),
    )

    by_legacy: dict[str, dict[str, Any]] = {}
    for card in cards:
        key = card["legacy_report_key"]
        by_legacy[key] = {
            "orders": card["orders_using"],
            "doses": card["confirmed_doses"],
            "ounces": card["quantity_used"],
            "quantity_used": card["quantity_used"],
            "estimated_cost": card["estimated_cost"],
            "orders_using": card["orders_using"],
            "confirmed_loads": card["confirmed_loads"],
            "cost_per_dose": card.get("cost_per_dose"),
            "average_dose": card.get("average_dose"),
            "label": card.get("label"),
            "product_name": card.get("product_name"),
            "brand": card.get("brand"),
        }

    status = "FINAL" if fin.get("finalizable") else "PROVISIONAL"
    banner = None
    banner_detail = None
    if not fin.get("finalizable"):
        banner = (
            f"PROVISIONAL — {pending_reviews} split review"
            f"{'s' if pending_reviews != 1 else ''} pending"
        )
        banner_detail = (
            "Confirmed costs shown below. "
            "Final cost may increase after pending split reviews resolve."
        )
        if (
            pot.get("potential_final_cost_min") is not None
            and pot.get("potential_final_cost_max") is not None
        ):
            banner_detail += (
                f" Potential final supply cost range: "
                f"${pot['potential_final_cost_min']:.2f} – "
                f"${pot['potential_final_cost_max']:.2f}."
            )

    return {
        "date_et": selected_date_et.isoformat(),
        "available": True,
        "deferred": False,
        "cost_available": cost_available,
        "cost": total_cost,
        "dashboard": dashboard,
        "rush_filtering_supported": True,
        "rush_filtering_reason": None,
        "scope": scope,
        "scope_label": _SCOPE_LABELS[scope],
        "population": {
            "orders": len(population_ids),
            "workload_orders": len(population_ids),
            "bag_ids_count": len(population_ids),
            "confirmed_orders": confirmed_orders,
            "confirmed_supply_orders": confirmed_orders,
            "confirmed_loads": confirmed_loads,
            "pending_split_reviews": pending_reviews,
            "unresolved_split_orders": provisional["unresolved_orders"],
            "additional_loads_min": provisional["additional_loads_min"],
            "additional_loads_max": provisional["additional_loads_max"],
            **{
                k: pounds_info[k]
                for k in (
                    "pounds",
                    "pounds_basis",
                    "pounds_available",
                    "pre_weight_lbs",
                    "post_weight_lbs",
                    "pre_weight_bag_count",
                    "post_weight_bag_count",
                    "pounds_scope",
                )
            },
        },
        "products": cards,
        "usage_by_supply": by_legacy,
        "supply_finalizable": bool(fin.get("finalizable")),
        "supply_status": status,
        "supply_banner": banner,
        "supply_banner_detail": banner_detail,
        "pending_split_reviews": pending_reviews,
        "split_pending_count": int(fin.get("split_pending_count") or 0),
        "split_review_count": int(fin.get("split_review_count") or 0),
        "split_finalizability": fin,
        "potential_final_cost_min": pot.get("potential_final_cost_min"),
        "potential_final_cost_max": pot.get("potential_final_cost_max"),
        "data_source": (
            "management_wf_day_bags membership + rinse_wf_canonical_split "
            "+ supply_product_master effective-dated cost"
        ),
        "as_of_date_et": selected_date_et.isoformat(),
        "price_basis": "effective_dated_as_of_selected_et_date",
        "terminology": {
            "doses": "confirmed_processing_loads_per_product",
            "orders": "unique_bags_using_product",
            "loads_population": "canonical_processing_units_across_workload",
            "split_rule": "not_split_1_split_2",
            "cost_per_lb": "confirmed_cost_over_confirmed_order_post_lbs",
        },
    }


def _get_or_build_workset(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    scope = normalize_rush_scope(rush_scope)
    org = int(organization_id)
    key = (org, selected_date_et.isoformat(), scope)
    ttl = (
        _WORKSET_TTL_LIVE_SEC
        if selected_date_et == business_today()
        else _WORKSET_TTL_CLOSED_SEC
    )
    now = time.monotonic()
    if not bypass_cache:
        hit = _WF_SUPPLY_WORKSET_CACHE.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]

    # Products once → mapping projects from that list (no seed/re-list).
    products = _active_products_as_of(cursor, org, selected_date_et)
    mapping_rules = _mapping_rules_for_products(cursor, org, products)
    membership = management_wf_supply_membership(
        cursor, org, selected_date_et, rush_scope=scope
    )
    order_rows, population_ids = load_orders_for_management_wf_supplies(
        cursor,
        org,
        selected_date_et,
        rush_scope=scope,
        mapping_rules=mapping_rules,
        membership=membership,
    )
    summary = _build_summary_from_rows(
        selected_date_et=selected_date_et,
        scope=scope,
        membership=membership,
        order_rows=order_rows,
        population_ids=population_ids,
        products=products,
    )
    workset = {
        "membership": membership,
        "order_rows": order_rows,
        "population_ids": population_ids,
        "products": products,
        "summary": summary,
        "scope": scope,
    }
    _WF_SUPPLY_WORKSET_CACHE[key] = (time.monotonic(), workset)
    return workset


def build_management_wf_supply_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Compact confirmed product cards + status for Management Rinse WF."""
    workset = _get_or_build_workset(
        cursor,
        organization_id,
        selected_date_et,
        rush_scope=rush_scope,
        bypass_cache=bypass_cache,
    )
    return dict(workset["summary"])


def _split_label(row: Mapping[str, Any]) -> str:
    if not row.get("confirmed_for_supply"):
        return "Pending"
    if row.get("canonical_split") is True:
        return "Yes"
    if row.get("canonical_split") is False:
        return "No"
    return "—"


def build_management_wf_supply_detail(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
    product_id: int | None = None,
    legacy_report_key: str | None = None,
) -> dict[str, Any]:
    """Lazy order-level rows for one product — reuses summary workset (no rebuild)."""
    scope = normalize_rush_scope(rush_scope)
    workset = _get_or_build_workset(
        cursor,
        organization_id,
        selected_date_et,
        rush_scope=scope,
        bypass_cache=False,
    )
    summary = workset["summary"]
    order_rows = workset["order_rows"]
    legacy = str(legacy_report_key or "").strip()
    pid = int(product_id) if product_id is not None else None
    product_card: dict[str, Any] | None = None
    if pid is not None or legacy:
        for card in summary.get("products") or []:
            if pid is not None and card.get("product_id") == pid:
                product_card = card
                legacy = str(card.get("legacy_report_key") or legacy or "")
                break
            if legacy and str(card.get("legacy_report_key") or "") == legacy:
                product_card = card
                break

    avg_dose = _qty((product_card or {}).get("average_dose"))
    cost_per_dose = _money((product_card or {}).get("cost_per_dose"))
    qty_unit = (product_card or {}).get("quantity_unit") or "oz"

    detail_rows: list[dict[str, Any]] = []
    for row in order_rows:
        supplies = list(row.get("supplies_used") or [])
        if legacy and legacy not in supplies:
            continue
        confirmed = bool(row.get("confirmed_for_supply"))
        loads = (
            int(row.get("confirmed_processing_units") or 0)
            if confirmed
            else 0
        )
        dose = loads if confirmed else None
        qty = None
        est_cost = None
        if dose is not None and avg_dose is not None:
            qty = round(float(dose) * float(avg_dose), 4)
        if dose is not None and cost_per_dose is not None:
            est_cost = round(float(dose) * float(cost_per_dose), 2)
        detail_rows.append(
            {
                "order_id": row.get("order_id"),
                "bag_id": row.get("order_id"),
                "customer": row.get("customer"),
                "preference": row.get("supply_interpretation"),
                "supply_interpretation": row.get("supply_interpretation"),
                "supplies_used": supplies,
                "split": _split_label(row),
                "split_state": row.get("split_state"),
                "canonical_split": row.get("canonical_split"),
                "split_finalized": bool(row.get("split_finalized")),
                "confirmed_for_supply": confirmed,
                "loads": loads,
                "confirmed_loads": loads,
                "processing_units": int(row.get("processing_units") or 0),
                "dose": dose,
                "quantity_used": qty,
                "quantity_unit": qty_unit,
                "average_dose": avg_dose,
                "cost_per_dose": cost_per_dose,
                "estimated_cost": est_cost,
                "rush_status": row.get("rush_status"),
            }
        )
    detail_rows.sort(
        key=lambda r: (
            0 if r.get("confirmed_for_supply") else 1,
            str(r.get("customer") or "").lower(),
            str(r.get("order_id") or ""),
        )
    )
    return {
        "date_et": selected_date_et.isoformat(),
        "scope": scope,
        "scope_label": _SCOPE_LABELS[scope],
        "product_id": pid or (product_card or {}).get("product_id"),
        "legacy_report_key": legacy or None,
        "product": product_card,
        "orders": detail_rows,
        "order_count": len(detail_rows),
        "supply_status": summary.get("supply_status"),
        "pending_split_reviews": summary.get("pending_split_reviews"),
        "period_grain": "day",
        "workset_reused": True,
    }


def reconcile_scope_populations(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, Any]:
    """ALL unique bags must equal Rush ∪ Non-Rush."""
    all_ids = set(
        membership_bag_ids(
            management_wf_supply_membership(
                cursor, organization_id, selected_date_et, rush_scope=SCOPE_ALL
            )
        )
    )
    rush_ids = set(
        membership_bag_ids(
            management_wf_supply_membership(
                cursor, organization_id, selected_date_et, rush_scope=SCOPE_RUSH
            )
        )
    )
    non_ids = set(
        membership_bag_ids(
            management_wf_supply_membership(
                cursor, organization_id, selected_date_et, rush_scope=SCOPE_NON_RUSH
            )
        )
    )
    union = rush_ids | non_ids
    return {
        "all": len(all_ids),
        "rush": len(rush_ids),
        "non_rush": len(non_ids),
        "union": len(union),
        "match": all_ids == union,
        "all_minus_union": sorted(all_ids - union),
        "union_minus_all": sorted(union - all_ids),
    }
