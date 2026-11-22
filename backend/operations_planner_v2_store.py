"""Persistence for Operations Planner v2.

Schema is applied only by backend/sql/operations_planner_v2.sql.
Opening the planner, starting the app, or signing in with a PIN does not
create or alter tables. Historical attendance, punches, payroll, and task
completion rows are not rewritten from here.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.operations_planner_v2 import (
    ACTIVITY_LOCKED,
    empty_state,
    plan_assignment_draft,
    plan_entry_write,
    plan_task_links,
)
from backend.ta_helpers import table_exists
from backend.weekly_schedule_week import parse_schedule_date, storage_week_for_dow

FLAGS = "ops_planner_org_flags"
PATTERNS = "ops_planner_patterns"
EXCEPTIONS = "ops_planner_exceptions"
WEEKS = "ops_planner_weeks"
AUDIT = "ops_planner_audit"
ACCESS = "ops_planner_employee_access"
ROLES = "ops_planner_role_settings"
HOURS = "ops_planner_role_hours"
LINKS = "ops_planner_links"
CODES = "ops_planner_paystub_codes"
STAFFING = "ops_planner_staffing_requirements"
RESPONSIBILITIES = "planned_weekly_schedule_responsibilities"
ACTIVITIES = "cleaning_task_activities"
PLANNER_TABLES = (FLAGS, PATTERNS, EXCEPTIONS, WEEKS, AUDIT, ACCESS, ROLES, HOURS, CODES, LINKS)
SCHEMA_VERSION = "operations_planner_v2.2"


class StaffingRequirementError(ValueError):
    """A blank headcount is not stored as zero."""


class PlannerSchemaNotApplied(RuntimeError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("operations planner migration has not been applied")


def schema_status(cursor) -> dict[str, Any]:
    missing = [name for name in PLANNER_TABLES if not table_exists(cursor, name)]
    return {"ready": not missing, "missing": missing, "version": SCHEMA_VERSION}


def require_schema(cursor) -> None:
    status = schema_status(cursor)
    if not status["ready"]:
        raise PlannerSchemaNotApplied(status["missing"])


def _date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return parse_schedule_date(raw)


def _loads(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def load_flags(cursor, organization_id: int) -> dict[str, bool]:
    require_schema(cursor)
    cursor.execute(
        f"""
        SELECT manager_pilot, employee_pilot, paystub_access
        FROM {FLAGS} WHERE organization_id=%s
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict):
        row = {}
    return {
        "manager_pilot": bool(row.get("manager_pilot")),
        "employee_pilot": bool(row.get("employee_pilot")),
        "paystub_access": bool(row.get("paystub_access")),
    }


class PaystubSecurityHold(RuntimeError):
    """PIN plus date of birth is not enough to open paystubs on a shared device."""


def save_flags(cursor, organization_id: int, flags: Mapping[str, Any]) -> dict[str, bool]:
    current = load_flags(cursor, organization_id)
    for key in ("manager_pilot", "employee_pilot", "paystub_access"):
        if key in flags:
            current[key] = bool(flags.get(key))
    if current["paystub_access"]:
        raise PaystubSecurityHold(
            "Paystub access stays off. A shared-device PIN and date of birth are not an adequate identity check for payroll documents."
        )
    cursor.execute(
        f"""
        INSERT INTO {FLAGS} (organization_id, manager_pilot, employee_pilot, paystub_access, updated_at)
        VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
          manager_pilot=VALUES(manager_pilot),
          employee_pilot=VALUES(employee_pilot),
          paystub_access=VALUES(paystub_access),
          updated_at=UTC_TIMESTAMP()
        """,
        (
            int(organization_id),
            1 if current["manager_pilot"] else 0,
            1 if current["employee_pilot"] else 0,
            1 if current["paystub_access"] else 0,
        ),
    )
    return current


def load_state(cursor, organization_id: int) -> dict[str, Any]:
    require_schema(cursor)
    state = empty_state()
    org = int(organization_id)
    cursor.execute(
        f"""
        SELECT id, user_id, day_of_week, effective_from, effective_until, shift_json
        FROM {PATTERNS} WHERE organization_id=%s ORDER BY id
        """,
        (org,),
    )
    max_pattern = 0
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        max_pattern = max(max_pattern, int(row["id"]))
        state["patterns"].append(
            {
                "id": int(row["id"]),
                "user_id": int(row["user_id"]),
                "day_of_week": int(row["day_of_week"]),
                "effective_from": _date(row.get("effective_from")),
                "effective_until": _date(row.get("effective_until")),
                "shift": _loads(row.get("shift_json")) or {},
            }
        )
    state["next_pattern_id"] = max_pattern + 1
    cursor.execute(
        f"""
        SELECT id, user_id, week_monday, day_of_week, kind, shift_json
        FROM {EXCEPTIONS} WHERE organization_id=%s ORDER BY id
        """,
        (org,),
    )
    max_exception = 0
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        max_exception = max(max_exception, int(row["id"]))
        state["exceptions"].append(
            {
                "id": int(row["id"]),
                "user_id": int(row["user_id"]),
                "week_monday": _date(row.get("week_monday")),
                "day_of_week": int(row["day_of_week"]),
                "kind": row.get("kind") or "override",
                "shift": _loads(row.get("shift_json")),
            }
        )
    state["next_exception_id"] = max_exception + 1
    cursor.execute(
        f"""
        SELECT week_monday, status, revision, published_snapshot, published_revision
        FROM {WEEKS} WHERE organization_id=%s
        """,
        (org,),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        monday = _date(row.get("week_monday"))
        if monday is None:
            continue
        state["weeks"][monday.isoformat()] = {
            "status": row.get("status") or "draft",
            "revision": int(row.get("revision") or 1),
            "published_snapshot": _loads(row.get("published_snapshot")),
            "published_revision": row.get("published_revision"),
        }
    return state


def save_state(cursor, organization_id: int, state: Mapping[str, Any], audit: Mapping[str, Any] | None, actor_id: int | None) -> None:
    org = int(organization_id)
    cursor.execute(f"DELETE FROM {PATTERNS} WHERE organization_id=%s", (org,))
    for pattern in state.get("patterns") or []:
        cursor.execute(
            f"""
            INSERT INTO {PATTERNS}
              (id, organization_id, user_id, day_of_week, effective_from, effective_until, shift_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(pattern["id"]),
                org,
                int(pattern["user_id"]),
                int(pattern["day_of_week"]),
                pattern.get("effective_from"),
                pattern.get("effective_until"),
                json.dumps(pattern.get("shift") or {}),
            ),
        )
    cursor.execute(f"DELETE FROM {EXCEPTIONS} WHERE organization_id=%s", (org,))
    for row in state.get("exceptions") or []:
        cursor.execute(
            f"""
            INSERT INTO {EXCEPTIONS}
              (id, organization_id, user_id, week_monday, day_of_week, kind, shift_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(row["id"]),
                org,
                int(row["user_id"]),
                row.get("week_monday"),
                int(row["day_of_week"]),
                row.get("kind") or "override",
                json.dumps(row.get("shift")) if row.get("shift") is not None else None,
            ),
        )
    for key, status in (state.get("weeks") or {}).items():
        if not isinstance(status, Mapping):
            continue
        snapshot = status.get("published_snapshot")
        cursor.execute(
            f"""
            INSERT INTO {WEEKS}
              (organization_id, week_monday, status, revision, published_snapshot, published_revision)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              status=VALUES(status),
              revision=VALUES(revision),
              published_snapshot=VALUES(published_snapshot),
              published_revision=VALUES(published_revision)
            """,
            (
                org,
                key,
                status.get("status") or "draft",
                int(status.get("revision") or 1),
                json.dumps(snapshot) if isinstance(snapshot, Mapping) else None,
                status.get("published_revision"),
            ),
        )
    if audit:
        cursor.execute(
            f"INSERT INTO {AUDIT} (organization_id, actor_id, detail_json) VALUES (%s,%s,%s)",
            (org, actor_id, json.dumps(audit, default=str)),
        )


def _entry_rows(cursor, organization_id: int, storage_week: date, user_id: int, day_of_week: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT id, start_time, end_time
        FROM planned_weekly_schedule_entries
        WHERE organization_id=%s AND week_start=%s AND user_id=%s AND day_of_week=%s
        ORDER BY id
        """,
        (int(organization_id), storage_week, int(user_id), int(day_of_week)),
    )
    return [row for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def planner_shift_assignments(shift: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Turn planner segments into weekly-schedule assignments without inventing ranges.

    A role named on the shift but missing from the stored segments stays a full-shift
    placeholder. Weekly schedule persistence skips those placeholders, so the combined
    label is kept and the unallocated hours are not written as the first role.
    """
    from backend.planned_weekly_schedule import parse_weekly_roles

    timed: dict[str, list[dict[str, Any]]] = {}
    for item in shift.get("role_assignments") or []:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip()
        if not role or item.get("full_shift") is True:
            continue
        start = item.get("start_time")
        end = item.get("end_time")
        if not start or not end:
            continue
        timed.setdefault(role, []).append(
            {"role": role, "start_time": start, "end_time": end, "full_shift": False}
        )
    roles = parse_weekly_roles(shift.get("role")) or list(timed)
    ordered: list[dict[str, Any]] = []
    for role in roles:
        pieces = timed.pop(role, None)
        if pieces:
            ordered.extend(sorted(pieces, key=lambda piece: str(piece.get("start_time"))))
        else:
            ordered.append({"role": role, "full_shift": True})
    for pieces in timed.values():
        ordered.extend(pieces)
    return ordered


def _shift_row(cursor, organization_id: int, entry_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id, user_id, day_of_week, role, start_time, end_time, break_minutes, break_slots
        FROM planned_weekly_schedule_entries
        WHERE organization_id=%s AND id=%s
        """,
        (int(organization_id), int(entry_id)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def _same_clock(stored: Any, expected: Any) -> bool:
    return _clock_text(stored) == _clock_text(expected)


def materialize_shift_set(
    conn,
    cursor,
    organization_id: int,
    monday: date,
    operations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Write every named half, or raise so the caller rolls the whole save back.

    An update changes only that id. A create inserts a new id. A delete removes
    only that id. Any other shift for the same employee and day stays as stored.
    """
    from backend.operations_planner_v2 import plan_shift_set
    from backend.planned_weekly_schedule import create_entry, delete_entry, update_entry

    planned = plan_shift_set(operations)
    if not planned.get("ok"):
        raise ValueError(planned.get("error") or "could not save the shifts")
    created: list[int] = []
    updated: list[int] = []
    deleted: list[int] = []
    for decision in planned["decisions"]:
        action = decision["action"]
        if action == "delete":
            entry_id = int(decision["entry_id"])
            before = _shift_row(cursor, organization_id, entry_id)
            if before is None:
                raise ValueError(f"shift {entry_id} was not saved")
            if not delete_entry(cursor, organization_id, entry_id):
                raise ValueError(f"shift {entry_id} was not saved")
            if _shift_row(cursor, organization_id, entry_id) is not None:
                raise ValueError(f"shift {entry_id} was not saved")
            deleted.append(entry_id)
            continue
        shift = dict(decision.get("shift") or {})
        user_id = int(decision["user_id"])
        day = int(decision["day_of_week"])
        shift["user_id"] = user_id
        shift["day_of_week"] = day
        if "assignments" not in shift and "role_assignments" in shift:
            shift["assignments"] = planner_shift_assignments(shift)
        if action == "update":
            entry_id = int(decision["entry_id"])
            if _shift_row(cursor, organization_id, entry_id) is None:
                raise ValueError(f"shift {entry_id} was not saved")
            saved, err = update_entry(conn, cursor, organization_id, entry_id, shift)
            if err or not saved:
                raise ValueError(err or f"shift {entry_id} was not saved")
            row = _shift_row(cursor, organization_id, entry_id)
            if (
                row is None
                or not _same_clock(row.get("start_time"), shift.get("start_time"))
                or not _same_clock(row.get("end_time"), shift.get("end_time"))
            ):
                raise ValueError(f"shift {entry_id} was not saved")
            updated.append(entry_id)
            continue
        storage = storage_week_for_dow(monday, day)
        saved, err = create_entry(conn, cursor, organization_id, week_start=storage, data=shift)
        if err or not saved or not saved.get("id"):
            raise ValueError(err or "the new shift was not saved")
        entry_id = int(saved["id"])
        row = _shift_row(cursor, organization_id, entry_id)
        if (
            row is None
            or int(row.get("user_id") or 0) != user_id
            or int(row.get("day_of_week") or -1) != day
            or not _same_clock(row.get("start_time"), shift.get("start_time"))
            or not _same_clock(row.get("end_time"), shift.get("end_time"))
        ):
            raise ValueError("the new shift was not saved")
        created.append(entry_id)
    expected_creates = sum(1 for item in planned["decisions"] if item["action"] == "create")
    expected_updates = sum(1 for item in planned["decisions"] if item["action"] == "update")
    expected_deletes = sum(1 for item in planned["decisions"] if item["action"] == "delete")
    if (len(created), len(updated), len(deleted)) != (expected_creates, expected_updates, expected_deletes):
        raise ValueError("a split half was not saved")
    if len(set(created)) != len(created):
        raise ValueError("a split half was not saved")
    return {"created_ids": created, "updated_ids": updated, "deleted_ids": deleted}


def _replace_cell_shifts(conn, cursor, organization_id: int, storage: date, user_id: int, day: int, shifts: Sequence[Mapping[str, Any]]) -> None:
    """Write every shift on one employee-day. Extra stored rows are removed. Missing rows are created."""
    from backend.planned_weekly_schedule import create_entry, delete_entry, update_entry

    existing = _entry_rows(cursor, organization_id, storage, user_id, day)
    for index, shift in enumerate(shifts):
        body = dict(shift)
        body["user_id"] = user_id
        body["day_of_week"] = day
        if "assignments" not in body and "role_assignments" in body:
            body["assignments"] = planner_shift_assignments(body)
        if index < len(existing):
            updated, err = update_entry(conn, cursor, organization_id, int(existing[index]["id"]), body)
            if err or not updated:
                raise ValueError(err or "could not update the shift")
            continue
        created, err = create_entry(conn, cursor, organization_id, week_start=storage, data=body)
        if err or not created:
            raise ValueError(err or "could not create the shift")
    for row in existing[len(list(shifts)) :]:
        if not delete_entry(cursor, organization_id, int(row["id"])):
            raise ValueError("could not remove the extra shift")


def materialize_plans(conn, cursor, organization_id: int, plans: list[Mapping[str, Any]]) -> None:
    """Write planned entries for the cells a confirmed change named."""
    from backend.planned_weekly_schedule import create_entry, delete_entry, update_entry

    require_schema(cursor)
    for plan in plans:
        monday = parse_schedule_date(plan.get("week_monday"))
        if monday is None:
            raise ValueError("week_monday is required")
        user_id = int(plan["user_id"])
        day = int(plan["day_of_week"])
        storage = storage_week_for_dow(monday, day)
        existing = _entry_rows(cursor, organization_id, storage, user_id, day)
        if isinstance(plan.get("shifts"), list):
            _replace_cell_shifts(conn, cursor, organization_id, storage, user_id, day, plan.get("shifts") or [])
            continue
        decision = plan_entry_write(existing, plan.get("shift"))
        if not decision.get("ok"):
            raise ValueError(decision.get("error") or "could not update the shift")
        action = decision.get("action")
        entry_id = decision.get("entry_id")
        if action == "delete" and entry_id:
            delete_entry(cursor, organization_id, int(entry_id))
            entry_id = None
        elif action in ("create", "update"):
            body = dict(plan.get("shift") or {})
            if "assignments" not in body and "role_assignments" in body:
                body["assignments"] = planner_shift_assignments(body)
            body["user_id"] = user_id
            body["day_of_week"] = day
            if action == "create":
                created, err = create_entry(conn, cursor, organization_id, week_start=storage, data=body)
                if err or not created:
                    raise ValueError(err or "could not create the shift")
                entry_id = created.get("id")
            else:
                updated, err = update_entry(conn, cursor, organization_id, int(entry_id), body)
                if err or not updated:
                    raise ValueError(err or "could not update the shift")
        cursor.execute(
            f"""
            INSERT INTO {LINKS} (organization_id, week_monday, user_id, day_of_week, entry_id)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE entry_id=VALUES(entry_id)
            """,
            (int(organization_id), monday, user_id, day, entry_id),
        )
        shift = plan.get("shift") or {}
        if isinstance(shift, Mapping) and shift.get("tasks") is not None:
            _sync_cell_tasks(
                conn,
                cursor,
                organization_id,
                storage_week=storage,
                user_id=user_id,
                day_of_week=day,
                tasks=shift.get("tasks") or [],
            )


def _sync_cell_tasks(conn, cursor, organization_id: int, *, storage_week: date, user_id: int, day_of_week: int, tasks: list) -> list[str]:
    """Create or remove responsibility rows. Rows with execution history stay.

    The existing task table is not created from the planner. A missing table
    stops the save instead of issuing CREATE TABLE.
    """
    if not table_exists(cursor, "planned_weekly_schedule_responsibilities"):
        raise ValueError("the existing task table is not provisioned; the planner will not create it")
    from backend.planned_weekly_schedule_responsibilities import (
        annotate_responsibility_activity,
        create_responsibility,
        delete_responsibility,
        list_week_responsibilities,
    )

    existing = [
        item
        for item in list_week_responsibilities(cursor, organization_id, week_start=storage_week)
        if int(item.get("user_id") or 0) == int(user_id) and int(item.get("day_of_week") or -1) == int(day_of_week)
    ]
    existing = annotate_responsibility_activity(cursor, organization_id, existing)
    decision = plan_task_links(existing, tasks)
    warnings: list[str] = []
    for row in decision["preserved_history"]:
        warnings.append(f"{row.get('role')} keeps its completion history")
    for row in decision["remove"]:
        delete_responsibility(cursor, organization_id, int(row["id"]))
    for spec in decision["add"]:
        members = [int(uid) for uid in (spec.get("user_ids") or [])] or [int(user_id)]
        if int(user_id) not in members:
            members.append(int(user_id))
        _created, err = create_responsibility(
            conn,
            cursor,
            organization_id,
            week_start=storage_week,
            data={
                "user_ids": members,
                "day_of_week": int(day_of_week),
                "role": spec.get("role"),
                "remarks": spec.get("remarks") or "",
                "timing_mode": spec.get("timing_mode") or "anytime",
                "start_time": spec.get("start_time"),
                "execution_mode": spec.get("execution_mode") or "individual",
            },
        )
        if err and "already has that task" in str(err):
            continue
        if err:
            raise ValueError(err)
    return warnings


def legacy_template_enabled(cursor, organization_id: int) -> bool:
    if not table_exists(cursor, "weekly_schedule_org_state"):
        return False
    cursor.execute(
        """
        SELECT template_enabled FROM weekly_schedule_org_state
        WHERE organization_id=%s LIMIT 1
        """,
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict):
        return False
    return bool(row.get("template_enabled"))


def stop_legacy_template(cursor, organization_id: int, actor_id: int | None) -> None:
    if not table_exists(cursor, "weekly_schedule_org_state"):
        return
    cursor.execute(
        """
        UPDATE weekly_schedule_org_state
        SET template_enabled=0, template_updated_at=UTC_TIMESTAMP(), template_updated_by=%s
        WHERE organization_id=%s
        """,
        (actor_id, int(organization_id)),
    )


def load_access(cursor, organization_id: int, user_id: int) -> dict[str, bool]:
    require_schema(cursor)
    cursor.execute(
        f"""
        SELECT schedule_enabled, hours_enabled, paystub_enabled
        FROM {ACCESS} WHERE organization_id=%s AND user_id=%s
        """,
        (int(organization_id), int(user_id)),
    )
    row = cursor.fetchone() or {}
    if not isinstance(row, dict):
        row = {}
    return {
        "schedule_enabled": bool(row.get("schedule_enabled")),
        "hours_enabled": bool(row.get("hours_enabled")),
        "paystub_enabled": bool(row.get("paystub_enabled")),
    }


def save_access(cursor, organization_id: int, user_id: int, access: Mapping[str, Any], actor_id: int | None) -> dict[str, bool]:
    current = load_access(cursor, organization_id, user_id)
    for key in ("schedule_enabled", "hours_enabled", "paystub_enabled"):
        if key in access:
            current[key] = bool(access.get(key))
    cursor.execute(
        f"""
        INSERT INTO {ACCESS}
          (organization_id, user_id, schedule_enabled, hours_enabled, paystub_enabled, updated_by, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
          schedule_enabled=VALUES(schedule_enabled),
          hours_enabled=VALUES(hours_enabled),
          paystub_enabled=VALUES(paystub_enabled),
          updated_by=VALUES(updated_by),
          updated_at=UTC_TIMESTAMP()
        """,
        (
            int(organization_id),
            int(user_id),
            1 if current["schedule_enabled"] else 0,
            1 if current["hours_enabled"] else 0,
            1 if current["paystub_enabled"] else 0,
            actor_id,
        ),
    )
    return current


def load_role_settings(cursor, organization_id: int) -> list[dict[str, Any]]:
    require_schema(cursor)
    cursor.execute(
        f"""
        SELECT role_key, show_on_rinse_dashboard, required_headcount
        FROM {ROLES} WHERE organization_id=%s ORDER BY role_key
        """,
        (int(organization_id),),
    )
    rows = []
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            rows.append(
                {
                    "role": row.get("role_key"),
                    "show_on_rinse_dashboard": bool(row.get("show_on_rinse_dashboard")),
                    "required_headcount": row.get("required_headcount"),
                    "hourly_headcount": {},
                }
            )
    cursor.execute(
        f"""
        SELECT role_key, hour_of_day, required_headcount
        FROM {HOURS} WHERE organization_id=%s
        """,
        (int(organization_id),),
    )
    by_role = {row["role"]: row for row in rows}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        target = by_role.get(row.get("role_key"))
        if target is None:
            continue
        target["hourly_headcount"][str(int(row.get("hour_of_day") or 0))] = row.get("required_headcount")
    return rows


def save_role_setting(cursor, organization_id: int, role: str, body: Mapping[str, Any]) -> None:
    require_schema(cursor)
    current = {row["role"]: row for row in load_role_settings(cursor, organization_id)}
    prior = current.get(role) or {"show_on_rinse_dashboard": False, "required_headcount": None, "hourly_headcount": {}}
    show = body.get("show_on_rinse_dashboard", prior["show_on_rinse_dashboard"])
    headcount = body.get("required_headcount", prior["required_headcount"])
    if headcount in ("", None):
        headcount = None
    else:
        headcount = int(headcount)
    cursor.execute(
        f"""
        INSERT INTO {ROLES} (organization_id, role_key, show_on_rinse_dashboard, required_headcount)
        VALUES (%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          show_on_rinse_dashboard=VALUES(show_on_rinse_dashboard),
          required_headcount=VALUES(required_headcount)
        """,
        (int(organization_id), role, 1 if show else 0, headcount),
    )
    if "hourly_headcount" in body and isinstance(body.get("hourly_headcount"), Mapping):
        cursor.execute(
            f"DELETE FROM {HOURS} WHERE organization_id=%s AND role_key=%s",
            (int(organization_id), role),
        )
        for hour, needed in body["hourly_headcount"].items():
            if needed in ("", None):
                continue
            cursor.execute(
                f"""
                INSERT INTO {HOURS} (organization_id, role_key, hour_of_day, required_headcount)
                VALUES (%s,%s,%s,%s)
                """,
                (int(organization_id), role, int(hour), int(needed)),
            )


def _clock_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "total_seconds") and not hasattr(value, "strftime"):
        total = int(value.total_seconds()) % (24 * 3600)
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def _require_clock(value: Any) -> str:
    text = _clock_text(value)
    if len(text) != 5 or text[2] != ":":
        raise StaffingRequirementError("A requirement needs a start and an end")
    return text


def normalize_staffing_requirement(item: Mapping[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or item.get("role_key") or "").strip()
    if not role:
        raise StaffingRequirementError("A requirement needs a role")
    head = item.get("required_headcount")
    if head is None or head == "":
        raise StaffingRequirementError(
            "An empty requirement is not zero. Enter a headcount or leave the interval unconfigured."
        )
    try:
        count = int(head)
    except (TypeError, ValueError) as exc:
        raise StaffingRequirementError("Headcount must be a whole number") from exc
    if count < 0:
        raise StaffingRequirementError("Headcount cannot be negative")
    raw_day = item.get("day_of_week")
    if raw_day in ("", None):
        day_value = None
    else:
        day_value = int(raw_day)
        if day_value < 0 or day_value > 6:
            raise StaffingRequirementError("Day must be 0–6 or empty for every day")
    return {
        "role": role,
        "day_of_week": day_value,
        "start_time": _require_clock(item.get("start_time")),
        "end_time": _require_clock(item.get("end_time")),
        "required_headcount": count,
    }


def load_staffing_requirements(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Missing table or missing rows means unconfigured, not zero staff."""
    if not table_exists(cursor, STAFFING):
        return []
    cursor.execute(
        f"""
        SELECT id, role_key, day_of_week, start_time, end_time, required_headcount
        FROM {STAFFING} WHERE organization_id=%s
        ORDER BY role_key, day_of_week, start_time, id
        """,
        (int(organization_id),),
    )
    rows = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "id": row.get("id"),
                "role": row.get("role_key"),
                "day_of_week": row.get("day_of_week"),
                "start_time": _clock_text(row.get("start_time")),
                "end_time": _clock_text(row.get("end_time")),
                "required_headcount": row.get("required_headcount"),
            }
        )
    return rows


def _clock_minutes(value: str) -> int:
    hour, minute = str(value).split(":")
    return int(hour) * 60 + int(minute)


def reject_overlapping_staffing_requirements(items: Sequence[Mapping[str, Any]]) -> None:
    """Refuse two intervals for the same role that cover the same minute.

    An empty day means every day, so it conflicts with that role on any weekday.
    Intervals that only touch at an endpoint are kept.
    """
    normalized = [item for item in items if isinstance(item, Mapping)]
    for index, left in enumerate(normalized):
        left_day = left.get("day_of_week")
        left_start = _clock_minutes(str(left.get("start_time")))
        left_end = _clock_minutes(str(left.get("end_time")))
        for right in normalized[index + 1 :]:
            if str(left.get("role")) != str(right.get("role")):
                continue
            right_day = right.get("day_of_week")
            if left_day is not None and right_day is not None and int(left_day) != int(right_day):
                continue
            right_start = _clock_minutes(str(right.get("start_time")))
            right_end = _clock_minutes(str(right.get("end_time")))
            if left_start < right_end and right_start < left_end:
                raise StaffingRequirementError(
                    "Overlapping staffing intervals for the same role must be resolved before saving."
                )


def replace_staffing_requirements(cursor, organization_id: int, items: Any) -> list[dict[str, Any]]:
    if not table_exists(cursor, STAFFING):
        raise PlannerSchemaNotApplied([STAFFING])
    normalized = [normalize_staffing_requirement(item) for item in (items or [])]
    reject_overlapping_staffing_requirements(normalized)
    cursor.execute(f"DELETE FROM {STAFFING} WHERE organization_id=%s", (int(organization_id),))
    for item in normalized:
        cursor.execute(
            f"""
            INSERT INTO {STAFFING}
              (organization_id, role_key, day_of_week, start_time, end_time, required_headcount)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                item["role"],
                item["day_of_week"],
                item["start_time"],
                item["end_time"],
                item["required_headcount"],
            ),
        )
    return load_staffing_requirements(cursor, organization_id)


def _activity_status(cursor, organization_id: int, responsibility_id: int) -> str:
    if not table_exists(cursor, ACTIVITIES):
        return ""
    cursor.execute(
        f"""
        SELECT status FROM {ACTIVITIES}
        WHERE organization_id=%s AND responsibility_id=%s
        """,
        (int(organization_id), int(responsibility_id)),
    )
    statuses = []
    for row in cursor.fetchall() or []:
        statuses.append(str((row.get("status") if isinstance(row, dict) else row[0]) or ""))
    for locked in ("completed", "approved", "pending_approval", "rejected", "in_progress"):
        if locked in statuses:
            return locked
    return statuses[0] if statuses else ""


def load_assignment_rows(cursor, organization_id: int, week_start: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, RESPONSIBILITIES):
        return []
    cursor.execute(
        f"""
        SELECT id, user_id, day_of_week, role, remarks, assignment_group_id
        FROM {RESPONSIBILITIES}
        WHERE organization_id=%s AND week_start=%s
        ORDER BY id
        """,
        (int(organization_id), week_start),
    )
    rows = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["activity_status"] = _activity_status(cursor, organization_id, int(item["id"]))
        rows.append(item)
    return rows


def _assignment_week_keys(week_monday: date) -> tuple[date, ...]:
    """Storage Sundays for the display week, plus the Monday key used by the bad task insert."""
    from backend.weekly_schedule_week import display_week_storage

    mon_sat, sunday = display_week_storage(week_monday)
    keys = [mon_sat, sunday]
    if week_monday not in keys:
        keys.append(week_monday)
    return tuple(keys)


def add_assignments(cursor, organization_id: int, week_start: date, additions: Any) -> dict[str, Any]:
    """Insert new assignment rows on the same storage week as the schedule.

    ``week_start`` is the display Monday. Monday–Saturday tasks are stored on the
    Sunday before that Monday. Writing the Monday itself hides the row from the
    week reload. Existing rows, including completed history, are not removed.
    """
    if not table_exists(cursor, RESPONSIBILITIES):
        raise PlannerSchemaNotApplied([RESPONSIBILITIES])
    existing: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for key in _assignment_week_keys(week_start):
        for row in load_assignment_rows(cursor, organization_id, key):
            row_id = int(row.get("id") or 0)
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            existing.append(row)
    locked_groups = {
        str(row.get("assignment_group_id"))
        for row in existing
        if row.get("assignment_group_id")
        and str(row.get("activity_status") or row.get("status") or "") in ACTIVITY_LOCKED
    }
    safe = []
    refused = 0
    for item in additions or []:
        group = str(item.get("assignment_group_id") or "")
        if group and group in locked_groups:
            refused += 1
            continue
        safe.append(item)
    desired = [
        {
            "user_id": row.get("user_id"),
            "day_of_week": row.get("day_of_week"),
            "role": row.get("role"),
            "assignment_group_id": row.get("assignment_group_id"),
        }
        for row in existing
    ] + safe
    plan = plan_assignment_draft(existing, desired)
    inserted = []
    for item in plan["add"]:
        group = item.get("assignment_group_id") or None
        if item.get("shared") and not group:
            group = uuid.uuid4().hex
        if group and str(group) in locked_groups:
            refused += 1
            continue
        mode = str(item.get("timing_mode") or "anytime")
        start = item.get("start_time") if mode == "specific_time" else None
        end = item.get("end_time") if mode == "specific_time" else None
        execution = "shared" if item.get("shared") or item.get("execution_mode") == "shared" else "individual"
        storage = storage_week_for_dow(week_start, int(item["day_of_week"]))
        from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table

        ensure_responsibilities_table(cursor)
        cursor.execute(
            f"""
            INSERT INTO {RESPONSIBILITIES} (
              organization_id, week_start, user_id, day_of_week, role, remarks,
              assignment_group_id, timing_mode, start_time, end_time, execution_mode
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                storage,
                int(item["user_id"]),
                int(item["day_of_week"]),
                str(item.get("role") or "")[:40],
                None,
                group,
                mode,
                start,
                end,
                execution,
            ),
        )
        inserted.append(int(cursor.lastrowid or 0))
    return {
        "inserted": len(inserted),
        "inserted_ids": inserted,
        "preserved_history": [
            row.get("id")
            for row in existing
            if str(row.get("activity_status") or row.get("status") or "") in ACTIVITY_LOCKED
        ],
        "refused_groups": refused,
        "removed": 0,
    }


def _fingerprint_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
    return str(value)


def schedule_fingerprint(cursor, organization_id: int, monday: date) -> str:
    """Identity of the stored shifts for a Monday–Sunday week. A mismatch means another save landed first."""
    import hashlib

    rows: list[dict[str, Any]] = []
    for dow in (1, 2, 3, 4, 5, 6, 0):
        storage = storage_week_for_dow(monday, dow)
        cursor.execute(
            """
            SELECT id, user_id, day_of_week, start_time, end_time, role, break_minutes, role_assignments, break_slots
            FROM planned_weekly_schedule_entries
            WHERE organization_id=%s AND week_start=%s AND day_of_week=%s
            ORDER BY id
            """,
            (int(organization_id), storage, dow),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "id": int(row["id"]),
                    "user_id": int(row["user_id"]),
                    "day": int(row["day_of_week"]),
                    "start": _clock_text(row.get("start_time")),
                    "end": _clock_text(row.get("end_time")),
                    "role": row.get("role") or "",
                    "break": int(row.get("break_minutes") or 0),
                    "roles": _fingerprint_text(row.get("role_assignments")),
                    "breaks": _fingerprint_text(row.get("break_slots")),
                }
            )
    raw = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def update_unlocked_assignment(cursor, organization_id: int, week_monday: date, item: Mapping[str, Any]) -> None:
    """Reschedule or reassign one task that has no execution history."""
    responsibility_id = int(item.get("id") or 0)
    status = _activity_status(cursor, organization_id, responsibility_id)
    if status in ACTIVITY_LOCKED:
        raise ValueError("This task already has execution history and was left unchanged.")
    day = int(item.get("day_of_week"))
    storage = storage_week_for_dow(week_monday, day)
    mode = str(item.get("timing_mode") or "anytime")
    start = item.get("start_time") if mode == "specific_time" else None
    end = item.get("end_time") if mode == "specific_time" else None
    from backend.planned_weekly_schedule_responsibilities import ensure_responsibilities_table

    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"""
        UPDATE {RESPONSIBILITIES}
           SET user_id=%s, day_of_week=%s, week_start=%s, role=%s, timing_mode=%s, start_time=%s, end_time=%s
         WHERE organization_id=%s AND id=%s
        """,
        (
            int(item.get("user_id") or 0),
            day,
            storage,
            str(item.get("role") or "")[:40],
            mode,
            start,
            end,
            int(organization_id),
            responsibility_id,
        ),
    )
    if not cursor.rowcount:
        raise ValueError("The task assignment was not found.")


def remove_unlocked_assignment(cursor, organization_id: int, responsibility_id: int) -> None:
    """Delete one assignment that has no execution history. Completed rows stay stored."""
    status = _activity_status(cursor, organization_id, int(responsibility_id))
    if status in ACTIVITY_LOCKED:
        raise ValueError("This task already has execution history and was left unchanged.")
    cursor.execute(
        f"DELETE FROM {RESPONSIBILITIES} WHERE organization_id=%s AND id=%s",
        (int(organization_id), int(responsibility_id)),
    )
    if not cursor.rowcount:
        raise ValueError("The task assignment was not found.")


def acquire_lock(cursor, organization_id: int) -> bool:
    cursor.execute("SELECT GET_LOCK(%s, 5) AS locked", (f"ops_planner_{int(organization_id)}",))
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("locked") or 0) == 1
    return bool(row and row[0])


def release_lock(cursor, organization_id: int) -> None:
    try:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (f"ops_planner_{int(organization_id)}",))
        cursor.fetchone()
    except Exception:
        return


def employee_pin_feature_allowed(conn, organization_id: int, user_id: int, feature_id: str) -> bool:
    """Default closed. Missing planner tables stay off so a PIN login does not migrate."""
    cursor = conn.cursor(dictionary=True)
    try:
        if not table_exists(cursor, FLAGS):
            return False
        flags = load_flags(cursor, organization_id)
        if feature_id == "my_paystubs":
            if not flags["paystub_access"] or not flags["employee_pilot"]:
                return False
        elif not flags["employee_pilot"]:
            return False
        access = load_access(cursor, organization_id, user_id)
        if feature_id == "my_schedule":
            return access["schedule_enabled"]
        if feature_id == "my_hours":
            return access["hours_enabled"]
        if feature_id == "my_paystubs":
            from backend.payroll_operations import worker_category_for_user

            if not access["paystub_enabled"]:
                return False
            return worker_category_for_user(conn, int(user_id)) == "w2"
        return False
    except Exception:
        return False
    finally:
        try:
            cursor.close()
        except Exception:
            pass
