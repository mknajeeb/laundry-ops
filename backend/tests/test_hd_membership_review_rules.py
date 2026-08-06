"""HD membership / Review Required / close-gate rules (no EDD gate)."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_hd_day_presentation import (
    apply_hd_same_day_membership_policy,
    finalize_hd_step1_summary,
    strip_hd_carryover_from_summary,
)
from backend.rinse_hd_edd_membership import apply_hd_edd_day_membership_gate
from backend.rinse_hd_step1_review import (
    apply_hd_review_status_to_summary,
    exclude_prior_completed_hd_from_summary,
)
from backend.rinse_scan_purpose import is_workitems_added_purpose
from backend.rinse_veewash_day_membership import INCLUSION_ADDED_LATER, INCLUSION_BASELINE
from backend.rinse_veewash_shift_day import (
    HD_CLOSE_REVIEW_REQUIRED_MESSAGE,
    close_shift_day,
    validate_close,
)
from backend.tests.test_hd_no_carryover_and_specialty_metrics import _seg


DAY = date(2026, 7, 26)


def test_purpose_workitems_added_normalization():
    assert is_workitems_added_purpose("workitems-added")
    assert is_workitems_added_purpose("Workitems-Added")
    assert is_workitems_added_purpose(" workitems_added ")
    assert is_workitems_added_purpose("workitems added")
    assert not is_workitems_added_purpose("create-workitem-bulk")
    assert not is_workitems_added_purpose("weight-entry")
    assert not is_workitems_added_purpose("create-workitem")


def test_a_future_edd_does_not_exclude():
    """A — Jul 26 scrape HD with EDD Jul 28 stays in membership."""
    membership = {
        "membership": {
            "FUTURE1": {
                "inclusion_source": INCLUSION_ADDED_LATER,
                "service_type_portal": "HD",
                "customer_name": "Future EDD",
                "estimated_delivery_date": "2026-07-28",
            },
            "WF01": {
                "inclusion_source": INCLUSION_BASELINE,
                "service_type_portal": "WF",
            },
        },
        "baseline_bag_ids": ["WF01"],
        "added_later_bag_ids": ["FUTURE1"],
        "baseline_count": 1,
        "added_later_count": 1,
        "total_count": 2,
    }
    # Legacy gate name must be a no-op.
    gated = apply_hd_edd_day_membership_gate(MagicMock(), 3, DAY, membership)
    assert "FUTURE1" in gated["membership"]
    assert gated["hd_edd_gate"]["enabled"] is False
    assert gated["hd_edd_gate"]["removed_future_edd_count"] == 0

    summary = {
        "selected_date_et": DAY.isoformat(),
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg(["FUTURE1"], [], pending=["FUTURE1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["FUTURE1"], [], pending=["FUTURE1"]),
            "all": _seg(["WF01", "FUTURE1"], [], pending=["FUTURE1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01", "FUTURE1"], [], pending=["FUTURE1"]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WF01"], []),
        },
        "membership": membership,
    }
    out = finalize_hd_step1_summary(
        summary, selected_date_et=DAY, membership=membership
    )
    assert "FUTURE1" in out["segments"]["hd"]["bag_ids"]["new_today"]


def test_b_only_workitems_added_enters_review():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg(["HDWIA1", "HDOTHER1"], [], pending=["HDWIA1", "HDOTHER1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDWIA1", "HDOTHER1"], [], pending=["HDWIA1", "HDOTHER1"]),
            "all": _seg(
                ["WF01", "HDWIA1", "HDOTHER1"], [], pending=["HDWIA1", "HDOTHER1"]
            ),
            "rush": _seg([], []),
            "non_rush": _seg(
                ["WF01", "HDWIA1", "HDOTHER1"], [], pending=["HDWIA1", "HDOTHER1"]
            ),
        }
    }
    out = apply_hd_review_status_to_summary(
        summary,
        production_by_bag={},
        workitems_added_bag_ids={"HDWIA1"},
    )
    hd = out["segments"]["hd"]
    assert "HDWIA1" in hd["bag_ids"]["review_required"]
    assert "HDOTHER1" not in hd["bag_ids"]["review_required"]
    assert "HDOTHER1" in hd["bag_ids"]["pending"]
    assert set(hd["bag_ids"]["new_today"]) == {"HDOTHER1", "HDWIA1"}
    assert out["hd_review_policy"]["review_required_requires_purpose"] == "workitems-added"
    assert out["segments"]["wf"]["bag_ids"]["new_today"] == ["WF01"]


def test_c_append_only_after_disappearance():
    """Admitted HD stays after later scrape would drop it (policy keeps members)."""
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg(["HDKEEP1"], [], pending=["HDKEEP1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDKEEP1"], [], pending=["HDKEEP1"]),
            "all": _seg(["WF01", "HDKEEP1"], [], pending=["HDKEEP1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01", "HDKEEP1"], [], pending=["HDKEEP1"]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WF01"], []),
        }
    }
    membership = {
        "baseline_bag_ids": ["WF01", "HDKEEP1"],
        "added_later_bag_ids": [],
        "membership": {
            "WF01": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "WF"},
            "HDKEEP1": {
                "inclusion_source": INCLUSION_BASELINE,
                "service_type_portal": "HD",
            },
        },
    }
    # Simulate a later membership rebuild that still includes the bag (append-only).
    out = apply_hd_same_day_membership_policy(summary, membership)
    assert "HDKEEP1" in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert out["hd_policy"]["same_day_adds_allowed"] is True


def test_d_later_same_day_admission():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg(["HDLATER1"], [], pending=["HDLATER1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDLATER1"], [], pending=["HDLATER1"]),
            "all": _seg(["WF01", "HDLATER1"], [], pending=["HDLATER1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01", "HDLATER1"], [], pending=["HDLATER1"]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WF01"], []),
        }
    }
    membership = {
        "baseline_bag_ids": ["WF01"],
        "added_later_bag_ids": ["HDLATER1"],
        "membership": {
            "WF01": {"inclusion_source": INCLUSION_BASELINE, "service_type_portal": "WF"},
            "HDLATER1": {
                "inclusion_source": INCLUSION_ADDED_LATER,
                "service_type_portal": "HD",
            },
        },
    }
    out = finalize_hd_step1_summary(
        summary, selected_date_et=DAY, membership=membership
    )
    assert "HDLATER1" in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert out["hd_policy"]["same_day_later_admit_count"] == 1


def test_e_prior_day_carryover_excluded():
    """Legacy HD carryover without membership Opening Carryover evidence is stripped."""
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "all": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WF01"], []),
        }
    }
    out = strip_hd_carryover_from_summary(summary, membership={"opening_carryover_bag_ids": []})
    assert out["segments"]["hd"]["bag_ids"]["carryover"] == []
    assert out["segments"]["hd"]["bag_ids"]["new_today"] == []
    assert out["hd_policy"]["carryover_removed_count"] == 1


def test_e2_opening_carryover_hd_preserved():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg([], ["HDCARRY1"], review=["HDCARRY1"]),
            "all": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
            "rush": _seg([], []),
            "non_rush": _seg(["WF01"], ["HDCARRY1"], review=["HDCARRY1"]),
            "wf_rush": _seg([], []),
            "wf_non_rush": _seg(["WF01"], []),
        }
    }
    out = strip_hd_carryover_from_summary(
        summary, membership={"opening_carryover_bag_ids": ["HDCARRY1"]}
    )
    assert "HDCARRY1" in out["segments"]["hd"]["bag_ids"]["carryover"]
    assert out["hd_policy"]["carryover_removed_count"] == 0


def test_f_prior_user_completed_excluded():
    summary = {
        "segments": {
            "wf": _seg(["WF01"], []),
            "hd": _seg(["HDDONE1", "HDNEW1"], [], pending=["HDDONE1", "HDNEW1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HDDONE1", "HDNEW1"], [], pending=["HDDONE1", "HDNEW1"]),
            "all": _seg(
                ["WF01", "HDDONE1", "HDNEW1"], [], pending=["HDDONE1", "HDNEW1"]
            ),
            "rush": _seg([], []),
            "non_rush": _seg(
                ["WF01", "HDDONE1", "HDNEW1"], [], pending=["HDDONE1", "HDNEW1"]
            ),
        }
    }
    out = exclude_prior_completed_hd_from_summary(summary, {"HDDONE1"})
    assert "HDDONE1" not in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert "HDNEW1" in out["segments"]["hd"]["bag_ids"]["new_today"]
    assert "WF01" in out["segments"]["wf"]["bag_ids"]["new_today"]


def test_g_batch_closure_blocked_when_hd_review_required():
    summary = {
        "segments": {
            "all": _seg(["HDWIA1"], [], review=["HDWIA1"]),
            "wf": _seg([], [], completed=[]),
            "hd": _seg(["HDWIA1"], [], review=["HDWIA1"]),
        }
    }
    day_bags = [
        {
            "bag_id": "HDWIA1",
            "service_type": "HD",
            "effective_status": "review_required",
        }
    ]
    v = validate_close(summary, day_bags=day_bags)
    assert v["ok"] is False
    assert "hd_review_required" in v["blocking"]
    assert v["message"] == HD_CLOSE_REVIEW_REQUIRED_MESSAGE
    assert v["blocking_counts"]["hd_review_required"] == 1


def test_h_batch_closure_allowed_when_no_hd_review_required():
    summary = {
        "segments": {
            "all": _seg(["HDPEND1", "WF01"], [], completed=["WF01"], pending=["HDPEND1"]),
            "wf": _seg([], [], completed=["WF01"]),
            "hd": _seg(["HDPEND1"], [], pending=["HDPEND1"]),
        }
    }
    day_bags = [
        {"bag_id": "WF01", "service_type": "WF", "effective_status": "completed"},
        {"bag_id": "HDPEND1", "service_type": "HD", "effective_status": "pending"},
    ]
    v = validate_close(summary, day_bags=day_bags)
    assert v["ok"] is True
    assert v["blocking_counts"]["hd_review_required"] == 0
    assert v["blocking_counts"].get("hd_pending_members") == 1


def test_close_shift_day_archives_hd_review_as_stale():
    """Release B: HD review no longer blocks close — archived as unfinished."""
    cursor = MagicMock()
    day = {
        "status": "OPEN",
        "shift_date_et": DAY,
        "organization_id": 3,
        "headline": {
            "segments": {
                "all": _seg(["HDWIA1"], [], review=["HDWIA1"]),
                "wf": _seg([], []),
                "hd": _seg(["HDWIA1"], [], review=["HDWIA1"]),
            }
        },
    }
    closed = {**day, "status": "CLOSED"}
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=[day, closed],
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=day["headline"],
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags",
        return_value=[
            {
                "bag_id": "HDWIA1",
                "service_type": "HD",
                "effective_status": "review_required",
                "bag_snapshot": {},
            }
        ],
    ), patch(
        "backend.rinse_veewash_shift_day.derive_shift_day_status", return_value="OPEN"
    ), patch(
        "backend.rinse_veewash_shift_day._write_audit",
    ), patch(
        "backend.rinse_employee_completed_bags.clear_step1_productivity_cache",
    ):
        out = close_shift_day(
            cursor,
            3,
            DAY,
            actor_user_id=1,
            actor_display_name="Manager",
        )
    assert out["ok"] is True
    assert out["archive"]["unfinished"] == 1


def test_wf_untouched_by_hd_review_rewrite():
    summary = {
        "segments": {
            "wf": _seg(["WF01", "WF02"], [], pending=["WF01"], completed=["WF02"]),
            "hd": _seg(["HD1"], [], pending=["HD1"]),
            "hd_rush": _seg([], []),
            "hd_non_rush": _seg(["HD1"], [], pending=["HD1"]),
            "all": _seg(
                ["WF01", "WF02", "HD1"], [], pending=["WF01", "HD1"], completed=["WF02"]
            ),
            "rush": _seg([], []),
            "non_rush": _seg(
                ["WF01", "WF02", "HD1"], [], pending=["WF01", "HD1"], completed=["WF02"]
            ),
        }
    }
    before = deepcopy(summary["segments"]["wf"])
    out = apply_hd_review_status_to_summary(
        summary, production_by_bag={}, workitems_added_bag_ids=set()
    )
    assert out["segments"]["wf"] == before
