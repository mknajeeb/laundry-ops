"""Try Out conversion preserves historical periods and requires a new start date."""

import pytest

from backend.employment_category_history import (
    current_assignment,
    validate_employment_assignments,
)


def test_validate_tryout_end_before_start(monkeypatch):
    monkeypatch.setattr(
        "backend.employment_category_history._row_kind",
        lambda conn, cid: ("tryout", "EC_TRYOUT", "Try Out"),
    )
    with pytest.raises(ValueError, match="earlier"):
        validate_employment_assignments(
            None,
            [
                {
                    "employment_category_id": 1,
                    "effective_from": "2026-08-13",
                    "effective_to": "2026-08-10",
                }
            ],
        )


def test_validate_tryout_requires_both_dates_for_new(monkeypatch):
    monkeypatch.setattr(
        "backend.employment_category_history._row_kind",
        lambda conn, cid: ("tryout", "EC_TRYOUT", "Try Out"),
    )
    with pytest.raises(ValueError, match="requires a start date"):
        validate_employment_assignments(
            None,
            [{"employment_category_id": 1, "effective_from": "2026-08-10", "effective_to": ""}],
        )


def test_validate_existing_empty_dates_grandfathered(monkeypatch):
    monkeypatch.setattr(
        "backend.employment_category_history._row_kind",
        lambda conn, cid: ("w2", "EC_W2", "W-2 Employee"),
    )
    validate_employment_assignments(
        None,
        [{"employment_category_id": 2, "effective_from": "2026-01-01", "effective_to": ""}],
        existing_rows=[{"employment_category_id": 2, "effective_from": "2026-01-01"}],
    )


def test_current_assignment_covers_today_not_future():
    rows = [
        {
            "id": 1,
            "employment_category_id": 9,
            "effective_from": "2026-08-10",
            "effective_to": "2026-08-13",
            "worker_category": "tryout",
        },
        {
            "id": 2,
            "employment_category_id": 1,
            "effective_from": "2026-08-14",
            "effective_to": None,
            "worker_category": "w2",
        },
    ]
    from datetime import date

    assert current_assignment(rows, on=date(2026, 8, 12))["id"] == 1
    assert current_assignment(rows, on=date(2026, 8, 15))["id"] == 2
