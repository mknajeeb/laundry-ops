"""Shared mocks for Current Facility / Due Today snapshot payload tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional, Tuple
from unittest.mock import patch


def unified_at_from_pending(pending_response: dict) -> Tuple[dict, dict]:
    rows: dict = {}
    for row in pending_response.get("rows") or []:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if not (
            row.get("in_active_staging")
            or row.get("registry_supplement")
            or row.get("at_vendor_presence")
            or row.get("presence_source")
        ):
            continue
        src = "orders_staging" if row.get("in_active_staging") else "registry"
        if row.get("at_vendor_presence") or row.get("presence_source"):
            src = "at_vendor_presence"
        rows[bid] = {**row, "bag_id": bid, "source_seen_in": [src]}
    return rows, {
        "unified_total": len(rows),
        "staging_count": sum(1 for r in rows.values() if r.get("in_active_staging")),
        "registry_supplement_count": sum(1 for r in rows.values() if r.get("registry_supplement")),
        "at_vendor_presence_count": sum(
            1 for r in rows.values() if r.get("at_vendor_presence") or r.get("presence_source")
        ),
    }


def unified_due_from_pending(pending_response: dict, today: date) -> Tuple[dict, dict]:
    rows: dict = {}
    for row in pending_response.get("rows") or []:
        if row.get("date_clean") != today:
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        src = "orders_staging" if row.get("in_active_staging") else "registry"
        rows[bid] = {**row, "bag_id": bid, "date_clean": today, "source_seen_in": [src]}
    return rows, {"unified_due_today_total": len(rows), "rfv_incoming_count": 0}


_EMPTY_PRESENCE_META = {
    "at_vendor_active": 0,
    "rfv_active": 0,
    "portal_list_available": False,
}


@contextmanager
def patch_unified_loaders_from_pending(pending_response: dict, *, today: Optional[date] = None):
    at_rows, at_meta = unified_at_from_pending(pending_response)
    due_rows, due_meta = (
        unified_due_from_pending(pending_response, today)
        if today is not None
        else ({}, {"unified_due_today_total": 0, "rfv_incoming_count": 0})
    )

    def _live_at(cursor, org, *, target_date, baseline_ctx):
        from backend.rinse_current_facility_snapshot import _merge_row

        rows: dict = {}
        for bid, row in at_rows.items():
            if not row.get("in_active_staging"):
                continue
            _merge_row(rows, {**row, "baseline_inclusion_reason": "test"}, source="orders_staging")
        meta = {**at_meta, "live_baseline": True, "at_vendor_scrape_ready": True}
        return rows, meta

    def _live_due(cursor, org, today, *, baseline_ctx, live_at_facility, live_rfv_rows):
        from backend.rinse_current_facility_snapshot import _merge_row, parse_record_date

        rows: dict = {}
        for bid, row in {**live_at_facility, **due_rows}.items():
            dc = parse_record_date(row.get("date_clean"))
            if dc == today:
                _merge_row(rows, row, source="orders_staging")
        return rows, {"unified_due_today_total": len(rows), "live_baseline": True}

    _baseline_off = {"active": False}
    _baseline_on = {
        "active": True,
        "shift_monitor_baseline_start_at_et": "2020-01-01 00:00:00",
        "baseline_source": "manual_reset",
        "baseline_note": "test",
        "timezone": "America/New_York",
    }
    _baseline_ctx = {
        "active": True,
        "shift_monitor_baseline_start_at_et": "2020-01-01 00:00:00",
        "baseline_source": "manual_reset",
        "baseline_note": "test",
        "timezone": "America/New_York",
        "baseline_start_naive_et": datetime(2020, 1, 1),
        "at_vendor_scrape_ready": True,
        "rfv_scrape_ready": True,
        "needs_refresh": False,
    }

    with patch(
        "backend.rinse_current_facility_snapshot.load_unified_at_facility_population",
        return_value=(at_rows, at_meta),
    ), patch(
        "backend.rinse_current_facility_snapshot.load_unified_due_today_population",
        return_value=(due_rows, due_meta),
    ), patch(
        "backend.rinse_current_facility_snapshot.load_portal_vendor_home_counts",
        return_value=(None, dict(_EMPTY_PRESENCE_META), [], []),
    ), patch(
        "backend.rinse_current_facility_snapshot.load_presence_edd_by_bag",
        return_value={},
    ), patch(
        "backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline",
        return_value=_baseline_on,
    ), patch(
        "backend.rinse_shift_monitor_baseline.build_baseline_context",
        return_value=_baseline_ctx,
    ), patch(
        "backend.rinse_shift_monitor_baseline.load_live_at_facility_population",
        side_effect=_live_at,
    ), patch(
        "backend.rinse_shift_monitor_baseline.load_live_due_today_population",
        side_effect=_live_due,
    ), patch(
        "backend.rinse_ready_for_vendor_queue.build_ready_for_vendor_queue",
        return_value={
            "section": {
                "live": True,
                "total": 0,
                "rows": [],
                "uses_scans": False,
                "snapshot_only": True,
            },
            "rows": [],
            "bag_ids": set(),
            "meta": {"uses_scans": False},
            "legacy_incoming_rows": [],
        },
    ), patch(
        "backend.rinse_shift_monitor_baseline.latest_at_vendor_scrape_after_baseline",
        return_value={"id": 1, "finished_at": datetime(2026, 6, 10, 12, 0, 0), "imported_batch_id": 1},
    ), patch(
        "backend.rinse_shift_monitor_baseline.latest_rfv_scrape_after_baseline",
        return_value={"id": 1, "finished_at": datetime(2026, 6, 10, 12, 0, 0)},
    ):
        yield
