"""Management Hub TODAY compact API."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_today import (
    CountingCursor,
    build_management_rinse_wf_payload,
    build_management_supply_summary,
    build_management_today_payload,
)
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def register_management_today_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _selected_date_et():
        raw_date = (request.args.get("date_et") or "").strip()
        if raw_date:
            try:
                selected = parse_date_value(raw_date)
            except (TypeError, ValueError):
                return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        else:
            selected = business_today()
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        return selected, None

    @app.route("/api/management/today", methods=["GET"])
    def management_today():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            bypass = str(request.args.get("refresh") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            counting = CountingCursor(cursor)
            payload = build_management_today_payload(
                counting,
                oid,
                selected,
                bypass_cache=bypass,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/today/supplies", methods=["GET"])
    def management_today_supplies():
        """Async compact Supply Usage summary — never block WF core."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            bypass = str(request.args.get("refresh") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            counting = CountingCursor(cursor)
            payload = build_management_supply_summary(
                counting,
                oid,
                selected,
                bypass_cache=bypass,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc), "supplies": {"available": False, "deferred": False}}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-wf", methods=["GET"])
    def management_rinse_wf():
        """Rinse WF compartment core — WF headline + weights only (no HD/labor/supplies)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            bypass = str(request.args.get("refresh") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            counting = CountingCursor(cursor)
            payload = build_management_rinse_wf_payload(
                counting,
                oid,
                selected,
                bypass_cache=bypass,
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
