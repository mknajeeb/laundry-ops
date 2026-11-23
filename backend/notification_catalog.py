"""Notification events that the application actually sends.

Management categories are assigned to people. Personal and system alerts stay
with the employee the event is about. Scheduling, Performance, and Quality do
not emit a notification event today, so they are not categories here.
"""

from __future__ import annotations

from typing import Any

# Returned when management routing has not been activated for the organization.
# Callers keep their existing recipient rules.
LEGACY_ROUTING = object()


MANAGEMENT_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "module_key": "pin_issues",
        "module_label": "PIN Issues",
        "event_key": "lost_found.item_reported",
        "label": "Issue reported",
        "description": (
            "A Found Item, Missing Item, Re-Dry, or Equipment report was filed. "
            "One category covers those reports because the app sends one event."
        ),
        "kind": "management",
        "targeting": "assignment",
    },
    {
        "module_key": "revenue_cost",
        "module_label": "Revenue & Cost",
        "event_key": "finance.drc.mobile_section.submitted",
        "label": "Section submitted",
        "description": "An employee submitted a mobile Revenue & Cost section for review.",
        "kind": "management",
        "targeting": "assignment",
    },
    {
        "module_key": "maintenance",
        "module_label": "Maintenance",
        "event_key": "maintenance.checklist.submitted",
        "label": "Checklist submitted",
        "description": "An employee submitted the daily maintenance checklist.",
        "kind": "management",
        "targeting": "assignment",
    },
)

AUTOMATIC_NOTIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "module_key": "revenue_cost",
        "module_label": "Revenue & Cost",
        "event_key": "finance.drc.mobile_section.returned",
        "label": "Section returned",
        "kind": "personal",
        "targeting": "The employee who submitted the section. Current delivery still uses that event's audience list.",
    },
    {
        "module_key": "attendance",
        "module_label": "Attendance",
        "event_key": "clock_in_reminder",
        "label": "Clock-in reminder",
        "kind": "personal",
        "targeting": "The employee who is at work and has not clocked in.",
    },
    {
        "module_key": "attendance",
        "module_label": "Attendance",
        "event_key": "geofence_outside",
        "label": "Outside geofence",
        "kind": "personal",
        "targeting": "The clocked-in employee whose phone is outside the geofence.",
    },
    {
        "module_key": "compliance",
        "module_label": "Compliance",
        "event_key": "document_compliance",
        "label": "Document expiring or expired",
        "kind": "system",
        "targeting": "The employee whose document is due. Sent only when that organization's compliance policy allows reminders.",
    },
)

_MANAGEMENT_BY_KEY = {row["event_key"]: row for row in MANAGEMENT_CATEGORIES}


def management_event(event_key: str) -> dict[str, Any] | None:
    return _MANAGEMENT_BY_KEY.get(str(event_key or "").strip())


def is_management_event(event_key: str) -> bool:
    return management_event(event_key) is not None
