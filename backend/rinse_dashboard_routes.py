"""Rinse Hub external-safe APIs — approved Performance snapshots only."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.rinse_dashboard_analytics import (
    build_daily_board,
    build_employee_period_history,
    build_performance_overview,
    build_role_period_board,
    build_roles_summary,
)
from backend.rinse_dashboard_performance import (
    build_employee_detail,
    build_employee_role_history,
    build_employees_list,
    build_rinse_meta,
    build_role_leaderboard,
)
from backend.rinse_dashboard_period import PeriodResolutionError
from backend.rinse_performance_employee_day import (
    ensure_employee_day_publications_for_range,
    ensure_employee_day_publications_for_week,
)
from backend.rinse_scan_time import json_safe_rinse
from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

RINSE_READ_ROLES = frozenset(
    {"RINSE", "ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"}
)
HUB_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _can_read_rinse_dashboard(me: dict) -> bool:
    roles = _role_set(me)
    if roles & HUB_ROLES:
        return True
    if roles & {"RINSE"}:
        return True
    return is_rinse_schedule_viewer(list(roles))


def _ensure_week_pubs(cursor, oid: int, *, role_key: str, week_start: date | None):
    """Self-healing publication cache before Rinse reads (no Management page visit)."""
    try:
        return ensure_employee_day_publications_for_week(
            cursor,
            oid,
            role_key=role_key,
            week_start=week_start,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "synced_count": 0}


def _ensure_range_pubs(
    cursor,
    oid: int,
    *,
    role_key: str,
    date_start: date,
    date_end: date,
):
    try:
        return ensure_employee_day_publications_for_range(
            cursor,
            oid,
            role_key=role_key,
            date_start=date_start,
            date_end=date_end,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "synced_count": 0}


def _parse_week_start(raw: str | None, parse_date_value) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return parse_date_value(value)


def _parse_opt_date(raw: str | None, parse_date_value) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return parse_date_value(value)


def _period_args(parse_date_value) -> dict:
    return {
        "period": (request.args.get("period") or "").strip() or None,
        "start": _parse_opt_date(request.args.get("start"), parse_date_value),
        "end": _parse_opt_date(request.args.get("end"), parse_date_value),
        "week_start": _parse_week_start(request.args.get("week_start"), parse_date_value),
        "compare": (request.args.get("compare") or "").strip() or None,
        "metric": (request.args.get("metric") or "").strip() or None,
    }


def _attach_ensure(payload: dict, ensure_meta: dict) -> dict:
    if isinstance(payload.get("perf"), dict):
        from backend.rinse_dashboard_performance import payload_bytes

        payload["perf"]["payload_bytes"] = payload_bytes(payload)
        payload["perf"]["publication_ensure"] = ensure_meta
    payload["publication_ensure"] = ensure_meta
    return payload


def register_rinse_dashboard_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    @app.route("/api/rinse-dashboard/meta", methods=["GET"])
    def rinse_dashboard_meta():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            payload = build_rinse_meta(cursor, oid)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/overview", methods=["GET"])
    def rinse_dashboard_overview():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            args = _period_args(parse_date_value)
            role_key = (request.args.get("role_key") or "FOLDER").strip().upper()
            from backend.rinse_dashboard_period import resolve_period_and_compare

            windows = resolve_period_and_compare(
                period=args["period"],
                start=args["start"],
                end=args["end"],
                week_start=args["week_start"],
                compare=args["compare"],
            )
            ensure_meta = _ensure_range_pubs(
                cursor,
                oid,
                role_key=role_key,
                date_start=windows["ensure_start"],
                date_end=windows["ensure_end"],
            )
            try:
                conn.commit()
            except Exception:
                pass
            payload = build_performance_overview(
                cursor,
                oid,
                role_key=role_key,
                period=args["period"],
                start=args["start"],
                end=args["end"],
                week_start=args["week_start"],
                compare=args["compare"],
                metric=args["metric"],
            )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(_attach_ensure(payload, ensure_meta)))
        except PeriodResolutionError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/roles", methods=["GET"])
    def rinse_dashboard_roles_summary():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            args = _period_args(parse_date_value)
            from backend.rinse_dashboard_period import resolve_period_and_compare

            windows = resolve_period_and_compare(
                period=args["period"],
                start=args["start"],
                end=args["end"],
                week_start=args["week_start"],
                compare=args["compare"],
            )
            ensure_meta = _ensure_range_pubs(
                cursor,
                oid,
                role_key="FOLDER",
                date_start=windows["ensure_start"],
                date_end=windows["ensure_end"],
            )
            try:
                conn.commit()
            except Exception:
                pass
            payload = build_roles_summary(
                cursor,
                oid,
                period=args["period"],
                start=args["start"],
                end=args["end"],
                week_start=args["week_start"],
                compare=args["compare"],
                metric=args["metric"],
            )
            return jsonify(json_safe_rinse(_attach_ensure(payload, ensure_meta)))
        except PeriodResolutionError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/roles/<role_key>", methods=["GET"])
    def rinse_dashboard_role_leaderboard(role_key: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            args = _period_args(parse_date_value)
            use_period = bool(args["period"] or args["start"] or args["compare"])
            if use_period:
                from backend.rinse_dashboard_period import resolve_period_and_compare

                windows = resolve_period_and_compare(
                    period=args["period"],
                    start=args["start"],
                    end=args["end"],
                    week_start=args["week_start"],
                    compare=args["compare"],
                )
                ensure_meta = _ensure_range_pubs(
                    cursor,
                    oid,
                    role_key=role_key,
                    date_start=windows["ensure_start"],
                    date_end=windows["ensure_end"],
                )
                try:
                    conn.commit()
                except Exception:
                    pass
                payload = build_role_period_board(
                    cursor,
                    oid,
                    role_key=role_key,
                    period=args["period"],
                    start=args["start"],
                    end=args["end"],
                    week_start=args["week_start"],
                    compare=args["compare"],
                    metric=args["metric"],
                )
            else:
                week_start = args["week_start"]
                ensure_meta = _ensure_week_pubs(
                    cursor, oid, role_key=role_key, week_start=week_start
                )
                try:
                    conn.commit()
                except Exception:
                    pass
                payload = build_role_leaderboard(
                    cursor,
                    oid,
                    role_key=role_key,
                    week_start=week_start,
                    metric=args["metric"],
                )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(_attach_ensure(payload, ensure_meta)))
        except PeriodResolutionError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/daily", methods=["GET"])
    def rinse_dashboard_daily():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            raw_date = (request.args.get("date") or "").strip()
            if not raw_date:
                return jsonify({"error": "date_required"}), 400
            biz = parse_date_value(raw_date)
            role_key = (request.args.get("role_key") or "FOLDER").strip().upper()
            metric = (request.args.get("metric") or "").strip() or None
            ensure_meta = _ensure_range_pubs(
                cursor, oid, role_key=role_key, date_start=biz, date_end=biz
            )
            try:
                conn.commit()
            except Exception:
                pass
            payload = build_daily_board(
                cursor, oid, business_date=biz, role_key=role_key, metric=metric
            )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(_attach_ensure(payload, ensure_meta)))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/employees", methods=["GET"])
    def rinse_dashboard_employees():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            ensure_meta = _ensure_week_pubs(
                cursor, oid, role_key="FOLDER", week_start=week_start
            )
            try:
                conn.commit()
            except Exception:
                pass
            payload = build_employees_list(cursor, oid, week_start=week_start)
            payload["publication_ensure"] = ensure_meta
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/rinse-dashboard/performance/employees/<employee_id>", methods=["GET"])
    def rinse_dashboard_employee(employee_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            week_start = _parse_week_start(request.args.get("week_start"), parse_date_value)
            ensure_meta = _ensure_week_pubs(
                cursor, oid, role_key="FOLDER", week_start=week_start
            )
            try:
                conn.commit()
            except Exception:
                pass
            payload = build_employee_detail(
                cursor, oid, employee_id=employee_id, week_start=week_start
            )
            payload["publication_ensure"] = ensure_meta
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/rinse-dashboard/performance/employees/<employee_id>/roles/<role_key>",
        methods=["GET"],
    )
    def rinse_dashboard_employee_role(employee_id: str, role_key: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not _can_read_rinse_dashboard(me):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            args = _period_args(parse_date_value)
            use_period = bool(args["period"] or args["start"] or args["compare"])
            if use_period:
                from backend.rinse_dashboard_period import resolve_period_and_compare

                windows = resolve_period_and_compare(
                    period=args["period"],
                    start=args["start"],
                    end=args["end"],
                    week_start=args["week_start"],
                    compare=args["compare"],
                )
                ensure_meta = _ensure_range_pubs(
                    cursor,
                    oid,
                    role_key=role_key,
                    date_start=windows["ensure_start"],
                    date_end=windows["ensure_end"],
                )
                try:
                    conn.commit()
                except Exception:
                    pass
                payload = build_employee_period_history(
                    cursor,
                    oid,
                    employee_id=employee_id,
                    role_key=role_key,
                    period=args["period"],
                    start=args["start"],
                    end=args["end"],
                    week_start=args["week_start"],
                    compare=args["compare"],
                    metric=args["metric"],
                )
            else:
                week_start = args["week_start"]
                try:
                    last_n = int(request.args.get("last_n") or 7)
                except (TypeError, ValueError):
                    last_n = 7
                ensure_meta = _ensure_week_pubs(
                    cursor, oid, role_key=role_key, week_start=week_start
                )
                try:
                    conn.commit()
                except Exception:
                    pass
                payload = build_employee_role_history(
                    cursor,
                    oid,
                    employee_id=employee_id,
                    role_key=role_key,
                    week_start=week_start,
                    last_n=last_n,
                    metric=args["metric"],
                )
            if payload.get("error") == "role_not_available":
                return jsonify(json_safe_rinse(payload)), 404
            payload["publication_ensure"] = ensure_meta
            return jsonify(json_safe_rinse(payload))
        except PeriodResolutionError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
