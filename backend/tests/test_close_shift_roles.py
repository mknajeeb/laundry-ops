"""Close Shift must accept list-shaped ``me.roles`` (portal users).

Regression for TypeError: unhashable type: 'list' on Confirm Close.
Also locks the strict close gate (no override).
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


def _bid(prefix: str, i: int) -> str:
    return f"{prefix}{i:06d}"[:10]


def _bags_for(summary):
    rows = []
    for i in range(int(summary["completed"] or 0)):
        rows.append(
            {"bag_id": _bid("DONE", i), "service_type": "WF", "effective_status": "completed"}
        )
    for i in range(int(summary["pending"] or 0)):
        rows.append(
            {"bag_id": _bid("WPND", i), "service_type": "WF", "effective_status": "pending"}
        )
    wf_review = int((summary["segments"]["wf"].get("exceptions") or {}).get("review_required") or 0)
    hd_review = int((summary["segments"]["hd"].get("exceptions") or {}).get("review_required") or 0)
    for i in range(wf_review):
        rows.append(
            {
                "bag_id": _bid("WREV", i),
                "service_type": "WF",
                "effective_status": "review_required",
            }
        )
    for i in range(hd_review):
        rows.append(
            {
                "bag_id": _bid("HREV", i),
                "service_type": "HD",
                "effective_status": "review_required",
            }
        )
    return rows


def _close(summary):
    cursor = MagicMock()
    day = {
        "status": STATUS_READY_TO_CLOSE
        if summary["exceptions"]["review_required"] == 0 and summary["pending"] == 0
        else STATUS_OPEN,
        "headline": summary,
    }
    closed = {**day, "status": "CLOSED"}
    bags = _bags_for(summary)
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=[day, closed],
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=summary,
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags",
        return_value=bags,
    ), patch(
        "backend.rinse_veewash_shift_day.persist_day_snapshot",
    ) as persist, patch(
        "backend.rinse_veewash_shift_day._write_audit"
    ), patch(
        "backend.rinse_employee_completed_bags.clear_step1_productivity_cache"
    ), patch(
        "backend.rinse_veewash_shift_day._count_hd_partially_recorded",
        return_value=0,
    ):
        out = close_shift_day(
            cursor,
            3,
            date(2026, 7, 25),
            actor_user_id=1,
            actor_display_name="Admin",
        )
    if out.get("ok"):
        persist.assert_not_called()
    return out


def test_close_no_reviews():
    out = _close(_summary(review=0, pending=0, completed=73))
    assert out["ok"] is True


def test_close_wf_reviews_blocked():
    summary = _summary(review=2, pending=0, completed=70, wf_review=2, hd_review=0)
    assert validate_close(summary, day_bags=_bags_for(summary))["ok"] is False
    out = _close(summary)
    assert out["ok"] is False
    assert out["error"] == "shift_not_ready_to_close"
    assert out["blocking_counts"]["wf_review_required"] == 2


def test_close_hd_reviews_blocked_no_override():
    summary = _summary(review=1, pending=0, completed=70, wf_review=0, hd_review=1)
    out = _close(summary)
    assert out["ok"] is False
    assert out["error"] == "shift_not_ready_to_close"
    assert out["blocking_counts"]["hd_review_required"] == 1


def test_close_mixed_wf_hd_reviews_blocked():
    summary = _summary(review=3, pending=0, completed=70, wf_review=2, hd_review=1)
    out = _close(summary)
    assert out["ok"] is False
    assert out["blocking_counts"]["wf_review_required"] == 2
    assert out["blocking_counts"]["hd_review_required"] == 1


def test_close_resolved_reviews():
    out = _close(_summary(review=0, pending=0, completed=70, wf_review=0, hd_review=0))
    assert out["ok"] is True
