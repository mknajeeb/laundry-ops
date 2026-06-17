"""Sync status helpers for Ready for Vendor presence scrapes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

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
    label = local.strftime("%b %d, %I:%M %p ET")
    if label.startswith("0"):
        label = label[1:]
    return label.replace(" 0", " ", 1)


def _parse_scrape_meta(raw: Any) -> dict[str, Any]:
    scrape_meta = raw
    if isinstance(scrape_meta, str):
        try:
            scrape_meta = json.loads(scrape_meta)
        except json.JSONDecodeError:
            scrape_meta = {}
    return scrape_meta if isinstance(scrape_meta, dict) else {}


def _portal_pulled_at_from_scrape_meta(scrape_meta: Mapping[str, Any] | None) -> Any:
    if not scrape_meta:
        return None
    meta = dict(scrape_meta)
    pulled = meta.get("scraped_at")
    if pulled:
        return pulled
    summary = meta.get("vendor_home_summary")
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            summary = {}
    if isinstance(summary, dict) and summary.get("scraped_at"):
        return summary.get("scraped_at")
    return None


def build_sync_freshness_fields(
    *,
    started_at: str | None = None,
    portal_pulled_at: str | None = None,
    data_updated_at: str | None = None,
    duration_seconds: int | None = None,
    duration_label: str | None = None,
    rows_found: int | None = None,
    scan_events_count: int | None = None,
    imported_batch_id: int | None = None,
    started_at_et: str | None = None,
    portal_pulled_at_et: str | None = None,
    data_updated_at_et: str | None = None,
) -> dict[str, Any]:
    """Normalized scrape freshness block for dashboard sync cards."""
    portal_pull_unavailable = not portal_pulled_at
    return {
        "scrape_started_at": started_at,
        "scrape_started_at_et": started_at_et,
        "portal_pulled_at": portal_pulled_at,
        "portal_pulled_at_et": portal_pulled_at_et,
        "data_updated_at": data_updated_at,
        "data_updated_at_et": data_updated_at_et,
        "duration_seconds": duration_seconds,
        "duration_label": duration_label or _duration_label(duration_seconds),
        "rows_found": rows_found,
        "scan_events_count": scan_events_count,
        "imported_batch_id": imported_batch_id,
        "portal_pull_unavailable": portal_pull_unavailable,
        "portal_pull_note": (
            "Portal pull time unavailable"
            if portal_pull_unavailable
            else None
        ),
    }


def build_presence_run_list_item(run: dict[str, Any]) -> dict[str, Any]:
    started = run.get("started_at") or run.get("created_at")
    finished = run.get("finished_at") or run.get("created_at")
    duration = run.get("duration_seconds")
    if duration is None and isinstance(started, datetime) and isinstance(finished, datetime):
        s = naive_system_utc(started)
        f = naive_system_utc(finished)
        if s is not None and f is not None:
            duration = int((f - s).total_seconds())
    scrape_meta = _parse_scrape_meta(run.get("scrape_meta_json"))
    portal_pulled_raw = _portal_pulled_at_from_scrape_meta(scrape_meta)
    started_fmt = _fmt_system(started if isinstance(started, datetime) else None)
    finished_fmt = _fmt_system(finished if isinstance(finished, datetime) else None)
    portal_pulled_fmt = None
    portal_pulled_et = None
    if portal_pulled_raw:
        if isinstance(portal_pulled_raw, datetime):
            portal_pulled_fmt = _fmt_system(portal_pulled_raw)
            portal_pulled_et = _short_time_et(portal_pulled_raw)
        else:
            portal_pulled_fmt = str(portal_pulled_raw)
            try:
                portal_pulled_et = _short_time_et(
                    datetime.fromisoformat(str(portal_pulled_raw).replace("Z", "+00:00")[:26]).replace(
                        tzinfo=None
                    )
                )
            except (TypeError, ValueError):
                portal_pulled_et = None
    freshness = build_sync_freshness_fields(
        started_at=started_fmt,
        portal_pulled_at=portal_pulled_fmt or finished_fmt,
        data_updated_at=finished_fmt,
        duration_seconds=duration,
        duration_label=_duration_label(duration),
        rows_found=run.get("rows_found"),
        started_at_et=_short_time_et(started if isinstance(started, datetime) else None),
        portal_pulled_at_et=portal_pulled_et or _short_time_et(finished if isinstance(finished, datetime) else None),
        data_updated_at_et=_short_time_et(finished if isinstance(finished, datetime) else None),
    )
    if portal_pulled_fmt is None and finished_fmt:
        freshness["portal_pull_unavailable"] = True
        freshness["portal_pull_note"] = "Portal pull time unavailable"
    return {
        "run_id": run.get("id"),
        "portal_status": run.get("portal_status"),
        "status": run.get("status") or ("success" if not run.get("errors_json") else "failed"),
        "run_type": run.get("run_type"),
        "started_at": started_fmt,
        "finished_at": finished_fmt,
        "duration_seconds": duration,
        "duration_label": _duration_label(duration),
        "rows_found": run.get("rows_found"),
        "freshness": freshness,
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
          AND (
            status IN ('success', 'partial')
            OR (status IS NULL AND (errors_json IS NULL OR errors_json = '' OR errors_json = '[]'))
          )
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
        "freshness": item.get("freshness")
        or build_sync_freshness_fields(
            started_at=item.get("started_at"),
            portal_pulled_at=item.get("finished_at"),
            data_updated_at=item.get("finished_at") or last_fmt,
            duration_seconds=item.get("duration_seconds"),
            duration_label=item.get("duration_label"),
            rows_found=item.get("rows_found"),
            started_at_et=_short_time_et(run.get("started_at") if isinstance(run.get("started_at"), datetime) else None),
            portal_pulled_at_et=last_et,
            data_updated_at_et=last_et,
        ),
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

    # Staleness reflects the latest run attempt; last_success_at tracks last good scrape.
    sync = build_sync_status_from_run(
        latest or last_success,
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
        raw_err = (latest or {}).get("errors_json") or (latest_item or {}).get("error_message") or ""
        if isinstance(raw_err, str):
            try:
                parsed = json.loads(raw_err)
                if isinstance(parsed, list) and parsed:
                    error_message = "; ".join(str(x) for x in parsed)
                elif parsed:
                    error_message = str(parsed)
                else:
                    error_message = raw_err.strip() or None
            except json.JSONDecodeError:
                error_message = raw_err.strip() or None
        elif isinstance(raw_err, list) and raw_err:
            error_message = "; ".join(str(x) for x in raw_err)
        else:
            error_message = str(raw_err).strip() if raw_err else None
        sync["latest_failed"] = True
        sync["message"] = f"Ready for Vendor Sync failed: {error_message or 'unknown error'}"
    elif latest_status == "success" and int((latest_item or {}).get("rows_found") or 0) == 0:
        scrape_meta = (latest or {}).get("scrape_meta_json")
        if isinstance(scrape_meta, str):
            try:
                scrape_meta = json.loads(scrape_meta)
            except json.JSONDecodeError:
                scrape_meta = {}
        if not isinstance(scrape_meta, dict):
            scrape_meta = {}
        empty_validated = scrape_meta.get("empty_result_validated")
        if empty_validated is True:
            sync["zero_rows_success"] = True
            sync["empty_result_validated"] = True
            sync["message"] = "Ready for Vendor Sync returned 0 rows successfully"
            sync["stale"] = False
            sync["stale_reason"] = None
        else:
            sync["empty_result_validated"] = False
            sync["stale"] = True
            sync["stale_reason"] = "Ready for Vendor zero-row scrape not validated"
            sync["message"] = "Ready for Vendor Sync: zero rows not validated — prior population preserved"

    rows_found = None
    if latest_item and latest_item.get("rows_found") is not None:
        rows_found = int(latest_item.get("rows_found") or 0)
    elif success_item and success_item.get("rows_found") is not None:
        rows_found = int(success_item.get("rows_found") or 0)

    return {
        **sync,
        "latest_run": latest_item,
        "last_success": success_item,
        "latest_attempt_at": sync.get("last_refreshed_at") or (latest_item or {}).get("finished_at"),
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


def _portal_pulled_at_from_batch(cursor, organization_id: int, batch_id: int | None) -> str | None:
    if not batch_id or not table_exists(cursor, "upload_batches"):
        return None
    from backend.rinse_portal_scrape_meta import fetch_portal_scrape_meta_for_batch

    meta = fetch_portal_scrape_meta_for_batch(cursor, int(batch_id), int(organization_id))
    pulled = _portal_pulled_at_from_scrape_meta(meta or {})
    return str(pulled) if pulled else None


def build_at_vendor_sync_status(cursor, organization_id: int, *, evaluation_time: datetime | None = None) -> dict[str, Any]:
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR
    from backend.rinse_scrape_status import build_scrape_run_batch_detail, _fetch_upload_batch_row

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

    batch_row = _fetch_upload_batch_row(cursor, org, latest.get("imported_batch_id")) if latest.get("imported_batch_id") else None
    detail = build_scrape_run_batch_detail(latest, batch_row) or {}
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
    in_progress = run_status == "running"
    if in_progress and isinstance(started_raw, datetime):
        s = naive_system_utc(started_raw)
        if s is not None:
            running_min = max(0, int((now - s).total_seconds()) // 60)
            if running_min > RINSE_SYNC_STALE_MINUTES:
                in_progress = False
                failed = True
                run_status = "failed"
                stale = True
    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'success'
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (org,),
    )
    last_success = cursor.fetchone()
    success_batch = (
        _fetch_upload_batch_row(cursor, org, last_success.get("imported_batch_id"))
        if last_success and isinstance(last_success, dict) and last_success.get("imported_batch_id")
        else None
    )
    success_detail = (
        build_scrape_run_batch_detail(last_success, success_batch)
        if last_success and isinstance(last_success, dict)
        else None
    )
    latest_attempt_at = detail.get("scrape_finished_at") or _fmt_system(
        finished_raw if isinstance(finished_raw, datetime) else None
    )
    last_success_at = (
        (success_detail or {}).get("scrape_finished_at")
        or (success_detail or {}).get("data_last_updated_at")
    )
    portal_pulled_raw = _portal_pulled_at_from_batch(cursor, org, latest.get("imported_batch_id"))
    if not portal_pulled_raw:
        presence_run = _latest_success_presence_run(cursor, org, PORTAL_STATUS_AT_VENDOR)
        if presence_run:
            portal_pulled_raw = _portal_pulled_at_from_scrape_meta(
                _parse_scrape_meta(presence_run.get("scrape_meta_json"))
            )
    portal_pulled_fmt = None
    portal_pulled_et = None
    if portal_pulled_raw:
        if isinstance(portal_pulled_raw, datetime):
            portal_pulled_fmt = _fmt_system(portal_pulled_raw)
            portal_pulled_et = _short_time_et(portal_pulled_raw)
        else:
            portal_pulled_fmt = str(portal_pulled_raw)
            try:
                portal_pulled_et = _short_time_et(
                    datetime.fromisoformat(str(portal_pulled_raw).replace("Z", "+00:00")[:26]).replace(
                        tzinfo=None
                    )
                )
            except (TypeError, ValueError):
                portal_pulled_et = None
    started_fmt = detail.get("scrape_started_at")
    finished_fmt = detail.get("data_last_updated_at") or detail.get("scrape_finished_at")
    freshness = build_sync_freshness_fields(
        started_at=started_fmt,
        portal_pulled_at=portal_pulled_fmt or started_fmt or finished_fmt,
        data_updated_at=finished_fmt,
        duration_seconds=detail.get("scrape_duration_seconds"),
        duration_label=detail.get("scrape_duration_label"),
        rows_found=detail.get("portal_rows_count"),
        started_at_et=_short_time_et(started_raw if isinstance(started_raw, datetime) else None),
        portal_pulled_at_et=portal_pulled_et
        or _short_time_et(started_raw if isinstance(started_raw, datetime) else None),
        data_updated_at_et=last_et,
        scan_events_count=detail.get("scan_events_count"),
        imported_batch_id=latest.get("imported_batch_id"),
    )
    if not portal_pulled_fmt:
        freshness["portal_pull_unavailable"] = True
        freshness["portal_pull_note"] = "Portal pull time unavailable"
    return {
        "enabled": True,
        "status": run_status,
        "failed": failed,
        "in_progress": in_progress,
        "message": (
            f"At Vendor Sync: in progress ({last_et or 'started'})"
            if in_progress
            else f"At Vendor Sync: {last_et or last_fmt or '—'}"
        ),
        "stale": stale or failed,
        "stale_reason": (
            "At Vendor Sync failed"
            if failed
            else ("At Vendor Sync stale" if stale else None)
        ),
        "last_refreshed_at": last_fmt,
        "last_refreshed_at_et": last_et,
        "latest_attempt_at": latest_attempt_at,
        "last_success_at": last_success_at,
        "last_started_at": detail.get("scrape_started_at"),
        "last_finished_at": detail.get("scrape_finished_at"),
        "duration_seconds": detail.get("scrape_duration_seconds"),
        "duration_label": detail.get("scrape_duration_label"),
        "rows_found": detail.get("portal_rows_count"),
        "rows_imported": detail.get("rows_imported"),
        "scan_events_count": detail.get("scan_events_count"),
        "imported_batch_id": latest.get("imported_batch_id"),
        "pages_visited": detail.get("pages_visited"),
        "sync_time_unavailable": not last_fmt,
        "age_minutes": age_min,
        "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        "run": detail,
        "latest_run": detail,
        "last_success": success_detail,
        "freshness": freshness,
        "error_message": latest.get("error_message"),
        "started_at_raw": started_raw,
        "finished_at_raw": finished_raw,
    }


def evaluate_at_vendor_presence_freshness(
    cursor,
    organization_id: int,
    *,
    evaluation_time: datetime | None = None,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """
    Returns (is_fresh, stale_reason, latest_run).
    Fresh means a successful at_vendor presence scrape within RINSE_SYNC_STALE_MINUTES.
    """
    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR

    run = _latest_success_presence_run(cursor, int(organization_id), PORTAL_STATUS_AT_VENDOR)
    if not run:
        return False, "No successful At Vendor presence scrape available", None
    finished = run.get("finished_at") or run.get("started_at")
    ref = naive_system_utc(finished if isinstance(finished, datetime) else None)
    now = naive_system_utc(evaluation_time) or datetime.now(timezone.utc).replace(tzinfo=None)
    if ref is None:
        return False, "At Vendor presence scrape timestamp unavailable", run
    age_min = max(0, int((now - ref).total_seconds()) // 60)
    if age_min > RINSE_SYNC_STALE_MINUTES:
        return (
            False,
            f"At Vendor presence scrape stale — last success {age_min} min ago (>{RINSE_SYNC_STALE_MINUTES} min)",
            run,
        )
    return True, None, run


def build_rinse_sync_cycle_status(cursor, organization_id: int) -> dict[str, Any]:
    """Combined RFV → At Vendor sync cycle from latest scrape run metadata."""
    org = int(organization_id)
    cycle: dict[str, Any] = {
        "label": "Last Rinse Sync Cycle",
        "sync_cycle_id": None,
        "cycle_started_at": None,
        "cycle_status": None,
        "rfv_started_at": None,
        "rfv_completed_at": None,
        "rfv_completed_at_et": None,
        "rfv_run_id": None,
        "at_vendor_run_id": None,
        "at_vendor_started_at": None,
        "at_vendor_started_at_et": None,
        "at_vendor_completed_at": None,
        "at_vendor_completed_at_et": None,
        "delay_seconds": None,
        "at_vendor_ran": None,
        "at_vendor_skipped_reason": None,
        "rfv_status": None,
        "at_vendor_status": None,
        "failure_message": None,
    }
    if not table_exists(cursor, "rinse_scrape_runs"):
        return cycle
    cursor.execute(
        """
        SELECT status, started_at, finished_at, result_json
        FROM rinse_scrape_runs
        WHERE organization_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (org,),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return cycle
    detail = row.get("result_json")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            detail = {}
    if not isinstance(detail, dict):
        detail = {}
    sync_cycle = detail.get("sync_cycle") if isinstance(detail.get("sync_cycle"), dict) else {}
    rfv_sync = detail.get("ready_for_vendor_sync") if isinstance(detail.get("ready_for_vendor_sync"), dict) else {}
    for key in (
        "sync_cycle_id",
        "cycle_started_at",
        "cycle_status",
        "rfv_started_at",
        "rfv_completed_at",
        "rfv_run_id",
        "at_vendor_run_id",
        "at_vendor_started_at",
        "at_vendor_completed_at",
        "delay_seconds",
        "at_vendor_ran",
        "at_vendor_skipped_reason",
        "rfv_status",
        "at_vendor_status",
        "failure_message",
    ):
        if sync_cycle.get(key) is not None:
            cycle[key] = sync_cycle.get(key)
    cycle["cycle_status"] = sync_cycle.get("cycle_status") or row.get("status")
    cycle["rfv_status"] = sync_cycle.get("rfv_status") or rfv_sync.get("status")
    cycle["at_vendor_status"] = sync_cycle.get("at_vendor_status") or row.get("status")
    cycle["rfv_completed_at"] = sync_cycle.get("rfv_completed_at") or rfv_sync.get("finished_at")
    if cycle.get("at_vendor_started_at") is None:
        cycle["at_vendor_started_at"] = sync_cycle.get("at_vendor_started_at") or _fmt_system(row.get("started_at"))
    if cycle.get("at_vendor_completed_at") is None:
        cycle["at_vendor_completed_at"] = sync_cycle.get("at_vendor_completed_at") or _fmt_system(row.get("finished_at"))
    if isinstance(row.get("started_at"), datetime):
        cycle["at_vendor_started_at_et"] = _short_time_et(row.get("started_at"))
    if isinstance(row.get("finished_at"), datetime):
        cycle["at_vendor_completed_at_et"] = _short_time_et(row.get("finished_at"))
    if cycle.get("rfv_completed_at"):
        try:
            from datetime import datetime as _dt

            rfv_dt = _dt.fromisoformat(str(cycle["rfv_completed_at"]).replace("Z", "+00:00")[:26])
            cycle["rfv_completed_at_et"] = _short_time_et(rfv_dt.replace(tzinfo=None))
        except (TypeError, ValueError):
            pass

    from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_READY

    rfv_run = _latest_success_presence_run(cursor, org, PORTAL_STATUS_READY)
    av_presence_run = _latest_success_presence_run(cursor, org, PORTAL_STATUS_AT_VENDOR)
    if rfv_run:
        rfv_item = build_presence_run_list_item(rfv_run)
        cycle["rfv_freshness"] = rfv_item.get("freshness")
    if av_presence_run:
        av_item = build_presence_run_list_item(av_presence_run)
        cycle["at_vendor_presence_freshness"] = av_item.get("freshness")
    av_scrape = build_at_vendor_sync_status(cursor, org)
    if av_scrape.get("freshness"):
        cycle["at_vendor_scrape_freshness"] = av_scrape.get("freshness")
    targeted = detail.get("targeted_pending_scan_refresh") or detail.get("off_portal_scan_refresh")
    if isinstance(targeted, dict):
        cycle["targeted_pending_scan_refresh"] = targeted
        if isinstance(row.get("finished_at"), datetime):
            cycle["targeted_refresh_completed_at_et"] = _short_time_et(row.get("finished_at"))
    return cycle
