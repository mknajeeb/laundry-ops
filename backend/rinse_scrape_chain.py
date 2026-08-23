"""Continuous Rinse sync chain: sequential loop, watchdog, zombie recovery, successor start."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.rinse_scrape_lease import (
    current_execution_name,
    read_lease,
)
from backend.rinse_scrape_runs import (
    _parse_result_json,
    mysql_lock_is_held,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def failure_backoff_seconds() -> int:
    """Small pause only after a failed cycle so a crash loop cannot hot-spin.

    Successful runs start the next cycle immediately (0). Default 15s after failure.
    """
    try:
        return max(0, int(os.getenv("RINSE_SCRAPE_FAILURE_BACKOFF_SEC", "15")))
    except (TypeError, ValueError):
        return 15


def hard_runtime_ceiling_seconds() -> int:
    """Whole-cycle ceiling from production history (7d max 58.5m, p99 49m).

    Playwright subprocess timeout stays 1800s. This ceiling is the full
    scrape+import+Stage-B envelope, not a shortened portal timeout.
    """
    try:
        return max(1800, int(os.getenv("RINSE_SCRAPE_HARD_CEILING_SEC", "4200")))
    except (TypeError, ValueError):
        return 4200


def stall_seconds() -> int:
    try:
        return max(60, int(os.getenv("RINSE_SCRAPE_STALL_SECONDS", "480")))
    except (TypeError, ValueError):
        return 480


def expected_cycle_seconds() -> int:
    """p95 production duration (~37m) used for freshness warning tolerance."""
    try:
        return max(600, int(os.getenv("RINSE_SCRAPE_EXPECTED_CYCLE_SEC", "2200")))
    except (TypeError, ValueError):
        return 2200


def replica_handoff_seconds() -> int:
    try:
        return max(60, int(os.getenv("RINSE_SCRAPE_REPLICA_HANDOFF_SEC", "180")))
    except (TypeError, ValueError):
        return 180


def replica_timeout_seconds() -> int:
    try:
        return max(600, int(os.getenv("RINSE_SCRAPE_REPLICA_TIMEOUT_SEC", "7200")))
    except (TypeError, ValueError):
        return 7200


def _progress_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")[:26]).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None
    return None


def classify_running_row(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    lease: dict[str, Any] | None = None,
) -> str:
    """healthy | stalled | over_ceiling."""
    now_utc = now or _utcnow()
    started = row.get("started_at")
    if isinstance(started, datetime):
        started = started.replace(tzinfo=None) if started.tzinfo else started
        if (now_utc - started).total_seconds() > hard_runtime_ceiling_seconds():
            return "over_ceiling"
    detail = _parse_result_json(row.get("result_json"))
    progress = detail.get("progress") if isinstance(detail.get("progress"), dict) else {}
    last_progress = _progress_datetime(progress.get("last_progress_at")) or _progress_datetime(
        progress.get("last_heartbeat_at")
    )
    if lease:
        last_progress = (
            _progress_datetime(lease.get("last_progress_at"))
            or _progress_datetime(lease.get("heartbeat_at"))
            or last_progress
        )
    if last_progress is None and isinstance(started, datetime):
        last_progress = started
    if last_progress is None:
        return "stalled"
    if (now_utc - last_progress).total_seconds() >= stall_seconds():
        return "stalled"
    return "healthy"


def recover_stalled_running_rows(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Orphan reclaim via shared multi-signal policy (not worker-progress stall)."""
    from backend.rinse_scrape_liveness import reclaim_orphan_owner

    result = reclaim_orphan_owner(cursor, int(organization_id))
    if result.get("action") != "reclaimed":
        return []
    run_id = int(result.get("run_id") or 0)
    try:
        from backend.rinse_aca_job_trigger import stop_foreign_running_executions

        stop_foreign_running_executions(
            keep_execution_name=current_execution_name(),
        )
    except Exception:
        pass
    return [
        {
            "run_id": run_id,
            "action": "FAILED_ORPHAN_RECLAIM",
            "reason": result.get("reason"),
        }
    ]


def recover_zombie_aca_executions(cursor, organization_id: int) -> list[dict[str, Any]]:
    """DB terminal + ACA still Running → cancel foreign executions."""
    from backend.rinse_scrape_runs import ensure_rinse_scrape_runs_table

    ensure_rinse_scrape_runs_table(cursor)
    org = int(organization_id)
    cursor.execute(
        """
        SELECT id, status
        FROM rinse_scrape_runs
        WHERE organization_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (org,),
    )
    latest = cursor.fetchone() or {}
    status = str((latest or {}).get("status") or "")
    lock_held, _ = mysql_lock_is_held(cursor, org)
    if status == "running" or lock_held:
        return []
    keep = current_execution_name()
    if not keep:
        return [{"skipped": "no_execution_name"}]
    try:
        from backend.rinse_aca_job_trigger import stop_foreign_running_executions

        stopped = stop_foreign_running_executions(
            keep_execution_name=keep,
        )
    except Exception as exc:
        return [{"error": str(exc)}]
    return [{"zombie_stopped": stopped, "db_status": status}]


def start_successor_execution(*, run_type: str = "scheduled") -> dict[str, Any]:
    from backend.rinse_aca_job_trigger import start_rinse_scrape_chain_job

    print(
        f"CHAIN_BOUNDARY successor_request_start utc={_utcnow().isoformat()}Z",
        flush=True,
    )
    result = start_rinse_scrape_chain_job(run_type=run_type)
    out = {
        "ok": bool(result.ok),
        "execution_name": result.execution_name,
        "error_message": result.error_message,
    }
    print(
        f"CHAIN_BOUNDARY successor_request_complete utc={_utcnow().isoformat()}Z "
        f"ok={out['ok']} execution={out.get('execution_name')}",
        flush=True,
    )
    return out


def maybe_restart_dead_chain(cursor, organization_id: int) -> dict[str, Any]:
    """API-side dead-man: start the chain only if nothing healthy is running."""
    org = int(organization_id)
    lock_held, _ = mysql_lock_is_held(cursor, org)
    lease = read_lease(cursor, org)
    now = _utcnow()
    if lock_held:
        from backend.rinse_scrape_liveness import is_owned_execution_live

        if is_owned_execution_live(cursor, org, now=now):
            return {"restarted": False, "reason": "healthy_lock_held"}
    hb = lease.get("heartbeat_at") if lease else None
    if isinstance(hb, datetime):
        hb = hb.replace(tzinfo=None) if hb.tzinfo else hb
        if (now - hb).total_seconds() < 90:
            return {"restarted": False, "reason": "recent_heartbeat"}
    started = start_successor_execution(run_type="scheduled")
    return {"restarted": bool(started.get("ok")), **started}


def run_continuous_scheduled_loop(
    conn,
    *,
    organization_ids: list[int] | None = None,
    run_type: str = "scheduled",
    dry_run: bool = False,
    max_cycles: int | None = None,
    force_fail: bool = False,
    force_stall: bool = False,
    loop_started_at: datetime | None = None,
) -> list[Any]:
    """Run scrape cycles back-to-back until replica handoff or max_cycles."""
    from backend.rinse_scheduled_scrape import (
        parse_scheduled_org_ids,
        run_all_scheduled_scrapes,
        scheduled_scrape_enabled,
    )

    if not scheduled_scrape_enabled() and not dry_run:
        raise RuntimeError("RINSE_SCHEDULED_SCRAPE_ENABLED is not set")

    orgs = organization_ids if organization_ids is not None else parse_scheduled_org_ids()
    started = loop_started_at or _utcnow()
    budget = replica_timeout_seconds() - replica_handoff_seconds()
    all_results: list[Any] = []
    cycle = 0
    raw_max = max_cycles
    if raw_max is None:
        try:
            env_max = os.getenv("RINSE_SCRAPE_MAX_CYCLES")
            raw_max = int(env_max) if env_max and str(env_max).strip() else None
        except (TypeError, ValueError):
            raw_max = None

    while True:
        cycle += 1
        elapsed = (_utcnow() - started).total_seconds()
        if elapsed >= budget:
            print(
                f"rinse chain handoff: replica budget {int(elapsed)}s >= {budget}s",
                flush=True,
            )
            break
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            for oid in orgs:
                try:
                    actions = recover_stalled_running_rows(cursor, int(oid))
                    if actions:
                        print(f"rinse watchdog org={oid} {actions}", flush=True)
                        conn.commit()
                    zombies = recover_zombie_aca_executions(cursor, int(oid))
                    if zombies:
                        print(f"rinse zombie recovery org={oid} {zombies}", flush=True)
                        conn.commit()
                except Exception as recover_exc:
                    print(f"rinse watchdog/zombie error org={oid}: {recover_exc}", flush=True)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        finally:
            try:
                cursor.close()
            except Exception:
                pass

        print(f"rinse continuous cycle {cycle} start", flush=True)
        os.environ["RINSE_SCRAPE_FORCE_FAIL"] = "1" if (force_fail and cycle == 1) else "0"
        os.environ["RINSE_SCRAPE_FORCE_STALL"] = "1" if (force_stall and cycle == 1) else "0"
        cycle_wall_start = _utcnow()
        try:
            results = run_all_scheduled_scrapes(
                conn,
                organization_ids=orgs,
                run_type=run_type,
                dry_run=dry_run,
            )
        except Exception as cycle_exc:
            print(f"rinse continuous cycle {cycle} crashed: {cycle_exc}", flush=True)
            results = []
            failed = True
            all_results.extend(results)
            wait = failure_backoff_seconds()
            if wait:
                print(f"rinse failure backoff {wait}s then next cycle", flush=True)
                time.sleep(wait)
            if raw_max is not None and cycle >= int(raw_max):
                print(f"rinse continuous loop stop after max_cycles={raw_max}", flush=True)
                break
            continue
        all_results.extend(results)
        finished_ats = [
            getattr(r, "finished_at", None)
            for r in results
            if getattr(r, "finished_at", None) is not None
        ]
        if finished_ats:
            last_fin = max(
                (f.replace(tzinfo=None) if getattr(f, "tzinfo", None) else f)
                for f in finished_ats
            )
            gap = (_utcnow() - last_fin).total_seconds()
            print(
                f"CHAIN_BOUNDARY next_cycle_eligible gap_from_last_finish_sec={gap:.3f} "
                f"cycle={cycle}",
                flush=True,
            )
        if results and all(
            str(getattr(r, "status", "") or "") == "skipped"
            and "ALREADY_RUNNING" in str(getattr(r, "error_message", "") or "")
            for r in results
        ):
            print("rinse continuous loop: another replica holds the chain; exit", flush=True)
            break
        failed = any(str(getattr(r, "status", "") or "") == "failed" for r in results)
        if raw_max is not None and cycle >= int(raw_max):
            print(f"rinse continuous loop stop after max_cycles={raw_max}", flush=True)
            break
        if failed:
            wait = failure_backoff_seconds()
            if wait:
                print(f"rinse failure backoff {wait}s then next cycle", flush=True)
                time.sleep(wait)
        # Success: next cycle immediately (no post-run wait).
        print(
            f"CHAIN_BOUNDARY next_cycle_launch cycle={cycle + 1} "
            f"after_cycle_elapsed_sec={(_utcnow() - cycle_wall_start).total_seconds():.3f}",
            flush=True,
        )
    os.environ.pop("RINSE_SCRAPE_FORCE_FAIL", None)
    os.environ.pop("RINSE_SCRAPE_FORCE_STALL", None)
    return all_results
