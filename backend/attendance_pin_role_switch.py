"""
Public PIN role-switch for mobile home-screen shortcut.
Does not clock in/out. Does not return Bearer tokens.
Employee must already have an active attendance shift.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.attendance_pin_punch import (
    ADMIN_ROLE_CODES,
    INVALID_PIN_MESSAGE,
    KIOSK_DISABLED_MESSAGE,
    PIN_LEN_KIOSK,
    _active_shift,
    fetch_organization_by_slug,
    is_rate_limited,
    record_pin_attempt,
    resolve_user_by_attendance_pin,
    shared_device_attendance_enabled,
)
from backend.category_role_tracking_settings import is_category_role_tracking_enabled
from backend.payroll_identity import payroll_profiles_active
from backend.shift_job_tracking import (
    IdempotencyConflictError,
    get_open_job_segment,
    list_active_selection_tree,
    start_category_role_segment,
)

logger = logging.getLogger(__name__)

NOT_CLOCKED_IN_MESSAGE = "You must be clocked in to change your role."
FEATURE_DISABLED_MESSAGE = "Category & Role Tracking is disabled for this organization."
MISSING_ASSIGNMENT_MESSAGE = "Select a category and role to continue."
MISSING_IDEMPOTENCY_MESSAGE = (
    "idempotency_key required (body.idempotency_key or Idempotency-Key header)"
)


def _employee_first_name(matched: dict) -> str:
    for key in ("first_name", "preferred_name", "display_name"):
        val = (matched.get(key) or "").strip()
        if val:
            return val.split()[0] if key == "display_name" else val
    return "there"


def _current_assignment_payload(conn, session_id: int) -> dict:
    open_seg = get_open_job_segment(conn, int(session_id)) or {}
    from backend.mobile_ops_labels import employee_assignment_label_from_segment

    label = employee_assignment_label_from_segment(open_seg) or None
    return {
        "current_category_id": open_seg.get("category_id"),
        "current_role_id": open_seg.get("role_id"),
        "current_display_label": label or open_seg.get("display_label"),
        "current_assignment_started_at": open_seg.get("started_at"),
        "segment_id": open_seg.get("id"),
    }


def _resolve_user_by_hub_token(
    conn, organization_id: int, org_slug: str, hub_token: str, fetch_roles_fn
) -> Optional[dict]:
    """Resolve employee from a verified PIN Hub session token (no bcrypt)."""
    from backend.employee_pin_hub import verify_hub_session_token

    try:
        claims = verify_hub_session_token(hub_token)
    except ValueError:
        return None
    emp_id = int(claims["employee_id"])
    claim_org = int(claims["organization_id"])
    if claim_org != int(organization_id):
        return None
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT u.id, u.username, u.display_name, u.active, u.organization_id,
                   pp.first_name, pp.last_name, pp.termination_date
            FROM users u
            LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
            INNER JOIN organizations o ON o.id = u.organization_id AND o.active = 1
            WHERE u.id = %s
              AND u.organization_id = %s
              AND u.active = 1
              AND LOWER(o.slug) = %s
            LIMIT 1
            """,
            (emp_id, int(organization_id), org_slug),
        )
        row = c.fetchone()
        if not row:
            return None
        if row.get("termination_date"):
            return None
        roles = fetch_roles_fn(c, row["id"])
        rs = {str(r).upper() for r in roles}
        if rs & ADMIN_ROLE_CODES:
            return None
        row["_roles"] = roles
        return row
    finally:
        try:
            c.close()
        except Exception:
            pass


def perform_pin_role_switch(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
    *,
    hub_token: Optional[str] = None,
    category_id: Optional[Any] = None,
    role_id: Optional[Any] = None,
    idempotency_key: Optional[str] = None,
) -> tuple[dict, int]:
    """
    PIN / hub_token → role switch for an already-clocked-in employee.

    Without category/role: validate identity + active shift + feature flag, return selection tree.
    With category/role + idempotency_key: perform the switch.

    When ``hub_token`` is present (PIN Hub already authenticated), skip bcrypt PIN scan.
    Mobile PIN Access ``switch_role`` is still re-checked on open and before mutate.
    """
    org_slug = (organization_slug or "").strip().lower()
    pin_clean = str(pin or "").strip()
    hub_clean = str(hub_token or "").strip()

    if not org_slug:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400
    if not hub_clean and not pin_clean:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400
    if pin_clean and (not pin_clean.isdigit() or len(pin_clean) != PIN_LEN_KIOSK):
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400

    if not payroll_profiles_active(conn):
        return {"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503

    org = fetch_organization_by_slug(conn, org_slug)
    if not org:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    org_id = int(org["id"])

    if not shared_device_attendance_enabled(conn, org_id):
        return {"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503

    if is_rate_limited(conn, org_id, ip_address):
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 429

    matched = None
    if hub_clean:
        matched = _resolve_user_by_hub_token(
            conn, org_id, org_slug, hub_clean, fetch_roles_fn
        )
        if not matched:
            record_pin_attempt(
                conn, org_id, ip_address, success=False, action="pin_role_switch_hub_fail"
            )
            conn.commit()
            return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401
    else:
        matched = resolve_user_by_attendance_pin(conn, org_id, pin_clean, fetch_roles_fn)
        if not matched:
            record_pin_attempt(
                conn, org_id, ip_address, success=False, action="pin_role_switch_fail"
            )
            conn.commit()
            return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    user_id = int(matched["id"])
    active = _active_shift(conn, user_id)
    if not active:
        record_pin_attempt(
            conn, org_id, ip_address, success=False, user_id=user_id, action="pin_role_switch_not_in"
        )
        conn.commit()
        return {"ok": False, "error": NOT_CLOCKED_IN_MESSAGE}, 400

    if not is_category_role_tracking_enabled(conn, org_id):
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=False,
            user_id=user_id,
            action="pin_role_switch_disabled",
        )
        conn.commit()
        return {"ok": False, "error": FEATURE_DISABLED_MESSAGE}, 403

    # Stage A: check current employee access before showing selections.
    from backend.employee_mobile_pin_access import (
        DENIED_MODULE_MESSAGE,
        MobilePinAccessDeniedError,
        assert_employee_allows_module,
    )

    access_c = conn.cursor(dictionary=True)
    try:
        try:
            assert_employee_allows_module(access_c, org_id, user_id, "switch_role")
        except MobilePinAccessDeniedError:
            record_pin_attempt(
                conn,
                org_id,
                ip_address,
                success=False,
                user_id=user_id,
                action="pin_role_switch_module_denied",
            )
            conn.commit()
            return {"ok": False, "error": DENIED_MODULE_MESSAGE}, 403
    finally:
        try:
            access_c.close()
        except Exception:
            pass

    session_id = int(active["id"])
    first_name = _employee_first_name(matched)
    current = _current_assignment_payload(conn, session_id)

    has_assignment = category_id is not None and role_id is not None and str(category_id) and str(
        role_id
    )
    if not has_assignment:
        c = conn.cursor(dictionary=True)
        try:
            tree = list_active_selection_tree(c, org_id)
        finally:
            try:
                c.close()
            except Exception:
                pass
        record_pin_attempt(
            conn, org_id, ip_address, success=True, user_id=user_id, action="pin_role_switch_open"
        )
        conn.commit()
        return {
            "ok": True,
            "needs_selection": True,
            "selection_tree": tree,
            "employee_first_name": first_name,
            "shift_session_id": session_id,
            **current,
        }, 200

    key = (idempotency_key or "").strip()
    if not key:
        return {"ok": False, "error": MISSING_IDEMPOTENCY_MESSAGE}, 400
    if len(key) > 64:
        return {"ok": False, "error": "idempotency_key must be at most 64 characters"}, 400

    # Re-check immediately before mutation so a mid-session revoke blocks it.
    access_c2 = conn.cursor(dictionary=True)
    try:
        try:
            assert_employee_allows_module(access_c2, org_id, user_id, "switch_role")
        except MobilePinAccessDeniedError:
            record_pin_attempt(
                conn,
                org_id,
                ip_address,
                success=False,
                user_id=user_id,
                action="pin_role_switch_module_denied_mutate",
            )
            conn.commit()
            return {"ok": False, "error": DENIED_MODULE_MESSAGE}, 403
    finally:
        try:
            access_c2.close()
        except Exception:
            pass

    try:
        open_before = get_open_job_segment(conn, session_id)
        change_source = "switch" if open_before else "assignment_selected_after_enable"
        seg = start_category_role_segment(
            conn,
            session_id,
            org_id,
            user_id,
            int(category_id),
            int(role_id),
            change_source=change_source,
            idempotency_key=key,
        )
        record_pin_attempt(
            conn, org_id, ip_address, success=True, user_id=user_id, action="pin_role_switch"
        )
        conn.commit()
        return {
            "ok": True,
            "action": "ROLE_SWITCHED",
            "employee_first_name": first_name,
            "segment": seg,
            "display_label": seg.get("employee_display_label") or seg.get("display_label"),
            "replayed": bool(seg.get("replayed")),
            "noop": bool(seg.get("noop")),
            "unchanged": bool(seg.get("unchanged") or seg.get("noop") or seg.get("replayed")),
            "shift_session_id": session_id,
        }, 200
    except IdempotencyConflictError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "code": "idempotency_conflict"}, 409
    except ValueError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        record_pin_attempt(
            conn, org_id, ip_address, success=False, user_id=user_id, action="pin_role_switch_fail"
        )
        try:
            conn.commit()
        except Exception:
            pass
        return {"ok": False, "error": str(e) or MISSING_ASSIGNMENT_MESSAGE}, 400
    except Exception:
        logger.exception("pin role switch failed user=%s org=%s", user_id, org_id)
        try:
            conn.rollback()
        except Exception:
            pass
        record_pin_attempt(conn, org_id, ip_address, success=False, user_id=user_id)
        try:
            conn.commit()
        except Exception:
            pass
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 500
