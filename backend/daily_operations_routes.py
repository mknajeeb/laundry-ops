"""Daily Operations Phase 1A/1B API routes."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.daily_operations import (
    build_daily_operations_day,
    compare_daily_operations_to_finance_drc,
    daily_operations_enabled_for_org,
)
from backend.daily_operations_wf_review import (
    build_wf_review_queue,
    get_wf_review_detail,
    preview_wf_review_save,
    save_wf_review,
    undo_wf_review,
)
from backend.db import get_db
from backend.rinse_scan_time import json_safe_rinse

DAILY_OPS_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
DAILY_OPS_SAVE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
DAILY_OPS_UNDO_ROLES = frozenset({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN"})
DAILY_OPS_PRICING_ROLES = frozenset({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _require_roles(me: dict, allowed: frozenset[str]):
    if not (_role_set(me) & allowed):
        return jsonify({"error": "Forbidden"}), 403
    return None, None


def _actor_name(me: dict) -> str | None:
    return (me.get("display_name") or me.get("username") or None)


def register_daily_operations_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _parse_ops_date(raw: str | None) -> date:
        if not raw:
            return business_today()
        return parse_date_value(str(raw).strip())

    @app.route("/api/daily-operations/meta", methods=["GET"])
    def daily_operations_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            return jsonify(
                json_safe_rinse(
                    {
                        "enabled": daily_operations_enabled_for_org(oid),
                        "organization_id": oid,
                        "tracking_started_et": "2026-07-23",
                        "message": "Daily Operations tracking started July 23, 2026.",
                        "phase": "1B",
                        "links": {
                            "workitem_maintenance": "/performance/settings",
                            "wf_rate_maintenance": "/finance/daily-revenue-cost",
                        },
                    }
                )
            )
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/daily-operations/days/<ops_date>", methods=["GET"])
    def daily_operations_day(ops_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            persist = str(request.args.get("persist") or "1").lower() not in ("0", "false", "no")
            out = build_daily_operations_day(
                cursor,
                oid,
                day,
                persist=persist,
                user_id=int(me["user_id"]) if me.get("user_id") else None,
            )
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

    @app.route("/api/daily-operations/days/<ops_date>/compare-finance", methods=["GET"])
    def daily_operations_compare_finance(ops_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            out = compare_daily_operations_to_finance_drc(cursor, oid, day)
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

    @app.route("/api/daily-operations/days/<ops_date>/wf-review", methods=["GET"])
    def daily_operations_wf_review_queue(ops_date: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            filter_key = str(request.args.get("filter") or "all")
            out = build_wf_review_queue(cursor, oid, day, filter_key=filter_key)
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

    @app.route("/api/daily-operations/days/<ops_date>/wf-review/<bag_id>", methods=["GET"])
    def daily_operations_wf_review_detail(ops_date: str, bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            out = get_wf_review_detail(cursor, oid, day, bag_id)
            status = 404 if not out.get("ok") else 200
            conn.commit()
            return jsonify(json_safe_rinse(out)), status
        except ValueError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/daily-operations/days/<ops_date>/wf-review/<bag_id>/preview", methods=["POST"])
    def daily_operations_wf_review_preview(ops_date: str, bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_READ_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            payload = request.get_json(silent=True) or {}
            out = preview_wf_review_save(cursor, oid, day, bag_id, payload)
            status = 400 if not out.get("ok") else 200
            return jsonify(json_safe_rinse(out)), status
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/daily-operations/days/<ops_date>/wf-review/<bag_id>", methods=["PUT"])
    def daily_operations_wf_review_save(ops_date: str, bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_SAVE_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            payload = request.get_json(silent=True) or {}
            out = save_wf_review(
                cursor,
                oid,
                day,
                bag_id,
                payload,
                actor_user_id=int(me["user_id"]) if me.get("user_id") else None,
                actor_display_name=_actor_name(me),
            )
            if not out.get("ok"):
                conn.rollback()
                status = int(out.get("status") or 400)
                if out.get("error") == "conflict":
                    status = 409
                return jsonify(json_safe_rinse(out)), status
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

    @app.route("/api/daily-operations/days/<ops_date>/wf-review/<bag_id>/undo", methods=["POST"])
    def daily_operations_wf_review_undo(ops_date: str, bag_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            forbidden = _require_roles(me, DAILY_OPS_UNDO_ROLES)
            if forbidden[0]:
                return forbidden
            oid = int(user_org_id(me))
            day = _parse_ops_date(ops_date)
            payload = request.get_json(silent=True) or {}
            out = undo_wf_review(
                cursor,
                oid,
                day,
                bag_id,
                reason=str(payload.get("reason") or ""),
                actor_user_id=int(me["user_id"]) if me.get("user_id") else None,
                actor_display_name=_actor_name(me),
            )
            if not out.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(out)), 400
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
