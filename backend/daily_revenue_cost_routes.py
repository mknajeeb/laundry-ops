"""Daily Revenue & Cost API routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.daily_revenue_cost import (
    build_dashboard,
    change_entry_workflow,
    create_commercial_account,
    get_cost_settings,
    get_daily_entry,
    get_rinse_wf_tiers,
    list_commercial_accounts,
    preview_entry_calculations,
    save_cost_settings,
    save_daily_entry,
    save_rinse_wf_tiers,
    update_commercial_account,
)
from backend.rinse_scan_time import json_safe_rinse


def _drc_access_error(cursor, me, user_org_id):
    """
    Manager/admin path unchanged (ADMIN+).
    Employee PIN path: Mobile PIN Access revenue_cost is sufficient — no second
    Washpro ADMIN/role grant required for the same PIN module.
    """
    rs = {str(r).upper() for r in (me.get("roles") or [])}
    if rs & {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"}:
        return None, None
    from backend.employee_mobile_pin_access import (
        DENIED_MODULE_MESSAGE,
        MobilePinAccessDeniedError,
        assert_employee_allows_module,
    )

    try:
        assert_employee_allows_module(
            cursor, int(user_org_id(me)), int(me["user_id"]), "revenue_cost"
        )
        return None, None
    except MobilePinAccessDeniedError:
        return jsonify({"error": DENIED_MODULE_MESSAGE}), 403


def register_daily_revenue_cost_routes(
    app,
    *,
    require_user,
    require_admin,
    user_org_id,
    parse_date_value,
) -> None:
    # require_admin kept for register() signature compatibility; access via _require_drc.
    _ = require_admin

    def _parse_entry_date(raw: str | None) -> date:
        if not raw:
            return business_today()
        return parse_date_value(raw.strip())

    def _require_drc(cursor):
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return None, err_resp, err_code
        err_body, err_code2 = _drc_access_error(cursor, me, user_org_id)
        if err_body is not None:
            return None, err_body, err_code2
        return me, None, None

    @app.route("/finance/daily-revenue-cost/cost-settings", methods=["GET", "PUT"])
    def finance_drc_cost_settings():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            if request.method == "GET":
                return jsonify(json_safe_rinse(get_cost_settings(cursor, tenant_oid)))
            data = request.get_json(silent=True) or {}
            out = save_cost_settings(cursor, tenant_oid, data, user_id=user_id)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/commercial-accounts", methods=["GET", "POST"])
    def finance_drc_commercial_accounts():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            if request.method == "GET":
                active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
                out = list_commercial_accounts(cursor, tenant_oid, active_only=active_only)
                conn.commit()
                return jsonify(json_safe_rinse(out))
            data = request.get_json(silent=True) or {}
            out = create_commercial_account(cursor, tenant_oid, data, user_id=user_id)
            conn.commit()
            return jsonify(json_safe_rinse(out)), 201
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/commercial-accounts/<int:account_id>", methods=["PUT"])
    def finance_drc_commercial_account_update(account_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            data = request.get_json(silent=True) or {}
            out = update_commercial_account(cursor, tenant_oid, account_id, data, user_id=user_id)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except LookupError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 404
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/rinse-wf-tiers", methods=["GET", "PUT"])
    def finance_drc_rinse_wf_tiers():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            if request.method == "GET":
                out = get_rinse_wf_tiers(cursor, tenant_oid)
                conn.commit()
                return jsonify(json_safe_rinse(out))
            data = request.get_json(silent=True) or {}
            tiers = data.get("tiers") if isinstance(data.get("tiers"), list) else data
            out = save_rinse_wf_tiers(cursor, tenant_oid, tiers, user_id=user_id)
            conn.commit()
            return jsonify(json_safe_rinse({"tiers": out}))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/entries/<entry_date>", methods=["GET", "PUT"])
    def finance_drc_daily_entry(entry_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            try:
                target_date = _parse_entry_date(entry_date)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400
            if not isinstance(target_date, date):
                return jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400
            if request.method == "GET":
                out = get_daily_entry(cursor, tenant_oid, target_date)
                conn.commit()
                return jsonify(json_safe_rinse(out))
            data = request.get_json(silent=True) or {}
            out = save_daily_entry(cursor, tenant_oid, target_date, data, user_id=user_id)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/entries/<entry_date>/preview", methods=["POST"])
    def finance_drc_daily_entry_preview(entry_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            try:
                target_date = _parse_entry_date(entry_date)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400
            data = request.get_json(silent=True) or {}
            exclude_id = data.get("exclude_entry_id")
            out = preview_entry_calculations(
                cursor,
                tenant_oid,
                target_date,
                data,
                exclude_entry_id=int(exclude_id) if exclude_id else None,
            )
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/entries/<entry_date>/workflow", methods=["POST"])
    def finance_drc_entry_workflow(entry_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            user_id = int(me["user_id"]) if me.get("user_id") else None
            try:
                target_date = _parse_entry_date(entry_date)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400
            data = request.get_json(silent=True) or {}
            action = (data.get("action") or "").strip().lower()
            out = change_entry_workflow(
                cursor, tenant_oid, target_date, action,
                user_id=user_id, notes=data.get("notes"),
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except LookupError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 404
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/dashboard", methods=["GET"])
    def finance_drc_dashboard():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = _require_drc(cursor)
            if err_resp:
                return err_resp, err_code
            tenant_oid = user_org_id(me)
            period = (request.args.get("period") or "daily").strip().lower()
            ref_raw = (request.args.get("date") or "").strip()
            start_raw = (request.args.get("start_date") or "").strip()
            end_raw = (request.args.get("end_date") or "").strip()
            try:
                ref_date = _parse_entry_date(ref_raw) if ref_raw else business_today()
                start_date = parse_date_value(start_raw) if start_raw else None
                end_date = parse_date_value(end_raw) if end_raw else None
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid date parameters"}), 400
            out = build_dashboard(cursor, tenant_oid, period, ref_date, start_date, end_date)
            return jsonify(json_safe_rinse(out))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
