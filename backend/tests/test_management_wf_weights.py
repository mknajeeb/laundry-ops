"""WF PRE/POST compact weight totals for Management Rinse WF."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.management_today import load_wf_day_weight_totals


class _Cur:
    def __init__(self, bag_rows, post_group_rows):
        self.bag_rows = bag_rows
        self.post_group_rows = post_group_rows
        self.sql = ""
        self._call = 0

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params
        self._call += 1

    def fetchall(self):
        if "GROUP BY" in self.sql.upper():
            return self.post_group_rows
        return self.bag_rows


def test_wf_weight_totals_sum_evidence_not_completion(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: True)
    monkeypatch.setattr("backend.management_today.table_has_column", lambda *a, **k: True)
    cur = _Cur(
        [
            {"bag_id": "BAG1", "rush_status": "RUSH"},
            {"bag_id": "BAG2", "rush_status": "RUSH"},
            {"bag_id": "BAG3", "rush_status": "NON-RUSH"},
        ],
        [
            {
                "rush_status": "RUSH",
                "post_lbs": 90.0,
                "post_bag_count": 2,
            },
            {
                "rush_status": "NON-RUSH",
                "post_lbs": 40.25,
                "post_bag_count": 1,
            },
        ],
    )

    def _weight_map(cursor, org, ids, *, selected_date_et):
        return {
            "BAG1": {"pre_weight_lbs": 50.0, "pre_weight_event_id": 1},
            "BAG2": {"pre_weight_lbs": 50.5, "pre_weight_event_id": 2},
            "BAG3": {"pre_weight_lbs": 50.0, "pre_weight_event_id": 3},
        }

    monkeypatch.setattr(
        "backend.rinse_veewash_review.load_bag_weight_map",
        _weight_map,
    )
    out = load_wf_day_weight_totals(cur, 3, date(2026, 8, 16))
    assert out["rush_filtering_supported"] is True
    assert out["pre_lbs"] == 150.5
    assert out["post_lbs"] == 130.2
    assert out["pre_weight_lbs"] == 150.5
    assert out["post_weight_lbs"] == 130.2
    assert out["pre_weight_bag_count"] == 3
    assert out["post_weight_bag_count"] == 3
    assert out["by_rush"]["rush"]["pre_weight_bag_count"] == 2
    assert out["by_rush"]["rush"]["post_weight_lbs"] == 90.0
    assert out["by_rush"]["non_rush"]["post_lbs"] == 40.2
    assert "COMPLETED" not in cur.sql.upper()
    assert "canonical_pre_resolver" in out["source"]


def test_drawer_and_headline_share_authoritative_pre(monkeypatch):
    from backend.management_rinse_wf_review import _canonical_review_weights, _merge_review_weight_fields
    from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs

    weights = {
        "BAG1": {
            "pre_weight_lbs": 15.7,
            "pre_weight_source": "portal_wf_lbs_num",
            "pre_weight_event_id": 2,
            "post_weight_lbs": 16.2,
            "post_weight_event_id": 4,
        }
    }
    monkeypatch.setattr(
        "backend.management_rinse_wf_review._canonical_review_weights",
        lambda *a, **k: weights,
    )
    bag = {"pre_weight_lbs": None, "evidence_pre_weight_lbs": None}
    _merge_review_weight_fields(bag, weights["BAG1"])
    assert bag["pre_weight_lbs"] == 15.7
    assert authoritative_evidence_pre_lbs(weights["BAG1"]) == 15.7


def test_wf_weight_totals_post_only_bag_contributes_zero_pre(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: True)
    monkeypatch.setattr("backend.management_today.table_has_column", lambda *a, **k: True)
    cur = _Cur(
        [{"bag_id": "0WMBKDYLS0", "rush_status": "NON-RUSH"}],
        [{"rush_status": "NON-RUSH", "post_lbs": 13.1, "post_bag_count": 1}],
    )

    monkeypatch.setattr(
        "backend.rinse_veewash_review.load_bag_weight_map",
        lambda *a, **k: {
            "0WMBKDYLS0": {
                "pre_weight_lbs": None,
                "pre_weight_event_id": None,
                "post_weight_lbs": 13.1,
                "post_weight_event_id": 99,
            }
        },
    )
    out = load_wf_day_weight_totals(cur, 3, date(2026, 8, 22))
    assert out["pre_lbs"] is None
    assert out["pre_weight_bag_count"] == 0
    assert out["post_weight_lbs"] == 13.1
    assert out["post_weight_bag_count"] == 1


def test_wf_weight_totals_empty_when_table_missing(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: False)
    out = load_wf_day_weight_totals(MagicMock(), 3, date(2026, 8, 16))
    assert out["pre_lbs"] is None
    assert out["post_lbs"] is None
    assert out["pre_weight_bag_count"] == 0
    assert out["rush_filtering_supported"] is False
