"""Organization schedule-reset boundary.

A stored date means that organization no longer regenerates employee shifts
into any Sunday–Saturday week that includes that date or a later one.
Opening a week does not copy shifts or tasks across the boundary. An explicit
copy may still write shifts, and it does not delete, replace, or insert tasks.

Weeks that end before the boundary keep the existing copy behavior.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from backend.ta_helpers import invalidate_schema_cache, table_exists

STATE_TABLE = "weekly_schedule_org_state"
RESET_COLUMN = "schedule_reset_on"


def week_reaches_reset(week_start: date, effective: date) -> bool:
    """True when this Sunday or Monday week contains ``effective`` or a later day."""
    return week_start + timedelta(days=6) >= effective


def pattern_end_before_reset(reset_on: date) -> date:
    """Last date a shift pattern may keep.

    The planner treats ``effective_until`` as exclusive (``monday < end``).
    The day before the reset is also outside an inclusive reading
    (``monday <= end``), so a pattern cannot cover the reset day either way.
    """
    return reset_on - timedelta(days=1)


def ensure_reset_column(cursor) -> bool:
    """Add the boundary column when the org-state table already exists."""
    if not table_exists(cursor, STATE_TABLE):
        return False
    cursor.execute(f"SHOW COLUMNS FROM {STATE_TABLE} LIKE %s", (RESET_COLUMN,))
    if cursor.fetchone():
        return True
    cursor.execute(
        f"ALTER TABLE {STATE_TABLE} ADD COLUMN {RESET_COLUMN} DATE NULL DEFAULT NULL"
    )
    invalidate_schema_cache()
    return True


def reset_effective_on(cursor, organization_id: int) -> date | None:
    if not ensure_reset_column(cursor):
        return None
    cursor.execute(
        f"SELECT {RESET_COLUMN} FROM {STATE_TABLE} WHERE organization_id=%s LIMIT 1",
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    raw = row.get(RESET_COLUMN) if isinstance(row, dict) else None
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw)[:10])


def reset_blocks_week(cursor, organization_id: int, week_start: date) -> bool:
    effective = reset_effective_on(cursor, organization_id)
    return effective is not None and week_reaches_reset(week_start, effective)


def weeks_open_for_automatic_copy(cursor, organization_id: int, weeks: Sequence[date]) -> list[date]:
    """Drop weeks an automatic template refresh must not rewrite."""
    return [week for week in weeks if not reset_blocks_week(cursor, organization_id, week)]
