"""Employee-day publication status, exclude filtering, and 400 error clarity."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_performance_approvals import (
    derive_employee_day_publication_status,
    exclude_session_publication,
)
from backend.rinse_performance_folder_publisher import (
    attach_publication_status_to_day,
    partition_employees_by_exclusion,
)
from backend.rinse_performance_roles import ROLE_FOLDER

DAY = date(2026, 9, 11)


def test_derive_employee_day_statuses():
    assert (
        derive_employee_day_publication_status(
            [
                {"role_status": "closed", "publication_status": "APPROVED"},
                {"role_status": "closed", "publication_status": "APPROVED"},
            ]
        )["status"]
        == "APPROVED"
    )
    assert (
        derive_employee_day_publication_status(
            [
                {"role_status": "closed", "publication_status": "UNAPPROVED"},
                {"role_status": "closed", "publication_status": "UNAPPROVED"},
            ]
        )["status"]
        == "NEEDS_APPROVAL"
    )
    assert (
        derive_employee_day_publication_status(
            [
                {"role_status": "closed", "publication_status": "APPROVED"},
                {"role_status": "closed", "publication_status": "UNAPPROVED"},
            ]
        )["status"]
        == "PARTIALLY_APPROVED"
    )
    assert (
        derive_employee_day_publication_status(
            [
                {"role_status": "closed", "publication_status": "EXCLUDED"},
                {"role_status": "closed", "publication_status": "EXCLUDED"},
            ]
        )["status"]
        == "EXCLUDED"
    )
    # Approved included + excluded sibling → Approved (not Partially)
    assert (
        derive_employee_day_publication_status(
            [
                {"role_status": "closed", "publication_status": "APPROVED"},
                {"role_status": "closed", "publication_status": "EXCLUDED"},
            ]
        )["status"]
        == "APPROVED"
    )


def test_partition_keeps_excluded_visible_but_out_of_active_summary():
    day = {
        "employees": [
            {
                "employee": "Tarannum",
                "orders_completed": 10,
                "total_pre_lbs": 200,
                "performance_hours": 4,
                "day_publication_status": "APPROVED",
            },
            {
                "employee": "Mrs Chen (VeeWash)",
                "orders_completed": 0,
                "total_pre_lbs": 0,
                "performance_hours": 1,
                "day_publication_status": "EXCLUDED",
            },
        ],
        "summary": {"needs_attribution_count": 2},
    }
    out = partition_employees_by_exclusion(day)
    # Excluded stay visible for management Review (do not vanish).
    assert len(out["employees"]) == 2
    assert out["employees"][1]["excluded_from_metrics"] is True
    assert out["employees"][1]["dashboard_rankable"] is False
    assert len(out["excluded_employees"]) == 1
    assert out["excluded_employees"][0]["employee"].startswith("Mrs Chen")
    # Active summary still excludes them.
    assert out["summary"]["employee_count"] == 1
    assert out["summary"]["orders_completed"] == 10
    assert out["summary"]["needs_attribution_count"] == 2
    assert out["summary_all_including_excluded"]["employee_count"] == 2
    assert out["summary_approved"]["employee_day_count"] == 1
    assert out["summary_approved"]["orders_completed"] == 10
    assert out["employees"][0]["dashboard_rankable"] is True


def test_exclude_without_prior_approval_uses_snapshot():
    cur = MagicMock()
    # get_approval_row: none, then row after upsert
    rows = [None, {"business_date_et": DAY, "published_metric_value": 40.0, "content_fingerprint": "fp"}]
    with (
        patch(
            "backend.rinse_performance_approvals.ensure_rinse_performance_approval_tables"
        ),
        patch(
            "backend.rinse_performance_approvals.get_approval_row",
            side_effect=lambda *a, **k: rows.pop(0) if rows else None,
        ),
        patch(
            "backend.rinse_performance_approvals.upsert_approved_snapshot",
            return_value={"ok": True},
        ) as upsert,
        patch("backend.rinse_performance_approvals._record_event"),
    ):
        out = exclude_session_publication(
            cur,
            3,
            role_key=ROLE_FOLDER,
            session_id="WF-1",
            snapshot={
                "business_date_et": DAY,
                "session_id": "WF-1",
                "employee_name": "X",
                "metric_key": "lbs_per_hour",
                "metric_unit": "lb/hr",
                "published_numerator": 100,
                "published_denominator": 2,
                "published_metric_value": 50,
                "calculated_numerator": 100,
                "calculated_denominator": 2,
                "calculated_metric_value": 50,
                "content_fingerprint": "fp",
            },
        )
    assert out["ok"] is True
    assert upsert.called
    assert out["publication"]["status"] == "EXCLUDED"


def test_exclude_without_snapshot_returns_useful_error():
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_performance_approvals.ensure_rinse_performance_approval_tables"
        ),
        patch(
            "backend.rinse_performance_approvals.get_approval_row",
            return_value=None,
        ),
    ):
        out = exclude_session_publication(
            cur, 3, role_key=ROLE_FOLDER, session_id="WF-2"
        )
    assert out["ok"] is False
    assert out["status"] == "not_approved"
    assert "error" in out
    assert "snapshot" in out["error"].lower() or "Approve" in out["error"]


def test_attach_sets_employee_day_status():
    day = {
        "employees": [
            {
                "employee": "A",
                "sessions": [
                    {"session_id": "WF-1", "role_status": "closed"},
                    {"session_id": "WF-2", "role_status": "closed"},
                ],
            }
        ],
        "sessions": [
            {"session_id": "WF-1", "role_status": "closed"},
            {"session_id": "WF-2", "role_status": "closed"},
        ],
    }
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_performance_folder_publisher.approval_status_map",
            return_value={
                "WF-1": {"status": "APPROVED"},
                "WF-2": {"status": "UNAPPROVED"},
            },
        ),
        patch(
            "backend.rinse_performance_folder_publisher.get_folder_benchmark",
            return_value=40.0,
        ),
    ):
        attach_publication_status_to_day(cur, 3, day)
    assert day["employees"][0]["day_publication_status"] == "PARTIALLY_APPROVED"
