"""Preview only: Lily Chen's Sunday Dryer Lint assignments from November 15.

This module does not connect to a database and does not update rows.
November 9, 2026 stays the planning date. November 2 and November 8 stay
on their current roles.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.intra_day_activity_groups import DRYER_LINT_CODE, DRYER_ROLE

TRANSITION_DATE = date(2026, 11, 9)
FIRST_SUNDAY = date(2026, 11, 15)
PROTECTED_DATES = (date(2026, 11, 2), date(2026, 11, 8))


def scheduled_date(row: Mapping[str, Any]) -> date:
    week = row.get("week_start")
    if isinstance(week, str):
        week = date.fromisoformat(week[:10])
    return week + timedelta(days=int(row.get("day_of_week") or 0))


def preview_lily_dryer_lint(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the exact before/after for the eight Sundays. No other row changes."""
    converted = []
    untouched = []
    for row in rows:
        day = scheduled_date(row)
        role = str(row.get("role") or "")
        employee = str(row.get("employee_name") or "")
        eligible = (
            role == DRYER_LINT_CODE
            and employee == "Lily Chen"
            and day >= FIRST_SUNDAY
            and day.weekday() == 6
            and not row.get("has_completion_history")
            and not row.get("has_verification_history")
        )
        entry = {
            "id": row.get("id"),
            "employee_name": employee,
            "scheduled_date": day.isoformat(),
            "scheduled_time": row.get("start_time") or row.get("timing_mode") or "anytime",
            "timing_mode": row.get("timing_mode") or "anytime",
            "before_role": role,
            "completion_history": bool(row.get("has_completion_history")),
            "verification_history": bool(row.get("has_verification_history")),
        }
        if eligible:
            entry["after_role"] = DRYER_ROLE
            entry["action"] = "convert_when_approved"
            converted.append(entry)
        else:
            entry["after_role"] = role
            entry["action"] = "leave"
            untouched.append(entry)
    return {
        "transition_date": TRANSITION_DATE.isoformat(),
        "first_convertible_sunday": FIRST_SUNDAY.isoformat(),
        "protected_dates": [day.isoformat() for day in PROTECTED_DATES],
        "converted": converted,
        "untouched": untouched,
        "rollback": (
            "If the new Dryer Lint Cleaning rows have no activity, delete those rows "
            "and restore the original lint_cleaning rows from this preview. "
            "Completed and verified history stays on the original role."
        ),
    }
