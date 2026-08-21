"""Historical closed-day snapshot isolation — never wipe workload with weights-only publish."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from backend.rinse_freshness_publish import publish_snapshot
from backend.rinse_management_headline_guard import (
    headline_has_wf_workload_segments,
    merge_weights_into_headline,
)


def test_weights_only_headline_is_not_valid_management_snapshot():
    assert not headline_has_wf_workload_segments(
        {"shift_date_et": "2026-08-20", "weights": {"by_rush": {"all": {}}}, "repair": "x"}
    )
    assert headline_has_wf_workload_segments(
        {
            "segments": {
                "wf": {
                    "total_workload": 143,
                    "completed": 115,
                    "pending": 0,
                    "exceptions": {"review_required": 0},
                }
            }
        }
    )


def test_merge_weights_preserves_segments():
    base = {
        "segments": {"wf": {"total_workload": 143, "completed": 115, "pending": 0}},
        "selected_date_et": "2026-08-20",
    }
    out = merge_weights_into_headline(
        base, {"by_rush": {"all": {"pre_lbs": 1}}}, repair_tag="t"
    )
    assert out["segments"]["wf"]["total_workload"] == 143
    assert out["weights"]["by_rush"]["all"]["pre_lbs"] == 1
    assert out["repair"] == "t"


def test_publish_snapshot_refuses_weights_only_headline(monkeypatch):
    monkeypatch.setattr(
        "backend.rinse_freshness_publish.assert_lane_writable", lambda *a, **k: None
    )
    cur = MagicMock()
    cur.fetchone.return_value = {
        "lease_generation": 1,
        "publish_status": "building",
    }
    with pytest.raises(ValueError, match="missing WF workload segments"):
        publish_snapshot(
            cur,
            organization_id=3,
            shift_date_et=date(2026, 8, 20),
            version=61,
            lease_generation=1,
            lane="deep",
            headline={
                "shift_date_et": "2026-08-20",
                "weights": {"x": 1},
                "repair": "authoritative_pre_post_weights",
            },
            workload_meta={"source": "authoritative_weight_repair"},
        )


def test_publish_snapshot_allows_partial_only_when_explicit(monkeypatch):
    monkeypatch.setattr(
        "backend.rinse_freshness_publish.assert_lane_writable", lambda *a, **k: None
    )
    cur = MagicMock()
    cur.fetchone.return_value = {
        "lease_generation": 1,
        "publish_status": "building",
    }
    publish_snapshot(
        cur,
        organization_id=3,
        shift_date_et=date(2026, 8, 20),
        version=61,
        lease_generation=1,
        lane="deep",
        headline={"weights": {"x": 1}},
        workload_meta={"allow_partial_headline": True},
    )
    assert cur.execute.call_count >= 2


def test_load_headline_falls_through_when_published_is_weights_only(monkeypatch):
    from backend import management_today as mt
    import backend.rinse_veewash_shift_day as sd

    published = {
        "version": 60,
        "headline_json": {
            "repair": "pre_select_empty_we_fix",
            "weights": {"by_rush": {"all": {"pre_lbs": 2458.3}}},
            "shift_date_et": "2026-08-20",
        },
        "published_at": None,
    }
    day = {
        "status": "CLOSED",
        "headline": {
            "segments": {
                "wf": {
                    "total_workload": 143,
                    "completed": 115,
                    "pending": 0,
                    "carried_forward": 28,
                    "exceptions": {"review_required": 0},
                }
            },
            "active_workload": 143,
            "total_workload": 143,
            "completed": 115,
            "pending": 0,
            "selected_date_et": "2026-08-20",
        },
        "workload_meta": {},
        "review_required_count": 0,
        "last_sync_at": "2026-08-21T03:00:00",
    }

    monkeypatch.setattr(
        "backend.rinse_freshness_publish.latest_published_snapshot",
        lambda *a, **k: published,
    )
    monkeypatch.setattr(sd, "get_day_record", lambda *a, **k: day)
    monkeypatch.setattr(
        sd,
        "summary_from_day_record",
        lambda d, **k: dict(d.get("headline") or {}),
    )
    monkeypatch.setattr(sd, "STATUS_NOT_STARTED", "NOT_STARTED")
    monkeypatch.setattr(
        sd, "_snapshot_missing_step1_payload", lambda *a, **k: ({}, {}, {})
    )
    monkeypatch.setattr(mt, "_specialty_packs_current", lambda *a, **k: True)

    _day_rec, headline = mt._load_headline(MagicMock(), 3, date(2026, 8, 20))
    assert ((headline.get("segments") or {}).get("wf") or {}).get(
        "total_workload"
    ) == 143
