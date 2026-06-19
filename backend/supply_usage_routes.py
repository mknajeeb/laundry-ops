"""Maintenance supply usage reporting routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.rinse_scan_time import json_safe_rinse
from backend.supply_usage import build_supply_usage_report
from backend.supply_usage_settings import (
    get_supply_usage_dosages,
    get_supply_usage_mapping_rules,
    mapping_rules_for_display,
    save_supply_usage_dosages,
    save_supply_usage_mapping_rules,
)


def register_supply_usage_routes(
    app,
    *,
    require_user,
    require_admin_or_ops,
    user_org_id,
    parse_date_value,
) -> None:
    @app.route("/maintenance/supply-usage", methods=["GET"])
    def maintenance_supply_usage():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            raw_date = (request.args.get("date_et") or "").strip()
            if raw_date:
                try:
                    target_date = parse_date_value(raw_date)
                except (TypeError, ValueError):
                    return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            else:
                target_date = business_today()
            if not isinstance(target_date, date):
                return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            payload = build_supply_usage_report(cursor, tenant_oid, target_date)
            return jsonify(json_safe_rinse(payload))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/maintenance/supply-usage/settings", methods=["GET"])
    def maintenance_supply_usage_settings():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            tenant_oid = user_org_id(me)
            mapping_rules = get_supply_usage_mapping_rules(cursor, tenant_oid)
            return jsonify(
                json_safe_rinse(
                    {
                        "dosages": get_supply_usage_dosages(cursor, tenant_oid),
                        "mapping_rules": mapping_rules_for_display(mapping_rules),
                    }
                )
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/maintenance/supply-usage/mapping-rules", methods=["GET", "PUT"])
    def maintenance_supply_usage_mapping_rules():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            if request.method == "GET":
                _, err_ops, code_ops = require_admin_or_ops(cursor)
                if err_ops:
                    return err_ops, code_ops
                rules = get_supply_usage_mapping_rules(cursor, tenant_oid)
                return jsonify(json_safe_rinse(mapping_rules_for_display(rules)))
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            data = request.get_json(silent=True) or {}
            rules_payload = data.get("mapping_rules") if isinstance(data.get("mapping_rules"), list) else data
            if not isinstance(rules_payload, list):
                return jsonify({"error": "mapping_rules must be a list"}), 400
            out = save_supply_usage_mapping_rules(cursor, tenant_oid, rules_payload)
            conn.commit()
            return jsonify(json_safe_rinse(mapping_rules_for_display(out)))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/maintenance/supply-usage/dosages", methods=["GET", "PUT"])
    def maintenance_supply_usage_dosages():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            if request.method == "GET":
                _, err_ops, code_ops = require_admin_or_ops(cursor)
                if err_ops:
                    return err_ops, code_ops
                return jsonify(json_safe_rinse(get_supply_usage_dosages(cursor, tenant_oid)))
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            data = request.get_json(silent=True) or {}
            out = save_supply_usage_dosages(cursor, tenant_oid, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
