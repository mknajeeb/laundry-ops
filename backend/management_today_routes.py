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

    @app.route("/api/management/rinse-wf/review", methods=["GET"])
    def management_rinse_wf_review_list():
        """Lightweight Review list — Specialty Items or Missing From Portal."""
        from backend.management_rinse_wf_review import build_management_review_list

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
            category = (request.args.get("category") or "").strip()
            rush = (request.args.get("rush") or request.args.get("rush_filter") or "all").strip()
            try:
                page = int(request.args.get("page") or 1)
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = int(request.args.get("page_size") or 50)
            except (TypeError, ValueError):
                page_size = 50
            counting = CountingCursor(cursor)
            payload = build_management_review_list(
                counting,
                oid,
                selected,
                category=category,
                rush_filter=rush,
                page=page,
                page_size=page_size,
            )
            if payload.get("ok") is False:
                return jsonify(json_safe_rinse(payload)), 400
            meta = dict(payload.get("_meta") or {})
            meta["query_count"] = int(getattr(counting, "query_count", 0))
            payload["_meta"] = meta
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-wf/review/<bag_id>", methods=["GET"])
    def management_rinse_wf_review_detail(bag_id: str):
        """On-demand Review modal core for ONE bag (scans optional / default off)."""
        from backend.management_rinse_wf_review import build_management_review_detail

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
            include_scans_raw = (
                request.args.get("include_scans")
                or request.args.get("scans")
                or "0"
            ).strip().lower()
            include_scans = include_scans_raw in ("1", "true", "yes", "on")
            counting = CountingCursor(cursor)
            payload = build_management_review_detail(
                counting,
                oid,
                selected,
                bag_id,
                include_scans=include_scans,
            )
            if payload.get("ok") is False:
                code = 404 if payload.get("error") == "bag_not_found" else 400
                return jsonify(json_safe_rinse(payload)), code
            meta = dict(payload.get("_meta") or {})
            meta["query_count"] = int(getattr(counting, "query_count", 0))
            payload["_meta"] = meta
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-wf/review/<bag_id>/scans", methods=["GET"])
    def management_rinse_wf_review_scans(bag_id: str):
        """Async scan chronology for ONE Review bag — does not block modal core."""
        from backend.management_rinse_wf_review import build_management_review_scans

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            counting = CountingCursor(cursor)
            payload = build_management_review_scans(counting, oid, bag_id)
            if payload.get("ok") is False:
                return jsonify(json_safe_rinse(payload)), 400
            meta = dict(payload.get("_meta") or {})
            meta["query_count"] = int(getattr(counting, "query_count", 0))
            payload["_meta"] = meta
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-wf/review/<bag_id>/split-decision", methods=["POST"])
    def management_rinse_wf_split_decision(bag_id: str):
        """MARK AS SPLIT / MARK AS NOT SPLIT — persists; survives rebuild."""
        import json as _json

        from backend.management_today import clear_management_today_cache
        from backend.rinse_veewash_shift_day import (
            _reproject_specialty_metrics_on_headline,
            get_day_record,
        )
        from backend.rinse_wf_canonical_split import (
            invalidate_supply_after_split_resolution,
            save_manager_split_decision,
        )

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
            body = request.get_json(silent=True) or {}
            decision = body.get("decision") or body.get("manager_split_decision")
            note = body.get("note") or body.get("manager_split_decision_note")
            display = (
                me.get("display_name")
                or me.get("full_name")
                or me.get("email")
                or me.get("username")
            )
            result = save_manager_split_decision(
                cursor,
                oid,
                selected,
                bag_id,
                decision=str(decision or ""),
                note=note,
                decided_by_user_id=me.get("id") or me.get("user_id"),
                decided_by_display_name=str(display) if display else None,
            )
            if not result.get("ok"):
                return jsonify(json_safe_rinse(result)), 400
            day = get_day_record(cursor, oid, selected)
            if day:
                try:
                    headline = _reproject_specialty_metrics_on_headline(
                        cursor, oid, selected, dict(day.get("headline") or {})
                    )
                    cursor.execute(
                        """
                        UPDATE rinse_shift_monitor_days
                        SET headline_json = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE organization_id = %s AND shift_date_et = %s
                        """,
                        (_json.dumps(headline, default=str), int(oid), selected),
                    )
                except Exception:
                    pass
            invalidate_supply_after_split_resolution(oid, selected)
            conn.commit()
            clear_management_today_cache(oid, selected, include_supplies=True)
            return jsonify(json_safe_rinse({"ok": True, **result}))
        except Exception as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
