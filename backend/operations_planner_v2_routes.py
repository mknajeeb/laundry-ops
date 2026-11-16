"""Operations Planner v2 HTTP API.

Manager routes require an operations login and the manager pilot flag.
Employee routes trust only a PIN hub token, then filter to that employee.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import Response, current_app, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.business_time import business_today
from backend.db import get_db
from backend.employee_pin_hub import verify_hub_session_token
from backend.operations_planner_v2 import (
    approve_weeks,
    commit_or_rollback,
    employee_module_visible,
    employee_schedule_view,
    employee_visible_snapshot,
    paystub_decision,
    plan_change,
    publish_weeks,
    shift_set_confirmation,
    role_visible_to_rinse,
    verify_personal_paystub_code,
    verify_step_up_factors,
)
from backend.operations_planner_v2_store import (
    acquire_lock,
    legacy_template_enabled,
    load_access,
    add_assignments,
    load_flags,
    load_role_settings,
    load_staffing_requirements,
    load_state,
    materialize_plans,
    materialize_shift_set,
    PaystubSecurityHold,
    PlannerSchemaNotApplied,
    release_lock,
    replace_staffing_requirements,
    StaffingRequirementError,
    save_access,
    save_flags,
    save_role_setting,
    save_state,
    stop_legacy_template,
)
from backend.ta_helpers import table_has_column
from backend.weekly_schedule_week import current_schedule_monday, parse_schedule_date

PAYSTUB_SALT = "ops-planner-paystub-v2"
PAYSTUB_MAX_AGE = 300
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _actor_id(me: dict) -> int | None:
    for key in ("user_id", "id"):
        try:
            value = int(me.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return None


def _monday_arg(raw: str | None) -> date | None:
    parsed = parse_schedule_date(raw)
    if parsed is None:
        return None
    return parsed - timedelta(days=parsed.weekday())


def _hub_identity() -> tuple[dict | None, tuple | None]:
    token = (
        request.headers.get("X-Pin-Hub-Token")
        or request.args.get("hub_token")
        or (request.get_json(silent=True) or {}).get("hub_token")
        or ""
    )
    try:
        data = verify_hub_session_token(str(token))
    except ValueError as exc:
        return None, (jsonify({"error": str(exc)}), 401)
    return data, None


def _step_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=PAYSTUB_SALT)


def _error_response(exc, *, rolled_back: bool = False):
    if isinstance(exc, PlannerSchemaNotApplied):
        return (
            jsonify(
                {
                    "code": "migration_required",
                    "missing": exc.missing,
                    "version": "operations_planner_v2.2",
                    "error": "Apply backend/sql/operations_planner_v2.sql. Opening the planner does not create tables.",
                }
            ),
            503,
        )
    if isinstance(exc, PaystubSecurityHold):
        return jsonify({"code": "paystub_security_hold", "error": str(exc)}), 409
    return jsonify({"error": str(exc), "rolled_back": rolled_back}), 500


def _no_store(response):
    for key, value in NO_STORE.items():
        response.headers[key] = value
    return response


def _worked_hours(conn, organization_id: int, user_id: int, start: date, end: date) -> dict:
    """Actual attendance hours for one employee. Clocks are Eastern wall times."""
    from backend.payroll_operations import list_time_records

    records = list_time_records(
        conn,
        int(organization_id),
        from_date=start.isoformat(),
        to_date=end.isoformat(),
        user_id=int(user_id),
        limit=500,
    )
    days = []
    total = 0.0
    overtime = None
    for record in records:
        if int(record.get("user_id") or 0) != int(user_id):
            continue
        approved = record.get("payroll_hours_approved")
        recorded = record.get("approved_hours")
        if approved in (True, 1, "1") and recorded not in (None, ""):
            hours = float(recorded)
            source = "approved"
        elif record.get("net_work_seconds") not in (None, ""):
            hours = round(float(record.get("net_work_seconds") or 0) / 3600.0, 4)
            source = "attendance"
        else:
            hours = round(float(recorded or 0), 4)
            source = "attendance"
        total += hours
        explicit = record.get("overtime_hours")
        if explicit not in (None, ""):
            overtime = float(overtime or 0) + float(explicit)
        clock = record.get("clock_in_at")
        days.append(
            {
                "clock_in_at": str(clock) if clock is not None else None,
                "hours": round(hours, 4),
                "source": source,
            }
        )
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "actual_hours": round(total, 4),
        "regular_hours": None if overtime is None else round(max(0.0, total - overtime), 4),
        "overtime_hours": None if overtime is None else round(overtime, 4),
        "overtime_note": None
        if overtime is not None
        else "Overtime is shown when the payroll record already splits it.",
        "days": days,
        "scheduled_hours": None,
    }


def register_operations_planner_v2_routes(
    app,
    *,
    require_user,
    require_admin,
    require_admin_or_ops,
    user_org_id,
) -> None:
    def _manager():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me, err, code = require_user(cursor)
        if err:
            cursor.close()
            conn.close()
            return None, None, None, (err, code)
        gate = require_admin_or_ops or require_admin
        _, err_gate, code_gate = gate(cursor)
        if err_gate:
            cursor.close()
            conn.close()
            return None, None, None, (err_gate, code_gate)
        return conn, cursor, me, None

    @app.route("/operations-planner/v2/status", methods=["GET"])
    def operations_planner_v2_status():
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            flags = load_flags(cursor, user_org_id(me))
            return jsonify({"flags": flags, "can_configure": True, "paystub_security_hold": True})
        except Exception as exc:
            return _error_response(exc)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/settings", methods=["PUT"])
    def operations_planner_v2_settings():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_user(cursor)
            if err:
                return err, code
            _, err_gate, code_gate = require_admin(cursor)
            if err_gate:
                return err_gate, code_gate
            flags = save_flags(cursor, user_org_id(me), request.get_json(silent=True) or {})
            conn.commit()
            return jsonify({"flags": flags})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/week", methods=["GET"])
    def operations_planner_v2_week():
        from backend.planned_weekly_schedule import build_week_payload

        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            org = user_org_id(me)
            flags = load_flags(cursor, org)
            if not flags["manager_pilot"]:
                return jsonify({"error": "Operations Planner pilot is off", "code": "manager_pilot_disabled", "flags": flags}), 403
            monday = _monday_arg(request.args.get("week_start")) or current_schedule_monday(business_today())
            payload = build_week_payload(
                conn, cursor, org, week_start=monday, user_roles=me.get("roles"), display_week=True
            )
            state = load_state(cursor, org)
            status = state["weeks"].get(monday.isoformat()) or {
                "status": "draft",
                "revision": 1,
                "published_revision": None,
            }
            hidden = set((payload.get("display") or {}).get("hidden_schedule_roles") or [])
            roles = []
            for row in load_role_settings(cursor, org):
                row["visible_to_rinse"] = role_visible_to_rinse(
                    str(row["role"]),
                    show_on_rinse_dashboard=row["show_on_rinse_dashboard"],
                    hidden_by_labor_policy=hidden,
                )
                roles.append(row)
            payload["planner"] = {
                "week_monday": monday.isoformat(),
                "status": status.get("status") or "draft",
                "revision": status.get("revision") or 1,
                "published_revision": status.get("published_revision"),
                "flags": flags,
                "legacy_template": legacy_template_enabled(cursor, org),
                "role_settings": roles,
                "staffing_requirements": load_staffing_requirements(cursor, org),
            }
            return jsonify(payload)
        except Exception as exc:
            return _error_response(exc)
        finally:
            cursor.close()
            conn.close()

    def _termination(cursor, user_id: int):
        if not table_has_column(cursor, "users", "termination_date"):
            return None
        cursor.execute("SELECT termination_date FROM users WHERE id=%s", (int(user_id),))
        row = cursor.fetchone() or {}
        raw = row.get("termination_date") if isinstance(row, dict) else None
        if raw is None or raw == "":
            return None
        return raw.isoformat() if hasattr(raw, "isoformat") else str(raw)[:10]

    def _command(body: dict, org: int, cursor) -> dict:
        command = dict(body)
        command["today"] = business_today()
        command.setdefault("anchor", body.get("week_start"))
        ids = command.get("user_ids") or ([command.get("user_id")] if command.get("user_id") else [])
        if not command.get("employment_end") and len(ids) == 1:
            try:
                command["employment_end"] = _termination(cursor, int(ids[0]))
            except (TypeError, ValueError):
                command["employment_end"] = None
        return command

    @app.route("/operations-planner/v2/preview", methods=["POST"])
    def operations_planner_v2_preview():
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            org = user_org_id(me)
            flags = load_flags(cursor, org)
            if not flags["manager_pilot"]:
                return jsonify({"error": "Operations Planner pilot is off", "code": "manager_pilot_disabled"}), 403
            body = request.get_json(silent=True) or {}
            if str(body.get("action") or "") == "apply_shift_set":
                monday = _monday_arg(body.get("week_start") or body.get("anchor"))
                if monday is None:
                    return jsonify({"ok": False, "error": "week_start is required"}), 400
                operations = body.get("operations") or []
                return jsonify(
                    {
                        "ok": True,
                        "preview": {
                            "dates": [monday.isoformat()],
                            "operations": [
                                {
                                    "op": item.get("op"),
                                    "id": item.get("id"),
                                    "user_id": item.get("user_id"),
                                    "day_of_week": item.get("day_of_week"),
                                    "start_time": (item.get("shift") or {}).get("start_time"),
                                    "end_time": (item.get("shift") or {}).get("end_time"),
                                    "role": (item.get("shift") or {}).get("role"),
                                }
                                for item in operations
                                if isinstance(item, dict)
                            ],
                        },
                    }
                )
            result = plan_change(load_state(cursor, org), _command(body, org, cursor))
            result.pop("state", None)
            result["legacy_template"] = legacy_template_enabled(cursor, org)
            code = 200 if result.get("ok") else 409
            return jsonify(result), code
        except Exception as exc:
            return _error_response(exc)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/apply", methods=["POST"])
    def operations_planner_v2_apply():
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        org = user_org_id(me)
        actor = _actor_id(me)
        body = request.get_json(silent=True) or {}
        try:
            flags = load_flags(cursor, org)
            if not flags["manager_pilot"]:
                return jsonify({"error": "Operations Planner pilot is off", "code": "manager_pilot_disabled"}), 403
            if not acquire_lock(cursor, org):
                return jsonify({"error": "Another manager is saving this schedule", "code": "busy"}), 409
            try:
                if str(body.get("action") or "") == "apply_shift_set":
                    monday = _monday_arg(body.get("week_start") or body.get("anchor"))
                    if monday is None:
                        return jsonify({"ok": False, "error": "week_start is required"}), 400
                    if str(body.get("scope") or "this_week") != "this_week":
                        return jsonify(
                            {
                                "ok": False,
                                "code": "invalid_action",
                                "error": "Saving more than one shift applies to this week. Choose this week.",
                            }
                        ), 409
                    state = load_state(cursor, org)
                    gate = shift_set_confirmation(state, monday, body.get("include_published"))
                    if not gate.get("ok"):
                        gate["preview"] = {"dates": [monday.isoformat()], "approved_or_published_weeks": [monday.isoformat()] if gate.get("code") == "confirmation_required" else []}
                        return jsonify(gate), 409
                    status = gate["status"]

                    def _write_shift_set():
                        written = materialize_shift_set(conn, cursor, org, monday, body.get("operations") or [])
                        if status["status"] in ("approved", "published"):
                            weeks = state.setdefault("weeks", {})
                            weeks[monday.isoformat()] = {
                                **status,
                                "status": "draft",
                                "revision": int(status["revision"]) + 1,
                            }
                            save_state(cursor, org, state, {"action": "apply_shift_set", "week": monday.isoformat()}, actor)
                        return written

                    outcome = commit_or_rollback(_write_shift_set, conn.commit, conn.rollback)
                    if not outcome["ok"]:
                        return jsonify({"ok": False, "code": "rolled_back", "rolled_back": True, "error": outcome["error"]}), 409
                    result = outcome.get("result") or {}
                    return jsonify({"ok": True, **result, "republish_required": [monday.isoformat()] if status["status"] in ("approved", "published") else []})
                result = plan_change(load_state(cursor, org), _command(body, org, cursor))
                if not result.get("ok"):
                    result.pop("state", None)
                    return jsonify(result), 409
                if legacy_template_enabled(cursor, org) and not body.get("stop_legacy_template"):
                    return jsonify(
                        {
                            "ok": False,
                            "code": "legacy_template_active",
                            "error": "Stop the old week-to-week template before saving a recurring change.",
                            "preview": result.get("preview"),
                        }
                    ), 409
                if body.get("stop_legacy_template"):
                    stop_legacy_template(cursor, org, actor)
                outcome = commit_or_rollback(
                    lambda: (
                        save_state(cursor, org, result["state"], result.get("audit"), actor),
                        materialize_plans(conn, cursor, org, result.get("cell_plans") or []),
                    ),
                    conn.commit,
                    conn.rollback,
                )
                if not outcome["ok"]:
                    return jsonify({"ok": False, "code": "rolled_back", "rolled_back": True, "error": outcome["error"]}), 409
            finally:
                release_lock(cursor, org)
            return jsonify(
                {
                    "ok": True,
                    "write_weeks": result.get("write_weeks"),
                    "frozen_weeks": result.get("frozen_weeks"),
                    "republish_required": result.get("republish_required"),
                    "warnings": result.get("warnings"),
                    "preview": result.get("preview"),
                }
            )
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    def _lifecycle(kind: str):
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        org = user_org_id(me)
        body = request.get_json(silent=True) or {}
        weeks = body.get("weeks") or []
        try:
            flags = load_flags(cursor, org)
            if not flags["manager_pilot"]:
                return jsonify({"error": "Operations Planner pilot is off", "code": "manager_pilot_disabled"}), 403
            if not acquire_lock(cursor, org):
                return jsonify({"error": "Another manager is saving this schedule", "code": "busy"}), 409
            try:
                state = load_state(cursor, org)
                if kind == "approve":
                    result = approve_weeks(state, weeks)
                else:
                    from backend.planned_weekly_schedule import build_week_payload

                    snapshots = {}
                    for raw in weeks:
                        monday = _monday_arg(str(raw))
                        if monday is None:
                            continue
                        payload = build_week_payload(
                            conn,
                            cursor,
                            org,
                            week_start=monday,
                            user_roles=me.get("roles"),
                            display_week=True,
                        )
                        snapshots[monday.isoformat()] = {
                            "week_start": monday.isoformat(),
                            "entries": payload.get("entries") or [],
                            "daily_responsibilities": payload.get("daily_responsibilities") or [],
                        }
                    result = publish_weeks(state, weeks, snapshots)
                if not result.get("ok"):
                    return jsonify(result), 409
                save_state(cursor, org, result["state"], {"action": kind, "weeks": result.get("weeks")}, _actor_id(me))
                conn.commit()
            finally:
                release_lock(cursor, org)
            return jsonify({"ok": True, "weeks": result.get("weeks")})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/weeks/approve", methods=["POST"])
    def operations_planner_v2_approve():
        return _lifecycle("approve")

    @app.route("/operations-planner/v2/weeks/publish", methods=["POST"])
    def operations_planner_v2_publish():
        return _lifecycle("publish")

    @app.route("/operations-planner/v2/employees/<int:user_id>/access", methods=["GET", "PUT"])
    def operations_planner_v2_access(user_id: int):
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            org = user_org_id(me)
            if request.method == "PUT":
                _, err_gate, code_gate = require_admin(cursor)
                if err_gate:
                    return err_gate, code_gate
                access = save_access(cursor, org, user_id, request.get_json(silent=True) or {}, _actor_id(me))
                conn.commit()
            else:
                access = load_access(cursor, org, user_id)
            return jsonify({"user_id": user_id, "access": access})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/staffing-requirements", methods=["PUT"])
    def operations_planner_v2_staffing():
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            _, err_gate, code_gate = require_admin(cursor)
            if err_gate:
                return err_gate, code_gate
            body = request.get_json(silent=True) or {}
            saved = replace_staffing_requirements(cursor, user_org_id(me), body.get("requirements") or [])
            conn.commit()
            return jsonify({"ok": True, "requirements": saved})
        except StaffingRequirementError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/task-assignments", methods=["POST"])
    def operations_planner_v2_task_assignments():
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            _, err_gate, code_gate = require_admin(cursor)
            if err_gate:
                return err_gate, code_gate
            body = request.get_json(silent=True) or {}
            monday = _monday_arg(body.get("week_start"))
            if monday is None:
                return jsonify({"error": "week_start is required"}), 400
            result = add_assignments(cursor, user_org_id(me), monday, body.get("tasks") or [])
            conn.commit()
            return jsonify({"ok": True, **result})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/operations-planner/v2/roles/<role_key>", methods=["PUT"])
    def operations_planner_v2_role(role_key: str):
        conn, cursor, me, denied = _manager()
        if denied:
            return denied
        try:
            _, err_gate, code_gate = require_admin(cursor)
            if err_gate:
                return err_gate, code_gate
            save_role_setting(cursor, user_org_id(me), role_key, request.get_json(silent=True) or {})
            conn.commit()
            return jsonify({"ok": True, "roles": load_role_settings(cursor, user_org_id(me))})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc, rolled_back=True)
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/attendance/pin-planner/schedule", methods=["GET"])
    def operations_planner_v2_my_schedule():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            identity, denied = _hub_identity()
            if denied:
                return _no_store(denied[0]), denied[1]
            org = int(identity["organization_id"])
            employee_id = int(identity["employee_id"])
            flags = load_flags(cursor, org)
            access = load_access(cursor, org, employee_id)
            monday = _monday_arg(request.args.get("week_start")) or current_schedule_monday(business_today())
            state = load_state(cursor, org)
            raw = employee_visible_snapshot(state, monday)
            filtered = employee_schedule_view(raw, employee_id) if raw else None
            decision = employee_module_visible(
                pilot_enabled=flags["employee_pilot"],
                employee_enabled=access["schedule_enabled"],
                published_snapshot=filtered,
            )
            published = []
            if decision["visible"]:
                for key, status in (state.get("weeks") or {}).items():
                    if isinstance(status, dict) and status.get("published_snapshot"):
                        published.append(key)
            return _no_store(
                jsonify(
                    {
                        "visible": decision["visible"],
                        "reason": decision["reason"],
                        "week_start": monday.isoformat(),
                        "schedule": decision.get("schedule") if decision["visible"] else None,
                        "published_weeks": sorted(published) if decision["visible"] else [],
                    }
                )
            )
        except Exception as exc:
            response, code = _error_response(exc)
            return _no_store(response), code
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/attendance/pin-planner/hours", methods=["GET"])
    def operations_planner_v2_my_hours():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            identity, denied = _hub_identity()
            if denied:
                return _no_store(denied[0]), denied[1]
            org = int(identity["organization_id"])
            employee_id = int(identity["employee_id"])
            flags = load_flags(cursor, org)
            access = load_access(cursor, org, employee_id)
            if not flags["employee_pilot"] or not access["hours_enabled"]:
                return _no_store(jsonify({"visible": False, "reason": "disabled"}))
            start = parse_schedule_date(request.args.get("from")) or current_schedule_monday(business_today())
            end = parse_schedule_date(request.args.get("to")) or (start + timedelta(days=6))
            if end < start:
                return _no_store(jsonify({"error": "to must be on or after from"})), 400
            payload = _worked_hours(conn, org, employee_id, start, end)
            payload["visible"] = True
            payload["scheduled_hours_note"] = "Scheduled hours are a plan. These figures are recorded attendance."
            return _no_store(jsonify(payload))
        except Exception as exc:
            response, code = _error_response(exc)
            return _no_store(response), code
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/attendance/pin-planner/paystub/step-up", methods=["POST"])
    def operations_planner_v2_paystub_step_up():
        from backend.attendance_pin_punch import record_pin_attempt, resolve_user_by_attendance_pin
        from backend.payroll_operations import worker_category_for_user

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            identity, denied = _hub_identity()
            if denied:
                return _no_store(denied[0]), denied[1]
            org = int(identity["organization_id"])
            employee_id = int(identity["employee_id"])
            flags = load_flags(cursor, org)
            access = load_access(cursor, org, employee_id)
            if not flags["paystub_access"]:
                return _no_store(jsonify({
                    "ok": False,
                    "code": "module_disabled",
                    "error": "Paystub access stays off until a separate security review.",
                })), 403
            category = worker_category_for_user(conn, employee_id)
            body = request.get_json(silent=True) or {}
            dob = parse_schedule_date(body.get("date_of_birth"))
            on_file = None
            try:
                cursor.execute(
                    """
                    SELECT date_of_birth FROM hr_extended_profiles
                    WHERE organization_id=%s AND user_id=%s LIMIT 1
                    """,
                    (org, employee_id),
                )
                row = cursor.fetchone() or {}
            except Exception:
                row = {}
            if isinstance(row, dict):
                raw_dob = row.get("date_of_birth")
                on_file = raw_dob.date() if hasattr(raw_dob, "date") and not isinstance(raw_dob, date) else raw_dob
                if isinstance(on_file, str):
                    on_file = parse_schedule_date(on_file)
            matched = resolve_user_by_attendance_pin(conn, org, str(body.get("pin") or ""), lambda _c, _u: [])
            pin_ok = bool(matched) and int(matched["id"]) == employee_id
            supplied_code = str(body.get("personal_code") or "").strip()
            if body.get("date_of_birth") and not supplied_code:
                ok, reason = False, "dob_not_accepted"
                code_on_file = False
            else:
                stored = {}
                try:
                    cursor.execute(
                        """
                        SELECT user_id, code_hash, expires_at, used_at
                        FROM ops_planner_paystub_codes
                        WHERE organization_id=%s AND user_id=%s
                        ORDER BY id DESC LIMIT 1
                        """,
                        (org, employee_id),
                    )
                    stored = cursor.fetchone() or {}
                except Exception:
                    stored = {}
                if not isinstance(stored, dict):
                    stored = {}
                expires = stored.get("expires_at")
                expired = bool(expires and hasattr(expires, "timestamp") and expires.timestamp() < __import__("time").time())
                ok, reason = verify_personal_paystub_code(
                    supplied=supplied_code,
                    stored_hash=stored.get("code_hash"),
                    employee_id=employee_id,
                    stored_employee_id=int(stored.get("user_id") or 0),
                    used=stored.get("used_at") is not None,
                    expired=expired,
                )
                ok = bool(ok and pin_ok)
                if not pin_ok and reason == "ok":
                    ok, reason = False, "verification_failed"
                code_on_file = bool(stored.get("code_hash"))
            if not flags["paystub_access"]:
                ok, reason = False, "module_disabled"
            decision = paystub_decision(
                module_enabled=flags["paystub_access"],
                employee_enabled=access["paystub_enabled"],
                worker_category=category,
                step_up_ok=ok,
                second_factor_on_file=code_on_file if flags["paystub_access"] else False,
                document_available=True,
            )
            if decision != "ok" or not ok:
                try:
                    record_pin_attempt(conn, org, request.remote_addr or "", False)
                    conn.commit()
                except Exception:
                    conn.rollback()
                message = "Verification failed" if reason == "verification_failed" else reason
                return _no_store(jsonify({"ok": False, "code": decision if decision != "ok" else reason, "error": message})), 403
            token = _step_serializer().dumps(
                {"purpose": "paystub_step_up", "organization_id": org, "employee_id": employee_id}
            )
            return _no_store(jsonify({"ok": True, "step_up_token": token, "expires_in": PAYSTUB_MAX_AGE}))
        finally:
            cursor.close()
            conn.close()

    def _paystub_employee():
        identity, denied = _hub_identity()
        if denied:
            return None, denied
        token = request.headers.get("X-Paystub-Step-Up") or ""
        try:
            data = _step_serializer().loads(token, max_age=PAYSTUB_MAX_AGE)
        except SignatureExpired:
            return None, (jsonify({"error": "Verify again to view paystubs", "code": "step_up_required"}), 401)
        except BadSignature:
            return None, (jsonify({"error": "Verify again to view paystubs", "code": "step_up_required"}), 401)
        if (
            not isinstance(data, dict)
            or data.get("purpose") != "paystub_step_up"
            or int(data.get("organization_id") or 0) != int(identity["organization_id"])
            or int(data.get("employee_id") or 0) != int(identity["employee_id"])
        ):
            return None, (jsonify({"error": "Verify again to view paystubs", "code": "step_up_required"}), 401)
        return identity, None

    @app.route("/api/public/attendance/pin-planner/paystubs", methods=["GET"])
    def operations_planner_v2_paystubs():
        from backend.payroll_operations import worker_category_for_user
        from backend.payroll_payout_details import can_generate_paystub_for_line, list_employee_payroll_history, parse_line_payout_details

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            identity, denied = _paystub_employee()
            if denied:
                return _no_store(denied[0]), denied[1]
            org = int(identity["organization_id"])
            employee_id = int(identity["employee_id"])
            flags = load_flags(cursor, org)
            access = load_access(cursor, org, employee_id)
            category = worker_category_for_user(conn, employee_id)
            decision = paystub_decision(
                module_enabled=flags["paystub_access"],
                employee_enabled=access["paystub_enabled"],
                worker_category=category,
                step_up_ok=True,
                second_factor_on_file=True,
                document_available=True,
            )
            if decision != "ok":
                return _no_store(jsonify({"visible": False, "code": decision})), 403
            history = list_employee_payroll_history(conn, org, employee_id, range_key="all", worker_category="w2")
            documents = []
            for line in history:
                if int(line.get("user_id") or 0) != employee_id:
                    continue
                batch = {
                    "worker_category": "w2",
                    "payout_details_finalized_at": line.get("payout_details_finalized_at") or line.get("_payout_details_finalized_at"),
                }
                details = line.get("payout_details") or parse_line_payout_details(line, worker_category="w2")
                if not can_generate_paystub_for_line(batch, details if isinstance(details, dict) else {}):
                    continue
                documents.append(
                    {
                        "batch_id": int(line.get("batch_id") or line.get("_batch_id") or 0),
                        "line_id": int(line.get("id") or 0),
                        "pay_period_start": str(line.get("pay_period_start") or line.get("_pay_period_start") or "")[:10],
                        "pay_period_end": str(line.get("pay_period_end") or line.get("_pay_period_end") or "")[:10],
                    }
                )
            return _no_store(jsonify({"visible": True, "documents": [row for row in documents if row["batch_id"] and row["line_id"]]}))
        except Exception as exc:
            response, code = _error_response(exc)
            return _no_store(response), code
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/attendance/pin-planner/paystubs/<int:batch_id>/<int:line_id>", methods=["GET"])
    def operations_planner_v2_paystub_document(batch_id: int, line_id: int):
        from backend.payroll_payout_details import generate_paystub_html

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            identity, denied = _paystub_employee()
            if denied:
                return _no_store(denied[0]), denied[1]
            org = int(identity["organization_id"])
            employee_id = int(identity["employee_id"])
            cursor.execute(
                """
                SELECT l.user_id
                FROM payout_batch_lines l
                JOIN payout_batches b ON b.id = l.batch_id AND b.organization_id = l.organization_id
                WHERE l.id=%s AND b.id=%s AND b.organization_id=%s
                LIMIT 1
                """,
                (int(line_id), int(batch_id), org),
            )
            row = cursor.fetchone() or {}
            owner = int(row.get("user_id") or 0) if isinstance(row, dict) else 0
            if owner != employee_id:
                return _no_store(jsonify({"error": "Paystub not found"})), 404
            html = generate_paystub_html(conn, org, int(batch_id), int(line_id), copy_mode="employee")
            response = Response(html, mimetype="text/html")
            response.headers["Content-Disposition"] = "inline; filename=paystub.html"
            return _no_store(response)
        except ValueError:
            return _no_store(jsonify({"error": "Paystub not found"})), 404
        except Exception as exc:
            response, code = _error_response(exc)
            return _no_store(response), code
        finally:
            cursor.close()
            conn.close()
