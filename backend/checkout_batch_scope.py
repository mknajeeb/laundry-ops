"""Scope checkout queue to the latest confirmed manual upload batch."""

from __future__ import annotations

from typing import Any

from backend.checkout_batch_source import (
    get_checkout_batch_source,
    upload_batch_is_auto_scrape,
)
from backend.rinse_bag_completion import normalize_bag_id
from backend.manual_checkout_eligibility import (
    effective_checkout_row_status,
    reclassify_checkout_batch_upload_rows,
    ticket_has_checkout_log,
)
from backend.ta_helpers import table_exists, table_has_column


def _batch_pk(cursor) -> str:
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        return "id"
    return "batch_id"


def _row_batch_col(cursor) -> str | None:
    for col in ("upload_batch_id", "batch_id"):
        if table_has_column(cursor, "upload_batch_rows", col):
            return col
    return None


def latest_checkout_batch(
    cursor,
    organization_id: int,
    *,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Latest confirmed batch for this tenant's checkout source mode."""
    if not table_exists(cursor, "upload_batches"):
        return None
    org = int(organization_id)
    mode = source or get_checkout_batch_source(cursor, org)
    want_auto = str(mode).strip().lower() == "auto"
    batch_pk = _batch_pk(cursor)
    org_clause = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_clause = " AND organization_id = %s"
        args.append(org)
    cursor.execute(
        f"""
        SELECT {batch_pk} AS batch_id, batch_date, confirmed_at, file_name
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
        is_auto = upload_batch_is_auto_scrape(cursor, int(row["batch_id"]), org)
        if want_auto == is_auto:
            return row
    return None


def batch_accepted_ticket_ids(cursor, batch_id: int) -> set[str]:
    """Normalized ticket_ids for ACCEPTED/OVERRIDDEN rows in an upload batch."""
    row_col = _row_batch_col(cursor)
    if not row_col or not table_exists(cursor, "upload_batch_rows"):
        return set()
    cursor.execute(
        f"""
        SELECT ticket_id
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
          AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        """,
        (int(batch_id),),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            tid = normalize_bag_id(row.get("ticket_id"))
            if tid:
                out.add(tid)
    return out


def batch_checkout_eligible_ticket_ids(
    cursor,
    batch_id: int,
    organization_id: int,
) -> set[str]:
    """
    Ticket IDs that belong in the live checkout queue for this batch.

    When at-vendor override is active, re-evaluates each batch row (same rules as
    checkout batch summary) so COMPLETED bags still in the vendor source are included
    even if upload_batch_rows still says REJECTED_DUPLICATE / ALREADY_COMPLETED.
    """
    from backend.manual_checkout_settings import checkout_at_vendor_override_active

    org = int(organization_id)
    bid = int(batch_id)
    if not checkout_at_vendor_override_active(cursor, org):
        return batch_accepted_ticket_ids(cursor, bid)

    row_col = _row_batch_col(cursor)
    if not row_col or not table_exists(cursor, "upload_batch_rows"):
        return set()

    batch_pk = _batch_pk(cursor)
    cursor.execute(
        f"SELECT batch_date FROM upload_batches WHERE {batch_pk} = %s",
        (bid,),
    )
    batch = cursor.fetchone()
    batch_date = batch.get("batch_date") if isinstance(batch, dict) else None
    is_auto = upload_batch_is_auto_scrape(cursor, bid, org)

    cursor.execute(
        f"""
        SELECT ticket_id, date_clean, name_clean, service_type, rush_type,
               row_status, reason, weight_num
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        """,
        (bid,),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid:
            continue
        eff_status, _reason = effective_checkout_row_status(
            cursor,
            org,
            {**row, "batch_date": batch_date},
            is_auto_scrape=is_auto,
        )
        if str(eff_status or "").strip().upper() not in ("ACCEPTED", "OVERRIDDEN"):
            continue
        if ticket_has_checkout_log(cursor, org, tid):
            continue
        out.add(tid)
    return out


def _checkout_staging_rows_for_batch(cursor, organization_id: int, batch_id: int) -> list[dict]:
    """Upload batch rows that should be staged for checkout (after optional reclassify)."""
    from backend.manual_checkout_settings import checkout_at_vendor_override_active

    org = int(organization_id)
    bid = int(batch_id)
    if checkout_at_vendor_override_active(cursor, org):
        reclassify_checkout_batch_upload_rows(cursor, org, bid)

    row_col = _row_batch_col(cursor)
    if not row_col or not table_exists(cursor, "upload_batch_rows"):
        return []
    cursor.execute(
        f"""
        SELECT date_clean, name_clean, weight_num, service_type, rush_type, ticket_id
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (bid,),
    )
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def checkout_batch_ticket_filter(cursor, organization_id: int) -> set[str] | None:
    """
    Ticket IDs that belong in checkout for this tenant.
    Manual/auto modes use their respective latest confirmed batch.
    Returns None when no batch applies (no filter).
    """
    batch = latest_checkout_batch(cursor, organization_id)
    if not batch or batch.get("batch_id") is None:
        return None
    org = int(organization_id)
    ids = batch_checkout_eligible_ticket_ids(cursor, int(batch["batch_id"]), org)
    return ids if ids else None


def reapply_checkout_batch_staging(
    cursor,
    organization_id: int,
    batch_id: int,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Reconcile ACCEPTED upload rows into orders_staging for a checkout batch.

    Applies to manual portal uploads and auto at_vendor scrapes. Reactivates SENT rows
    and inserts missing staging for accepted ticket_ids.
    """
    from backend.checkout_batch_staging import upsert_staging_for_ticket_upload_row
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    bid = int(batch_id)

    row_col = _row_batch_col(cursor)
    if not row_col or not table_exists(cursor, "upload_batch_rows"):
        return {"updated": 0, "inserted": 0, "skipped": 0, "dry_run": dry_run}

    batch_pk = _batch_pk(cursor)
    cursor.execute(
        f"SELECT {batch_pk} AS batch_id, batch_date FROM upload_batches WHERE {batch_pk} = %s",
        (bid,),
    )
    batch = cursor.fetchone()
    if not batch or not isinstance(batch, dict):
        return {"updated": 0, "inserted": 0, "skipped": 0, "dry_run": dry_run}

    batch_date = batch.get("batch_date")
    accepted_rows = _checkout_staging_rows_for_batch(cursor, org, bid)

    cap = {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")

    updated = 0
    inserted = 0
    skipped = 0

    for row in accepted_rows:
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid or not cap.get("has_ticket_id"):
            skipped += 1
            continue

        if dry_run:
            from backend.rinse_bag_upload import find_staging_by_ticket_id
            from backend.manual_checkout_settings import checkout_at_vendor_override_active

            existing = find_staging_by_ticket_id(
                cursor,
                org,
                tid,
                has_staging_org=has_staging_org,
                has_ticket_id_col=True,
            )
            reactivate = checkout_at_vendor_override_active(cursor, org)
            if existing:
                from backend.manual_checkout_eligibility import staging_checkout_sent_reason

                if staging_checkout_sent_reason(existing) and not reactivate:
                    skipped += 1
                else:
                    updated += 1
            else:
                inserted += 1
            continue

        from backend.manual_checkout_settings import checkout_at_vendor_override_active

        reactivate = checkout_at_vendor_override_active(cursor, org)
        action, _sid = upsert_staging_for_ticket_upload_row(
            cursor,
            org,
            row,
            batch_date,
            cap,
            has_staging_org=has_staging_org,
            reactivate_sent=reactivate,
        )
        if action == "updated":
            updated += 1
        elif action == "inserted":
            inserted += 1
        else:
            skipped += 1

    return {"updated": updated, "inserted": inserted, "skipped": skipped, "dry_run": dry_run}


reapply_manual_batch_staging = reapply_checkout_batch_staging
