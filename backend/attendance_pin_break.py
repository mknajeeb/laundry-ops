"""
Public PIN Take Break / Resume Work for Mobile Ops hub.

Does not issue Bearer tokens. Reuses hub_token after PIN Hub unlock.
"""

from __future__ import annotations

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
from backend.attendance_pin_role_switch import (
    NOT_CLOCKED_IN_MESSAGE,
    _employee_first_name,
    _resolve_user_by_hub_token,
)
from backend.category_role_tracking_settings import is_category_role_tracking_enabled
from backend.payroll_identity import payroll_profiles_active
from backend.shift_break_ops import BreakOpError, end_break_on_session, start_break_on_session
from backend.ta_routes import get_open_break, json_safe

NOT_ON_BREAK_MESSAGE = "You are not on break."
ALREADY_ON_BREAK_MESSAGE = "Break already in progress."
FEATURE_DISABLED_MESSAGE = "Category & Role Tracking is disabled for this organization."
MISSING_IDEMPOTENCY_MESSAGE = (
    "idempotency_key required (body.idempotency_key or Idempotency-Key header)"
)


def _resolve_matched(
    conn,
    org_id: int,
    org_slug: str,
    pin_clean: str,
    hub_clean: Optional[str],
    fetch_roles_fn,
    ip_address: str,
    *,
    action_prefix: str,
):
    matched = None
    if hub_clean:
        matched = _resolve_user_by_hub_token(
            conn, org_id, org_slug, hub_clean, fetch_roles_fn
        )
        if not matched:
            record_pin_attempt(
                conn, org_id, ip_address, success=False, action=f"{action_prefix}_hub_fail"
            )
            conn.commit()
            return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 401)
    else:
        matched = resolve_user_by_attendance_pin(conn, org_id, pin_clean, fetch_roles_fn)
        if not matched:
            record_pin_attempt(
                conn, org_id, ip_address, success=False, action=f"{action_prefix}_fail"
            )
            conn.commit()
            return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 401)
    return matched, None


def _gate_common(
    conn,
    organization_slug: str,
    pin: str,
    hub_token: Optional[str],
    fetch_roles_fn,
    ip_address: str,
    *,
    action_prefix: str,
):
    org_slug = (organization_slug or "").strip().lower()
    pin_clean = str(pin or "").strip()
    hub_clean = str(hub_token or "").strip() or None

    if not org_slug:
        return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 400)
    if not hub_clean and not pin_clean:
        return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 400)
    if pin_clean and (not pin_clean.isdigit() or len(pin_clean) != PIN_LEN_KIOSK):
        return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 400)

    if not payroll_profiles_active(conn):
        return None, ({"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503)

    org = fetch_organization_by_slug(conn, org_slug)
    if not org:
        return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 401)

    org_id = int(org["id"])
    if not shared_device_attendance_enabled(conn, org_id):
        return None, ({"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503)

    if is_rate_limited(conn, org_id, ip_address):
        return None, ({"ok": False, "error": INVALID_PIN_MESSAGE}, 429)

    matched, err = _resolve_matched(
        conn,
        org_id,
        org_slug,
        pin_clean,
        hub_clean,
        fetch_roles_fn,
        ip_address,
        action_prefix=action_prefix,
    )
    if err:
        return None, err

    user_id = int(matched["id"])
    active = _active_shift(conn, user_id)
    if not active:
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=False,
            user_id=user_id,
            action=f"{action_prefix}_not_in",
        )
        conn.commit()
        return None, ({"ok": False, "error": NOT_CLOCKED_IN_MESSAGE}, 400)

    return {
        "org_id": org_id,
        "org_slug": org_slug,
        "matched": matched,
        "user_id": user_id,
        "session": active,
    }, None


def perform_pin_break_start(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
    *,
    hub_token: Optional[str] = None,
) -> tuple[dict, int]:
    """Start break: close open role segment, open shift_breaks, keep session active."""
    ctx, err = _gate_common(
        conn,
        organization_slug,
        pin,
        hub_token,
        fetch_roles_fn,
        ip_address,
        action_prefix="pin_break_start",
    )
    if err:
        return err

    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    session = ctx["session"]
    matched = ctx["matched"]

    if get_open_break(conn, int(session["id"])):
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=False,
            user_id=user_id,
            action="pin_break_start_already",
        )
        conn.commit()
        return {"ok": False, "error": ALREADY_ON_BREAK_MESSAGE}, 400

    try:
        row = start_break_on_session(conn, int(session["id"]))
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=True,
            user_id=user_id,
            action="pin_break_start",
        )
        conn.commit()
        return {
            "ok": True,
            "action": "break_start",
            "employee_first_name": _employee_first_name(matched),
            "shift_session_id": int(session["id"]),
            "break": json_safe(row),
            "on_break": True,
        }, 200
    except BreakOpError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": e.message, **(e.payload or {})}, e.status


def perform_pin_break_resume(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
    *,
    hub_token: Optional[str] = None,
    category_id: Any = None,
    role_id: Any = None,
    idempotency_key: Optional[str] = None,
) -> tuple[dict, int]:
    """
    Resume from break: end break + start role segment (shared Role selector).

    Without category/role: return selection tree (needs_selection).
    """
    ctx, err = _gate_common(
        conn,
        organization_slug,
        pin,
        hub_token,
        fetch_roles_fn,
        ip_address,
        action_prefix="pin_break_resume",
    )
    if err:
        return err

    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    session = ctx["session"]
    matched = ctx["matched"]
    session_id = int(session["id"])

    if not get_open_break(conn, session_id):
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=False,
            user_id=user_id,
            action="pin_break_resume_not_on_break",
        )
        conn.commit()
        return {"ok": False, "error": NOT_ON_BREAK_MESSAGE}, 400

    if not is_category_role_tracking_enabled(conn, org_id):
        record_pin_attempt(
            conn,
            org_id,
            ip_address,
            success=False,
            user_id=user_id,
            action="pin_break_resume_tracking_off",
        )
        conn.commit()
        return {"ok": False, "error": FEATURE_DISABLED_MESSAGE}, 403

    first_name = _employee_first_name(matched)
    has_assignment = category_id is not None and role_id is not None and str(category_id) and str(
        role_id
    )

    if not has_assignment:
        from backend.shift_job_tracking import list_active_selection_tree, seed_default_categories_and_roles

        c = conn.cursor(dictionary=True)
        try:
            seed_default_categories_and_roles(c, org_id)
            tree = list_active_selection_tree(c, org_id)
        finally:
            try:
                c.close()
            except Exception:
                pass
        record_pin_attempt(
            conn, org_id, ip_address, success=True, user_id=user_id, action="pin_break_resume_open"
        )
        conn.commit()
        return {
            "ok": True,
            "needs_selection": True,
            "resume_from_break": True,
            "selection_tree": tree,
            "employee_first_name": first_name,
            "shift_session_id": session_id,
            "on_break": True,
        }, 200

    key = (idempotency_key or "").strip()
    if not key:
        return {"ok": False, "error": MISSING_IDEMPOTENCY_MESSAGE}, 400
    if len(key) > 64:
        return {"ok": False, "error": "idempotency_key must be at most 64 characters"}, 400

    try:
        row, segment = end_break_on_session(
            conn,
            session_id,
            org_id,
            user_id,
            category_id=category_id,
            role_id=role_id,
            require_role_when_tracking=True,
        )
        record_pin_attempt(
            conn, org_id, ip_address, success=True, user_id=user_id, action="pin_break_resume"
        )
        conn.commit()
        body = {
            "ok": True,
            "action": "break_resume",
            "employee_first_name": first_name,
            "shift_session_id": session_id,
            "break": json_safe(row),
            "on_break": False,
            "segment": segment,
            "employee_display_label": (segment or {}).get("employee_display_label")
            or (segment or {}).get("display_label"),
        }
        return body, 200
    except BreakOpError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": e.message, **(e.payload or {})}, e.status
