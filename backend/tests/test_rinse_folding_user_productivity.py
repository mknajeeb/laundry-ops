"""Phase 4A read-only folding productivity (3 modes)."""

from datetime import date, datetime

from backend.rinse_folding_user_productivity import (
    build_mode_a_bag_wise,
    build_mode_b_work_span,
    build_mode_c_clock_hours,
    build_sequence_rows,
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
    lbs=10.0,
):
    if duration_seconds is None and start and end:
        duration_seconds = int((end - start).total_seconds())
    return {
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
    }


def test_mode_a_rates_use_sum_duration_seconds_only():
    rows = [
        _perf_row(
            "A",
            start=datetime(2026, 5, 26, 9, 0),
            end=datetime(2026, 5, 26, 9, 30),
            duration_seconds=600,
        ),
        _perf_row(
            "B",
            start=datetime(2026, 5, 26, 10, 0),
            end=datetime(2026, 5, 26, 10, 20),
            duration_seconds=600,
        ),
    ]
    seq = build_sequence_rows(rows)
    summary = build_mode_a_bag_wise(seq)["summary"]
    assert summary["total_folding_minutes"] == 20.0
    folding_hours = 1200 / 3600.0
    assert summary["bags_per_folding_hour"] == round(2 / folding_hours, 4)


def test_mode_b_work_span_earliest_start_latest_end():
    rows = [
        _perf_row(
            "A",
            start=datetime(2026, 5, 26, 9, 0),
            end=datetime(2026, 5, 26, 9, 10),
            duration_seconds=600,
        ),
        _perf_row(
            "B",
            start=datetime(2026, 5, 26, 11, 0),
            end=datetime(2026, 5, 26, 11, 30),
            duration_seconds=1800,
        ),
    ]
    seq = build_sequence_rows(rows)
    b = build_mode_b_work_span(seq)["summary"]
    assert b["work_window_start"] == datetime(2026, 5, 26, 9, 0)
    assert b["work_window_end"] == datetime(2026, 5, 26, 11, 30)
    assert b["work_window_minutes"] == 150.0
    assert b["folding_minutes"] == 40.0
    assert b["idle_minutes"] == 110.0


def test_gap_between_bags_calculated_correctly():
    rows = [
        _perf_row(
            "A",
            start=datetime(2026, 5, 26, 10, 0),
            end=datetime(2026, 5, 26, 10, 10),
            duration_seconds=600,
        ),
        _perf_row(
            "B",
            start=datetime(2026, 5, 26, 10, 25),
            end=datetime(2026, 5, 26, 10, 50),
            duration_seconds=1500,
        ),
    ]
    seq = build_sequence_rows(rows)
    assert seq[0]["gap_seconds_from_previous"] is None
    assert seq[1]["gap_seconds_from_previous"] == 15 * 60
    assert seq[1]["gap_minutes_from_previous"] == 15.0
    assert build_mode_a_bag_wise(seq)["summary"]["total_gap_minutes"] == 15.0


def test_total_folded_includes_exceptions_scoring_excludes():
    rows = [
        _perf_row(
            "OK",
            start=datetime(2026, 5, 26, 9, 0),
            end=datetime(2026, 5, 26, 9, 15),
            duration_seconds=900,
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
    seq = build_sequence_rows(rows)
    s = build_mode_a_bag_wise(seq)["summary"]
    assert s["total_bags"] == 2
    assert s["scoring_bags"] == 1
    assert s["exception_bags"] == 1


def test_two_minute_row_visible_not_in_scoring(monkeypatch):
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
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.ensure_rinse_folding_tables",
        lambda c: None,
    )
    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="Jennifer",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert len(out["mode_a_bag_wise"]["rows"]) == 1
    assert out["mode_a_bag_wise"]["summary"]["scoring_bags"] == 0
    diag = out["diagnostics"]["short_duration_bags"]
    assert len(diag) == 1
    assert diag[0]["bag_id"] == "JEN"
    assert diag[0]["included_in_scoring"] == 0
    assert diag[0]["in_leaderboard_scoring"] is False


def test_unmapped_user_mode_c_unavailable(monkeypatch):
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.load_user_performance_rows",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.get_user_map",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.ensure_rinse_folding_tables",
        lambda c: None,
    )

    class Cur:
        def execute(self, *a, **k):
            pass

    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="Nobody",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    c = out["mode_c_clock_hours"]
    assert c["available"] is False
    assert "No employee clock mapping" in c["message"]


def test_mapping_enables_mode_c(monkeypatch):
    rows = [
        _perf_row(
            "A",
            start=datetime(2026, 5, 26, 10, 0),
            end=datetime(2026, 5, 26, 10, 15),
            duration_seconds=900,
        ),
    ]
    shifts = [
        {
            "id": 1,
            "clock_in_at": datetime(2026, 5, 26, 9, 0),
            "clock_out_at": datetime(2026, 5, 26, 12, 0),
            "status": "closed",
            "net_work_seconds": 10800,
        }
    ]

    class Cur:
        def __init__(self):
            self._shift_rows = shifts

        def execute(self, sql, args=None):
            self.last_sql = sql

        def fetchall(self):
            return self._shift_rows

        def fetchone(self):
            return None

    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.load_user_performance_rows",
        lambda *a, **k: rows,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.get_user_map",
        lambda *a, **k: {"user_id": 42, "display_name": "Clock User"},
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.ta_helpers.table_exists",
        lambda c, t: t == "shift_sessions",
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity._last_rinse_sync_naive",
        lambda c, o: None,
    )

    out = build_user_folding_productivity(
        Cur(),
        3,
        user_name="Mapped",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["mode_c_clock_hours"]["available"] is True
    assert out["mode_c_clock_hours"]["summary"]["clocked_minutes"] == 180.0


def test_mode_c_uses_shift_clock_times(monkeypatch):
    seq = build_sequence_rows(
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
            self.args = args

        def fetchall(self):
            return shifts

    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda c, t: True)
    monkeypatch.setattr(
        "backend.rinse_folding_user_productivity._last_rinse_sync_naive",
        lambda c, o: None,
    )
    cur = Cur()
    out = build_mode_c_clock_hours(
        cur,
        3,
        user_id=5,
        seq_rows=seq,
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert "shift_sessions" in cur.sql
    assert out["shifts"][0]["clock_in_at"] == datetime(2026, 5, 26, 8, 0)
    assert out["shifts"][0]["clock_out_at"] == datetime(2026, 5, 26, 17, 0)
    assert out["summary"]["clocked_minutes"] == 9 * 60


def test_active_shift_uses_last_sync_estimate(monkeypatch):
    seq = []
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
    out = build_mode_c_clock_hours(
        Cur(),
        3,
        user_id=1,
        seq_rows=seq,
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    sh = out["shifts"][0]
    assert sh["is_active_estimate"] is True
    assert sh["effective_clock_out_at"] == sync_at
    assert "Rinse sync" in (sh["estimate_label"] or "")
