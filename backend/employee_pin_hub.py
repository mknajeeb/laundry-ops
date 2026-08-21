"""
Employee phone PIN hub: one PIN → assignable feature menu buttons.

Org assigns which buttons exist (pin_menu in clock_payroll_ui_json).
Stage A AND-gates Switch Role and End-of-Day Checklist with employee Mobile
PIN Access. Permissions still gate who can open checklist / inventory.
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
    _active_shift,
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

PIN_HUB_FEATURE_DEFS = (
    {
        "id": "switch_role",
        "label": "Role",
        "path": "/attendance/role",
    },
    {
        "id": "revenue_cost",
        "label": "Revenue / Cash",
        "path": "/revenue-cash",
    },
    {
        "id": "checklist",
        "label": "End-of-Day Checklist",
        "path": "/attendance/maintenance",
    },
    {
        "id": "inventory",
        "label": "Inventory",
        "path": "/inventory",
    },
    {
        "id": "team_status",
        "label": "Team Status",
        "path": "/team-status",
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


def _tenant_modules_enabled(conn, org_id: int, module_keys: tuple[str, ...]) -> dict[str, bool]:
    """Resolve several tenant entitlements in one short path (cached schema checks)."""
    from backend.ta_helpers import table_exists

    out = {str(k): True for k in module_keys}
    c = conn.cursor(dictionary=True)
    try:
        if not table_exists(c, "tenant_entitlements"):
            return out
        c.execute(
            "SELECT 1 FROM tenant_entitlements WHERE organization_id = %s LIMIT 1",
            (int(org_id),),
        )
        if c.fetchone() is None:
            return out
        placeholders = ", ".join(["%s"] * len(module_keys))
        c.execute(
            f"""
            SELECT module_key, enabled
            FROM tenant_entitlements
            WHERE organization_id = %s AND module_key IN ({placeholders})
            """,
            (int(org_id), *[str(k) for k in module_keys]),
        )
        for row in c.fetchall() or []:
            key = str(row.get("module_key") or "")
            if key in out:
                out[key] = bool(row.get("enabled"))
        return out
    finally:
        c.close()


def _tenant_module_enabled(conn, org_id: int, module_key: str) -> bool:
    return bool(_tenant_modules_enabled(conn, org_id, (str(module_key),)).get(str(module_key), True))


def _permission_keys(conn, user_id: int, effective_keys_fn: Optional[Callable]) -> set[str]:
    # Kept for tests/callers; PIN Hub feature tiles no longer depend on Washpro
    # role permission keys (Mobile PIN Access is the employee source).
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


def attendance_snapshot_for_hub(
    conn,
    org_id: int,
    user_id: int,
    *,
    employee_module_access: Optional[dict] = None,
    pin_menu: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Read-only punch state for PIN Menu tile labels/visibility.
    Does not change clock/break rules — presentation metadata only.
    """
    pm = pin_menu if isinstance(pin_menu, dict) else load_pin_menu_settings(conn, int(org_id))
    if "shared_device_attendance" in pm:
        shared = bool(pm.get("shared_device_attendance"))
    else:
        shared = bool(shared_device_attendance_enabled(conn, int(org_id)))
    allow_clock = bool(pm.get("allow_clock_from_hub", True))
    emp_access = employee_module_access
    if emp_access is None:
        from backend.employee_mobile_pin_access import resolve_employee_mobile_pin_access

        cursor = conn.cursor(dictionary=True)
        try:
            emp_access = resolve_employee_mobile_pin_access(cursor, int(org_id), int(user_id))
        finally:
            try:
                cursor.close()
            except Exception:
                pass
    employee_allow_clock = bool(emp_access.get("clock")) if isinstance(emp_access, dict) else True
    active = _active_shift(conn, int(user_id))
    on_break = False
    break_started_at = None
    current_display_label = None
    open_seg: dict = {}
    if active:
        from backend.ta_routes import get_open_break
        from backend.shift_job_tracking import get_open_job_segment
        from backend.ta_helpers import json_safe

        open_br = get_open_break(conn, active["id"])
        on_break = bool(open_br)
        if open_br:
            # Authoritative break start for Mobile Ops Break Mode timer.
            break_started_at = json_safe(open_br.get("break_start_at"))
        open_seg = get_open_job_segment(conn, int(active["id"])) or {}
        from backend.mobile_ops_labels import employee_assignment_label_from_segment

        current_display_label = employee_assignment_label_from_segment(open_seg) or None
        if not current_display_label:
            label = (open_seg.get("display_label") or "").strip()
            current_display_label = label or None
    return {
        "shared_device_enabled": shared,
        "allow_clock_from_hub": allow_clock,
        "employee_allow_clock": employee_allow_clock,
        "clocked_in": bool(active),
        "on_break": on_break,
        "break_started_at": break_started_at,
        "current_display_label": current_display_label,
        "current_category_id": open_seg.get("category_id"),
        "current_role_id": open_seg.get("role_id"),
    }


def apply_attendance_gates_to_features(
    features: dict[str, Any],
    attendance: dict[str, Any],
    *,
    allow_take_break: bool = True,
) -> dict[str, Any]:
    """
    Keep Role allowed when clocked out so the tile stays visible; mark requires_clock_in
    for the client to show the shared-tablet clock-in message on tap.
    On break: hide Change Role and other working tiles; expose Resume Work only.
    When clocked in and not on break: expose Take a Break if employee Mobile PIN Access
    grants take_break (independent of Clock / Role). Resume is never gated by take_break.
    """
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in (features or {}).items()}
    role = out.get("switch_role")
    clocked_in = bool(attendance.get("clocked_in"))
    on_break = bool(attendance.get("on_break"))

    if isinstance(role, dict) and role.get("allowed"):
        if not clocked_in:
            role = dict(role)
            role["requires_clock_in"] = True
            role["blocked_reason"] = "not_clocked_in"
            out["switch_role"] = role
        elif on_break:
            # Change Role is not available on break — Resume Work handles role selection.
            role = dict(role)
            role["allowed"] = False
            role["hidden"] = True
            role["blocked_reason"] = "on_break"
            out["switch_role"] = role

    if clocked_in and not on_break and allow_take_break:
        out["take_break"] = {
            "allowed": True,
            "label": "Take a Break",
            "path": None,
        }
    else:
        out.pop("take_break", None)

    if on_break:
        out["resume_work"] = {
            "allowed": True,
            "label": "Resume Work",
            "path": "/attendance/role",
            "resume_from_break": True,
        }
        # Persistent Break Mode: hide ordinary Mobile Ops working actions.
        for fid in ("revenue_cost", "checklist", "inventory", "team_status", "clock"):
            feat = out.get(fid)
            if isinstance(feat, dict) and feat.get("allowed"):
                blocked = dict(feat)
                blocked["allowed"] = False
                blocked["hidden"] = True
                blocked["blocked_reason"] = "on_break"
                out[fid] = blocked
    else:
        out.pop("resume_work", None)

    return out


def load_pin_menu_settings(conn, org_id: int) -> dict:
    from backend.ta_helpers import as_bool
    from backend.ta_routes import load_clock_payroll_ui

    ui = load_clock_payroll_ui(conn, int(org_id))
    pm = ui.get("pin_menu") if isinstance(ui, dict) else None
    clock = ui.get("clock") if isinstance(ui, dict) else None
    shared = as_bool((clock or {}).get("shared_device_attendance"), False)
    base_feats = {d["id"]: True for d in PIN_HUB_FEATURE_DEFS}
    if not isinstance(pm, dict):
        return {
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": base_feats,
            "shared_device_attendance": shared,
        }
    feats = dict(base_feats)
    raw_feats = pm.get("features") if isinstance(pm.get("features"), dict) else {}
    for k, v in raw_feats.items():
        feats[str(k)] = bool(v)
    return {
        "enabled": bool(pm.get("enabled", True)),
        "allow_clock_from_hub": bool(pm.get("allow_clock_from_hub", True)),
        "features": feats,
        "shared_device_attendance": shared,
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
    tenant_modules: Optional[dict[str, bool]] = None,
) -> bool:
    """
    Org/module gates beyond pin_menu + employee Mobile PIN Access.

    Employee-facing Washpro role permission keys are intentionally NOT required
    here — Mobile PIN Access is the employee permission source for PIN modules.
    Manager/admin app permissions remain separate on manager routes.
    """
    del keys, roles, matched  # reserved for future non-employee gates
    if feature_id == "switch_role":
        return bool(is_category_role_tracking_enabled(conn, org_id))

    if feature_id == "checklist":
        return True

    mods = tenant_modules if isinstance(tenant_modules, dict) else None
    if feature_id == "inventory":
        if mods is not None:
            return bool(mods.get("inventory", True))
        return bool(_tenant_module_enabled(conn, org_id, "inventory"))

    if feature_id == "revenue_cost":
        if mods is not None:
            return bool(mods.get("finance", True))
        return bool(_tenant_module_enabled(conn, org_id, "finance"))

    if feature_id == "team_status":
        # Manager/supervisor roster — gated only by Mobile PIN Access grant.
        return True

    return False


def resolve_hub_features(
    conn,
    *,
    org_id: int,
    matched: dict,
    effective_keys_fn: Optional[Callable] = None,
    employee_module_access: Optional[dict] = None,
    pin_menu: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Return feature tiles for the mobile PIN menu.
    Org pin_menu ∧ employee Mobile PIN Access (ENFORCED modules) ∧ feature gates.
    """
    from backend.employee_mobile_pin_access import (
        ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES,
        resolve_employee_mobile_pin_access,
    )

    del effective_keys_fn  # unused: do not load Washpro role perms on hub open
    roles = _role_set(matched)
    keys: set[str] = set()
    pin_menu_settings = pin_menu if isinstance(pin_menu, dict) else load_pin_menu_settings(conn, org_id)
    emp_access = employee_module_access if isinstance(employee_module_access, dict) else None
    needs_emp = any(d["id"] in ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES for d in PIN_HUB_FEATURE_DEFS)
    if emp_access is None and needs_emp:
        cursor = conn.cursor(dictionary=True)
        try:
            emp_access = resolve_employee_mobile_pin_access(
                cursor, int(org_id), int(matched["id"])
            )
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    tenant_modules = _tenant_modules_enabled(conn, org_id, ("inventory", "finance"))

    out: dict[str, Any] = {}
    for defn in PIN_HUB_FEATURE_DEFS:
        fid = defn["id"]
        org_on = _org_feature_enabled(pin_menu_settings, fid)
        emp_on = (
            bool(emp_access.get(fid))
            if fid in ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES and emp_access is not None
            else True
        )
        user_ok = (
            _user_may_use_feature(
                conn,
                org_id=org_id,
                matched=matched,
                feature_id=fid,
                keys=keys,
                roles=roles,
                tenant_modules=tenant_modules,
            )
            if org_on and emp_on
            else False
        )
        out[fid] = {
            "id": fid,
            "label": defn["label"],
            "path": defn["path"],
            "org_enabled": org_on,
            "employee_allowed": emp_on,
            "allowed": bool(org_on and emp_on and user_ok),
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
    del effective_keys_fn  # hub tiles use Mobile PIN Access, not Washpro role keys
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

    employee_id = int(matched["id"])
    from backend.employee_mobile_pin_access import resolve_employee_mobile_pin_access

    access_cursor = conn.cursor(dictionary=True)
    try:
        emp_access = resolve_employee_mobile_pin_access(access_cursor, org_id, employee_id)
    finally:
        try:
            access_cursor.close()
        except Exception:
            pass

    features = resolve_hub_features(
        conn,
        org_id=org_id,
        matched=matched,
        employee_module_access=emp_access,
        pin_menu=pin_menu,
    )
    attendance = attendance_snapshot_for_hub(
        conn,
        org_id,
        employee_id,
        employee_module_access=emp_access,
        pin_menu=pin_menu,
    )
    features = apply_attendance_gates_to_features(
        features,
        attendance,
        allow_take_break=bool(emp_access.get("take_break")),
    )

    # Weekday checklist assignment: tile stays visible when org-enabled; disable if not assigned.
    checklist = features.get("checklist")
    if isinstance(checklist, dict) and checklist.get("allowed"):
        from backend.maintenance_task_list_module import (
            employee_assigned_for_date,
            ensure_maintenance_task_list_tables,
        )

        cursor = conn.cursor(dictionary=True)
        try:
            ensure_maintenance_task_list_tables(cursor)
            assigned = employee_assigned_for_date(cursor, org_id, employee_id)
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        checklist = dict(checklist)
        checklist["assigned_today"] = bool(assigned)
        if not assigned:
            checklist["disabled"] = True
            checklist["disabled_helper"] = "No maintenance checklist assigned today."
        features["checklist"] = checklist

    # Prefetch org selection tree when Role or Resume Work is usable from hub.
    selection_tree = None
    switch = features.get("switch_role") if isinstance(features.get("switch_role"), dict) else {}
    resume = features.get("resume_work") if isinstance(features.get("resume_work"), dict) else {}
    need_tree = (
        (
            switch.get("allowed")
            and attendance.get("clocked_in")
            and not attendance.get("on_break")
            and not switch.get("requires_clock_in")
            and not switch.get("disabled")
        )
        or (resume.get("allowed") and attendance.get("on_break"))
    )
    if need_tree:
        from backend.shift_job_tracking import list_active_selection_tree

        tree_c = conn.cursor(dictionary=True)
        try:
            selection_tree = list_active_selection_tree(tree_c, org_id)
        finally:
            try:
                tree_c.close()
            except Exception:
                pass

    # Stable button order for the client (dynamic attendance tiles injected after Role).
    feature_order = [d["id"] for d in PIN_HUB_FEATURE_DEFS]
    if features.get("resume_work", {}).get("allowed"):
        # Break Mode: only Resume Work is meaningful; other tiles are gated hidden.
        feature_order = ["resume_work"]
    elif features.get("take_break", {}).get("allowed"):
        feature_order = ["switch_role", "take_break"] + [
            x for x in feature_order if x not in ("switch_role", "take_break")
        ]

    record_pin_attempt(conn, org_id, ip_address, True)
    hub_token = issue_hub_session_token(organization_id=org_id, employee_id=employee_id)

    maintenance_token = None
    if features.get("checklist", {}).get("allowed") and not features.get("checklist", {}).get(
        "disabled"
    ):
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
        "attendance": attendance,
        "selection_tree": selection_tree,
    }, 200
