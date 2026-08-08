"""Maintenance Task List API — employee PIN + manager authenticated routes."""

from __future__ import annotations

from flask import jsonify, request

from backend.db import get_db
from backend.maintenance_task_list_module import (
    MaintenanceTaskListError,
    business_today_iso,
    create_or_update_definition,
    ensure_maintenance_task_list_tables,
    format_task_date_display,
    get_or_create_task_list,
    get_task_list,
    list_submission_summaries,
    list_task_definitions,
    list_weekday_assignments,
    reopen_task_list,
    reorder_definitions,
    save_progress,
    save_task_item,
    save_weekday_assignments,
    set_definition_active,
    submit_task_list,
)
from backend.maintenance_task_list_constants import SUGGESTED_CATEGORIES, WEEKDAY_ROWS
from backend.employee_mobile_pin_access import (
    DENIED_MODULE_MESSAGE,
    MobilePinAccessDeniedError,
)
from backend.maintenance_task_list_pin import (
    perform_pin_maintenance_open,
    verify_pin_session_token,
)
from backend.rinse_scan_time import json_safe_rinse
from backend.ta_helpers import json_safe


def register_maintenance_task_list_routes(
    app,
    *,
    require_user,
    require_admin,
    require_admin_or_ops,
    user_org_id,
    parse_date_value,
    fetch_user_roles,
    get_request_ip,
    effective_washpro_permission_keys=None,
    write_audit=None,
) -> None:
    def _roles(me) -> set[str]:
        return {str(r).upper() for r in (me.get("roles") or [])}

    def _is_admin(rs: set[str]) -> bool:
        return bool(rs & {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"})

    def _is_ops(rs: set[str]) -> bool:
        return _is_admin(rs) or "OPS" in rs

    def _has_perm(conn, me, perm_key: str) -> bool:
        if _is_admin(_roles(me)):
            return True
        if effective_washpro_permission_keys is None:
            return False
        try:
            keys = effective_washpro_permission_keys(conn, int(me["user_id"]))
            return perm_key in keys
        except Exception:
            return False

    def _perm_or_fallback(conn, me, perm_key: str, *, allow_ops: bool = False, allow_floor: bool = False) -> bool:
        """Prefer explicit permissions; fall back to role tiers until migration is applied."""
        if _has_perm(conn, me, perm_key):
            return True
        # If any maintenance.tasks.* perm exists for this user, treat missing key as deny.
        if effective_washpro_permission_keys is not None:
            try:
                keys = effective_washpro_permission_keys(conn, int(me["user_id"]))
                if any(str(k).startswith("maintenance.tasks.") for k in keys):
                    return False
            except Exception:
                pass
        rs = _roles(me)
        if _is_admin(rs):
            return True
        if allow_ops and _is_ops(rs):
            return True
        if allow_floor and ("FRONT_DESK" in rs or _is_ops(rs)):
            return True
        return False

    def _me(cursor):
        me, err_resp, err_code = require_user(cursor)
        return me, err_resp, err_code, user_org_id(me) if me else None

    def _pin_session_from_request(cursor=None) -> dict:
        """Resolve a PIN session and re-check current checklist access."""
        from backend.employee_mobile_pin_access import assert_employee_allows_module

        auth = (request.headers.get("Authorization") or "").strip()
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            token = (request.headers.get("X-Maintenance-Session") or "").strip()
        if not token and request.json:
            token = str((request.json or {}).get("session_token") or "").strip()
        session = verify_pin_session_token(token)
        org_id = int(session["organization_id"])
        employee_id = int(session["employee_id"])
        if cursor is None:
            raise ValueError("Invalid session. Enter your PIN again.")
        cursor.execute(
            """
            SELECT id FROM users
            WHERE id = %s AND organization_id = %s AND active = 1
            LIMIT 1
            """,
            (employee_id, org_id),
        )
        if not cursor.fetchone():
            raise ValueError("Invalid session. Enter your PIN again.")
        assert_employee_allows_module(cursor, org_id, employee_id, "checklist")
        return {"organization_id": org_id, "employee_id": employee_id}

    def _safe(payload):
        try:
            return json_safe_rinse(payload)
        except Exception:
            return json_safe(payload)

    def _pin_denied_response():
        return jsonify({"ok": False, "error": DENIED_MODULE_MESSAGE}), 403

    # ----- Public PIN employee APIs -----

    @app.route("/api/public/attendance/pin-maintenance-tasks", methods=["POST"])
    def public_pin_maintenance_tasks_open():
        data = request.json or {}
        org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
        pin = data.get("pin")
        conn = get_db()
        try:
            body, status = perform_pin_maintenance_open(
                conn,
                org_slug,
                pin,
                fetch_user_roles,
                get_request_ip(),
            )
            if body.get("ok"):
                conn.commit()
            else:
                try:
                    conn.commit()
                except Exception:
                    pass
            return jsonify(body), status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Invalid PIN. Please try again."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/maintenance-task-list/today", methods=["GET", "POST"])
    def public_mtl_today():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            session = _pin_session_from_request(cursor)
            ensure_maintenance_task_list_tables(cursor)
            task_date = None
            if request.method == "POST":
                task_date = (request.json or {}).get("task_date")
            else:
                task_date = request.args.get("task_date")
            # Employees normally only work on today; ignore other dates from the PIN client.
            task_date = business_today_iso()
            payload = get_or_create_task_list(
                cursor,
                session["organization_id"],
                session["employee_id"],
                task_date,
                actor_user_id=session["employee_id"],
            )
            conn.commit()
            return jsonify(
                _safe(
                    {
                        "ok": True,
                        "task_date": payload["task_date"],
                        "task_date_display": format_task_date_display(payload["task_date"]),
                        "employee_id": session["employee_id"],
                        "list": payload,
                    }
                )
            )
        except MobilePinAccessDeniedError:
            return _pin_denied_response()
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 401
        except MaintenanceTaskListError as e:
            return jsonify({"ok": False, "error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/maintenance-task-list/<int:list_id>/items/<int:item_id>", methods=["PATCH"])
    def public_mtl_item_patch(list_id, item_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            session = _pin_session_from_request(cursor)
            data = request.json or {}
            existing = get_task_list(cursor, session["organization_id"], list_id)
            if int(existing["employee_id"]) != int(session["employee_id"]):
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            payload = save_task_item(
                cursor,
                session["organization_id"],
                list_id,
                item_id,
                completed=data.get("completed"),
                note=data.get("note"),
                actor_user_id=session["employee_id"],
            )
            conn.commit()
            return jsonify(_safe({"ok": True, "list": payload}))
        except MobilePinAccessDeniedError:
            return _pin_denied_response()
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 401
        except MaintenanceTaskListError as e:
            return jsonify({"ok": False, "error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/maintenance-task-list/<int:list_id>/save", methods=["POST"])
    def public_mtl_save(list_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            session = _pin_session_from_request(cursor)
            existing = get_task_list(cursor, session["organization_id"], list_id)
            if int(existing["employee_id"]) != int(session["employee_id"]):
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            payload = save_progress(
                cursor,
                session["organization_id"],
                list_id,
                request.json or {},
                session["employee_id"],
            )
            conn.commit()
            return jsonify(_safe({"ok": True, "list": payload}))
        except MobilePinAccessDeniedError:
            return _pin_denied_response()
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 401
        except MaintenanceTaskListError as e:
            return jsonify({"ok": False, "error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/public/maintenance-task-list/<int:list_id>/submit", methods=["POST"])
    def public_mtl_submit(list_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            session = _pin_session_from_request(cursor)
            existing = get_task_list(cursor, session["organization_id"], list_id)
            if int(existing["employee_id"]) != int(session["employee_id"]):
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            data = request.json or {}
            payload = submit_task_list(
                cursor,
                session["organization_id"],
                list_id,
                session["employee_id"],
                notes=data.get("notes"),
            )
            conn.commit()
            return jsonify(
                _safe(
                    {
                        "ok": True,
                        "message": "Maintenance task list completed successfully.",
                        "list": payload,
                    }
                )
            )
        except MobilePinAccessDeniedError:
            return _pin_denied_response()
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 401
        except MaintenanceTaskListError as e:
            return jsonify({"ok": False, "error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    # ----- Authenticated manager / settings APIs -----

    @app.route("/api/maintenance-task-list/meta", methods=["GET"])
    def mtl_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            rs = _roles(me)
            return jsonify(
                {
                    "today": business_today_iso(),
                    "today_display": format_task_date_display(),
                    "can_manage": _perm_or_fallback(conn, me, "maintenance.tasks.manage"),
                    "can_reports": _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True),
                    "can_reopen": False,
                    "role_tier": "admin" if _is_admin(rs) else ("ops" if _is_ops(rs) else "floor"),
                    "suggested_categories": list(SUGGESTED_CATEGORIES),
                    "weekday_labels": [{"weekday": w, "label": label} for w, label in WEEKDAY_ROWS],
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/definitions", methods=["GET", "POST", "PUT"])
    def mtl_definitions():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                if not _perm_or_fallback(
                    conn, me, "maintenance.tasks.manage", allow_ops=True
                ) and not _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True):
                    return jsonify({"error": "Forbidden", "missing_permission": "maintenance.tasks.manage"}), 403
                include_inactive = str(request.args.get("include_inactive") or "1") not in ("0", "false")
                rows = list_task_definitions(cursor, org_id, include_inactive=include_inactive)
                conn.commit()
                return jsonify(_safe({"definitions": rows, "today": business_today_iso()}))

            if not _perm_or_fallback(conn, me, "maintenance.tasks.manage"):
                return jsonify({"error": "Forbidden", "missing_permission": "maintenance.tasks.manage"}), 403
            data = request.json or {}
            if request.method == "PUT" and data.get("id") is None:
                return jsonify({"error": "id is required"}), 400
            row = create_or_update_definition(
                cursor,
                org_id,
                data,
                int(me["user_id"]),
            )
            conn.commit()
            return jsonify(_safe({"definition": row}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/definitions/<int:definition_id>/active", methods=["POST"])
    def mtl_definition_active(definition_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if not _perm_or_fallback(conn, me, "maintenance.tasks.manage"):
                return jsonify({"error": "Forbidden"}), 403
            data = request.json or {}
            is_active = bool(data.get("is_active", True))
            row = set_definition_active(
                cursor, org_id, definition_id, is_active, int(me["user_id"])
            )
            conn.commit()
            return jsonify(_safe({"definition": row}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/definitions/reorder", methods=["POST"])
    def mtl_definitions_reorder():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if not _perm_or_fallback(conn, me, "maintenance.tasks.manage"):
                return jsonify({"error": "Forbidden"}), 403
            ordered_ids = (request.json or {}).get("ordered_ids") or []
            rows = reorder_definitions(cursor, org_id, ordered_ids, int(me["user_id"]))
            conn.commit()
            return jsonify(_safe({"definitions": rows}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/reports", methods=["GET"])
    def mtl_reports():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if not _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True):
                return jsonify({"error": "Forbidden", "missing_permission": "maintenance.tasks.reports"}), 403
            task_date = request.args.get("task_date") or business_today_iso()
            employee_id = request.args.get("employee_id")
            status = request.args.get("status")
            completed_filter = request.args.get("completed")
            definition_id = request.args.get("definition_id")
            rows = list_submission_summaries(
                cursor,
                org_id,
                task_date=task_date,
                employee_id=int(employee_id) if employee_id else None,
                status=status or None,
                completed_filter=completed_filter or None,
                definition_id=int(definition_id) if definition_id else None,
            )
            conn.commit()
            return jsonify(
                _safe(
                    {
                        "task_date": task_date,
                        "task_date_display": format_task_date_display(task_date),
                        "rows": rows,
                    }
                )
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/<int:list_id>", methods=["GET"])
    def mtl_detail(list_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if not (
                _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True)
                or _perm_or_fallback(conn, me, "maintenance.tasks.view", allow_floor=True)
            ):
                return jsonify({"error": "Forbidden"}), 403
            payload = get_task_list(cursor, org_id, list_id, include_events=True)
            # Floor users may only see their own list.
            if not _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True):
                if int(payload["employee_id"]) != int(me["user_id"]):
                    return jsonify({"error": "Forbidden"}), 403
            return jsonify(_safe({"list": payload}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/<int:list_id>/reopen", methods=["POST"])
    def mtl_reopen(list_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            if not _perm_or_fallback(conn, me, "maintenance.tasks.reopen", allow_ops=True):
                return jsonify({"error": "Forbidden", "missing_permission": "maintenance.tasks.reopen"}), 403
            remarks = (request.json or {}).get("remarks")
            payload = reopen_task_list(
                cursor, org_id, list_id, int(me["user_id"]), remarks=remarks
            )
            conn.commit()
            return jsonify(_safe({"list": payload}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/<int:list_id>/save", methods=["POST"])
    def mtl_manager_save(list_id):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            can_manage = _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True)
            can_update = _perm_or_fallback(conn, me, "maintenance.tasks.update", allow_floor=True)
            if not (can_manage or can_update):
                return jsonify({"error": "Forbidden"}), 403
            existing = get_task_list(cursor, org_id, list_id)
            if not can_manage and int(existing["employee_id"]) != int(me["user_id"]):
                return jsonify({"error": "Forbidden"}), 403
            payload = save_progress(
                cursor,
                org_id,
                list_id,
                request.json or {},
                int(me["user_id"]),
                allow_manager_override=can_manage,
            )
            conn.commit()
            return jsonify(_safe({"list": payload}))
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/employee/<int:employee_id>/today", methods=["GET", "POST"])
    def mtl_employee_today(employee_id):
        """Authenticated get-or-create for a specific employee (managers / self)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            is_self = int(employee_id) == int(me["user_id"])
            if is_self:
                if not _perm_or_fallback(conn, me, "maintenance.tasks.view", allow_floor=True):
                    return jsonify({"error": "Forbidden"}), 403
            elif not _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True):
                return jsonify({"error": "Forbidden"}), 403
            task_date = business_today_iso()
            if request.method == "POST":
                task_date = (request.json or {}).get("task_date") or task_date
            elif request.args.get("task_date"):
                task_date = request.args.get("task_date")
            if is_self:
                task_date = business_today_iso()
            payload = get_or_create_task_list(
                cursor,
                org_id,
                int(employee_id),
                task_date,
                actor_user_id=int(me["user_id"]),
            )
            conn.commit()
            return jsonify(
                _safe(
                    {
                        "task_date": payload["task_date"],
                        "task_date_display": format_task_date_display(payload["task_date"]),
                        "list": payload,
                    }
                )
            )
        except MaintenanceTaskListError as e:
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/maintenance-task-list/weekday-assignments", methods=["GET", "PUT"])
    def mtl_weekday_assignments():
        """Manager: recurring weekday checklist assignee (one employee per day, optional)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            ensure_maintenance_task_list_tables(cursor)
            if request.method == "GET":
                if not (
                    _perm_or_fallback(conn, me, "maintenance.tasks.manage")
                    or _perm_or_fallback(conn, me, "maintenance.tasks.reports", allow_ops=True)
                ):
                    return jsonify({"error": "Forbidden"}), 403
                rows = list_weekday_assignments(cursor, org_id)
                return jsonify(_safe({"assignments": rows}))
            if not _perm_or_fallback(conn, me, "maintenance.tasks.manage"):
                return jsonify({"error": "Forbidden"}), 403
            data = request.json or {}
            rows = save_weekday_assignments(
                cursor,
                org_id,
                data.get("assignments") or [],
                actor_user_id=int(me["user_id"]),
            )
            conn.commit()
            return jsonify(_safe({"ok": True, "assignments": rows}))
        except MaintenanceTaskListError as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), e.status
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
