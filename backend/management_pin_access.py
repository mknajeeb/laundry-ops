"""Shared gate: Management hub roles OR employee Mobile PIN Access (revenue_cost).

PIN employees use the same Management Revenue / Hang Dry APIs and tables as
managers. They must not get a parallel write path.
"""

from __future__ import annotations

from typing import Any

from backend.employee_mobile_pin_access import employee_allows_module

HUB_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})

# Floor supervisors use these role codes. They are not ordinary employee roles.
PIN_MANAGEMENT_ROLES = HUB_ROLES | frozenset({"SUPERVISOR", "OPERATIONS"})

# Supervisor/admin PIN modules. Ordinary employee tiles stay outside this set.
PIN_MANAGEMENT_MODULES = frozenset(
    {"issues", "scan_chronology", "payroll", "ops_dashboard"}
)


def holds_pin_management_role(roles) -> bool:
    if isinstance(roles, str):
        roles = [part for part in roles.split(",") if part.strip()]
    return bool({str(role).upper() for role in (roles or [])} & PIN_MANAGEMENT_ROLES)


def user_holds_pin_management_role(cursor, user_id: int) -> bool:
    cursor.execute(
        """
        SELECT r.code
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        """,
        (int(user_id),),
    )
    codes = []
    for row in cursor.fetchall() or []:
        code = row.get("code") if isinstance(row, dict) else row[0]
        if code:
            codes.append(code)
    return holds_pin_management_role(codes)


def is_pin_management_module(module: str | None) -> bool:
    return str(module or "").strip().lower() in PIN_MANAGEMENT_MODULES


def role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def actor_name(me: dict) -> str | None:
    for key in ("display_name", "name", "full_name", "username", "email"):
        val = me.get(key)
        if val:
            return str(val)
    return None


def is_hub_manager(me: dict) -> bool:
    return bool(role_set(me) & HUB_ROLES)


def allows_management_revenue_pin(
    cursor,
    me: dict,
    *,
    org_id: int,
) -> bool:
    """True when caller may use Management Revenue / Hang Dry entry APIs."""
    if is_hub_manager(me):
        return True
    try:
        uid = int(me.get("user_id") or 0)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    return bool(employee_allows_module(cursor, int(org_id), uid, "revenue_cost"))


def access_denied_payload() -> tuple[dict[str, Any], int]:
    return {"error": "Forbidden"}, 403
