"""Shift Analysis Dashboard API routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_folding_period import parse_range_from_request
from backend.rinse_shift_analysis import (
    build_shift_analysis_summary,
    enrich_record_scoring_fields,
    get_pending_bag_status,
)
from backend.rinse_scan_time import json_safe_rinse


def register_rinse_shift_analysis_routes(app, *, require_user, user_org_id, parse_date_value):
    @app.route("/rinse/shift-analysis/summary", methods=["GET"])
    def rinse_shift_analysis_summary():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            period_start, period_end, date_field = parse_range_from_request(
                request, parse_date_value, default_date_field="folding_work_date"
            )
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                return jsonify({"error": "date_start and date_end required"}), 400
            raw_acts = request.args.get("processing_activities") or ""
            acts = [a.strip().lower() for a in raw_acts.split(",") if a.strip()] or None
            payload = build_shift_analysis_summary(
                cursor,
                tenant_oid,
                period_start=period_start,
                period_end=period_end,
                date_field=date_field,
                processing_activities=acts,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/pending", methods=["GET"])
    def rinse_shift_analysis_pending():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            target_raw = request.args.get("date") or request.args.get("date_end") or request.args.get("date_start")
            target = parse_date_value(target_raw) if target_raw else None
            if not isinstance(target, date):
                return jsonify({"error": "date required"}), 400
            payload = get_pending_bag_status(cursor, tenant_oid, target_date=target)
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/records", methods=["GET"])
    def rinse_shift_analysis_records():
        from backend.rinse_folding_registry import list_folding_performance_rows

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            period_start, period_end, date_field = parse_range_from_request(
                request, parse_date_value, default_date_field="folding_work_date"
            )
            try:
                limit = min(500, max(1, int(request.args.get("limit", 200))))
            except (TypeError, ValueError):
                limit = 200
            scoring_filter = (request.args.get("scoring_filter") or "").strip().lower()
            included = None
            if scoring_filter == "scoring":
                included = True
            elif scoring_filter in ("not_scoring", "not-scoring", "excluded"):
                included = False
            payload = list_folding_performance_rows(
                cursor,
                tenant_oid,
                period_start=period_start if isinstance(period_start, date) else None,
                period_end=period_end if isinstance(period_end, date) else None,
                date_field=date_field,
                user_name=(request.args.get("user_name") or "").strip() or None,
                bag_id=(request.args.get("bag_id") or "").strip() or None,
                customer=(request.args.get("customer") or "").strip() or None,
                status=(request.args.get("status") or "").strip().upper() or None,
                exception_code=(request.args.get("exception_code") or "").strip() or None,
                included_in_scoring=included,
                limit=limit,
                offset=0,
            )
            rows = [enrich_record_scoring_fields(r) for r in (payload.get("rows") or [])]
            return jsonify(json_safe_rinse({**payload, "rows": rows, "activity": "folding"}))
        finally:
            cursor.close()
            conn.close()
