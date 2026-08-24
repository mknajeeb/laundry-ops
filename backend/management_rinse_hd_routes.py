"""Management Hub — Rinse HD routes (wash → fold → entry → Complete).

Managers and PIN employees with Mobile PIN Access ``revenue_cost`` share the
same Hang Dry production APIs / ``hd_day_bag_production`` records.
Mobile should request ``status=awaiting_entry``.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_hd_performance import (
    build_hd_employee_performance,
    build_hd_employee_performance_detail,
)
from backend.management_pin_access import (
    access_denied_payload,
    actor_name,
    allows_management_revenue_pin,
    is_hub_manager,
)
from backend.management_rinse_hd import (
    apply_rinse_hd_processing_correction,
    build_rinse_hd_day,
    build_rinse_hd_summary,
    get_rinse_hd_order_detail,
    mark_rinse_hd_complete,
    run_hd_activation_reset,
    save_rinse_hd_items_revenue,
    update_rinse_hd_attribution,
)
from backend.rinse_scan_time import json_safe_rinse


def register_management_rinse_hd_routes(
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
            # Employees may still pass date_et for backfill when authorized via PIN;
            # default remains business today.
            if raw:
                selected = parse_date_value(raw)
                if isinstance(selected, date):
                    return selected
            return business_today()
        selected = parse_date_value(raw) if raw else business_today()
        if not isinstance(selected, date):
            raise ValueError("Invalid date_et; use YYYY-MM-DD")
        return selected

    def _actor_user_id(me: dict):
        return me.get("user_id") or me.get("id")

    def _period_bounds(period: str, start_raw: str, end_raw: str, today: date):
        key = str(period or "today").strip().lower()
        if key == "yesterday":
            return today - timedelta(days=1), today - timedelta(days=1)
        if key == "week":
            return today - timedelta(days=6), today
        if key == "month":
            return today.replace(day=1), today
        if key == "custom":
            start = parse_date_value(start_raw) if start_raw else today
            end = parse_date_value(end_raw) if end_raw else today
            if not isinstance(start, date) or not isinstance(end, date):
                raise ValueError("Invalid custom range")
            if end < start:
                start, end = end, start
            return start, end
        return today, today

    @app.route("/api/management/rinse-hd", methods=["GET"])
    def management_rinse_hd_day():
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
            status = (request.args.get("status") or "all").strip().lower()
            # Mobile default: only awaiting entry
            if employee and status in ("", "all") and request.args.get("mobile") == "1":
                status = "awaiting_entry"
            payload = build_rinse_hd_day(cursor, oid, selected, status=status)
            # Durable admit / scan persist may write during list read.
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/activation-reset", methods=["POST"])
    def management_rinse_hd_activation_reset():
        """Manager-only: soft-quarantine pre-activation HD rows + seed opening day."""
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("opening_date_et") or body.get("date_et") or "").strip()
            opening = None
            if raw_date:
                try:
                    opening = _selected_date(raw_date, employee=False)
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 400
            scrape_run_id = body.get("scrape_run_id")
            try:
                scrape_run_id = int(scrape_run_id) if scrape_run_id not in (None, "") else None
            except (TypeError, ValueError):
                scrape_run_id = None
            result = run_hd_activation_reset(
                cursor,
                oid,
                opening_date_et=opening,
                scrape_run_id=scrape_run_id,
                actor_user_id=_actor_user_id(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), 400
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/summary", methods=["GET"])
    def management_rinse_hd_summary():
        """Lazy/parallel summary — does not block the operational list."""
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
            today = business_today()
            try:
                start, end = _period_bounds(
                    request.args.get("period") or "today",
                    (request.args.get("start_et") or "").strip(),
                    (request.args.get("end_et") or "").strip(),
                    today,
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            raw_snapshot = (request.args.get("date_et") or "").strip()
            snapshot = parse_date_value(raw_snapshot) if raw_snapshot else end
            if not isinstance(snapshot, date):
                snapshot = end
            payload = build_rinse_hd_summary(
                cursor,
                oid,
                start_et=start,
                end_et=end,
                snapshot_date_et=snapshot,
            )
            conn.commit()
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/performance", methods=["GET"])
    def management_rinse_hd_performance():
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            raw_date = (request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=False)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            summary_only = str(request.args.get("summary") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            payload = build_hd_employee_performance(
                cursor, oid, selected, summary_only=summary_only
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/performance/employees/<int:user_id>", methods=["GET"])
    def management_rinse_hd_performance_employee(user_id: int):
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            raw_date = (request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=False)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            payload = build_hd_employee_performance_detail(
                cursor, oid, selected, int(user_id)
            )
            if not payload.get("ok"):
                return jsonify(json_safe_rinse(payload)), int(payload.get("status") or 404)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>", methods=["GET"])
    def management_rinse_hd_detail(bag_id: str):
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
            payload = get_rinse_hd_order_detail(cursor, oid, bag_id, selected_date_et=selected)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/production", methods=["PUT"])
    def management_rinse_hd_production(bag_id: str):
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
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = save_rinse_hd_items_revenue(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                total_items=body.get("total_items"),
                revenue=body.get("revenue"),
                version=int(body.get("version") or 0),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/mark-complete", methods=["POST"])
    def management_rinse_hd_mark_complete(bag_id: str):
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
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=employee)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = mark_rinse_hd_complete(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                version=int(body.get("version") or 0),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/processing", methods=["POST"])
    def management_rinse_hd_processing(bag_id: str):
        """Manager-only wash/fold/entry processing corrections with audit."""
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=False)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = apply_rinse_hd_processing_correction(
                cursor,
                oid,
                bag_id,
                action=body.get("action") or "",
                selected_date_et=selected,
                version=int(body.get("version") or 0),
                employee_user_id=body.get("employee_user_id"),
                operational_at=body.get("operational_at"),
                confirm_remove=bool(body.get("confirm_remove")),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/attribution", methods=["PUT"])
    def management_rinse_hd_attribution(bag_id: str):
        """Manager-only wash/fold attribution edit with audit."""
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or request.args.get("date_et") or "").strip()
            try:
                selected = _selected_date(raw_date, employee=False)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            result = update_rinse_hd_attribution(
                cursor,
                oid,
                bag_id,
                selected_date_et=selected,
                version=int(body.get("version") or 0),
                washed_by_user_id=body.get("washed_by_user_id"),
                washed_at=body.get("washed_at"),
                folded_by_user_id=body.get("folded_by_user_id"),
                folded_at=body.get("folded_at"),
                actor_user_id=_actor_user_id(me),
                actor_display_name=actor_name(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/fresh-start", methods=["POST"])
    def management_rinse_hd_fresh_start():
        """Manager-only: HD workflow fresh start — retain Pending Wash only."""
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            from backend.hd_workflow_extensions import run_hd_fresh_start

            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or "").strip()
            selected = None
            if raw_date:
                try:
                    selected = _selected_date(raw_date, employee=False)
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 400
            result = run_hd_fresh_start(
                cursor,
                oid,
                actor_user_id=_actor_user_id(me),
                selected_date_et=selected,
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), 400
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/exclude", methods=["POST"])
    def management_rinse_hd_exclude(bag_id: str):
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            from backend.hd_workflow_extensions import exclude_hd_order

            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or "").strip()
            selected = business_today()
            if raw_date:
                try:
                    selected = _selected_date(raw_date, employee=False)
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 400
            result = exclude_hd_order(
                cursor,
                oid,
                bag_id,
                reason=body.get("reason"),
                note=body.get("note"),
                actor_user_id=_actor_user_id(me),
                actor_name=actor_name(me),
                selected_date_et=selected,
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), 400
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/<bag_id>/restore", methods=["POST"])
    def management_rinse_hd_restore(bag_id: str):
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            from backend.hd_workflow_extensions import restore_hd_order

            body = request.get_json(silent=True) or {}
            raw_date = str(body.get("date_et") or "").strip()
            selected = business_today()
            if raw_date:
                try:
                    selected = _selected_date(raw_date, employee=False)
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 400
            result = restore_hd_order(
                cursor,
                oid,
                bag_id,
                actor_user_id=_actor_user_id(me),
                selected_date_et=selected,
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), 400
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/rinse-hd/permanent-delete", methods=["POST"])
    def management_rinse_hd_permanent_delete():
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
            if not is_hub_manager(me):
                body, code = access_denied_payload()
                return jsonify(body), code
            from backend.hd_workflow_extensions import permanent_delete_hd_orders

            body = request.get_json(silent=True) or {}
            bag_ids = body.get("bag_ids") or body.get("bag_id")
            if isinstance(bag_ids, str):
                bag_ids = [bag_ids]
            if not isinstance(bag_ids, list):
                return jsonify({"error": "bag_ids required"}), 400
            result = permanent_delete_hd_orders(
                cursor,
                oid,
                bag_ids,
                actor_user_id=_actor_user_id(me),
            )
            if not result.get("ok"):
                conn.rollback()
                return jsonify(json_safe_rinse(result)), 400
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
