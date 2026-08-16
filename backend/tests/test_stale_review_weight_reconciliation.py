"""P0.2 — stale Review / PRE-POST weight reconciliation regressions.

Normal cycle derivation must clear invalidated Disappeared/missing-POST
reasons when later evidence arrives, keep valid bulk Review, and persist
PRE/POST without overwriting PRE with POST.

Root cause covered: mis-tagged dryer ``sent-to-vendor`` must not become the
cycle anchor or truncate the current cycle (9IDG97VIS4 / D10-50-VW).
"""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_bulk_workitems import REASON_WF_BULK_WORKITEM_REVIEW
from backend.rinse_cycle_boundary import resolve_current_cycle, resolve_cycle_anchor
from backend.rinse_current_cycle_weight import resolve_current_cycle_weights
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    classify_veewash_workload,
)

DAY = date(2026, 8, 16)
ENTRY = list(DEFAULT_FACILITY_ENTRY_RACKS)


def _ev(purpose, ts, *, rack=None, user="Op", lbs=None, eid=1, **extra):
    row = {
        "id": eid,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "rack": rack,
        "user_name": user,
        "weight_lbs": lbs,
    }
    row.update(extra)
    return row


def _pres(active=1, service="WF", rush="RUSH", last_seen=None, portal="at_vendor"):
    ls = None
    if last_seen is not None:
        ls = datetime(last_seen.year, last_seen.month, last_seen.day, 16, 0)
    return {
        "active": active,
        "service_type": service,
        "rush_flag": rush,
        "portal_status": portal,
        "last_seen_at": ls,
        "customer_name": "Test",
    }


def _entry(d, hour=6):
    return {
        "first_entry_at": datetime(d.year, d.month, d.day, hour, 0),
        "entry_date": d,
        "entry_source": "facility_dirty_scan",
    }


def _comp(d, hour=13, by="Jennifer (VeeWash)"):
    return {
        "completion_at": datetime(d.year, d.month, d.day, hour, 0),
        "completion_date": d,
        "completed_by": by,
        "completion_source": "post_garments_reviewed_weight_entry",
    }


def _idg_timeline(*, with_dryer_stv=True, with_post=True):
    """Authoritative 9IDG97VIS4-shaped chronology for 2026-08-16."""
    events = [
        _ev("sent-to-vendor", datetime(2026, 8, 16, 4, 34), rack="Rinse Zipvan", eid=1),
        _ev("sent-to-vendor", datetime(2026, 8, 16, 5, 47), rack="VeeWash Dirty", eid=2),
        _ev(
            "weight-entry",
            datetime(2026, 8, 16, 5, 53),
            lbs=34.2,
            user="Varun (VeeWash)",
            eid=3,
        ),
    ]
    if with_dryer_stv:
        events.append(
            _ev("sent-to-vendor", datetime(2026, 8, 16, 7, 27), rack="D10-50-VW", eid=4)
        )
    events.extend(
        [
            _ev(
                "garments-reviewed",
                datetime(2026, 8, 16, 8, 3),
                user="Jennifer (VeeWash)",
                eid=5,
            ),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 16, 8, 3),
                rack="Folding-6-VW",
                user="Jennifer (VeeWash)",
                eid=6,
            ),
            _ev(
                "move-bag",
                datetime(2026, 8, 16, 9, 1),
                rack="VeeWash Clean",
                user="Jennifer (VeeWash)",
                eid=7,
            ),
        ]
    )
    if with_post:
        events.append(
            _ev(
                "weight-entry",
                datetime(2026, 8, 16, 9, 1),
                lbs=32.9,
                user="Jennifer (VeeWash)",
                eid=8,
            )
        )
    return events


def test_a_dryer_stv_does_not_keep_disappeared_when_completion_exists():
    """A: dryer STV noise + later GR/Clean/POST → Completed; Disappeared cleared."""
    tl = _idg_timeline(with_dryer_stv=True)
    assert resolve_cycle_anchor(tl, selected_date_et=DAY, entry_racks=ENTRY) == datetime(
        2026, 8, 16, 5, 47
    )
    cycle = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY)
    assert cycle.effective_status == "completed"
    assert cycle.completion_at == datetime(2026, 8, 16, 9, 1)
    assert cycle.entry_rack == "VeeWash Dirty"

    presence = {"BAG1": _pres(active=0, last_seen=DAY)}
    entry = {"BAG1": _entry(DAY, hour=5)}
    completion = {
        "BAG1": {
            "completion_date": DAY,
            "completion_at": cycle.completion_at,
            "completed_by": "Jennifer (VeeWash)",
            "completion_source": cycle.completion_source,
        }
    }
    classified = classify_veewash_workload(
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
        disappearance_state_by_bag={"BAG1": REASON_DISAPPEARED_WITHOUT_COMPLETION},
    )
    assert "BAG1" in classified["completed_on_date"]
    assert "BAG1" not in classified.get("disappeared_exception", [])


def test_d_pre_then_post_persisted_independently_despite_dryer_stv():
    """D: PRE then POST both correct; PRE not overwritten; POST not null."""
    tl = _idg_timeline(with_dryer_stv=True)
    w = resolve_current_cycle_weights(tl, selected_date_et=DAY, entry_racks=ENTRY)
    assert w.pre_weight_lbs == 34.2
    assert w.pre_weight_at == datetime(2026, 8, 16, 5, 53)
    assert w.pre_weight_employee == "Varun (VeeWash)"
    assert w.post_weight_lbs == 32.9
    assert w.post_weight_at == datetime(2026, 8, 16, 9, 1)
    assert w.post_weight_employee == "Jennifer (VeeWash)"
    assert w.post_weight_event_exists is True


def test_b_missing_post_clears_when_valid_post_arrives():
    """B: completed with only PRE → missing POST; later POST clears it."""
    presence = {"BAGB": _pres()}
    entry = {"BAGB": _entry(DAY)}
    completion = {"BAGB": _comp(DAY, hour=10)}

    raw = classify_veewash_workload(
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    missing = expand_review_required(
        raw,
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "BAGB": {
                "pre_weight_lbs": 20.0,
                "post_weight_lbs": None,
                "post_weight_event_exists": False,
                "weight_entry_count": 1,
            }
        },
    )
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in missing["review_reasons_by_bag"]["BAGB"]

    cleared = expand_review_required(
        classify_veewash_workload(
            selected_date_et=DAY,
            presence_by_bag=presence,
            entry_by_bag=entry,
            completion_by_bag=completion,
        ),
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "BAGB": {
                "pre_weight_lbs": 20.0,
                "post_weight_lbs": 18.0,
                "post_weight_event_exists": True,
                "weight_entry_count": 2,
            }
        },
    )
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT not in (
        cleared["review_reasons_by_bag"].get("BAGB") or []
    )


def test_c_valid_bulk_review_outranks_completed():
    """C: completed + uncleared bulk specialty → remains Review."""
    presence = {"BAGC": _pres()}
    entry = {"BAGC": _entry(DAY)}
    completion = {"BAGC": _comp(DAY, hour=16)}
    raw = classify_veewash_workload(
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag=completion,
    )
    out = expand_review_required(
        raw,
        selected_date_et=DAY,
        presence_by_bag=presence,
        entry_by_bag=entry,
        weight_by_bag={
            "BAGC": {
                "pre_weight_lbs": 20.5,
                "post_weight_lbs": 18.1,
                "post_weight_event_exists": True,
                "weight_entry_count": 2,
            }
        },
        bulk_scan_by_bag={
            "BAGC": {"count": 1, "first_at": datetime(2026, 8, 16, 9, 6)}
        },
        bulk_resolution_by_bag={},
    )
    assert "BAGC" in out["review_required"]
    assert REASON_WF_BULK_WORKITEM_REVIEW in out["review_reasons_by_bag"]["BAGC"]
    assert "BAGC" not in out["completed_on_date"]


def test_e_late_scan_in_later_cycle_updates_via_normal_resolve():
    """E: late POST arrives later — same resolver updates state (no manual repair)."""
    early = _idg_timeline(with_dryer_stv=True, with_post=False)
    mid = resolve_current_cycle(early, selected_date_et=DAY, entry_racks=ENTRY)
    assert mid.effective_status == "pending"
    assert mid.garments_reviewed_at == datetime(2026, 8, 16, 8, 3)

    full = _idg_timeline(with_dryer_stv=True, with_post=True)
    late = resolve_current_cycle(full, selected_date_et=DAY, entry_racks=ENTRY)
    assert late.effective_status == "completed"
    assert late.completion_at == datetime(2026, 8, 16, 9, 1)
    w = resolve_current_cycle_weights(full, selected_date_et=DAY, entry_racks=ENTRY)
    assert w.post_weight_lbs == 32.9


def test_f_no_manual_repair_required_machine_stv_ignored():
    """F: normal resolve alone heals dryer-STV corruption — no hand edit."""
    bad_anchor_world = resolve_cycle_anchor(
        [
            _ev("sent-to-vendor", datetime(2026, 8, 16, 5, 47), rack="VeeWash Dirty", eid=1),
            _ev("sent-to-vendor", datetime(2026, 8, 16, 7, 27), rack="D10-50-VW", eid=2),
        ],
        selected_date_et=DAY,
        entry_racks=ENTRY,
    )
    assert bad_anchor_world == datetime(2026, 8, 16, 5, 47)


def test_washer_stv_also_ignored_as_cycle_boundary():
    tl = [
        _ev("sent-to-vendor", datetime(2026, 8, 16, 5, 0), rack="VeeWash Dirty", eid=1),
        _ev("sent-to-vendor", datetime(2026, 8, 16, 6, 0), rack="W45-60-VW", eid=2),
        _ev("weight-entry", datetime(2026, 8, 16, 6, 30), lbs=10.0, eid=3),
        _ev("garments-reviewed", datetime(2026, 8, 16, 9, 0), eid=4),
        _ev("weight-entry", datetime(2026, 8, 16, 9, 5), lbs=9.0, eid=5),
    ]
    c = resolve_current_cycle(tl, selected_date_et=DAY, entry_racks=ENTRY)
    assert c.cycle_anchor_at == datetime(2026, 8, 16, 5, 0)
    assert c.effective_status == "completed"
