"""Management Hub — Rinse HD routes (new operating model).

Managers and PIN employees with Mobile PIN Access ``revenue_cost`` share the
same Hang Dry production APIs / ``hd_day_bag_production`` records.
"""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_pin_access import (
    access_denied_payload,
    actor_name,
    allows_management_revenue_pin,
    is_hub_manager,
)
from backend.management_rinse_hd import (
    build_rinse_hd_day,
    get_rinse_hd_order_detail,
    mark_rinse_hd_complete,
    save_rinse_hd_items_revenue,
)
from backend.rinse_scan_time import json_safe_rinse


def register_management_rinse_hd_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _gate(cursor, me, oid: int):
        if allows_management_revenue_pin(cursor, me, org_id=oid):
            return None
        body, code = access_denied_payload()
        return jsonify(body), code

    def _selected_date(raw: str, *, employee: bool):
        if employee:
            return business_today()
        selected = parse_date_value(raw) if raw else business_today()
        if not isinstance(selected, date):
            raise ValueError("Invalid date_et; use YYYY-MM-DD")
        return selected

    def _actor_user_id(me: dict):
        return me.get("user_id") or me.get("id")

    @app.route("/api/management/rinse-hd", methods=["GET"])
    def management_rinse_hd_day():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            raw_date = (request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            raw_date = (request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = save_rinse_hd_items_revenue(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                total_items=body.get("total_items"),
                revenue=body.get("revenue"),
                version=int(body.get("version") or 0),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = mark_rinse_hd_complete(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                version=int(body.get("version") or 0),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
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
