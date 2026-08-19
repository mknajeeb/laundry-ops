"""Management Revenue — Accounts & Pricing routes."""

from __future__ import annotations

from flask import jsonify, request

from backend.db import get_db
from backend.management_revenue_accounts import list_accounts, save_account
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
HUB_WRITE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def register_management_revenue_accounts_routes(
    app,
    *,
    require_user,
    user_org_id,
) -> None:
    @app.route("/api/management/revenue/accounts", methods=["GET", "POST"])
    def management_revenue_accounts():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            oid = int(user_org_id(me))
            if request.method == "GET":
                if not (_role_set(me) & HUB_READ_ROLES):
                    return jsonify({"error": "Forbidden"}), 403
                accounts = list_accounts(cursor, oid)
                conn.commit()
                return jsonify(json_safe_rinse({"accounts": accounts}))
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            body = request.get_json(silent=True) or {}
            saved = save_account(
                cursor,
                oid,
                body,
                user_id=int(me.get("id") or 0) or None,
            )
            conn.commit()
            return jsonify(json_safe_rinse({"account": saved}))
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except LookupError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
