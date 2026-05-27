"""Processing productivity APIs (start-cleaning scans)."""

from __future__ import annotations

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_folding_period import parse_range_from_request
from backend.rinse_folding_settings import get_rinse_folding_benchmarks
from backend.rinse_processing_productivity import build_processing_productivity
from backend.rinse_processing_settings import get_processing_settings, put_processing_settings
from backend.rinse_scan_time import json_safe_rinse


def register_rinse_processing_routes(app, *, require_user, require_admin, user_org_id, parse_date_value):
    @app.route("/rinse/processing/productivity", methods=["GET"])
    def rinse_processing_productivity():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            benchmarks = get_rinse_folding_benchmarks(cursor, tenant_oid)
            week_start_day = str(benchmarks.get("week_start_day") or "MONDAY")
            try:
                period_start, period_end, _label, _date_field = parse_range_from_request(
                    request.args,
                    parse_date_value,
                    week_start_day=week_start_day,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            user_name = (request.args.get("user_name") or "").strip() or None
            shift_filter = (request.args.get("shift_filter") or "all").strip().lower()
            include_unmapped = str(
                request.args.get("include_unmapped", "true")
            ).strip().lower() in ("1", "true", "yes")
            payload = build_processing_productivity(
                cursor,
                tenant_oid,
                period_start=period_start,
                period_end=period_end,
                user_name=user_name,
                shift_filter=shift_filter,
                include_unmapped=include_unmapped,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/processing/settings", methods=["GET", "PUT"])
    def rinse_processing_settings_route():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            if request.method == "GET":
                return jsonify(json_safe_rinse(get_processing_settings(cursor, tenant_oid)))
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            data = request.get_json(silent=True) or {}
            out = put_processing_settings(cursor, tenant_oid, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
