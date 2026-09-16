"""PRE must not satisfy same-minute POST completion; missing POST is not Specialty.

OI 5535 (36T8SNUK5E-OI-09142026) is the regression fixture. These tests do not
write to order instances or manager corrections.
"""

from __future__ import annotations

from datetime import date, datetime

from backend.management_rinse_wf_review import (
    CATEGORY_SPECIALTY,
    CATEGORY_WEIGHT_REVIEW,
    SPECIALTY_ITEMS_REASONS,
    WEIGHT_REVIEW_REASONS,
    _short_reason,
    category_for_reason_codes,
)
from backend.rinse_cycle_boundary import (
    COMPLETION_SOURCE_POST_REVIEW_WEIGHT,
    COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW,
    resolve_current_cycle,
)
from backend.rinse_veewash_workload import REASON_WF_ZERO_OR_MISSING_POST_WEIGHT

ENTRY_RACKS = ["VeeWash Dirty"]
DAY = date(2026, 9, 14)


def _ev(**kwargs):
    row = {
        "scanned_at_parsed": kwargs["ts"],
        "purpose": kwargs["purpose"],
        "rack": kwargs.get("rack"),
        "user_name": kwargs.get("user"),
        "weight_lbs": kwargs.get("weight"),
    }
    if kwargs.get("scan_index") is not None:
        row["scan_index"] = kwargs["scan_index"]
    if kwargs.get("ev_id") is not None:
        row["id"] = kwargs["ev_id"]
    if kwargs.get("weight_role") is not None:
        row["weight_role"] = kwargs["weight_role"]
    if kwargs.get("weight_source") is not None:
        row["weight_source"] = kwargs["weight_source"]
    return row


def _oi_5535_natural_timeline():
    """Natural scans only — no operator manual POST correction."""
    return [
        _ev(
            ts=datetime(2026, 9, 14, 0, 38),
            purpose="sent-to-vendor",
            rack="VeeWash Dirty",
            user="Jordan Graham",
            ev_id=7610259,
        ),
        _ev(
            ts=datetime(2026, 9, 14, 5, 30),
            purpose="weight-entry",
            user="Varun",
            weight=8.7,
            weight_role="PRE",
            weight_source="rinse_preclean_info",
            ev_id=7650197,
        ),
        _ev(
            ts=datetime(2026, 9, 14, 8, 54),
            purpose="garments-reviewed",
            user="Amna",
            scan_index=6,
            ev_id=7684826,
        ),
        _ev(
            ts=datetime(2026, 9, 14, 8, 54),
            purpose="weight-entry",
            user="Amna",
            weight=8.7,
            weight_role="PRE",
            weight_source="rinse_preclean_info",
            scan_index=2,
            ev_id=7684822,
        ),
    ]


def test_preclean_pre_after_review_does_not_complete_same_minute():
    out = resolve_current_cycle(
        _oi_5535_natural_timeline(),
        selected_date_et=DAY,
        entry_racks=ENTRY_RACKS,
    )
    assert out.effective_status == "pending"
    assert out.completion_at is None
    assert out.completion_source is None
    assert out.completion_source != COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
    assert out.garments_reviewed_at == datetime(2026, 9, 14, 8, 54)


def test_explicit_weight_role_pre_cannot_satisfy_post_completion():
    tie = datetime(2026, 9, 14, 8, 54)
    tl = [
        _ev(ts=datetime(2026, 9, 14, 0, 38), purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 9, 14, 5, 30), purpose="weight-entry", weight=8.7, weight_role="PRE"),
        _ev(ts=tie, purpose="garments-reviewed", scan_index=6, ev_id=10),
        _ev(
            ts=tie,
            purpose="weight-entry",
            weight=8.7,
            weight_role="PRE",
            scan_index=2,
            ev_id=11,
        ),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.completion_at is None
    assert out.completion_source is None


def test_genuine_postclean_same_minute_still_completes():
    tie = datetime(2026, 9, 14, 8, 54)
    tl = [
        _ev(ts=datetime(2026, 9, 14, 0, 38), purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(
            ts=datetime(2026, 9, 14, 5, 30),
            purpose="weight-entry",
            weight=8.7,
            weight_role="PRE",
            weight_source="rinse_preclean_info",
        ),
        _ev(ts=tie, purpose="garments-reviewed", scan_index=6, ev_id=20),
        _ev(
            ts=tie,
            purpose="weight-entry",
            weight=8.5,
            weight_role="POST",
            weight_source="rinse_postclean_info",
            scan_index=2,
            ev_id=21,
        ),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW
    assert out.completion_at == tie


def test_workitem_wf_lbs_still_completes():
    review = datetime(2026, 9, 14, 8, 50)
    post = datetime(2026, 9, 14, 8, 54)
    tl = [
        _ev(ts=datetime(2026, 9, 14, 0, 38), purpose="sent-to-vendor", rack="VeeWash Dirty"),
        _ev(ts=datetime(2026, 9, 14, 5, 30), purpose="weight-entry", weight=8.7, weight_role="PRE"),
        _ev(ts=review, purpose="garments-reviewed"),
        _ev(
            ts=post,
            purpose="weight-entry",
            weight=8.5,
            weight_source="rinse_workitem_wf_lbs",
        ),
    ]
    out = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY_RACKS)
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_POST_REVIEW_WEIGHT
    assert out.completion_at == post


def test_unlabeled_same_minute_post_still_completes():
    """Existing chronology-only same-minute POST remains valid."""
    tie = datetime(2026, 7, 30, 8, 49)
    tl = [
        _ev(ts=datetime(2026, 7, 30, 4, 19), purpose="sent-to-vendor"),
        _ev(ts=datetime(2026, 7, 30, 5, 12), purpose="move-bag", rack="VeeWash Dirty"),
        _ev(ts=tie, purpose="weight-entry", weight=12.9, scan_index=2, ev_id=100),
        _ev(ts=tie, purpose="garments-reviewed", scan_index=7, ev_id=105),
    ]
    out = resolve_current_cycle(tl, selected_date_et=date(2026, 7, 30), entry_racks=ENTRY_RACKS)
    assert out.effective_status == "completed"
    assert out.completion_source == COMPLETION_SOURCE_SAME_MINUTE_POST_AFTER_REVIEW


def test_missing_post_reason_is_weight_review_not_specialty():
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in SPECIALTY_ITEMS_REASONS
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in WEIGHT_REVIEW_REASONS
    assert category_for_reason_codes([REASON_WF_ZERO_OR_MISSING_POST_WEIGHT]) == CATEGORY_WEIGHT_REVIEW
    assert category_for_reason_codes([REASON_WF_ZERO_OR_MISSING_POST_WEIGHT]) != CATEGORY_SPECIALTY
    assert category_for_reason_codes(["WF_BULK_WORKITEM_REVIEW"]) == CATEGORY_SPECIALTY
    assert _short_reason([REASON_WF_ZERO_OR_MISSING_POST_WEIGHT], CATEGORY_WEIGHT_REVIEW) == (
        "Missing POST Weight"
    )
    assert _short_reason(["WF_BULK_WORKITEM_REVIEW"], CATEGORY_SPECIALTY) == (
        "Specialty / Bulky Item Review"
    )


def test_oi_5535_manager_correction_is_not_rewritten_by_resolver():
    """Resolver is pure. The 16:36 manager correction must not be an input or output."""
    import inspect

    from backend import rinse_cycle_boundary as boundary

    source = inspect.getsource(boundary._chain_from_entry)
    assert "UPDATE" not in source
    assert "rinse_step1_corrections" not in source
    out = resolve_current_cycle(
        _oi_5535_natural_timeline(),
        selected_date_et=DAY,
        entry_racks=ENTRY_RACKS,
    )
    assert out.completion_event is None
