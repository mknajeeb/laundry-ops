"""Management Hub — WF Folder Performance APIs (compartment: Performance)."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_wf_folder_attribution import (
    move_bag_attribution,
    reset_bag_attribution,
)
from backend.management_wf_folder_performance import (
    DEFAULT_LAST_N_SESSIONS,
    build_day_folder_performance,
    build_folder_performance_dashboard,
    find_bag_attribution_context,
    get_session_orders,
    list_move_destinations,
)
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
HUB_WRITE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def register_management_wf_folder_performance_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _selected_date_et(raw: str | None = None):
        value = (raw if raw is not None else (request.args.get("date_et") or "")).strip()
        if value:
            try:
                selected = parse_date_value(value)
            except (TypeError, ValueError):
                return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        else:
            selected = business_today()
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        return selected, None

    def _parse_optional_date(raw: str | None):
        value = str(raw or "").strip()
        if not value:
            return None, None
        try:
            selected = parse_date_value(value)
        except (TypeError, ValueError):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        return selected, None

    @app.route("/api/management/performance/wf-folder", methods=["GET"])
    def management_wf_folder_performance():
        """Summary-first Folder Performance dashboard (Performance compartment only)."""
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
            compare = (request.args.get("compare") or "today").strip().lower()
            try:
                last_n = int(request.args.get("last_n") or DEFAULT_LAST_N_SESSIONS)
            except (TypeError, ValueError):
                last_n = DEFAULT_LAST_N_SESSIONS
            custom_start, err_cs = _parse_optional_date(request.args.get("start_et"))
            if err_cs:
                return err_cs
            custom_end, err_ce = _parse_optional_date(request.args.get("end_et"))
            if err_ce:
                return err_ce
            payload = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare=compare,
                last_n=last_n,
                custom_start=custom_start,
                custom_end=custom_end,
            )
            return jsonify(json_safe_rinse(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/wf-folder/sessions/<session_id>/orders",
        methods=["GET"],
    )
    def management_wf_folder_session_orders(session_id: str):
        """Lazy session order drill-down — no full scan chronology."""
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
            payload = get_session_orders(
                cursor,
                oid,
                selected_date_et=selected,
                session_id=session_id,
            )
            if payload.get("error") == "session_not_found":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/unmapped", methods=["GET"])
    def management_wf_folder_unmapped():
        """Folder Performance exception queues (Needs Attribution + Outside Session)."""
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
            day = build_day_folder_performance(
                cursor,
                oid,
                selected_date_et=selected,
                attach_customers=True,
            )
            return jsonify(
                json_safe_rinse(
                    {
                        "selected_date_et": selected.isoformat(),
                        "needs_attribution_count": day.get("needs_attribution_count")
                        or 0,
                        "needs_attribution_orders": day.get("needs_attribution_orders")
                        or [],
                        "outside_folder_session_count": day.get(
                            "outside_folder_session_count"
                        )
                        or 0,
                        "outside_folder_session_orders": day.get(
                            "outside_folder_session_orders"
                        )
                        or [],
                        "unmapped_count": day.get("unmapped_count") or 0,
                        "orders": day.get("unmapped_orders") or [],
                    }
                )
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/destinations", methods=["GET"])
    def management_wf_folder_destinations():
        """Move picker: mapped users with activity on the selected ET day only."""
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
            payload = list_move_destinations(
                cursor, oid, selected_date_et=selected
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/attribution/move", methods=["POST"])
    def management_wf_folder_attribution_move():
        """Move one or many orders to a destination employee/session (auditable)."""
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
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            bag_ids_raw = body.get("bag_ids") or body.get("bag_id")
            if isinstance(bag_ids_raw, str):
                bag_ids = [bag_ids_raw]
            elif isinstance(bag_ids_raw, list):
                bag_ids = [str(b) for b in bag_ids_raw if b]
            else:
                bag_ids = []
            bag_ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
            if not bag_ids:
                return jsonify({"error": "bag_ids required"}), 400
            to_employee = (body.get("to_employee") or body.get("employee") or "").strip()
            if not to_employee:
                return jsonify({"error": "to_employee required"}), 400
            to_session_id = body.get("to_session_id") or body.get("session_id")
            to_segment_id = body.get("to_segment_id") or body.get("segment_id")
            try:
                seg_id = (
                    int(to_segment_id)
                    if to_segment_id is not None and to_segment_id != ""
                    else None
                )
            except (TypeError, ValueError):
                seg_id = None
            note = body.get("note")
            actor_name = None
            if isinstance(me, dict):
                actor_name = (
                    me.get("name")
                    or me.get("display_name")
                    or me.get("email")
                    or me.get("username")
                )
            actor_id = me.get("id") if isinstance(me, dict) else None

            day = build_day_folder_performance(
                cursor, oid, selected_date_et=selected, attach_customers=False
            )
            results = []
            for bid in bag_ids:
                ctx = find_bag_attribution_context(day, bid)
                if not ctx:
                    results.append({"bag_id": bid, "ok": False, "error": "bag_not_found"})
                    continue
                original = (
                    ctx.get("original_scanner")
                    or ctx.get("original_employee_name")
                    or ctx.get("credited_employee")
                    or ctx.get("employee")
                    or "Unknown"
                )
                row = move_bag_attribution(
                    cursor,
                    oid,
                    bag_id=bid,
                    selected_date_et=selected,
                    original_employee_name=str(original),
                    original_scanner_name=str(
                        ctx.get("original_scanner") or original
                    ),
                    original_completion_et=ctx.get("completion_time")
                    or ctx.get("completion_timestamp")
                    or ctx.get("completion_time_et"),
                    from_employee_name=ctx.get("effective_employee")
                    or ctx.get("credited_employee")
                    or ctx.get("employee"),
                    from_session_id=ctx.get("session_id"),
                    to_employee_name=to_employee,
                    to_session_id=to_session_id,
                    to_segment_id=seg_id,
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                    note=note,
                )
                results.append({"ok": True, **row})
            conn.commit()

            # Recalculate immediately after reassignment
            refreshed = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare="today",
                include_baseline_delta=False,
            )
            return jsonify(
                json_safe_rinse(
                    {
                        "ok": True,
                        "moved": sum(1 for r in results if r.get("ok")),
                        "results": results,
                        "dashboard": refreshed,
                    }
                )
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/attribution/reset", methods=["POST"])
    def management_wf_folder_attribution_reset():
        """Reset override(s) back to original scanner attribution."""
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
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            bag_ids_raw = body.get("bag_ids") or body.get("bag_id")
            if isinstance(bag_ids_raw, str):
                bag_ids = [bag_ids_raw]
            elif isinstance(bag_ids_raw, list):
                bag_ids = [str(b) for b in bag_ids_raw if b]
            else:
                bag_ids = []
            bag_ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
            if not bag_ids:
                return jsonify({"error": "bag_ids required"}), 400
            actor_name = None
            if isinstance(me, dict):
                actor_name = (
                    me.get("name")
                    or me.get("display_name")
                    or me.get("email")
                    or me.get("username")
                )
            actor_id = me.get("id") if isinstance(me, dict) else None
            results = []
            for bid in bag_ids:
                row = reset_bag_attribution(
                    cursor,
                    oid,
                    bag_id=bid,
                    selected_date_et=selected,
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                    note=body.get("note"),
                )
                results.append({"ok": True, **row})
            conn.commit()
            refreshed = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare="today",
                include_baseline_delta=False,
            )
            return jsonify(
                json_safe_rinse(
                    {
                        "ok": True,
                        "reset": sum(1 for r in results if r.get("reset")),
                        "results": results,
                        "dashboard": refreshed,
                    }
                )
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
