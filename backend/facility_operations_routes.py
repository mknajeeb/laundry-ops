"""Machine register, cleaning exclusions, and recurring task occurrences.

These routes read and update the existing task and incident records. They do
not start a second task engine or a second incident form.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.facility_machines import (
    STATUSES,
    end_exclusion,
    exclude_machine,
    list_events,
    list_exclusions,
    list_machines,
    related_issue_reports,
    update_machine,
)
from backend.management_pin_access import HUB_ROLES
from backend.planned_weekly_schedule import normalize_week_start
from backend.task_catalog import list_task_definitions
from backend.task_recurrence import (
    generate_week,
    list_occurrences,
    machine_week_targets,
    reschedule_slot,
    skip_slot,
    weekly_task_progress,
)
from backend.task_recurrence import OCCURRENCES, MACHINE_CLEANINGS
from backend.facility_machines import EXCLUSIONS


def register_facility_operations_routes(app, *, require_user: Callable, user_org_id: Callable, fetch_user_roles: Callable):
    def _open():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        user, err_resp, err_code = require_user(cursor)
        if err_resp:
            conn.close()
            return None, None, None, None, (err_resp, err_code)
        org_id = user_org_id(user)
        roles = {str(role).upper() for role in (user.get("roles") or fetch_user_roles(cursor, user["id"]) or [])}
        return user, org_id, conn, cursor, roles

    def _manager(roles) -> bool:
        return bool(roles & HUB_ROLES)

    @app.route("/api/facility-machines", methods=["GET"])
    def facility_machines_list():
        opened = _open()
        if opened[4] is not None and opened[0] is None:
            return opened[4]
        _user, org_id, conn, cursor, _roles = opened
        try:
            machine_type = request.args.get("type")
            status = request.args.get("status")
            rows = list_machines(cursor, int(org_id), machine_type=machine_type, status=status)
            conn.commit()
            summary = {name: 0 for name in STATUSES}
            for row in rows:
                summary[row["operational_status"]] = summary.get(row["operational_status"], 0) + 1
            return jsonify({"ok": True, "machines": rows, "summary": summary, "can_update": _manager(_roles)})
        finally:
            conn.close()

    @app.route("/api/facility-machines/<machine_code>", methods=["GET"])
    def facility_machine_detail(machine_code: str):
        opened = _open()
        if opened[0] is None:
            return opened[4]
        _user, org_id, conn, cursor, roles = opened
        try:
            rows = list_machines(cursor, int(org_id))
            match = next((row for row in rows if row["machine_code"] == machine_code), None)
            if not match:
                return jsonify({"error": "Machine is not in the register"}), 404
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "machine": match,
                    "events": list_events(cursor, int(org_id), machine_code),
                    "exclusions": list_exclusions(cursor, int(org_id), machine_code),
                    "issues": related_issue_reports(cursor, int(org_id), machine_code),
                    "can_update": _manager(roles),
                }
            )
        finally:
            conn.close()

    @app.route("/api/facility-machines/<machine_code>", methods=["PATCH"])
    def facility_machine_update(machine_code: str):
        opened = _open()
        if opened[0] is None:
            return opened[4]
        user, org_id, conn, cursor, roles = opened
        if not _manager(roles):
            return jsonify({"error": "Forbidden"}), 403
        try:
            updated = update_machine(
                cursor,
                int(org_id),
                machine_code,
                request.json or {},
                actor_user_id=int(user["id"]),
            )
            conn.commit()
            return jsonify({"ok": True, "machine": updated})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/facility-machines/<machine_code>/exclusions", methods=["POST"])
    def facility_machine_exclude(machine_code: str):
        opened = _open()
        if opened[0] is None:
            return opened[4]
        user, org_id, conn, cursor, roles = opened
        if not _manager(roles):
            return jsonify({"error": "Forbidden"}), 403
        body = request.json or {}
        try:
            exclude_machine(
                cursor,
                int(org_id),
                machine_code,
                reason=str(body.get("reason") or ""),
                effective_start=str(body.get("effective_start") or business_today().isoformat()),
                effective_end=body.get("effective_end"),
                actor_user_id=int(user["id"]),
            )
            conn.commit()
            return jsonify({"ok": True})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/facility-machines/exclusions/<int:exclusion_id>/end", methods=["POST"])
    def facility_machine_end_exclusion(exclusion_id: int):
        opened = _open()
        if opened[0] is None:
            return opened[4]
        user, org_id, conn, cursor, roles = opened
        if not _manager(roles):
            return jsonify({"error": "Forbidden"}), 403
        end_exclusion(cursor, int(org_id), exclusion_id, actor_user_id=int(user["id"]))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/management/task-occurrences", methods=["GET", "POST"])
    def task_occurrences():
        opened = _open()
        if opened[0] is None:
            return opened[4]
        _user, org_id, conn, cursor, roles = opened
        if not _manager(roles):
            conn.close()
            return jsonify({"error": "Forbidden"}), 403
        body = request.json or {}
        week = normalize_week_start(
            request.args.get("week_start") or body.get("week_start") or business_today().isoformat()
        )
        try:
            tasks = list_task_definitions(cursor, int(org_id))
            if request.method == "POST" and body.get("action") not in ("skip", "reschedule"):
                from backend.task_recurrence import materialize_schedule_weeks

                materialize_schedule_weeks(cursor, int(org_id), week)
                generate_week(cursor, int(org_id), week, tasks)
                conn.commit()
            rows = list_occurrences(cursor, int(org_id), week)
            action = body.get("action") if request.method == "POST" else None
            if action in ("skip", "reschedule"):
                key = str(body.get("recurrence_key") or "")
                current = next((row for row in rows if row.get("recurrence_key") == key), None)
                if not current:
                    return jsonify({"error": "Occurrence not found"}), 404
                updated = skip_slot(current, body.get("reason") or "") if action == "skip" else reschedule_slot(current, int(body.get("day_of_week")), body.get("reason") or "")
                cursor.execute(
                    f"""
                    UPDATE {OCCURRENCES}
                    SET status=%s, day_of_week=%s, skip_reason=%s, schedule_reason=%s
                    WHERE organization_id=%s AND recurrence_key=%s
                      AND status NOT IN ('completed', 'verified')
                    """,
                    (
                        updated.get("status"),
                        updated.get("day_of_week"),
                        updated.get("skip_reason"),
                        updated.get("schedule_reason"),
                        int(org_id),
                        key,
                    ),
                )
                conn.commit()
                rows = list_occurrences(cursor, int(org_id), week)
            progress = []
            today = business_today()
            for task in tasks:
                rule = task.get("recurrence") or {}
                mine = [row for row in rows if row.get("task_code") == task.get("code")]
                if rule.get("mode") != "recurring" and not mine:
                    continue
                item = {
                    "task_code": task.get("code"),
                    "name": task.get("name"),
                    "recurrence": rule,
                    **weekly_task_progress(frequency=int(rule.get("weekly_frequency") or 1), occurrences=mine, today=today),
                }
                if task.get("code") in ("custom_washer_deep_cleaning", "custom_dryer_deep_cleaning"):
                    item["machines"] = _machine_progress(cursor, int(org_id), task.get("code"), int(rule.get("weekly_frequency") or 1), week)
                progress.append(item)
            return jsonify({"ok": True, "week_start": week.isoformat(), "occurrences": rows, "progress": progress})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()


def _machine_progress(cursor, organization_id: int, task_code: str, frequency: int, week: date):
    machines = list_machines(cursor, organization_id, machine_type="washer" if "washer" in task_code else "dryer")
    cursor.execute(
        f"SELECT machine_code, occurrence_key, user_id, verified FROM {MACHINE_CLEANINGS} WHERE organization_id=%s AND task_code=%s",
        (int(organization_id), task_code),
    )
    cleanings = [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]
    exclusions = list_exclusions(cursor, organization_id)
    return machine_week_targets(machines, cleanings, exclusions, frequency=frequency, week_start=week)
