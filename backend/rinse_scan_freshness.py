"""Scan / portal data-freshness helpers for Shift Monitor Step-1."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

# Presence.last_seen_at is scrape observation wall-clock, not facility scan time.
# Comparing it to MAX(scanned_at_parsed) falsely flags idle-but-present bags once
# they sit on the portal longer than this gap. Keep the helper for tests / audits
# but do not use it as the production trust signal.
DEFAULT_STALE_GAP = timedelta(hours=4)
# Pipeline lag: portal presence finished successfully but scan-event import is behind.
DEFAULT_IMPORT_LAG = timedelta(minutes=45)


def build_scan_data_freshness(
    *,
    selected_date_et: date,
    shift_last_sync_at: datetime | None,
    most_recent_persisted_scan_at: datetime | None,
    portal_last_seen_at: datetime | None = None,
    last_scan_refresh_at: datetime | None = None,
    last_portal_scrape_at: datetime | None = None,
    partial_portal_scrape: bool = False,
    partial_scan_scrape: bool = False,
    scan_import_lagging: bool = False,
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
    if scan_import_lagging:
        reasons.append("scan_import_lagging_portal_scrape")
    if stale_bags:
        reasons.append("pending_missing_scan_association")

    status = "ok"
    if partial_portal_scrape or partial_scan_scrape:
        status = "incomplete_scrape"
    elif scan_import_lagging:
        status = "scan_chronology_stale"
    elif stale_bags:
        status = "scan_chronology_stale"

    return {
        "status": status,
        "selected_date_et": selected_date_et.isoformat(),
        "shift_last_sync_at": shift_last_sync_at,
        "most_recent_persisted_scan_at": most_recent_persisted_scan_at,
        "last_scan_refresh_at": last_scan_refresh_at,
        "last_portal_scrape_at": last_portal_scrape_at,
        "portal_last_seen_at": portal_last_seen_at,
        "partial_portal_scrape": bool(partial_portal_scrape),
        "partial_scan_scrape": bool(partial_scan_scrape),
        "scan_import_lagging": bool(scan_import_lagging),
        "stale_chronology_bag_ids": stale_bags,
        "stale_chronology_bag_count": len(stale_bags),
        "portal_ahead_bag_count": len(stale_bags),
        "reasons": reasons,
        "trust_pending_from_missing_completion": status == "ok",
        "pending_trust": "trusted" if status == "ok" else "provisional",
    }


def bag_scan_chronology_is_stale(
    *,
    last_scan_at: datetime | None,
    portal_last_seen_at: datetime | None,
    min_gap: timedelta = DEFAULT_STALE_GAP,
) -> bool:
    """Legacy audit helper: portal observation wall-clock vs last facility scan.

    Do **not** use this for Pending trust. ``presence.last_seen_at`` is updated to
    scrape ``now`` on every successful observation, so idle in-process bags look
    "stale" after ``min_gap`` even when scan ingestion is healthy.
    """
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


def _max_dt(*values: datetime | None) -> datetime | None:
    present = [v for v in values if isinstance(v, datetime)]
    return max(present) if present else None


def _load_pipeline_timestamps(cursor, organization_id: int) -> dict[str, Any]:
    """Latest successful portal presence + scan-event import markers."""
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    out: dict[str, Any] = {
        "last_portal_scrape_at": None,
        "last_scan_refresh_at": None,
        "partial_portal_scrape": False,
        "partial_scan_scrape": False,
        "scan_import_lagging": False,
    }

    if table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        cursor.execute(
            """
            SELECT finished_at, status, evidence_failed_stage
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id = %s
              AND portal_status = 'at_vendor'
              AND finished_at IS NOT NULL
            ORDER BY finished_at DESC
            LIMIT 8
            """,
            (org,),
        )
        rows = list(cursor.fetchall() or [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            st = str(r.get("status") or "").strip().lower()
            if st == "success" and out["last_portal_scrape_at"] is None:
                out["last_portal_scrape_at"] = r.get("finished_at")
                break
            if st in ("partial", "incomplete"):
                # Newest finished run itself was incomplete.
                if rows and r is rows[0]:
                    out["partial_portal_scrape"] = True
                if out["last_portal_scrape_at"] is None:
                    continue
                break
            if st in ("anomalous", "failed", "error"):
                # Anomalous/failed scrapes that did not apply still leave prior success valid.
                failed_stage = str(r.get("evidence_failed_stage") or "").strip()
                if rows and r is rows[0] and not failed_stage:
                    out["partial_portal_scrape"] = True
                continue

    if table_exists(cursor, "rinse_scrape_runs"):
        cursor.execute(
            """
            SELECT finished_at, status, scan_events_count, error_message
            FROM rinse_scrape_runs
            WHERE organization_id = %s
              AND finished_at IS NOT NULL
            ORDER BY finished_at DESC
            LIMIT 12
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            if not isinstance(r, dict):
                continue
            st = str(r.get("status") or "").strip().lower()
            if st != "success":
                continue
            finished = r.get("finished_at")
            scan_n = int(r.get("scan_events_count") or 0)
            if scan_n > 0 and out["last_scan_refresh_at"] is None:
                out["last_scan_refresh_at"] = finished
            if out["last_scan_refresh_at"] is not None:
                break

    if table_exists(cursor, "rinse_bag_scan_events"):
        cursor.execute(
            """
            SELECT MAX(created_at) AS mx
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
            """,
            (org,),
        )
        row = cursor.fetchone() or {}
        created = row.get("mx") if isinstance(row, dict) else (row[0] if row else None)
        out["last_scan_refresh_at"] = _max_dt(out.get("last_scan_refresh_at"), created)

    portal_at = out.get("last_portal_scrape_at")
    scan_at = out.get("last_scan_refresh_at")
    if (
        isinstance(portal_at, datetime)
        and isinstance(scan_at, datetime)
        and portal_at - scan_at >= DEFAULT_IMPORT_LAG
    ):
        out["scan_import_lagging"] = True
    elif isinstance(portal_at, datetime) and scan_at is None:
        out["scan_import_lagging"] = True
        out["partial_scan_scrape"] = True

    return out


def freshness_from_day_and_presence(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    day_meta: Mapping[str, Any] | None = None,
    sample_bag_ids: Sequence[str] | None = None,
    pending_bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build freshness payload from day record + optional bag sample.

    Pending trust is withheld only when:
    - the latest portal scrape is partial/anomalous, or
    - scan-event import is lagging the portal scrape pipeline, or
    - pending bags are active on portal with **zero** persisted scan events
      (failed scan association).

    Idle pending/completed bags that remain on the portal after their last
    facility scan are **not** treated as chronology-stale.

    Historical selected dates are date-scoped: next-day live portal scrapes must
    never produce portal-ahead / provisional-pending warnings for a prior day.
    """
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    last_sync = (day_meta or {}).get("last_sync_at")
    most_recent_scan = None
    portal_last_seen = None
    stale: list[str] = []

    # Resolve "today" in ET without importing the heavy workload module cycle.
    try:
        from backend.rinse_veewash_workload import today_et

        is_historical = selected_date_et < today_et()
    except Exception:
        is_historical = False

    if is_historical:
        # Frozen day: evaluate only this date's stored sync + same-day scan window.
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
        same_day_portal = None
        if table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
            cursor.execute(
                """
                SELECT finished_at
                FROM rinse_cleaner_ticket_presence_runs
                WHERE organization_id = %s
                  AND portal_status = 'at_vendor'
                  AND status = 'success'
                  AND finished_at IS NOT NULL
                  AND finished_at >= %s
                  AND finished_at < DATE_ADD(%s, INTERVAL 1 DAY)
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (org, selected_date_et, selected_date_et),
            )
            row = cursor.fetchone() or {}
            same_day_portal = row.get("finished_at") if isinstance(row, dict) else (row[0] if row else None)
        return build_scan_data_freshness(
            selected_date_et=selected_date_et,
            shift_last_sync_at=last_sync if isinstance(last_sync, datetime) else None,
            most_recent_persisted_scan_at=most_recent_scan
            if isinstance(most_recent_scan, datetime)
            else None,
            portal_last_seen_at=None,
            last_scan_refresh_at=most_recent_scan
            if isinstance(most_recent_scan, datetime)
            else None,
            last_portal_scrape_at=same_day_portal
            if isinstance(same_day_portal, datetime)
            else (last_sync if isinstance(last_sync, datetime) else None),
            partial_portal_scrape=False,
            partial_scan_scrape=False,
            scan_import_lagging=False,
            bags_with_stale_chronology=[],
        )

    pipeline = _load_pipeline_timestamps(cursor, org)

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

    pending_ids = sorted(
        {
            str(b).strip().upper()
            for b in (pending_bag_ids if pending_bag_ids is not None else sample_bag_ids or [])
            if str(b).strip()
        }
    )
    sample_ids = sorted(
        {str(b).strip().upper() for b in (sample_bag_ids or []) if str(b).strip()}
    )
    presence_ids = sample_ids or pending_ids

    if presence_ids and table_exists(cursor, "rinse_cleaner_ticket_presence"):
        ph = ",".join(["%s"] * len(presence_ids))
        cursor.execute(
            f"""
            SELECT bag_id, last_seen_at, active
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *presence_ids),
        )
        presence_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
        portal_last_seen = max(
            (r.get("last_seen_at") for r in presence_rows if r.get("last_seen_at") is not None),
            default=None,
        )
        active_pending = {
            str(r.get("bag_id") or "").strip().upper()
            for r in presence_rows
            if int(r.get("active") or 0) == 1
            and str(r.get("bag_id") or "").strip().upper() in set(pending_ids)
        }
        if active_pending and table_exists(cursor, "rinse_bag_scan_events"):
            ph2 = ",".join(["%s"] * len(active_pending))
            cursor.execute(
                f"""
                SELECT DISTINCT bag_id
                FROM rinse_bag_scan_events
                WHERE organization_id = %s AND bag_id IN ({ph2})
                """,
                (org, *sorted(active_pending)),
            )
            have_scans = {
                str(r.get("bag_id") or "").strip().upper()
                for r in (cursor.fetchall() or [])
                if isinstance(r, dict)
            }
            stale = sorted(active_pending - have_scans)

    return build_scan_data_freshness(
        selected_date_et=selected_date_et,
        shift_last_sync_at=last_sync if isinstance(last_sync, datetime) else None,
        most_recent_persisted_scan_at=most_recent_scan
        if isinstance(most_recent_scan, datetime)
        else None,
        portal_last_seen_at=portal_last_seen if isinstance(portal_last_seen, datetime) else None,
        last_scan_refresh_at=pipeline.get("last_scan_refresh_at")
        if isinstance(pipeline.get("last_scan_refresh_at"), datetime)
        else None,
        last_portal_scrape_at=pipeline.get("last_portal_scrape_at")
        if isinstance(pipeline.get("last_portal_scrape_at"), datetime)
        else None,
        partial_portal_scrape=bool(pipeline.get("partial_portal_scrape")),
        partial_scan_scrape=bool(pipeline.get("partial_scan_scrape")),
        scan_import_lagging=bool(pipeline.get("scan_import_lagging")),
        bags_with_stale_chronology=stale,
    )
