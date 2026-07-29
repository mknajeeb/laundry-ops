"""At Vendor module — sent-to-vendor scope, completion, rush, changed-to-rush."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_at_vendor_module import (
    AV_NON_RUSH,
    AV_RUSH,
    AV_STATUS_COMPLETED,
    AV_STATUS_PENDING,
    CHANGED_RUSH_REASON_DAY_ADVANCE,
    INCLUSION_CARRY_IN,
    INCLUSION_CLEAN_SCRAPE_SEED,
    INCLUSION_NEW_SENT,
    INCLUSION_POST_BASELINE_SENT,
    MOD_AT_VENDOR_CHANGED_RUSH,
    MOD_AT_VENDOR_COMPLETED,
    MOD_AT_VENDOR_PENDING,
    MOD_AT_VENDOR_TOTAL,
    _bag_status_as_of,
    _build_row,
    _evaluate_bag_as_of,
    _filter_cross_org_contaminated_bags,
    _load_bag_organization_ownership,
    _load_selected_day_at_vendor_population,
    _resolve_selected_day_anchor_ts,
    build_at_vendor_module,
    classify_at_vendor_rush,
    explain_historical_scope_vs_presence,
    resolve_delivery_fields,
    validate_days_load_invariant,
    _apply_off_portal_workload_row_filter,
    _enrich_presence_delivery_meta,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_shift_monitor_modules import build_shift_monitor_modules


def _ev(
    purpose: str,
    ts: datetime,
    *,
    ev_id: int = 1,
    scan_index: int = 1,
    rack: str = "",
    user_name: str = "Tester",
) -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": scan_index,
        "rack": rack,
        "user_name": user_name,
    }


T0 = datetime(2026, 6, 10, 4, 0)
T0_ENTRY = datetime(2026, 6, 10, 4, 30)
T1 = datetime(2026, 6, 10, 5, 0)
T2 = datetime(2026, 6, 10, 6, 0)
T3 = datetime(2026, 6, 10, 7, 0)
SELECTED = date(2026, 6, 10)


def _dirty_entry(ts: datetime = T0_ENTRY) -> dict:
    """Configured WF entry rack move after sent-to-vendor (required for completion)."""
    return _ev("move-bag", ts, rack="VeeWash Dirty")


class TestAtVendorRush:
    def test_rush_when_edd_equals_selected_day(self):
        bucket, _ = classify_at_vendor_rush(
            latest_edd=SELECTED,
            delivery_texts=[],
            selected_date_et=SELECTED,
            pending=True,
        )
        assert bucket == AV_RUSH

    def test_rush_when_today_in_text(self):
        bucket, _ = classify_at_vendor_rush(
            latest_edd=date(2026, 6, 12),
            delivery_texts=["Delivery TODAY"],
            selected_date_et=SELECTED,
            pending=True,
        )
        assert bucket == AV_RUSH

    def test_rush_when_past_due_pending(self):
        bucket, _ = classify_at_vendor_rush(
            latest_edd=date(2026, 6, 9),
            delivery_texts=[],
            selected_date_et=SELECTED,
            pending=True,
        )
        assert bucket == AV_RUSH

    def test_non_rush_future_edd(self):
        bucket, _ = classify_at_vendor_rush(
            latest_edd=date(2026, 6, 12),
            delivery_texts=[],
            selected_date_et=SELECTED,
            pending=True,
        )
        assert bucket == AV_NON_RUSH


class TestWFCompletion:
    def test_first_weight_only_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("weight-entry", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_second_weight_without_processing_stays_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("weight-entry", T1), _ev("weight-entry", T2)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_early_double_weight_then_processing_without_post_weight_pending(self):
        """Regression: 5JO4VYLVHY — two weight-entry before add-photos, no post-processing weight."""
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("weight-entry", T2),
            _ev("add-photos", T3),
        ]
        status, signal, _, _, _ = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_processing_then_final_weight_completes(self):
        """Completion requires entry then garments-reviewed then post-review weight."""
        events = [
            _ev("sent-to-vendor", T0),
            _dirty_entry(),
            _ev("weight-entry", T1),
            _ev("add-photos", T2),
            _ev("garments-reviewed", T2),
            _ev("weight-entry", T3),
        ]
        status, signal, comp_ts, _, fields = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "post_garments_reviewed_weight_entry"
        assert comp_ts == T3
        assert fields.get("post_clean_weight_time") is not None

    def test_same_minute_final_weight_with_pre_clean_completes(self):
        """Post-review weight completes even when tied to other same-minute portal events."""
        selected = date(2026, 6, 18)
        tie = datetime(2026, 6, 18, 13, 59)
        pre = datetime(2026, 6, 18, 10, 51)
        review = datetime(2026, 6, 18, 13, 45)
        anchor = datetime(2026, 6, 18, 4, 33)
        events = [
            _ev("sent-to-vendor", anchor),
            _ev("move-bag", datetime(2026, 6, 18, 5, 0), rack="VeeWash Dirty"),
            _ev("weight-entry", pre),
            _ev("add-photos", datetime(2026, 6, 18, 11, 23)),
            _ev("garments-reviewed", review),
            _ev("add-photos", tie),
            _ev("weight-entry", tie),
            _ev("processed-by-vendor", tie),
        ]
        status, signal, comp_ts, _, fields = _evaluate_bag_as_of(
            events,
            service_type="WF",
            as_of_end=naive_et_day_end_inclusive(selected),
            anchor_ts_override=anchor,
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "post_garments_reviewed_weight_entry"
        assert comp_ts == tie
        assert fields.get("post_clean_weight_time") is not None

    def test_clean_rack_without_post_processing_weight_stays_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("move-bag", T2, rack="VeeWash Clean"),
        ]
        status, signal, _, _, fields = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert fields is not None
        assert fields.get("post_clean_weight") is None

    def test_complete_cleaning_without_post_processing_weight_stays_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("add-photos", T2),
            _ev("complete-cleaning", T3),
        ]
        status, signal, _, _, fields = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert fields.get("post_clean_weight") is None

    def test_received_from_vendor_does_not_complete(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("received-from-vendor", T2),
        ]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None


class TestHDCompletion:
    def test_first_add_photos_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_second_add_photos_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1), _ev("add-photos", T2)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"

    def test_complete_cleaning_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("complete-cleaning", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "complete-cleaning"

    def test_garments_reviewed_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("garments-reviewed", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED

    def test_assembly_printed_ct_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("assembly-printed-ct", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED


class TestRepeatedEventCompletion:
    """Second-occurrence completion requires strictly increasing unique timestamps."""

    def test_hd_one_add_photos_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_hd_duplicate_add_photos_same_timestamp_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1, ev_id=1),
            _ev("add-photos", T1, ev_id=2, scan_index=2),
        ]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_hd_two_add_photos_increasing_timestamps_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1), _ev("add-photos", T2)]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"
        assert comp_ts == T2

    def test_hd_pre_anchor_add_photos_plus_one_after_pending(self):
        events = [_ev("add-photos", T0), _ev("sent-to-vendor", T1), _ev("add-photos", T2)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_hd_two_post_anchor_add_photos_increasing_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1), _ev("add-photos", T2)]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"
        assert comp_ts == T2

    def test_hd_duplicate_add_photos_regression_7l3cpdv81q(self):
        anchor = datetime(2026, 6, 11, 4, 23)
        dup_ts = datetime(2026, 6, 12, 17, 1)
        events = [
            _ev("sent-to-vendor", anchor, ev_id=81388),
            _ev("add-photos", dup_ts, ev_id=88304, scan_index=2),
            _ev("add-photos", dup_ts, ev_id=88322, scan_index=4),
            _ev("workitems-added", datetime(2026, 6, 12, 17, 4), ev_id=88324, scan_index=2),
        ]
        as_of = naive_et_day_end_inclusive(date(2026, 6, 12))
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=as_of)
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_wf_one_weight_entry_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("weight-entry", T1)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_wf_duplicate_weight_entry_same_timestamp_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, ev_id=1),
            _ev("weight-entry", T1, ev_id=2, scan_index=2),
        ]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_wf_two_weight_entries_without_processing_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("weight-entry", T1), _ev("weight-entry", T2)]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_wf_processing_then_weight_completes(self):
        events = [
            _ev("sent-to-vendor", T0),
            _dirty_entry(),
            _ev("weight-entry", T1),
            _ev("garments-reviewed", T2),
            _ev("weight-entry", T3),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "post_garments_reviewed_weight_entry"
        assert comp_ts == T3

    def test_wf_pre_anchor_weight_plus_one_after_pending(self):
        events = [_ev("weight-entry", T0), _ev("sent-to-vendor", T1), _ev("weight-entry", T2)]
        status, signal, _, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None


class TestHDCreateIssueAddPhotosGuard:
    """Second add-photos HD completion blocked when create-issue precedes it."""

    def test_two_add_photos_no_create_issue_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1), _ev("add-photos", T2)]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"
        assert comp_ts == T2

    def test_two_add_photos_then_create_issue_completes(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1),
            _ev("add-photos", T2),
            _ev("create-issue", T3),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"
        assert comp_ts == T2

    def test_create_issue_between_add_photos_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1),
            _ev("create-issue", T2),
            _ev("add-photos", T3),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_create_issue_same_timestamp_as_second_add_photos_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1),
            _ev("create-issue", T2),
            _ev("add-photos", T2, ev_id=4, scan_index=4),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_create_issue_before_both_add_photos_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("create-issue", T1),
            _ev("add-photos", T2),
            _ev("add-photos", T3),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_duplicate_add_photos_before_create_issue_pending(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1, ev_id=1),
            _ev("add-photos", T1, ev_id=2, scan_index=2),
            _ev("create-issue", T2),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_one_add_photos_then_issue_then_duplicate_add_photos_pending(self):
        dup_ts = datetime(2026, 6, 10, 8, 0)
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1),
            _ev("create-issue", T2),
            _ev("add-photos", dup_ts, ev_id=4, scan_index=4),
            _ev("add-photos", dup_ts, ev_id=5, scan_index=5),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_create_workitem_bulk_between_add_photos_pending(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 4, 35)),
            _ev("add-photos", datetime(2026, 6, 12, 19, 56)),
            _ev("create-workitem-bulk", datetime(2026, 6, 12, 19, 58)),
            _ev("workitems-added", datetime(2026, 6, 12, 19, 58)),
            _ev("add-photos", datetime(2026, 6, 12, 20, 0)),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(date(2026, 6, 13))
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_amber_9fuw30xsfq_exact_sequence_regression(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 4, 35)),
            _ev("sent-to-vendor", datetime(2026, 6, 12, 4, 39)),
            _ev("add-photos", datetime(2026, 6, 12, 19, 56)),
            _ev("create-workitem-bulk", datetime(2026, 6, 12, 19, 58)),
            _ev("workitems-added", datetime(2026, 6, 12, 19, 58)),
            _ev("add-photos", datetime(2026, 6, 12, 20, 0)),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(date(2026, 6, 12))
        )
        assert status == AV_STATUS_PENDING
        assert signal is None
        assert comp_ts is None

    def test_other_hd_completion_signals_still_allowed_after_create_issue(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("create-issue", T1),
            _ev("complete-cleaning", T2),
        ]
        status, signal, comp_ts, _, _ = _evaluate_bag_as_of(
            events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED)
        )
        assert status == AV_STATUS_COMPLETED
        assert signal == "complete-cleaning"
        assert comp_ts == T2


class TestChangedToRush:
    def test_day_advance_pending(self):
        meta = {"service_type": "WF", "date_clean": date(2026, 6, 11)}
        events = [_ev("sent-to-vendor", datetime(2026, 6, 9, 4, 0)), _ev("weight-entry", datetime(2026, 6, 9, 5, 0))]
        row = _build_row(
            bag_id="B1",
            meta=meta,
            events=events,
            selected_date_et=date(2026, 6, 11),
            as_of_end=naive_et_day_end_inclusive(date(2026, 6, 11)),
        )
        assert row is not None
        assert row["rush_bucket"] == AV_RUSH
        assert row["previous_rush_bucket"] == AV_NON_RUSH
        assert MOD_AT_VENDOR_CHANGED_RUSH in row["module_tags"]
        assert row["changed_to_rush_reason"] == CHANGED_RUSH_REASON_DAY_ADVANCE

    def test_no_changed_to_rush_when_completed(self):
        meta = {"service_type": "WF", "date_clean": date(2026, 6, 11)}
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 11, 4, 0)),
            _ev("move-bag", datetime(2026, 6, 11, 4, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 11, 5, 0)),
            _ev("garments-reviewed", datetime(2026, 6, 11, 5, 30)),
            _ev("weight-entry", datetime(2026, 6, 11, 6, 0)),
        ]
        row = _build_row(
            bag_id="B2",
            meta=meta,
            events=events,
            selected_date_et=date(2026, 6, 11),
            as_of_end=naive_et_day_end_inclusive(date(2026, 6, 11)),
        )
        assert row is not None
        assert row["at_vendor_status"] == AV_STATUS_COMPLETED
        assert MOD_AT_VENDOR_CHANGED_RUSH not in row["module_tags"]


class TestAtVendorModuleCards:
    def test_three_main_cards_no_sent(self):
        rows = [
            {
                "bag_id": "A",
                "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING],
                "rush_bucket": AV_RUSH,
                "service_bucket": "WF",
            },
            {
                "bag_id": "B",
                "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED],
                "rush_bucket": AV_NON_RUSH,
                "service_bucket": "HD",
            },
        ]
        av_module = {
            "selected_date_et": SELECTED.isoformat(),
            "rows": rows,
            "total": 2,
            "pending": 1,
            "completed": 1,
            "changed_to_rush": 0,
            "total_equals_pending_plus_completed": True,
        }
        modules = build_shift_monitor_modules(
            [],
            events_by_bag={},
            period_start=SELECTED,
            period_end=SELECTED,
            period_start_dt=datetime(2026, 6, 10),
            period_end_exclusive=datetime(2026, 6, 11),
            portal_list_available=False,
            portal_counts=None,
            last_rush_wash=None,
            last_nonrush_wash=None,
            last_wash_overall=None,
            today_et=SELECTED,
            at_vendor_module=av_module,
        )
        fac = modules["facility_status"]
        labels = [c["label"] for c in fac["cards"]]
        assert "Total Bags" in labels
        assert "Pending" in labels
        assert "Completed" in labels
        assert "Sent" not in labels
        assert av_module["total"] == av_module["pending"] + av_module["completed"]


class TestSelectedDayPopulation:
    def test_carry_in_open_at_midnight_plus_new_sent_today(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "CARRY",
                "service_type": "WF",
                "population_inclusion": INCLUSION_CARRY_IN,
                "currently_on_vendor_home": False,
            },
            {
                "bag_id": "NEW",
                "service_type": "HD",
                "population_inclusion": INCLUSION_NEW_SENT,
                "currently_on_vendor_home": True,
            },
        ]
        pop_meta = {
            "available": True,
            "start_of_day_et": "2026-06-10T00:00:00",
            "end_of_day_et": "2026-06-10T23:59:59",
            "current_live_vendor_home_total": 1,
            "carry_in_open_at_midnight_count": 1,
            "new_sent_to_vendor_today_count": 1,
            "overlap_carry_in_and_new_sent_count": 0,
            "selected_day_at_vendor_total": 2,
            "bags_completed_before_midnight_excluded": ["OLD"],
            "bags_entered_after_midnight": ["NEW"],
            "bags_new_sent_only_today": ["NEW"],
        }
        events = {
            "CARRY": [_ev("sent-to-vendor", T0), _ev("weight-entry", T1)],
            "NEW": [_ev("sent-to-vendor", T2), _ev("complete-cleaning", T3)],
        }
        with patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
            return_value=(population, pop_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value=events,
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"CARRY": "WF", "NEW": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(object(), 1, selected_date_et=SELECTED)
        assert out["live"] is True
        assert out["selected_day_at_vendor_total"] == 2
        assert out["current_live_vendor_home_total"] == 1
        assert out["total"] == out["pending"] + out["completed"]
        assert out["carry_in_open_at_midnight_count"] == 1
        assert out["new_sent_to_vendor_today_count"] == 1
        recon = out["reconciliation"]
        assert recon["total_reconciles_to_selected_day_formula"] is True
        assert recon["difference_total_vs_live_vendor_home"] == 1

    def test_completed_before_midnight_excluded_without_resend(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 8, 4, 0)),
            _ev("move-bag", datetime(2026, 6, 8, 4, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 8, 5, 0)),
            _ev("garments-reviewed", datetime(2026, 6, 8, 5, 30)),
            _ev("weight-entry", datetime(2026, 6, 8, 6, 0)),
        ]
        prior_end = naive_et_day_end_inclusive(date(2026, 6, 9))
        anchor = datetime(2026, 6, 8, 4, 0)
        status, _, _, _, _ = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=prior_end, anchor_ts_override=anchor
        )
        assert status == AV_STATUS_COMPLETED

    def test_presence_carry_in_does_not_readd_completed_before_midnight(self):
        from unittest.mock import patch

        selected = date(2026, 6, 19)
        presence_carry = [
            {
                "bag_id": "DONECARRY",
                "portal_status": "at_vendor",
                "customer_name": "Done Carry",
                "estimated_delivery_date": date(2026, 6, 21),
                "service_type": "WF",
                "active": 0,
            },
            {
                "bag_id": "OPENCARRY",
                "portal_status": "at_vendor",
                "customer_name": "Open Carry",
                "estimated_delivery_date": date(2026, 6, 21),
                "service_type": "WF",
                "active": 1,
            },
        ]
        with patch(
            "backend.rinse_at_vendor_module.table_exists",
            return_value=True,
        ), patch(
            "backend.rinse_at_vendor_module._load_active_at_vendor_presence_by_bag",
            return_value={"OPENCARRY": {"bag_id": "OPENCARRY", "portal_yet_to_process": True}},
        ), patch(
            "backend.rinse_at_vendor_module._load_sent_to_vendor_bag_id_sets_for_et_day",
            return_value=({"DONECARRY", "OPENCARRY"}, set()),
        ), patch(
            "backend.rinse_at_vendor_module._load_carry_in_open_at_midnight_bag_ids",
            return_value=({"OPENCARRY"}, ["DONECARRY"], {}),
        ), patch(
            "backend.rinse_at_vendor_module._load_presence_carry_in_candidates",
            return_value=presence_carry,
        ), patch(
            "backend.rinse_at_vendor_module._filter_cross_org_contaminated_bags",
            side_effect=lambda _c, _o, ids: (set(ids), []),
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"OPENCARRY": "WF"},
        ), patch(
            "backend.rinse_at_vendor_module._load_delivery_meta",
            return_value={},
        ):
            population, meta = _load_selected_day_at_vendor_population(
                object(), 3, selected_date_et=selected
            )

        bag_ids = {p["bag_id"] for p in population}
        assert "OPENCARRY" in bag_ids
        assert "DONECARRY" not in bag_ids
        assert meta["bags_completed_before_midnight_excluded"] == ["DONECARRY"]
        assert meta["carry_in_open_at_midnight_count"] == 1

    def test_resend_same_day_resets_completion_anchor(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 8, 4, 0)),
            _ev("weight-entry", datetime(2026, 6, 8, 5, 0)),
            _ev("weight-entry", datetime(2026, 6, 8, 6, 0)),
            _ev("sent-to-vendor", T0),
        ]
        day_end = naive_et_day_end_inclusive(SELECTED)
        status, _, _, sent_ts, _ = _evaluate_bag_as_of(
            events,
            service_type="WF",
            as_of_end=day_end,
            anchor_ts_override=_resolve_selected_day_anchor_ts(events, SELECTED),
        )
        assert sent_ts == T0
        assert status == AV_STATUS_PENDING


class TestCrossOrgContamination:
    def test_filter_excludes_bag_owned_only_by_other_org(self):
        from unittest.mock import patch

        with patch(
            "backend.rinse_at_vendor_module._load_bag_organization_ownership",
            return_value={
                "3M8QVPGA2R": {1},
                "VEEONLY1": {3},
                "UNKNOWN1": set(),
            },
        ):
            kept, excluded = _filter_cross_org_contaminated_bags(
                object(), 3, {"3M8QVPGA2R", "VEEONLY1", "UNKNOWN1"}
            )
        assert kept == {"VEEONLY1", "UNKNOWN1"}
        assert [e["bag_id"] for e in excluded] == ["3M8QVPGA2R"]

    def test_filter_veewash_presence_excludes_dual_registry_washpro_canonical(self):
        from datetime import datetime
        from unittest.mock import patch

        with patch(
            "backend.rinse_at_vendor_module._load_bag_organization_ownership",
            return_value={"DVE92G8WAL": {1, 3}, "VEEONLY1": {3}},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_created_at_by_org",
            return_value={
                "DVE92G8WAL": {
                    1: datetime(2026, 5, 25, 14, 27, 4),
                    3: datetime(2026, 6, 13, 8, 41, 56),
                },
                "VEEONLY1": {3: datetime(2026, 6, 1, 12, 0, 0)},
            },
        ), patch(
            "backend.rinse_at_vendor_module._configured_veewash_org_ids",
            return_value={3},
        ), patch(
            "backend.rinse_at_vendor_module._configured_washpro_org_ids",
            return_value={1},
        ):
            from backend.rinse_at_vendor_module import filter_veewash_presence_cross_org_bags

            kept, excluded = filter_veewash_presence_cross_org_bags(
                object(), 3, {"DVE92G8WAL", "VEEONLY1"}
            )
        assert kept == {"VEEONLY1"}
        assert excluded[0]["bag_id"] == "DVE92G8WAL"
        assert excluded[0]["reason"] == "cross_org_washpro_canonical_registry"

    def test_veewash_module_excludes_washpro_only_presence_bag(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "3M8QVPGA2R",
                "service_type": "WF",
                "population_inclusion": "portal_live_at_vendor",
                "currently_on_vendor_home": True,
                "delivery_source": "presence",
            },
            {
                "bag_id": "VEEONLY1",
                "service_type": "HD",
                "population_inclusion": INCLUSION_CARRY_IN,
                "currently_on_vendor_home": True,
                "delivery_source": "presence",
            },
        ]
        pop_meta = {
            "available": True,
            "start_of_day_et": "2026-06-10T00:00:00",
            "end_of_day_et": "2026-06-10T23:59:59",
            "current_live_vendor_home_total": 2,
            "carry_in_open_at_midnight_count": 1,
            "new_sent_to_vendor_today_count": 0,
            "portal_live_supplement_count": 1,
            "new_during_selected_day_count": 1,
            "overlap_carry_in_and_new_sent_count": 0,
            "selected_day_at_vendor_total": 2,
            "bags_completed_before_midnight_excluded": [],
            "bags_entered_after_midnight": [],
            "bags_new_sent_only_today": [],
            "cross_org_excluded_bags": [],
            "cross_org_excluded_from_live_presence": [],
        }

        def fake_population(cursor, org, *, selected_date_et):
            kept, excluded = _filter_cross_org_contaminated_bags(
                cursor,
                org,
                {p["bag_id"] for p in population},
            )
            filtered = [p for p in population if p["bag_id"] in kept]
            meta = {
                **pop_meta,
                "selected_day_at_vendor_total": len(filtered),
                "cross_org_excluded_bags": excluded,
            }
            return filtered, meta

        with patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
            side_effect=fake_population,
        ), patch(
            "backend.rinse_at_vendor_module._load_bag_organization_ownership",
            return_value={"3M8QVPGA2R": {1}, "VEEONLY1": {3}},
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={"VEEONLY1": []},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"VEEONLY1": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(object(), 3, selected_date_et=SELECTED)

        assert out["total"] == 1
        assert [r["bag_id"] for r in out["rows"]] == ["VEEONLY1"]
        excluded = (out.get("population_meta") or {}).get("cross_org_excluded_bags") or []
        assert any(e.get("bag_id") == "3M8QVPGA2R" for e in excluded)

    def test_washpro_module_excludes_veewash_only_presence_bag(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "VEEONLY9",
                "service_type": "HD",
                "population_inclusion": INCLUSION_CARRY_IN,
                "currently_on_vendor_home": True,
                "delivery_source": "presence",
            },
            {
                "bag_id": "WASHOK1",
                "service_type": "WF",
                "population_inclusion": INCLUSION_CARRY_IN,
                "currently_on_vendor_home": True,
                "delivery_source": "presence",
            },
        ]

        def fake_population(cursor, org, *, selected_date_et):
            kept, excluded = _filter_cross_org_contaminated_bags(
                cursor, org, {p["bag_id"] for p in population},
            )
            filtered = [p for p in population if p["bag_id"] in kept]
            return filtered, {
                "available": True,
                "start_of_day_et": "2026-06-10T00:00:00",
                "end_of_day_et": "2026-06-10T23:59:59",
                "current_live_vendor_home_total": len(filtered),
                "carry_in_open_at_midnight_count": len(filtered),
                "new_sent_to_vendor_today_count": 0,
                "portal_live_supplement_count": 0,
                "new_during_selected_day_count": 0,
                "overlap_carry_in_and_new_sent_count": 0,
                "selected_day_at_vendor_total": len(filtered),
                "bags_completed_before_midnight_excluded": [],
                "bags_entered_after_midnight": [],
                "bags_new_sent_only_today": [],
                "cross_org_excluded_bags": excluded,
                "cross_org_excluded_from_live_presence": [],
            }

        with patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
            side_effect=fake_population,
        ), patch(
            "backend.rinse_at_vendor_module._load_bag_organization_ownership",
            return_value={"VEEONLY9": {3}, "WASHOK1": {1}},
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={"WASHOK1": []},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"WASHOK1": "WF"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(object(), 1, selected_date_et=SELECTED)

        assert out["total"] == 1
        assert [r["bag_id"] for r in out["rows"]] == ["WASHOK1"]


class TestAtVendorPresencePopulation:
    def test_build_row_always_includes_presence_bag_without_sent_scan(self):
        row = _build_row(
            bag_id="P1",
            meta={
                "bag_id": "P1",
                "service_type": "WF",
                "delivery_source": "presence",
                "portal_status": "at_vendor",
                "active_presence": True,
            },
            events=[],
            selected_date_et=SELECTED,
            as_of_end=naive_et_day_end_inclusive(SELECTED),
        )
        assert row is not None
        assert row["bag_id"] == "P1"
        assert row["at_vendor_status"] == AV_STATUS_PENDING
        assert "mod_at_vendor_total" in row["module_tags"]

    def test_unavailable_when_no_data_sources(self):
        from unittest.mock import patch

        with patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
            return_value=(
                [],
                {
                    "available": False,
                    "reason": "Scan events and cleaner-ticket presence tables unavailable",
                    "current_live_vendor_home_total": 0,
                },
            ),
        ):
            out = build_at_vendor_module(object(), 1, selected_date_et=SELECTED)
        assert out.get("live") is False
        assert out.get("total") is None

    def test_total_equals_selected_day_population(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "A1",
                "portal_status": "at_vendor",
                "customer_name": "Cust",
                "estimated_delivery_date": date(2026, 6, 11),
                "service_type": "WF",
                "raw_row_json": "{}",
                "delivery_source": "presence",
                "active_presence": True,
                "portal_yet_to_process": True,
                "population_inclusion": INCLUSION_CARRY_IN,
                "currently_on_vendor_home": True,
                "inclusion_reason": "Open at vendor before midnight and not completed before midnight",
            },
            {
                "bag_id": "A2",
                "portal_status": "at_vendor",
                "customer_name": "Cust2",
                "estimated_delivery_date": date(2026, 6, 12),
                "service_type": "HD",
                "raw_row_json": "{}",
                "delivery_source": "presence",
                "active_presence": True,
                "portal_yet_to_process": False,
                "population_inclusion": INCLUSION_NEW_SENT,
                "currently_on_vendor_home": True,
                "inclusion_reason": "New sent-to-vendor during selected ET day",
            },
        ]
        with patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
            return_value=(
                population,
                {
                    "available": True,
                    "current_live_vendor_home_total": 2,
                    "carry_in_open_at_midnight_count": 1,
                    "new_sent_to_vendor_today_count": 1,
                    "overlap_carry_in_and_new_sent_count": 0,
                    "selected_day_at_vendor_total": 2,
                    "start_of_day_et": "2026-06-10T00:00:00",
                    "end_of_day_et": "2026-06-10T23:59:59",
                    "bags_completed_before_midnight_excluded": [],
                    "bags_entered_after_midnight": ["A2"],
                    "bags_new_sent_only_today": ["A2"],
                },
            ),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={"A1": [], "A2": []},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"A1": "WF", "A2": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(object(), 1, selected_date_et=SELECTED)
        assert out.get("live") is True
        assert out["total"] == 2
        assert out["selected_day_at_vendor_total"] == 2
        assert out["current_live_vendor_home_total"] == 2
        assert out["total"] == out["pending"] + out["completed"]
        recon = out.get("reconciliation") or {}
        assert recon.get("total_reconciles_to_selected_day_formula") is True


CLEAN_BASELINE_CTX = {
    "baseline_source": "latest_clean_veewash_scrape",
    "baseline_start_naive_et": datetime(2026, 6, 11, 20, 38, 25),
    "baseline_time_et": "2026-06-11 20:38:25",
    "baseline_source_batch_id": "veewash_cleanup_rescrape-ac99501873604898a55d66a5a4710d84",
    "baseline_presence_run_id": 6,
    "latest_at_vendor_presence_source_batch_id": (
        "veewash_cleanup_rescrape-ac99501873604898a55d66a5a4710d84"
    ),
}
SELECTED_POST_BASELINE = date(2026, 6, 12)
T_BASELINE = datetime(2026, 6, 11, 20, 38, 25)
T_POST_SENT = datetime(2026, 6, 12, 9, 0)


class TestCleanVeeWashAtVendorBaseline:
    def test_uses_clean_scrape_seed_population(self):
        from unittest.mock import patch

        seed_bags = [f"SEED{i}" for i in range(10)]
        population = [
            {
                "bag_id": bid,
                "service_type": "WF",
                "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED,
                "currently_on_vendor_home": True,
                "portal_yet_to_process": True,
            }
            for bid in seed_bags
        ]
        pop_meta = {
            "available": True,
            "scope": "clean_veewash_baseline",
            "uses_clean_veewash_baseline": True,
            "clean_scrape_seed_count": 10,
            "post_baseline_sent_count": 0,
            "post_baseline_sent_total_count": 0,
            "carry_in_open_at_midnight_count": 0,
            "current_live_vendor_home_total": 10,
            "selected_day_at_vendor_total": 10,
            "contaminated_presence_rows_excluded_count": 2,
            "cross_org_excluded_bags": [],
            "baseline_snapshot_bag_ids": seed_bags,
            "same_day_arrival_bag_ids": [],
        }
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, pop_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={bid: [] for bid in seed_bags},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={bid: "WF" for bid in seed_bags},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=SELECTED_POST_BASELINE,
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        assert out["live"] is True
        assert out["scope"] == "clean_veewash_daily_et"
        assert out["uses_clean_veewash_baseline"] is True
        assert out["total"] == 10
        assert out["current_live_vendor_home_total"] == 10
        assert out["start_of_day_open_carry_in_count"] == 10
        assert out["daily_workload_total"] == 10
        meta = out.get("population_meta") or {}
        assert meta.get("clean_scrape_seed_count") == 10
        assert meta.get("contaminated_presence_rows_excluded_count") == 2

    def test_excludes_pre_baseline_carry_in(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "SEED1",
                "service_type": "WF",
                "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED,
                "currently_on_vendor_home": True,
            },
        ]
        pop_meta = {
            "available": True,
            "scope": "clean_veewash_baseline",
            "clean_scrape_seed_count": 1,
            "post_baseline_sent_count": 0,
            "carry_in_open_at_midnight_count": 0,
            "current_live_vendor_home_total": 1,
            "selected_day_at_vendor_total": 1,
            "cross_org_excluded_bags": [],
            "baseline_snapshot_bag_ids": ["SEED1"],
            "same_day_arrival_bag_ids": [],
        }
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, pop_meta),
        ) as mock_pop, patch(
            "backend.rinse_at_vendor_module._load_selected_day_at_vendor_population",
        ) as mock_legacy, patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={"SEED1": []},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"SEED1": "WF"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=SELECTED_POST_BASELINE,
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        mock_pop.assert_called_once()
        mock_legacy.assert_not_called()
        assert out["total"] == 1
        assert out["start_of_day_open_carry_in_count"] == 1
        assert out["daily_workload_total"] == 1

    def test_includes_post_baseline_sent_to_vendor(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "SEED1",
                "service_type": "WF",
                "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED,
                "currently_on_vendor_home": True,
            },
            {
                "bag_id": "NEWSENT1",
                "service_type": "HD",
                "population_inclusion": INCLUSION_POST_BASELINE_SENT,
                "currently_on_vendor_home": False,
            },
        ]
        pop_meta = {
            "available": True,
            "scope": "clean_veewash_baseline",
            "clean_scrape_seed_count": 1,
            "post_baseline_sent_count": 1,
            "post_baseline_sent_total_count": 1,
            "carry_in_open_at_midnight_count": 0,
            "current_live_vendor_home_total": 1,
            "selected_day_at_vendor_total": 2,
            "cross_org_excluded_bags": [],
            "baseline_snapshot_bag_ids": ["SEED1"],
            "same_day_arrival_bag_ids": ["NEWSENT1"],
        }
        events = {
            "SEED1": [],
            "NEWSENT1": [_ev("sent-to-vendor", T_POST_SENT)],
        }
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, pop_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value=events,
        ) as mock_events, patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"SEED1": "WF", "NEWSENT1": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=SELECTED_POST_BASELINE,
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        assert out["total"] == 2
        from backend.rinse_folding_et import naive_et_day_end_exclusive

        assert mock_events.call_args.kwargs["scanned_before"] == naive_et_day_end_exclusive(
            SELECTED_POST_BASELINE
        )
        assert "scanned_on_or_after" not in mock_events.call_args.kwargs
        assert any(r["bag_id"] == "NEWSENT1" for r in out["rows"])

    def test_excludes_washpro_only_bag_from_clean_baseline(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "VEEONLY1",
                "service_type": "HD",
                "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED,
                "currently_on_vendor_home": True,
            },
        ]
        pop_meta = {
            "available": True,
            "scope": "clean_veewash_baseline",
            "clean_scrape_seed_count": 1,
            "current_live_vendor_home_total": 1,
            "selected_day_at_vendor_total": 1,
            "baseline_snapshot_bag_ids": ["VEEONLY1"],
            "same_day_arrival_bag_ids": [],
            "cross_org_excluded_bags": [
                {
                    "bag_id": "3M8QVPGA2R",
                    "reason": "cross_org_washpro_owned",
                }
            ],
            "cross_org_excluded_from_live_presence": [
                {"bag_id": "3M8QVPGA2R"},
            ],
        }
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, pop_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={"VEEONLY1": []},
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"VEEONLY1": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=SELECTED_POST_BASELINE,
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        assert out["total"] == 1
        assert [r["bag_id"] for r in out["rows"]] == ["VEEONLY1"]
        excluded = (out.get("population_meta") or {}).get("cross_org_excluded_bags") or []
        assert any(e.get("bag_id") == "3M8QVPGA2R" for e in excluded)

    def test_baseline_gated_loader_uses_daily_baseline_seed_plus_same_day_arrivals(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_at_vendor_module import _load_baseline_gated_at_vendor_population
        from backend.rinse_shift_monitor_baseline import BASELINE_SELECTION_BEFORE_MIDNIGHT

        cursor = MagicMock()
        seed_rows = {
            f"B{i}": {
                "bag_id": f"B{i}",
                "service_type": "WF",
                "portal_yet_to_process": True,
                "active_presence": True,
            }
            for i in range(3)
        }
        baseline_run = {
            "id": 6,
            "source_batch_id": "veewash_cleanup_rescrape-ac99501873604898a55d66a5a4710d84",
            "finished_at": datetime(2026, 6, 11, 16, 38, 25),
            "rows_found": 10,
        }
        with patch(
            "backend.rinse_shift_monitor_baseline.select_daily_at_vendor_baseline_scrape",
            return_value=(baseline_run, BASELINE_SELECTION_BEFORE_MIDNIGHT),
        ), patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value=seed_rows,
        ) as mock_seed, patch(
            "backend.rinse_cleaner_ticket_presence.count_presence_run_snapshot_rows",
            return_value=3,
        ), patch(
            "backend.rinse_cleaner_ticket_presence.backfill_presence_run_snapshot_from_live_batch",
            return_value=0,
        ), patch(
            "backend.rinse_at_vendor_module._load_active_at_vendor_presence_by_bag",
            return_value={
                **seed_rows,
                "NEWSENT": {
                    "bag_id": "NEWSENT",
                    "service_type": "HD",
                    "portal_yet_to_process": True,
                    "active_presence": True,
                },
            },
        ), patch(
            "backend.rinse_at_vendor_module._load_sent_to_vendor_bag_id_sets_for_et_day",
            return_value=(set(), {"NEWSENT"}),
        ), patch(
            "backend.rinse_at_vendor_module._load_same_day_scrape_arrival_bag_ids",
            return_value=(set(), {}),
        ), patch(
            "backend.rinse_at_vendor_module._filter_cross_org_contaminated_bags",
            side_effect=lambda _c, _o, ids: (set(ids), []),
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._load_delivery_meta",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._count_contaminated_active_presence_rows",
            return_value=5,
        ), patch(
            "backend.rinse_presence_sync_status.evaluate_at_vendor_presence_freshness",
            return_value=(True, None, {"id": 99, "finished_at": datetime.utcnow()}),
        ):
            population, meta = _load_baseline_gated_at_vendor_population(
                cursor,
                3,
                selected_date_et=SELECTED_POST_BASELINE,
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        mock_seed.assert_called_once_with(
            cursor,
            3,
            presence_run_id=6,
        )
        assert len(population) == 4
        assert meta["start_of_day_carry_in_count"] == 3
        assert meta["baseline_seed_original_row_count"] == 10
        assert meta["baseline_seed_query_row_count"] == 3
        assert meta["baseline_seed_source"] == "presence_run_snapshot"
        assert meta["same_day_arrivals_from_sent_to_vendor_count"] == 1
        assert meta["selected_day_at_vendor_total"] == 4
        assert meta["baseline_selection_type"] == BASELINE_SELECTION_BEFORE_MIDNIGHT
        assert meta["contaminated_presence_rows_excluded_count"] == 5
        assert meta["baseline_seed_incomplete"] is True
        assert meta["daily_metrics_reliable"] is False
        assert meta["daily_metrics_status"] == "INCOMPLETE_BASELINE_SNAPSHOT"
        assert "3 of 10 rows available" in (meta.get("daily_metrics_warning") or "")

    def test_daily_workload_includes_seed_bags_no_longer_on_portal(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_at_vendor_module import _load_baseline_gated_at_vendor_population
        from backend.rinse_shift_monitor_baseline import BASELINE_SELECTION_BEFORE_MIDNIGHT

        cursor = MagicMock()
        seed_rows = {
            f"SEED{i}": {
                "bag_id": f"SEED{i}",
                "service_type": "WF",
                "portal_yet_to_process": True,
                "active_presence": False,
            }
            for i in range(72)
        }
        live_rows = {
            f"SEED{i}": {
                "bag_id": f"SEED{i}",
                "service_type": "WF",
                "active_presence": True,
                "raw_row_json": {
                    "steps_in_cleaning_process": (
                        "In progress at vendor"
                        if i < 17
                        else "Complete — ready for pickup"
                    ),
                },
            }
            for i in range(20)
        }
        baseline_run = {
            "id": 28,
            "source_batch_id": "run28-batch",
            "finished_at": datetime(2026, 6, 13, 0, 5, 0),
            "rows_found": 72,
        }
        with patch(
            "backend.rinse_shift_monitor_baseline.select_daily_at_vendor_baseline_scrape",
            return_value=(baseline_run, BASELINE_SELECTION_BEFORE_MIDNIGHT),
        ), patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value=seed_rows,
        ), patch(
            "backend.rinse_cleaner_ticket_presence.count_presence_run_snapshot_rows",
            return_value=72,
        ), patch(
            "backend.rinse_cleaner_ticket_presence.backfill_presence_run_snapshot_from_live_batch",
            return_value=0,
        ), patch(
            "backend.rinse_at_vendor_module._load_active_at_vendor_presence_by_bag",
            return_value=live_rows,
        ), patch(
            "backend.rinse_at_vendor_module._load_sent_to_vendor_bag_id_sets_for_et_day",
            return_value=(set(), set()),
        ), patch(
            "backend.rinse_at_vendor_module._load_same_day_scrape_arrival_bag_ids",
            return_value=(set(), {}),
        ), patch(
            "backend.rinse_at_vendor_module._filter_cross_org_contaminated_bags",
            side_effect=lambda _c, _o, ids: (set(ids), []),
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._load_delivery_meta",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._count_contaminated_active_presence_rows",
            return_value=0,
        ), patch(
            "backend.rinse_presence_sync_status.evaluate_at_vendor_presence_freshness",
            return_value=(True, None, {"id": 30, "finished_at": datetime.utcnow()}),
        ):
            population, meta = _load_baseline_gated_at_vendor_population(
                cursor,
                3,
                selected_date_et=date(2026, 6, 13),
                baseline_ctx=CLEAN_BASELINE_CTX,
            )

        assert meta["selected_day_at_vendor_total"] == 72
        assert meta["current_live_vendor_home_total"] == 20
        assert meta["current_portal_snapshot_total"] == 20
        assert meta["portal_snapshot_yet_to_process"] == 17
        assert meta["portal_snapshot_yet_to_process_reliable"] is True
        assert meta["portal_snapshot_yet_to_process_source"] == "portal_cleaning_steps"
        assert len(population) == 72
        gone = [p for p in population if not p.get("currently_on_vendor_home")]
        assert len(gone) == 52


class TestCrossDayCompletionAttribution:
    def test_baseline_seed_completed_before_day_start_classified(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_COMPLETED_BEFORE_DAY_START,
            _classify_baseline_seed_bag,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
            _ev("move-bag", datetime(2026, 6, 12, 18, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 12, 20, 0)),
            _ev("garments-reviewed", datetime(2026, 6, 12, 20, 30)),
            _ev("weight-entry", datetime(2026, 6, 12, 21, 0)),
        ]
        daily_class, signal, comp_ts, _ = _classify_baseline_seed_bag(
            events,
            service_type="WF",
            selected_date_et=date(2026, 6, 13),
        )
        assert daily_class == DAILY_CLASS_COMPLETED_BEFORE_DAY_START
        assert signal == "post_garments_reviewed_weight_entry"
        assert comp_ts == datetime(2026, 6, 12, 21, 0)

    def test_baseline_seed_resend_today_opens_new_cycle(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_OPEN_AT_DAY_START,
            _classify_baseline_seed_bag,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
            _ev("weight-entry", datetime(2026, 6, 12, 20, 0)),
            _ev("weight-entry", datetime(2026, 6, 12, 21, 0)),
            _ev("sent-to-vendor", datetime(2026, 6, 13, 5, 11)),
            _ev("weight-entry", datetime(2026, 6, 13, 15, 37)),
            _ev("weight-entry", datetime(2026, 6, 13, 15, 37)),
        ]
        daily_class, signal, comp_ts, sent_ts = _classify_baseline_seed_bag(
            events,
            service_type="WF",
            selected_date_et=date(2026, 6, 13),
        )
        assert daily_class == DAILY_CLASS_OPEN_AT_DAY_START
        assert signal is None
        assert comp_ts is None
        assert sent_ts == datetime(2026, 6, 13, 5, 11)

    def test_baseline_seed_departed_before_day_start_excluded_from_carry_in(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_DEPARTED_BEFORE_DAY_START,
            _classify_baseline_seed_bag,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 20, 5, 23)),
        ]
        departures = [
            _ev("received-from-vendor", datetime(2026, 6, 20, 18, 1)),
            _ev("actual-delivery", datetime(2026, 6, 22, 22, 18)),
        ]
        daily_class, signal, comp_ts, sent_ts = _classify_baseline_seed_bag(
            events,
            service_type="HD",
            selected_date_et=date(2026, 6, 26),
            departure_events=departures,
        )
        assert daily_class == DAILY_CLASS_DEPARTED_BEFORE_DAY_START
        assert signal is None
        assert comp_ts is None
        assert sent_ts == datetime(2026, 6, 20, 5, 23)

    def test_baseline_seed_same_day_resend_not_treated_as_departed(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_OPEN_AT_DAY_START,
            _classify_baseline_seed_bag,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
            _ev("received-from-vendor", datetime(2026, 6, 12, 22, 0)),
            _ev("sent-to-vendor", datetime(2026, 6, 13, 5, 11)),
        ]
        daily_class, _, _, sent_ts = _classify_baseline_seed_bag(
            events,
            service_type="WF",
            selected_date_et=date(2026, 6, 13),
            departure_events=[_ev("received-from-vendor", datetime(2026, 6, 12, 22, 0))],
        )
        assert daily_class == DAILY_CLASS_OPEN_AT_DAY_START
        assert sent_ts == datetime(2026, 6, 13, 5, 11)

    def test_completion_counts_on_completion_et_date_only(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_COMPLETED_DURING_SELECTED_DAY,
            DAILY_CLASS_PENDING_AS_OF_SELECTED_DAY_END_OR_NOW,
            _build_row,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
            _ev("move-bag", datetime(2026, 6, 12, 18, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 12, 20, 0)),
            _ev("garments-reviewed", datetime(2026, 6, 12, 20, 30)),
            _ev("weight-entry", datetime(2026, 6, 12, 21, 0)),
        ]
        june12_row = _build_row(
            bag_id="CROSS1",
            meta={"service_type": "WF"},
            events=events,
            selected_date_et=date(2026, 6, 12),
            as_of_end=naive_et_day_end_inclusive(date(2026, 6, 12)),
            daily_et_attribution=True,
        )
        assert june12_row["daily_classification"] == DAILY_CLASS_COMPLETED_DURING_SELECTED_DAY
        assert june12_row["at_vendor_status"] == AV_STATUS_COMPLETED

        june13_row = _build_row(
            bag_id="CROSS1",
            meta={"service_type": "WF"},
            events=events,
            selected_date_et=date(2026, 6, 13),
            as_of_end=naive_et_day_end_inclusive(date(2026, 6, 13)),
            daily_et_attribution=True,
        )
        assert june13_row["daily_classification"] == DAILY_CLASS_PENDING_AS_OF_SELECTED_DAY_END_OR_NOW
        assert june13_row["at_vendor_status"] == AV_STATUS_PENDING

    def test_repeat_trip_after_et_day_completion_stays_completed_in_days_load(self):
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_COMPLETED_DURING_SELECTED_DAY,
            _apply_off_portal_workload_row_filter,
        )

        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 5, 5, 0)),
            _ev("move-bag", datetime(2026, 7, 5, 5, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 7, 5, 6, 0)),
            _ev("garments-reviewed", datetime(2026, 7, 5, 8, 0)),
            _ev("weight-entry", datetime(2026, 7, 5, 9, 0), user_name="Jennifer"),
            _ev("received-from-vendor", datetime(2026, 7, 5, 11, 0)),
            _ev("sent-to-vendor", datetime(2026, 7, 5, 14, 0)),
        ]
        row = _build_row(
            bag_id="TRIP1",
            meta={"service_type": "WF"},
            events=events,
            selected_date_et=date(2026, 7, 5),
            as_of_end=naive_et_day_end_inclusive(date(2026, 7, 5)),
            daily_et_attribution=True,
        )
        assert row["daily_classification"] == DAILY_CLASS_COMPLETED_DURING_SELECTED_DAY
        assert row["at_vendor_status"] == AV_STATUS_COMPLETED
        assert row["completed_during_et_day"] is True

        kept, meta = _apply_off_portal_workload_row_filter(
            [row],
            off_portal_terminal_ids={"TRIP1"},
            portal_scrape_rejected_ids=set(),
        )
        assert len(kept) == 1
        assert meta["off_portal_completed_retained_in_days_load"] == ["TRIP1"]

    def test_clean_baseline_excludes_completed_before_day_start_from_workload(self):
        from unittest.mock import patch

        population = [
            {
                "bag_id": "SEEDOPEN",
                "service_type": "WF",
                "population_inclusion": "daily_baseline_scrape_seed",
            },
            {
                "bag_id": "SEEDDONE",
                "service_type": "WF",
                "population_inclusion": "daily_baseline_scrape_seed",
            },
            {
                "bag_id": "NEW1",
                "service_type": "HD",
                "population_inclusion": "same_day_sent_to_vendor",
            },
        ]
        population_meta = {
            "available": True,
            "baseline_snapshot_bag_ids": ["SEEDOPEN", "SEEDDONE"],
            "same_day_arrival_bag_ids": ["NEW1"],
            "current_live_vendor_home_total": 2,
            "daily_metrics_reliable": True,
        }
        open_events = [_ev("sent-to-vendor", datetime(2026, 6, 13, 1, 0))]
        done_events = [
            _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
            _ev("move-bag", datetime(2026, 6, 12, 18, 30), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 12, 20, 0)),
            _ev("garments-reviewed", datetime(2026, 6, 12, 20, 30)),
            _ev("weight-entry", datetime(2026, 6, 12, 21, 0)),
        ]
        new_events = [_ev("sent-to-vendor", datetime(2026, 6, 13, 10, 0))]
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, population_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={
                "SEEDOPEN": open_events,
                "SEEDDONE": done_events,
                "NEW1": new_events,
            },
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"SEEDOPEN": "WF", "SEEDDONE": "WF", "NEW1": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._load_completed_before_day_start_still_present",
            return_value=([], set()),
        ), patch(
            "backend.rinse_at_vendor_module._load_off_portal_registry_terminal_bag_ids",
            return_value=set(),
        ), patch(
            "backend.rinse_employee_completed_bags.build_employee_completed_bags_today",
            return_value={"employees": [], "reconciliation": {"ok": True}, "reconciliation_banner": {}},
        ), patch(
            "backend.rinse_simple_shift_performance._load_bag_metadata",
            return_value={},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=date(2026, 6, 13),
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        assert out["baseline_snapshot_count"] == 2
        assert out["completed_before_day_start_count"] == 1
        assert out["start_of_day_open_carry_in_count"] == 1
        assert out["daily_workload_total"] == 2
        assert out["total"] == 2
        assert out["pending"] + out["completed"] == 2
        assert "SEEDDONE" not in [r["bag_id"] for r in out["rows"]]
        assert out["completed_before_day_start_count"] + out["start_of_day_open_carry_in_count"] == 2

    def test_bags_completed_today_includes_repeat_trip_resend_completion(self):
        from backend.rinse_at_vendor_module import _latest_sent_to_vendor_ts
        from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start

        selected = date(2026, 6, 25)
        day_start = naive_et_day_start(selected)
        day_end_excl = naive_et_day_end_exclusive(selected)
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 19, 4, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 10, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 11, 0)),
            _ev("sent-to-vendor", datetime(2026, 6, 25, 5, 11)),
            _ev("move-bag", datetime(2026, 6, 25, 5, 40), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 25, 7, 37)),
            _ev("garments-reviewed", datetime(2026, 6, 25, 15, 36)),
            _ev("weight-entry", datetime(2026, 6, 25, 15, 37)),
        ]
        resend_ts = _latest_sent_to_vendor_ts(
            events, on_or_after=day_start, before=day_end_excl
        )
        assert resend_ts == datetime(2026, 6, 25, 5, 11)

        row = _build_row(
            bag_id="73NBRCJBHJ",
            meta={"service_type": "WF"},
            events=events,
            selected_date_et=selected,
            as_of_end=naive_et_day_end_inclusive(selected),
            completion_window_start=day_start,
        )
        assert row["at_vendor_status"] == AV_STATUS_COMPLETED
        assert row["completion_time"] == datetime(2026, 6, 25, 15, 37).isoformat()

    def test_still_present_skips_bags_with_same_day_sent_to_vendor_reset(self):
        from backend.rinse_at_vendor_module import _latest_sent_to_vendor_ts
        from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start

        selected = date(2026, 6, 25)
        day_start = naive_et_day_start(selected)
        day_end_excl = naive_et_day_end_exclusive(selected)
        prior_completed_cycle = [
            _ev("sent-to-vendor", datetime(2026, 6, 19, 4, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 10, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 11, 0)),
            _ev("sent-to-vendor", datetime(2026, 6, 25, 5, 9)),
        ]
        assert (
            _latest_sent_to_vendor_ts(
                prior_completed_cycle,
                on_or_after=day_start,
                before=day_end_excl,
            )
            is not None
        )
        # Same-day re-send must bypass stale completed-before-day-start carry logic.
        from backend.rinse_at_vendor_module import (
            DAILY_CLASS_OPEN_AT_DAY_START,
            _classify_baseline_seed_bag,
        )

        daily_class, _, _, _ = _classify_baseline_seed_bag(
            prior_completed_cycle,
            service_type="WF",
            selected_date_et=selected,
        )
        assert daily_class == DAILY_CLASS_OPEN_AT_DAY_START
    def test_resolve_delivery_fields_presence_run_snapshot_uses_estimated_delivery_date(self):
        edd, texts, source = resolve_delivery_fields(
            {
                "delivery_source": "presence_run_snapshot",
                "estimated_delivery_date": date(2026, 6, 15),
                "raw_row_json": {"estimated_delivery_text": "Mon 06/15/2026"},
                "customer_name": "Amber Webster",
            }
        )
        assert source == "presence_run_snapshot"
        assert edd == date(2026, 6, 15)
        assert "Mon 06/15/2026" in texts

    def test_enrich_presence_delivery_meta_backfills_missing_edd(self):
        meta = _enrich_presence_delivery_meta(
            {"delivery_source": "presence_run_snapshot", "estimated_delivery_date": None},
            {"estimated_delivery_date": date(2026, 6, 14), "rush_flag": "NON-RUSH"},
        )
        assert meta["estimated_delivery_date"] == date(2026, 6, 14)
        assert meta["rush_flag"] == "NON-RUSH"

    def test_build_row_non_rush_when_snapshot_edd_after_selected_day(self):
        row = _build_row(
            bag_id="9FUW30XSFQ",
            meta={
                "delivery_source": "presence_run_snapshot",
                "estimated_delivery_date": date(2026, 6, 15),
                "service_type": "HD",
                "raw_row_json": {"rush_type": "NON-RUSH"},
            },
            events=[_ev("sent-to-vendor", datetime(2026, 6, 13, 10, 0))],
            selected_date_et=date(2026, 6, 13),
            as_of_end=naive_et_day_end_inclusive(date(2026, 6, 13)),
            daily_et_attribution=True,
        )
        assert row["rush_bucket"] == AV_NON_RUSH
        assert row["estimated_delivery_date"] == "2026-06-15"
        assert "Non-Rush because EDD" in (row.get("rush_reason") or "")


class TestDaysLoadOffPortalFilter:
    """Day's Load must stay stable when completed bags leave the vendor portal."""

    def test_apply_filter_retains_off_portal_completed(self):
        from backend.rinse_at_vendor_module import _apply_off_portal_workload_row_filter

        rows = [
            {"bag_id": "DONEOFF", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]},
            {"bag_id": "STALE", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "LIVE", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
        ]
        kept, meta = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"DONEOFF", "STALE"},
            portal_scrape_rejected_ids=set(),
        )
        kept_ids = {r["bag_id"] for r in kept}
        assert kept_ids == {"DONEOFF", "LIVE"}
        assert meta["off_portal_completed_retained_in_days_load"] == ["DONEOFF"]
        assert meta["off_portal_stale_pending_excluded"] == ["STALE"]

    def test_apply_filter_excludes_portal_scrape_rejected_regardless_of_status(self):
        from backend.rinse_at_vendor_module import _apply_off_portal_workload_row_filter

        rows = [
            {"bag_id": "REJECTED", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]},
        ]
        kept, meta = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"REJECTED"},
            portal_scrape_rejected_ids={"REJECTED"},
        )
        assert kept == []
        assert meta["portal_scrape_rejected_excluded"] == ["REJECTED"]

    def test_merge_does_not_reinject_portal_scrape_rejected_pending(self):
        from backend.rinse_at_vendor_module import _merge_operational_active_pending_rows
        from backend.rinse_workload_ledger import MEMBERSHIP_NEW_TODAY

        pre = {
            "PHANTOM": {
                "bag_id": "PHANTOM",
                "at_vendor_status": AV_STATUS_PENDING,
                "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING],
                "customer_name": "Stale Customer 0",
            }
        }
        kept = _merge_operational_active_pending_rows(
            rows=[{"bag_id": "LIVE", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]}],
            pre_filter_rows_by_bag=pre,
            active_bag_ids={"PHANTOM", "LIVE"},
            off_portal_filter_meta={
                "off_portal_stale_pending_excluded": [],
                "portal_scrape_rejected_excluded": ["PHANTOM"],
            },
            membership_tiers_by_bag={"PHANTOM": MEMBERSHIP_NEW_TODAY, "LIVE": MEMBERSHIP_NEW_TODAY},
        )
        assert [r["bag_id"] for r in kept] == ["LIVE"]

    def test_merge_reinjects_stale_pending_but_not_scrape_rejected(self):
        from backend.rinse_at_vendor_module import _merge_operational_active_pending_rows
        from backend.rinse_workload_ledger import MEMBERSHIP_CARRYOVER_YESTERDAY

        pre = {
            "STALE": {
                "bag_id": "STALE",
                "at_vendor_status": AV_STATUS_PENDING,
                "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING],
            },
            "REJECTED": {
                "bag_id": "REJECTED",
                "at_vendor_status": AV_STATUS_PENDING,
                "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING],
            },
        }
        kept = _merge_operational_active_pending_rows(
            rows=[],
            pre_filter_rows_by_bag=pre,
            active_bag_ids={"STALE", "REJECTED"},
            off_portal_filter_meta={
                "off_portal_stale_pending_excluded": ["STALE", "REJECTED"],
                "portal_scrape_rejected_excluded": ["REJECTED"],
            },
            membership_tiers_by_bag={
                "STALE": MEMBERSHIP_CARRYOVER_YESTERDAY,
                "REJECTED": MEMBERSHIP_CARRYOVER_YESTERDAY,
            },
        )
        assert [r["bag_id"] for r in kept] == ["STALE"]
        assert kept[0].get("off_portal_operational_pending") is True

    def test_pending_completed_disjoint_invariant(self):
        from backend.rinse_at_vendor_module import validate_pending_completed_disjoint

        validate_pending_completed_disjoint(
            {
                "rows": [
                    {"bag_id": "A", "at_vendor_status": AV_STATUS_PENDING, "module_tags": [MOD_AT_VENDOR_PENDING]},
                    {"bag_id": "B", "at_vendor_status": AV_STATUS_COMPLETED, "module_tags": [MOD_AT_VENDOR_COMPLETED]},
                ]
            }
        )
        try:
            validate_pending_completed_disjoint(
                {
                    "rows": [
                        {
                            "bag_id": "X",
                            "at_vendor_status": AV_STATUS_PENDING,
                            "module_tags": [MOD_AT_VENDOR_PENDING, MOD_AT_VENDOR_COMPLETED],
                            "completed_during_et_day": True,
                        }
                    ]
                }
            )
            raise AssertionError("expected conflict")
        except AssertionError as exc:
            assert "Pending/Completed conflict" in str(exc)

    def test_scrape_rejected_not_operational_pending_invariant(self):
        from backend.rinse_at_vendor_module import validate_no_scrape_rejected_operational_pending

        validate_no_scrape_rejected_operational_pending(
            {
                "rows": [
                    {"bag_id": "OK", "at_vendor_status": AV_STATUS_PENDING, "module_tags": [MOD_AT_VENDOR_PENDING]},
                ]
            },
            portal_scrape_rejected_ids={"GONE"},
        )
        try:
            validate_no_scrape_rejected_operational_pending(
                {
                    "rows": [
                        {
                            "bag_id": "GONE",
                            "at_vendor_status": AV_STATUS_PENDING,
                            "module_tags": [MOD_AT_VENDOR_PENDING],
                            "off_portal_operational_pending": True,
                        }
                    ]
                },
                portal_scrape_rejected_ids={"GONE"},
            )
            raise AssertionError("expected scrape-rejected pending")
        except AssertionError as exc:
            assert "Portal-scrape rejected" in str(exc)

    def test_apply_filter_excludes_off_portal_stale_rush_wf_pending(self):
        from backend.rinse_at_vendor_module import _apply_off_portal_workload_row_filter

        rows = [
            {"bag_id": "PHANTOM", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "REAL", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
        ]
        kept, meta = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"PHANTOM"},
            portal_scrape_rejected_ids=set(),
        )
        assert [r["bag_id"] for r in kept] == ["REAL"]
        assert meta["off_portal_stale_pending_excluded"] == ["PHANTOM"]

    def test_days_load_unchanged_when_pending_completes_off_portal(self):
        from backend.rinse_at_vendor_module import _apply_off_portal_workload_row_filter

        pending_kept, _ = _apply_off_portal_workload_row_filter(
            [{"bag_id": "BAG1", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]}],
            off_portal_terminal_ids=set(),
            portal_scrape_rejected_ids=set(),
        )
        completed_kept, meta = _apply_off_portal_workload_row_filter(
            [{"bag_id": "BAG1", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]}],
            off_portal_terminal_ids={"BAG1"},
            portal_scrape_rejected_ids=set(),
        )
        assert len(pending_kept) == 1
        assert len(completed_kept) == 1
        assert meta["off_portal_completed_retained_in_days_load"] == ["BAG1"]


def _days_load_module_from_rows(rows: list[dict]) -> dict:
    pending = sum(
        1 for r in rows if MOD_AT_VENDOR_PENDING in (r.get("module_tags") or [])
    )
    completed = sum(
        1 for r in rows if MOD_AT_VENDOR_COMPLETED in (r.get("module_tags") or [])
    )
    total = len(rows)
    return {
        "total": total,
        "days_load_total": total,
        "daily_workload_total": total,
        "pending": pending,
        "completed": completed,
        "completed_today_count": completed,
        "rows": rows,
        "total_equals_pending_plus_completed": total == pending + completed,
    }


class TestDaysLoadInvariant:
    """Permanent Shift Monitor invariant: Day's Load == Pending + Completed Today."""

    def test_invariant_formula_on_module_output(self):
        rows = [
            {"bag_id": "P1", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "P2", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "C1", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]},
        ]
        validate_days_load_invariant(_days_load_module_from_rows(rows))

    def test_completing_bag_never_decreases_days_load(self):
        pending_row = {
            "bag_id": "BAG1",
            "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING],
        }
        completed_row = {
            "bag_id": "BAG1",
            "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED],
        }
        before = _days_load_module_from_rows([pending_row, {"bag_id": "P2", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]}])
        after = _days_load_module_from_rows([completed_row, {"bag_id": "P2", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]}])
        validate_days_load_invariant(before)
        validate_days_load_invariant(after)
        assert before["days_load_total"] == after["days_load_total"]
        assert before["pending"] == after["pending"] + 1
        assert after["completed"] == before["completed"] + 1

    def test_off_portal_removal_never_decreases_days_load_for_completed(self):
        rows = [
            {"bag_id": "OPEN", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "DONE", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]},
        ]
        before = _days_load_module_from_rows(rows)
        kept, _ = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"DONE"},
            portal_scrape_rejected_ids=set(),
        )
        after = _days_load_module_from_rows(kept)
        validate_days_load_invariant(before)
        validate_days_load_invariant(after)
        assert before["days_load_total"] == after["days_load_total"]
        assert "DONE" in [r["bag_id"] for r in kept]

    def test_phantom_pending_off_portal_excluded_and_invariant_holds(self):
        rows = [
            {"bag_id": "PHANTOM", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "REAL", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
        ]
        kept, meta = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"PHANTOM"},
            portal_scrape_rejected_ids=set(),
        )
        out = _days_load_module_from_rows(kept)
        validate_days_load_invariant(out)
        assert out["days_load_total"] == 1
        assert meta["off_portal_stale_pending_excluded"] == ["PHANTOM"]

    def test_pre_midnight_completed_excluded_invariant_on_baseline_module(self):
        from unittest.mock import patch

        population = [
            {"bag_id": "SEEDOPEN", "service_type": "WF", "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED},
            {"bag_id": "SEEDDONE", "service_type": "WF", "population_inclusion": INCLUSION_CLEAN_SCRAPE_SEED},
            {"bag_id": "NEW1", "service_type": "HD", "population_inclusion": INCLUSION_NEW_SENT},
        ]
        population_meta = {
            "available": True,
            "baseline_snapshot_bag_ids": ["SEEDOPEN", "SEEDDONE"],
            "same_day_arrival_bag_ids": ["NEW1"],
            "current_live_vendor_home_total": 2,
            "daily_metrics_reliable": True,
        }
        with patch(
            "backend.rinse_at_vendor_module._load_baseline_gated_at_vendor_population",
            return_value=(population, population_meta),
        ), patch(
            "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
            return_value={
                "SEEDOPEN": [_ev("sent-to-vendor", datetime(2026, 6, 13, 1, 0))],
                "SEEDDONE": [
                    _ev("sent-to-vendor", datetime(2026, 6, 12, 18, 0)),
                    _ev("move-bag", datetime(2026, 6, 12, 18, 30), rack="VeeWash Dirty"),
                    _ev("weight-entry", datetime(2026, 6, 12, 20, 0)),
                    _ev("garments-reviewed", datetime(2026, 6, 12, 20, 30)),
                    _ev("weight-entry", datetime(2026, 6, 12, 21, 0)),
                ],
                "NEW1": [_ev("sent-to-vendor", datetime(2026, 6, 13, 10, 0))],
            },
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={"SEEDOPEN": "WF", "SEEDDONE": "WF", "NEW1": "HD"},
        ), patch(
            "backend.rinse_at_vendor_module._load_prior_edd_from_batches_bulk",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._load_completed_before_day_start_still_present",
            return_value=([], set()),
        ), patch(
            "backend.rinse_at_vendor_module._load_off_portal_registry_terminal_bag_ids",
            return_value=set(),
        ), patch(
            "backend.rinse_employee_completed_bags.build_employee_completed_bags_today",
            return_value={"employees": [], "reconciliation": {"ok": True}, "reconciliation_banner": {}},
        ):
            out = build_at_vendor_module(
                object(),
                3,
                selected_date_et=date(2026, 6, 13),
                baseline_ctx=CLEAN_BASELINE_CTX,
            )
        validate_days_load_invariant(out)
        assert "SEEDDONE" not in [r["bag_id"] for r in out["rows"]]
        assert out["days_load_total"] == 2

    def test_repeat_trip_resend_counts_in_days_load_invariant(self):
        from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start

        selected = date(2026, 6, 25)
        day_start = naive_et_day_start(selected)
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 19, 4, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 10, 0)),
            _ev("weight-entry", datetime(2026, 6, 19, 11, 0)),
            _ev("sent-to-vendor", datetime(2026, 6, 25, 5, 11)),
            _ev("move-bag", datetime(2026, 6, 25, 5, 40), rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 6, 25, 7, 37)),
            _ev("garments-reviewed", datetime(2026, 6, 25, 15, 36)),
            _ev("weight-entry", datetime(2026, 6, 25, 15, 37)),
        ]
        row = _build_row(
            bag_id="73NBRCJBHJ",
            meta={"service_type": "WF"},
            events=events,
            selected_date_et=selected,
            as_of_end=naive_et_day_end_inclusive(selected),
            completion_window_start=day_start,
        )
        assert MOD_AT_VENDOR_COMPLETED in row.get("module_tags", [])
        validate_days_load_invariant(_days_load_module_from_rows([row]))

    def test_portal_scrape_rejected_reduces_days_load(self):
        rows = [
            {"bag_id": "GOOD", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_PENDING]},
            {"bag_id": "BAD", "module_tags": [MOD_AT_VENDOR_TOTAL, MOD_AT_VENDOR_COMPLETED]},
        ]
        kept, meta = _apply_off_portal_workload_row_filter(
            rows,
            off_portal_terminal_ids={"BAD"},
            portal_scrape_rejected_ids={"BAD"},
        )
        out = _days_load_module_from_rows(kept)
        validate_days_load_invariant(out)
        assert out["days_load_total"] == 1
        assert meta["portal_scrape_rejected_excluded"] == ["BAD"]
