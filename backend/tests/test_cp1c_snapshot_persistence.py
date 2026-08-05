"""Checkpoint 1C — reliable Step-1 snapshot persistence (merge-completeness)."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_registry import merge_scan_events_from_upload
from backend.rinse_scan_chronology_gate import evaluate_timeline_replace_decision
from backend.rinse_step1_evidence_gate import (
    GATE_COMPLETE,
    evaluate_durable_evidence_gate,
    record_evidence_gate_for_batch,
    record_evidence_gate_from_merge,
)
from backend.rinse_step1_scrape_refresh import (
    STATUS_DEFERRED,
    STATUS_SUCCESS,
    refresh_step1_after_scrape,
)
from backend.tests.test_durable_incomplete_batch_stageb_gate import (
    DAY,
    _GateCursor,
    _day_meta,
    _refresh_patches,
)


def test_thinner_preserve_is_not_stage_b_incomplete():
    decision = evaluate_timeline_replace_decision(
        existing_max=datetime(2026, 8, 4, 18, 47),
        existing_n=34,
        incoming_max=datetime(2026, 8, 5, 12, 0),
        incoming_n=9,
    )
    assert decision["preserve"] is True
    assert decision["replace"] is False
    assert "incoming_materially_thinner" in decision["reasons"]
    assert decision.get("incomplete") is not True


def test_incoming_empty_still_marks_incomplete():
    decision = evaluate_timeline_replace_decision(
        existing_max=datetime(2026, 8, 4, 18, 47),
        existing_n=34,
        incoming_max=None,
        incoming_n=0,
    )
    assert decision["preserve"] is True
    assert decision.get("incomplete") is True
    assert "incoming_empty" in decision["reasons"]


def _merge_patches(stack: ExitStack, *, existing_n: int = 34):
    stack.enter_context(patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"))
    stack.enter_context(
        patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema")
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
            side_effect=lambda _c, _o, ids, **_k: (list(ids), []),
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags",
            return_value=0,
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry.upsert_scan_event_row",
            return_value="inserted",
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry._persistent_scan_bounds_for_bags",
            return_value={"BAG1": (datetime(2026, 8, 4, 18, 47), existing_n)},
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry._persistent_completion_stage_counts",
            return_value={"BAG1": 2},
        )
    )


def test_merge_thinner_preserve_does_not_set_import_incomplete():
    """Production failure mode: lifetime richer than portal export slice."""
    df = pd.DataFrame(
        [
            {
                "Bag ID": "BAG1",
                "Scan Index": "1",
                "Rack": "CLEAN",
                "Time Scanned": "Tuesday, August 5, 2026 10:00 AM",
                "User": "A",
                "Purpose": "weight-entry",
                "Last Location": "",
                "Last Scan": "",
            },
            {
                "Bag ID": "BAG1",
                "Scan Index": "2",
                "Rack": "CLEAN",
                "Time Scanned": "Tuesday, August 5, 2026 11:00 AM",
                "User": "A",
                "Purpose": "weight-entry",
                "Last Location": "",
                "Last Scan": "",
            },
        ]
    )
    cursor = MagicMock()
    with ExitStack() as stack:
        _merge_patches(stack, existing_n=34)
        stack.enter_context(
            patch(
                "backend.rinse_bag_registry.parse_rinse_scanned_at",
                side_effect=lambda raw: (
                    datetime(2026, 8, 5, 10, 0)
                    if "10:00" in raw
                    else datetime(2026, 8, 5, 11, 0)
                ),
            )
        )
        out = merge_scan_events_from_upload(
            cursor, 3, 3314, df, "batch_3314.csv", replace_existing=True
        )
    assert out["bags_preserve_existing_timeline"] == ["BAG1"]
    assert out["bags_preserve_reasons"]["BAG1"] == ["incoming_materially_thinner"]
    assert out["import_incomplete"] is False
    assert out["timeline_replacement_deferred"] is False


def test_merge_incoming_empty_still_sets_import_incomplete():
    df = pd.DataFrame(
        [
            {
                "Bag ID": "BAG1",
                "Scan Index": "1",
                "Rack": "CLEAN",
                "Time Scanned": "",
                "User": "A",
                "Purpose": "weight-entry",
                "Last Location": "",
                "Last Scan": "",
            }
        ]
    )
    cursor = MagicMock()
    with ExitStack() as stack:
        _merge_patches(stack, existing_n=10)
        stack.enter_context(
            patch("backend.rinse_bag_registry.parse_rinse_scanned_at", return_value=None)
        )
        out = merge_scan_events_from_upload(
            cursor, 3, 99, df, "empty.csv", replace_existing=True
        )
    assert out["import_incomplete"] is True
    assert out["timeline_replacement_deferred"] is True


def test_incomplete_batch_defers_and_writes_nothing():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3310,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        patches = _refresh_patches(day_meta, backfill=backfill)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
            6
        ], patches[7], patches[8]:
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3310,
            )
    assert out["deferred"] is True
    assert out["persisted"] is False
    assert out["step1_refresh_status"] == STATUS_DEFERRED
    backfill.assert_not_called()


def test_retry_same_incomplete_batch_still_defers():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3310,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        patches = _refresh_patches(day_meta, backfill=backfill)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
            6
        ], patches[7], patches[8]:
            for _ in range(3):
                out = refresh_step1_after_scrape(
                    conn,
                    cursor,
                    organization_id=3,
                    operations_date_et=DAY,
                    import_batch_id=3310,
                )
                assert out["deferred"] is True
                assert out["persisted"] is False
    backfill.assert_not_called()


def test_complete_later_batch_supersedes_prior_incomplete():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3310,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3314,
            import_incomplete=False,
        )
        old = evaluate_durable_evidence_gate(cur, 3, import_batch_id=3310)
        tip = evaluate_durable_evidence_gate(cur, 3, import_batch_id=None)
    assert old["blocking"] is True
    assert tip["import_batch_id"] == 3314
    assert tip["allow_persist"] is True
    assert tip["gate_status"] == GATE_COMPLETE


def test_thinner_merge_records_complete_gate():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        recorded = record_evidence_gate_from_merge(
            cur,
            organization_id=3,
            import_batch_id=3314,
            scrape_run_id=3531,
            merge={
                "import_incomplete": False,
                "timeline_replacement_deferred": False,
                "bags_preserve_existing_timeline": ["BAG1"],
                "bags_preserve_reasons": {"BAG1": ["incoming_materially_thinner"]},
            },
        )
        tip = evaluate_durable_evidence_gate(cur, 3, import_batch_id=3314)
    assert recorded["gate_status"] == GATE_COMPLETE
    assert recorded["allow_persist"] is True
    assert tip["allow_persist"] is True


def test_complete_batch_creates_day_and_day_bags_via_stage_b():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    day_meta["headline"] = {
        "completed": 2,
        "pending": 1,
        "exceptions": {"review_required": 0},
        "segments": {
            "all": {
                "bag_ids": {
                    "pending": ["P1"],
                    "completed": ["C1", "C2"],
                    "review_required": [],
                }
            }
        },
    }
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3314,
            import_incomplete=False,
        )
        with patch(
            "backend.rinse_veewash_shift_day.get_day_record", return_value=day_meta
        ), patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live",
            return_value={
                "ok": True,
                "day": day_meta,
                "bag_count": 3,
                "summary_totals": {
                    "completed": 2,
                    "pending": 1,
                    "review_required": 0,
                },
            },
        ) as backfill, patch(
            "backend.rinse_step1_scrape_refresh.table_exists", return_value=False
        ), patch(
            "backend.rinse_step1_scrape_refresh.record_evidence_import_pending",
            return_value=12,
        ), patch(
            "backend.rinse_step1_scrape_refresh._update_refresh_row"
        ), patch(
            "backend.rinse_step1_scrape_refresh._persist_day_meta_diagnostics"
        ), patch(
            "backend.rinse_step1_scrape_refresh.verify_step1_snapshot_freshness",
            return_value={"fresh": True, "reason": "ok"},
        ), patch(
            "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
            return_value=False,
        ), patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"status": "ok", "portal_ahead_bag_count": 0},
        ), patch(
            "backend.rinse_scan_chronology_gate.table_exists", return_value=False
        ):
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3314,
            )
    assert out["ok"] is True
    assert out.get("deferred") is not True
    assert out["step1_refresh_status"] == STATUS_SUCCESS
    assert out.get("persisted") is True
    backfill.assert_called_once()
    totals = out.get("summary_totals") or {}
    assert int(totals.get("completed") or 0) == 2
    assert int(totals.get("pending") or 0) == 1
    # Headline invariant: Stage-B day-bag count equals membership from backfill.
    assert int(out.get("day_bags_rebuilt") or 0) == 3


def test_existing_snapshot_retained_while_newer_batch_incomplete():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3315,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        patches = _refresh_patches(day_meta, backfill=backfill)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
            6
        ], patches[7], patches[8]:
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3315,
            )
    assert out["deferred"] is True
    snap = out["last_consistent_snapshot"]
    assert (snap["completed"], snap["pending"], snap["review_required"]) == (89, 3, 1)
    backfill.assert_not_called()


def test_stateful_no_snapshot_incomplete_then_complete_one_persist():
    """
    no snapshot → incomplete defer → later complete → exactly one successful persist
    → subsequent reads use snapshot (no interactive rebuild).
    """
    conn = MagicMock()
    cursor = _GateCursor()
    persist_calls: list[int] = []

    def _backfill(*_a, **kwargs):
        persist_calls.append(int(kwargs.get("import_batch_id") or 0))
        return {
            "ok": True,
            "day": {
                "status": "OPEN",
                "headline": {
                    "completed": 2,
                    "pending": 1,
                    "exceptions": {"review_required": 0},
                    "total": 3,
                },
                "last_sync_at": datetime(2026, 8, 5, 14, 0, 0),
            },
            "bag_count": 3,
            "summary_totals": {
                "completed": 2,
                "pending": 1,
                "review_required": 0,
            },
        }

    # Phase 0: missing snapshot interactive read must not rebuild (1B).
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch(
            "backend.rinse_veewash_shift_day.get_step1_activation_date",
            return_value=date(2026, 8, 1),
        ),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=None),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 8, 5)),
        patch("backend.rinse_veewash_shift_day._build_step1_workload_for_date") as rebuild,
        patch(
            "backend.rinse_shift_day_close_archive.ensure_prior_et_day_archived_on_rollover",
            return_value={"ok": False},
        ),
    ):
        _wl, missing_summary, _meta = build_or_load_step1_for_date(
            MagicMock(), 3, date(2026, 8, 5), persist_live=False, include_bag_rows=False
        )
    rebuild.assert_not_called()
    assert missing_summary["snapshot_available"] is False
    assert missing_summary["data_unavailable"] is True

    # Phase 1: incomplete batch defers — no persist.
    day_absent = None
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3310,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        with patch(
            "backend.rinse_veewash_shift_day.get_day_record", return_value=day_absent
        ), patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live", side_effect=_backfill
        ) as backfill, patch(
            "backend.rinse_step1_scrape_refresh.table_exists", return_value=False
        ), patch(
            "backend.rinse_step1_scrape_refresh.record_evidence_import_pending",
            return_value=1,
        ), patch(
            "backend.rinse_step1_scrape_refresh._update_refresh_row"
        ), patch(
            "backend.rinse_step1_scrape_refresh._persist_day_meta_diagnostics"
        ), patch(
            "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
            return_value=False,
        ), patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"status": "ok", "portal_ahead_bag_count": 0},
        ), patch(
            "backend.rinse_scan_chronology_gate.table_exists", return_value=False
        ):
            incomplete = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=date(2026, 8, 5),
                import_batch_id=3310,
            )
    assert incomplete["deferred"] is True
    assert incomplete["persisted"] is False
    assert persist_calls == []
    backfill.assert_not_called()

    # Phase 2: later complete batch (thinner-preserve merge flags false) persists once.
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3314,
            import_incomplete=False,
            timeline_replacement_deferred=False,
        )
        assert evaluate_durable_evidence_gate(cursor, 3)["gate_status"] == GATE_COMPLETE
        with patch(
            "backend.rinse_veewash_shift_day.get_day_record", return_value=None
        ), patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live", side_effect=_backfill
        ), patch(
            "backend.rinse_step1_scrape_refresh.table_exists", return_value=False
        ), patch(
            "backend.rinse_step1_scrape_refresh.record_evidence_import_pending",
            return_value=2,
        ), patch(
            "backend.rinse_step1_scrape_refresh._update_refresh_row"
        ), patch(
            "backend.rinse_step1_scrape_refresh._persist_day_meta_diagnostics"
        ), patch(
            "backend.rinse_step1_scrape_refresh.verify_step1_snapshot_freshness",
            return_value={"fresh": True, "reason": "ok"},
        ), patch(
            "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
            return_value=False,
        ), patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"status": "ok", "portal_ahead_bag_count": 0},
        ), patch(
            "backend.rinse_scan_chronology_gate.table_exists", return_value=False
        ):
            complete = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=date(2026, 8, 5),
                import_batch_id=3314,
            )
    assert complete["ok"] is True
    assert complete.get("deferred") is not True
    assert complete["step1_refresh_status"] == STATUS_SUCCESS
    assert persist_calls == [3314]

    # Phase 3: subsequent interactive read uses snapshot — no rebuild.
    day_after = {
        "status": "OPEN",
        "headline": {
            "completed": 2,
            "pending": 1,
            "exceptions": {"review_required": 0},
            "total": 3,
            "snapshot_available": True,
        },
        "shift_date_et": date(2026, 8, 5),
        "review_required_count": 0,
    }
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch(
            "backend.rinse_veewash_shift_day.get_step1_activation_date",
            return_value=date(2026, 8, 1),
        ),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day_after),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=day_after["headline"],
        ),
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 8, 5)),
        patch("backend.rinse_veewash_shift_day._build_step1_workload_for_date") as rebuild2,
        patch(
            "backend.rinse_veewash_shift_day._ensure_specialty_metrics",
            side_effect=lambda *a, **k: a[-1],
        ),
    ):
        _wl2, loaded_summary, _meta2 = build_or_load_step1_for_date(
            MagicMock(), 3, date(2026, 8, 5), persist_live=False, include_bag_rows=False
        )
    rebuild2.assert_not_called()
    assert loaded_summary.get("completed") == 2
    assert loaded_summary.get("pending") == 1


def test_manager_locks_and_entry_before_first_weight_unchanged():
    from backend.rinse_scan_chronology_gate import should_preserve_persisted_completion

    assert (
        should_preserve_persisted_completion(
            previous_status="completed",
            incoming_status="pending",
            chronology_complete=True,
            manager_edit_version=2,
        )
        is True
    )


def test_no_duplicate_membership_on_gate_complete_tip():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cur, organization_id=3, import_batch_id=3314, import_incomplete=False
        )
        record_evidence_gate_for_batch(
            cur, organization_id=3, import_batch_id=3314, import_incomplete=False
        )
        tip = evaluate_durable_evidence_gate(cur, 3)
    assert tip["import_batch_id"] == 3314
    assert tip["gate_status"] == GATE_COMPLETE
    assert len(cur.rows) == 1
