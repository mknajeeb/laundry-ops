"""Portal login accounts that are not payroll workers (Rinse schedule viewer, etc.)."""

from __future__ import annotations

from typing import Optional, Sequence

PORTAL_SYSTEM_ONLY_ROLES = frozenset({"RINSE", "SYSTEM"})

# Roles that must not appear on the shared kiosk "Currently at work" board.
KIOSK_AT_WORK_EXCLUDED_ROLES = frozenset(
    {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN", "ACCOUNTANT", "RINSE", "SYSTEM"}
)

# Known non-floor system accounts (org3 VeeWash / Alliance).
KNOWN_SYSTEM_USER_IDS = frozenset({15})
KNOWN_SYSTEM_DISPLAY_NAMES = frozenset(
    {
        "alliance business consultant",
        "new veewash admin",
    }
)

SYSTEM_EMPLOYMENT_CATEGORY_CODES = frozenset({"EC_SYSTEM"})


def normalized_role_codes(role_codes: Sequence[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in role_codes or []:
        if raw is None:
            continue
        for part in str(raw).split(","):
            code = part.strip().upper()
            if code:
                out.add(code)
    return out


def is_portal_system_only_user(role_codes: Sequence[str] | None) -> bool:
    """True when the login exists only for an external/partner portal role (not payroll)."""
    codes = normalized_role_codes(role_codes)
    if not codes:
        return False
    if codes - PORTAL_SYSTEM_ONLY_ROLES:
        return False
    return bool(codes & PORTAL_SYSTEM_ONLY_ROLES)


def fetch_user_role_codes(conn, user_id: int) -> list[str]:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT r.code
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        ORDER BY r.code
        """,
        (int(user_id),),
    )
    rows = c.fetchall()
    if not isinstance(rows, (list, tuple)):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        if code:
            out.append(str(code).upper())
    return out


def user_has_system_role_flag(conn, user_id: int) -> bool:
    """True if the user is assigned any role marked is_system in the roles table."""
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT 1 AS ok
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = %s AND COALESCE(r.is_system, 0) = 1
            LIMIT 1
            """,
            (int(user_id),),
        )
    except Exception:
        return False
    row = c.fetchone()
    if not row or not isinstance(row, (dict, tuple, list)):
        return False
    return True


def user_has_system_employment_category(conn, user_id: int) -> bool:
    """True when People category is System user (not on payroll)."""
    c = conn.cursor(dictionary=True)
    try:
        codes = sorted(SYSTEM_EMPLOYMENT_CATEGORY_CODES)
        placeholders = ",".join(["%s"] * len(codes))
        c.execute(
            f"""
            SELECT 1 AS ok
            FROM user_employment_categories uec
            JOIN employment_categories ec ON ec.id = uec.employment_category_id
            WHERE uec.user_id = %s
              AND UPPER(TRIM(ec.code)) IN ({placeholders})
              AND uec.effective_from <= CURDATE()
              AND (uec.effective_to IS NULL OR uec.effective_to >= CURDATE())
            LIMIT 1
            """,
            (int(user_id), *codes),
        )
    except Exception:
        return False
    row = c.fetchone()
    return bool(row)


def is_portal_system_user(conn, user_id: int) -> bool:
    """True for portal-only roles or People 'System user (not on payroll)' category."""
    if is_portal_system_only_user(fetch_user_role_codes(conn, int(user_id))):
        return True
    return user_has_system_employment_category(conn, int(user_id))


def _normalize_display_name(name: Optional[str]) -> str:
    return " ".join(str(name or "").strip().lower().split())


def is_excluded_from_kiosk_at_work(
    conn,
    user_id: int,
    *,
    display_name: Optional[str] = None,
) -> bool:
    """True for system/admin/portal accounts that must not appear on the kiosk presence board."""
    uid = int(user_id)
    if uid in KNOWN_SYSTEM_USER_IDS:
        return True
    label = _normalize_display_name(display_name)
    if label and label in KNOWN_SYSTEM_DISPLAY_NAMES:
        return True
    if user_has_system_role_flag(conn, uid):
        return True
    if user_has_system_employment_category(conn, uid):
        return True
    codes = set(fetch_user_role_codes(conn, uid))
    if codes & KIOSK_AT_WORK_EXCLUDED_ROLES:
        return True
    return False


def ensure_system_role(cursor) -> int:
    """Ensure a built-in SYSTEM role exists for non-payroll portal/People accounts."""
    cursor.execute(
        """
        SELECT id FROM roles
        WHERE UPPER(TRIM(code)) = 'SYSTEM'
        ORDER BY (CASE WHEN organization_id = 0 OR organization_id IS NULL THEN 0 ELSE 1 END), id
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])
    cursor.execute(
        """
        INSERT INTO roles (code, name, organization_id, is_system)
        VALUES ('SYSTEM', 'System user (not on payroll)', 0, 1)
        """
    )
    return int(cursor.lastrowid)


def ensure_system_employment_category(cursor, organization_id: int) -> int:
    """Ensure EC_SYSTEM exists for the org; return its id."""
    from backend.hr_workspace_schema import seed_worker_categories_if_missing

    oid = int(organization_id)
    seed_worker_categories_if_missing(cursor, oid)
    cursor.execute(
        """
        SELECT id FROM employment_categories
        WHERE organization_id=%s AND UPPER(TRIM(code))='EC_SYSTEM'
        LIMIT 1
        """,
        (oid,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"EC_SYSTEM category missing for organization_id={oid}")
    return int(row["id"] if isinstance(row, dict) else row[0])


def assign_system_employment_category(cursor, user_id: int, organization_id: int) -> int:
    """Replace employment categories with EC_SYSTEM for this user."""
    cat_id = ensure_system_employment_category(cursor, organization_id)
    uid = int(user_id)
    cursor.execute("DELETE FROM user_employment_categories WHERE user_id=%s", (uid,))
    cursor.execute(
        """
        INSERT INTO user_employment_categories
          (user_id, employment_category_id, effective_from, effective_to)
        VALUES (%s, %s, CURDATE(), NULL)
        """,
        (uid, int(cat_id)),
    )
    return int(cat_id)


def strip_payroll_schedule_rows(cursor, user_id: int) -> None:
    """Remove scheduling/payroll worker rows while keeping People profile contact fields."""
    uid = int(user_id)
    cursor.execute("DELETE FROM payroll_worker_profiles WHERE user_id=%s", (uid,))


def convert_user_to_system_only(
    cursor,
    *,
    user_id: int,
    organization_id: int,
    keep_profile: bool = True,
) -> dict:
    """Mark a login as system-only: SYSTEM role, EC_SYSTEM category, no schedule worker row."""
    uid = int(user_id)
    oid = int(organization_id)
    role_id = ensure_system_role(cursor)
    cursor.execute("DELETE FROM user_roles WHERE user_id=%s", (uid,))
    cursor.execute(
        "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
        (uid, int(role_id)),
    )
    cat_id = assign_system_employment_category(cursor, uid, oid)
    strip_payroll_schedule_rows(cursor, uid)
    if not keep_profile:
        cursor.execute("DELETE FROM payroll_profiles WHERE user_id=%s", (uid,))
    return {
        "user_id": uid,
        "organization_id": oid,
        "role_id": int(role_id),
        "employment_category_id": int(cat_id),
        "kept_payroll_profile": bool(keep_profile),
    }
