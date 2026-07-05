"""WF completed-bag weight must come from post-processing scan events."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_employee_completed_bags import build_employee_completed_bags_today
from backend.rinse_workload_bag_weight import (
    WEIGHT_SOURCE_POST_PROCESSING_SCAN,
    WEIGHT_STATUS_INTEGRITY_FAILURE,
    WEIGHT_STATUS_RESOLVED,
    assert_completed_wf_bags_have_weight,
    attach_portal_weight_to_post_processing_scan,
    finalize_completed_bag_weight_fields,
    resolve_wf_completion_weight_lbs,
)

JUL3 = date(2026, 7, 3)
T0 = datetime(2026, 7, 3, 8, 0)
T1 = datetime(2026, 7, 3, 9, 0)
T2 = datetime(2026, 7, 3, 10, 0)
EMPLOYEE = "Evelin Worker"


def _ev(purpose: str, ts: datetime, *, user_name: str = EMPLOYEE, ev_id: int = 1, weight_lbs: float | None = None) -> dict:
    row = {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": ev_id,
        "user_name": user_name,
        "bag_id": "PLACEHOLDER",
    }
    if weight_lbs is not None:
        row["weight_lbs"] = weight_lbs
    return row


def _wf_events(bag_id: str, post_weight: datetime, *, post_weight_lbs: float | None = None) -> list[dict]:
    events = [
        {**_ev("sent-to-vendor", T0, ev_id=1), "bag_id": bag_id},
        {**_ev("weight-entry", T0, ev_id=2), "bag_id": bag_id},
        {**_ev("add-photos", T1, ev_id=3), "bag_id": bag_id},
        {**_ev("complete-cleaning", T1, ev_id=4), "bag_id": bag_id},
        {**_ev("weight-entry", post_weight, ev_id=5), "bag_id": bag_id},
    ]
    if post_weight_lbs is not None:
        events[-1]["weight_lbs"] = post_weight_lbs
    return events


class TestTraceWfCompletionWeight:
    def test_resolves_from_post_processing_scan_weight_lbs(self):
        events = _wf_events("WF1", T2, post_weight_lbs=18.5)
        lbs, trace = resolve_wf_completion_weight_lbs(
            bag_id="WF1",
            events=events,
            credit_ts=T2,
            anchor_ts=T0,
            as_of_end=T2,
            selected_date_et=JUL3,
        )
        assert lbs == 18.5
        assert trace["completion_event_found"] is True
        assert trace["failure_stage"] is None

    def test_fails_when_scan_has_no_weight_payload(self):
        events = _wf_events("WF1", T2, post_weight_lbs=None)
        lbs, trace = resolve_wf_completion_weight_lbs(
            bag_id="WF1",
            events=events,
            credit_ts=T2,
            anchor_ts=T0,
            as_of_end=T2,
            selected_date_et=JUL3,
            portal_upload_weight=24.8,
        )
        assert lbs is None
        assert trace["failure_stage"] == "scan_missing_weight_payload"
        assert "Events CSV schema" in (trace["failure_detail"] or "")


class TestFinalizeCompletedBagWeight:
    def test_integrity_failure_without_scan_weight(self):
        bag = {"bag_id": "WF1", "completion_signal": "post_processing_weight"}
        row = {"bag_id": "WF1", "service_type": "WF"}
        events = _wf_events("WF1", T2)
        finalize_completed_bag_weight_fields(
            bag,
            row,
            {},
            events=events,
            selected_date_et=JUL3,
            as_of_end=T2,
            portal_upload_weight=None,
            credit_ts=T2,
            repair_scan_from_portal=False,
        )
        assert bag["weight_status"] == WEIGHT_STATUS_INTEGRITY_FAILURE
        assert bag["weight_lbs"] is None
        assert bag["completion_signal"] == "post_processing_weight"

    def test_resolved_from_scan_weight(self):
        bag = {"bag_id": "WF1"}
        row = {"bag_id": "WF1", "service_type": "WF"}
        events = _wf_events("WF1", T2, post_weight_lbs=22.0)
        finalize_completed_bag_weight_fields(
            bag,
            row,
            {},
            events=events,
            selected_date_et=JUL3,
            as_of_end=T2,
            credit_ts=T2,
            repair_scan_from_portal=False,
        )
        assert bag["weight_lbs"] == 22.0
        assert bag["weight_source"] == WEIGHT_SOURCE_POST_PROCESSING_SCAN
        assert bag["weight_status"] == WEIGHT_STATUS_RESOLVED


class _FakeCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class TestEmployeeProductivityWeightIntegrity:
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps", return_value={EMPLOYEE.casefold(): {"user_id": 1, "display_name": EMPLOYEE}})
    @patch("backend.rinse_processing_productivity._load_shift_sessions_bulk", return_value={})
    @patch("backend.daily_shift_roster.list_roster_entries", return_value=[])
    @patch("backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk", return_value={})
    @patch("backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk", return_value={})
    @patch("backend.rinse_workload_bag_weight.load_portal_upload_weights_for_bags", return_value={"WF1": 11.0})
    @patch("backend.rinse_workload_bag_weight.attach_portal_weight_to_post_processing_scan", return_value={"updated": True})
    def test_section_weight_integrity_ok_with_scan_weight(self, *_mocks):
        row = {
            "bag_id": "WF1",
            "service_type": "WF",
            "at_vendor_status": "Completed",
            "completion_time": T2.isoformat(),
        }
        events = {"WF1": _wf_events("WF1", T2, post_weight_lbs=11.0)}
        section = build_employee_completed_bags_today(
            _FakeCursor(),
            3,
            completed_rows=[row],
            workload_rows=[row],
            events_by_bag=events,
            selected_date_et=JUL3,
            registry_meta_by_bag={},
        )
        assert section["weight_integrity_ok"] is True

    def test_assert_fails_when_scan_weight_missing(self):
        bag = {
            "bag_id": "WF9",
            "service_type": "WF",
            "weight_lbs": None,
            "weight_integrity_failure": {"failure_stage": "scan_missing_weight_payload"},
        }
        violations = assert_completed_wf_bags_have_weight([bag])
        assert len(violations) == 1
