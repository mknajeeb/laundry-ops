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
    INCLUSION_NEW_SENT,
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
)
from backend.rinse_folding_et import naive_et_day_end_inclusive
from backend.rinse_shift_monitor_modules import build_shift_monitor_modules


def _ev(purpose: str, ts: datetime, *, ev_id: int = 1, scan_index: int = 1, rack: str = "") -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": scan_index,
        "rack": rack,
        "user_name": "Tester",
    }


T0 = datetime(2026, 6, 10, 4, 0)
T1 = datetime(2026, 6, 10, 5, 0)
T2 = datetime(2026, 6, 10, 6, 0)
T3 = datetime(2026, 6, 10, 7, 0)
SELECTED = date(2026, 6, 10)


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
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_second_weight_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("weight-entry", T1), _ev("weight-entry", T2)]
        status, signal, comp_ts, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "weight-entry"
        assert comp_ts == T2

    def test_clean_rack_does_not_complete(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("move-bag", T2, rack="VeeWash Clean"),
        ]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_received_from_vendor_does_not_complete(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("received-from-vendor", T2),
        ]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="WF", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None


class TestHDCompletion:
    def test_first_add_photos_pending(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1)]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_PENDING
        assert signal is None

    def test_second_add_photos_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("add-photos", T1), _ev("add-photos", T2)]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "second add-photos"

    def test_complete_cleaning_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("complete-cleaning", T1)]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED
        assert signal == "complete-cleaning"

    def test_garments_reviewed_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("garments-reviewed", T1)]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED

    def test_assembly_printed_ct_completes(self):
        events = [_ev("sent-to-vendor", T0), _ev("assembly-printed-ct", T1)]
        status, signal, _, _ = _evaluate_bag_as_of(events, service_type="HD", as_of_end=naive_et_day_end_inclusive(SELECTED))
        assert status == AV_STATUS_COMPLETED


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
            _ev("weight-entry", datetime(2026, 6, 11, 5, 0)),
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
            _ev("weight-entry", datetime(2026, 6, 8, 5, 0)),
            _ev("weight-entry", datetime(2026, 6, 8, 6, 0)),
        ]
        prior_end = naive_et_day_end_inclusive(date(2026, 6, 9))
        anchor = datetime(2026, 6, 8, 4, 0)
        status, _, _, _ = _evaluate_bag_as_of(
            events, service_type="WF", as_of_end=prior_end, anchor_ts_override=anchor
        )
        assert status == AV_STATUS_COMPLETED

    def test_resend_same_day_resets_completion_anchor(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 8, 4, 0)),
            _ev("weight-entry", datetime(2026, 6, 8, 5, 0)),
            _ev("weight-entry", datetime(2026, 6, 8, 6, 0)),
            _ev("sent-to-vendor", T0),
        ]
        day_end = naive_et_day_end_inclusive(SELECTED)
        status, _, _, sent_ts = _evaluate_bag_as_of(
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
