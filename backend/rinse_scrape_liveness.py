"""Scraper liveness: supervisor heartbeat independent of worker blocking."""

from __future__ import annotations

import os
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from backend.db import _connection_kwargs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _direct_mysql_connection():
    import mysql.connector

    return mysql.connector.connect(**_connection_kwargs())


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
            from backend.ta_helpers import table_has_column

            if not table_has_column(cur, "rinse_scrape_org_lease", "supervisor_heartbeat_at"):
                cur.execute(
                    """
                    ALTER TABLE rinse_scrape_org_lease
                    ADD COLUMN supervisor_heartbeat_at DATETIME(6) NULL AFTER heartbeat_at,
                    ADD COLUMN worker_progress_at DATETIME(6) NULL AFTER last_progress_at
                    """
                )
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
        conn.commit()
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
    from backend.rinse_scrape_lease import read_lease

    ensure_lease_liveness_columns(cursor)
    lease = read_lease(cursor, organization_id) or {}
    if not lease:
        return None
    sup = lease.get("supervisor_heartbeat_at") or lease.get("heartbeat_at")
    worker = lease.get("worker_progress_at") or lease.get("last_progress_at")
    lease["supervisor_heartbeat_at"] = sup
    lease["worker_progress_at"] = worker
    return lease
