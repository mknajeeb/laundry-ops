"""Exclude reasons + Processed Pounds filter + Manual Complete disposition."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.management_today import load_wf_day_weight_totals
from backend.rinse_step1_edit_bag import (
    classify_edit_reason_requirements,
    resolve_edit_audit_reason,
)
from backend.rinse_wf_oi_manager_disposition import (
    EXCLUDE_REASON_CODE_SET,
    COMPLETE_REASON_CODE_SET,
    collect_processed_pounds_excluded_bag_ids,
    validate_complete_reason,
    validate_exclude_reason,
)


def test_exclude_reason_catalog_and_other_requires_comment():
    assert "EXTRA_OR_DUPLICATE_BAG" in EXCLUDE_REASON_CODE_SET
    assert "REJECTED_NOT_PROCESSED" in EXCLUDE_REASON_CODE_SET
    ok = validate_exclude_reason("EXTRA_OR_DUPLICATE_BAG", None)
    assert ok["ok"] is True
    bad = validate_exclude_reason("OTHER", "")
    assert bad["ok"] is False
    assert bad["error"] == "reason_note_required_for_other"


def test_complete_reason_requires_manager_note():
    assert "BAG_ID_REASSIGNED" in COMPLETE_REASON_CODE_SET
    bad = validate_complete_reason("BAG_ID_REASSIGNED", "")
    assert bad["ok"] is False
    assert bad["error"] == "manager_note_required"
    ok = validate_complete_reason(
        "BAG_ID_REASSIGNED",
        "Original bag ID was unassigned; replacement issued.",
    )
    assert ok["ok"] is True


def test_edit_bag_exclude_requires_explicit_reason_code():
    before = {"dashboard_status": "review_required"}
    draft = {"service_type": "WF"}
    policy = classify_edit_reason_requirements(draft, before, outcome="exclude")
    assert policy["reason_required"] is True
    assert policy["suggested_reason_code"] is None
    codes = {c["code"] for c in policy["reason_codes"]}
    assert codes == EXCLUDE_REASON_CODE_SET

    missing = resolve_edit_audit_reason(
        reason=None,
        reason_code=None,
        reason_note=None,
        draft=draft,
        before=before,
        outcome="exclude",
    )
    assert missing["ok"] is False
    assert missing["error"] == "reason_code_required"

    ok = resolve_edit_audit_reason(
        reason=None,
        reason_code="REJECTED_NOT_PROCESSED",
        reason_note="Whole bag rejected",
        draft=draft,
        before=before,
        outcome="exclude",
    )
    assert ok["ok"] is True
    assert ok["reason_code"] == "REJECTED_NOT_PROCESSED"


def test_edit_bag_mark_completed_requires_reason_and_note():
    before = {
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": 12.0,
        "completed_by": "Ada",
        "completion_at": "2026-07-24T14:00:00",
        "dashboard_status": "review_required",
    }
    draft = {
        "post_weight_lbs": 12.0,
        "completed_by": "Ada",
        "completion_at": "2026-07-24T14:00",
    }
    policy = classify_edit_reason_requirements(draft, before, outcome="mark_completed")
    assert policy["reason_required"] is True
    assert policy["confirm_completed"] is True
    codes = {c["code"] for c in policy["reason_codes"]}
    assert codes == COMPLETE_REASON_CODE_SET

    missing_note = resolve_edit_audit_reason(
        reason=None,
        reason_code="MANUAL_RESEARCH_CONFIRMED",
        reason_note=None,
        draft=draft,
        before=before,
        outcome="mark_completed",
    )
    assert missing_note["ok"] is False
    assert missing_note["error"] == "manager_note_required"


def test_collect_excluded_bag_ids_from_day_bag_and_oi(monkeypatch):
    rows = [
        {"bag_id": "KEEP1A", "disposition": None, "effective_status": "completed"},
        {"bag_id": "EXCL01", "disposition": "EXCLUDE", "effective_status": "excluded"},
        {"bag_id": "EXCL02", "disposition": None, "effective_status": "completed"},
    ]
    monkeypatch.setattr(
        "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
        lambda *a, **k: {
            "EXCL02": {"override_type": "exclude", "active": True},
        },
    )
    monkeypatch.setattr(
        "backend.rinse_wf_oi_manager_disposition.active_excluded_bag_ids",
        lambda *a, **k: set(),
    )
    monkeypatch.setattr(
        "backend.rinse_wf_oi_manager_disposition.bag_ids_with_manager_exclude_oi",
        lambda *a, **k: {"EXCL03"},
    )
    out = collect_processed_pounds_excluded_bag_ids(MagicMock(), 3, rows)
    assert "EXCL01" in out
    assert "EXCL02" in out
    assert "KEEP1A" not in out


def test_processed_pounds_omits_excluded_bags(monkeypatch):
    monkeypatch.setattr("backend.management_today.table_exists", lambda *a, **k: True)
    monkeypatch.setattr("backend.management_today.table_has_column", lambda *a, **k: True)

    class _Cur:
        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return [
                {
                    "bag_id": "KEEP",
                    "rush_status": "RUSH",
                    "post_weight_lbs": 100.0,
                    "disposition": None,
                    "effective_status": "completed",
                },
                {
                    "bag_id": "EXCL",
                    "rush_status": "RUSH",
                    "post_weight_lbs": 35.8,
                    "disposition": "EXCLUDE",
                    "effective_status": "excluded",
                },
            ]

    monkeypatch.setattr(
        "backend.rinse_wf_oi_manager_disposition.collect_processed_pounds_excluded_bag_ids",
        lambda cursor, org, rows: {
            str(r.get("bag_id") or "").strip().upper()
            for r in rows
            if str(r.get("disposition") or "").upper() == "EXCLUDE"
        },
    )
    monkeypatch.setattr(
        "backend.rinse_veewash_review.load_bag_weight_map",
        lambda cursor, org, ids, *, selected_date_et: {
            "KEEP": {"pre_weight_lbs": 110.0, "pre_weight_event_id": 1},
            "EXCL": {"pre_weight_lbs": 36.2, "pre_weight_event_id": 2},
        },
    )
    out = load_wf_day_weight_totals(_Cur(), 3, date(2026, 9, 13))
    assert out["pre_lbs"] == 110.0
    assert out["post_lbs"] == 100.0
    assert out["pre_weight_bag_count"] == 1
    assert out["post_weight_bag_count"] == 1
    assert out["excluded_bag_count"] == 1
