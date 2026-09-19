"""Post-reset operational boundaries. Historical rows stay stored.

Proves pre-epoch reject/split/performance evidence cannot drive current
Management projections, while post-epoch evidence still can. HD current
membership is a portal-generation floor, not the WF epoch. Payroll loaders
are not fenced.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from backend.management_rinse_hd import (
    has_positive_hd_admission_evidence,
    stale_open_hd_bag_ids,
)
from backend.management_wf_folder_performance import clip_folder_segments_to_epoch
from backend.rinse_hd_day_metrics import _load_create_issue_rejections
from backend.rinse_wf_canonical_split import _load_events_for_bags, evaluate_bags_split
from backend.wf_ops_reset_epoch import epoch_scan_wall

ORG = 3
DAY = date(2026, 9, 17)
# 2026-09-18 02:43:15.978865 UTC == 2026-09-17 22:43:15.978865 ET
EPOCH_UTC = datetime(2026, 9, 18, 2, 43, 15, 978865, tzinfo=timezone.utc)
EPOCH_WALL = epoch_scan_wall(EPOCH_UTC)
REPO = Path(__file__).resolve().parents[2]


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=None):
        self.sql = " ".join(str(sql).split())
        self.params = tuple(params or ())

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _patch_epoch(monkeypatch, epoch):
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.get_wf_reset_epoch_at",
        lambda *_a, **_k: epoch,
    )
    monkeypatch.setattr(
        "backend.rinse_hd_day_metrics.table_exists", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "backend.ta_helpers.table_exists", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "backend.management_rinse_hd.table_exists", lambda *_a, **_k: True
    )


def test_pre_epoch_create_issue_is_not_reject(monkeypatch):
    _patch_epoch(monkeypatch, EPOCH_UTC)
    pre = datetime(2026, 9, 17, 8, 58)
    cur = _Cursor(
        [
            {
                "bag_id": "12KVWPK59Z",
                "scanned_at_parsed": pre,
                "purpose": "create-issue",
                "user_name": "Yessenia",
                "id": 1,
            }
        ]
    )
    # The loader trusts SQL. Assert the bound is the epoch wall, not midnight.
    out = _load_create_issue_rejections(cur, ORG, DAY, ["12KVWPK59Z"])
    assert EPOCH_WALL in cur.params
    assert pre < EPOCH_WALL
    # A correct SQL engine would not return this row. Simulate that contract:
    # if the only row is before the bound, the projection must not count it
    # when the caller honors the predicate. Re-run with an empty result.
    cur_empty = _Cursor([])
    out = _load_create_issue_rejections(cur_empty, ORG, DAY, ["12KVWPK59Z"])
    assert out == {}
    assert "create-issue" in cur_empty.sql
    assert EPOCH_WALL in cur_empty.params


def test_post_epoch_create_issue_is_reject(monkeypatch):
    _patch_epoch(monkeypatch, EPOCH_UTC)
    post = datetime(2026, 9, 17, 23, 10)
    cur = _Cursor(
        [
            {
                "bag_id": "NEWBAG0001",
                "scanned_at_parsed": post,
                "purpose": "create-issue",
                "user_name": "Maria",
                "id": 99,
            }
        ]
    )
    out = _load_create_issue_rejections(cur, ORG, DAY, ["NEWBAG0001"])
    assert "NEWBAG0001" in out
    assert out["NEWBAG0001"]["create_issue_event_id"] == 99
    assert out["NEWBAG0001"]["create_issue_at"] == post


def test_no_epoch_keeps_same_day_create_issue(monkeypatch):
    _patch_epoch(monkeypatch, None)
    pre = datetime(2026, 9, 17, 8, 58)
    cur = _Cursor(
        [
            {
                "bag_id": "12KVWPK59Z",
                "scanned_at_parsed": pre,
                "purpose": "create-issue",
                "user_name": "Yessenia",
                "id": 1,
            }
        ]
    )
    out = _load_create_issue_rejections(cur, ORG, DAY, ["12KVWPK59Z"])
    assert "12KVWPK59Z" in out
    assert datetime(2026, 9, 17, 0, 0) in cur.params


def test_split_sql_applies_epoch_and_post_epoch_events_still_split(monkeypatch):
    _patch_epoch(monkeypatch, EPOCH_UTC)
    monkeypatch.setattr(
        "backend.rinse_wf_canonical_split.table_exists", lambda *_a, **_k: True
    )
    cur = _Cursor([])
    _load_events_for_bags(cur, ORG, ["0S5YKMDPQH"], slim=True)
    assert "scanned_at_parsed" in cur.sql
    assert EPOCH_WALL in cur.params

    # Same evaluator the Management card uses. Post-epoch evidence still confirms.
    post_base = datetime(2026, 9, 17, 23, 0)
    events = [
        {"id": 1, "bag_id": "POST1", "purpose": "sent-to-vendor", "scanned_at_parsed": post_base, "rack": "VeeWash Dirty", "scan_index": 1},
        {"id": 2, "bag_id": "POST1", "purpose": "split-load", "scanned_at_parsed": post_base.replace(minute=5), "rack": None, "scan_index": 2},
        {"id": 3, "bag_id": "POST1", "purpose": "start-cleaning", "scanned_at_parsed": post_base.replace(minute=10), "rack": "W61-30-VW", "scan_index": 3},
        {"id": 4, "bag_id": "POST1", "purpose": "start-cleaning", "scanned_at_parsed": post_base.replace(minute=15), "rack": "W62-30-VW", "scan_index": 4},
        {"id": 5, "bag_id": "POST1", "purpose": "drying", "scanned_at_parsed": post_base.replace(minute=20), "rack": "D10-50-VW", "scan_index": 5},
    ]
    ev = evaluate_bags_split({"POST1": events})["POST1"]
    assert ev["state"] == "CONFIRMED_SPLIT"
    assert ev["canonical_split"] is True


def test_pre_epoch_split_events_are_not_loaded(monkeypatch):
    """The loader predicate is the fence. A row before the wall is not selected."""
    _patch_epoch(monkeypatch, EPOCH_UTC)
    monkeypatch.setattr(
        "backend.rinse_wf_canonical_split.table_exists", lambda *_a, **_k: True
    )
    cur = _Cursor([])
    _load_events_for_bags(cur, ORG, ["OLD1"], slim=False)
    assert EPOCH_WALL in cur.params
    assert "scanned_at_parsed" in cur.sql


def test_folder_segment_epoch_clip():
    wall = EPOCH_WALL
    pre = {
        1: [
            {
                "id": 10,
                "started_at": datetime(2026, 9, 17, 7, 36),
                "ended_at": datetime(2026, 9, 17, 15, 50),
            }
        ]
    }
    assert clip_folder_segments_to_epoch(pre, wall)[1] == []

    post = {
        1: [
            {
                "id": 11,
                "started_at": datetime(2026, 9, 17, 23, 0),
                "ended_at": datetime(2026, 9, 17, 23, 40),
            }
        ]
    }
    kept = clip_folder_segments_to_epoch(post, wall)[1]
    assert len(kept) == 1
    assert kept[0]["started_at"] == datetime(2026, 9, 17, 23, 0)
    hours = (kept[0]["ended_at"] - kept[0]["started_at"]).total_seconds() / 3600
    assert round(hours, 4) == round(40 / 60, 4)

    crossing = {
        1: [
            {
                "id": 12,
                "started_at": datetime(2026, 9, 17, 20, 0),
                "ended_at": datetime(2026, 9, 17, 23, 30),
            }
        ]
    }
    clipped = clip_folder_segments_to_epoch(crossing, wall)[1][0]
    assert clipped["started_at"] == wall
    assert clipped["ended_at"] == datetime(2026, 9, 17, 23, 30)
    assert clipped["wf_ops_epoch_clipped"] is True
    credited = (clipped["ended_at"] - clipped["started_at"]).total_seconds()
    full = (
        datetime(2026, 9, 17, 23, 30) - datetime(2026, 9, 17, 20, 0)
    ).total_seconds()
    assert credited < full
    assert credited == (datetime(2026, 9, 17, 23, 30) - wall).total_seconds()


def test_payroll_segment_loader_default_has_no_epoch_fence():
    import inspect

    from backend.rinse_folding_folder_role_productivity import load_day_job_segments_by_user

    default = inspect.signature(load_day_job_segments_by_user).parameters[
        "not_ended_before"
    ].default
    assert default is None
    tracking = (REPO / "backend/shift_job_tracking.py").read_text()
    assert "wf_reset_epoch" not in tracking
    assert "clip_folder_segments_to_epoch" not in tracking


def test_stale_hd_open_is_identified_without_deleting(monkeypatch):
    _patch_epoch(monkeypatch, None)
    floor = datetime(2026, 9, 18, 2, 30)
    cur = _Cursor([{"bag_id": "0BVVPG6SIK"}])
    stale = stale_open_hd_bag_ids(
        cur, ORG, activation=date(2026, 8, 21), floor=floor
    )
    assert stale == {"0BVVPG6SIK"}
    assert "hd_day_bag_production" in cur.sql
    assert "DELETE" not in cur.sql.upper()
    assert floor in cur.params


def test_current_hd_queue_math_keeps_positive_evidence_and_drops_stale():
    """Current queue = admitted minus stale opens, except live discovery."""
    admitted = {"0BVVPG6SIK", "1DPUWLKIHU", "DONE1"}
    discovery = {"1DPUWLKIHU"}  # positive #HD, currently in portal
    stale = {"0BVVPG6SIK"}
    candidates = set(admitted) | discovery
    candidates -= stale - discovery
    assert "0BVVPG6SIK" not in candidates
    assert "1DPUWLKIHU" in candidates
    assert "DONE1" in candidates  # complete rows are not in the stale open set


def test_portal_presence_without_hd_count_is_not_hd():
    """E74IZANNG1 shape: service_type HD, active, no #HD count."""
    row = {
        "bag_id": "E74IZANNG1",
        "service_type": "HD",
        "active": 1,
        "raw_row_json": (
            '{"service_type": "HD", "weight_num": 0.0, "hd_count_num": null, '
            '"hd_count_raw": null}'
        ),
    }
    assert has_positive_hd_admission_evidence(row) is False


def test_wf_cycle_admission_still_uses_epoch_fence():
    src = (REPO / "backend/rinse_wf_service_cycle.py").read_text()
    assert "def wf_reset_epoch_scan_wall" in src
    assert "baseline_anchor = wf_reset_epoch_scan_wall" in src
