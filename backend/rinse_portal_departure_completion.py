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


def fetch_upload_batch_scan_rows_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    up_to_batch_id: int | None = None,
    include_raw_json: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Batch draft upload scan rows for many bags (same columns/order as single-bag)."""
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in ids}
    if not ids or not table_exists(cursor, "upload_batch_scan_events"):
        return out
    org = int(organization_id)
    cols = (
        "upload_batch_id, bag_id, scan_index, rack, time_scanned_raw, "
        "scanned_at_parsed, user_name, purpose, last_location, last_scan, "
        "source_filename"
    )
    if include_raw_json:
        cols += ", raw_json"
    # Always select id so callers can hydrate raw_json for missing rows only.
    cols = "id, " + cols
    chunk = 100
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        sql = f"""
            SELECT {cols}
            FROM upload_batch_scan_events
            WHERE organization_id = %s AND UPPER(TRIM(bag_id)) IN ({ph})
        """
        args: list[Any] = [org, *part]
        if up_to_batch_id is not None:
            sql += " AND upload_batch_id <= %s"
            args.append(int(up_to_batch_id))
        sql += " ORDER BY bag_id ASC, upload_batch_id DESC, scanned_at_parsed ASC, scan_index ASC, id ASC"
        cursor.execute(sql, tuple(args))
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if bid:
                out.setdefault(bid, []).append(dict(row))
    return out


def fetch_draft_scan_rows_missing_from_persistent(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    up_to_batch_id: int | None = None,
    existing_events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """
    Draft rows required for portal-absence scan recovery only.

    Loads lightweight draft columns (no raw_json), keeps only rows whose dedupe
    key is absent from persistent events, then hydrates raw_json for those ids.
    Business outcomes unchanged: recovery still inserts exactly the missing
    scans; bags with nothing missing get an empty draft list (stable skip path).
    """
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    stats = {
        "draft_rows_examined": 0,
        "draft_rows_missing": 0,
        "bags_with_missing_drafts": 0,
    }
    empty: dict[str, list[dict[str, Any]]] = {bid: [] for bid in ids}
    if not ids:
        return empty, stats

    org = int(organization_id)
    existing_by_bag = existing_events_by_bag or {}
    existing_keys_by_bag: dict[str, set[str]] = {}
    for bid in ids:
        keys: set[str] = set()
        for ev in existing_by_bag.get(bid) or []:
            dk = str(ev.get("dedupe_key") or "").strip()
            if not dk:
                try:
                    dk = compute_scan_event_dedupe_key(
                        organization_id=org,
                        bag_id=bid,
                        rack=ev.get("rack"),
                        user_name=ev.get("user_name"),
                        purpose=ev.get("purpose"),
                        time_scanned_raw=str(
                            ev.get("time_scanned_raw") or ev.get("scanned_at_parsed") or ""
                        ),
                        scanned_at_parsed=ev.get("scanned_at_parsed"),
                    )
                except ValueError:
                    continue
            if dk:
                keys.add(dk)
        existing_keys_by_bag[bid] = keys

    light = fetch_upload_batch_scan_rows_for_bags(
        cursor,
        org,
        ids,
        up_to_batch_id=up_to_batch_id,
        include_raw_json=False,
    )
    missing_ids: list[int] = []
    missing_by_bag: dict[str, list[dict[str, Any]]] = {bid: [] for bid in ids}
    examined = 0
    for bid, rows in light.items():
        keys = existing_keys_by_bag.get(bid) or set()
        for row in rows:
            examined += 1
            time_raw = str(row.get("time_scanned_raw") or "").strip()
            scanned_at = row.get("scanned_at_parsed")
            if not time_raw and not scanned_at:
                continue
            if not time_raw and scanned_at is not None:
                time_raw = str(scanned_at)
            try:
                # Match recover_missing_scans_from_preloaded / _recovery_would_insert
                # identity fields exactly (no last_location).
                dedupe_key = compute_scan_event_dedupe_key(
                    organization_id=org,
                    bag_id=bid,
                    rack=row.get("rack"),
                    user_name=row.get("user_name"),
                    purpose=row.get("purpose"),
                    time_scanned_raw=time_raw,
                    scanned_at_parsed=scanned_at,
                )
            except ValueError:
                continue
            if dedupe_key in keys:
                continue
            rid = row.get("id")
            if rid is not None:
                missing_ids.append(int(rid))
            missing_by_bag.setdefault(bid, []).append(row)

    stats["draft_rows_examined"] = examined
    stats["draft_rows_missing"] = len(missing_ids)
    stats["bags_with_missing_drafts"] = sum(
        1 for bid in ids if missing_by_bag.get(bid)
    )

    if not missing_ids:
        return missing_by_bag, stats

    # Hydrate raw_json (and full columns) only for rows that can insert.
    raw_by_id: dict[int, dict[str, Any]] = {}
    chunk = 200
    for i in range(0, len(missing_ids), chunk):
        part = missing_ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT id, upload_batch_id, bag_id, scan_index, rack, time_scanned_raw,
                   scanned_at_parsed, user_name, purpose, last_location, last_scan,
                   source_filename, raw_json
            FROM upload_batch_scan_events
            WHERE organization_id = %s AND id IN ({ph})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("id") is not None:
                raw_by_id[int(row["id"])] = dict(row)

    hydrated: dict[str, list[dict[str, Any]]] = {bid: [] for bid in ids}
    for bid, rows in missing_by_bag.items():
        for row in rows:
            rid = row.get("id")
            full = raw_by_id.get(int(rid)) if rid is not None else None
            hydrated.setdefault(bid, []).append(full or row)
    return hydrated, stats


def recover_missing_scans_from_preloaded(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    existing_events: Sequence[Mapping[str, Any]],
    draft_rows: Sequence[Mapping[str, Any]],
    source_filename: str = "portal_departure_recovery",
) -> dict[str, Any]:
    """Same recovery semantics as upload-history recovery, using preloaded rows."""
    from backend.rinse_bag_registry import (
        ensure_rinse_bag_registry_table,
        ensure_rinse_bag_scan_events_dedupe_schema,
        ensure_rinse_bag_scan_events_table,
        upsert_scan_event_row,
    )
    from backend.rinse_scan_weight_enrichment import ensure_scan_weight_enrichment_columns
    from backend.rinse_workload_bag_weight import ensure_scan_events_weight_lbs_column

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return {"bag_id": "", "inserted": 0, "already_present": 0, "skipped_no_time": 0}

    existing_keys: set[str] = set()
    for ev in existing_events or []:
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

    inserted = 0
    already_present = 0
    skipped_no_time = 0
    ensure_rinse_bag_registry_table(cursor)
    ensure_rinse_bag_scan_events_table(cursor)
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    ensure_scan_events_weight_lbs_column(cursor)
    ensure_scan_weight_enrichment_columns(cursor)

    for row in draft_rows or []:
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
            schema_ready=True,
            owner_checked=True,
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
        "draft_rows_seen": len(list(draft_rows or [])),
    }


def _stable_portal_absence_needs_verification(reg: Mapping[str, Any] | None) -> bool:
    """True when registry already encodes the portal-absence verify outcome."""
    if not reg:
        return False
    status = str(reg.get("completion_status") or "").upper()
    reason = str(reg.get("completion_reason") or "").strip()
    trigger = str(reg.get("trigger_kind") or "").strip()
    return (
        status == COMPLETION_INCOMPLETE
        and reason == REASON_PORTAL_ABSENCE_NEEDS_VERIFICATION
        and trigger == TRIGGER_KIND_PORTAL_ABSENCE_NEEDS_VERIFICATION
    )


def _recovery_would_insert(
    organization_id: int,
    bag_id: str,
    *,
    existing_events: Sequence[Mapping[str, Any]],
    draft_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """True when at least one draft scan is missing from persistent keys."""
    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return False
    existing_keys: set[str] = set()
    for ev in existing_events or []:
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
    for row in draft_rows or []:
        time_raw = str(row.get("time_scanned_raw") or "").strip()
        scanned_at = row.get("scanned_at_parsed")
        if not time_raw and not scanned_at:
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
        if dedupe_key and dedupe_key not in existing_keys:
            return True
    return False


def verify_and_resolve_portal_departure_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    upload_batch_id: int,
    rejected_at: datetime | None = None,
    recover_scans: bool = True,
    preloaded_registry: Mapping[str, Any] | None = None,
    preloaded_events: Sequence[Mapping[str, Any]] | None = None,
    preloaded_draft_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Recovery path for a bag missing from the latest portal scrape.

    Returns dict with action: completed | needs_verification | rejected | unchanged

    Optional preloaded_* reuse batch-loaded state within one finalize pass.
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

    reg = dict(preloaded_registry) if preloaded_registry is not None else None
    if reg is None:
        if is_bag_already_completed(cursor, org, bid):
            return {"bag_id": bid, "action": "unchanged", "reason": "already_completed"}
        reg = get_registry_row(cursor, org, bid) or {}
    else:
        if str(reg.get("completion_status") or "").upper() == COMPLETION_COMPLETED:
            return {"bag_id": bid, "action": "unchanged", "reason": "already_completed"}

    events = list(preloaded_events) if preloaded_events is not None else None
    draft_rows = list(preloaded_draft_rows) if preloaded_draft_rows is not None else None

    # Stable skip: already marked needs_verification and no new scan recovery possible
    # and in-memory evidence still cannot complete/cancel → cheap batch-id touch only.
    if (
        recover_scans
        and events is not None
        and draft_rows is not None
        and _stable_portal_absence_needs_verification(reg)
        and not _recovery_would_insert(org, bid, existing_events=events, draft_rows=draft_rows)
    ):
        ordered = order_events_for_completion(events)
        evidence = detect_portal_departure_completion_evidence(
            ordered, service_type=str(reg.get("service_type") or "")
        )
        if not evidence and not detect_confirmed_cancellation(ordered):
            from backend.rinse_bag_registry import ensure_rinse_bag_registry_table

            ensure_rinse_bag_registry_table(cursor)
            cursor.execute(
                """
                UPDATE rinse_bag_registry
                SET last_upload_batch_id = %s, updated_at = NOW()
                WHERE organization_id = %s AND bag_id = %s
                """,
                (int(upload_batch_id), org, bid),
            )
            return {
                "bag_id": bid,
                "action": "needs_verification",
                "applied": True,
                "recovery": {
                    "bag_id": bid,
                    "inserted": 0,
                    "already_present": 0,
                    "skipped_no_time": 0,
                    "draft_rows_seen": len(draft_rows),
                    "stable_skip": True,
                },
            }

    recovery: dict[str, Any] = {"inserted": 0}
    if recover_scans:
        if events is not None and draft_rows is not None:
            recovery = recover_missing_scans_from_preloaded(
                cursor,
                org,
                bid,
                existing_events=events,
                draft_rows=draft_rows,
            )
            if int(recovery.get("inserted") or 0) > 0:
                # Reload after inserts so evidence sees recovered scans.
                events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
        else:
            recovery = recover_missing_scans_from_upload_batch_history(
                cursor, org, bid, up_to_batch_id=upload_batch_id
            )
            events = None

    if events is None:
        events = fetch_persistent_scan_events_for_bag(cursor, org, bid)
    ordered = order_events_for_completion(events)
    if preloaded_registry is None:
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
    from backend.rinse_bag_registry import fetch_persistent_scan_events_for_bag

    bid = normalize_bag_id(bag_id)
    org = int(organization_id)
    if not bid:
        return {"bag_id": "", "inserted": 0, "already_present": 0, "skipped_no_time": 0}

    existing = fetch_persistent_scan_events_for_bag(cursor, org, bid)
    draft_rows = fetch_upload_batch_scan_rows_for_bag(
        cursor, org, bid, up_to_batch_id=up_to_batch_id
    )
    return recover_missing_scans_from_preloaded(
        cursor,
        org,
        bid,
        existing_events=existing,
        draft_rows=draft_rows,
        source_filename=source_filename,
    )


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
