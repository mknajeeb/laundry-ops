"""Management Hub — Revenue & Cash routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_revenue import (
    build_cash_activity,
    build_revenue_day,
    create_cash_payout,
    delete_cash_payout,
    list_cash_payout_audits,
    save_non_rinse_revenue,
    update_cash_payout,
)
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
HUB_WRITE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _actor_name(me: dict) -> str | None:
    for key in ("display_name", "name", "full_name", "username", "email"):
        val = me.get(key)
        if val:
            return str(val)
    return None


def register_management_revenue_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    @app.route("/api/management/revenue", methods=["GET"])
    def management_revenue_day():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            raw_date = (request.args.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else business_today()
            if not isinstance(selected, date):
                return jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400
            payload = build_revenue_day(cursor, oid, selected)
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/non-rinse", methods=["PUT"])
    def management_revenue_non_rinse_save():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            raw_date = (body.get("date_et") or request.args.get("date_et") or "").strip()
            selected = parse_date_value(raw_date) if raw_date else business_today()
            payload = save_non_rinse_revenue(
                cursor,
                oid,
                selected,
                body,
                user_id=int(me.get("id") or 0) or None,
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/cash-payouts", methods=["POST"])
    def management_revenue_cash_payout_create():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            payout = create_cash_payout(
                cursor,
                oid,
                body,
                user_id=int(me.get("id") or 0) or None,
                actor_name=_actor_name(me),
            )
            conn.commit()
            return jsonify(json_safe_rinse({"payout": payout})), 201
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/cash-payouts/<int:payout_id>", methods=["PUT", "DELETE"])
    def management_revenue_cash_payout_mutate(payout_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            if request.method == "DELETE":
                delete_cash_payout(
                    cursor,
                    oid,
                    payout_id,
                    user_id=int(me.get("id") or 0) or None,
                    actor_name=_actor_name(me),
                )
                conn.commit()
                return jsonify({"ok": True})
            body = request.get_json(silent=True) or {}
            payout = update_cash_payout(
                cursor,
                oid,
                payout_id,
                body,
                user_id=int(me.get("id") or 0) or None,
                actor_name=_actor_name(me),
            )
            conn.commit()
            return jsonify(json_safe_rinse({"payout": payout}))
        except LookupError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/cash-payouts/<int:payout_id>/audits", methods=["GET"])
    def management_revenue_cash_payout_audits(payout_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            audits = list_cash_payout_audits(cursor, oid, payout_id)
            return jsonify(json_safe_rinse({"audits": audits}))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/cash-activity", methods=["GET"])
    def management_revenue_cash_activity():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            period = (request.args.get("period") or "today").strip().lower()
            raw_date = (request.args.get("date") or request.args.get("date_et") or "").strip()
            ref = parse_date_value(raw_date) if raw_date else business_today()
            raw_start = (request.args.get("start") or "").strip()
            raw_end = (request.args.get("end") or "").strip()
            start = parse_date_value(raw_start) if raw_start else None
            end = parse_date_value(raw_end) if raw_end else None
            payload = build_cash_activity(cursor, oid, period, ref, start, end)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
