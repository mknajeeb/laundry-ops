"""Portal departure completion — bags leaving the board must not be wrongly rejected."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    COMPLETION_REJECTED,
    REASON_COMPLETED_PORTAL_DEPARTURE,
    REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE,
    REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION,
)
from backend.rinse_portal_absence_completion import process_bags_missing_from_latest_portal
from backend.rinse_portal_departure_completion import (
    detect_confirmed_cancellation,
    detect_portal_departure_completion_evidence,
    verify_and_resolve_portal_departure_bag,
)


def _wf_completion_events(
    *,
    first_weight_user: str = "Singh (VeeWash)",
    second_weight_user: str = "Evelin (VeeWash)",
    second_weight_at: datetime | None = None,
) -> list[dict]:
    second_at = second_weight_at or datetime(2026, 7, 2, 15, 12, 0)
    return [
        {"id": 1, "purpose": "sent-to-vendor", "scanned_at_parsed": datetime(2026, 7, 2, 4, 33, 0), "user_name": "Melissa"},
        {"id": 2, "purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 7, 2, 7, 14, 0), "user_name": first_weight_user},
        {"id": 3, "purpose": "complete-cleaning", "scanned_at_parsed": datetime(2026, 7, 2, 14, 52, 0), "user_name": second_weight_user},
        {"id": 4, "purpose": "weight-entry Last Scan", "scanned_at_parsed": second_at, "user_name": second_weight_user},
        {"id": 5, "purpose": "processed-by-vendor", "scanned_at_parsed": second_at, "user_name": second_weight_user},
    ]


class TestPortalDepartureCompletionEvidence(unittest.TestCase):
    def test_second_weight_entry_is_completion_evidence(self):
        events = _wf_completion_events()
        evidence = detect_portal_departure_completion_evidence(events, service_type="WF")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["employee"], "Evelin (VeeWash)")
        self.assertEqual(evidence["completion_at"], datetime(2026, 7, 2, 15, 12, 0))

    def test_no_events_returns_none(self):
        self.assertIsNone(detect_portal_departure_completion_evidence([], service_type="WF"))

    def test_cancellation_detection(self):
        events = [{"purpose": "bag-cancelled", "scanned_at_parsed": datetime(2026, 7, 2, 12, 0, 0)}]
        self.assertTrue(detect_confirmed_cancellation(events))


class TestVerifyPortalDepartureBag(unittest.TestCase):
    def test_missing_from_scrape_with_weight_completes_not_rejects(self):
        cursor = MagicMock()
        events = _wf_completion_events()
        with (
            patch(
                "backend.rinse_portal_departure_completion.recover_missing_scans_from_upload_batch_history",
                return_value={"inserted": 0},
            ),
            patch(
                "backend.rinse_bag_registry.fetch_persistent_scan_events_for_bag",
                return_value=events,
            ),
            patch(
                "backend.rinse_bag_registry.get_registry_row",
                return_value={"service_type": "WF", "completion_status": COMPLETION_INCOMPLETE},
            ),
            patch(
                "backend.rinse_bag_registry.is_bag_already_completed",
                return_value=False,
            ),
            patch(
                "backend.rinse_portal_departure_completion.mark_registry_completed_portal_departure",
                return_value=True,
            ) as mock_complete,
            patch(
                "backend.rinse_bag_registry.mark_registry_rejected_portal_absence"
            ) as mock_reject,
        ):
            out = verify_and_resolve_portal_departure_bag(
                cursor, 3, "AFXRSXEXYK", upload_batch_id=1984
            )
        self.assertEqual(out["action"], "completed")
        mock_complete.assert_called_once()
        mock_reject.assert_not_called()

    def test_missing_without_evidence_needs_verification_not_reject(self):
        cursor = MagicMock()
        partial = _wf_completion_events()[:3]
        with (
            patch(
                "backend.rinse_portal_departure_completion.recover_missing_scans_from_upload_batch_history",
                return_value={"inserted": 0},
            ),
            patch(
                "backend.rinse_bag_registry.fetch_persistent_scan_events_for_bag",
                return_value=partial,
            ),
            patch(
                "backend.rinse_bag_registry.get_registry_row",
                return_value={"service_type": "WF"},
            ),
            patch(
                "backend.rinse_bag_registry.is_bag_already_completed",
                return_value=False,
            ),
            patch(
                "backend.rinse_portal_departure_completion.mark_registry_needs_verification_portal_absence",
                return_value=True,
            ) as mock_verify,
            patch(
                "backend.rinse_bag_registry.mark_registry_rejected_portal_absence"
            ) as mock_reject,
        ):
            out = verify_and_resolve_portal_departure_bag(
                cursor, 3, "PARTIALBAG", upload_batch_id=1984
            )
        self.assertEqual(out["action"], "needs_verification")
        mock_verify.assert_called_once()
        mock_reject.assert_not_called()


class TestProcessBagsMissingFromLatestPortal(unittest.TestCase):
    def test_completed_bag_not_rejected_when_missing_from_scrape(self):
        cursor = MagicMock()
        accepted = [{"ticket_id": "BAGB"}]
        completed_outcome = {
            "bag_id": "BAGA",
            "action": "completed",
            "evidence": {"kind": "second-weight-entry"},
        }
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value={"BAGA"},
            ),
            patch(
                "backend.rinse_portal_absence_completion.verify_and_resolve_portal_departure_bag",
                return_value=completed_outcome,
            ),
            patch(
                "backend.rinse_portal_absence_completion.is_bag_already_completed",
                return_value=False,
            ),
            patch(
                "backend.rinse_portal_absence_completion.deactivate_at_vendor_presence_for_bags"
            ) as mock_deact,
        ):
            out = process_bags_missing_from_latest_portal(
                cursor, 1, 99, accepted, full_snapshot=True
            )
        self.assertEqual(out["completed_bag_ids"], ["BAGA"])
        self.assertEqual(out["bag_ids"], [])
        self.assertEqual(out["count"], 0)
        mock_deact.assert_not_called()

    def test_between_scrape_recovery_path_invoked(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value={"BETWEEN1"},
            ),
            patch(
                "backend.rinse_portal_absence_completion.verify_and_resolve_portal_departure_bag",
                return_value={"bag_id": "BETWEEN1", "action": "needs_verification"},
            ) as mock_verify,
            patch(
                "backend.rinse_portal_absence_completion.is_bag_already_completed",
                return_value=False,
            ),
        ):
            out = process_bags_missing_from_latest_portal(
                cursor, 1, 99, [{"ticket_id": "OTHER"}], full_snapshot=True
            )
        mock_verify.assert_called_once()
        self.assertEqual(out["needs_verification_bag_ids"], ["BETWEEN1"])


class TestRecoverRejectedIntegration(unittest.TestCase):
    """Recovered completed bag credits correct employee via attribution."""

    def test_recovered_wf_bag_credits_evelin(self):
        from backend.rinse_employee_completed_bags import resolve_completion_attribution
        from backend.rinse_folding_et import naive_et_day_end_inclusive

        events = _wf_completion_events()
        anchor = datetime(2026, 7, 2, 4, 33, 0)
        emp, comp_ts, sig = resolve_completion_attribution(
            service_type="WF",
            events=events,
            anchor_ts=anchor,
            as_of_end=naive_et_day_end_inclusive(datetime(2026, 7, 2).date()),
        )
        self.assertEqual(emp, "Evelin (VeeWash)")
        self.assertEqual(comp_ts, datetime(2026, 7, 2, 15, 12, 0))
        self.assertEqual(sig, "post_processing_weight")

    def test_recovered_bag_in_employee_productivity_and_reconciliation(self):
        from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
        from backend.rinse_employee_workload_productivity import (
            build_workload_productivity_reconciliation,
            credit_workload_bags,
        )

        bag_id = "AFXRSXEXYK"
        events = _wf_completion_events()
        row = {
            "bag_id": bag_id,
            "service_type": "WF",
            "service_bucket": "WF",
            "at_vendor_status": "Completed",
            "module_tags": [MOD_AT_VENDOR_COMPLETED],
            "completion_time": datetime(2026, 7, 2, 15, 12, 0).isoformat(),
            "completion_signal": "post_processing_weight",
            "post_clean_weight": 14.9,
            "rush_bucket": "RUSH",
        }
        credited, dups = credit_workload_bags(
            [row],
            events_by_bag={bag_id: events},
            selected_date_et=datetime(2026, 7, 2).date(),
        )
        self.assertEqual(dups, [])
        self.assertEqual(len(credited), 1)
        self.assertEqual(credited[0]["credited_employee"], "Evelin (VeeWash)")
        self.assertEqual(credited[0]["bag_id"], bag_id)

        recon = build_workload_productivity_reconciliation(
            workload_rows=[row],
            credited_bags=credited,
            duplicate_bag_ids=dups,
            selected_date_et=datetime(2026, 7, 2).date(),
        )
        self.assertTrue(recon["ok"])
        self.assertEqual(recon["credited_total"], 1)
        self.assertEqual(recon["workload_completed_today"], 1)

    def test_portal_refresh_backfill_credits_evelin_second_bag(self):
        from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
        from backend.rinse_employee_workload_productivity import credit_workload_bags

        bag_id = "2GBPXVG0CM"
        second_at = datetime(2026, 7, 2, 15, 32, 0)
        events = _wf_completion_events(second_weight_at=second_at)
        row = {
            "bag_id": bag_id,
            "service_type": "WF",
            "service_bucket": "WF",
            "at_vendor_status": "Completed",
            "module_tags": [MOD_AT_VENDOR_COMPLETED],
            "completion_time": second_at.isoformat(),
            "completion_signal": "post_processing_weight",
            "post_clean_weight": 13.9,
            "rush_bucket": "RUSH",
        }
        credited, _ = credit_workload_bags(
            [row],
            events_by_bag={bag_id: events},
            selected_date_et=datetime(2026, 7, 2).date(),
        )
        self.assertEqual(credited[0]["credited_employee"], "Evelin (VeeWash)")
        self.assertEqual(credited[0]["bag_id"], bag_id)


class TestMarkRegistryPortalDeparture(unittest.TestCase):
    def test_completed_reason_is_portal_departure(self):
        from backend.rinse_portal_departure_completion import mark_registry_completed_portal_departure

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        when = datetime(2026, 7, 2, 15, 12, 0)
        ok = mark_registry_completed_portal_departure(
            cursor,
            3,
            "AFXRSXEXYK",
            upload_batch_id=1984,
            evidence={"kind": "second-weight-entry", "completion_at": when},
            completed_at=when,
        )
        self.assertTrue(ok)
        params = cursor.execute.call_args_list[-1][0][1]
        self.assertEqual(params[2], COMPLETION_COMPLETED)
        self.assertEqual(params[3], REASON_COMPLETED_PORTAL_DEPARTURE)


class TestRestorePortalScrapeRejected(unittest.TestCase):
    def test_restore_clears_wrong_rejection(self):
        from backend.rinse_portal_departure_completion import restore_portal_scrape_rejected_bag

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "completion_status": COMPLETION_REJECTED,
            "completion_reason": REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE,
        }
        ok = restore_portal_scrape_rejected_bag(cursor, 3, "BAG1")
        self.assertTrue(ok)
        update_params = cursor.execute.call_args[0][1]
        self.assertEqual(update_params[0], COMPLETION_INCOMPLETE)
        self.assertEqual(update_params[1], REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION)


if __name__ == "__main__":
    unittest.main()
