"""HD specialty metrics + legacy EDD-gate no-op (membership is scrape-based)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_hd_edd_membership import apply_hd_edd_day_membership_gate
from backend.rinse_hd_day_metrics import is_create_issue_rejected_scan
from backend.rinse_hd_day_presentation import finalize_hd_step1_summary
from backend.rinse_veewash_day_membership import INCLUSION_ADDED_LATER, INCLUSION_BASELINE
from backend.rinse_veewash_step1_api import _filter_bag_ids, normalize_step1_queue_metric
from backend.tests.test_hd_no_carryover_and_specialty_metrics import _seg


DAY = date(2026, 7, 25)

VICTORIA = "D7G8ZZMCJD"
NICOLE = "7RIQ8VESUR"
CATHERINE = "60UAYQX9JH"
CHRIS = "30YT9G2QHR"
MARC = "EFX3SHSDC1"
GRACE = "EQM0CVJZY8"


def _wrong_scrape_membership():
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


def test_edd_gate_is_noop_keeps_future_edd_nicole():
    """Future-EDD HD scrape members must remain; EDD gate is disabled."""
    out = apply_hd_edd_day_membership_gate(
        MagicMock(), 3, DAY, _wrong_scrape_membership()
    )
    mem = out["membership"]
    assert NICOLE in mem
    assert CATHERINE in mem
    assert "WFKEEP1" in mem
    assert out["hd_edd_gate"]["enabled"] is False
    assert out["hd_edd_gate"]["removed_future_edd_count"] == 0


def test_presentation_keeps_future_edd_nicole_in_hd_segment():
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
    with patch(
        "backend.rinse_hd_step1_review.load_prior_completed_hd_bag_ids",
        return_value=set(),
    ), patch(
        "backend.rinse_hd_step1_review.load_hd_production_status_map",
        return_value={},
    ), patch(
        "backend.rinse_hd_step1_review.load_hd_workitems_added_bag_ids",
        return_value=set(),
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
    hd_ids = set(out["segments"]["hd"]["bag_ids"]["new_today"])
    assert NICOLE in hd_ids
    assert CATHERINE in hd_ids
    assert out["segments"]["wf"]["bag_ids"]["new_today"] == ["WFKEEP1"]
    # Without WIA, future-EDD Nicole is a pending member — not Review Required.
    assert NICOLE in out["segments"]["hd"]["bag_ids"]["pending"]
    assert NICOLE not in out["segments"]["hd"]["bag_ids"]["review_required"]


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
    assert is_create_issue_rejected_scan("create-issue")
    assert is_create_issue_rejected_scan("Create Issue")
    assert not is_create_issue_rejected_scan("weight-entry")
    assert not is_create_issue_rejected_scan("create-workitem")
    assert not is_create_issue_rejected_scan("MISSING_FROM_LATEST_PORTAL_SCRAPE")


def test_scrape_membership_keeps_nicole_with_future_edd():
    out = apply_hd_edd_day_membership_gate(
        MagicMock(), 3, DAY, _wrong_scrape_membership()
    )
    hd_ids = sorted(
        bid
        for bid, row in out["membership"].items()
        if str(row.get("service_type_portal") or "").upper() == "HD"
    )
    assert NICOLE in hd_ids
    assert set(hd_ids) == {NICOLE, CATHERINE, CHRIS, MARC, GRACE}
