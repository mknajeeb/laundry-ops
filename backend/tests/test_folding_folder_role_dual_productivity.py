"""Tests for Rinse WF — Folder dual productivity averages (Folding Performance)."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

from backend.rinse_folding_et import eastern_today
from backend.rinse_folding_folder_role_productivity import (
    aggregate_folder_dual_productivity,
    apply_folder_dual_productivity_to_section,
    bags_in_segment,
    compute_employee_folder_dual_productivity,
    compute_folder_segment_dual_productivity,
    resolve_effective_role_end,
    _bag_credited_lbs_pre,
)

TARGET = 35.0
DAY = date(2026, 7, 10)


def _bag(
    bag_id: str,
    completion: str,
    lbs: float = 22.0,
    service: str = "WF",
    *,
    pre: float | None = None,
    post: float | None = None,
) -> dict:
    pre_lbs = pre if pre is not None else lbs
    row = {
        "bag_id": bag_id,
        "service_type": service,
        "service_bucket": service,
        "completion_time": completion,
        "completion_timestamp": completion,
        "credit_timestamp": completion,
        "credited_weight_lbs": pre_lbs,
        "credited_weight_source": "EVIDENCE_PRE",
        "credited_lbs": pre_lbs,
    }
    if post is not None:
        row["output_weight_lbs"] = post
        row["authoritative_post_weight_lbs"] = post
        row["weight_lbs"] = post  # POST-synced display must not affect Folder credit
        row["completed_lbs"] = post
    else:
        row["weight_lbs"] = pre_lbs
        row["completed_lbs"] = pre_lbs
    return row


def _seg(
    start: str,
    end: str | None = None,
    *,
    cat: str = "RINSE_WF",
    role: str = "FOLDER",
    sid: int = 1,
    session_id: int = 100,
) -> dict:
    return {
        "id": sid,
        "shift_session_id": session_id,
        "category_code": cat,
        "role_code": role,
        "category_name_snapshot": "Rinse WF" if cat == "RINSE_WF" else cat,
        "role_name_snapshot": "Folder" if role == "FOLDER" else "Operator",
        "started_at": start,
        "ended_at": end,
    }


def _iso(d: date, hour: int, minute: int = 0, second: int = 0) -> str:
    return datetime(d.year, d.month, d.day, hour, minute, second).isoformat()


class TestClosedFolderRoleWithBags:
    def test_example_from_spec(self):
        bags = [
            _bag(f"B{i}", f"2026-07-10T0{7 + (i // 3)}:{(i * 7) % 60:02d}:00", 22.0)
            for i in range(7)
        ]
        bags.append(_bag("B7", "2026-07-10T10:18:00", 22.0))
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            role_end=datetime(2026, 7, 10, 11, 0, 0),
            bags=bags,
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
            now_et=datetime(2026, 7, 10, 15, 0, 0),
        )
        assert result["role_hours"] == 4.0
        assert result["active_completion_hours"] == 3.3
        assert abs(result["idle_time_hours"] - 0.7) < 0.0001
        assert result["role_bags_per_hour"] == 2.0
        assert result["role_lbs_per_hour"] == 44.0
        assert result["role_productivity_pct"] == 125.7
        assert result["active_productivity_pct"] == 152.4
        assert result["role_status"] == "closed"
        assert result["role_end_missing"] is False


class TestOpenFolderRoleCurrentDay:
    def test_open_uses_current_et_time(self):
        today = eastern_today()
        bags = [_bag("A1", _iso(today, 8, 0), 35.0)]
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(today.year, today.month, today.day, 7, 0, 0),
            role_end=None,
            bags=bags,
            selected_date_et=today,
            folding_target_lbs_per_hour=TARGET,
            now_et=datetime(today.year, today.month, today.day, 9, 0, 0),
        )
        assert result["role_status"] == "open"
        assert result["end_source"] == "current_et_now"
        assert result["role_hours"] == 2.0
        assert result["active_completion_hours"] == 1.0
        assert result["idle_time_hours"] == 1.0
        assert result["role_end_missing"] is False


class TestHistoricalUnresolvedOpenNoMidnight:
    def test_historical_open_does_not_use_midnight(self):
        hist = eastern_today() - timedelta(days=3)
        info = resolve_effective_role_end(
            role_start=datetime(hist.year, hist.month, hist.day, 7, 0, 0),
            role_end=None,
            selected_date_et=hist,
            now_et=datetime(hist.year, hist.month, hist.day, 18, 0, 0) + timedelta(days=2),
        )
        assert info["effective_end"] is None
        assert info["role_end_missing"] is True
        assert info["rates_provisional"] is True
        assert info["include_in_authoritative_aggregate"] is False
        assert info["role_status"] == "unresolved"
        # Must not silently equal day-end 23:59:59
        assert info["effective_end"] != datetime(hist.year, hist.month, hist.day, 23, 59, 59)

        result = compute_folder_segment_dual_productivity(
            role_start=datetime(hist.year, hist.month, hist.day, 7, 0, 0),
            role_end=None,
            bags=[_bag("H1", _iso(hist, 8, 0), 20.0)],
            selected_date_et=hist,
            folding_target_lbs_per_hour=TARGET,
        )
        assert result["role_end_missing"] is True
        assert result["role_hours"] is None
        assert result["role_bags_per_hour"] is None
        assert result["include_in_authoritative_aggregate"] is False


class TestAttendanceCheckoutEndsOpenRole:
    def test_session_checkout_closes_otherwise_open_role(self):
        hist = eastern_today() - timedelta(days=2)
        checkout = datetime(hist.year, hist.month, hist.day, 15, 30, 0)
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(hist.year, hist.month, hist.day, 7, 0, 0),
            role_end=None,
            bags=[_bag("C1", _iso(hist, 10, 0), 35.0)],
            selected_date_et=hist,
            folding_target_lbs_per_hour=TARGET,
            session_clock_out=checkout,
        )
        assert result["role_end_missing"] is False
        assert result["end_source"] == "session_checkout"
        assert result["effective_role_end"] == checkout.isoformat()
        assert result["role_hours"] == 8.5
        assert result["role_status"] == "closed"


class TestNextSegmentStartEndsOpenRole:
    def test_next_segment_start_bounds_folder_role(self):
        hist = eastern_today() - timedelta(days=2)
        next_start = datetime(hist.year, hist.month, hist.day, 12, 0, 0)
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(hist.year, hist.month, hist.day, 7, 0, 0),
            role_end=None,
            bags=[_bag("N1", _iso(hist, 9, 0), 20.0)],
            selected_date_et=hist,
            folding_target_lbs_per_hour=TARGET,
            next_segment_start=next_start,
        )
        assert result["end_source"] == "next_segment_start"
        assert result["role_hours"] == 5.0
        assert result["role_end_missing"] is False


class TestNoCompletedBags:
    def test_entire_segment_is_idle_and_active_rates_na(self):
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            role_end=datetime(2026, 7, 10, 11, 0, 0),
            bags=[],
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
        )
        assert result["completed_bags"] == 0
        assert result["active_completion_hours"] == 0.0
        assert result["active_bags_per_hour"] is None
        assert result["active_lbs_per_hour"] is None
        assert result["active_productivity_pct"] is None
        assert result["idle_time_hours"] == 4.0
        assert result["role_hours"] == 4.0


class TestPostCorrectionDoesNotChangePreRates:
    def test_post_correction_ignored_for_folder_lbs(self):
        bag = _bag("P1", "2026-07-10T08:00:00", pre=20.0, post=99.0)
        assert _bag_credited_lbs_pre(bag) == 20.0
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            role_end=datetime(2026, 7, 10, 9, 0, 0),
            bags=[bag],
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
        )
        assert result["credited_lbs"] == 20.0
        assert result["role_lbs_per_hour"] == 10.0  # 20 / 2h
        assert result["credited_weight_basis"] == "EVIDENCE_PRE"


class TestCompletionOutsideRoleSegment:
    def test_excludes_before_and_after(self):
        bags = [
            _bag("BEFORE", "2026-07-10T06:59:00", 10.0),
            _bag("IN", "2026-07-10T08:00:00", 10.0),
            _bag("AFTER", "2026-07-10T11:01:00", 10.0),
        ]
        result = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            role_end=datetime(2026, 7, 10, 11, 0, 0),
            bags=bags,
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
        )
        assert result["completed_bags"] == 1
        assert result["eligible_bag_ids"] == ["IN"]


class TestOneBagOneSegment:
    def test_bag_not_duplicated_across_overlapping_segments(self):
        # Overlapping / malformed Folder windows — bag at 08:00 must count once.
        segs = [
            _seg("2026-07-10T07:00:00", "2026-07-10T11:00:00", sid=1),
            _seg("2026-07-10T07:30:00", "2026-07-10T10:00:00", sid=2),
        ]
        bags = [_bag("ONCE", "2026-07-10T08:00:00", 40.0)]
        dual = compute_employee_folder_dual_productivity(
            segments=segs,
            bags=bags,
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
        )
        assert dual is not None
        assert dual["completed_bags"] == 1
        claimed = []
        for s in dual["folder_role_segments"]:
            claimed.extend(s.get("eligible_bag_ids") or [])
        assert claimed.count("ONCE") == 1


class TestCompletionDuringOperatorRole:
    def test_operator_segments_ignored(self):
        segs = [
            _seg(
                "2026-07-10T07:00:00",
                "2026-07-10T09:00:00",
                cat="RINSE_WF",
                role="OPERATOR",
                sid=1,
            ),
            _seg(
                "2026-07-10T09:00:00",
                "2026-07-10T11:00:00",
                cat="RINSE_WF",
                role="FOLDER",
                sid=2,
            ),
        ]
        bags = [
            _bag("OP", "2026-07-10T08:00:00", 50.0),
            _bag("FD", "2026-07-10T10:00:00", 50.0),
        ]
        dual = compute_employee_folder_dual_productivity(
            segments=segs,
            bags=bags,
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
            all_day_segments=segs,
        )
        assert dual is not None
        assert dual["segment_count"] == 1
        assert dual["completed_bags"] == 1
        assert dual["folder_role_segments"][0]["eligible_bag_ids"] == ["FD"]


class TestMultipleFolderSegmentsAggregate:
    def test_summed_denominators_not_averaged_rates(self):
        a = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            role_end=datetime(2026, 7, 10, 8, 0, 0),
            bags=[
                _bag("A1", "2026-07-10T07:20:00", 10.0),
                _bag("A2", "2026-07-10T07:40:00", 10.0),
            ],
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
            segment_id=1,
        )
        b = compute_folder_segment_dual_productivity(
            role_start=datetime(2026, 7, 10, 12, 0, 0),
            role_end=datetime(2026, 7, 10, 15, 0, 0),
            bags=[
                _bag("B1", "2026-07-10T12:30:00", 10.0),
                _bag("B2", "2026-07-10T14:00:00", 10.0),
            ],
            selected_date_et=DAY,
            folding_target_lbs_per_hour=TARGET,
            segment_id=2,
        )
        agg = aggregate_folder_dual_productivity([a, b], folding_target_lbs_per_hour=TARGET)
        assert agg["role_hours"] == 4.0
        assert agg["role_bags_per_hour"] == 1.0
        avg_of_rates = (a["role_bags_per_hour"] + b["role_bags_per_hour"]) / 2
        assert agg["role_bags_per_hour"] != round(avg_of_rates, 4)


class TestUnresolvedExcludedFromAggregate:
    def test_unresolved_duration_excluded_from_authoritative_totals(self):
        hist = eastern_today() - timedelta(days=4)
        closed = compute_folder_segment_dual_productivity(
            role_start=datetime(hist.year, hist.month, hist.day, 7, 0, 0),
            role_end=datetime(hist.year, hist.month, hist.day, 9, 0, 0),
            bags=[_bag("OK", _iso(hist, 8, 0), 20.0)],
            selected_date_et=hist,
            folding_target_lbs_per_hour=TARGET,
            segment_id=1,
        )
        unresolved = compute_folder_segment_dual_productivity(
            role_start=datetime(hist.year, hist.month, hist.day, 12, 0, 0),
            role_end=None,
            bags=[_bag("ORPHAN", _iso(hist, 13, 0), 50.0)],
            selected_date_et=hist,
            folding_target_lbs_per_hour=TARGET,
            segment_id=2,
        )
        assert unresolved["role_end_missing"] is True
        agg = aggregate_folder_dual_productivity(
            [closed, unresolved], folding_target_lbs_per_hour=TARGET
        )
        assert agg["authoritative_segment_count"] == 1
        assert agg["role_hours"] == 2.0
        assert agg["completed_bags"] == 1
        assert agg["credited_lbs"] == 20.0
        assert agg["role_end_missing"] is True
        assert agg["rates_provisional"] is True


class TestNonFolderEmployeesUnchanged:
    def test_operator_employee_fields_unchanged(self):
        section = {
            "employees": [
                {
                    "employee": "Operator Ann",
                    "roster_role": "operator",
                    "productive_hours": 3.25,
                    "completed_bags": 4,
                    "total_completed_lbs": 88.0,
                    "completed_bags_per_hour": 1.2308,
                    "completed_lbs_per_hour": 27.0769,
                    "bags_per_hour": 1.2308,
                    "lbs_per_hour": 27.0769,
                    "bags": [_bag("O1", "2026-07-10T08:00:00", 22.0)],
                }
            ]
        }
        before = deepcopy(section["employees"][0])

        class _Cursor:
            def execute(self, *a, **k):
                return None

            def fetchall(self):
                return []

            def fetchone(self):
                return None

        # No Folder segments loaded → enrichment is a no-op for this employee.
        out = apply_folder_dual_productivity_to_section(
            _Cursor(),
            3,
            section,
            selected_date_et=DAY,
            user_maps={},  # no user map → cannot load segments
        )
        after = out["employees"][0]
        assert after == before
        assert after.get("folder_role_dual_productivity") is None


class TestHdAndNonWfExcluded:
    def test_hd_bag_not_counted(self):
        bags = [
            _bag("HD1", "2026-07-10T08:00:00", 99.0, service="HD"),
            _bag("WF1", "2026-07-10T08:30:00", 20.0, service="WF"),
        ]
        eligible = bags_in_segment(
            bags,
            role_start=datetime(2026, 7, 10, 7, 0, 0),
            effective_end=datetime(2026, 7, 10, 11, 0, 0),
        )
        assert [b["bag_id"] for b in eligible] == ["WF1"]
