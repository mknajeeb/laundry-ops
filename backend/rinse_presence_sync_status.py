"""Sync status helpers for Ready for Vendor presence scrapes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_READY, ensure_presence_tables
from backend.rinse_scan_time import serialize_system_datetime_for_api, system_datetime_to_et, naive_system_utc
from backend.rinse_presence_scrape import ready_for_vendor_scrape_enabled
from backend.ta_helpers import table_exists

RINSE_SYNC_STALE_MINUTES = 120


def _duration_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    sec = int(seconds)
    if sec < 60:
        return f"{sec}s"
    return f"{max(1, round(sec / 60))} min"


def _fmt_system(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return serialize_system_datetime_for_api(dt)


def _short_time_et(dt: datetime | None) -> str | None:
    if not isinstance(dt, datetime):
        return None
    local = system_datetime_to_et(dt)
    if local is None:
        return None
    label = local.strftime("%b %d, %I:%M %p")
    if label.startswith("0"):
        label = label[1:]
    return label.replace(" 0", " ", 1)


def build_presence_run_list_item(run: dict[str, Any]) -> dict[str, Any]:
    started = run.get("started_at") or run.get("created_at")
    finished = run.get("finished_at") or run.get("created_at")
    duration = run.get("duration_seconds")
    if duration is None and isinstance(started, datetime) and isinstance(finished, datetime):
        s = naive_system_utc(started)
        f = naive_system_utc(finished)
        if s is not None and f is not None:
            duration = int((f - s).total_seconds())
    scrape_meta = run.get("scrape_meta_json")
    if isinstance(scrape_meta, str):
        try:
            scrape_meta = json.loads(scrape_meta)
        except json.JSONDecodeError:
            scrape_meta = {}
    if not isinstance(scrape_meta, dict):
        scrape_meta = {}
    return {
        "run_id": run.get("id"),
        "portal_status": run.get("portal_status"),
        "status": run.get("status") or ("success" if not run.get("errors_json") else "failed"),
        "run_type": run.get("run_type"),
        "started_at": _fmt_system(started if isinstance(started, datetime) else None),
        "finished_at": _fmt_system(finished if isinstance(finished, datetime) else None),
        "duration_seconds": duration,
        "duration_label": _duration_label(duration),
        "rows_found": run.get("rows_found"),
        "rows_inserted": run.get("rows_inserted"),
        "rows_updated": run.get("rows_updated"),
        "rows_unchanged": run.get("rows_unchanged"),
        "rows_missing": run.get("rows_missing"),
        "pages_visited": run.get("pages_visited") or scrape_meta.get("pages_scraped"),
        "rows_per_page": scrape_meta.get("rows_per_page"),
        "stopped_reason": scrape_meta.get("stopped_reason"),
        "error_message": run.get("errors_json"),
        "source_url": run.get("source_url"),
    }


def _latest_presence_run(cursor, organization_id: int, portal_status: str) -> dict[str, Any] | None:
    ensure_presence_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND portal_status = %s AND dry_run = 0
        ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (int(organization_id), portal_status),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def _latest_success_presence_run(cursor, organization_id: int, portal_status: str) -> dict[str, Any] | None:
    ensure_presence_tables(cursor)
    cursor.execute(
        """
        SELECT *
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s AND portal_status = %s AND dry_run = 0
          AND status IN ('success', 'partial')
        ORDER BY COALESCE(finished_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (int(organization_id), portal_status),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def build_sync_status_from_run(
    run: dict[str, Any] | None,
    *,
    sync_name: str,
    enabled: bool = True,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "message": f"{sync_name}: disabled",
            "stale": False,
            "stale_reason": None,
            "last_refreshed_at": None,
            "last_refreshed_at_et": None,
            "sync_time_unavailable": True,
            "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        }
    if not run:
        return {
            "enabled": True,
            "status": "never_run",
            "message": f"{sync_name}: never run",
            "stale": True,
            "stale_reason": f"{sync_name} stale",
            "last_refreshed_at": None,
            "last_refreshed_at_et": None,
            "sync_time_unavailable": True,
            "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        }

    item = build_presence_run_list_item(run)
    finished_raw = run.get("finished_at") or run.get("created_at")
    last_fmt = _fmt_system(finished_raw if isinstance(finished_raw, datetime) else None)
    last_et = _short_time_et(finished_raw if isinstance(finished_raw, datetime) else None)
    now = naive_system_utc(evaluation_time) or datetime.now(timezone.utc).replace(tzinfo=None)
    age_min = None
    stale = False
    if isinstance(finished_raw, datetime):
        ref = naive_system_utc(finished_raw)
        if ref is not None:
            age_min = max(0, int((now - ref).total_seconds()) // 60)
            stale = age_min > RINSE_SYNC_STALE_MINUTES
    run_status = str(run.get("status") or item.get("status") or "unknown")
    failed = run_status == "failed"
    return {
        "enabled": True,
        "status": run_status,
        "failed": failed,
        "message": f"{sync_name}: {last_et or last_fmt or '—'}",
        "stale": stale or failed,
        "stale_reason": (
            f"{sync_name} failed"
            if failed
            else (f"{sync_name} stale" if stale else None)
        ),
        "last_refreshed_at": last_fmt,
        "last_refreshed_at_et": last_et,
        "last_started_at": item.get("started_at"),
        "last_finished_at": item.get("finished_at"),
        "duration_seconds": item.get("duration_seconds"),
        "duration_label": item.get("duration_label"),
        "rows_found": item.get("rows_found"),
        "rows_inserted": item.get("rows_inserted"),
        "rows_updated": item.get("rows_updated"),
        "rows_unchanged": item.get("rows_unchanged"),
        "pages_visited": item.get("pages_visited"),
        "sync_time_unavailable": not last_fmt,
        "age_minutes": age_min,
        "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        "run": item,
    }


def _count_active_presence_rows(cursor, organization_id: int, portal_status: str) -> int:
    ensure_presence_tables(cursor)
    cursor.execute(
        """
        SELECT COUNT(*) AS active_rows
        FROM rinse_cleaner_ticket_presence
        WHERE organization_id=%s AND portal_status=%s AND active=1
        """,
        (int(organization_id), portal_status),
    )
    row = cursor.fetchone()
    if isinstance(row, dict):
        return int(row.get("active_rows") or 0)
    if row:
        return int(row[0] or 0)
    return 0


def get_ready_for_vendor_sync_status(
    cursor,
    organization_id: int,
    *,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    enabled = ready_for_vendor_scrape_enabled(cursor, org)
    latest = _latest_presence_run(cursor, org, PORTAL_STATUS_READY) if enabled else None
    last_success = _latest_success_presence_run(cursor, org, PORTAL_STATUS_READY) if enabled else None
    active_rows = _count_active_presence_rows(cursor, org, PORTAL_STATUS_READY) if enabled else 0

    sync = build_sync_status_from_run(
        last_success or latest,
        sync_name="Ready for Vendor Sync",
        enabled=enabled,
        evaluation_time=evaluation_time,
    )
    latest_item = build_presence_run_list_item(latest) if latest else None
    success_item = build_presence_run_list_item(last_success) if last_success else None
    latest_status = str((latest or {}).get("status") or (latest_item or {}).get("status") or "")
    skipped_reason = None
    error_message = None
    if not enabled:
        skipped_reason = "enable_ready_for_vendor_scrape=false"
    elif latest_status == "disabled":
        skipped_reason = "enable_ready_for_vendor_scrape=false"
    elif latest_status == "failed":
        error_message = str((latest or {}).get("errors_json") or (latest_item or {}).get("error_message") or "")
        sync["latest_failed"] = True
        sync["message"] = f"Ready for Vendor Sync failed: {error_message or 'unknown error'}"
    elif latest_status == "success" and int((latest_item or {}).get("rows_found") or 0) == 0:
        sync["zero_rows_success"] = True
        sync["message"] = "Ready for Vendor Sync returned 0 rows successfully"

    rows_found = None
    if latest_item and latest_item.get("rows_found") is not None:
        rows_found = int(latest_item.get("rows_found") or 0)
    elif success_item and success_item.get("rows_found") is not None:
        rows_found = int(success_item.get("rows_found") or 0)

    return {
        **sync,
        "latest_run": latest_item,
        "last_success": success_item,
        "last_success_at": success_item.get("finished_at") if success_item else None,
        "last_success_at_et": _short_time_et(
            (last_success or {}).get("finished_at")
            if isinstance((last_success or {}).get("finished_at"), datetime)
            else None
        ),
        "latest_status": latest_status or sync.get("status"),
        "rows_found": rows_found,
        "active_rows": active_rows,
        "skipped_reason": skipped_reason,
        "error": error_message,
        "enabled": enabled,
    }


def list_presence_runs_for_et_range(
    cursor,
    organization_id: int,
    *,
    from_date,
    to_date,
    portal_status: str = PORTAL_STATUS_READY,
) -> list[dict[str, Any]]:
    from datetime import date

    from backend.rinse_upload_batch_retention import et_date_range_to_utc_bounds

    ensure_presence_tables(cursor)
    if not isinstance(from_date, date) or not isinstance(to_date, date):
        raise ValueError("from_date and to_date required")
    start_utc, end_utc = et_date_range_to_utc_bounds(from_date, to_date)
    cursor.execute(
        """
        SELECT *
        FROM rinse_cleaner_ticket_presence_runs
        WHERE organization_id = %s
          AND portal_status = %s
          AND COALESCE(started_at, created_at) >= %s
          AND COALESCE(started_at, created_at) <= %s
        ORDER BY COALESCE(started_at, created_at) DESC
        """,
        (int(organization_id), portal_status, start_utc, end_utc),
    )
    return [build_presence_run_list_item(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def build_at_vendor_sync_status(cursor, organization_id: int, *, evaluation_time: datetime | None = None) -> dict[str, Any]:
    from backend.rinse_scrape_status import build_scrape_run_batch_detail

    org = int(organization_id)
    if not table_exists(cursor, "rinse_scrape_runs"):
        return build_sync_status_from_run(None, sync_name="At Vendor Sync", enabled=True)

    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (org,),
    )
    latest = cursor.fetchone()
    if not latest or not isinstance(latest, dict):
        return build_sync_status_from_run(None, sync_name="At Vendor Sync", enabled=True)

    detail = build_scrape_run_batch_detail(latest, None) or {}
    finished_raw = latest.get("finished_at")
    started_raw = latest.get("started_at")
    last_fmt = detail.get("data_last_updated_at") or detail.get("scrape_finished_at")
    last_et = _short_time_et(finished_raw if isinstance(finished_raw, datetime) else None)
    now = naive_system_utc(evaluation_time) or datetime.now(timezone.utc).replace(tzinfo=None)
    age_min = None
    stale = False
    ref_dt = naive_system_utc(finished_raw if isinstance(finished_raw, datetime) else None)
    if ref_dt is not None:
        age_min = max(0, int((now - ref_dt).total_seconds()) // 60)
        stale = age_min > RINSE_SYNC_STALE_MINUTES
    run_status = str(latest.get("status") or "unknown")
    failed = run_status == "failed"
    return {
        "enabled": True,
        "status": run_status,
        "failed": failed,
        "message": f"At Vendor Sync: {last_et or last_fmt or '—'}",
        "stale": stale or failed,
        "stale_reason": (
            "At Vendor Sync failed"
            if failed
            else ("At Vendor Sync stale" if stale else None)
        ),
        "last_refreshed_at": last_fmt,
        "last_refreshed_at_et": last_et,
        "last_started_at": detail.get("scrape_started_at"),
        "last_finished_at": detail.get("scrape_finished_at"),
        "duration_seconds": detail.get("scrape_duration_seconds"),
        "duration_label": detail.get("scrape_duration_label"),
        "rows_found": detail.get("portal_rows_count"),
        "rows_imported": detail.get("rows_imported"),
        "scan_events_count": detail.get("scan_events_count"),
        "sync_time_unavailable": not last_fmt,
        "age_minutes": age_min,
        "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        "run": detail,
        "started_at_raw": started_raw,
        "finished_at_raw": finished_raw,
    }
