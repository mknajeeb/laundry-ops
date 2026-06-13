"""MySQL-backed Rinse scheduled scrape run history and overlap locks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stale_minutes() -> int:
    try:
        return max(30, int(os.getenv("RINSE_SCRAPE_STALE_MINUTES", "120")))
    except (TypeError, ValueError):
        return 120


def _infer_failed_step_from_presence_runs(cursor, organization_id: int, started_at: datetime) -> str:
    """Best-effort phase label when a combined sync cycle times out."""
    try:
        cursor.execute(
            """
            SELECT portal_status, status, started_at, finished_at
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id = %s AND dry_run = 0 AND started_at >= %s
            ORDER BY started_at ASC
            """,
            (int(organization_id), started_at),
        )
        rows = cursor.fetchall() or []
    except Exception:
        return "unknown"
    rfv_done = False
    av_started = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        ps = str(row.get("portal_status") or "")
        st = str(row.get("status") or "")
        if ps == "ready_for_vendor" and st in ("success", "partial", "dry_run"):
            rfv_done = True
        if ps == "at_vendor":
            av_started = True
            if st == "running" or (row.get("finished_at") is None and st not in ("success", "failed")):
                return "at_vendor_presence_scrape"
    if rfv_done and not av_started:
        return "at_vendor_presence_start"
    if not rfv_done:
        return "rfv_presence_scrape"
    return "at_vendor_csv_import"


def ensure_rinse_scrape_runs_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_scrape_runs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            tenant_slug VARCHAR(64) NULL,
            rinse_vendor VARCHAR(16) NULL,
            run_type VARCHAR(16) NOT NULL DEFAULT 'scheduled',
            status VARCHAR(24) NOT NULL DEFAULT 'running',
            started_at DATETIME(6) NOT NULL,
            finished_at DATETIME(6) NULL,
            duration_seconds INT NULL,
            portal_csv_path VARCHAR(1024) NULL,
            scan_events_csv_path VARCHAR(1024) NULL,
            scan_events_events_path VARCHAR(1024) NULL,
            portal_rows_count INT NULL,
            scan_events_count INT NULL,
            imported_batch_id INT NULL,
            error_message TEXT NULL,
            log_path VARCHAR(1024) NULL,
            result_json LONGTEXT NULL,
            INDEX idx_rsr_org_started (organization_id, started_at DESC),
            INDEX idx_rsr_org_status (organization_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _mysql_lock_name(organization_id: int) -> str:
    return f"rinse_scrape_org_{int(organization_id)}"


def acquire_scrape_lock(cursor, organization_id: int) -> tuple[bool, str]:
    """
    Returns (acquired, reason).
    Uses GET_LOCK + clears stale `running` rows older than RINSE_SCRAPE_STALE_MINUTES.
    """
    ensure_rinse_scrape_runs_table(cursor)
    org = int(organization_id)
    stale_cutoff = _utcnow() - timedelta(minutes=_stale_minutes())

    cursor.execute(
        """
        SELECT id, started_at, result_json
        FROM rinse_scrape_runs
        WHERE organization_id = %s
          AND status = 'running'
          AND started_at < %s
        ORDER BY started_at ASC
        """,
        (org, stale_cutoff),
    )
    stale_rows = cursor.fetchall() or []
    for stale in stale_rows:
        if not isinstance(stale, dict):
            continue
        run_id = int(stale.get("id") or 0)
        started = stale.get("started_at")
        failed_step = (
            _infer_failed_step_from_presence_runs(cursor, org, started)
            if isinstance(started, datetime)
            else "unknown"
        )
        failure_message = f"Combined sync cycle timed out after {_stale_minutes()} minutes"
        detail: dict[str, Any] = {}
        raw_detail = stale.get("result_json")
        if isinstance(raw_detail, str):
            try:
                detail = json.loads(raw_detail)
            except json.JSONDecodeError:
                detail = {}
        elif isinstance(raw_detail, dict):
            detail = dict(raw_detail)
        sync_cycle = dict(detail.get("sync_cycle") or {})
        sync_cycle.update(
            {
                "sync_cycle_id": run_id,
                "cycle_status": "FAILED_TIMEOUT",
                "failure_message": failure_message,
                "failed_step": failed_step,
            }
        )
        detail["sync_cycle"] = sync_cycle
        cursor.execute(
            """
            UPDATE rinse_scrape_runs
            SET status = 'failed',
                finished_at = %s,
                error_message = %s,
                result_json = %s
            WHERE id = %s AND organization_id = %s
            """,
            (
                _utcnow(),
                failure_message,
                json.dumps(detail, default=str),
                run_id,
                org,
            ),
        )

    cursor.execute(
        """
        SELECT id FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'running'
        LIMIT 1
        """,
        (org,),
    )
    if cursor.fetchone():
        return False, "previous run still active"

    cursor.execute("SELECT GET_LOCK(%s, 0) AS got", (_mysql_lock_name(org),))
    row = cursor.fetchone() or {}
    got = row.get("got") if isinstance(row, dict) else row[0]
    if int(got or 0) != 1:
        return False, "could not acquire MySQL lock"

    return True, ""


def release_scrape_lock(cursor, organization_id: int) -> None:
    cursor.execute("SELECT RELEASE_LOCK(%s) AS released", (_mysql_lock_name(int(organization_id)),))
    cursor.fetchone()


def insert_scrape_run(
    cursor,
    organization_id: int,
    *,
    tenant_slug: str | None,
    rinse_vendor: str | None,
    run_type: str,
    log_path: str | None,
) -> int:
    ensure_rinse_scrape_runs_table(cursor)
    started = _utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_scrape_runs
        (organization_id, tenant_slug, rinse_vendor, run_type, status, started_at, log_path)
        VALUES (%s, %s, %s, %s, 'running', %s, %s)
        """,
        (
            int(organization_id),
            (tenant_slug or "")[:64] or None,
            (rinse_vendor or "")[:16] or None,
            (run_type or "scheduled")[:16],
            started,
            (log_path or "")[:1024] or None,
        ),
    )
    return int(cursor.lastrowid)


def insert_skipped_scrape_run(
    cursor,
    organization_id: int,
    *,
    tenant_slug: str | None,
    rinse_vendor: str | None,
    run_type: str,
    reason: str,
) -> int:
    ensure_rinse_scrape_runs_table(cursor)
    started = finished = _utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_scrape_runs
        (organization_id, tenant_slug, rinse_vendor, run_type, status,
         started_at, finished_at, duration_seconds, error_message)
        VALUES (%s, %s, %s, %s, 'skipped', %s, %s, 0, %s)
        """,
        (
            int(organization_id),
            (tenant_slug or "")[:64] or None,
            (rinse_vendor or "")[:16] or None,
            (run_type or "scheduled")[:16],
            started,
            finished,
            reason[:4000],
        ),
    )
    return int(cursor.lastrowid)


def finish_scrape_run(
    cursor,
    run_id: int,
    organization_id: int,
    *,
    status: str,
    started_at: datetime,
    portal_csv_path: str | None = None,
    scan_events_csv_path: str | None = None,
    scan_events_events_path: str | None = None,
    portal_rows_count: int | None = None,
    scan_events_count: int | None = None,
    imported_batch_id: int | None = None,
    error_message: str | None = None,
    log_path: str | None = None,
    result_json: dict[str, Any] | None = None,
) -> None:
    finished = _utcnow()
    duration = max(0, int((finished - started_at).total_seconds()))
    cursor.execute(
        """
        UPDATE rinse_scrape_runs
        SET status=%s,
            finished_at=%s,
            duration_seconds=%s,
            portal_csv_path=%s,
            scan_events_csv_path=%s,
            scan_events_events_path=%s,
            portal_rows_count=%s,
            scan_events_count=%s,
            imported_batch_id=%s,
            error_message=%s,
            log_path=COALESCE(%s, log_path),
            result_json=%s
        WHERE id=%s AND organization_id=%s
        """,
        (
            status[:24],
            finished,
            duration,
            (portal_csv_path or "")[:1024] or None,
            (scan_events_csv_path or "")[:1024] or None,
            (scan_events_events_path or "")[:1024] or None,
            portal_rows_count,
            scan_events_count,
            imported_batch_id,
            (error_message or "")[:65000] or None,
            (log_path or "")[:1024] or None,
            json.dumps(result_json, default=str) if result_json is not None else None,
            int(run_id),
            int(organization_id),
        ),
    )
