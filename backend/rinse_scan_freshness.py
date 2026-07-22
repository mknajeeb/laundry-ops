"""Scan / portal data-freshness helpers for Shift Monitor Step-1."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence


def build_scan_data_freshness(
    *,
    selected_date_et: date,
    shift_last_sync_at: datetime | None,
    most_recent_persisted_scan_at: datetime | None,
    portal_last_seen_at: datetime | None = None,
    partial_portal_scrape: bool = False,
    partial_scan_scrape: bool = False,
    bags_with_stale_chronology: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Expose whether classification may be based on incomplete scan ingestion.

    A partial scrape must not silently conclude Pending from missing completion
    evidence — callers should treat status != ok as a soft safety flag.
    """
    stale_bags = sorted(
        {str(b).strip().upper() for b in (bags_with_stale_chronology or []) if str(b).strip()}
    )
    reasons: list[str] = []
    if partial_portal_scrape:
        reasons.append("partial_portal_scrape")
    if partial_scan_scrape:
        reasons.append("partial_scan_scrape")
    if stale_bags:
        reasons.append("scan_chronology_behind_portal_last_seen")

    status = "ok"
    if partial_portal_scrape or partial_scan_scrape:
        status = "incomplete_scrape"
    elif stale_bags:
        status = "scan_chronology_stale"

    return {
        "status": status,
        "selected_date_et": selected_date_et.isoformat(),
        "shift_last_sync_at": shift_last_sync_at,
        "most_recent_persisted_scan_at": most_recent_persisted_scan_at,
        "portal_last_seen_at": portal_last_seen_at,
        "partial_portal_scrape": bool(partial_portal_scrape),
        "partial_scan_scrape": bool(partial_scan_scrape),
        "stale_chronology_bag_ids": stale_bags,
        "stale_chronology_bag_count": len(stale_bags),
        "reasons": reasons,
        "trust_pending_from_missing_completion": status == "ok",
    }


def bag_scan_chronology_is_stale(
    *,
    last_scan_at: datetime | None,
    portal_last_seen_at: datetime | None,
    min_gap: timedelta = timedelta(hours=4),
) -> bool:
    """True when portal last-seen is materially later than the last persisted scan."""
    if last_scan_at is None or portal_last_seen_at is None:
        return False
    return portal_last_seen_at - last_scan_at >= min_gap


def load_last_scan_at_by_bag(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, datetime | None]:
    """Max persisted scanned_at_parsed per bag (complete chronology source)."""
    from backend.ta_helpers import table_exists

    out: dict[str, datetime | None] = {
        str(b).strip().upper(): None
        for b in bag_ids
        if str(b).strip()
    }
    ids = sorted(out.keys())
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    chunk = 200
    org = int(organization_id)
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({ph})
            GROUP BY bag_id
            """,
            (org, *part),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict):
                bid = str(r.get("bag_id") or "").strip().upper()
                out[bid] = r.get("mx")
            else:
                bid = str(r[0] or "").strip().upper()
                out[bid] = r[1]
    return out


def freshness_from_day_and_presence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    day_meta: Mapping[str, Any] | None = None,
    sample_bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build freshness payload from day record + optional bag sample."""
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    last_sync = (day_meta or {}).get("last_sync_at")
    most_recent_scan = None
    portal_last_seen = None
    stale: list[str] = []

    if table_exists(cursor, "rinse_bag_scan_events"):
        cursor.execute(
            """
            SELECT MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed < DATE_ADD(%s, INTERVAL 1 DAY)
            """,
            (org, selected_date_et, selected_date_et),
        )
        row = cursor.fetchone() or {}
        most_recent_scan = row.get("mx") if isinstance(row, dict) else (row[0] if row else None)

    ids = sorted({str(b).strip().upper() for b in (sample_bag_ids or []) if str(b).strip()})
    if ids and table_exists(cursor, "rinse_cleaner_ticket_presence"):
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, last_seen_at
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *ids),
        )
        presence = {
            str(r.get("bag_id") or "").strip().upper(): r.get("last_seen_at")
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict)
        }
        portal_last_seen = max((t for t in presence.values() if t is not None), default=None)
        cursor.execute(
            f"""
            SELECT bag_id, MAX(scanned_at_parsed) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({ph})
            GROUP BY bag_id
            """,
            (org, *ids),
        )
        for r in cursor.fetchall() or []:
            if not isinstance(r, dict):
                continue
            bid = str(r.get("bag_id") or "").strip().upper()
            if bag_scan_chronology_is_stale(
                last_scan_at=r.get("mx"),
                portal_last_seen_at=presence.get(bid),
            ):
                stale.append(bid)

    return build_scan_data_freshness(
        selected_date_et=selected_date_et,
        shift_last_sync_at=last_sync if isinstance(last_sync, datetime) else None,
        most_recent_persisted_scan_at=most_recent_scan
        if isinstance(most_recent_scan, datetime)
        else None,
        portal_last_seen_at=portal_last_seen if isinstance(portal_last_seen, datetime) else None,
        bags_with_stale_chronology=stale,
    )
