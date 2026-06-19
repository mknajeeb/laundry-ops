"""Maintenance machine rack configuration routes."""

from __future__ import annotations

from flask import jsonify, request

from backend.db import get_db
from backend.machine_configuration_settings import (
    get_machine_rack_config,
    save_machine_rack_config,
)
from backend.rinse_scan_time import json_safe_rinse


def register_machine_configuration_routes(
    app,
    *,
    require_user,
    require_admin_or_ops,
    user_org_id,
) -> None:
    @app.route("/maintenance/machine-configuration", methods=["GET", "PUT"])
    def maintenance_machine_configuration():
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
                return jsonify(json_safe_rinse(get_machine_rack_config(cursor, tenant_oid)))
            _, err_ops, code_ops = require_admin_or_ops(cursor)
            if err_ops:
                return err_ops, code_ops
            data = request.get_json(silent=True) or {}
            out = save_machine_rack_config(cursor, tenant_oid, data)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
