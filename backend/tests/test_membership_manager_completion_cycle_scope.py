"""Opening membership: manager correct_completion must be cycle-scoped.

Mirrors load_canonical_completions_v2 / manager_completion_belongs_to_cycle.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_day_membership import _bags_canonically_completed_before_opening

ORG = 3
DAY = date(2026, 8, 13)
RACKS = ["VeeWash Dirty", "Rinse Zipvan"]


def _scan(
    *,
    bag_id: str,
    ts: datetime,
    purpose: str,
    rack: str | None = None,
    user: str = "Ops",
    weight: float | None = None,
    scan_id: int = 1,
) -> dict:
    return {
        "id": scan_id,
        "bag_id": bag_id,
        "purpose": purpose,
        "rack": rack,
        "scanned_at_parsed": ts,
        "user_name": user,
        "weight_lbs": weight,
        "raw_json": None,
    }


def _corr(bag_id: str, completion_at: str, *, completed_by: str = "Manager") -> dict:
    return {
        "bag_id": bag_id,
        "new_values": {
            "completed_by": completed_by,
            "completion_at": completion_at,
        },
    }


def _run_helper(timeline_by_bag: dict[str, list[dict]], corrections: list[dict]):
    """Drive _bags_canonically_completed_before_opening with mocked DB + comps."""
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split()).lower()
        cursor._last_sql = s
        cursor._last_params = params

    def fetchall():
        s = getattr(cursor, "_last_sql", "") or ""
        if "from rinse_bag_scan_events" in s:
            # params: org, *bag_ids, day_start
            params = cursor._last_params or ()
            bag_ids = [
                str(p).strip().upper()
                for p in params[1:]
                if isinstance(p, str) and str(p).strip()
            ]
            rows = []
            for bid in bag_ids:
                rows.extend(timeline_by_bag.get(bid) or [])
            rows.sort(
                key=lambda r: (r.get("scanned_at_parsed"), r.get("id") or 0)
            )
            return rows
        if "from rinse_step1_corrections" in s:
            params = cursor._last_params or ()
            bag_ids = {str(p).strip().upper() for p in params[1:]}
            return [c for c in corrections if str(c.get("bag_id")).upper() in bag_ids]
        return []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = fetchall

    bag_ids = sorted(timeline_by_bag.keys()) or [
        str(c["bag_id"]).strip().upper() for c in corrections
    ]
    with (
        patch("backend.ta_helpers.table_exists", return_value=True),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={},
        ),
        patch(
            "backend.rinse_processing_settings.get_processing_settings",
            return_value={"facility_entry_racks": list(RACKS)},
        ),
    ):
        return _bags_canonically_completed_before_opening(
            cursor,
            ORG,
            DAY,
            bag_ids,
            service_type_by_bag={bid: "WF" for bid in bag_ids},
        )


def test_a_prior_cycle_manager_correction_newer_cycle_not_excluded():
    """A: Jul-30 manager correction must not exclude Aug 12/13 newer cycle."""
    bid = "1ZFBR7HMLX"
    tl = [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 30, 6, 0),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 30, 13, 3),
            purpose="garments-reviewed",
            user="Singh",
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 30, 13, 5),
            purpose="weight-entry",
            user="Mrs Chen",
            weight=25.5,
            scan_id=3,
        ),
        # Newer cycle starts before Today midnight
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 23, 13),
            purpose="sent-to-vendor",
            rack="Rinse Zipvan",
            user="Shaquille",
            scan_id=4,
        ),
    ]
    out = _run_helper(
        {bid: tl},
        [_corr(bid, "2026-07-30T13:05:00", completed_by="Mrs Chen (VeeWash)")],
    )
    assert bid not in out


def test_b_same_cycle_manager_correction_before_opening_still_excludes():
    """B: Same-cycle manager correction completed before opening still excludes."""
    bid = "SAME1"
    tl = [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 6, 0),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 10, 0),
            purpose="garments-reviewed",
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 10, 5),
            purpose="weight-entry",
            weight=12.0,
            scan_id=3,
        ),
    ]
    out = _run_helper(
        {bid: tl},
        [_corr(bid, "2026-08-12T10:10:00", completed_by="Manager Override")],
    )
    assert bid in out


def test_c_yesterday_completed_no_newer_cycle_remains_excluded():
    """C: Bag completed yesterday with no newer cycle remains excluded."""
    bid = "YDAY1"
    tl = [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 6, 3),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 16, 44),
            purpose="garments-reviewed",
            user="Evelin",
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 16, 45),
            purpose="weight-entry",
            user="Evelin",
            weight=19.5,
            scan_id=3,
        ),
    ]
    # No manager correction required — scan completion before opening excludes.
    cursor = MagicMock()

    def execute(sql, params=None):
        cursor._last_sql = " ".join(str(sql).split()).lower()
        cursor._last_params = params

    def fetchall():
        s = getattr(cursor, "_last_sql", "") or ""
        if "from rinse_bag_scan_events" in s:
            return list(tl)
        if "from rinse_step1_corrections" in s:
            return []
        return []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = fetchall

    with (
        patch("backend.ta_helpers.table_exists", return_value=True),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={},
        ),
        patch(
            "backend.rinse_processing_settings.get_processing_settings",
            return_value={"facility_entry_racks": list(RACKS)},
        ),
    ):
        out = _bags_canonically_completed_before_opening(
            cursor,
            ORG,
            DAY,
            [bid],
            service_type_by_bag={bid: "WF"},
        )
    assert bid in out


def test_d_midnight_crossing_cycle_included_when_not_completed():
    """D: Cycle starts before midnight and continues into selected day → not excluded."""
    bid = "MIDN1"
    tl = [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 23, 13),
            purpose="sent-to-vendor",
            rack="Rinse Zipvan",
            scan_id=1,
        ),
    ]
    out = _run_helper({bid: tl}, [])
    assert bid not in out


def test_e_multi_cycle_manager_correction_affects_only_own_cycle():
    """E: Correction on cycle A must not exclude open cycle B."""
    bid = "MULTI1"
    tl = [
        # Cycle A — completed + manager-corrected
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 1, 6, 0),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 1, 12, 0),
            purpose="garments-reviewed",
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 7, 1, 12, 5),
            purpose="weight-entry",
            weight=10.0,
            scan_id=3,
        ),
        # Cycle B — open before Today opening
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 22, 0),
            purpose="sent-to-vendor",
            rack="Rinse Zipvan",
            scan_id=4,
        ),
    ]
    out = _run_helper(
        {bid: tl},
        [_corr(bid, "2026-07-01T12:05:00", completed_by="Old Manager")],
    )
    assert bid not in out


def _prior_completed_cycle(bid: str, *, day: date = date(2026, 8, 12)) -> list[dict]:
    """Completed prior-day cycle ending before selected-day opening."""
    return [
        _scan(
            bag_id=bid,
            ts=datetime(day.year, day.month, day.day, 6, 3),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(day.year, day.month, day.day, 16, 44),
            purpose="garments-reviewed",
            user="Evelin",
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(day.year, day.month, day.day, 16, 45),
            purpose="weight-entry",
            user="Evelin",
            weight=19.5,
            scan_id=3,
        ),
    ]


def test_f_newer_cycle_at_selected_day_midnight_not_excluded():
    """Prior-cycle completion must not exclude a new STV at selected-day 00:00 ET."""
    bid = "AXYMIDN"
    tl = _prior_completed_cycle(bid) + [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 13, 0, 0),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            user="Shaquille",
            scan_id=4,
        ),
    ]
    out = _run_helper({bid: tl}, [])
    assert bid not in out


def test_f2_newer_cycle_just_after_midnight_not_excluded():
    """STV at 00:00:01 ET on the selected day is still a selected-day cycle."""
    bid = "AFTERMID"
    tl = _prior_completed_cycle(bid) + [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 13, 0, 0, 1),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            user="Shaquille",
            scan_id=4,
        ),
    ]
    out = _run_helper({bid: tl}, [])
    assert bid not in out


def test_f3_cycle_starting_at_prior_day_end_not_excluded():
    """STV at 23:59:59 ET before opening is a newer pre-opening cycle (not excluded)."""
    bid = "BEFOREMID"
    tl = _prior_completed_cycle(bid, day=date(2026, 8, 11)) + [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 23, 59, 59),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            user="Shaquille",
            scan_id=4,
        ),
    ]
    out = _run_helper({bid: tl}, [])
    assert bid not in out


def test_f4_multi_cycle_bag_admitted_once_not_duplicated():
    """Opening membership admits a multi-cycle bag once (new selected-day cycle)."""
    from backend.rinse_veewash_day_membership import (
        INCLUSION_OPENING_NEW,
        classify_opening_scrape_membership,
    )

    bid = "ONCE1"
    membership = {
        bid: {
            "bag_id": bid,
            "inclusion_source": INCLUSION_OPENING_NEW,
            "service_type_portal": "WF",
            "rush_flag": "RUSH",
        }
    }
    cursor = MagicMock()
    with patch(
        "backend.rinse_veewash_day_membership._bags_canonically_completed_before_opening",
        return_value=set(),
    ), patch(
        "backend.rinse_veewash_day_membership._load_prior_day_membership_ids",
        return_value=set(),
    ):
        kept, excluded, meta = classify_opening_scrape_membership(
            cursor, ORG, DAY, membership
        )
    assert bid not in excluded
    assert bid in kept
    assert meta["opening_new_bag_ids"].count(bid) == 1
    assert list(kept.keys()).count(bid) == 1


def test_g_comps_prior_plus_midnight_stv_not_excluded():
    """First-pass prior-day completion still yields to a selected-day midnight cycle."""
    bid = "AXYPRIOR"
    tl = [
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 6, 3),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            scan_id=1,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 12, 16, 45),
            purpose="weight-entry",
            user="Evelin",
            weight=19.5,
            scan_id=2,
        ),
        _scan(
            bag_id=bid,
            ts=datetime(2026, 8, 13, 0, 0),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            user="Shaquille",
            scan_id=3,
        ),
    ]
    cursor = MagicMock()

    def execute(sql, params=None):
        cursor._last_sql = " ".join(str(sql).split()).lower()
        cursor._last_params = params

    def fetchall():
        s = getattr(cursor, "_last_sql", "") or ""
        if "from rinse_bag_scan_events" in s:
            return list(tl)
        if "from rinse_step1_corrections" in s:
            return []
        return []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = fetchall

    with (
        patch("backend.ta_helpers.table_exists", return_value=True),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={
                bid: {
                    "completion_date": date(2026, 8, 12),
                    "completion_at": datetime(2026, 8, 12, 16, 45),
                }
            },
        ),
        patch(
            "backend.rinse_processing_settings.get_processing_settings",
            return_value={"facility_entry_racks": list(RACKS)},
        ),
    ):
        out = _bags_canonically_completed_before_opening(
            cursor,
            ORG,
            DAY,
            [bid],
            service_type_by_bag={bid: "WF"},
        )
    assert bid not in out
    """Manager correction with no pre-opening scans still excludes (no newer cycle)."""
    bid = "MGRONLY"
    out = _run_helper(
        {bid: []},
        [_corr(bid, "2026-08-10T15:00:00")],
    )
    assert bid in out
