"""Safety and idempotency tests for near-complete WF weight recovery."""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_employee_completed_bags import _wf_completion_weight_event
from backend.rinse_near_complete_wf_backfill import (
    BACKFILL_REASON,
    BACKFILL_SOURCE,
    _insert_post_processing_weight_scan,
    apply_near_complete_wf_backfill_for_bag,
    plan_near_complete_wf_backfill_for_bag,
)

DAY = date(2026, 7, 16)
T0 = datetime(2026, 7, 16, 7, 0)
CC = datetime(2026, 7, 16, 13, 54)


def _ev(purpose: str, ts: datetime, user: str = "Jennifer (VeeWash)", **extra):
    row = {
        "id": extra.pop("id", None),
        "dedupe_key": extra.pop("dedupe_key", None),
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "bag_id": "BAG1",
    }
    row.update(extra)
    return row


def _eligible_events():
    return [
        _ev("sent-to-vendor", T0, user="Driver"),
        _ev("weight-entry", datetime(2026, 7, 16, 8, 0), user="Singh (VeeWash)"),
        _ev("start-cleaning", datetime(2026, 7, 16, 9, 0), user="Singh (VeeWash)"),
        _ev(
            "complete-cleaning",
            CC,
            user="Jennifer (VeeWash)",
            id=44,
            dedupe_key="cc-dedupe",
        ),
    ]


def _weight_evidence(
    *,
    service_type="WF",
    status="REJECTED",
    reason="MISSING_FROM_LATEST_PORTAL_SCRAPE",
    registry_lbs=27.2,
    portal_lbs=27.2,
):
    return {
        "registry": {
            "id": 7,
            "service_type": service_type,
            "date_clean": DAY,
            "completion_status": status,
            "completion_reason": reason,
            "last_upload_batch_id": 2566,
        },
        "registry_weight_lbs": registry_lbs,
        "portal_weight_lbs": portal_lbs,
        "weights_consistent": (
            registry_lbs is not None
            and portal_lbs is not None
            and abs(registry_lbs - portal_lbs) <= 0.05
        ),
        "weight_source": {
            "kind": "confirmed_upload_batch_row",
            "registry_row_id": 7,
            "upload_row_id": 99,
            "upload_batch_id": 2566,
            "upload_batch_state": "CONFIRMED",
            "row_status": "ACCEPTED",
        },
    }


def _plan(events, evidence=None):
    cursor = MagicMock()
    with patch(
        "backend.rinse_near_complete_wf_backfill._registry_weight_evidence",
        return_value=evidence or _weight_evidence(),
    ):
        return plan_near_complete_wf_backfill_for_bag(
            cursor,
            3,
            "BAG1",
            selected_date_et=DAY,
            events=events,
        )


def test_eligible_wf_bag_is_recoverable_with_provenance():
    plan = _plan(_eligible_events())
    assert plan["eligible"] is True
    assert plan["credited_employee"] == "Jennifer (VeeWash)"
    assert plan["registry_weight_lbs"] == 27.2
    assert plan["portal_weight_lbs"] == 27.2
    assert plan["originating_complete_cleaning_event_id"] == 44
    assert plan["originating_complete_cleaning_dedupe_key"] == "cc-dedupe"


def test_eligible_wf_bag_is_recovered_transactionally():
    before = _eligible_events()
    synthetic = _ev(
        "weight-entry",
        CC.replace(minute=55),
        user="Jennifer (VeeWash)",
        weight_lbs=27.2,
        source_filename=BACKFILL_SOURCE,
    )
    conn = MagicMock()
    conn.autocommit = True
    cursor = conn.cursor.return_value
    with patch(
        "backend.rinse_near_complete_wf_backfill._registry_weight_evidence",
        return_value=_weight_evidence(),
    ), patch(
        "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
        side_effect=[{"BAG1": before}, {"BAG1": before + [synthetic]}],
    ), patch(
        "backend.rinse_near_complete_wf_backfill._insert_post_processing_weight_scan",
        return_value={"action": "inserted_post_processing_weight_scan"},
    ), patch(
        "backend.rinse_portal_departure_completion.restore_portal_scrape_rejected_bag",
        return_value=True,
    ), patch(
        "backend.rinse_bag_registry.recompute_completion_for_bags",
        return_value={"completed": 1},
    ), patch(
        "backend.rinse_at_vendor_module._evaluate_bag_as_of",
        return_value=(
            "Completed",
            "post_processing_weight",
            CC.replace(minute=55),
            {},
            None,
        ),
    ):
        out = apply_near_complete_wf_backfill_for_bag(
            conn,
            3,
            "BAG1",
            selected_date_et=DAY,
        )
    assert out["applied"] is True
    assert out["success"] is True
    assert out["after"]["at_vendor_status"] == "Completed"
    conn.commit.assert_called_once()
    conn.rollback.assert_called_once()
    assert conn.autocommit is True


def test_second_refresh_does_not_create_duplicate_synthetic_event():
    synthetic = _ev(
        "weight-entry",
        CC.replace(minute=55),
        weight_lbs=27.2,
        source_filename=BACKFILL_SOURCE,
        raw_json=json.dumps(
            {"synthetic": True, "backfill_source": BACKFILL_SOURCE}
        ),
    )
    plan = _plan(_eligible_events() + [synthetic])
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "already_has_post_processing_weight"


def test_insert_is_idempotent_by_dedupe_key():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 123, "weight_lbs": 27.2}
    with patch(
        "backend.rinse_bag_registry.ensure_rinse_bag_scan_events_table"
    ), patch(
        "backend.rinse_workload_bag_weight.ensure_scan_events_weight_lbs_column"
    ), patch(
        "backend.rinse_scan_event_identity.dedupe_key_from_row",
        return_value="stable-key",
    ):
        out = _insert_post_processing_weight_scan(
            cursor,
            3,
            "BAG1",
            scanned_at=CC.replace(minute=55),
            user_name="Jennifer (VeeWash)",
            weight_lbs=27.2,
            anchor_purpose="complete-cleaning",
            complete_cleaning_timestamp=CC,
            complete_cleaning_event_id=44,
            complete_cleaning_dedupe_key="cc-dedupe",
            weight_source=_weight_evidence()["weight_source"],
        )
    assert out["action"] == "scan_already_exists"
    assert out["dedupe_key"] == "stable-key"
    assert not any(
        str(call.args[0]).lstrip().upper().startswith("INSERT")
        for call in cursor.execute.call_args_list
    )


def test_real_post_weight_takes_precedence_over_synthetic_even_if_earlier():
    events = _eligible_events()
    real = _ev(
        "weight-entry",
        datetime(2026, 7, 16, 13, 54, 30),
        user="Jennifer Real",
        weight_lbs=27.2,
        source_filename="scheduled-events.csv",
    )
    synthetic = _ev(
        "weight-entry",
        datetime(2026, 7, 16, 13, 55),
        user="Jennifer Synthetic",
        weight_lbs=27.2,
        source_filename=BACKFILL_SOURCE,
        raw_json=json.dumps(
            {"synthetic": True, "backfill_source": BACKFILL_SOURCE}
        ),
    )
    chosen, completion_ts = _wf_completion_weight_event(
        events + [real, synthetic],
        anchor_ts=T0,
        as_of_end=datetime(2026, 7, 16, 23, 59),
    )
    assert chosen["user_name"] == "Jennifer Real"
    assert completion_ts == real["scanned_at_parsed"]


def test_late_real_event_still_resolves_to_one_completion_event():
    events = _eligible_events()
    synthetic = _ev(
        "weight-entry",
        datetime(2026, 7, 16, 13, 55),
        user="Synthetic",
        weight_lbs=27.2,
        source_filename=BACKFILL_SOURCE,
    )
    real = _ev(
        "weight-entry",
        datetime(2026, 7, 16, 14, 1),
        user="Real Folder",
        weight_lbs=27.2,
        source_filename="portal-detail.csv",
    )
    chosen, _ = _wf_completion_weight_event(
        events + [synthetic, real],
        anchor_ts=T0,
        as_of_end=datetime(2026, 7, 16, 23, 59),
    )
    assert chosen["user_name"] == "Real Folder"


def test_no_registry_weight_means_no_recovery():
    plan = _plan(
        _eligible_events(),
        _weight_evidence(registry_lbs=None, portal_lbs=None),
    )
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "no_registry_weight"


def test_mismatched_portal_and_registry_weight_is_not_reliable():
    plan = _plan(
        _eligible_events(),
        _weight_evidence(registry_lbs=27.2, portal_lbs=25.0),
    )
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "unreliable_registry_weight"


def test_no_complete_cleaning_means_no_recovery():
    plan = _plan(_eligible_events()[:-1])
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "no_complete_cleaning_on_selected_day"


def test_hd_bag_is_not_recovered():
    plan = _plan(_eligible_events(), _weight_evidence(service_type="HD"))
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "not_wf"


def test_genuinely_rejected_bag_remains_rejected():
    plan = _plan(
        _eligible_events(),
        _weight_evidence(status="REJECTED", reason="CONFIRMED_CANCELLATION"),
    )
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "genuinely_rejected"


def test_explicit_cancellation_event_blocks_recovery():
    events = _eligible_events() + [
        _ev("cancelled", datetime(2026, 7, 16, 14, 0), user="Portal")
    ]
    plan = _plan(events)
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "confirmed_cancellation"


def test_synthetic_event_contains_full_audit_metadata():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.lastrowid = 321
    with patch(
        "backend.rinse_bag_registry.ensure_rinse_bag_scan_events_table"
    ), patch(
        "backend.rinse_workload_bag_weight.ensure_scan_events_weight_lbs_column"
    ), patch(
        "backend.rinse_scan_event_identity.dedupe_key_from_row",
        return_value="stable-key",
    ):
        out = _insert_post_processing_weight_scan(
            cursor,
            3,
            "BAG1",
            scanned_at=CC.replace(minute=55),
            user_name="Jennifer (VeeWash)",
            weight_lbs=27.2,
            anchor_purpose="complete-cleaning",
            complete_cleaning_timestamp=CC,
            complete_cleaning_event_id=44,
            complete_cleaning_dedupe_key="cc-dedupe",
            weight_source=_weight_evidence()["weight_source"],
        )
    insert_call = cursor.execute.call_args_list[-1]
    raw = json.loads(insert_call.args[1][-1])
    assert raw["synthetic"] is True
    assert raw["backfill_source"] == BACKFILL_SOURCE
    assert raw["backfill_reason"] == BACKFILL_REASON
    assert raw["synthetic_created_at_utc"]
    assert raw["idempotency_key"] == "stable-key"
    assert raw["originating_complete_cleaning"]["event_id"] == 44
    assert raw["originating_complete_cleaning"]["dedupe_key"] == "cc-dedupe"
    assert raw["originating_complete_cleaning"]["timestamp"] == CC.isoformat()
    assert raw["registry_weight_source"]["upload_batch_state"] == "CONFIRMED"
    assert out["source"] == BACKFILL_SOURCE
