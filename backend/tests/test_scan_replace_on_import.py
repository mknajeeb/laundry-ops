"""Portal export replaces prior persistent scan timelines per bag."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_registry import merge_scan_events_from_upload
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key
from backend.rinse_sorting_chronology import extract_sorting_sessions_for_bag
from backend.rinse_bag_stage_bounds import gaming_events_from_records


def _scan_df(
    bag_id: str,
    when: str,
    *,
    scan_index: int = 1,
    rack: str = "CLEAN",
    purpose: str = "weight-entry",
    user: str = "Francis",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Bag ID": bag_id,
                "Scan Index": str(scan_index),
                "Rack": rack,
                "Time Scanned": when,
                "User": user,
                "Purpose": purpose,
                "Last Location": "",
                "Last Scan": "",
            }
        ]
    )


def _enter_merge_patches(stack: ExitStack, *, store_rows: list[dict], allowed_bags: list[str] | None = None):
    bag_set = set(allowed_bags or [])

    def _delete(_cursor, org, bag_ids):
        bids = set(bag_ids)
        before = len(store_rows)
        store_rows[:] = [
            r
            for r in store_rows
            if not (r["organization_id"] == org and r["bag_id"] in bids)
        ]
        return before - len(store_rows)

    def _upsert(_cursor, **kwargs):
        store_rows.append(kwargs)
        return "inserted"

    def _filter(_cursor, _org, raw_bag_ids, **kwargs):
        if bag_set:
            allowed = [b for b in raw_bag_ids if b in bag_set]
            return allowed, []
        return list(raw_bag_ids), []

    stack.enter_context(patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"))
    stack.enter_context(patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"))
    stack.enter_context(
        patch(
            "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
            side_effect=_filter,
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags",
            side_effect=_delete,
        )
    )
    stack.enter_context(patch("backend.rinse_bag_registry.upsert_scan_event_row", side_effect=_upsert))


class TestScanReplaceOnImport:
    def test_reentry_bag_drops_old_cycle_scans(self):
        store_rows: list[dict] = []
        cursor = MagicMock()
        bag = "3F848Y9FP4"
        jun19 = _scan_df(bag, "Thursday, June 19, 2026 10:00 AM", rack="FOLDING")
        jun23 = _scan_df(bag, "Monday, June 23, 2026 10:35 AM")

        with ExitStack() as stack:
            _enter_merge_patches(stack, store_rows=store_rows)
            stack.enter_context(
                patch(
                    "backend.rinse_bag_registry.parse_rinse_scanned_at",
                    side_effect=lambda raw: datetime(2026, 6, 19, 10, 0)
                    if "June 19" in raw
                    else datetime(2026, 6, 23, 10, 35),
                )
            )
            merge_scan_events_from_upload(cursor, 3, 100, jun19, "jun19.csv")
            assert len(store_rows) == 1
            out = merge_scan_events_from_upload(cursor, 3, 200, jun23, "jun23.csv")

        assert out["events_deleted"] == 1
        assert out["replace_existing"] is True
        assert len(store_rows) == 1
        assert "June 23" in store_rows[0]["time_scanned_raw"]

    def test_batch_b_replaces_not_appends_same_bag(self):
        store_rows: list[dict] = []
        cursor = MagicMock()
        bag = "67MQFD65GQ"
        cycle_a = _scan_df(
            bag,
            "Wednesday, June 18, 2026 10:50 AM",
            scan_index=4,
            purpose="cleaning",
            user="Maria (Veewash)",
        )
        cycle_b = _scan_df(
            bag,
            "Wednesday, June 24, 2026 9:46 AM",
            scan_index=12,
            purpose="weight-entry",
            user="Francis (Veewash)",
        )

        with ExitStack() as stack:
            _enter_merge_patches(stack, store_rows=store_rows)
            stack.enter_context(
                patch(
                    "backend.rinse_bag_registry.parse_rinse_scanned_at",
                    side_effect=lambda raw: datetime(2026, 6, 18, 10, 50)
                    if "June 18" in raw
                    else datetime(2026, 6, 24, 9, 46),
                )
            )
            merge_scan_events_from_upload(cursor, 3, 1347, cycle_a, "batch_confirm_1347")
            assert len(store_rows) == 1
            out = merge_scan_events_from_upload(cursor, 3, 1630, cycle_b, "batch_confirm_1630")

        assert out["events_deleted"] == 1
        assert len(store_rows) == 1
        assert store_rows[0]["source_upload_batch_id"] == 1630
        assert "June 24" in store_rows[0]["time_scanned_raw"]

    def test_same_logical_scan_different_scan_index_dedupes(self):
        at = datetime(2026, 6, 24, 9, 46)
        raw = "Wednesday, June 24, 2026 9:46 AM"
        base = dict(
            organization_id=3,
            bag_id="67MQFD65GQ",
            rack="Scale",
            user_name="Francis (Veewash)",
            purpose="weight-entry",
            time_scanned_raw=raw,
            scanned_at_parsed=at,
        )
        k1 = compute_scan_event_dedupe_key(**base, scan_index=4)
        k2 = compute_scan_event_dedupe_key(**base, scan_index=12)
        assert k1 == k2

    def test_last_scan_suffix_same_dedupe_key(self):
        at = datetime(2026, 6, 24, 10, 8)
        raw = "Wednesday, June 24, 2026 10:08 AM"
        base = dict(
            organization_id=3,
            bag_id="BAG1",
            rack="W68",
            user_name="Francis",
            time_scanned_raw=raw,
            scanned_at_parsed=at,
        )
        k_plain = compute_scan_event_dedupe_key(**base, purpose="split-load")
        k_suffix = compute_scan_event_dedupe_key(**base, purpose="split-load Last Scan")
        assert k_plain == k_suffix

    def test_partial_targeted_import_can_merge_without_replace(self):
        store_rows: list[dict] = []
        cursor = MagicMock()
        bag = "BAG1"
        first = _scan_df(bag, "Friday, June 20, 2026 8:00 AM")
        second = _scan_df(bag, "Friday, June 20, 2026 9:00 AM", scan_index=2, purpose="cleaning")

        with ExitStack() as stack:
            _enter_merge_patches(stack, store_rows=store_rows)
            stack.enter_context(
                patch(
                    "backend.rinse_bag_registry.parse_rinse_scanned_at",
                    side_effect=lambda raw: datetime(2026, 6, 20, 8, 0)
                    if "8:00" in raw
                    else datetime(2026, 6, 20, 9, 0),
                )
            )
            merge_scan_events_from_upload(cursor, 3, 1, first, "a.csv", replace_existing=False)
            merge_scan_events_from_upload(cursor, 3, 2, second, "b.csv", replace_existing=False)

        assert len(store_rows) == 2


class TestSortingAfterReplace:
    def _ev(self, purpose, at, *, ev_id=1, user="Francis"):
        return {
            "id": ev_id,
            "rack": "Scale",
            "user_name": user,
            "purpose": purpose,
            "scanned_at_parsed": at,
            "scan_index": ev_id,
        }

    def test_old_cycle_not_counted_after_reintake_anchor(self):
        """Jun 18 completed cycle ignored when latest sent-to-vendor is Jun 24."""
        events = [
            self._ev("sent-to-vendor", datetime(2026, 6, 18, 4, 27), ev_id=1, user="Melissa"),
            self._ev("weight-entry", datetime(2026, 6, 18, 10, 50), ev_id=2, user="Maria"),
            self._ev("add-photos", datetime(2026, 6, 18, 11, 8), ev_id=3, user="Maria"),
            self._ev("processed-by-vendor", datetime(2026, 6, 18, 13, 45), ev_id=4, user="Evelin"),
            self._ev("sent-to-vendor", datetime(2026, 6, 24, 4, 34), ev_id=5, user="Melissa"),
            self._ev("weight-entry", datetime(2026, 6, 24, 9, 46), ev_id=6),
            self._ev("cleaning", datetime(2026, 6, 24, 10, 6), ev_id=7),
            self._ev("add-photos", datetime(2026, 6, 24, 10, 8), ev_id=8),
        ]
        tl = gaming_events_from_records(events)
        jun18 = extract_sorting_sessions_for_bag(
            "67MQFD65GQ", tl, selected_date_et=date(2026, 6, 18)
        )
        jun24 = extract_sorting_sessions_for_bag(
            "67MQFD65GQ", tl, selected_date_et=date(2026, 6, 24)
        )
        assert jun18 == []
        assert len(jun24) == 1
        assert jun24[0]["sort_end_et"] == datetime(2026, 6, 24, 10, 8)

    def test_completed_prior_cycle_alone_does_not_sort_today(self):
        events = [
            self._ev("sent-to-vendor", datetime(2026, 6, 18, 4, 27), ev_id=1, user="Melissa"),
            self._ev("weight-entry", datetime(2026, 6, 18, 10, 50), ev_id=2, user="Maria"),
            self._ev("add-photos", datetime(2026, 6, 18, 11, 8), ev_id=3, user="Maria"),
            self._ev("processed-by-vendor", datetime(2026, 6, 18, 13, 45), ev_id=4, user="Evelin"),
        ]
        tl = gaming_events_from_records(events)
        sessions = extract_sorting_sessions_for_bag(
            "67MQFD65GQ", tl, selected_date_et=date(2026, 6, 24)
        )
        assert sessions == []
