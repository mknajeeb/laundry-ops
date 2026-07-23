"""Inventory v2.5 operational analytics — dashboard, history, reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.inventory_constants import (
    ADJUSTMENT_BAG_SALE,
    ADJUSTMENT_MANUAL,
    ADJUSTMENT_ORDER_RECEIVE,
    ADJUSTMENT_STOCK_CHECK,
    ORDER_CANCELLED,
    ORDER_ORDERED,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    STOCK_CHECK_SUBMITTED,
)
from backend.inventory_module import (
    _d,
    _float,
    _money,
    _sum_purchase_orders,
    ensure_inventory_tables,
    get_latest_stock_check,
    get_variance_threshold,
    list_items,
    list_reorder_suggestions,
    migrate_legacy_inventory,
)


def _sum_purchases(cursor, org_id: int, start: date, end: date) -> float:
    return _sum_purchase_orders(cursor, org_id, start, end)


def build_dashboard(cursor, org_id: int, *, include_financials: bool = True) -> dict:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    items = list_items(cursor, org_id, active_only=True)
    low_stock = list_reorder_suggestions(cursor, org_id)

    inventory_value = _money(sum(_d(i.get("estimated_value")) for i in items))

    items_out = 0
    items_low = 0
    recently_counted = 0
    needs_recount = 0
    week_ago = datetime.now() - timedelta(days=7)
    for item in items:
        mode = str(item.get("tracking_mode") or "QUANTITY").upper()
        if mode == "STATUS":
            level = str(item.get("status_level") or "OK").upper()
            if level == "OUT":
                items_out += 1
            elif level == "LOW":
                items_low += 1
        else:
            on_hand = _float(item.get("current_on_hand"))
            if on_hand <= 0:
                items_out += 1
            elif on_hand <= _float(item.get("reorder_level")):
                items_low += 1
        if item.get("needs_recount"):
            needs_recount += 1
        lca = item.get("last_count_at")
        if lca:
            try:
                dt = lca if isinstance(lca, datetime) else datetime.fromisoformat(str(lca).replace("Z", ""))
                if dt >= week_ago:
                    recently_counted += 1
            except Exception:
                pass

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM inventory_orders
        WHERE organization_id = %s AND status IN (%s, %s)
        """,
        (org_id, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED),
    )
    pending_pos = int((cursor.fetchone() or {}).get("c") or 0)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    this_week = _sum_purchases(cursor, org_id, week_start, today)
    this_month = _sum_purchases(cursor, org_id, month_start, today)

    latest = get_latest_stock_check(cursor, org_id)
    days_since_check = None
    last_check_label = None
    if latest and latest.get("submitted_at"):
        submitted = latest["submitted_at"]
        if isinstance(submitted, datetime):
            days_since_check = (datetime.now() - submitted).days
        last_check_label = latest.get("checked_by_name")

    category_totals: dict[str, float] = {}
    for item in items:
        cat = item.get("category_name") or "Other"
        category_totals[cat] = category_totals.get(cat, 0) + _float(item.get("estimated_value"))

    kpis = {
        "inventory_value": inventory_value if include_financials else None,
        "items_below_reorder": len(low_stock),
        "items_low": items_low,
        "items_out": items_out,
        "need_ordering": len(low_stock),
        "recently_counted": recently_counted,
        "needs_recount": needs_recount,
        "pending_purchase_orders": pending_pos,
        "this_week_purchases": this_week if include_financials else None,
        "this_month_purchases": this_month if include_financials else None,
        "last_stock_check_by": last_check_label,
        "last_stock_check_at": latest.get("submitted_at") if latest else None,
        "days_since_last_check": days_since_check,
        "variance_threshold": get_variance_threshold(cursor, org_id),
    }

    low_stock_rows = [
        {
            "id": i["id"],
            "name": i.get("name"),
            "category": i.get("category_name"),
            "on_hand": i.get("current_on_hand"),
            "status_level": i.get("status_level"),
            "tracking_mode": i.get("tracking_mode"),
            "reorder_level": i.get("reorder_level"),
            "suggested_qty": i.get("suggested_qty") or i.get("suggested_order_qty"),
            "vendor": i.get("vendor_name") or i.get("default_vendor_name"),
            "weeks_remaining": i.get("weeks_remaining"),
        }
        for i in low_stock
    ]

    activity = get_recent_activity(cursor, org_id, limit=15)
    recount_items = [
        {"id": i["id"], "name": i.get("name"), "category": i.get("category_name")}
        for i in items if i.get("needs_recount")
    ]

    return {
        "kpis": kpis,
        "low_stock": low_stock_rows,
        "needs_recount": recount_items,
        "category_value_totals": [
            {"category": k, "value": _money(v)} for k, v in sorted(category_totals.items(), key=lambda x: -x[1])
        ],
        "recent_activity": activity,
    }


def _activity_label(row: dict) -> str:
    atype = row.get("event_type") or row.get("activity_type") or ""
    actor = row.get("actor") or row.get("created_by_name") or "Someone"
    item = row.get("item_name") or ""
    if atype == "STOCK_CHECK":
        return f"{actor} counted inventory" + (f" ({item})" if item else "")
    if atype in ("ORDER", "PURCHASE_ORDER"):
        vendor = row.get("vendor_name") or row.get("extra_value") or "vendor"
        status = row.get("status") or row.get("extra_value") or ""
        if "RECEIVED" in str(status).upper():
            return f"{vendor} order received"
        return f"{vendor} order created"
    if atype == ADJUSTMENT_MANUAL or atype == "ADJUSTMENT":
        return f"{item or 'Inventory'} adjusted by {actor}"
    if atype == ADJUSTMENT_ORDER_RECEIVE or atype == "RECEIVED":
        return f"{item} received (+{row.get('qty_change') or row.get('qty')})"
    if atype == "BAG_SALE":
        return f"Bag sale recorded by {actor}"
    return f"{actor} — {atype} {item}".strip()


def get_recent_activity(cursor, org_id: int, *, limit: int = 20) -> list[dict]:
    ensure_inventory_tables(cursor)
    events: list[dict] = []

    cursor.execute(
        """
        SELECT sc.id, 'STOCK_CHECK' AS event_type, sc.submitted_at AS event_at,
               sc.checked_by_name AS actor, NULL AS item_name, NULL AS qty_change,
               NULL AS vendor_name, sc.status
        FROM inventory_stock_checks sc
        WHERE sc.organization_id = %s AND sc.status = %s
        ORDER BY sc.submitted_at DESC LIMIT %s
        """,
        (org_id, STOCK_CHECK_SUBMITTED, limit),
    )
    events.extend(cursor.fetchall() or [])

    cursor.execute(
        """
        SELECT o.id, 'PURCHASE_ORDER' AS event_type, COALESCE(o.received_date, o.order_date, o.created_at) AS event_at,
               o.ordered_by_name AS actor, NULL AS item_name, NULL AS qty_change,
               COALESCE(o.vendor_name, v.name) AS vendor_name, o.status
        FROM inventory_orders o
        LEFT JOIN inventory_vendors v ON v.id = o.vendor_id
        WHERE o.organization_id = %s
        ORDER BY o.created_at DESC LIMIT %s
        """,
        (org_id, limit),
    )
    events.extend(cursor.fetchall() or [])

    cursor.execute(
        """
        SELECT a.id, a.adjustment_type AS event_type, a.created_at AS event_at,
               a.created_by_name AS actor, i.item_name, a.qty_change, NULL AS vendor_name, a.reason AS status
        FROM inventory_adjustments a
        JOIN inventory_items i ON i.id = a.item_id
        WHERE a.organization_id = %s
        ORDER BY a.created_at DESC LIMIT %s
        """,
        (org_id, limit),
    )
    events.extend(cursor.fetchall() or [])

    events.sort(key=lambda r: r.get("event_at") or datetime.min, reverse=True)
    out = []
    for e in events[:limit]:
        out.append({
            "id": e.get("id"),
            "event_at": e.get("event_at"),
            "label": _activity_label(e),
            "event_type": e.get("event_type"),
        })
    return out


def get_item_history(cursor, org_id: int, item_id: int, *, limit: int = 100) -> list[dict]:
    ensure_inventory_tables(cursor)
    history: list[dict] = []

    cursor.execute(
        """
        SELECT sc.submitted_at AS event_at, 'Weekly Count' AS event_label,
               scl.counted_qty AS qty, scl.previous_on_hand, scl.variance_qty, scl.variance_reason,
               sc.checked_by_name AS actor
        FROM inventory_stock_check_lines scl
        JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
        WHERE sc.organization_id = %s AND scl.item_id = %s AND sc.status = %s AND scl.counted_qty IS NOT NULL
        ORDER BY sc.submitted_at DESC LIMIT %s
        """,
        (org_id, item_id, STOCK_CHECK_SUBMITTED, limit),
    )
    for r in cursor.fetchall() or []:
        prev = _float(r.get("previous_on_hand"))
        counted = _float(r.get("counted_qty"))
        change = counted - prev
        history.append({
            "event_at": r.get("event_at"),
            "event_label": "Weekly Count",
            "qty_change": change,
            "display_qty": counted,
            "previous_qty": prev,
            "actor": r.get("actor"),
            "note": r.get("variance_reason"),
        })

    # Status-only checks (counted_qty may be null)
    try:
        cursor.execute(
            """
            SELECT sc.submitted_at AS event_at, 'Status Check' AS event_label,
                   scl.status_level, scl.previous_on_hand, scl.note,
                   sc.checked_by_name AS actor
            FROM inventory_stock_check_lines scl
            JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
            WHERE sc.organization_id = %s AND scl.item_id = %s AND sc.status = %s
              AND scl.status_level IS NOT NULL AND scl.counted_qty IS NULL
            ORDER BY sc.submitted_at DESC LIMIT %s
            """,
            (org_id, item_id, STOCK_CHECK_SUBMITTED, limit),
        )
        for r in cursor.fetchall() or []:
            history.append({
                "event_at": r.get("event_at"),
                "event_label": f"Status → {r.get('status_level')}",
                "qty_change": 0,
                "display_qty": None,
                "previous_qty": _float(r.get("previous_on_hand")),
                "actor": r.get("actor"),
                "note": r.get("note"),
                "status_level": r.get("status_level"),
            })
    except Exception:
        pass

    cursor.execute(
        """
        SELECT o.received_date AS event_at, 'Received' AS event_label,
               ol.qty_received AS qty, o.ordered_by_name AS actor, o.vendor_name
        FROM inventory_order_lines ol
        JOIN inventory_orders o ON o.id = ol.order_id
        WHERE o.organization_id = %s AND ol.item_id = %s AND ol.qty_received > 0
        ORDER BY o.received_date DESC, o.id DESC LIMIT %s
        """,
        (org_id, item_id, limit),
    )
    for r in cursor.fetchall() or []:
        history.append({
            "event_at": r.get("event_at"),
            "event_label": "Received",
            "qty_change": _float(r.get("qty")),
            "display_qty": _float(r.get("qty")),
            "actor": r.get("actor"),
            "note": r.get("vendor_name"),
        })

    cursor.execute(
        """
        SELECT created_at AS event_at, adjustment_type, qty_change, reason, reason_code, created_by_name AS actor
        FROM inventory_adjustments
        WHERE organization_id = %s AND item_id = %s
        ORDER BY created_at DESC LIMIT %s
        """,
        (org_id, item_id, limit),
    )
    for r in cursor.fetchall() or []:
        label = "Adjustment"
        if r.get("adjustment_type") == ADJUSTMENT_STOCK_CHECK:
            label = "Weekly Count"
        elif r.get("adjustment_type") == ADJUSTMENT_ORDER_RECEIVE:
            label = "Received"
        elif r.get("adjustment_type") == ADJUSTMENT_BAG_SALE:
            label = "Bag Sale"
        history.append({
            "event_at": r.get("event_at"),
            "event_label": label,
            "qty_change": _float(r.get("qty_change")),
            "display_qty": None,
            "actor": r.get("actor"),
            "note": r.get("reason_code") or r.get("reason"),
        })

    history.sort(key=lambda r: r.get("event_at") or datetime.min, reverse=True)
    return history[:limit]


def get_reports_bundle(cursor, org_id: int, report_type: str = "all") -> dict:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    today = date.today()
    month_start = today.replace(day=1)
    out: dict[str, Any] = {}

    if report_type in ("all", "inventory_value"):
        items = list_items(cursor, org_id, active_only=True)
        out["inventory_value"] = {
            "total": _money(sum(_d(i.get("estimated_value")) for i in items)),
            "by_category": {},
        }
        for i in items:
            cat = i.get("category_name") or "Other"
            out["inventory_value"]["by_category"][cat] = out["inventory_value"]["by_category"].get(cat, 0) + _float(i.get("estimated_value"))
        out["inventory_value"]["by_category"] = {k: _money(v) for k, v in out["inventory_value"]["by_category"].items()}

    if report_type in ("all", "purchases_by_vendor"):
        cursor.execute(
            """
            SELECT COALESCE(o.vendor_name, v.name, 'Unknown') AS vendor_name,
                   COALESCE(SUM(o.grand_total), 0) AS total
            FROM inventory_orders o
            LEFT JOIN inventory_vendors v ON v.id = o.vendor_id
            WHERE o.organization_id = %s AND o.status NOT IN (%s)
              AND o.order_date >= %s
            GROUP BY COALESCE(o.vendor_name, v.name, 'Unknown')
            ORDER BY total DESC
            """,
            (org_id, ORDER_CANCELLED, month_start),
        )
        out["purchases_by_vendor"] = [{"vendor": r["vendor_name"], "total": _money(r["total"])} for r in (cursor.fetchall() or [])]

    if report_type in ("all", "purchases_by_category"):
        cursor.execute(
            """
            SELECT COALESCE(c.name, 'Uncategorized') AS category,
                   COALESCE(SUM(ol.line_total), 0) AS total
            FROM inventory_order_lines ol
            JOIN inventory_orders o ON o.id = ol.order_id
            JOIN inventory_items i ON i.id = ol.item_id
            LEFT JOIN inventory_categories c ON c.id = i.category_id
            WHERE o.organization_id = %s AND o.status NOT IN (%s) AND o.order_date >= %s
            GROUP BY c.name ORDER BY total DESC
            """,
            (org_id, ORDER_CANCELLED, month_start),
        )
        out["purchases_by_category"] = [{"category": r["category"], "total": _money(r["total"])} for r in (cursor.fetchall() or [])]

    if report_type in ("all", "monthly_spend"):
        cursor.execute(
            """
            SELECT DATE_FORMAT(order_date, '%%Y-%%m') AS month_key,
                   COALESCE(SUM(grand_total), 0) AS total
            FROM inventory_orders
            WHERE organization_id = %s AND status NOT IN (%s)
              AND order_date >= DATE_SUB(%s, INTERVAL 6 MONTH)
            GROUP BY DATE_FORMAT(order_date, '%%Y-%%m')
            ORDER BY month_key
            """,
            (org_id, ORDER_CANCELLED, today),
        )
        out["monthly_spend"] = [{"month": r["month_key"], "total": _money(r["total"])} for r in (cursor.fetchall() or [])]

    if report_type in ("all", "low_inventory"):
        out["low_inventory"] = list_reorder_suggestions(cursor, org_id)

    if report_type in ("all", "adjustments"):
        cursor.execute(
            """
            SELECT a.created_at, a.adjustment_type, a.qty_change, a.reason, a.reason_code,
                   i.item_name, a.created_by_name
            FROM inventory_adjustments a
            JOIN inventory_items i ON i.id = a.item_id
            WHERE a.organization_id = %s AND a.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            ORDER BY a.created_at DESC LIMIT 200
            """,
            (org_id,),
        )
        out["adjustments"] = cursor.fetchall() or []

    if report_type in ("all", "stock_checks"):
        cursor.execute(
            """
            SELECT id, check_date, checked_by_name, submitted_at, notes
            FROM inventory_stock_checks
            WHERE organization_id = %s AND status = %s
            ORDER BY submitted_at DESC LIMIT 52
            """,
            (org_id, STOCK_CHECK_SUBMITTED),
        )
        out["stock_check_history"] = cursor.fetchall() or []

    if report_type in ("all", "most_purchased", "least_purchased"):
        cursor.execute(
            """
            SELECT i.item_name, COALESCE(SUM(ol.qty_ordered), 0) AS qty, COALESCE(SUM(ol.line_total), 0) AS total
            FROM inventory_order_lines ol
            JOIN inventory_orders o ON o.id = ol.order_id
            JOIN inventory_items i ON i.id = ol.item_id
            WHERE o.organization_id = %s AND o.status NOT IN (%s)
              AND o.order_date >= DATE_SUB(%s, INTERVAL 6 MONTH)
            GROUP BY i.id, i.item_name
            ORDER BY qty DESC
            """,
            (org_id, ORDER_CANCELLED, today),
        )
        ranked = cursor.fetchall() or []
        out["most_purchased"] = [
            {"item_name": r["item_name"], "qty": _float(r["qty"]), "total": _money(r["total"])} for r in ranked[:10]
        ]
        out["least_purchased"] = [
            {"item_name": r["item_name"], "qty": _float(r["qty"]), "total": _money(r["total"])} for r in ranked[-10:]
        ] if len(ranked) > 10 else []

    return out
