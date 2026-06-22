"""Portal login accounts that are not payroll workers (Rinse schedule viewer, etc.)."""

from __future__ import annotations

from typing import Sequence

PORTAL_SYSTEM_ONLY_ROLES = frozenset({"RINSE"})


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
    return [str(row.get("code") or "").upper() for row in (c.fetchall() or []) if row.get("code")]


def is_portal_system_user(conn, user_id: int) -> bool:
    return is_portal_system_only_user(fetch_user_role_codes(conn, int(user_id)))
