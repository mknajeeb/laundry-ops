"""Operations dashboard summary (upload batch for Washpro manual upload; registry fallback)."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED, normalize_bag_id
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


def _norm_rush(value: str | None) -> str:
    raw = str(value or "").strip().upper()
    return "RUSH" if raw == "RUSH" else "NON-RUSH"


def _classify_upload_row(row: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return (is_rush, is_wf, is_hd) for an upload_batch_rows record."""
    svc = str(row.get("service_type") or "WF").strip().upper()
    is_hd = svc == "HD"
    is_wf = svc == "WF"
    if is_hd:
        return False, False, True
    rush = _norm_rush(row.get("rush_type"))
    return rush == "RUSH", is_wf, False


def _upload_row_is_completed(
    row: dict[str, Any],
    registry_completed: set[str],
) -> bool:
    row_status = str(row.get("row_status") or "").strip().upper()
    reason = str(row.get("reason") or "").strip().upper()
    if row_status == "REJECTED_DUPLICATE" and reason == "ALREADY_COMPLETED":
        return True
    tid = normalize_bag_id(row.get("ticket_id"))
    return bool(tid and tid in registry_completed)


def _summary_from_upload_batch(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    batch_id: int,
) -> dict[str, Any]:
    """Counts from upload_batch_rows only — matches the manual Washpro upload file."""
    org = int(organization_id)
    batch_id = int(batch_id)
    out: dict[str, Any] = {
        "date": target_date.isoformat(),
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
        "source": "upload_batch",
    }

    row_batch_col = None
    for col in ("upload_batch_id", "batch_id"):
        if table_has_column(cursor, "upload_batch_rows", col):
            row_batch_col = col
            break
    if not row_batch_col:
        return out

    cursor.execute(
        f"""
        SELECT ticket_id, service_type, rush_type, row_status, reason
        FROM upload_batch_rows
        WHERE {row_batch_col} = %s
        """,
        (batch_id,),
    )
    batch_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]

    ticket_ids = [
        normalize_bag_id(r.get("ticket_id"))
        for r in batch_rows
        if normalize_bag_id(r.get("ticket_id"))
    ]
    registry_completed: set[str] = set()
    if ticket_ids and table_exists(cursor, "rinse_bag_registry"):
        from backend.rinse_bag_registry import ensure_rinse_bag_registry_table

        ensure_rinse_bag_registry_table(cursor)
        placeholders = ", ".join(["%s"] * len(ticket_ids))
        cursor.execute(
            f"""
            SELECT bag_id
            FROM rinse_bag_registry
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND UPPER(COALESCE(completion_status, '')) = %s
            """,
            tuple([org, *ticket_ids, COMPLETION_COMPLETED]),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict):
                bid = normalize_bag_id(row.get("bag_id"))
                if bid:
                    registry_completed.add(bid)

    batch_ticket_set = set(ticket_ids)
    for row in batch_rows:
        is_rush, is_wf, is_hd = _classify_upload_row(row)
        is_done = _upload_row_is_completed(row, registry_completed)

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

    if batch_ticket_set and table_exists(cursor, "orders_staging") and table_has_column(
        cursor, "orders_staging", "ticket_id"
    ):
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        org_clause = " AND s.organization_id = %s" if has_org else ""
        placeholders = ", ".join(["%s"] * len(batch_ticket_set))
        args: list[Any] = []
        if has_org:
            args.append(org)
        args.extend(batch_ticket_set)
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM orders_staging s
            WHERE ({active_where}){org_clause}
              AND UPPER(TRIM(s.ticket_id)) IN ({placeholders})
            """,
            tuple(args),
        )
        co = cursor.fetchone()
        if co and isinstance(co, dict):
            out["checkout_active"] = int(co.get("cnt") or 0)

    if table_exists(cursor, "rinse_folding_performance") and batch_ticket_set:
        placeholders = ", ".join(["%s"] * len(batch_ticket_set))
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM rinse_folding_performance p
            WHERE p.organization_id = %s
              AND p.status = 'EXCEPTION'
              AND UPPER(TRIM(p.bag_id)) IN ({placeholders})
            """,
            tuple([org, *batch_ticket_set]),
        )
        fx = cursor.fetchone()
        if fx and isinstance(fx, dict):
            out["folding_exceptions"] = int(fx.get("cnt") or 0)

    return out


def get_operations_dashboard_summary(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    batch_id: int | None = None,
) -> dict[str, Any]:
    """
    Order counts for the Operations Dashboard.

    When batch_id is set (Washpro manual upload), totals come from upload_batch_rows
    for that batch only — not registry last_upload_batch_id or delivery-date slices.
    Without batch_id, falls back to registry + staging for the target delivery date.
    """
    if batch_id is not None and table_exists(cursor, "upload_batch_rows"):
        return _summary_from_upload_batch(
            cursor,
            organization_id,
            target_date=target_date,
            batch_id=int(batch_id),
        )

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
        where = ["r.organization_id = %s", "r.date_clean = %s"]
        args: list[Any] = [org, td]

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
