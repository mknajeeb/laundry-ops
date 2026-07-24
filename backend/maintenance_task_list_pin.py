"""PIN session helpers for the employee Maintenance Task List."""

from __future__ import annotations

from typing import Any, Optional

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.attendance_pin_punch import (
    INVALID_PIN_MESSAGE,
    KIOSK_DISABLED_MESSAGE,
    PIN_LEN_KIOSK,
    fetch_organization_by_slug,
    is_rate_limited,
    record_pin_attempt,
    resolve_user_by_attendance_pin,
    shared_device_attendance_enabled,
)
from backend.maintenance_task_list_constants import (
    PIN_SESSION_MAX_AGE_SECONDS,
    PIN_SESSION_SALT,
)
from backend.payroll_identity import payroll_profiles_active


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=PIN_SESSION_SALT,
    )


def issue_pin_session_token(*, organization_id: int, employee_id: int) -> str:
    return _serializer().dumps(
        {
            "purpose": "maintenance_task_list",
            "organization_id": int(organization_id),
            "employee_id": int(employee_id),
        }
    )


def verify_pin_session_token(token: str) -> dict:
    if not token:
        raise ValueError("Missing session")
    try:
        data = _serializer().loads(token, max_age=PIN_SESSION_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise ValueError("Session expired. Enter your PIN again.") from exc
    except BadSignature as exc:
        raise ValueError("Invalid session. Enter your PIN again.") from exc
    if not isinstance(data, dict) or data.get("purpose") != "maintenance_task_list":
        raise ValueError("Invalid session. Enter your PIN again.")
    try:
        org_id = int(data["organization_id"])
        emp_id = int(data["employee_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid session. Enter your PIN again.") from exc
    return {"organization_id": org_id, "employee_id": emp_id}


def _employee_first_name(matched: dict) -> str:
    for key in ("first_name", "preferred_name", "display_name"):
        val = (matched.get(key) or "").strip()
        if val:
            return val.split()[0] if key == "display_name" else val
    return "there"


def perform_pin_maintenance_open(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
) -> tuple[dict, int]:
    """
    Validate org slug + attendance PIN and return a short-lived maintenance session.
    Does not create a full Washpro auth_sessions row.
    """
    org_slug = (organization_slug or "").strip().lower()
    pin_clean = str(pin or "").strip()

    if not org_slug or not pin_clean:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400
    if not pin_clean.isdigit() or len(pin_clean) != PIN_LEN_KIOSK:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400

    if not payroll_profiles_active(conn):
        return {"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503

    org = fetch_organization_by_slug(conn, org_slug)
    if not org:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    org_id = int(org["id"])
    if is_rate_limited(conn, org_id, ip_address):
        return {"ok": False, "error": "Too many attempts. Please try again later."}, 429

    if not shared_device_attendance_enabled(conn, org_id):
        record_pin_attempt(conn, org_id, ip_address, False)
        return {"ok": False, "error": "Kiosk attendance is not enabled for this organization."}, 403

    matched = resolve_user_by_attendance_pin(conn, org_id, pin_clean, fetch_roles_fn)
    if not matched:
        record_pin_attempt(conn, org_id, ip_address, False)
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    employee_id = int(matched["id"])
    try:
        from backend.maintenance_task_list_module import (
            employee_assigned_for_date,
            ensure_maintenance_task_list_tables,
        )

        cursor = conn.cursor(dictionary=True)
        try:
            ensure_maintenance_task_list_tables(cursor)
            if not employee_assigned_for_date(cursor, org_id, employee_id):
                record_pin_attempt(conn, org_id, ip_address, True)
                return {
                    "ok": False,
                    "error": "You are not assigned to the maintenance checklist for today.",
                }, 403
        finally:
            try:
                cursor.close()
            except Exception:
                pass
    except Exception:
        pass

    record_pin_attempt(conn, org_id, ip_address, True)
    token = issue_pin_session_token(organization_id=org_id, employee_id=employee_id)
    first = _employee_first_name(matched)
    display = (
        (matched.get("display_name") or "").strip()
        or f"{(matched.get('first_name') or '').strip()} {(matched.get('last_name') or '').strip()}".strip()
        or first
    )
    return {
        "ok": True,
        "token": token,
        "organization_id": org_id,
        "organization_slug": org_slug,
        "employee_id": employee_id,
        "employee_name": display,
        "employee_first_name": first,
        "expires_in_seconds": PIN_SESSION_MAX_AGE_SECONDS,
    }, 200
