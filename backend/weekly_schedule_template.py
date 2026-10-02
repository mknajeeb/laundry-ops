"""Weekly schedule propagation to future weeks.

Two modes:

* Ongoing template — one org-wide source week. Every week after it mirrors it by weekday:
  existing later weeks are replaced when the template is enabled and on every change to the
  source week, and later weeks opened for the first time are seeded from it. Only the
  linkage is stored (no pre-created weeks).
* One-time copy — the source week replaces the selected later weeks once; no linkage.

Both replace planned rows only (shifts, partial role ranges, tasks, instructions, breaks,
exclusions). Attendance, payroll, and weeks on or before the source/current week are never touched.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import (
    apply_week_copy,
    build_week_copy,
    clear_week_schedule,
    normalize_week_start,
    week_copy_has_content,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists

STATE_TABLE = "weekly_schedule_org_state"
FUTURE_WEEKS_HORIZON = 12


def ensure_org_state_table(cursor) -> None:
    if table_exists(cursor, STATE_TABLE):
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
          organization_id INT NOT NULL PRIMARY KEY,
          template_enabled TINYINT(1) NOT NULL DEFAULT 0,
          template_source_week DATE NULL DEFAULT NULL,
          template_updated_at TIMESTAMP NULL DEFAULT NULL,
          template_updated_by INT NULL DEFAULT NULL,
          cleaning_tasks_migrated_at TIMESTAMP NULL DEFAULT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    invalidate_schema_cache()


def get_org_state(cursor, organization_id: int) -> dict[str, Any]:
    ensure_org_state_table(cursor)
    cursor.execute(
        f"""
        SELECT organization_id, template_enabled, template_source_week, template_updated_at,
               template_updated_by, cleaning_tasks_migrated_at
        FROM {STATE_TABLE}
        WHERE organization_id = %s
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else {"organization_id": int(organization_id)}


def _save_template(cursor, organization_id: int, *, enabled: bool, source: date | None, user_id: int | None) -> None:
    ensure_org_state_table(cursor)
    cursor.execute(
        f"""
        INSERT INTO {STATE_TABLE}
            (organization_id, template_enabled, template_source_week, template_updated_at, template_updated_by)
        VALUES (%s, %s, %s, UTC_TIMESTAMP(), %s)
        ON DUPLICATE KEY UPDATE
            template_enabled = VALUES(template_enabled),
            template_source_week = VALUES(template_source_week),
            template_updated_at = VALUES(template_updated_at),
            template_updated_by = VALUES(template_updated_by)
        """,
        (int(organization_id), 1 if enabled else 0, source, user_id),
    )


def _as_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def active_template_source(cursor, organization_id: int) -> date | None:
    state = get_org_state(cursor, organization_id)
    if not state.get("template_enabled"):
        return None
    return _as_date(state.get("template_source_week"))


def template_source_for_week(cursor, organization_id: int, week_start: date) -> date | None:
    """Template source week that ``week_start`` follows (None when it does not follow one)."""
    source = active_template_source(cursor, organization_id)
    return source if source and week_start > source else None


def schedule_template_payload(cursor, organization_id: int, week_start: date) -> dict[str, Any]:
    state = get_org_state(cursor, organization_id)
    enabled = bool(state.get("template_enabled"))
    source = _as_date(state.get("template_source_week")) if enabled else None
    updated_at = state.get("template_updated_at")
    return {
        "enabled": bool(source),
        "source_week_start": str(source) if source else None,
        "is_source": bool(source) and week_start == source,
        "follows_template": bool(source) and week_start > source,
        "updated_at": f"{updated_at.isoformat()}Z" if hasattr(updated_at, "isoformat") else None,
    }


def current_week_start() -> date:
    from backend.business_time import business_today

    week = normalize_week_start(business_today())
    assert week is not None
    return week


def _content_weeks_after(cursor, organization_id: int, after: date) -> list[date]:
    from backend.planned_weekly_schedule_responsibilities import TABLE as RESP_TABLE, ensure_responsibilities_table
    from backend.planned_weekly_schedule import (
        ensure_planned_weekly_schedule_exclusions_table,
        ensure_planned_weekly_schedule_table,
    )

    ensure_planned_weekly_schedule_table(cursor)
    ensure_planned_weekly_schedule_exclusions_table(cursor)
    ensure_responsibilities_table(cursor)
    weeks: set[date] = set()
    for table in ("planned_weekly_schedule_entries", "planned_weekly_schedule_exclusions", RESP_TABLE):
        cursor.execute(
            f"SELECT DISTINCT week_start FROM {table} WHERE organization_id = %s AND week_start > %s",
            (int(organization_id), after),
        )
        for row in cursor.fetchall() or []:
            week = _as_date(row.get("week_start") if isinstance(row, dict) else row[0])
            if week:
                weeks.add(week)
    return sorted(weeks)


def _replace_week(cursor, organization_id: int, week: date, copy: Mapping[str, Any]) -> dict[str, Any]:
    cleared = clear_week_schedule(cursor, organization_id, week_start=week)
    applied = apply_week_copy(cursor, organization_id, target_week_start=week, copy=copy)
    had_content = any(int(v or 0) for v in cleared.values())
    has_content = week_copy_has_content(copy)
    if had_content and has_content:
        status = "replaced"
    elif has_content:
        status = "created"
    else:
        status = "cleared" if had_content else "unchanged"
    return {
        "week_start": str(week),
        "status": status,
        "shifts_removed": int(cleared.get("entries_deleted") or 0),
        "tasks_removed": int(cleared.get("responsibilities_deleted") or 0),
        "shifts_copied": int(applied.get("entries_copied") or 0),
        "tasks_copied": int(applied.get("responsibilities_copied") or 0),
        "employees_skipped": int(applied.get("entries_skipped") or 0),
    }


def _copy_to_weeks(conn, cursor, organization_id: int, *, source: date, weeks: Sequence[date]) -> list[dict[str, Any]]:
    if not weeks:
        return []
    copy = build_week_copy(conn, cursor, organization_id, source_week_start=source, seed_sunday_from_saturday=False)
    return [_replace_week(cursor, organization_id, week, copy) for week in weeks]


def enable_template(
    conn,
    cursor,
    organization_id: int,
    *,
    source_week_start: Any,
    user_id: int | None,
) -> tuple[dict[str, Any] | None, str | None]:
    source = normalize_week_start(source_week_start)
    if not isinstance(source, date):
        return None, "source_week_start must be YYYY-MM-DD"
    if source < current_week_start():
        return None, "the template week must be the current week or a later week"
    copy = build_week_copy(conn, cursor, organization_id, source_week_start=source, seed_sunday_from_saturday=False)
    if not week_copy_has_content(copy):
        return None, "this week has no schedule to use as the template"
    weeks = _content_weeks_after(cursor, organization_id, source)
    results = [_replace_week(cursor, organization_id, week, copy) for week in weeks]
    _save_template(cursor, organization_id, enabled=True, source=source, user_id=user_id)
    return {"mode": "template", "source_week_start": str(source), "weeks": results}, None


def disable_template(cursor, organization_id: int, *, user_id: int | None) -> dict[str, Any]:
    source = active_template_source(cursor, organization_id)
    _save_template(cursor, organization_id, enabled=False, source=source, user_id=user_id)
    return {"mode": "template", "disabled": True, "source_week_start": str(source) if source else None}


def propagate_template_if_source(conn, cursor, organization_id: int, week_start: Any) -> dict[str, Any] | None:
    """After a change to the template source week, re-sync every later week. No-op for other weeks."""
    week = normalize_week_start(week_start)
    source = active_template_source(cursor, organization_id)
    if not source or week != source:
        return None
    weeks = _content_weeks_after(cursor, organization_id, source)
    return {"source_week_start": str(source), "weeks": _copy_to_weeks(conn, cursor, organization_id, source=source, weeks=weeks)}


def copy_to_selected_weeks(
    conn,
    cursor,
    organization_id: int,
    *,
    source_week_start: Any,
    target_weeks: Sequence[Any],
    user_id: int | None,
) -> tuple[dict[str, Any] | None, str | None]:
    source = normalize_week_start(source_week_start)
    if not isinstance(source, date):
        return None, "source_week_start must be YYYY-MM-DD"
    floor = max(source, current_week_start())
    weeks: list[date] = []
    for raw in target_weeks or []:
        week = normalize_week_start(raw)
        if not isinstance(week, date):
            return None, f"invalid target week: {raw}"
        if week <= floor:
            return None, f"{week} is not a future week after {source}"
        if week not in weeks:
            weeks.append(week)
    if not weeks:
        return None, "select at least one future week"
    copy = build_week_copy(conn, cursor, organization_id, source_week_start=source, seed_sunday_from_saturday=False)
    if not week_copy_has_content(copy):
        return None, "this week has no schedule to copy"
    # Choosing selected weeks ends any ongoing template, so later edits stop propagating.
    template_stopped = active_template_source(cursor, organization_id)
    if template_stopped:
        _save_template(cursor, organization_id, enabled=False, source=template_stopped, user_id=user_id)
    results = [_replace_week(cursor, organization_id, week, copy) for week in sorted(weeks)]
    return {
        "mode": "selected",
        "source_week_start": str(source),
        "weeks": results,
        "template_stopped": str(template_stopped) if template_stopped else None,
    }, None


def list_future_weeks(cursor, organization_id: int, *, source_week_start: Any) -> list[dict[str, Any]]:
    """Weeks a copy from ``source_week_start`` may target: the next few weeks plus any later saved weeks."""
    from backend.planned_weekly_schedule_responsibilities import TABLE as RESP_TABLE

    source = normalize_week_start(source_week_start)
    if not isinstance(source, date):
        return []
    floor = max(source, current_week_start())
    weeks = {floor + timedelta(days=7 * i) for i in range(1, FUTURE_WEEKS_HORIZON + 1)}
    weeks.update(_content_weeks_after(cursor, organization_id, floor))
    counts: dict[date, dict[str, int]] = {w: {"shifts": 0, "tasks": 0} for w in weeks}
    for table, key in (("planned_weekly_schedule_entries", "shifts"), (RESP_TABLE, "tasks")):
        cursor.execute(
            f"""
            SELECT week_start, COUNT(*) AS n FROM {table}
            WHERE organization_id = %s AND week_start > %s
            GROUP BY week_start
            """,
            (int(organization_id), floor),
        )
        for row in cursor.fetchall() or []:
            week = _as_date(row.get("week_start"))
            if week in counts:
                counts[week][key] = int(row.get("n") or 0)
    return [
        {"week_start": str(w), **counts[w], "has_schedule": bool(counts[w]["shifts"] or counts[w]["tasks"])}
        for w in sorted(weeks)
    ]


def ensure_cleaning_tasks_migrated(cursor, organization_id: int) -> dict[str, Any] | None:
    """One-time per org: cleaning assignments saved on timed shifts become day tasks."""
    from backend.planned_weekly_schedule_responsibilities import migrate_timed_tasks_to_responsibilities
    from backend.weekly_schedule_roles import CLEANING_TASK_CODES, catalog_index, list_role_catalog

    state = get_org_state(cursor, organization_id)
    if state.get("cleaning_tasks_migrated_at"):
        return None
    catalog = catalog_index(list_role_catalog(cursor, organization_id))
    task_roles = {code for code in CLEANING_TASK_CODES if not catalog.get(code, {}).get("uses_time_slots", True)}
    result = migrate_timed_tasks_to_responsibilities(cursor, organization_id, task_roles=task_roles)
    cursor.execute(
        f"""
        INSERT INTO {STATE_TABLE} (organization_id, cleaning_tasks_migrated_at)
        VALUES (%s, UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE cleaning_tasks_migrated_at = VALUES(cleaning_tasks_migrated_at)
        """,
        (int(organization_id),),
    )
    return result
