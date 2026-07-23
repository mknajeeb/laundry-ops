"""
Employee phone PIN hub: one PIN → permission-gated feature menu.

Features (v1):
- switch_role: org flags (shared device + category/role tracking)
- checklist: maintenance.tasks.* (or FRONT_DESK/OPS role fallback) + shared device
- inventory: inventory.* (or FRONT_DESK/OPS role fallback) + inventory module on
"""

from __future__ import annotations

from typing import Any, Callable, Optional

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
from backend.category_role_tracking_settings import is_category_role_tracking_enabled
from backend.maintenance_task_list_pin import issue_pin_session_token
from backend.payroll_identity import payroll_profiles_active

HUB_SESSION_SALT = "employee-pin-hub-v1"
HUB_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60

INVENTORY_PERM_KEYS = (
    "inventory.view",
    "inventory.dashboard.view",
    "inventory.check.view",
    "inventory.orders.view",
    "inventory.reports.view",
    "inventory.settings.view",
    "inventory.settings.manage",
)
CHECKLIST_PERM_KEYS = (
    "maintenance.tasks.view",
    "maintenance.tasks.update",
    "maintenance.tasks.submit",
    "maintenance.tasks.manage",
)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=HUB_SESSION_SALT,
    )


def issue_hub_session_token(*, organization_id: int, employee_id: int) -> str:
    return _serializer().dumps(
        {
            "purpose": "employee_pin_hub",
            "organization_id": int(organization_id),
            "employee_id": int(employee_id),
        }
    )


def verify_hub_session_token(token: str) -> dict:
    if not token:
        raise ValueError("Missing session")
    try:
        data = _serializer().loads(token, max_age=HUB_SESSION_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise ValueError("Session expired. Enter your PIN again.") from exc
    except BadSignature as exc:
        raise ValueError("Invalid session. Enter your PIN again.") from exc
    if not isinstance(data, dict) or data.get("purpose") != "employee_pin_hub":
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


def _role_set(matched: dict) -> set[str]:
    roles = matched.get("_roles") or []
    return {str(r).upper() for r in roles}


def _tenant_module_enabled(conn, org_id: int, module_key: str) -> bool:
    """Empty entitlements table / no rows ⇒ all modules on (same as app.load_tenant_modules_map)."""
    from backend.ta_helpers import table_exists

    c = conn.cursor(dictionary=True)
    try:
        if not table_exists(c, "tenant_entitlements"):
            return True
        c.execute(
            "SELECT 1 FROM tenant_entitlements WHERE organization_id = %s LIMIT 1",
            (int(org_id),),
        )
        if c.fetchone() is None:
            return True
        c.execute(
            "SELECT enabled FROM tenant_entitlements WHERE organization_id = %s AND module_key = %s LIMIT 1",
            (int(org_id), str(module_key)),
        )
        row = c.fetchone()
        if row is None:
            return True  # module not listed ⇒ default on
        return bool(row.get("enabled"))
    finally:
        c.close()


def _permission_keys(conn, user_id: int, effective_keys_fn: Optional[Callable]) -> set[str]:
    if effective_keys_fn is None:
        return set()
    try:
        return set(effective_keys_fn(conn, int(user_id)) or set())
    except Exception:
        return set()


def _has_any_perm(keys: set[str], wanted: tuple[str, ...]) -> bool:
    return any(k in keys for k in wanted)


def _has_prefix(keys: set[str], prefix: str) -> bool:
    return any(str(k).startswith(prefix) for k in keys)


def resolve_hub_features(
    conn,
    *,
    org_id: int,
    matched: dict,
    effective_keys_fn: Optional[Callable] = None,
) -> dict[str, Any]:
    """
    Return feature tiles the employee may open from the hub.
    """
    roles = _role_set(matched)
    keys = _permission_keys(conn, int(matched["id"]), effective_keys_fn)
    shared = shared_device_attendance_enabled(conn, org_id)
    tracking = is_category_role_tracking_enabled(conn, org_id)
    floor_or_ops = bool(roles & {"FRONT_DESK", "OPS"})

    # Switch role — org feature flags (clocked-in enforced when opening the feature).
    switch_role = bool(shared and tracking)

    # Checklist — prefer explicit maintenance.tasks.*; else FRONT_DESK/OPS fallback.
    if _has_prefix(keys, "maintenance.tasks."):
        checklist = _has_any_perm(keys, CHECKLIST_PERM_KEYS)
    else:
        checklist = floor_or_ops
    checklist = bool(checklist and shared)

    # Inventory — module on + inventory.* or FRONT_DESK/OPS.
    inventory_module = _tenant_module_enabled(conn, org_id, "inventory")
    if _has_prefix(keys, "inventory."):
        inventory = _has_any_perm(keys, INVENTORY_PERM_KEYS)
    else:
        inventory = floor_or_ops
    inventory = bool(inventory and inventory_module)

    return {
        "switch_role": {
            "id": "switch_role",
            "allowed": switch_role,
            "path": "/attendance/role",
        },
        "checklist": {
            "id": "checklist",
            "allowed": checklist,
            "path": "/attendance/maintenance",
        },
        "inventory": {
            "id": "inventory",
            "allowed": inventory,
            "path": "/inventory",
        },
    }


def perform_pin_hub_open(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
    *,
    effective_keys_fn: Optional[Callable] = None,
) -> tuple[dict, int]:
    """
    Validate org slug + attendance PIN and return hub session + allowed features.
    Does not create a full Washpro auth_sessions row (inventory mints that on demand).
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

    matched = resolve_user_by_attendance_pin(conn, org_id, pin_clean, fetch_roles_fn)
    if not matched:
        record_pin_attempt(conn, org_id, ip_address, False)
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    features = resolve_hub_features(
        conn,
        org_id=org_id,
        matched=matched,
        effective_keys_fn=effective_keys_fn,
    )
    allowed = [f for f in features.values() if f.get("allowed")]
    if not allowed:
        record_pin_attempt(conn, org_id, ip_address, True)
        return {
            "ok": False,
            "error": "No PIN features are available for your account.",
            "features": features,
        }, 403

    record_pin_attempt(conn, org_id, ip_address, True)
    employee_id = int(matched["id"])
    hub_token = issue_hub_session_token(organization_id=org_id, employee_id=employee_id)

    maintenance_token = None
    if features["checklist"]["allowed"]:
        maintenance_token = issue_pin_session_token(
            organization_id=org_id, employee_id=employee_id
        )

    first = _employee_first_name(matched)
    display = (
        (matched.get("display_name") or "").strip()
        or f"{(matched.get('first_name') or '').strip()} {(matched.get('last_name') or '').strip()}".strip()
        or first
    )

    return {
        "ok": True,
        "token": hub_token,
        "organization_id": org_id,
        "organization_slug": org_slug,
        "employee_id": employee_id,
        "employee_name": display,
        "employee_first_name": first,
        "expires_in_seconds": HUB_SESSION_MAX_AGE_SECONDS,
        "features": features,
        "maintenance_token": maintenance_token,
    }, 200
