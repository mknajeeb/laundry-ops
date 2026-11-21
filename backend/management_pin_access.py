"""Shared gate: Management hub roles OR employee Mobile PIN Access (revenue_cost).

PIN employees use the same Management Revenue / Hang Dry APIs and tables as
managers. They must not get a parallel write path.
"""

from __future__ import annotations

from typing import Any

from backend.employee_mobile_pin_access import employee_allows_module

HUB_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})

# Floor supervisors use these role codes. They are not ordinary employee roles.
PIN_MANAGEMENT_ROLES = HUB_ROLES | frozenset(
    {"SUPERVISOR", "OPERATIONS", "PAYROLL_ADMIN", "FINANCE"}
)
# A role named "Shift Supervisor" still counts. Desk, checkout, rinse, and
# accountant roles do not become management roles because of a shared word.
_MANAGEMENT_ROLE_WORDS = frozenset({"SUPERVISOR", "OPERATIONS", "MANAGER"})

# Supervisor/admin PIN modules. Ordinary employee tiles stay outside this set.
PIN_MANAGEMENT_MODULES = frozenset(
    {"issues", "scan_chronology", "payroll", "ops_dashboard"}
)


def holds_pin_management_role(roles) -> bool:
    if isinstance(roles, str):
        roles = [part for part in roles.split(",") if part.strip()]
    tokens = set()
    for role in roles or []:
        token = str(role or "").upper().replace("-", " ").strip()
        if token:
            tokens.add(token)
    if tokens & PIN_MANAGEMENT_ROLES:
        return True
    for token in tokens:
        words = [part for part in token.replace("_", " ").split() if part]
        if any(word in _MANAGEMENT_ROLE_WORDS for word in words):
            return True
        if words in (["ADMIN"], ["OPS"]):
            return True
    return False


def user_holds_pin_management_role(cursor, user_id: int) -> bool:
    cursor.execute(
        """
        SELECT r.code, r.name
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        """,
        (int(user_id),),
    )
    labels = []
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            labels.extend([row.get("code"), row.get("name")])
        else:
            labels.append(row[0] if row else None)
    return holds_pin_management_role(labels)


def may_use_pin_management(cursor, organization_id: int, user_id: int, roles) -> bool:
    """Management PIN modules follow the assigned role or the Task Review grant.

    Task Review is the existing supervisor PIN permission. Ordinary employees
    without that grant, and without a management role, stay on the floor menu.
    """
    if holds_pin_management_role(roles):
        return True
    try:
        oid = int(organization_id)
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if oid <= 0 or uid <= 0:
        return False
    return employee_allows_module(cursor, oid, uid, "cleaning_task_review")


def user_may_use_pin_management(cursor, user_id: int) -> bool:
    if user_holds_pin_management_role(cursor, user_id):
        return True
    cursor.execute(
        "SELECT organization_id FROM users WHERE id=%s",
        (int(user_id),),
    )
    row = cursor.fetchone()
    organization_id = row.get("organization_id") if isinstance(row, dict) else (row[0] if row else None)
    if not organization_id:
        return False
    return employee_allows_module(cursor, int(organization_id), int(user_id), "cleaning_task_review")


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
