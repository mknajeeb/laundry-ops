"""WF completed-bag weight: post-processing scan only, with integrity tracing."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import gaming_events_from_records, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import (
    WF_POST_PROCESSING_WEIGHT_SIGNAL,
    normalize_scan_weight_lbs,
    parse_weight_lbs_from_scan_event,
)

WEIGHT_SOURCE_POST_PROCESSING_SCAN = "post_processing_scan_weight"
WEIGHT_STATUS_RESOLVED = "resolved"
WEIGHT_STATUS_INTEGRITY_FAILURE = "integrity_failure"


def _positive_float(raw: Any) -> float | None:
    """Strictly > 0 — used for revenue / integrity positive checks only."""
    val = normalize_scan_weight_lbs(raw)
    if val is None or val <= 0:
        return None
    return val


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _on_selected_et_day(ts: datetime | None, selected_date_et: date) -> bool:
    if ts is None:
        return False
    return naive_et_day_start(selected_date_et) <= ts <= naive_et_day_end_inclusive(selected_date_et)


def _raw_json_weight_keys(raw_json: Any) -> list[str]:
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw_json, dict):
        return []
    keys = ("Weight", "weight", "# WF LBS", "WF LBS", "weight_lbs", "weight_num", "pounds", "lbs")
    return [k for k in keys if raw_json.get(k) not in (None, "", "(None)")]


def _weight_from_completion_scan_event(ev: Mapping[str, Any] | None) -> float | None:
    if not ev:
        return None
    col_lbs = normalize_scan_weight_lbs(ev.get("weight_lbs"))
    if col_lbs is not None:
        return col_lbs
    return parse_weight_lbs_from_scan_event(ev)


def _last_weight_entry_on_selected_day(
    events: Sequence[Mapping[str, Any]] | None,
    selected_date_et: date,
) -> Mapping[str, Any] | None:
    """Chronologically last weight-entry on the selected ET day (fallback attach target)."""
    best: Mapping[str, Any] | None = None
    best_ts: datetime | None = None
    for ev in events or []:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = _parse_dt(ev.get("scanned_at_parsed") or ev.get("scanned_at"))
        if not _on_selected_et_day(ts, selected_date_et):
            continue
        if best_ts is None or (ts is not None and ts >= best_ts):
            best_ts = ts
            best = ev
    return best


def trace_wf_completion_weight(
    *,
    bag_id: str,
    events: Sequence[Mapping[str, Any]] | None,
    credit_ts: datetime | None,
    anchor_ts: datetime | None,
    as_of_end: datetime | None,
    selected_date_et: date | None = None,
    portal_upload_weight: float | None = None,
) -> dict[str, Any]:
    """
    Trace post-processing weight for a completed WF bag.

    Business rule: completed WF ⇒ post-processing weight-entry scan exists with numeric lbs.
    """
    from backend.rinse_employee_completed_bags import (
        _scan_event_timestamp,
        _wf_completion_weight_event,
    )

    bid = str(bag_id or "").strip().upper()
    trace: dict[str, Any] = {
        "bag_id": bid,
        "completion_event_found": False,
        "completion_event_id": None,
        "completion_event_ts": None,
        "completion_scan_purpose": None,
        "scan_weight_lbs_column": None,
        "scan_weight_lbs_parsed": None,
        "raw_json_weight_keys": [],
        "failure_stage": None,
        "failure_detail": None,
        "portal_weight_available": normalize_scan_weight_lbs(portal_upload_weight),
        "events_count": len(events or []),
    }

    if not events:
        trace["failure_stage"] = "no_scan_events"
        trace["failure_detail"] = "No rinse_bag_scan_events rows loaded for this bag."
        return trace

    if anchor_ts is None or not ts_valid(anchor_ts):
        trace["failure_stage"] = "no_lifecycle_anchor"
        trace["failure_detail"] = "Could not resolve lifecycle anchor for the selected ET day."
        return trace

    if as_of_end is None:
        trace["failure_stage"] = "missing_as_of_end"
        trace["failure_detail"] = "Day boundary (as_of_end) not provided."
        return trace

    timeline = gaming_events_from_records(events)
    weight_ev: Mapping[str, Any] | None = None
    comp_ts: datetime | None = None

    if credit_ts is not None:
        for ev in timeline:
            if _scan_event_timestamp(ev) == credit_ts and is_weight_entry_purpose(ev.get("purpose")):
                weight_ev = ev
                comp_ts = credit_ts
                break

    if weight_ev is None:
        weight_ev, comp_ts = _wf_completion_weight_event(
            timeline,
            anchor_ts=anchor_ts,
            as_of_end=as_of_end,
        )

    if weight_ev is None or comp_ts is None:
        trace["failure_stage"] = "no_post_processing_weight_scan"
        trace["failure_detail"] = (
            "No qualifying post-processing weight-entry scan after latest processing step."
        )
        return trace

    trace["completion_event_found"] = True
    trace["completion_event_id"] = weight_ev.get("id")
    trace["completion_event_ts"] = comp_ts.isoformat() if comp_ts else None
    trace["completion_scan_purpose"] = weight_ev.get("purpose")
    trace["scan_weight_lbs_column"] = normalize_scan_weight_lbs(weight_ev.get("weight_lbs"))
    trace["scan_weight_lbs_parsed"] = _weight_from_completion_scan_event(weight_ev)
    trace["raw_json_weight_keys"] = _raw_json_weight_keys(weight_ev.get("raw_json"))

    if trace["scan_weight_lbs_parsed"] is not None:
        return trace

    trace["failure_stage"] = "scan_missing_weight_payload"
    if not trace["raw_json_weight_keys"]:
        trace["failure_detail"] = (
            "Post-processing weight-entry scan exists but carries no numeric weight. "
            "Events CSV schema (Bag ID, Time Scanned, User, Purpose) excludes Weight; "
            "weight must be attached to this scan row at portal batch confirm."
        )
    else:
        trace["failure_detail"] = (
            "Post-processing weight-entry scan raw_json has weight-like keys "
            f"{trace['raw_json_weight_keys']} but parser could not extract numeric lbs."
        )

    if trace["portal_weight_available"] is not None:
        trace["failure_detail"] = (
            f"{trace['failure_detail']} Portal upload has {trace['portal_weight_available']} lbs "
            "but it is not joined onto the completion scan event."
        )
    return trace


def resolve_wf_completion_weight_lbs(
    *,
    bag_id: str,
    events: Sequence[Mapping[str, Any]] | None,
    credit_ts: datetime | None,
    anchor_ts: datetime | None,
    as_of_end: datetime | None,
    selected_date_et: date | None = None,
    portal_upload_weight: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Resolve weight ONLY from the post-processing completion scan."""
    trace = trace_wf_completion_weight(
        bag_id=bag_id,
        events=events,
        credit_ts=credit_ts,
        anchor_ts=anchor_ts,
        as_of_end=as_of_end,
        selected_date_et=selected_date_et,
        portal_upload_weight=portal_upload_weight,
    )
    lbs = trace.get("scan_weight_lbs_parsed")
    if lbs is not None:
        return float(lbs), trace
    return None, trace


def ensure_scan_events_weight_lbs_column(cursor) -> None:
    from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
    from backend.ta_helpers import table_has_column

    ensure_rinse_bag_scan_events_table(cursor)
    if table_has_column(cursor, "rinse_bag_scan_events", "weight_lbs"):
        return
    try:
        cursor.execute(
            "ALTER TABLE rinse_bag_scan_events ADD COLUMN weight_lbs DECIMAL(10,4) NULL"
        )
    except Exception as exc:
        errno = getattr(exc, "errno", None)
        if errno != 1060 and "Duplicate column" not in str(exc):
            raise
    from backend.ta_helpers import _column_cache, _schema_lock

    with _schema_lock:
        _column_cache[("rinse_bag_scan_events", "weight_lbs")] = True


def attach_portal_weight_to_post_processing_scan(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    weight_lbs: float,
    selected_date_et: date,
    events: Sequence[Mapping[str, Any]] | None = None,
    credit_ts: datetime | None = None,
) -> dict[str, Any]:
    """
    Ingestion repair: portal list weight belongs on the post-processing scan row.

    Events CSV does not include Weight; this join writes portal weight onto the
    completion weight-entry scan so productivity / chronology reads one source.

    Fallback: when no post-processing weight-entry exists after the latest
    processing step, attach onto the last weight-entry on the selected ET day.
    """
    from backend.rinse_employee_completed_bags import _resolve_anchor_ts
    from backend.rinse_post_processing_weight_chronology import _load_scan_events_for_bags

    org = int(organization_id)
    bid = str(bag_id or "").strip().upper()
    lbs = normalize_scan_weight_lbs(weight_lbs)
    if not bid or lbs is None:
        return {"updated": False, "reason": "invalid_bag_or_weight"}

    if events is None:
        events = _load_scan_events_for_bags(cursor, org, [bid])
    as_of_end = naive_et_day_end_inclusive(selected_date_et)
    anchor = _resolve_anchor_ts(events, selected_date_et)
    trace = trace_wf_completion_weight(
        bag_id=bid,
        events=events,
        credit_ts=credit_ts,
        anchor_ts=anchor,
        as_of_end=as_of_end,
        selected_date_et=selected_date_et,
        portal_upload_weight=lbs,
    )
    scan_id = trace.get("completion_event_id")
    attach_target = "post_processing_weight_entry"
    if not scan_id:
        fallback = _last_weight_entry_on_selected_day(events, selected_date_et)
        if fallback and fallback.get("id") is not None:
            scan_id = fallback.get("id")
            attach_target = "last_weight_entry_on_day"
            trace["completion_event_found"] = True
            trace["completion_event_id"] = scan_id
            fb_ts = _parse_dt(fallback.get("scanned_at_parsed") or fallback.get("scanned_at"))
            trace["completion_event_ts"] = fb_ts.isoformat() if fb_ts else None
            trace["completion_scan_purpose"] = fallback.get("purpose")
            trace["scan_weight_lbs_column"] = normalize_scan_weight_lbs(fallback.get("weight_lbs"))
            trace["scan_weight_lbs_parsed"] = _weight_from_completion_scan_event(fallback)
            trace["raw_json_weight_keys"] = _raw_json_weight_keys(fallback.get("raw_json"))
            trace["failure_stage"] = None
            trace["failure_detail"] = None
            trace["attach_target"] = attach_target
        else:
            return {"updated": False, "reason": "no_completion_scan", "trace": trace}
    else:
        trace["attach_target"] = attach_target

    if trace.get("scan_weight_lbs_parsed") is not None:
        return {"updated": False, "reason": "scan_already_has_weight", "trace": trace}

    # Delegate schema/provenance to rinse_scan_weight_enrichment so every caller of
    # this legacy entry point also gets weight_observed_at/weight_source/
    # weight_attach_reason populated. SQL params intentionally stay (lbs, org,
    # scan_id, bid) — unchanged from the pre-enrichment version — so this remains
    # a pure additive change for existing callers/tests.
    from backend.rinse_scan_weight_enrichment import (
        WEIGHT_SOURCE_PORTAL_CURRENT,
        ensure_scan_weight_enrichment_columns,
    )

    ensure_scan_weight_enrichment_columns(cursor)
    attach_reason_literal = (
        "post_processing_weight_entry_repair"
        if attach_target == "post_processing_weight_entry"
        else "last_weight_entry_on_day_repair"
    )
    cursor.execute(
        f"""
        UPDATE rinse_bag_scan_events
        SET weight_lbs = %s,
            weight_observed_at = COALESCE(weight_observed_at, NOW()),
            weight_source = COALESCE(NULLIF(weight_source, ''), '{WEIGHT_SOURCE_PORTAL_CURRENT}'),
            weight_attach_reason = COALESCE(NULLIF(weight_attach_reason, ''), '{attach_reason_literal}'),
            updated_at = NOW()
        WHERE organization_id = %s AND id = %s AND bag_id = %s AND weight_lbs IS NULL
        """,
        (lbs, org, int(scan_id), bid),
    )
    return {
        "updated": cursor.rowcount > 0,
        "scan_event_id": scan_id,
        "weight_lbs": lbs,
        "attach_target": attach_target,
        "source_field": "portal_weight_num",
        "trace": trace,
    }


def _registry_weight_for_repair(meta: Mapping[str, Any] | None) -> float | None:
    if not meta:
        return None
    for key in ("weight_num", "post_clean_weight", "registry_weight_num", "weight_lbs"):
        lbs = _positive_float(meta.get(key))
        if lbs is not None:
            return lbs
    return None


def load_portal_upload_weights_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    selected_date_et: date,
) -> dict[str, float]:
    """Portal upload weights for selected ET day — attach onto completion scan rows only."""
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    if not ids or not hasattr(cursor, "execute"):
        return {}
    if not table_exists(cursor, "upload_batch_rows"):
        return {}
    if not table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        return {}

    out: dict[str, float] = {}
    chunk = 100
    from backend.checkout_batch_scope import _batch_pk, _row_batch_col

    row_batch_col = _row_batch_col(cursor)
    batch_pk = _batch_pk(cursor)
    org_join = ""
    org_args: tuple[Any, ...] = ()
    if row_batch_col and table_exists(cursor, "upload_batches"):
        if table_has_column(cursor, "upload_batches", "organization_id"):
            org_join = (
                f" INNER JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}"
                f" AND ub.organization_id = %s"
            )
            org_args = (org,)

    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT ubr.ticket_id, ubr.weight_num, ubr.upload_batch_id
            FROM upload_batch_rows ubr{org_join}
            WHERE ubr.ticket_id IN ({ph})
              AND ubr.date_clean = %s
              AND ubr.weight_num IS NOT NULL
              AND UPPER(COALESCE(ubr.row_status, '')) IN ('ACCEPTED', 'OVERRIDDEN', 'NEEDS_ATTENTION')
            ORDER BY ubr.upload_batch_id DESC
            """,
            (*org_args, *part, selected_date_et),
        )
        for row in cursor.fetchall() or []:
            bid = str(row.get("ticket_id") or "").strip().upper()
            if not bid or bid in out:
                continue
            w = normalize_scan_weight_lbs(row.get("weight_num"))
            if w is not None:
                out[bid] = w
    return out


def load_latest_portal_weights_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, float]:
    """Latest portal upload weight per bag (any date_clean) — ingestion repair only."""
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    if not ids or not hasattr(cursor, "execute"):
        return {}
    if not table_exists(cursor, "upload_batch_rows"):
        return {}
    if not table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        return {}

    out: dict[str, float] = {}
    chunk = 100
    from backend.checkout_batch_scope import _batch_pk, _row_batch_col

    row_batch_col = _row_batch_col(cursor)
    batch_pk = _batch_pk(cursor)
    org_join = ""
    org_args: tuple[Any, ...] = ()
    if row_batch_col and table_exists(cursor, "upload_batches"):
        if table_has_column(cursor, "upload_batches", "organization_id"):
            org_join = (
                f" INNER JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}"
                f" AND ub.organization_id = %s"
            )
            org_args = (org,)

    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT ubr.ticket_id, ubr.weight_num
            FROM upload_batch_rows ubr{org_join}
            INNER JOIN (
                SELECT ticket_id, MAX(upload_batch_id) AS max_batch_id
                FROM upload_batch_rows
                WHERE ticket_id IN ({ph})
                  AND weight_num IS NOT NULL
                  AND UPPER(COALESCE(row_status, '')) IN ('ACCEPTED', 'OVERRIDDEN', 'NEEDS_ATTENTION')
                GROUP BY ticket_id
            ) latest ON latest.ticket_id = ubr.ticket_id
                AND latest.max_batch_id = ubr.upload_batch_id
            WHERE ubr.ticket_id IN ({ph})
              AND ubr.weight_num IS NOT NULL
            """,
            (*org_args, *part, *part),
        )
        for row in cursor.fetchall() or []:
            bid = str(row.get("ticket_id") or "").strip().upper()
            if not bid or bid in out:
                continue
            w = normalize_scan_weight_lbs(row.get("weight_num"))
            if w is not None:
                out[bid] = w
    return out


def load_weight_repair_sources_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    selected_date_et: date,
    registry_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, float]:
    """
    Weight candidates to attach onto post-processing scan rows.

    Rinse scan-events CSV has no Weight column. Prefer same-day portal
    weight_num (0 preserved). Registry weight_num is last fallback only when
    portal has no numeric value at all.
    """
    registry = registry_meta or {}
    same_day = load_portal_upload_weights_for_bags(
        cursor, organization_id, bag_ids, selected_date_et=selected_date_et
    )
    latest = load_latest_portal_weights_for_bags(cursor, organization_id, bag_ids)
    out: dict[str, float] = {}
    for bid in sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()}):
        if bid in same_day:
            out[bid] = same_day[bid]
            continue
        if bid in latest:
            out[bid] = latest[bid]
            continue
        lbs = _registry_weight_for_repair(registry.get(bid))
        if lbs is not None:
            out[bid] = lbs
    return out


def sync_post_processing_scan_weights_from_portal(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    selected_date_et: date,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    portal_weights_by_bag: Mapping[str, float] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Attach portal upload weight onto post-processing scan rows missing weight."""
    portal = dict(portal_weights_by_bag or {})
    if not portal:
        portal = load_weight_repair_sources_for_bags(
            cursor,
            organization_id,
            bag_ids,
            selected_date_et=selected_date_et,
        )
    results: list[dict[str, Any]] = []
    for bid in sorted(set(str(b).strip().upper() for b in bag_ids if str(b).strip())):
        portal_lbs = portal.get(bid)
        if portal_lbs is None:
            continue
        if dry_run:
            results.append(
                {
                    "bag_id": bid,
                    "dry_run": True,
                    "would_attach_weight_lbs": float(portal_lbs),
                }
            )
            continue
        events = (events_by_bag or {}).get(bid)
        results.append(
            attach_portal_weight_to_post_processing_scan(
                cursor,
                organization_id,
                bid,
                weight_lbs=portal_lbs,
                selected_date_et=selected_date_et,
                events=events,
            )
        )
    return results


def finalize_completed_bag_weight_fields(
    bag: dict[str, Any],
    row: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
    *,
    events: Sequence[Mapping[str, Any]] | None = None,
    selected_date_et: date,
    as_of_end: datetime,
    portal_upload_weight: float | None = None,
    credit_ts: datetime | None = None,
    anchor_ts: datetime | None = None,
    cursor=None,
    organization_id: int | None = None,
    repair_scan_from_portal: bool = True,
) -> None:
    """Resolve WF weight from post-processing scan only; record integrity failures."""
    from backend.rinse_employee_completed_bags import _apply_bag_weight_fields, _resolve_anchor_ts

    bid = str(bag.get("bag_id") or row.get("bag_id") or "").strip().upper()
    svc = str(row.get("service_type") or row.get("service_bucket") or bag.get("service_type") or "")
    if anchor_ts is None and events:
        anchor_ts = _resolve_anchor_ts(events, selected_date_et)
    if credit_ts is None:
        raw_credit_ts = bag.get("credit_timestamp")
        if isinstance(raw_credit_ts, datetime):
            credit_ts = raw_credit_ts
        elif raw_credit_ts:
            try:
                credit_ts = datetime.fromisoformat(str(raw_credit_ts))
            except ValueError:
                credit_ts = None

    portal_lbs = normalize_scan_weight_lbs(portal_upload_weight)
    if portal_lbs is None and svc.upper() == "WF":
        portal_lbs = _registry_weight_for_repair(meta)

    if (
        repair_scan_from_portal
        and cursor is not None
        and organization_id is not None
        and portal_lbs is not None
    ):
        repair_result = attach_portal_weight_to_post_processing_scan(
            cursor,
            int(organization_id),
            bid,
            weight_lbs=portal_lbs,
            selected_date_et=selected_date_et,
            events=events,
            credit_ts=credit_ts,
        )
        scan_id = (repair_result or {}).get("scan_event_id")
        if events and isinstance(events, list) and scan_id is not None:
            for ev in events:
                if ev.get("id") == scan_id:
                    ev["weight_lbs"] = portal_lbs
                    break

    lbs, trace = resolve_wf_completion_weight_lbs(
        bag_id=bid,
        events=events,
        credit_ts=credit_ts,
        anchor_ts=anchor_ts,
        as_of_end=as_of_end,
        selected_date_et=selected_date_et,
        portal_upload_weight=portal_lbs,
    )

    bag["weight_trace"] = trace
    if lbs is not None:
        _apply_bag_weight_fields(bag, lbs)
        bag["weight_lbs"] = lbs
        bag["weight_source"] = WEIGHT_SOURCE_POST_PROCESSING_SCAN
        bag["weight_status"] = WEIGHT_STATUS_RESOLVED
        bag["weight_integrity_failure"] = None
        return

    bag["weight_lbs"] = None
    bag["completed_lbs"] = None
    bag["weight"] = None
    bag["weight_status"] = WEIGHT_STATUS_INTEGRITY_FAILURE
    bag["weight_source"] = None
    bag["weight_missing"] = True
    bag["weight_integrity_failure"] = {
        "failure_stage": trace.get("failure_stage"),
        "failure_detail": trace.get("failure_detail"),
        "completion_event_id": trace.get("completion_event_id"),
        "portal_weight_available": trace.get("portal_weight_available"),
    }


def assert_completed_wf_bags_have_weight(
    bags: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return integrity violations for completed WF bags without post-processing scan weight."""
    violations: list[dict[str, Any]] = []
    for bag in bags:
        if not isinstance(bag, dict):
            continue
        svc = str(bag.get("service_type") or bag.get("service_bucket") or "").upper()
        if svc != "WF":
            continue
        if bag.get("weight_lbs") is None and bag.get("completed_lbs") is None:
            failure = bag.get("weight_integrity_failure") or {}
            trace = bag.get("weight_trace") or {}
            violations.append(
                {
                    "bag_id": bag.get("bag_id"),
                    "employee": bag.get("credited_employee") or bag.get("completed_by_employee"),
                    "completion_signal": bag.get("completion_signal") or bag.get("processed_signal"),
                    "failure_stage": failure.get("failure_stage") or trace.get("failure_stage"),
                    "failure_detail": failure.get("failure_detail") or trace.get("failure_detail"),
                    "completion_event_id": failure.get("completion_event_id") or trace.get("completion_event_id"),
                    "portal_weight_available": trace.get("portal_weight_available"),
                }
            )
    return violations
