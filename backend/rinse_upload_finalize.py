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

from backend.rinse_bag_completion import evaluate_bag_completion, normalize_bag_id
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
        n += 1
    return n


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
    Call only from confirm_upload_batch (after staging apply is acceptable either order;
    completion uses persistent scans).
    """
    org = int(organization_id)
    batch_id = int(upload_batch_id)
    accepted = list(accepted_portal_rows or [])

    from backend.rinse_portal_absence_completion import complete_bags_missing_from_latest_portal

    portal_absence = complete_bags_missing_from_latest_portal(
        cursor, org, batch_id, accepted
    )
    absence_bag_ids = list(portal_absence.get("bag_ids") or [])

    events_df = load_upload_batch_scan_events_as_dataframe(cursor, org, batch_id)
    merge_payload: dict[str, Any] = {"bags_merged": 0, "events_inserted": 0, "bag_ids": []}
    if not events_df.empty:
        merge_payload = merge_scan_events_from_upload(
            cursor,
            org,
            batch_id,
            events_df,
            source_filename or "batch_confirm",
        )

    bag_ids: set[str] = set()
    for raw in merge_payload.get("bag_ids") or []:
        bid = normalize_bag_id(raw)
        if bid:
            bag_ids.add(bid)
    for row in accepted:
        bid = normalize_bag_id(row.get("ticket_id"))
        if bid:
            bag_ids.add(bid)
    bag_id_list = sorted(bag_ids)
    folding_bag_ids = sorted(set(bag_id_list) | set(absence_bag_ids))

    completion_payload: dict[str, Any] = {"bags": 0}
    if bag_id_list:
        completion_payload = recompute_completion_for_bags(cursor, org, bag_id_list)

    registry_rows_updated = apply_registry_from_accepted_portal_rows(
        cursor, org, batch_id, accepted
    )

    folding_payload: dict[str, Any] = {"ok": True, "processed": 0}
    if folding_bag_ids:
        from backend.rinse_folding_registry import recompute_folding_after_upload

        folding_payload = recompute_folding_after_upload(cursor, org, folding_bag_ids)

    return {
        "persistent_merge": merge_payload,
        "portal_absence": portal_absence,
        "completion": completion_payload,
        "registry_rows_updated": registry_rows_updated,
        "folding": folding_payload,
        "bag_ids": bag_id_list,
        "missing_prior_bags_completed_count": int(portal_absence.get("count") or 0),
        "missing_prior_bag_ids_completed": absence_bag_ids,
        "full_snapshot": bool(portal_absence.get("full_snapshot")),
    }
