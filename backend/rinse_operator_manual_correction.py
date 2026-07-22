"""Operator-approved manual bag corrections with audit trail."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    REASON_OPERATOR_APPROVED_MANUAL_CORRECTION,
    TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
    normalize_bag_id,
)


def write_operator_audit_log(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    action: str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    remarks: str,
    actor_user_id: int | None = None,
) -> bool:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "audit_log"):
        return False
    cursor.execute(
        """
        INSERT INTO audit_log (
            organization_id, actor_user_id, entity_type, entity_id,
            action, old_value, new_value, remarks
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            actor_user_id,
            "rinse_bag",
            normalize_bag_id(bag_id),
            action,
            json.dumps(old_value, default=str) if old_value is not None else None,
            json.dumps(new_value, default=str) if new_value is not None else None,
            remarks,
        ),
    )
    return True


def apply_operator_approved_manual_completion(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    credited_employee: str,
    weight_lbs: float,
    selected_date_et: date,
    completion_timestamp: datetime,
    upload_batch_id: int,
    remarks: str,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """
    Operator-approved correction: complete bag, attach weight, credit employee.

    Documents the change in audit_log — not an automated portal recovery.
    """
    from backend.rinse_bag_registry import (
        ensure_rinse_bag_registry_table,
        ensure_rinse_bag_scan_events_table,
        get_registry_row,
        recompute_completion_for_bags,
    )
    from backend.rinse_portal_departure_completion import restore_portal_scrape_rejected_bag
    from backend.rinse_scan_event_identity import dedupe_key_from_row
    from backend.rinse_workload_bag_weight import (
        attach_portal_weight_to_post_processing_scan,
        ensure_scan_events_weight_lbs_column,
    )

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return {"applied": False, "reason": "invalid_bag_id"}

    before_registry = get_registry_row(cursor, org, bid)
    ensure_rinse_bag_registry_table(cursor)
    ensure_rinse_bag_scan_events_table(cursor)
    ensure_scan_events_weight_lbs_column(cursor)

    time_raw = completion_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "organization_id": org,
        "bag_id": bid,
        "purpose": "weight-entry",
        "scanned_at_parsed": completion_timestamp,
        "time_scanned_raw": time_raw,
        "user_name": credited_employee,
        "rack": None,
        "scan_index": None,
        "last_location": None,
        "last_scan": None,
    }
    dedupe_key = dedupe_key_from_row(row)
    raw_json = json.dumps(
        {
            "Bag ID": bid,
            "Purpose": "weight-entry",
            "Time Scanned": time_raw,
            "User": credited_employee,
            "backfill_source": TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
            "operator_approved": True,
            "Weight": weight_lbs,
        }
    )
    cursor.execute(
        """
        INSERT INTO rinse_bag_scan_events (
            organization_id, bag_id, dedupe_key, scan_index, rack,
            time_scanned_raw, scanned_at_parsed, source_timezone,
            user_name, purpose, last_location, last_scan,
            source_upload_batch_id, source_filename, weight_lbs,
            last_seen_at, raw_json, created_at, updated_at
        ) VALUES (
            %s, %s, %s, NULL, NULL,
            %s, %s, 'America/New_York',
            %s, 'weight-entry', NULL, NULL,
            0, %s, %s,
            NOW(), %s, NOW(), NOW()
        )
        ON DUPLICATE KEY UPDATE
            user_name = VALUES(user_name),
            weight_lbs = COALESCE(weight_lbs, VALUES(weight_lbs)),
            raw_json = VALUES(raw_json),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            dedupe_key,
            time_raw,
            completion_timestamp,
            credited_employee,
            TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
            float(weight_lbs),
            raw_json,
        ),
    )
    insert_result = {
        "action": "inserted_or_updated_operator_weight_scan",
        "dedupe_key": dedupe_key,
        "weight_lbs": float(weight_lbs),
        "source": TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
    }
    attach_result = attach_portal_weight_to_post_processing_scan(
        cursor,
        org,
        bid,
        weight_lbs=float(weight_lbs),
        selected_date_et=selected_date_et,
    )

    from backend.rinse_at_vendor_module import (
        AV_STATUS_COMPLETED,
        _evaluate_bag_as_of,
        _load_at_vendor_scan_events_for_bags,
        _resolve_selected_day_anchor_ts,
    )
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_scan_purpose import is_weight_entry_purpose
    from backend.rinse_wf_weight_events import wf_post_processing_weight_completion

    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    events = _load_at_vendor_scan_events_for_bags(
        cursor, org, [bid], scanned_before=as_of_end
    ).get(bid, [])
    weight_entries = [ev for ev in events if is_weight_entry_purpose(ev.get("purpose"))]
    if len(weight_entries) < 2:
        first_ts = completion_timestamp - timedelta(minutes=30)
        first_row = {
            "organization_id": org,
            "bag_id": bid,
            "purpose": "weight-entry",
            "scanned_at_parsed": first_ts,
            "time_scanned_raw": first_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "user_name": credited_employee,
            "rack": None,
            "scan_index": None,
            "last_location": None,
            "last_scan": None,
        }
        first_dk = dedupe_key_from_row(first_row)
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, dedupe_key, scan_index, rack,
                time_scanned_raw, scanned_at_parsed, source_timezone,
                user_name, purpose, last_location, last_scan,
                source_upload_batch_id, source_filename, weight_lbs,
                last_seen_at, raw_json, created_at, updated_at
            ) VALUES (
                %s, %s, %s, NULL, NULL,
                %s, %s, 'America/New_York',
                %s, 'weight-entry', NULL, NULL,
                0, %s, NULL,
                NOW(), %s, NOW(), NOW()
            )
            ON DUPLICATE KEY UPDATE updated_at = NOW()
            """,
            (
                org,
                bid,
                first_dk,
                first_row["time_scanned_raw"],
                first_ts,
                credited_employee,
                TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
                json.dumps({"operator_approved": True, "role": "first_weight_entry_anchor"}),
            ),
        )
        attach_result = attach_portal_weight_to_post_processing_scan(
            cursor,
            org,
            bid,
            weight_lbs=float(weight_lbs),
            selected_date_et=selected_date_et,
        )

    events = _load_at_vendor_scan_events_for_bags(
        cursor, org, [bid], scanned_before=as_of_end
    ).get(bid, [])
    anchor = _resolve_selected_day_anchor_ts(events, selected_date_et)
    if anchor is not None:
        from backend.rinse_wf_weight_events import _latest_wf_processing_after_anchor

        timeline = gaming_events_from_records(events)
        latest_proc_ts, _ = _latest_wf_processing_after_anchor(
            timeline, anchor_ts=anchor, as_of_end=as_of_end
        )
        if latest_proc_ts is None:
            proc_ts = completion_timestamp - timedelta(minutes=31)
            proc_row = {
                "organization_id": org,
                "bag_id": bid,
                "purpose": "add-photos",
                "scanned_at_parsed": proc_ts,
                "time_scanned_raw": proc_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "user_name": credited_employee,
                "rack": None,
                "scan_index": None,
                "last_location": None,
                "last_scan": None,
            }
            proc_dk = dedupe_key_from_row(proc_row)
            cursor.execute(
                """
                INSERT INTO rinse_bag_scan_events (
                    organization_id, bag_id, dedupe_key, scan_index, rack,
                    time_scanned_raw, scanned_at_parsed, source_timezone,
                    user_name, purpose, last_location, last_scan,
                    source_upload_batch_id, source_filename, weight_lbs,
                    last_seen_at, raw_json, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, NULL, NULL,
                    %s, %s, 'America/New_York',
                    %s, 'add-photos', NULL, NULL,
                    0, %s, NULL,
                    NOW(), %s, NOW(), NOW()
                )
                ON DUPLICATE KEY UPDATE updated_at = NOW()
                """,
                (
                    org,
                    bid,
                    proc_dk,
                    proc_row["time_scanned_raw"],
                    proc_ts,
                    credited_employee,
                    TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
                    json.dumps(
                        {
                            "operator_approved": True,
                            "role": "wf_processing_anchor",
                        }
                    ),
                ),
            )

    restore_portal_scrape_rejected_bag(cursor, org, bid)
    recompute = recompute_completion_for_bags(cursor, org, [bid])

    events_after = _load_at_vendor_scan_events_for_bags(
        cursor, org, [bid], scanned_before=as_of_end
    ).get(bid, [])
    anchor = _resolve_selected_day_anchor_ts(events_after, selected_date_et)
    timeline = gaming_events_from_records(events_after)
    status_after, _, comp_ts, _, _ = _evaluate_bag_as_of(
        timeline,
        service_type="WF",
        as_of_end=as_of_end,
        anchor_ts_override=anchor,
    )
    weight_hit = (
        wf_post_processing_weight_completion(timeline, anchor_ts=anchor, as_of_end=as_of_end)
        if anchor
        else None
    )
    wf_complete = status_after == AV_STATUS_COMPLETED and weight_hit is not None

    if not wf_complete:
        cursor.execute(
            """
            INSERT INTO rinse_bag_registry (
                organization_id, bag_id, completion_status, completion_reason,
                completed_at, trigger_kind, trigger_scan_at, weight_num,
                last_upload_batch_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                completion_status = VALUES(completion_status),
                completion_reason = VALUES(completion_reason),
                completed_at = VALUES(completed_at),
                trigger_kind = VALUES(trigger_kind),
                trigger_scan_at = VALUES(trigger_scan_at),
                weight_num = VALUES(weight_num),
                last_upload_batch_id = VALUES(last_upload_batch_id),
                updated_at = NOW()
            """,
            (
                org,
                bid,
                COMPLETION_COMPLETED,
                REASON_OPERATOR_APPROVED_MANUAL_CORRECTION,
                completion_timestamp,
                TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
                completion_timestamp,
                float(weight_lbs),
                int(upload_batch_id),
            ),
        )
    else:
        cursor.execute(
            """
            UPDATE rinse_bag_registry
            SET completion_reason = %s,
                trigger_kind = %s,
                weight_num = %s,
                last_upload_batch_id = %s,
                updated_at = NOW()
            WHERE organization_id = %s AND bag_id = %s
            """,
            (
                REASON_OPERATOR_APPROVED_MANUAL_CORRECTION,
                TRIGGER_KIND_OPERATOR_APPROVED_MANUAL_CORRECTION,
                float(weight_lbs),
                int(upload_batch_id),
                org,
                bid,
            ),
        )

    after_registry = get_registry_row(cursor, org, bid)

    audit_remarks = (
        f"{remarks} credited_employee={credited_employee} weight_lbs={weight_lbs} "
        f"selected_date_et={selected_date_et.isoformat()}"
    )
    write_operator_audit_log(
        cursor,
        org,
        bag_id=bid,
        action="operator_approved_manual_bag_completion",
        old_value={"registry": before_registry},
        new_value={
            "registry": after_registry,
            "insert_weight_scan": insert_result,
            "attach_portal_weight": attach_result,
            "recompute": recompute,
        },
        remarks=audit_remarks,
        actor_user_id=actor_user_id,
    )

    return {
        "bag_id": bid,
        "applied": True,
        "credited_employee": credited_employee,
        "weight_lbs": float(weight_lbs),
        "completion_timestamp": completion_timestamp.isoformat(),
        "insert_weight_scan": insert_result,
        "attach_portal_weight": attach_result,
        "recompute": recompute,
        "registry_after": after_registry,
    }
