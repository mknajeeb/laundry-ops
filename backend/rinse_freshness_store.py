"""Rinse freshness watermarks, cycle records, and lane leases.

Independent watermarks answer “where is data stuck?” without a single last_sync_at.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_freshness_tables(cursor) -> None:
    sql_path = os.path.join(
        os.path.dirname(__file__), "sql", "rinse_freshness_v1.sql"
    )
    _run_sql_file(cursor, sql_path)
    chrono_path = os.path.join(
        os.path.dirname(__file__), "sql", "rinse_freshness_chronology_watermark_v1.sql"
    )
    if os.path.isfile(chrono_path):
        _run_sql_file(cursor, chrono_path)


def _run_sql_file(cursor, sql_path: str) -> None:
    raw = open(sql_path, encoding="utf-8").read()
    # Split on semicolons that end statements (simple; file has no routines).
    statements = []
    buf: list[str] = []
    for line in raw.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    for stmt in statements:
        s = stmt.strip()
        if not s:
            continue
        cursor.execute(s)
        try:
            if getattr(cursor, "with_rows", False):
                cursor.fetchall()
        except Exception:
            pass
        try:
            for _ in range(8):
                more = cursor.nextset()
                if more is not True:
                    break
                if getattr(cursor, "with_rows", False):
                    cursor.fetchall()
        except Exception:
            pass


def get_watermarks(cursor, organization_id: int) -> dict[str, Any]:
    ensure_freshness_tables(cursor)
    org = int(organization_id)
    cursor.execute(
        "SELECT * FROM rinse_freshness_watermarks WHERE organization_id = %s LIMIT 1",
        (org,),
    )
    row = cursor.fetchone()
    if isinstance(row, dict):
        return row
    return {
        "organization_id": org,
        "source_inspected_through": None,
        "source_inspected_complete": 0,
        "raw_imported_through": None,
        "canonical_processed_through": None,
        "chronology_processed_through": None,
        "management_published_through": None,
        "last_rolling_reconciliation": None,
        "last_deep_reconciliation": None,
        "last_fast_cycle_id": None,
        "last_fast_result": None,
    }


def upsert_watermarks(cursor, organization_id: int, **fields: Any) -> None:
    ensure_freshness_tables(cursor)
    org = int(organization_id)
    now = _utcnow()
    allowed = {
        "source_inspected_through",
        "source_inspected_complete",
        "raw_imported_through",
        "canonical_processed_through",
        "chronology_processed_through",
        "management_published_through",
        "last_rolling_reconciliation",
        "last_deep_reconciliation",
        "last_fast_cycle_id",
        "last_fast_result",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    cols = ["organization_id", "updated_at"] + list(payload.keys())
    vals = [org, now] + [payload[k] for k in payload]
    updates = ", ".join(f"{k}=VALUES({k})" for k in payload)
    updates += ", updated_at=VALUES(updated_at)"
    placeholders = ", ".join(["%s"] * len(cols))
    cursor.execute(
        f"""
        INSERT INTO rinse_freshness_watermarks ({", ".join(cols)})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {updates}
        """,
        vals,
    )


def insert_cycle(
    cursor,
    *,
    organization_id: int,
    lane: str,
    lease_generation: int | None = None,
    child_pid: int | None = None,
) -> int:
    ensure_freshness_tables(cursor)
    now = _utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_freshness_cycles (
          organization_id, lane, cycle_status, started_at, lease_generation,
          child_pid, stage, meaningful_progress_at, heartbeat_at, created_at
        ) VALUES (%s, %s, 'RUNNING', %s, %s, %s, 'starting', %s, %s, %s)
        """,
        (
            int(organization_id),
            str(lane)[:16],
            now,
            lease_generation,
            child_pid,
            now,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def touch_cycle_progress(
    cursor,
    cycle_id: int,
    *,
    stage: str | None = None,
    meaningful: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    now = _utcnow()
    sets = ["heartbeat_at = %s"]
    args: list[Any] = [now]
    if stage:
        sets.append("stage = %s")
        args.append(str(stage)[:64])
    if meaningful:
        sets.append("meaningful_progress_at = %s")
        args.append(now)
    if extra:
        for k in (
            "portal_seconds",
            "import_seconds",
            "projection_seconds",
            "publish_seconds",
            "portal_pages",
            "portal_rows",
            "bags_affected",
            "batch_id",
            "scrape_run_id",
            "source_inspected_complete",
        ):
            if k in extra and extra[k] is not None:
                sets.append(f"{k} = %s")
                args.append(extra[k])
        if "dates_affected" in extra and extra["dates_affected"] is not None:
            sets.append("dates_affected_json = %s")
            args.append(json.dumps(extra["dates_affected"], default=str))
    args.append(int(cycle_id))
    cursor.execute(
        f"UPDATE rinse_freshness_cycles SET {', '.join(sets)} WHERE id = %s",
        args,
    )


def finish_cycle(
    cursor,
    cycle_id: int,
    *,
    cycle_status: str,
    error_message: str | None = None,
    result_json: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> None:
    now = _utcnow()
    dur = None
    if started_at is not None:
        dur = max(0, int((now - started_at).total_seconds()))
    cursor.execute(
        """
        UPDATE rinse_freshness_cycles
        SET cycle_status = %s,
            finished_at = %s,
            duration_seconds = COALESCE(%s, TIMESTAMPDIFF(SECOND, started_at, %s)),
            error_message = %s,
            result_json = %s,
            heartbeat_at = %s
        WHERE id = %s AND cycle_status = 'RUNNING'
        """,
        (
            str(cycle_status)[:16],
            now,
            dur,
            now,
            (error_message or "")[:512] or None,
            json.dumps(result_json or {}, default=str),
            now,
            int(cycle_id),
        ),
    )


def list_recent_cycles(
    cursor, organization_id: int, *, limit: int = 20, lane: str | None = None
) -> list[dict[str, Any]]:
    ensure_freshness_tables(cursor)
    if lane:
        cursor.execute(
            """
            SELECT * FROM rinse_freshness_cycles
            WHERE organization_id = %s AND lane = %s
            ORDER BY id DESC LIMIT %s
            """,
            (int(organization_id), str(lane)[:16], int(limit)),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM rinse_freshness_cycles
            WHERE organization_id = %s
            ORDER BY id DESC LIMIT %s
            """,
            (int(organization_id), int(limit)),
        )
    rows = cursor.fetchall() or []
    return [r for r in rows if isinstance(r, dict)]


class LaneFencedError(RuntimeError):
    pass


def take_lane_lease(
    cursor, organization_id: int, lane: str, *, cycle_id: int
) -> int:
    ensure_freshness_tables(cursor)
    org = int(organization_id)
    now = _utcnow()
    lane_s = str(lane)[:16]
    cursor.execute(
        """
        INSERT INTO rinse_freshness_lane_lease (
          organization_id, lane, generation, owner_cycle_id, owner_pid,
          heartbeat_at, meaningful_progress_at, current_stage, fenced_at,
          fence_reason, updated_at
        ) VALUES (%s, %s, 1, %s, %s, %s, %s, 'starting', NULL, NULL, %s)
        ON DUPLICATE KEY UPDATE
          generation = generation + 1,
          owner_cycle_id = VALUES(owner_cycle_id),
          owner_pid = VALUES(owner_pid),
          heartbeat_at = VALUES(heartbeat_at),
          meaningful_progress_at = VALUES(meaningful_progress_at),
          current_stage = VALUES(current_stage),
          fenced_at = NULL,
          fence_reason = NULL,
          updated_at = VALUES(updated_at)
        """,
        (org, lane_s, int(cycle_id), os.getpid(), now, now, now),
    )
    cursor.execute(
        """
        SELECT generation FROM rinse_freshness_lane_lease
        WHERE organization_id = %s AND lane = %s LIMIT 1
        """,
        (org, lane_s),
    )
    row = cursor.fetchone() or {}
    return int((row.get("generation") if isinstance(row, dict) else 1) or 1)


def assert_lane_writable(
    cursor, organization_id: int, lane: str, generation: int
) -> None:
    cursor.execute(
        """
        SELECT generation FROM rinse_freshness_lane_lease
        WHERE organization_id = %s AND lane = %s LIMIT 1
        """,
        (int(organization_id), str(lane)[:16]),
    )
    row = cursor.fetchone() or {}
    live = int((row.get("generation") if isinstance(row, dict) else 0) or 0)
    if live != int(generation):
        raise LaneFencedError(
            f"lane {lane} generation {generation} fenced; live={live}"
        )


def touch_lane_lease(
    cursor,
    organization_id: int,
    lane: str,
    generation: int,
    *,
    stage: str | None = None,
    meaningful: bool = False,
) -> bool:
    now = _utcnow()
    if stage and meaningful:
        cursor.execute(
            """
            UPDATE rinse_freshness_lane_lease
            SET heartbeat_at=%s, meaningful_progress_at=%s, current_stage=%s, updated_at=%s
            WHERE organization_id=%s AND lane=%s AND generation=%s
            """,
            (
                now,
                now,
                str(stage)[:64],
                now,
                int(organization_id),
                str(lane)[:16],
                int(generation),
            ),
        )
    elif stage:
        cursor.execute(
            """
            UPDATE rinse_freshness_lane_lease
            SET heartbeat_at=%s, current_stage=%s, updated_at=%s
            WHERE organization_id=%s AND lane=%s AND generation=%s
            """,
            (
                now,
                str(stage)[:64],
                now,
                int(organization_id),
                str(lane)[:16],
                int(generation),
            ),
        )
    else:
        cursor.execute(
            """
            UPDATE rinse_freshness_lane_lease
            SET heartbeat_at=%s, updated_at=%s
            WHERE organization_id=%s AND lane=%s AND generation=%s
            """,
            (now, now, int(organization_id), str(lane)[:16], int(generation)),
        )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def fence_lane_lease(
    cursor, organization_id: int, lane: str, *, reason: str
) -> int:
    ensure_freshness_tables(cursor)
    now = _utcnow()
    cursor.execute(
        """
        UPDATE rinse_freshness_lane_lease
        SET generation = generation + 1,
            owner_cycle_id = NULL,
            owner_pid = NULL,
            current_stage = NULL,
            fenced_at = %s,
            fence_reason = %s,
            updated_at = %s
        WHERE organization_id = %s AND lane = %s
        """,
        (now, str(reason)[:255], now, int(organization_id), str(lane)[:16]),
    )
    cursor.execute(
        """
        SELECT generation FROM rinse_freshness_lane_lease
        WHERE organization_id = %s AND lane = %s LIMIT 1
        """,
        (int(organization_id), str(lane)[:16]),
    )
    row = cursor.fetchone() or {}
    return int((row.get("generation") if isinstance(row, dict) else 0) or 0)


def release_lane_lease_if_owner(
    cursor, organization_id: int, lane: str, generation: int
) -> None:
    now = _utcnow()
    cursor.execute(
        """
        UPDATE rinse_freshness_lane_lease
        SET owner_cycle_id = NULL,
            owner_pid = NULL,
            current_stage = NULL,
            updated_at = %s
        WHERE organization_id = %s AND lane = %s AND generation = %s
        """,
        (now, int(organization_id), str(lane)[:16], int(generation)),
    )
