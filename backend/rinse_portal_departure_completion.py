"""
Portal departure completion — bags that leave the at-vendor board are not rejections.

When a bag disappears from a full portal scrape:
  1. Recover any missing scans from upload batch history.
  2. If completion evidence exists → mark COMPLETED.
  3. If no evidence → mark needs verification (INCOMPLETE), do not reject.
  4. Only explicit cancellation signals may still reject.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    COMPLETION_REJECTED,
    REASON_COMPLETED_PORTAL_DEPARTURE,
    REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION,
    REASON_STRONG_COMPLETION_EVIDENCE,
    TRIGGER_KIND_PORTAL_DEPARTURE_COMPLETION,
    TRIGGER_KIND_PORTAL_ABSENCE_NEEDS_VERIFICATION,
    normalize_bag_id,
    order_events_for_completion,
)
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key
from backend.rinse_scan_purpose import normalize_scan_purpose
from backend.ta_helpers import table_exists

logger = logging.getLogger(__name__)

_CANCELLATION_PURPOSE_TERMS = (
    "cancel",
    "cancelled",
    "canceled",
    "lost-bag",
    "bag-lost",
)


def _purpose_indicates_cancellation(purpose: Any) -> bool:
    p = normalize_scan_purpose(purpose)
    return any(term in p for term in _CANCELLATION_PURPOSE_TERMS)


def detect_confirmed_cancellation(events: Sequence[Mapping[str, Any]]) -> bool:
    """True only when scan timeline contains an explicit cancellation signal."""
    for ev in events or []:
        if _purpose_indicates_cancellation(ev.get("purpose")):
            return True
    return False


def detect_portal_departure_completion_evidence(
    events: Sequence[Mapping[str, Any]],
    *,
    service_type: str | None = None,
) -> dict[str, Any] | None:
    """
    Return completion evidence dict when bag has a known completion signal.

    Checks strong completion evidence (v2) and WF/HD attribution rules.
    """
    from backend.rinse_bag_activity_rules import find_strong_completion_evidence_v2
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_employee_completed_bags import (
        _resolve_anchor_ts,
        resolve_completion_attribution,
    )
    from backend.rinse_folding_et import naive_et_day_end_inclusive

    timeline = gaming_events_from_records(list(events or []))
    if not timeline:
        return None

    evidence = find_strong_completion_evidence_v2(timeline)
    if evidence is not None:
        ev, ts, kind = evidence
        return {
            "kind": kind,
            "completion_at": ts,
            "employee": str(ev.get("user_name") or ev.get("user") or "").strip() or None,
            "event_id": ev.get("id"),
            "source": "strong_completion_evidence_v2",
        }

    svc = str(service_type or "").upper()
    if svc in ("WF", "HD"):
        from backend.rinse_bag_stage_bounds import event_ts, ts_valid

        anchor_dates = sorted(
            {
                event_ts(ev).date()
                for ev in timeline
                if ts_valid(event_ts(ev))
            }
        )
        for day in anchor_dates or [None]:
            anchor = _resolve_anchor_ts(timeline, day) if day else None
            if anchor is None:
                continue
            as_of = naive_et_day_end_inclusive(day)
            emp, comp_ts, sig = resolve_completion_attribution(
                service_type=svc,
                events=timeline,
                anchor_ts=anchor,
                as_of_end=as_of,
            )
            if comp_ts is not None and emp and emp != "Unknown user":
                return {
                    "kind": sig or f"{svc.lower()}-completion",
                    "completion_at": comp_ts,
                    "employee": emp,
                    "event_id": None,
                    "source": "completion_attribution",
                }

    return None


def fetch_upload_batch_scan_rows_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    up_to_batch_id: int | None = None,
) -> list[dict[str, Any]]:
    """All draft upload scan rows for a bag, newest batch first."""
    if not table_exists(cursor, "upload_batch_scan_events"):
        return []
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    org = int(organization_id)
    sql = """
        SELECT upload_batch_id, bag_id, scan_index, rack, time_scanned_raw,
               scanned_at_parsed, user_name, purpose, last_location, last_scan,
               source_filename, raw_json
        FROM upload_batch_scan_events
        WHERE organization_id = %s AND UPPER(TRIM(bag_id)) = %s
    """
    args: list[Any] = [org, bid]
    if up_to_batch_id is not None:
        sql += " AND upload_batch_id <= %s"
        args.append(int(up_to_batch_id))
    sql += " ORDER BY upload_batch_id DESC, scanned_at_parsed ASC, scan_index ASC, id ASC"
    cursor.execute(sql, tuple(args))
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def recover_missing_scans_from_upload_batch_history(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    up_to_batch_id: int | None = None,
    source_filename: str = "portal_departure_recovery",
) -> dict[str, Any]:
    """
    Insert scan rows from upload_batch_scan_events missing in rinse_bag_scan_events.

    Does not delete existing persistent rows — incremental recovery only.
    """
    from backend.rinse_bag_registry import (
        ensure_rinse_bag_registry_table,
        fetch_persistent_scan_events_for_bag,
        upsert_scan_event_row,
    )

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return {"bag_id": "", "inserted": 0, "already_present": 0, "skipped_no_time": 0}

    existing = fetch_persistent_scan_events_for_bag(cursor, org, bid)
    existing_keys: set[str] = set()
    for ev in existing:
        dk = compute_scan_event_dedupe_key(
            organization_id=org,
            bag_id=bid,
            rack=ev.get("rack"),
            user_name=ev.get("user_name"),
            purpose=ev.get("purpose"),
            time_scanned_raw=str(ev.get("time_scanned_raw") or ev.get("scanned_at_parsed") or ""),
            scanned_at_parsed=ev.get("scanned_at_parsed"),
        )
        if dk:
            existing_keys.add(dk)

    draft_rows = fetch_upload_batch_scan_rows_for_bag(
        cursor, org, bid, up_to_batch_id=up_to_batch_id
    )
    inserted = 0
    already_present = 0
    skipped_no_time = 0
    ensure_rinse_bag_registry_table(cursor)

    for row in draft_rows:
        time_raw = str(row.get("time_scanned_raw") or "").strip()
        scanned_at = row.get("scanned_at_parsed")
        if not time_raw and not scanned_at:
            skipped_no_time += 1
            continue
        if not time_raw and scanned_at is not None:
            time_raw = str(scanned_at)

        dedupe_key = compute_scan_event_dedupe_key(
            organization_id=org,
            bag_id=bid,
            rack=row.get("rack"),
            user_name=row.get("user_name"),
            purpose=row.get("purpose"),
            time_scanned_raw=time_raw,
            scanned_at_parsed=scanned_at,
        )
        if dedupe_key in existing_keys:
            already_present += 1
            continue

        raw_json = row.get("raw_json")
        if raw_json is not None and not isinstance(raw_json, str):
            raw_json = json.dumps(raw_json, default=str)

        action = upsert_scan_event_row(
            cursor,
            organization_id=org,
            bag_id=bid,
            dedupe_key=dedupe_key,
            scan_index=row.get("scan_index"),
            rack=row.get("rack"),
            time_scanned_raw=time_raw,
            scanned_at_parsed=scanned_at,
            user_name=row.get("user_name"),
            purpose=row.get("purpose"),
            last_location=row.get("last_location"),
            last_scan=row.get("last_scan"),
            source_upload_batch_id=int(row.get("upload_batch_id") or 0),
            source_filename=row.get("source_filename") or source_filename,
            raw_json=raw_json,
            credential_sourced=True,
        )
        existing_keys.add(dedupe_key)
        if action == "inserted":
            inserted += 1
        else:
            already_present += 1

    return {
        "bag_id": bid,
        "inserted": inserted,
        "already_present": already_present,
        "skipped_no_time": skipped_no_time,
        "draft_rows_seen": len(draft_rows),
    }


def mark_registry_completed_portal_departure(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    evidence: Mapping[str, Any],
    completed_at: datetime | None = None,
) -> bool:
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table, get_registry_row

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    existing = get_registry_row(cursor, org, bid)
    if existing and str(existing.get("completion_status") or "").upper() == COMPLETION_COMPLETED:
        return False

    when = completed_at or evidence.get("completion_at") or datetime.utcnow()
    kind = str(evidence.get("kind") or "portal-departure")
    trigger_kind = TRIGGER_KIND_PORTAL_DEPARTURE_COMPLETION
    event_id = evidence.get("event_id")

    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status, completion_reason,
            completed_at, trigger_kind, trigger_scan_at, trigger_scan_event_id,
            last_upload_batch_id, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            completion_status = VALUES(completion_status),
            completion_reason = VALUES(completion_reason),
            completed_at = VALUES(completed_at),
            trigger_kind = VALUES(trigger_kind),
            trigger_scan_at = VALUES(trigger_scan_at),
            trigger_scan_event_id = VALUES(trigger_scan_event_id),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_COMPLETED,
            REASON_COMPLETED_PORTAL_DEPARTURE,
            when,
            trigger_kind,
            when,
            int(event_id) if event_id is not None else None,
            int(upload_batch_id),
        ),
    )
    logger.info(
        "Marked bag %s COMPLETED (portal departure, kind=%s) org=%s batch=%s",
        bid,
        kind,
        org,
        upload_batch_id,
    )
    return True


def mark_registry_needs_verification_portal_absence(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    marked_at: datetime | None = None,
) -> bool:
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table, get_registry_row

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    existing = get_registry_row(cursor, org, bid)
    if existing:
        status = str(existing.get("completion_status") or "").upper()
        if status == COMPLETION_COMPLETED:
            return False
        if status == COMPLETION_REJECTED:
            # Clear wrongful rejection — leave incomplete pending verification.
            pass

    when = marked_at or datetime.utcnow()
    cursor.execute(
        """
        INSERT INTO rinse_bag_registry (
            organization_id, bag_id, completion_status, completion_reason,
            completed_at, trigger_kind, last_upload_batch_id, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, NULL, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            completion_status = VALUES(completion_status),
            completion_reason = VALUES(completion_reason),
            completed_at = NULL,
            trigger_kind = VALUES(trigger_kind),
            last_upload_batch_id = VALUES(last_upload_batch_id),
            updated_at = NOW()
        """,
        (
            org,
            bid,
            COMPLETION_INCOMPLETE,
            REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION,
            TRIGGER_KIND_PORTAL_ABSENCE_NEEDS_VERIFICATION,
            int(upload_batch_id),
        ),
    )
    return True


def restore_portal_scrape_rejected_bag(
    cursor,
    organization_id: int,
    bag_id: str,
) -> bool:
    """Undo a wrongful portal-scrape rejection so recovery can proceed."""
    from backend.rinse_bag_completion import REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table, get_registry_row

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    row = get_registry_row(cursor, org, bid)
    if not row:
        return False
    if str(row.get("completion_status") or "").upper() != COMPLETION_REJECTED:
        return False
    if str(row.get("completion_reason") or "").strip() != REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE:
        return False

    ensure_rinse_bag_registry_table(cursor)
    cursor.execute(
        """
        UPDATE rinse_bag_registry
        SET completion_status = %s,
            completion_reason = %s,
            completed_at = NULL,
            trigger_kind = NULL,
            updated_at = NOW()
        WHERE organization_id = %s AND bag_id = %s
        """,
        (
            COMPLETION_INCOMPLETE,
            REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION,
            org,
            bid,
        ),
    )
    return True


def verify_and_resolve_portal_departure_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    rejected_at: datetime | None = None,
    recover_scans: bool = True,
) -> dict[str, Any]:
    """
    Recovery path for a bag missing from the latest portal scrape.

    Returns dict with action: completed | needs_verification | rejected | unchanged
    """
    from backend.rinse_bag_registry import (
        fetch_persistent_scan_events_for_bag,
        get_registry_row,
        is_bag_already_completed,
    )

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return {"bag_id": "", "action": "unchanged", "reason": "invalid_bag_id"}

    if is_bag_already_completed(cursor, org, bid):
        return {"bag_id": bid, "action": "unchanged", "reason": "already_completed"}

    recovery: dict[str, Any] = {"inserted": 0}
    if recover_scans:
        recovery = recover_missing_scans_from_upload_batch_history(
            cursor, org, bid, up_to_batch_id=upload_batch_id
        )

    events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
    ordered = order_events_for_completion(events)
    reg = get_registry_row(cursor, org, bid) or {}
    service_type = reg.get("service_type")

    evidence = detect_portal_departure_completion_evidence(
        ordered, service_type=str(service_type or "")
    )
    if evidence:
        applied = mark_registry_completed_portal_departure(
            cursor,
            org,
            bid,
            upload_batch_id=upload_batch_id,
            evidence=evidence,
            completed_at=evidence.get("completion_at"),
        )
        return {
            "bag_id": bid,
            "action": "completed",
            "applied": applied,
            "evidence": evidence,
            "recovery": recovery,
        }

    if detect_confirmed_cancellation(ordered):
        from backend.rinse_bag_registry import mark_registry_rejected_portal_absence

        when = rejected_at or datetime.utcnow()
        applied = mark_registry_rejected_portal_absence(
            cursor, org, bid, upload_batch_id=upload_batch_id, rejected_at=when
        )
        return {
            "bag_id": bid,
            "action": "rejected",
            "applied": applied,
            "reason": "confirmed_cancellation",
            "recovery": recovery,
        }

    applied = mark_registry_needs_verification_portal_absence(
        cursor,
        org,
        bid,
        upload_batch_id=upload_batch_id,
        marked_at=rejected_at,
    )
    return {
        "bag_id": bid,
        "action": "needs_verification",
        "applied": applied,
        "recovery": recovery,
    }


def list_portal_scrape_rejected_bag_ids(cursor, organization_id: int) -> list[str]:
    from backend.rinse_bag_completion import REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table

    org = int(organization_id)
    ensure_rinse_bag_registry_table(cursor)
    cursor.execute(
        """
        SELECT bag_id FROM rinse_bag_registry
        WHERE organization_id = %s
          AND UPPER(COALESCE(completion_status, '')) = %s
          AND completion_reason = %s
        ORDER BY bag_id
        """,
        (org, COMPLETION_REJECTED, REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE),
    )
    out: list[str] = []
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id") if isinstance(row, dict) else row[0])
        if bid:
            out.append(bid)
    return out
