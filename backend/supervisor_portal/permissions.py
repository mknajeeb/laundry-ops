"""Server-side supervisor portal permissions.

Management keeps targets, weights, issue types, training templates, and
score activation. Supervisors get operational actions. Rinse users get a
stripped aggregate only.
"""

from __future__ import annotations

MANAGEMENT_ROLES = frozenset({"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"})
SUPERVISOR_ROLES = MANAGEMENT_ROLES | frozenset({"OPS", "MANAGER"})
RINSE_ROLES = frozenset({"RINSE"})

# Fields a Rinse aggregate is allowed to return. Everything else is dropped.
RINSE_SUMMARY_FIELDS = frozenset(
    {
        "date_et",
        "timezone",
        "volume",
        "approved_productivity",
        "role_performance",
        "quality",
        "field_policy",
    }
)

CONFIDENTIAL_KEYS = frozenset(
    {
        "notes",
        "supervisor_notes",
        "confidential_notes",
        "employees",
        "bags",
        "adjustments",
        "training",
        "wages",
        "pay_rate",
        "employee_name",
        "employee",
    }
)


def role_set(me: dict | None) -> set[str]:
    raw = (me or {}).get("roles") or []
    if isinstance(raw, str):
        raw = [part for part in raw.split(",") if part]
    return {str(role).upper() for role in raw}


def can(roles: set[str] | list[str] | None, action: str) -> bool:
    held = {str(role).upper() for role in (roles or [])}
    management = bool(held & MANAGEMENT_ROLES)
    supervisor = bool(held & SUPERVISOR_ROLES)
    rinse = bool(held & RINSE_ROLES)
    if action == "view_portal":
        return supervisor
    if action == "adjust_session":
        return supervisor
    if action == "assign_quality":
        return supervisor
    if action == "assign_training":
        return supervisor
    if action == "verify_training":
        return supervisor
    if action == "configure_targets":
        return management
    if action == "configure_weights":
        return management
    if action == "configure_issue_types":
        return management
    if action == "configure_training_template":
        return management
    if action == "activate_scoring":
        return False
    if action == "view_rinse_aggregate":
        return rinse or supervisor
    if action == "view_confidential":
        return supervisor
    if action == "view_own_training":
        return True
    return False


def strip_rinse_summary(payload: dict) -> dict:
    """Return the Rinse-safe subset. Employee names and notes never pass."""
    volume = payload.get("volume") if isinstance(payload.get("volume"), dict) else {}
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    role_rows = []
    for row in payload.get("role_performance") or []:
        if not isinstance(row, dict):
            continue
        role_rows.append(
            {
                "role_key": row.get("role_key"),
                "label": row.get("label"),
                "measurable": bool(row.get("measurable")),
                "unit": row.get("unit"),
                "team_average": row.get("team_average"),
                "team_median": row.get("team_median"),
                "target": row.get("target"),
            }
        )
    return {
        "date_et": payload.get("date_et"),
        "timezone": "America/New_York",
        "volume": {
            "completed_bags": volume.get("completed_bags"),
            "approved_bags": volume.get("approved_bags"),
            "approved_pounds": volume.get("approved_pounds"),
            "accounted_bags": volume.get("accounted_bags"),
        },
        "approved_productivity": {
            "unit": "lb/hr",
            "approved_hours": (payload.get("approved_productivity") or {}).get("approved_hours"),
            "approved_lbs_per_hour": (payload.get("approved_productivity") or {}).get(
                "approved_lbs_per_hour"
            ),
            "target_lbs_per_hour": (payload.get("approved_productivity") or {}).get(
                "target_lbs_per_hour"
            ),
        },
        "role_performance": role_rows,
        "quality": {
            "week_start": quality.get("week_start"),
            "incident_count": quality.get("incident_count"),
            "by_type": [
                {"issue_type": row.get("issue_type"), "incidents": row.get("incidents")}
                for row in (quality.get("by_type") or [])
                if isinstance(row, dict)
            ],
        },
        "field_policy": "rinse_aggregate_v1",
    }
