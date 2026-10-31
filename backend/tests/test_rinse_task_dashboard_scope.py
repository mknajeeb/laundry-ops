"""Rinse Task Dashboard responses must strip labor/duration fields at the API layer."""

from __future__ import annotations

from backend.cleaning_task_activity import apply_rinse_task_dashboard_scope


def test_rinse_dashboard_scope_strips_durations_and_time_on_tasks():
    payload = {
        "metrics": {
            "total_assigned": 3,
            "completed": 2,
            "overdue": 0,
            "time_spent_seconds": 900,
            "completion_rate": 66.7,
        },
        "durations": [
            {"employee_id": 1, "duration_seconds": 120, "role": "floor_cleaning"},
        ],
        "shared_assignments": [
            {
                "role": "floor_cleaning",
                "status": "pending",
                "completion_status": "in_progress",
                "verification_status": "not_required",
                "has_manual_completion": False,
                "contributions": [
                    {
                        "employee_name": "Amna",
                        "status": "in_progress",
                        "group_duration_seconds": 300,
                        "activity": {
                            "id": 9,
                            "duration_seconds": 300,
                            "status": "in_progress",
                            "completion_source": "pin",
                            "times_manual": 0,
                            "manual_reason": "secret",
                        },
                    }
                ],
            }
        ],
        "activity_log": [
            {"id": 1, "duration_seconds": 45, "status": "approved", "employee_name": "Amna"},
        ],
        "queue": {"overdue": [{"duration_seconds": 10}]},
        "shift_end": {"blocking_close": [{"duration_seconds": 11}]},
        "checklists": [
            {
                "checklist_name": "EOD",
                "groups": [{"group_name": "Floor", "items": [{"task_code": "x", "duration_seconds": 9}]}],
            }
        ],
    }
    out = apply_rinse_task_dashboard_scope(payload)
    assert "time_spent_seconds" not in out["metrics"]
    assert out["metrics"]["total_assigned"] == 1
    assert out["durations"] == []
    assert out["activity_log"] == []
    assert "queue" not in out
    assert "duration_seconds" not in out["shared_assignments"][0]["contributions"][0]
    assert "group_duration_seconds" not in out["shared_assignments"][0]["contributions"][0]
    assert "duration_seconds" not in out["shared_assignments"][0]["contributions"][0]["activity"]
    assert "manual_reason" not in out["shared_assignments"][0]["contributions"][0]["activity"]
    assert "duration_seconds" not in out["shift_end"]["blocking_close"][0]
    assert "duration_seconds" not in out["checklists"][0]["groups"][0]["items"][0]
    assert out["hide_labor_metrics"] is True
    assert out["labor_fields_hidden"] is True
    assert out["read_only"] is True
    assert out["rinse_scope"]["pin_original_only"] is True
