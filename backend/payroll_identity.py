"""
Unified payroll identity: Washpro `users.id` is the only subject id for clock, geofences,
rates, and permissions (via `user_roles` ↔ `role_permissions`).

When table `payroll_profiles` exists, this module is active. Until migration SQL is applied,
`ta_users` remains the source of record (legacy).
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from backend.ta_helpers import cycle_ref_for_week_start, hash_password, week_bounds_for_date

_schema_lock = threading.Lock()
_organizations_table_cache: Optional[bool] = None
_organizations_logo_col_cache: Optional[bool] = None
_payroll_profiles_active_cache: Optional[bool] = None


def _organizations_table_exists(conn) -> bool:
    global _organizations_table_cache
    if _organizations_table_cache is not None:
        return _organizations_table_cache
    with _schema_lock:
        if _organizations_table_cache is not None:
            return _organizations_table_cache
        c = conn.cursor()
        c.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'organizations'
            LIMIT 1
            """
        )
        _organizations_table_cache = c.fetchone() is not None
        return _organizations_table_cache


def _organizations_has_logo_url(conn) -> bool:
    global _organizations_logo_col_cache
    if _organizations_logo_col_cache is not None:
        return _organizations_logo_col_cache
    with _schema_lock:
        if _organizations_logo_col_cache is not None:
            return _organizations_logo_col_cache
        c = conn.cursor()
        c.execute("SHOW COLUMNS FROM organizations LIKE 'logo_url'")
        _organizations_logo_col_cache = c.fetchone() is not None
        return _organizations_logo_col_cache


def payroll_profiles_active(conn) -> bool:
    global _payroll_profiles_active_cache
    if _payroll_profiles_active_cache is not None:
        return _payroll_profiles_active_cache
    with _schema_lock:
        if _payroll_profiles_active_cache is not None:
            return _payroll_profiles_active_cache
        c = conn.cursor()
        c.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'payroll_profiles'
            LIMIT 1
            """
        )
        _payroll_profiles_active_cache = c.fetchone() is not None
        return _payroll_profiles_active_cache


def user_has_perm_washpro(conn, washpro_user_id: int, perm_key: str) -> bool:
    """Permission from Washpro roles only (no per-user TA role_id)."""
    c = conn.cursor()
    c.execute(
        """
        SELECT 1 FROM user_roles ur
        JOIN role_permissions rp ON rp.role_id = ur.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE ur.user_id = %s AND p.perm_key = %s
        LIMIT 1
        """,
        (washpro_user_id, perm_key),
    )
    return c.fetchone() is not None


def washpro_bearer_is_platform_operator(conn, bearer_token: str | None) -> bool:
    """True if Bearer token is a valid Washpro session with SUPER_ADMIN or PLATFORM_ADMIN."""
    if not bearer_token:
        return False
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT s.expires_at, s.revoked, r.code
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            JOIN user_roles ur ON ur.user_id = u.id
            JOIN roles r ON r.id = ur.role_id
            WHERE s.token = %s
            """,
            (bearer_token,),
        )
        rows = c.fetchall() or []
        if not rows:
            return False
        if rows[0].get("revoked"):
            return False
        exp = rows[0].get("expires_at")
        if isinstance(exp, datetime) and exp < datetime.utcnow():
            return False
        codes = {str(r.get("code") or "").upper() for r in rows}
        return "SUPER_ADMIN" in codes or "PLATFORM_ADMIN" in codes
    finally:
        try:
            c.close()
        except Exception:
            pass


def _primary_role_for_user(conn, washpro_user_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT r.id, r.code, r.name
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        ORDER BY FIELD(UPPER(r.code), 'ADMIN', 'OPS', 'FRONT_DESK'), r.id
        LIMIT 1
        """,
        (washpro_user_id,),
    )
    return c.fetchone()


def _role_codes_for_user(conn, washpro_user_id: int):
    """All role codes for Washpro user (matches `roles` on /auth/login payload)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT UPPER(r.code) AS code
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        ORDER BY r.code
        """,
        (washpro_user_id,),
    )
    return [str(x["code"]) for x in c.fetchall() if x.get("code")]


def fetch_payroll_profile_row(conn, washpro_user_id: int):
    """Return one row shaped like legacy `ta_users` + role_code for API consumers."""
    c = conn.cursor(dictionary=True)
    if _organizations_table_exists(conn):
        logo_sql = "o.logo_url AS organization_logo_url" if _organizations_has_logo_url(conn) else "NULL AS organization_logo_url"
        c.execute(
            f"""
            SELECT pp.*, u.username, u.display_name AS washpro_display_name, u.active AS washpro_active,
                   u.organization_id,
                   o.slug AS organization_slug,
                   o.display_name AS organization_name,
                   {logo_sql}
            FROM payroll_profiles pp
            JOIN users u ON u.id = pp.user_id
            LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE pp.user_id = %s
            LIMIT 1
            """,
            (washpro_user_id,),
        )
    else:
        c.execute(
            """
            SELECT pp.*, u.username, u.display_name AS washpro_display_name, u.active AS washpro_active,
                   u.organization_id
            FROM payroll_profiles pp
            JOIN users u ON u.id = pp.user_id
            WHERE pp.user_id = %s
            LIMIT 1
            """,
            (washpro_user_id,),
        )
    row = c.fetchone()
    if not row:
        return None
    role = _primary_role_for_user(conn, washpro_user_id)
    out = {k: row[k] for k in row}
    out["id"] = washpro_user_id
    if role:
        out["role_id"] = role["id"]
        out["role_code"] = role["code"]
        out["role_name"] = role["name"]
    out["active"] = bool(row.get("active", 1)) and bool(
        row.get("washpro_active", True)
    )
    out["organization_id"] = int(row.get("organization_id") or 1)
    if "organization_slug" in row:
        out["organization_slug"] = row.get("organization_slug")
    if "organization_name" in row:
        out["organization_name"] = row.get("organization_name")
    if "organization_logo_url" in row:
        out["organization_logo_url"] = row.get("organization_logo_url")
    role_codes = _role_codes_for_user(conn, washpro_user_id)
    if role_codes:
        out["roles"] = role_codes
    return out


def ensure_payroll_profile_for_washpro(conn, wp: dict):
    """Create minimal `payroll_profiles` row for first TA/payroll API use."""
    uid = int(wp["user_id"])
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM payroll_profiles WHERE user_id=%s LIMIT 1", (uid,))
    existing = c.fetchone()
    if existing:
        return fetch_payroll_profile_row(conn, uid)
    username = (wp.get("username") or "user").strip() or "user"
    display = (wp.get("display_name") or username).strip()
    parts = display.split(None, 1)
    first = (parts[0] or username)[:128]
    last = (parts[1] if len(parts) > 1 else "")[:128] or first
    email = f"{username.lower()}.{uid}@washpro.local"
    ph = hash_password("unused-washpro-sso-" + str(uid))
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO payroll_profiles (
              user_id, employee_id, first_name, last_name, email, hire_date,
              active, password_hash
            ) VALUES (%s,%s,%s,%s,%s,CURDATE(),1,%s)
            """,
            (uid, f"WP{uid}", first, last, email, ph),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    return fetch_payroll_profile_row(conn, uid)


def payroll_week_bounds(conn, d: date, organization_id: int = 1):
    """Week interval for payroll using `payroll_period_settings.week_starts_on` (0=Mon..6=Sun)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT week_starts_on FROM payroll_period_settings WHERE organization_id=%s LIMIT 1",
        (int(organization_id),),
    )
    row = c.fetchone()
    anchor = 0
    if row and row.get("week_starts_on") is not None:
        try:
            anchor = int(row["week_starts_on"])
        except (TypeError, ValueError):
            anchor = 0
    delta = (d.weekday() - anchor) % 7
    week_start = d - timedelta(days=delta)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def payroll_cycle_ref(conn, week_start: date, organization_id: int = 1) -> str:
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT ref_prefix FROM payroll_period_settings WHERE organization_id=%s LIMIT 1",
        (int(organization_id),),
    )
    row = c.fetchone() or {}
    prefix = (row.get("ref_prefix") or "PC").strip() or "PC"
    iso = week_start.isocalendar()
    return f"{prefix}-{week_start.year}-W{iso[1]:02d}"


PAYROLL_BUSINESS_TZ = "America/New_York"


def payroll_calendar_date_for_cycle(at: datetime, _organization_id: int = 1) -> date:
    """
    Calendar date used to pick ISO week / payroll cycle. Uses US Eastern so late shifts stay on the
    correct local business day (avoids UTC rollover putting 04/05 work into the next week's cycle).
    Naive `at` values are treated as Eastern wall time (matches eastern_now_naive() storage).
    """
    tz = ZoneInfo(PAYROLL_BUSINESS_TZ)
    if at.tzinfo is None:
        dloc = datetime.combine(at.date(), at.time(), tzinfo=tz)
    else:
        dloc = at.astimezone(tz)
    return dloc.date()


def eastern_now_naive() -> datetime:
    """Store clock times as naive Eastern local wall time for consistent payroll week boundaries."""
    return datetime.now(ZoneInfo(PAYROLL_BUSINESS_TZ)).replace(tzinfo=None)


def get_or_create_payroll_cycle_unified(conn, at: datetime, organization_id: int = 1) -> int:
    d = payroll_calendar_date_for_cycle(at, organization_id)
    oid = int(organization_id)
    if payroll_profiles_active(conn):
        week_start, week_end = payroll_week_bounds(conn, d, oid)
        ref = payroll_cycle_ref(conn, week_start, oid)
    else:
        week_start, week_end = week_bounds_for_date(d)
        ref = cycle_ref_for_week_start(week_start)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT id FROM payroll_cycles WHERE week_start_date=%s AND organization_id=%s",
        (week_start, oid),
    )
    row = c.fetchone()
    if row:
        return row["id"]
    c2 = conn.cursor()
    c2.execute(
        """
        INSERT INTO payroll_cycles (organization_id, cycle_ref, week_start_date, week_end_date, status)
        VALUES (%s,%s,%s,%s,'open')
        """,
        (oid, ref, week_start, week_end),
    )
    return c2.lastrowid


def get_payroll_period_settings(conn, organization_id: int = 1):
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payroll_period_settings WHERE organization_id=%s LIMIT 1",
        (int(organization_id),),
    )
    return c.fetchone()


def set_payroll_period_settings(conn, organization_id: int, week_starts_on: int, ref_prefix: str):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO payroll_period_settings (organization_id, week_starts_on, ref_prefix)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
          week_starts_on = VALUES(week_starts_on),
          ref_prefix = VALUES(ref_prefix)
        """,
        (int(organization_id), int(week_starts_on), (ref_prefix or "PC")[:16]),
    )
