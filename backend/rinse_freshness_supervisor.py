"""Long-lived Rinse freshness supervisor.

The supervisor owns the loop. Children never start their replacement.
Hung children are killed/fenced; the supervisor continues.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def failure_backoff_seconds(consecutive_failures: int) -> int:
    base = int(os.getenv("RINSE_FRESHNESS_FAILURE_BACKOFF_SEC", "15") or 15)
    cap = int(os.getenv("RINSE_FRESHNESS_FAILURE_BACKOFF_CAP_SEC", "120") or 120)
    # 15, 30, 60, 120...
    delay = min(cap, base * (2 ** max(0, consecutive_failures - 1)))
    return max(10, int(delay))


def fast_child_ceiling_seconds() -> int:
    # Fast lane target is ≤10 min end-to-end; keep a modest buffer above cold
    # 2-page portal expand, but never the old 25-minute hang window.
    return int(os.getenv("RINSE_FRESHNESS_FAST_CEILING_SEC", "900") or 900)


def meaningful_stall_seconds() -> int:
    # No stdout / DB progress for this long ⇒ fence. Portal expands must keep
    # printing heartbeats (see _run_bash_script) so this does not false-fire.
    return int(os.getenv("RINSE_FRESHNESS_STALL_SEC", "180") or 180)  # 3 min


def rolling_every_n_fast() -> int:
    return int(os.getenv("RINSE_FRESHNESS_ROLLING_EVERY_N", "8") or 8)


def deep_every_n_fast() -> int:
    return int(os.getenv("RINSE_FRESHNESS_DEEP_EVERY_N", "48") or 48)


def _spawn_cycle(organization_id: int, lane: str) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "backend.jobs.run_rinse_freshness_cycle",
        "--organization-id",
        str(int(organization_id)),
        "--lane",
        str(lane),
    ]
    env = os.environ.copy()
    env["RINSE_FRESHNESS_CHILD"] = "1"
    env["RINSE_FRESHNESS_LANE"] = str(lane)
    # Children must never start successors.
    env["RINSE_FRESHNESS_DISABLE_SUCCESSOR"] = "1"
    env["RINSE_FRESHNESS_SKIP_GET_LOCK"] = "1"
    if lane == "fast":
        env["RINSE_FRESHNESS_DELTA_FINALIZE"] = "1"
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.kill(proc.pid, signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def run_supervisor(
    *,
    organization_id: int | None = None,
    max_cycles: int | None = None,
) -> int:
    """Run forever (or max_cycles). Exit code 0 unless fatal misconfig."""
    from backend.db import get_db
    from backend.rinse_freshness_store import (
        ensure_freshness_tables,
        fence_lane_lease,
        finish_cycle,
        get_watermarks,
        insert_cycle,
        list_recent_cycles,
        touch_cycle_progress,
        upsert_watermarks,
    )
    from backend.rinse_scheduled_scrape import parse_scheduled_org_ids

    org = int(organization_id or (parse_scheduled_org_ids() or [3])[0])
    print(
        f"rinse freshness supervisor start org={org} "
        f"ceiling={fast_child_ceiling_seconds()}s stall={meaningful_stall_seconds()}s",
        flush=True,
    )

    # Reclaim orphans left by a dead ACA execution (cycle RUNNING, no live child).
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        ensure_freshness_tables(cursor)
        stall = meaningful_stall_seconds()
        cursor.execute(
            """
            UPDATE rinse_freshness_cycles
            SET cycle_status='FAILED',
                finished_at=UTC_TIMESTAMP(6),
                duration_seconds=TIMESTAMPDIFF(SECOND, started_at, UTC_TIMESTAMP(6)),
                error_message=%s
            WHERE organization_id=%s
              AND cycle_status='RUNNING'
              AND (
                meaningful_progress_at IS NULL
                OR meaningful_progress_at < (UTC_TIMESTAMP(6) - INTERVAL %s SECOND)
              )
            """,
            (f"FAILED_ORPHAN_RECLAIM stall>{stall}s", org, int(stall)),
        )
        reclaimed = cursor.rowcount
        if reclaimed:
            fence_lane_lease(cursor, org, "fast", reason="FAILED_ORPHAN_RECLAIM")
            print(
                f"rinse freshness supervisor reclaimed {reclaimed} orphan RUNNING cycle(s)",
                flush=True,
            )
        # Also terminalize orphan scrape runs stuck in running.
        try:
            cursor.execute(
                """
                UPDATE rinse_scrape_runs
                SET status='failed',
                    finished_at=UTC_TIMESTAMP(6),
                    error_message=%s
                WHERE organization_id=%s AND status='running'
                  AND started_at < (UTC_TIMESTAMP(6) - INTERVAL %s SECOND)
                """,
                (f"FAILED_ORPHAN_RECLAIM stall>{stall}s", org, int(max(stall, 300))),
            )
        except Exception:
            pass
        conn.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    consecutive_failures = 0
    fast_successes = 0
    cycles_run = 0

    while True:
        if max_cycles is not None and cycles_run >= int(max_cycles):
            print("rinse freshness supervisor max_cycles reached", flush=True)
            return 0

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            ensure_freshness_tables(cursor)
            conn.commit()
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        # Decide lane: fast always; occasionally kick rolling/deep as separate children
        # AFTER a fast cycle (non-blocking from the fast path's perspective: sequential
        # in this single-replica supervisor, but deep uses its own lane lease and cannot
        # fence the fast lane).
        lane = "fast"
        cycles_run += 1
        print(
            f"CHAIN_BOUNDARY supervisor_cycle_start lane={lane} n={cycles_run} "
            f"utc={_utcnow().isoformat()}Z",
            flush=True,
        )

        proc = _spawn_cycle(org, lane)
        started = time.monotonic()
        last_output = time.monotonic()
        child_ok = False
        timed_out = False
        stalled = False
        exit_code = None

        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
                last_output = time.monotonic()
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)

            elapsed = time.monotonic() - started
            if elapsed >= fast_child_ceiling_seconds():
                timed_out = True
                print(
                    f"rinse freshness supervisor: child ceiling {elapsed:.0f}s — killing",
                    flush=True,
                )
                _kill_process_tree(proc)
                break
            if (time.monotonic() - last_output) >= meaningful_stall_seconds():
                # No stdout = no meaningful progress telemetry from child.
                stalled = True
                print(
                    f"rinse freshness supervisor: child silent "
                    f"{time.monotonic() - last_output:.0f}s — killing",
                    flush=True,
                )
                _kill_process_tree(proc)
                break

        exit_code = proc.poll()
        # 0=SUCCESS, 2=DEGRADED (raw retained; continue immediately for projection retry)
        child_ok = exit_code in (0, 2) and not timed_out and not stalled

        # Fence if needed
        if not child_ok:
            conn = get_db()
            cursor = conn.cursor(dictionary=True, buffered=True)
            try:
                reason = (
                    "FAILED_TIMEOUT"
                    if timed_out
                    else ("FAILED_STALLED" if stalled else f"FAILED_EXIT_{exit_code}")
                )
                fence_lane_lease(cursor, org, "fast", reason=reason)
                # Terminalize any RUNNING fast cycles left by a killed child.
                cursor.execute(
                    """
                    UPDATE rinse_freshness_cycles
                    SET cycle_status='FAILED',
                        finished_at=UTC_TIMESTAMP(6),
                        duration_seconds=TIMESTAMPDIFF(SECOND, started_at, UTC_TIMESTAMP(6)),
                        error_message=%s
                    WHERE organization_id=%s AND lane='fast' AND cycle_status='RUNNING'
                    """,
                    (reason[:512], org),
                )
                conn.commit()
                print(f"rinse freshness supervisor fenced fast lane reason={reason}", flush=True)
            finally:
                cursor.close()
                conn.close()
            consecutive_failures += 1
            wait = failure_backoff_seconds(consecutive_failures)
            print(
                f"rinse freshness supervisor backoff {wait}s after failure "
                f"(consecutive={consecutive_failures})",
                flush=True,
            )
            time.sleep(wait)
            continue

        consecutive_failures = 0
        if exit_code == 2:
            print(
                f"CHAIN_BOUNDARY supervisor_cycle_degraded n={cycles_run} "
                f"next=immediate (projection retry)",
                flush=True,
            )
        else:
            fast_successes += 1
            print(
                f"CHAIN_BOUNDARY supervisor_cycle_success n={cycles_run} "
                f"fast_successes={fast_successes} next=immediate",
                flush=True,
            )

        # Optional rolling / deep as separate children (own lane lease).
        # Rolling: short wait. Deep: fire-and-forget so it cannot block fast freshness;
        # a dedicated reconcile replica is preferred long-term.
        if fast_successes % rolling_every_n_fast() == 0:
            print("rinse freshness supervisor spawning rolling reconcile", flush=True)
            rproc = _spawn_cycle(org, "rolling")
            try:
                rproc.wait(timeout=min(600, fast_child_ceiling_seconds()))
            except subprocess.TimeoutExpired:
                _kill_process_tree(rproc)
                conn = get_db()
                cur = conn.cursor(dictionary=True, buffered=True)
                try:
                    fence_lane_lease(cur, org, "rolling", reason="FAILED_TIMEOUT")
                    conn.commit()
                finally:
                    cur.close()
                    conn.close()
        if fast_successes % deep_every_n_fast() == 0:
            print(
                "rinse freshness supervisor spawning deep reconcile (non-blocking)",
                flush=True,
            )
            # Non-blocking: do not wait. Deep uses its own lane lease and cannot
            # fence the fast lane. Orphan risk is accepted for v1 single replica;
            # production should add a separate deep-reconcile Container App later.
            _spawn_cycle(org, "deep")

        # Success → immediate next fast cycle (no cooldown).
