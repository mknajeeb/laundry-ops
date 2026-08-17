"""Day specialty metrics for Step-1 Today's Workload (comforters, bath mats, rejected).

Isolated from WF classify / Employee Productivity. Counts are distinct order IDs.
Normalized item classes are stored on the day summary snapshot so historical
numbers do not drift when mapping rules change later.

Rejected Orders are authoritative from scan chronology only:
an order counts when it has at least one scan/event with purpose create-issue
on the selected ET day (within the current service/rush membership filter).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scan_purpose import is_create_issue_purpose
from backend.ta_helpers import table_exists

CLASSIFICATION_VERSION = 2

ITEM_CLASS_COMFORTER = "comforter"
ITEM_CLASS_BATH_MAT = "bath_mat"

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


def is_create_issue_rejected_scan(purpose: Any) -> bool:
    """Authoritative rejected-order signal: scan purpose create-issue."""
    return is_create_issue_purpose(purpose)


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


def _load_create_issue_rejections(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """
    Distinct member orders with at least one create-issue scan on the ET day.

    Returns first create-issue event metadata per order (time + employee).
    Does not use registry completion, bulk workitems, or disappearance reasons.
    """
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, dict[str, Any]] = {}
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    ph = ",".join(["%s"] * len(ids))
    # scanned_at_parsed is naive America/New_York wall time.
    cursor.execute(
        f"""
        SELECT bag_id, scanned_at_parsed, purpose, user_name, id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IN ({ph})
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < DATE_ADD(%s, INTERVAL 1 DAY)
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), *ids, selected_date_et, selected_date_et),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if not is_create_issue_rejected_scan(row.get("purpose")):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid or bid in out:
            # First create-issue only (query ordered ascending).
            continue
        ts = row.get("scanned_at_parsed")
        out[bid] = {
            "bag_id": bid,
            "create_issue_at": ts,
            "create_issue_by": (str(row.get("user_name") or "").strip() or None),
            "create_issue_purpose": "create-issue",
            "create_issue_event_id": row.get("id"),
            "completion_status": "REJECTED",
            "completion_reason": "create-issue",
            "completed_at": ts,
        }
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
        entry["rejection_status"] = rejection.get("completion_status") or "REJECTED"
        entry["rejection_reason"] = rejection.get("completion_reason") or "create-issue"
        entry["rejection_at"] = (
            rejection.get("create_issue_at") or rejection.get("completed_at")
        )
        entry["create_issue_at"] = rejection.get("create_issue_at") or entry["rejection_at"]
        entry["create_issue_by"] = rejection.get("create_issue_by")
        entry["rejection_by"] = rejection.get("create_issue_by")
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
    Build comforter / bath-mat / rejected / split cards for day membership.

    Rejected Orders = distinct member orders with ≥1 create-issue scan on the
    selected ET day. Card counts = distinct order numbers in each orders list.
    """
    member_ids = _membership_ids_from_summary(summary, service=service)
    ctx = _bag_context_from_summary(summary)
    specialty = _load_bulk_specialty_lines(
        cursor, organization_id, selected_date_et, member_ids
    )
    create_issues = _load_create_issue_rejections(
        cursor, organization_id, selected_date_et, member_ids
    )
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
    for bid, issue in create_issues.items():
        rejected_orders[bid] = _order_entry(
            bid,
            ctx=ctx.get(bid) or {"bag_id": bid, "status": "rejected"},
            customer=customers.get(bid),
            rejection=issue,
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
        total_quantity = 0.0
        for order in ordered:
            try:
                total_quantity += float(order.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
        return {
            "key": key,
            "count": len(ordered),
            "order_count": len(ordered),
            "total_quantity": round(total_quantity, 1) if total_quantity else 0,
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
    out["comforter_item_qty"] = all_pack["comforter_orders"].get("total_quantity") or 0
    out["bath_mat_item_qty"] = all_pack["bath_mat_orders"].get("total_quantity") or 0
    out["rejected_order_count"] = all_pack["rejected_orders"]["count"]
    out["split_order_count"] = all_pack["split_orders"]["count"]
    return out


def specialty_order_ids_from_summary(
    summary: Mapping[str, Any],
    *,
    metric: str,
    service: str = "all",
    rush: str = "all",
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
    ids = {
        normalize_bag_id(b)
        for b in (pack.get("order_ids") or [o.get("bag_id") for o in (pack.get("orders") or [])])
        if normalize_bag_id(b)
    }
    r = str(rush or "all").strip().lower().replace("-", "_")
    if r in ("rush", "non_rush"):
        # Intersect with the active service×rush segment so KPI/drawer share one list.
        segs = summary.get("segments") or {}
        if svc == "wf":
            seg_key = "wf_rush" if r == "rush" else "wf_non_rush"
        elif svc == "hd":
            seg_key = "hd_rush" if r == "rush" else "hd_non_rush"
        else:
            seg_key = "rush" if r == "rush" else "non_rush"
        bags = ((segs.get(seg_key) or {}).get("bag_ids") or {})
        allowed: set[str] = set()
        for bucket in ("new_today", "carryover", "completed", "pending", "review_required"):
            for raw in bags.get(bucket) or []:
                bid = normalize_bag_id(raw)
                if bid:
                    allowed.add(bid)
        ids &= allowed
    return sorted(ids)