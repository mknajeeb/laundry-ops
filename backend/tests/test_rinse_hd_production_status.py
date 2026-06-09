"""HD production stage logic — separate from WF weighing workflow."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_hd_production_status import (
    HD_NOT_STARTED,
    HD_SENT_LEFT,
    HD_STARTED_CLEANING,
    HD_STILL_AT_FACILITY,
    derive_hd_production_status,
    hd_stage_drilldown_tag,
    is_hd_wrongly_in_wf_weighing,
)


def _ev(purpose: str, ts: datetime, **extra) -> dict:
    return {"purpose": purpose, "scanned_at_parsed": ts, **extra}


class TestHdProductionStatus(unittest.TestCase):
    def test_not_started_after_vendor_anchor(self):
        t0 = datetime(2026, 6, 9, 10, 0, 0)
        events = [_ev("sent-to-vendor", t0)]
        out = derive_hd_production_status(events, at_vendor_presence=True)
        self.assertEqual(out["hd_stage"], HD_NOT_STARTED)
        self.assertFalse(out["hd_started"])

    def test_workitem_marks_started(self):
        t0 = datetime(2026, 6, 9, 10, 0, 0)
        t1 = datetime(2026, 6, 9, 11, 0, 0)
        events = [
            _ev("sent-to-vendor", t0),
            _ev("create-workitem", t1),
        ]
        out = derive_hd_production_status(events, at_vendor_presence=True)
        self.assertEqual(out["hd_stage"], HD_STARTED_CLEANING)
        self.assertTrue(out["hd_started"])
        self.assertFalse(out["hd_completed"])

    def test_add_photos_after_workitem_marks_still_at_facility(self):
        t0 = datetime(2026, 6, 9, 10, 0, 0)
        t1 = datetime(2026, 6, 9, 11, 0, 0)
        t2 = datetime(2026, 6, 9, 12, 0, 0)
        events = [
            _ev("sent-to-vendor", t0),
            _ev("create-workitem", t1),
            _ev("add-photos", t2),
        ]
        out = derive_hd_production_status(events, at_vendor_presence=True)
        self.assertEqual(out["hd_stage"], HD_STILL_AT_FACILITY)
        self.assertTrue(out["hd_completed"])

    def test_sent_left_overrides(self):
        t0 = datetime(2026, 6, 9, 10, 0, 0)
        events = [_ev("sent-to-vendor", t0)]
        out = derive_hd_production_status(
            events,
            at_vendor_presence=True,
            logistics_status="SENT_TO_RINSE",
        )
        self.assertEqual(out["hd_stage"], HD_SENT_LEFT)

    def test_hd_never_wrongly_in_weighing_when_clean(self):
        self.assertFalse(
            is_hd_wrongly_in_wf_weighing(
                service_type="HD",
                lifecycle_status="HD_NOT_STARTED",
                drilldown_tags=["wip_hd", "hd_not_started"],
            )
        )

    def test_hd_wrongly_in_weighing_detected(self):
        self.assertTrue(
            is_hd_wrongly_in_wf_weighing(
                service_type="HD",
                lifecycle_status="PENDING_WEIGHING",
                drilldown_tags=["shift_not_weighed"],
            )
        )

    def test_efx3_regression_not_pending_weighing_stage(self):
        """HD bag must not surface as PENDING_WEIGHING — use HD stages instead."""
        t0 = datetime(2026, 6, 9, 11, 48, 0)
        events = [_ev("sent-to-vendor", t0)]
        out = derive_hd_production_status(events, at_vendor_presence=True)
        self.assertNotEqual(out["hd_stage"], "PENDING_WEIGHING")
        self.assertEqual(hd_stage_drilldown_tag(out["hd_stage"]), "hd_not_started")


if __name__ == "__main__":
    unittest.main()
