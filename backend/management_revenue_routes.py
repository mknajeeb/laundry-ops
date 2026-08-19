"""Management Hub — Revenue & Cash routes.

Managers use hub roles. PIN employees with Mobile PIN Access ``revenue_cost``
use the same entry endpoints (same tables) — no dashboard/settings/accounts.
"""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_pin_access import (
    access_denied_payload,
    actor_name,
    allows_management_revenue_pin,
    is_hub_manager,
)
from backend.management_revenue import (
    build_cash_activity,
    build_revenue_day,
    create_cash_payout,
    delete_cash_payout,
    list_cash_payout_audits,
    save_non_rinse_revenue,
    update_cash_payout,
)
from backend.management_revenue_accounts import build_revenue_dashboard, save_dhs_account_revenue
from backend.rinse_scan_time import json_safe_rinse


def register_management_revenue_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _gate(cursor, me, oid: int):
        if allows_management_revenue_pin(cursor, me, org_id=oid):
            return None
        body, code = access_denied_payload()
        return jsonify(body), code

    def _selected_date(raw: str, *, employee: bool):
        if employee:
            return business_today()
        selected = parse_date_value(raw) if raw else business_today()
        if not isinstance(selected, date):
            raise ValueError("Invalid date_et; use YYYY-MM-DD")
        return selected

    def _user_id(me: dict) -> int | None:
        try:
            uid = int(me.get("user_id") or me.get("id") or 0)
        except (TypeError, ValueError):
            return None
        return uid or None

    @app.route("/api/management/revenue", methods=["GET"])
    def management_revenue_day():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            raw_date = (request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            body = request.get_json(silent=True) or {}
            raw_date = (body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            payload = save_non_rinse_revenue(
                cursor,
                oid,
                selected,
                body,
                user_id=_user_id(me),
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            body = request.get_json(silent=True) or {}
            if employee:
                body = dict(body)
                body["date_et"] = business_today().isoformat()
            payout = create_cash_payout(
                cursor,
                oid,
                body,
                user_id=_user_id(me),
                actor_name=actor_name(me),
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
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            if request.method == "DELETE":
                delete_cash_payout(
                    cursor,
                    oid,
                    payout_id,
                    user_id=_user_id(me),
                    actor_name=actor_name(me),
                )
                conn.commit()
                return jsonify({"ok": True})
            body = request.get_json(silent=True) or {}
            payout = update_cash_payout(
                cursor,
                oid,
                payout_id,
                body,
                user_id=_user_id(me),
                actor_name=actor_name(me),
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            oid = int(user_org_id(me))
            audits = list_cash_payout_audits(cursor, oid, payout_id)
            return jsonify(json_safe_rinse({"audits": audits}))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/revenue/dhs", methods=["PUT"])
    def management_revenue_dhs_save():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            oid = int(user_org_id(me))
            denied = _gate(cursor, me, oid)
            if denied:
                return denied
            employee = not is_hub_manager(me)
            body = request.get_json(silent=True) or {}
            raw_date = (body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            payload = save_dhs_account_revenue(
                cursor,
                oid,
                selected,
                body.get("accounts") or [],
                user_id=_user_id(me),
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

    @app.route("/api/management/revenue/dashboard", methods=["GET"])
    def management_revenue_dashboard():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            oid = int(user_org_id(me))
            period = (request.args.get("period") or "today").strip().lower()
            raw_date = (request.args.get("date") or request.args.get("date_et") or "").strip()
            ref = parse_date_value(raw_date) if raw_date else business_today()
            raw_start = (request.args.get("start") or "").strip()
            raw_end = (request.args.get("end") or "").strip()
            start = parse_date_value(raw_start) if raw_start else None
            end = parse_date_value(raw_end) if raw_end else None
            payload = build_revenue_dashboard(cursor, oid, period, ref, start, end)
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
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
