"""Day specialty metrics for Step-1 Today's Workload (comforters, bath mats, rejected).

Isolated from WF classify / Employee Productivity. Counts are distinct order IDs.
Normalized item classes are stored on the day summary snapshot so historical
numbers do not drift when mapping rules change later.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists

CLASSIFICATION_VERSION = 1

ITEM_CLASS_COMFORTER = "comforter"
ITEM_CLASS_BATH_MAT = "bath_mat"

# Legacy auto-rejects from portal disappearance — not canonical "Rejected Orders".
_NON_CANONICAL_REJECTION_REASONS = frozenset(
    {
        "MISSING_FROM_LATEST_PORTAL_SCRAPE",
    }
)

_COMFORTER_RE = re.compile(r"^comforters?$", re.IGNORECASE)
_BATH_MAT_RE = re.compile(r"^bath[\s_-]*mats?$", re.IGNORECASE)


def normalize_specialty_item_name(raw: Any) -> str | None:
    """Normalize recognized specialty item names at the ingestion/read boundary."""
    name = str(raw or "").strip()
    if not name:
        return None
    # Collapse internal whitespace for matching; keep original only for display qty.
    compact = re.sub(r"\s+", " ", name)
    if _COMFORTER_RE.match(compact):
        return ITEM_CLASS_COMFORTER
    if _BATH_MAT_RE.match(compact):
        return ITEM_CLASS_BATH_MAT
    return None


def is_canonical_rejected(
    *,
    completion_status: Any,
    completion_reason: Any = None,
) -> bool:
    """True only for explicit canonical rejection — not disappearance / review."""
    status = str(completion_status or "").strip().upper()
    if status != "REJECTED":
        return False
    reason = str(completion_reason or "").strip().upper()
    if reason in _NON_CANONICAL_REJECTION_REASONS:
        return False
    return True


def _membership_ids_from_summary(
    summary: Mapping[str, Any],
    *,
    service: str = "all",
) -> list[str]:
    segs = summary.get("segments") or {}
    svc = str(service or "all").strip().lower()
    if svc == "wf":
        seg = segs.get("wf") or {}
    elif svc == "hd":
        seg = segs.get("hd") or {}
    else:
        seg = segs.get("all") or segs.get("wf") or {}
        # Union WF+HD when "all" so specialty cards cover both services.
        if svc == "all":
            ids: set[str] = set()
            for key in ("all", "wf", "hd"):
                bags = ((segs.get(key) or {}).get("bag_ids") or {})
                for bucket in ("new_today", "carryover", "completed", "pending", "review_required"):
                    ids |= {normalize_bag_id(b) for b in (bags.get(bucket) or []) if normalize_bag_id(b)}
            return sorted(ids)
    bags = seg.get("bag_ids") or {}
    ids = set()
    for bucket in ("new_today", "carryover", "completed", "pending", "review_required"):
        ids |= {normalize_bag_id(b) for b in (bags.get(bucket) or []) if normalize_bag_id(b)}
    return sorted(ids)


def _bag_context_from_summary(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Best-effort service / rush / status from segment membership."""
    ctx: dict[str, dict[str, Any]] = {}
    segs = summary.get("segments") or {}
    for svc_key, svc_label in (("wf", "WF"), ("hd", "HD")):
        seg = segs.get(svc_key) or {}
        bags = seg.get("bag_ids") or {}
        for bucket, status in (
            ("completed", "completed"),
            ("pending", "pending"),
            ("review_required", "review_required"),
            ("new_today", None),
            ("carryover", None),
        ):
            for raw in bags.get(bucket) or []:
                bid = normalize_bag_id(raw)
                if not bid:
                    continue
                row = ctx.setdefault(bid, {"bag_id": bid, "service": svc_label})
                if status and not row.get("status"):
                    row["status"] = status
        for rush_key, rush_label in ((f"{svc_key}_rush", "RUSH"), (f"{svc_key}_non_rush", "NON_RUSH")):
            rseg = segs.get(rush_key) or {}
            rbags = rseg.get("bag_ids") or {}
            for bucket in ("new_today", "carryover", "completed", "pending", "review_required"):
                for raw in rbags.get(bucket) or []:
                    bid = normalize_bag_id(raw)
                    if not bid:
                        continue
                    row = ctx.setdefault(bid, {"bag_id": bid, "service": svc_label})
                    row["rush"] = rush_label
    return ctx


def _load_bulk_specialty_lines(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if not ids or not table_exists(cursor, "rinse_bag_bulk_workitems"):
        return out
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT bag_id, workitem_name_snapshot, quantity
        FROM rinse_bag_bulk_workitems
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND bag_id IN ({ph})
        """,
        (int(organization_id), selected_date_et, *ids),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid or bid not in out:
            continue
        item_class = normalize_specialty_item_name(row.get("workitem_name_snapshot"))
        if not item_class:
            continue
        try:
            qty = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        out[bid].append(
            {
                "item_class": item_class,
                "item_name_raw": row.get("workitem_name_snapshot"),
                "quantity": qty,
            }
        )
    return out


def _load_registry_rejection_map(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, dict[str, Any]] = {}
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return out
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT bag_id, completion_status, completion_reason, completed_at,
               service_type, name_clean, rush_type
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id IN ({ph})
        """,
        (int(organization_id), *ids),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out[bid] = dict(row)
    return out


def _load_split_orders_from_supply_usage(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Reuse Supply Usage split_order flags — do not reimplement detection."""
    member = {normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)}
    if not member:
        return {}
    try:
        from backend.supply_usage import load_orders_for_supply_usage
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = load_orders_for_supply_usage(cursor, organization_id, selected_date_et)
    except Exception:
        return {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("split_order"):
            continue
        bid = normalize_bag_id(row.get("order_id") or row.get("ticket_id") or row.get("bag_id"))
        if not bid or bid not in member:
            continue
        out[bid] = dict(row)
    return out


def _load_customer_names(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, str | None]:
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, str | None] = {b: None for b in ids}
    if not ids:
        return out
    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, customer_name
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if bid and row.get("customer_name"):
                out[bid] = str(row.get("customer_name"))
    return out


def _order_entry(
    bid: str,
    *,
    ctx: Mapping[str, Any],
    customer: str | None,
    quantity: float | None = None,
    rejection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "bag_id": bid,
        "order_number": bid,
        "customer_name": customer,
        "service": ctx.get("service"),
        "rush": ctx.get("rush"),
        "status": ctx.get("status"),
    }
    if quantity is not None:
        entry["quantity"] = quantity
    if rejection:
        entry["rejection_status"] = rejection.get("completion_status")
        entry["rejection_reason"] = rejection.get("completion_reason")
        entry["rejection_at"] = rejection.get("completed_at")
        if not entry.get("service") and rejection.get("service_type"):
            entry["service"] = rejection.get("service_type")
        if not entry.get("customer_name") and rejection.get("name_clean"):
            entry["customer_name"] = rejection.get("name_clean")
        if not entry.get("rush") and rejection.get("rush_type"):
            entry["rush"] = rejection.get("rush_type")
    return entry


def build_day_specialty_metrics(
    cursor,
    organization_id: int,
    selected_date_et: date,
    summary: Mapping[str, Any],
    *,
    service: str = "all",
) -> dict[str, Any]:
    """
    Build comforter / bath-mat / rejected order cards for the day membership.

    Card counts = distinct order numbers in each orders list.
    """
    member_ids = _membership_ids_from_summary(summary, service=service)
    ctx = _bag_context_from_summary(summary)
    specialty = _load_bulk_specialty_lines(
        cursor, organization_id, selected_date_et, member_ids
    )
    registry = _load_registry_rejection_map(cursor, organization_id, member_ids)
    customers = _load_customer_names(cursor, organization_id, member_ids)
    split_rows = _load_split_orders_from_supply_usage(
        cursor, organization_id, selected_date_et, member_ids
    )

    comforter_orders: dict[str, dict[str, Any]] = {}
    bath_mat_orders: dict[str, dict[str, Any]] = {}
    for bid in member_ids:
        lines = specialty.get(bid) or []
        comforter_qty = sum(
            float(x.get("quantity") or 0)
            for x in lines
            if x.get("item_class") == ITEM_CLASS_COMFORTER
        )
        bath_qty = sum(
            float(x.get("quantity") or 0)
            for x in lines
            if x.get("item_class") == ITEM_CLASS_BATH_MAT
        )
        if comforter_qty > 0:
            comforter_orders[bid] = _order_entry(
                bid,
                ctx=ctx.get(bid) or {"bag_id": bid},
                customer=customers.get(bid),
                quantity=comforter_qty,
            )
            comforter_orders[bid]["item_class"] = ITEM_CLASS_COMFORTER
        if bath_qty > 0:
            bath_mat_orders[bid] = _order_entry(
                bid,
                ctx=ctx.get(bid) or {"bag_id": bid},
                customer=customers.get(bid),
                quantity=bath_qty,
            )
            bath_mat_orders[bid]["item_class"] = ITEM_CLASS_BATH_MAT

    rejected_orders: dict[str, dict[str, Any]] = {}
    review_ids = set(
        normalize_bag_id(b)
        for b in (
            ((summary.get("segments") or {}).get("all") or {}).get("bag_ids") or {}
        ).get("review_required")
        or []
        if normalize_bag_id(b)
    )
    for bid in member_ids:
        reg = registry.get(bid) or {}
        if not is_canonical_rejected(
            completion_status=reg.get("completion_status"),
            completion_reason=reg.get("completion_reason"),
        ):
            continue
        # Review Required and Rejected remain separate: a bag under review for
        # disappearance without a canonical rejection reason is already excluded
        # by is_canonical_rejected. Keep review_ids out when reason is empty-ish.
        if bid in review_ids and not is_canonical_rejected(
            completion_status=reg.get("completion_status"),
            completion_reason=reg.get("completion_reason"),
        ):
            continue
        rejected_orders[bid] = _order_entry(
            bid,
            ctx=ctx.get(bid) or {"bag_id": bid, "status": "rejected"},
            customer=customers.get(bid),
            rejection=reg,
        )
        rejected_orders[bid]["status"] = "rejected"

    split_orders: dict[str, dict[str, Any]] = {}
    for bid, row in split_rows.items():
        entry = _order_entry(
            bid,
            ctx=ctx.get(bid) or {"bag_id": bid, "status": "split"},
            customer=customers.get(bid) or row.get("customer"),
        )
        if not entry.get("service") and row.get("service_type"):
            entry["service"] = row.get("service_type")
        entry["status"] = "split"
        entry["split_order"] = True
        entry["split_status"] = row.get("split_status")
        entry["split_confirmed"] = row.get("split_confirmed")
        entry["washer_load_count"] = row.get("washer_load_count")
        entry["washer_racks"] = list(row.get("washer_racks") or [])
        split_orders[bid] = entry

    def _pack(orders: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        ordered = [orders[k] for k in sorted(orders.keys())]
        return {
            "key": key,
            "count": len(ordered),
            "order_ids": [o["bag_id"] for o in ordered],
            "orders": ordered,
        }

    return {
        "classification_version": CLASSIFICATION_VERSION,
        "selected_date_et": selected_date_et.isoformat(),
        "service_filter": str(service or "all").lower(),
        "comforter_orders": _pack(comforter_orders, "comforter_orders"),
        "bath_mat_orders": _pack(bath_mat_orders, "bath_mat_orders"),
        "rejected_orders": _pack(rejected_orders, "rejected_orders"),
        "split_orders": _pack(split_orders, "split_orders"),
    }


def attach_specialty_metrics_to_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach all/wf/hd specialty metric packs onto the summary snapshot."""
    out = dict(summary or {})
    packs = {
        "all": build_day_specialty_metrics(
            cursor, organization_id, selected_date_et, out, service="all"
        ),
        "wf": build_day_specialty_metrics(
            cursor, organization_id, selected_date_et, out, service="wf"
        ),
        "hd": build_day_specialty_metrics(
            cursor, organization_id, selected_date_et, out, service="hd"
        ),
    }
    out["specialty_metrics"] = packs
    # Convenience aliases for the default (all-services) cards.
    all_pack = packs["all"]
    out["comforter_order_count"] = all_pack["comforter_orders"]["count"]
    out["bath_mat_order_count"] = all_pack["bath_mat_orders"]["count"]
    out["rejected_order_count"] = all_pack["rejected_orders"]["count"]
    out["split_order_count"] = all_pack["split_orders"]["count"]
    return out


def specialty_order_ids_from_summary(
    summary: Mapping[str, Any],
    *,
    metric: str,
    service: str = "all",
) -> list[str]:
    """Resolve drawer bag ids for specialty metric keys from the frozen snapshot."""
    key = str(metric or "").strip().lower().replace("-", "_")
    aliases = {
        "comforters": "comforter_orders",
        "comforter": "comforter_orders",
        "comforter_orders": "comforter_orders",
        "bath_mats": "bath_mat_orders",
        "bath_mat": "bath_mat_orders",
        "bath_mat_orders": "bath_mat_orders",
        "rejected": "rejected_orders",
        "rejected_orders": "rejected_orders",
        "split": "split_orders",
        "split_orders": "split_orders",
    }
    pack_key = aliases.get(key)
    if not pack_key:
        return []
    svc = str(service or "all").strip().lower()
    if svc not in ("all", "wf", "hd"):
        svc = "all"
    root = summary.get("specialty_metrics") or {}
    pack = (root.get(svc) or root.get("all") or {}).get(pack_key) or {}
    ids = pack.get("order_ids") or [o.get("bag_id") for o in (pack.get("orders") or [])]
    return sorted({normalize_bag_id(b) for b in ids if normalize_bag_id(b)})
