"""Persistence for Operations Planner v2.

Schema is applied only by backend/sql/operations_planner_v2.sql.
Opening the planner, starting the app, or signing in with a PIN does not
create or alter tables. Historical attendance, punches, payroll, and task
completion rows are not rewritten from here.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping

from backend.operations_planner_v2 import empty_state, plan_entry_write, plan_task_links
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
PLANNER_TABLES = (FLAGS, PATTERNS, EXCEPTIONS, WEEKS, AUDIT, ACCESS, ROLES, HOURS, LINKS)
SCHEMA_VERSION = "operations_planner_v2.1"


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


def acquire_lock(cursor, organization_id: int) -> bool:
    cursor.execute("SELECT GET_LOCK(%s, 5) AS locked", (f"ops_planner_{int(organization_id)}",))
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("locked") or 0) == 1
    return bool(row and row[0])


def release_lock(cursor, organization_id: int) -> None:
    try:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (f"ops_planner_{int(organization_id)}",))
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
