"""Team Status API — manager Mobile Ops view-only attendance roster."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.employee_mobile_pin_access import (
    MobilePinAccessDeniedError,
    assert_employee_allows_module,
)
from backend.management_pin_access import access_denied_payload
from backend.team_status import build_team_status


def register_team_status_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _gate(cursor, me, oid: int):
        """Requires Mobile PIN Access team_status (not default hub-manager roles)."""
        try:
            uid = int(me.get("user_id") or me.get("id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            body, code = access_denied_payload()
            return jsonify(body), code
        try:
            assert_employee_allows_module(cursor, int(oid), uid, "team_status")
        except MobilePinAccessDeniedError:
            body, code = access_denied_payload()
            return jsonify(body), code
        return None

    @app.route("/api/team-status", methods=["GET"])
    def team_status_day():
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
            raw = (request.args.get("date_et") or "").strip()
            try:
                selected = parse_date_value(raw) if raw else business_today()
            except Exception:
                return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            if not isinstance(selected, date):
                return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            payload = build_team_status(conn, oid, date_et=selected)
            return jsonify(payload)
        finally:
            try:
                cursor.close()
            except Exception:
                pass
