"""Current-day completed workload weight resolution from portal upload + scans."""

from __future__ import annotations

POST_PROCESSING_WEIGHT_SIGNAL = "post_processing_weight"
POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL = "post_clean_weight_unavailable"
WEIGHT_STATUS_RESOLVED = "resolved"
WEIGHT_STATUS_MISSING = "missing"

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import gaming_events_from_records, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import parse_weight_lbs_from_scan_event


def _positive_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        val = float(raw)
        if val > 0:
            return round(val, 4)
    except (TypeError, ValueError):
        return None
    return None


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
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    return day_start <= ts <= day_end


def load_portal_upload_weights_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    selected_date_et: date,
) -> dict[str, float]:
    """Latest portal upload weight per bag for the selected ET clean date."""
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
            org_join = f" INNER JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col} AND ub.organization_id = %s"
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
            lbs = _positive_float(row.get("weight_num"))
            if lbs is not None:
                out[bid] = lbs
    return out


def load_registry_weight_context_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return {}

    cols = ["bag_id", "weight_num", "completion_status"]
    if table_has_column(cursor, "rinse_bag_registry", "completed_at"):
        cols.append("completed_at")
    if table_has_column(cursor, "rinse_bag_registry", "date_clean"):
        cols.append("date_clean")
    if table_has_column(cursor, "rinse_bag_registry", "updated_at"):
        cols.append("updated_at")

    out: dict[str, dict[str, Any]] = {}
    chunk = 100
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT {", ".join(cols)}
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if bid:
                out[bid] = dict(row)
    return out


def registry_weight_for_selected_day(
    registry_ctx: Mapping[str, Any] | None,
    *,
    selected_date_et: date,
) -> float | None:
    """Registry weight only when it belongs to the selected ET completion instance."""
    if not registry_ctx:
        return None
    lbs = _positive_float(registry_ctx.get("weight_num"))
    if lbs is None:
        return None

    completed_at = _parse_dt(registry_ctx.get("completed_at"))
    if completed_at is not None and _on_selected_et_day(completed_at, selected_date_et):
        return lbs

    date_clean = registry_ctx.get("date_clean")
    if isinstance(date_clean, datetime):
        date_clean = date_clean.date()
    if isinstance(date_clean, date) and date_clean == selected_date_et:
        return lbs

    return None


def _weight_from_row_only(row: Mapping[str, Any]) -> float | None:
    for key in ("post_clean_weight", "weight_lbs", "weight_num", "pre_clean_weight"):
        lbs = _positive_float(row.get(key))
        if lbs is not None:
            return lbs
    return None


def _weight_from_scan_events(
    *,
    events: Sequence[Mapping[str, Any]] | None,
    credit_ts: datetime | None,
    anchor_ts: datetime | None,
    as_of_end: datetime | None,
    service_type: str | None,
    meta: Mapping[str, Any] | None,
) -> float | None:
    if not events:
        return None

    from backend.rinse_employee_completed_bags import (
        _completed_lbs_from_attribution_scan,
        _scan_event_timestamp,
        _wf_completion_weight_event,
    )

    timeline = gaming_events_from_records(events)
    if credit_ts is not None:
        for ev in timeline:
            if _scan_event_timestamp(ev) == credit_ts and is_weight_entry_purpose(ev.get("purpose")):
                lbs = _positive_float(parse_weight_lbs_from_scan_event(ev))
                if lbs is not None:
                    return lbs
    if anchor_ts is not None and as_of_end is not None and ts_valid(anchor_ts):
        weight_ev, _ = _wf_completion_weight_event(
            timeline,
            anchor_ts=anchor_ts,
            as_of_end=as_of_end,
        )
        if weight_ev is not None:
            lbs = _positive_float(parse_weight_lbs_from_scan_event(weight_ev))
            if lbs is not None:
                return lbs
        return _completed_lbs_from_attribution_scan(
            service_type=str(service_type or ""),
            events=events,
            anchor_ts=anchor_ts,
            as_of_end=as_of_end,
        )
    return None


def resolve_current_completed_workload_weight_lbs(
    row: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
    *,
    events: Sequence[Mapping[str, Any]] | None = None,
    credit_ts: datetime | None = None,
    anchor_ts: datetime | None = None,
    as_of_end: datetime | None = None,
    service_type: str | None = None,
    selected_date_et: date | None = None,
    portal_upload_weight: float | None = None,
    registry_context: Mapping[str, Any] | None = None,
    processed_lbs: float | None = None,
) -> tuple[float | None, str | None]:
    """
    Resolve weight for a current completed workload instance.

    Priority:
    1. Current-day post-clean / final weight scan numeric
    2. Registry weight only when same completion instance/date
    3. Current-date upload_batch_rows.weight_num (same bag)
    4. Current workload row weight fields
    5. Legacy processed_lbs fallback (same day chronology)
    """
    scan_lbs = _weight_from_scan_events(
        events=events,
        credit_ts=credit_ts,
        anchor_ts=anchor_ts,
        as_of_end=as_of_end,
        service_type=service_type,
        meta=meta,
    )
    if scan_lbs is not None:
        return scan_lbs, "scan_post_clean_weight"

    if selected_date_et is not None:
        reg_lbs = registry_weight_for_selected_day(registry_context, selected_date_et=selected_date_et)
        if reg_lbs is not None:
            return reg_lbs, "registry_same_day_weight"

    portal_lbs = _positive_float(portal_upload_weight)
    if portal_lbs is not None:
        return portal_lbs, "portal_upload_weight"

    row_lbs = _weight_from_row_only(row)
    if row_lbs is not None:
        return row_lbs, "workload_row_weight"

    proc_lbs = _positive_float(processed_lbs)
    if proc_lbs is not None:
        return proc_lbs, "processed_chronology_weight"

    return None, None


def _explain_missing_weight(
    *,
    service_type: str | None,
    selected_date_et: date | None,
    registry_context: Mapping[str, Any] | None,
    portal_upload_weight: float | None,
    attribution_signal: str | None,
) -> str:
    parts: list[str] = []
    svc = str(service_type or "").upper()
    if svc == "WF" and str(attribution_signal or "") == POST_PROCESSING_WEIGHT_SIGNAL:
        parts.append(
            "Completion attributed to a post-processing weight-entry scan, "
            "but the scan payload has no numeric weight."
        )
    elif svc == "WF":
        parts.append("No parseable post-clean weight on scan events for this completion.")

    reg_ctx = registry_context or {}
    stale_reg = _positive_float(reg_ctx.get("weight_num"))
    if stale_reg is not None and selected_date_et is not None and registry_weight_for_selected_day(
        reg_ctx, selected_date_et=selected_date_et
    ) is None:
        parts.append("Registry weight exists but belongs to a prior completion date.")

    if portal_upload_weight is None:
        parts.append("No portal upload weight for this bag on the selected date.")

    if not parts:
        return "No weight source matched for this completed bag."
    return " ".join(parts)


def _reconcile_weight_display_signals(bag: dict[str, Any], *, weight_lbs: float | None) -> None:
    """Never show post_processing_weight as the display signal when weight is missing."""
    if weight_lbs is not None:
        return
    for field in ("completion_signal", "processed_signal"):
        if str(bag.get(field) or "") == POST_PROCESSING_WEIGHT_SIGNAL:
            bag[field] = POST_CLEAN_WEIGHT_UNAVAILABLE_SIGNAL


def finalize_completed_bag_weight_fields(
    bag: dict[str, Any],
    row: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
    *,
    events: Sequence[Mapping[str, Any]] | None = None,
    selected_date_et: date,
    as_of_end: datetime,
    portal_upload_weight: float | None = None,
    registry_context: Mapping[str, Any] | None = None,
    processed_lbs: float | None = None,
    credit_ts: datetime | None = None,
    anchor_ts: datetime | None = None,
) -> None:
    """Resolve weight, attach API fields, and reconcile display signals."""
    from backend.rinse_employee_completed_bags import _apply_bag_weight_fields, _resolve_anchor_ts

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

    lbs, weight_source = resolve_current_completed_workload_weight_lbs(
        row,
        meta,
        events=events,
        credit_ts=credit_ts,
        anchor_ts=anchor_ts,
        as_of_end=as_of_end,
        processed_lbs=processed_lbs,
        service_type=svc,
        selected_date_et=selected_date_et,
        portal_upload_weight=portal_upload_weight,
        registry_context=registry_context,
    )
    attribution_signal = (
        bag.get("credit_event_type")
        or bag.get("credit_signal")
        or bag.get("completion_signal")
        or row.get("completion_signal")
    )

    if lbs is not None:
        _apply_bag_weight_fields(bag, lbs)
        bag["weight_lbs"] = lbs
        bag["weight_status"] = WEIGHT_STATUS_RESOLVED
        bag["weight_source"] = weight_source
        bag["weight_debug_reason"] = None
        if portal_upload_weight is not None:
            bag["portal_upload_weight"] = portal_upload_weight
        return

    bag["weight_lbs"] = None
    bag["weight_status"] = WEIGHT_STATUS_MISSING
    bag["weight_source"] = None
    bag["weight_missing"] = True
    bag["completed_lbs"] = None
    bag["processed_lbs"] = None
    bag["credited_lbs"] = None
    bag["weight"] = None
    reg_ctx = registry_context or {}
    debug_reason = _explain_missing_weight(
        service_type=svc,
        selected_date_et=selected_date_et,
        registry_context=reg_ctx,
        portal_upload_weight=portal_upload_weight,
        attribution_signal=str(attribution_signal or ""),
    )
    if stale_reg := _positive_float(reg_ctx.get("weight_num")):
        if registry_weight_for_selected_day(reg_ctx, selected_date_et=selected_date_et) is None:
            debug_reason = (
                f"{debug_reason} Prior registry weight {stale_reg} lbs is from another completion date."
            ).strip()
    bag["weight_debug_reason"] = debug_reason
    _reconcile_weight_display_signals(bag, weight_lbs=None)


def sync_registry_weight_for_workload_day(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    weight_lbs: float,
    selected_date_et: date,
) -> bool:
    """Write current-day portal/completion weight into rinse_bag_registry when safe."""
    from backend.rinse_bag_registry import ensure_rinse_bag_registry_table, normalize_bag_id
    from backend.ta_helpers import table_has_column

    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    org = int(organization_id)
    lbs = _positive_float(weight_lbs)
    if lbs is None:
        return False

    ensure_rinse_bag_registry_table(cursor)
    ctx = load_registry_weight_context_for_bags(cursor, org, [bid]).get(bid) or {}
    status = str(ctx.get("completion_status") or "").upper()
    completed_at = _parse_dt(ctx.get("completed_at"))
    date_clean = ctx.get("date_clean")
    if isinstance(date_clean, datetime):
        date_clean = date_clean.date()

    prior_completed = status == "COMPLETED"
    new_portal_cycle = isinstance(selected_date_et, date) and (
        not isinstance(date_clean, date) or date_clean != selected_date_et
    )
    if prior_completed and completed_at is not None and not _on_selected_et_day(completed_at, selected_date_et):
        if not new_portal_cycle:
            return False

    set_parts = ["weight_num = %s", "updated_at = NOW()"]
    args: list[Any] = [lbs]
    if table_has_column(cursor, "rinse_bag_registry", "date_clean"):
        set_parts.append("date_clean = %s")
        args.append(selected_date_et)

    args.extend([org, bid])
    cursor.execute(
        f"""
        UPDATE rinse_bag_registry
        SET {", ".join(set_parts)}
        WHERE organization_id = %s AND bag_id = %s
        """,
        tuple(args),
    )
    return cursor.rowcount > 0
