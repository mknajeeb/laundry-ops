"""Detect WF bags missing from the latest confirmed full portal CSV snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import (
    REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
    normalize_bag_id,
    rack_contains_clean,
)
from backend.rinse_bag_gaming_performance import gaming_events_from_records
from backend.rinse_bag_stage_bounds import event_ts as _event_ts, ts_valid as _ts_valid
from backend.rinse_portal_scrape_meta import (
    fetch_portal_scrape_meta_for_batch,
    portal_scrape_meta_allows_absence_completion,
)
from backend.rinse_shift_operational_exceptions import find_strong_completion_evidence
from backend.ta_helpers import table_exists, table_has_column


def _events_for_bag(
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    bag_id: str,
) -> Sequence[Mapping[str, Any]]:
    normalized = normalize_bag_id(bag_id)
    if normalized in events_by_bag:
        return events_by_bag[normalized]
    for key, events in events_by_bag.items():
        if normalize_bag_id(key) == normalized:
            return events
    return []


def _lifecycle_completion_time(
    events: Sequence[Mapping[str, Any]],
) -> datetime | None:
    """CLEAN rack time, else earliest strong completion signal."""
    timeline = gaming_events_from_records(events)
    for ev in timeline:
        if rack_contains_clean(ev.get("rack")):
            ts = _event_ts(ev)
            if _ts_valid(ts):
                return ts
    evidence = find_strong_completion_evidence(timeline)
    if evidence is None:
        return None
    _ev, ts, _kind = evidence
    return ts if _ts_valid(ts) else None


def fetch_latest_confirmed_full_portal_batch(
    cursor,
    organization_id: int,
) -> dict[str, Any] | None:
    """
    Latest confirmed upload batch that is a trustworthy full portal snapshot.

    Returns None when no batch, unconfirmed, or partial/failed scrape metadata.
    """
    if not table_exists(cursor, "upload_batches"):
        return None

    org = int(organization_id)
    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"

    org_clause = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_clause = " AND organization_id = %s"
        args.append(org)

    cursor.execute(
        f"""
        SELECT {batch_pk} AS batch_id, confirmed_at
        FROM upload_batches
        WHERE confirmed_at IS NOT NULL{org_clause}
        ORDER BY confirmed_at DESC, {batch_pk} DESC
        LIMIT 1
        """,
        tuple(args),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None

    batch_id = int(row.get("batch_id") or 0)
    confirmed_at = row.get("confirmed_at")
    if not batch_id or not isinstance(confirmed_at, datetime):
        return None

    meta = fetch_portal_scrape_meta_for_batch(cursor, batch_id, org)
    if meta is not None and not portal_scrape_meta_allows_absence_completion(meta):
        return None

    if table_has_column(cursor, "upload_batches", "full_snapshot"):
        cursor.execute(
            f"""
            SELECT full_snapshot FROM upload_batches
            WHERE {batch_pk} = %s{org_clause}
            LIMIT 1
            """,
            (batch_id, *([org] if org_clause else [])),
        )
        fs_row = cursor.fetchone()
        if isinstance(fs_row, dict) and fs_row.get("full_snapshot") is not None:
            if not int(fs_row.get("full_snapshot") or 0):
                return None

    if not table_exists(cursor, "upload_batch_rows"):
        return None

    row_batch_col = (
        "upload_batch_id"
        if table_has_column(cursor, "upload_batch_rows", "upload_batch_id")
        else "batch_id"
    )
    cursor.execute(
        f"""
        SELECT ticket_id, service_type
        FROM upload_batch_rows
        WHERE {row_batch_col} = %s
        """,
        (batch_id,),
    )
    wf_ids: set[str] = set()
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("service_type") or "WF").upper() != "WF":
            continue
        bid = normalize_bag_id(r.get("ticket_id"))
        if bid:
            wf_ids.add(bid)

    return {
        "batch_id": batch_id,
        "confirmed_at": confirmed_at,
        "wf_bag_ids": wf_ids,
        "portal_scrape_meta": meta,
    }


def _bag_in_prior_confirmed_portal_batch(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    before_confirmed_at: datetime,
    exclude_batch_id: int,
) -> bool:
    if not table_exists(cursor, "upload_batches") or not table_exists(cursor, "upload_batch_rows"):
        return False

    org = int(organization_id)
    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"

    row_batch_col = (
        "upload_batch_id"
        if table_has_column(cursor, "upload_batch_rows", "upload_batch_id")
        else "batch_id"
    )

    org_ub = ""
    org_ub_args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_ub = " AND ub.organization_id = %s"
        org_ub_args.append(org)

    cursor.execute(
        f"""
        SELECT 1 AS ok
        FROM upload_batch_rows ubr
        INNER JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}
        WHERE ub.confirmed_at IS NOT NULL
          AND ubr.ticket_id = %s
          AND ub.{batch_pk} != %s
          AND ub.confirmed_at <= %s
          {org_ub}
        LIMIT 1
        """,
        (bag_id, int(exclude_batch_id), before_confirmed_at, *org_ub_args),
    )
    return bool(cursor.fetchone())


def compute_missing_from_confirmed_portal_scrape(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, bool]:
    """
    True when bag was in a prior confirmed portal batch, has completion evidence,
    is absent from the latest confirmed full portal batch, and that batch is after completion.
    """
    latest = fetch_latest_confirmed_full_portal_batch(cursor, organization_id)
    if latest is None:
        return {}

    org = int(organization_id)
    latest_ids = latest["wf_bag_ids"]
    latest_at: datetime = latest["confirmed_at"]
    latest_batch_id: int = latest["batch_id"]
    out: dict[str, bool] = {}

    for raw_bid in bag_ids:
        bid = normalize_bag_id(raw_bid)
        if not bid:
            continue
        if bid in latest_ids:
            out[bid] = False
            continue

        completion_at = _lifecycle_completion_time(
            _events_for_bag(events_by_bag, bid)
        )
        if completion_at is None:
            out[bid] = False
            continue
        if completion_at >= latest_at:
            out[bid] = False
            continue

        if table_exists(cursor, "rinse_bag_registry"):
            cursor.execute(
                """
                SELECT completed_at, completion_reason
                FROM rinse_bag_registry
                WHERE organization_id = %s AND bag_id = %s
                LIMIT 1
                """,
                (org, bid),
            )
            reg = cursor.fetchone()
            if isinstance(reg, dict):
                reason = str(reg.get("completion_reason") or "").strip()
                reg_at = reg.get("completed_at")
                if (
                    reason == REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD
                    and isinstance(reg_at, datetime)
                    and reg_at < latest_at
                ):
                    out[bid] = True
                    continue

        if not _bag_in_prior_confirmed_portal_batch(
            cursor,
            organization_id,
            bid,
            before_confirmed_at=latest_at,
            exclude_batch_id=latest_batch_id,
        ):
            out[bid] = False
            continue
        out[bid] = True

    return out
