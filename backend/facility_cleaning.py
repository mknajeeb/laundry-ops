"""Facility Cleaning tasks inside the existing task catalog.

These are ordinary task definitions. Recurrence, timers, checklists, shared
activity groups, and verification stay on the task system they already use.
"""

from __future__ import annotations

from backend.task_catalog import (
    COMPLETION_INPUT,
    COMPLETION_SIMPLE,
    VERIFY_SUPERVISOR,
    get_task_definition,
    seed_builtin_categories,
    upsert_category,
    upsert_task_definition,
)

CATEGORY_CODE = "facility_cleaning"

FACILITY_TASKS = (
    {
        "code": "washer_deep_cleaning",
        "name": "Washer Deep Cleaning",
        "completion_type": COMPLETION_INPUT,
        "input_schema": [
            {
                "id": "washer_machines",
                "label": "Washers cleaned",
                "type": "machine_numbers",
                "machine_kind": "washer",
                "required": True,
            }
        ],
    },
    {
        "code": "dryer_deep_cleaning",
        "name": "Dryer Deep Cleaning",
        "completion_type": COMPLETION_INPUT,
        "input_schema": [
            {
                "id": "dryer_machines",
                "label": "Dryers cleaned",
                "type": "machine_numbers",
                "machine_kind": "dryer",
                "required": True,
            }
        ],
    },
    {"code": "bathroom_cleaning", "name": "Bathroom Cleaning", "completion_type": COMPLETION_SIMPLE},
    {"code": "facility_mopping", "name": "Facility Mopping", "completion_type": COMPLETION_SIMPLE},
    {"code": "parking_area_sweeping", "name": "Parking Area Sweeping", "completion_type": COMPLETION_SIMPLE},
    {"code": "water_pit_cleaning", "name": "Water Pit Cleaning", "completion_type": COMPLETION_SIMPLE},
)


def ensure_facility_cleaning(cursor, organization_id: int) -> None:
    """Create the group and tasks once. An existing task keeps its recurrence and checklist."""
    seed_builtin_categories(cursor, int(organization_id))
    upsert_category(
        cursor,
        int(organization_id),
        {"code": CATEGORY_CODE, "name": "Facility Cleaning", "display_order": 25, "active": True},
    )
    for index, spec in enumerate(FACILITY_TASKS):
        if get_task_definition(cursor, int(organization_id), f"custom_{spec['code']}"):
            continue
        if get_task_definition(cursor, int(organization_id), spec["code"]):
            continue
        upsert_task_definition(
            cursor,
            int(organization_id),
            spec["code"],
            {
                "name": spec["name"],
                "category_code": CATEGORY_CODE,
                "completion_type": spec["completion_type"],
                "input_schema": spec.get("input_schema") or [],
                "timer_enabled": True,
                "verification_required": True,
                "verification_method": VERIFY_SUPERVISOR,
                "verification_inherits": False,
                "active": True,
                "display_order": (index + 1) * 10,
                "recurrence": {
                    "mode": "manual",
                    "weekly_frequency": 1,
                    "weekdays": [],
                    "active": True,
                    "paused": False,
                },
            },
        )
