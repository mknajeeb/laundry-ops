"""Regression: current-day completed workload weight from portal upload + registry rules."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from backend.rinse_employee_completed_bags import (
    _enrich_credited_bag_weights,
    build_employee_completed_bags_today,
)
from backend.rinse_employee_workload_productivity import (
    credit_workload_bags,
    resolve_workload_bag_credit,
)
from backend.rinse_workload_bag_weight import (
    POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL,
    POST_PROCESSING_WEIGHT_SIGNAL,
    WEIGHT_STATUS_MISSING,
    WEIGHT_STATUS_RESOLVED,
    finalize_completed_bag_weight_fields,
    registry_weight_for_selected_day,
    resolve_current_completed_workload_weight_lbs,
)

JUL3 = date(2026, 7, 3)
JUN28 = date(2026, 6, 28)
T2 = datetime(2026, 7, 3, 10, 0)
EMPLOYEE = "Evelin Worker"


def _registry_ctx(*, weight: float, completed_at: datetime | None, date_clean: date | None) -> dict:
    return {
        "weight_num": weight,
        "completed_at": completed_at,
        "date_clean": date_clean,
        "completion_status": "COMPLETED",
    }


class TestResolveCurrentCompletedWorkloadWeight:
    def test_portal_upload_weight_when_registry_null(self):
        row = {"bag_id": "BAG1", "post_clean_weight": None}
        lbs, source = resolve_current_completed_workload_weight_lbs(
            row,
            {},
            selected_date_et=JUL3,
            portal_upload_weight=24.8,
            registry_context={"weight_num": None, "completion_status": "INCOMPLETE"},
        )
        assert lbs == 24.8
        assert source == "portal_upload_weight"

    def test_portal_upload_overrides_stale_registry(self):
        row = {"bag_id": "8UIXS2OC6W"}
        stale = _registry_ctx(
            weight=14.0,
            completed_at=datetime(2026, 6, 28, 15, 0),
            date_clean=JUN28,
        )
        lbs, source = resolve_current_completed_workload_weight_lbs(
            row,
            {"weight_num": 14.0},
            selected_date_et=JUL3,
            portal_upload_weight=8.6,
            registry_context=stale,
        )
        assert lbs == 8.6
        assert source == "portal_upload_weight"

    def test_registry_weight_only_when_same_completion_day(self):
        same_day = _registry_ctx(
            weight=12.5,
            completed_at=datetime(2026, 7, 3, 11, 0),
            date_clean=JUL3,
        )
        lbs, source = resolve_current_completed_workload_weight_lbs(
            {"bag_id": "BAG2"},
            {"weight_num": 12.5},
            selected_date_et=JUL3,
            portal_upload_weight=None,
            registry_context=same_day,
        )
        assert lbs == 12.5
        assert source == "registry_same_day_weight"

        stale = _registry_ctx(
            weight=14.0,
            completed_at=datetime(2026, 6, 28, 15, 0),
            date_clean=JUN28,
        )
        lbs2, source2 = resolve_current_completed_workload_weight_lbs(
            {"bag_id": "BAG2"},
            {"weight_num": 14.0},
            selected_date_et=JUL3,
            portal_upload_weight=None,
            registry_context=stale,
        )
        assert lbs2 is None
        assert source2 is None

    def test_registry_same_day_via_date_clean_only(self):
        ctx = {
            "weight_num": 9.25,
            "completed_at": None,
            "date_clean": JUL3,
            "completion_status": "INCOMPLETE",
        }
        assert registry_weight_for_selected_day(ctx, selected_date_et=JUL3) == 9.25

    def test_registry_before_portal_when_same_day(self):
        row = {"bag_id": "BAG3"}
        same_day = _registry_ctx(
            weight=11.0,
            completed_at=None,
            date_clean=JUL3,
        )
        lbs, source = resolve_current_completed_workload_weight_lbs(
            row,
            {},
            selected_date_et=JUL3,
            portal_upload_weight=20.0,
            registry_context=same_day,
        )
        assert lbs == 11.0
        assert source == "registry_same_day_weight"


class TestFinalizeCompletedBagWeightFields:
    def test_signal_not_post_processing_weight_when_weight_missing(self):
        bag = {
            "bag_id": "WF1",
            "completion_signal": POST_PROCESSING_WEIGHT_SIGNAL,
            "processed_signal": POST_PROCESSING_WEIGHT_SIGNAL,
            "credit_event_type": POST_PROCESSING_WEIGHT_SIGNAL,
        }
        row = {"bag_id": "WF1", "service_type": "WF"}
        finalize_completed_bag_weight_fields(
            bag,
            row,
            {},
            events=_wf_events("WF1"),
            selected_date_et=JUL3,
            as_of_end=T2,
            portal_upload_weight=None,
            registry_context=_registry_ctx(
                weight=14.0,
                completed_at=datetime(2026, 6, 28, 15, 0),
                date_clean=JUN28,
            ),
        )
        assert bag["weight_status"] == WEIGHT_STATUS_MISSING
        assert bag["weight_lbs"] is None
        assert bag["completion_signal"] == POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL
        assert bag["processed_signal"] == POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL
        assert bag["credit_event_type"] == POST_PROCESSING_WEIGHT_SIGNAL
        assert bag.get("weight_debug_reason")

    def test_resolved_weight_sets_api_fields(self):
        bag = {"bag_id": "WF2", "completion_signal": POST_PROCESSING_WEIGHT_SIGNAL}
        row = {"bag_id": "WF2", "service_type": "WF"}
        finalize_completed_bag_weight_fields(
            bag,
            row,
            {},
            events=[],
            selected_date_et=JUL3,
            as_of_end=T2,
            portal_upload_weight=18.4,
            registry_context={},
        )
        assert bag["weight_lbs"] == 18.4
        assert bag["weight_status"] == WEIGHT_STATUS_RESOLVED
        assert bag["weight_source"] == "portal_upload_weight"
        assert bag["completed_lbs"] == 18.4


class _PortalWeightCursor:
    """Minimal cursor stub for enrich tests."""

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def _workload_row(bag_id: str, *, weight: float | None = None) -> dict:
    return {
        "bag_id": bag_id,
        "service_type": "WF",
        "service_bucket": "WF",
        "at_vendor_status": "Completed",
        "completion_time": T2.isoformat(),
        "post_clean_weight": weight,
        "rush_bucket": "non_rush",
    }


def _wf_events(bag_id: str) -> list[dict]:
    t0 = datetime(2026, 7, 3, 8, 0)
    t1 = datetime(2026, 7, 3, 9, 0)
    return [
        {"purpose": "sent-to-vendor", "scanned_at_parsed": t0, "user_name": EMPLOYEE, "bag_id": bag_id, "id": 1},
        {"purpose": "weight-entry", "scanned_at_parsed": t0, "user_name": EMPLOYEE, "bag_id": bag_id, "id": 2},
        {"purpose": "add-photos", "scanned_at_parsed": t1, "user_name": EMPLOYEE, "bag_id": bag_id, "id": 3},
        {"purpose": "complete-cleaning", "scanned_at_parsed": t1, "user_name": EMPLOYEE, "bag_id": bag_id, "id": 4},
        {"purpose": "weight-entry", "scanned_at_parsed": T2, "user_name": EMPLOYEE, "bag_id": bag_id, "id": 5},
    ]


class TestEmployeeProductivityWeightEnrichment:
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps", return_value={EMPLOYEE.casefold(): {"user_id": 1, "display_name": EMPLOYEE}})
    @patch("backend.rinse_processing_productivity._load_shift_sessions_bulk", return_value={})
    @patch("backend.daily_shift_roster.list_roster_entries", return_value=[])
    @patch("backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk", return_value={})
    @patch("backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk", return_value={})
    @patch(
        "backend.rinse_workload_bag_weight.load_portal_upload_weights_for_bags",
        return_value={"WF1": 18.0, "WF2": 22.0, "WF3": 9.5},
    )
    @patch("backend.rinse_workload_bag_weight.load_registry_weight_context_for_bags", return_value={})
    @patch("backend.rinse_workload_bag_weight.sync_registry_weight_for_workload_day", return_value=True)
    def test_completed_lbs_equals_sum_of_displayed_weights(self, *_mocks):
        rows = [
            _workload_row("WF1", weight=None),
            _workload_row("WF2", weight=None),
            _workload_row("WF3", weight=None),
        ]
        events = {r["bag_id"]: _wf_events(r["bag_id"]) for r in rows}
        section = build_employee_completed_bags_today(
            _PortalWeightCursor(),
            3,
            completed_rows=rows,
            workload_rows=rows,
            events_by_bag=events,
            selected_date_et=JUL3,
            registry_meta_by_bag={},
        )
        alice = next(e for e in section["employees"] if e["employee"] == EMPLOYEE)
        displayed = [b["completed_lbs"] for b in alice["bags"]]
        assert displayed == [18.0, 22.0, 9.5]
        assert alice["total_completed_lbs"] == pytest.approx(49.5)
        assert all(not b.get("weight_missing") for b in alice["bags"])

    @patch(
        "backend.rinse_workload_bag_weight.load_portal_upload_weights_for_bags",
        return_value={"8UIXS2OC6W": 8.6},
    )
    @patch(
        "backend.rinse_workload_bag_weight.load_registry_weight_context_for_bags",
        return_value={
            "8UIXS2OC6W": _registry_ctx(
                weight=14.0,
                completed_at=datetime(2026, 6, 28, 15, 0),
                date_clean=JUN28,
            )
        },
    )
    def test_jul3_style_no_missing_when_portal_upload_exists(self, *_mocks):
        row = _workload_row("8UIXS2OC6W", weight=None)
        credited = [
            resolve_workload_bag_credit(
                row,
                events=_wf_events("8UIXS2OC6W"),
                selected_date_et=JUL3,
                as_of_end=T2,
                registry_meta={"8UIXS2OC6W": {"weight_num": 14.0}},
            )
        ]
        _enrich_credited_bag_weights(
            credited,
            cursor=_PortalWeightCursor(),
            organization_id=3,
            workload_rows=[row],
            events_by_bag={"8UIXS2OC6W": _wf_events("8UIXS2OC6W")},
            registry_meta={"8UIXS2OC6W": {"weight_num": 14.0}},
            selected_date_et=JUL3,
            as_of_end=T2,
            sync_registry=False,
        )
        bag = credited[0]
        assert bag["completed_lbs"] == 8.6
        assert bag.get("weight_missing") is False
        assert bag.get("weight_source") == "portal_upload_weight"

    @patch(
        "backend.rinse_workload_bag_weight.load_portal_upload_weights_for_bags",
        return_value={"WF1": 10.0},
    )
    @patch("backend.rinse_workload_bag_weight.load_registry_weight_context_for_bags", return_value={})
    def test_missing_weight_warning_when_some_bags_unresolved(self, *_mocks):
        row_with = _workload_row("WF1", weight=None)
        row_missing = _workload_row("WF2", weight=None)
        events = {
            "WF1": _wf_events("WF1"),
            "WF2": _wf_events("WF2"),
        }
        credited = [
            resolve_workload_bag_credit(
                row_with,
                events=events["WF1"],
                selected_date_et=JUL3,
                as_of_end=T2,
                registry_meta={},
            ),
            resolve_workload_bag_credit(
                row_missing,
                events=events["WF2"],
                selected_date_et=JUL3,
                as_of_end=T2,
                registry_meta={},
            ),
        ]
        _enrich_credited_bag_weights(
            credited,
            cursor=_PortalWeightCursor(),
            organization_id=3,
            workload_rows=[row_with, row_missing],
            events_by_bag=events,
            registry_meta={},
            selected_date_et=JUL3,
            as_of_end=T2,
            sync_registry=False,
        )
        assert credited[0]["weight_lbs"] == 10.0
        assert credited[1]["weight_status"] == WEIGHT_STATUS_MISSING
        display_signal = credited[1].get("completion_signal") or credited[1].get("processed_signal")
        assert display_signal == POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL

        from backend.rinse_employee_productivity_presentation import _build_executive_summary

        summary = _build_executive_summary(
            [
                {
                    "employee": EMPLOYEE,
                    "completed_bags": 2,
                    "total_completed_lbs": 10.0,
                    "productive_hours": 4.0,
                    "completed_lbs_per_hour": 2.5,
                    "missing_weight_count": 1,
                }
            ]
        )
        assert summary["average_completed_pounds_per_hour"] == 2.5
        assert "1 of 2 completed bags missing weight" in (summary.get("missing_weight_warning") or "")

    def test_attribution_unchanged_when_weight_changes(self):
        row = _workload_row("WF1", weight=None)
        events = _wf_events("WF1")
        before = resolve_workload_bag_credit(
            row,
            events=events,
            selected_date_et=JUL3,
            as_of_end=T2,
            registry_meta={},
        )
        credited, _ = credit_workload_bags(
            [row],
            events_by_bag={"WF1": events},
            selected_date_et=JUL3,
            registry_meta={},
        )
        with patch(
            "backend.rinse_workload_bag_weight.load_portal_upload_weights_for_bags",
            return_value={"WF1": 31.2},
        ), patch(
            "backend.rinse_workload_bag_weight.load_registry_weight_context_for_bags",
            return_value={},
        ):
            _enrich_credited_bag_weights(
                credited,
                cursor=_PortalWeightCursor(),
                organization_id=3,
                workload_rows=[row],
                events_by_bag={"WF1": events},
                registry_meta={},
                selected_date_et=JUL3,
                as_of_end=T2,
                sync_registry=False,
            )
        assert credited[0]["credited_employee"] == before["credited_employee"] == EMPLOYEE
        assert credited[0]["credit_timestamp"] == before["credit_timestamp"]
        assert credited[0]["completed_lbs"] == 31.2
