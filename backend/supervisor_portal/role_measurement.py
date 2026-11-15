"""What each operational role can measure today.

Folding uses the approved pounds-per-hour publisher. Other roles stay unscored.
A rate is returned only when eligible time and output were both supplied as
captured facts. Missing hours are not filled in from scans or from zero.
"""

from __future__ import annotations

from typing import Any, Mapping

from backend.supervisor_portal.roles import ROLE_CATALOG, role_public

# Minimum capture still required before a role can be scored.
CAPTURE = {
    "FOLDER": {
        "timestamps": "Eligible folding session start and end, Eastern wall time",
        "output": "Credited pounds on unique completed WF bags",
        "publisher": "rinse_performance_folder_publisher",
        "scoring_ready": True,
        "missing": None,
    },
    "SORT": {
        "timestamps": "Eligible sorting interval, not a shared shift clock",
        "output": "Unique bags sorted by that employee during the interval",
        "publisher": None,
        "scoring_ready": False,
        "missing": "Record the sort interval on the employee's activity, plus the bag count for that interval. Scan chronology alone is not eligible time.",
    },
    "WEIGH": {
        "timestamps": "Eligible weighing interval",
        "output": "Unique bags weighed by that employee during the interval",
        "publisher": None,
        "scoring_ready": False,
        "missing": "Record the weigh interval on the employee's activity. A weigh scan names the bag, not the productive hours.",
    },
    "WASH": {
        "timestamps": "Eligible washer-operator interval",
        "output": "Washer loads completed by that employee during the interval",
        "publisher": None,
        "scoring_ready": False,
        "missing": "Record operator time and load count on the activity. Load counts without an eligible interval are not a rate.",
    },
    "DRY": {
        "timestamps": "Eligible dryer-operator interval",
        "output": "Dryer loads completed by that employee during the interval",
        "publisher": None,
        "scoring_ready": False,
        "missing": "Record operator time and load count on the activity. Load counts without an eligible interval are not a rate.",
    },
    "HD_OPERATOR": {
        "timestamps": "Hang Dry production time on the Hang Dry screen",
        "output": "Hang Dry pieces or bags from that screen",
        "publisher": None,
        "scoring_ready": False,
        "missing": "Keep Hang Dry on its existing production screen until that screen has an approved rate publisher.",
    },
    "HD_FOLDER": {
        "timestamps": "Eligible HD folding interval",
        "output": "HD pounds or pieces folded during the interval",
        "publisher": None,
        "scoring_ready": False,
        "missing": "No approved HD folder pounds-per-hour series exists yet.",
    },
    "GENERAL": {
        "timestamps": None,
        "output": None,
        "publisher": None,
        "scoring_ready": False,
        "missing": "General is not a productivity role.",
    },
}


def role_readiness() -> list[dict[str, Any]]:
    rows = []
    for role in ROLE_CATALOG:
        extra = CAPTURE.get(role["role_key"], {})
        rows.append(
            {
                **role,
                "timestamps": extra.get("timestamps"),
                "output": extra.get("output"),
                "publisher": extra.get("publisher"),
                "scoring_ready": bool(extra.get("scoring_ready")),
                "missing": extra.get("missing"),
            }
        )
    return rows


def measure_captured(role_key: str, record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Divide captured output by captured eligible hours. Never invent either."""
    role = role_public(role_key)
    source = dict(record or {})
    hours = source.get("eligible_hours")
    output = source.get("output_quantity")
    if hours is None or output is None:
        return {
            "role_key": role["role_key"],
            "measurable_now": False,
            "rate": None,
            "unit": role.get("unit"),
            "scoring_ready": False,
            "reason": CAPTURE.get(role["role_key"], {}).get("missing") or role.get("reason"),
        }
    try:
        hours_value = float(hours)
        output_value = float(output)
    except (TypeError, ValueError):
        return {
            "role_key": role["role_key"],
            "measurable_now": False,
            "rate": None,
            "unit": role.get("unit"),
            "scoring_ready": False,
            "reason": "Eligible hours and output must be numbers",
        }
    if hours_value <= 0:
        return {
            "role_key": role["role_key"],
            "measurable_now": False,
            "rate": None,
            "unit": role.get("unit"),
            "scoring_ready": False,
            "reason": "Eligible hours are zero, so no rate is calculated",
        }
    ready = bool(CAPTURE.get(role["role_key"], {}).get("scoring_ready"))
    return {
        "role_key": role["role_key"],
        "measurable_now": True,
        "rate": round(output_value / hours_value, 4),
        "unit": role.get("unit") or "units/hr",
        "output_quantity": output_value,
        "eligible_hours": hours_value,
        "scoring_ready": ready,
        "reason": None if ready else "Captured rate is visible. Target scoring stays off until this role has an approved publisher.",
    }
