"""Management Hub — Rinse HD routes (new operating model)."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_rinse_hd import (
    build_rinse_hd_day,
    get_rinse_hd_order_detail,
    mark_rinse_hd_complete,
    save_rinse_hd_items_revenue,
)
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
HUB_WRITE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _actor_name(me: dict) -> str | None:
    for key in ("display_name", "name", "full_name", "username", "email"):
        val = me.get(key)
        if val:
            return str(val)
    return None


def register_management_rinse_hd_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    @app.route("/api/management/rinse-hd", methods=["GET"])
    def management_rinse_hd_day():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            raw_date = (request.args.get("date_et") or "").strip()
            if raw_date:
                try:
                    selected = parse_date_value(raw_date)
                except (TypeError, ValueError):
                    return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            else:
                selected = business_today()
            if not isinstance(selected, date):
                return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            status = (request.args.get("status") or "all").strip().lower()
            payload = build_rinse_hd_day(cursor, oid, selected, status=status)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>", methods=["GET"])
    def management_rinse_hd_detail(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            raw_date = (request.args.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else business_today()
            payload = get_rinse_hd_order_detail(cursor, oid, bag_id, selected_date_et=selected)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/production", methods=["PUT"])
    def management_rinse_hd_production(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else business_today()
            result = save_rinse_hd_items_revenue(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                total_items=body.get("total_items"),
                revenue=body.get("revenue"),
                version=int(body.get("version") or 0),
                actor_user_id=me.get("id") or me.get("user_id"),
                actor_display_name=_actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/mark-complete", methods=["POST"])
    def management_rinse_hd_mark_complete(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else business_today()
            result = mark_rinse_hd_complete(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                version=int(body.get("version") or 0),
                actor_user_id=me.get("id") or me.get("user_id"),
                actor_display_name=_actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
