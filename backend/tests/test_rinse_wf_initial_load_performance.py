"""WF initial load performance — primary/secondary split and count parity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.management_today import (
    build_management_rinse_wf_primary_payload,
    build_management_rinse_wf_secondary_payload,
    clear_management_today_cache,
)


def _headline():
    return {
        "selected_date_et": "2026-08-16",
        "segments": {
            "wf": {
                "total_workload": 113,
                "completed": 80,
                "pending": 5,
                "exceptions": {"review_required": 12},
                "bag_ids": {
                    "completed": ["C1", "C2", "C3", "B1"],
                    "pending": [],
                    "review_required": [],
                    "new_today": [],
                    "carryover": [],
                },
            },
            "wf_rush": {
                "total_workload": 20,
                "completed": 15,
                "pending": 1,
                "exceptions": {"review_required": 2},
            },
            "wf_non_rush": {
                "total_workload": 93,
                "completed": 65,
                "pending": 4,
                "exceptions": {"review_required": 10},
            },
        },
        "specialty_metrics": {
            "wf": {
                "classification_version": 99,
                "comforter_orders": {
                    "count": 3,
                    "item_qty": 4,
                    "order_ids": ["C1", "C2", "C3"],
                    "total_quantity": 4,
                },
                "bath_mat_orders": {"count": 1, "item_qty": 2, "order_ids": ["B1"], "total_quantity": 2},
                "rejected_orders": {"count": 2},
                "split_orders": {"count": 7},
            },
            "wf_rush": {
                "classification_version": 99,
                "comforter_orders": {"count": 1},
                "bath_mat_orders": {"count": 0},
                "rejected_orders": {"count": 0},
                "split_orders": {"count": 1},
            },
            "wf_non_rush": {
                "classification_version": 99,
                "comforter_orders": {"count": 2},
                "bath_mat_orders": {"count": 1},
                "rejected_orders": {"count": 2},
                "split_orders": {"count": 6},
            },
        },
        "review_reasons_by_bag": {
            "BAG1": ["WF_BULK_WORKITEM_REVIEW"],
            "BAG2": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "BAG3": ["SPLIT_ORDER_REVIEW"],
        },
    }


def _weight_totals():
    return {
        "pre_lbs": 500.0,
        "post_lbs": 420.0,
        "pre_weight_lbs": 500.0,
        "post_weight_lbs": 420.0,
        "pre_weight_bag_count": 113,
        "post_weight_bag_count": 95,
        "rush_filtering_supported": True,
        "source": "test",
        "by_rush": {
            "all": {
                "pre_lbs": 500.0,
                "post_lbs": 420.0,
                "pre_weight_lbs": 500.0,
                "post_weight_lbs": 420.0,
                "pre_weight_bag_count": 113,
                "post_weight_bag_count": 95,
            },
            "rush": {
                "pre_lbs": 90.0,
                "post_lbs": 80.0,
                "pre_weight_lbs": 90.0,
                "post_weight_lbs": 80.0,
                "pre_weight_bag_count": 20,
                "post_weight_bag_count": 18,
            },
            "non_rush": {
                "pre_lbs": 410.0,
                "post_lbs": 340.0,
                "pre_weight_lbs": 410.0,
                "post_weight_lbs": 340.0,
                "pre_weight_bag_count": 93,
                "post_weight_bag_count": 77,
            },
        },
    }


def _review_payload():
    return {
        "split_available": True,
        "review_required": 3,
        "specialty_items": 1,
        "missing_from_portal": 1,
        "split_order_review": 1,
        "unknown_review": 0,
        "by_rush": {
            "all": {
                "specialty_items": 1,
                "missing_from_portal": 1,
                "split_order_review": 1,
                "review_required": 3,
            },
            "rush": {
                "specialty_items": 0,
                "missing_from_portal": 0,
                "split_order_review": 1,
                "review_required": 1,
            },
            "non_rush": {
                "specialty_items": 1,
                "missing_from_portal": 1,
                "split_order_review": 0,
                "review_required": 2,
            },
        },
    }


def test_primary_payload_skips_review_and_specialty_compute(monkeypatch):
    clear_management_today_cache()
    day = date(2026, 8, 16)
    headline = _headline()
    review_calls: list[str] = []

    def _track_review(*_a, **_k):
        review_calls.append("review")
        return _review_payload()

    with patch(
        "backend.management_today._load_headline",
        return_value=({"status": "OPEN"}, headline),
    ), patch(
        "backend.management_today._overlay_lifecycle_wf_segment",
        return_value=None,
    ), patch(
        "backend.management_today.business_today",
        return_value=day,
    ), patch(
        "backend.management_today.business_now",
        return_value=datetime(2026, 8, 16, 18, 0, 0),
    ):
        payload = build_management_rinse_wf_primary_payload(
            object(), 3, day, bypass_cache=True
        )

    assert payload["rinse"]["segments"]["wf"]["total_workload"] == 113
    assert "weight_totals" not in payload["rinse"]
    assert "specialty_metrics" not in payload["rinse"]
    assert payload["review"]["deferred"] is True
    assert review_calls == []
    assert payload["_meta"]["tier"] == "primary"
    assert "phases" in payload["_meta"]


def test_secondary_payload_includes_review_and_specialty(monkeypatch):
    clear_management_today_cache()
    day = date(2026, 8, 16)
    headline = _headline()

    with patch(
        "backend.management_today._load_headline",
        return_value=({"status": "OPEN"}, headline),
    ), patch(
        "backend.management_today.load_wf_day_weight_totals",
        return_value=_weight_totals(),
    ), patch(
        "backend.management_rinse_wf_review.review_category_count_payload",
        return_value={**_review_payload(), "_membership": {}},
    ), patch(
        "backend.management_rinse_wf_review.enrich_review_counts_by_rush",
        side_effect=lambda _c, _o, _d, _h, base: dict(base),
    ), patch(
        "backend.management_today.business_today",
        return_value=day,
    ), patch(
        "backend.management_today.business_now",
        return_value=datetime(2026, 8, 16, 18, 0, 0),
    ):
        payload = build_management_rinse_wf_secondary_payload(
            object(), 3, day, bypass_cache=True
        )

    spec = payload["rinse"]["specialty_metrics"]["wf"]
    assert spec["comforter_orders"]["count"] == 3
    assert payload["rinse"]["weight_totals"]["pre_weight_bag_count"] == 113
    assert payload["review"]["specialty_items"] == 1
    assert payload["review"]["split_available"] is True
    assert payload["_meta"]["tier"] == "secondary"


def test_primary_headline_skips_specialty_rebuild(monkeypatch):
    from backend.management_today import _load_headline

    rebuild_calls: list[str] = []

    def _fake_build(*_a, **_k):
        rebuild_calls.append("rebuild")
        return {"count": 1}

    stale_headline = {
        "segments": {"wf": {"total_workload": 1}},
        "specialty_metrics": {"wf": {"split_orders": {}}},
    }
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"headline": stale_headline},
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=stale_headline,
    ), patch(
        "backend.management_today._specialty_packs_current",
        return_value=False,
    ), patch(
        "backend.rinse_hd_day_metrics.build_day_specialty_metrics",
        side_effect=_fake_build,
    ):
        _rec, out = _load_headline(object(), 1, date(2026, 8, 16), rebuild_specialty=False)

    assert rebuild_calls == []
    assert out["specialty_metrics"]["wf"] == {"split_orders": {}}

    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"headline": stale_headline},
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=stale_headline,
    ), patch(
        "backend.management_today._specialty_packs_current",
        return_value=False,
    ), patch(
        "backend.rinse_hd_day_metrics.build_day_specialty_metrics",
        side_effect=_fake_build,
    ):
        _rec, out = _load_headline(object(), 1, date(2026, 8, 16), rebuild_specialty=True)

    assert rebuild_calls == ["rebuild"]


def test_secondary_rebuilds_specialty_after_primary_caches_bare_headline():
    """Primary caches rebuild_specialty=False headline; secondary must still rebuild.

    Reproduces production: secondary alone returns Rejects/Splits, but
    primary→secondary returned zeros because the shared headline cache lacked packs.
    """
    from backend.management_today import (
        _RINSE_WF_SECONDARY_CACHE,
        _cache_headline,
        _get_cached_headline,
        _specialty_packs_current,
    )
    from backend.rinse_hd_day_metrics import CLASSIFICATION_VERSION

    clear_management_today_cache()
    day = date(2026, 8, 16)
    reject_ids = [f"R{i}" for i in range(1, 7)]
    split_ids = [f"S{i}" for i in range(1, 100)]
    member_ids = reject_ids + split_ids
    bare_headline = {
        "selected_date_et": "2026-08-16",
        "segments": {
            "wf": {
                "total_workload": len(member_ids),
                "completed": len(member_ids),
                "pending": 0,
                "exceptions": {"review_required": 0},
                "bag_ids": {
                    "completed": list(member_ids),
                    "pending": [],
                    "review_required": [],
                    "new_today": [],
                    "carryover": [],
                },
            },
            "wf_rush": {
                "total_workload": 0,
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": 0},
                "bag_ids": {},
            },
            "wf_non_rush": {
                "total_workload": len(member_ids),
                "completed": len(member_ids),
                "pending": 0,
                "exceptions": {"review_required": 0},
                "bag_ids": {
                    "completed": list(member_ids),
                    "pending": [],
                    "review_required": [],
                },
            },
        },
    }
    day_rec = {"status": "OPEN"}
    # Simulate primary caching a headline without specialty packs.
    _cache_headline(3, day, day_rec, bare_headline)
    assert _specialty_packs_current(_get_cached_headline(3, day)[1]) is False

    rebuild_calls: list[str] = []

    def _fake_rebuild(_cursor, _org, _day, _headline, *, service="wf"):
        rebuild_calls.append(service)
        return {
            "classification_version": CLASSIFICATION_VERSION,
            "comforter_orders": {
                "count": 0,
                "order_count": 0,
                "order_ids": [],
                "orders": [],
                "total_quantity": 0,
            },
            "bath_mat_orders": {
                "count": 0,
                "order_count": 0,
                "order_ids": [],
                "orders": [],
                "total_quantity": 0,
            },
            "rejected_orders": {
                "count": 6,
                "order_count": 6,
                "order_ids": list(reject_ids),
                "orders": [{"bag_id": b} for b in reject_ids],
            },
            "split_orders": {
                "count": 99,
                "order_count": 99,
                "order_ids": list(split_ids),
                "orders": [{"bag_id": b} for b in split_ids],
            },
            "split_review": {"count": 0, "order_ids": [], "orders": []},
            "split_pending": {"count": 0, "order_ids": [], "orders": []},
        }

    def _run_secondary():
        with patch(
            "backend.management_today.load_wf_day_weight_totals",
            return_value=_weight_totals(),
        ), patch(
            "backend.management_rinse_wf_review.review_category_count_payload",
            return_value={**_review_payload(), "_membership": {}},
        ), patch(
            "backend.management_rinse_wf_review.enrich_review_counts_by_rush",
            side_effect=lambda _c, _o, _d, _h, base: dict(base),
        ), patch(
            "backend.management_today.business_today",
            return_value=day,
        ), patch(
            "backend.management_today.business_now",
            return_value=datetime(2026, 8, 16, 18, 0, 0),
        ), patch(
            "backend.rinse_hd_day_metrics.build_day_specialty_metrics",
            side_effect=_fake_rebuild,
        ):
            # Do NOT bypass_cache — that would clear the primary-seeded headline cache.
            return build_management_rinse_wf_secondary_payload(
                object(), 3, day, bypass_cache=False
            )

    sec = _run_secondary()
    assert rebuild_calls == ["wf"]
    wf = sec["rinse"]["specialty_metrics"]["wf"]
    assert wf["rejected_orders"]["count"] == 6
    assert wf["split_orders"]["count"] == 99
    assert wf["comforter_orders"]["count"] == 0
    assert wf["bath_mat_orders"]["count"] == 0
    # Headline cache now holds current packs for later secondary reuse.
    assert _specialty_packs_current(_get_cached_headline(3, day)[1]) is True

    # secondary → secondary: response cache cleared, headline packs current → no rebuild.
    _RINSE_WF_SECONDARY_CACHE.clear()
    rebuild_calls.clear()
    sec2 = _run_secondary()
    assert rebuild_calls == []
    wf2 = sec2["rinse"]["specialty_metrics"]["wf"]
    assert wf2["rejected_orders"]["count"] == 6
    assert wf2["split_orders"]["count"] == 99
