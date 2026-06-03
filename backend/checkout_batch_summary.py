"""Checkout rush/non-rush counts from latest confirmed upload batch vs active staging queue."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.manual_checkout_eligibility import REASON_RACK_SCAN_AFTER_CLEAN_LABEL
from backend.ta_helpers import table_exists, table_has_column


def _orders_status_capabilities(cursor) -> dict[str, bool]:
    return {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }


def _where_active_at_washpro_sql(cap: dict[str, bool]) -> str:
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if cap["has_status"]:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def _norm_rush(value: str | None) -> str:
    raw = str(value or "").strip().upper()
    return "RUSH" if raw == "RUSH" else "NON-RUSH"


def _latest_confirmed_batch(
    cursor,
    organization_id: int,
    *,
    source: str = "manual",
) -> dict[str, Any] | None:
    """Latest confirmed batch matching checkout source (manual upload vs auto scrape)."""
    from backend.checkout_batch_source import upload_batch_is_auto_scrape

    if not table_exists(cursor, "upload_batches"):
        return None
    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"
    org_clause = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_clause = " AND organization_id = %s"
        args.append(int(organization_id))
    want_auto = str(source or "manual").strip().lower() == "auto"
    cursor.execute(
        f"""
        SELECT {batch_pk} AS batch_id, batch_date, confirmed_at
        FROM upload_batches
        WHERE confirmed_at IS NOT NULL{org_clause}
        ORDER BY confirmed_at DESC, {batch_pk} DESC
        LIMIT 50
        """,
        tuple(args),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or row.get("batch_id") is None:
            continue
        is_auto = upload_batch_is_auto_scrape(
            cursor, int(row["batch_id"]), int(organization_id)
        )
        if want_auto == is_auto:
            return row
    return None


def _batch_row_col(cursor, table: str, candidates: tuple[str, ...]) -> str | None:
    for col in candidates:
        if table_has_column(cursor, table, col):
            return col
    return None


def build_checkout_batch_summary(
    cursor,
    organization_id: int,
    *,
    source: str = "manual",
) -> dict[str, Any]:
    """
    Compare latest confirmed upload batch rows to active checkout queue (orders_staging).

    source=manual: latest confirmed manual upload (Washpro Excel).
    source=auto: latest confirmed auto-scrape batch (VeeWash scheduled scrape).
    """
    org = int(organization_id)
    batch_source = str(source or "manual").strip().lower()
    if batch_source not in ("manual", "auto"):
        batch_source = "manual"
    out: dict[str, Any] = {
        "batch_id": None,
        "batch_date": None,
        "confirmed_at": None,
        "checkout_batch_source": batch_source,
        "rush": _empty_bucket(),
        "non_rush": _empty_bucket(),
        "missing_rush_rows": [],
    }
    batch = _latest_confirmed_batch(cursor, org, source=batch_source)
    if not batch or batch.get("batch_id") is None:
        return out

    batch_id = batch["batch_id"]
    batch_date = batch.get("batch_date")
    out["batch_id"] = batch_id
    if isinstance(batch_date, date):
        out["batch_date"] = batch_date.isoformat()
    elif batch_date is not None:
        out["batch_date"] = str(batch_date)
    confirmed_at = batch.get("confirmed_at")
    if isinstance(confirmed_at, datetime):
        out["confirmed_at"] = confirmed_at.isoformat()

    if not table_exists(cursor, "upload_batch_rows"):
        return out

    row_batch_col = _batch_row_col(cursor, "upload_batch_rows", ("upload_batch_id", "batch_id"))
    if not row_batch_col:
        return out

    cursor.execute(
        f"""
        SELECT ticket_id, date_clean, name_clean, service_type, rush_type,
               row_status, reason, weight_num
        FROM upload_batch_rows
        WHERE {row_batch_col} = %s
        """,
        (batch_id,),
    )
    batch_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    batch_ticket_set: set[str] = set()
    for row in batch_rows:
        tid = normalize_bag_id(row.get("ticket_id"))
        if tid:
            batch_ticket_set.add(tid)

    cap = _orders_status_capabilities(cursor)
    active_where = _where_active_at_washpro_sql(cap)
    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_rush = table_has_column(cursor, "orders_staging", "rush_type")
    has_ticket = table_has_column(cursor, "orders_staging", "ticket_id")
    date_rush = "CASE WHEN o.date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
    rush_expr = (
        f"UPPER(COALESCE(NULLIF(TRIM(o.rush_type), ''), {date_rush}))"
        if has_rush
        else date_rush
    )
    org_clause = " AND o.organization_id = %s" if has_org else ""
    cursor.execute(
        f"""
        SELECT o.id, o.ticket_id, o.name_clean, o.date_clean, o.service_type,
               {rush_expr} AS effective_rush,
               o.status, o.logistics_status, o.weight_num
        FROM orders_staging o
        WHERE ({active_where}){org_clause}
        """,
        (org,) if has_org else (),
    )
    active_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]

    def _staging_bucket(row: dict[str, Any]) -> str:
        rush = str(row.get("effective_rush") or "").strip().upper()
        return "rush" if rush == "RUSH" else "non_rush"

    queue_remaining = {"rush": 0, "non_rush": 0}
    for row in active_rows:
        tid = normalize_bag_id(row.get("ticket_id"))
        if batch_ticket_set and tid and tid not in batch_ticket_set:
            continue
        queue_remaining[_staging_bucket(row)] += 1

    def classify_batch_row(row: dict[str, Any]) -> str:
        rush = _norm_rush(row.get("rush_type"))
        return "rush" if rush == "RUSH" else "non_rush"

    active_by_ticket: dict[str, dict[str, Any]] = {}
    if has_ticket:
        for row in active_rows:
            tid = normalize_bag_id(row.get("ticket_id"))
            if tid:
                active_by_ticket[tid] = row

    checked_out_tickets: set[str] = set()
    if has_ticket and table_exists(cursor, "orders_staging"):
        sent_statuses = ("SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT", "FORCED_CHECKOUT")
        if cap["has_logistics"]:
            sent_clause = (
                f"COALESCE(logistics_status, CASE "
                f"WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE' "
                f"WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT' "
                f"ELSE 'AT_WASHPRO' END) IN ({', '.join('%s' for _ in sent_statuses)})"
            )
        elif cap["has_status"]:
            sent_clause = f"status IN ({', '.join('%s' for _ in sent_statuses)})"
        else:
            sent_clause = None
        if sent_clause:
            org_args: list[Any] = list(sent_statuses)
            sent_org = ""
            if has_org:
                sent_org = " AND organization_id = %s"
                org_args.append(org)
            cursor.execute(
                f"""
                SELECT ticket_id
                FROM orders_staging
                WHERE ticket_id IS NOT NULL AND ({sent_clause}){sent_org}
                """,
                tuple(org_args),
            )
            for row in cursor.fetchall() or []:
                if isinstance(row, dict):
                    tid = normalize_bag_id(row.get("ticket_id"))
                    if tid:
                        checked_out_tickets.add(tid)

    buckets = {"rush": _empty_bucket(), "non_rush": _empty_bucket()}
    missing_rush: list[dict[str, Any]] = []
    from backend.checkout_batch_source import upload_batch_is_auto_scrape
    from backend.manual_checkout_settings import checkout_at_vendor_override_active

    is_auto_batch = upload_batch_is_auto_scrape(cursor, int(batch_id), org)
    checkout_override = checkout_at_vendor_override_active(cursor, org)

    for row in batch_rows:
        bucket_key = classify_batch_row(row)
        bucket = buckets[bucket_key]
        bucket["total"] += 1

        tid = normalize_bag_id(row.get("ticket_id"))
        in_queue = bool(tid and tid in active_by_ticket)
        row_status = str(row.get("row_status") or "").strip().upper()
        reason = str(row.get("reason") or "").strip().upper()

        if checkout_override and tid:
            from backend.manual_checkout_eligibility import effective_checkout_row_status

            eff_status, eff_reason = effective_checkout_row_status(
                cursor,
                org,
                {**row, "batch_date": batch_date},
                has_active_staging=in_queue,
                is_auto_scrape=is_auto_batch,
            )
            row_status = str(eff_status or "").strip().upper()
            reason = str(eff_reason or "").strip().upper()

        exclude_reason = None

        if in_queue:
            pass
        elif row_status == "REJECTED_DUPLICATE" and reason == "RACK_SCAN_AFTER_CLEAN":
            bucket["excluded_rack_scan_after_clean"] += 1
            exclude_reason = REASON_RACK_SCAN_AFTER_CLEAN_LABEL
        elif row_status == "REJECTED_DUPLICATE" and reason in (
            "ALREADY_SENT_TO_RINSE",
            "ALREADY_CHECKED_OUT",
        ):
            bucket["excluded_already_sent"] += 1
            exclude_reason = "Already sent / checked out"
        elif row_status == "REJECTED_DUPLICATE" and reason == "ALREADY_FORCE_CHECKOUT":
            bucket["excluded_force_checkout"] += 1
            exclude_reason = "Force checkout"
        elif row_status == "REJECTED_DUPLICATE" and reason == "ALREADY_COMPLETED":
            bucket["excluded_already_completed"] += 1
            exclude_reason = "ALREADY_COMPLETED (batch rejected duplicate)"
        elif row_status in ("ACCEPTED", "OVERRIDDEN"):
            if tid and tid in checked_out_tickets:
                bucket["checked_out"] += 1
            else:
                bucket["excluded_not_staged"] += 1
                exclude_reason = "ACCEPTED but not in active staging (identity or confirm skip)"
        else:
            bucket["excluded_other"] += 1
            exclude_reason = f"Batch row status {row_status or 'UNKNOWN'}"

        if bucket_key == "rush" and exclude_reason:
            missing_rush.append(
                {
                    "bag_id": tid or row.get("ticket_id"),
                    "customer": row.get("name_clean"),
                    "delivery_date": (
                        row["date_clean"].isoformat()
                        if isinstance(row.get("date_clean"), date)
                        else row.get("date_clean")
                    ),
                    "service_type": row.get("service_type"),
                    "rush_type": row.get("rush_type"),
                    "row_status": row.get("row_status"),
                    "reason": row.get("reason"),
                    "weight_num": row.get("weight_num"),
                    "reason_excluded": exclude_reason,
                }
            )

    for key in ("rush", "non_rush"):
        buckets[key]["remaining"] = int(queue_remaining.get(key) or 0)

    out["rush"] = buckets["rush"]
    out["non_rush"] = buckets["non_rush"]
    out["missing_rush_rows"] = missing_rush
    return out


def _empty_bucket() -> dict[str, int]:
    return {
        "total": 0,
        "remaining": 0,
        "checked_out": 0,
        "excluded_already_completed": 0,
        "excluded_rack_scan_after_clean": 0,
        "excluded_already_sent": 0,
        "excluded_force_checkout": 0,
        "excluded_not_staged": 0,
        "excluded_other": 0,
    }
