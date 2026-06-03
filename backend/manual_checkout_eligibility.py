"""
Checkout queue eligibility only — does not alter lifecycle, folding, or performance.

Core rule: completed ≠ checked out. Bags still at vendor (portal/scrape) belong in Checkout
until sent-out evidence exists.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from backend.manual_checkout_settings import (
    checkout_at_vendor_override_active,
    get_checkout_include_completed_if_at_vendor,
)
from backend.rinse_bag_completion import (
    REASON_OK,
    REASON_RACK_SCAN_AFTER_CLEAN,
    REASON_UPDATED_EXISTING_BAG,
    ROW_ACCEPTED,
    ROW_REJECTED,
    classify_portal_upload_row,
    events_from_records,
    normalize_bag_id,
    order_events_for_completion,
    rack_contains_clean,
    _progressive_timeline_sort_key,
)
from backend.rinse_scan_purpose import (
    is_inbound_cycle_reset_purpose,
    is_rack_location_movement_purpose,
)

REASON_RACK_SCAN_AFTER_CLEAN_LABEL = "Rack scan after CLEAN"
REASON_ALREADY_SENT_TO_RINSE = "ALREADY_SENT_TO_RINSE"
REASON_ALREADY_FORCE_CHECKOUT = "ALREADY_FORCE_CHECKOUT"


def _is_real_non_clean_rack(rack: Any) -> bool:
    raw = str(rack or "").strip()
    if not raw or raw.lower() in {"none", "null", "(none)"}:
        return False
    return not rack_contains_clean(rack)


def find_rack_scan_after_clean_trigger(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """
    Return the first post-CLEAN rack movement that triggers checkout exclusion, if any.

    Uses last chronological CLEAN rack as anchor. Inbound load-in / sent-to-vendor with a
    non-CLEAN rack after that anchor starts a new cycle and clears the stale CLEAN anchor.
    """
    ordered = order_events_for_completion(events)
    last_clean_ev: dict[str, Any] | None = None
    last_clean_idx = -1
    for i, ev in enumerate(ordered):
        if rack_contains_clean(ev.get("rack")):
            last_clean_ev = ev
            last_clean_idx = i

    if last_clean_ev is None or last_clean_idx < 0:
        return None

    clean_key = _progressive_timeline_sort_key(last_clean_ev)

    for ev in ordered[last_clean_idx + 1 :]:
        if _progressive_timeline_sort_key(ev) <= clean_key:
            continue
        if is_inbound_cycle_reset_purpose(ev.get("purpose")) and _is_real_non_clean_rack(
            ev.get("rack")
        ):
            return None

    for ev in ordered[last_clean_idx + 1 :]:
        if _progressive_timeline_sort_key(ev) <= clean_key:
            continue
        if is_rack_location_movement_purpose(ev.get("purpose")) and _is_real_non_clean_rack(
            ev.get("rack")
        ):
            return dict(ev)
    return None


def bag_has_rack_scan_after_clean(events: Sequence[Mapping[str, Any]]) -> bool:
    """Non-CLEAN rack movement strictly after the last valid CLEAN rack (Washpro manual only)."""
    return find_rack_scan_after_clean_trigger(events) is not None


def staging_checkout_sent_reason(staging_row: Mapping[str, Any] | None) -> str | None:
    """Checkout-scoped sent/force reason from latest staging row."""
    if not staging_row or not isinstance(staging_row, dict):
        return None
    logistics = str(staging_row.get("logistics_status") or "").strip().upper()
    status = str(staging_row.get("status") or "").strip().upper()
    if logistics == "FORCE_CHECKOUT" or status in ("FORCED_CHECKOUT", "FORCE_CHECKOUT"):
        return REASON_ALREADY_FORCE_CHECKOUT
    if logistics in ("SENT_TO_RINSE", "CHECKED_OUT") or status in ("CHECKED_OUT", "SENT_TO_RINSE"):
        return REASON_ALREADY_SENT_TO_RINSE
    return None


def events_for_bag_from_events_df(events_df: pd.DataFrame | None, bag_id: str) -> list[dict[str, Any]]:
    bid = normalize_bag_id(bag_id)
    if not bid or events_df is None or events_df.empty:
        return []
    if "Bag ID" not in events_df.columns:
        return []
    subset = events_df[events_df["Bag ID"].astype(str).map(normalize_bag_id) == bid]
    if subset.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in subset.iterrows():
        records.append(
            {
                "rack": row.get("Rack"),
                "user_name": row.get("User"),
                "scanned_at_parsed": row.get("scanned_at_parsed"),
                "scan_index": row.get("Scan Index"),
                "purpose": row.get("Purpose"),
            }
        )
    return events_from_records(records)


def load_bag_scan_timeline(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    pending_events_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    from backend.rinse_bag_registry import fetch_persistent_scan_events_for_bag

    events = list(fetch_persistent_scan_events_for_bag(cursor, int(organization_id), bag_id))
    events.extend(events_for_bag_from_events_df(pending_events_df, bag_id))
    return events


def _latest_staging_for_ticket(cursor, organization_id: int, ticket_id: str) -> dict | None:
    from backend.rinse_bag_upload import find_staging_by_ticket_id
    from backend.ta_helpers import table_has_column

    org = int(organization_id)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_ticket = table_has_column(cursor, "orders_staging", "ticket_id")
    if not has_ticket:
        return None
    return find_staging_by_ticket_id(
        cursor, org, ticket_id, has_staging_org=has_staging_org, has_ticket_id_col=True
    )


def classify_at_vendor_checkout_row(
    *,
    ticket_id: str | None,
    has_active_staging: bool,
    row_date_before_batch: bool,
    staging_sent_reason: str | None = None,
    has_rack_scan_after_clean: bool = False,
    apply_rack_after_clean_rule: bool = False,
) -> tuple[str, str]:
    """
    Checkout upload row when bag is still at vendor (manual portal or auto scrape).

    apply_rack_after_clean_rule: Washpro manual only — not used for VeeWash auto scrape.
    """
    tid = normalize_bag_id(ticket_id)
    if not tid:
        raise ValueError("classify_at_vendor_checkout_row requires ticket_id")

    if row_date_before_batch:
        return "NEEDS_ATTENTION", "OLDER_THAN_BATCH_DATE"

    if staging_sent_reason:
        return ROW_REJECTED, staging_sent_reason

    if apply_rack_after_clean_rule and has_rack_scan_after_clean:
        return ROW_REJECTED, REASON_RACK_SCAN_AFTER_CLEAN

    if has_active_staging:
        return ROW_ACCEPTED, REASON_UPDATED_EXISTING_BAG

    return ROW_ACCEPTED, REASON_OK


def effective_checkout_row_status(
    cursor,
    organization_id: int,
    row: Mapping[str, Any],
    *,
    pending_events_df: pd.DataFrame | None = None,
    has_active_staging: bool | None = None,
    is_auto_scrape: bool = False,
) -> tuple[str, str]:
    """Re-evaluate portal row for checkout batch summary when at-vendor override is active."""
    tid = normalize_bag_id(row.get("ticket_id"))
    if not tid:
        return str(row.get("row_status") or ""), str(row.get("reason") or "")

    org = int(organization_id)
    if not checkout_at_vendor_override_active(cursor, org):
        return str(row.get("row_status") or ""), str(row.get("reason") or "")

    batch_date = row.get("batch_date")
    date_clean = row.get("date_clean")
    row_date_before_batch = False
    if batch_date is not None and date_clean is not None:
        try:
            bd = batch_date.date() if hasattr(batch_date, "date") and callable(batch_date.date) else batch_date
            dc = date_clean.date() if hasattr(date_clean, "date") and callable(date_clean.date) else date_clean
            row_date_before_batch = dc < bd
        except Exception:
            row_date_before_batch = False

    latest_staging = _latest_staging_for_ticket(cursor, org, tid)
    sent_reason = None
    if not is_auto_scrape:
        sent_reason = staging_checkout_sent_reason(latest_staging)

    rack_after = False
    apply_rack = not is_auto_scrape
    if apply_rack:
        events = load_bag_scan_timeline(cursor, org, tid, pending_events_df=pending_events_df)
        rack_after = bag_has_rack_scan_after_clean(events)

    return classify_at_vendor_checkout_row(
        ticket_id=tid,
        has_active_staging=bool(has_active_staging),
        row_date_before_batch=row_date_before_batch,
        staging_sent_reason=sent_reason,
        has_rack_scan_after_clean=rack_after,
        apply_rack_after_clean_rule=apply_rack,
    )


def classify_upload_row_for_checkout(
    cursor,
    organization_id: int,
    *,
    ticket_id: str,
    has_active_staging: bool,
    row_date_before_batch: bool,
    was_completed_before_upload: bool,
    pending_events_df: pd.DataFrame | None = None,
    is_auto_scrape: bool = False,
) -> tuple[str, str]:
    """
    Upload row classification for checkout staging only.

    When checkout_include_completed_if_at_vendor is on:
    - Auto scrape: row in at_vendor scrape → eligible even if registry COMPLETED
    - Manual: row in portal upload → eligible unless sent or rack-after-CLEAN
    """
    org = int(organization_id)
    if not checkout_at_vendor_override_active(cursor, org):
        return classify_portal_upload_row(
            ticket_id=ticket_id,
            was_completed_before_upload=was_completed_before_upload,
            has_active_staging=has_active_staging,
            row_date_before_batch=row_date_before_batch,
        )

    latest = _latest_staging_for_ticket(cursor, org, ticket_id)
    sent_reason = None
    if not is_auto_scrape:
        sent_reason = staging_checkout_sent_reason(latest)

    rack_after = False
    apply_rack = not is_auto_scrape
    if apply_rack:
        timeline = load_bag_scan_timeline(cursor, org, ticket_id, pending_events_df=pending_events_df)
        rack_after = bag_has_rack_scan_after_clean(timeline)

    return classify_at_vendor_checkout_row(
        ticket_id=ticket_id,
        has_active_staging=has_active_staging,
        row_date_before_batch=row_date_before_batch,
        staging_sent_reason=sent_reason,
        has_rack_scan_after_clean=rack_after,
        apply_rack_after_clean_rule=apply_rack,
    )


# Back-compat aliases
classify_washpro_manual_checkout_row = classify_at_vendor_checkout_row
effective_washpro_manual_checkout_row_status = effective_checkout_row_status
classify_manual_portal_upload_row = classify_at_vendor_checkout_row
effective_manual_upload_row_status = effective_checkout_row_status


def reclassify_checkout_batch_upload_rows(
    cursor,
    organization_id: int,
    batch_id: int,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Update upload_batch_rows to at-vendor checkout rules (manual + auto scrape)."""
    from backend.checkout_batch_source import upload_batch_is_auto_scrape
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    bid = int(batch_id)
    is_auto = upload_batch_is_auto_scrape(cursor, bid, org)
    if not get_checkout_include_completed_if_at_vendor(cursor, org):
        return {"updated": 0, "accepted": 0, "rejected": 0, "dry_run": dry_run}

    row_col = None
    for col in ("upload_batch_id", "batch_id"):
        if table_has_column(cursor, "upload_batch_rows", col):
            row_col = col
            break
    if not row_col or not table_exists(cursor, "upload_batch_rows"):
        return {"updated": 0, "accepted": 0, "rejected": 0, "dry_run": dry_run}

    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"
    cursor.execute(
        f"SELECT batch_date FROM upload_batches WHERE {batch_pk} = %s",
        (bid,),
    )
    batch = cursor.fetchone()
    batch_date = batch.get("batch_date") if isinstance(batch, dict) else None

    row_pk = "id"
    if table_has_column(cursor, "upload_batch_rows", "row_id"):
        row_pk = "row_id"
    elif not table_has_column(cursor, "upload_batch_rows", "id"):
        row_pk = "row_id"

    cursor.execute(
        f"""
        SELECT id, ticket_id, date_clean, row_status, reason
        FROM upload_batch_rows
        WHERE {row_col} = %s AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        """,
        (bid,),
    )
    rows = cursor.fetchall() or []

    updated = accepted = rejected = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid:
            continue
        row_id = row.get(row_pk) or row.get("id") or row.get("row_id")
        if row_id is None:
            continue
        eff_status, eff_reason = effective_checkout_row_status(
            cursor,
            org,
            {**row, "batch_date": batch_date},
            has_active_staging=False,
            is_auto_scrape=is_auto,
        )
        old_status = str(row.get("row_status") or "")
        old_reason = str(row.get("reason") or "")
        if eff_status == old_status and eff_reason == old_reason:
            continue
        updated += 1
        if eff_status == ROW_ACCEPTED:
            accepted += 1
        elif eff_status == ROW_REJECTED:
            rejected += 1
        if not dry_run:
            cursor.execute(
                f"""
                UPDATE upload_batch_rows
                SET row_status = %s, reason = %s, updated_at = NOW()
                WHERE {row_pk} = %s
                """,
                (eff_status, eff_reason, row_id),
            )

    return {
        "updated": updated,
        "accepted": accepted,
        "rejected": rejected,
        "dry_run": dry_run,
        "is_auto_scrape": is_auto,
    }


reclassify_manual_batch_upload_rows = reclassify_checkout_batch_upload_rows
