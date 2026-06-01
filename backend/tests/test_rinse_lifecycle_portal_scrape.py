"""Tests for missing-from-confirmed-portal-scrape lifecycle detection."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD
from backend.rinse_bag_lifecycle_status import (
    SENT_TO_RINSE,
    SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN,
    SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE,
)
from backend.rinse_lifecycle_portal_scrape import compute_missing_from_confirmed_portal_scrape


def _ev(purpose: str, at: datetime, *, rack: str = "Scale", user: str = "Alex") -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": at,
        "rack": rack,
        "user_name": user,
        "scan_index": 1,
        "id": 1,
    }


class TestComputeMissingFromConfirmedPortalScrape:
    LATEST_AT = datetime(2026, 5, 29, 10, 0)
    COMPLETION_AT = datetime(2026, 5, 28, 12, 0)

    def _latest_batch(self, *, wf_ids: set[str] | None = None) -> dict:
        return {
            "batch_id": 99,
            "confirmed_at": self.LATEST_AT,
            "wf_bag_ids": wf_ids or {"STILL_HERE"},
            "portal_scrape_meta": {"stopped_reason": "no_next_page_ui"},
        }

    def test_clean_rack_missing_from_later_confirmed_scrape(self):
        cursor = MagicMock()
        events = {"MISSING1": [_ev("", self.COMPLETION_AT, rack="CLEAN")]}
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=self._latest_batch(),
        ), patch(
            "backend.rinse_lifecycle_portal_scrape._bag_in_prior_confirmed_portal_batch",
            return_value=True,
        ), patch(
            "backend.rinse_lifecycle_portal_scrape.table_exists",
            return_value=False,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["MISSING1"], events
            )
        assert out["MISSING1"] is True

    def test_missing_from_scrape_before_completion_time_not_flagged(self):
        cursor = MagicMock()
        events = {"LATE1": [_ev("", datetime(2026, 5, 29, 11, 0), rack="CLEAN")]}
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=self._latest_batch(),
        ), patch(
            "backend.rinse_lifecycle_portal_scrape.table_exists",
            return_value=False,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["LATE1"], events
            )
        assert out.get("LATE1") is False

    def test_no_completion_evidence_not_flagged(self):
        cursor = MagicMock()
        events = {"WASH1": [_ev("start-cleaning", self.COMPLETION_AT)]}
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=self._latest_batch(),
        ), patch(
            "backend.rinse_lifecycle_portal_scrape._bag_in_prior_confirmed_portal_batch",
            return_value=True,
        ), patch(
            "backend.rinse_lifecycle_portal_scrape.table_exists",
            return_value=False,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["WASH1"], events
            )
        assert out.get("WASH1") is False

    def test_unconfirmed_or_failed_latest_scrape_not_flagged(self):
        cursor = MagicMock()
        events = {"MISSING2": [_ev("", self.COMPLETION_AT, rack="CLEAN")]}
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=None,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["MISSING2"], events
            )
        assert out == {}

    def test_bag_still_in_latest_scrape_not_flagged(self):
        cursor = MagicMock()
        events = {"STILL_HERE": [_ev("", self.COMPLETION_AT, rack="CLEAN")]}
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=self._latest_batch(wf_ids={"STILL_HERE"}),
        ), patch(
            "backend.rinse_lifecycle_portal_scrape.table_exists",
            return_value=False,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["STILL_HERE"], events
            )
        assert out.get("STILL_HERE") is False

    def test_registry_missing_from_latest_shortcut(self):
        cursor = MagicMock()
        events = {"REG1": [_ev("", self.COMPLETION_AT, rack="CLEAN")]}
        cursor.fetchone.return_value = {
            "completed_at": datetime(2026, 5, 28, 13, 0),
            "completion_reason": REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
        }
        with patch(
            "backend.rinse_lifecycle_portal_scrape.fetch_latest_confirmed_full_portal_batch",
            return_value=self._latest_batch(),
        ), patch(
            "backend.rinse_lifecycle_portal_scrape.table_exists",
            return_value=True,
        ):
            out = compute_missing_from_confirmed_portal_scrape(
                cursor, 1, ["REG1"], events
            )
        assert out["REG1"] is True


class TestShiftAnalysisSentToRinseDrilldown:
    def test_drilldown_includes_external_scan_and_missing_from_scrape(self):
        from backend.rinse_bag_lifecycle_status import (
            SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN as EXT,
            SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE as MISS,
        )
        from backend.rinse_shift_analysis import build_lifecycle_pending_payload
        from backend.tests.test_rinse_shift_analysis import _staging_execute_side_effect

        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "EXT1",
                    "name_clean": "External",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "NON-RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
                {
                    "bag_id": "MIS1",
                    "name_clean": "Missing",
                    "weight_num": 8,
                    "service_type": "WF",
                    "effective_rush": "NON-RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
            ],
            scan_events=[
                {
                    "bag_id": "EXT1",
                    "id": 1,
                    "rack": "CLEAN",
                    "user_name": "Alex",
                    "purpose": "",
                    "scanned_at_parsed": datetime(2026, 5, 28, 12, 0),
                    "scan_index": 1,
                },
                {
                    "bag_id": "EXT1",
                    "id": 2,
                    "rack": "",
                    "user_name": "Rinse Driver",
                    "purpose": "move-bag",
                    "scanned_at_parsed": datetime(2026, 5, 28, 12, 10),
                    "scan_index": 2,
                },
                {
                    "bag_id": "MIS1",
                    "id": 3,
                    "rack": "CLEAN",
                    "user_name": "Alex",
                    "purpose": "",
                    "scanned_at_parsed": datetime(2026, 5, 28, 12, 0),
                    "scan_index": 1,
                },
            ],
        )

        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={
                "washing_minutes": 30,
                "drying_minutes": 45,
                "reject_after_create_issue_minutes": 45,
            },
        ), patch(
            "backend.rinse_shift_analysis._load_mapped_internal_scan_users",
            return_value={"Alex"},
        ), patch(
            "backend.rinse_shift_analysis.compute_missing_from_confirmed_portal_scrape",
            return_value={"MIS1": True},
        ):
            from datetime import date

            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 28))

        sent_rows = [
            r
            for r in out["rows"]
            if r.get("current_lifecycle_status") == SENT_TO_RINSE
        ]
        assert len(sent_rows) == 2
        reasons = {
            r["bag_id"]: r["stage_detail"].get("sent_to_rinse_reason") for r in sent_rows
        }
        assert reasons["EXT1"] == EXT
        assert reasons["MIS1"] == MISS
        assert out["groups"]["combined"]["by_lifecycle_group"]["sent_to_rinse"] == 2
