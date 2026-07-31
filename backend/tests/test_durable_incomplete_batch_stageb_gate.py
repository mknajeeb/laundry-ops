"""Durable incomplete-batch Stage-B gate — blocks all Stage-B paths."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_scan_chronology_gate import (
    STATUS_IMPORT_INCOMPLETE,
    evaluate_step1_rebuild_gate,
    last_consistent_snapshot_counts,
    should_preserve_persisted_completion,
)
from backend.rinse_step1_evidence_gate import (
    GATE_COMPLETE,
    GATE_INCOMPLETE,
    evaluate_durable_evidence_gate,
    record_evidence_gate_for_batch,
    resolve_batch_id_for_stage_b,
)
from backend.rinse_step1_scrape_refresh import (
    STATUS_DEFERRED,
    refresh_step1_after_scrape,
    retry_failed_step1_refreshes,
)
from backend.rinse_veewash_shift_day import STATUS_OPEN


DAY = date(2026, 7, 31)
BASELINE = {
    "completed": 89,
    "pending": 3,
    "review_required": 1,
    "total": 93,
    "source": "last_consistent_snapshot",
}


def _day_meta():
    return {
        "status": STATUS_OPEN,
        "last_sync_at": datetime(2026, 7, 31, 13, 0, 0),
        "headline": {
            "completed": 89,
            "pending": 3,
            "exceptions": {"review_required": 1},
            "segments": {
                "all": {
                    "bag_ids": {
                        "pending": ["P1", "P2", "P3"],
                        "completed": ["C1"],
                        "review_required": ["R1"],
                    }
                }
            },
        },
        "workload_meta": {},
    }


class _GateCursor:
    """Minimal in-memory cursor for rinse_step1_evidence_gate."""

    def __init__(self):
        self.tables = {"rinse_step1_evidence_gate": True}
        self.rows: dict[tuple[int, int], dict] = {}
        self.lastrowid = 0
        self._last = None

    def execute(self, sql, params=None):
        s = " ".join(str(sql).lower().split())
        params = params or ()
        if s.startswith("create table"):
            self._last = None
            return
        if "insert into rinse_step1_evidence_gate" in s:
            org, batch = int(params[0]), int(params[1])
            self.lastrowid += 1
            row = {
                "organization_id": org,
                "import_batch_id": batch,
                "scrape_run_id": params[2],
                "portal_presence_run_id": params[3],
                "evidence_generation_id": params[4],
                "gate_status": params[5],
                "gate_reason": params[6],
                "import_incomplete": params[7],
                "timeline_replacement_deferred": params[8],
                "coverage_incomplete": params[9],
                "invalid_for_step1_rebuild": params[10],
                "detail_json": params[11],
            }
            self.rows[(org, batch)] = row
            self._last = None
            return
        if "from rinse_step1_evidence_gate" in s and "and import_batch_id" in s:
            org, batch = int(params[0]), int(params[1])
            self._last = self.rows.get((org, batch))
            return
        if "from rinse_step1_evidence_gate" in s and "order by import_batch_id desc" in s:
            org = int(params[0])
            items = [r for (o, _), r in self.rows.items() if o == org]
            items.sort(key=lambda r: int(r["import_batch_id"]), reverse=True)
            self._last = items[:8]
            return
        self._last = None

    def fetchone(self):
        if isinstance(self._last, list):
            return self._last[0] if self._last else None
        return self._last

    def fetchall(self):
        if isinstance(self._last, list):
            return self._last
        return [self._last] if self._last else []


def test_record_incomplete_batch_blocks_durable_gate():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        recorded = record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3173,
            scrape_run_id=3299,
            portal_presence_run_id=3801,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        assert recorded["blocking"] is True
        assert recorded["gate_status"] == GATE_INCOMPLETE
        decision = evaluate_durable_evidence_gate(
            cur, 3, import_batch_id=3173, scrape_run_id=None
        )
    assert decision["allow_persist"] is False
    assert decision["blocking"] is True
    assert decision["import_batch_id"] == 3173
    assert decision["portal_presence_run_id"] == 3801


def test_null_scrape_run_still_resolves_incomplete_batch():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3173,
            scrape_run_id=3299,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        resolved = resolve_batch_id_for_stage_b(cur, 3, import_batch_id=None, scrape_run_id=None)
        decision = evaluate_durable_evidence_gate(cur, 3)
    assert resolved == 3173
    assert decision["blocking"] is True


def test_later_complete_batch_clears_org_tip_but_not_old_batch():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3173,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        record_evidence_gate_for_batch(
            cur,
            organization_id=3,
            import_batch_id=3174,
            import_incomplete=False,
        )
        old = evaluate_durable_evidence_gate(cur, 3, import_batch_id=3173)
        tip = evaluate_durable_evidence_gate(cur, 3, import_batch_id=None)
    assert old["blocking"] is True
    assert tip["import_batch_id"] == 3174
    assert tip["allow_persist"] is True
    assert tip["gate_status"] == GATE_COMPLETE


def _refresh_patches(day_meta, *, backfill=None):
    return [
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day_meta),
        patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live",
            backfill or MagicMock(),
        ),
        patch("backend.rinse_step1_scrape_refresh.table_exists", return_value=False),
        patch(
            "backend.rinse_step1_scrape_refresh.record_evidence_import_pending",
            return_value=99,
        ),
        patch("backend.rinse_step1_scrape_refresh._update_refresh_row"),
        patch("backend.rinse_step1_scrape_refresh._persist_day_meta_diagnostics"),
        patch(
            "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
            return_value=False,
        ),
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"status": "ok", "portal_ahead_bag_count": 0},
        ),
        patch("backend.rinse_scan_chronology_gate.table_exists", return_value=False),
    ]


def test_incomplete_batch_initial_stage_b_defers_no_persist():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3173,
            scrape_run_id=3299,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        patches = _refresh_patches(day_meta, backfill=backfill)
        # resolve_batch uses evidence gate table_exists True already
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
            6
        ], patches[7], patches[8], patch(
            "backend.rinse_step1_evidence_gate.table_exists", return_value=True
        ):
            # share same cursor rows into resolve — evaluate uses cursor
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3173,
                scrape_run_id=3299,
            )
    assert out["deferred"] is True
    assert out["persisted"] is False
    assert out["step1_refresh_status"] == STATUS_DEFERRED
    assert out["reason"] in (
        STATUS_IMPORT_INCOMPLETE,
        "import_batch_incomplete",
    ) or "incomplete" in str(out["reason"])
    assert out.get("gate_reason") == "import_batch_incomplete" or "incomplete" in str(
        out.get("gate_reason") or out["reason"]
    )
    snap = out["last_consistent_snapshot"]
    assert (snap["completed"], snap["pending"], snap["review_required"]) == (89, 3, 1)
    backfill.assert_not_called()


def test_retry_same_incomplete_batch_still_deferred():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3173,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        patches = _refresh_patches(day_meta, backfill=backfill)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[
            6
        ], patches[7], patches[8]:
            # No force_incomplete — durable gate must still block (Jul 31 failure mode)
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3173,
                scrape_run_id=None,
            )
    assert out["deferred"] is True
    assert out["persisted"] is False
    backfill.assert_not_called()


def test_watchdog_same_incomplete_batch_still_deferred():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3173,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        with patch(
            "backend.rinse_step1_scrape_refresh.list_retryable_step1_refreshes",
            return_value=[
                {
                    "id": 285,
                    "affected_operations_date_et": DAY,
                    "scrape_run_id": 3299,
                    "import_batch_id": 3173,
                    "attempt_count": 2,
                }
            ],
        ), patch(
            "backend.rinse_veewash_shift_day.get_day_record", return_value=day_meta
        ), patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live", backfill
        ), patch(
            "backend.rinse_step1_scrape_refresh.table_exists", return_value=False
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
            out = retry_failed_step1_refreshes(conn, cursor, organization_id=3)
    assert out["retried"] == 1
    assert out["results"][0]["step1_refresh_status"] == STATUS_DEFERRED
    backfill.assert_not_called()


def test_manual_retry_same_incomplete_batch_still_deferred():
    """Manual Retry Shift Monitor Refresh = refresh_step1_after_scrape without force."""
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    backfill = MagicMock()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3173,
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
                import_batch_id=3173,
            )
    assert out["deferred"] is True
    backfill.assert_not_called()


def test_later_complete_batch_allows_rebuild():
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3173,
            import_incomplete=True,
            timeline_replacement_deferred=True,
        )
        record_evidence_gate_for_batch(
            cursor,
            organization_id=3,
            import_batch_id=3174,
            import_incomplete=False,
        )
        with patch(
            "backend.rinse_veewash_shift_day.get_day_record", return_value=day_meta
        ), patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live",
            return_value={
                "ok": True,
                "day": day_meta,
                "bag_count": 93,
                "summary_totals": {
                    "completed": 89,
                    "pending": 3,
                    "review_required": 1,
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
                import_batch_id=3174,
            )
    assert out.get("deferred") is not True
    assert out["ok"] is True
    assert out["step1_refresh_status"] == "SUCCESS"
    backfill.assert_called_once()


def test_baseline_counts_hold_across_incomplete_and_repeat():
    day_meta = _day_meta()
    snap = last_consistent_snapshot_counts(day_meta)
    assert (snap["completed"], snap["pending"], snap["review_required"]) == (89, 3, 1)

    cursor = MagicMock()
    with patch(
        "backend.rinse_scan_chronology_gate.scrape_import_in_progress",
        return_value=False,
    ), patch(
        "backend.rinse_scan_freshness.freshness_from_day_and_presence",
        return_value={"status": "ok", "portal_ahead_bag_count": 0},
    ), patch(
        "backend.rinse_scan_chronology_gate.table_exists", return_value=False
    ), patch(
        "backend.rinse_step1_evidence_gate.evaluate_durable_evidence_gate",
        return_value={
            "blocking": True,
            "allow_persist": False,
            "gate_reason": "import_batch_incomplete",
            "gate_status": GATE_INCOMPLETE,
            "import_batch_id": 3173,
            "durable_gate_checked": True,
        },
    ):
        gate = evaluate_step1_rebuild_gate(
            cursor, 3, DAY, day_meta=day_meta, import_batch_id=3173
        )
    assert gate["allow_persist"] is False
    assert gate["gate_reason"] == "import_batch_incomplete"
    assert gate["last_consistent_snapshot"]["completed"] == 89
    assert gate["last_consistent_snapshot"]["pending"] == 3
    assert gate["last_consistent_snapshot"]["review_required"] == 1

    # Repeated Stage B still retains baseline
    assert last_consistent_snapshot_counts(day_meta)["completed"] == 89


def test_completed_rows_cannot_downgrade_while_incomplete():
    assert (
        should_preserve_persisted_completion(
            previous_status="Completed",
            incoming_status="Pending",
            chronology_complete=False,
        )
        is True
    )
    assert (
        should_preserve_persisted_completion(
            previous_status="Completed",
            incoming_status="Pending",
            chronology_complete=True,
        )
        is False
    )
