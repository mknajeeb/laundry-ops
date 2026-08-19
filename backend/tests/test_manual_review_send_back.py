"""Manual review resolve + send-back-to-review transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.rinse_manual_review import (
    is_manually_reviewed_active,
    public_manual_review_fields,
    resolve_send_back_reasons,
    stamp_manual_review_resolved,
    stamp_manual_review_sent_back,
)
from backend.rinse_veewash_workload import OUTCOME_COMPLETED, OUTCOME_REVIEW_REQUIRED

ORG = 3
DAY = __import__("datetime").date(2026, 8, 10)
BAG = "MRBAG001"


def test_stamp_resolve_and_send_back_preserves_history():
    snap = {"bag_id": BAG, "outcome": "review_required"}
    snap = stamp_manual_review_resolved(
        snap,
        prior_reason_codes=["WF_ZERO_OR_MISSING_POST_WEIGHT"],
        actor_user_id=7,
        actor_display_name="Manager A",
        at="2026-08-10T12:00:00",
    )
    assert is_manually_reviewed_active(snap) is True
    fields = public_manual_review_fields(snap)
    assert fields["reviewed_by"] == "Manager A"
    assert fields["manual_review_reason_codes"] == ["WF_ZERO_OR_MISSING_POST_WEIGHT"]

    snap = stamp_manual_review_sent_back(
        snap,
        reason_codes=["WF_ZERO_OR_MISSING_POST_WEIGHT"],
        actor_user_id=9,
        actor_display_name="Manager B",
        at="2026-08-10T13:00:00",
    )
    assert is_manually_reviewed_active(snap) is False
    fields = public_manual_review_fields(snap)
    assert fields["sent_back_by"] == "Manager B"
    history = fields["manual_review_history"]
    assert [h["event"] for h in history] == ["resolved", "sent_back"]
    assert history[0]["reason_codes"] == ["WF_ZERO_OR_MISSING_POST_WEIGHT"]


def test_resolve_send_back_reasons_prefers_prior_stamp():
    snap = stamp_manual_review_resolved(
        {},
        prior_reason_codes=["DISAPPEARED_WITHOUT_COMPLETION"],
        actor_display_name="Mgr",
        at="2026-08-10T12:00:00",
    )
    assert resolve_send_back_reasons(
        snap=snap,
        previous_reason_codes=[],
        explicit_reason_code="MANAGER_SENT_FOR_REVIEW",
    ) == ["DISAPPEARED_WITHOUT_COMPLETION"]


def test_move_to_review_from_completed_preserves_completion_and_clears_manual_active():
    from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch

    snap = stamp_manual_review_resolved(
        {
            "bag_id": BAG,
            "outcome": "completed",
            "completion_at": "2026-08-10T11:00:00",
            "completed_by": "Folder One",
        },
        prior_reason_codes=["WF_BULK_WORKITEM_REVIEW"],
        actor_display_name="Manager A",
        at="2026-08-10T12:00:00",
    )
    day_row = {
        "bag_id": BAG,
        "effective_status": "completed",
        "review_reason_codes": [],
        "bag_snapshot": snap,
        "canonical_completion_status": "completed",
        "canonical_completion_timestamp": "2026-08-10T11:00:00",
        "canonical_completion_employee": "Folder One",
        "disposition": "COMPLETED",
        "service_type": "WF",
        "rush_status": "NON_RUSH",
    }
    day_rec = {
        "headline": {
            "segments": {
                "all": {
                    "completed": 1,
                    "pending": 0,
                    "exceptions": {"review_required": 0, "total": 0},
                    "bag_ids": {
                        "completed": [BAG],
                        "pending": [],
                        "review_required": [],
                        "new_today": [BAG],
                        "carryover": [],
                    },
                    "total_workload": 1,
                    "active_workload": 1,
                },
                "wf": {
                    "completed": 1,
                    "pending": 0,
                    "exceptions": {"review_required": 0, "total": 0},
                    "bag_ids": {
                        "completed": [BAG],
                        "pending": [],
                        "review_required": [],
                        "new_today": [BAG],
                        "carryover": [],
                    },
                    "total_workload": 1,
                    "active_workload": 1,
                },
            },
            "exceptions": {"review_required": 0},
            "review_reasons_by_bag": {},
            "review_by_reason": {},
            "completed": 1,
            "completed_count": 1,
            "pending_count": 0,
            "review_required_count": 0,
            "total_workload": 1,
        },
        "workload_meta": {"review_reasons_by_bag": {}},
    }
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=[day_row]
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=day_rec
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={},
    ):
        out = apply_manager_edit_day_bag_patch(
            cursor,
            ORG,
            DAY,
            BAG,
            previous_effective_status="completed",
            previous_reason_codes=[],
            outcome_action="move_to_review",
            actor_user_id=9,
            actor_display_name="Manager B",
        )

    assert out["ok"] is True
    assert out["effective_status"] == OUTCOME_REVIEW_REQUIRED
    assert out["review_reason_codes"] == ["WF_BULK_WORKITEM_REVIEW"]

    update_params = None
    for call in cursor.execute.call_args_list:
        sql = str(call.args[0])
        if "update rinse_shift_monitor_day_bags" in sql.lower():
            update_params = call.args[1]
            break
    assert update_params is not None
    assert update_params[0] == OUTCOME_REVIEW_REQUIRED
    # canonical_completion_status preserved as completed (not review_required)
    assert update_params[2] == OUTCOME_COMPLETED
    # disposition COMPLETED preserved
    assert update_params[8] == "COMPLETED"
    snap_json = update_params[9]
    assert "sent_back" in snap_json
    assert '"active": false' in snap_json or '"active":false' in snap_json


def test_mark_completed_from_review_stamps_manually_reviewed():
    from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch

    day_row = {
        "bag_id": BAG,
        "effective_status": "review_required",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        "bag_snapshot": {"bag_id": BAG, "outcome": "review_required"},
        "canonical_completion_status": "completed",
        "disposition": "COMPLETED",
        "service_type": "WF",
        "rush_status": "RUSH",
    }
    day_rec = {
        "headline": {
            "segments": {
                "all": {
                    "completed": 0,
                    "pending": 0,
                    "exceptions": {"review_required": 1, "total": 1},
                    "bag_ids": {
                        "completed": [],
                        "pending": [],
                        "review_required": [BAG],
                        "new_today": [BAG],
                        "carryover": [],
                    },
                    "total_workload": 1,
                    "active_workload": 1,
                },
            },
            "exceptions": {"review_required": 1},
            "review_reasons_by_bag": {BAG: ["DISAPPEARED_WITHOUT_COMPLETION"]},
            "review_by_reason": {},
            "completed": 0,
            "completed_count": 0,
            "pending_count": 0,
            "review_required_count": 1,
            "total_workload": 1,
        },
        "workload_meta": {"review_reasons_by_bag": {BAG: ["DISAPPEARED_WITHOUT_COMPLETION"]}},
    }
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=[day_row]
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record", return_value=day_rec
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={},
    ):
        out = apply_manager_edit_day_bag_patch(
            cursor,
            ORG,
            DAY,
            BAG,
            previous_effective_status="review_required",
            previous_reason_codes=["DISAPPEARED_WITHOUT_COMPLETION"],
            outcome_action="mark_completed",
            actor_user_id=3,
            actor_display_name="Manager A",
        )

    assert out["ok"] is True
    assert out["effective_status"] == OUTCOME_COMPLETED
    update_params = None
    for call in cursor.execute.call_args_list:
        sql = str(call.args[0])
        if "update rinse_shift_monitor_day_bags" in sql.lower():
            update_params = call.args[1]
            break
    assert update_params is not None
    snap_json = update_params[9]
    assert "Manager A" in snap_json
    assert "DISAPPEARED_WITHOUT_COMPLETION" in snap_json
    assert '"active": true' in snap_json or '"active":true' in snap_json
