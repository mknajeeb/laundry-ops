"""Operations dashboard summary (registry + staging; survives upload row purge)."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_order_search import _active_staging_where_sql
from backend.ta_helpers import table_exists, table_has_column


def effective_rush_expr(alias: str, *, date_col: str = "date_clean") -> str:
    """Same rush rule as checkout dashboard / GET /orders."""
    return (
        f"UPPER(COALESCE(NULLIF(TRIM({alias}.rush_type), ''), "
        f"CASE WHEN {alias}.{date_col} < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END))"
    )


def _service_expr(alias: str) -> str:
    return f"UPPER(COALESCE({alias}.service_type, 'WF'))"


def _completed_expr(alias: str) -> str:
    return f"UPPER(COALESCE({alias}.completion_status, '')) = '{COMPLETION_COMPLETED}'"


def get_operations_dashboard_summary(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    batch_id: int | None = None,
) -> dict[str, Any]:
    """
    Per-date (and optional batch) order counts from registry, with staging-only
    active rows for the same batch_date when no registry row exists yet.
    """
    org = int(organization_id)
    td = target_date
    out: dict[str, Any] = {
        "date": td.isoformat(),
        "batch_id": batch_id,
        "total_orders": 0,
        "rush_total": 0,
        "non_rush_total": 0,
        "completed_total": 0,
        "remaining_total": 0,
        "rush_completed": 0,
        "rush_remaining": 0,
        "non_rush_completed": 0,
        "non_rush_remaining": 0,
        "wf_total": 0,
        "wf_completed": 0,
        "wf_remaining": 0,
        "hd_total": 0,
        "hd_completed": 0,
        "hd_remaining": 0,
        "checkout_active": 0,
        "folding_exceptions": 0,
        "source": "registry+staging",
    }

    rows: list[dict[str, Any]] = []

    if table_exists(cursor, "rinse_bag_registry"):
        from backend.rinse_bag_registry import ensure_rinse_bag_registry_table

        ensure_rinse_bag_registry_table(cursor)
        rush = effective_rush_expr("r")
        svc = _service_expr("r")
        done = _completed_expr("r")
        where = ["r.organization_id = %s"]
        args: list[Any] = [org]
        if batch_id is not None:
            where.append(
                """(
                    r.date_clean = %s
                    OR r.last_upload_batch_id = %s
                    OR EXISTS (
                        SELECT 1 FROM upload_batch_rows ubr
                        WHERE ubr.ticket_id = r.bag_id AND ubr.upload_batch_id = %s
                    )
                )"""
            )
            args.extend([td, int(batch_id), int(batch_id)])
        else:
            where.append("r.date_clean = %s")
            args.append(td)

        cursor.execute(
            f"""
            SELECT
                r.bag_id,
                {svc} AS service_type,
                {rush} AS effective_rush,
                CASE WHEN {done} THEN 1 ELSE 0 END AS is_completed
            FROM rinse_bag_registry r
            WHERE {" AND ".join(where)}
            """,
            tuple(args),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict):
                rows.append(r)

    if table_exists(cursor, "orders_staging") and table_has_column(
        cursor, "orders_staging", "ticket_id"
    ):
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_batch = table_has_column(cursor, "orders_staging", "batch_date")
        has_rush = table_has_column(cursor, "orders_staging", "rush_type")
        rush_s = (
            effective_rush_expr("s")
            if has_rush
            else "CASE WHEN s.date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
        )
        svc_s = _service_expr("s")
        org_clause = " AND s.organization_id = %s" if has_org else ""
        batch_clause = ""
        st_args: list[Any] = []
        if has_batch:
            batch_clause = " AND s.batch_date = %s"
            st_args.append(td)
        if has_org:
            st_args.append(org)

        reg_exists = (
            "EXISTS (SELECT 1 FROM rinse_bag_registry r "
            "WHERE r.organization_id = s.organization_id AND r.bag_id = s.ticket_id)"
            if table_exists(cursor, "rinse_bag_registry")
            and has_org
            else (
                "EXISTS (SELECT 1 FROM rinse_bag_registry r WHERE r.bag_id = s.ticket_id)"
                if table_exists(cursor, "rinse_bag_registry")
                else "0"
            )
        )

        cursor.execute(
            f"""
            SELECT
                s.ticket_id AS bag_id,
                {svc_s} AS service_type,
                UPPER({rush_s}) AS effective_rush,
                0 AS is_completed
            FROM orders_staging s
            WHERE ({active_where}){org_clause}{batch_clause}
              AND s.ticket_id IS NOT NULL AND TRIM(s.ticket_id) != ''
              AND NOT ({reg_exists})
            """,
            tuple(st_args),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict) and r.get("bag_id"):
                rows.append(r)

        # Checkout active for batch date (staging only)
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM orders_staging s
            WHERE ({active_where}){org_clause}{batch_clause}
            """,
            tuple(st_args),
        )
        co = cursor.fetchone()
        if co and isinstance(co, dict):
            out["checkout_active"] = int(co.get("cnt") or 0)

    seen: set[str] = set()
    for r in rows:
        bid = str(r.get("bag_id") or "").strip().upper()
        if not bid or bid in seen:
            continue
        seen.add(bid)
        is_rush = str(r.get("effective_rush") or "").upper() == "RUSH"
        is_done = int(r.get("is_completed") or 0) == 1
        svc = str(r.get("service_type") or "WF").upper()
        is_wf = svc == "WF"
        is_hd = svc == "HD"

        out["total_orders"] += 1
        if is_rush:
            out["rush_total"] += 1
        else:
            out["non_rush_total"] += 1
        if is_done:
            out["completed_total"] += 1
        else:
            out["remaining_total"] += 1
        if is_rush and is_done:
            out["rush_completed"] += 1
        elif is_rush:
            out["rush_remaining"] += 1
        elif is_done:
            out["non_rush_completed"] += 1
        else:
            out["non_rush_remaining"] += 1
        if is_wf:
            out["wf_total"] += 1
            if is_done:
                out["wf_completed"] += 1
            else:
                out["wf_remaining"] += 1
        elif is_hd:
            out["hd_total"] += 1
            if is_done:
                out["hd_completed"] += 1
            else:
                out["hd_remaining"] += 1

    if table_exists(cursor, "rinse_folding_performance"):
        fold_where = ["p.organization_id = %s", "p.status = 'EXCEPTION'"]
        fold_args: list[Any] = [org]
        if table_exists(cursor, "rinse_bag_registry"):
            fold_where.append(
                """
                EXISTS (
                    SELECT 1 FROM rinse_bag_registry r
                    WHERE r.organization_id = p.organization_id
                      AND r.bag_id = p.bag_id
                      AND r.date_clean = %s
                )
                """
            )
            fold_args.append(td)
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM rinse_folding_performance p
            WHERE {" AND ".join(fold_where)}
            """,
            tuple(fold_args),
        )
        fx = cursor.fetchone()
        if fx and isinstance(fx, dict):
            out["folding_exceptions"] = int(fx.get("cnt") or 0)

    return out
