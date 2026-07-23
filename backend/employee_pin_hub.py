"""
Employee phone PIN hub: one PIN → assignable feature menu buttons.

Org assigns which buttons exist (pin_menu in clock_payroll_ui_json).
Permissions still gate who can open checklist / inventory.
Add new features to PIN_HUB_FEATURE_DEFS later.
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

# Extensible registry — add entries here for new mobile PIN buttons.
PIN_HUB_FEATURE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "switch_role",
        "label": "Switch Role",
        "path": "/attendance/role",
    },
    {
        "id": "checklist",
        "label": "End-of-day checklist",
        "path": "/attendance/maintenance",
    },
    {
        "id": "inventory",
        "label": "Inventory",
        "path": "/inventory",
    },
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
            return True
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


def load_pin_menu_settings(conn, org_id: int) -> dict:
    from backend.ta_routes import load_clock_payroll_ui

    ui = load_clock_payroll_ui(conn, int(org_id))
    pm = ui.get("pin_menu") if isinstance(ui, dict) else None
    base_feats = {d["id"]: True for d in PIN_HUB_FEATURE_DEFS}
    if not isinstance(pm, dict):
        return {"enabled": True, "features": base_feats}
    feats = dict(base_feats)
    raw_feats = pm.get("features") if isinstance(pm.get("features"), dict) else {}
    for k, v in raw_feats.items():
        feats[str(k)] = bool(v)
    return {
        "enabled": bool(pm.get("enabled", True)),
        "features": feats,
    }


def _org_feature_enabled(pin_menu: dict, feature_id: str) -> bool:
    if not pin_menu.get("enabled", True):
        return False
    feats = pin_menu.get("features") or {}
    if feature_id not in feats:
        # Unknown / newly added feature defaults on until admin turns it off.
        return True
    return bool(feats.get(feature_id))


def _user_may_use_feature(
    conn,
    *,
    org_id: int,
    matched: dict,
    feature_id: str,
    keys: set[str],
    roles: set[str],
) -> bool:
    """
    Extra gates beyond org pin_menu assignment.
    Checklist/inventory: any employee with a valid attendance PIN (org toggle is the assigner).
    Switch role: still requires category/role tracking.
    """
    if feature_id == "switch_role":
        return bool(is_category_role_tracking_enabled(conn, org_id))

    if feature_id == "checklist":
        return True

    if feature_id == "inventory":
        return bool(_tenant_module_enabled(conn, org_id, "inventory"))

    return False


def resolve_hub_features(
    conn,
    *,
    org_id: int,
    matched: dict,
    effective_keys_fn: Optional[Callable] = None,
) -> dict[str, Any]:
    """
    Return feature tiles for the mobile PIN menu.
    Org pin_menu assigns which buttons exist; feature defs add small extra gates.
    """
    roles = _role_set(matched)
    keys = _permission_keys(conn, int(matched["id"]), effective_keys_fn)
    pin_menu = load_pin_menu_settings(conn, org_id)

    out: dict[str, Any] = {}
    for defn in PIN_HUB_FEATURE_DEFS:
        fid = defn["id"]
        org_on = _org_feature_enabled(pin_menu, fid)
        user_ok = (
            _user_may_use_feature(
                conn,
                org_id=org_id,
                matched=matched,
                feature_id=fid,
                keys=keys,
                roles=roles,
            )
            if org_on
            else False
        )
        out[fid] = {
            "id": fid,
            "label": defn["label"],
            "path": defn["path"],
            "org_enabled": org_on,
            "allowed": bool(org_on and user_ok),
        }
    return out


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

    pin_menu = load_pin_menu_settings(conn, org_id)
    if not pin_menu.get("enabled", True):
        record_pin_attempt(conn, org_id, ip_address, False)
        return {"ok": False, "error": "Mobile PIN menu is disabled for this organization."}, 403

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
    # Stable button order for the client.
    feature_order = [d["id"] for d in PIN_HUB_FEATURE_DEFS]
    allowed = [features[fid] for fid in feature_order if features.get(fid, {}).get("allowed")]
    if not allowed:
        record_pin_attempt(conn, org_id, ip_address, True)
        return {
            "ok": False,
            "error": "No PIN menu buttons are available for your account.",
            "features": features,
            "feature_order": feature_order,
        }, 403

    record_pin_attempt(conn, org_id, ip_address, True)
    employee_id = int(matched["id"])
    hub_token = issue_hub_session_token(organization_id=org_id, employee_id=employee_id)

    maintenance_token = None
    if features.get("checklist", {}).get("allowed"):
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
        "feature_order": feature_order,
        "maintenance_token": maintenance_token,
    }, 200
