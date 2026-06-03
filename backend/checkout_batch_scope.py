"""Scope checkout queue to the latest confirmed manual upload batch."""

from __future__ import annotations

from typing import Any

from backend.checkout_batch_source import (
    get_checkout_batch_source,
    upload_batch_is_auto_scrape,
)
from backend.rinse_bag_completion import normalize_bag_id
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


def checkout_batch_ticket_filter(cursor, organization_id: int) -> set[str] | None:
    """
    Ticket IDs that belong in checkout for this tenant.
    Manual/auto modes use their respective latest confirmed batch.
    Returns None when no batch applies (no filter).
    """
    batch = latest_checkout_batch(cursor, organization_id)
    if not batch or batch.get("batch_id") is None:
        return None
    ids = batch_accepted_ticket_ids(cursor, int(batch["batch_id"]))
    return ids if ids else None


def reapply_manual_batch_staging(
    cursor,
    organization_id: int,
    batch_id: int,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Reconcile ACCEPTED upload rows into orders_staging for a manual batch.

    Reactivates SENT rows and inserts missing staging for accepted ticket_ids.
    """
    from backend.rinse_bag_upload import find_staging_by_ticket_id, update_staging_from_upload_row
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    bid = int(batch_id)
    if upload_batch_is_auto_scrape(cursor, bid, org):
        return {"updated": 0, "inserted": 0, "skipped": 0, "dry_run": dry_run}

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
    cursor.execute(
        f"""
        SELECT date_clean, name_clean, weight_num, service_type, rush_type, ticket_id
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (bid,),
    )
    accepted_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]

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

        portal = {
            "date_clean": row["date_clean"],
            "name_clean": row["name_clean"],
            "weight_num": row["weight_num"],
            "service_type": row["service_type"],
            "rush_type": row.get("rush_type") or "NON-RUSH",
            "ticket_id": tid,
        }

        existing = find_staging_by_ticket_id(
            cursor,
            org,
            tid,
            has_staging_org=has_staging_org,
            has_ticket_id_col=True,
        )
        if existing:
            if not dry_run:
                update_staging_from_upload_row(
                    cursor,
                    int(existing["id"]),
                    portal,
                    batch_date,
                    cap,
                    organization_id=org,
                    has_staging_org=has_staging_org,
                )
                cursor.execute(
                    """
                    UPDATE rinse_bag_registry
                    SET last_staging_order_id = %s, updated_at = NOW()
                    WHERE organization_id = %s AND bag_id = %s
                    """,
                    (int(existing["id"]), org, tid),
                )
            updated += 1
            continue

        if dry_run:
            inserted += 1
            continue

        cols = [
            "date_clean",
            "name_clean",
            "weight_num",
            "service_type",
            "rush_type",
            "batch_date",
        ]
        vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
        args: list[Any] = [
            portal["date_clean"],
            portal["name_clean"],
            portal["weight_num"],
            portal["service_type"],
            portal["rush_type"],
            batch_date,
        ]
        if has_staging_org:
            cols = ["organization_id"] + cols
            vals = ["%s"] + vals
            args = [org] + args
        if cap.get("has_logistics"):
            cols.append("logistics_status")
            vals.append("%s")
            args.append("AT_WASHPRO")
        if cap.get("has_processing"):
            cols.append("processing_status")
            vals.append("%s")
            args.append("PENDING")
        if cap.get("has_status"):
            cols.append("status")
            vals.append("%s")
            args.append("PENDING")
        cols.append("ticket_id")
        vals.append("%s")
        args.append(tid[:120])

        cursor.execute(
            f"""
            INSERT INTO orders_staging ({", ".join(cols)})
            VALUES ({", ".join(vals)})
            """,
            tuple(args),
        )
        new_id = cursor.lastrowid
        inserted += 1
        cursor.execute(
            """
            UPDATE rinse_bag_registry
            SET last_staging_order_id = %s, updated_at = NOW()
            WHERE organization_id = %s AND bag_id = %s
            """,
            (int(new_id), org, tid),
        )

    return {"updated": updated, "inserted": inserted, "skipped": skipped, "dry_run": dry_run}
