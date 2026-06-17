"""Shift Analysis Dashboard API routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_folding_period import parse_range_from_request
from backend.rinse_shift_operational_exceptions import filter_operational_records
from backend.rinse_shift_analysis import (
    build_operational_dashboard_data,
    build_shift_analysis_summary,
    enrich_record_scoring_fields,
    filter_lifecycle_pending_rows,
    get_pending_bag_status,
    _parse_evaluation_time,
)
from backend.rinse_scan_time import json_safe_rinse


def register_rinse_shift_analysis_routes(
    app,
    *,
    require_user,
    require_admin,
    require_admin_or_ops=None,
    user_org_id,
    parse_date_value,
):
    @app.route("/rinse/shift-analysis/summary", methods=["GET"])
    def rinse_shift_analysis_summary():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            period_start, period_end, _period_label, date_field = parse_range_from_request(
                request.args, parse_date_value
            )
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                return jsonify({"error": "date_start and date_end required"}), 400
            raw_acts = request.args.get("processing_activities") or ""
            acts = [a.strip().lower() for a in raw_acts.split(",") if a.strip()] or None
            eval_at = _parse_evaluation_time(request.args.get("evaluation_time"))
            payload = build_shift_analysis_summary(
                cursor,
                tenant_oid,
                period_start=period_start,
                period_end=period_end,
                date_field=date_field,
                processing_activities=acts,
                evaluation_time=eval_at,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
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
            eval_at = _parse_evaluation_time(request.args.get("evaluation_time"))
            payload = get_pending_bag_status(
                cursor,
                tenant_oid,
                target_date=target,
                evaluation_time=eval_at,
            )
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
            period_start, period_end, _period_label, date_field = parse_range_from_request(
                request.args, parse_date_value
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
                include_total=True,
            )
            raw_rows = payload.get("rows") if isinstance(payload, dict) else payload
            rows = [enrich_record_scoring_fields(r) for r in (raw_rows or [])]
            out = payload if isinstance(payload, dict) else {"rows": rows, "total": len(rows), "limit": limit, "offset": 0}

            operational_filter = (request.args.get("operational_filter") or "").strip()
            lifecycle_group = (request.args.get("lifecycle_group") or "").strip() or None
            lifecycle_filter = (request.args.get("lifecycle_filter") or "").strip().lower() or None
            lifecycle_status = (request.args.get("lifecycle_status") or "").strip().upper() or None
            rush_group = (request.args.get("rush_group") or "").strip().lower() or None
            if lifecycle_group or lifecycle_filter or lifecycle_status or rush_group:
                target = period_end if isinstance(period_end, date) else None
                if target:
                    eval_at = _parse_evaluation_time(request.args.get("evaluation_time"))
                    pending_payload = get_pending_bag_status(
                        cursor,
                        tenant_oid,
                        target_date=target,
                        evaluation_time=eval_at,
                    )
                    life_rows = filter_lifecycle_pending_rows(
                        pending_payload.get("rows") or [],
                        rush_group=rush_group,
                        lifecycle_group=lifecycle_group,
                        lifecycle_status=lifecycle_status,
                        filter_kind=lifecycle_filter,
                    )
                    return jsonify(
                        json_safe_rinse(
                            {
                                **out,
                                "rows": life_rows,
                                "total": len(life_rows),
                                "activity": "lifecycle",
                                "status_model": pending_payload.get("status_model"),
                            }
                        )
                    )

            if operational_filter:
                target = period_end if isinstance(period_end, date) else None
                if target:
                    from backend.rinse_processing_settings import get_processing_settings

                    pending_payload = get_pending_bag_status(cursor, tenant_oid, target_date=target)
                    proc_settings = get_processing_settings(cursor, tenant_oid)
                    reject_limit = int(proc_settings.get("reject_no_start_cleaning_minutes") or 30)
                    operational = build_operational_dashboard_data(
                        cursor,
                        tenant_oid,
                        pending_payload=pending_payload,
                        reject_no_start_cleaning_minutes=reject_limit,
                    )
                    op_rows = filter_operational_records(
                        operational.get("records") or [],
                        drill_filter=operational_filter,
                    )
                    return jsonify(json_safe_rinse({**out, "rows": op_rows, "total": len(op_rows), "activity": "operational"}))

            return jsonify(json_safe_rinse({**out, "rows": rows, "activity": "folding"}))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/simple", methods=["GET"])
    def rinse_shift_analysis_simple():
        """Simplified Scope A / Scope B performance payload (backend-first)."""
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            period_start, period_end, _period_label, _date_field = parse_range_from_request(
                request.args, parse_date_value
            )
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                return jsonify({"error": "date_start and date_end required"}), 400
            eval_at = _parse_evaluation_time(request.args.get("evaluation_time"))
            include_debug = str(
                request.args.get("include_debug") or request.args.get("debug") or ""
            ).strip().lower() in (
                "1",
                "true",
                "yes",
            )
            summary_only = str(request.args.get("summary_only") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            if include_debug:
                summary_only = False
            payload = build_simple_shift_performance_payload(
                cursor,
                tenant_oid,
                period_start=period_start,
                period_end=period_end,
                evaluation_time=eval_at,
                include_debug=include_debug,
                slim_records=True,
                summary_only=summary_only,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/debug", methods=["GET"])
    def rinse_shift_analysis_debug():
        """Admin-only audit payload for /performance data reconciliation."""
        from backend.rinse_shift_analysis_debug import build_shift_analysis_debug_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a is not None:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            period_start, period_end, _period_label, date_field = parse_range_from_request(
                request.args, parse_date_value
            )
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                return jsonify({"error": "date_start and date_end required"}), 400
            eval_at = _parse_evaluation_time(request.args.get("evaluation_time"))
            payload = build_shift_analysis_debug_payload(
                cursor,
                tenant_oid,
                period_start=period_start,
                period_end=period_end,
                date_field=date_field,
                evaluation_time=eval_at,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse/sync/both", methods=["POST"])
    def rinse_sync_both():
        """Run Ready for Vendor presence sync first, then At Vendor scheduled scrape."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            gate = require_admin_or_ops or require_admin
            _, err_gate, code_gate = gate(cursor)
            if err_gate:
                return err_gate, code_gate
            tenant_oid = user_org_id(me)

            body = request.get_json(silent=True) or {}
            dry_run = bool(body.get("dry_run", False))

            from backend.rinse_manual_sync_dispatch import dispatch_manual_rinse_sync

            dispatch = dispatch_manual_rinse_sync(
                conn,
                tenant_oid,
                dry_run=dry_run,
            )
            payload = dispatch.to_payload()
            if payload.get("ready_for_vendor_sync", {}).get("status") == "disabled":
                payload["ready_for_vendor_sync"]["skipped_reason"] = (
                    payload["ready_for_vendor_sync"].get("skipped_reason")
                    or "enable_ready_for_vendor_scrape=false"
                )
            return jsonify(json_safe_rinse(payload)), dispatch.http_status
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
