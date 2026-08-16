"""WF PRE/POST compact weight totals for Management Rinse WF."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.management_today import load_wf_day_weight_totals


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


def test_wf_weight_totals_sum_pre_and_completed_post_by_rush(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: True)
    monkeypatch.setattr("backend.management_today.table_has_column", lambda *a, **k: True)
    cur = _Cur(
        [
            {"rush_status": "RUSH", "pre_lbs": 100.5, "post_lbs": 90.0},
            {"rush_status": "NON-RUSH", "pre_lbs": 50.0, "post_lbs": 40.25},
        ]
    )
    out = load_wf_day_weight_totals(cur, 3, date(2026, 8, 16))
    assert out["rush_filtering_supported"] is True
    assert out["pre_lbs"] == 150.5
    assert out["post_lbs"] == 130.2
    assert out["by_rush"]["rush"]["pre_lbs"] == 100.5
    assert out["by_rush"]["non_rush"]["post_lbs"] == 40.2
    assert "rinse_shift_monitor_day_bags" in out["source"]
    assert "GROUP BY" in cur.sql.upper()
    assert "rinse_bag_scan_events" not in cur.sql.lower()


def test_wf_weight_totals_empty_when_table_missing(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: False)
    out = load_wf_day_weight_totals(MagicMock(), 3, date(2026, 8, 16))
    assert out["pre_lbs"] is None
    assert out["post_lbs"] is None
    assert out["rush_filtering_supported"] is False
