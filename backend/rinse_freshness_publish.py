"""Atomic Management snapshot publish for freshness cycles.

Management must never display business zeros for an unpublished day.
Failed cycles keep the last published version visible (STALE).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from backend.rinse_freshness_store import LaneFencedError, assert_lane_writable, ensure_freshness_tables


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_snapshot_version(cursor, organization_id: int, shift_date_et: date) -> int:
    ensure_freshness_tables(cursor)
    cursor.execute(
        """
        SELECT COALESCE(MAX(version), 0) AS mx
        FROM rinse_management_snapshot_versions
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (int(organization_id), shift_date_et),
    )
    row = cursor.fetchone() or {}
    return int((row.get("mx") if isinstance(row, dict) else 0) or 0) + 1


def begin_snapshot_build(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    cycle_id: int,
    lease_generation: int,
) -> int:
    ensure_freshness_tables(cursor)
    ver = next_snapshot_version(cursor, organization_id, shift_date_et)
    now = _utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_management_snapshot_versions (
          organization_id, shift_date_et, version, publish_status,
          cycle_id, lease_generation, created_at
        ) VALUES (%s, %s, %s, 'building', %s, %s, %s)
        """,
        (
            int(organization_id),
            shift_date_et,
            ver,
            int(cycle_id),
            int(lease_generation),
            now,
        ),
    )
    return ver


def publish_snapshot(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    version: int,
    lease_generation: int,
    lane: str,
    headline: dict[str, Any] | None,
    workload_meta: dict[str, Any] | None,
) -> None:
    """Promote building→published only if lease generation is still live."""
    assert_lane_writable(cursor, organization_id, lane, lease_generation)
    now = _utcnow()
    # Reject stale generation on the version row itself.
    cursor.execute(
        """
        SELECT lease_generation, publish_status
        FROM rinse_management_snapshot_versions
        WHERE organization_id=%s AND shift_date_et=%s AND version=%s
        LIMIT 1
        """,
        (int(organization_id), shift_date_et, int(version)),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict):
        raise RuntimeError("snapshot version missing")
    if int(row.get("lease_generation") or 0) != int(lease_generation):
        raise LaneFencedError("snapshot lease generation mismatch")
    if row.get("publish_status") != "building":
        raise RuntimeError(f"snapshot not building: {row.get('publish_status')}")

    cursor.execute(
        """
        UPDATE rinse_management_snapshot_versions
        SET publish_status='superseded'
        WHERE organization_id=%s AND shift_date_et=%s
          AND publish_status='published' AND version < %s
        """,
        (int(organization_id), shift_date_et, int(version)),
    )
    cursor.execute(
        """
        UPDATE rinse_management_snapshot_versions
        SET publish_status='published',
            published_at=%s,
            headline_json=%s,
            workload_meta_json=%s
        WHERE organization_id=%s AND shift_date_et=%s AND version=%s
          AND publish_status='building'
        """,
        (
            now,
            json.dumps(headline or {}, default=str),
            json.dumps(workload_meta or {}, default=str),
            int(organization_id),
            shift_date_et,
            int(version),
        ),
    )


def mark_snapshot_failed(
    cursor,
    *,
    organization_id: int,
    shift_date_et: date,
    version: int,
) -> None:
    cursor.execute(
        """
        UPDATE rinse_management_snapshot_versions
        SET publish_status='failed'
        WHERE organization_id=%s AND shift_date_et=%s AND version=%s
          AND publish_status='building'
        """,
        (int(organization_id), shift_date_et, int(version)),
    )


def latest_published_snapshot(
    cursor, organization_id: int, shift_date_et: date
) -> dict[str, Any] | None:
    ensure_freshness_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM rinse_management_snapshot_versions
        WHERE organization_id=%s AND shift_date_et=%s AND publish_status='published'
        ORDER BY version DESC LIMIT 1
        """,
        (int(organization_id), shift_date_et),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def latest_any_published_for_org(
    cursor, organization_id: int
) -> dict[str, Any] | None:
    """Most recent published snapshot across dates (for STALE fallback)."""
    ensure_freshness_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM rinse_management_snapshot_versions
        WHERE organization_id=%s AND publish_status='published'
        ORDER BY published_at DESC, version DESC LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None
