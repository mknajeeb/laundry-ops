"""Rinse Hub external-safe APIs — approved Performance snapshots only."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_dashboard_performance import (
    build_employee_detail,
    build_employee_role_history,
    build_employees_list,
    build_rinse_meta,
    build_role_leaderboard,
)
from backend.rinse_scan_time import json_safe_rinse
from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

RINSE_READ_ROLES = frozenset(
    {"RINSE", "ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"}
)
HUB_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _can_read_rinse_dashboard(me: dict) -> bool:
    roles = _role_set(me)
    if roles & HUB_ROLES:
        return True
    if roles & {"RINSE"}:
        return True
    return is_rinse_schedule_viewer(list(roles))


def _parse_week_start(raw: str | None, parse_date_value) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return parse_date_value(value)


def register_rinse_dashboard_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    @app.route("/api/rinse-dashboard/meta", methods=["GET"])
    def rinse_dashboard_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            payload = build_rinse_meta(cursor, oid)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/roles/<role_key>", methods=["GET"])
    def rinse_dashboard_role_leaderboard(role_key: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            payload = build_role_leaderboard(
                cursor, oid, role_key=role_key, week_start=week_start
            )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            from backend.rinse_dashboard_performance import payload_bytes

            if isinstance(payload.get("perf"), dict):
                payload["perf"]["payload_bytes"] = payload_bytes(payload)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/employees", methods=["GET"])
    def rinse_dashboard_employees():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            payload = build_employees_list(cursor, oid, week_start=week_start)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/employees/<employee_id>", methods=["GET"])
    def rinse_dashboard_employee(employee_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            payload = build_employee_detail(
                cursor, oid, employee_id=employee_id, week_start=week_start
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/rinse-dashboard/performance/employees/<employee_id>/roles/<role_key>",
        methods=["GET"],
    )
    def rinse_dashboard_employee_role(employee_id: str, role_key: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            try:
                last_n = int(request.args.get("last_n") or 5)
            except (TypeError, ValueError):
                last_n = 5
            payload = build_employee_role_history(
                cursor,
                oid,
                employee_id=employee_id,
                role_key=role_key,
                week_start=week_start,
                last_n=last_n,
            )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
