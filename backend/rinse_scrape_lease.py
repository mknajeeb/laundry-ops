"""Fencing tokens for Rinse scheduled sync ownership.

GET_LOCK remains a secondary overlap guard. The lease generation is the
authority for who may commit/publish. After run A is fenced, generation N
cannot overwrite work from generation N+1.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


class FencedWriterError(RuntimeError):
    """Raised when a scrape tries to write after its lease generation was fenced."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_execution_name() -> str | None:
    raw = (
        os.getenv("CONTAINER_APP_JOB_EXECUTION_NAME")
        or os.getenv("CONTAINER_APP_REPLICA_NAME")
        or ""
    ).strip()
    return raw[:256] or None


def ensure_rinse_scrape_org_lease_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_scrape_org_lease (
            organization_id INT NOT NULL PRIMARY KEY,
            generation BIGINT NOT NULL DEFAULT 0,
            owner_run_id BIGINT NULL,
            owner_execution_name VARCHAR(256) NULL,
            owner_pid INT NULL,
            heartbeat_at DATETIME(6) NULL,
            last_progress_at DATETIME(6) NULL,
            current_stage VARCHAR(64) NULL,
            fenced_at DATETIME(6) NULL,
            fence_reason VARCHAR(255) NULL,
            updated_at DATETIME(6) NOT NULL,
            INDEX idx_rs_lease_owner_run (owner_run_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    try:
        if getattr(cursor, "with_rows", False):
            cursor.fetchall()
    except Exception:
        pass
    try:
        # mysql-connector returns True/False. Bound the loop so mocks cannot hang.
        for _ in range(32):
            more = cursor.nextset()
            if more is not True:
                break
            if getattr(cursor, "with_rows", False):
                cursor.fetchall()
    except Exception:
        pass


def read_lease(cursor, organization_id: int) -> dict[str, Any] | None:
    ensure_rinse_scrape_org_lease_table(cursor)
    cursor.execute(
        """
        SELECT organization_id, generation, owner_run_id, owner_execution_name,
               owner_pid, heartbeat_at, last_progress_at, current_stage,
               fenced_at, fence_reason, updated_at
        FROM rinse_scrape_org_lease
        WHERE organization_id = %s
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def take_lease(
    cursor,
    organization_id: int,
    *,
    run_id: int,
    execution_name: str | None = None,
    pid: int | None = None,
) -> int:
    """Increment generation and assign ownership to this run. Returns new generation."""
    ensure_rinse_scrape_org_lease_table(cursor)
    org = int(organization_id)
    now = _utcnow()
    exec_name = (execution_name or current_execution_name() or "")[:256] or None
    owner_pid = int(pid) if pid is not None else os.getpid()
    cursor.execute(
        """
        INSERT INTO rinse_scrape_org_lease (
            organization_id, generation, owner_run_id, owner_execution_name,
            owner_pid, heartbeat_at, last_progress_at, current_stage,
            fenced_at, fence_reason, updated_at
        )
        VALUES (%s, 1, %s, %s, %s, %s, %s, 'starting', NULL, NULL, %s)
        ON DUPLICATE KEY UPDATE
            generation = generation + 1,
            owner_run_id = VALUES(owner_run_id),
            owner_execution_name = VALUES(owner_execution_name),
            owner_pid = VALUES(owner_pid),
            heartbeat_at = VALUES(heartbeat_at),
            last_progress_at = VALUES(last_progress_at),
            current_stage = VALUES(current_stage),
            fenced_at = NULL,
            fence_reason = NULL,
            updated_at = VALUES(updated_at)
        """,
        (org, int(run_id), exec_name, owner_pid, now, now, now),
    )
    lease = read_lease(cursor, org) or {}
    return int(lease.get("generation") or 1)


def assert_lease_writable(cursor, organization_id: int, generation: int) -> None:
    lease = read_lease(cursor, organization_id)
    live = int((lease or {}).get("generation") or 0)
    if live != int(generation):
        raise FencedWriterError(
            f"lease generation {generation} is fenced; live generation is {live}"
        )


def touch_lease_heartbeat(
    cursor,
    organization_id: int,
    generation: int,
    *,
    stage: str | None = None,
    progress: bool = False,
) -> bool:
    ensure_rinse_scrape_org_lease_table(cursor)
    now = _utcnow()
    if stage and progress:
        cursor.execute(
            """
            UPDATE rinse_scrape_org_lease
            SET heartbeat_at = %s,
                last_progress_at = %s,
                current_stage = %s,
                updated_at = %s
            WHERE organization_id = %s AND generation = %s
            """,
            (now, now, str(stage)[:64], now, int(organization_id), int(generation)),
        )
    elif stage:
        cursor.execute(
            """
            UPDATE rinse_scrape_org_lease
            SET heartbeat_at = %s,
                current_stage = %s,
                updated_at = %s
            WHERE organization_id = %s AND generation = %s
            """,
            (now, str(stage)[:64], now, int(organization_id), int(generation)),
        )
    elif progress:
        cursor.execute(
            """
            UPDATE rinse_scrape_org_lease
            SET heartbeat_at = %s,
                last_progress_at = %s,
                updated_at = %s
            WHERE organization_id = %s AND generation = %s
            """,
            (now, now, now, int(organization_id), int(generation)),
        )
    else:
        cursor.execute(
            """
            UPDATE rinse_scrape_org_lease
            SET heartbeat_at = %s,
                updated_at = %s
            WHERE organization_id = %s AND generation = %s
            """,
            (now, now, int(organization_id), int(generation)),
        )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def fence_lease(
    cursor,
    organization_id: int,
    *,
    reason: str,
    expected_generation: int | None = None,
) -> int:
    """Invalidate the current owner. Returns the new (fenced-away) generation.

    Increments generation so the old owner can no longer write. Does not assign
    a new run until take_lease is called.
    """
    ensure_rinse_scrape_org_lease_table(cursor)
    org = int(organization_id)
    now = _utcnow()
    reason_s = (reason or "fenced")[:255]
    if expected_generation is not None:
        cursor.execute(
            """
            UPDATE rinse_scrape_org_lease
            SET generation = generation + 1,
                owner_run_id = NULL,
                fenced_at = %s,
                fence_reason = %s,
                updated_at = %s
            WHERE organization_id = %s AND generation = %s
            """,
            (now, reason_s, now, org, int(expected_generation)),
        )
    else:
        cursor.execute(
            """
            INSERT INTO rinse_scrape_org_lease (
                organization_id, generation, owner_run_id, fenced_at, fence_reason, updated_at
            )
            VALUES (%s, 1, NULL, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                generation = generation + 1,
                owner_run_id = NULL,
                fenced_at = VALUES(fenced_at),
                fence_reason = VALUES(fence_reason),
                updated_at = VALUES(updated_at)
            """,
            (org, now, reason_s, now),
        )
    lease = read_lease(cursor, org) or {}
    return int(lease.get("generation") or 0)


def release_lease_if_owner(
    cursor,
    organization_id: int,
    generation: int,
) -> None:
    ensure_rinse_scrape_org_lease_table(cursor)
    now = _utcnow()
    cursor.execute(
        """
        UPDATE rinse_scrape_org_lease
        SET owner_run_id = NULL,
            owner_execution_name = NULL,
            owner_pid = NULL,
            updated_at = %s
        WHERE organization_id = %s AND generation = %s
        """,
        (now, int(organization_id), int(generation)),
    )
