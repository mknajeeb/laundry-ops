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
from backend.shift_capacity_planner import simulate_shift_capacity


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

    @app.route("/rinse/shift-analysis/operations-timeline", methods=["GET"])
    def rinse_shift_analysis_operations_timeline():
        """Read-only shift operations timeline for a single ET calendar day."""
        from backend.rinse_operations_timeline import build_operations_timeline_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date_start") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                selected = _today_et()
            else:
                selected = parse_date_value(raw_date)
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            view = (request.args.get("view") or "").strip() or None
            bag_id = (request.args.get("bag_id") or "").strip() or None
            payload = build_operations_timeline_payload(
                cursor,
                tenant_oid,
                selected_date_et=selected,
                view_filter=view,
                bag_id_filter=bag_id,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/scan-chronology", methods=["GET"])
    def rinse_shift_analysis_scan_chronology():
        """Read-only scan session timeline for a single ET calendar day."""
        from backend.rinse_scan_chronology import build_scan_chronology_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date_start") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                selected = _today_et()
            else:
                selected = parse_date_value(raw_date)
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            stage = (request.args.get("stage") or "sorting").strip().lower()
            employee = (request.args.get("employee") or "").strip() or None
            bag_id = (request.args.get("bag_id") or "").strip() or None
            confidence = (request.args.get("confidence") or "").strip() or None
            machine = (request.args.get("machine") or "").strip() or None
            activity_type = (request.args.get("activity_type") or "all").strip().lower()
            payload = build_scan_chronology_payload(
                cursor,
                tenant_oid,
                selected_date_et=selected,
                stage=stage,
                employee_filter=employee,
                bag_id_filter=bag_id,
                confidence_filter=confidence,
                machine_filter=machine,
                activity_type_filter=activity_type,
            )
            return jsonify(json_safe_rinse(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/sorting-chronology", methods=["GET"])
    def rinse_shift_analysis_sorting_chronology():
        """Legacy sorting chronology endpoint — delegates to scan-chronology stage=sorting."""
        from backend.rinse_scan_chronology import build_scan_chronology_payload
        from backend.rinse_sorting_chronology import build_sorting_chronology_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date_start") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                selected = _today_et()
            else:
                selected = parse_date_value(raw_date)
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            employee = (request.args.get("employee") or "").strip() or None
            bag_id = (request.args.get("bag_id") or "").strip() or None
            confidence = (request.args.get("confidence") or "").strip() or None
            if request.args.get("stage"):
                payload = build_scan_chronology_payload(
                    cursor,
                    tenant_oid,
                    selected_date_et=selected,
                    stage="sorting",
                    employee_filter=employee,
                    bag_id_filter=bag_id,
                    confidence_filter=confidence,
                )
            else:
                payload = build_sorting_chronology_payload(
                    cursor,
                    tenant_oid,
                    selected_date_et=selected,
                    employee_filter=employee,
                    bag_id_filter=bag_id,
                    confidence_filter=confidence,
                )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/employee-productivity", methods=["GET"])
    def rinse_shift_analysis_employee_productivity():
        """Phase 2 — employee productivity only (full bags, no full dashboard reload)."""
        from backend.rinse_employee_completed_bags import (
            build_employee_productivity_dashboard_payload,
        )
        from backend.rinse_shift_monitor_baseline import (
            build_baseline_context,
            get_shift_monitor_baseline,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date_start") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                selected = _today_et()
            else:
                selected = parse_date_value(raw_date)
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            rush_filter = (request.args.get("rush_filter") or "all").strip().lower()
            baseline_ctx = build_baseline_context(
                cursor, tenant_oid, get_shift_monitor_baseline(cursor, tenant_oid)
            )
            payload = build_employee_productivity_dashboard_payload(
                cursor,
                tenant_oid,
                selected_date_et=selected,
                baseline_ctx=baseline_ctx,
                rush_filter=rush_filter,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/workload-productivity-debug", methods=["GET"])
    def rinse_shift_analysis_workload_productivity_debug():
        """Debug — workload ↔ employee productivity reconciliation audit."""
        from backend.rinse_employee_completed_bags import build_workload_productivity_debug_payload
        from backend.rinse_shift_monitor_baseline import (
            build_baseline_context,
            get_shift_monitor_baseline,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date_start") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                selected = _today_et()
            else:
                selected = parse_date_value(raw_date)
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            rush_filter = (request.args.get("rush_filter") or "all").strip().lower()
            baseline_ctx = build_baseline_context(
                cursor, tenant_oid, get_shift_monitor_baseline(cursor, tenant_oid)
            )
            payload = build_workload_productivity_debug_payload(
                cursor,
                tenant_oid,
                selected_date_et=selected,
                baseline_ctx=baseline_ctx,
                rush_filter=rush_filter,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster", methods=["GET"])
    def rinse_shift_analysis_daily_roster_get():
        from backend.daily_shift_roster import build_roster_payload

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or request.args.get("date") or "").strip()
            if not raw_date:
                from backend.rinse_scheduled_scrape import _today_et

                roster_date = _today_et()
            else:
                roster_date = parse_date_value(raw_date)
            if not isinstance(roster_date, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster", methods=["POST"])
    def rinse_shift_analysis_daily_roster_create():
        from backend.daily_shift_roster import build_roster_payload, create_roster_entry

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
            raw_date = (body.get("date_et") or body.get("roster_date") or "").strip()
            if not raw_date:
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            roster_date = parse_date_value(raw_date)
            if not isinstance(roster_date, date):
                return jsonify({"error": "date_et must be YYYY-MM-DD"}), 400
            entry, err = create_roster_entry(
                cursor,
                tenant_oid,
                roster_date=roster_date,
                data=body,
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload)), 201
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster/<int:entry_id>", methods=["PUT"])
    def rinse_shift_analysis_daily_roster_update(entry_id: int):
        from backend.daily_shift_roster import build_roster_payload, get_roster_entry, update_roster_entry

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
            existing = get_roster_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "roster entry not found"}), 404
            body = request.get_json(silent=True) or {}
            entry, err = update_roster_entry(cursor, tenant_oid, entry_id, body)
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            roster_date = parse_date_value(existing.get("roster_date"))
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster/<int:entry_id>", methods=["DELETE"])
    def rinse_shift_analysis_daily_roster_delete(entry_id: int):
        from backend.daily_shift_roster import build_roster_payload, delete_roster_entry, get_roster_entry

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
            existing = get_roster_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "roster entry not found"}), 404
            ok, err = delete_roster_entry(cursor, tenant_oid, entry_id)
            if not ok:
                return jsonify({"error": err or "delete failed"}), 400
            conn.commit()
            roster_date = parse_date_value(existing.get("roster_date"))
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster/batch-save", methods=["POST"])
    def rinse_shift_analysis_daily_roster_batch_save():
        from backend.daily_shift_roster import batch_save_roster_entries, build_roster_payload

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
            raw_date = (body.get("date_et") or body.get("roster_date") or "").strip()
            if not raw_date:
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            roster_date = parse_date_value(raw_date)
            if not isinstance(roster_date, date):
                return jsonify({"error": "date_et must be YYYY-MM-DD"}), 400
            entries = body.get("entries") or []
            if not isinstance(entries, list) or not entries:
                return jsonify({"error": "entries array required"}), 400
            created, err = batch_save_roster_entries(
                cursor,
                tenant_oid,
                roster_date=roster_date,
                entries=entries,
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            payload["saved_count"] = len(created)
            return jsonify(json_safe_rinse(payload)), 201
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/daily-roster/import-from-payroll", methods=["POST"])
    def rinse_shift_analysis_daily_roster_import_payroll():
        from backend.daily_shift_roster import build_roster_payload
        from backend.daily_shift_roster_payroll import import_payroll_records_into_roster

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
            raw_date = (body.get("date_et") or body.get("roster_date") or "").strip()
            if not raw_date:
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            roster_date = parse_date_value(raw_date)
            if not isinstance(roster_date, date):
                return jsonify({"error": "date_et must be YYYY-MM-DD"}), 400
            added, _, err = import_payroll_records_into_roster(
                cursor,
                tenant_oid,
                roster_date=roster_date,
                conn=conn,
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_roster_payload(
                cursor, tenant_oid, roster_date=roster_date, conn=conn
            )
            payload["imported_count"] = added
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule", methods=["GET"])
    def rinse_shift_analysis_weekly_schedule_get():
        from backend.planned_weekly_schedule import (
            build_week_payload,
            ensure_week_schedule_carried_forward,
            normalize_week_start,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            raw_week = (request.args.get("week_start") or "").strip()
            if not raw_week:
                from backend.rinse_scheduled_scrape import _today_et

                week_start = normalize_week_start(_today_et())
            else:
                week_start = normalize_week_start(raw_week)
            if not isinstance(week_start, date):
                return jsonify({"error": "week_start must be YYYY-MM-DD"}), 400
            from backend.weekly_schedule_display_settings import validate_schedule_week_access

            week_err = validate_schedule_week_access(week_start, me.get("roles"))
            if week_err:
                return jsonify({"error": week_err}), 403
            carry = ensure_week_schedule_carried_forward(
                conn, cursor, tenant_oid, week_start=week_start
            )
            if carry:
                conn.commit()
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            if carry:
                payload["carried_forward_from"] = carry["source_week_start"]
                payload["carried_forward"] = carry
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule", methods=["POST"])
    def rinse_shift_analysis_weekly_schedule_create():
        from backend.planned_weekly_schedule import build_week_payload, create_entry, normalize_week_start

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
            raw_week = (body.get("week_start") or "").strip()
            if not raw_week:
                return jsonify({"error": "week_start required (YYYY-MM-DD)"}), 400
            week_start = normalize_week_start(raw_week)
            if not isinstance(week_start, date):
                return jsonify({"error": "week_start must be YYYY-MM-DD"}), 400
            entry, err = create_entry(
                conn,
                cursor,
                tenant_oid,
                week_start=week_start,
                data=body,
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload)), 201
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/<int:entry_id>", methods=["PUT"])
    def rinse_shift_analysis_weekly_schedule_update(entry_id: int):
        from backend.planned_weekly_schedule import build_week_payload, get_entry, update_entry

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
            existing = get_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "schedule entry not found"}), 404
            body = request.get_json(silent=True) or {}
            entry, err = update_entry(conn, cursor, tenant_oid, entry_id, body)
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            week_start = date.fromisoformat(str(existing["week_start"]))
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/<int:entry_id>", methods=["DELETE"])
    def rinse_shift_analysis_weekly_schedule_delete(entry_id: int):
        from backend.planned_weekly_schedule import build_week_payload, delete_entry, get_entry

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
            existing = get_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "schedule entry not found"}), 404
            if not delete_entry(cursor, tenant_oid, entry_id):
                return jsonify({"error": "schedule entry not found"}), 404
            conn.commit()
            week_start = date.fromisoformat(str(existing["week_start"]))
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/<int:entry_id>/move", methods=["POST"])
    def rinse_shift_analysis_weekly_schedule_move(entry_id: int):
        from backend.planned_weekly_schedule import build_week_payload, get_entry, move_entry

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
            existing = get_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "schedule entry not found"}), 404
            body = request.get_json(silent=True) or {}
            entry, err = move_entry(
                conn,
                cursor,
                tenant_oid,
                entry_id,
                user_id=body.get("user_id"),
                day_of_week=body.get("day_of_week"),
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            week_start = date.fromisoformat(str(existing["week_start"]))
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/<int:entry_id>/duplicate", methods=["POST"])
    def rinse_shift_analysis_weekly_schedule_duplicate(entry_id: int):
        from backend.planned_weekly_schedule import build_week_payload, duplicate_entry, get_entry

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
            existing = get_entry(cursor, tenant_oid, entry_id)
            if not existing:
                return jsonify({"error": "schedule entry not found"}), 404
            body = request.get_json(silent=True) or {}
            entry, err = duplicate_entry(
                conn,
                cursor,
                tenant_oid,
                entry_id,
                user_id=body.get("user_id"),
                day_of_week=body.get("day_of_week"),
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            week_start = date.fromisoformat(str(existing["week_start"]))
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["entry"] = entry
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/exclusions", methods=["POST"])
    def rinse_shift_analysis_weekly_schedule_exclusion():
        from backend.planned_weekly_schedule import (
            build_week_payload,
            normalize_week_start,
            set_employee_exclusion,
        )

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
            raw_week = (body.get("week_start") or "").strip()
            if not raw_week:
                return jsonify({"error": "week_start required (YYYY-MM-DD)"}), 400
            week_start = normalize_week_start(raw_week)
            if not isinstance(week_start, date):
                return jsonify({"error": "week_start must be YYYY-MM-DD"}), 400
            excluded_raw = body.get("excluded")
            if excluded_raw is None:
                return jsonify({"error": "excluded is required (boolean)"}), 400
            excluded, err = set_employee_exclusion(
                conn,
                cursor,
                tenant_oid,
                week_start=week_start,
                user_id=body.get("user_id"),
                excluded=bool(excluded_raw),
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["excluded"] = excluded
            payload["user_id"] = int(body.get("user_id") or 0)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/bulk-employer", methods=["POST"])
    def rinse_shift_analysis_weekly_schedule_bulk_employer():
        from backend.planned_weekly_schedule import (
            build_week_payload,
            bulk_set_week_entry_employer_affiliation,
            normalize_week_start,
        )

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
            raw_week = (body.get("week_start") or "").strip()
            if not raw_week:
                return jsonify({"error": "week_start required (YYYY-MM-DD)"}), 400
            week_start = normalize_week_start(raw_week)
            if not isinstance(week_start, date):
                return jsonify({"error": "week_start must be YYYY-MM-DD"}), 400
            employer_affiliation = (body.get("employer_affiliation") or "").strip()
            if not employer_affiliation:
                return jsonify({"error": "employer_affiliation required"}), 400
            updated, err, skipped = bulk_set_week_entry_employer_affiliation(
                conn,
                cursor,
                tenant_oid,
                week_start=week_start,
                employer_affiliation=employer_affiliation,
            )
            if err:
                return jsonify({"error": err}), 400
            conn.commit()
            payload = build_week_payload(conn, cursor, tenant_oid, week_start=week_start, user_roles=me.get("roles"))
            payload["entries_updated"] = updated
            payload["entries_skipped"] = skipped
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/display-settings", methods=["GET"])
    def rinse_shift_analysis_weekly_schedule_display_settings_get():
        from backend.weekly_schedule_display_settings import get_weekly_schedule_display_settings

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
            return jsonify(
                json_safe_rinse(get_weekly_schedule_display_settings(cursor, tenant_oid))
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/weekly-schedule/display-settings", methods=["PUT"])
    def rinse_shift_analysis_weekly_schedule_display_settings_put():
        from backend.weekly_schedule_display_settings import save_weekly_schedule_display_settings

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
            saved = save_weekly_schedule_display_settings(cursor, tenant_oid, body)
            conn.commit()
            return jsonify(json_safe_rinse(saved))
        except Exception as exc:
            conn.rollback()
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

    @app.route("/api/rinse/sync/targeted-pending-refresh", methods=["POST"])
    def rinse_sync_targeted_pending_refresh():
        """Direct ?q=BAGID refresh for pending workload bags missing from latest portal crawl."""
        from backend.rinse_off_portal_scan_refresh import refresh_pending_workload_scans_via_direct_lookup
        from backend.rinse_scheduled_scrape import _today_et

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
            rush_only = bool(body.get("rush_only", False))
            bag_ids = body.get("bag_ids")
            if bag_ids is not None and not isinstance(bag_ids, list):
                return jsonify({"error": "bag_ids must be an array"}), 400
            raw_date = (body.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else _today_et()
            if not isinstance(selected, date):
                return jsonify({"error": "date_et required (YYYY-MM-DD)"}), 400
            from backend.rinse_shift_monitor_baseline import (
                build_baseline_context,
                get_shift_monitor_baseline,
            )

            baseline_ctx = build_baseline_context(
                cursor, tenant_oid, get_shift_monitor_baseline(cursor, tenant_oid)
            )
            batch_id = body.get("upload_batch_id")
            payload = refresh_pending_workload_scans_via_direct_lookup(
                cursor,
                tenant_oid,
                upload_batch_id=int(batch_id) if batch_id else None,
                selected_date_et=selected,
                baseline_ctx=baseline_ctx,
                bag_ids=bag_ids,
                dry_run=dry_run,
                rush_only=rush_only,
            )
            if not dry_run:
                conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/shift-capacity-planner/simulate", methods=["GET", "POST"])
    def rinse_shift_capacity_planner_simulate():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
            else:
                body = {k: request.args.get(k) for k in request.args if request.args.get(k) is not None}
            payload = simulate_shift_capacity(body)
            return jsonify(json_safe_rinse(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
