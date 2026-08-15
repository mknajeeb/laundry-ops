"""Admin status for scheduled Rinse scrape (per organization)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.ta_helpers import table_exists

ET = ZoneInfo("America/New_York")

# ACA job schedule in deploy docs (UTC cron)
DEFAULT_CRON_UTC = "*/30 * * * *"
DEFAULT_INTERVAL_MINUTES = 30


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt_system(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    from backend.rinse_scan_time import serialize_system_datetime_for_api

    if isinstance(dt, datetime):
        return serialize_system_datetime_for_api(dt)
    return str(dt)


def _short_time_et(dt: datetime | None) -> str | None:
    if not isinstance(dt, datetime):
        return None
    from backend.rinse_scan_time import system_datetime_to_et

    local = system_datetime_to_et(dt)
    if local is None:
        return None
    label = local.strftime("%I:%M %p")
    if label.startswith("0"):
        label = label[1:]
    return label


def _duration_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    sec = int(seconds)
    if sec < 60:
        return f"{sec}s"
    mins = max(1, round(sec / 60))
    return f"{mins} min"


def _build_timing_summary(
    *,
    scrape_started_at: datetime | None,
    data_last_updated_at: datetime | None,
    duration_seconds: int | None,
) -> str | None:
    parts: list[str] = []
    t0 = _short_time_et(scrape_started_at)
    if t0:
        parts.append(f"Scrape started {t0}")
    t1 = _short_time_et(data_last_updated_at)
    if t1:
        parts.append(f"Data updated {t1}")
    dur = _duration_label(duration_seconds)
    if dur:
        parts.append(f"Duration {dur}")
    return " • ".join(parts) if parts else None


def _fetch_upload_batch_row(cursor, organization_id: int, batch_id: int) -> dict[str, Any] | None:
    if not batch_id or not table_exists(cursor, "upload_batches"):
        return None
    org = int(organization_id)
    cols = ["batch_id", "state", "orders_loaded", "confirmed_at", "batch_date"]
    from backend.ta_helpers import table_has_column

    if table_has_column(cursor, "upload_batches", "id"):
        pk = "id"
    else:
        pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "created_at"):
        cols.append("created_at")
    elif table_has_column(cursor, "upload_batches", "uploaded_at"):
        cols.append("uploaded_at AS created_at")
    if table_has_column(cursor, "upload_batches", "raw_rows_purged_at"):
        cols.append("raw_rows_purged_at")
    if table_has_column(cursor, "upload_batches", "purged_summary_json"):
        cols.append("purged_summary_json")
    where_org = ""
    args: list[Any] = [int(batch_id)]
    if table_has_column(cursor, "upload_batches", "organization_id"):
        where_org = " AND organization_id = %s"
        args.append(org)
    cursor.execute(
        f"""
        SELECT {pk} AS batch_id, {", ".join(c for c in cols if c != "batch_id")}
        FROM upload_batches
        WHERE {pk} = %s{where_org}
        LIMIT 1
        """,
        tuple(args),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def build_scrape_run_batch_detail(
    scrape_run: dict[str, Any] | None,
    batch_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge rinse_scrape_runs + upload_batches timing for admin UI."""
    if not scrape_run or not isinstance(scrape_run, dict):
        return None

    started = scrape_run.get("started_at")
    finished = scrape_run.get("finished_at")
    duration_seconds = scrape_run.get("duration_seconds")
    if duration_seconds is None and isinstance(started, datetime) and isinstance(
        finished, datetime
    ):
        duration_seconds = int((finished - started).total_seconds())

    batch_created = batch_row.get("created_at") if batch_row else None
    batch_confirmed = batch_row.get("confirmed_at") if batch_row else None
    data_raw = batch_confirmed if isinstance(batch_confirmed, datetime) else finished

    portal_rows = scrape_run.get("portal_rows_count")
    rows_imported = portal_rows
    if rows_imported is None and batch_row:
        rows_imported = batch_row.get("orders_loaded")

    return {
        "scrape_run_id": scrape_run.get("id"),
        "scrape_status": scrape_run.get("status"),
        "run_type": scrape_run.get("run_type"),
        "scrape_started_at": _fmt_system(started),
        "scrape_finished_at": _fmt_system(finished),
        "scrape_duration_seconds": duration_seconds,
        "scrape_duration_label": _duration_label(duration_seconds),
        "imported_batch_id": scrape_run.get("imported_batch_id"),
        "rows_imported": rows_imported,
        "portal_rows_count": portal_rows,
        "scan_events_count": scrape_run.get("scan_events_count"),
        "batch_created_at": _fmt_system(batch_created),
        "batch_confirmed_at": _fmt_system(batch_confirmed),
        "batch_state": batch_row.get("state") if batch_row else None,
        "data_last_updated_at": _fmt_system(data_raw),
        "data_last_updated_at_raw": data_raw,
        "timing_summary": _build_timing_summary(
            scrape_started_at=started if isinstance(started, datetime) else None,
            data_last_updated_at=data_raw if isinstance(data_raw, datetime) else None,
            duration_seconds=duration_seconds,
        ),
        "is_scheduled": str(scrape_run.get("run_type") or "").lower() in (
            "scheduled",
            "aca",
            "cron",
        )
        or bool(scrape_run.get("id")),
        "error_message": scrape_run.get("error_message"),
    }


def fetch_scrape_run_for_batch(
    cursor, organization_id: int, batch_id: int
) -> dict[str, Any] | None:
    """Latest rinse_scrape_runs row linked via imported_batch_id."""
    if not table_exists(cursor, "rinse_scrape_runs"):
        return None
    org = int(organization_id)
    bid = int(batch_id)
    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, run_type, tenant_slug
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND imported_batch_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (org, bid),
    )
    run = cursor.fetchone()
    if not run or not isinstance(run, dict):
        return None
    batch_row = _fetch_upload_batch_row(cursor, org, bid)
    return build_scrape_run_batch_detail(run, batch_row)


def attach_scrape_runs_to_batches(
    cursor, organization_id: int, batches: list[dict[str, Any]]
) -> None:
    """Annotate upload batch list rows with linked scrape timing (in-place)."""
    if not batches:
        return
    org = int(organization_id)
    for b in batches:
        if not isinstance(b, dict):
            continue
        created = b.get("created_at")
        confirmed = b.get("confirmed_at")
        b["batch_created_at"] = _fmt_system(created) if isinstance(created, datetime) else None
        b["batch_confirmed_at"] = _fmt_system(confirmed) if isinstance(confirmed, datetime) else None
        b["batch_time_label"] = "Batch created"
        b["scheduled_scrape"] = None

    if not table_exists(cursor, "rinse_scrape_runs"):
        return

    ids = [int(b["id"]) for b in batches if isinstance(b, dict) and b.get("id") is not None]
    if not ids:
        return

    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND imported_batch_id IN ({placeholders})
        ORDER BY started_at DESC
        """,
        (org, *ids),
    )
    runs = list(cursor.fetchall() or [])
    by_batch: dict[int, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        bid = run.get("imported_batch_id")
        if bid is None:
            continue
        bid_int = int(bid)
        if bid_int not in by_batch:
            by_batch[bid_int] = run

    for b in batches:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        if bid is None:
            continue
        run = by_batch.get(int(bid))
        if not run:
            continue
        detail = build_scrape_run_batch_detail(run, b)
        if detail:
            b["scheduled_scrape"] = detail
            b["batch_time_label"] = "Imported at"


def _next_run_estimate_utc(last_started: datetime | None) -> datetime | None:
    """Best-effort next run: last start + 30m (matches */30 cron), not exact ACA scheduler."""
    if last_started is None:
        return _utcnow_naive() + timedelta(minutes=DEFAULT_INTERVAL_MINUTES)
    return last_started + timedelta(minutes=DEFAULT_INTERVAL_MINUTES)


def _batch_row_counts(
    cursor, batch_id: int | None, batch_row: dict[str, Any] | None
) -> dict[str, int]:
    """Live row counts or purged snapshot from batch header."""
    import json

    if batch_row and batch_row.get("raw_rows_purged_at") and batch_row.get("purged_summary_json"):
        try:
            snap = json.loads(batch_row["purged_summary_json"])
            if isinstance(snap, dict):
                return {
                    "accepted_rows": int(snap.get("accepted_rows") or 0),
                    "rejected_rows": int(snap.get("rejected_rows") or 0),
                    "attention_rows": int(snap.get("attention_rows") or 0),
                    "total_rows": int(snap.get("total_rows") or 0),
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if not batch_id or not table_exists(cursor, "upload_batch_rows"):
        return {
            "accepted_rows": 0,
            "rejected_rows": 0,
            "attention_rows": 0,
            "total_rows": 0,
        }
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(row_status IN ('ACCEPTED', 'OVERRIDDEN')) AS accepted_rows,
            SUM(row_status = 'REJECTED_DUPLICATE') AS rejected_rows,
            SUM(row_status = 'NEEDS_ATTENTION') AS attention_rows
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        """,
        (int(batch_id),),
    )
    row = cursor.fetchone() or {}
    return {
        "accepted_rows": int(row.get("accepted_rows") or 0),
        "rejected_rows": int(row.get("rejected_rows") or 0),
        "attention_rows": int(row.get("attention_rows") or 0),
        "total_rows": int(row.get("total_rows") or 0),
    }


def build_scrape_run_list_item(
    cursor,
    organization_id: int,
    scrape_run: dict[str, Any],
    batch_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """One row for Today's Rinse Sync Runs table."""
    detail = build_scrape_run_batch_detail(scrape_run, batch_row) or {}
    bid = scrape_run.get("imported_batch_id")
    counts = _batch_row_counts(
        cursor, int(bid) if bid is not None else None, batch_row
    )
    from backend.rinse_scan_time import system_datetime_to_et

    started = scrape_run.get("started_at")
    started_et = system_datetime_to_et(started) if isinstance(started, datetime) else None
    return {
        **detail,
        "run_id": scrape_run.get("id"),
        "status": scrape_run.get("status"),
        "error_message": scrape_run.get("error_message"),
        "log_path": scrape_run.get("log_path"),
        "started_at_et_date": started_et.date().isoformat() if started_et else None,
        "accepted_rows": counts["accepted_rows"],
        "rejected_rows": counts["rejected_rows"],
        "needs_attention_rows": counts["attention_rows"],
        "job_finished_at": detail.get("scrape_finished_at"),
        "data_available_at": detail.get("batch_confirmed_at") or detail.get("data_last_updated_at"),
        "heavy_rows_purged": bool(batch_row.get("raw_rows_purged_at")) if batch_row else False,
    }


def list_scrape_runs_for_et_range(
    cursor,
    organization_id: int,
    *,
    from_date,
    to_date,
) -> list[dict[str, Any]]:
    """List scrape runs whose started_at falls on ET calendar dates [from_date, to_date]."""
    from datetime import date

    from backend.rinse_upload_batch_retention import et_date_range_to_utc_bounds

    if not table_exists(cursor, "rinse_scrape_runs"):
        return []
    org = int(organization_id)
    if not isinstance(from_date, date) or not isinstance(to_date, date):
        raise ValueError("from_date and to_date required")
    start_utc, end_utc = et_date_range_to_utc_bounds(from_date, to_date)
    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, rinse_vendor, tenant_slug, run_type, log_path
        FROM rinse_scrape_runs
        WHERE organization_id = %s
          AND started_at >= %s AND started_at <= %s
        ORDER BY started_at DESC
        """,
        (org, start_utc, end_utc),
    )
    out: list[dict[str, Any]] = []
    for run in cursor.fetchall() or []:
        if not isinstance(run, dict):
            continue
        bid = run.get("imported_batch_id")
        batch_row = (
            _fetch_upload_batch_row(cursor, org, int(bid)) if bid else None
        )
        item = build_scrape_run_list_item(cursor, org, run, batch_row)
        out.append(item)
    return out


def get_scheduled_scrape_status(cursor, organization_id: int) -> dict[str, Any]:
    """
    Latest rinse_scrape_runs row + linked upload_batches timing for admin UI.

    data_last_updated_at: batch confirmed_at when set, else scrape finished_at.
    """
    org = int(organization_id)
    out: dict[str, Any] = {
        "organization_id": org,
        "schedule_cron_utc": os.getenv("RINSE_SCHEDULE_CRON_UTC", DEFAULT_CRON_UTC),
        "schedule_interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "schedule_timezone_note": "Cron runs in UTC. Display times use America/New_York.",
        "latest_run": None,
        "last_success": None,
        "data_last_updated_at": None,
        "data_last_updated_at_et": None,
        "timing_summary": None,
        "next_run_estimate_utc": None,
        "next_run_estimate_et": None,
    }

    if not table_exists(cursor, "rinse_scrape_runs"):
        return out

    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id,
               error_message, rinse_vendor, tenant_slug, run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (org,),
    )
    latest = cursor.fetchone()
    if latest and isinstance(latest, dict):
        bid = latest.get("imported_batch_id")
        batch_row = (
            _fetch_upload_batch_row(cursor, org, int(bid)) if bid else None
        )
        detail = build_scrape_run_batch_detail(latest, batch_row)
        if detail:
            out["latest_run"] = {
                **detail,
                "error_message": latest.get("error_message"),
                "rinse_vendor": latest.get("rinse_vendor"),
                "tenant_slug": latest.get("tenant_slug"),
            }
        started = latest.get("started_at")
        if isinstance(started, datetime):
            nxt = _next_run_estimate_utc(started)
            out["next_run_estimate_utc"] = nxt.isoformat() + "Z" if nxt else None
            out["next_run_estimate_et"] = _fmt_system(nxt)

    cursor.execute(
        """
        SELECT id, status, started_at, finished_at, duration_seconds,
               portal_rows_count, scan_events_count, imported_batch_id, error_message,
               run_type
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'success'
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (org,),
    )
    success = cursor.fetchone()
    if success and isinstance(success, dict):
        batch_id = success.get("imported_batch_id")
        batch_row = (
            _fetch_upload_batch_row(cursor, org, int(batch_id)) if batch_id else None
        )
        detail = build_scrape_run_batch_detail(success, batch_row)
        if detail:
            out["last_success"] = detail
            data_raw = detail.get("data_last_updated_at_raw")
            out["data_last_updated_at"] = detail.get("data_last_updated_at")
            out["data_last_updated_at_et"] = detail.get("data_last_updated_at")
            out["timing_summary"] = detail.get("timing_summary")

    from backend.rinse_scrape_runs import mysql_lock_is_held

    lock_held, lock_hint = mysql_lock_is_held(cursor, org)
    out["currently_running"] = bool(lock_held)
    if lock_held:
        cursor.execute(
            """
            SELECT id, status, started_at FROM rinse_scrape_runs
            WHERE organization_id = %s AND status = 'running'
            ORDER BY started_at DESC LIMIT 1
            """,
            (org,),
        )
        running = cursor.fetchone()
        if running and isinstance(running, dict):
            out["running_run_id"] = running.get("id")
            out["running_started_at"] = _fmt_system(running.get("started_at"))
        elif lock_hint:
            out["running_hint"] = lock_hint

    from backend.rinse_presence_sync_status import (
        build_at_vendor_sync_status,
        get_ready_for_vendor_sync_status,
    )

    out["at_vendor_sync"] = build_at_vendor_sync_status(cursor, org)
    out["ready_for_vendor_sync"] = get_ready_for_vendor_sync_status(cursor, org)

    return out
