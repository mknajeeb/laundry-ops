"""Public PIN + authenticated dashboard routes for Cleaning / Tasks."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from flask import jsonify, request

from backend.attendance_pin_break import _gate_common
from backend.attendance_pin_punch import INVALID_PIN_MESSAGE
from backend.business_time import business_today
from backend.cleaning_task_activity import (
    CleaningTaskError,
    approve_activity,
    attendance_cleaning_snapshot,
    complete_task,
    complete_untimed_task,
    apply_rinse_task_dashboard_scope,
    dashboard_summary,
    ensure_cleaning_task_activity_tables,
    list_employee_day_tasks,
    list_supervisor_queue,
    list_tasks_to_verify,
    record_post_complete_choice,
    reject_activity,
    start_task,
    user_can_verify_activity,
)
from backend.cleaning_task_group_execution import (
    checkoff_group_item,
    complete_group_activity,
    start_group_activity,
)
from backend.task_activity_groups import (
    ActivityGroupError,
    is_activity_group_code,
    list_activity_groups,
    upsert_activity_group,
)
from backend.task_catalog import (
    TaskCatalogError,
    list_categories,
    list_task_definitions,
    reorder_categories,
    seed_builtin_categories,
    upsert_category,
    upsert_task_definition,
)
from backend.task_checklist import (
    list_checklists,
    list_checklists_to_verify,
    reject_checklist_item,
    upsert_checklist,
    verify_checklist,
    verify_checklist_group,
)
from backend.employee_mobile_pin_access import (
    MobilePinAccessDeniedError,
    assert_optional_pin_hub_module,
    employee_allows_module,
)
from backend.management_pin_access import HUB_ROLES, role_set


def _parse_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _can_review(cursor, org_id: int, user_id: int, roles: set[str]) -> bool:
    if roles & HUB_ROLES:
        return True
    if employee_allows_module(cursor, int(org_id), int(user_id), "cleaning_task_review"):
        return True
    if employee_allows_module(cursor, int(org_id), int(user_id), "team_status"):
        return True
    return False


def register_cleaning_task_activity_routes(
    app,
    *,
    require_user: Callable,
    user_org_id: Callable,
    fetch_user_roles: Callable,
    get_request_ip: Callable,
    parse_date_value: Callable | None = None,
):
    del parse_date_value

    def _pin_gate(action_prefix: str, *, require_clocked_in: bool = True):
        from backend.db import get_db

        data = request.json or {}
        org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
        pin = data.get("pin")
        hub_token = str(data.get("hub_token") or "").strip() or None
        conn = get_db()
        try:
            if require_clocked_in:
                ctx, err = _gate_common(
                    conn,
                    org_slug,
                    pin,
                    hub_token,
                    fetch_user_roles,
                    get_request_ip(),
                    action_prefix=action_prefix,
                )
                if err:
                    return None, conn, err
                return ctx, conn, None

            # Review may work even when supervisor is not clocked in — resolve hub/PIN only.
            from backend.attendance_pin_break import _resolve_matched
            from backend.attendance_pin_punch import (
                KIOSK_DISABLED_MESSAGE,
                PIN_LEN_KIOSK,
                fetch_organization_by_slug,
                is_rate_limited,
                shared_device_attendance_enabled,
            )
            from backend.payroll_identity import payroll_profiles_active

            org_slug = (org_slug or "").strip().lower()
            pin_clean = str(pin or "").strip()
            hub_clean = str(hub_token or "").strip() or None
            if not org_slug or (not hub_clean and not pin_clean):
                return None, conn, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 400)
            if pin_clean and (not pin_clean.isdigit() or len(pin_clean) != PIN_LEN_KIOSK):
                return None, conn, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 400)
            if not payroll_profiles_active(conn):
                return None, conn, ({"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503)
            org = fetch_organization_by_slug(conn, org_slug)
            if not org:
                return None, conn, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 401)
            org_id = int(org["id"])
            if not shared_device_attendance_enabled(conn, org_id):
                return None, conn, ({"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503)
            if is_rate_limited(conn, org_id, get_request_ip()):
                return None, conn, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 429)
            matched, err = _resolve_matched(
                conn,
                org_id,
                org_slug,
                pin_clean,
                hub_clean,
                fetch_user_roles,
                get_request_ip(),
                action_prefix=action_prefix,
            )
            if err:
                return None, conn, err
            return {
                "org_id": org_id,
                "org_slug": org_slug,
                "matched": matched,
                "user_id": int(matched["id"]),
                "session": None,
            }, conn, None
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    @app.route("/api/public/attendance/pin-cleaning-tasks", methods=["POST"])
    def public_pin_cleaning_tasks_list():
        ctx, conn, err = _pin_gate("cleaning_list", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            ensure_cleaning_task_activity_tables(cursor)
            day = _parse_date((request.json or {}).get("business_date")) or business_today()
            payload = list_employee_day_tasks(
                cursor, int(ctx["org_id"]), int(ctx["user_id"]), business_date=day
            )
            snap = attendance_cleaning_snapshot(cursor, int(ctx["org_id"]), int(ctx["user_id"]))
            conn.commit()
            return jsonify({"ok": True, **payload, **snap})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not load cleaning tasks."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/start", methods=["POST"])
    def public_pin_cleaning_tasks_start():
        ctx, conn, err = _pin_gate("cleaning_start", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            responsibility_id = data.get("responsibility_id")
            if responsibility_id is None:
                return jsonify({"ok": False, "error": "responsibility_id is required"}), 400
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            session = ctx.get("session") or {}
            # Dispatch activity groups to shared-timer start.
            day = list_employee_day_tasks(
                cursor, int(ctx["org_id"]), int(ctx["user_id"])
            )
            target = next(
                (
                    t
                    for t in (day.get("tasks") or [])
                    if int(t.get("responsibility_id") or 0) == int(responsibility_id)
                ),
                None,
            )
            start_fn = (
                start_group_activity
                if target and (target.get("is_activity_group") or is_activity_group_code(target.get("role")))
                else start_task
            )
            activity = start_fn(
                conn,
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                responsibility_id=int(responsibility_id),
                shift_session_id=int(session["id"]) if session.get("id") else None,
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not start cleaning task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/group-checkoff", methods=["POST"])
    def public_pin_cleaning_tasks_group_checkoff():
        ctx, conn, err = _pin_gate("cleaning_group_checkoff", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            activity_id = data.get("activity_id")
            task_code = data.get("task_code") or data.get("role")
            if activity_id is None or not task_code:
                return jsonify({"ok": False, "error": "activity_id and task_code are required"}), 400
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            activity = checkoff_group_item(
                conn,
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                activity_id=int(activity_id),
                task_code=str(task_code),
                completion_input=data.get("completion_input") or data.get("input"),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not check off group task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/complete-group", methods=["POST"])
    def public_pin_cleaning_tasks_complete_group():
        ctx, conn, err = _pin_gate("cleaning_complete_group", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            activity_id = data.get("activity_id")
            if activity_id is None:
                return jsonify({"ok": False, "error": "activity_id is required"}), 400
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            activity = complete_group_activity(
                conn,
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                activity_id=int(activity_id),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not complete activity group."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/complete", methods=["POST"])
    def public_pin_cleaning_tasks_complete():
        ctx, conn, err = _pin_gate("cleaning_complete", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            activity_id = data.get("activity_id")
            if activity_id is None:
                return jsonify({"ok": False, "error": "activity_id is required"}), 400
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            activity = complete_task(
                conn,
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                activity_id=int(activity_id),
                completion_input=data.get("completion_input") or data.get("input"),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not complete task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/complete-untimed", methods=["POST"])
    def public_pin_cleaning_tasks_complete_untimed():
        ctx, conn, err = _pin_gate("cleaning_complete_untimed", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            rid = data.get("responsibility_id")
            if rid is None:
                return jsonify({"ok": False, "error": "responsibility_id is required"}), 400
            cursor = conn.cursor(dictionary=True)
            try:
                assert_optional_pin_hub_module(
                    cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                )
            except MobilePinAccessDeniedError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            activity = complete_untimed_task(
                conn,
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                responsibility_id=int(rid),
                shift_session_id=ctx.get("shift_id"),
                completion_input=data.get("completion_input") or data.get("input"),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not complete task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/verify-queue", methods=["POST"])
    def public_pin_cleaning_tasks_verify_queue():
        """Tasks to Verify — peer or supervisor, including cross-day / next-day items."""
        ctx, conn, err = _pin_gate("cleaning_verify_queue", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            cursor = conn.cursor(dictionary=True)
            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            can_sup = _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles)
            # Peer verifiers only need cleaning_tasks; supervisors/review grant also ok.
            if not can_sup:
                try:
                    assert_optional_pin_hub_module(
                        cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                    )
                except MobilePinAccessDeniedError as exc:
                    return jsonify({"ok": False, "error": str(exc)}), 403
            day = _parse_date((request.json or {}).get("business_date")) or business_today()
            payload = list_tasks_to_verify(
                cursor,
                int(ctx["org_id"]),
                int(ctx["user_id"]),
                as_of=day,
                verifier_roles=sorted(roles),
                has_supervisor_review=can_sup,
            )
            checklists = list_checklists_to_verify(
                cursor,
                int(ctx["org_id"]),
                int(ctx["user_id"]),
                as_of=day,
                has_supervisor_review=can_sup,
            )
            return jsonify({"ok": True, **payload, "checklists": checklists.get("checklists") or []})
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/checklist-verify", methods=["POST"])
    def public_pin_cleaning_tasks_checklist_verify():
        ctx, conn, err = _pin_gate("cleaning_checklist_verify", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            cursor = conn.cursor(dictionary=True)
            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            can_sup = _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles)
            if not can_sup:
                try:
                    assert_optional_pin_hub_module(
                        cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                    )
                except MobilePinAccessDeniedError as exc:
                    return jsonify({"ok": False, "error": str(exc)}), 403
            biz = _parse_date(data.get("business_date"))
            if not biz:
                return jsonify({"ok": False, "error": "business_date is required"}), 400
            group_id = data.get("group_id")
            if group_id not in (None, ""):
                result = verify_checklist_group(
                    cursor,
                    organization_id=int(ctx["org_id"]),
                    checklist_id=int(data.get("checklist_id") or 0),
                    group_id=int(group_id),
                    business_date=biz,
                    verifier_user_id=int(ctx["user_id"]),
                    has_supervisor_review=can_sup,
                )
            else:
                result = verify_checklist(
                    cursor,
                    organization_id=int(ctx["org_id"]),
                    checklist_id=int(data.get("checklist_id") or 0),
                    business_date=biz,
                    verifier_user_id=int(ctx["user_id"]),
                    has_supervisor_review=can_sup,
                )
            conn.commit()
            return jsonify({"ok": True, "checklist": result})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not verify checklist."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/checklist-reject-item", methods=["POST"])
    def public_pin_cleaning_tasks_checklist_reject_item():
        ctx, conn, err = _pin_gate("cleaning_checklist_reject_item", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            cursor = conn.cursor(dictionary=True)
            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            can_sup = _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles)
            if not can_sup:
                try:
                    assert_optional_pin_hub_module(
                        cursor, int(ctx["org_id"]), int(ctx["user_id"]), "cleaning_tasks"
                    )
                except MobilePinAccessDeniedError as exc:
                    return jsonify({"ok": False, "error": str(exc)}), 403
            activity = reject_checklist_item(
                cursor,
                organization_id=int(ctx["org_id"]),
                activity_id=int(data.get("activity_id") or 0),
                verifier_user_id=int(ctx["user_id"]),
                reason=str(data.get("reason") or ""),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not reject checklist item."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/next", methods=["POST"])
    def public_pin_cleaning_tasks_next():
        ctx, conn, err = _pin_gate("cleaning_next", require_clocked_in=True)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            cursor = conn.cursor(dictionary=True)
            result = record_post_complete_choice(
                cursor,
                organization_id=int(ctx["org_id"]),
                user_id=int(ctx["user_id"]),
                activity_id=int(data.get("activity_id") or 0),
                choice=str(data.get("choice") or ""),
            )
            conn.commit()
            return jsonify({"ok": True, **result})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not record next step."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/review", methods=["POST"])
    def public_pin_cleaning_tasks_review():
        ctx, conn, err = _pin_gate("cleaning_review", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            cursor = conn.cursor(dictionary=True)
            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            if not _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles):
                return jsonify({"ok": False, "error": "Supervisor task review is not available for this PIN."}), 403
            data = request.json or {}
            day = _parse_date(data.get("business_date")) or business_today()
            payload = list_supervisor_queue(
                cursor,
                int(ctx["org_id"]),
                business_date=day,
                status=data.get("status"),
                user_id=int(data["user_id"]) if data.get("user_id") not in (None, "") else None,
                role=str(data["role"]).strip() if data.get("role") else None,
            )
            conn.commit()
            return jsonify({"ok": True, "supervisor_id": int(ctx["user_id"]), **payload})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not load task review."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/approve", methods=["POST"])
    def public_pin_cleaning_tasks_approve():
        ctx, conn, err = _pin_gate("cleaning_approve", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            cursor = conn.cursor(dictionary=True)
            from backend.cleaning_task_activity import get_activity

            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            can_sup = _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles)
            ids = data.get("activity_ids") or data.get("activity_id")
            if ids is None:
                return jsonify({"ok": False, "error": "activity_id is required"}), 400
            if not isinstance(ids, list):
                ids = [ids]
            approved = []
            for aid in ids:
                row = get_activity(cursor, int(ctx["org_id"]), int(aid))
                if not row:
                    raise CleaningTaskError("Task activity not found.", status=404)
                if not user_can_verify_activity(
                    cursor,
                    organization_id=int(ctx["org_id"]),
                    activity=row,
                    verifier_user_id=int(ctx["user_id"]),
                    verifier_roles=sorted(roles),
                    has_supervisor_review=can_sup,
                ):
                    return jsonify(
                        {"ok": False, "error": "You are not authorized to verify this task."}
                    ), 403
                approved.append(
                    approve_activity(
                        cursor,
                        organization_id=int(ctx["org_id"]),
                        activity_id=int(aid),
                        supervisor_user_id=int(ctx["user_id"]),
                    )
                )
            conn.commit()
            return jsonify({"ok": True, "activities": approved})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not verify task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/public/attendance/pin-cleaning-tasks/reject", methods=["POST"])
    def public_pin_cleaning_tasks_reject():
        ctx, conn, err = _pin_gate("cleaning_reject", require_clocked_in=False)
        if err:
            body, status = err
            try:
                conn.close()
            except Exception:
                pass
            return jsonify(body), status
        try:
            data = request.json or {}
            cursor = conn.cursor(dictionary=True)
            from backend.cleaning_task_activity import get_activity

            roles = {str(r).upper() for r in (ctx["matched"].get("_roles") or [])}
            can_sup = _can_review(cursor, int(ctx["org_id"]), int(ctx["user_id"]), roles)
            row = get_activity(cursor, int(ctx["org_id"]), int(data.get("activity_id") or 0))
            if not row:
                return jsonify({"ok": False, "error": "Task activity not found."}), 404
            if not user_can_verify_activity(
                cursor,
                organization_id=int(ctx["org_id"]),
                activity=row,
                verifier_user_id=int(ctx["user_id"]),
                verifier_roles=sorted(roles),
                has_supervisor_review=can_sup,
            ):
                return jsonify(
                    {"ok": False, "error": "You are not authorized to reject this task."}
                ), 403
            activity = reject_activity(
                cursor,
                organization_id=int(ctx["org_id"]),
                activity_id=int(data.get("activity_id") or 0),
                supervisor_user_id=int(ctx["user_id"]),
                reason=str(data.get("reason") or data.get("rejection_reason") or ""),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": exc.message, **exc.payload}), exc.status
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not reject task."}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-dashboard", methods=["GET"])
    def management_task_dashboard():
        """Management Task Dashboard (edit-capable for managers; Rinse is read-only)."""
        from backend.db import get_db
        from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

        conn = get_db()
        try:
            cursor = conn.cursor(dictionary=True)
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org_id = user_org_id(me)
            if not org_id:
                return jsonify({"error": "Organization required"}), 400
            roles = role_set(me)
            rinse_only = is_rinse_schedule_viewer(roles) and not (roles & HUB_ROLES)
            if not (roles & HUB_ROLES) and not rinse_only:
                # Managers via hub roles, or Rinse viewers; also allow cleaning_task_review grant.
                uid = int(me.get("user_id") or me.get("id") or 0)
                if not employee_allows_module(cursor, int(org_id), uid, "cleaning_task_review"):
                    return jsonify({"error": "Forbidden"}), 403
            day = _parse_date(request.args.get("date") or request.args.get("business_date")) or business_today()
            user_filter = request.args.get("user_id")
            payload = dashboard_summary(
                cursor,
                int(org_id),
                business_date=day,
                user_id=int(user_filter) if user_filter not in (None, "") else None,
                role=(request.args.get("role") or "").strip() or None,
                status=(request.args.get("status") or "").strip() or None,
            )
            payload["read_only"] = bool(rinse_only)
            payload["can_approve"] = not rinse_only
            if rinse_only:
                payload = apply_rinse_task_dashboard_scope(payload)
            return jsonify(payload)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-dashboard/approve", methods=["POST"])
    def management_task_dashboard_approve():
        from backend.db import get_db
        from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

        conn = get_db()
        try:
            cursor = conn.cursor(dictionary=True)
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org_id = user_org_id(me)
            if not org_id:
                return jsonify({"error": "Organization required"}), 400
            roles = role_set(me)
            if is_rinse_schedule_viewer(roles) and not (roles & HUB_ROLES):
                return jsonify({"error": "Rinse access is read-only for the Task Dashboard."}), 403
            uid = int(me.get("user_id") or me.get("id") or 0)
            if not (roles & HUB_ROLES) and not employee_allows_module(
                cursor, int(org_id), uid, "cleaning_task_review"
            ):
                return jsonify({"error": "Forbidden"}), 403
            data = request.json or {}
            ids = data.get("activity_ids") or data.get("activity_id")
            if ids is None:
                return jsonify({"error": "activity_id is required"}), 400
            if not isinstance(ids, list):
                ids = [ids]
            approved = [
                approve_activity(
                    cursor,
                    organization_id=int(org_id),
                    activity_id=int(aid),
                    supervisor_user_id=uid,
                )
                for aid in ids
            ]
            conn.commit()
            return jsonify({"ok": True, "activities": approved})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-dashboard/reject", methods=["POST"])
    def management_task_dashboard_reject():
        from backend.db import get_db
        from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

        conn = get_db()
        try:
            cursor = conn.cursor(dictionary=True)
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            org_id = user_org_id(me)
            if not org_id:
                return jsonify({"error": "Organization required"}), 400
            roles = role_set(me)
            if is_rinse_schedule_viewer(roles) and not (roles & HUB_ROLES):
                return jsonify({"error": "Rinse access is read-only for the Task Dashboard."}), 403
            uid = int(me.get("user_id") or me.get("id") or 0)
            if not (roles & HUB_ROLES) and not employee_allows_module(
                cursor, int(org_id), uid, "cleaning_task_review"
            ):
                return jsonify({"error": "Forbidden"}), 403
            data = request.json or {}
            activity = reject_activity(
                cursor,
                organization_id=int(org_id),
                activity_id=int(data.get("activity_id") or 0),
                supervisor_user_id=uid,
                reason=str(data.get("reason") or data.get("rejection_reason") or ""),
            )
            conn.commit()
            return jsonify({"ok": True, "activity": activity})
        except CleaningTaskError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _mgmt_catalog_gate():
        from backend.db import get_db
        from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            try:
                conn.close()
            except Exception:
                pass
            return None, None, None, (err_resp, err_code)
        org_id = user_org_id(me)
        roles = role_set(me)
        if is_rinse_schedule_viewer(roles) and not (roles & HUB_ROLES):
            try:
                conn.close()
            except Exception:
                pass
            return None, None, None, (jsonify({"error": "Rinse access is read-only for Task Management."}), 403)
        if not (roles & HUB_ROLES):
            try:
                conn.close()
            except Exception:
                pass
            return None, None, None, (jsonify({"error": "Forbidden"}), 403)
        return conn, cursor, org_id, None

    @app.route("/api/management/task-catalog", methods=["GET"])
    def management_task_catalog():
        """Task Management — categories + task definitions."""
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            seed_builtin_categories(cursor, int(org_id))
            conn.commit()
            return jsonify(
                {
                    "categories": list_categories(cursor, int(org_id)),
                    "tasks": list_task_definitions(cursor, int(org_id)),
                    "checklists": list_checklists(cursor, int(org_id)),
                    "activity_groups": list_activity_groups(
                        cursor, int(org_id), include_inactive=True
                    ),
                }
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/activity-groups", methods=["POST"])
    def management_task_catalog_activity_group_upsert():
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            data = request.json or {}
            gid = data.get("id")
            row = upsert_activity_group(
                cursor,
                int(org_id),
                data,
                group_id=int(gid) if gid not in (None, "") else None,
            )
            conn.commit()
            return jsonify({"ok": True, "activity_group": row})
        except ActivityGroupError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        except TaskCatalogError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/categories", methods=["POST"])
    def management_task_catalog_category_create():
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            row = upsert_category(cursor, int(org_id), request.json or {})
            conn.commit()
            return jsonify({"ok": True, "category": row})
        except TaskCatalogError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/categories/<int:category_id>", methods=["PUT"])
    def management_task_catalog_category_update(category_id: int):
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            row = upsert_category(cursor, int(org_id), request.json or {}, category_id=int(category_id))
            conn.commit()
            return jsonify({"ok": True, "category": row})
        except TaskCatalogError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/categories/reorder", methods=["POST"])
    def management_task_catalog_category_reorder():
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            codes = (request.json or {}).get("ordered_codes") or []
            rows = reorder_categories(cursor, int(org_id), codes)
            conn.commit()
            return jsonify({"ok": True, "categories": rows})
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/tasks", methods=["POST"])
    def management_task_catalog_task_upsert():
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            data = request.json or {}
            code = str(data.get("code") or "").strip()
            row = upsert_task_definition(cursor, int(org_id), code, data)
            conn.commit()
            return jsonify({"ok": True, "task": row})
        except TaskCatalogError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @app.route("/api/management/task-catalog/checklists", methods=["POST"])
    def management_task_catalog_checklist_upsert():
        conn, cursor, org_id, err = _mgmt_catalog_gate()
        if err:
            return err
        try:
            data = request.json or {}
            cid = data.get("id")
            row = upsert_checklist(
                cursor,
                int(org_id),
                data,
                checklist_id=int(cid) if cid not in (None, "") else None,
            )
            conn.commit()
            return jsonify({"ok": True, "checklist": row})
        except TaskCatalogError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": exc.message}), exc.status
        finally:
            try:
                conn.close()
            except Exception:
                pass
