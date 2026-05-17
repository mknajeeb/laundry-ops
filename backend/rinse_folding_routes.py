"""Rinse folding performance APIs (admin recompute, exceptions, stats)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_folding_registry import (
    apply_folding_performance_for_bag,
    apply_performance_override,
    aggregate_user_folding_stats,
    get_folding_performance_row,
    list_folding_performance_rows,
    recompute_folding_performance_for_bags,
    recompute_folding_performance_for_date_range,
)
from backend.rinse_folding_settings import get_rinse_folding_benchmarks, put_rinse_folding_benchmarks


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
            status = (request.args.get("status") or "").strip().upper() or None
            work_date_raw = request.args.get("work_date")
            work_date = parse_date_value(work_date_raw) if work_date_raw else None
            user_name = (request.args.get("user_name") or "").strip() or None
            try:
                limit = min(500, max(1, int(request.args.get("limit", 100))))
            except (TypeError, ValueError):
                limit = 100
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0
            rows = list_folding_performance_rows(
                cursor,
                tenant_oid,
                status=status,
                work_date=work_date,
                user_name=user_name,
                limit=limit,
                offset=offset,
            )
            return jsonify(rows)
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
            exception_code = (request.args.get("exception_code") or "").strip() or None
            try:
                limit = min(500, max(1, int(request.args.get("limit", 100))))
            except (TypeError, ValueError):
                limit = 100
            try:
                offset = max(0, int(request.args.get("offset", 0)))
            except (TypeError, ValueError):
                offset = 0
            rows = list_folding_performance_rows(
                cursor,
                tenant_oid,
                exception_only=True,
                limit=limit,
                offset=offset,
            )
            if exception_code:
                rows = [
                    r
                    for r in rows
                    if str(r.get("exception_code") or "").upper() == exception_code.upper()
                ]
            return jsonify(rows)
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

            return jsonify(
                {
                    "performance": row,
                    "registry": get_registry_row(cursor, tenant_oid, bid),
                    "scan_events": list_scan_events_for_bag(cursor, tenant_oid, bid),
                }
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
            conn.commit()
            return jsonify(payload)
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
            return jsonify(payload)
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
                new=json_safe_row(payload.get("row")),
                remarks=data.get("notes"),
                organization_id=tenant_oid,
            )
            conn.commit()
            return jsonify(payload)
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
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
            return jsonify(stats)
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
            return jsonify(stats)
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
            bags = data.get("bags_per_hour_target")
            lbs = data.get("lbs_per_hour_target")
            if bags is not None:
                bags = float(bags)
            if lbs is not None:
                lbs = float(lbs)
            out = put_rinse_folding_benchmarks(
                cursor, tenant_oid, bags_per_hour=bags, lbs_per_hour=lbs
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
    if not row:
        return None
    out = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
