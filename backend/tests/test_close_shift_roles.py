"""Close Shift must accept list-shaped ``me.roles`` (portal users).

Regression for TypeError: unhashable type: 'list' on Confirm Close.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_shift_analysis_routes import roles_from_user
from backend.rinse_veewash_shift_day import (
    STATUS_OPEN,
    STATUS_READY_TO_CLOSE,
    close_shift_day,
    validate_close,
)


def test_roles_list_must_not_be_set_literal_member():
    """Document the exact bug: set({list}) raises unhashable type: 'list'."""
    me = {"roles": ["ADMIN", "MANAGER"]}
    with pytest.raises(TypeError, match="unhashable type: 'list'"):
        _ = {(me.get("roles") or me.get("role") or "")}


def test_roles_from_user_accepts_list_and_string():
    assert roles_from_user({"roles": ["Admin", "manager"]}) == {"ADMIN", "MANAGER"}
    assert roles_from_user({"role": "OPS,admin"}) == {"OPS", "ADMIN"}
    assert roles_from_user({"roles": []}) == set()
    assert roles_from_user(None) == set()


def _summary(*, review=0, pending=0, completed=70, active=None, wf_review=None, hd_review=None):
    active = completed + pending + review if active is None else active
    wf_review = review if wf_review is None else wf_review
    hd_review = 0 if hd_review is None else hd_review
    return {
        "active_workload": active,
        "total_workload": active,
        "completed": completed,
        "pending": pending,
        "new_today": active,
        "exceptions": {"review_required": review},
        "review_by_reason": {},
        "segments": {
            "all": {
                "active_workload": active,
                "completed": completed,
                "pending": pending,
                "new_today": active,
                "exceptions": {"review_required": review},
                "bag_ids": {
                    "new_today": [f"B{i}" for i in range(active)],
                    "completed": [f"B{i}" for i in range(completed)],
                    "pending": [f"P{i}" for i in range(pending)],
                    "review_required": [f"R{i}" for i in range(review)],
                },
            },
            "wf": {
                "new_today": active - hd_review,
                "completed": completed,
                "pending": pending,
                "exceptions": {"review_required": wf_review},
                "bag_ids": {"review_required": [f"WR{i}" for i in range(wf_review)]},
            },
            "hd": {
                "new_today": hd_review,
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": hd_review},
                "bag_ids": {"review_required": [f"HR{i}" for i in range(hd_review)]},
            },
        },
    }


def _close_ok(summary, *, allow_unresolved=False, reason=None):
    cursor = MagicMock()
    day = {"status": STATUS_READY_TO_CLOSE if summary["exceptions"]["review_required"] == 0 else STATUS_OPEN}
    with patch(
        "backend.rinse_veewash_shift_day.build_or_load_step1_for_date",
        return_value=({}, summary, day),
    ), patch(
        "backend.rinse_veewash_shift_day.persist_day_snapshot",
        return_value={**day, "status": "CLOSED"},
    ), patch(
        "backend.rinse_veewash_shift_day._write_audit"
    ), patch(
        "backend.rinse_veewash_shift_day._commit"
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": "CLOSED"},
    ):
        return close_shift_day(
            cursor,
            3,
            date(2026, 7, 25),
            actor_user_id=1,
            actor_display_name="Admin",
            reason=reason,
            allow_unresolved_reviews=allow_unresolved,
            checklist={"workload_reconciled": True},
        )


def test_close_no_reviews():
    out = _close_ok(_summary(review=0, pending=0, completed=73))
    assert out["ok"] is True


def test_close_wf_reviews_blocked_without_override():
    summary = _summary(review=2, pending=0, completed=70, wf_review=2, hd_review=0)
    assert validate_close(summary)["ok"] is False
    out = _close_ok(summary, allow_unresolved=False)
    assert out["ok"] is False
    assert out["error"] == "validation_failed"


def test_close_hd_reviews_with_override():
    summary = _summary(review=1, pending=0, completed=70, wf_review=0, hd_review=1)
    out = _close_ok(summary, allow_unresolved=True, reason="HD review deferred")
    assert out["ok"] is True


def test_close_mixed_wf_hd_reviews_with_override():
    summary = _summary(review=3, pending=0, completed=70, wf_review=2, hd_review=1)
    out = _close_ok(summary, allow_unresolved=True, reason="mixed reviews cleared offline")
    assert out["ok"] is True


def test_close_resolved_reviews():
    out = _close_ok(_summary(review=0, pending=0, completed=70, wf_review=0, hd_review=0))
    assert out["ok"] is True
