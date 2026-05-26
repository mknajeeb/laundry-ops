"""Rinse folding performance APIs (admin recompute, exceptions, stats)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_registry import (
    aggregate_folding_employee_analysis,
    aggregate_folding_leaderboard,
    apply_folding_performance_for_bag,
    apply_performance_override,
    aggregate_user_folding_stats,
    get_folding_performance_row,
    list_folding_performance_overrides,
    list_folding_performance_rows,
    recompute_folding_performance_for_bags,
    recompute_folding_performance_for_date_range,
    summarize_recompute_results,
)
from backend.rinse_folding_period import parse_range_from_request
from backend.rinse_folding_settings import get_rinse_folding_benchmarks, put_rinse_folding_benchmarks
from backend.rinse_scan_time import json_safe_rinse


def _optional_float(val: str | None) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    return float(val)


def _optional_int(val: str | None) -> int | None:
    if val is None or str(val).strip() == "":
        return None
    return int(val)


def _optional_bool(val: str | None) -> bool | None:
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip().lower() in ("1", "true", "yes")


def _folding_list_kwargs(request, parse_date_value) -> dict:
    start_raw = request.args.get("date_start") or request.args.get("start_date")
    end_raw = request.args.get("date_end") or request.args.get("end_date")
    period_start = parse_date_value(start_raw) if start_raw else None
    period_end = parse_date_value(end_raw) if end_raw else None
    date_field = str(request.args.get("date_field") or "folding_work_date").strip().lower()
    return {
        "status": (request.args.get("status") or "").strip().upper() or None,
        "period_start": period_start if isinstance(period_start, date) else None,
        "period_end": period_end if isinstance(period_end, date) else None,
        "date_field": date_field,
        "user_name": (request.args.get("user_name") or "").strip() or None,
        "bag_id": (request.args.get("bag_id") or "").strip() or None,
        "customer": (request.args.get("customer") or request.args.get("name_clean") or "").strip() or None,
        "q": (request.args.get("q") or "").strip() or None,
        "exception_code": (request.args.get("exception_code") or "").strip() or None,
        "weight_min": _optional_float(request.args.get("weight_min")),
        "weight_max": _optional_float(request.args.get("weight_max")),
        "duration_min": _optional_int(request.args.get("duration_min")),
        "duration_max": _optional_int(request.args.get("duration_max")),
        "lbs_per_hour_min": _optional_float(request.args.get("lbs_per_hour_min")),
        "lbs_per_hour_max": _optional_float(request.args.get("lbs_per_hour_max")),
        "bags_per_hour_min": _optional_float(request.args.get("bags_per_hour_min")),
        "bags_per_hour_max": _optional_float(request.args.get("bags_per_hour_max")),
        "reviewed": _optional_bool(request.args.get("reviewed")),
        "approved": _optional_bool(request.args.get("approved")),
        "excluded_from_scoring": _optional_bool(request.args.get("excluded_from_scoring")),
        "included_in_scoring": _optional_bool(request.args.get("included_in_scoring")),
    }


def register_rinse_folding_routes(app, *, require_user, require_admin, user_org_id, parse_date_value):
    @app.route("/rinse/folding/performance", methods=["GET"])
    def list_rinse_folding_performance():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            work_date_raw = request.args.get("work_date")
            work_date = parse_date_value(work_date_raw) if work_date_raw else None
            try:
                limit = min(500, max(1, int(request.args.get("limit", 100))))
            except (TypeError, ValueError):
                limit = 100
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0
            kwargs = _folding_list_kwargs(request, parse_date_value)
            payload = list_folding_performance_rows(
                cursor,
                tenant_oid,
                work_date=work_date if isinstance(work_date, date) else None,
                limit=limit,
                offset=offset,
                include_total=True,
                **kwargs,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions", methods=["GET"])
    def list_rinse_folding_exceptions():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            try:
                limit = min(500, max(1, int(request.args.get("limit", 100))))
            except (TypeError, ValueError):
                limit = 100
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0
            kwargs = _folding_list_kwargs(request, parse_date_value)
            payload = list_folding_performance_rows(
                cursor,
                tenant_oid,
                exception_only=True,
                limit=limit,
                offset=offset,
                include_total=True,
                **kwargs,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/performance/<bag_id>", methods=["GET"])
    def get_rinse_folding_performance(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            row = get_folding_performance_row(cursor, tenant_oid, bid)
            if not row:
                return jsonify({"error": "Performance row not found"}), 404
            from backend.rinse_bag_registry import get_registry_row, list_scan_events_for_bag

            registry = get_registry_row(cursor, tenant_oid, bid)
            perf = dict(row)
            if registry:
                perf["name_clean"] = registry.get("name_clean")
            return jsonify(
                json_safe_rinse(
                    {
                        "performance": perf,
                        "registry": registry,
                        "scan_events": list_scan_events_for_bag(cursor, tenant_oid, bid),
                        "override_history": list_folding_performance_overrides(
                            cursor, tenant_oid, bid
                        ),
                    }
                )
            )
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/bags/<bag_id>/recompute-folding", methods=["POST"])
    def recompute_rinse_bag_folding(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            payload = apply_folding_performance_for_bag(
                cursor, tenant_oid, bid, source_recompute_kind="bag"
            )
            if payload.get("reason") == "no_registry_row":
                return jsonify({"error": "Bag not found"}), 404
            payload["summary"] = summarize_recompute_results([payload])
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/recompute", methods=["POST"])
    def recompute_rinse_folding_bulk():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            data = request.get_json(silent=True) or {}
            bag_ids = data.get("bag_ids") or []
            start_raw = data.get("start_date")
            end_raw = data.get("end_date")
            date_field = (data.get("date_field") or "date_clean").strip()

            if bag_ids:
                normalized = [normalize_bag_id(b) for b in bag_ids]
                normalized = [b for b in normalized if b]
                payload = recompute_folding_performance_for_bags(
                    cursor, tenant_oid, normalized, source_recompute_kind="bag"
                )
            elif start_raw and end_raw:
                start_date = parse_date_value(start_raw)
                end_date = parse_date_value(end_raw)
                if not isinstance(start_date, date) or not isinstance(end_date, date):
                    return jsonify({"error": "Invalid start_date or end_date"}), 400
                payload = recompute_folding_performance_for_date_range(
                    cursor,
                    tenant_oid,
                    start_date,
                    end_date,
                    date_field=date_field,
                )
            else:
                return jsonify(
                    {"error": "Provide bag_ids or start_date and end_date"}
                ), 400
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/performance/<bag_id>/override", methods=["POST"])
    def override_rinse_folding_performance(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            data = request.get_json(silent=True) or {}
            payload = apply_performance_override(
                cursor,
                tenant_oid,
                bid,
                data,
                actor_user_id=int(me.get("user_id") or 0) or None,
            )
            from backend.ta_routes import write_audit

            write_audit(
                conn,
                me.get("user_id"),
                "rinse_folding_performance",
                payload["performance_id"],
                "override",
                old=None,
                new=json_safe_rinse(payload.get("row")),
                remarks=data.get("notes"),
                organization_id=tenant_oid,
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/leaderboard", methods=["GET"])
    def rinse_folding_leaderboard():
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
                period_start, period_end, period_label, date_field = parse_range_from_request(
                    request.args,
                    parse_date_value,
                    week_start_day=week_start_day,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            period_raw = (request.args.get("period") or period_label).strip().lower()
            if period_raw == "month":
                period = "month"
            elif period_raw in ("today", "day"):
                period = "today"
            else:
                period = "week"
            anchor_raw = request.args.get("date")
            anchor = parse_date_value(anchor_raw) if anchor_raw else date.today()
            if not isinstance(anchor, date):
                anchor = date.today()
            payload = aggregate_folding_leaderboard(
                cursor,
                tenant_oid,
                period=period,
                anchor=anchor,
                period_start=period_start,
                period_end=period_end,
                date_field=date_field,
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/employee-analysis", methods=["GET"])
    def rinse_folding_employee_analysis():
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
                period_start, period_end, period_label, _date_field = parse_range_from_request(
                    request.args,
                    parse_date_value,
                    week_start_day=week_start_day,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            date_raw = request.args.get("date")
            anchor = parse_date_value(date_raw) if date_raw else date.today()
            if not isinstance(anchor, date):
                return jsonify({"error": "Invalid date"}), 400
            user_name = (request.args.get("user_name") or "").strip() or None
            try:
                payload = aggregate_folding_employee_analysis(
                    cursor,
                    tenant_oid,
                    period=period_label,
                    anchor=anchor,
                    custom_start=period_start,
                    custom_end=period_end,
                    user_name=user_name,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/stats/daily", methods=["GET"])
    def rinse_folding_stats_daily():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_name = (request.args.get("user_name") or "").strip()
            if not user_name:
                return jsonify({"error": "user_name is required"}), 400
            day_raw = request.args.get("date") or request.args.get("work_date")
            if day_raw:
                day = parse_date_value(day_raw)
            else:
                day = date.today()
            if not isinstance(day, date):
                return jsonify({"error": "Invalid date"}), 400
            stats = aggregate_user_folding_stats(
                cursor, tenant_oid, user_name, day, day
            )
            return jsonify(json_safe_rinse(stats))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/stats/weekly", methods=["GET"])
    def rinse_folding_stats_weekly():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_name = (request.args.get("user_name") or "").strip()
            if not user_name:
                return jsonify({"error": "user_name is required"}), 400
            week_start_raw = request.args.get("week_start")
            if week_start_raw:
                week_start = parse_date_value(week_start_raw)
            else:
                today = date.today()
                week_start = today - timedelta(days=today.weekday())
            if not isinstance(week_start, date):
                return jsonify({"error": "Invalid week_start"}), 400
            week_end = week_start + timedelta(days=6)
            stats = aggregate_user_folding_stats(
                cursor, tenant_oid, user_name, week_start, week_end
            )
            stats["granularity"] = "week"
            return jsonify(json_safe_rinse(stats))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/users", methods=["GET"])
    def rinse_folding_users():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            from backend.rinse_folding_excluded_users import (
                list_distinct_folding_user_names,
                list_folding_user_options,
            )
            from backend.rinse_folding_settings_flags import folding_approvals_enabled

            return jsonify(
                {
                    "users": list_distinct_folding_user_names(cursor, tenant_oid),
                    "user_options": list_folding_user_options(cursor, tenant_oid),
                    "approvals_enabled": folding_approvals_enabled(),
                }
            )
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/excluded-users", methods=["GET", "POST", "DELETE"])
    def rinse_folding_excluded_users():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            from backend.rinse_folding_excluded_users import (
                ensure_rinse_folding_excluded_users_table,
                list_excluded_folding_users,
                remove_excluded_folding_user,
            )

            if request.method == "GET":
                return jsonify(list_excluded_folding_users(cursor, tenant_oid))

            if request.method == "DELETE":
                data = request.get_json(silent=True) or {}
                user_name = (data.get("user_name") or request.args.get("user_name") or "").strip()
                row_id = data.get("id") or request.args.get("id")
                try:
                    rid = int(row_id) if row_id is not None and str(row_id).strip() != "" else None
                except (TypeError, ValueError):
                    rid = None
                if not user_name and rid is None:
                    return jsonify({"error": "user_name or id is required"}), 400
                deleted = remove_excluded_folding_user(
                    cursor, tenant_oid, user_name=user_name or None, row_id=rid
                )
                conn.commit()
                return jsonify({"ok": True, "deleted": deleted})

            data = request.get_json(silent=True) or {}
            user_name = (data.get("user_name") or "").strip()
            if not user_name:
                return jsonify({"error": "user_name is required"}), 400
            ensure_rinse_folding_excluded_users_table(cursor)
            cursor.execute(
                """
                INSERT INTO rinse_folding_excluded_users
                  (organization_id, user_name, employee_id, reason, created_by_user_id)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  employee_id = COALESCE(VALUES(employee_id), employee_id),
                  reason = COALESCE(VALUES(reason), reason)
                """,
                (
                    tenant_oid,
                    user_name,
                    (data.get("employee_id") or "").strip() or None,
                    (data.get("reason") or "").strip() or None,
                    me.get("id") if isinstance(me, dict) else None,
                ),
            )
            conn.commit()
            return jsonify({"ok": True, "user_name": user_name}), 201
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/settings/exception-rules", methods=["GET", "PUT"])
    def rinse_folding_exception_rules_settings():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            from backend.rinse_folding_exception_rules import (
                get_folding_exception_rules,
                put_folding_exception_rules,
            )

            if request.method == "GET":
                return jsonify(get_folding_exception_rules(cursor, tenant_oid))
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            data = request.get_json(silent=True) or {}
            out = put_folding_exception_rules(cursor, tenant_oid, data)
            conn.commit()
            return jsonify(out)
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/search", methods=["GET"])
    def rinse_folding_exceptions_search():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            try:
                limit = min(500, max(1, int(request.args.get("limit", 100))))
            except (TypeError, ValueError):
                limit = 100
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0
            from backend.rinse_folding_review import search_folding_exceptions

            kwargs = _folding_list_kwargs(request, parse_date_value)
            payload = search_folding_exceptions(
                cursor, tenant_oid, limit=limit, offset=offset, **kwargs
            )
            return jsonify(json_safe_rinse(payload))
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/<bag_id>/reviewed", methods=["POST"])
    def rinse_folding_exception_mark_reviewed(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            data = request.get_json(silent=True) or {}
            from backend.rinse_folding_review import mark_exception_reviewed

            payload = mark_exception_reviewed(
                cursor,
                tenant_oid,
                bid,
                actor_user_id=int(me.get("user_id") or 0) or None,
                note=data.get("note") or data.get("admin_notes"),
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/<bag_id>/approve", methods=["POST"])
    def rinse_folding_exception_approve(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            data = request.get_json(silent=True) or {}
            from backend.rinse_folding_review import approve_exception_for_scoring

            payload = approve_exception_for_scoring(
                cursor,
                tenant_oid,
                bid,
                actor_user_id=int(me.get("user_id") or 0) or None,
                note=data.get("note") or data.get("admin_notes"),
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/<bag_id>/exclude", methods=["POST"])
    def rinse_folding_exception_exclude(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            data = request.get_json(silent=True) or {}
            from backend.rinse_folding_review import exclude_exception_from_scoring

            payload = exclude_exception_from_scoring(
                cursor,
                tenant_oid,
                bid,
                actor_user_id=int(me.get("user_id") or 0) or None,
                note=data.get("note") or data.get("admin_notes"),
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/bulk-action", methods=["POST"])
    def rinse_folding_exceptions_bulk_action():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            data = request.get_json(silent=True) or {}
            action = (data.get("action") or "").strip()
            raw_ids = data.get("bag_ids") or []
            if not isinstance(raw_ids, list) or not raw_ids:
                return jsonify({"error": "bag_ids required"}), 400
            if not action:
                return jsonify({"error": "action required"}), 400
            note = (data.get("note") or data.get("admin_notes") or "").strip() or None
            from backend.rinse_folding_settings_flags import folding_approvals_enabled

            if action == "approve_scoring" and not folding_approvals_enabled():
                return jsonify({"error": "Folding approvals are disabled"}), 403
            if action in ("approve_scoring", "exclude_scoring") and not note:
                return jsonify({"error": "note is required for approve and exclude"}), 400
            from backend.rinse_folding_review import bulk_folding_exceptions_action

            payload = bulk_folding_exceptions_action(
                cursor,
                tenant_oid,
                [str(x) for x in raw_ids],
                action=action,
                actor_user_id=int(me.get("user_id") or 0) or None,
                note=note,
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/exceptions/<bag_id>/override", methods=["POST"])
    def rinse_folding_exception_override(bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            tenant_oid = user_org_id(me)
            bid = normalize_bag_id(bag_id)
            if not bid:
                return jsonify({"error": "Invalid bag id"}), 400
            data = request.get_json(silent=True) or {}
            from backend.rinse_folding_review import apply_review_override

            payload = apply_review_override(
                cursor,
                tenant_oid,
                bid,
                data,
                actor_user_id=int(me.get("user_id") or 0) or None,
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/rinse/folding/benchmarks", methods=["GET", "PUT"])
    def rinse_folding_benchmarks():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            if request.method == "GET":
                return jsonify(get_rinse_folding_benchmarks(cursor, tenant_oid))
            _, err_a, code_a = require_admin(cursor)
            if err_a:
                return err_a, code_a
            data = request.get_json(silent=True) or {}
            out = put_rinse_folding_benchmarks(
                cursor,
                tenant_oid,
                bags_per_hour=_opt_float(data.get("bags_per_hour_target")),
                lbs_per_hour=_opt_float(data.get("lbs_per_hour_target")),
                minutes_per_bag=_opt_float(data.get("minutes_per_bag_target")),
                issue_free_percent=_opt_float(data.get("issue_free_percent_target")),
                week_start_day=data.get("week_start_day"),
            )
            conn.commit()
            return jsonify(out)
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()


def json_safe_row(row: dict | None) -> dict | None:
    """Serialize one row for audit/API (ET-aware datetimes)."""
    if not row:
        return None
    return json_safe_rinse(row)


def _opt_float(val):
    if val is None:
        return None
    return float(val)
