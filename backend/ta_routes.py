import json
import math
import os
import re
import threading
from io import BytesIO
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Optional

import mysql.connector
from flask import Blueprint, Response, current_app, g, jsonify, request, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.db import get_db
from backend.payroll_identity import (
    eastern_now_naive,
    ensure_payroll_profile_for_user_id,
    ensure_payroll_profile_for_washpro,
    extend_permissions_for_platform_operator,
    extend_permissions_for_tenant_admin,
    fetch_payroll_profile_row,
    get_or_create_payroll_cycle_unified,
    get_payroll_period_settings,
    payroll_profiles_active,
    set_payroll_period_settings,
    user_has_perm_washpro,
    washpro_bearer_is_platform_operator,
)
from backend.onesignal_client import notify_geofence_outside_cooldown
from backend.hr_forms.delivery import build_hr_forms_inventory, infer_user_form_lanes
from backend.hr_forms.registry import get_form_def, resolve_form_asset_path
from backend.hr_pdf_acroform import (
    build_ny_it2104_field_values,
    build_irs_w4_field_values,
    build_irs_w9_field_values,
    fill_acroform_pdf_bytes,
    work_json_from_hr_row,
)
from backend.hr_compliance import (
    build_document_records_export_zip,
    build_i9_field_values,
    build_i9_field_values_es,
    clock_in_blocked_by_expired_documents,
    create_employee_document_record,
    delete_employee_document_record,
    ensure_document_compliance_tables,
    ensure_hr_extended_profiles_table,
    fetch_hr_org_settings,
    fetch_organization_document_records_by_ids,
    fill_i9_pdf_bytes,
    get_document_compliance_policy,
    get_merged_hr_profile,
    list_employee_document_records,
    list_expiring_document_records,
    list_organization_document_records,
    resolve_i9_template_path,
    update_employee_document_record,
    upsert_document_compliance_policy,
    upsert_generated_hr_form_record,
    upsert_hr_extended_profile,
)
from backend.ta_helpers import (
    as_bool,
    haversine_meters,
    hash_password,
    invalidate_schema_cache,
    json_safe,
    mask_tax_id_for_api_response,
    table_exists,
    table_has_column,
    verify_password,
)
from backend.ops_ui_flags import get_ops_ui_flags

ta_bp = Blueprint("ta_api", __name__)


def _coerce_lat_lng(lat, lng):
    """Parse lat/lng from query/json (strings allowed). Returns (None, None) if invalid."""
    if lat is None or lng is None:
        return None, None
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(la) or not math.isfinite(lo):
        return None, None
    return la, lo


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="laundry-ta-auth")


def create_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def parse_token(token: str) -> dict:
    return _serializer().loads(token, max_age=60 * 60 * 24 * 7)


def get_setting(conn, organization_id: int, key: str, default=None):
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s",
        (int(organization_id), key),
    )
    r = c.fetchone()
    return r["svalue"] if r else default


def set_setting(conn, organization_id: int, key: str, value: str):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


_CLOCK_PAYROLL_UI_KEY = "clock_payroll_ui_json"


def _default_clock_ui_dict() -> dict:
    return {
        "outside_geofence_label_enabled": True,
        "outside_geofence_label_text": "You are outside the designated work area.",
        "clock_banner_enabled": False,
        "clock_banner_text": "",
        "show_outside_geofence_on_clock": True,
        "show_outside_geofence_on_summary": True,
        "ask_personal_laundry_bags": False,
        "est_midnight_force_clock_out": True,
        "clock_in_gate_enabled": True,
        "clock_in_gate_strict": False,
        "dim_app_until_clocked_in": False,
        "sign_out_after_clock_out": False,
        "shared_device_attendance": False,
        "clock_out_require_inside_geofence": True,
        "geofence_reminder_enabled": True,
        "geofence_reminder_hours": 1.5,
        "geofence_reminder_cooldown_hours": 6.0,
    }


def _default_payroll_screen_dict() -> dict:
    return {
        "nav_payroll_visible": True,
        "tab_live": True,
        "tab_maintenance": True,
        "tab_period": True,
        "tab_clock_ui": True,
        "monitor_show_cycle_filter": True,
        "monitor_show_user_filter": True,
        "monitor_show_apply": True,
        "monitor_col_id": True,
        "monitor_col_user": True,
        "monitor_col_cycle": True,
        "monitor_col_clock_in": True,
        "monitor_col_clock_out": True,
        "monitor_col_net": True,
        "monitor_col_status": True,
        "monitor_col_geofence": True,
        "monitor_col_gross": True,
        "monitor_col_breaks": True,
        "monitor_col_geofence_out": True,
        "monitor_col_bags": True,
        "monitor_col_period_adj": True,
        "monitor_col_actions": True,
    }


def load_clock_payroll_ui(conn, organization_id: int) -> dict:
    raw = get_setting(conn, organization_id, _CLOCK_PAYROLL_UI_KEY, None)
    out = {"clock": _default_clock_ui_dict(), "payroll": _default_payroll_screen_dict()}
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
        if isinstance(parsed.get("clock"), dict):
            out["clock"] = {**_default_clock_ui_dict(), **parsed["clock"]}
        if isinstance(parsed.get("payroll"), dict):
            out["payroll"] = {**_default_payroll_screen_dict(), **parsed["payroll"]}
    except Exception:
        pass
    return out


def _tenant_id():
    return int(g.ta_user.get("organization_id") or 1)


# Bump when WORKSPACE_PAYROLL_EXTRA / seed lists change so each org re-runs ensure once per process.
_PEOPLE_WORKSPACE_ENSURE_VERSION = 4
_people_workspace_ensured_version_by_org: dict[int, int] = {}


def _ensure_people_workspace(conn) -> None:
    """Idempotent DDL + seed for People/payroll workspace. Runs once per org per worker (cached)."""
    oid = _tenant_id()
    if _people_workspace_ensured_version_by_org.get(oid) == _PEOPLE_WORKSPACE_ENSURE_VERSION:
        return

    from backend.hr_workspace_schema import (
        ensure_people_workspace_schema,
        seed_org_hr_lookups_if_empty,
        seed_worker_categories_if_missing,
    )

    cur = conn.cursor()
    ensure_people_workspace_schema(cur)
    try:
        seed_org_hr_lookups_if_empty(cur, oid)
    except Exception:
        pass
    try:
        seed_worker_categories_if_missing(cur, oid)
    except Exception:
        pass
    conn.commit()
    invalidate_schema_cache()
    _people_workspace_ensured_version_by_org[oid] = _PEOPLE_WORKSPACE_ENSURE_VERSION


def _user_wants_push_notification(conn, u: dict) -> bool:
    """Honor user_notification_preferences.push_out (Washpro user id) when payroll mode is on."""
    if not payroll_profiles_active(conn):
        return True
    uid = int(u.get("id") or 0)
    if not uid:
        return True
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "user_notification_preferences"):
        return True
    c.execute(
        "SELECT push_out FROM user_notification_preferences WHERE user_id=%s LIMIT 1",
        (uid,),
    )
    row = c.fetchone()
    if not row:
        return True
    return bool(row.get("push_out"))


def _sanitize_role_code(raw: str) -> str:
    s = re.sub(r"[^A-Z0-9_]", "_", (raw or "").strip().upper())
    s = s.strip("_")
    return (s[:48] if s else "CUSTOM_ROLE")


def _role_visible_sql(cursor, alias="r"):
    """Platform roles (organization_id=0) plus current tenant's custom roles."""
    if table_has_column(cursor, "roles", "organization_id"):
        return (
            f"({alias}.organization_id = 0 OR {alias}.organization_id = %s)",
            (_tenant_id(),),
        )
    return "1=1", ()


def _role_mutable_by_tenant(cursor, role_id: int):
    """Tenant may delete custom role (not platform/system templates)."""
    c = cursor
    if not table_has_column(c, "roles", "organization_id"):
        return False
    c.execute(
        "SELECT organization_id, is_system FROM roles WHERE id=%s LIMIT 1",
        (int(role_id),),
    )
    row = c.fetchone()
    if not row:
        return False
    if as_bool(row.get("is_system"), default=False):
        return False
    return int(row.get("organization_id") or 0) == _tenant_id()


def _build_permission_hierarchy(flat_perms):
    """Route → section → resource → actions[]."""
    routes = {}
    for p in flat_perms:
        rk = (p.get("route_key") or "general").strip() or "general"
        rl = (p.get("route_label") or "").strip() or rk.replace("_", " ").title()
        sk = (p.get("section_key") or "").strip()
        sl = (p.get("section_label") or "").strip() or (
            sk.replace("_", " ").title() if sk else "General"
        )
        resk = (p.get("resource_key") or "").strip()
        resl = (p.get("resource_label") or "").strip()

        routes.setdefault(rk, {"route_key": rk, "route_label": rl, "_sections": {}})
        sec_bucket = routes[rk]["_sections"]
        sec_bucket.setdefault(sk, {"section_key": sk, "section_label": sl, "_resources": {}})
        r_bucket = sec_bucket[sk]["_resources"]
        r_bucket.setdefault(
            resk,
            {"resource_key": resk, "resource_label": resl, "actions": []},
        )
        r_bucket[resk]["actions"].append(
            {
                "id": p.get("id"),
                "perm_key": p.get("perm_key"),
                "action_key": (p.get("action_key") or "view"),
                "description": p.get("description"),
                "sort_order": int(p.get("sort_order") or 0),
            }
        )

    out_routes = []
    for rk in sorted(routes.keys()):
        r = routes[rk]
        sections = []
        for sk in sorted(r["_sections"].keys(), key=lambda x: (x == "", x)):
            s = r["_sections"][sk]
            resources = []
            for resk in sorted(s["_resources"].keys(), key=lambda x: (x == "", x)):
                res = s["_resources"][resk]
                res["actions"].sort(
                    key=lambda a: (a.get("sort_order") or 0, a.get("perm_key") or "")
                )
                resources.append(
                    {
                        "resource_key": res["resource_key"],
                        "resource_label": res["resource_label"],
                        "actions": res["actions"],
                    }
                )
            sections.append(
                {
                    "section_key": s["section_key"],
                    "section_label": s["section_label"],
                    "resources": resources,
                }
            )
        out_routes.append(
            {"route_key": r["route_key"], "route_label": r["route_label"], "sections": sections}
        )
    return out_routes


def _user_belongs_to_tenant(conn, user_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT organization_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
    row = c.fetchone()
    if not row:
        return False
    return int(row.get("organization_id") or 1) == _tenant_id()


def _ta_user_can_access_payroll_subject(conn, subject_user_id: int) -> bool:
    """
    Same-tenant users can access payroll/HR data for their org.
    Platform operators (SUPER_ADMIN / PLATFORM_ADMIN) may access any Washpro user that exists,
    so HR and I-9 work when the session tenant differs from the employee's organization_id.
    """
    if _user_belongs_to_tenant(conn, subject_user_id):
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    tok = auth[7:].strip()
    if not tok:
        return False
    return washpro_bearer_is_platform_operator(conn, tok)


def user_has_perm(conn, user_id: int, perm_key: str) -> bool:
    if payroll_profiles_active(conn):
        return user_has_perm_washpro(conn, user_id, perm_key)
    c = conn.cursor()
    c.execute(
        """
        SELECT 1 FROM ta_users u
        JOIN role_permissions rp ON rp.role_id = u.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE u.id = %s AND p.perm_key = %s
        LIMIT 1
        """,
        (user_id, perm_key),
    )
    return c.fetchone() is not None


def effective_washpro_permission_keys(conn, washpro_user_id: int) -> set[str]:
    """
    Permission keys exactly as GET /ta/bootstrap returns in `permissions`
    (same SQL + extend_permissions_* for unified payroll mode).

    `washpro_user_id` is always Washpro `users.id` (auth_sessions.user_id), even when the
    legacy TA path resolves roles via `ta_users.id`.
    """
    uid = int(washpro_user_id)
    if payroll_profiles_active(conn):
        c = conn.cursor(dictionary=True)
        try:
            c.execute(
                """
                SELECT DISTINCT p.perm_key
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE ur.user_id = %s
                ORDER BY p.perm_key
                """,
                (uid,),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
        finally:
            c.close()
        extend_permissions_for_platform_operator(conn, uid, perms)
        extend_permissions_for_tenant_admin(conn, uid, perms)
        return set(perms)

    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            "SELECT id FROM ta_users WHERE washpro_user_id=%s LIMIT 1",
            (uid,),
        )
        row = c.fetchone()
        if not row or row.get("id") is None:
            return set()
        ta_id = int(row["id"])
        c.execute(
            """
            SELECT p.perm_key
            FROM ta_users u
            JOIN role_permissions rp ON rp.role_id = u.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE u.id=%s
            """,
            (ta_id,),
        )
        return {r["perm_key"] for r in c.fetchall()}
    finally:
        c.close()


def fetch_user_row(conn, user_id: int):
    if payroll_profiles_active(conn):
        return fetch_payroll_profile_row(conn, int(user_id))
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT u.*, r.code AS role_code, r.name AS role_name
        FROM ta_users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = %s
        """,
        (user_id,),
    )
    u = c.fetchone()
    if u is not None and "organization_id" not in u:
        u["organization_id"] = 1
    return u


def _ta_users_table_exists(conn) -> bool:
    c = conn.cursor()
    c.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'ta_users'
        LIMIT 1
        """
    )
    return c.fetchone() is not None


def _washpro_session_row(conn, token: str):
    """Validate main-app auth_sessions token (Washpro login)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT s.user_id, s.revoked, s.expires_at,
               u.username, u.display_name, u.active
        FROM auth_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = %s
        LIMIT 1
        """,
        (token,),
    )
    row = c.fetchone()
    if not row or row.get("revoked"):
        return None
    exp = row.get("expires_at")
    if isinstance(exp, datetime) and exp < datetime.utcnow():
        return None
    if not as_bool(row.get("active"), default=False):
        return None
    return row


def _pick_default_ta_role_id(conn, washpro_user_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT r.code FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        """,
        (washpro_user_id,),
    )
    codes = {str(x["code"]).upper() for x in c.fetchall()}
    # Must match real rows in `roles` (see maintenance_inventory_auth.sql: ADMIN, OPS, FRONT_DESK).
    target = "OPS"
    if "ADMIN" in codes:
        target = "ADMIN"
    elif "FRONT_DESK" in codes:
        target = "FRONT_DESK"
    elif "OPS" in codes:
        target = "OPS"
    c.execute("SELECT id FROM roles WHERE code=%s LIMIT 1", (target,))
    r = c.fetchone()
    if r:
        return r["id"]
    c.execute(
        """
        SELECT r.id FROM roles r
        JOIN role_permissions rp ON rp.role_id = r.id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.perm_key = 'ta.clock'
        ORDER BY r.id LIMIT 1
        """
    )
    r = c.fetchone()
    return r["id"] if r else None


def _ensure_ta_user_for_washpro(conn, wp: dict):
    """Link Washpro login to a ta_users row (auto-create on first TA API use)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM ta_users WHERE washpro_user_id=%s LIMIT 1",
        (wp["user_id"],),
    )
    existing = c.fetchone()
    if existing:
        return existing
    role_id = _pick_default_ta_role_id(conn, wp["user_id"])
    if not role_id:
        return None
    username = (wp.get("username") or "user").strip() or "user"
    display = (wp.get("display_name") or username).strip()
    parts = display.split(None, 1)
    first = (parts[0] or username)[:128]
    last = (parts[1] if len(parts) > 1 else "")[:128] or first
    email = f"{username.lower()}.{wp['user_id']}@washpro.local"
    ph = hash_password("unused-washpro-sso-" + str(wp["user_id"]))
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ta_users (
              washpro_user_id, employee_id, first_name, last_name, email, hire_date,
              active, role_id, password_hash
            ) VALUES (%s,%s,%s,%s,%s,CURDATE(),1,%s,%s)
            """,
            (
                wp["user_id"],
                f"WP{wp['user_id']}",
                first,
                last,
                email,
                role_id,
                ph,
            ),
        )
        uid = cur.lastrowid
        conn.commit()
        return fetch_user_row(conn, uid)
    except Exception:
        conn.rollback()
        c.execute(
            "SELECT * FROM ta_users WHERE washpro_user_id=%s LIMIT 1",
            (wp["user_id"],),
        )
        return c.fetchone()


def resolve_user_from_token():
    """
    Accepts (1) legacy TA signed JWT, or (2) Washpro session token (same Bearer as /auth/login).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None

    # 1) Legacy TA token (itsdangerous) — uid is ta_users.id before migration, Washpro users.id after
    try:
        data = parse_token(token)
        uid = data.get("uid")
        if uid:
            conn = get_db()
            try:
                if not payroll_profiles_active(conn) and not _ta_users_table_exists(conn):
                    return None
                u = fetch_user_row(conn, int(uid))
                if u and as_bool(u.get("active"), default=False):
                    u.pop("password_hash", None)
                    return u
            finally:
                conn.close()
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        pass

    # 2) Washpro app session (hex token from auth_sessions)
    conn = get_db()
    try:
        if not payroll_profiles_active(conn) and not _ta_users_table_exists(conn):
            return None
        wp = _washpro_session_row(conn, token)
        if not wp:
            return None
        if payroll_profiles_active(conn):
            u = ensure_payroll_profile_for_washpro(conn, wp)
        else:
            u = _ensure_ta_user_for_washpro(conn, wp)
        if not u or not as_bool(u.get("active"), default=False):
            return None
        u.pop("password_hash", None)
        return u
    except Exception:
        return None
    finally:
        conn.close()


def write_audit(
    conn,
    actor_id,
    entity_type,
    entity_id,
    action,
    old=None,
    new=None,
    remarks=None,
    organization_id=None,
):
    if organization_id is not None:
        org_id = int(organization_id or 1)
    else:
        org_id = 1
        try:
            org_id = int(g.ta_user.get("organization_id") or 1)
        except Exception:
            pass
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO audit_log (organization_id, actor_user_id, entity_type, entity_id, action, old_value, new_value, remarks)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            org_id,
            actor_id,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            action,
            _audit_json_for_db(old),
            _audit_json_for_db(new),
            remarks,
        ),
    )


def _audit_json_for_db(obj):
    """Serialize audit payload; never raise (NaN / odd types break MySQL JSON insert)."""
    if obj is None:
        return None
    try:
        return json.dumps(obj, default=str, ensure_ascii=False, allow_nan=False)
    except Exception:
        try:
            return json.dumps({"_audit_unserializable": str(type(obj).__name__)}, ensure_ascii=False)
        except Exception:
            return '"<audit omitted>"'


def get_or_create_payroll_cycle(conn, at: datetime, organization_id: int) -> int:
    return get_or_create_payroll_cycle_unified(conn, at, organization_id)


def list_user_clock_geofences(conn, user_id: int):
    """
    Active geofences assigned to this user (tenant-scoped).
    Rows with is_primary=1 sort first; otherwise any assignment counts for clock-in/out.
    """
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT g.*, ug.is_primary
        FROM user_geofences ug
        JOIN geofences g ON g.id = ug.geofence_id
        JOIN users u ON u.id = ug.user_id
        WHERE ug.user_id=%s AND g.active=1 AND g.organization_id = u.organization_id
        ORDER BY ug.is_primary DESC, ug.geofence_id ASC
        """,
        (user_id,),
    )
    return c.fetchall() or []


def effective_clock_geofences(conn, user_id: int, tenant_id: int):
    """
    Geofences used for clock-in/out and inside/outside checks.

    Prefer explicit user_geofences assignments. If none, use the tenant's first active
    geofence (same rule as _tenant_fallback_geofence_id) so orgs like VeeWash work once
    a work area exists in `geofences`, without requiring HR to assign every employee first.
    """
    gfs = list_user_clock_geofences(conn, user_id)
    if gfs:
        return gfs
    fid = _tenant_fallback_geofence_id(conn, int(tenant_id))
    if not fid:
        return []
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT g.*, 1 AS is_primary
        FROM geofences g
        WHERE g.id=%s AND g.organization_id=%s AND g.active=1
        LIMIT 1
        """,
        (int(fid), int(tenant_id)),
    )
    row = c.fetchone()
    return [row] if row else []


def _tenant_fallback_geofence_id(conn, tenant_id: int) -> Optional[int]:
    """First active geofence in org (for shift_sessions.geofence_id when user has no assignment)."""
    c = conn.cursor()
    c.execute(
        """
        SELECT id FROM geofences
        WHERE organization_id=%s AND active=1
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(tenant_id),),
    )
    row = c.fetchone()
    return int(row[0]) if row else None


def user_clock_geofence_exempt(conn, washpro_user_id: int) -> bool:
    """Remote / overseas workers: skip clock-in and clock-out location checks (unified payroll only)."""
    if not payroll_profiles_active(conn):
        return False
    chk = conn.cursor()
    if not table_has_column(chk, "payroll_profiles", "clock_geofence_exempt"):
        return False
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT clock_geofence_exempt FROM payroll_profiles WHERE user_id=%s LIMIT 1",
        (int(washpro_user_id),),
    )
    row = c.fetchone()
    return bool(row and as_bool(row.get("clock_geofence_exempt"), False))


def user_clock_in_gate_exempt(conn, washpro_user_id: int) -> bool:
    """Skip mandatory clock-in gate (dim_app / redirect to /clock) for this user when tenant gate is on."""
    if not payroll_profiles_active(conn):
        return False
    chk = conn.cursor()
    if not table_has_column(chk, "payroll_profiles", "clock_in_gate_exempt"):
        return False
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT clock_in_gate_exempt FROM payroll_profiles WHERE user_id=%s LIMIT 1",
        (int(washpro_user_id),),
    )
    row = c.fetchone()
    return bool(row and as_bool(row.get("clock_in_gate_exempt"), False))


def user_inside_assigned_geofences(
    conn, user_id: int, lat: float, lng: float
) -> tuple[bool, Optional[float], Optional[dict]]:
    """
    True if (lat,lng) lies inside at least one assigned geofence.
    Returns (inside, distance_to_nearest_center, nearest_geofence_row).
    """
    cu = conn.cursor(dictionary=True)
    cu.execute("SELECT organization_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
    ur = cu.fetchone()
    tid = int(ur["organization_id"]) if ur and ur.get("organization_id") is not None else 1
    gfs = effective_clock_geofences(conn, user_id, tid)
    if not gfs:
        return False, None, None
    nearest_d = None
    nearest_row = None
    for gf in gfs:
        dist = haversine_meters(
            float(lat), float(lng), float(gf["latitude"]), float(gf["longitude"])
        )
        if nearest_d is None or dist < nearest_d:
            nearest_d = dist
            nearest_row = gf
        if dist <= float(gf["radius_meters"]):
            return True, dist, gf
    return False, nearest_d, nearest_row


def sum_break_seconds(conn, shift_id: int) -> int:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT break_start_at, break_end_at FROM shift_breaks WHERE shift_session_id=%s
        """,
        (shift_id,),
    )
    total = 0
    for row in c.fetchall():
        start = row["break_start_at"]
        end = row["break_end_at"]
        if start and end:
            total += int((end - start).total_seconds())
    return total


def get_open_break(conn, shift_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM shift_breaks
        WHERE shift_session_id=%s AND break_end_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (shift_id,),
    )
    return c.fetchone()


def _parse_mysql_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if getattr(val, "tzinfo", None) else val
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t.replace(tzinfo=None) if t.tzinfo else t
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:26], fmt)
        except Exception:
            continue
    return None


def _session_gross_seconds(row: dict) -> Optional[int]:
    """Total span clock-in → clock-out (or now if active). Same as shift length before pay adjustments."""
    ci = _parse_mysql_dt(row.get("clock_in_at"))
    co = _parse_mysql_dt(row.get("clock_out_at"))
    if not ci:
        return None
    end = co or eastern_now_naive()
    return int((end - ci).total_seconds())


def _break_duration_seconds(br: dict) -> Optional[int]:
    start = _parse_mysql_dt(br.get("break_start_at"))
    end = _parse_mysql_dt(br.get("break_end_at"))
    if not start or not end:
        return None
    return int((end - start).total_seconds())


def _fetch_breaks_for_sessions(conn, session_ids: list) -> dict:
    if not session_ids:
        return {}
    c = conn.cursor(dictionary=True)
    ph = ",".join(["%s"] * len(session_ids))
    c.execute(
        f"SELECT * FROM shift_breaks WHERE shift_session_id IN ({ph}) ORDER BY break_start_at ASC, id ASC",
        session_ids,
    )
    out = {}
    for r in c.fetchall():
        sid = r["shift_session_id"]
        out.setdefault(sid, []).append(r)
    return out


def _geofence_exception_bounds(conn, sid: int) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT MIN(created_at) AS first_at, MAX(created_at) AS last_at
        FROM shift_exceptions
        WHERE shift_session_id=%s AND exception_type='outside_geofence'
        """,
        (sid,),
    )
    row = c.fetchone() or {}
    return {"first_exception_at": row.get("first_at"), "last_exception_at": row.get("last_at")}


def _effective_bag_rate_cents(conn, on_dt) -> int:
    from datetime import date as date_type

    if on_dt is None:
        d = date_type.today()
    elif isinstance(on_dt, datetime):
        d = on_dt.date()
    elif hasattr(on_dt, "date"):
        d = on_dt.date()
    else:
        d = date_type.today()
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT rate_per_bag_cents FROM bag_rate_maintenance
        WHERE effective_from <= %s AND (effective_to IS NULL OR effective_to >= %s) AND active = 1
        ORDER BY effective_from DESC LIMIT 1
        """,
        (d, d),
    )
    row = c.fetchone()
    if row:
        return int(row.get("rate_per_bag_cents") or 0)
    c.execute(
        "SELECT rate_per_bag_cents FROM bag_rate_maintenance WHERE active = 1 ORDER BY effective_from DESC LIMIT 1"
    )
    row2 = c.fetchone()
    return int(row2.get("rate_per_bag_cents") or 0) if row2 else 0


def _enrich_monitor_rows(conn, rows: list, tenant_id: int) -> list:
    if not rows:
        return []
    chk = conn.cursor()
    has_out_excl = table_has_column(chk, "shift_sessions", "geofence_outside_deduction_excluded")
    has_bag_excl = table_has_column(chk, "shift_sessions", "laundry_bag_deduction_excluded")
    has_remarks = table_has_column(chk, "shift_sessions", "period_adjustment_remarks")
    has_payable = table_has_column(chk, "shift_sessions", "geofence_outside_payable")

    sids = [r["id"] for r in rows]
    breaks_by_sid = _fetch_breaks_for_sessions(conn, sids)
    out = []
    for row in rows:
        sid = row["id"]
        gross = _session_gross_seconds(row)
        row["gross_seconds"] = gross
        brs = breaks_by_sid.get(sid, [])
        enriched_breaks = []
        tb = 0
        for b in brs:
            bd = dict(b)
            dur = _break_duration_seconds(bd)
            bd["duration_seconds"] = dur
            if dur is not None:
                tb += dur
            enriched_breaks.append(json_safe(bd))
        row["breaks"] = enriched_breaks
        row["total_break_seconds_computed"] = tb

        outside_sec = int(row.get("outside_geofence_seconds") or 0)
        if has_out_excl:
            out_excl = bool(int(row.get("geofence_outside_deduction_excluded") or 0))
        elif has_payable:
            out_excl = bool(int(row.get("geofence_outside_payable") or 0))
        else:
            out_excl = False
        outside_deducted_sec = 0 if out_excl else outside_sec

        gross_val = int(gross) if gross is not None else 0
        row["paid_net_seconds"] = int(gross_val - tb - outside_deducted_sec)
        row["outside_seconds_deducted_from_pay"] = outside_deducted_sec

        bags = row.get("personal_laundry_bags")
        try:
            bags = int(bags) if bags is not None else 0
        except (TypeError, ValueError):
            bags = 0
        ci = _parse_mysql_dt(row.get("clock_in_at"))
        rate = _effective_bag_rate_cents(conn, ci or eastern_now_naive())
        row["bag_rate_cents"] = rate
        bag_excl = bool(int(row.get("laundry_bag_deduction_excluded") or 0)) if has_bag_excl else False
        row["laundry_bag_deduction_cents"] = 0 if bag_excl else max(0, bags) * rate

        bounds = _geofence_exception_bounds(conn, sid)
        row["geofence_outside"] = json_safe(
            {
                "total_seconds": outside_sec,
                "deduction_excluded": out_excl,
                "deducted_seconds": outside_deducted_sec,
                "first_exception_at": bounds.get("first_exception_at"),
                "last_exception_at": bounds.get("last_exception_at"),
            }
        )
        row["period_bonus_cents"] = int(row.get("period_bonus_cents") or 0)
        row["period_deduction_cents"] = int(row.get("period_deduction_cents") or 0)
        if has_remarks:
            row["period_adjustment_remarks"] = row.get("period_adjustment_remarks") or ""
        out.append(json_safe(row))
    return out


def maybe_auto_close_shift(conn, sess: dict, user_id: int, organization_id: int):
    max_h = float(get_setting(conn, organization_id, "max_shift_hours", "14"))
    clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
    if not clock_in:
        return None
    now = eastern_now_naive()
    elapsed = (now - clock_in).total_seconds()
    if elapsed <= max_h * 3600:
        return None

    br = sum_break_seconds(conn, sess["id"])
    net = int(elapsed) - br
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, status='auto_closed', total_break_seconds=%s, net_work_seconds=%s
        WHERE id=%s
        """,
        (now, br, net, sess["id"]),
    )
    c.execute(
        """
        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message, severity)
        VALUES (%s,%s,'max_shift_exceeded',%s,'error')
        """,
        (sess["id"], user_id, f"Shift exceeded {max_h} hours; auto clock-out."),
    )
    return fetch_session(conn, sess["id"])


def _today_est_midnight_bounds():
    """Start [start, end) in naive Eastern wall time for the current Eastern calendar day."""
    now = eastern_now_naive()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def count_shift_sessions_starting_today_est(conn, user_id: int) -> int:
    """Clock-ins whose clock_in_at falls on today's Eastern date (any completed status)."""
    start, end = _today_est_midnight_bounds()
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*) FROM shift_sessions
        WHERE user_id=%s AND clock_in_at >= %s AND clock_in_at < %s
        """,
        (user_id, start, end),
    )
    row = c.fetchone()
    return int(row[0]) if row else 0


def maybe_force_clock_out_est_midnight(conn, sess: dict, user_id: int, organization_id: int):
    """
    If an active session's clock-in date (EST) is before today's EST date, force clock-out.
    Suppressed when maintenance disables est_midnight_force_clock_out for the org.
    """
    ui = load_clock_payroll_ui(conn, organization_id)
    clock_cfg = ui.get("clock") or {}
    if not as_bool(clock_cfg.get("est_midnight_force_clock_out"), True):
        return None
    clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
    if not clock_in:
        return None
    now = eastern_now_naive()
    if clock_in.date() == now.date():
        return None

    br = sum_break_seconds(conn, sess["id"])
    elapsed = int((now - clock_in).total_seconds())
    net = max(0, elapsed - br)
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, clock_out_lat=NULL, clock_out_lng=NULL,
            status='auto_closed', total_break_seconds=%s, net_work_seconds=%s
        WHERE id=%s
        """,
        (now, br, net, sess["id"]),
    )
    c.execute(
        """
        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message, severity)
        VALUES (%s,%s,'est_midnight_auto_clock_out',%s,'warning')
        """,
        (
            sess["id"],
            user_id,
            "Still clocked in after Eastern midnight — session closed automatically.",
        ),
    )
    return fetch_session(conn, sess["id"])


def fetch_session(conn, sid: int):
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
    return c.fetchone()


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = resolve_user_from_token()
        if not u:
            return jsonify({"error": "Unauthorized"}), 401
        g.ta_user = u
        return f(*args, **kwargs)

    return wrapper


def require_perm(perm_key: str):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            conn = get_db()
            try:
                if not user_has_perm(conn, g.ta_user["id"], perm_key):
                    return jsonify(
                        {
                            "error": "Forbidden",
                            "missing_permission": perm_key,
                            "detail": (
                                f'Missing permission "{perm_key}". '
                                "An admin can grant it under People - Permissions for your Washpro role, "
                                "or assign a role that includes time clock access."
                            ),
                        }
                    ), 403
            finally:
                conn.close()
            return f(*args, **kwargs)

        return wrapper

    return deco


def require_any_perm(*perm_keys: str):
    """Allow the request if the TA user has any of the listed permissions."""

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            conn = get_db()
            try:
                ok = any(
                    user_has_perm(conn, g.ta_user["id"], k) for k in perm_keys
                )
                if not ok:
                    return jsonify(
                        {
                            "error": "Forbidden",
                            "detail": "You do not have any of the permissions required for this action.",
                        }
                    ), 403
            finally:
                conn.close()
            return f(*args, **kwargs)

        return wrapper

    return deco


# --- Auth ---


@ta_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT pp.*, u.id AS washpro_user_id
                FROM payroll_profiles pp
                JOIN users u ON u.id = pp.user_id
                WHERE LOWER(pp.email)=%s
                LIMIT 1
                """,
                (email,),
            )
            row = c.fetchone()
            if not row or not as_bool(row.get("active"), default=False):
                return jsonify({"error": "Invalid credentials"}), 401
            if not verify_password(row["password_hash"], password):
                return jsonify({"error": "Invalid credentials"}), 401
            uid = int(row["washpro_user_id"])
            u = fetch_payroll_profile_row(conn, uid)
            u.pop("password_hash", None)
            token = create_token(uid)
            conn.commit()
            return jsonify({"token": token, "user": json_safe(u)})
        c.execute(
            """
            SELECT u.*, r.code AS role_code, r.name AS role_name
            FROM ta_users u JOIN roles r ON r.id = u.role_id
            WHERE LOWER(u.email)=%s
            """,
            (email,),
        )
        u = c.fetchone()
        if not u or not u.get("active"):
            return jsonify({"error": "Invalid credentials"}), 401
        if not verify_password(u["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        u.pop("password_hash", None)
        token = create_token(u["id"])
        conn.commit()
        return jsonify({"token": token, "user": json_safe(u)})
    finally:
        conn.close()


@ta_bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT DISTINCT p.perm_key
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE ur.user_id = %s
                ORDER BY p.perm_key
                """,
                (g.ta_user["id"],),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
            extend_permissions_for_platform_operator(conn, int(g.ta_user["id"]), perms)
            extend_permissions_for_tenant_admin(conn, int(g.ta_user["id"]), perms)
        else:
            c.execute(
                """
                SELECT p.perm_key FROM ta_users u
                JOIN role_permissions rp ON rp.role_id = u.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE u.id=%s
                """,
                (g.ta_user["id"],),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
        u = fetch_user_row(conn, g.ta_user["id"])
        u.pop("password_hash", None)
        if payroll_profiles_active(conn):
            u["clock_in_gate_exempt"] = user_clock_in_gate_exempt(conn, int(g.ta_user["id"]))
        else:
            u["clock_in_gate_exempt"] = False
        return jsonify({"user": json_safe(u), "permissions": perms})
    finally:
        conn.close()


@ta_bp.route("/bootstrap", methods=["GET"])
@require_auth
def ta_bootstrap():
    """
    One round-trip for app shell: identity + permissions + clock/payroll UI + optional session state.
    Cuts 3–4 sequential HTTP calls (each paying Azure RTT) down to 1 for clock/home.
    """
    lat = request.args.get("latitude")
    lng = request.args.get("longitude")
    conn = get_db()
    try:
        uid = int(g.ta_user["id"])
        tid = _tenant_id()
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT DISTINCT p.perm_key
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE ur.user_id = %s
                ORDER BY p.perm_key
                """,
                (uid,),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
            extend_permissions_for_platform_operator(conn, uid, perms)
            extend_permissions_for_tenant_admin(conn, uid, perms)
        else:
            c.execute(
                """
                SELECT p.perm_key FROM ta_users u
                JOIN role_permissions rp ON rp.role_id = u.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE u.id=%s
                """,
                (uid,),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
        u = fetch_user_row(conn, uid)
        u.pop("password_hash", None)
        if payroll_profiles_active(conn):
            u["clock_in_gate_exempt"] = user_clock_in_gate_exempt(conn, uid)
        else:
            u["clock_in_gate_exempt"] = False
        ui = load_clock_payroll_ui(conn, tid)
        session_state = None
        if user_has_perm(conn, uid, "ta.clock"):
            session_state = _build_sessions_current_payload(conn, g.ta_user, tid, lat, lng)
        else:
            conn.commit()
        ops_ui = get_ops_ui_flags(c, tid)
        return jsonify(
            {
                "user": json_safe(u),
                "permissions": perms,
                "clock_payroll_ui": ui,
                "session_state": session_state,
                "ops_ui": ops_ui,
            }
        )
    finally:
        conn.close()


# --- Geofence / me ---


@ta_bp.route("/me/geofence", methods=["GET"])
@require_auth
def my_geofence():
    conn = get_db()
    try:
        exempt = user_clock_geofence_exempt(conn, g.ta_user["id"])
        gfs = effective_clock_geofences(conn, g.ta_user["id"], _tenant_id())
        if exempt:
            if gfs:
                body = dict(gfs[0])
                body["clock_geofence_exempt"] = True
                return jsonify(json_safe(body))
            fid = _tenant_fallback_geofence_id(conn, _tenant_id())
            if not fid:
                return jsonify(
                    {"clock_geofence_exempt": True, "note": "no_geofence_configured"}
                )
            c = conn.cursor(dictionary=True)
            c.execute(
                "SELECT * FROM geofences WHERE id=%s AND organization_id=%s LIMIT 1",
                (fid, _tenant_id()),
            )
            row = c.fetchone()
            if not row:
                return jsonify({"clock_geofence_exempt": True, "note": "no_geofence_configured"})
            row["clock_geofence_exempt"] = True
            return jsonify(json_safe(row))
        if not gfs:
            return jsonify({"error": "No geofence assigned"}), 400
        return jsonify(json_safe(gfs[0]))
    finally:
        conn.close()


# --- Clock ---


def maybe_clock_in_geofence_reminder(
    conn,
    ta_user: dict,
    organization_id: int,
    inside: Optional[bool],
) -> None:
    """
    If user has no active session but stays inside geofence longer than configured hours,
    send a throttled push to open the clock screen.
    """
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "user_clock_geofence_presence"):
        return
    uid = int(ta_user.get("id") or 0)
    if not uid:
        return
    if user_clock_geofence_exempt(conn, uid):
        return

    clock_cfg = load_clock_payroll_ui(conn, organization_id).get("clock") or {}
    if not as_bool(clock_cfg.get("geofence_reminder_enabled")):
        return
    try:
        hours_need = float(clock_cfg.get("geofence_reminder_hours") or 1.5)
    except (TypeError, ValueError):
        hours_need = 1.5
    try:
        cooldown_h = float(clock_cfg.get("geofence_reminder_cooldown_hours") or 6.0)
    except (TypeError, ValueError):
        cooldown_h = 6.0

    now = datetime.now()
    uc = conn.cursor()

    if inside is None:
        return
    if inside is False:
        uc.execute(
            "UPDATE user_clock_geofence_presence SET inside_since=NULL WHERE user_id=%s",
            (uid,),
        )
        return

    uc.execute(
        "SELECT inside_since, last_reminder_at FROM user_clock_geofence_presence WHERE user_id=%s LIMIT 1",
        (uid,),
    )
    row = uc.fetchone()
    if not row:
        uc.execute(
            """
            INSERT INTO user_clock_geofence_presence (user_id, organization_id, inside_since, last_reminder_at)
            VALUES (%s,%s,%s,NULL)
            """,
            (uid, int(organization_id), now),
        )
        return

    inside_since = row.get("inside_since")
    last_rem = row.get("last_reminder_at")

    if inside_since is None:
        uc.execute(
            """
            UPDATE user_clock_geofence_presence
            SET inside_since=%s, organization_id=%s
            WHERE user_id=%s
            """,
            (now, int(organization_id), uid),
        )
        return

    if isinstance(inside_since, str):
        inside_since = datetime.fromisoformat(str(inside_since).replace("Z", "+00:00"))
    if inside_since and getattr(inside_since, "tzinfo", None):
        inside_since = inside_since.replace(tzinfo=None)

    elapsed_sec = (now - inside_since).total_seconds()
    if elapsed_sec < hours_need * 3600:
        return

    if last_rem:
        if isinstance(last_rem, str):
            last_rem = datetime.fromisoformat(str(last_rem).replace("Z", "+00:00"))
        if last_rem and getattr(last_rem, "tzinfo", None):
            last_rem = last_rem.replace(tzinfo=None)
        if last_rem and (now - last_rem).total_seconds() < cooldown_h * 3600:
            return

    if not _user_wants_push_notification(conn, ta_user):
        return

    base = (
        (os.getenv("PUBLIC_APP_URL") or os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    )
    click_url = f"{base}/clock" if base else None

    eid = external_user_id(int(organization_id), uid)
    ok, err = send_push_to_external_user_ids(
        [eid],
        "Laundry Ops",
        "You're at work — tap to clock in.",
        data={"type": "clock_in_reminder", "open_path": "/clock"},
        url=click_url,
    )
    if not ok:
        current_app.logger.debug("clock_in reminder push: %s", err)
        return

    uc.execute(
        "UPDATE user_clock_geofence_presence SET last_reminder_at=%s WHERE user_id=%s",
        (now, uid),
    )


def _build_sessions_current_payload(conn, ta_user: dict, tenant_id: int, lat, lng):
    """Shared logic for GET /sessions/current and GET /bootstrap. Commits conn."""
    lat, lng = _coerce_lat_lng(lat, lng)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM shift_sessions
        WHERE user_id=%s AND status='active'
        ORDER BY id DESC LIMIT 1
        """,
        (ta_user["id"],),
    )
    sess = c.fetchone()
    inside = None
    ob = None
    gfs = []
    if sess:
        closed = maybe_auto_close_shift(conn, sess, ta_user["id"], tenant_id)
        if closed:
            conn.commit()
            sess = None
        else:
            closed_md = maybe_force_clock_out_est_midnight(conn, sess, ta_user["id"], tenant_id)
            if closed_md:
                conn.commit()
                sess = None

        if sess:
            sess = fetch_session(conn, sess["id"])
            ob = get_open_break(conn, sess["id"])
            sess["open_break"] = json_safe(ob) if ob else None
            clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
            now_ts = eastern_now_naive()
            br_done = sum_break_seconds(conn, sess["id"])
            break_live = br_done
            if ob:
                bs = _parse_mysql_dt(ob.get("break_start_at"))
                if bs:
                    break_live += int((now_ts - bs).total_seconds())
            elapsed = int((now_ts - clock_in).total_seconds()) if clock_in else 0
            sess["elapsed_shift_seconds"] = elapsed
            sess["elapsed_break_seconds"] = int(break_live)
            sess["elapsed_work_seconds"] = max(0, elapsed - break_live)
            exempt = user_clock_geofence_exempt(conn, ta_user["id"])
            sess["clock_geofence_exempt"] = exempt
            gfs = effective_clock_geofences(conn, ta_user["id"], tenant_id)
            gfn = gfs[0] if gfs else None
            inside = None
            if exempt:
                inside = True
            elif lat is not None and lng is not None and gfs:
                inside, dist, _hit = user_inside_assigned_geofences(
                    conn, ta_user["id"], float(lat), float(lng)
                )
                if inside is False and dist is not None:
                    c.execute(
                        """
                        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message)
                        VALUES (%s,%s,'outside_geofence',%s)
                        """,
                        (
                            sess["id"],
                            ta_user["id"],
                            f"Location ping outside all assigned geofences (~{int(dist)}m to nearest center).",
                        ),
                    )
                    if _user_wants_push_notification(conn, ta_user):
                        notify_geofence_outside_cooldown(
                            ta_user["id"], tenant_id, int(dist)
                        )
            sess["geofence_inside"] = inside
            sess["primary_geofence"] = json_safe(gfn) if gfn else None
            sess["assigned_geofences"] = [json_safe(x) for x in gfs]

            if (
                sess
                and not exempt
                and lat is not None
                and lng is not None
                and gfs
                and inside is not None
                and table_has_column(c, "shift_sessions", "outside_geofence_seconds")
            ):
                poll_now = eastern_now_naive()
                poll_ts = sess.get("last_geofence_poll_at")
                if isinstance(poll_ts, str):
                    poll_ts = datetime.fromisoformat(str(poll_ts).replace("Z", "+00:00"))
                if poll_ts and getattr(poll_ts, "tzinfo", None):
                    poll_ts = poll_ts.replace(tzinfo=None)
                baseline = poll_ts
                if baseline is None and clock_in:
                    baseline = clock_in
                outside_col = int(sess.get("outside_geofence_seconds") or 0)
                if baseline is not None:
                    dt = (poll_now - baseline).total_seconds()
                    dt = min(max(dt, 0.0), 180.0)
                    if inside is False:
                        outside_col += int(dt)
                uc = conn.cursor()
                uc.execute(
                    """
                    UPDATE shift_sessions
                    SET outside_geofence_seconds=%s, last_geofence_poll_at=%s, last_geofence_inside=%s
                    WHERE id=%s
                    """,
                    (outside_col, poll_now, 1 if inside else 0, sess["id"]),
                )
                sess["outside_geofence_seconds"] = outside_col
                sess["last_geofence_poll_at"] = poll_now
                sess["last_geofence_inside"] = 1 if inside else 0

    elif lat is not None and lng is not None:
        _gfs_rem = effective_clock_geofences(conn, ta_user["id"], tenant_id)
        inside = None
        if user_clock_geofence_exempt(conn, ta_user["id"]):
            inside = None
        elif _gfs_rem:
            inside, _, _ = user_inside_assigned_geofences(
                conn, ta_user["id"], float(lat), float(lng)
            )
        maybe_clock_in_geofence_reminder(conn, ta_user, tenant_id, inside)

    n_today = count_shift_sessions_starting_today_est(conn, ta_user["id"])
    ui_ck = load_clock_payroll_ui(conn, tenant_id)
    cc_k = ui_ck.get("clock") or {}
    clock_hints = {
        "first_clock_in_est_today": n_today == 0,
        "ask_personal_laundry_bags": as_bool(cc_k.get("ask_personal_laundry_bags"), False),
        "est_midnight_force_clock_out": as_bool(cc_k.get("est_midnight_force_clock_out"), True),
    }

    op = get_operational_state(
        conn,
        ta_user["id"],
        sess,
        geofence_inside=inside,
        open_break_cached=ob,
        assigned_geofences_cached=gfs if sess else _MISSING_OP_STATE,
    )
    conn.commit()
    return {
        "session": json_safe(sess),
        "operational": op,
        "clock_hints": clock_hints,
    }


@ta_bp.route("/sessions/current", methods=["GET"])
@require_auth
@require_perm("ta.clock")
def sessions_current():
    lat = request.args.get("latitude")
    lng = request.args.get("longitude")
    conn = get_db()
    try:
        payload = _build_sessions_current_payload(conn, g.ta_user, _tenant_id(), lat, lng)
        return jsonify(payload)
    finally:
        conn.close()


_MISSING_OP_STATE = object()


def get_operational_state(
    conn,
    user_id: int,
    sess,
    geofence_inside=None,
    *,
    open_break_cached=_MISSING_OP_STATE,
    assigned_geofences_cached=_MISSING_OP_STATE,
):
    """When caller already loaded open break / geofence list, pass them to skip duplicate queries."""
    clock_gate_exempt = user_clock_in_gate_exempt(conn, user_id)
    geofence_exempt = user_clock_geofence_exempt(conn, user_id)
    # Global TA gate bypass: either exemption should unblock operational gate checks
    # (checkout/clock-driven gating) across the app.
    if clock_gate_exempt or geofence_exempt:
        return {"allowed": True, "reasons": []}

    if not sess:
        return {"allowed": False, "reasons": ["not_clocked_in"]}
    ob = (
        get_open_break(conn, sess["id"])
        if open_break_cached is _MISSING_OP_STATE
        else open_break_cached
    )
    if ob:
        return {"allowed": False, "reasons": ["on_break"]}
    if assigned_geofences_cached is not _MISSING_OP_STATE:
        gfs = assigned_geofences_cached
    else:
        cu = conn.cursor(dictionary=True)
        cu.execute("SELECT organization_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
        ur = cu.fetchone()
        tid_g = int(ur["organization_id"]) if ur and ur.get("organization_id") is not None else 1
        gfs = effective_clock_geofences(conn, user_id, tid_g)
    if not gfs and not geofence_exempt:
        return {"allowed": False, "reasons": ["no_geofence"]}
    if geofence_inside is False and not geofence_exempt:
        return {"allowed": False, "reasons": ["outside_geofence"]}
    return {"allowed": True, "reasons": []}


@ta_bp.route("/sessions/clock-in", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def clock_in():
    data = request.json or {}
    lat_raw = data.get("latitude")
    lng_raw = data.get("longitude")
    employment_category_id = data.get("employment_category_id")

    lat_f = None
    lng_f = None
    if lat_raw is not None and lng_raw is not None:
        try:
            lat_f = float(lat_raw)
            lng_f = float(lng_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid coordinates"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        u = fetch_user_row(conn, g.ta_user["id"])
        if not u["active"]:
            return jsonify({"error": "User inactive"}), 400
        if u.get("termination_date"):
            return jsonify({"error": "Employment terminated"}), 400

        c.execute(
            "SELECT id FROM shift_sessions WHERE user_id=%s AND status='active'",
            (g.ta_user["id"],),
        )
        if c.fetchone():
            return jsonify({"error": "Already clocked in"}), 400

        exempt = user_clock_geofence_exempt(conn, g.ta_user["id"])
        ui_ci = load_clock_payroll_ui(conn, _tenant_id())
        kiosk = as_bool((ui_ci.get("clock") or {}).get("shared_device_attendance"), False)

        if lat_f is None and not exempt and not kiosk:
            return jsonify({"error": "latitude and longitude required"}), 400

        gfs = effective_clock_geofences(conn, g.ta_user["id"], _tenant_id())
        geofence_id_for_session = None
        if exempt or (kiosk and lat_f is None):
            if gfs:
                geofence_id_for_session = int(gfs[0]["id"])
            else:
                fid = _tenant_fallback_geofence_id(conn, _tenant_id())
                if not fid:
                    return jsonify(
                        {
                            "error": "No active geofence for this organization",
                            "detail": "Add at least one active geofence for this tenant (Payroll / attendance geofence setup — latitude, longitude, radius). "
                            "Until then, clock-in cannot create a shift. If this employee is marked geofence-exempt, a tenant geofence record is still required for reporting.",
                        }
                    ), 400
                geofence_id_for_session = fid
        else:
            if lat_f is None or lng_f is None:
                return jsonify({"error": "latitude and longitude required"}), 400
            if not gfs:
                return jsonify({"error": "Assign at least one geofence before clock-in"}), 400
            inside, dist, matched_gf = user_inside_assigned_geofences(
                conn, g.ta_user["id"], lat_f, lng_f
            )
            if not inside:
                ref = gfs[0]
                return jsonify(
                    {
                        "error": "Outside assigned work geofences",
                        "distance_meters": round(float(dist), 1) if dist is not None else None,
                        "radius_meters": float(ref["radius_meters"]),
                    }
                ), 400
            geofence_id_for_session = int(matched_gf["id"]) if matched_gf else int(gfs[0]["id"])

        if clock_in_blocked_by_expired_documents(conn, g.ta_user["id"], _tenant_id()):
            return jsonify(
                {
                    "error": "Document compliance required",
                    "detail": "An HR document is past due. Update it before clock-in (see HR / compliance).",
                }
            ), 403

        if employment_category_id:
            c.execute(
                """
                SELECT 1 FROM employment_categories
                WHERE id=%s AND organization_id=%s
                """,
                (employment_category_id, _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category"}), 400
            c.execute(
                """
                SELECT 1 FROM user_employment_categories
                WHERE user_id=%s AND employment_category_id=%s
                  AND effective_from <= CURDATE()
                  AND (effective_to IS NULL OR effective_to >= CURDATE())
                """,
                (g.ta_user["id"], employment_category_id),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category for user"}), 400
        else:
            c.execute(
                """
                SELECT employment_category_id FROM user_employment_categories
                WHERE user_id=%s AND effective_from <= CURDATE()
                  AND (effective_to IS NULL OR effective_to >= CURDATE())
                ORDER BY effective_from DESC LIMIT 1
                """,
                (g.ta_user["id"],),
            )
            row = c.fetchone()
            employment_category_id = row["employment_category_id"] if row else None

        now = eastern_now_naive()
        pc_id = get_or_create_payroll_cycle(conn, now, _tenant_id())

        chk_ci = conn.cursor()
        has_plb_ci = table_has_column(chk_ci, "shift_sessions", "personal_laundry_bags")
        started_today_ct = count_shift_sessions_starting_today_est(conn, g.ta_user["id"])
        ask_bags_ci = as_bool(ui_ci.get("clock", {}).get("ask_personal_laundry_bags"), False)
        plb_val = None
        if has_plb_ci:
            if started_today_ct == 0 and ask_bags_ci:
                raw_plb = data.get("personal_laundry_bags")
                try:
                    if raw_plb is None or raw_plb == "":
                        plb_val = 0
                    else:
                        plb_val = max(0, int(raw_plb))
                except (TypeError, ValueError):
                    plb_val = 0
            else:
                plb_val = 0

        c2 = conn.cursor()
        if has_plb_ci:
            c2.execute(
                """
                INSERT INTO shift_sessions (
                  user_id, organization_id, payroll_cycle_id, geofence_id, employment_category_id,
                  clock_in_at, clock_in_lat, clock_in_lng, status, personal_laundry_bags
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)
                """,
                (
                    g.ta_user["id"],
                    _tenant_id(),
                    pc_id,
                    geofence_id_for_session,
                    employment_category_id,
                    now,
                    lat_f,
                    lng_f,
                    plb_val,
                ),
            )
        else:
            c2.execute(
                """
                INSERT INTO shift_sessions (
                  user_id, organization_id, payroll_cycle_id, geofence_id, employment_category_id,
                  clock_in_at, clock_in_lat, clock_in_lng, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')
                """,
                (
                    g.ta_user["id"],
                    _tenant_id(),
                    pc_id,
                    geofence_id_for_session,
                    employment_category_id,
                    now,
                    lat_f,
                    lng_f,
                ),
            )
        sid = c2.lastrowid
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "clock_in",
            new={"clock_in_at": now.isoformat(), "geofence_id": geofence_id_for_session},
        )
        conn.commit()
        sess = fetch_session(conn, sid)
        return jsonify(json_safe(sess)), 201
    finally:
        conn.close()


@ta_bp.route("/sessions/clock-out", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def clock_out():
    data = request.json or {}
    lat = data.get("latitude")
    lng = data.get("longitude")
    plb_raw = data.get("personal_laundry_bags")

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400

        if get_open_break(conn, sess["id"]):
            return jsonify({"error": "End break before clocking out"}), 400

        ui = load_clock_payroll_ui(conn, _tenant_id())
        clock_cfg = ui.get("clock") or {}
        require_inside_co = as_bool(
            clock_cfg.get("clock_out_require_inside_geofence"), True
        )
        kiosk_co = as_bool(clock_cfg.get("shared_device_attendance"), False)
        if require_inside_co and not user_clock_geofence_exempt(conn, g.ta_user["id"]) and not kiosk_co:
            if lat is None or lng is None:
                return jsonify(
                    {
                        "error": "latitude and longitude required",
                        "detail": "Location is required to clock out so we can verify you are at work.",
                    }
                ), 400
            gfs_co = effective_clock_geofences(conn, g.ta_user["id"], _tenant_id())
            if not gfs_co:
                return jsonify({"error": "No geofence assigned"}), 400
            try:
                lat_f = float(lat)
                lng_f = float(lng)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid coordinates"}), 400
            inside_co, dist_co, _h = user_inside_assigned_geofences(
                conn, g.ta_user["id"], lat_f, lng_f
            )
            if not inside_co:
                ref = gfs_co[0]
                return jsonify(
                    {
                        "error": "Outside assigned work geofences",
                        "distance_meters": round(float(dist_co), 1)
                        if dist_co is not None
                        else None,
                        "radius_meters": float(ref["radius_meters"]),
                        "detail": "Move inside an assigned work area to clock out, or ask an admin to adjust your geofences.",
                    }
                ), 400

        br = sum_break_seconds(conn, sess["id"])
        now = eastern_now_naive()
        clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
        if not clock_in:
            return jsonify({"error": "Invalid session clock_in"}), 400
        elapsed = (now - clock_in).total_seconds()
        net = int(elapsed) - br

        plb = None
        if plb_raw is not None and table_has_column(c, "shift_sessions", "personal_laundry_bags"):
            try:
                plb = int(plb_raw)
            except (TypeError, ValueError):
                plb = None

        c2 = conn.cursor()
        if plb is not None and table_has_column(c, "shift_sessions", "personal_laundry_bags"):
            c2.execute(
                """
                UPDATE shift_sessions
                SET clock_out_at=%s, clock_out_lat=%s, clock_out_lng=%s,
                    status='completed', total_break_seconds=%s, net_work_seconds=%s,
                    personal_laundry_bags=%s
                WHERE id=%s
                """,
                (
                    now,
                    float(lat) if lat is not None else None,
                    float(lng) if lng is not None else None,
                    br,
                    net,
                    plb,
                    sess["id"],
                ),
            )
        else:
            c2.execute(
                """
                UPDATE shift_sessions
                SET clock_out_at=%s, clock_out_lat=%s, clock_out_lng=%s,
                    status='completed', total_break_seconds=%s, net_work_seconds=%s
                WHERE id=%s
                """,
                (
                    now,
                    float(lat) if lat is not None else None,
                    float(lng) if lng is not None else None,
                    br,
                    net,
                    sess["id"],
                ),
            )
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sess["id"],
            "clock_out",
            old={"session_id": sess["id"]},
            new={"clock_out_at": now.isoformat(), "net_work_seconds": net},
        )
        conn.commit()
        out = fetch_session(conn, sess["id"])
        outside_sec = int(out.get("outside_geofence_seconds") or 0) if out else 0
        return jsonify(
            {
                "session": json_safe(out),
                "summary": {
                    "clock_in_at": json_safe(out["clock_in_at"]),
                    "clock_out_at": json_safe(out["clock_out_at"]),
                    "total_break_seconds": br,
                    "net_work_seconds": net,
                    "outside_geofence_seconds": outside_sec,
                    "personal_laundry_bags": out.get("personal_laundry_bags"),
                },
            }
        )
    finally:
        conn.close()


@ta_bp.route("/sessions/break/start", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def break_start():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400
        if get_open_break(conn, sess["id"]):
            return jsonify({"error": "Break already in progress"}), 400

        now = eastern_now_naive()
        c2 = conn.cursor()
        c2.execute(
            """
            INSERT INTO shift_breaks (shift_session_id, break_start_at)
            VALUES (%s,%s)
            """,
            (sess["id"], now),
        )
        bid = c2.lastrowid
        c.execute("SELECT * FROM shift_breaks WHERE id=%s", (bid,))
        b = c.fetchone()
        conn.commit()
        return jsonify(json_safe(b)), 201
    finally:
        conn.close()


@ta_bp.route("/sessions/break/end", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def break_end():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400
        ob = get_open_break(conn, sess["id"])
        if not ob:
            return jsonify({"error": "No active break"}), 400

        now = eastern_now_naive()
        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE shift_breaks SET break_end_at=%s WHERE id=%s
            """,
            (now, ob["id"]),
        )
        conn.commit()
        c.execute("SELECT * FROM shift_breaks WHERE id=%s", (ob["id"],))
        return jsonify(json_safe(c.fetchone()))
    finally:
        conn.close()


# --- Users ---


@ta_bp.route("/users", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings")
def users_list():
    conn = get_db()
    try:
        if payroll_profiles_active(conn):
            _ensure_people_workspace(conn)
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT pp.user_id FROM payroll_profiles pp
                JOIN users u ON u.id = pp.user_id
                WHERE u.organization_id = %s
                ORDER BY pp.last_name, pp.first_name
                """,
                (_tenant_id(),),
            )
            out = []
            for row in c.fetchall():
                uid = int(row["user_id"])
                r = fetch_payroll_profile_row(conn, uid)
                if not r:
                    continue
                c2 = conn.cursor(dictionary=True)
                c2.execute(
                    """
                    SELECT GROUP_CONCAT(DISTINCT r.code ORDER BY r.code SEPARATOR ',') AS role_codes
                    FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = %s
                    """,
                    (uid,),
                )
                rc = c2.fetchone() or {}
                r["role_codes"] = rc.get("role_codes")
                try:
                    c2.execute(
                        """
                        SELECT uec.employment_category_id, uec.effective_from, uec.effective_to,
                               ec.code AS category_code, ec.name AS category_name
                        FROM user_employment_categories uec
                        JOIN employment_categories ec ON ec.id = uec.employment_category_id
                        WHERE uec.user_id = %s
                        ORDER BY uec.effective_from DESC, uec.employment_category_id DESC
                        """,
                        (uid,),
                    )
                    r["employment_assignments"] = c2.fetchall() or []
                except mysql.connector.Error:
                    r["employment_assignments"] = []
                try:
                    r["hr_form_lanes"] = infer_user_form_lanes(conn, uid)
                except Exception:
                    r["hr_form_lanes"] = ["employee_w2"]
                r.pop("password_hash", None)
                mask_tax_id_for_api_response(r)
                out.append(r)
            return jsonify([json_safe(r) for r in out])
        c.execute(
            """
            SELECT u.*, r.code AS role_code, r.name AS role_name
            FROM ta_users u JOIN roles r ON r.id = u.role_id
            ORDER BY u.last_name, u.first_name
            """
        )
        rows = c.fetchall()
        for r in rows:
            r.pop("password_hash", None)
        return jsonify([json_safe(r) for r in rows])
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def users_get(user_id):
    conn = get_db()
    try:
        if payroll_profiles_active(conn):
            _ensure_people_workspace(conn)
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            u = fetch_payroll_profile_row(conn, user_id)
            if not u and _ta_user_can_access_payroll_subject(conn, user_id):
                u = ensure_payroll_profile_for_user_id(conn, user_id)
            if not u:
                return jsonify({"error": "Not found"}), 404
            if int(u.get("organization_id") or 1) != _tenant_id():
                return jsonify({"error": "Not found"}), 404
            u.pop("password_hash", None)
            u.pop("attendance_pin_hash", None)
            mask_tax_id_for_api_response(u)
            pid = u.get("rehire_parent_user_id")
            if pid:
                c.execute(
                    """
                    SELECT user_id AS id, employee_id, first_name, last_name, email, active, termination_date
                    FROM payroll_profiles WHERE user_id=%s
                    """,
                    (pid,),
                )
                u["rehire_parent"] = c.fetchone()
                u["rehire_parent_id"] = pid
            else:
                u["rehire_parent"] = None
                u["rehire_parent_id"] = None
            try:
                c.execute(
                    """
                    SELECT user_id AS id, employee_id, first_name, last_name, email, active, hire_date
                    FROM payroll_profiles WHERE rehire_parent_user_id=%s ORDER BY user_id
                    """,
                    (user_id,),
                )
                u["rehire_successors"] = c.fetchall()
            except mysql.connector.Error:
                u["rehire_successors"] = []
        else:
            c.execute(
                """
                SELECT u.*, r.code AS role_code, r.name AS role_name
                FROM ta_users u JOIN roles r ON r.id = u.role_id
                WHERE u.id=%s
                """,
                (user_id,),
            )
            u = c.fetchone()
            if not u:
                return jsonify({"error": "Not found"}), 404
            u.pop("password_hash", None)
            if u.get("rehire_parent_id"):
                c.execute(
                    """
                    SELECT id, employee_id, first_name, last_name, email, active, termination_date
                    FROM ta_users WHERE id=%s
                    """,
                    (u["rehire_parent_id"],),
                )
                u["rehire_parent"] = c.fetchone()
            else:
                u["rehire_parent"] = None
            try:
                c.execute(
                    """
                    SELECT id, employee_id, first_name, last_name, email, active, hire_date
                    FROM ta_users WHERE rehire_parent_id=%s ORDER BY id
                    """,
                    (user_id,),
                )
                u["rehire_successors"] = c.fetchall()
            except mysql.connector.Error:
                u["rehire_successors"] = []
        c.execute(
            "SELECT geofence_id, is_primary FROM user_geofences WHERE user_id=%s",
            (user_id,),
        )
        gfs = c.fetchall()
        u["geofence_ids"] = [g["geofence_id"] for g in gfs]
        primary = next((g["geofence_id"] for g in gfs if g["is_primary"]), None)
        u["primary_geofence_id"] = primary
        c.execute(
            """
            SELECT employment_category_id, effective_from, effective_to
            FROM user_employment_categories WHERE user_id=%s
            """,
            (user_id,),
        )
        u["employment_assignments"] = c.fetchall()
        if table_exists(c, "user_entity_tags"):
            c.execute(
                """
                SELECT entity_type, entity_key, label
                FROM user_entity_tags
                WHERE user_id=%s
                ORDER BY entity_type, entity_key
                """,
                (user_id,),
            )
            u["entity_tags"] = c.fetchall()
        else:
            u["entity_tags"] = []
        try:
            u["hr_form_lanes"] = infer_user_form_lanes(conn, user_id)
        except Exception:
            u["hr_form_lanes"] = ["employee_w2"]
        return jsonify(json_safe(u))
    finally:
        conn.close()


@ta_bp.route("/users", methods=["POST"])
@require_auth
@require_perm("users.add")
def users_create():
    data = request.json or {}
    conn = get_db()
    try:
        if payroll_profiles_active(conn):
            required = ["washpro_user_id", "first_name", "last_name", "email", "password"]
            for k in required:
                if not data.get(k):
                    return jsonify({"error": f"Missing {k}"}), 400
            wid = int(data["washpro_user_id"])
            ph = hash_password(data["password"])
            c = conn.cursor(dictionary=True)
            c.execute("SELECT id, organization_id FROM users WHERE id=%s", (wid,))
            uw = c.fetchone()
            if not uw:
                return jsonify({"error": "Washpro user not found"}), 404
            if int(uw.get("organization_id") or 1) != _tenant_id():
                return jsonify({"error": "Washpro user is not in your organization"}), 400
            c.execute("SELECT 1 FROM payroll_profiles WHERE user_id=%s", (wid,))
            if c.fetchone():
                return jsonify({"error": "Payroll profile already exists for this user"}), 400
            rp = data.get("rehireParentUserId") or data.get("rehire_parent_user_id")
            if rp in (None, ""):
                rp = None
            else:
                rp = int(rp)
                c.execute(
                    """
                    SELECT pp.user_id FROM payroll_profiles pp
                    JOIN users u ON u.id = pp.user_id
                    WHERE pp.user_id=%s AND u.organization_id=%s
                    """,
                    (rp, _tenant_id()),
                )
                if not c.fetchone():
                    return jsonify({"error": "rehire_parent not found"}), 400
            c2 = conn.cursor()
            c2.execute(
                """
                INSERT INTO payroll_profiles (
                  user_id, employee_id, first_name, last_name, address, email, mobile, itin_ssn,
                  hire_date, termination_date, rehired, active, rehire_parent_user_id, prior_employee_id, password_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    wid,
                    data.get("employee_id"),
                    data["first_name"],
                    data["last_name"],
                    data.get("address"),
                    data["email"].strip().lower(),
                    data.get("mobile"),
                    data.get("itin_ssn"),
                    data.get("hire_date"),
                    data.get("termination_date"),
                    1 if data.get("rehired") else 0,
                    1 if data.get("active", True) else 0,
                    rp,
                    data.get("prior_employee_id"),
                    ph,
                ),
            )
            from backend.hr_workspace_schema import WORKSPACE_PAYROLL_EXTRA_KEYS

            chk = conn.cursor()
            extra_fields = []
            extra_vals = []
            for key in WORKSPACE_PAYROLL_EXTRA_KEYS:
                if key not in data:
                    continue
                if not table_has_column(chk, "payroll_profiles", key):
                    continue
                v = data[key]
                if key == "laundry_experience":
                    if v is None:
                        continue
                    v = 1 if v else 0
                elif key in ("clock_geofence_exempt", "clock_in_gate_exempt"):
                    v = 1 if as_bool(v) else 0
                extra_fields.append(f"{key}=%s")
                extra_vals.append(v)
            if extra_fields:
                c2.execute(
                    f"UPDATE payroll_profiles SET {', '.join(extra_fields)} WHERE user_id=%s",
                    (*extra_vals, wid),
                )
            if data.get("role_id"):
                c2.execute("DELETE FROM user_roles WHERE user_id=%s", (wid,))
                c2.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                    (wid, int(data["role_id"])),
                )
            write_audit(conn, g.ta_user["id"], "user", wid, "create", new={"email": data["email"]})
            conn.commit()
            return jsonify({"id": wid}), 201

        required = ["first_name", "last_name", "email", "role_id", "password"]
        for k in required:
            if not data.get(k):
                return jsonify({"error": f"Missing {k}"}), 400

        ph = hash_password(data["password"])
        c = conn.cursor(dictionary=True)
        rp = data.get("rehire_parent_id")
        if rp is not None and str(rp).strip() != "":
            rp = int(rp)
        else:
            rp = None
        if rp is not None:
            c.execute("SELECT id FROM ta_users WHERE id=%s", (rp,))
            if not c.fetchone():
                return jsonify({"error": "rehire_parent_id not found"}), 400
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO ta_users (
              employee_id, first_name, last_name, address, email, mobile, itin_ssn,
              hire_date, termination_date, rehired, active, role_id,
              rehire_parent_id, prior_employee_id, password_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("employee_id"),
                data["first_name"],
                data["last_name"],
                data.get("address"),
                data["email"].strip().lower(),
                data.get("mobile"),
                data.get("itin_ssn"),
                data.get("hire_date"),
                data.get("termination_date"),
                1 if data.get("rehired") else 0,
                1 if data.get("active", True) else 0,
                int(data["role_id"]),
                rp,
                data.get("prior_employee_id"),
                ph,
            ),
        )
        uid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "user", uid, "create", new={"email": data["email"]})
        conn.commit()
        return jsonify({"id": uid}), 201
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def users_update(user_id):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute("SELECT * FROM payroll_profiles WHERE user_id=%s", (user_id,))
            old = c.fetchone()
            if not old:
                if not _user_belongs_to_tenant(conn, user_id):
                    return jsonify({"error": "Not found"}), 404
                if not ensure_payroll_profile_for_user_id(conn, user_id):
                    return jsonify({"error": "Not found"}), 404
                c.execute("SELECT * FROM payroll_profiles WHERE user_id=%s", (user_id,))
                old = c.fetchone()
            if not old:
                return jsonify({"error": "Not found"}), 404
            if not _user_belongs_to_tenant(conn, user_id):
                return jsonify({"error": "Not found"}), 404

            fields = []
            vals = []
            mapping = [
                ("employee_id", "employee_id"),
                ("first_name", "first_name"),
                ("last_name", "last_name"),
                ("address", "address"),
                ("email", "email"),
                ("mobile", "mobile"),
                ("itin_ssn", "itin_ssn"),
                ("hire_date", "hire_date"),
                ("termination_date", "termination_date"),
                ("rehired", "rehired"),
                ("active", "active"),
                ("prior_employee_id", "prior_employee_id"),
            ]
            chk = conn.cursor()
            from backend.hr_workspace_schema import WORKSPACE_PAYROLL_EXTRA_KEYS

            for key in WORKSPACE_PAYROLL_EXTRA_KEYS:
                if key not in data:
                    continue
                if not table_has_column(chk, "payroll_profiles", key):
                    continue
                v = data[key]
                if key == "laundry_experience":
                    if v is None:
                        continue
                    v = 1 if v else 0
                elif key in ("clock_geofence_exempt", "clock_in_gate_exempt"):
                    v = 1 if as_bool(v) else 0
                fields.append(f"{key}=%s")
                vals.append(v)
            for json_k, col in mapping:
                if json_k in data:
                    if col == "itin_ssn":
                        v = data.get(json_k)
                        if v in (None, ""):
                            continue
                        v = re.sub(r"\D", "", str(v))[:9]
                        if len(v) != 9:
                            return jsonify({"error": "SSN/ITIN must be 9 digits"}), 400
                    else:
                        v = data[json_k]
                    if col in ("rehired", "active"):
                        v = 1 if v else 0
                    fields.append(f"{col}=%s")
                    vals.append(v)
            if "rehire_parent_id" in data:
                v = data["rehire_parent_id"]
                if v in (None, ""):
                    v = None
                else:
                    v = int(v)
                if v is not None and v == user_id:
                    return jsonify({"error": "rehire parent cannot be the same user"}), 400
                if v is not None:
                    c.execute(
                        """
                        SELECT pp.user_id FROM payroll_profiles pp
                        JOIN users u ON u.id = pp.user_id
                        WHERE pp.user_id=%s AND u.organization_id=%s
                        """,
                        (v, _tenant_id()),
                    )
                    if not c.fetchone():
                        return jsonify({"error": "rehire_parent not found"}), 400
                fields.append("rehire_parent_user_id=%s")
                vals.append(v)
            if data.get("password"):
                fields.append("password_hash=%s")
                vals.append(hash_password(data["password"]))

            if "attendance_pin" in data and table_has_column(chk, "payroll_profiles", "attendance_pin_hash"):
                ap_raw = data.get("attendance_pin")
                if ap_raw in (None, ""):
                    fields.append("attendance_pin_hash=%s")
                    vals.append(None)
                else:
                    ps = str(ap_raw).strip()
                    if not ps.isdigit() or len(ps) < 4 or len(ps) > 10:
                        return jsonify({"error": "Attendance PIN must be 4–10 digits"}), 400
                    c_chk = conn.cursor(dictionary=True)
                    c_chk.execute(
                        """
                        SELECT pp.user_id, pp.attendance_pin_hash
                        FROM payroll_profiles pp
                        JOIN users u ON u.id = pp.user_id
                        WHERE u.organization_id = %s AND pp.user_id != %s AND pp.attendance_pin_hash IS NOT NULL
                        """,
                        (_tenant_id(), user_id),
                    )
                    for ow in c_chk.fetchall() or []:
                        h = ow.get("attendance_pin_hash")
                        if h and verify_password(str(h), ps):
                            return jsonify(
                                {"error": "That PIN is already assigned to another employee in this organization"}
                            ), 400
                    fields.append("attendance_pin_hash=%s")
                    vals.append(hash_password(ps))

            if fields:
                vals.append(user_id)
                c2 = conn.cursor()
                c2.execute(f"UPDATE payroll_profiles SET {', '.join(fields)} WHERE user_id=%s", vals)
            if "role_id" in data and data["role_id"] is not None:
                c.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
                c.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                    (user_id, int(data["role_id"])),
                )
            write_audit(conn, g.ta_user["id"], "user", user_id, "update", old={"id": old["user_id"]}, new=data)
            conn.commit()
            return jsonify({"ok": True})

        c.execute("SELECT * FROM ta_users WHERE id=%s", (user_id,))
        old = c.fetchone()
        if not old:
            return jsonify({"error": "Not found"}), 404

        fields = []
        vals = []
        mapping = [
            ("employee_id", "employee_id"),
            ("first_name", "first_name"),
            ("last_name", "last_name"),
            ("address", "address"),
            ("email", "email"),
            ("mobile", "mobile"),
            ("itin_ssn", "itin_ssn"),
            ("hire_date", "hire_date"),
            ("termination_date", "termination_date"),
            ("rehired", "rehired"),
            ("active", "active"),
            ("role_id", "role_id"),
            ("prior_employee_id", "prior_employee_id"),
        ]
        for json_k, col in mapping:
            if json_k in data:
                v = data[json_k]
                if col in ("rehired", "active"):
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if "rehire_parent_id" in data:
            v = data["rehire_parent_id"]
            if v in (None, ""):
                v = None
            else:
                v = int(v)
            if v is not None and v == user_id:
                return jsonify({"error": "rehire_parent_id cannot be the same user"}), 400
            if v is not None:
                c.execute("SELECT id FROM ta_users WHERE id=%s", (v,))
                if not c.fetchone():
                    return jsonify({"error": "rehire_parent_id not found"}), 400
            fields.append("rehire_parent_id=%s")
            vals.append(v)
        if data.get("password"):
            fields.append("password_hash=%s")
            vals.append(hash_password(data["password"]))

        if fields:
            vals.append(user_id)
            c2 = conn.cursor()
            c2.execute(f"UPDATE ta_users SET {', '.join(fields)} WHERE id=%s", vals)
        write_audit(conn, g.ta_user["id"], "user", user_id, "update", old={"id": old["id"]}, new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>", methods=["DELETE"])
@require_auth
@require_perm("users.edit")
def users_delete_payroll_profile(user_id):
    """Unified payroll: delete payroll_profiles row for this Washpro user id (login remains). Legacy: delete ta_users row."""
    conn = get_db()
    try:
        if payroll_profiles_active(conn):
            if not _user_belongs_to_tenant(conn, user_id):
                return jsonify({"error": "Not found"}), 404
            c = conn.cursor(dictionary=True)
            c.execute("SELECT user_id FROM payroll_profiles WHERE user_id=%s", (user_id,))
            if not c.fetchone():
                return jsonify({"error": "No payroll profile for this user"}), 404
            c2 = conn.cursor()
            c2.execute("DELETE FROM payroll_profiles WHERE user_id=%s", (user_id,))
            write_audit(
                conn,
                g.ta_user["id"],
                "user",
                user_id,
                "payroll_profile_delete",
                old={"user_id": user_id},
            )
            conn.commit()
            return jsonify({"ok": True})

        c = conn.cursor(dictionary=True)
        c.execute("SELECT id FROM ta_users WHERE id=%s", (user_id,))
        if not c.fetchone():
            return jsonify({"error": "Not found"}), 404
        c2 = conn.cursor()
        c2.execute("DELETE FROM ta_users WHERE id=%s", (user_id,))
        write_audit(conn, g.ta_user["id"], "user", user_id, "delete", old={"id": user_id})
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/geofences", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def user_geofences(user_id):
    data = request.json or {}
    ids = data.get("geofence_ids") or []
    primary_id = data.get("primary_geofence_id")

    conn = get_db()
    try:
        if payroll_profiles_active(conn) and not _user_belongs_to_tenant(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        c = conn.cursor()
        for gid in ids:
            c.execute(
                "SELECT 1 FROM geofences WHERE id=%s AND organization_id=%s",
                (int(gid), _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid geofence"}), 400
        c.execute("DELETE FROM user_geofences WHERE user_id=%s", (user_id,))
        for gid in ids:
            gid_int = int(gid)
            is_p = (
                1
                if primary_id is not None and gid_int == int(primary_id)
                else 0
            )
            c.execute(
                "INSERT INTO user_geofences (user_id, geofence_id, is_primary) VALUES (%s,%s,%s)",
                (user_id, gid_int, is_p),
            )
        write_audit(
            conn,
            g.ta_user["id"],
            "user_geofences",
            user_id,
            "replace",
            new={"geofence_ids": ids, "primary": primary_id},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/employment-categories", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def user_employment_cats(user_id):
    data = request.json or {}
    rows = data.get("assignments") or []
    conn = get_db()
    try:
        if payroll_profiles_active(conn) and not _user_belongs_to_tenant(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        c = conn.cursor()
        for r in rows:
            cid = int(r["employment_category_id"])
            c.execute(
                "SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s",
                (cid, _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category"}), 400
        c.execute("DELETE FROM user_employment_categories WHERE user_id=%s", (user_id,))
        for r in rows:
            c.execute(
                """
                INSERT INTO user_employment_categories (user_id, employment_category_id, effective_from, effective_to)
                VALUES (%s,%s,%s,%s)
                """,
                (
                    user_id,
                    int(r["employment_category_id"]),
                    r["effective_from"],
                    r.get("effective_to"),
                ),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/entity-tags", methods=["GET", "PUT"])
@require_auth
def user_entity_tags_api(user_id):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if not table_exists(c, "user_entity_tags"):
            if request.method == "GET":
                return jsonify({"tags": []})
            return jsonify({"ok": True})
        if not table_has_column(c, "users", "organization_id") or not _user_belongs_to_tenant(
            conn, user_id
        ):
            return jsonify({"error": "Not found"}), 404
        if request.method == "GET":
            if not user_has_perm(conn, g.ta_user["id"], "users.view"):
                return jsonify({"error": "Forbidden"}), 403
            c.execute(
                """
                SELECT entity_type, entity_key, label
                FROM user_entity_tags
                WHERE user_id=%s
                ORDER BY entity_type, entity_key
                """,
                (user_id,),
            )
            return jsonify({"tags": c.fetchall() or []})
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        tags = data.get("tags")
        if not isinstance(tags, list):
            return jsonify({"error": "tags array required"}), 400
        c2 = conn.cursor(dictionary=True)
        c2.execute(
            "SELECT organization_id FROM users WHERE id=%s LIMIT 1",
            (int(user_id),),
        )
        urow = c2.fetchone()
        if not urow:
            return jsonify({"error": "Not found"}), 404
        oid = int(urow.get("organization_id") or 1)
        c.execute("DELETE FROM user_entity_tags WHERE user_id=%s", (user_id,))
        for t in tags:
            if not isinstance(t, dict):
                continue
            et = str(t.get("entity_type") or "").strip()[:64]
            ek = str(t.get("entity_key") or "").strip()[:128]
            if not et or not ek:
                return jsonify({"error": "Each tag needs entity_type and entity_key"}), 400
            lab = str(t.get("label") or "").strip()[:255] or None
            c.execute(
                """
                INSERT INTO user_entity_tags (organization_id, user_id, entity_type, entity_key, label)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (oid, int(user_id), et, ek, lab),
            )
        write_audit(conn, g.ta_user["id"], "user_entity_tags", user_id, "replace", new={"tags": tags})
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- HR compliance (extended profile + I-9 prefill) ---


@ta_bp.route("/org/hr-employer-settings", methods=["GET", "PUT"])
@require_auth
def org_hr_employer_settings():
    conn = get_db()
    try:
        oid = _tenant_id()
        if request.method == "GET":
            if not user_has_perm(conn, g.ta_user["id"], "users.view"):
                return jsonify({"error": "Forbidden"}), 403
            return jsonify(fetch_hr_org_settings(conn, oid))
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        for src, sk in (
            ("employer_name", "hr_employer_legal_name"),
            ("employer_address", "hr_employer_address"),
            ("employer_ein", "hr_employer_ein"),
        ):
            if src in data:
                set_setting(conn, oid, sk, (data.get(src) or "").strip())
        write_audit(
            conn,
            g.ta_user["id"],
            "system_settings",
            oid,
            "hr_employer",
            new={k: data.get(k) for k in ("employer_name", "employer_address", "employer_ein") if k in data},
        )
        conn.commit()
        return jsonify(fetch_hr_org_settings(conn, oid))
    finally:
        conn.close()


@ta_bp.route("/org/tax-form-year-settings", methods=["GET", "PUT"])
@require_auth
def org_tax_form_year_settings():
    """W-4 Step 3 credit amounts by tax year (maintainable per tenant)."""
    from decimal import Decimal

    from backend.tax_form_year_settings import (
        ensure_tax_form_year_settings_table,
        fetch_w4_year_settings,
        upsert_w4_year_settings,
    )

    conn = get_db()
    try:
        oid = _tenant_id()
        cur = conn.cursor()
        ensure_tax_form_year_settings_table(cur)
        if request.method == "GET":
            if not (
                user_has_perm(conn, g.ta_user["id"], "users.view")
                or user_has_perm(conn, g.ta_user["id"], "users.edit")
            ):
                return jsonify({"error": "Forbidden"}), 403
            try:
                tax_year = int(request.args.get("tax_year") or date.today().year)
            except (TypeError, ValueError):
                tax_year = date.today().year
            row = fetch_w4_year_settings(conn, oid, tax_year)
            safe = {}
            for k, v in row.items():
                if isinstance(v, Decimal):
                    safe[k] = float(v)
                elif hasattr(v, "isoformat"):
                    safe[k] = v.isoformat()
                else:
                    safe[k] = v
            return jsonify({"settings": safe, "tax_year": tax_year})
        if not user_has_perm(conn, g.ta_user["id"], "ta.settings"):
            return jsonify({"error": "Forbidden"}), 403
        data = request.get_json(silent=True) or {}
        row = upsert_w4_year_settings(conn, oid, data)
        conn.commit()
        safe = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                safe[k] = float(v)
            elif hasattr(v, "isoformat"):
                safe[k] = v.isoformat()
            else:
                safe[k] = v
        return jsonify({"settings": safe})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/hr-profile", methods=["GET", "PUT"])
@require_auth
def user_hr_profile(user_id):
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify(
                {"error": "HR profile requires unified payroll (payroll_profiles). Run payroll_unify_to_users_v1.sql"}
            ), 503
        u = fetch_payroll_profile_row(conn, user_id)
        if not u and _ta_user_can_access_payroll_subject(conn, user_id):
            u = ensure_payroll_profile_for_user_id(conn, user_id)
        if not u:
            return jsonify(
                {
                    "error": "No payroll profile for this user. Add or migrate the employee in People first.",
                }
            ), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        cur = conn.cursor()
        ensure_hr_extended_profiles_table(cur)
        if request.method == "GET":
            # Editors need HR JSON (work_json.w4, i9, etc.) even when they lack users.view.
            if not (
                user_has_perm(conn, g.ta_user["id"], "users.view")
                or user_has_perm(conn, g.ta_user["id"], "users.edit")
            ):
                return jsonify({"error": "Forbidden"}), 403
            return jsonify(get_merged_hr_profile(conn, user_id, u))
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        try:
            body = request.get_json(force=True)
            if body is None:
                body = {}
        except Exception:
            return jsonify({"error": "Invalid JSON body"}), 400
        if not isinstance(body, dict):
            return jsonify({"error": "JSON body must be an object"}), 400
        if "date_of_birth" in body and body.get("date_of_birth") not in (None, ""):
            dob_s = str(body.get("date_of_birth")).strip()[:10]
            if len(dob_s) == 10 and dob_s >= date.today().isoformat():
                return jsonify({"error": "date_of_birth must be before today"}), 400
        oid = int(u.get("organization_id") or _tenant_id())
        from backend.w4_step3_compute import patch_work_json_w4_compliance

        if isinstance(body.get("work_json"), dict):
            body = dict(body)
            body["work_json"] = patch_work_json_w4_compliance(
                conn, oid, body["work_json"], int(g.ta_user["id"])
            )
        hr_out = upsert_hr_extended_profile(conn, user_id, oid, body)
        try:
            write_audit(
                conn,
                g.ta_user["id"],
                "hr_extended_profiles",
                user_id,
                "update",
                new=body,
            )
        except Exception:
            current_app.logger.exception("audit log failed for hr_extended_profiles update")
        conn.commit()
        u2 = fetch_payroll_profile_row(conn, user_id)
        merged = get_merged_hr_profile(conn, user_id, u2 or u)
        merged["hr"] = hr_out
        return jsonify(merged)
    finally:
        conn.close()


def _hr_form_safe_id(raw: str) -> Optional[str]:
    s = (raw or "").strip().lower()
    if re.match(r"^[a-z][a-z0-9_]{0,63}$", s):
        return s
    return None


@ta_bp.route("/users/<int:user_id>/hr-forms/inventory", methods=["GET"])
@require_auth
def user_hr_forms_inventory(user_id):
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "HR forms require unified payroll"}), 503
        if not (
            user_has_perm(conn, g.ta_user["id"], "users.view")
            or user_has_perm(conn, g.ta_user["id"], "users.edit")
        ):
            return jsonify({"error": "Forbidden"}), 403
        u = fetch_payroll_profile_row(conn, user_id)
        if not u:
            return jsonify({"error": "No payroll profile for this user"}), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify(build_hr_forms_inventory(conn, user_id))
    finally:
        conn.close()


@ta_bp.route("/hr-forms/org-summary", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def hr_forms_org_summary():
    """One row per payroll profile: lanes + form count (Documents & Evidence center)."""
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify([])
        _ensure_people_workspace(conn)
        c = conn.cursor()
        c.execute(
            """
            SELECT pp.user_id FROM payroll_profiles pp
            JOIN users u ON u.id = pp.user_id
            WHERE u.organization_id=%s
            ORDER BY pp.last_name, pp.first_name
            """,
            (_tenant_id(),),
        )
        out = []
        for row in c.fetchall():
            uid = int(row[0])
            if not _ta_user_can_access_payroll_subject(conn, uid):
                continue
            inv = build_hr_forms_inventory(conn, uid)
            prow = fetch_payroll_profile_row(conn, uid)
            nm = f"{(prow or {}).get('first_name') or ''} {(prow or {}).get('last_name') or ''}".strip()
            out.append(
                {
                    "user_id": uid,
                    "employee_id": (prow or {}).get("employee_id"),
                    "name": nm,
                    "email": (prow or {}).get("email"),
                    "lanes_detected": inv.get("lanes_detected") or [],
                    "forms_count": len(inv.get("forms") or []),
                }
            )
        return jsonify(out)
    finally:
        conn.close()


@ta_bp.route("/documents/org-records", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def documents_org_records():
    """
    Flat list of employee_document_records for the tenant (Documents & Evidence center).
    """
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"items": [], "reminder_days_before": 14})
        ensure_document_compliance_tables(conn.cursor())
        oid = _tenant_id()
        pol = get_document_compliance_policy(conn, oid)
        raw = list_organization_document_records(conn, oid)
        out = []
        for r in raw:
            uid = int(r.get("user_id") or 0)
            if uid and not _ta_user_can_access_payroll_subject(conn, uid):
                continue
            out.append(r)
        return jsonify(
            {
                "items": json_safe(out),
                "reminder_days_before": int(pol.get("reminder_days_before") or 14),
            }
        )
    finally:
        conn.close()


@ta_bp.route("/documents/org-records/export-zip", methods=["POST"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def documents_org_records_export_zip():
    """Download a ZIP of http(s) files linked from selected document records (file_uri + evidence_uri)."""
    body = request.get_json(silent=True) or {}
    ids = body.get("record_ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "record_ids (non-empty list) is required"}), 400
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "HR documents require unified payroll"}), 503
        ensure_document_compliance_tables(conn.cursor())
        oid = _tenant_id()
        rows = fetch_organization_document_records_by_ids(conn, oid, ids)
        allowed: list[dict] = []
        for r in rows:
            uid = int(r.get("user_id") or 0)
            if uid and _ta_user_can_access_payroll_subject(conn, uid):
                allowed.append(r)
        if not allowed:
            return jsonify({"error": "No matching records for export"}), 404
        blob = build_document_records_export_zip(allowed)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
        return send_file(
            BytesIO(blob),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"document-evidence-{oid}-{stamp}.zip",
        )
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/hr-forms/<form_id>", methods=["POST"])
@require_auth
def user_hr_form_deliver(user_id, form_id):
    """Download one form: AcroForm prefill for I-9, W-4, W-9 (en/es); else serve official/internal file as-is."""
    fid = _hr_form_safe_id(form_id)
    if not fid:
        return jsonify({"error": "Invalid form"}), 400
    body = request.get_json(silent=True) or {}
    locale = str(body.get("locale") or request.args.get("locale") or "en").lower()
    if locale not in ("en", "es", "bilingual"):
        return jsonify({"error": "Invalid locale"}), 400

    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "HR forms require unified payroll"}), 503
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        u = fetch_payroll_profile_row(conn, user_id)
        if not u:
            return jsonify(
                {"error": "No payroll profile for this user. Add or migrate the employee in People first."}
            ), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404

        fdef = get_form_def(fid)
        if not fdef:
            return jsonify({"error": "Unknown form"}), 404
        allowed_lanes = infer_user_form_lanes(conn, user_id)
        lane = fdef.get("lane")
        if lane and lane not in allowed_lanes:
            return jsonify({"error": "This form is not part of this worker's assigned packet."}), 404

        oid_hub = int(u.get("organization_id") or _tenant_id())

        def _record_hub_download(download_name: str) -> None:
            try:
                upsert_generated_hr_form_record(
                    conn,
                    oid_hub,
                    int(user_id),
                    int(g.ta_user["id"]),
                    document_code=fid,
                    document_name=str(fdef.get("title") or fid),
                    form_locale=locale,
                    download_filename=download_name,
                )
            except Exception:
                current_app.logger.exception("upsert generated document record failed")

        if fdef.get("fill_strategy") in ("docx_template", "reference_pdf"):
            from backend.hr_internal_reference_pdf import internal_form_reference_pdf_bytes

            org_hub = fetch_hr_org_settings(conn, oid_hub)
            pdf = internal_form_reference_pdf_bytes(
                str(fdef.get("title") or fid),
                form_id=fid,
                locale=locale,
                worker=u,
                org_name=str(org_hub.get("employer_name") or ""),
                org_address=str(org_hub.get("employer_address") or ""),
            )
            fn = f"{fid}_{locale}_reference.pdf"
            _record_hub_download(fn)
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{fn}"'},
            )

        path = resolve_form_asset_path(fid, locale)
        if not path:
            return jsonify({"error": f"Template not found for {fid} ({locale}). See backend/hr_forms/catalog.json."}), 503

        ext = os.path.splitext(path)[1].lower() or ".pdf"
        dl = f"{fid}_{locale}{ext}"

        if fid == "uscis_i9" and locale in ("en", "es"):
            cur = conn.cursor()
            ensure_hr_extended_profiles_table(cur)
            c = conn.cursor(dictionary=True)
            c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (user_id,))
            hr = c.fetchone()
            oid = int(u.get("organization_id") or _tenant_id())
            org = fetch_hr_org_settings(conn, oid)
            if locale == "en":
                vals = build_i9_field_values(
                    u,
                    hr,
                    org.get("employer_name") or "",
                    org.get("employer_address") or "",
                )
            else:
                vals = build_i9_field_values_es(
                    u,
                    hr,
                    org.get("employer_name") or "",
                    org.get("employer_address") or "",
                )
            try:
                pdf = fill_i9_pdf_bytes(path, vals)
            except RuntimeError as e:
                return jsonify({"error": str(e)}), 503
            ln = (u.get("last_name") or "user").replace("/", "-")[:40]
            fn = f"i9-prefill-{locale}-{ln}-{user_id}.pdf"
            _record_hub_download(fn)
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{fn}"'},
            )

        if fid in ("irs_w4", "irs_w9", "ny_it2104") and locale in ("en", "es"):
            cur = conn.cursor()
            ensure_hr_extended_profiles_table(cur)
            c = conn.cursor(dictionary=True)
            c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (user_id,))
            hr = c.fetchone()
            work = work_json_from_hr_row(hr)
            try:
                if fid == "irs_w4":
                    oid_w4 = int(u.get("organization_id") or _tenant_id())
                    org_w4 = fetch_hr_org_settings(conn, oid_w4)
                    vals = build_irs_w4_field_values(
                        u, hr, work, locale, template_path=path, org=org_w4
                    )
                elif fid == "irs_w9":
                    vals = build_irs_w9_field_values(u, work, locale, hr_row=hr)
                else:
                    vals = build_ny_it2104_field_values(u, work, hr_row=hr)
                pdf = fill_acroform_pdf_bytes(path, vals)
            except Exception as e:
                return jsonify({"error": f"PDF fill failed: {e}"}), 503
            fn = f"{fid}-prefill-{locale}-{user_id}.pdf"
            _record_hub_download(fn)
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{fn}"'},
            )

        mime = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if ext == ".docx"
            else "application/pdf"
        )
        _record_hub_download(dl)
        return send_file(path, mimetype=mime, as_attachment=True, download_name=dl)
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/hr-forms/i9", methods=["POST"])
@require_auth
def user_hr_form_i9(user_id):
    """Backward-compatible I-9 download: English and Spanish AcroForm prefill (see build_i9_field_values / _es)."""
    body = request.get_json(silent=True) or {}
    locale = str(body.get("locale") or request.args.get("locale") or "en").lower()
    if locale not in ("en", "es"):
        locale = "en"
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "HR forms require unified payroll"}), 503
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        u = fetch_payroll_profile_row(conn, user_id)
        if not u:
            return jsonify(
                {
                    "error": "No payroll profile for this user. Add or migrate the employee in People first.",
                }
            ), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        allowed_lanes = infer_user_form_lanes(conn, user_id)
        if "employee_w2" not in allowed_lanes:
            return jsonify({"error": "I-9 applies to this worker's W-2 packet only."}), 404
        cur = conn.cursor()
        ensure_hr_extended_profiles_table(cur)
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (user_id,))
        hr = c.fetchone()
        oid = int(u.get("organization_id") or _tenant_id())
        org = fetch_hr_org_settings(conn, oid)
        path = resolve_form_asset_path("uscis_i9", locale) or (
            resolve_i9_template_path() if locale == "en" else None
        )
        if not path:
            return jsonify(
                {
                    "error": "I-9 template PDF not found. Add uscis_i9_en.pdf under hr_form_assets/forms/ or set HR_I9_TEMPLATE_PATH.",
                }
            ), 503
        if locale == "en":
            vals = build_i9_field_values(
                u,
                hr,
                org.get("employer_name") or "",
                org.get("employer_address") or "",
            )
        else:
            vals = build_i9_field_values_es(
                u,
                hr,
                org.get("employer_name") or "",
                org.get("employer_address") or "",
            )
        try:
            pdf = fill_i9_pdf_bytes(path, vals)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        ln = (u.get("last_name") or "user").replace("/", "-")[:40]
        fn = f"i9-prefill-{locale}-{ln}-{user_id}.pdf"
        try:
            i9def = get_form_def("uscis_i9") or {}
            upsert_generated_hr_form_record(
                conn,
                int(u.get("organization_id") or _tenant_id()),
                int(user_id),
                int(g.ta_user["id"]),
                document_code="uscis_i9",
                document_name=str(i9def.get("title") or "uscis_i9"),
                form_locale=locale,
                download_filename=fn,
            )
        except Exception:
            current_app.logger.exception("upsert generated document record failed")
        return Response(
            pdf,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'},
        )
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/documents", methods=["GET", "POST"])
@require_auth
def user_document_records(user_id):
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "Documents require unified payroll"}), 503
        u = fetch_payroll_profile_row(conn, user_id)
        if not u:
            return jsonify({"error": "No payroll profile for this user"}), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        oid = int(u.get("organization_id") or _tenant_id())
        cur = conn.cursor()
        ensure_document_compliance_tables(cur)
        if request.method == "GET":
            if not user_has_perm(conn, g.ta_user["id"], "users.view"):
                return jsonify({"error": "Forbidden"}), 403
            return jsonify({"items": list_employee_document_records(conn, oid, user_id)})
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        body = request.json or {}
        try:
            row = create_employee_document_record(conn, oid, user_id, int(g.ta_user["id"]), body)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        write_audit(conn, g.ta_user["id"], "employee_document_records", row.get("id"), "create", new=body)
        conn.commit()
        return jsonify(row), 201
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/documents/<int:record_id>", methods=["PUT", "DELETE"])
@require_auth
def user_document_record_item(user_id, record_id):
    conn = get_db()
    try:
        if not payroll_profiles_active(conn):
            return jsonify({"error": "Documents require unified payroll"}), 503
        u = fetch_payroll_profile_row(conn, user_id)
        if not u:
            return jsonify({"error": "No payroll profile for this user"}), 404
        if not _ta_user_can_access_payroll_subject(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        if not user_has_perm(conn, g.ta_user["id"], "users.edit"):
            return jsonify({"error": "Forbidden"}), 403
        oid = int(u.get("organization_id") or _tenant_id())
        cur = conn.cursor()
        ensure_document_compliance_tables(cur)
        if request.method == "DELETE":
            ok = delete_employee_document_record(conn, oid, user_id, record_id)
            if not ok:
                return jsonify({"error": "Not found"}), 404
            write_audit(conn, g.ta_user["id"], "employee_document_records", record_id, "delete")
            conn.commit()
            return jsonify({"ok": True})
        body = request.json or {}
        row = update_employee_document_record(conn, oid, user_id, record_id, body)
        if not row:
            return jsonify({"error": "Not found"}), 404
        write_audit(conn, g.ta_user["id"], "employee_document_records", record_id, "update", new=body)
        conn.commit()
        return jsonify(row)
    finally:
        conn.close()


@ta_bp.route("/admin/document-compliance-policy", methods=["GET", "PUT"])
@require_auth
def admin_document_compliance_policy():
    conn = get_db()
    try:
        if not user_has_perm(conn, g.ta_user["id"], "ta.settings"):
            return jsonify({"error": "Forbidden"}), 403
        oid = _tenant_id()
        cur = conn.cursor()
        ensure_document_compliance_tables(cur)
        if request.method == "GET":
            return jsonify(get_document_compliance_policy(conn, oid))
        body = request.json or {}
        out = upsert_document_compliance_policy(conn, oid, int(g.ta_user["id"]), body)
        write_audit(conn, g.ta_user["id"], "org_document_compliance_policy", oid, "update", new=body)
        conn.commit()
        return jsonify(out)
    finally:
        conn.close()


@ta_bp.route("/admin/document-compliance/expiring", methods=["GET"])
@require_auth
def admin_document_compliance_expiring():
    conn = get_db()
    try:
        if not (user_has_perm(conn, g.ta_user["id"], "users.view") or user_has_perm(conn, g.ta_user["id"], "ta.monitor")):
            return jsonify({"error": "Forbidden"}), 403
        cur = conn.cursor()
        ensure_document_compliance_tables(cur)
        days = int(request.args.get("days") or 14)
        code = (request.args.get("document_code") or "").strip() or None
        items = list_expiring_document_records(conn, _tenant_id(), days=days, code=code)
        return jsonify({"items": items, "days": days, "document_code": code})
    finally:
        conn.close()


# --- Geofences CRUD ---


@ta_bp.route("/geofences", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def geofences_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM geofences WHERE organization_id=%s ORDER BY name",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/geofences", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def geofences_create():
    data = request.json or {}
    for k in ("name", "latitude", "longitude", "radius_meters"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO geofences (organization_id, name, location_description, latitude, longitude, radius_meters, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                _tenant_id(),
                data["name"],
                data.get("location_description"),
                float(data["latitude"]),
                float(data["longitude"]),
                int(data["radius_meters"]),
                1 if data.get("active", True) else 0,
            ),
        )
        gid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "geofence", gid, "create", new=data)
        conn.commit()
        return jsonify({"id": gid}), 201
    finally:
        conn.close()


@ta_bp.route("/geofences/<int:gid>", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def geofences_update(gid):
    data = request.json or {}
    conn = get_db()
    try:
        fields = []
        vals = []
        for col in (
            "name",
            "location_description",
            "latitude",
            "longitude",
            "radius_meters",
            "active",
        ):
            if col in data:
                v = data[col]
                if col == "active":
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if not fields:
            return jsonify({"error": "No fields"}), 400
        vals.extend([gid, _tenant_id()])
        c = conn.cursor()
        c.execute(
            f"UPDATE geofences SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            vals,
        )
        write_audit(conn, g.ta_user["id"], "geofence", gid, "update", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/geofences/<int:gid>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def geofences_delete(gid):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE geofences SET active=0 WHERE id=%s AND organization_id=%s",
            (gid, _tenant_id()),
        )
        if c.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
        write_audit(
            conn,
            g.ta_user["id"],
            "geofence",
            gid,
            "deactivate",
            new={"active": False},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- Employment categories & rates ---


@ta_bp.route("/org-hr-lookups", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def org_hr_lookups_list():
    conn = get_db()
    try:
        _ensure_people_workspace(conn)
        cat = (request.args.get("category") or "").strip()
        c = conn.cursor(dictionary=True)
        if cat:
            c.execute(
                """
                SELECT * FROM org_hr_lookup
                WHERE organization_id=%s AND category=%s AND active=1
                ORDER BY sort_order, label
                """,
                (_tenant_id(), cat),
            )
        else:
            c.execute(
                """
                SELECT * FROM org_hr_lookup
                WHERE organization_id=%s AND active=1
                ORDER BY category, sort_order, label
                """,
                (_tenant_id(),),
            )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/org-hr-lookups", methods=["POST"])
@require_auth
@require_perm("users.edit")
def org_hr_lookups_create():
    data = request.json or {}
    cat = (data.get("category") or "").strip()
    code = (data.get("code") or "").strip()
    label = (data.get("label") or "").strip()
    if not cat or not code or not label:
        return jsonify({"error": "category, code, and label required"}), 400
    sort_order = int(data.get("sort_order") or 0)
    conn = get_db()
    try:
        _ensure_people_workspace(conn)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO org_hr_lookup (organization_id, category, code, label, sort_order, active)
            VALUES (%s,%s,%s,%s,%s,1)
            """,
            (_tenant_id(), cat, code, label, sort_order),
        )
        lid = c.lastrowid
        conn.commit()
        return jsonify({"id": lid}), 201
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) == 1062:
            return jsonify({"error": "Duplicate code for this category"}), 400
        raise
    finally:
        conn.close()


@ta_bp.route("/org-hr-lookups/<int:lid>", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def org_hr_lookups_update(lid):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT id FROM org_hr_lookup WHERE id=%s AND organization_id=%s",
            (lid, _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Not found"}), 404
        fields = []
        vals = []
        for col in ("label", "sort_order", "active"):
            if col in data:
                v = data[col]
                if col == "active":
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if not fields:
            return jsonify({"error": "No fields"}), 400
        vals.extend([lid, _tenant_id()])
        c2 = conn.cursor()
        c2.execute(
            f"UPDATE org_hr_lookup SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            vals,
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/employment-categories", methods=["GET"])
@require_auth
def employment_categories_list():
    conn = get_db()
    try:
        _ensure_people_workspace(conn)
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM employment_categories WHERE organization_id=%s ORDER BY name",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/employment-categories", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def employment_categories_create():
    data = request.json or {}
    if not data.get("name") or not data.get("code"):
        return jsonify({"error": "name and code required"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO employment_categories (organization_id, code, name, active)
            VALUES (%s,%s,%s,%s)
            """,
            (
                _tenant_id(),
                data["code"],
                data["name"],
                1 if data.get("active", True) else 0,
            ),
        )
        cid = c.lastrowid
        conn.commit()
        return jsonify({"id": cid}), 201
    finally:
        conn.close()


@ta_bp.route("/employment-categories/<int:cid>", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def employment_categories_update(cid):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s",
            (cid, _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Not found"}), 404
        fields = []
        vals = []
        for col in ("code", "name", "active"):
            if col in data:
                v = data[col]
                if col == "active":
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if not fields:
            return jsonify({"error": "No fields"}), 400
        vals.extend([cid, _tenant_id()])
        c.execute(
            f"UPDATE employment_categories SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            vals,
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "employment_category",
            cid,
            "update",
            new=data,
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/employment-categories/<int:cid>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def employment_categories_delete(cid):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE employment_categories SET active=0 WHERE id=%s AND organization_id=%s",
            (cid, _tenant_id()),
        )
        if c.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
        write_audit(
            conn,
            g.ta_user["id"],
            "employment_category",
            cid,
            "deactivate",
            new={"active": False},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/user-rates", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def user_rates_list():
    uid = request.args.get("user_id")
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if uid:
            c.execute(
                """
                SELECT ur.*, ec.name AS category_name, ec.code AS category_code
                FROM user_rates ur
                JOIN employment_categories ec ON ec.id = ur.employment_category_id
                JOIN users u ON u.id = ur.user_id
                WHERE ur.user_id=%s AND u.organization_id=%s
                ORDER BY ur.effective_date DESC
                """,
                (int(uid), _tenant_id()),
            )
        else:
            if payroll_profiles_active(conn):
                c.execute(
                    """
                    SELECT ur.*, ec.name AS category_name, pp.email AS user_email
                    FROM user_rates ur
                    JOIN employment_categories ec ON ec.id = ur.employment_category_id
                    JOIN payroll_profiles pp ON pp.user_id = ur.user_id
                    JOIN users u ON u.id = ur.user_id
                    WHERE u.organization_id=%s
                    ORDER BY ur.effective_date DESC
                    LIMIT 500
                    """,
                    (_tenant_id(),),
                )
            else:
                c.execute(
                    """
                    SELECT ur.*, ec.name AS category_name, u.email AS user_email
                    FROM user_rates ur
                    JOIN employment_categories ec ON ec.id = ur.employment_category_id
                    JOIN ta_users u ON u.id = ur.user_id
                    ORDER BY ur.effective_date DESC
                    LIMIT 500
                    """
                )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/user-rates", methods=["POST"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def user_rates_create():
    data = request.json or {}
    for k in ("user_id", "employment_category_id", "hourly_rate", "effective_date"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        if payroll_profiles_active(conn):
            if not _user_belongs_to_tenant(conn, int(data["user_id"])):
                return jsonify({"error": "Invalid user"}), 400
        c.execute(
            """
            SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s
            """,
            (int(data["employment_category_id"]), _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Invalid employment category"}), 400
        c.execute(
            """
            INSERT INTO user_rates (user_id, employment_category_id, hourly_rate, effective_date, end_date, role_job_function)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                int(data["user_id"]),
                int(data["employment_category_id"]),
                float(data["hourly_rate"]),
                data["effective_date"],
                data.get("end_date"),
                data.get("role_job_function"),
            ),
        )
        rid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "user_rate", rid, "create", new=data)
        conn.commit()
        return jsonify({"id": rid}), 201
    finally:
        conn.close()


def _user_rate_belongs_to_tenant(conn, rid: int) -> bool:
    c = conn.cursor()
    if payroll_profiles_active(conn):
        c.execute(
            """
            SELECT 1 FROM user_rates ur
            JOIN users u ON u.id = ur.user_id
            WHERE ur.id=%s AND u.organization_id=%s
            """,
            (rid, _tenant_id()),
        )
    else:
        c.execute(
            """
            SELECT 1 FROM user_rates ur
            JOIN ta_users u ON u.id = ur.user_id
            WHERE ur.id=%s
            """,
            (rid,),
        )
    return bool(c.fetchone())


@ta_bp.route("/user-rates/<int:rid>", methods=["PUT"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def user_rates_update(rid):
    data = request.json or {}
    conn = get_db()
    try:
        if not _user_rate_belongs_to_tenant(conn, rid):
            return jsonify({"error": "Not found"}), 404
        fields = []
        vals = []
        for col in ("hourly_rate", "effective_date", "end_date", "role_job_function"):
            if col in data:
                v = data[col]
                if col == "end_date" and v in ("", None):
                    v = None
                fields.append(f"{col}=%s")
                vals.append(v)
        if not fields:
            return jsonify({"error": "No fields"}), 400
        vals.append(rid)
        c = conn.cursor()
        c.execute(
            f"UPDATE user_rates SET {', '.join(fields)} WHERE id=%s",
            vals,
        )
        write_audit(conn, g.ta_user["id"], "user_rate", rid, "update", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/user-rates/<int:rid>", methods=["DELETE"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def user_rates_delete(rid):
    conn = get_db()
    try:
        if not _user_rate_belongs_to_tenant(conn, rid):
            return jsonify({"error": "Not found"}), 404
        c = conn.cursor()
        c.execute("DELETE FROM user_rates WHERE id=%s", (rid,))
        write_audit(conn, g.ta_user["id"], "user_rate", rid, "delete", new={"id": rid})
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- Monitor ---


@ta_bp.route("/monitor/sessions", methods=["GET"])
@require_auth
@require_perm("ta.monitor")
def monitor_sessions():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        has_pc_review = table_has_column(c, "payroll_cycles", "review_state")
        can_see_pending = user_has_perm(conn, g.ta_user["id"], "ta.settings")
        review_select = ", pc.review_state AS payroll_cycle_review_state" if has_pc_review else ""
        review_filter = ""
        if has_pc_review and not can_see_pending:
            review_filter = (
                " AND (pc.review_state IS NULL OR pc.review_state NOT IN ('pending_approval'))"
            )
        if payroll_profiles_active(conn):
            q = f"""
            SELECT s.*, pp.email, pp.first_name, pp.last_name, g.name AS geofence_name,
                   pc.cycle_ref, ec.name AS category_name
                   {review_select}
            FROM shift_sessions s
            JOIN payroll_profiles pp ON pp.user_id = s.user_id
            JOIN geofences g ON g.id = s.geofence_id
            JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
            LEFT JOIN employment_categories ec ON ec.id = s.employment_category_id
            WHERE s.organization_id=%s
            {review_filter}
            """
        else:
            q = f"""
            SELECT s.*, u.email, u.first_name, u.last_name, g.name AS geofence_name,
                   pc.cycle_ref, ec.name AS category_name
                   {review_select}
            FROM shift_sessions s
            JOIN ta_users u ON u.id = s.user_id
            JOIN geofences g ON g.id = s.geofence_id
            JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
            LEFT JOIN employment_categories ec ON ec.id = s.employment_category_id
            WHERE s.organization_id=%s
            {review_filter}
            """
        params = [_tenant_id()]
        if request.args.get("payroll_cycle_id"):
            q += " AND s.payroll_cycle_id=%s"
            params.append(int(request.args["payroll_cycle_id"]))
        if request.args.get("user_id"):
            q += " AND s.user_id=%s"
            params.append(int(request.args["user_id"]))
        if request.args.get("from_date"):
            q += " AND DATE(s.clock_in_at) >= %s"
            params.append(request.args["from_date"])
        if request.args.get("to_date"):
            q += " AND DATE(s.clock_in_at) <= %s"
            params.append(request.args["to_date"])
        if request.args.get("geofence_id"):
            q += " AND s.geofence_id=%s"
            params.append(int(request.args["geofence_id"]))
        q += " ORDER BY s.clock_in_at DESC, s.id DESC LIMIT 500"
        c.execute(q, params)
        rows = c.fetchall()
        enriched = _enrich_monitor_rows(conn, rows, _tenant_id())
        return jsonify(enriched)
    finally:
        conn.close()


@ta_bp.route("/sessions/<int:sid>/force-clock-out", methods=["POST"])
@require_auth
@require_perm("ta.override")
def force_clock_out(sid):
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        sess = c.fetchone()
        if not sess or sess["status"] != "active":
            return jsonify({"error": "No active session"}), 400

        if get_open_break(conn, sid):
            return jsonify({"error": "User is on break; end break first"}), 400

        br = sum_break_seconds(conn, sid)
        now = eastern_now_naive()
        clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
        if not clock_in:
            return jsonify({"error": "Invalid session"}), 400
        elapsed = (now - clock_in).total_seconds()
        net = int(elapsed) - br

        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE shift_sessions
            SET clock_out_at=%s, status='completed', total_break_seconds=%s,
                net_work_seconds=%s, manual_override=1
            WHERE id=%s
            """,
            (now, br, net, sid),
        )
        c2.execute(
            """
            INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message)
            VALUES (%s,%s,'manual_force_clock_out',%s)
            """,
            (sid, sess["user_id"], remarks),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "force_clock_out",
            remarks=remarks,
        )
        conn.commit()
        return jsonify(json_safe(fetch_session(conn, sid)))
    finally:
        conn.close()


@ta_bp.route("/sessions/<int:sid>/adjust-times", methods=["POST"])
@require_auth
@require_perm("ta.override")
def adjust_times(sid):
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "Not found"}), 400

        cin = data.get("clock_in_at")
        cout = data.get("clock_out_at")
        if cin:
            c.execute("UPDATE shift_sessions SET clock_in_at=%s, manual_override=1 WHERE id=%s", (cin, sid))
        if cout:
            c.execute("UPDATE shift_sessions SET clock_out_at=%s, manual_override=1 WHERE id=%s", (cout, sid))

        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        s2 = c.fetchone()
        br = sum_break_seconds(conn, sid)
        if s2["clock_in_at"] and s2["clock_out_at"]:
            ci, co = s2["clock_in_at"], s2["clock_out_at"]
            if isinstance(ci, str):
                ci = datetime.fromisoformat(str(ci).replace("Z", "+00:00"))
            if isinstance(co, str):
                co = datetime.fromisoformat(str(co).replace("Z", "+00:00"))
            if ci.tzinfo:
                ci = ci.replace(tzinfo=None)
            if co.tzinfo:
                co = co.replace(tzinfo=None)
            net = int((co - ci).total_seconds()) - br
            c.execute(
                "UPDATE shift_sessions SET total_break_seconds=%s, net_work_seconds=%s WHERE id=%s",
                (br, net, sid),
            )

        write_audit(conn, g.ta_user["id"], "shift_session", sid, "adjust_times", new=data, remarks=remarks)
        conn.commit()
        return jsonify(json_safe(fetch_session(conn, sid)))
    finally:
        conn.close()


@ta_bp.route("/adjustments", methods=["POST"])
@require_auth
@require_perm("ta.override")
def create_adjustment():
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "user_id required"}), 400

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO payroll_adjustments (
              shift_session_id, payroll_cycle_id, user_id, adjustment_type,
              amount_cents, slack_minutes, remarks, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("shift_session_id"),
                data.get("payroll_cycle_id"),
                int(uid),
                data.get("adjustment_type", "manual"),
                int(data.get("amount_cents") or 0),
                int(data.get("slack_minutes") or 0),
                remarks,
                g.ta_user["id"],
            ),
        )
        aid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "payroll_adjustment", aid, "create", new=data, remarks=remarks)
        conn.commit()
        return jsonify({"id": aid}), 201
    finally:
        conn.close()


@ta_bp.route("/exceptions", methods=["GET"])
@require_auth
@require_perm("ta.monitor")
def list_exceptions():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_exceptions
            ORDER BY created_at DESC LIMIT 200
            """
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payroll-cycles", methods=["GET"])
@require_auth
@require_any_perm("ta.monitor", "ta.settings")
def payroll_cycles_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM payroll_cycles WHERE organization_id=%s ORDER BY week_start_date DESC LIMIT 52",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payroll-cycles/<int:pc_id>/submit-for-approval", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def payroll_cycle_submit_for_approval(pc_id):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if not table_has_column(c, "payroll_cycles", "review_state"):
            return jsonify({"error": "Database migration required: payroll_workflow_and_session_payroll_v1.sql"}), 400
        c.execute(
            "SELECT * FROM payroll_cycles WHERE id=%s AND organization_id=%s",
            (pc_id, _tenant_id()),
        )
        pc = c.fetchone()
        if not pc:
            return jsonify({"error": "Not found"}), 404
        st = str(pc.get("review_state") or "open").strip()
        if st != "open":
            return jsonify({"error": "Only cycles in open review state can be submitted"}), 400
        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE payroll_cycles
            SET review_state='pending_approval', submitted_at=NOW()
            WHERE id=%s AND organization_id=%s
            """,
            (pc_id, _tenant_id()),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "payroll_cycle",
            pc_id,
            "submit_for_approval",
            new={"review_state": "pending_approval"},
        )
        conn.commit()
        c.execute("SELECT * FROM payroll_cycles WHERE id=%s", (pc_id,))
        return jsonify(json_safe(c.fetchone()))
    finally:
        conn.close()


@ta_bp.route("/payroll-cycles/<int:pc_id>/approve", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def payroll_cycle_approve(pc_id):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if not table_has_column(c, "payroll_cycles", "review_state"):
            return jsonify({"error": "Database migration required: payroll_workflow_and_session_payroll_v1.sql"}), 400
        c.execute(
            "SELECT * FROM payroll_cycles WHERE id=%s AND organization_id=%s",
            (pc_id, _tenant_id()),
        )
        pc = c.fetchone()
        if not pc:
            return jsonify({"error": "Not found"}), 404
        st = str(pc.get("review_state") or "").strip()
        if st != "pending_approval":
            return jsonify({"error": "Only cycles pending approval can be approved"}), 400
        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE payroll_cycles
            SET review_state='approved', approved_at=NOW()
            WHERE id=%s AND organization_id=%s
            """,
            (pc_id, _tenant_id()),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "payroll_cycle",
            pc_id,
            "approve",
            new={"review_state": "approved"},
        )
        conn.commit()
        c.execute("SELECT * FROM payroll_cycles WHERE id=%s", (pc_id,))
        return jsonify(json_safe(c.fetchone()))
    finally:
        conn.close()


@ta_bp.route("/sessions/<int:sid>/payroll-line", methods=["PATCH"])
@require_auth
@require_perm("ta.settings")
def session_payroll_line_patch(sid):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        has_rev = table_has_column(c, "payroll_cycles", "review_state")
        rev_sel = ", pc.review_state AS payroll_cycle_review_state" if has_rev else ""
        c.execute(
            f"""
            SELECT s.*{rev_sel}
            FROM shift_sessions s
            JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
            WHERE s.id=%s AND s.organization_id=%s
            """,
            (sid, _tenant_id()),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "Not found"}), 404
        rev = str(sess.get("payroll_cycle_review_state") or "open").strip()
        if has_rev and rev not in ("open", "pending_approval"):
            return jsonify({"error": "Payroll line is locked for this cycle"}), 403
        fields = []
        vals = []
        if "geofence_outside_payable" in data and table_has_column(
            c, "shift_sessions", "geofence_outside_payable"
        ):
            fields.append("geofence_outside_payable=%s")
            vals.append(1 if as_bool(data.get("geofence_outside_payable")) else 0)
        if "geofence_outside_deduction_excluded" in data and table_has_column(
            c, "shift_sessions", "geofence_outside_deduction_excluded"
        ):
            fields.append("geofence_outside_deduction_excluded=%s")
            vals.append(1 if as_bool(data.get("geofence_outside_deduction_excluded")) else 0)
        if "laundry_bag_deduction_excluded" in data and table_has_column(
            c, "shift_sessions", "laundry_bag_deduction_excluded"
        ):
            fields.append("laundry_bag_deduction_excluded=%s")
            vals.append(1 if as_bool(data.get("laundry_bag_deduction_excluded")) else 0)
        if "period_adjustment_remarks" in data and table_has_column(
            c, "shift_sessions", "period_adjustment_remarks"
        ):
            fields.append("period_adjustment_remarks=%s")
            vals.append((data.get("period_adjustment_remarks") or "")[:2000])
        if "period_bonus_cents" in data and table_has_column(c, "shift_sessions", "period_bonus_cents"):
            fields.append("period_bonus_cents=%s")
            vals.append(int(data.get("period_bonus_cents") or 0))
        if "period_deduction_cents" in data and table_has_column(
            c, "shift_sessions", "period_deduction_cents"
        ):
            fields.append("period_deduction_cents=%s")
            vals.append(int(data.get("period_deduction_cents") or 0))
        if not fields:
            return jsonify({"error": "No updatable fields"}), 400
        vals.append(sid)
        c2 = conn.cursor()
        c2.execute(
            f"UPDATE shift_sessions SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            vals + [_tenant_id()],
        )
        write_audit(conn, g.ta_user["id"], "shift_session", sid, "payroll_line_patch", new=data)
        conn.commit()
        return jsonify(json_safe(fetch_session(conn, sid)))
    finally:
        conn.close()


@ta_bp.route("/settings", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def settings_get():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT skey, svalue FROM system_settings WHERE organization_id=%s",
            (_tenant_id(),),
        )
        return jsonify({r["skey"]: r["svalue"] for r in c.fetchall()})
    finally:
        conn.close()


@ta_bp.route("/settings", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def settings_put():
    data = request.json or {}
    conn = get_db()
    try:
        for k, v in data.items():
            set_setting(conn, _tenant_id(), k, str(v))
        write_audit(conn, g.ta_user["id"], "system_settings", 0, "update", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/audit-log", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def audit_log_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT a.*, pp.email AS actor_email
                FROM audit_log a
                LEFT JOIN payroll_profiles pp ON pp.user_id = a.actor_user_id
                WHERE a.organization_id = %s
                ORDER BY a.id DESC LIMIT 200
                """,
                (_tenant_id(),),
            )
        else:
            c.execute(
                """
                SELECT a.*, u.email AS actor_email
                FROM audit_log a
                LEFT JOIN ta_users u ON u.id = a.actor_user_id
                WHERE a.organization_id = %s
                ORDER BY a.id DESC LIMIT 200
                """,
                (_tenant_id(),),
            )
        rows = c.fetchall()
        return jsonify([json_safe(r) for r in rows])
    finally:
        conn.close()


@ta_bp.route("/roles", methods=["GET"])
@require_auth
def roles_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        vis_sql, vis_params = _role_visible_sql(c, "r")
        if table_has_column(c, "roles", "organization_id"):
            c.execute(
                f"""
                SELECT id, code, name, organization_id, is_system
                FROM roles r
                WHERE {vis_sql}
                ORDER BY r.organization_id, r.name
                """,
                vis_params,
            )
        else:
            c.execute("SELECT id, code, name FROM roles ORDER BY name")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payment-methods", methods=["GET"])
@require_auth
@require_perm("finance.payments")
def payment_methods_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM payment_methods WHERE active=1 ORDER BY name")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payments", methods=["POST"])
@require_auth
@require_perm("finance.payments")
def payments_upsert():
    data = request.json or {}
    for k in ("payroll_cycle_id", "user_id", "payment_status"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO payroll_payments (payroll_cycle_id, user_id, payment_status, paid_date, payment_method_id, remarks, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              payment_status=VALUES(payment_status),
              paid_date=VALUES(paid_date),
              payment_method_id=VALUES(payment_method_id),
              remarks=VALUES(remarks),
              created_by=VALUES(created_by)
            """,
            (
                int(data["payroll_cycle_id"]),
                int(data["user_id"]),
                data["payment_status"],
                data.get("paid_date"),
                data.get("payment_method_id"),
                data.get("remarks"),
                g.ta_user["id"],
            ),
        )
        write_audit(conn, g.ta_user["id"], "payroll_payment", data["user_id"], "upsert", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/bag-count", methods=["POST"])
@require_auth
@require_perm("ta.override")
def bag_count_increment():
    data = request.json or {}
    uid = data.get("user_id")
    pc_id = data.get("payroll_cycle_id")
    delta = int(data.get("delta", 1))
    if not uid or not pc_id:
        return jsonify({"error": "user_id and payroll_cycle_id required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM bag_count_summary WHERE user_id=%s AND payroll_cycle_id=%s",
            (int(uid), int(pc_id)),
        )
        row = c.fetchone()
        if row:
            new_c = row["bag_count"] + delta
            c2 = conn.cursor()
            c2.execute(
                "UPDATE bag_count_summary SET bag_count=%s WHERE id=%s",
                (new_c, row["id"]),
            )
        else:
            c2 = conn.cursor()
            c2.execute(
                "INSERT INTO bag_count_summary (user_id, payroll_cycle_id, bag_count) VALUES (%s,%s,%s)",
                (int(uid), int(pc_id), max(0, delta)),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/bag-rates", methods=["GET"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def bag_rates_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM bag_rate_maintenance ORDER BY effective_from DESC")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


# --- Clock / payroll UI (tenant) ---


@ta_bp.route("/clock-payroll-ui", methods=["GET"])
@require_auth
def clock_payroll_ui_get():
    """Clock + payroll screen visibility for this tenant (any authenticated TA / Washpro user)."""
    conn = get_db()
    try:
        return jsonify(load_clock_payroll_ui(conn, _tenant_id()))
    finally:
        conn.close()


@ta_bp.route("/admin/clock-payroll-ui", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def clock_payroll_ui_put():
    data = request.json or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid body"}), 400
    clock = data.get("clock")
    payroll = data.get("payroll")
    if clock is not None and not isinstance(clock, dict):
        return jsonify({"error": "clock must be an object"}), 400
    if payroll is not None and not isinstance(payroll, dict):
        return jsonify({"error": "payroll must be an object"}), 400
    conn = get_db()
    try:
        cur = load_clock_payroll_ui(conn, _tenant_id())
        if isinstance(clock, dict):
            cur["clock"] = {**_default_clock_ui_dict(), **clock}
        if isinstance(payroll, dict):
            cur["payroll"] = {**_default_payroll_screen_dict(), **payroll}
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
            """,
            (int(_tenant_id()), _CLOCK_PAYROLL_UI_KEY, json.dumps(cur)),
        )
        conn.commit()
        return jsonify({"ok": True, **cur})
    finally:
        conn.close()


# --- Admin: payroll period (week anchor + cycle ref prefix) ---


@ta_bp.route("/admin/payroll-period", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def admin_payroll_period_get():
    conn = get_db()
    try:
        row = get_payroll_period_settings(conn, _tenant_id())
        if not row:
            return jsonify(
                {
                    "week_starts_on": 0,
                    "ref_prefix": "PC",
                    "note": "Run organizations_multitenancy_v1.sql (payroll_period_settings per org).",
                }
            )
        return jsonify(json_safe(row))
    finally:
        conn.close()


@ta_bp.route("/admin/payroll-period", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def admin_payroll_period_put():
    data = request.json or {}
    ws = data.get("week_starts_on", 0)
    try:
        ws = int(ws)
    except (TypeError, ValueError):
        return jsonify({"error": "week_starts_on must be 0-6"}), 400
    if ws < 0 or ws > 6:
        return jsonify({"error": "week_starts_on must be 0-6 (Mon-Sun)"}), 400
    prefix = (data.get("ref_prefix") or "PC").strip()[:16] or "PC"
    conn = get_db()
    try:
        set_payroll_period_settings(conn, _tenant_id(), ws, prefix)
        conn.commit()
        return jsonify({"ok": True, "week_starts_on": ws, "ref_prefix": prefix})
    finally:
        conn.close()


# --- Admin: role ↔ permission matrix (Washpro TA permissions catalog) ---


@ta_bp.route("/admin/permission-matrix", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def admin_permission_matrix():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if table_has_column(c, "permissions", "route_key"):
            c.execute(
                """
                SELECT id, perm_key, description, route_key, route_label,
                       section_key, section_label, resource_key, resource_label,
                       action_key, sort_order
                FROM permissions
                ORDER BY route_key, section_key, resource_key, sort_order, perm_key
                """
            )
        else:
            c.execute("SELECT id, perm_key, description FROM permissions ORDER BY perm_key")
        perms = [json_safe(x) for x in c.fetchall()]
        for p in perms:
            if not p.get("route_key"):
                pk = p.get("perm_key") or ""
                bits = pk.split(".")
                p["route_key"] = bits[0] if bits else "general"
                p["route_label"] = p["route_key"].replace("_", " ").title()
                p["section_key"] = bits[1] if len(bits) > 1 else ""
                p["section_label"] = (
                    p["section_key"].replace("_", " ").title() if p["section_key"] else "General"
                )
                p["resource_key"] = ""
                p["resource_label"] = ""
                p["action_key"] = bits[-1] if len(bits) > 1 else "view"
                p["sort_order"] = 0
        hierarchy = _build_permission_hierarchy(perms)

        vis_sql, vis_params = _role_visible_sql(c, "r")
        if table_has_column(c, "roles", "organization_id"):
            c.execute(
                f"""
                SELECT id, code, name, organization_id, is_system
                FROM roles r
                WHERE {vis_sql}
                ORDER BY r.organization_id, r.code
                """,
                vis_params,
            )
        else:
            c.execute("SELECT id, code, name FROM roles ORDER BY code")
        roles = c.fetchall()
        c.execute(
            """
            SELECT rp.role_id, p.perm_key
            FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            """
        )
        role_map = {}
        for row in c.fetchall():
            role_map.setdefault(row["role_id"], []).append(row["perm_key"])
        return jsonify(
            {
                "permissions": perms,
                "hierarchy": hierarchy,
                "roles": [json_safe(x) for x in roles],
                "role_permissions": {str(k): v for k, v in role_map.items()},
            }
        )
    finally:
        conn.close()


@ta_bp.route("/admin/roles", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def admin_roles_create():
    data = request.json or {}
    code = _sanitize_role_code(data.get("code") or "")
    name = (data.get("name") or "").strip() or code.replace("_", " ").title()
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        tid = _tenant_id()
        if table_has_column(c, "roles", "organization_id"):
            c.execute(
                "SELECT id FROM roles WHERE organization_id=%s AND code=%s LIMIT 1",
                (tid, code),
            )
            if c.fetchone():
                return jsonify({"error": "Role code already exists for this organization"}), 409
            c.execute(
                """
                INSERT INTO roles (organization_id, code, name, is_system)
                VALUES (%s, %s, %s, 0)
                """,
                (tid, code, name),
            )
        else:
            c.execute("SELECT id FROM roles WHERE code=%s LIMIT 1", (code,))
            if c.fetchone():
                return jsonify({"error": "Role code already exists"}), 409
            c.execute("INSERT INTO roles (code, name) VALUES (%s, %s)", (code, name))
        rid = c.lastrowid
        write_audit(
            conn,
            g.ta_user["id"],
            "roles",
            rid,
            "create",
            new={"code": code, "name": name, "organization_id": tid},
        )
        conn.commit()
        return jsonify({"ok": True, "id": rid, "code": code, "name": name})
    finally:
        conn.close()


@ta_bp.route("/admin/roles/<int:role_id>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def admin_roles_delete(role_id):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if table_has_column(c, "roles", "organization_id"):
            c.execute(
                "SELECT id, code, organization_id, is_system FROM roles WHERE id=%s",
                (int(role_id),),
            )
        else:
            c.execute("SELECT id, code FROM roles WHERE id=%s", (int(role_id),))
        meta = c.fetchone()
        if not meta:
            return jsonify({"error": "Role not found"}), 404
        if table_has_column(c, "roles", "organization_id"):
            oid = int(meta.get("organization_id") or 0)
            if oid == 0:
                auth = request.headers.get("Authorization", "")
                tok = auth[7:].strip() if auth.startswith("Bearer ") else ""
                if not washpro_bearer_is_platform_operator(conn, tok):
                    return jsonify({"error": "Platform roles are managed in the platform console"}), 403
                if as_bool(meta.get("is_system"), default=False):
                    return jsonify({"error": "Cannot delete system roles"}), 403
            elif not _role_mutable_by_tenant(c, role_id):
                return jsonify({"error": "Cannot delete system or foreign roles"}), 403
        elif not _role_mutable_by_tenant(c, role_id):
            return jsonify({"error": "Cannot delete system or foreign roles"}), 403
        if table_has_column(c, "ta_users", "role_id"):
            c.execute("SELECT COUNT(*) AS n FROM ta_users WHERE role_id=%s", (role_id,))
            n = (c.fetchone() or {}).get("n", 0) or 0
            if n:
                return jsonify({"error": f"Role is assigned to {n} TA user(s); reassign first"}), 409
        if table_exists(c, "user_roles"):
            c.execute("SELECT COUNT(*) AS n FROM user_roles WHERE role_id=%s", (role_id,))
            n = (c.fetchone() or {}).get("n", 0) or 0
            if n:
                return jsonify({"error": f"Role is assigned to {n} login(s); reassign first"}), 409
        c.execute("DELETE FROM roles WHERE id=%s", (role_id,))
        write_audit(
            conn,
            g.ta_user["id"],
            "roles",
            role_id,
            "delete",
            old={"code": meta.get("code")},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/admin/roles/<int:role_id>/permissions", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def admin_role_permissions_put(role_id):
    data = request.json or {}
    keys = data.get("permission_keys")
    if not isinstance(keys, list):
        return jsonify({"error": "permission_keys array required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT id FROM roles WHERE id=%s", (role_id,))
        if not c.fetchone():
            return jsonify({"error": "Role not found"}), 404
        if table_has_column(c, "roles", "organization_id"):
            c.execute(
                "SELECT organization_id FROM roles WHERE id=%s",
                (role_id,),
            )
            rrow = c.fetchone()
            oid = int(rrow.get("organization_id") or 0)
            if oid == 0:
                auth = request.headers.get("Authorization", "")
                tok = auth[7:].strip() if auth.startswith("Bearer ") else ""
                if not washpro_bearer_is_platform_operator(conn, tok):
                    return jsonify(
                        {
                            "error": "Platform role packages are edited under /platform (Role packages)."
                        }
                    ), 403
            elif oid != _tenant_id():
                return jsonify({"error": "Role not in your organization"}), 403
        c2 = conn.cursor()
        c2.execute("DELETE FROM role_permissions WHERE role_id=%s", (role_id,))
        for key in keys:
            c.execute("SELECT id FROM permissions WHERE perm_key=%s", (key,))
            prow = c.fetchone()
            if prow:
                c2.execute(
                    "INSERT IGNORE INTO role_permissions (role_id, permission_id) VALUES (%s,%s)",
                    (role_id, prow["id"]),
                )
        write_audit(
            conn,
            g.ta_user["id"],
            "role_permissions",
            role_id,
            "replace",
            new={"permission_keys": keys},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


def register_ta_routes(app):
    app.register_blueprint(ta_bp, url_prefix="/api/ta")
