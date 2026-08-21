"""Day-boundary + Dirty-membership regression tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.rinse_workload_membership_eligibility import (
    filter_operationally_eligible_ids,
    headline_identity_ok,
    resolve_day_operational_membership,
)


D0 = date(2026, 8, 20)
D1 = date(2026, 8, 21)


def test_headline_identity_balances():
    ok, msg = headline_identity_ok(
        {
            "segments": {
                "wf": {
                    "total_workload": 44,
                    "completed": 0,
                    "pending": 44,
                    "exceptions": {"review_required": 0},
                },
                "all": {
                    "total_workload": 45,
                    "completed": 1,
                    "pending": 44,
                    "exceptions": {"review_required": 0},
                },
            }
        }
    )
    assert ok, msg


def test_headline_identity_fails_when_unmapped():
    ok, msg = headline_identity_ok(
        {
            "segments": {
                "wf": {
                    "total_workload": 49,
                    "completed": 0,
                    "pending": 29,
                    "exceptions": {"review_required": 0},
                }
            }
        }
    )
    assert not ok
    assert "49" in msg


def test_unfinished_prior_day_carries_and_completed_does_not(monkeypatch):
    from backend import rinse_workload_membership_eligibility as elig

    monkeypatch.setattr(
        elig,
        "load_prior_day_unfinished_member_ids",
        lambda *a, **k: {"CARRY01", "CARRY02"},
    )
    monkeypatch.setattr(
        elig,
        "load_dirty_entry_dates",
        lambda *a, **k: {
            "CARRY01": D0,
            "CARRY02": D0,
            "DONE01": D0,
            "NEW01": D1,
            "PORTAL1": D0,  # would-be portal-only if no dirty — has dirty here
        },
    )
    monkeypatch.setattr(
        elig,
        "load_completed_before_date",
        lambda *a, **k: {"DONE01"},
    )
    monkeypatch.setattr(
        elig,
        "load_prior_day_disappearance_ids",
        lambda *a, **k: set(),
    )

    out = resolve_day_operational_membership(
        MagicMock(),
        3,
        D1,
        extra_candidates=["DONE01", "NEW01", "PORTALONLY"],
        existing_member_ids=[],
        service_type="WF",
    )
    assert "CARRY01" in out["carryover_bag_ids"]
    assert "CARRY02" in out["carryover_bag_ids"]
    assert "DONE01" not in out["member_ids"]
    assert "NEW01" in out["member_ids"]
    assert "PORTALONLY" not in out["member_ids"]
    assert "PORTALONLY" in out["excluded_no_dirty"]


def test_prior_disappearance_does_not_carry(monkeypatch):
    from backend import rinse_workload_membership_eligibility as elig

    monkeypatch.setattr(
        elig,
        "load_dirty_entry_dates",
        lambda *a, **k: {"GONE01": date(2026, 7, 1)},
    )
    monkeypatch.setattr(elig, "load_completed_before_date", lambda *a, **k: set())
    monkeypatch.setattr(
        elig,
        "load_prior_day_disappearance_ids",
        lambda *a, **k: {"GONE01"},
    )
    filtered = filter_operationally_eligible_ids(
        MagicMock(), 3, D1, ["GONE01"]
    )
    assert filtered["eligible"] == []
    assert filtered["excluded_prior_disappearance"] == ["GONE01"]


def test_partial_portal_cannot_admit_without_dirty(monkeypatch):
    from backend import rinse_workload_membership_eligibility as elig

    monkeypatch.setattr(
        elig, "load_prior_day_unfinished_member_ids", lambda *a, **k: set()
    )
    monkeypatch.setattr(elig, "load_dirty_entry_dates", lambda *a, **k: {})
    monkeypatch.setattr(elig, "load_completed_before_date", lambda *a, **k: set())
    monkeypatch.setattr(
        elig, "load_prior_day_disappearance_ids", lambda *a, **k: set()
    )
    # 50 portal rows from a 2-page scrape — none Dirty-eligible.
    portal = [f"PORT{i:04d}" for i in range(50)]
    out = resolve_day_operational_membership(
        MagicMock(), 3, D1, extra_candidates=portal, existing_member_ids=[]
    )
    assert out["member_ids"] == []
    assert len(out["excluded_no_dirty"]) == 50


def test_prior_dirty_not_prior_member_can_enter_if_eligible(monkeypatch):
    from backend import rinse_workload_membership_eligibility as elig

    monkeypatch.setattr(
        elig, "load_prior_day_unfinished_member_ids", lambda *a, **k: set()
    )
    monkeypatch.setattr(
        elig,
        "load_dirty_entry_dates",
        lambda *a, **k: {"OPEN01": D0},
    )
    monkeypatch.setattr(elig, "load_completed_before_date", lambda *a, **k: set())
    monkeypatch.setattr(
        elig, "load_prior_day_disappearance_ids", lambda *a, **k: set()
    )
    out = resolve_day_operational_membership(
        MagicMock(),
        3,
        D1,
        extra_candidates=["OPEN01"],
        existing_member_ids=[],
    )
    assert out["member_ids"] == ["OPEN01"]
    assert out["carryover_bag_ids"] == []
    assert "OPEN01" in out["new_or_other_bag_ids"]


def test_no_midnight_scrape_still_seeds_carryover(monkeypatch):
    from backend.rinse_veewash_day_membership import build_append_only_membership

    monkeypatch.setattr(
        "backend.rinse_veewash_day_membership.select_first_valid_scrape_after_midnight",
        lambda *a, **k: (None, False, "no_valid_scrape_after_midnight"),
    )
    monkeypatch.setattr(
        "backend.rinse_workload_membership_eligibility.load_prior_day_unfinished_member_ids",
        lambda *a, **k: {"CARRY99"},
    )
    monkeypatch.setattr(
        "backend.rinse_workload_membership_eligibility.filter_operationally_eligible_ids",
        lambda *a, **k: {
            "eligible": ["CARRY99"],
            "excluded_no_dirty": [],
            "excluded_completed_before": [],
            "excluded_prior_disappearance": [],
            "dirty_entry_by_bag": {"CARRY99": D0},
        },
    )
    out = build_append_only_membership(MagicMock(), 3, D1)
    assert out["ok"] is True
    assert out["no_valid_scrape_after_midnight"] is True
    assert out["opening_carryover_bag_ids"] == ["CARRY99"]
    assert out["total_count"] == 1
