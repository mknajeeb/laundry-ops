"""Role measurability and primary-role history.

Only Folding has a validated pounds-per-hour publisher today. Other roles stay
visible and unscored. A primary-role change is effective-dated and does not
rewrite stored performance.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

ROLE_CATALOG = (
    {
        "role_key": "FOLDER",
        "label": "Folding",
        "unit": "lb/hr",
        "measurable": True,
        "reason": None,
    },
    {
        "role_key": "SORT",
        "label": "Sorting",
        "unit": "bags/hr",
        "measurable": False,
        "reason": "No validated bags-per-hour time and output series",
    },
    {
        "role_key": "WEIGH",
        "label": "Weighing",
        "unit": "bags/hr",
        "measurable": False,
        "reason": "No validated bags-per-hour time and output series",
    },
    {
        "role_key": "WASH",
        "label": "Washing",
        "unit": None,
        "measurable": False,
        "reason": "No validated output and time series",
    },
    {
        "role_key": "DRY",
        "label": "Drying",
        "unit": None,
        "measurable": False,
        "reason": "No validated output and time series",
    },
    {
        "role_key": "HD_OPERATOR",
        "label": "HD Operator",
        "unit": None,
        "measurable": False,
        "reason": "Hang Dry performance stays on its existing screen and is not scored here",
    },
    {
        "role_key": "HD_FOLDER",
        "label": "HD Folder",
        "unit": None,
        "measurable": False,
        "reason": "No validated HD folder rate publisher",
    },
    {
        "role_key": "GENERAL",
        "label": "General / multiple roles",
        "unit": None,
        "measurable": False,
        "reason": "Not a productivity role",
    },
)

_BY_KEY = {row["role_key"]: row for row in ROLE_CATALOG}


def role_public(role_key: str | None) -> dict[str, Any]:
    key = str(role_key or "GENERAL").strip().upper() or "GENERAL"
    row = _BY_KEY.get(key)
    if not row:
        return {
            "role_key": key,
            "label": key,
            "unit": None,
            "measurable": False,
            "reason": "Role is not in the measurable catalog",
        }
    return dict(row)


def primary_role_on(history: Sequence[Mapping[str, Any]], day: date) -> dict[str, Any] | None:
    """Effective-dated primary role. Later rows do not change earlier days."""
    chosen = None
    for row in history or []:
        start = row.get("effective_from")
        end = row.get("effective_to")
        if isinstance(start, str):
            start = date.fromisoformat(start[:10])
        if isinstance(end, str):
            end = date.fromisoformat(end[:10])
        if not isinstance(start, date) or start > day:
            continue
        if isinstance(end, date) and end < day:
            continue
        if chosen is None or start >= chosen[0]:
            chosen = (start, row)
    if chosen is None:
        return None
    return dict(chosen[1])
