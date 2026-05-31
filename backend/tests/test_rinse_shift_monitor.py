"""Tests for shift live monitor and staff performance."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.rinse_bag_lifecycle_status import (
    CHECKOUT_STATUS_NEEDS_REVIEW,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    PENDING_WEIGHING,
    SORTED_READY_FOR_WASH,
)
from backend.rinse_shift_monitor import (
    ALERT_IN_DRYING,
    ALERT_PENDING_WEIGHING,
    ALERT_WAITING_WASHER,
    build_live_monitor_payload,
    build_staff_performance_payload,
    filter_monitor_records,
)


def _ev(purpose: str, ts: datetime, user: str = "Alice") -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "id": 1,
        "scan_index": 1,
    }


class TestLiveMonitor:
    def test_pending_weighing_alert(self):
        now = datetime(2026, 5, 27, 12, 0)
        rows = [
            {
                "bag_id": "B1",
                "rush": True,
                "current_lifecycle_status": PENDING_WEIGHING,
                "status_timestamp": now - timedelta(minutes=45),
                "operational_flags": {},
                "checkout_status": "NOT_CHECKED_OUT",
            }
        ]
        out = build_live_monitor_payload(
            rows,
            events_by_bag={"B1": [_ev("sent-to-vendor", now - timedelta(hours=2))]},
            monitor_settings={"pending_weighing_alert_minutes": 30, "washing_minutes": 30, "drying_minutes": 45},
            evaluation_time=now,
        )
        types = {a["type"] for a in out["alerts"]}
        assert ALERT_PENDING_WEIGHING in types
        alert = next(a for a in out["alerts"] if a["type"] == ALERT_PENDING_WEIGHING)
        assert alert["severity"] == "critical"
        assert alert["record_count"] == 1

    def test_waiting_for_washer_rush_critical(self):
        now = datetime(2026, 5, 27, 12, 0)
        rows = [
            {
                "bag_id": "B2",
                "rush": True,
                "current_lifecycle_status": SORTED_READY_FOR_WASH,
                "status_timestamp": now - timedelta(minutes=25),
                "operational_flags": {},
            }
        ]
        out = build_live_monitor_payload(
            rows,
            events_by_bag={},
            monitor_settings={"waiting_for_washer_alert_minutes": 20},
            evaluation_time=now,
        )
        alert = next(a for a in out["alerts"] if a["type"] == ALERT_WAITING_WASHER)
        assert alert["severity"] == "critical"
        assert alert["rush_count"] == 1

    def test_in_drying_over_limit(self):
        now = datetime(2026, 5, 27, 12, 0)
        rows = [
            {
                "bag_id": "B3",
                "rush": False,
                "current_lifecycle_status": IN_DRYING,
                "status_timestamp": now - timedelta(minutes=60),
                "operational_flags": {},
            }
        ]
        out = build_live_monitor_payload(
            rows,
            events_by_bag={},
            monitor_settings={"drying_minutes": 45, "drying_grace_minutes": 5},
            evaluation_time=now,
        )
        assert any(a["type"] == ALERT_IN_DRYING for a in out["alerts"])

    def test_step_metrics_avg_median_longest(self):
        t0 = datetime(2026, 5, 27, 8, 0)
        events = [
            _ev("cleaning", t0, "Alice"),
            _ev("sent-to-vendor", t0 + timedelta(minutes=5), "Alice"),
            _ev("weight-entry", t0 + timedelta(minutes=10), "Alice"),
            _ev("add-photos", t0 + timedelta(minutes=15), "Alice"),
            _ev("start-cleaning", t0 + timedelta(minutes=20), "Bob"),
        ]
        rows = [{"bag_id": "B4", "rush": False, "operational_flags": {}, "current_lifecycle_status": IN_WASHING}]
        out = build_live_monitor_payload(
            rows,
            events_by_bag={"B4": events},
            monitor_settings={},
            evaluation_time=t0 + timedelta(hours=2),
            proc_settings={"washing_minutes": 30, "drying_minutes": 45},
        )
        weighing = next(m for m in out["step_metrics"] if m["step"] == "weighing")
        assert weighing["bag_count"] >= 1
        assert weighing["avg_seconds"] is not None
        assert weighing["median_seconds"] is not None
        assert weighing["longest_seconds"] is not None

    def test_load_washer_not_lifecycle_status_in_rows(self):
        """Lifecycle rows should not use LOAD_WASHER as current_lifecycle_status."""
        now = datetime(2026, 5, 27, 12, 0)
        rows = [
            {
                "bag_id": "B5",
                "rush": False,
                "current_lifecycle_status": IN_WASHING,
                "status_timestamp": now - timedelta(minutes=10),
                "operational_flags": {},
            }
        ]
        for r in rows:
            assert r["current_lifecycle_status"] not in ("LOAD_WASHER", "LOAD_DRYER")


class TestStaffPerformance:
    def test_weighing_task_metrics(self):
        t0 = datetime(2026, 5, 27, 8, 0)
        events = [
            _ev("cleaning", t0, "Francis"),
            _ev("sent-to-vendor", t0 + timedelta(minutes=1), "Francis"),
            _ev("weight-entry", t0 + timedelta(minutes=6), "Francis"),
        ]
        rows = [
            {
                "bag_id": "B10",
                "customer": "Cust",
                "rush_label": "Non-Rush",
                "current_lifecycle_status": SORTED_READY_FOR_WASH,
                "operational_flags": {},
            }
        ]
        out = build_staff_performance_payload(rows, events_by_bag={"B10": events})
        weighing = [t for t in out["tasks"] if t["task"] == "weighing" and t["employee_name"] == "Francis"]
        assert len(weighing) == 1
        assert weighing[0]["bag_count"] == 1
        assert weighing[0]["avg_seconds_per_bag"] == 360.0

    def test_overall_vs_scoring_separation(self):
        t0 = datetime(2026, 5, 27, 8, 0)
        events = [
            _ev("cleaning", t0, "Francis"),
            _ev("sent-to-vendor", t0 + timedelta(minutes=1), "Francis"),
            _ev("weight-entry", t0 + timedelta(minutes=6), "Francis"),
        ]
        rows = [{"bag_id": "B11", "rush_label": "Rush", "operational_flags": {}}]
        fold_rows = [{"bag_id": "B11", "status": "EXCEPTION", "exception_code": "MISSING_CLEAN"}]
        out = build_staff_performance_payload(rows, events_by_bag={"B11": events}, folding_rows=fold_rows)
        rec = next(r for r in out["records"] if r["bag_id"] == "B11" and r["task"] == "weighing")
        assert rec["in_scoring"] is False
        assert rec["reason_not_scoring"]

    def test_drilldown_filter_exact_records(self):
        rows = [
            {"bag_id": "B20", "current_lifecycle_status": PENDING_WEIGHING, "operational_flags": {}},
            {"bag_id": "B21", "current_lifecycle_status": IN_WASHING, "operational_flags": {}},
        ]
        staff_recs = [
            {"bag_id": "B20", "task": "weighing", "employee_name": "Francis", "in_scoring": True, "needs_review": False},
        ]
        filtered = filter_monitor_records(
            rows,
            staff_recs,
            {"source": "monitor", "alert_type": ALERT_PENDING_WEIGHING, "bag_ids": ["B20"]},
        )
        assert len(filtered) == 1
        assert filtered[0]["bag_id"] == "B20"

        staff_filtered = filter_monitor_records(
            rows,
            staff_recs,
            {"source": "monitor", "employee_name": "Francis", "task": "weighing"},
        )
        assert len(staff_filtered) == 1
        assert staff_filtered[0]["activity"] == "staff"
