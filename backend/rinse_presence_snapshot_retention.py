"""Retain latest immutable presence snapshots; protect midnight baseline runs."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
from backend.rinse_shift_monitor_baseline import select_daily_at_vendor_baseline_scrape
from backend.ta_helpers import table_exists

KEEP_LATEST_SUCCESSFUL_SNAPSHOTS = 3


def _is_successful_presence_run(run: Mapping[str, Any]) -> bool:
    status = str(run.get("status") or "").strip().lower()
    if status in ("success", "partial"):
        return True
    errors = run.get("errors_json")
    return status == "" and errors in (None, "", "[]", "null", "NULL")


def _list_successful_presence_runs(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    rinse_vendor: str | None = None,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return []
    org = int(organization_id)
    ps = str(portal_status or "").strip()
    vendor = str(rinse_vendor or "").strip().lower() or None
    sql = """
        SELECT id, organization_id, portal_status, source_batch_id, status, finished_at, created_at,
               scrape_meta_json, rows_found
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND portal_status = %s AND dry_run = 0
        ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
    """
    cursor.execute(sql, (org, ps))
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or not _is_successful_presence_run(row):
            continue
        if vendor:
            meta = row.get("scrape_meta_json")
            meta_vendor = None
            if isinstance(meta, dict):
                meta_vendor = str(meta.get("rinse_vendor") or meta.get("resolved_vendor") or "").strip().lower()
            if meta_vendor and meta_vendor != vendor:
                continue
        out.append(dict(row))
    return out


def resolve_protected_presence_run_ids(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    selected_date_et: date | None = None,
) -> set[int]:
    """Runs that must not be pruned (latest N + required midnight baseline)."""
    runs = _list_successful_presence_runs(cursor, organization_id, portal_status=portal_status)
    keep: set[int] = set()
    for row in runs[:KEEP_LATEST_SUCCESSFUL_SNAPSHOTS]:
        rid = int(row.get("id") or 0)
        if rid:
            keep.add(rid)
    if portal_status == PORTAL_STATUS_AT_VENDOR and selected_date_et is not None:
        baseline_run, _ = select_daily_at_vendor_baseline_scrape(
            cursor, organization_id, selected_date_et
        )
        if baseline_run:
            bid = int(baseline_run.get("id") or 0)
            if bid:
                keep.add(bid)
    return keep


def prune_presence_run_snapshots(
    cursor,
    organization_id: int,
    *,
    portal_status: str,
    rinse_vendor: str | None = None,
    selected_date_et: date | None = None,
    keep_latest: int = KEEP_LATEST_SUCCESSFUL_SNAPSHOTS,
) -> dict[str, Any]:
    """
    Keep latest `keep_latest` successful snapshot runs (+ protected baseline) per org/status/vendor.
    Deletes older run_rows only; never deletes scan events, registry, staging, or current presence.
    """
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return {"deleted_run_rows": 0, "deleted_runs": 0, "kept_run_ids": [], "pruned_run_ids": []}

    runs = _list_successful_presence_runs(
        cursor, organization_id, portal_status=portal_status, rinse_vendor=rinse_vendor
    )
    keep_ids = resolve_protected_presence_run_ids(
        cursor,
        organization_id,
        portal_status=portal_status,
        selected_date_et=selected_date_et,
    )
    for row in runs[: max(1, int(keep_latest))]:
        rid = int(row.get("id") or 0)
        if rid:
            keep_ids.add(rid)

    all_ids = [int(r.get("id") or 0) for r in runs if int(r.get("id") or 0)]
    prune_ids = [rid for rid in all_ids if rid not in keep_ids]
    deleted_rows = 0
    deleted_runs = 0
    for rid in prune_ids:
        cursor.execute(
            "DELETE FROM rinse_cleaner_ticket_presence_run_rows WHERE presence_run_id = %s",
            (rid,),
        )
        deleted_rows += int(cursor.rowcount or 0)
        cursor.execute(
            """
            SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence_run_rows
            WHERE presence_run_id = %s
            """,
            (rid,),
        )
        remaining = int((cursor.fetchone() or {}).get("c") or 0)
        if remaining == 0:
            cursor.execute(
                "DELETE FROM rinse_cleaner_ticket_presence_runs WHERE id = %s AND organization_id = %s",
                (rid, int(organization_id)),
            )
            deleted_runs += int(cursor.rowcount or 0)

    return {
        "portal_status": portal_status,
        "rinse_vendor": rinse_vendor,
        "runs_before": len(all_ids),
        "kept_run_ids": sorted(keep_ids),
        "pruned_run_ids": prune_ids,
        "deleted_run_rows": deleted_rows,
        "deleted_runs": deleted_runs,
        "protected_baseline_run_ids": sorted(
            keep_ids - set(all_ids[: max(1, int(keep_latest))])
        ),
    }
