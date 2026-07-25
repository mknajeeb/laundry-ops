"""HD Estimated Delivery Date membership gate + specialty drawer metric parity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_hd_edd_membership import apply_hd_edd_day_membership_gate
from backend.rinse_hd_day_metrics import is_canonical_rejected
from backend.rinse_hd_day_presentation import finalize_hd_step1_summary
from backend.rinse_veewash_day_membership import INCLUSION_ADDED_LATER, INCLUSION_BASELINE
from backend.rinse_veewash_step1_api import _filter_bag_ids, normalize_step1_queue_metric
from backend.tests.test_hd_no_carryover_and_specialty_metrics import _seg


DAY = date(2026, 7, 25)

# Production-like Jul 25 IDs
VICTORIA = "D7G8ZZMCJD"
NICOLE = "7RIQ8VESUR"
CATHERINE = "60UAYQX9JH"
CHRIS = "30YT9G2QHR"
MARC = "EFX3SHSDC1"
GRACE = "EQM0CVJZY8"
INACTIVE = "INACTHD001"
COMPLETED = "COMPLHD001"


def _presence_rows():
    return [
        {
            "bag_id": VICTORIA,
            "customer_name": "Victoria Panettiere",
            "estimated_delivery_date": date(2026, 7, 25),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 6, 26, 12, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": NICOLE,
            "customer_name": "Nicole Callender",
            "estimated_delivery_date": date(2026, 7, 28),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 25, 9, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": CATHERINE,
            "customer_name": "Catherine Duncan",
            "estimated_delivery_date": date(2026, 7, 25),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 25, 8, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": CHRIS,
            "customer_name": "Chris Maxwell",
            "estimated_delivery_date": date(2026, 7, 25),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 25, 8, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": MARC,
            "customer_name": "MarcAnthony Paz",
            "estimated_delivery_date": date(2026, 7, 25),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 25, 8, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": GRACE,
            "customer_name": "Grace Hickey",
            "estimated_delivery_date": date(2026, 7, 25),
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 25, 8, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
        {
            "bag_id": "WFKEEP1",
            "customer_name": "WF Keep",
            "estimated_delivery_date": date(2026, 7, 28),
            "rush_flag": 0,
            "service_type": "WF",
            "first_seen_at": datetime(2026, 7, 25, 8, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        },
    ]


def _wrong_scrape_membership():
    """Pre-gate membership: Nicole in (seen today), Victoria out (prior carry-in)."""
    mem = {
        NICOLE: {
            "inclusion_source": INCLUSION_ADDED_LATER,
            "service_type_portal": "HD",
            "customer_name": "Nicole Callender",
        },
        CATHERINE: {
            "inclusion_source": INCLUSION_BASELINE,
            "service_type_portal": "HD",
            "customer_name": "Catherine Duncan",
        },
        CHRIS: {
            "inclusion_source": INCLUSION_BASELINE,
            "service_type_portal": "HD",
            "customer_name": "Chris Maxwell",
        },
        MARC: {
            "inclusion_source": INCLUSION_ADDED_LATER,
            "service_type_portal": "HD",
            "customer_name": "MarcAnthony Paz",
        },
        GRACE: {
            "inclusion_source": INCLUSION_ADDED_LATER,
            "service_type_portal": "HD",
            "customer_name": "Grace Hickey",
        },
        "WFKEEP1": {
            "inclusion_source": INCLUSION_BASELINE,
            "service_type_portal": "WF",
            "customer_name": "WF Keep",
        },
    }
    return {
        "membership": mem,
        "baseline_bag_ids": [CATHERINE, CHRIS, "WFKEEP1"],
        "added_later_bag_ids": [NICOLE, MARC, GRACE],
        "baseline_count": 3,
        "added_later_count": 3,
        "total_count": 6,
        "added_later": [],
    }


def _run_gate(presence_rows, membership, *, completed=None):
    cursor = MagicMock()
    cursor.fetchall.return_value = presence_rows
    with patch("backend.rinse_hd_edd_membership.table_exists", return_value=True), patch(
        "backend.rinse_hd_edd_membership._load_completed_hd_bag_ids",
        return_value=set(completed or []),
    ):
        return apply_hd_edd_day_membership_gate(cursor, 3, DAY, membership)


def test_edd_gate_includes_victoria_excludes_nicole():
    out = _run_gate(_presence_rows(), _wrong_scrape_membership())
    mem = out["membership"]
    assert VICTORIA in mem
    assert NICOLE not in mem
    assert set([CATHERINE, CHRIS, MARC, GRACE, VICTORIA]).issubset(set(mem))
    assert "WFKEEP1" in mem  # WF untouched even with future EDD
    assert out["hd_edd_gate"]["authoritative_field"] == "estimated_delivery_date"
    assert out["hd_edd_gate"]["admit_requires_active_presence"] is True
    assert NICOLE in out["hd_edd_gate"]["removed_future_edd_bag_ids"]
    assert VICTORIA in out["hd_edd_gate"]["added_edd_day_bag_ids"]
    assert mem[VICTORIA]["hd_membership_reason"] == "edd_day_readmit_from_active_presence"
    assert mem[CATHERINE]["hd_membership_reason"] == "edd_active_not_completed"


def test_edd_jul25_inactive_not_admitted():
    """EDD == selected day but active=false → not admitted (stale / disappeared)."""
    rows = [
        {
            "bag_id": INACTIVE,
            "customer_name": "Inactive HD",
            "estimated_delivery_date": DAY,
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 24, 12, 0, 0),
            "last_seen_at": datetime(2026, 7, 24, 18, 0, 0),
            "active": 0,
            "portal_status": "at_vendor",
        }
    ]
    membership = {
        "membership": {
            INACTIVE: {
                "inclusion_source": INCLUSION_ADDED_LATER,
                "service_type_portal": "HD",
                "customer_name": "Inactive HD",
            },
            "WFKEEP1": {
                "inclusion_source": INCLUSION_BASELINE,
                "service_type_portal": "WF",
            },
        },
        "baseline_bag_ids": ["WFKEEP1"],
        "added_later_bag_ids": [INACTIVE],
        "added_later": [],
    }
    out = _run_gate(rows, membership)
    assert INACTIVE not in out["membership"]
    assert "WFKEEP1" in out["membership"]
    assert INACTIVE in out["hd_edd_gate"]["removed_inactive_bag_ids"]


def test_edd_jul25_active_prior_completed_not_admitted():
    """EDD == selected day, active=true, prior COMPLETE → not admitted (no resurrect)."""
    rows = [
        {
            "bag_id": COMPLETED,
            "customer_name": "Already Done HD",
            "estimated_delivery_date": DAY,
            "rush_flag": 0,
            "service_type": "HD",
            "first_seen_at": datetime(2026, 7, 20, 12, 0, 0),
            "last_seen_at": datetime(2026, 7, 25, 10, 0, 0),
            "active": 1,
            "portal_status": "at_vendor",
        }
    ]
    membership = {
        "membership": {
            "WFKEEP1": {
                "inclusion_source": INCLUSION_BASELINE,
                "service_type_portal": "WF",
            },
        },
        "baseline_bag_ids": ["WFKEEP1"],
        "added_later_bag_ids": [],
        "added_later": [],
    }
    out = _run_gate(rows, membership, completed={COMPLETED})
    assert COMPLETED not in out["membership"]
    assert "WFKEEP1" in out["membership"]
    assert COMPLETED in out["hd_edd_gate"]["removed_completed_bag_ids"]


def test_presentation_strips_future_edd_nicole_from_hd_segment():
    summary = {
        "selected_date_et": DAY.isoformat(),
        "segments": {
            "wf": _seg(["WFKEEP1"], []),
            "hd": _seg(
                [CATHERINE, CHRIS, NICOLE, MARC, GRACE],
                [],
                pending=[CATHERINE, CHRIS, NICOLE, MARC, GRACE],
            ),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(
                [CATHERINE, CHRIS, NICOLE, MARC, GRACE],
                [],
                pending=[CATHERINE, CHRIS, NICOLE, MARC, GRACE],
            ),
            "all": _seg(
                ["WFKEEP1", CATHERINE, CHRIS, NICOLE, MARC, GRACE],
                [],
                pending=[CATHERINE, CHRIS, NICOLE, MARC, GRACE],
            ),
            "rush": _seg([], []),
            "non_rush": _seg(
                ["WFKEEP1", CATHERINE, CHRIS, NICOLE, MARC, GRACE],
                [],
                pending=[CATHERINE, CHRIS, NICOLE, MARC, GRACE],
            ),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WFKEEP1"], []),
        },
        "membership": {
            "baseline_bag_ids": [CATHERINE, CHRIS, "WFKEEP1"],
            "membership": {
                CATHERINE: {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "HD"},
                CHRIS: {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "HD"},
                NICOLE: {"inclusion_source": INCLUSION_ADDED_LATER, "service_type_portal": "HD"},
                MARC: {"inclusion_source": INCLUSION_ADDED_LATER, "service_type_portal": "HD"},
                GRACE: {"inclusion_source": INCLUSION_ADDED_LATER, "service_type_portal": "HD"},
                "WFKEEP1": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "WF"},
            },
        },
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = _presence_rows()
    with patch("backend.rinse_hd_edd_membership.table_exists", return_value=True), patch(
        "backend.rinse_hd_step1_review.load_prior_completed_hd_bag_ids",
        return_value=set(),
    ), patch(
        "backend.rinse_hd_step1_review.load_hd_production_status_map",
        return_value={},
    ), patch(
        "backend.rinse_hd_step1_review.apply_hd_review_status_to_summary",
        side_effect=lambda s, **kwargs: s,
    ), patch(
        "backend.rinse_hd_step1_review.build_hd_dashboard_totals",
        return_value={},
    ):
        out = finalize_hd_step1_summary(
            summary,
            selected_date_et=DAY,
            membership=summary["membership"],
            cursor=cursor,
            organization_id=3,
        )
    hd_ids = set(out["segments"]["hd"]["bag_ids"]["new_today"]) | set(
        out["segments"]["hd"]["bag_ids"]["pending"]
    )
    assert NICOLE not in hd_ids
    assert CATHERINE in hd_ids
    assert out["segments"]["wf"]["bag_ids"]["new_today"] == ["WFKEEP1"]


def test_normalize_specialty_metrics_pass_through():
    assert normalize_step1_queue_metric("comforter_orders") == "comforter_orders"
    assert normalize_step1_queue_metric("bath_mat_orders") == "bath_mat_orders"
    assert normalize_step1_queue_metric("rejected_orders") == "rejected_orders"
    assert normalize_step1_queue_metric("split_orders") == "split_orders"
    assert normalize_step1_queue_metric("comforters") == "comforter_orders"
    assert normalize_step1_queue_metric("rejected") == "rejected_orders"
    assert normalize_step1_queue_metric("bogus") == "review_required"


def test_specialty_drawer_filter_uses_canonical_order_ids():
    summary = {
        "segments": {
            "all": _seg(["AAAA", "BBBB", "CCCC"], []),
            "hd": _seg(["AAAA", "BBBB"], []),
            "wf": _seg(["CCCC"], []),
        },
        "specialty_metrics": {
            "all": {
                "comforter_orders": {
                    "count": 2,
                    "order_ids": ["AAAA", "BBBB"],
                    "orders": [{"bag_id": "AAAA"}, {"bag_id": "BBBB"}],
                },
                "rejected_orders": {
                    "count": 1,
                    "order_ids": ["CCCC"],
                    "orders": [{"bag_id": "CCCC"}],
                },
                "split_orders": {
                    "count": 1,
                    "order_ids": ["AAAA"],
                    "orders": [{"bag_id": "AAAA"}],
                },
                "bath_mat_orders": {"count": 0, "order_ids": [], "orders": []},
            },
            "hd": {
                "comforter_orders": {
                    "count": 2,
                    "order_ids": ["AAAA", "BBBB"],
                    "orders": [{"bag_id": "AAAA"}, {"bag_id": "BBBB"}],
                },
                "rejected_orders": {"count": 0, "order_ids": [], "orders": []},
                "split_orders": {"count": 0, "order_ids": [], "orders": []},
                "bath_mat_orders": {"count": 0, "order_ids": [], "orders": []},
            },
        },
    }
    assert _filter_bag_ids(
        summary, metric="comforter_orders", service="all", rush="all"
    ) == ["AAAA", "BBBB"]
    assert _filter_bag_ids(
        summary, metric="rejected_orders", service="all", rush="all"
    ) == ["CCCC"]
    assert _filter_bag_ids(
        summary, metric="split_orders", service="hd", rush="all"
    ) == []
    assert (
        len(
            _filter_bag_ids(
                summary, metric="comforter_orders", service="hd", rush="all"
            )
        )
        == summary["specialty_metrics"]["hd"]["comforter_orders"]["count"]
    )


def test_rejected_distinct_order_not_line_count_and_missing_excluded():
    assert is_canonical_rejected(
        completion_status="REJECTED",
        completion_reason="CREATE_ISSUE_NO_COMPLETION_PORTAL_DEPARTURE",
    )
    assert not is_canonical_rejected(
        completion_status="REJECTED",
        completion_reason="MISSING_FROM_LATEST_PORTAL_SCRAPE",
    )
    assert not is_canonical_rejected(completion_status="INCOMPLETE")


def test_expected_jul25_hd_five_without_nicole():
    """Expected Jul 25 HD membership identities after EDD gate."""
    out = _run_gate(_presence_rows(), _wrong_scrape_membership())
    hd_ids = sorted(
        bid
        for bid, row in out["membership"].items()
        if str(row.get("service_type_portal") or "").upper() == "HD"
    )
    assert hd_ids == sorted([VICTORIA, CATHERINE, CHRIS, MARC, GRACE])
    assert NICOLE not in hd_ids
