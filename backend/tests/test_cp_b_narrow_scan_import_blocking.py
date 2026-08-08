"""Checkpoint B — narrow Stage-B blocking to durable import_running stamp."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_scan_chronology_gate import (
    STATUS_IMPORT_INCOMPLETE,
    STATUS_OK,
    STATUS_SCAN_CHRONOLOGY_STALE,
    STATUS_SCAN_IMPORT_IN_PROGRESS,
    evaluate_step1_rebuild_gate,
    scrape_import_in_progress,
)
from backend.rinse_step1_evidence_gate import (
    GATE_COMPLETE,
    GATE_IMPORT_RUNNING,
    GATE_INCOMPLETE,
    REASON_IMPORT_BATCH_INCOMPLETE,
    active_scan_import_running,
    record_scan_import_running,
    record_scan_import_terminal_failure,
    reconcile_stale_import_running_gates,
)


DAY = date(2026, 8, 8)


def _day_meta():
    return {
        "status": "OPEN",
        "headline": {
            "completed": 30,
            "pending": 60,
            "exceptions": {"review_required": 5},
            "segments": {"all": {"bag_ids": {"pending": ["P1"], "completed": [], "review_required": []}}},
        },
    }


def _fresh_ok(**extra):
    out = {"status": "ok", "portal_ahead_bag_count": 0}
    out.update(extra)
    return out


def test_scrape_running_alone_does_not_mean_import_in_progress():
    """Presence / CSV download: scrape running must not block via old predicate."""
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_evidence_gate.table_exists", return_value=True
    ), patch(
        "backend.rinse_step1_evidence_gate.reconcile_stale_import_running_gates",
        return_value=0,
    ):
        cursor.fetchall.return_value = []
        assert scrape_import_in_progress(cursor, 3) is False


def test_presence_phase_running_scrape_allows_retry_when_otherwise_ok():
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={"blocking": False, "allow_persist": True, "gate_status": None},
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is True
    assert gate["status"] == STATUS_OK


def test_csv_download_running_scrape_allows_retry_when_otherwise_ok():
    """Same as presence — no import_running stamp yet."""
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={"blocking": False, "allow_persist": True},
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is True


def test_active_import_running_gate_defers_with_scan_import_in_progress():
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=True,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": True,
            "allow_persist": False,
            "gate_status": GATE_IMPORT_RUNNING,
            "gate_reason": "import_running",
            "import_batch_id": 3379,
        },
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is False
    assert gate["status"] == STATUS_SCAN_IMPORT_IN_PROGRESS
    assert gate["reason"] == STATUS_SCAN_IMPORT_IN_PROGRESS


def test_complete_terminal_gate_allows_retry():
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": False,
            "allow_persist": True,
            "gate_status": GATE_COMPLETE,
            "import_batch_id": 3379,
        },
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is True


def test_incomplete_terminal_gate_defers_import_batch_incomplete():
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": True,
            "allow_persist": False,
            "gate_status": GATE_INCOMPLETE,
            "gate_reason": REASON_IMPORT_BATCH_INCOMPLETE,
            "import_batch_id": 3379,
        },
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is False
    assert gate["status"] == STATUS_IMPORT_INCOMPLETE
    assert gate["reason"] == REASON_IMPORT_BATCH_INCOMPLETE


def test_merge_exception_clears_import_running_via_terminal_failure():
    """record_scan_import_terminal_failure must replace import_running."""
    calls = []

    def _record(_cursor=None, **kwargs):
        calls.append(dict(kwargs))
        return {
            "gate_status": (
                GATE_IMPORT_RUNNING if kwargs.get("import_running") else GATE_INCOMPLETE
            ),
            "blocking": True,
            "import_batch_id": kwargs["import_batch_id"],
        }

    with patch(
        "backend.rinse_step1_evidence_gate.record_evidence_gate_for_batch",
        side_effect=_record,
    ):
        start = record_scan_import_running(
            MagicMock(), organization_id=3, import_batch_id=99, scrape_run_id=3688
        )
        assert start["gate_status"] == GATE_IMPORT_RUNNING
        fail = record_scan_import_terminal_failure(
            MagicMock(),
            organization_id=3,
            import_batch_id=99,
            scrape_run_id=3688,
            error="boom",
        )
        assert fail["gate_status"] == GATE_INCOMPLETE
        assert calls[0].get("import_running") is True
        assert calls[1].get("import_incomplete") is True
        assert calls[1].get("import_running") is not True


def test_running_scrape_after_merge_commit_allows_retry():
    """Post-merge Stage-B window: scrape still running, gate complete."""
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value=_fresh_ok(),
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": False,
            "allow_persist": True,
            "gate_status": GATE_COMPLETE,
        },
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is True
    assert gate.get("scan_import_in_progress") is False


def test_portal_ahead_and_freshness_still_defer():
    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value={
            "status": "scan_chronology_stale",
            "portal_ahead_bag_count": 4,
        },
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={"blocking": False, "allow_persist": True},
    ):
        gate = evaluate_step1_rebuild_gate(cursor, 3, DAY, day_meta=_day_meta())
    assert gate["allow_persist"] is False
    assert gate["status"] == STATUS_SCAN_CHRONOLOGY_STALE


def test_active_scan_import_running_reads_gate_table():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "import_batch_id": 3379,
            "scrape_run_id": 3688,
            "gate_status": GATE_IMPORT_RUNNING,
            "updated_at": datetime.utcnow(),
        }
    ]
    with patch(
        "backend.rinse_step1_evidence_gate.table_exists", return_value=True
    ), patch(
        "backend.rinse_step1_evidence_gate.reconcile_stale_import_running_gates",
        return_value=0,
    ):
        assert active_scan_import_running(cursor, 3) is True


def test_stale_import_running_reconciled_to_incomplete():
    cursor = MagicMock()
    stale_time = datetime.utcnow() - timedelta(hours=5)
    cursor.fetchall.return_value = [
        {"import_batch_id": 3379, "scrape_run_id": 3688, "updated_at": stale_time}
    ]
    with patch(
        "backend.rinse_step1_evidence_gate.table_exists", return_value=True
    ), patch(
        "backend.rinse_step1_evidence_gate.record_scan_import_terminal_failure"
    ) as fail:
        n = reconcile_stale_import_running_gates(cursor, 3)
    assert n == 1
    fail.assert_called_once()


def test_commit_combined_upload_stamps_import_running_and_clears_on_success():
    from backend.rinse_combined_upload import commit_rinse_combined_upload

    conn = MagicMock()
    cursor = MagicMock()
    orders = MagicMock()
    orders.__len__ = lambda self: 1
    events = MagicMock()
    events.empty = False

    stamps = []

    def _running(_cursor=None, **kw):
        stamps.append(("running", kw.get("import_batch_id")))
        return {"gate_status": GATE_IMPORT_RUNNING}

    def _from_merge(_cursor=None, **kw):
        stamps.append(("terminal", kw.get("import_batch_id")))
        return {"gate_status": GATE_COMPLETE, "blocking": False}

    with patch(
        "backend.rinse_combined_upload.prepare_orders_df", return_value=orders
    ), patch(
        "backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids",
        return_value=set(),
    ), patch(
        "backend.rinse_combined_upload.get_upload_batch_schema",
        return_value=MagicMock(
            has_rows_inserted=True,
            has_state=True,
            has_updated_at=True,
            has_ub_org=True,
            upload_batches_pk="batch_id",
            row_pk="id",
        ),
    ), patch(
        "backend.rinse_combined_upload.create_draft_upload_batch_shell",
        return_value=5501,
    ), patch(
        "backend.rinse_portal_scrape_meta.load_portal_scrape_meta_file",
        return_value={"row_count": 1},
    ), patch(
        "backend.rinse_portal_scrape_meta.persist_portal_scrape_meta_on_batch",
        return_value={
            "portal_scrape_meta": {"row_count": 1},
            "portal_absence_allowed": True,
            "full_snapshot": True,
        },
    ), patch(
        "backend.rinse_combined_upload.collect_bag_ids_from_upload",
        return_value=["BAG1"],
    ), patch(
        "backend.rinse_combined_upload.build_upload_duplicate_indexes",
        return_value=({}, {}, 3),
    ), patch(
        "backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df",
        return_value={"rows_inserted": 1, "rejected_rows": 0, "needs_attention_rows": 0},
    ), patch(
        "backend.rinse_step1_evidence_gate.record_scan_import_running",
        side_effect=_running,
    ), patch(
        "backend.rinse_scan_events_upload.commit_scan_events_for_batch",
        return_value={"rows_inserted": 2},
    ), patch(
        "backend.rinse_bag_registry.merge_scan_events_from_upload",
        return_value={"bags_merged": 1, "import_incomplete": False},
    ), patch(
        "backend.rinse_combined_upload._attach_portal_weights_after_draft_merge"
    ), patch(
        "backend.rinse_combined_upload.finalize_upload_batch_row_counts"
    ), patch(
        "backend.rinse_step1_evidence_gate.record_evidence_gate_from_merge",
        side_effect=_from_merge,
    ), patch(
        "backend.app.summarize_batch_rows",
        return_value={"accepted_rows": "1"},
    ), patch(
        "backend.upload_batch_requirements.batch_upload_files_status",
        return_value={"confirm_ready": True},
    ):
        out = commit_rinse_combined_upload(
            conn,
            cursor,
            3,
            DAY,
            "portal.csv",
            orders,
            "events.csv",
            events,
            portal_scrape_meta={"row_count": 1},
            scrape_run_id=3688,
        )

    assert out["batch_id"] == 5501
    assert stamps[0][0] == "running"
    assert stamps[-1][0] == "terminal"
    assert conn.commit.call_count >= 2


def test_commit_combined_upload_exception_does_not_leave_import_running():
    from backend.rinse_combined_upload import commit_rinse_combined_upload

    conn = MagicMock()
    cursor = MagicMock()
    orders = MagicMock()
    orders.__len__ = lambda self: 1
    events = MagicMock()
    events.empty = False
    cleared = []

    with patch(
        "backend.rinse_combined_upload.prepare_orders_df", return_value=orders
    ), patch(
        "backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids",
        return_value=set(),
    ), patch(
        "backend.rinse_combined_upload.get_upload_batch_schema",
        return_value=MagicMock(
            has_rows_inserted=True,
            has_state=True,
            has_updated_at=True,
            has_ub_org=True,
            upload_batches_pk="batch_id",
            row_pk="id",
        ),
    ), patch(
        "backend.rinse_combined_upload.create_draft_upload_batch_shell",
        return_value=5502,
    ), patch(
        "backend.rinse_portal_scrape_meta.persist_portal_scrape_meta_on_batch",
        return_value={
            "portal_scrape_meta": {},
            "portal_absence_allowed": True,
            "full_snapshot": True,
        },
    ), patch(
        "backend.rinse_combined_upload.collect_bag_ids_from_upload",
        return_value=["BAG1"],
    ), patch(
        "backend.rinse_combined_upload.build_upload_duplicate_indexes",
        return_value=({}, {}, 3),
    ), patch(
        "backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df",
        return_value={"rows_inserted": 1, "rejected_rows": 0, "needs_attention_rows": 0},
    ), patch(
        "backend.rinse_step1_evidence_gate.record_scan_import_running",
        return_value={"gate_status": GATE_IMPORT_RUNNING},
    ), patch(
        "backend.rinse_scan_events_upload.commit_scan_events_for_batch",
        side_effect=RuntimeError("merge boom"),
    ), patch(
        "backend.rinse_step1_evidence_gate.record_scan_import_terminal_failure",
        side_effect=lambda _c=None, **kw: cleared.append(kw)
        or {"gate_status": GATE_INCOMPLETE},
    ):
        with pytest.raises(RuntimeError, match="merge boom"):
            commit_rinse_combined_upload(
                conn,
                cursor,
                3,
                DAY,
                "portal.csv",
                orders,
                "events.csv",
                events,
                portal_scrape_meta={"row_count": 1},
                scrape_run_id=3688,
            )

    assert cleared
    assert cleared[0]["import_batch_id"] == 5502
    assert "boom" in (cleared[0].get("error") or "")
