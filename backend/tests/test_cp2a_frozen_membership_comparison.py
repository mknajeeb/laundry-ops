"""Fix A: frozen membership compare uses new_today ∪ carryover (CP2B-safe)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_shift_day import reproject_day_bag_completions_from_chronology

# normalize_bag_id rejects very short IDs — use realistic bag shapes.
A, B, C, D = "BAGAAAAAAA", "BAGBBBBBBB", "BAGCCCCCCC", "BAGDDDDDDD"


def _run_reproject(*, frozen, wl, day=date(2026, 8, 7)):
    cursor = MagicMock()
    summary = {
        "active_workload": len(frozen),
        "total_workload": len(frozen),
        "completed": len(wl.get("completed_on_date") or []),
        "pending": len(wl.get("pending_end_of_date") or []),
        "exceptions": {"review_required": len(wl.get("review_required") or [])},
        "membership": wl.get("membership") or {"ok": True, "total_count": len(frozen)},
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"status": "OPEN"},
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            side_effect=[
                [{"bag_id": b} for b in frozen],
                [{"bag_id": b, "effective_status": "pending"} for b in frozen],
            ],
        ),
        patch(
            "backend.rinse_veewash_shift_day.get_step1_activation_date",
            return_value=date(2026, 7, 23),
        ),
        patch(
            "backend.rinse_veewash_shift_day.build_veewash_daily_workload_from_membership",
            return_value=wl,
        ),
        patch(
            "backend.rinse_veewash_shift_day.build_step1_headline_summary",
            return_value=summary,
        ),
        patch(
            "backend.rinse_hd_day_presentation.finalize_hd_step1_summary",
            side_effect=lambda s, **k: s,
        ),
        patch(
            "backend.rinse_hd_day_metrics.attach_specialty_metrics_to_summary",
            side_effect=lambda _c, _o, _d, s, **k: s,
        ),
        patch(
            "backend.rinse_veewash_shift_day.persist_day_snapshot",
            return_value={"status": "OPEN"},
        ) as persist,
        patch("backend.rinse_veewash_shift_day._commit"),
        patch(
            "backend.rinse_veewash_shift_day.derive_shift_day_status",
            return_value="OPEN",
        ),
    ):
        out = reproject_day_bag_completions_from_chronology(cursor, 3, day)
    return out, persist


def test_cp2b_carryover_not_false_divergence():
    """frozen=A B C D; new_today=C D; carryover=A B → no divergence."""
    frozen = [A, B, C, D]
    wl = {
        "new_today": [C, D],
        "carryover": [A, B],
        "opening_carryover": [A, B],
        "completed_on_date": [],
        "pending_end_of_date": list(frozen),
        "review_required": [],
        "rows": [{"bag_id": b, "outcome": "pending"} for b in frozen],
        "membership": {"ok": True, "total_count": 4},
    }
    out, persist = _run_reproject(frozen=frozen, wl=wl)
    assert out["ok"] is True
    assert out.get("error") != "frozen_membership_diverged"
    assert out["persisted"] is True
    assert out["membership_count"] == 4
    persist.assert_called_once()


def test_true_unexpected_admit_still_diverges():
    frozen = [A, B, C]
    wl = {
        "new_today": [A, B, C, D],
        "carryover": [],
        "opening_carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": [A, B, C, D],
        "review_required": [],
        "rows": [],
        "membership": {"ok": True, "total_count": 4},
    }
    out, persist = _run_reproject(frozen=frozen, wl=wl)
    assert out["ok"] is False
    assert out["error"] == "frozen_membership_diverged"
    assert out["persisted"] is False
    assert D in (out.get("only_in_rebuild") or [])
    persist.assert_not_called()


def test_true_missing_member_still_diverges():
    frozen = [A, B, C]
    wl = {
        "new_today": [A, B],
        "carryover": [],
        "opening_carryover": [],
        "completed_on_date": [],
        "pending_end_of_date": [A, B],
        "review_required": [],
        "rows": [],
        "membership": {"ok": True, "total_count": 2},
    }
    out, persist = _run_reproject(frozen=frozen, wl=wl)
    assert out["ok"] is False
    assert out["error"] == "frozen_membership_diverged"
    assert out["persisted"] is False
    assert C in (out.get("missing_from_rebuild") or [])
    persist.assert_not_called()


def test_duplicate_ids_across_new_today_and_carryover_deduped():
    """Same bag in both buckets must not inflate rebuilt set."""
    frozen = [A, B, C]
    wl = {
        "new_today": [A, B, C],
        "carryover": [A, B],  # overlap with new_today
        "opening_carryover": [A, B],
        "completed_on_date": [],
        "pending_end_of_date": list(frozen),
        "review_required": [],
        "rows": [{"bag_id": b, "outcome": "pending"} for b in frozen],
        "membership": {"ok": True, "total_count": 3},
    }
    out, persist = _run_reproject(frozen=frozen, wl=wl)
    assert out["ok"] is True
    assert out["membership_count"] == 3
    assert out["persisted"] is True
    persist.assert_called_once()


def test_aug7_regression_112_equals_72_plus_40():
    """Aug 7 shape: frozen 112 = new_today 72 ∪ carryover 40."""
    carryover = [f"CO{i:08d}" for i in range(40)]
    new_today = [f"NT{i:08d}" for i in range(72)]
    frozen = sorted(carryover + new_today)
    assert len(frozen) == 112
    wl = {
        "new_today": list(new_today),
        "carryover": list(carryover),
        "opening_carryover": list(carryover),
        "completed_on_date": [],
        "pending_end_of_date": list(frozen),
        "review_required": [],
        "rows": [{"bag_id": b, "outcome": "pending"} for b in frozen],
        "membership": {"ok": True, "total_count": 112},
    }
    out, persist = _run_reproject(frozen=frozen, wl=wl)
    assert out["ok"] is True
    assert out.get("error") != "frozen_membership_diverged"
    assert out["membership_count"] == 112
    assert out["persisted"] is True
    persist.assert_called_once()
