"""
Rinse scrape orphan watchdog — multi-signal reclaim only.

Reclaim requires stale supervisor heartbeat AND no live ownership evidence
(ACA execution not Running, MySQL lock not held).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _reexec_with_project_venv() -> None:
    repo = Path(__file__).resolve().parents[2]
    venv_python = repo / ".venv" / "bin" / "python"
    if venv_python.is_file() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), "-m", "backend.jobs.run_rinse_freshness_watchdog", *sys.argv[1:]])


_reexec_with_project_venv()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def orphan_stall_seconds() -> int:
    try:
        return max(300, int(os.getenv("RINSE_SCRAPE_ORPHAN_STALL_SEC", "1200")))
    except (TypeError, ValueError):
        return 1200


def _aca_execution_running(execution_name: str | None) -> bool:
    name = (execution_name or "").strip()
    if not name:
        return False
    try:
        from backend.rinse_aca_job_trigger import list_running_job_executions

        running = list_running_job_executions()
        return name in {str(x) for x in running}
    except Exception as exc:
        print(f"watchdog: ACA list failed: {exc}", flush=True)
        return False


def _seconds_stale(ts: datetime | None, now: datetime) -> float | None:
    if not isinstance(ts, datetime):
        return None
    t = ts.replace(tzinfo=None) if ts.tzinfo else ts
    return (now - t).total_seconds()


def run_watchdog(cursor, organization_id: int) -> dict:
    from backend.rinse_scrape_lease import fence_lease, read_lease
    from backend.rinse_scrape_liveness import ensure_lease_liveness_columns, read_lease_liveness
    from backend.rinse_scrape_runs import (
        ensure_scrape_run_terminal,
        mysql_lock_is_held,
        release_scrape_lock,
        _parse_result_json,
    )

    org = int(organization_id)
    now = _utcnow()
    stall = orphan_stall_seconds()
    ensure_lease_liveness_columns(cursor)
    lease = read_lease_liveness(cursor, org)
    if not lease:
        return {"action": "no_lease"}

    owner_run = lease.get("owner_run_id")
    if not owner_run:
        return {"action": "no_owner"}

    sup_stale = _seconds_stale(lease.get("supervisor_heartbeat_at"), now)
    worker_stale = _seconds_stale(lease.get("worker_progress_at"), now)
    if sup_stale is None:
        sup_stale = _seconds_stale(lease.get("heartbeat_at"), now)
    if worker_stale is None:
        worker_stale = _seconds_stale(lease.get("last_progress_at"), now)

    lock_held, _ = mysql_lock_is_held(cursor, org)
    exec_running = _aca_execution_running(lease.get("owner_execution_name"))

  # Fresh supervisor — never reclaim
    if sup_stale is not None and sup_stale < stall:
        return {
            "action": "skip_fresh_supervisor",
            "supervisor_age_sec": sup_stale,
            "exec_running": exec_running,
            "lock_held": lock_held,
        }

    if exec_running:
        return {
            "action": "skip_live_aca_execution",
            "execution": lease.get("owner_execution_name"),
            "supervisor_age_sec": sup_stale,
        }

    if lock_held:
        return {
            "action": "skip_live_mysql_lock",
            "supervisor_age_sec": sup_stale,
        }

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
        return {"action": "skip_not_running", "run_id": owner_run}

    gen = run.get("lease_generation")
    reason = f"FAILED_ORPHAN_RECLAIM stall>{stall}s"
    fence_lease(cursor, org, reason="FAILED_ORPHAN_RECLAIM", expected_generation=int(gen) if gen else None)
    detail = _parse_result_json(run.get("result_json"))
    sync_cycle = dict(detail.get("sync_cycle") or {})
    sync_cycle.update(
        {
            "cycle_status": "FAILED_ORPHAN_RECLAIM",
            "failure_message": reason,
            "failed_step": "orphan_reclaim",
            "lock_was_free": not lock_held,
            "supervisor_age_sec": sup_stale,
            "worker_age_sec": worker_stale,
            "exec_running": exec_running,
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
        "supervisor_age_sec": sup_stale,
        "worker_age_sec": worker_stale,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rinse scrape orphan watchdog")
    p.add_argument("--organization-id", type=int, action="append", dest="organization_ids")
    args = p.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids

    orgs = args.organization_ids or parse_scheduled_org_ids()
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        for oid in orgs:
            out = run_watchdog(cursor, int(oid))
            print(f"watchdog org={oid} {out}", flush=True)
            conn.commit()
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
