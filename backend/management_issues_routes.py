"""Management Issues API routes — hub roles only (no RINSE)."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.db import get_db
from backend.management_issues import (
    build_order_context,
    create_issue,
    dashboard_by_employee,
    dashboard_by_issue,
    employee_drilldown,
    ensure_mgmt_issues_tables,
    get_issue,
    link_issue_to_bag,
    list_issues,
    list_taxonomy,
    override_attributions,
    search_issue_bags,
    seed_mgmt_issue_taxonomy,
    update_issue,
)
from backend.management_today import CountingCursor
from backend.rinse_scan_time import json_safe_rinse

HUB_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _actor(me: dict) -> tuple[int | None, str | None]:
    uid = me.get("id") or me.get("user_id")
    try:
        uid_i = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_i = None
    name = (
        me.get("display_name")
        or me.get("full_name")
        or me.get("name")
        or me.get("email")
        or None
    )
    return uid_i, (str(name).strip() if name else None)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def register_management_issues_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value=None,
) -> None:
    def _gate(cursor):
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return None, None, err_resp, err_code
        if not (_role_set(me) & HUB_ROLES):
            return None, None, jsonify({"error": "Forbidden"}), 403
        return me, int(user_org_id(me)), None, None

    @app.route("/api/management/issues/taxonomy", methods=["GET"])
    def management_issues_taxonomy():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            seed_mgmt_issue_taxonomy(cursor, oid)
            conn.commit()
            return jsonify(json_safe_rinse(list_taxonomy(cursor, oid)))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/bag-search", methods=["GET"])
    def management_issues_bag_search():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            q = (request.args.get("q") or "").strip()
            counting = CountingCursor(cursor)
            payload = search_issue_bags(counting, oid, q, limit=10)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/order-context", methods=["GET"])
    def management_issues_order_context():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            bag_id = (request.args.get("bag_id") or "").strip()
            oi_raw = (request.args.get("order_instance_id") or "").strip()
            try:
                oi_id = int(oi_raw)
            except ValueError:
                return jsonify({"error": "order_instance_id_required"}), 400
            counting = CountingCursor(cursor)
            payload = build_order_context(
                counting, oid, bag_id=bag_id, order_instance_id=oi_id
            )
            if payload.get("error"):
                return jsonify(payload), int(payload.get("status") or 400)
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues", methods=["GET"])
    def management_issues_list():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            counting = CountingCursor(cursor)
            payload = list_issues(
                counting,
                oid,
                status=(request.args.get("status") or None),
                category=(request.args.get("category") or None),
                employee=(request.args.get("employee") or None),
                service=(request.args.get("service") or None),
                q=(request.args.get("q") or None),
                date_from=_parse_date(request.args.get("date_from")),
                date_to=_parse_date(request.args.get("date_to")),
                date_basis=(request.args.get("date_basis") or "production"),
                limit=int(request.args.get("limit") or 50),
                offset=int(request.args.get("offset") or 0),
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues", methods=["POST"])
    def management_issues_create():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            body = request.get_json(silent=True) or {}
            if body.get("typed_bag_id") and not body.get("order_instance_id"):
                if str(body.get("matched_state") or "").upper() != "UNMATCHED":
                    return jsonify({"error": "selection_required"}), 400
            ensure_mgmt_issues_tables(cursor)
            uid, name = _actor(me)
            counting = CountingCursor(cursor)
            result = create_issue(
                counting, oid, body, actor_user_id=uid, actor_name=name
            )
            if result.get("error"):
                conn.rollback()
                return jsonify(result), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result)), 201
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/<int:issue_id>", methods=["GET"])
    def management_issues_detail(issue_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            include_events = str(request.args.get("events") or "").lower() in (
                "1",
                "true",
                "yes",
            )
            counting = CountingCursor(cursor)
            result = get_issue(
                counting, oid, issue_id, include_events=include_events
            )
            if result.get("error"):
                return jsonify(result), int(result.get("status") or 404)
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/<int:issue_id>", methods=["PATCH"])
    def management_issues_patch(issue_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            body = request.get_json(silent=True) or {}
            uid, name = _actor(me)
            counting = CountingCursor(cursor)
            result = update_issue(
                counting, oid, issue_id, body, actor_user_id=uid, actor_name=name
            )
            if result.get("error"):
                conn.rollback()
                return jsonify(result), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/<int:issue_id>/link-bag", methods=["POST"])
    def management_issues_link_bag(issue_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            body = request.get_json(silent=True) or {}
            uid, name = _actor(me)
            counting = CountingCursor(cursor)
            result = link_issue_to_bag(
                counting,
                oid,
                issue_id,
                bag_id=str(body.get("bag_id") or ""),
                order_instance_id=int(body.get("order_instance_id") or 0),
                actor_user_id=uid,
                actor_name=name,
            )
            if result.get("error"):
                conn.rollback()
                return jsonify(result), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/issues/<int:issue_id>/attributions", methods=["PUT"]
    )
    def management_issues_attributions(issue_id: int):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            body = request.get_json(silent=True) or {}
            uid, name = _actor(me)
            counting = CountingCursor(cursor)
            result = override_attributions(
                counting,
                oid,
                issue_id,
                body.get("attributions") or [],
                actor_user_id=uid,
                actor_name=name,
                reason=body.get("reason"),
            )
            if result.get("error"):
                conn.rollback()
                return jsonify(result), int(result.get("status") or 400)
            conn.commit()
            return jsonify(json_safe_rinse(result))
        except Exception as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/dashboard/by-issue", methods=["GET"])
    def management_issues_dash_by_issue():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            counting = CountingCursor(cursor)
            payload = dashboard_by_issue(
                counting,
                oid,
                period=(request.args.get("period") or "30d"),
                date_basis=(request.args.get("date_basis") or "production"),
                custom_from=_parse_date(request.args.get("date_from")),
                custom_to=_parse_date(request.args.get("date_to")),
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/dashboard/by-employee", methods=["GET"])
    def management_issues_dash_by_employee():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            counting = CountingCursor(cursor)
            payload = dashboard_by_employee(
                counting,
                oid,
                period=(request.args.get("period") or "30d"),
                date_basis=(request.args.get("date_basis") or "production"),
                role_key=(request.args.get("role_key") or None),
                custom_from=_parse_date(request.args.get("date_from")),
                custom_to=_parse_date(request.args.get("date_to")),
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/issues/dashboard/employee", methods=["GET"])
    def management_issues_employee_drill():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, err, code = _gate(cursor)
            if err:
                return err, code
            emp = (request.args.get("employee_name") or "").strip()
            if not emp:
                return jsonify({"error": "employee_name_required"}), 400
            counting = CountingCursor(cursor)
            payload = employee_drilldown(
                counting,
                oid,
                employee_name=emp,
                role_key=(request.args.get("role_key") or None),
                period=(request.args.get("period") or "30d"),
                date_basis=(request.args.get("date_basis") or "production"),
                custom_from=_parse_date(request.args.get("date_from")),
                custom_to=_parse_date(request.args.get("date_to")),
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
