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
    REASON_ALREADY_COMPLETED,
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

REASON_OLDER_THAN_BATCH_DATE = "OLDER_THAN_BATCH_DATE"
# Confirm-boundary isolation: diagnostically stale portal row, rejected from admission
# so it cannot block the rest of the batch. Does not mutate OI/lifecycle.
REASON_ISOLATED_OLDER_THAN_BATCH_DATE = "ISOLATED_OLDER_THAN_BATCH_DATE"
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


def staging_row_has_sent_status(staging_row: Mapping[str, Any] | None) -> bool:
    return staging_checkout_sent_reason(staging_row) is not None


def has_checkout_log_for_staging(cursor, organization_id: int, staging_id: int) -> bool:
    """True when an explicit checkout_log row exists for this staging order."""
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "checkout_log") or staging_id is None:
        return False
    sid = int(staging_id)
    if table_has_column(cursor, "checkout_log", "organization_id"):
        cursor.execute(
            """
            SELECT 1 AS ok FROM checkout_log
            WHERE order_id = %s AND organization_id = %s
            LIMIT 1
            """,
            (sid, int(organization_id)),
        )
    else:
        cursor.execute(
            "SELECT 1 AS ok FROM checkout_log WHERE order_id = %s LIMIT 1",
            (sid,),
        )
    return bool(cursor.fetchone())


def ticket_has_checkout_log(cursor, organization_id: int, ticket_id: str) -> bool:
    """True when any staging row for this bag has an explicit checkout_log entry."""
    from backend.ta_helpers import table_exists, table_has_column

    tid = normalize_bag_id(ticket_id)
    if not tid or not table_exists(cursor, "checkout_log"):
        return False
    if not table_has_column(cursor, "orders_staging", "ticket_id"):
        return False

    org = int(organization_id)
    if table_has_column(cursor, "orders_staging", "organization_id"):
        cursor.execute(
            """
            SELECT 1 AS ok
            FROM checkout_log cl
            INNER JOIN orders_staging os ON os.id = cl.order_id
            WHERE os.ticket_id = %s AND os.organization_id = %s
            LIMIT 1
            """,
            (tid, org),
        )
    else:
        cursor.execute(
            """
            SELECT 1 AS ok
            FROM checkout_log cl
            INNER JOIN orders_staging os ON os.id = cl.order_id
            WHERE os.ticket_id = %s
            LIMIT 1
            """,
            (tid,),
        )
    return bool(cursor.fetchone())


def ticket_true_sent_out_for_checkout(
    cursor,
    organization_id: int,
    ticket_id: str,
    *,
    in_latest_vendor_batch: bool,
) -> bool:
    """
    True sent-out evidence for checkout summary/queue.

    When the bag is still in the latest confirmed vendor source (portal upload / at_vendor
    scrape), stale staging SENT/FORCE rows are ignored unless an explicit checkout_log exists.
    """
    tid = normalize_bag_id(ticket_id)
    if not tid:
        return False
    if in_latest_vendor_batch:
        return ticket_has_checkout_log(cursor, organization_id, tid)
    staging = _latest_staging_for_ticket(cursor, organization_id, tid)
    return staging_row_has_sent_status(staging)


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
    was_completed_before_upload: bool = False,
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

    if was_completed_before_upload and row_date_before_batch:
        return ROW_REJECTED, REASON_ALREADY_COMPLETED

    if row_date_before_batch:
        return "NEEDS_ATTENTION", REASON_OLDER_THAN_BATCH_DATE

    # Bag is in latest vendor upload/scrape — stale staging sent/force and rack-after-CLEAN
    # do not remove it from checkout. True sent-out is enforced via checkout_log or absence
    # from a later confirmed vendor source.

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

    from backend.rinse_bag_registry import is_bag_already_completed

    return classify_at_vendor_checkout_row(
        ticket_id=tid,
        has_active_staging=bool(has_active_staging),
        row_date_before_batch=row_date_before_batch,
        was_completed_before_upload=is_bag_already_completed(cursor, org, tid),
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
    - Manual: row in portal upload → eligible even if registry COMPLETED / rack-after-CLEAN
    Stale staging sent/force does not exclude rows still present in the vendor source.
    """
    org = int(organization_id)
    if not checkout_at_vendor_override_active(cursor, org):
        return classify_portal_upload_row(
            ticket_id=ticket_id,
            was_completed_before_upload=was_completed_before_upload,
            has_active_staging=has_active_staging,
            row_date_before_batch=row_date_before_batch,
        )

    return classify_at_vendor_checkout_row(
        ticket_id=ticket_id,
        has_active_staging=has_active_staging,
        row_date_before_batch=row_date_before_batch,
        was_completed_before_upload=was_completed_before_upload,
    )


def resolve_stale_portal_attention_rows_before_confirm(
    cursor,
    organization_id: int,
    batch_id: int,
) -> dict[str, Any]:
    """
    Completed bags still on Vendor Home often carry yesterday's EDD on today's scrape.
    Downgrade NEEDS_ATTENTION/OLDER_THAN_BATCH_DATE → REJECTED/ALREADY_COMPLETED so one
    stale portal row cannot block scan-event import for the whole batch.

    Remaining OLDER_THAN_BATCH_DATE attention (including null ticket_id, or bags whose
    *current* OI is open so is_bag_already_completed is false) are isolated as
    non-blocking rejects — they must not hold the entire batch at DRAFT.
    Does not mutate order instances or weaken is_bag_already_completed().
    """
    from backend.rinse_bag_registry import is_bag_already_completed
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    bid = int(batch_id)
    empty = {
        "resolved_count": 0,
        "resolved_bag_ids": [],
        "isolated_count": 0,
        "isolated_ticket_ids": [],
        "isolated_null_ticket_rows": 0,
    }
    if not table_exists(cursor, "upload_batch_rows"):
        return empty

    row_col = "upload_batch_id"
    if not table_has_column(cursor, "upload_batch_rows", row_col):
        row_col = "batch_id" if table_has_column(cursor, "upload_batch_rows", "batch_id") else None
    if not row_col:
        return empty

    row_pk = "id"
    if table_has_column(cursor, "upload_batch_rows", "row_id"):
        row_pk = "row_id"
    elif not table_has_column(cursor, "upload_batch_rows", "id"):
        row_pk = "row_id"

    cursor.execute(
        f"""
        SELECT {row_pk} AS row_pk, ticket_id
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND row_status = 'NEEDS_ATTENTION'
          AND reason = %s
          AND ticket_id IS NOT NULL
          AND TRIM(ticket_id) != ''
        """,
        (bid, REASON_OLDER_THAN_BATCH_DATE),
    )
    resolved: list[str] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        tid = normalize_bag_id(row.get("ticket_id"))
        row_id = row.get("row_pk")
        if not tid or row_id is None:
            continue
        if not is_bag_already_completed(cursor, org, tid):
            continue
        cursor.execute(
            f"""
            UPDATE upload_batch_rows
            SET row_status = %s, reason = %s, updated_at = NOW()
            WHERE {row_pk} = %s
            """,
            (ROW_REJECTED, REASON_ALREADY_COMPLETED, row_id),
        )
        resolved.append(tid)

    isolated = isolate_nonblocking_older_than_batch_date_attention_rows(
        cursor, organization_id, batch_id
    )
    return {
        "resolved_count": len(resolved),
        "resolved_bag_ids": sorted(set(resolved)),
        "isolated_count": int(isolated.get("isolated_count") or 0),
        "isolated_ticket_ids": list(isolated.get("isolated_ticket_ids") or []),
        "isolated_null_ticket_rows": int(isolated.get("isolated_null_ticket_rows") or 0),
    }


def isolate_nonblocking_older_than_batch_date_attention_rows(
    cursor,
    organization_id: int,
    batch_id: int,
) -> dict[str, Any]:
    """Reject residual OLDER_THAN_BATCH_DATE attention so it cannot block confirm.

    Scope: only ``NEEDS_ATTENTION`` + ``OLDER_THAN_BATCH_DATE``.
    Includes null ``ticket_id`` rows (no fabricated identity).
    Does not call or weaken ``is_bag_already_completed``.
    Does not write order instances / CW / completion.
    Other NEEDS_ATTENTION reasons remain blocking.
    """
    from backend.ta_helpers import table_exists, table_has_column

    bid = int(batch_id)
    empty = {
        "isolated_count": 0,
        "isolated_ticket_ids": [],
        "isolated_null_ticket_rows": 0,
        "isolated_row_ids": [],
    }
    if not table_exists(cursor, "upload_batch_rows"):
        return empty

    row_col = "upload_batch_id"
    if not table_has_column(cursor, "upload_batch_rows", row_col):
        row_col = "batch_id" if table_has_column(cursor, "upload_batch_rows", "batch_id") else None
    if not row_col:
        return empty

    row_pk = "id"
    if table_has_column(cursor, "upload_batch_rows", "row_id"):
        row_pk = "row_id"
    elif not table_has_column(cursor, "upload_batch_rows", "id"):
        row_pk = "row_id"

    cursor.execute(
        f"""
        SELECT {row_pk} AS row_pk, ticket_id, reason
        FROM upload_batch_rows
        WHERE {row_col} = %s
          AND row_status = 'NEEDS_ATTENTION'
          AND reason = %s
        """,
        (bid, REASON_OLDER_THAN_BATCH_DATE),
    )
    isolated_tickets: list[str] = []
    isolated_null = 0
    isolated_ids: list[Any] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        row_id = row.get("row_pk")
        if row_id is None:
            continue
        tid = normalize_bag_id(row.get("ticket_id"))
        cursor.execute(
            f"""
            UPDATE upload_batch_rows
            SET row_status = %s, reason = %s, updated_at = NOW()
            WHERE {row_pk} = %s
              AND row_status = 'NEEDS_ATTENTION'
              AND reason = %s
            """,
            (
                ROW_REJECTED,
                REASON_ISOLATED_OLDER_THAN_BATCH_DATE,
                row_id,
                REASON_OLDER_THAN_BATCH_DATE,
            ),
        )
        isolated_ids.append(row_id)
        if tid:
            isolated_tickets.append(tid)
        else:
            isolated_null += 1

    return {
        "isolated_count": len(isolated_ids),
        "isolated_ticket_ids": sorted(set(isolated_tickets)),
        "isolated_null_ticket_rows": isolated_null,
        "isolated_row_ids": isolated_ids,
    }


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
        old_status = str(row.get("row_status") or "")
        old_reason = str(row.get("reason") or "")
        # Confirm-boundary isolation must stick: do not revive OLDER_THAN attention.
        if old_reason == REASON_ISOLATED_OLDER_THAN_BATCH_DATE:
            continue
        eff_status, eff_reason = effective_checkout_row_status(
            cursor,
            org,
            {**row, "batch_date": batch_date},
            has_active_staging=False,
            is_auto_scrape=is_auto,
        )
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


def repair_spurious_active_staging_after_checkout(
    cursor,
    organization_id: int,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Close duplicate AT_WASHPRO/PENDING staging rows when the same bag_id already has checkout_log.

    Scheduled scrapes can insert a fresh staging row after checkout; checkout_log is keyed by
    staging order_id, so the new row bypasses sent-out detection until repaired.
    """
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    if not table_exists(cursor, "checkout_log") or not table_has_column(
        cursor, "orders_staging", "ticket_id"
    ):
        return {"closed": 0, "dry_run": dry_run}

    has_org = table_has_column(cursor, "orders_staging", "organization_id")
    org_where = " AND os.organization_id = %s" if has_org else ""
    org_join = " AND os2.organization_id = os.organization_id" if has_org else ""
    args: list[int] = [org] if has_org else []

    cursor.execute(
        f"""
        SELECT os.id, os.ticket_id
        FROM orders_staging os
        WHERE os.ticket_id IS NOT NULL AND TRIM(os.ticket_id) != ''
          AND COALESCE(os.logistics_status, 'AT_WASHPRO') = 'AT_WASHPRO'
          AND COALESCE(os.status, 'PENDING') NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')
          {org_where}
          AND EXISTS (
            SELECT 1
            FROM checkout_log cl
            INNER JOIN orders_staging os2 ON os2.id = cl.order_id
            WHERE os2.ticket_id = os.ticket_id{org_join}
          )
        """,
        tuple(args),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    closed = 0
    for row in rows:
        closed += 1
        if dry_run:
            continue
        sid = int(row["id"])
        set_parts = []
        if table_has_column(cursor, "orders_staging", "logistics_status"):
            set_parts.append("logistics_status = 'SENT_TO_RINSE'")
        if table_has_column(cursor, "orders_staging", "status"):
            set_parts.append("status = 'CHECKED_OUT'")
        if not set_parts:
            continue
        sql = f"UPDATE orders_staging SET {', '.join(set_parts)} WHERE id = %s"
        upd_args: list[int] = [sid]
        if has_org:
            sql += " AND organization_id = %s"
            upd_args.append(org)
        cursor.execute(sql, tuple(upd_args))

    return {"closed": closed, "dry_run": dry_run}


reclassify_manual_batch_upload_rows = reclassify_checkout_batch_upload_rows
