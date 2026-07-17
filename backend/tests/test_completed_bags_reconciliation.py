"""Tests for completed-bags reconciliation diagnostic."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

from backend.rinse_completed_bags_reconciliation import (
    EXCLUSION_MISSING_POST_WEIGHT,
    build_completed_bags_reconciliation,
)


class TestCompletedBagsReconciliation:
    def test_sources_agree_when_scan_dashboard_and_attribution_match(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._scan_evidence_wf_completed_ids",
            lambda *a, **k: {"A1", "A2"},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_completed_et_day",
            lambda *a, **k: {"A1": {}, "A2": {}},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_wf_complete_cleaning_today",
            lambda *a, **k: {
                "A1": {"bag_id": "A1", "user_name": "Amna", "scanned_at_parsed": datetime(2026, 7, 16, 10)},
                "A2": {"bag_id": "A2", "user_name": "Evelin", "scanned_at_parsed": datetime(2026, 7, 16, 11)},
            },
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_rows",
            lambda *a, **k: {
                "A1": {"bag_id": "A1", "service_type": "WF", "completion_status": "COMPLETED", "name_clean": "Cust1"},
                "A2": {"bag_id": "A2", "service_type": "WF", "completion_status": "COMPLETED", "name_clean": "Cust2"},
            },
        )

        module = {
            "rows": [
                {"bag_id": "A1", "at_vendor_status": "Completed", "service_type": "WF"},
                {"bag_id": "A2", "at_vendor_status": "Completed", "service_type": "WF"},
            ]
        }
        emp = {
            "employees": [
                {"display_name": "Amna", "bags": [{"bag_id": "A1"}]},
                {"display_name": "Evelin", "bags": [{"bag_id": "A2"}]},
            ]
        }
        out = build_completed_bags_reconciliation(
            MagicMock(),
            3,
            selected_date_et=date(2026, 7, 16),
            at_vendor_module=module,
            employee_completed_section=emp,
            claimed_portal_completed=2,
        )
        assert out["counts"]["scan_evidence_completed"] == 2
        assert out["counts"]["dashboard_completed"] == 2
        assert out["counts"]["employee_attributed"] == 2
        assert out["counts"]["claimed_minus_dashboard"] == 0
        assert out["invariant"]["sources_agree"] is True
        assert out["unreconciled"] == []

    def test_cc_without_post_weight_is_unreconciled_not_silent(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._scan_evidence_wf_completed_ids",
            lambda *a, **k: {"DONE"},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_completed_et_day",
            lambda *a, **k: {"DONE": {}},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_wf_complete_cleaning_today",
            lambda *a, **k: {
                "DONE": {"bag_id": "DONE", "user_name": "Amna", "scanned_at_parsed": datetime(2026, 7, 16, 10)},
                "STUCK": {
                    "bag_id": "STUCK",
                    "user_name": "Evelin",
                    "scanned_at_parsed": datetime(2026, 7, 16, 12),
                    "name_clean": "Stuck Cust",
                    "service_type": "WF",
                    "completion_status": "REJECTED",
                    "completion_reason": "MISSING_FROM_LATEST_PORTAL_SCRAPE",
                    "weight_num": 12.5,
                },
            },
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_rows",
            lambda *a, **k: {
                "DONE": {"bag_id": "DONE", "service_type": "WF", "completion_status": "COMPLETED"},
                "STUCK": {
                    "bag_id": "STUCK",
                    "service_type": "WF",
                    "completion_status": "REJECTED",
                    "completion_reason": "MISSING_FROM_LATEST_PORTAL_SCRAPE",
                    "name_clean": "Stuck Cust",
                    "weight_num": 12.5,
                },
            },
        )
        module = {
            "rows": [{"bag_id": "DONE", "at_vendor_status": "Completed", "service_type": "WF"}]
        }
        emp = {"employees": [{"display_name": "Amna", "bags": [{"bag_id": "DONE"}]}]}
        out = build_completed_bags_reconciliation(
            MagicMock(),
            3,
            selected_date_et=date(2026, 7, 16),
            at_vendor_module=module,
            employee_completed_section=emp,
            claimed_portal_completed=75,
        )
        assert out["counts"]["dashboard_completed"] == 1
        assert out["counts"]["claimed_minus_dashboard"] == 74
        assert len(out["unreconciled"]) == 1
        u = out["unreconciled"][0]
        assert u["bag_id"] == "STUCK"
        assert EXCLUSION_MISSING_POST_WEIGHT in u["exclusion_reasons"]
        assert u["dashboard_status"] == "Absent"

    def test_claimed_gap_is_visible_even_when_sources_agree(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._scan_evidence_wf_completed_ids",
            lambda *a, **k: {"A1"},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_completed_et_day",
            lambda *a, **k: {},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_wf_complete_cleaning_today",
            lambda *a, **k: {},
        )
        monkeypatch.setattr(
            "backend.rinse_completed_bags_reconciliation._load_registry_rows",
            lambda *a, **k: {"A1": {"bag_id": "A1", "service_type": "WF", "completion_status": "COMPLETED"}},
        )
        out = build_completed_bags_reconciliation(
            MagicMock(),
            3,
            selected_date_et=date(2026, 7, 16),
            at_vendor_module={
                "rows": [{"bag_id": "A1", "at_vendor_status": "Completed", "service_type": "WF"}]
            },
            employee_completed_section={
                "employees": [{"display_name": "Amna", "bags": [{"bag_id": "A1"}]}]
            },
            claimed_portal_completed=75,
        )
        assert out["counts"]["claimed_portal_completed"] == 75
        assert out["counts"]["dashboard_completed"] == 1
        assert out["counts"]["claimed_minus_dashboard"] == 74
        assert out["invariant"]["sources_agree"] is True
