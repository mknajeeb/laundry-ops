"""Shift Analysis Dashboard API routes."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


def _public_server_error(user_message: str, exc: BaseException):
    """Log full traceback; never expose raw exception text to clients."""
    logger.exception("%s", user_message, exc_info=exc)
    return jsonify({"error": user_message}), 500


def roles_from_user(me) -> set[str]:
    """Normalize ``me.roles`` / ``me.role`` to an uppercased string set.

    ``roles`` may arrive as a list (portal users) or a comma-separated string.
    Never put a list into a set literal — that raises ``unhashable type: 'list'``.
    """
    if not isinstance(me, dict):
        return set()
    raw = me.get("roles")
    if raw is None or raw == "":
        raw = me.get("role") or []
    if isinstance(raw, str):
        return {part.strip().upper() for part in raw.split(",") if part.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(r).upper() for r in raw if r is not None and str(r).strip()}
    return {str(raw).upper()} if raw else set()


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

    @app.route("/rinse/shift-analysis/completion-review", methods=["GET"])
    def rinse_completion_review_list():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            raw_day = request.args.get("date") or request.args.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else date.today()
            if not isinstance(day, date):
                day = date.today()
            sync = str(request.args.get("sync") or "1").lower() not in ("0", "false", "no")
            from backend.rinse_completion_review import build_completion_review_dashboard_block

            confirmed = request.args.get("confirmed_completed_count")
            confirmed_n = int(confirmed) if confirmed not in (None, "") else None
            block = build_completion_review_dashboard_block(
                cursor,
                org,
                selected_date_et=day,
                confirmed_completed_count=confirmed_n,
                sync=sync,
            )
            return jsonify(json_safe_rinse(block))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/rinse/shift-analysis/completion-review/<bag_id>/confirm",
        methods=["POST"],
    )
    def rinse_completion_review_confirm(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from datetime import datetime as dt

            from backend.rinse_completion_review import confirm_completion_review

            emp = str(body.get("employee") or "").strip()
            completion_raw = body.get("completion_at") or body.get("completion_end_time")
            completion_at = None
            if isinstance(completion_raw, str) and completion_raw.strip():
                try:
                    completion_at = dt.fromisoformat(completion_raw.replace("Z", ""))
                except ValueError:
                    completion_at = None
            day_raw = body.get("selected_date_et") or body.get("completion_date") or body.get("date")
            day = parse_date_value(day_raw) if day_raw else date.today()
            if not isinstance(day, date):
                day = date.today()
            weight = body.get("weight_lbs")
            if weight is not None and weight != "":
                try:
                    weight = float(weight)
                except (TypeError, ValueError):
                    return jsonify({"error": "weight_lbs must be a number"}), 400
            else:
                weight = None
            out = confirm_completion_review(
                cursor,
                org,
                bag_id,
                employee=emp,
                completion_at=completion_at,
                selected_date_et=day,
                weight_lbs=weight,
                review_note=body.get("review_note") or body.get("note"),
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(out), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/rinse/shift-analysis/completion-review/<bag_id>/resolve",
        methods=["POST"],
    )
    def rinse_completion_review_resolve(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from backend.rinse_completion_review import resolve_completion_review

            resolution = str(body.get("resolution") or "").strip().upper()
            out = resolve_completion_review(
                cursor,
                org,
                bag_id,
                resolution=resolution,
                review_note=body.get("review_note") or body.get("note"),
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(out), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/completion-review/batch-confirm", methods=["POST"])
    def rinse_completion_review_batch_confirm():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from backend.rinse_completion_review import batch_confirm_completion_reviews

            day_raw = body.get("selected_date_et") or body.get("date")
            day = parse_date_value(day_raw) if day_raw else date.today()
            if not isinstance(day, date):
                day = date.today()
            items = body.get("items") or body.get("bags") or []
            out = batch_confirm_completion_reviews(
                cursor,
                org,
                items,
                selected_date_et=day,
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(out), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/drilldown", methods=["GET"])
    def rinse_veewash_step1_drilldown():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            raw_day = request.args.get("date") or request.args.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else date.today()
            if not isinstance(day, date):
                day = date.today()
            from backend.rinse_veewash_step1_api import (
                build_drilldown,
                normalize_step1_queue_metric,
            )

            # Prefer explicit queue=; fall back to metric= for compatibility.
            raw_queue = request.args.get("queue") or request.args.get("metric") or "review_required"
            metric = normalize_step1_queue_metric(raw_queue)
            out = build_drilldown(
                cursor,
                org,
                selected_date_et=day,
                metric=metric,
                service=str(request.args.get("service") or "all"),
                rush=str(request.args.get("rush") or "all"),
                include_details=str(request.args.get("include_details") or "").lower()
                in ("1", "true", "yes"),
                bag_id=request.args.get("bag_id"),
                page=int(request.args.get("page") or 1),
                page_size=int(request.args.get("page_size") or 25),
                reason_code=request.args.get("reason_code") or request.args.get("reason"),
            )
            if isinstance(out, dict):
                out["queue"] = metric
                out["service"] = str(request.args.get("service") or "all")
                out["rush"] = str(request.args.get("rush") or "all")
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            metric = str(request.args.get("queue") or request.args.get("metric") or "")
            if metric in ("review_required", "review"):
                return _public_server_error("Unable to load WF Review right now.", exc)
            return _public_server_error("Unable to load workload details.", exc)
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/correct", methods=["POST"])
    def rinse_veewash_step1_correct():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from backend.rinse_veewash_step1_api import apply_step1_correction

            out = apply_step1_correction(
                cursor,
                org,
                bag_id=str(body.get("bag_id") or ""),
                action=str(body.get("action") or ""),
                body=body,
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
                actor_display_name=(
                    (me.get("display_name") or me.get("username"))
                    if isinstance(me, dict)
                    else None
                ),
            )
            if not out.get("ok"):
                conn.rollback()
                status = int(out.get("status") or 400)
                if status not in (400, 409, 422):
                    status = 400
                return jsonify(out), status
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return _public_server_error("Unable to save WF Review right now.", exc)
        finally:
            cursor.close()
            conn.close()

    def _require_manager_or_admin(me) -> tuple[bool, Any, int | None]:
        roles = roles_from_user(me)
        if roles.intersection({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN", "MANAGER"}):
            return True, None, None
        role_blob = " ".join(sorted(roles))
        if "ADMIN" in role_blob or "OPS" in role_blob or "MANAGER" in role_blob:
            return True, None, None
        return False, jsonify({"error": "manager_or_admin_required"}), 403

    @app.route("/rinse/bulk-workitems", methods=["GET"])
    def rinse_bulk_workitems_list():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            from backend.rinse_bulk_workitems import list_workitems

            include_inactive = str(request.args.get("include_inactive") or "1").lower() in (
                "1",
                "true",
                "yes",
            )
            rows = list_workitems(cursor, org, include_inactive=include_inactive)
            conn.commit()
            return jsonify({"ok": True, "workitems": json_safe_rinse(rows)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/bulk-workitems", methods=["POST"])
    def rinse_bulk_workitems_create():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            ok, err_j, err_c = _require_manager_or_admin(me)
            if not ok:
                return err_j, err_c
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from backend.rinse_bulk_workitems import create_workitem

            row = create_workitem(
                cursor,
                org,
                name=str(body.get("name") or ""),
                current_unit_price=body.get("current_unit_price") or body.get("unit_price") or 0,
                display_order=int(body.get("display_order") or 100),
                active=bool(body.get("active", True)),
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
                actor_display_name=(
                    (me.get("display_name") or me.get("username"))
                    if isinstance(me, dict)
                    else None
                ),
            )
            conn.commit()
            return jsonify({"ok": True, "workitem": json_safe_rinse(row)})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/bulk-workitems/<int:workitem_id>", methods=["PUT", "PATCH"])
    def rinse_bulk_workitems_update(workitem_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            ok, err_j, err_c = _require_manager_or_admin(me)
            if not ok:
                return err_j, err_c
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            from backend.rinse_bulk_workitems import update_workitem

            row = update_workitem(
                cursor,
                org,
                workitem_id,
                name=body.get("name"),
                current_unit_price=body.get("current_unit_price", body.get("unit_price")),
                display_order=body.get("display_order"),
                active=body.get("active"),
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
                actor_display_name=(
                    (me.get("display_name") or me.get("username"))
                    if isinstance(me, dict)
                    else None
                ),
            )
            conn.commit()
            return jsonify({"ok": True, "workitem": json_safe_rinse(row)})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/bulk-workitems/<int:workitem_id>", methods=["DELETE"])
    def rinse_bulk_workitems_delete(workitem_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            ok, err_j, err_c = _require_manager_or_admin(me)
            if not ok:
                return err_j, err_c
            org = user_org_id(me)
            from backend.rinse_bulk_workitems import delete_workitem

            out = delete_workitem(cursor, org, workitem_id)
            conn.commit()
            return jsonify(out)
        except ValueError as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/bulk-workitems/revenue", methods=["GET"])
    def rinse_bulk_workitems_revenue():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            from backend.rinse_bulk_workitems import build_bulk_revenue_rows

            raw_day = request.args.get("date") or request.args.get("shift_date_et")
            start_raw = request.args.get("start_date")
            end_raw = request.args.get("end_date")
            day = parse_date_value(raw_day) if raw_day else None
            start_d = parse_date_value(start_raw) if start_raw else None
            end_d = parse_date_value(end_raw) if end_raw else None
            rows = build_bulk_revenue_rows(
                cursor,
                org,
                shift_date_et=day if isinstance(day, date) else None,
                start_date=start_d if isinstance(start_d, date) else None,
                end_date=end_d if isinstance(end_d, date) else None,
            )
            return jsonify({"ok": True, "rows": json_safe_rinse(rows), "count": len(rows)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/day-status", methods=["GET"])
    def rinse_veewash_step1_day_status():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            raw_day = request.args.get("date") or request.args.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else date.today()
            if not isinstance(day, date):
                day = date.today()
            from backend.rinse_veewash_shift_day import (
                get_day_record,
                list_close_audit,
                validate_close,
                build_or_load_step1_for_date,
            )

            # Read-only status bar: never rebuild/persist the live day.
            _wl, summary, day_rec = build_or_load_step1_for_date(
                cursor, org, day, persist_live=False, include_bag_rows=False
            )
            validation = validate_close(summary or {}, allow_unresolved_reviews=False)
            return jsonify(
                json_safe_rinse(
                    {
                        "day": day_rec or get_day_record(cursor, org, day),
                        "shift_day": (summary or {}).get("shift_day"),
                        "validation": validation,
                        "audit": list_close_audit(cursor, org, day),
                    }
                )
            )
        except Exception as exc:
            return _public_server_error("Unable to load day status.", exc)
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/close", methods=["POST"])
    def rinse_veewash_step1_close():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            ok_roles, role_err, role_code = _require_manager_or_admin(me)
            if not ok_roles:
                return role_err, role_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            raw_day = body.get("date") or body.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else date.today()
            if not isinstance(day, date):
                return jsonify({"error": "invalid_date"}), 400
            from backend.rinse_veewash_shift_day import close_shift_day

            out = close_shift_day(
                cursor,
                org,
                day,
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
                actor_display_name=(
                    (me.get("display_name") or me.get("username"))
                    if isinstance(me, dict)
                    else None
                ),
                reason=body.get("reason"),
                allow_unresolved_reviews=bool(body.get("allow_unresolved_reviews")),
                checklist=body.get("checklist"),
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(out)), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/reopen", methods=["POST"])
    def rinse_veewash_step1_reopen():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            raw_day = body.get("date") or body.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else date.today()
            if not isinstance(day, date):
                return jsonify({"error": "invalid_date"}), 400
            from backend.rinse_veewash_shift_day import reopen_shift_day

            out = reopen_shift_day(
                cursor,
                org,
                day,
                actor_user_id=me.get("id") if isinstance(me, dict) else None,
                actor_display_name=(
                    (me.get("display_name") or me.get("username"))
                    if isinstance(me, dict)
                    else None
                ),
                reason=str(body.get("reason") or ""),
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(out)), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/backfill-day", methods=["POST"])
    def rinse_veewash_step1_backfill_day():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            raw_day = body.get("date") or body.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else None
            if not isinstance(day, date):
                return jsonify({"error": "invalid_date"}), 400
            from backend.rinse_veewash_shift_day import backfill_day_from_live

            out = backfill_day_from_live(cursor, org, day)
            if not out.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(out)), 400
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/shift-analysis/veewash-step1/retry-refresh", methods=["POST"])
    def rinse_veewash_step1_retry_refresh():
        """Manager Stage-B only: rebuild OPEN/REOPENED day without portal scrape."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org = user_org_id(me)
            body = request.get_json(silent=True) or {}
            raw_day = body.get("date") or body.get("selected_date_et")
            day = parse_date_value(raw_day) if raw_day else None
            if not isinstance(day, date):
                from backend.rinse_veewash_workload import today_et

                day = today_et()
            from backend.rinse_step1_scrape_refresh import refresh_step1_after_scrape

            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=org,
                operations_date_et=day,
                scrape_run_id=body.get("scrape_run_id"),
                import_batch_id=body.get("import_batch_id") or body.get("batch_id"),
            )
            if not out.get("ok"):
                return jsonify(json_safe_rinse({"ok": False, **out})), 400
            return jsonify(json_safe_rinse({"ok": True, **out}))
        except Exception as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 500
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
            order_type = (request.args.get("order_type") or request.args.get("service_type") or "").strip() or None
            status = (request.args.get("status") or request.args.get("bag_status") or "").strip() or None
            view_mode = (request.args.get("view_mode") or "").strip() or None
            drying_duration_raw = (
                request.args.get("drying_duration_minutes")
                or request.args.get("drying_duration")
                or ""
            ).strip()
            drying_duration_minutes = None
            if drying_duration_raw:
                try:
                    drying_duration_minutes = int(drying_duration_raw)
                except ValueError:
                    return jsonify({"error": "drying_duration_minutes must be an integer"}), 400
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
                drying_duration_minutes=drying_duration_minutes,
                order_type_filter=order_type,
                status_filter=status,
                view_mode=view_mode,
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
            # Step-1 path builds from the day snapshot and ignores baseline_ctx.
            # Only pay for baseline scrape hunting on the legacy at-vendor fallback.
            baseline_ctx = None
            try:
                from backend.rinse_veewash_workload import (
                    VEEWASH_ORG_ID,
                    get_step1_activation_date,
                    is_step1_enabled,
                )

                use_step1 = (
                    int(tenant_oid) == VEEWASH_ORG_ID
                    and is_step1_enabled(cursor, tenant_oid)
                    and (get_step1_activation_date(cursor, tenant_oid) or selected) <= selected
                )
            except Exception:
                use_step1 = False
            if not use_step1:
                from backend.rinse_shift_monitor_baseline import (
                    build_baseline_context,
                    get_shift_monitor_baseline,
                )

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
            return _public_server_error("Unable to load employee productivity.", exc)
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

    @app.route("/rinse/shift-analysis/daily-roster/refresh-from-payroll", methods=["POST"])
    def rinse_shift_analysis_daily_roster_refresh_payroll():
        from backend.daily_shift_roster import build_roster_payload
        from backend.daily_shift_roster_payroll import refresh_roster_from_payroll

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
            refreshed, err = refresh_roster_from_payroll(
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
            payload["refreshed_count"] = refreshed
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
