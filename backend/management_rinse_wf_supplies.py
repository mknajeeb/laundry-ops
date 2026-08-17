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

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_shift_day import (
    _matches_segment_filters,
    _segment_filters,
    load_day_bags,
)
from backend.rinse_wf_canonical_split import (
    evaluate_bag_split,
    load_manager_split_decisions,
    supply_day_finalizable,
)
from backend.supply_product_constants import LEGACY_REPORT_KEYS
from backend.supply_product_master import list_supply_products
from backend.supply_usage import (
    _load_approved_order_metadata,
    _order_row_from_staging,
)
from backend.supply_usage_settings import get_supply_usage_mapping_rules

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


def normalize_rush_scope(raw: Any) -> str:
    v = str(raw or SCOPE_ALL).strip().lower().replace("-", "_")
    if v in (SCOPE_RUSH, "wf_rush"):
        return SCOPE_RUSH
    if v in (SCOPE_NON_RUSH, "nonrush", "wf_non_rush"):
        return SCOPE_NON_RUSH
    return SCOPE_ALL


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
    bags = load_day_bags(cursor, int(organization_id), selected_date_et)
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

    meta_by_ticket = _load_approved_order_metadata(cursor, organization_id, bag_ids)
    mgr = load_manager_split_decisions(
        cursor, organization_id, selected_date_et, bag_ids
    )
    from backend.rinse_wf_canonical_split import _load_events_for_bags

    events_by_bag = _load_events_for_bags(cursor, organization_id, bag_ids)
    by_id = {
        normalize_bag_id(b.get("bag_id")): b
        for b in membership
        if normalize_bag_id(b.get("bag_id"))
    }

    orders: list[dict[str, Any]] = []
    for bid in bag_ids:
        bag = by_id.get(bid) or {"bag_id": bid}
        split_ev = evaluate_bag_split(
            events_by_bag.get(bid) or [],
            bag_id=bid,
            manager_decision=mgr.get(bid),
        )
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
        # doses_by_supply for confirmed accounting
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
    # Seeded master may be empty locally — still emit legacy card shells.
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
        for row in order_rows:
            supplies = set(row.get("supplies_used") or [])
            if legacy not in supplies:
                continue
            if not row.get("confirmed_for_supply"):
                continue
            orders_using += 1
            confirmed_loads += int(
                (row.get("confirmed_doses_by_supply") or {}).get(legacy)
                or row.get("confirmed_processing_units")
                or 0
            )
        avg_dose = _qty(product.get("average_dose"))
        cost_per_dose = _money(product.get("cost_per_dose"))
        qty = None
        if avg_dose is not None:
            qty = round(confirmed_loads * float(avg_dose), 4)
        est_cost = None
        if cost_per_dose is not None:
            est_cost = round(confirmed_loads * float(cost_per_dose), 2)
        label = str(product.get("brand") or legacy).strip() or legacy
        if product.get("product_name") and str(product.get("product_name")) != label:
            label = f"{label}".strip()
        cards.append(
            {
                "product_id": product.get("id"),
                "legacy_report_key": legacy,
                "supply_type": product.get("supply_type"),
                "label": legacy,
                "brand": product.get("brand"),
                "product_name": product.get("product_name"),
                "orders_using": orders_using,
                "confirmed_loads": confirmed_loads,
                "confirmed_doses": confirmed_loads,
                "quantity_used": qty,
                "quantity_unit": product.get("dose_unit") or product.get("package_unit") or "oz",
                "average_dose": avg_dose,
                "cost_per_dose": cost_per_dose,
                "estimated_cost": est_cost,
                "price_as_of": product.get("price_as_of") or product.get("as_of"),
                "purchase_price_per_package": _money(
                    product.get("purchase_price_per_package")
                ),
            }
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


def _population_pounds(
    membership: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """PRE/POST lbs for membership bags — used for cost/lb when available."""
    pre_sum = 0.0
    post_sum = 0.0
    pre_n = 0
    post_n = 0
    for bag in membership or []:
        pre = bag.get("pre_weight_lbs")
        post = bag.get("post_weight_lbs")
        if pre is None and isinstance(bag.get("bag_snapshot"), Mapping):
            pre = (bag.get("bag_snapshot") or {}).get("pre_weight_lbs")
        if post is None and isinstance(bag.get("bag_snapshot"), Mapping):
            post = (bag.get("bag_snapshot") or {}).get("post_weight_lbs")
        try:
            if pre is not None and pre != "":
                pre_sum += float(pre)
                pre_n += 1
        except (TypeError, ValueError):
            pass
        try:
            if post is not None and post != "":
                post_sum += float(post)
                post_n += 1
        except (TypeError, ValueError):
            pass
    # Prefer POST when any POST evidence exists; else PRE.
    lbs = None
    basis = None
    if post_n > 0:
        lbs = round(post_sum, 1)
        basis = "post_weight_lbs"
    elif pre_n > 0:
        lbs = round(pre_sum, 1)
        basis = "pre_weight_lbs"
    return {
        "pounds": lbs,
        "pounds_basis": basis,
        "pounds_available": lbs is not None and lbs > 0,
        "pre_weight_lbs": round(pre_sum, 1) if pre_n else None,
        "post_weight_lbs": round(post_sum, 1) if post_n else None,
        "pre_weight_bag_count": pre_n,
        "post_weight_bag_count": post_n,
    }


def _build_cost_dashboard(
    *,
    selected_date_et: date,
    cards: Sequence[Mapping[str, Any]],
    population_orders: int,
    confirmed_orders: int,
    confirmed_loads: int,
    total_cost: float | None,
    pounds_info: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Day-grain cost dashboard — same shape can later roll up Daily/Weekly/Monthly
    by summing period rows (do not bake UI-only period logic here).
    """
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
        # Unique workload bags (not sum of per-product order counts).
        "unique_orders": int(population_orders),
        "confirmed_orders": int(confirmed_orders),
        # Canonical processing units across workload (not sum of product doses).
        "confirmed_loads": int(confirmed_loads),
        "pounds": lbs,
        "pounds_basis": pounds_info.get("pounds_basis"),
        "pounds_available": bool(pounds_info.get("pounds_available")),
        "kpis": {
            "cost_per_order": cost_per_order,
            "cost_per_load": cost_per_load,
            "cost_per_lb": cost_per_lb,
            "orders_basis": "confirmed_unique_orders",
            "loads_basis": "confirmed_canonical_processing_units",
            "pounds_basis": pounds_info.get("pounds_basis"),
        },
    }


def build_management_wf_supply_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = SCOPE_ALL,
) -> dict[str, Any]:
    """Compact confirmed product cards + status for Management Rinse WF."""
    scope = normalize_rush_scope(rush_scope)
    mapping_rules = get_supply_usage_mapping_rules(cursor, organization_id)
    membership = management_wf_supply_membership(
        cursor, organization_id, selected_date_et, rush_scope=scope
    )
    order_rows, population_ids = load_orders_for_management_wf_supplies(
        cursor,
        organization_id,
        selected_date_et,
        rush_scope=scope,
        mapping_rules=mapping_rules,
        membership=membership,
    )
    products = _active_products_as_of(cursor, organization_id, selected_date_et)
    cards = _product_usage_cards(order_rows, products)
    pounds_info = _population_pounds(membership)

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
            sum(float(c.get("estimated_cost") or 0) for c in cards if c.get("estimated_cost") is not None),
            2,
        )

    dashboard = _build_cost_dashboard(
        selected_date_et=selected_date_et,
        cards=cards,
        population_orders=len(population_ids),
        confirmed_orders=confirmed_orders,
        confirmed_loads=confirmed_loads,
        total_cost=total_cost,
        pounds_info=pounds_info,
    )

    # Legacy key map for transitional UI / tests
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
        }

    status = "FINAL" if fin.get("finalizable") else "PROVISIONAL"
    banner = None
    banner_detail = None
    if not fin.get("finalizable"):
        banner = (
            f"PROVISIONAL · {pending_reviews} split review"
            f"{'s' if pending_reviews != 1 else ''} pending"
        )
        banner_detail = (
            "Costs may increase after pending split reviews are resolved. "
            "Confirmed totals exclude unresolved split increments."
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
            "bag_ids_count": len(population_ids),
            "confirmed_orders": confirmed_orders,
            "confirmed_loads": confirmed_loads,
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
        "data_source": (
            "management_wf_day_bags membership + rinse_wf_canonical_split "
            "+ supply_product_master effective-dated cost"
        ),
        "as_of_date_et": selected_date_et.isoformat(),
        "price_basis": "effective_dated_as_of_selected_et_date",
        # Terminology: confirmed_doses == confirmed processing loads per product
        # (Not Split → 1 · Split → 2). Doses can exceed orders when splits apply.
        "terminology": {
            "doses": "confirmed_processing_loads_per_product",
            "orders": "unique_bags_using_product",
            "loads_population": "canonical_processing_units_across_workload",
            "split_rule": "not_split_1_split_2",
        },
    }


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
    """Lazy order-level rows for one product (or all products)."""
    scope = normalize_rush_scope(rush_scope)
    summary = build_management_wf_supply_summary(
        cursor, organization_id, selected_date_et, rush_scope=scope
    )
    mapping_rules = get_supply_usage_mapping_rules(cursor, organization_id)
    order_rows, _ = load_orders_for_management_wf_supplies(
        cursor,
        organization_id,
        selected_date_et,
        rush_scope=scope,
        mapping_rules=mapping_rules,
    )
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
        # Dose == confirmed processing loads for this product (split=2, normal=1).
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
