"""Active orders_staging snapshot — same source as GET /dashboard."""

from __future__ import annotations

from typing import Any

from backend.rinse_order_search import _active_staging_where_sql
from backend.ta_helpers import table_exists, table_has_column


def dashboard_rush_expr(cursor) -> str:
    """Identical rush rule to GET /dashboard in app.py."""
    if table_has_column(cursor, "orders_staging", "rush_type"):
        return (
            "COALESCE(NULLIF(TRIM(rush_type), ''), "
            "CASE WHEN date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END)"
        )
    return "CASE WHEN date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"


def _classify_dashboard_row(service_type: str, effective_rush: str) -> str:
    svc = str(service_type or "WF").upper()
    if svc not in ("WF", "HD"):
        svc = "WF"
    rush = str(effective_rush or "").upper()
    bucket = "rush" if rush == "RUSH" else "nonrush"
    return f"{bucket}_{svc.lower()}"


def get_dashboard_active_staging_snapshot(
    cursor,
    organization_id: int,
) -> dict[str, Any]:
    """
    Active orders_staging rows and aggregates matching GET /dashboard exactly.
    No registry, presence, lifecycle, or supplements.
    """
    org = int(organization_id)
    empty_buckets = {
        "rush_wf_ids": [],
        "rush_hd_ids": [],
        "nonrush_wf_ids": [],
        "nonrush_hd_ids": [],
        "unknown_ids": [],
    }
    out: dict[str, Any] = {
        "source": "GET /dashboard orders_staging",
        "total_orders": 0,
        "wf_total": 0,
        "hd_total": 0,
        "wf_rush": 0,
        "wf_non_rush": 0,
        "hd_rush": 0,
        "hd_non_rush": 0,
        "batch_date": None,
        "staging_row_count": 0,
        "unique_bag_count": 0,
        "duplicate_staging_rows": 0,
        "rows": [],
        "unique_bag_ids": [],
        "active_staging_bag_ids": [],
        **empty_buckets,
    }

    if not table_exists(cursor, "orders_staging") or not table_has_column(
        cursor, "orders_staging", "ticket_id"
    ):
        return out

    active_where = _active_staging_where_sql(cursor)
    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    org_clause = " AND organization_id = %s" if has_org else ""
    args: list[Any] = [org] if has_org else []
    rush_expr = dashboard_rush_expr(cursor)

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_orders,
            MAX(batch_date) AS batch_date,
            SUM(service_type = 'WF') AS wf_total,
            SUM(service_type = 'HD') AS hd_total,
            SUM(service_type = 'WF' AND UPPER({rush_expr}) = 'RUSH') AS wf_rush,
            SUM(service_type = 'WF' AND UPPER({rush_expr}) <> 'RUSH') AS wf_non_rush,
            SUM(service_type = 'HD' AND UPPER({rush_expr}) = 'RUSH') AS hd_rush,
            SUM(service_type = 'HD' AND UPPER({rush_expr}) <> 'RUSH') AS hd_non_rush
        FROM orders_staging
        WHERE ({active_where}){org_clause}
        """,
        tuple(args),
    )
    stats = cursor.fetchone()
    if isinstance(stats, dict):
        for key in (
            "total_orders",
            "wf_total",
            "hd_total",
            "wf_rush",
            "wf_non_rush",
            "hd_rush",
            "hd_non_rush",
        ):
            out[key] = int(stats.get(key) or 0)
        out["batch_date"] = stats.get("batch_date")

    name_col = "name_clean" if table_has_column(cursor, "orders_staging", "name_clean") else "NULL"
    cursor.execute(
        f"""
        SELECT
            ticket_id AS bag_id,
            UPPER(COALESCE(service_type, 'WF')) AS service_type,
            UPPER({rush_expr}) AS effective_rush,
            {name_col} AS name_clean
        FROM orders_staging
        WHERE ({active_where}){org_clause}
          AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        ORDER BY ticket_id, id
        """,
        tuple(args),
    )

    seen: set[str] = set()
    bucket_map = {
        "rush_wf": "rush_wf_ids",
        "rush_hd": "rush_hd_ids",
        "nonrush_wf": "nonrush_wf_ids",
        "nonrush_hd": "nonrush_hd_ids",
    }
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        out["staging_row_count"] += 1
        bid = str(raw.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        svc = str(raw.get("service_type") or "WF").upper()
        rush = str(raw.get("effective_rush") or "").upper()
        bucket = _classify_dashboard_row(svc, rush)
        row = {
            "bag_id": bid,
            "service_type": svc if svc in ("WF", "HD") else "WF",
            "effective_rush": rush if rush in ("RUSH", "NON-RUSH") else rush,
            "rush_type": rush,
            "name_clean": raw.get("name_clean"),
            "in_active_staging": True,
            "registry_supplement": False,
            "presence_source": False,
            "record_scope": "hd_lifecycle" if svc == "HD" else "wf_lifecycle",
            "dashboard_bucket": bucket,
        }
        if bid in seen:
            out["duplicate_staging_rows"] += 1
            continue
        seen.add(bid)
        out["rows"].append(row)
        out["unique_bag_ids"].append(bid)
        if bucket in bucket_map:
            out[bucket_map[bucket]].append(bid)
        else:
            out["unknown_ids"].append(bid)

    out["unique_bag_count"] = len(out["unique_bag_ids"])
    out["active_staging_bag_ids"] = list(out["unique_bag_ids"])
    return out


def build_dashboard_vs_monitor_reconciliation(
    dashboard: dict[str, Any],
    monitor: dict[str, Any],
    *,
    monitor_bag_ids: list[str] | None = None,
) -> dict[str, Any]:
    dash_ids = {str(b).strip().upper() for b in (dashboard.get("unique_bag_ids") or []) if b}
    mon_ids = {str(b).strip().upper() for b in (monitor_bag_ids or dashboard.get("unique_bag_ids") or []) if b}
    return {
        "dashboard_total": int(dashboard.get("total_orders") or 0),
        "monitor_total": int(monitor.get("total") or 0),
        "match": int(dashboard.get("total_orders") or 0) == int(monitor.get("total") or 0),
        "dashboard_unique_bags": len(dash_ids),
        "monitor_unique_bags": len(mon_ids),
        "bag_ids_in_dashboard_not_monitor": sorted(dash_ids - mon_ids),
        "bag_ids_in_monitor_not_dashboard": sorted(mon_ids - dash_ids),
        "active_staging_bag_ids": sorted(dash_ids),
        "rush_wf_ids": sorted(dashboard.get("rush_wf_ids") or []),
        "rush_hd_ids": sorted(dashboard.get("rush_hd_ids") or []),
        "nonrush_wf_ids": sorted(dashboard.get("nonrush_wf_ids") or []),
        "nonrush_hd_ids": sorted(dashboard.get("nonrush_hd_ids") or []),
        "unknown_ids": sorted(dashboard.get("unknown_ids") or []),
        "duplicate_staging_rows": int(dashboard.get("duplicate_staging_rows") or 0),
        "source": dashboard.get("source"),
    }
