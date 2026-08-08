"""Phase 5E — mobile Revenue & Cost section entry routes."""

from __future__ import annotations

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.rinse_scan_time import json_safe_rinse


def register_drc_mobile_entry_routes(
    app,
    *,
    require_user,
    require_admin,
    require_admin_or_ops=None,
    user_org_id,
    parse_date_value,
    effective_washpro_permission_keys=None,
) -> None:
    def _roles(me) -> set[str]:
        return {str(r).upper() for r in (me.get("roles") or [])}

    def _is_admin(rs: set[str]) -> bool:
        return bool(rs & {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"})

    def _is_ops(rs: set[str]) -> bool:
        return _is_admin(rs) or "OPS" in rs or "MANAGER" in rs or "FINANCE" in rs

    def _me(cursor):
        me, err_resp, err_code = require_user(cursor)
        return me, err_resp, err_code, user_org_id(me) if me else None

    def _manager(cursor, conn):
        """Manager/admin review & assignment — no employee Mobile PIN Access gate."""
        me, err_resp, err_code, org_id = _me(cursor)
        if err_resp:
            return me, err_resp, err_code, org_id
        rs = _roles(me)
        if _is_ops(rs):
            return me, None, None, org_id
        if effective_washpro_permission_keys is not None:
            try:
                keys = effective_washpro_permission_keys(conn, int(me["user_id"]))
                if any(str(k).startswith("finance.") for k in keys):
                    return me, None, None, org_id
            except Exception:
                pass
        return me, jsonify({"error": "Forbidden"}), 403, org_id

    def _assert_employee_revenue_cost(cursor, org_id, user_id):
        """
        Per-request employee Mobile PIN Access for self-service /mobile/* routes.

        Re-reads current DB permission (not unlock-time / session cache).
        Manager routes use ``_manager`` and intentionally skip this check.
        """
        from backend.employee_mobile_pin_access import (
            DENIED_MODULE_MESSAGE,
            MobilePinAccessDeniedError,
            assert_employee_allows_module,
        )

        try:
            assert_employee_allows_module(cursor, int(org_id), int(user_id), "revenue_cost")
            return None
        except MobilePinAccessDeniedError:
            return jsonify({"error": DENIED_MODULE_MESSAGE}), 403

    def _err(exc):
        from backend.drc_mobile_entry import DrcMobileEntryError
        from backend.employee_mobile_pin_access import MobilePinAccessDeniedError, DENIED_MODULE_MESSAGE

        if isinstance(exc, MobilePinAccessDeniedError):
            return jsonify({"error": DENIED_MODULE_MESSAGE}), 403
        if isinstance(exc, DrcMobileEntryError):
            return jsonify({"error": str(exc)}), int(exc.status or 400)
        if isinstance(exc, ValueError):
            return jsonify({"error": str(exc)}), 400
        return jsonify({"error": str(exc)}), 500

    def _parse_date(raw):
        if not raw:
            return business_today()
        return parse_date_value(str(raw).strip())

    @app.route("/finance/daily-revenue-cost/mobile/today", methods=["GET"])
    def drc_mobile_today():
        from backend.drc_mobile_entry import list_today_for_employee

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"])
            denied = _assert_employee_revenue_cost(cursor, org_id, user_id)
            if denied:
                return denied
            on_date = _parse_date(request.args.get("entry_date") or request.args.get("business_date"))
            out = list_today_for_employee(cursor, org_id, user_id, on_date=on_date)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/sections/<section_key>/draft", methods=["PUT", "POST"])
    def drc_mobile_section_draft(section_key: str):
        from backend.drc_mobile_entry import save_section_draft

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"])
            denied = _assert_employee_revenue_cost(cursor, org_id, user_id)
            if denied:
                return denied
            data = request.get_json(silent=True) or {}
            on_date = _parse_date(data.get("entry_date") or data.get("business_date"))
            out = save_section_draft(
                cursor,
                org_id,
                user_id,
                section_key,
                data.get("values") or {},
                note=data.get("note"),
                expected_revision=data.get("expected_revision"),
                on_date=on_date,
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/sections/<section_key>/submit", methods=["POST"])
    def drc_mobile_section_submit(section_key: str):
        from backend.drc_mobile_entry import submit_section

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"])
            denied = _assert_employee_revenue_cost(cursor, org_id, user_id)
            if denied:
                return denied
            data = request.get_json(silent=True) or {}
            on_date = _parse_date(data.get("entry_date") or data.get("business_date"))
            out = submit_section(
                cursor,
                org_id,
                user_id,
                section_key,
                expected_revision=data.get("expected_revision"),
                on_date=on_date,
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/submit", methods=["POST"])
    def drc_mobile_submit_all():
        from backend.drc_mobile_entry import submit_all_assigned

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _me(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me["user_id"])
            denied = _assert_employee_revenue_cost(cursor, org_id, user_id)
            if denied:
                return denied
            data = request.get_json(silent=True) or {}
            on_date = _parse_date(data.get("entry_date") or data.get("business_date"))
            out = submit_all_assigned(cursor, org_id, user_id, on_date=on_date)
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/weekday-assignments", methods=["GET", "PUT"])
    def drc_mobile_weekday_assignments():
        from backend.drc_mobile_entry import (
            list_weekday_section_assignments,
            save_weekday_section_assignments,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _manager(cursor, conn)
            if err_resp:
                return err_resp, err_code
            if request.method == "GET":
                return jsonify({"assignments": list_weekday_section_assignments(cursor, org_id)})
            if not (_is_admin(_roles(me)) or _is_ops(_roles(me))):
                return jsonify({"error": "Forbidden"}), 403
            data = request.get_json(silent=True) or {}
            rows = save_weekday_section_assignments(
                cursor,
                org_id,
                data.get("assignments") or [],
                actor_user_id=int(me["user_id"]),
            )
            conn.commit()
            return jsonify({"assignments": rows})
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/submissions", methods=["GET"])
    def drc_mobile_submissions_list():
        from backend.drc_mobile_entry import list_mobile_submissions

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _manager(cursor, conn)
            if err_resp:
                return err_resp, err_code
            limit = int(request.args.get("limit") or 60)
            return jsonify({"submissions": list_mobile_submissions(cursor, org_id, limit=limit)})
        except Exception as e:
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route("/finance/daily-revenue-cost/mobile/submissions/<int:submission_id>", methods=["GET"])
    def drc_mobile_submission_detail(submission_id: int):
        from backend.drc_mobile_entry import get_mobile_submission

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code, org_id = _manager(cursor, conn)
            if err_resp:
                return err_resp, err_code
            return jsonify(json_safe_rinse(get_mobile_submission(cursor, org_id, submission_id)))
        except Exception as e:
            return _err(e)
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/finance/daily-revenue-cost/mobile/submissions/<int:submission_id>/review",
        methods=["POST"],
    )
    def drc_mobile_submission_review(submission_id: int):
        from backend.drc_mobile_entry import (
            DrcMobileEntryError,
            record_approval_conflict_audit,
            review_mobile_submission,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me = None
        org_id = None
        try:
            me, err_resp, err_code, org_id = _manager(cursor, conn)
            if err_resp:
                return err_resp, err_code
            data = request.get_json(silent=True) or {}
            out = review_mobile_submission(
                cursor,
                org_id,
                submission_id,
                action=data.get("action") or "",
                actor_user_id=int(me["user_id"]),
                reason=data.get("reason"),
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            # Durable approval_conflict audit after financial txn rollback.
            if (
                isinstance(e, DrcMobileEntryError)
                and getattr(e, "durable_conflict", False)
                and org_id is not None
            ):
                try:
                    record_approval_conflict_audit(
                        organization_id=int(org_id),
                        submission_id=int(submission_id),
                        actor_user_id=int(me["user_id"]) if me else None,
                        conflict_type=str(e.conflict_type or "approval_conflict"),
                        audit_detail=getattr(e, "audit_detail", None),
                        message=str(e),
                    )
                except Exception:
                    pass
            return _err(e)
        finally:
            cursor.close()
            conn.close()
