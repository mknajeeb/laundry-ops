"""
Finalize Rinse operational state on upload batch CONFIRM only.

Draft uploads store portal rows + upload_batch_scan_events (audit/staging).
Persistent rinse_bag_scan_events, registry completion, and folding performance
update only when the batch is confirmed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    REASON_CLEAN_RACK_SCANNED,
    evaluate_bag_completion,
    normalize_bag_id,
)
from backend.rinse_bag_registry import (
    merge_scan_events_from_upload,
    recompute_completion_for_bags,
)
from backend.ta_helpers import table_exists


def load_upload_batch_scan_events_as_dataframe(
    cursor, organization_id: int, upload_batch_id: int
) -> pd.DataFrame:
    """Rebuild events CSV shape from draft upload_batch_scan_events rows."""
    if not table_exists(cursor, "upload_batch_scan_events"):
        return pd.DataFrame()

    cursor.execute(
        """
        SELECT bag_id, scan_index, rack, time_scanned_raw, user_name, purpose,
               last_location, last_scan
        FROM upload_batch_scan_events
        WHERE organization_id = %s AND upload_batch_id = %s
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        """,
        (int(organization_id), int(upload_batch_id)),
    )
    rows = cursor.fetchall() or []
    if not rows:
        return pd.DataFrame()

    out_rows: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out_rows.append(
            {
                "Bag ID": r.get("bag_id") or "",
                "Scan Index": "" if r.get("scan_index") is None else str(r.get("scan_index")),
                "Rack": r.get("rack") or "",
                "Time Scanned": r.get("time_scanned_raw") or "",
                "User": r.get("user_name") or "",
                "Purpose": r.get("purpose") or "",
                "Last Location": r.get("last_location") or "",
                "Last Scan": r.get("last_scan") or "",
            }
        )
    return pd.DataFrame(out_rows)


def fetch_batch_scan_events_by_bag(
    cursor, organization_id: int, upload_batch_id: int
) -> dict[str, list[dict[str, Any]]]:
    """Timeline events per bag from draft upload_batch_scan_events."""
    if not table_exists(cursor, "upload_batch_scan_events"):
        return {}

    cursor.execute(
        """
        SELECT id, bag_id, rack, user_name, scanned_at_parsed, scan_index
        FROM upload_batch_scan_events
        WHERE organization_id = %s AND upload_batch_id = %s
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        """,
        (int(organization_id), int(upload_batch_id)),
    )
    by_bag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        bid = normalize_bag_id(r.get("bag_id"))
        if not bid:
            continue
        by_bag[bid].append(
            {
                "id": r.get("id"),
                "rack": r.get("rack"),
                "user_name": r.get("user_name"),
                "scanned_at_parsed": r.get("scanned_at_parsed"),
                "scan_index": r.get("scan_index"),
            }
        )
    return dict(by_bag)


def preview_completion_for_batch(
    cursor, organization_id: int, upload_batch_id: int
) -> dict[str, dict[str, Any]]:
    """Non-persisted completion preview from draft scan-events only."""
    by_bag = fetch_batch_scan_events_by_bag(cursor, organization_id, upload_batch_id)
    out: dict[str, dict[str, Any]] = {}
    for bag_id, events in by_bag.items():
        result = evaluate_bag_completion(events)
        out[bag_id] = {
            "completion_status": result.completion_status,
            "completion_reason": result.completion_reason,
            "trigger_kind": result.trigger_kind,
            "first_clean_scan_at": (
                result.first_clean_scan_at.isoformat()
                if isinstance(result.first_clean_scan_at, datetime)
                else None
            ),
            "trigger_scan_at": (
                result.trigger_scan_at.isoformat()
                if isinstance(result.trigger_scan_at, datetime)
                else None
            ),
        }
    return out


def apply_registry_from_accepted_portal_rows(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    accepted_rows: list[dict],
) -> int:
    """Persist registry portal snapshot for accepted bag rows (confirm only)."""
    from backend.rinse_bag_completion import COMPLETION_COMPLETED
    from backend.rinse_bag_registry import get_registry_row
    from backend.rinse_bag_upload import upsert_registry_from_portal_row

    n = 0
    for row in accepted_rows:
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid:
            continue
        reg = get_registry_row(cursor, organization_id, tid)
        is_completed = (
            reg is not None
            and str(reg.get("completion_status") or "").upper() == COMPLETION_COMPLETED
        )
        dc = row.get("date_clean")
        if isinstance(dc, datetime):
            row_date = dc.date()
        elif isinstance(dc, date):
            row_date = dc
        else:
            row_date = dc
        upsert_registry_from_portal_row(
            cursor,
            organization_id,
            upload_batch_id,
            ticket_id=tid,
            name_clean=str(row.get("name_clean") or ""),
            weight_num=row.get("weight_num"),
            service_type=str(row.get("service_type") or ""),
            date_clean=row_date,
            rush_type=str(row.get("rush_type") or "NON-RUSH"),
            is_completed=is_completed,
        )
        # Events CSV never carries Weight. Portal weight_num (incl. 0) must be
        # re-attached after every confirm merge, including HD rows — otherwise
        # replace_existing scan imports wipe prior weight_lbs and leave nulls.
        # attach_portal_weight_to_latest_eligible attaches to the chronologically
        # latest eligible weight-entry that is still null (never re-attributing a
        # later/current value onto an earlier scan), and records provenance
        # (weight_observed_at/weight_source/weight_attach_batch_id/reason).
        from backend.rinse_scan_weight_enrichment import attach_portal_weight_to_latest_eligible
        from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

        lbs = normalize_scan_weight_lbs(row.get("weight_num"))
        if lbs is not None:
            portal_observed_at = row.get("confirmed_at")
            if not isinstance(portal_observed_at, datetime):
                portal_observed_at = datetime.utcnow()
            attach_portal_weight_to_latest_eligible(
                cursor,
                organization_id,
                tid,
                weight_lbs=lbs,
                portal_observed_at=portal_observed_at,
                upload_batch_id=upload_batch_id,
                selected_date_et=row_date if isinstance(row_date, date) else None,
            )
        n += 1
    return n


def _union_normalized_bag_ids(*groups: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        if not group:
            continue
        for raw in group:
            bid = normalize_bag_id(raw)
            if bid and bid not in seen:
                seen.add(bid)
                out.append(bid)
    return sorted(out)


def count_clean_rack_completed_bags(completion_payload: dict[str, Any]) -> int:
    """Bags marked COMPLETED with CLEAN_RACK_SCANNED after this confirm's recompute."""
    bags = list(completion_payload.get("bags") or [])
    return sum(
        1
        for b in bags
        if str(b.get("completion_status") or "").upper() == COMPLETION_COMPLETED
        and str(b.get("completion_reason") or "") == REASON_CLEAN_RACK_SCANNED
    )


def fetch_accepted_portal_rows_for_finalize(cursor, upload_batch_id: int) -> list[dict[str, Any]]:
    """Accepted/overridden portal rows used by confirm-time and post-lock finalize."""
    if not table_exists(cursor, "upload_batch_rows"):
        return []
    from backend.ta_helpers import table_has_column

    ticket_sql = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
    cursor.execute(
        f"""
        SELECT date_clean, name_clean, weight_num, service_type, rush_type{ticket_sql}
        FROM upload_batch_rows
        WHERE upload_batch_id = %s AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (int(upload_batch_id),),
    )
    return [row for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def summarize_confirm_batch_portal_rows(cursor, upload_batch_id: int) -> dict[str, int]:
    """Portal row counts from upload_batch_rows for confirm response."""
    if not table_exists(cursor, "upload_batch_rows"):
        return {
            "accepted_portal_rows": 0,
            "rejected_already_completed_rows": 0,
            "rejected_duplicate_rows": 0,
        }
    from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED

    cursor.execute(
        """
        SELECT
            SUM(row_status IN ('ACCEPTED', 'OVERRIDDEN')) AS accepted_portal_rows,
            SUM(
                row_status = 'REJECTED_DUPLICATE' AND reason = %s
            ) AS rejected_already_completed_rows,
            SUM(row_status = 'REJECTED_DUPLICATE') AS rejected_duplicate_rows
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        """,
        (REASON_ALREADY_COMPLETED, int(upload_batch_id)),
    )
    row = cursor.fetchone() or {}
    return {
        "accepted_portal_rows": int(row.get("accepted_portal_rows") or 0),
        "rejected_already_completed_rows": int(row.get("rejected_already_completed_rows") or 0),
        "rejected_duplicate_rows": int(row.get("rejected_duplicate_rows") or 0),
    }


def finalize_rinse_after_batch_confirm(
    cursor,
    organization_id: int,
    upload_batch_id: int,
    *,
    accepted_portal_rows: list[dict] | None = None,
    source_filename: str = "",
) -> dict[str, Any]:
    """
    Merge draft scan-events → persistent, recompute completion + folding, update registry.
    Call only from confirm_upload_batch after staging apply.

    Folding recompute runs last, only for registry-COMPLETED bags touched by this confirm.
    """
    org = int(organization_id)
    batch_id = int(upload_batch_id)
    accepted = list(accepted_portal_rows or [])

    events_df = load_upload_batch_scan_events_as_dataframe(cursor, org, batch_id)
    merge_payload: dict[str, Any] = {"bags_merged": 0, "events_inserted": 0, "bag_ids": []}
    if not events_df.empty:
        merge_payload = merge_scan_events_from_upload(
            cursor,
            org,
            batch_id,
            events_df,
            source_filename or "batch_confirm",
            replace_existing=True,
            credential_sourced=True,
        )

    from backend.rinse_portal_absence_completion import process_bags_missing_from_latest_portal

    portal_absence = process_bags_missing_from_latest_portal(
        cursor, org, batch_id, accepted
    )
    absence_bag_ids = list(portal_absence.get("rejected_bag_ids") or portal_absence.get("bag_ids") or [])
    completed_absence_ids = list(portal_absence.get("completed_bag_ids") or [])

    merge_bag_ids = list(merge_payload.get("bag_ids") or [])
    accepted_bag_ids = [
        normalize_bag_id(row.get("ticket_id"))
        for row in accepted
        if normalize_bag_id(row.get("ticket_id"))
    ]

    # Registry portal snapshot before completion so accepted bags have rows to update.
    registry_rows_updated = apply_registry_from_accepted_portal_rows(
        cursor, org, batch_id, accepted
    )

    completion_candidate_ids = _union_normalized_bag_ids(
        merge_bag_ids,
        accepted_bag_ids,
        completed_absence_ids,
    )

    completion_payload: dict[str, Any] = {"bags_recomputed": 0, "bags_completed": 0, "bags": []}
    if completion_candidate_ids:
        completion_payload = recompute_completion_for_bags(
            cursor, org, completion_candidate_ids
        )

    completion_summaries = list(completion_payload.get("bags") or [])

    from backend.rinse_folding_registry import (
        folding_recompute_summary_for_response,
        recompute_folding_after_upload,
    )

    folding_payload: dict[str, Any] = recompute_folding_after_upload(
        cursor,
        org,
        completion_candidate_ids,
        completion_summaries=completion_summaries,
    )
    folding_summary = folding_recompute_summary_for_response(folding_payload)
    newly_completed_clean_rack_count = count_clean_rack_completed_bags(completion_payload)

    return {
        "persistent_merge": merge_payload,
        "portal_absence": portal_absence,
        "completion": completion_payload,
        "registry_rows_updated": registry_rows_updated,
        "folding": folding_payload,
        "folding_summary": folding_summary,
        "bag_ids": completion_candidate_ids,
        "newly_completed_clean_rack_count": newly_completed_clean_rack_count,
        "missing_prior_bags_rejected_count": int(portal_absence.get("rejected_count") or portal_absence.get("count") or 0),
        "missing_prior_bags_completed_count": int(portal_absence.get("completed_count") or 0),
        "missing_prior_bag_ids_rejected": absence_bag_ids,
        "missing_prior_bag_ids_completed": completed_absence_ids,
        "missing_prior_bags_needs_verification_count": int(
            portal_absence.get("needs_verification_count") or 0
        ),
        "missing_prior_bag_ids_needs_verification": list(
            portal_absence.get("needs_verification_bag_ids") or []
        ),
        "full_snapshot": bool(portal_absence.get("full_snapshot")),
        **folding_summary,
    }
