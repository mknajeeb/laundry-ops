"""
Complete registry bags missing from a confirmed full portal CSV snapshot.

On CONFIRM only: incomplete bags for the tenant that are not in the new portal
upload are treated as having left the Rinse portal and marked COMPLETED.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED, normalize_bag_id
from backend.rinse_bag_registry import (
    ensure_rinse_bag_registry_table,
    get_registry_row,
    is_bag_already_completed,
    mark_registry_completed_portal_absence,
)
from backend.ta_helpers import table_exists, table_has_column


def build_current_upload_bag_ids(accepted_portal_rows: list[dict]) -> set[str]:
    out: set[str] = set()
    for row in accepted_portal_rows or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("ticket_id"))
        if bid:
            out.add(bid)
    return out


def upload_batch_is_full_snapshot_portal(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    accepted_portal_rows: list[dict],
) -> bool:
    """
    True when this confirm represents a full portal export (not scan-events-only).

    Uses upload_batches.full_snapshot when present; otherwise any confirm with
    accepted portal order rows (ticket_id-bearing CSV) is treated as a full snapshot.
    """
    from backend.upload_batch_requirements import batch_upload_files_status

    status = batch_upload_files_status(cursor, upload_batch_id, organization_id)
    if not status.get("has_order_rows"):
        return False
    if not accepted_portal_rows:
        return False

    if table_exists(cursor, "upload_batches") and table_has_column(
        cursor, "upload_batches", "full_snapshot"
    ):
        batch_pk = "id" if table_has_column(cursor, "upload_batches", "id") else "batch_id"
        cursor.execute(
            f"SELECT full_snapshot FROM upload_batches WHERE {batch_pk} = %s LIMIT 1",
            (int(upload_batch_id),),
        )
        row = cursor.fetchone()
        if row is not None:
            val = row.get("full_snapshot") if isinstance(row, dict) else row[0]
            if val is not None:
                return bool(int(val))

    return len(build_current_upload_bag_ids(accepted_portal_rows)) > 0


def fetch_incomplete_bag_candidates_for_org(
    cursor, organization_id: int
) -> set[str]:
    """Incomplete registry bags + active staging ticket_ids (same tenant)."""
    org = int(organization_id)
    candidates: set[str] = set()

    ensure_rinse_bag_registry_table(cursor)
    cursor.execute(
        """
        SELECT bag_id FROM rinse_bag_registry
        WHERE organization_id = %s
          AND UPPER(COALESCE(completion_status, '')) != %s
        """,
        (org, COMPLETION_COMPLETED),
    )
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id") if isinstance(row, dict) else row[0])
        if bid:
            candidates.add(bid)

    if not table_exists(cursor, "orders_staging"):
        return candidates

    from backend.app import orders_status_capabilities, where_not_sent_or_forced_sql

    cap = orders_status_capabilities(cursor)
    active_where = where_not_sent_or_forced_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_ticket_id = table_has_column(cursor, "orders_staging", "ticket_id")

    if not has_ticket_id:
        return candidates

    sql = f"""
        SELECT DISTINCT ticket_id
        FROM orders_staging
        WHERE {active_where}
          AND ticket_id IS NOT NULL
          AND TRIM(ticket_id) != ''
    """
    args: list[Any] = []
    if has_staging_org:
        sql += " AND organization_id = %s"
        args.append(org)
    cursor.execute(sql, tuple(args))
    for row in cursor.fetchall() or []:
        tid = normalize_bag_id(row.get("ticket_id") if isinstance(row, dict) else row[0])
        if not tid:
            continue
        reg = get_registry_row(cursor, org, tid)
        if reg is None:
            candidates.add(tid)
            continue
        if str(reg.get("completion_status") or "").upper() != COMPLETION_COMPLETED:
            candidates.add(tid)

    return candidates


def complete_bags_missing_from_latest_portal(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    accepted_portal_rows: list[dict],
    *,
    full_snapshot: bool | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Mark incomplete tenant bags absent from the confirmed portal CSV as COMPLETED.

    Returns counts and bag ids; does nothing when not a full portal snapshot.
    """
    org = int(organization_id)
    batch_id = int(upload_batch_id)
    accepted = list(accepted_portal_rows or [])

    is_full = (
        bool(full_snapshot)
        if full_snapshot is not None
        else upload_batch_is_full_snapshot_portal(cursor, org, batch_id, accepted)
    )
    if not is_full:
        return {
            "full_snapshot": False,
            "skipped": True,
            "reason": "not_full_snapshot_or_scan_events_only",
            "count": 0,
            "bag_ids": [],
        }

    current_ids = build_current_upload_bag_ids(accepted)
    if not current_ids:
        return {
            "full_snapshot": True,
            "skipped": True,
            "reason": "no_ticket_ids_in_portal_rows",
            "count": 0,
            "bag_ids": [],
        }

    candidates = fetch_incomplete_bag_candidates_for_org(cursor, org)
    missing = sorted(bid for bid in candidates if bid not in current_ids)
    when = completed_at or datetime.utcnow()
    completed: list[str] = []
    for bid in missing:
        if is_bag_already_completed(cursor, org, bid):
            continue
        if mark_registry_completed_portal_absence(
            cursor, org, bid, upload_batch_id=batch_id, completed_at=when
        ):
            completed.append(bid)

    return {
        "full_snapshot": True,
        "skipped": False,
        "count": len(completed),
        "bag_ids": completed,
        "current_upload_bag_count": len(current_ids),
    }
