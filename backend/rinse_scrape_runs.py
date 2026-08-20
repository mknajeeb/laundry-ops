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


def _drain_cursor(cursor) -> None:
    """Consume any unread result so the next execute cannot InternalError."""
    try:
        if getattr(cursor, "with_rows", False):
            cursor.fetchall()
    except Exception:
        pass
    try:
        # mysql-connector returns True/False. Bound so MagicMock cannot hang.
        for _ in range(32):
            more = cursor.nextset()
            if more is not True:
                break
            if getattr(cursor, "with_rows", False):
                cursor.fetchall()
    except Exception:
        pass


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
            lease_generation BIGINT NULL,
            INDEX idx_rsr_org_started (organization_id, started_at DESC),
            INDEX idx_rsr_org_status (organization_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _drain_cursor(cursor)
    from backend.ta_helpers import table_has_column

    try:
        if not table_has_column(cursor, "rinse_scrape_runs", "lease_generation"):
            cursor.execute(
                "ALTER TABLE rinse_scrape_runs ADD COLUMN lease_generation BIGINT NULL"
            )
            _drain_cursor(cursor)
    except Exception:
        _drain_cursor(cursor)


MYSQL_LOCK_HELD_REASON = "could not acquire MySQL lock"
DEAD_EXECUTION_MESSAGE = (
    "previous execution died before terminalizing (MySQL lock was free)"
)
POST_RUN_COOLDOWN_REASON = "post_run_cooldown"
# Sequential chain: next scheduled scrape starts immediately after the previous
# cycle terminals. A small failure backoff lives in rinse_scrape_chain.py.
DEFAULT_POST_RUN_COOLDOWN_MINUTES = 0
_TERMINAL_SCRAPE_STATUSES = frozenset(
    {
        "success",
        "failed",
        "partial_success",
        "needs_attention",
        "anomalous",
    }
)


def post_run_cooldown_minutes() -> int:
    try:
        return max(0, int(os.getenv("RINSE_SCRAPE_POST_RUN_COOLDOWN_MINUTES", str(DEFAULT_POST_RUN_COOLDOWN_MINUTES))))
    except (TypeError, ValueError):
        return DEFAULT_POST_RUN_COOLDOWN_MINUTES


def compute_next_run_at(finished_at: datetime | None, *, cooldown_minutes: int | None = None) -> datetime | None:
    """Next scheduled start = previous finished_at (immediate sequential chain)."""
    if finished_at is None:
        return None
    mins = post_run_cooldown_minutes() if cooldown_minutes is None else max(0, int(cooldown_minutes))
    fin = finished_at.replace(tzinfo=None) if finished_at.tzinfo else finished_at
    return fin + timedelta(minutes=mins)


def latest_terminal_scrape_finished_at(cursor, organization_id: int) -> datetime | None:
    """Most recent finished_at among terminal (non-skipped) scrape runs for the org."""
    ensure_rinse_scrape_runs_table(cursor)
    statuses = tuple(sorted(_TERMINAL_SCRAPE_STATUSES))
    placeholders = ", ".join(["%s"] * len(statuses))
    cursor.execute(
        f"""
        SELECT finished_at
        FROM rinse_scrape_runs
        WHERE organization_id = %s
          AND status IN ({placeholders})
          AND finished_at IS NOT NULL
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (int(organization_id), *statuses),
    )
    row = cursor.fetchone() or {}
    finished = row.get("finished_at") if isinstance(row, dict) else None
    if isinstance(finished, datetime):
        return finished.replace(tzinfo=None) if finished.tzinfo else finished
    return None


def scheduled_post_run_cooldown(
    cursor,
    organization_id: int,
    *,
    now: datetime | None = None,
    run_type: str = "scheduled",
) -> dict[str, Any]:
    """Sequential chain: scheduled runs are eligible immediately after terminal finish.

    Overlap is prevented by GET_LOCK + lease fencing, not by a wait interval.
    """
    last_finished = latest_terminal_scrape_finished_at(cursor, organization_id)
    next_run = compute_next_run_at(last_finished)
    return {
        "ok_to_run": True,
        "reason": None,
        "last_finished_at": last_finished,
        "next_run_at": next_run,
        "remaining_seconds": 0,
        "bypassed": str(run_type or "scheduled").strip().lower() != "scheduled",
        "sequential_immediate": True,
    }


def _mysql_lock_name(organization_id: int) -> str:
    return f"rinse_scrape_org_{int(organization_id)}"


def mysql_lock_is_held(cursor, organization_id: int) -> tuple[bool, str | None]:
    """True when GET_LOCK for this org is held by a live MySQL session."""
    cursor.execute(
        "SELECT IS_USED_LOCK(%s) AS used",
        (_mysql_lock_name(int(organization_id)),),
    )
    row = cursor.fetchone() or {}
    used = row.get("used") if isinstance(row, dict) else (row[0] if row else None)
    if used is None:
        return False, None
    return True, f"MySQL lock held (connection_id={used})"


def is_scrape_cycle_running(cursor, organization_id: int) -> tuple[bool, str | None]:
    """True only when a live session owns the org scrape lock.

    A leftover ``status='running'`` row is not evidence of a live process.
    """
    ensure_rinse_scrape_runs_table(cursor)
    return mysql_lock_is_held(cursor, organization_id)


def _parse_result_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _terminalize_orphaned_running_row(
    cursor,
    organization_id: int,
    row: dict[str, Any],
    *,
    now: datetime,
    stale_cutoff: datetime,
) -> int | None:
    """Mark a leftover running row failed. Caller already owns GET_LOCK."""
    run_id = int(row.get("id") or 0)
    if not run_id:
        return None
    started = row.get("started_at")
    timed_out = isinstance(started, datetime) and started < stale_cutoff
    if timed_out:
        failed_step = (
            _infer_failed_step_from_presence_runs(cursor, organization_id, started)
            if isinstance(started, datetime)
            else "unknown"
        )
        failure_message = f"Combined sync cycle timed out after {_stale_minutes()} minutes"
        cycle_status = "FAILED_TIMEOUT"
    else:
        failed_step = "died_before_terminal"
        failure_message = DEAD_EXECUTION_MESSAGE
        cycle_status = "FAILED_DEAD"
    detail = _parse_result_json(row.get("result_json"))
    sync_cycle = dict(detail.get("sync_cycle") or {})
    sync_cycle.update(
        {
            "sync_cycle_id": run_id,
            "cycle_status": cycle_status,
            "failure_message": failure_message,
            "failed_step": failed_step,
            "lock_was_free": True,
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
        WHERE id = %s AND organization_id = %s AND status = 'running'
        """,
        (
            now,
            failure_message,
            json.dumps(detail, default=str),
            run_id,
            int(organization_id),
        ),
    )
    return run_id


def acquire_scrape_lock(cursor, organization_id: int) -> tuple[bool, str]:
    """Acquire the org scrape lock. GET_LOCK is the authority for live execution.

    If GET_LOCK fails, another process is alive — do not overlap.

    If GET_LOCK succeeds, leftover ``status='running'`` rows are dead executions
    (the previous session released the lock). Terminalize them here as part of
    taking ownership so they cannot block the next natural cron.
    """
    ensure_rinse_scrape_runs_table(cursor)
    org = int(organization_id)
    now = _utcnow()
    stale_cutoff = now - timedelta(minutes=_stale_minutes())

    cursor.execute("SELECT GET_LOCK(%s, 0) AS got", (_mysql_lock_name(org),))
    row = cursor.fetchone() or {}
    got = row.get("got") if isinstance(row, dict) else row[0]
    if int(got or 0) != 1:
        return False, MYSQL_LOCK_HELD_REASON

    cursor.execute(
        """
        SELECT id, started_at, result_json
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND status = 'running'
        ORDER BY started_at ASC
        """,
        (org,),
    )
    leftover_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    leftover_ids: list[int] = []
    for leftover in leftover_rows:
        rid = _terminalize_orphaned_running_row(
            cursor,
            org,
            leftover,
            now=now,
            stale_cutoff=stale_cutoff,
        )
        if rid:
            leftover_ids.append(rid)

    if leftover_ids:
        try:
            from backend.rinse_step1_evidence_gate import (
                terminalize_import_running_gates_for_scrape_runs,
            )

            terminalize_import_running_gates_for_scrape_runs(
                cursor,
                organization_id=org,
                scrape_run_ids=leftover_ids,
                error=DEAD_EXECUTION_MESSAGE,
            )
        except Exception:
            pass
        # Import may have confirmed while Stage-B never started. Heal Today
        # from the complete gate before this cycle continues under the lock.
        try:
            conn = getattr(cursor, "connection", None)
            if conn is not None:
                from backend.rinse_step1_scrape_refresh import (
                    ensure_today_snapshot_if_missing,
                )

                ensure_today_snapshot_if_missing(
                    conn,
                    cursor,
                    org,
                    scrape_run_id=leftover_ids[-1],
                )
                try:
                    conn.commit()
                except Exception:
                    pass
        except Exception:
            pass

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


def bind_run_lease(cursor, run_id: int, organization_id: int, generation: int) -> None:
    ensure_rinse_scrape_runs_table(cursor)
    cursor.execute(
        """
        UPDATE rinse_scrape_runs
        SET lease_generation = %s
        WHERE id = %s AND organization_id = %s
        """,
        (int(generation), int(run_id), int(organization_id)),
    )


def _run_lease_generation(cursor, run_id: int, organization_id: int) -> int | None:
    ensure_rinse_scrape_runs_table(cursor)
    cursor.execute(
        """
        SELECT lease_generation FROM rinse_scrape_runs
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(run_id), int(organization_id)),
    )
    row = cursor.fetchone() or {}
    gen = row.get("lease_generation") if isinstance(row, dict) else None
    return int(gen) if gen is not None else None


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
    from backend.rinse_scrape_lease import FencedWriterError, assert_lease_writable, release_lease_if_owner

    gen = _run_lease_generation(cursor, int(run_id), int(organization_id))
    if gen is not None:
        assert_lease_writable(cursor, int(organization_id), gen)
    finished = _utcnow()
    duration = max(0, int((finished - started_at).total_seconds()))
    payload = dict(result_json) if isinstance(result_json, dict) else {}
    payload["next_run_at"] = finished.isoformat() + "Z"
    payload["post_run_cooldown_minutes"] = 0
    payload["schedule_mode"] = "sequential_immediate"
    payload["lease_generation"] = gen
    payload["started_at"] = (
        started_at.replace(tzinfo=None).isoformat() + "Z"
        if isinstance(started_at, datetime)
        else None
    )
    payload["finished_at"] = finished.isoformat() + "Z"
    payload["duration_seconds"] = duration
    payload["outcome"] = status[:24]
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
          AND (lease_generation IS NULL OR lease_generation = %s)
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
            json.dumps(payload, default=str),
            int(run_id),
            int(organization_id),
            gen,
        ),
    )
    if int(getattr(cursor, "rowcount", 0) or 0) < 1:
        raise FencedWriterError(
            f"finish_scrape_run rejected for run {run_id} generation {gen}"
        )
    if gen is not None:
        print(
            f"CHAIN_BOUNDARY lease_generation_release_start "
            f"utc={finished.isoformat()}Z run_id={run_id} gen={gen}",
            flush=True,
        )
        release_lease_if_owner(cursor, int(organization_id), int(gen))
        print(
            f"CHAIN_BOUNDARY lease_generation_release_complete "
            f"utc={_utcnow().isoformat()}Z run_id={run_id} gen={gen}",
            flush=True,
        )


def ensure_scrape_run_terminal(
    cursor,
    run_id: int,
    organization_id: int,
    *,
    status: str,
    error_message: str | None = None,
    result_json: dict[str, Any] | None = None,
) -> bool:
    """Force a still-running row to a terminal status. No-op if already terminal.

    Used from ``finally`` so a failed ``finish_scrape_run`` cannot leave the
    cycle running after the lock is released.
    """
    ensure_rinse_scrape_runs_table(cursor)
    finished = _utcnow()
    cursor.execute(
        """
        UPDATE rinse_scrape_runs
        SET status = %s,
            finished_at = COALESCE(finished_at, %s),
            error_message = COALESCE(%s, error_message),
            result_json = COALESCE(%s, result_json)
        WHERE id = %s AND organization_id = %s AND status = 'running'
        """,
        (
            (status or "failed")[:24],
            finished,
            (error_message or "")[:65000] or None,
            json.dumps(result_json, default=str) if result_json is not None else None,
            int(run_id),
            int(organization_id),
        ),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def scrape_run_heartbeat_interval_sec() -> int:
    try:
        return max(15, int(os.getenv("RINSE_SCRAPE_HEARTBEAT_SEC", "60")))
    except (TypeError, ValueError):
        return 60


def touch_scrape_run_progress(
    cursor,
    run_id: int,
    organization_id: int,
    *,
    stage: str,
    detail_patch: dict[str, Any] | None = None,
    progress: bool = True,
    lease_generation: int | None = None,
) -> None:
    """Bump heartbeat + current stage on a running scrape (result_json only)."""
    from backend.rinse_scrape_lease import touch_lease_heartbeat

    ensure_rinse_scrape_runs_table(cursor)
    now = _utcnow()
    cursor.execute(
        """
        SELECT status, result_json, lease_generation
        FROM rinse_scrape_runs
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(run_id), int(organization_id)),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict) or str(row.get("status") or "") != "running":
        return
    gen = lease_generation if lease_generation is not None else row.get("lease_generation")
    if gen is not None:
        if not touch_lease_heartbeat(
            cursor,
            int(organization_id),
            int(gen),
            stage=stage,
            progress=progress,
        ):
            return
    detail = _parse_result_json(row.get("result_json"))
    progress_block = dict(detail.get("progress") or {})
    progress_block.update(
        {
            "current_stage": str(stage or "unknown")[:128],
            "last_heartbeat_at": now.isoformat() + "Z",
            "execution_name": progress_block.get("execution_name")
            or os.getenv("CONTAINER_APP_JOB_EXECUTION_NAME"),
            "pid": os.getpid(),
        }
    )
    if progress:
        progress_block["last_progress_at"] = now.isoformat() + "Z"
    detail["progress"] = progress_block
    if isinstance(detail_patch, dict):
        detail.update(detail_patch)
    cursor.execute(
        """
        UPDATE rinse_scrape_runs
        SET result_json = %s
        WHERE id = %s AND organization_id = %s AND status = 'running'
          AND (lease_generation IS NULL OR lease_generation = %s)
        """,
        (
            json.dumps(detail, default=str),
            int(run_id),
            int(organization_id),
            gen,
        ),
    )


def infer_running_scrape_stage(
    cursor,
    organization_id: int,
    *,
    run_id: int | None = None,
    started_at: datetime | None = None,
    result_json: Any = None,
) -> str:
    """Best-effort live stage label for admin status (running rows only)."""
    detail = _parse_result_json(result_json)
    progress = detail.get("progress") if isinstance(detail.get("progress"), dict) else {}
    stage = progress.get("current_stage")
    if stage:
        return str(stage)
    if detail.get("step1_day_refresh"):
        return "stage_b_refresh"
    life = detail.get("ingestion_lifecycle") if isinstance(detail.get("ingestion_lifecycle"), dict) else {}
    if life.get("batch_confirmed_et"):
        return "post_confirm"
    if life.get("batch_id") or detail.get("draft") or detail.get("confirm"):
        return "import_or_confirm"
    if started_at is not None:
        try:
            cursor.execute(
                """
                SELECT portal_status, status, finished_at
                FROM rinse_cleaner_ticket_presence_runs
                WHERE organization_id = %s AND dry_run = 0 AND started_at >= %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (int(organization_id), started_at),
            )
            pr = cursor.fetchone()
            if isinstance(pr, dict):
                ps = str(pr.get("portal_status") or "")
                st = str(pr.get("status") or "")
                if ps == "at_vendor" and st == "running":
                    return "at_vendor_presence_scrape"
                if ps == "at_vendor" and st in ("success", "partial") and pr.get("finished_at"):
                    return "portal_scan_or_import"
        except Exception:
            pass
    return "playwright_scan"


def merge_scrape_run_result_json(
    cursor,
    run_id: int,
    organization_id: int,
    patch: dict[str, Any],
) -> None:
    """Merge keys into a finished scrape's result_json without changing status.

    Used for post-lock best-effort targeted refresh metadata. Never reopens a
    terminal scrape as ``running``.
    """
    ensure_rinse_scrape_runs_table(cursor)
    cursor.execute(
        """
        SELECT status, result_json
        FROM rinse_scrape_runs
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(run_id), int(organization_id)),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict):
        return
    status = str(row.get("status") or "")
    if status == "running":
        # Refuse to annotate an active main cycle — caller must finish first.
        return
    detail: dict[str, Any] = {}
    raw = row.get("result_json")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                detail = parsed
        except json.JSONDecodeError:
            detail = {}
    elif isinstance(raw, dict):
        detail = dict(raw)
    detail.update(patch)
    cursor.execute(
        """
        UPDATE rinse_scrape_runs
        SET result_json = %s
        WHERE id = %s AND organization_id = %s
          AND status <> 'running'
        """,
        (json.dumps(detail, default=str), int(run_id), int(organization_id)),
    )
