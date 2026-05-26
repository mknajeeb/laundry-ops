"""User folding sequence, gaps, and recompute metadata."""

from datetime import date, datetime

import pytest

from backend.rinse_folding_user_sequence import build_user_folding_sequence


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.last_sql = ""

    def execute(self, sql, args=None):
        self.last_sql = sql

    def fetchall(self):
        return self._rows


def _row(
    bag_id,
    *,
    start,
    end,
    status="CALCULATED",
    exception_code=None,
    included=1,
    lbs=10.0,
):
    dur = int((end - start).total_seconds()) if start and end else None
    return {
        "bag_id": bag_id,
        "name_clean": f"Cust {bag_id}",
        "weight_lbs": lbs,
        "registry_weight_num": lbs,
        "folding_start_at": start,
        "folding_end_at": end,
        "duration_seconds": dur,
        "status": status,
        "scoring_status": status,
        "exception_code": exception_code,
        "included_in_scoring": included,
        "excluded_from_performance": 0,
    }


def test_sequence_sorts_by_folding_start(monkeypatch):
    rows = [
        _row("A", start=datetime(2026, 5, 26, 9, 0), end=datetime(2026, 5, 26, 9, 20)),
        _row("B", start=datetime(2026, 5, 26, 11, 0), end=datetime(2026, 5, 26, 11, 30)),
    ]
    cur = FakeCursor(rows)
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.sql_period_filter_sql_and_args",
        lambda *a, **k: (" AND 1=1", []),
    )
    out = build_user_folding_sequence(
        cur,
        3,
        user_name="Test User",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert "folding_start_at ASC" in cur.last_sql
    assert [r["bag_id"] for r in out["rows"]] == ["A", "B"]


def test_gap_first_row_null_second_calculated(monkeypatch):
    rows = [
        _row("A", start=datetime(2026, 5, 26, 10, 0), end=datetime(2026, 5, 26, 10, 10)),
        _row("B", start=datetime(2026, 5, 26, 10, 25), end=datetime(2026, 5, 26, 10, 50)),
    ]
    cur = FakeCursor(rows)
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.sql_period_filter_sql_and_args",
        lambda *a, **k: (" AND 1=1", []),
    )
    out = build_user_folding_sequence(
        cur,
        3,
        user_name="Test User",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["rows"][0]["gap_minutes_from_previous"] is None
    assert out["rows"][1]["gap_minutes_from_previous"] == 15.0
    assert out["summary"]["total_gap_minutes"] == 15.0


def test_overlap_gap_zero(monkeypatch):
    rows = [
        _row("A", start=datetime(2026, 5, 26, 10, 0), end=datetime(2026, 5, 26, 10, 30)),
        _row(
            "B",
            start=datetime(2026, 5, 26, 10, 15),
            end=datetime(2026, 5, 26, 10, 45),
        ),
    ]
    cur = FakeCursor(rows)
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.sql_period_filter_sql_and_args",
        lambda *a, **k: (" AND 1=1", []),
    )
    out = build_user_folding_sequence(
        cur,
        3,
        user_name="Test User",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["rows"][1]["gap_overlap"] is True
    assert out["rows"][1]["gap_minutes_from_previous"] == 0.0


def test_total_bags_includes_exceptions(monkeypatch):
    rows = [
        _row(
            "A",
            start=datetime(2026, 5, 26, 10, 0),
            end=datetime(2026, 5, 26, 10, 2),
            status="EXCEPTION",
            exception_code="FOLDING_DURATION_TOO_SHORT",
            included=0,
        ),
        _row("B", start=datetime(2026, 5, 26, 11, 0), end=datetime(2026, 5, 26, 11, 30)),
    ]
    cur = FakeCursor(rows)
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.sql_period_filter_sql_and_args",
        lambda *a, **k: (" AND 1=1", []),
    )
    out = build_user_folding_sequence(
        cur,
        3,
        user_name="Test User",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    assert out["summary"]["total_bags"] == 2
    assert out["summary"]["scoring_bags"] == 1
    assert out["summary"]["not_in_scoring_bags"] == 1


def test_two_minute_bag_not_in_scoring(monkeypatch):
    rows = [
        _row(
            "SHORT",
            start=datetime(2026, 5, 26, 9, 3),
            end=datetime(2026, 5, 26, 9, 5),
            status="EXCEPTION",
            exception_code="FOLDING_DURATION_TOO_SHORT",
            included=0,
        ),
    ]
    cur = FakeCursor(rows)
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.ensure_rinse_folding_tables",
        lambda c: None,
    )
    monkeypatch.setattr(
        "backend.rinse_folding_user_sequence.sql_period_filter_sql_and_args",
        lambda *a, **k: (" AND 1=1", []),
    )
    out = build_user_folding_sequence(
        cur,
        3,
        user_name="Jennifer",
        period_start=date(2026, 5, 26),
        period_end=date(2026, 5, 26),
    )
    r = out["rows"][0]
    assert r["status"] == "EXCEPTION"
    assert r["exception_code"] == "FOLDING_DURATION_TOO_SHORT"
    assert r["included_in_scoring"] is False


def test_recompute_needed_when_rules_saved_after_recompute():
    from backend.rinse_folding_exception_rules import get_folding_rules_meta

    class C:
        def execute(self, sql, args):
            pass

        def fetchone(self):
            return {"svalue": "2026-05-27T10:00:00Z"}

    cur = C()

    def fake_get(cursor, org, key):
        if "saved" in key:
            return "2026-05-27T12:00:00Z"
        return "2026-05-27T10:00:00Z"

    import backend.rinse_folding_exception_rules as mod

    orig = mod._get_setting
    mod._get_setting = fake_get
    try:
        meta = get_folding_rules_meta(cur, 3)
        assert meta["recompute_needed"] is True
    finally:
        mod._get_setting = orig
