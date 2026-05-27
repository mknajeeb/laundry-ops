"""Phase 4A employee productivity: clocked time + gaming/scoring."""

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from backend.rinse_folding_registry import apply_scoring_override
from backend.rinse_folding_scoring import SCORING_OVERRIDE_EXCLUDE, SCORING_OVERRIDE_INCLUDE
from backend.rinse_folding_user_productivity import (
    build_clocked_productivity,
    build_gaming_record_rows,
    build_gaming_scoring_view,
    build_user_folding_productivity,
)


def _perf_row(
    bag_id,
    *,
    start,
    end,
    duration_seconds=None,
    status="CALCULATED",
    scoring_status=None,
    exception_code=None,
    included_in_scoring=1,
    scoring_override=None,
    lbs=10.0,
    perf_id=1,
):
    if duration_seconds is None and start and end:
        duration_seconds = int((end - start).total_seconds())
    return {
        "id": perf_id,
        "bag_id": bag_id,
        "name_clean": f"Cust {bag_id}",
        "weight_lbs": lbs,
        "registry_weight_num": lbs,
        "folding_start_at": start,
        "folding_end_at": end,
        "duration_seconds": duration_seconds,
        "status": status,
        "scoring_status": scoring_status or status,
        "exception_code": exception_code,
        "included_in_scoring": included_in_scoring,
        "excluded_from_performance": 0 if included_in_scoring else 1,
        "scoring_override": scoring_override,
    }


def test_clocked_productivity_uses_shift_duration(monkeypatch):
    rows = build_gaming_record_rows(
        [
            _perf_row(
                "A",
                start=datetime(2026, 5, 26, 10, 0),
                end=datetime(2026, 5, 26, 10, 15),
                duration_seconds=900,
            ),
        ]
    )
    shifts = [
        {
            "id": 7,
            "clock_in_at": datetime(2026, 5, 26, 8, 0),
            "clock_out_at": datetime(2026, 5, 26, 17, 0),
            "status": "closed",
            "net_work_seconds": None,
        }
    ]

    class Cur:
        def execute(self, sql, args=None):
            self.sql = sql

        def fetchall(self):
            return shifts

    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda c, t: True)
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity._last_rinse_sync_naive",
        lambda c, o: None,
    )
    out = build_clocked_productivity(
        Cur(),
        3,
        user_id=5,
        employee_name="Test",
        gaming_rows=rows,
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["summary"]["clocked_minutes"] == 9 * 60
    assert out["summary"]["clocked_hours"] == 9.0


def test_bags_per_clocked_hour():
    from backend.rinse_folding_user_productivity import _shift_summary_from_bags

    rows = build_gaming_record_rows(
        [
            _perf_row(
                "A",
                start=datetime(2026, 5, 26, 9, 0),
                end=datetime(2026, 5, 26, 9, 30),
            ),
            _perf_row(
                "B",
                start=datetime(2026, 5, 26, 10, 0),
                end=datetime(2026, 5, 26, 10, 30),
            ),
        ]
    )
    clocked_sec = 2 * 3600
    summary = _shift_summary_from_bags(
        shift_id=1,
        employee_name="E",
        clock_in=datetime(2026, 5, 26, 8, 0),
        clock_out_raw=datetime(2026, 5, 26, 10, 0),
        effective_clock_out=datetime(2026, 5, 26, 10, 0),
        is_active_estimate=False,
        estimate_label=None,
        clocked_sec=clocked_sec,
        bag_rows=rows,
    )
    assert summary["bags_per_clocked_hour"] == 1.0
    assert summary["lbs_per_clocked_hour"] == 10.0


def test_total_bags_includes_exceptions_scoring_excludes():
    rows = build_gaming_record_rows(
        [
            _perf_row(
                "OK",
                start=datetime(2026, 5, 26, 9, 0),
                end=datetime(2026, 5, 26, 9, 15),
                included_in_scoring=1,
            ),
            _perf_row(
                "BAD",
                start=datetime(2026, 5, 26, 9, 30),
                end=datetime(2026, 5, 26, 9, 32),
                duration_seconds=120,
                status="EXCEPTION",
                scoring_status="EXCEPTION",
                exception_code="FOLDING_DURATION_TOO_SHORT",
                included_in_scoring=0,
            ),
        ]
    )
    s = build_gaming_scoring_view(rows)["summary"]
    assert s["total_bags"] == 2
    assert s["scoring_bags"] == 1
    assert s["not_in_scoring_bags"] == 1


def test_two_minute_exception_in_records_not_scoring(monkeypatch):
    rows = [
        _perf_row(
            "JEN",
            start=datetime(2026, 5, 26, 14, 0),
            end=datetime(2026, 5, 26, 14, 2),
            duration_seconds=120,
            status="EXCEPTION",
            scoring_status="EXCEPTION",
            exception_code="FOLDING_DURATION_TOO_SHORT",
            included_in_scoring=0,
        ),
    ]

    class Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return None

    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.load_user_performance_rows",
        lambda *a, **k: rows,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.get_user_map",
        lambda *a, **k: None,
    )
    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="Jennifer",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert "mode_b_work_span" not in out
    assert "mode_a_bag_wise" not in out
    rec = out["gaming_scoring"]["rows"][0]
    assert rec["bag_id"] == "JEN"
    assert rec["exception_code"] == "FOLDING_DURATION_TOO_SHORT"
    assert rec["included_in_scoring"] is False
    assert out["gaming_scoring"]["summary"]["scoring_bags"] == 0


def test_unmapped_user_no_clocked_still_has_gaming(monkeypatch):
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.load_user_performance_rows",
        lambda *a, **k: [
            _perf_row(
                "X",
                start=datetime(2026, 5, 26, 9, 0),
                end=datetime(2026, 5, 26, 9, 20),
            )
        ],
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.get_user_map",
        lambda *a, **k: None,
    )

    class Cur:
        def execute(self, *a, **k):
            pass

    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="Rinse Only",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["clocked_productivity"]["available"] is False
    assert "No employee clock mapping" in out["clocked_productivity"]["message"]
    assert len(out["gaming_scoring"]["rows"]) == 1


def test_active_shift_uses_last_sync_estimate(monkeypatch):
    sync_at = datetime(2026, 5, 26, 15, 30)
    shifts = [
        {
            "id": 2,
            "clock_in_at": datetime(2026, 5, 26, 8, 0),
            "clock_out_at": None,
            "status": "active",
            "net_work_seconds": None,
        }
    ]

    class Cur:
        def execute(self, sql, args=None):
            pass

        def fetchall(self):
            return shifts

    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda c, t: True)
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity._last_rinse_sync_naive",
        lambda c, o: sync_at,
    )
    out = build_clocked_productivity(
        Cur(),
        3,
        user_id=1,
        employee_name="E",
        gaming_rows=[],
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    sh = out["shifts"][0]
    assert sh["is_active_estimate"] is True
    assert sh["effective_clock_out_at"] == sync_at
    assert "last successful Rinse sync" in (sh["estimate_label"] or "")


def test_work_span_not_in_payload(monkeypatch):
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.load_user_performance_rows",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.get_user_map",
        lambda *a, **k: None,
    )

    class Cur:
        def execute(self, *a, **k):
            pass

    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="U",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert "mode_b_work_span" not in out
    assert "clocked_productivity" in out
    assert "gaming_scoring" in out


def test_scoring_override_include_changes_gaming_only(monkeypatch):
    row = _perf_row(
        "B1",
        start=datetime(2026, 5, 26, 10, 0),
        end=datetime(2026, 5, 26, 10, 10),
        status="EXCEPTION",
        scoring_status="EXCEPTION",
        exception_code="FOLDING_DURATION_TOO_SHORT",
        included_in_scoring=0,
        perf_id=99,
    )
    after = {
        **row,
        "scoring_override": SCORING_OVERRIDE_INCLUDE,
        "included_in_scoring": 1,
        "scoring_status": "INCLUDED_OVERRIDE",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_folding_registry.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.normalize_bag_id",
        lambda b: "B1",
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.get_folding_performance_row",
        lambda c, o, b: after,
    )
    r = apply_scoring_override(cursor, 3, "B1", action="include", note="gaming test")
    assert r["row"]["included_in_scoring"] == 1
    assert r["row"]["scoring_override"] == SCORING_OVERRIDE_INCLUDE
    assert row["folding_start_at"] == after["folding_start_at"]


def test_scoring_override_exclude_changes_gaming_only(monkeypatch):
    row = _perf_row(
        "B2",
        start=datetime(2026, 5, 26, 11, 0),
        end=datetime(2026, 5, 26, 11, 10),
        included_in_scoring=1,
        perf_id=100,
    )
    after = {
        **row,
        "scoring_override": SCORING_OVERRIDE_EXCLUDE,
        "included_in_scoring": 0,
        "scoring_status": "EXCLUDED",
    }
    cursor = MagicMock()
    monkeypatch.setattr(
        "backend.rinse_folding_registry.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.normalize_bag_id",
        lambda b: "B2",
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.get_folding_performance_row",
        lambda c, o, b: after,
    )
    r = apply_scoring_override(cursor, 3, "B2", action="exclude")
    assert r["row"]["included_in_scoring"] == 0


def test_scoring_override_clear_recomputes(monkeypatch):
    row = _perf_row(
        "B3",
        start=datetime(2026, 5, 26, 12, 0),
        end=datetime(2026, 5, 26, 12, 10),
        scoring_override=SCORING_OVERRIDE_INCLUDE,
        included_in_scoring=1,
        perf_id=101,
    )
    cleared = {**row, "scoring_override": None, "included_in_scoring": 0}
    cursor = MagicMock()
    state = {"n": 0}

    def get_row(c, o, b):
        state["n"] += 1
        return cleared if state["n"] > 1 else row

    monkeypatch.setattr(
        "backend.rinse_folding_registry.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.normalize_bag_id",
        lambda b: "B3",
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.get_folding_performance_row",
        get_row,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_registry.apply_folding_performance_for_bag",
        lambda *a, **k: {"ok": True},
    )
    r = apply_scoring_override(cursor, 3, "B3", action="clear")
    assert r["action"] == "clear"
    assert r["recomputed"] == {"ok": True}
