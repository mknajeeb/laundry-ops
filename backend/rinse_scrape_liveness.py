"""Scraper liveness: supervisor heartbeat independent of worker blocking."""

from __future__ import annotations

import os
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from backend.db import _connection_kwargs

_liveness_columns_verified = False
_liveness_columns_lock = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _direct_mysql_connection():
    import mysql.connector

    conn = mysql.connector.connect(**_connection_kwargs())
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SET SESSION innodb_lock_wait_timeout = 2")
        cur.close()
    except Exception:
        pass
    return conn


def _ensure_liveness_columns_on_connection(cur) -> None:
    """One-time column ensure per process — avoids per-tick schema checks."""
    global _liveness_columns_verified
    with _liveness_columns_lock:
        if _liveness_columns_verified:
            return
        from backend.ta_helpers import table_has_column

        if not table_has_column(cur, "rinse_scrape_org_lease", "supervisor_heartbeat_at"):
            cur.execute(
                """
                ALTER TABLE rinse_scrape_org_lease
                ADD COLUMN supervisor_heartbeat_at DATETIME(6) NULL AFTER heartbeat_at,
                ADD COLUMN worker_progress_at DATETIME(6) NULL AFTER last_progress_at
                """
            )
        _liveness_columns_verified = True


def ensure_lease_liveness_columns(cursor) -> None:
    from backend.rinse_scrape_lease import ensure_rinse_scrape_org_lease_table
    from backend.ta_helpers import table_has_column

    ensure_rinse_scrape_org_lease_table(cursor)
    if not table_has_column(cursor, "rinse_scrape_org_lease", "supervisor_heartbeat_at"):
        cursor.execute(
            """
            ALTER TABLE rinse_scrape_org_lease
            ADD COLUMN supervisor_heartbeat_at DATETIME(6) NULL AFTER heartbeat_at,
            ADD COLUMN worker_progress_at DATETIME(6) NULL AFTER last_progress_at
            """
        )


def touch_supervisor_heartbeat(
    organization_id: int,
    generation: int,
    *,
    stage: str | None = None,
    worker_progress: bool = False,
) -> bool:
    """Independent-connection supervisor tick. Never uses the app connection pool."""
    org = int(organization_id)
    gen = int(generation)
    now = _utcnow()
    stage_s = str(stage or "")[:64] if stage else None
    conn = None
    try:
        conn = _direct_mysql_connection()
        cur = conn.cursor()
        try:
            _ensure_liveness_columns_on_connection(cur)
        except Exception:
            pass
        if worker_progress and stage_s:
            cur.execute(
                """
                UPDATE rinse_scrape_org_lease
                SET supervisor_heartbeat_at = %s,
                    heartbeat_at = %s,
                    worker_progress_at = %s,
                    last_progress_at = %s,
                    current_stage = %s,
                    updated_at = %s
                WHERE organization_id = %s AND generation = %s AND fenced_at IS NULL
                """,
                (now, now, now, now, stage_s, now, org, gen),
            )
        elif stage_s:
            cur.execute(
                """
                UPDATE rinse_scrape_org_lease
                SET supervisor_heartbeat_at = %s,
                    heartbeat_at = %s,
                    current_stage = %s,
                    updated_at = %s
                WHERE organization_id = %s AND generation = %s AND fenced_at IS NULL
                """,
                (now, now, stage_s, now, org, gen),
            )
        else:
            cur.execute(
                """
                UPDATE rinse_scrape_org_lease
                SET supervisor_heartbeat_at = %s,
                    heartbeat_at = %s,
                    updated_at = %s
                WHERE organization_id = %s AND generation = %s AND fenced_at IS NULL
                """,
                (now, now, now, org, gen),
            )
        ok = int(cur.rowcount or 0) > 0
        cur.close()
        return ok
    except Exception as exc:
        print(
            f"SUPERVISOR_HB_FAIL org={org} gen={gen} stage={stage_s}: {exc}",
            flush=True,
        )
        traceback.print_exc()
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def scrape_supervisor_heartbeat_interval_sec() -> int:
    try:
        return max(15, int(os.getenv("RINSE_SCRAPE_SUPERVISOR_HEARTBEAT_SEC", "30")))
    except (TypeError, ValueError):
        return 30


@contextmanager
def scrape_supervisor_heartbeat(
    organization_id: int,
    lease_generation: int | None,
    *,
    stage: str,
    run_id: int | None = None,
    progress: bool = False,
) -> Iterator[None]:
    """Supervisor liveness thread — direct MySQL, not the shared pool."""
    if lease_generation is None:
        yield
        return

    stop = threading.Event()
    interval = scrape_supervisor_heartbeat_interval_sec()
    org = int(organization_id)
    gen = int(lease_generation)
    stage_s = str(stage or "unknown")[:64]
    rid = int(run_id) if run_id is not None else None

    def _loop() -> None:
        touch_supervisor_heartbeat(org, gen, stage=stage_s, worker_progress=progress)
        while not stop.wait(interval):
            touch_supervisor_heartbeat(org, gen, stage=stage_s, worker_progress=False)

    thread = threading.Thread(
        target=_loop,
        daemon=True,
        name=f"scrape-supervisor-hb-{rid or org}-{stage_s}",
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def read_lease_liveness(cursor, organization_id: int) -> dict[str, Any] | None:
    from backend.rinse_scrape_lease import ensure_rinse_scrape_org_lease_table

    ensure_lease_liveness_columns(cursor)
    ensure_rinse_scrape_org_lease_table(cursor)
    cursor.execute(
        """
        SELECT organization_id, generation, owner_run_id, owner_execution_name,
               owner_pid, heartbeat_at, supervisor_heartbeat_at,
               last_progress_at, worker_progress_at, current_stage,
               fenced_at, fence_reason, updated_at
        FROM rinse_scrape_org_lease
        WHERE organization_id = %s
        LIMIT 1
        """,
        (int(organization_id),),
    )
    lease = cursor.fetchone()
    if not isinstance(lease, dict):
        return None
    sup = lease.get("supervisor_heartbeat_at") or lease.get("heartbeat_at")
    worker = lease.get("worker_progress_at") or lease.get("last_progress_at")
    lease["supervisor_heartbeat_at"] = sup
    lease["worker_progress_at"] = worker
    return lease


def orphan_stall_seconds() -> int:
    try:
        return max(300, int(os.getenv("RINSE_SCRAPE_ORPHAN_STALL_SEC", "1200")))
    except (TypeError, ValueError):
        return 1200


def _seconds_stale(ts: datetime | None, now: datetime) -> float | None:
    if not isinstance(ts, datetime):
        return None
    t = ts.replace(tzinfo=None) if ts.tzinfo else ts
    return (now - t).total_seconds()


def _aca_execution_running(execution_name: str | None) -> bool:
    name = (execution_name or "").strip()
    if not name:
        return False
    try:
        from backend.rinse_aca_job_trigger import list_running_job_executions

        running = list_running_job_executions()
        return name in {str(x) for x in running}
    except Exception as exc:
        print(f"liveness: ACA list failed: {exc}", flush=True)
        return False


def orphan_reclaim_diagnostics(
    cursor,
    organization_id: int,
    lease: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Shared liveness signals for orphan reclaim decisions."""
    from backend.rinse_scrape_runs import mysql_lock_is_held

    org = int(organization_id)
    now_utc = now or _utcnow()
    sup_stale = _seconds_stale(lease.get("supervisor_heartbeat_at"), now_utc)
    worker_stale = _seconds_stale(lease.get("worker_progress_at"), now_utc)
    if sup_stale is None:
        sup_stale = _seconds_stale(lease.get("heartbeat_at"), now_utc)
    if worker_stale is None:
        worker_stale = _seconds_stale(lease.get("last_progress_at"), now_utc)
    lock_held, _ = mysql_lock_is_held(cursor, org)
    exec_running = _aca_execution_running(lease.get("owner_execution_name"))
    return {
        "supervisor_age_sec": sup_stale,
        "worker_age_sec": worker_stale,
        "exec_running": exec_running,
        "lock_held": lock_held,
        "execution": lease.get("owner_execution_name"),
    }


def orphan_reclaim_allowed(
    cursor,
    organization_id: int,
    lease: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[bool, str | None, dict[str, Any]]:
    """Canonical reclaim predicate — supervisor stale AND ACA dead AND lock free."""
    stall = orphan_stall_seconds()
    diag = orphan_reclaim_diagnostics(cursor, organization_id, lease, now=now)
    sup_stale = diag.get("supervisor_age_sec")
    if sup_stale is not None and sup_stale < stall:
        return False, "skip_fresh_supervisor", diag
    if diag.get("exec_running"):
        return False, "skip_live_aca_execution", diag
    if diag.get("lock_held"):
        return False, "skip_live_mysql_lock", diag
    return True, None, diag


def is_owned_execution_live(
    cursor,
    organization_id: int,
    *,
    now: datetime | None = None,
) -> bool:
    """True when ownership evidence indicates a healthy live run."""
    lease = read_lease_liveness(cursor, organization_id)
    if not lease or not lease.get("owner_run_id"):
        return False
    allowed, skip_reason, _ = orphan_reclaim_allowed(cursor, organization_id, lease, now=now)
    return not allowed and skip_reason in (
        "skip_fresh_supervisor",
        "skip_live_aca_execution",
        "skip_live_mysql_lock",
    )


def reclaim_orphan_owner(cursor, organization_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Fence + terminalize lease owner when canonical orphan reclaim is allowed."""
    from backend.rinse_scrape_lease import fence_lease
    from backend.rinse_scrape_runs import (
        _parse_result_json,
        ensure_rinse_scrape_runs_table,
        ensure_scrape_run_terminal,
        release_scrape_lock,
    )

    org = int(organization_id)
    now_utc = now or _utcnow()
    stall = orphan_stall_seconds()
    ensure_lease_liveness_columns(cursor)
    ensure_rinse_scrape_runs_table(cursor)
    lease = read_lease_liveness(cursor, org)
    if not lease:
        return {"action": "no_lease"}

    owner_run = lease.get("owner_run_id")
    if not owner_run:
        return {"action": "no_owner"}

    allowed, skip_reason, diag = orphan_reclaim_allowed(cursor, org, lease, now=now_utc)
    if not allowed:
        return {"action": skip_reason, **diag}

    cursor.execute(
        """
        SELECT id, status, started_at, result_json, lease_generation
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (org, int(owner_run)),
    )
    run = cursor.fetchone() or {}
    if str(run.get("status") or "") != "running":
        return {"action": "skip_not_running", "run_id": owner_run, **diag}

    gen = run.get("lease_generation")
    reason = f"FAILED_ORPHAN_RECLAIM stall>{stall}s"
    fence_lease(
        cursor,
        org,
        reason="FAILED_ORPHAN_RECLAIM",
        expected_generation=int(gen) if gen else None,
    )
    detail = _parse_result_json(run.get("result_json"))
    sync_cycle = dict(detail.get("sync_cycle") or {})
    sync_cycle.update(
        {
            "cycle_status": "FAILED_ORPHAN_RECLAIM",
            "failure_message": reason,
            "failed_step": "orphan_reclaim",
            "lock_was_free": not diag.get("lock_held"),
            "supervisor_age_sec": diag.get("supervisor_age_sec"),
            "worker_age_sec": diag.get("worker_age_sec"),
            "exec_running": diag.get("exec_running"),
        }
    )
    detail["sync_cycle"] = sync_cycle
    ensure_scrape_run_terminal(
        cursor,
        int(owner_run),
        org,
        status="failed",
        error_message=reason,
        result_json=detail,
    )
    try:
        release_scrape_lock(cursor, org)
    except Exception:
        pass
    return {
        "action": "reclaimed",
        "run_id": int(owner_run),
        "reason": reason,
        **diag,
    }
