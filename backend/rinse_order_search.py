"""
Rinse order / bag archive search (full lifecycle, not checkout-only).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists, table_has_column


def _like(s: str) -> str:
    return f"%{s}%"


def _active_staging_where_sql(cursor) -> str:
    """Mirror app.where_not_sent_or_forced_sql without importing Flask app."""
    has_logistics = table_has_column(cursor, "orders_staging", "logistics_status")
    has_status = table_has_column(cursor, "orders_staging", "status")
    if has_logistics:
        if has_status:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if has_status:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def _in_checkout_exists_sql(has_staging_org: bool) -> str:
    org_clause = " AND s.organization_id = r.organization_id" if has_staging_org else ""
    return f"""
        EXISTS (
            SELECT 1 FROM orders_staging s
            WHERE s.ticket_id = r.bag_id{org_clause}
              AND ({{active_where}})
        )
    """


def search_rinse_orders(
    cursor,
    organization_id: int,
    *,
    bag_id: str | None = None,
    customer_name: str | None = None,
    batch_id: int | None = None,
    completion_status: str | None = None,
    folding_status: str | None = None,
    in_checkout: bool | None = None,
    lifecycle_filter: str | None = None,
    date_clean_from: date | None = None,
    date_clean_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Search registry bags with staging/folding flags and lifecycle summary counts."""
    org = int(organization_id)
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))

    summary = _lifecycle_summary(cursor, org)

    if not table_exists(cursor, "rinse_bag_registry"):
        return {"total": 0, "limit": lim, "offset": off, "summary": summary, "rows": []}

    active_where = _active_staging_where_sql(cursor)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_staging = table_exists(cursor, "orders_staging") and table_has_column(
        cursor, "orders_staging", "ticket_id"
    )

    lf = (lifecycle_filter or "").strip().lower()
    if lf == "completed":
        completion_status = completion_status or "COMPLETED"
    elif lf == "incomplete":
        completion_status = None
    elif lf == "folding_exceptions":
        folding_status = folding_status or "EXCEPTION"
    elif lf == "in_checkout":
        in_checkout = True

    where = ["r.organization_id = %s"]
    args: list[Any] = [org]

    if lf == "incomplete":
        where.append("UPPER(COALESCE(r.completion_status,'')) != 'COMPLETED'")

    if bag_id:
        bid = normalize_bag_id(bag_id)
        if bid:
            where.append("r.bag_id = %s")
            args.append(bid)
    if customer_name:
        where.append("r.name_clean LIKE %s")
        args.append(_like(customer_name.strip()))
    if completion_status:
        where.append("UPPER(COALESCE(r.completion_status,'')) = %s")
        args.append(str(completion_status).strip().upper())
    if date_clean_from:
        where.append("r.date_clean >= %s")
        args.append(date_clean_from)
    if date_clean_to:
        where.append("r.date_clean <= %s")
        args.append(date_clean_to)

    fold_join = ""
    if table_exists(cursor, "rinse_folding_performance"):
        fold_join = """
            LEFT JOIN rinse_folding_performance f
              ON f.organization_id = r.organization_id AND f.bag_id = r.bag_id
        """
        if folding_status:
            where.append("UPPER(COALESCE(f.status,'')) = %s")
            args.append(str(folding_status).strip().upper())

    batch_sql = ""
    if batch_id is not None:
        batch_sql = """
          AND EXISTS (
            SELECT 1 FROM upload_batch_rows ubr
            WHERE ubr.ticket_id = r.bag_id AND ubr.upload_batch_id = %s
          )
        """
        args.append(int(batch_id))

    checkout_sql = ""
    if in_checkout is not None and has_staging:
        exists_tpl = _in_checkout_exists_sql(has_staging_org).format(active_where=active_where)
        if in_checkout:
            where.append(exists_tpl)
        else:
            where.append(f"NOT ({exists_tpl.strip()})")

    where_clause = " AND ".join(where)

    count_sql = f"""
        SELECT COUNT(*) AS cnt
        FROM rinse_bag_registry r
        {fold_join}
        WHERE {where_clause}
        {batch_sql}
    """
    cursor.execute(count_sql, tuple(args))
    count_row = cursor.fetchone()
    total = int(count_row.get("cnt") or 0) if isinstance(count_row, dict) else 0

    cursor.execute(
        f"""
        SELECT
            r.bag_id, r.name_clean, r.date_clean, r.weight_num, r.service_type,
            r.rush_type, r.completion_status, r.completion_reason, r.completed_at,
            r.last_upload_batch_id, r.last_staging_order_id,
            f.status AS folding_status, f.exception_code AS folding_exception_code
        FROM rinse_bag_registry r
        {fold_join}
        WHERE {where_clause}
        {batch_sql}
        ORDER BY r.updated_at DESC, r.bag_id ASC
        LIMIT %s OFFSET %s
        """,
        tuple(args + [lim, off]),
    )
    rows = list(cursor.fetchall() or [])

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid = row.get("bag_id")
        in_co = False
        staging_id = None
        if bid and has_staging:
            sq = f"SELECT id FROM orders_staging WHERE ticket_id = %s AND ({active_where})"
            sq_args: list[Any] = [bid]
            if has_staging_org:
                sq += " AND organization_id = %s"
                sq_args.append(org)
            sq += " LIMIT 1"
            cursor.execute(sq, tuple(sq_args))
            hit = cursor.fetchone()
            if hit:
                in_co = True
                staging_id = hit.get("id") if isinstance(hit, dict) else hit[0]

        out_rows.append({**row, "in_checkout": in_co, "staging_order_id": staging_id})

    return {
        "total": total,
        "limit": lim,
        "offset": off,
        "summary": summary,
        "rows": out_rows,
    }


def _lifecycle_summary(cursor, org: int) -> dict[str, Any]:
    """Aggregate counts for admin dashboard chips."""
    out: dict[str, Any] = {
        "registry_total": 0,
        "completed": 0,
        "incomplete": 0,
        "in_checkout": 0,
        "folding_exceptions": 0,
    }
    if not table_exists(cursor, "rinse_bag_registry"):
        return out

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN UPPER(COALESCE(completion_status,'')) = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN UPPER(COALESCE(completion_status,'')) != 'COMPLETED' THEN 1 ELSE 0 END) AS incomplete
        FROM rinse_bag_registry
        WHERE organization_id = %s
        """,
        (org,),
    )
    reg = cursor.fetchone()
    if reg and isinstance(reg, dict):
        out["registry_total"] = int(reg.get("total") or 0)
        out["completed"] = int(reg.get("completed") or 0)
        out["incomplete"] = int(reg.get("incomplete") or 0)

    if table_exists(cursor, "orders_staging"):
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        org_clause = " AND organization_id = %s" if has_org else ""
        cursor.execute(
            f"SELECT COUNT(*) AS cnt FROM orders_staging WHERE ({active_where}){org_clause}",
            (org,) if has_org else (),
        )
        st = cursor.fetchone()
        if st and isinstance(st, dict):
            out["in_checkout"] = int(st.get("cnt") or 0)

    if table_exists(cursor, "rinse_folding_performance"):
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM rinse_folding_performance
            WHERE organization_id = %s AND status = 'EXCEPTION'
            """,
            (org,),
        )
        fx = cursor.fetchone()
        if fx and isinstance(fx, dict):
            out["folding_exceptions"] = int(fx.get("cnt") or 0)

    return out


def get_order_archive_detail(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    active_where_sql: str,
    has_staging_org: bool,
    has_ticket_id_col: bool,
    upload_batch_row_pk: str,
) -> dict[str, Any] | None:
    """Full lifecycle archive detail for one bag."""
    from backend.rinse_order_search_detail import build_order_lifecycle_detail
    from backend.rinse_scrape_status import get_scheduled_scrape_status

    detail = build_order_lifecycle_detail(
        cursor,
        organization_id,
        bag_id,
        active_where_sql=active_where_sql,
        has_staging_org=has_staging_org,
        has_ticket_id_col=has_ticket_id_col,
        upload_batch_row_pk=upload_batch_row_pk,
    )
    if not detail:
        return None

    org = int(organization_id)
    bid = detail["bag_id"]
    if detail.get("registry", {}).get("last_upload_batch_id") and table_exists(
        cursor, "upload_batch_rows"
    ):
        cursor.execute(
            f"""
            SELECT * FROM upload_batch_rows
            WHERE upload_batch_id = %s AND ticket_id = %s
            ORDER BY {upload_batch_row_pk} DESC
            LIMIT 1
            """,
            (int(detail["registry"]["last_upload_batch_id"]), bid),
        )
        detail["latest_upload_batch_row"] = cursor.fetchone()

    scrape_status = get_scheduled_scrape_status(cursor, org)
    detail["scheduled_scrape"] = scrape_status.get("last_success")
    detail["scheduled_scrape_status"] = scrape_status
    return detail
