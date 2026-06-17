"""Simplified Scope A / Scope B shift performance payload (backend-first, no UI logic)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import (
    ALL_ROLES,
    ROLE_FOLDING,
    ROLE_ISSUES,
    ROLE_SORTING,
    ROLE_WASHING,
    ROLE_WEIGHING,
    ROLE_WORKITEMS,
    BagActivityCredit,
    credit_in_et_period,
    evaluate_bag_completion_v2,
    evaluate_weight_difference,
    extract_bag_activity_credits,
)
from backend.rinse_bag_lifecycle_status import (
    CHECKOUT_STATUS_CHECKED_OUT,
    CHECKOUT_STATUS_NEEDS_REVIEW,
    CHECKOUT_STATUS_NOT_CHECKED_OUT,
    CHECKOUT_STATUS_NOT_RECORDED,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    PENDING_WEIGHING,
    SENT_TO_RINSE,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
)
from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et
from backend.rinse_processing_productivity import _load_shift_sessions, _shift_effective_clock_out
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_add_photos_purpose, is_drying_purpose, is_start_cleaning_purpose, is_weight_entry_purpose
from backend.rinse_bag_stage_bounds import first_start_cleaning_after, first_weight_after_anchor, gaming_events_from_records, lifecycle_anchor, events_on_or_after
from backend.rinse_scan_time import RINSE_SCAN_SOURCE_TIMEZONE, naive_system_utc
from backend.rinse_shift_analysis import (
    LIFECYCLE_COMPLETED_STATUSES,
    _load_scan_events_for_bags,
    _rush_bucket_key,
    _staging_logistics_expr,
    get_pending_bag_status,
)
from backend.ta_helpers import table_exists, table_has_column

RINSE_SYNC_STALE_MINUTES = 120
PRODUCTION_TENANT_MARKERS = ("veewash", "washpro staff", "washpro")

_LOGISTICS_SENT = frozenset({"SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"})
_PRE_FOLD_LIFECYCLE = frozenset(
    {
        PENDING_WEIGHING,
        WEIGHED_NOT_STARTED,
        "ASSIGNED_NOT_SENT_TO_VENDOR",
        "SENT_TO_VENDOR",
    }
)
_YET_TO_FOLD_LIFECYCLE = frozenset({SORTED_READY_FOR_WASH, IN_WASHING, IN_DRYING})


def _normalized_service_type(row: Mapping[str, Any]) -> str | None:
    svc_raw = row.get("service_type")
    if svc_raw is not None and str(svc_raw).strip():
        svc = str(svc_raw).strip().upper()
        if svc in ("WF", "HD"):
            return svc
    from backend.rinse_cleaner_ticket_presence import _presence_service_type

    inferred = _presence_service_type(row)
    return inferred if inferred in ("WF", "HD") else None


def _split_counts() -> dict[str, int]:
    return {
        "rush_wf": 0,
        "rush_hd": 0,
        "nonrush_wf": 0,
        "nonrush_hd": 0,
        "unknown_rush_wf": 0,
        "unknown_rush_hd": 0,
        "unknown_service": 0,
    }


def _bucket_for_row(row: Mapping[str, Any]) -> str | None:
    rush_raw = row.get("effective_rush") or row.get("rush_type") or row.get("rush_label") or ""
    rush = _rush_bucket_key(str(rush_raw))
    svc = _normalized_service_type(row)
    if svc is None:
        return "unknown_service"
    if rush == "rush":
        return f"rush_{svc.lower()}"
    if rush == "non_rush":
        return f"nonrush_{svc.lower()}"
    return f"unknown_rush_{svc.lower()}"


def _logistics_sent(row: Mapping[str, Any]) -> bool:
    logistics = str(row.get("logistics_status") or row.get("status") or "").upper()
    return logistics in _LOGISTICS_SENT


def _qualifies_for_active_work(
    pending_row: Mapping[str, Any] | None,
    completion: Any,
) -> bool:
    """Match GET /dashboard: every active orders_staging row (WF + HD), regardless of lifecycle."""
    if not pending_row or not isinstance(pending_row, dict):
        return False
    scope = str(pending_row.get("record_scope") or "")
    if scope == "incoming" or scope not in ("wf_lifecycle", "hd_lifecycle"):
        return False
    return bool(pending_row.get("in_active_staging"))


def _qualifies_yet_to_fold(
    pending_row: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    completion: Any,
) -> bool:
    """Post-wash / in-process WF bags not yet completed on our side."""
    if completion.completed:
        return False
    if not pending_row:
        return False
    svc = str(pending_row.get("service_type") or "").strip().upper()
    if svc == "HD":
        return False
    status = str(pending_row.get("current_lifecycle_status") or "")
    if status in LIFECYCLE_COMPLETED_STATUSES or status in _PRE_FOLD_LIFECYCLE:
        if status in _PRE_FOLD_LIFECYCLE:
            return False
    has_start_cleaning = any(is_start_cleaning_purpose(ev.get("purpose")) for ev in events)
    if status in _YET_TO_FOLD_LIFECYCLE:
        return True
    if has_start_cleaning and status not in LIFECYCLE_COMPLETED_STATUSES:
        return True
    return False


def _inc_split(counts: dict[str, int], bucket: str | None) -> None:
    if bucket and bucket in counts:
        counts[bucket] += 1
    elif bucket == "unknown_service":
        counts["unknown_service"] += 1


def _load_bag_ids_with_et_activity(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
) -> list[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    cursor.execute(
        """
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
        ORDER BY bag_id
        """,
        (org, start_dt, end_exclusive),
    )
    out: list[str] = []
    for row in cursor.fetchall() or []:
        bid = row.get("bag_id") if isinstance(row, dict) else row[0]
        if bid:
            out.append(str(bid).strip().upper())
    return out


def _load_bag_metadata(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, dict[str, Any]]:
    org = int(organization_id)
    meta: dict[str, dict[str, Any]] = {bid: {"bag_id": bid} for bid in bag_ids}
    if not bag_ids:
        return meta

    if table_exists(cursor, "rinse_bag_registry"):
        chunk = 100
        rush_sel = (
            "COALESCE(NULLIF(UPPER(rush_type), ''), 'UNKNOWN') AS rush_type"
            if table_has_column(cursor, "rinse_bag_registry", "rush_type")
            else "'UNKNOWN' AS rush_type"
        )
        registry_cols = ["bag_id", "name_clean", "weight_num", "service_type", rush_sel]
        if table_has_column(cursor, "rinse_bag_registry", "completion_status"):
            registry_cols.append("completion_status")
        if table_has_column(cursor, "rinse_bag_registry", "logistics_status"):
            registry_cols.append("logistics_status")
        else:
            registry_cols.append("NULL AS logistics_status")
        for i in range(0, len(bag_ids), chunk):
            part = bag_ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            cursor.execute(
                f"""
                SELECT {", ".join(registry_cols)}
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
                    meta[bid] = {**meta.get(bid, {}), **row, "bag_id": bid}

    if table_exists(cursor, "orders_staging") and table_has_column(cursor, "orders_staging", "ticket_id"):
        chunk = 100
        for i in range(0, len(bag_ids), chunk):
            part = bag_ids[i : i + chunk]
            ph = ",".join(["%s"] * len(part))
            org_clause = " AND organization_id = %s" if table_has_column(cursor, "orders_staging", "organization_id") else ""
            args: list[Any] = list(part)
            if org_clause:
                args.append(org)
            logistics_sel = f"{_staging_logistics_expr(cursor, 'os')} AS logistics_status"
            staging_cols = [
                "os.ticket_id AS bag_id",
                "os.name_clean",
                "os.weight_num",
                "os.service_type",
                "os.rush_type",
                logistics_sel,
            ]
            if table_has_column(cursor, "orders_staging", "status"):
                staging_cols.append("os.status")
            else:
                staging_cols.append("NULL AS status")
            if table_has_column(cursor, "orders_staging", "special_instructions_raw"):
                staging_cols.extend(
                    [
                        "os.special_instructions_raw",
                        "os.supply_interpretation",
                        "os.special_instruction_review",
                    ]
                )
            cursor.execute(
                f"""
                SELECT {", ".join(staging_cols)}
                FROM orders_staging os
                WHERE os.ticket_id IN ({ph}){org_clause}
                """,
                tuple(args),
            )
            for row in cursor.fetchall() or []:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bag_id") or "").strip().upper()
                if not bid:
                    continue
                cur = meta.setdefault(bid, {"bag_id": bid})
                for k, v in row.items():
                    if v is not None and cur.get(k) in (None, ""):
                        cur[k] = v
    return meta


def _load_rinse_user_maps(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    if not table_exists(cursor, "rinse_folding_user_map"):
        return {}
    org = int(organization_id)
    active_clause = " AND m.active = 1" if table_has_column(cursor, "rinse_folding_user_map", "active") else ""
    if table_has_column(cursor, "users", "display_name"):
        display_expr = "u.display_name AS display_name"
    elif table_has_column(cursor, "users", "username"):
        display_expr = "u.username AS display_name"
    else:
        display_expr = "NULL AS display_name"
    cursor.execute(
        f"""
        SELECT m.rinse_user_name, m.user_id, {display_expr}
        FROM rinse_folding_user_map m
        LEFT JOIN users u ON u.id = m.user_id
        WHERE m.organization_id = %s{active_clause}
        """,
        (org,),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("rinse_user_name") or "").strip()
        if name:
            out[name.casefold()] = row
    return out


def _employee_shift_window(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    period_start: date,
    period_end: date,
    sessions_by_user: dict[int, list[dict[str, Any]]] | None = None,
    last_sync: datetime | None = None,
    last_sync_loaded: bool = False,
    window_cache: dict[int, tuple[datetime | None, datetime | None, str | None]] | None = None,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Earliest clock-in and latest effective clock-out overlapping ET day."""
    uid = int(user_id)
    if window_cache is not None and uid in window_cache:
        return window_cache[uid]

    from backend.rinse_processing_productivity import (
        _employee_shift_window_from_sessions,
        _last_rinse_sync_naive,
        _load_shift_sessions,
    )

    if sessions_by_user is not None:
        sessions = sessions_by_user.get(uid) or []
    else:
        sessions = _load_shift_sessions(cursor, organization_id, uid, period_start, period_end)
    sync = last_sync if last_sync_loaded else _last_rinse_sync_naive(cursor, organization_id)
    result = _employee_shift_window_from_sessions(
        sessions,
        period_start=period_start,
        period_end=period_end,
        last_sync=sync,
    )
    if window_cache is not None:
        window_cache[uid] = result
    return result


def _activity_allowed(
    ts: datetime,
    *,
    clock_in: datetime | None,
    clock_out: datetime | None,
) -> bool:
    if clock_in is None:
        return False
    if ts < clock_in:
        return False
    if clock_out is not None and ts > clock_out:
        return False
    return True


def _count_splits_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = _split_counts()
    counts["total"] = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        counts["total"] += 1
        _inc_split(counts, _bucket_for_row(row))
    return counts


def _presence_last_refreshed(pending: Mapping[str, Any]) -> str | None:
    incoming = pending.get("incoming") or {}
    summary = incoming.get("summary") or {}
    for key in ("last_presence_refresh_at", "presence_last_refreshed_at", "last_refreshed_at", "last_seen_at"):
        raw = summary.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            return raw.isoformat()
        return str(raw)
    portal = pending.get("portal_alignment") or {}
    raw = portal.get("presence_last_refreshed_at") or portal.get("last_presence_refresh_at")
    if isinstance(raw, datetime):
        return raw.isoformat()
    if raw:
        return str(raw)
    return None


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return naive_system_utc(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return naive_system_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")[:26]))
        except ValueError:
            return None
    return None


def _build_sync_status(
    last_refreshed_at: str | None,
    *,
    sync_name: str = "Ready for Vendor Sync",
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    if not last_refreshed_at:
        return {
            "sync_time_unavailable": True,
            "stale": False,
            "stale_reason": None,
            "message": f"{sync_name}: unavailable",
            "last_rinse_sync_at": None,
            "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
            "sync_name": sync_name,
        }
    last_dt = _parse_iso_datetime(last_refreshed_at)
    now = naive_system_utc(
        evaluation_time if isinstance(evaluation_time, datetime) else datetime.utcnow()
    )
    if last_dt is None:
        return {
            "sync_time_unavailable": True,
            "stale": False,
            "stale_reason": None,
            "message": f"{sync_name}: unavailable",
            "last_rinse_sync_at": last_refreshed_at,
            "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
            "sync_name": sync_name,
        }
    age_min = max(0, int((now - last_dt).total_seconds()) // 60)
    stale = age_min > RINSE_SYNC_STALE_MINUTES
    return {
        "sync_time_unavailable": False,
        "stale": stale,
        "stale_reason": f"{sync_name} stale" if stale else None,
        "message": f"{sync_name}: {last_refreshed_at}",
        "last_rinse_sync_at": last_refreshed_at,
        "age_minutes": age_min,
        "stale_after_minutes": RINSE_SYNC_STALE_MINUTES,
        "sync_name": sync_name,
    }


def _finalize_section_counts(section: dict[str, Any]) -> None:
    parts = (
        int(section.get("rush_wf") or 0)
        + int(section.get("rush_hd") or 0)
        + int(section.get("nonrush_wf") or 0)
        + int(section.get("nonrush_hd") or 0)
        + int(section.get("unknown_needs_review") or 0)
    )
    total = int(section.get("total") or 0)
    rush_total = int(section.get("rush_wf") or 0) + int(section.get("rush_hd") or 0)
    nonrush_total = (
        int(section.get("nonrush_wf") or 0)
        + int(section.get("nonrush_hd") or 0)
        + int(section.get("unknown_needs_review") or 0)
    )
    section["rush_total"] = rush_total
    section["nonrush_total"] = nonrush_total
    section["split_sum"] = parts
    section["counts_add_up"] = total == parts
    section["rush_nonrush_reconciled"] = total == rush_total + nonrush_total
    section["unreconciled"] = max(0, total - parts) if total != parts else 0


def _collect_unreconciled_ids(records: list[dict[str, Any]], base_tag: str) -> list[str]:
    prefix = "rfv_" if base_tag == "ready_for_vendor" else "active_"
    bucket_suffixes = ("rush_wf", "rush_hd", "nonrush_wf", "nonrush_hd", "unknown_rush_wf", "unknown_rush_hd")
    out: list[str] = []
    for rec in records:
        tags = set(rec.get("drilldown_tags") or [])
        if base_tag not in tags:
            continue
        if any(f"{prefix}{suffix}" in tags for suffix in bucket_suffixes):
            continue
        if "rfv_unknown_needs_review" in tags or "unknown_speed_service" in tags:
            continue
        bid = str(rec.get("bag_id") or "").strip()
        if bid:
            out.append(bid)
    return sorted(out)


def _data_quality_warning(section: dict[str, Any]) -> str | None:
    total = int(section.get("total") or 0)
    unknown = int(section.get("unknown_needs_review") or 0)
    if total > 0 and unknown >= total:
        return "Ready for Vendor rows are missing Rush/WF/HD classification. Check Rinse Sync parser."
    if int(section.get("unreconciled") or 0) > 0:
        return "Section counts do not add up — see unreconciled drilldown."
    return None


def _is_production_employee(employee: str, user_maps: dict[str, dict[str, Any]]) -> bool:
    emp = str(employee or "").strip()
    if not emp:
        return False
    if emp.casefold() in user_maps:
        return True
    if "(" in emp and ")" in emp:
        inner = emp.split("(")[-1].split(")")[0].casefold()
        if any(marker in inner for marker in PRODUCTION_TENANT_MARKERS):
            return True
    return False


def _build_ready_for_vendor_section(
    pending: Mapping[str, Any],
    *,
    rfv_sync: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sync = dict(rfv_sync or {})
    enabled = sync.get("enabled", True)
    latest_status = str(sync.get("latest_status") or sync.get("status") or "")
    skipped_reason = sync.get("skipped_reason")
    error_message = sync.get("error") or sync.get("error_message")
    stale = bool(sync.get("stale"))
    last_success_at = sync.get("last_success_at")
    last_refreshed_at = (
        sync.get("last_refreshed_at")
        or last_success_at
        or _presence_last_refreshed(pending)
    )
    base_sync = sync if sync else _build_sync_status(
        last_refreshed_at, sync_name="Ready for Vendor Sync"
    )

    def _unavailable(reason: str) -> dict[str, Any]:
        return {
            "live": False,
            "under_review": True,
            "total": None,
            "rush_wf": None,
            "rush_hd": None,
            "nonrush_wf": None,
            "nonrush_hd": None,
            "unknown_needs_review": None,
            "source": "Ready for Vendor queue",
            "last_refreshed_at": last_refreshed_at,
            "sync_status": base_sync,
            "unavailable_reason": reason,
            "data_quality_warning": reason,
            "drilldown_filter": "ready_for_vendor",
            "rows_found": sync.get("rows_found"),
            "active_rows": sync.get("active_rows"),
            "skipped_reason": skipped_reason,
            "error": error_message,
        }

    if not enabled or latest_status == "disabled" or skipped_reason:
        return _unavailable(
            f"Ready for Vendor Sync skipped: {skipped_reason or 'feature flag disabled'}"
        )
    if latest_status == "failed" or sync.get("latest_failed"):
        return _unavailable(
            f"Ready for Vendor Sync failed: {error_message or 'unknown error'}"
        )
    if stale and not sync.get("zero_rows_success"):
        stale_ref = last_refreshed_at or last_success_at or "unknown"
        return _unavailable(
            (
                f"Ready for Vendor sync stale — last refresh {stale_ref}. "
                "Refresh Both Syncs before using live counts."
            )
        )

    incoming = pending.get("incoming") or {}
    rows = [r for r in (incoming.get("rows") or []) if isinstance(r, dict)]
    splits = _count_splits_from_rows(rows)
    section = {
        "live": True,
        "under_review": False,
        "total": int(splits.get("total") or 0),
        "rush_wf": int(splits.get("rush_wf") or 0),
        "rush_hd": int(splits.get("rush_hd") or 0),
        "nonrush_wf": int(splits.get("nonrush_wf") or 0),
        "nonrush_hd": int(splits.get("nonrush_hd") or 0),
        "unknown_needs_review": int(splits.get("unknown_rush_wf") or 0)
        + int(splits.get("unknown_rush_hd") or 0)
        + int(splits.get("unknown_service") or 0),
        "source": "Ready for Vendor queue",
        "last_refreshed_at": last_refreshed_at,
        "sync_status": base_sync,
        "drilldown_filter": "ready_for_vendor",
        "rows_found": sync.get("rows_found"),
        "active_rows": sync.get("active_rows"),
        "skipped_reason": skipped_reason,
        "error": error_message,
    }
    if sync.get("zero_rows_success"):
        section["zero_rows_success"] = True
        section["data_quality_warning"] = "Ready for Vendor Sync returned 0 rows successfully"
    else:
        section["data_quality_warning"] = _data_quality_warning(section)
    _finalize_section_counts(section)
    return section


def _build_work_pipeline_section(
    pipeline_bag_ids: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    target_date: date,
    *,
    last_rush_wash: dict[str, Any] | None = None,
    last_nonrush_wash: dict[str, Any] | None = None,
    last_wash_overall: dict[str, Any] | None = None,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Current Work Pipeline Now — pending bags including carryover (excludes completed/sent)."""
    from backend.rinse_facility_tracker import classify_bag_ids_into_section

    ids = sorted({str(b).strip().upper() for b in pipeline_bag_ids if b})
    section = classify_bag_ids_into_section(
        ids,
        meta_by_bag,
        target_date,
        source="Active orders_staging minus completed/sent",
        drilldown_filter="pipeline_work",
        scope_label="current_work_pipeline",
    )
    section["description"] = "Bags still pending now — includes carryover from prior days"
    section["scope"] = "current_work_pipeline"
    recs = records or []
    rush_pending = sum(1 for r in recs if r.get("rush_label") == "Rush" and "pipeline_work" in (r.get("drilldown_tags") or []))
    nonrush_pending = sum(1 for r in recs if r.get("rush_label") == "Non-Rush" and "pipeline_work" in (r.get("drilldown_tags") or []))
    section["rush_pending"] = rush_pending
    section["nonrush_pending"] = nonrush_pending
    section["pending_wash_rush"] = _count_tag(recs, "wf_pending_wash_rush")
    section["pending_wash_nonrush"] = _count_tag(recs, "wf_pending_wash_nonrush")
    section["pending_wash_total"] = _count_tag(
        [r for r in recs if r.get("service_type") == "WF"], "pending_wash"
    )
    section["yet_to_fold"] = _count_tag([r for r in recs if r.get("service_type") == "WF"], "wf_pending_folding")
    section["issues"] = _count_tag(recs, "issues")
    section["workitems"] = _count_tag(recs, "workitems")
    section["last_rush_wash"] = last_rush_wash
    section["last_nonrush_wash"] = last_nonrush_wash
    section["last_wash_overall"] = last_wash_overall
    section["pending_wash_rush_ids"] = sorted(
        str(r.get("bag_id"))
        for r in recs
        if "wf_pending_wash_rush" in (r.get("drilldown_tags") or [])
    )
    section["pending_wash_nonrush_ids"] = sorted(
        str(r.get("bag_id"))
        for r in recs
        if "wf_pending_wash_nonrush" in (r.get("drilldown_tags") or [])
    )
    return section


def _build_active_work_from_dashboard(dashboard: Mapping[str, Any]) -> dict[str, Any]:
    """Current Active Work Now — currently active/pending facility work (orders_staging)."""
    section = {
        "total": int(dashboard.get("total_orders") or 0),
        "rush_wf": int(dashboard.get("wf_rush") or 0),
        "rush_hd": int(dashboard.get("hd_rush") or 0),
        "nonrush_wf": int(dashboard.get("wf_non_rush") or 0),
        "nonrush_hd": int(dashboard.get("hd_non_rush") or 0),
        "unknown_needs_review": int(len(dashboard.get("unknown_ids") or [])),
        "staging_total": int(dashboard.get("total_orders") or 0),
        "staging_row_count": int(dashboard.get("staging_row_count") or 0),
        "duplicate_staging_rows": int(dashboard.get("duplicate_staging_rows") or 0),
        "unique_bag_count": int(dashboard.get("unique_bag_count") or 0),
        "batch_date": dashboard.get("batch_date"),
        "source": "Currently active/pending facility work (orders_staging)",
        "description": "Bags still pending now — includes carryover from prior days",
        "scope": "current_active_work_now",
        "drilldown_filter": "active_work",
        "dashboard_source": True,
        "rush_wf_ids": sorted(dashboard.get("rush_wf_ids") or []),
        "rush_hd_ids": sorted(dashboard.get("rush_hd_ids") or []),
        "nonrush_wf_ids": sorted(dashboard.get("nonrush_wf_ids") or []),
        "nonrush_hd_ids": sorted(dashboard.get("nonrush_hd_ids") or []),
        "unknown_ids": sorted(dashboard.get("unknown_ids") or []),
        "bag_ids": sorted(dashboard.get("unique_bag_ids") or []),
    }
    _finalize_section_counts(section)
    dup = int(dashboard.get("duplicate_staging_rows") or 0)
    if dup > 0:
        section["data_quality_warning"] = (
            f"orders_staging has {dup} duplicate ticket_id row(s); "
            f"Active Total ({section['total']}) matches GET /dashboard COUNT(*)."
        )
    return section


def _build_active_work_section(pending: Mapping[str, Any]) -> dict[str, Any]:
    active_staging = pending.get("active_staging") or {}
    staging_rows = [r for r in (active_staging.get("rows") or []) if isinstance(r, dict)]
    if staging_rows:
        active_rows = staging_rows
    else:
        active_rows = [
            r
            for r in (pending.get("rows") or [])
            if isinstance(r, dict)
            and str(r.get("record_scope") or "") != "incoming"
            and r.get("in_active_staging")
        ]
    splits = _count_splits_from_rows(active_rows)
    staging_meta = active_staging.get("meta") or {}
    portal = pending.get("portal_alignment") or {}
    staging_total = int(
        staging_meta.get("unique_bag_count") or portal.get("portal_active_total") or 0
    )
    duplicate_rows = int(staging_meta.get("duplicate_staging_rows") or 0)
    section = {
        "total": int(splits.get("total") or 0),
        "rush_wf": int(splits.get("rush_wf") or 0),
        "rush_hd": int(splits.get("rush_hd") or 0),
        "nonrush_wf": int(splits.get("nonrush_wf") or 0),
        "nonrush_hd": int(splits.get("nonrush_hd") or 0),
        "unknown_needs_review": int(splits.get("unknown_rush_wf") or 0)
        + int(splits.get("unknown_rush_hd") or 0)
        + int(splits.get("unknown_service") or 0),
        "staging_total": staging_total,
        "staging_row_count": int(staging_meta.get("staging_row_count") or staging_total),
        "duplicate_staging_rows": duplicate_rows,
        "source": "At Vendor — active orders_staging (same basis as GET /dashboard)",
        "drilldown_filter": "active_work",
    }
    _finalize_section_counts(section)
    if duplicate_rows > 0:
        section["data_quality_warning"] = (
            f"orders_staging has {duplicate_rows} duplicate ticket_id row(s); "
            f"Active Work uses {staging_total} unique bags."
        )
    elif staging_total > 0 and int(section.get("total") or 0) != staging_total:
        section["data_quality_warning"] = (
            f"Active Work ({section.get('total')}) does not match orders_staging ({staging_total}). "
            "Run Refresh Both Syncs or check Advanced Debug."
        )
    return section


def _attach_section_sync_statuses(
    cursor,
    organization_id: int,
    *,
    ready_for_vendor: dict[str, Any],
    active_work: dict[str, Any],
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    from backend.rinse_presence_sync_status import (
        build_at_vendor_sync_status,
        get_ready_for_vendor_sync_status,
    )

    rfv_sync = get_ready_for_vendor_sync_status(
        cursor, organization_id, evaluation_time=evaluation_time
    )
    av_sync = build_at_vendor_sync_status(
        cursor, organization_id, evaluation_time=evaluation_time
    )
    ready_for_vendor["last_refreshed_at"] = (
        rfv_sync.get("last_refreshed_at") or ready_for_vendor.get("last_refreshed_at")
    )
    ready_for_vendor["sync_status"] = {
        **_build_sync_status(
            ready_for_vendor.get("last_refreshed_at"),
            sync_name="Ready for Vendor Sync",
            evaluation_time=evaluation_time,
        ),
        **{k: v for k, v in rfv_sync.items() if k not in ("message",)},
    }
    active_work["last_refreshed_at"] = av_sync.get("last_refreshed_at")
    active_work["sync_status"] = av_sync
    from backend.rinse_presence_sync_status import build_rinse_sync_cycle_status

    return {
        "at_vendor": av_sync,
        "ready_for_vendor": rfv_sync,
        "ready_for_vendor_enabled": bool(rfv_sync.get("enabled", True)),
        "sync_cycle": build_rinse_sync_cycle_status(cursor, organization_id),
    }


def _build_rush_checkout_section(pending: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    checkout = (pending.get("checkout_summary") or {}).get("rush") or {}
    return {
        "checkout_pending": _count_tag(records, "checkout_pending"),
        "checked_out": int(checkout.get("checked_out") or 0) or _count_tag(records, "checkout_checked_out"),
        "checkout_needs_review": int(checkout.get("checkout_needs_review") or 0)
        or _count_tag(records, "checkout_needs_review"),
        "checkout_not_recorded": _count_tag(records, "checkout_not_recorded"),
        "source": "Rush facility checkout workflow",
        "description": "Checkout Pending = Rush bags still waiting for facility checkout",
        "drilldown_filter": "checkout_pending",
    }


def _build_scope_a(
    pending: Mapping[str, Any],
) -> dict[str, Any]:
    incoming = pending.get("incoming") or {}
    inc_groups = incoming.get("groups") or {}
    inc_combined = inc_groups.get("combined") or {}

    wf = pending.get("wf_lifecycle") or {}
    wf_groups = wf.get("groups") or {}
    wf_combined = wf_groups.get("combined") or {}
    wf_by_status = wf_combined.get("by_lifecycle_status") or {}
    wf_by_group = wf_combined.get("by_lifecycle_group") or {}

    rush_pending_wash = 0
    for grp_key in ("rush", "combined"):
        grp = wf_groups.get(grp_key) or {}
        bs = grp.get("by_lifecycle_status") or {}
        rush_pending_wash += int(bs.get(SORTED_READY_FOR_WASH) or 0)

    not_weighed = int(wf_by_status.get(PENDING_WEIGHING) or 0) + int(
        wf_by_status.get(WEIGHED_NOT_STARTED) or 0
    )
    yet_to_fold = (
        int(wf_by_group.get("wash_dry") or 0)
        + int(wf_by_group.get("sorted_ready") or 0)
        + int(wf_by_group.get("weighed_not_started") or 0)
        + int(wf_by_group.get("pending_weighing") or 0)
    )

    return {
        "ready_for_vendor": {
            "total": int(inc_combined.get("ready_for_vendor") or 0),
            "wf": int(inc_combined.get("wf") or 0),
            "hd": int(inc_combined.get("hd") or 0),
            "groups": inc_groups,
        },
        "current_active_work": {
            "wf_total": int(wf_combined.get("total") or 0),
            "hd_total": int((pending.get("hd_lifecycle") or {}).get("groups", {}).get("combined", {}).get("total") or 0),
            "groups": wf_groups,
        },
        "not_weighed": {"total": not_weighed, "by_status": {PENDING_WEIGHING: wf_by_status.get(PENDING_WEIGHING, 0), WEIGHED_NOT_STARTED: wf_by_status.get(WEIGHED_NOT_STARTED, 0)}},
        "rush_pending_wash": {"total": rush_pending_wash},
        "yet_to_fold": {"total": yet_to_fold},
        "checkout_pending": pending.get("checkout_rush") or {},
    }


def _build_employee_activity_summary(
    cursor,
    organization_id: int,
    *,
    credits: list[BagActivityCredit],
    period_start: date,
    period_end: date,
    user_maps: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)

    by_emp_role: dict[tuple[str, str], list[BagActivityCredit]] = defaultdict(list)
    all_employees: set[str] = set()
    for cr in credits:
        if not credit_in_et_period(cr, period_start=start_dt, period_end_exclusive=end_exclusive):
            continue
        emp = str(cr.employee or "").strip()
        if not emp:
            continue
        all_employees.add(emp)
        if not _is_production_employee(emp, user_maps):
            continue
        by_emp_role[(emp, cr.role)].append(cr)

    excluded_external = sorted(
        e for e in all_employees if not _is_production_employee(e, user_maps)
    )

    from backend.rinse_processing_productivity import (
        _last_rinse_sync_naive,
        _load_shift_sessions_bulk,
    )

    user_ids = sorted(
        {
            int(mapping["user_id"])
            for (employee, _role) in by_emp_role
            if (mapping := user_maps.get(employee.casefold())) and mapping.get("user_id")
        }
    )
    last_sync = _last_rinse_sync_naive(cursor, organization_id)
    sessions_by_user = (
        _load_shift_sessions_bulk(
            cursor, organization_id, user_ids, period_start, period_end
        )
        if user_ids
        else {}
    )
    window_cache: dict[int, tuple[datetime | None, datetime | None, str | None]] = {}

    summaries: list[dict[str, Any]] = []
    for (employee, role), rows in sorted(by_emp_role.items(), key=lambda x: (x[0][0].lower(), x[0][1])):
        mapping = user_maps.get(employee.casefold())
        user_id = int(mapping["user_id"]) if mapping and mapping.get("user_id") else None
        clock_in: datetime | None = None
        clock_out: datetime | None = None
        diagnostic: str | None = None
        if user_id is None:
            diagnostic = "User mapping missing"
        else:
            clock_in, clock_out, diagnostic = _employee_shift_window(
                cursor,
                organization_id,
                user_id=user_id,
                period_start=period_start,
                period_end=period_end,
                sessions_by_user=sessions_by_user,
                last_sync=last_sync,
                last_sync_loaded=True,
                window_cache=window_cache,
            )

        if clock_in is None:
            filtered = list(rows)
        else:
            filtered = [
                r
                for r in rows
                if _activity_allowed(r.activity_at, clock_in=clock_in, clock_out=clock_out)
            ]
        if not filtered:
            continue

        bag_ids = {r.bag_id for r in filtered}
        first_ts = min(r.activity_at for r in filtered)
        last_row = max(filtered, key=lambda r: r.activity_at)
        last_ts = last_row.activity_at
        lbs = round(sum(float(r.lbs or 0) for r in filtered if r.lbs), 2)

        perf_hours: float | None = None
        active_span_hours: float | None = None
        bags_per_hour: float | None = None
        lbs_per_hour: float | None = None
        needs_review = sum(1 for r in filtered if r.needs_review)

        if diagnostic:
            pass
        elif clock_in is None:
            diagnostic = "Clock-in missing"
        else:
            perf_sec = max(0, int((last_ts - clock_in).total_seconds()))
            perf_hours = round(perf_sec / 3600.0, 4)
            active_span_hours = round(max(0, int((last_ts - first_ts).total_seconds())) / 3600.0, 4)
            if perf_hours > 0:
                bags_per_hour = round(len(bag_ids) / perf_hours, 4)
                if lbs:
                    lbs_per_hour = round(lbs / perf_hours, 4)

        summaries.append(
            {
                "employee": employee,
                "role": role,
                "bags": len(bag_ids),
                "bag_ids": sorted(bag_ids),
                "lbs": lbs,
                "clock_in_time": clock_in.isoformat() if isinstance(clock_in, datetime) else None,
                "first_activity_time": first_ts.isoformat(),
                "last_activity_time": last_ts.isoformat(),
                "last_activity_type": last_row.activity_kind,
                "last_activity_bag_id": last_row.bag_id,
                "last_activity_customer": last_row.customer,
                "performance_hours": perf_hours,
                "active_span_hours": active_span_hours,
                "bags_per_hour": bags_per_hour,
                "lbs_per_hour": lbs_per_hour,
                "needs_review_count": needs_review,
                "exception_count": sum(len(r.flags) for r in filtered),
                "diagnostic": diagnostic or (None if bags_per_hour is not None else "No completion activity"),
            }
        )

    folding_blank_reason = None
    folding_rows = [s for s in summaries if s.get("role") == ROLE_FOLDING]
    if not folding_rows:
        folding_blank_reason = "No completion activity"
    elif all(s.get("diagnostic") for s in folding_rows):
        folding_blank_reason = folding_rows[0].get("diagnostic")

    diagnostics = {
        "included_employees": sorted({s["employee"] for s in summaries}),
        "excluded_external": excluded_external,
        "folding_averages_status": (
            "ok"
            if any(s.get("bags_per_hour") is not None for s in folding_rows)
            else (folding_blank_reason or "Clock-in missing")
        ),
    }
    return summaries, diagnostics


def _build_employee_cards(role_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_emp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in role_summaries:
        emp = str(row.get("employee") or "").strip()
        if emp:
            by_emp[emp].append(row)
    cards: list[dict[str, Any]] = []
    for employee, roles in sorted(by_emp.items(), key=lambda x: x[0].lower()):
        all_bags: set[str] = set()
        last_ts: datetime | None = None
        last_meta: dict[str, Any] = {}
        clock_in_raw = roles[0].get("clock_in_time")
        diagnostic = roles[0].get("diagnostic")
        for role_row in roles:
            all_bags.update(role_row.get("bag_ids") or [])
            lat = role_row.get("last_activity_time")
            if lat:
                try:
                    ts = datetime.fromisoformat(str(lat))
                except ValueError:
                    ts = None
                if ts and (last_ts is None or ts > last_ts):
                    last_ts = ts
                    last_meta = role_row
        perf_hours = None
        bags_per_hour = None
        if not diagnostic and clock_in_raw and last_ts:
            try:
                cin = datetime.fromisoformat(str(clock_in_raw))
                perf_sec = max(0, int((last_ts - cin).total_seconds()))
                perf_hours = round(perf_sec / 3600.0, 4)
                if perf_hours > 0:
                    bags_per_hour = round(len(all_bags) / perf_hours, 4)
            except ValueError:
                diagnostic = diagnostic or "Clock-in missing"
        elif not diagnostic:
            diagnostic = "Clock-in missing"
        total_lbs = round(sum(float(r.get("lbs") or 0) for r in roles if r.get("lbs")), 2)
        lbs_per_hour = None
        if perf_hours and perf_hours > 0 and total_lbs:
            lbs_per_hour = round(total_lbs / perf_hours, 4)
        cards.append(
            {
                "employee": employee,
                "clock_in_time": clock_in_raw,
                "last_activity_time": last_meta.get("last_activity_time"),
                "last_activity_type": last_meta.get("last_activity_type"),
                "last_activity_bag_id": last_meta.get("last_activity_bag_id"),
                "total_bags_touched": len(all_bags),
                "total_lbs": total_lbs or None,
                "performance_hours": perf_hours,
                "bags_per_hour": bags_per_hour,
                "lbs_per_hour": lbs_per_hour,
                "diagnostic": diagnostic,
                "roles": roles,
            }
        )
    return cards


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _rush_label(bucket: str | None) -> str:
    if not bucket:
        return "Unknown"
    if bucket.startswith("rush"):
        return "Rush"
    if bucket.startswith("nonrush"):
        return "Non-Rush"
    return "Unknown"


def _wf_stage_audit_fields(
    events: Sequence[Mapping[str, Any]],
    completion: Any,
    wdiff: Any,
) -> dict[str, Any]:
    """WF-only drilldown audit fields (never applied to HD)."""
    timeline = gaming_events_from_records(events)
    anchor_ts, _ = lifecycle_anchor(timeline)
    anchored = events_on_or_after(timeline, anchor_ts) if anchor_ts else list(timeline)
    _, fw_ts = first_weight_after_anchor(anchored)
    sorted_ts = None
    if fw_ts is not None:
        for ev in anchored:
            if not is_add_photos_purpose(ev.get("purpose")):
                continue
            ts = ev.get("scanned_at_parsed")
            if isinstance(ts, datetime) and ts > fw_ts:
                sorted_ts = ts
                break
    sc_ev = first_start_cleaning_after(anchored, after_ts=fw_ts)
    sc_ts = sc_ev.get("scanned_at_parsed") if isinstance(sc_ev, dict) else None
    dry_ts = None
    for ev in anchored:
        if not is_drying_purpose(ev.get("purpose")):
            continue
        ts = ev.get("scanned_at_parsed")
        if isinstance(ts, datetime):
            dry_ts = ts
            break
    clean_ts = None
    for ev in timeline:
        rack = str(ev.get("rack") or "").lower()
        if "clean" in rack and "dirty" not in rack:
            ts = ev.get("scanned_at_parsed")
            if isinstance(ts, datetime):
                clean_ts = ts
    completion_signal = completion.completion_kind or completion.exception_code
    return {
        "first_weight_time": (
            wdiff.first_weight_at.isoformat()
            if isinstance(wdiff.first_weight_at, datetime)
            else (fw_ts.isoformat() if isinstance(fw_ts, datetime) else None)
        ),
        "first_weight_value": wdiff.first_weight_lbs,
        "second_weight_time": (
            wdiff.second_weight_at.isoformat() if isinstance(wdiff.second_weight_at, datetime) else None
        ),
        "second_weight_value": wdiff.second_weight_lbs,
        "start_cleaning_time": sc_ts.isoformat() if isinstance(sc_ts, datetime) else None,
        "drying_time": dry_ts.isoformat() if isinstance(dry_ts, datetime) else None,
        "clean_rack_time": clean_ts.isoformat() if isinstance(clean_ts, datetime) else None,
        "sorted_time": sorted_ts.isoformat() if isinstance(sorted_ts, datetime) else None,
        "completion_signal": completion_signal,
    }


def _last_scan_fields(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    last_ev: Mapping[str, Any] | None = None
    last_ts: datetime | None = None
    for ev in events:
        ts = ev.get("scanned_at_parsed")
        if isinstance(ts, datetime) and (last_ts is None or ts > last_ts):
            last_ts = ts
            last_ev = ev
    if not isinstance(last_ev, dict):
        return {"last_scan_purpose": None, "last_scan_rack": None}
    return {
        "last_scan_purpose": last_ev.get("purpose"),
        "last_scan_rack": last_ev.get("rack"),
    }


def _record_from_bag(
    *,
    bid: str,
    meta: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    pending_row: Mapping[str, Any] | None,
    threshold: float,
    period_start: datetime,
    period_end_exclusive: datetime,
    in_pipeline: bool = False,
    in_staging: bool = False,
    in_incoming: bool,
    in_facility_tracker: bool = False,
    completion: Any | None = None,
) -> dict[str, Any]:
    row_meta = dict(pending_row or {})
    merged = {**dict(meta), **row_meta}
    customer = merged.get("name_clean") or merged.get("customer")
    bucket = _bucket_for_row(merged)
    completion = completion if completion is not None else evaluate_bag_completion_v2(events)
    credits = extract_bag_activity_credits(
        bid, events, customer=customer, default_lbs=_safe_float(merged.get("weight_num"))
    )
    period_credits = [
        c for c in credits if credit_in_et_period(c, period_start=period_start, period_end_exclusive=period_end_exclusive)
    ]
    wdiff = evaluate_weight_difference(events, threshold_lbs=threshold)
    has_weigh = any(c.role == ROLE_WEIGHING for c in credits)
    has_start_cleaning = any(is_start_cleaning_purpose(ev.get("purpose")) for ev in events)
    is_rush = _rush_bucket_key(str(merged.get("effective_rush") or merged.get("rush_type") or "")) == "rush"
    svc = _normalized_service_type(merged) or "UNKNOWN"
    is_wf = svc == "WF"
    is_hd = svc == "HD"
    tags: set[str] = set()
    if in_incoming:
        tags.add("ready_for_vendor")
        if is_wf:
            tags.add("rfv_wf")
        elif is_hd:
            tags.add("rfv_hd")
        if bucket:
            tags.add(f"rfv_{bucket}")
            if bucket.startswith("rush"):
                tags.add("rfv_rush")
            elif bucket.startswith("nonrush"):
                tags.add("rfv_non_rush")
            if bucket.startswith("unknown") or bucket == "unknown_service":
                tags.add("rfv_unknown_needs_review")
    if in_facility_tracker:
        tags.add("facility_tracker")
        if bucket:
            tags.add(f"facility_{bucket}")
            if bucket.startswith("unknown") or bucket == "unknown_service":
                tags.add("facility_unknown_needs_review")
    active_eligible = in_pipeline
    hd_production: dict[str, Any] | None = None
    if in_pipeline:
        tags.add("pipeline_work")
        tags.add("active_work")
        if bucket:
            tags.add(f"pipeline_{bucket}")
            tags.add(f"active_{bucket}")
        if is_rush:
            tags.add("wip_rush")
        elif _rush_label(bucket) == "Non-Rush":
            tags.add("wip_non_rush")
        if is_wf:
            tags.add("wip_wf")
            if has_weigh:
                tags.add("shift_weighed")
                tags.add("wf_weighed")
            else:
                tags.add("shift_not_weighed")
                tags.add("wf_not_weighed")
            if not has_start_cleaning:
                tags.add("pending_wash")
                if is_rush:
                    tags.add("pending_wash_rush")
                    tags.add("wf_pending_wash_rush")
                elif rec_rush_label := _rush_label(bucket):
                    if rec_rush_label == "Non-Rush":
                        tags.add("pending_wash_nonrush")
                        tags.add("wf_pending_wash_nonrush")
            if _qualifies_yet_to_fold(pending_row, events, completion):
                tags.add("yet_to_fold")
                tags.add("wf_pending_folding")
        elif is_hd:
            from backend.rinse_hd_production_status import (
                derive_hd_production_status,
                hd_stage_drilldown_tag,
            )

            hd_production = derive_hd_production_status(
                events,
                at_vendor_presence=bool(row_meta.get("at_vendor_presence")),
                logistics_status=merged.get("logistics_status") or merged.get("status"),
                lifecycle_status=row_meta.get("current_lifecycle_status"),
            )
            tags.add("wip_hd")
            stage_tag = hd_stage_drilldown_tag(str(hd_production.get("hd_stage") or ""))
            tags.add(stage_tag)
            if hd_production.get("hd_completed"):
                tags.add("hd_completed")
            if hd_production.get("sent_left"):
                tags.add("hd_sent_left")
            elif hd_production.get("hd_completed"):
                tags.add("hd_still_at_facility")
    if is_wf and wdiff.flagged:
        tags.add("weight_difference")
    elif is_wf and active_eligible and wdiff.unavailable_reason:
        tags.add("weight_difference_unavailable")
    if any(c.role == ROLE_ISSUES for c in period_credits):
        tags.add("issues")
    if any(c.role == ROLE_WORKITEMS for c in period_credits):
        tags.add("workitems")
        if is_hd:
            tags.add("hd_workitems")
    if is_wf and completion.exception_code == "COMPLETED_WITHOUT_FINAL_CLEAN_SCAN":
        tags.add("completed_without_clean")
    if bucket and (bucket.startswith("unknown") or bucket == "unknown_service"):
        tags.add("unknown_speed_service")
    last_scan = None
    last_employee = None
    for ev in events:
        ts = ev.get("scanned_at_parsed")
        if isinstance(ts, datetime) and (last_scan is None or ts > last_scan):
            last_scan = ts
            last_employee = ev.get("user_name")
    status = str(row_meta.get("current_lifecycle_status") or "")
    if is_hd and hd_production:
        status = str(hd_production.get("hd_stage") or status)
    elif not status and completion.completed and is_wf:
        status = FOLDED_COMPLETED
    primary_employee = None
    for role in (ROLE_FOLDING, ROLE_WASHING, ROLE_SORTING, ROLE_WEIGHING):
        match = next((c for c in credits if c.role == role and c.employee), None)
        if match:
            primary_employee = match.employee
            break
    flag_set = {f for c in credits for f in c.flags}
    if completion.exception_code:
        flag_set.add(completion.exception_code)
    last_scan_meta = _last_scan_fields(events)
    wf_audit = _wf_stage_audit_fields(events, completion, wdiff) if is_wf else {}
    hd_audit: dict[str, Any] = {}
    if is_hd and hd_production:
        hd_audit = {
            "workitem_time": hd_production.get("workitem_time"),
            "add_photos_time_after_workitem": hd_production.get("add_photos_time_after_workitem"),
            "hd_started": hd_production.get("hd_started"),
            "hd_completed": hd_production.get("hd_completed"),
            "sent_left_signal": hd_production.get("sent_left_signal"),
        }
    rush_audit: dict[str, Any] = {}
    vd_raw = merged.get("view_date")
    if vd_raw:
        try:
            from backend.rinse_shift_analysis import explain_effective_rush_for_row

            if isinstance(vd_raw, date):
                td = vd_raw
            else:
                td = date.fromisoformat(str(vd_raw)[:10])
            rush_audit = explain_effective_rush_for_row(merged, td)
        except Exception:
            rush_audit = {}
    due_date = rush_audit.get("date_clean") or (
        merged.get("date_clean").isoformat()
        if hasattr(merged.get("date_clean"), "isoformat")
        else merged.get("date_clean")
    )
    return {
        "bag_id": bid,
        "customer": customer,
        "service_type": _normalized_service_type(merged) or "UNKNOWN",
        "rush_bucket": bucket,
        "rush_label": _rush_label(bucket),
        "date_clean": due_date,
        "due_date": due_date,
        "current_status": (
            (hd_production.get("hd_stage_label") if is_hd and hd_production else None)
            or status
            or row_meta.get("lifecycle_status_label")
        ),
        "current_stage": (
            (hd_production.get("hd_stage_label") if is_hd and hd_production else None)
            or status
            or row_meta.get("lifecycle_status_label")
        ),
        "hd_stage": hd_production.get("hd_stage") if hd_production else row_meta.get("hd_stage"),
        "hd_stage_label": hd_production.get("hd_stage_label") if hd_production else row_meta.get("hd_stage_label"),
        "view_date": rush_audit.get("view_date") or row_meta.get("view_date"),
        "effective_rush": rush_audit.get("effective_rush") or merged.get("effective_rush"),
        "computed_rush_label": rush_audit.get("computed_rush_label") or _rush_label(bucket),
        "computed_rush_rule": rush_audit.get("computed_rush_rule"),
        "rush_type_raw": rush_audit.get("rush_type_raw") or merged.get("rush_type") or merged.get("rush_label"),
        "rush_flag_parsed": rush_audit.get("rush_flag_parsed"),
        "last_scan_time": last_scan.isoformat() if isinstance(last_scan, datetime) else None,
        "last_activity_time": last_scan.isoformat() if isinstance(last_scan, datetime) else None,
        "last_scan_purpose": last_scan_meta.get("last_scan_purpose"),
        "last_activity_purpose": last_scan_meta.get("last_scan_purpose"),
        "last_scan_rack": last_scan_meta.get("last_scan_rack"),
        "raw_status": row_meta.get("current_lifecycle_status"),
        "employee": primary_employee or last_employee,
        "flags": sorted(flag_set),
        "completed": completion.completed,
        "completion_kind": completion.completion_kind,
        "completion_exception": completion.exception_code,
        "needs_review": completion.needs_review or bool(row_meta.get("needs_review")),
        "in_scope_a_active": active_eligible,
        "in_pipeline": in_pipeline,
        "in_staging": in_staging,
        "in_ready_for_vendor": in_incoming,
        "weight_difference": {
            "flagged": wdiff.flagged,
            "comparable": wdiff.comparable,
            "first_weight_lbs": wdiff.first_weight_lbs,
            "second_weight_lbs": wdiff.second_weight_lbs,
            "difference_lbs": wdiff.difference_lbs,
            "threshold_lbs": wdiff.threshold_lbs,
            "first_weight_at": wdiff.first_weight_at.isoformat() if isinstance(wdiff.first_weight_at, datetime) else None,
            "second_weight_at": wdiff.second_weight_at.isoformat() if isinstance(wdiff.second_weight_at, datetime) else None,
            "first_weight_user": wdiff.first_weight_user,
            "second_weight_user": wdiff.second_weight_user,
            "unavailable_reason": wdiff.unavailable_reason,
        },
        "activities": [
            {
                "role": c.role,
                "employee": c.employee,
                "activity_at": c.activity_at.isoformat(),
                "needs_review": c.needs_review,
                "flags": list(c.flags),
            }
            for c in period_credits
        ],
        "scan_event_count": len(events),
        "drilldown_tags": sorted(tags),
        "checkout_status": row_meta.get("checkout_status"),
        "special_instructions_raw": row_meta.get("special_instructions_raw"),
        "supply_interpretation": row_meta.get("supply_interpretation"),
        "special_instruction_review": bool(row_meta.get("special_instruction_review")),
        "source": "Scan events" if events else "Portal scrape",
        "source_seen_in": list(merged.get("source_seen_in") or []),
        "baseline_inclusion_reason": merged.get("baseline_inclusion_reason"),
        "live_dashboard": merged.get("live_dashboard"),
        **wf_audit,
        **hd_audit,
    }


def _count_tag(records: list[dict[str, Any]], tag: str) -> int:
    return sum(1 for r in records if tag in (r.get("drilldown_tags") or []))


def _make_drilldown_card(
    label: str,
    count: int | None,
    drilldown_tag: str | None,
    records: list[dict[str, Any]],
    *,
    under_review: bool = False,
    under_review_reason: str | None = None,
) -> dict[str, Any]:
    """Unified drilldown contract: visible count must equal drilldown record count."""
    records_count = _count_tag(records, drilldown_tag) if drilldown_tag else None
    if count is None or drilldown_tag is None:
        return {
            "label": label,
            "count": None,
            "drilldown_tag": drilldown_tag,
            "records_count": records_count,
            "clickable": False,
            "needs_review": True,
            "under_review_reason": under_review_reason or "Under Review",
        }
    parity = int(count) == int(records_count or 0)
    clickable = bool(drilldown_tag) and parity and not under_review
    return {
        "label": label,
        "count": int(count),
        "drilldown_tag": drilldown_tag,
        "records_count": int(records_count or 0),
        "clickable": clickable,
        "needs_review": under_review or not parity,
        "under_review_reason": under_review_reason if under_review else (None if parity else "Count does not match drilldown rows"),
    }


def _cards_parity_ok(cards: Sequence[Mapping[str, Any]]) -> bool:
    actionable = [c for c in cards if c.get("drilldown_tag") and c.get("count") is not None]
    if not actionable:
        return True
    return all(not c.get("needs_review") for c in actionable)


def _build_facility_block_cards(
    block: Mapping[str, Any],
    records: list[dict[str, Any]],
    prefix: str,
) -> list[dict[str, Any]]:
    status = block.get("status") or {}
    cards = [
        _make_drilldown_card("Total", block.get("total"), prefix, records),
        _make_drilldown_card("Rush", block.get("rush_total"), f"{prefix}_rush", records),
        _make_drilldown_card("Non-Rush", block.get("nonrush_total"), f"{prefix}_non_rush", records),
        _make_drilldown_card("Rush WF", block.get("rush_wf"), f"{prefix}_rush_wf", records),
        _make_drilldown_card("Rush HD", block.get("rush_hd"), f"{prefix}_rush_hd", records),
        _make_drilldown_card("Non-Rush WF", block.get("nonrush_wf"), f"{prefix}_nonrush_wf", records),
        _make_drilldown_card("Non-Rush HD", block.get("nonrush_hd"), f"{prefix}_nonrush_hd", records),
        _make_drilldown_card("Pending", status.get("pending"), f"{prefix}_pending", records),
        _make_drilldown_card("Completed", status.get("completed"), f"{prefix}_completed", records),
        _make_drilldown_card("Sent / Left", status.get("left_sent"), f"{prefix}_left_sent", records),
        _make_drilldown_card("Still at Facility", status.get("still_at_facility"), f"{prefix}_still_at_facility", records),
    ]
    unknown = int(block.get("unknown_needs_review") or 0)
    if unknown:
        cards.append(
            _make_drilldown_card(
                "Unknown / Review",
                unknown,
                f"{prefix}_unknown_needs_review",
                records,
            )
        )
    return cards


def _attach_facility_drilldown_cards(tracker: dict[str, Any], records: list[dict[str, Any]]) -> None:
    for key in ("entered_today", "carryover", "total_workload"):
        block = tracker.get(key)
        if not isinstance(block, dict):
            continue
        prefix = str(block.get("drilldown_prefix") or "ft_total")
        block["cards"] = _build_facility_block_cards(block, records, prefix)
        block["parity_ok"] = _cards_parity_ok(block["cards"])
    total = tracker.get("total_workload") or {}
    entered = tracker.get("entered_today") or {}
    carryover = tracker.get("carryover") or {}
    total_status = total.get("status") or {}
    tracker["summary_cards"] = [
        _make_drilldown_card("Total Workload", total.get("total"), "ft_total", records),
        _make_drilldown_card("Received Today", entered.get("total"), "ft_entered", records),
        _make_drilldown_card("Carryover", carryover.get("total"), "ft_carryover", records),
        _make_drilldown_card("Pending", total_status.get("pending"), "ft_total_pending", records),
        _make_drilldown_card("Completed", total_status.get("completed"), "ft_total_completed", records),
        _make_drilldown_card("Sent / Left", total_status.get("left_sent"), "ft_total_left_sent", records),
    ]
    tracker["summary_parity_ok"] = _cards_parity_ok(tracker["summary_cards"])


def _build_rfv_drilldown_cards(section: Mapping[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not section.get("live"):
        return []
    return [
        {
            **_make_drilldown_card("Ready for Vendor Total", section.get("total"), "ready_for_vendor", records),
            "level": 1,
        },
        {
            **_make_drilldown_card("Rush", section.get("rush_total"), "rfv_rush", records),
            "level": 1,
        },
        {
            **_make_drilldown_card("Non-Rush", section.get("nonrush_total"), "rfv_non_rush", records),
            "level": 1,
        },
        {
            **_make_drilldown_card("Rush WF", section.get("rush_wf"), "rfv_rush_wf", records),
            "level": 2,
            "parent": "rush",
        },
        {
            **_make_drilldown_card("Rush HD", section.get("rush_hd"), "rfv_rush_hd", records),
            "level": 2,
            "parent": "rush",
        },
        {
            **_make_drilldown_card("Non-Rush WF", section.get("nonrush_wf"), "rfv_nonrush_wf", records),
            "level": 2,
            "parent": "non_rush",
        },
        {
            **_make_drilldown_card("Non-Rush HD", section.get("nonrush_hd"), "rfv_nonrush_hd", records),
            "level": 2,
            "parent": "non_rush",
        },
        {
            **_make_drilldown_card(
                "Unknown Review",
                section.get("unknown_needs_review"),
                "rfv_unknown_needs_review",
                records,
            ),
            "level": 2,
            "parent": "all",
        },
    ]


def _attach_rfv_drilldown_cards(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["cards"] = _build_rfv_drilldown_cards(section, records)
    section["parity_ok"] = _cards_parity_ok(section.get("cards") or [])


def _build_drilldown_parity_audit(payload_sections: Mapping[str, Any]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    card_keys = ("cards", "breakdown_cards", "summary_cards", "wf_cards", "hd_cards", "monitor_cards")
    for section_name, section in payload_sections.items():
        if not isinstance(section, dict):
            continue
        for key in card_keys:
            cards = section.get(key)
            if not cards:
                continue
            for card in cards:
                if not card.get("needs_review") or not card.get("drilldown_tag"):
                    continue
                mismatches.append(
                        {
                            "section": section_name,
                            "card_group": key,
                            "label": card.get("label"),
                            "drilldown_tag": card.get("drilldown_tag"),
                            "count": card.get("count"),
                            "records_count": card.get("records_count"),
                            "reason": card.get("under_review_reason"),
                        }
                    )
    return {
        "ok": len(mismatches) == 0,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _record_matches_rush(rec: Mapping[str, Any], rush_filter: str | None) -> bool:
    if not rush_filter or rush_filter == "all":
        return True
    label = str(rec.get("rush_label") or "")
    if rush_filter == "rush":
        return label == "Rush"
    if rush_filter == "non_rush":
        return label == "Non-Rush"
    return True


def _count_tag_by_rush(
    records: list[dict[str, Any]],
    tag: str,
    *,
    rush_filter: str | None = None,
    active_only: bool = False,
) -> int:
    return sum(
        1
        for r in records
        if tag in (r.get("drilldown_tags") or [])
        and _record_matches_rush(r, rush_filter)
        and (not active_only or r.get("in_scope_a_active"))
    )


def _metric_split_counts(
    records: list[dict[str, Any]],
    tag: str,
    *,
    active_only: bool = False,
    rush_only_metric: bool = False,
) -> dict[str, int]:
    if rush_only_metric:
        return {
            "all": _count_tag_by_rush(records, tag, rush_filter="rush", active_only=active_only),
            "rush": _count_tag_by_rush(records, tag, rush_filter="rush", active_only=active_only),
            "non_rush": 0,
        }
    return {
        "all": _count_tag_by_rush(records, tag, rush_filter="all", active_only=active_only),
        "rush": _count_tag_by_rush(records, tag, rush_filter="rush", active_only=active_only),
        "non_rush": _count_tag_by_rush(records, tag, rush_filter="non_rush", active_only=active_only),
    }


def _build_shift_status(records: list[dict[str, Any]], *, threshold: float, last_rush_wash: dict | None) -> dict[str, Any]:
    active_records = [r for r in records if r.get("in_scope_a_active")]
    wf_active = [r for r in active_records if r.get("service_type") == "WF"]
    hd_active = [r for r in active_records if r.get("service_type") == "HD"]
    flagged = _count_tag([r for r in records if r.get("service_type") == "WF"], "weight_difference")
    unavailable = _count_tag(wf_active, "weight_difference_unavailable")
    return {
        "weighed": _metric_split_counts(wf_active, "wf_weighed", active_only=True),
        "not_weighed": _metric_split_counts(wf_active, "wf_not_weighed", active_only=True),
        "issues": _metric_split_counts(records, "issues"),
        "workitems": _metric_split_counts(records, "workitems"),
        "weight_difference": {
            "flagged": flagged,
            "unavailable": unavailable,
            "all": flagged,
            "rush": _count_tag_by_rush(
                [r for r in records if r.get("service_type") == "WF"],
                "weight_difference",
                rush_filter="rush",
            ),
            "non_rush": _count_tag_by_rush(
                [r for r in records if r.get("service_type") == "WF"],
                "weight_difference",
                rush_filter="non_rush",
            ),
        },
        "weight_difference_threshold_lbs": threshold,
        "weight_difference_status": (
            "flagged"
            if flagged
            else ("unavailable" if unavailable else "none")
        ),
        "rush_pending_wash": _metric_split_counts(wf_active, "wf_pending_wash_rush", active_only=True, rush_only_metric=True),
        "last_rush_wash": last_rush_wash,
        "yet_to_fold": _metric_split_counts(wf_active, "wf_pending_folding", active_only=True),
        "wf_pipeline_total": len(wf_active),
        "hd_pipeline_total": len(hd_active),
        "source": "WF-only weighing/folding; HD uses separate wip_hd stages",
    }


def _apply_current_facility_snapshot_tags(
    records: list[dict[str, Any]],
    *,
    at_facility_ids: set[str],
    at_facility_meta: Mapping[str, Mapping[str, Any]] | None = None,
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    qualifies_yet_to_fold: Any,
    completion_events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> None:
    """Tag unified at-VeeWash bags for Current Facility Snapshot + in-progress WIP."""
    from backend.rinse_current_facility_snapshot import (
        CFS_COMPLETED_STILL,
        CFS_IN_PROGRESS,
        CFS_SENT_LEFT,
        bag_is_operationally_complete,
        bag_is_sent_left_from_facility,
        classify_current_facility_bag,
        hd_in_progress_bucket_and_reason,
        wf_in_progress_bucket_and_reason,
    )
    from backend.rinse_current_facility_snapshot import (
        _has_drying as cfs_has_drying,
        _has_start_cleaning as cfs_has_start_cleaning,
        _has_weight_entry as cfs_has_weight_entry,
    )
    from backend.rinse_hd_production_status import derive_hd_production_status

    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        if bid not in at_facility_ids:
            continue
        unified_row = (at_facility_meta or {}).get(bid) or {}
        if unified_row.get("source_seen_in"):
            rec["source_seen_in"] = list(unified_row["source_seen_in"])
        events = events_by_bag.get(bid) or []
        completion_events = (completion_events_by_bag or events_by_bag).get(bid) or []
        pending_row = pending_by_bag.get(bid)
        meta = meta_by_bag.get(bid) or {}
        completion = completions_by_bag.get(bid)
        svc = str(rec.get("service_type") or unified_row.get("service_type") or "").upper()
        in_staging = bool((pending_row or {}).get("in_active_staging") or unified_row.get("in_active_staging"))
        sent_left = bag_is_sent_left_from_facility(
            pending_row,
            completion,
            meta,
            events,
            completion_events=completion_events,
        )
        op_complete = bag_is_operationally_complete(
            service_type=svc,
            completion=completion,
            events=events,
            pending_row=pending_row,
            meta=meta,
            completion_events=completion_events,
            record=rec,
        )
        category = classify_current_facility_bag(
            in_active_staging=True,
            sent_left=sent_left,
            operationally_complete=op_complete,
        )
        tags = set(rec.get("drilldown_tags") or [])
        bucket = str(rec.get("rush_bucket") or "")
        rec["facility_snapshot_category"] = category
        rec["in_facility_snapshot"] = category in (CFS_IN_PROGRESS, CFS_COMPLETED_STILL)
        if not in_staging and "orders_staging" not in (rec.get("source_seen_in") or []):
            rec["snapshot_bucket_reason"] = (
                rec.get("snapshot_bucket_reason")
                or "At VeeWash via registry/presence — not in active orders_staging"
            )
        if category == CFS_SENT_LEFT:
            tags.add("cfs_sent_left")
            if svc == "HD":
                tags.add("hd_sent_left")
            rec["wip_bucket"] = None
            rec["wip_bucket_reason"] = "Sent/left — excluded from At Facility Total"
            rec["drilldown_tags"] = sorted(tags)
            continue
        tags.add("cfs_total")
        if bucket:
            tags.add(f"cfs_total_{bucket}")
            if bucket.startswith("rush"):
                tags.add("cfs_total_rush")
            elif bucket.startswith("nonrush"):
                tags.add("cfs_total_non_rush")
        if category == CFS_IN_PROGRESS:
            tags.add("cfs_in_progress")
            if bucket.startswith("rush"):
                tags.add("cfs_in_progress_rush")
            elif bucket.startswith("nonrush"):
                tags.add("cfs_in_progress_non_rush")
            if svc == "WF":
                tags.add("wip_wf_in_progress")
                has_weigh = cfs_has_weight_entry(events) or any(
                    t in tags for t in ("wf_weighed", "shift_weighed")
                )
                has_sc = cfs_has_start_cleaning(events)
                has_dry = cfs_has_drying(events)
                pending_fold = qualifies_yet_to_fold(pending_row, events, completion)
                wip_tag, reason = wf_in_progress_bucket_and_reason(
                    has_weigh=has_weigh,
                    has_start_cleaning=has_sc,
                    has_drying=has_dry,
                    pending_folding=pending_fold,
                )
                tags.add(wip_tag)
                rec["wip_bucket"] = wip_tag
                rec["wip_bucket_reason"] = reason
                rec["snapshot_bucket_reason"] = reason
            elif svc == "HD":
                tags.add("wip_hd_in_progress")
                hd_prod = derive_hd_production_status(
                    events,
                    at_vendor_presence=True,
                    logistics_status=meta.get("logistics_status") or meta.get("status"),
                    lifecycle_status=(pending_row or {}).get("current_lifecycle_status"),
                )
                wip_tag, reason = hd_in_progress_bucket_and_reason(hd_production=hd_prod)
                tags.add(wip_tag)
                rec["wip_bucket"] = wip_tag
                rec["wip_bucket_reason"] = reason
                rec["snapshot_bucket_reason"] = reason
        elif category == CFS_COMPLETED_STILL:
            tags.add("cfs_completed_still_at_facility")
            tags.add("cfs_completed_still")
            if svc == "WF":
                tags.add("wf_completed_by_scan")
            elif svc == "HD":
                tags.add("hd_completed")
            rec["wip_bucket"] = None
            rec["wip_bucket_reason"] = "Operationally complete but still at VeeWash (not sent/left)"
            rec["snapshot_bucket_reason"] = rec["wip_bucket_reason"]
        rec["drilldown_tags"] = sorted(tags)


def _apply_due_today_snapshot_tags(
    records: list[dict[str, Any]],
    *,
    today: date,
    due_today_ids: set[str] | None = None,
    due_today_meta: Mapping[str, Mapping[str, Any]] | None = None,
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    completion_events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> None:
    from backend.rinse_current_facility_snapshot import (
        SCAN_DTS_COMPLETED,
        SCAN_DTS_TOTAL,
        SCAN_DTS_YET_TO_PROCESS,
        bag_is_due_today_processed,
        bag_is_operationally_complete,
        bag_is_sent_left_from_facility,
        parse_record_date,
        record_is_due_today,
    )

    due_today_ids = due_today_ids or set()
    due_today_meta = due_today_meta or {}

    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        pending_row = pending_by_bag.get(bid)
        meta = meta_by_bag.get(bid) or {}
        unified_dt = due_today_meta.get(bid) or {}
        if unified_dt.get("source_seen_in"):
            existing = list(rec.get("source_seen_in") or [])
            for s in unified_dt["source_seen_in"]:
                if s not in existing:
                    existing.append(s)
            rec["source_seen_in"] = existing
        if not rec.get("date_clean"):
            dc_raw = (pending_row or {}).get("date_clean") or meta.get("date_clean")
            dc = parse_record_date(dc_raw)
            if dc:
                iso = dc.isoformat()
                rec["date_clean"] = iso
                rec["due_date"] = iso
        is_due = bid in due_today_ids or record_is_due_today(rec, today)
        if not is_due:
            dc = parse_record_date(
                (pending_row or {}).get("date_clean") or meta.get("date_clean") or rec.get("due_date")
            )
            if dc != today:
                continue
        events = events_by_bag.get(bid) or []
        completion_events = (completion_events_by_bag or events_by_bag).get(bid) or []
        pending_row = pending_by_bag.get(bid)
        meta = meta_by_bag.get(bid) or {}
        completion = completions_by_bag.get(bid)
        svc = str(rec.get("service_type") or "").upper()
        bucket = str(rec.get("rush_bucket") or "")
        sent_left = bag_is_sent_left_from_facility(
            pending_row,
            completion,
            meta,
            events,
            completion_events=completion_events,
        )
        op_complete = bag_is_operationally_complete(
            service_type=svc,
            completion=completion,
            events=events,
            pending_row=pending_row,
            meta=meta,
            completion_events=completion_events,
            record=rec,
        )
        processed = bag_is_due_today_processed(
            operationally_complete=op_complete,
            sent_left=sent_left,
        )
        tags = set(rec.get("drilldown_tags") or [])
        tags.add("dts_total")
        tags.add(SCAN_DTS_TOTAL)
        if bucket:
            tags.add(f"dts_total_{bucket}")
            if bucket.startswith("rush"):
                tags.add("dts_total_rush")
            elif bucket.startswith("nonrush"):
                tags.add("dts_total_non_rush")
        if processed:
            tags.add("dts_completed_processed")
            tags.add(SCAN_DTS_COMPLETED)
            rec["scan_dts_bucket_reason"] = "Scan-inferred: due today — operationally complete or sent/left (scan evidence)"
            rec["due_today_bucket_reason"] = rec["scan_dts_bucket_reason"]
        else:
            tags.add("dts_yet_to_process")
            tags.add(SCAN_DTS_YET_TO_PROCESS)
            rec["scan_dts_bucket_reason"] = "Scan-inferred: due today — not yet complete by scan rules"
            rec["due_today_bucket_reason"] = rec["scan_dts_bucket_reason"]
            if "ready_for_vendor_presence" in (rec.get("source_seen_in") or []):
                tags.add("due_today_rfv_or_incoming")
            if "orders_staging" not in (rec.get("source_seen_in") or []):
                tags.add("due_today_missing_from_staging")
            if bucket.startswith("rush"):
                tags.add("dts_rush_pending")
            elif bucket.startswith("nonrush"):
                tags.add("dts_non_rush_pending")
            if svc == "WF":
                tags.add("dts_wf_pending")
            elif svc == "HD":
                tags.add("dts_hd_pending")
        if not rec.get("snapshot_bucket_reason"):
            rec["snapshot_bucket_reason"] = rec.get("due_today_bucket_reason")
        rec["drilldown_tags"] = sorted(tags)


def _build_current_facility_snapshot_section(
    records: list[dict[str, Any]],
    dashboard_snapshot: Mapping[str, Any],
    *,
    rinse_home_at_veewash: int | None = None,
    rinse_home_yet_to_process: int | None = None,
    vendor_home_view: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.rinse_current_facility_snapshot import (
        VENDOR_HOME_REFERENCE,
        build_vendor_home_reconciliation,
        manual_vendor_home_counts,
    )

    at_facility = _count_tag(records, "cfs_total")
    in_progress = _count_tag(records, "cfs_in_progress")
    completed_still = _count_tag(records, "cfs_completed_still_at_facility")
    sent_left = _count_tag(records, "cfs_sent_left")
    staging_total = int(dashboard_snapshot.get("unique_bag_count") or dashboard_snapshot.get("total_orders") or 0)

    internal_cards = [
        _make_drilldown_card("Dashboard At Facility", at_facility, "cfs_total", records),
        _make_drilldown_card("Scan-Inferred In Progress", in_progress, "cfs_in_progress", records),
        _make_drilldown_card("Scan-Inferred Completed Still at Facility", completed_still, "cfs_completed_still_at_facility", records),
    ]
    breakdown_cards = [
        _make_drilldown_card("Rush", _count_tag(records, "cfs_total_rush"), "cfs_total_rush", records),
        _make_drilldown_card("Non-Rush", _count_tag(records, "cfs_total_non_rush"), "cfs_total_non_rush", records),
        _make_drilldown_card("Rush WF", _count_tag(records, "cfs_total_rush_wf"), "cfs_total_rush_wf", records),
        _make_drilldown_card("Rush HD", _count_tag(records, "cfs_total_rush_hd"), "cfs_total_rush_hd", records),
        _make_drilldown_card("Non-Rush WF", _count_tag(records, "cfs_total_nonrush_wf"), "cfs_total_nonrush_wf", records),
        _make_drilldown_card("Non-Rush HD", _count_tag(records, "cfs_total_nonrush_hd"), "cfs_total_nonrush_hd", records),
    ]

    internal_scan_view = {
        "source": "internal_scan_events",
        "description": "Operational scan-inferred status — not Vendor Home portal state",
        "at_facility_total": at_facility,
        "in_progress": in_progress,
        "completed_still_at_facility": completed_still,
        "sent_left": sent_left,
        "cards": internal_cards,
        "breakdown_cards": breakdown_cards,
        "parity_ok": _cards_parity_ok(internal_cards + breakdown_cards),
        "identity_ok": in_progress + completed_still == at_facility,
    }

    vh_view = dict(vendor_home_view or {})
    manual = manual_vendor_home_counts()
    ref_at = rinse_home_at_veewash if rinse_home_at_veewash is not None else manual.get("at_veewash_total")
    ref_proc = rinse_home_yet_to_process if rinse_home_yet_to_process is not None else manual.get("at_veewash_yet_to_process")

    reconciliation = build_vendor_home_reconciliation(
        at_facility=at_facility,
        in_progress=in_progress,
        completed_still=completed_still,
        rinse_home_at_veewash=ref_at,
        rinse_home_yet_to_process=ref_proc,
    )
    reconciliation["staging_unique_bag_count"] = staging_total
    reconciliation["sent_left"] = sent_left
    reconciliation["vendor_home_view_source"] = vh_view.get("source", "manual_screenshot")
    reconciliation["internal_scan_at_facility"] = at_facility
    reconciliation["internal_scan_in_progress"] = in_progress
    reconciliation["ok"] = bool(internal_scan_view["identity_ok"])
    reconciliation["vendor_home_parity_ok"] = False
    reconciliation["comparison_status"] = "Needs Review — Vendor Home uses portal state; internal scan view differs"

    return {
        "source": "vendor_home_parity + internal_scan",
        "description": "Vendor Home portal view vs scan-inferred operational view",
        "vendor_home_view": vh_view,
        "internal_scan_view": internal_scan_view,
        "at_facility_total": at_facility,
        "in_progress": in_progress,
        "completed_still_at_facility": completed_still,
        "sent_left": sent_left,
        "sent_left_excluded_from_total": sent_left,
        "cards": internal_cards,
        "breakdown_cards": breakdown_cards,
        "parity_ok": internal_scan_view["parity_ok"],
        "reconciliation": reconciliation,
        "vendor_home_reconciliation": reconciliation,
    }


def _build_due_today_snapshot_section(
    records: list[dict[str, Any]],
    *,
    today: date,
    vendor_home_view: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.rinse_current_facility_snapshot import (
        SCAN_DTS_COMPLETED,
        SCAN_DTS_TOTAL,
        SCAN_DTS_YET_TO_PROCESS,
        build_due_today_reconciliation,
        manual_vendor_home_counts,
    )

    due_total = _count_tag(records, SCAN_DTS_TOTAL)
    yet_to_process = _count_tag(records, SCAN_DTS_YET_TO_PROCESS)
    completed = _count_tag(records, SCAN_DTS_COMPLETED)

    internal_cards = [
        _make_drilldown_card("Dashboard Due Today Total", due_total, SCAN_DTS_TOTAL, records),
        _make_drilldown_card("Scan-Inferred Due Today Pending", yet_to_process, SCAN_DTS_YET_TO_PROCESS, records),
        _make_drilldown_card("Scan-Inferred Due Today Completed", completed, SCAN_DTS_COMPLETED, records),
    ]
    breakdown_cards = [
        _make_drilldown_card("Rush Due Today", _count_tag(records, "dts_total_rush"), "dts_total_rush", records),
        _make_drilldown_card("Non-Rush Due Today", _count_tag(records, "dts_total_non_rush"), "dts_total_non_rush", records),
        _make_drilldown_card("Rush WF Due Today", _count_tag(records, "dts_total_rush_wf"), "dts_total_rush_wf", records),
        _make_drilldown_card("Rush HD Due Today", _count_tag(records, "dts_total_rush_hd"), "dts_total_rush_hd", records),
        _make_drilldown_card("Non-Rush WF Due Today", _count_tag(records, "dts_total_nonrush_wf"), "dts_total_nonrush_wf", records),
        _make_drilldown_card("Non-Rush HD Due Today", _count_tag(records, "dts_total_nonrush_hd"), "dts_total_nonrush_hd", records),
    ]

    internal_scan_view = {
        "source": "internal_scan_events",
        "description": "Scan-inferred due-today status — not Vendor Home portal processing state",
        "due_today_total": due_total,
        "due_today_yet_to_process": yet_to_process,
        "due_today_completed_processed": completed,
        "cards": internal_cards,
        "breakdown_cards": breakdown_cards,
        "parity_ok": _cards_parity_ok(internal_cards + breakdown_cards),
        "identity_ok": yet_to_process + completed == due_total,
    }

    vh_view = dict(vendor_home_view or {})
    manual = manual_vendor_home_counts()
    reconciliation = build_due_today_reconciliation(
        due_today_total=due_total,
        yet_to_process=yet_to_process,
        completed_processed=completed,
        rinse_due_today_total=manual.get("due_today_total"),
        rinse_due_today_yet_to_process=manual.get("due_today_yet_to_process"),
    )
    reconciliation["vendor_home_view_source"] = vh_view.get("source", "manual_screenshot")
    reconciliation["internal_scan_due_today"] = due_total
    reconciliation["internal_scan_pending"] = yet_to_process
    reconciliation["ok"] = bool(internal_scan_view["identity_ok"])
    reconciliation["vendor_home_parity_ok"] = False
    reconciliation["comparison_status"] = "Needs Review — Vendor Home due-today pending uses portal state"

    return {
        "source": "vendor_home_parity + internal_scan",
        "description": "Vendor Home due-today view vs scan-inferred due-today view",
        "view_date": today.isoformat(),
        "vendor_home_view": vh_view,
        "internal_scan_view": internal_scan_view,
        "due_today_total": due_total,
        "due_today_yet_to_process": yet_to_process,
        "due_today_completed_processed": completed,
        "cards": internal_cards,
        "breakdown_cards": breakdown_cards,
        "parity_ok": internal_scan_view["parity_ok"],
        "reconciliation": reconciliation,
    }


def _build_due_today_wip_section(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Due Today WIP — scan-inferred yet-to-process due today only."""
    from backend.rinse_current_facility_snapshot import SCAN_DTS_YET_TO_PROCESS

    pending = [r for r in records if SCAN_DTS_YET_TO_PROCESS in (r.get("drilldown_tags") or [])]
    wf_pending = [r for r in pending if r.get("service_type") == "WF"]
    hd_pending = [r for r in pending if r.get("service_type") == "HD"]
    rush_pending = [r for r in pending if r.get("rush_label") == "Rush"]
    nonrush_pending = [r for r in pending if r.get("rush_label") == "Non-Rush"]

    cards = [
        _make_drilldown_card("Scan-Inferred Due Today Pending", len(pending), SCAN_DTS_YET_TO_PROCESS, records),
        _make_drilldown_card("Due Today WF Pending", len(wf_pending), "dts_wf_pending", records),
        _make_drilldown_card("Due Today HD Pending", len(hd_pending), "dts_hd_pending", records),
        _make_drilldown_card("Due Today Rush Pending", len(rush_pending), "dts_rush_pending", records),
        _make_drilldown_card("Due Today Non-Rush Pending", len(nonrush_pending), "dts_non_rush_pending", records),
    ]
    return {
        "scope": SCAN_DTS_YET_TO_PROCESS,
        "summary": {"total": len(pending), "wf": len(wf_pending), "hd": len(hd_pending)},
        "cards": cards,
        "parity_ok": _cards_parity_ok(cards),
    }


def _build_wip_sections(records: list[dict[str, Any]], target_date: date) -> dict[str, Any]:
    """WIP — in-progress at facility only (Yet to Process), not day workload history."""
    in_progress = [r for r in records if "cfs_in_progress" in (r.get("drilldown_tags") or [])]
    wf = [r for r in in_progress if r.get("service_type") == "WF"]
    hd = [r for r in in_progress if r.get("service_type") == "HD"]

    wf_counts = {
        "total": len(wf),
        "not_weighed": _count_tag(wf, "wf_not_weighed"),
        "weighed_not_started": _count_tag(wf, "wf_weighed_not_started"),
        "started_washing": _count_tag(wf, "wf_started_washing"),
        "pending_drying": _count_tag(wf, "wf_pending_drying"),
        "pending_folding": _count_tag(wf, "wf_pending_folding"),
    }
    hd_counts = {
        "total": len(hd),
        "not_started": _count_tag(hd, "hd_not_started"),
        "started_cleaning": _count_tag(hd, "hd_started_cleaning"),
    }

    summary_cards = [
        _make_drilldown_card("Scan-Inferred In Progress", len(in_progress), "cfs_in_progress", records),
        _make_drilldown_card("WF Scan-Inferred In Progress", len(wf), "wip_wf_in_progress", records),
        _make_drilldown_card("HD Scan-Inferred In Progress", len(hd), "wip_hd_in_progress", records),
    ]
    wf_completed = _count_tag(records, "wf_completed_by_scan")
    hd_completed = _count_tag(records, "hd_completed")
    hd_sent_left = _count_tag(records, "hd_sent_left")

    wf_cards = [
        _make_drilldown_card("WF Total In Progress", wf_counts["total"], "wip_wf_in_progress", records),
        _make_drilldown_card("WF Not Weighed", wf_counts["not_weighed"], "wf_not_weighed", records),
        _make_drilldown_card("WF Weighed — Not Started", wf_counts["weighed_not_started"], "wf_weighed_not_started", records),
        _make_drilldown_card("WF Started Washing", wf_counts["started_washing"], "wf_started_washing", records),
        _make_drilldown_card("WF Pending Drying", wf_counts["pending_drying"], "wf_pending_drying", records),
        _make_drilldown_card("WF Pending Folding", wf_counts["pending_folding"], "wf_pending_folding", records),
        _make_drilldown_card("WF Completed by Scan", wf_completed, "wf_completed_by_scan", records),
    ]
    hd_cards = [
        _make_drilldown_card("HD Total In Progress", hd_counts["total"], "wip_hd_in_progress", records),
        _make_drilldown_card("HD Not Started", hd_counts["not_started"], "hd_not_started", records),
        _make_drilldown_card("HD Started Cleaning", hd_counts["started_cleaning"], "hd_started_cleaning", records),
        _make_drilldown_card("HD Completed", hd_completed, "hd_completed", records),
        _make_drilldown_card("HD Sent / Left", hd_sent_left, "hd_sent_left", records),
    ]

    return {
        "view_date": target_date.isoformat(),
        "scope": "cfs_in_progress",
        "summary": {
            "total": len(in_progress),
            "wf_total": len(wf),
            "hd_total": len(hd),
        },
        "summary_cards": summary_cards,
        "wf": wf_counts,
        "wf_cards": wf_cards,
        "hd": hd_counts,
        "hd_cards": hd_cards,
        "parity_ok": _cards_parity_ok(summary_cards + wf_cards + hd_cards),
    }


def _build_stage_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.rinse_bag_lifecycle_status import PENDING_WEIGHING, WEIGHED_NOT_STARTED
    from backend.rinse_hd_production_status import is_hd_wrongly_in_wf_weighing

    wf_ids: list[str] = []
    hd_ids: list[str] = []
    hd_wrongly: list[str] = []
    wf_weighed: list[str] = []
    wf_not_weighed: list[str] = []
    hd_not_started: list[str] = []
    hd_started: list[str] = []
    hd_completed: list[str] = []
    unknown_svc: list[str] = []
    missing_edd: list[str] = []

    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        svc = str(rec.get("service_type") or "").strip().upper()
        tags = rec.get("drilldown_tags") or []
        if svc == "WF":
            wf_ids.append(bid)
            if "wf_weighed" in tags:
                wf_weighed.append(bid)
            if "wf_not_weighed" in tags:
                wf_not_weighed.append(bid)
        elif svc == "HD":
            hd_ids.append(bid)
            if "hd_not_started" in tags:
                hd_not_started.append(bid)
            if "hd_started_cleaning" in tags:
                hd_started.append(bid)
            if "hd_completed" in tags or "hd_still_at_facility" in tags:
                hd_completed.append(bid)
        else:
            unknown_svc.append(bid)
        if not rec.get("date_clean"):
            missing_edd.append(bid)
        if is_hd_wrongly_in_wf_weighing(
            service_type=svc,
            lifecycle_status=rec.get("current_status") or rec.get("current_lifecycle_status"),
            drilldown_tags=tags,
        ):
            hd_wrongly.append(bid)
        status = str(rec.get("current_status") or "").upper()
        if svc == "HD" and status in (PENDING_WEIGHING, WEIGHED_NOT_STARTED):
            if bid not in hd_wrongly:
                hd_wrongly.append(bid)

    return {
        "wf_ids": sorted(set(wf_ids)),
        "hd_ids": sorted(set(hd_ids)),
        "hd_wrongly_in_weighing_ids": sorted(set(hd_wrongly)),
        "wf_weighed_ids": sorted(set(wf_weighed)),
        "wf_not_weighed_ids": sorted(set(wf_not_weighed)),
        "hd_not_started_ids": sorted(set(hd_not_started)),
        "hd_started_ids": sorted(set(hd_started)),
        "hd_completed_ids": sorted(set(hd_completed)),
        "records_with_unknown_service": sorted(set(unknown_svc)),
        "records_with_missing_edd": sorted(set(missing_edd)),
        "reconciliation_ok": len(hd_wrongly) == 0,
    }


def _weight_entry_counts(events: Sequence[Mapping[str, Any]]) -> tuple[int, list[str]]:
    weights = [ev for ev in events if is_weight_entry_purpose(ev.get("purpose"))]
    non_parseable: list[str] = []
    parseable = 0
    for ev in weights:
        raw = ev.get("weight_lbs") or ev.get("weight") or ev.get("purpose")
        try:
            if raw is not None and float(str(raw).split()[0]) > 0:
                parseable += 1
                continue
        except (TypeError, ValueError):
            pass
        non_parseable.append(str(ev.get("purpose") or ""))
    return len(weights), non_parseable


def _collect_active_bucket_ids(
    records: list[dict[str, Any]],
    pending_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, list[str]]:
    buckets = {
        "rush_wf_ids": "pipeline_rush_wf",
        "rush_hd_ids": "pipeline_rush_hd",
        "nonrush_wf_ids": "pipeline_nonrush_wf",
        "nonrush_hd_ids": "pipeline_nonrush_hd",
        "unknown_ids": None,
    }
    out: dict[str, list[str]] = {k: [] for k in buckets}
    seen: list[str] = []
    dupes: list[str] = []
    excluded: list[dict[str, str]] = []
    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        tags = set(rec.get("drilldown_tags") or [])
        if "pipeline_work" in tags or "active_work" in tags:
            if bid in seen:
                dupes.append(bid)
            seen.append(bid)
            for key, tag in buckets.items():
                if tag and tag in tags:
                    out[key].append(bid)
            if any(t.startswith("pipeline_unknown") for t in tags) or "unknown_speed_service" in tags:
                out["unknown_ids"].append(bid)
        elif rec.get("in_ready_for_vendor"):
            excluded.append({"bag_id": bid, "reason": "ready_for_vendor"})
        elif rec.get("completed"):
            excluded.append({"bag_id": bid, "reason": "completed_scan_evidence"})
        elif not rec.get("in_scope_a_active"):
            pending_row = (pending_by_bag or {}).get(bid)
            if pending_row and not pending_row.get("in_active_staging"):
                if pending_row.get("registry_supplement"):
                    excluded.append({"bag_id": bid, "reason": "registry_supplement"})
                elif pending_row.get("presence_source"):
                    excluded.append({"bag_id": bid, "reason": "presence_supplement"})
                else:
                    excluded.append({"bag_id": bid, "reason": "not_in_active_staging"})
            elif pending_row and str(pending_row.get("current_lifecycle_status") or "") in LIFECYCLE_COMPLETED_STATUSES:
                excluded.append({"bag_id": bid, "reason": "lifecycle_completed"})
            elif bid:
                excluded.append({"bag_id": bid, "reason": "not_in_active_staging_or_completed"})
    for key in out:
        out[key] = sorted(set(out[key]))
    return {"bucket_ids": out, "duplicate_ids": sorted(set(dupes)), "excluded_ids": excluded}


def _build_debug_audit(
    *,
    pending: Mapping[str, Any],
    ready_for_vendor: dict[str, Any],
    active_work: dict[str, Any],
    rush_checkout: dict[str, Any],
    records: list[dict[str, Any]],
    employee_diagnostics: dict[str, Any],
    shift_status: dict[str, Any],
    events_by_bag: dict[str, list[dict[str, Any]]] | None = None,
    dashboard_snapshot: Mapping[str, Any] | None = None,
    dashboard_reconciliation: Mapping[str, Any] | None = None,
    facility_tracker: Mapping[str, Any] | None = None,
    scope_overlap: Mapping[str, Any] | None = None,
    pipeline_debug: Mapping[str, Any] | None = None,
    rfv_sync: Mapping[str, Any] | None = None,
    av_sync: Mapping[str, Any] | None = None,
    current_facility_snapshot: Mapping[str, Any] | None = None,
    due_today_snapshot: Mapping[str, Any] | None = None,
    unified_at_meta: Mapping[str, Any] | None = None,
    gap_analysis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    incoming_rows = [r for r in ((pending.get("incoming") or {}).get("rows") or []) if isinstance(r, dict)]
    unknown_why: list[str] = []
    if ready_for_vendor.get("unknown_needs_review"):
        if any(not _normalized_service_type(r) for r in incoming_rows):
            unknown_why.append("missing service_type in presence rows")
        if any(_rush_bucket_key(str(r.get("effective_rush") or "")) not in ("rush", "non_rush") for r in incoming_rows):
            unknown_why.append("missing rush classification (rush_flag/estimated_delivery_date)")

    bucket_audit = _collect_active_bucket_ids(records, pending_by_bag={
        str(r.get("bag_id") or "").strip().upper(): r
        for r in (pending.get("rows") or [])
        if isinstance(r, dict) and r.get("bag_id")
    })
    bucket_ids = bucket_audit["bucket_ids"]
    expected_bucket_total = sum(len(bucket_ids[k]) for k in bucket_ids)
    api_total = _count_tag(records, "pipeline_work")

    rush_rows = [r for r in (pending.get("rows") or []) if isinstance(r, dict) and _rush_bucket_key(str(r.get("effective_rush") or "")) == "rush"]
    rush_active = [r for r in records if r.get("rush_label") == "Rush" and "active_work" in (r.get("drilldown_tags") or [])]

    yet_to_fold_ids: list[str] = []
    completion_by_bag: dict[str, dict[str, Any]] = {}
    excluded_completed: list[str] = []
    for rec in records:
        bid = str(rec.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        completion_by_bag[bid] = {
            "completed": rec.get("completed"),
            "completion_kind": rec.get("completion_kind"),
            "completion_exception": rec.get("completion_exception"),
        }
        if "wf_pending_folding" in (rec.get("drilldown_tags") or []):
            yet_to_fold_ids.append(bid)
        if rec.get("completed") and "yet_to_fold" not in (rec.get("drilldown_tags") or []):
            if rec.get("in_scope_a_active") or rec.get("in_ready_for_vendor"):
                excluded_completed.append(bid)

    zero_w = one_w = two_plus = parseable_two = 0
    non_parseable: list[dict[str, str]] = []
    events_by_bag = events_by_bag or {}
    for rec in records:
        if not rec.get("in_scope_a_active"):
            continue
        bid = str(rec.get("bag_id") or "").strip().upper()
        evs = events_by_bag.get(bid) or []
        n, bad = _weight_entry_counts(evs)
        if n == 0:
            zero_w += 1
        elif n == 1:
            one_w += 1
        else:
            two_plus += 1
            wdiff = rec.get("weight_difference") or {}
            if wdiff.get("comparable"):
                parseable_two += 1
            elif bad:
                non_parseable.append({"bag_id": bid, "issue": "non_parseable_weight_values"})

    stage_audit = _build_stage_audit(records)
    from backend.rinse_current_facility_snapshot import (
        build_due_today_debug_ids,
        build_snapshot_debug_ids,
        build_vendor_home_debug_audit,
    )

    cfs_reconciliation = (current_facility_snapshot or {}).get("reconciliation") or {}
    dts_reconciliation = (due_today_snapshot or {}).get("reconciliation") or {}
    vendor_home_debug = build_vendor_home_debug_audit(
        cfs_reconciliation=cfs_reconciliation,
        dts_reconciliation=dts_reconciliation,
        cfs_debug_ids=build_snapshot_debug_ids(records),
        dts_debug_ids=build_due_today_debug_ids(records),
        gap_analysis=gap_analysis,
        unified_meta=unified_at_meta,
    )
    return {
        "ready_for_vendor_sync": {
            "latest_attempt_at": (rfv_sync or {}).get("latest_attempt_at") or (rfv_sync or {}).get("last_refreshed_at"),
            "last_success_at": (rfv_sync or {}).get("last_success_at"),
            "status": (rfv_sync or {}).get("latest_status") or (rfv_sync or {}).get("status"),
            "rows_found": (rfv_sync or {}).get("rows_found"),
            "active_rows": (rfv_sync or {}).get("active_rows"),
            "error": (rfv_sync or {}).get("error"),
            "skipped_reason": (rfv_sync or {}).get("skipped_reason"),
            "enabled": (rfv_sync or {}).get("enabled"),
            "stale": (rfv_sync or {}).get("stale"),
        },
        "at_vendor_sync": {
            "latest_attempt_at": (av_sync or {}).get("latest_attempt_at") or (av_sync or {}).get("last_refreshed_at"),
            "last_success_at": (av_sync or {}).get("last_success_at"),
            "status": (av_sync or {}).get("status"),
            "rows_found": (av_sync or {}).get("rows_found"),
            "pages_visited": (av_sync or {}).get("pages_visited"),
            "error_message": (av_sync or {}).get("error_message"),
            "stale": (av_sync or {}).get("stale"),
        },
        "dashboard_vs_monitor": dict(dashboard_reconciliation or {}),
        "facility_tracker_today": {
            "entered_today_ids": sorted((facility_tracker.get("entered_today") or {}).get("bag_ids") or []),
            "carryover_ids": sorted((facility_tracker.get("carryover") or {}).get("bag_ids") or []),
            "total_workload_ids": sorted((facility_tracker.get("total_workload") or {}).get("bag_ids") or []),
            "reconciliation": facility_tracker.get("reconciliation"),
            "entered_today": facility_tracker.get("entered_today"),
            "carryover": facility_tracker.get("carryover"),
            "total_workload": facility_tracker.get("total_workload"),
            "entry_racks": facility_tracker.get("entry_racks"),
            "bag_ids": sorted(facility_tracker.get("bag_ids") or []),
            "total": facility_tracker.get("total"),
        },
        "current_work_pipeline": {
            "active_now_ids": sorted(active_work.get("bag_ids") or []),
            "entered_today_still_active": (pipeline_debug or scope_overlap or {}).get("entered_today_still_active")
            or (scope_overlap or {}).get("current_work_pipeline", {}).get("entered_today_still_active")
            or [],
            "carryover_active_from_prior_day": (pipeline_debug or {}).get("carryover_active_from_prior_day") or [],
            "pending_wash_rush_ids": sorted(active_work.get("pending_wash_rush_ids") or []),
            "pending_wash_nonrush_ids": sorted(active_work.get("pending_wash_nonrush_ids") or []),
            "last_rush_wash": active_work.get("last_rush_wash"),
            "last_nonrush_wash": active_work.get("last_nonrush_wash"),
            "last_wash_overall": active_work.get("last_wash_overall"),
            "completed_excluded": sorted((pipeline_debug or {}).get("completed_excluded") or []),
            "sent_excluded": sorted((pipeline_debug or {}).get("sent_excluded") or []),
            "source": active_work.get("source"),
            "bag_ids": sorted(active_work.get("bag_ids") or []),
            "total": active_work.get("total"),
        },
        "current_active_work_now": {
            "source": active_work.get("source"),
            "bag_ids": sorted(active_work.get("bag_ids") or []),
            "rush_wf_ids": sorted(active_work.get("rush_wf_ids") or []),
            "rush_hd_ids": sorted(active_work.get("rush_hd_ids") or []),
            "nonrush_wf_ids": sorted(active_work.get("nonrush_wf_ids") or []),
            "nonrush_hd_ids": sorted(active_work.get("nonrush_hd_ids") or []),
            "unknown_ids": sorted(active_work.get("unknown_ids") or []),
            "total": active_work.get("total"),
        },
        "overlap": dict(scope_overlap or {}),
        "active_staging_bag_ids": sorted(dashboard_snapshot.get("unique_bag_ids") or []) if dashboard_snapshot else [],
        "ready_for_vendor": {
            "total": ready_for_vendor.get("total"),
            "live": ready_for_vendor.get("live"),
            "unavailable_reason": ready_for_vendor.get("unavailable_reason"),
            "rush_wf": ready_for_vendor.get("rush_wf"),
            "rush_hd": ready_for_vendor.get("rush_hd"),
            "nonrush_wf": ready_for_vendor.get("nonrush_wf"),
            "nonrush_hd": ready_for_vendor.get("nonrush_hd"),
            "unknown": ready_for_vendor.get("unknown_needs_review"),
            "why_unknown": unknown_why or None,
            "counts_add_up": ready_for_vendor.get("counts_add_up"),
            "unreconciled_ids": _collect_unreconciled_ids(records, "ready_for_vendor"),
        },
        "current_active_work": {
            "expected_total_from_pending": active_work.get("total"),
            "actual_api_total": api_total,
            "rush_wf": active_work.get("rush_wf"),
            "rush_hd": active_work.get("rush_hd"),
            "nonrush_wf": active_work.get("nonrush_wf"),
            "nonrush_hd": active_work.get("nonrush_hd"),
            "unknown": active_work.get("unknown_needs_review"),
            "unreconciled": active_work.get("unreconciled"),
            "unreconciled_ids": _collect_unreconciled_ids(records, "active_work"),
        },
        "active_work_reconciliation": {
            "expected_total_from_buckets": int(active_work.get("total") or 0),
            "api_total": api_total,
            "staging_total": int(dashboard_snapshot.get("total_orders") or 0) if dashboard_snapshot else int(active_work.get("total") or 0),
            "staging_row_count": int(dashboard_snapshot.get("staging_row_count") or 0) if dashboard_snapshot else 0,
            "duplicate_staging_rows": int(dashboard_snapshot.get("duplicate_staging_rows") or 0) if dashboard_snapshot else 0,
            "dashboard_source": True,
            "counts_add_up": expected_bucket_total == api_total == int(active_work.get("total") or 0),
            "lifecycle_sent_excluded_from_monitor": [
                str(r.get("bag_id"))
                for r in (pending.get("rows") or [])
                if isinstance(r, dict)
                and r.get("in_active_staging")
                and str(r.get("current_lifecycle_status") or "") == SENT_TO_RINSE
            ],
            **bucket_ids,
            "duplicate_ids": bucket_audit["duplicate_ids"],
            "excluded_ids": bucket_audit["excluded_ids"],
        },
        "rush_classification_audit": {
            "rush_expected_count": len(rush_rows),
            "rush_api_count": len(rush_active),
            "rows_missing_rush_type": [
                str(r.get("bag_id"))
                for r in (pending.get("rows") or [])
                if isinstance(r, dict)
                and not str(r.get("rush_type") or r.get("effective_rush") or "").strip()
            ],
            "rows_using_fallback": [
                str(r.get("bag_id"))
                for r in (pending.get("rows") or [])
                if isinstance(r, dict) and r.get("in_active_staging") and r.get("date_clean")
            ],
            "misclassified_candidates": [],
        },
        "yet_to_fold_audit": {
            "count": len(yet_to_fold_ids),
            "bag_ids": sorted(yet_to_fold_ids),
            "completion_signal_by_bag": completion_by_bag,
            "excluded_as_completed": sorted(set(excluded_completed)),
        },
        "weight_difference_audit": {
            "zero_weight_entries": zero_w,
            "one_weight_entry": one_w,
            "two_plus_weight_entries": two_plus,
            "parseable_two_weight_entries": parseable_two,
            "non_parseable_weights": non_parseable,
        },
        "rush_checkout": {
            "checkout_pending_rush_only": rush_checkout.get("checkout_pending"),
            "checked_out": rush_checkout.get("checked_out"),
            "checkout_not_recorded": rush_checkout.get("checkout_not_recorded"),
            "checkout_needs_review": rush_checkout.get("checkout_needs_review"),
        },
        "employee_activity": employee_diagnostics,
        "weight_difference": {
            "flagged": shift_status.get("weight_difference", {}).get("flagged"),
            "unavailable": shift_status.get("weight_difference", {}).get("unavailable"),
            "status": shift_status.get("weight_difference_status"),
        },
        "drilldown_tag_counts": _drilldown_tag_counts(records),
        "stage_audit": stage_audit,
        "reconciliation_status": {
            "ready_for_vendor_counts_add_up": ready_for_vendor.get("counts_add_up"),
            "ready_for_vendor_rush_nonrush": ready_for_vendor.get("rush_nonrush_reconciled"),
            "facility_total_equals_entered_plus_carryover": (facility_tracker or {}).get("reconciliation", {}).get(
                "total_equals_entered_plus_carryover"
            ),
            "hd_weighing_separation_ok": stage_audit.get("reconciliation_ok"),
            "current_facility_snapshot_ok": cfs_reconciliation.get("ok"),
            "due_today_snapshot_ok": dts_reconciliation.get("ok"),
        },
        "vendor_home_reconciliation": cfs_reconciliation,
        "vendor_home_debug": vendor_home_debug,
        "vendor_home_gap_analysis": gap_analysis,
        "current_facility_snapshot": build_snapshot_debug_ids(records),
        "due_today_snapshot_debug": build_due_today_debug_ids(records),
    }


def _drilldown_tag_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    from collections import Counter

    counts: Counter[str] = Counter()
    for rec in records:
        for tag in rec.get("drilldown_tags") or []:
            counts[str(tag)] += 1
    return dict(sorted(counts.items()))


def _align_ready_for_vendor_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["total"] = _count_tag(records, "ready_for_vendor")
    section["rush_total"] = _count_tag(records, "rfv_rush")
    section["nonrush_total"] = _count_tag(records, "rfv_non_rush")
    section["rush_wf"] = _count_tag(records, "rfv_rush_wf")
    section["rush_hd"] = _count_tag(records, "rfv_rush_hd")
    section["nonrush_wf"] = _count_tag(records, "rfv_nonrush_wf")
    section["nonrush_hd"] = _count_tag(records, "rfv_nonrush_hd")
    section["wf_total"] = _count_tag(records, "rfv_wf")
    section["hd_total"] = _count_tag(records, "rfv_hd")
    section["unknown_needs_review"] = _count_tag(records, "rfv_unknown_needs_review")
    _finalize_section_counts(section)
    section["data_quality_warning"] = _data_quality_warning(section)
    section["unreconciled_ids"] = _collect_unreconciled_ids(records, "ready_for_vendor")


def _align_pipeline_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["total"] = _count_tag(records, "pipeline_work")
    section["rush_wf"] = _count_tag(records, "pipeline_rush_wf")
    section["rush_hd"] = _count_tag(records, "pipeline_rush_hd")
    section["nonrush_wf"] = _count_tag(records, "pipeline_nonrush_wf")
    section["nonrush_hd"] = _count_tag(records, "pipeline_nonrush_hd")
    section["unknown_needs_review"] = sum(
        1
        for r in records
        if "pipeline_work" in (r.get("drilldown_tags") or [])
        and (
            "unknown_speed_service" in (r.get("drilldown_tags") or [])
            or any(t.startswith("pipeline_unknown") for t in (r.get("drilldown_tags") or []))
        )
    )
    section["rush_pending"] = sum(
        1 for r in records if r.get("rush_label") == "Rush" and "pipeline_work" in (r.get("drilldown_tags") or [])
    )
    section["nonrush_pending"] = sum(
        1 for r in records if r.get("rush_label") == "Non-Rush" and "pipeline_work" in (r.get("drilldown_tags") or [])
    )
    section["pending_wash_rush"] = _count_tag(
        [r for r in records if r.get("service_type") == "WF"], "wf_pending_wash_rush"
    )
    section["pending_wash_nonrush"] = _count_tag(
        [r for r in records if r.get("service_type") == "WF"], "wf_pending_wash_nonrush"
    )
    section["pending_wash_total"] = _count_tag(
        [r for r in records if r.get("service_type") == "WF"], "pending_wash"
    )
    section["yet_to_fold"] = _count_tag([r for r in records if r.get("service_type") == "WF"], "wf_pending_folding")
    section["issues"] = _count_tag(records, "issues")
    section["workitems"] = _count_tag(records, "workitems")
    _finalize_section_counts(section)
    section["monitor_cards"] = [
        _make_drilldown_card("Pending Wash — Rush (WF)", section.get("pending_wash_rush"), "wf_pending_wash_rush", records),
        _make_drilldown_card("Pending Wash — Non-Rush (WF)", section.get("pending_wash_nonrush"), "wf_pending_wash_nonrush", records),
        _make_drilldown_card("Create Issue", section.get("issues"), "issues", records),
        _make_drilldown_card("Workitems Added", section.get("workitems"), "workitems", records),
    ]


def _align_active_work_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    _align_pipeline_counts(section, records)


def _build_exceptions_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    wf_records = [r for r in records if r.get("service_type") == "WF"]
    hd_records = [r for r in records if r.get("service_type") == "HD"]
    return {
        "completed_without_clean_rack": {
            "count": _count_tag(wf_records, "completed_without_clean"),
            "drilldown_filter": "completed_without_clean",
            "source": "WF scan events",
        },
        "create_issue": {"count": _count_tag(records, "issues"), "drilldown_filter": "issues", "source": "Scan events"},
        "workitems": {"count": _count_tag(records, "workitems"), "drilldown_filter": "workitems", "source": "Scan events"},
        "weight_difference": {
            "count": _count_tag(wf_records, "weight_difference"),
            "drilldown_filter": "weight_difference",
            "source": "WF only",
        },
        "hd_started_no_completion": {
            "count": sum(
                1
                for r in hd_records
                if "hd_started_cleaning" in (r.get("drilldown_tags") or [])
                and "hd_completed" not in (r.get("drilldown_tags") or [])
            ),
            "drilldown_filter": "hd_started_cleaning",
            "source": "HD scan events",
        },
        "unknown_service_speed": {
            "count": _count_tag(records, "unknown_speed_service"),
            "drilldown_filter": "unknown_speed_service",
            "source": "Portal scrape",
        },
        "checkout_not_recorded": {
            "count": _count_tag(records, "checkout_not_recorded"),
            "drilldown_filter": "checkout_not_recorded",
            "source": "Checkout staging",
        },
    }


_AV_PORTAL_DRILLDOWN_ROW_KEYS = frozenset({
    "bag_id",
    "customer_name",
    "service_type",
    "service_bucket",
    "estimated_delivery_date",
    "date_clean",
    "portal_yet_to_process",
    "currently_on_vendor_home",
    "left_vendor_home_but_counted",
    "rush_bucket",
    "rush_label",
    "source_seen_in",
})

_AV_DRILLDOWN_ROW_KEYS = frozenset({
    "bag_id",
    "customer_name",
    "service_type",
    "service_bucket",
    "rush_bucket",
    "rush_label",
    "at_vendor_status",
    "facility_status",
    "module_tags",
    "drilldown_tags",
    "daily_classification",
    "currently_on_vendor_home",
    "estimated_delivery_date",
    "date_clean",
    "delivery_source",
    "rush_reason",
    "status_reason",
    "changed_to_rush",
    "changed_to_rush_reason",
    "portal_yet_to_process",
    "population_inclusion",
    "completion_signal",
    "completion_time",
    "completion_time_et",
    "sent_to_vendor_time_et",
    "left_vendor_home_but_counted",
    "pre_clean_weight",
    "pre_clean_weight_time_et",
    "post_clean_weight",
    "post_clean_weight_time_et",
    "clean_weight_delta",
    "completed_lbs",
    "completed_by_employee",
    "weight_missing",
})

_RFV_DRILLDOWN_ROW_KEYS = frozenset({
    "bag_id",
    "customer_name",
    "service_type",
    "service_bucket",
    "rush_bucket",
    "rush_label",
    "estimated_delivery_date",
    "estimated_delivery_date_et",
    "estimated_delivery_raw",
    "has_today_label",
    "reason",
    "source",
    "drilldown_tags",
})


def _slim_row_for_drilldown(row: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: row[k] for k in keys if k in row and row.get(k) is not None}


def _slim_at_vendor_module_payload(module: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(module)
    out["rows"] = [
        _slim_row_for_drilldown(r, _AV_DRILLDOWN_ROW_KEYS)
        for r in (module.get("rows") or [])
        if isinstance(r, dict)
    ]
    monitoring = module.get("completed_before_day_start_still_present_rows") or []
    out["completed_before_day_start_still_present_rows"] = [
        _slim_row_for_drilldown(r, _AV_DRILLDOWN_ROW_KEYS)
        for r in monitoring
        if isinstance(r, dict)
    ]
    out["portal_snapshot_drilldown_rows"] = [
        _slim_row_for_drilldown(r, _AV_PORTAL_DRILLDOWN_ROW_KEYS)
        for r in (module.get("portal_snapshot_drilldown_rows") or [])
        if isinstance(r, dict)
    ]
    emp_section = module.get("employee_completed_bags_today")
    if isinstance(emp_section, dict):
        slim_employees = []
        for emp in emp_section.get("employees") or []:
            if not isinstance(emp, dict):
                continue
            slim_emp = {k: v for k, v in emp.items() if k != "bags"}
            slim_employees.append(slim_emp)
        out["employee_completed_bags_today"] = {
            **emp_section,
            "employees": slim_employees,
            "reconciliation_banner": emp_section.get("reconciliation_banner"),
            "reconciliation": emp_section.get("reconciliation"),
            "bags_stripped_for_summary": True,
        }
    return out


def _slim_ready_for_vendor_payload(section: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(section)
    out["rows"] = [
        _slim_row_for_drilldown(r, _RFV_DRILLDOWN_ROW_KEYS)
        for r in (section.get("rows") or [])
        if isinstance(r, dict)
    ]
    return out


def _build_performance_meta(
    *,
    total_build_ms: float,
    at_vendor_build_ms: float = 0.0,
    rfv_build_ms: float = 0.0,
    records_build_ms: float = 0.0,
    debug_build_ms: float = 0.0,
    drilldown_build_ms: float = 0.0,
    payload: Mapping[str, Any],
    summary_only: bool,
) -> dict[str, Any]:
    import json

    serialized = json.dumps(payload, default=str)
    return {
        "summary_only": summary_only,
        "total_build_ms": round(total_build_ms, 1),
        "at_vendor_build_ms": round(at_vendor_build_ms, 1),
        "rfv_build_ms": round(rfv_build_ms, 1),
        "records_build_ms": round(records_build_ms, 1),
        "debug_build_ms": round(debug_build_ms, 1),
        "drilldown_build_ms": round(drilldown_build_ms, 1),
        "payload_size_bytes": len(serialized.encode("utf-8")),
    }


def _build_shift_monitor_summary_payload(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    """Fast initial /performance payload: RFV + At Vendor summaries and sync status only."""
    import time

    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_presence_sync_status import get_ready_for_vendor_sync_status
    from backend.rinse_ready_for_vendor_queue import build_ready_for_vendor_queue
    from backend.rinse_scheduled_scrape import _today_et
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        format_baseline_banner_et,
        get_shift_monitor_baseline,
    )

    org = int(organization_id)
    t0 = time.perf_counter()
    eval_at = naive_system_utc(
        evaluation_time if isinstance(evaluation_time, datetime) else datetime.utcnow()
    )

    t_baseline = time.perf_counter()
    baseline_settings = get_shift_monitor_baseline(cursor, org)
    baseline_ctx = build_baseline_context(cursor, org, baseline_settings)
    baseline_ms = (time.perf_counter() - t_baseline) * 1000

    t_rfv = time.perf_counter()
    rfv_sync = get_ready_for_vendor_sync_status(cursor, org, evaluation_time=eval_at)
    rfv_queue = build_ready_for_vendor_queue(
        cursor, org, baseline_ctx=baseline_ctx, rfv_sync=rfv_sync
    )
    ready_for_vendor = _slim_ready_for_vendor_payload(rfv_queue["section"])
    rfv_ms = (time.perf_counter() - t_rfv) * 1000

    t_av = time.perf_counter()
    at_vendor_module = build_at_vendor_module(
        cursor, org, selected_date_et=period_end, baseline_ctx=baseline_ctx
    )
    from backend.rinse_current_facility_snapshot import build_portal_snapshot_vendor_home_fields

    at_vendor_module.update(
        build_portal_snapshot_vendor_home_fields(
            cursor, org, today=period_end, module=at_vendor_module
        )
    )
    at_vendor_module = _slim_at_vendor_module_payload(at_vendor_module)
    av_ms = (time.perf_counter() - t_av) * 1000

    t_sync = time.perf_counter()
    active_work_stub: dict[str, Any] = {"live": True}
    rinse_sync = _attach_section_sync_statuses(
        cursor,
        org,
        ready_for_vendor=ready_for_vendor,
        active_work=active_work_stub,
        evaluation_time=eval_at,
    )
    sync_ms = (time.perf_counter() - t_sync) * 1000

    baseline_payload = {
        "baseline_source": baseline_ctx.get("baseline_source"),
        "baseline_time_et": baseline_ctx.get("baseline_time_et"),
        "banner_title": format_baseline_banner_et(baseline_ctx),
        "banner_subtitle": (
            "Using latest post-baseline Rinse scrape + post-baseline scans"
            if baseline_ctx.get("at_vendor_scrape_ready")
            else baseline_ctx.get("needs_refresh_reason")
        ),
        "at_vendor_scrape_ready": baseline_ctx.get("at_vendor_scrape_ready"),
    }

    payload: dict[str, Any] = {
        "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "summary_only": True,
        "ready_for_vendor": ready_for_vendor,
        "at_vendor_module": at_vendor_module,
        "rinse_sync": rinse_sync,
        "live_baseline": baseline_payload,
        "records": [],
        "shift_monitor_modules": None,
        "current_facility_snapshot": None,
        "due_today_snapshot": None,
        "vendor_home_parity": None,
        "vendor_home_gap_analysis": None,
        "facility_tracker_today": None,
        "sections_under_review": None,
        "employee_cards": None,
        "debug_audit": None,
        "drilldown_parity": None,
        "scope_overlap": None,
        "current_work_pipeline": active_work_stub,
        "current_active_work": active_work_stub,
        "current_active_work_now": active_work_stub,
    }
    total_ms = (time.perf_counter() - t0) * 1000
    payload["performance_meta"] = _build_performance_meta(
        total_build_ms=total_ms,
        at_vendor_build_ms=av_ms,
        rfv_build_ms=rfv_ms + baseline_ms,
        records_build_ms=0.0,
        debug_build_ms=0.0,
        drilldown_build_ms=sync_ms,
        payload=payload,
        summary_only=True,
    )
    return payload


def build_simple_shift_performance_payload(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    evaluation_time: datetime | None = None,
    include_debug: bool = False,
    slim_records: bool = False,
    summary_only: bool = False,
) -> dict[str, Any]:
    if summary_only and not include_debug:
        return _build_shift_monitor_summary_payload(
            cursor,
            organization_id,
            period_start=period_start,
            period_end=period_end,
            evaluation_time=evaluation_time,
        )

    import time

    _build_t0 = time.perf_counter()
    _step_ms: dict[str, float] = {}
    org = int(organization_id)
    settings = get_processing_settings(cursor, org)
    threshold = float(settings.get("weight_difference_threshold_lbs") or 5.0)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    from backend.rinse_scheduled_scrape import _today_et

    target_date = period_end
    today_et = _today_et()

    from backend.rinse_current_facility_snapshot import load_unified_at_facility_population, load_unified_due_today_population
    from backend.rinse_dashboard_staging import (
        build_dashboard_vs_monitor_reconciliation,
        get_dashboard_active_staging_snapshot,
    )
    from backend.rinse_facility_tracker import (
        apply_facility_management_drilldown_tags,
        build_facility_management_tracker,
        build_scope_overlap_debug,
        load_facility_entry_bag_ids,
        load_first_facility_entry_dates,
    )
    from backend.rinse_presence_sync_status import get_ready_for_vendor_sync_status
    from backend.rinse_shift_analysis import resolve_effective_rush_for_row
    from backend.rinse_work_pipeline import (
        bag_is_pipeline_eligible,
        bag_is_sent_or_left,
        build_current_work_pipeline_debug,
        build_last_wash_detail,
        update_last_wash_if_newer,
    )

    eval_at = naive_system_utc(
        evaluation_time if isinstance(evaluation_time, datetime) else datetime.utcnow()
    )

    from backend.rinse_shift_monitor_baseline import (
        apply_live_baseline_to_pending_incoming,
        build_baseline_context,
        build_baseline_debug_block,
        compute_excluded_pre_baseline_only,
        filter_events_by_bag_after_baseline,
        format_baseline_banner_et,
        get_shift_monitor_baseline,
        load_live_at_facility_population,
        load_live_due_today_population,
    )
    from backend.rinse_ready_for_vendor_queue import build_ready_for_vendor_queue

    baseline_settings = get_shift_monitor_baseline(cursor, org)
    baseline_ctx = build_baseline_context(cursor, org, baseline_settings)
    baseline_start_naive_et = baseline_ctx["baseline_start_naive_et"]
    use_live_baseline = bool(baseline_settings.get("active"))

    dashboard_snapshot = get_dashboard_active_staging_snapshot(cursor, org)
    rfv_sync = get_ready_for_vendor_sync_status(cursor, org, evaluation_time=eval_at)
    entry_racks = settings.get("facility_entry_racks") or ["VeeWash Dirty"]
    facility_entry_ids = load_facility_entry_bag_ids(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
        entry_racks=entry_racks,
    )
    first_entry_dates = load_first_facility_entry_dates(
        cursor, org, entry_racks=entry_racks, through_date=target_date
    )
    carryover_candidates = {bid for bid, d in first_entry_dates.items() if d < target_date}

    pending = get_pending_bag_status(
        cursor, org, target_date=target_date, evaluation_time=evaluation_time
    )
    _t_rfv = time.perf_counter()
    rfv_queue = build_ready_for_vendor_queue(
        cursor, org, baseline_ctx=baseline_ctx, rfv_sync=rfv_sync
    )
    _step_ms["rfv_build_ms"] = round((time.perf_counter() - _t_rfv) * 1000, 1)
    ready_for_vendor = rfv_queue["section"]
    rfv_bag_ids: set[str] = set(rfv_queue.get("bag_ids") or set())
    live_rfv_rows = list(rfv_queue.get("legacy_incoming_rows") or [])
    if use_live_baseline:
        pending = apply_live_baseline_to_pending_incoming(
            pending, [], baseline_ctx=baseline_ctx
        )
    scope_a = _build_scope_a(pending)

    incoming_rows = {
        str(r.get("bag_id") or "").strip().upper(): r
        for r in ((pending.get("incoming") or {}).get("rows") or [])
        if isinstance(r, dict) and r.get("bag_id")
    }
    pending_by_bag = {
        str(r.get("bag_id") or "").strip().upper(): r
        for r in (pending.get("rows") or [])
        if isinstance(r, dict) and r.get("bag_id")
    }
    for row in dashboard_snapshot.get("rows") or []:
        if not isinstance(row, dict) or not row.get("bag_id"):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        pending_by_bag[bid] = {**(pending_by_bag.get(bid) or {}), **row}
    active_candidates = {
        str(b).strip().upper()
        for b in (dashboard_snapshot.get("unique_bag_ids") or [])
        if b
    }
    legacy_unified_at: dict[str, dict[str, Any]] = {}
    excluded_pre_baseline_count = 0
    excluded_pre_baseline_samples: list[dict[str, Any]] = []
    live_rfv_bids: set[str] = set()
    if use_live_baseline:
        legacy_unified_at, _legacy_meta = load_unified_at_facility_population(cursor, org, target_date=today_et)
        unified_at_facility, unified_at_meta = load_live_at_facility_population(
            cursor, org, target_date=today_et, baseline_ctx=baseline_ctx
        )
        unified_at_meta["live_baseline"] = True
        unified_at_meta["legacy_unified_total"] = len(legacy_unified_at)
        live_rfv_bids = set(rfv_bag_ids)
        excluded_pre_baseline_count, excluded_pre_baseline_samples = compute_excluded_pre_baseline_only(
            legacy_unified_at=legacy_unified_at,
            live_at_facility=unified_at_facility,
            live_due_today={},
            live_rfv_bids=live_rfv_bids,
        )
        unified_at_meta["excluded_pre_baseline_only_count"] = excluded_pre_baseline_count
    else:
        unified_at_facility, unified_at_meta = load_unified_at_facility_population(cursor, org, target_date=today_et)
    at_facility_ids = set(unified_at_facility.keys())
    if use_live_baseline:
        unified_due_today, unified_due_meta = load_live_due_today_population(
            cursor,
            org,
            today_et,
            baseline_ctx=baseline_ctx,
            live_at_facility=unified_at_facility,
            live_rfv_rows=live_rfv_rows,
        )
        unified_due_meta["live_baseline"] = True
        _, excluded_due_samples = compute_excluded_pre_baseline_only(
            legacy_unified_at=legacy_unified_at,
            live_at_facility={},
            live_due_today=unified_due_today,
            live_rfv_bids=live_rfv_bids,
        )
        excluded_pre_baseline_count = max(excluded_pre_baseline_count, len(excluded_due_samples))
    else:
        unified_due_today, unified_due_meta = load_unified_due_today_population(cursor, org, today_et)
    due_today_ids = set(unified_due_today.keys())
    for bid, row in unified_at_facility.items():
        pending_by_bag[bid] = {**(pending_by_bag.get(bid) or {}), **row}
    for bid, row in unified_due_today.items():
        pending_by_bag[bid] = {**(pending_by_bag.get(bid) or {}), **row}
        due_today_ids.add(bid)

    scope_b_ids = _load_bag_ids_with_et_activity(
        cursor, org, period_start=period_start, period_end=period_end
    )
    live_dashboard_ids = (at_facility_ids | due_today_ids | set(incoming_rows.keys())) - rfv_bag_ids
    if use_live_baseline:
        pending_by_bag = {k: v for k, v in pending_by_bag.items() if k in live_dashboard_ids}
        all_bag_ids = sorted(
            live_dashboard_ids
            | (set(scope_b_ids) & live_dashboard_ids)
            | (set(facility_entry_ids) & live_dashboard_ids)
        )
    else:
        all_bag_ids = sorted(
            (set(scope_b_ids)
            | set(incoming_rows.keys())
            | set(pending_by_bag.keys())
            | set(facility_entry_ids)
            | set(carryover_candidates)
            | set(active_candidates)
            | set(at_facility_ids)
            | set(due_today_ids))
            - rfv_bag_ids
        )

    meta_by_bag = _load_bag_metadata(cursor, org, all_bag_ids)
    for bid, row in unified_at_facility.items():
        meta_by_bag[bid] = {**(meta_by_bag.get(bid) or {"bag_id": bid}), **{k: v for k, v in row.items() if v is not None}}
    for bid, row in unified_due_today.items():
        meta_by_bag[bid] = {**(meta_by_bag.get(bid) or {"bag_id": bid}), **{k: v for k, v in row.items() if v is not None}}
    for bid in all_bag_ids:
        base = meta_by_bag.get(bid) or {"bag_id": bid}
        pending_row = pending_by_bag.get(bid)
        merged = {**base, **{k: v for k, v in (pending_row or {}).items() if v is not None}}
        merged["effective_rush"] = resolve_effective_rush_for_row(merged, target_date)
        meta_by_bag[bid] = merged

    events_by_bag = _load_scan_events_for_bags(cursor, org, all_bag_ids)
    completion_events_by_bag = events_by_bag
    _t_records = time.perf_counter()
    if use_live_baseline:
        events_by_bag = filter_events_by_bag_after_baseline(events_by_bag, baseline_start_naive_et)
    user_maps = _load_rinse_user_maps(cursor, org)

    records: list[dict[str, Any]] = []
    completions_by_bag: dict[str, Any] = {}
    all_credits: list[BagActivityCredit] = []
    split = _split_counts()
    scope_b_completed = 0
    scope_b_sent = 0
    last_rush_wash: dict[str, Any] | None = None
    last_nonrush_wash: dict[str, Any] | None = None
    last_wash_overall: dict[str, Any] | None = None
    pipeline_bag_ids: set[str] = set()
    completed_excluded: list[str] = []
    sent_excluded: list[str] = []

    for bid in all_bag_ids:
        meta = meta_by_bag.get(bid) or {"bag_id": bid}
        pending_row = pending_by_bag.get(bid)
        if pending_row:
            meta = {**meta, **{k: v for k, v in pending_row.items() if v is not None}}
        meta["effective_rush"] = resolve_effective_rush_for_row(meta, target_date)
        meta["view_date"] = target_date.isoformat()
        events = events_by_bag.get(bid) or []
        completion_events = completion_events_by_bag.get(bid) or []
        in_incoming = bid in incoming_rows
        in_staging = bid in active_candidates
        in_facility_tracker = bid in facility_entry_ids
        completion = evaluate_bag_completion_v2(completion_events)
        completions_by_bag[bid] = completion
        in_pipeline = bag_is_pipeline_eligible(pending_row, completion, meta, completion_events)
        if in_pipeline:
            pipeline_bag_ids.add(bid)
        elif in_staging and pending_row:
            if bag_is_sent_or_left(pending_row, completion, meta, completion_events):
                sent_excluded.append(bid)
            elif completion.completed or str(pending_row.get("current_lifecycle_status") or "").upper() in LIFECYCLE_COMPLETED_STATUSES:
                completed_excluded.append(bid)
        rec = _record_from_bag(
            bid=bid,
            meta=meta,
            events=events,
            pending_row=pending_row,
            threshold=threshold,
            period_start=start_dt,
            period_end_exclusive=end_exclusive,
            in_pipeline=in_pipeline,
            in_staging=in_staging,
            in_incoming=in_incoming,
            in_facility_tracker=in_facility_tracker,
            completion=completion,
        )
        records.append(rec)

        if bid in scope_b_ids:
            _inc_split(split, rec.get("rush_bucket"))
            if rec.get("completed"):
                scope_b_completed += 1
            if str(meta.get("logistics_status") or "").upper() == "SENT_TO_RINSE" or (
                pending_row and str(pending_row.get("current_lifecycle_status") or "") == SENT_TO_RINSE
            ):
                scope_b_sent += 1
            credits = extract_bag_activity_credits(
                bid, events, customer=rec.get("customer"), default_lbs=_safe_float(meta.get("weight_num"))
            )
            all_credits.extend(
                c for c in credits if credit_in_et_period(c, period_start=start_dt, period_end_exclusive=end_exclusive)
            )
        rush_label = rec.get("rush_label")
        for ev in events:
            if not is_start_cleaning_purpose(ev.get("purpose")):
                continue
            ts = ev.get("scanned_at_parsed")
            if not isinstance(ts, datetime) or not (start_dt <= ts < end_exclusive):
                continue
            detail = build_last_wash_detail(
                at=ts,
                bag_id=bid,
                customer=rec.get("customer"),
                user=ev.get("user_name"),
                service_type=rec.get("service_type"),
                rush_label=rush_label,
                rush_bucket=rec.get("rush_bucket"),
            )
            last_wash_overall = update_last_wash_if_newer(last_wash_overall, detail)
            if rush_label == "Rush":
                last_rush_wash = update_last_wash_if_newer(last_rush_wash, detail)
            elif rush_label == "Non-Rush":
                last_nonrush_wash = update_last_wash_if_newer(last_nonrush_wash, detail)

    _step_ms["records_build_ms"] = round((time.perf_counter() - _t_records) * 1000, 1)

    _apply_current_facility_snapshot_tags(
        records,
        at_facility_ids=at_facility_ids,
        at_facility_meta=unified_at_facility,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
        meta_by_bag=meta_by_bag,
        qualifies_yet_to_fold=_qualifies_yet_to_fold,
        completion_events_by_bag=completion_events_by_bag,
    )
    _apply_due_today_snapshot_tags(
        records,
        today=today_et,
        due_today_ids=due_today_ids,
        due_today_meta=unified_due_today,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
        meta_by_bag=meta_by_bag,
        completion_events_by_bag=completion_events_by_bag,
    )

    work_pipeline = _build_work_pipeline_section(
        pipeline_bag_ids,
        meta_by_bag,
        target_date,
        last_rush_wash=last_rush_wash,
        last_nonrush_wash=last_nonrush_wash,
        last_wash_overall=last_wash_overall,
        records=records,
    )
    _align_pipeline_counts(work_pipeline, records)
    active_work = work_pipeline

    shift_status = _build_shift_status(records, threshold=threshold, last_rush_wash=last_rush_wash)

    from backend.rinse_current_facility_snapshot import (
        apply_portal_vendor_home_tags_on_records,
        backfill_record_due_dates,
        build_vendor_home_parity,
        build_vendor_home_view_section,
        load_portal_vendor_home_counts,
        load_presence_edd_by_bag,
    )

    portal_counts, presence_meta, at_vendor_presence_rows, due_today_portal_rows = load_portal_vendor_home_counts(
        cursor, org, today_et
    )
    apply_portal_vendor_home_tags_on_records(
        records,
        at_vendor_rows=at_vendor_presence_rows,
        due_today_portal_rows=due_today_portal_rows,
    )
    presence_edd_by_bag = load_presence_edd_by_bag(cursor, org)
    edd_backfill_stats = backfill_record_due_dates(
        records, meta_by_bag, presence_edd_by_bag=presence_edd_by_bag
    )

    vendor_home_view = build_vendor_home_view_section(
        portal_counts=portal_counts,
        presence_meta=presence_meta,
        records=records,
        record_count_fn=_count_tag,
    )

    current_facility_snapshot = _build_current_facility_snapshot_section(
        records, dashboard_snapshot, vendor_home_view=vendor_home_view
    )
    due_today_snapshot = _build_due_today_snapshot_section(
        records, today=today_et, vendor_home_view=vendor_home_view
    )
    due_today_wip = _build_due_today_wip_section(records)
    due_today_snapshot["wip"] = due_today_wip
    wip_sections = _build_wip_sections(records, target_date)
    from backend.rinse_current_facility_snapshot import build_vendor_home_gap_analysis

    gap_analysis = build_vendor_home_gap_analysis(
        records=records,
        unified_at_facility=unified_at_facility,
        unified_due_today=unified_due_today,
        cfs_reconciliation=current_facility_snapshot.get("reconciliation") or {},
        dts_reconciliation=due_today_snapshot.get("reconciliation") or {},
        unified_meta=unified_at_meta,
    )
    current_facility_snapshot["gap_analysis"] = gap_analysis
    due_today_snapshot["gap_analysis"] = gap_analysis

    vendor_home_parity = build_vendor_home_parity(
        vendor_home_view=vendor_home_view,
        internal_scan_view={
            "at_facility_total": current_facility_snapshot.get("at_facility_total"),
            "in_progress": current_facility_snapshot.get("in_progress"),
            "completed_still_at_facility": current_facility_snapshot.get("completed_still_at_facility"),
            "due_today_total": due_today_snapshot.get("due_today_total"),
            "due_today_yet_to_process": due_today_snapshot.get("due_today_yet_to_process"),
            "due_today_completed": due_today_snapshot.get("due_today_completed_processed"),
        },
        presence_meta=presence_meta,
        portal_counts=portal_counts,
    )
    vendor_home_parity["edd_backfill"] = edd_backfill_stats
    stage_audit = _build_stage_audit(records)

    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_shift_monitor_modules import apply_module_tags, build_shift_monitor_modules

    _t_av = time.perf_counter()
    at_vendor_module = build_at_vendor_module(
        cursor, org, selected_date_et=period_end, baseline_ctx=baseline_ctx
    )
    from backend.rinse_current_facility_snapshot import build_portal_snapshot_vendor_home_fields

    at_vendor_module.update(
        build_portal_snapshot_vendor_home_fields(
            cursor, org, today=period_end, module=at_vendor_module
        )
    )
    _step_ms["at_vendor_build_ms"] = round((time.perf_counter() - _t_av) * 1000, 1)
    apply_module_tags(records, events_by_bag=events_by_bag)
    _t_modules = time.perf_counter()
    shift_monitor_modules = build_shift_monitor_modules(
        records,
        events_by_bag=events_by_bag,
        period_start=period_start,
        period_end=period_end,
        period_start_dt=start_dt,
        period_end_exclusive=end_exclusive,
        portal_list_available=bool(presence_meta.get("portal_list_available")),
        portal_counts=portal_counts,
        last_rush_wash=last_rush_wash,
        last_nonrush_wash=last_nonrush_wash,
        last_wash_overall=last_wash_overall,
        today_et=today_et,
        at_vendor_module=at_vendor_module,
    )
    _step_ms["drilldown_build_ms"] = round((time.perf_counter() - _t_modules) * 1000, 1)

    _t_employee = time.perf_counter()
    employee_summary, employee_diagnostics = _build_employee_activity_summary(
        cursor, org, credits=all_credits, period_start=period_start, period_end=period_end, user_maps=user_maps
    )
    employee_cards = _build_employee_cards(employee_summary)
    exceptions_summary = _build_exceptions_summary(records)
    rinse_sync = _attach_section_sync_statuses(
        cursor,
        org,
        ready_for_vendor=ready_for_vendor,
        active_work=active_work,
        evaluation_time=eval_at,
    )
    if rfv_sync.get("stale"):
        ready_for_vendor["sync_status"] = {
            **(ready_for_vendor.get("sync_status") or {}),
            **{k: v for k, v in rfv_sync.items() if k != "message"},
        }
    rush_checkout = _build_rush_checkout_section(pending, records)
    records_by_bag = {str(r.get("bag_id") or "").strip().upper(): r for r in records if r.get("bag_id")}
    facility_tracker = build_facility_management_tracker(
        cursor,
        org,
        target_date=target_date,
        entry_racks=entry_racks,
        meta_by_bag=meta_by_bag,
        records_by_bag=records_by_bag,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
    )
    apply_facility_management_drilldown_tags(
        records,
        facility_tracker,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
        first_entry_dates=first_entry_dates,
    )
    _attach_facility_drilldown_cards(facility_tracker, records)
    pipeline_debug = build_current_work_pipeline_debug(
        facility_bag_ids=facility_entry_ids,
        pipeline_bag_ids=pipeline_bag_ids,
        staging_bag_ids=active_candidates,
        completed_excluded=completed_excluded,
        sent_excluded=sent_excluded,
    )
    scope_overlap = build_scope_overlap_debug(
        facility_bag_ids=facility_entry_ids,
        active_bag_ids=pipeline_bag_ids,
        records_by_bag=records_by_bag,
        pipeline_debug=pipeline_debug,
        management_tracker=facility_tracker,
    )
    dashboard_reconciliation = build_dashboard_vs_monitor_reconciliation(
        dashboard_snapshot,
        active_work,
        monitor_bag_ids=sorted(pipeline_bag_ids),
    )
    _t_debug = time.perf_counter()
    debug_audit = (
        _build_debug_audit(
            pending=pending,
            ready_for_vendor=ready_for_vendor,
            active_work=active_work,
            rush_checkout=rush_checkout,
            records=records,
            employee_diagnostics=employee_diagnostics,
            shift_status=shift_status,
            events_by_bag=events_by_bag,
            dashboard_snapshot=dashboard_snapshot,
            dashboard_reconciliation=dashboard_reconciliation,
            facility_tracker=facility_tracker,
            scope_overlap=scope_overlap,
            pipeline_debug=pipeline_debug,
            rfv_sync=rfv_sync,
            av_sync=rinse_sync.get("at_vendor") if isinstance(rinse_sync, dict) else None,
            current_facility_snapshot=current_facility_snapshot,
            due_today_snapshot=due_today_snapshot,
            unified_at_meta=unified_at_meta,
            gap_analysis=gap_analysis,
        )
        if include_debug
        else None
    )
    _step_ms["debug_build_ms"] = round((time.perf_counter() - _t_debug) * 1000, 1) if include_debug else 0.0

    sections_under_review = {
        "current_facility_snapshot": True,
        "due_today_snapshot": True,
        "vendor_home_parity": not vendor_home_parity.get("reconciled"),
        "shift_status": not stage_audit.get("reconciliation_ok", True),
        "wip": not wip_sections.get("parity_ok", True) or not stage_audit.get("reconciliation_ok", True),
        "employee_activity": True,
        "rush_checkout": True,
        "exceptions": False,
        "ready_for_vendor_live": bool(ready_for_vendor.get("live")),
        "facility_workload": not all(
            (facility_tracker.get(k) or {}).get("parity_ok", True)
            for k in ("entered_today", "carryover", "total_workload")
        ),
    }

    drilldown_parity = _build_drilldown_parity_audit(
        {
            "current_facility_snapshot": current_facility_snapshot,
            "due_today_snapshot": due_today_snapshot,
            "due_today_wip": due_today_wip,
            "ready_for_vendor": ready_for_vendor,
            "wip": wip_sections,
            "facility_entered": facility_tracker.get("entered_today") or {},
            "facility_carryover": facility_tracker.get("carryover") or {},
            "facility_total": facility_tracker.get("total_workload") or {},
        }
    )
    if debug_audit is not None:
        debug_audit["drilldown_parity"] = drilldown_parity
        if use_live_baseline:
            debug_audit["live_baseline"] = build_baseline_debug_block(
                baseline_ctx=baseline_ctx,
                live_record_count=len(records),
                excluded_pre_baseline_only_count=excluded_pre_baseline_count,
                excluded_samples=excluded_pre_baseline_samples,
            )

    baseline_payload = {
        **baseline_ctx,
        "banner_title": format_baseline_banner_et(baseline_ctx),
        "banner_subtitle": (
            "Using latest post-baseline Rinse scrape + post-baseline scans"
            if baseline_ctx.get("at_vendor_scrape_ready")
            else baseline_ctx.get("needs_refresh_reason")
        ),
        "banner_footer": "Historical data kept for audit only",
        "live_dashboard_record_count": len(records),
        "excluded_pre_baseline_only_count": excluded_pre_baseline_count,
    }

    payload: dict[str, Any] = {
        "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "summary_only": False,
        "ready_for_vendor": ready_for_vendor,
        "at_vendor_module": at_vendor_module,
        "facility_tracker_today": facility_tracker,
        "current_work_pipeline": work_pipeline,
        "current_active_work": work_pipeline,
        "current_active_work_now": work_pipeline,
        "dashboard_active_staging": {
            k: v for k, v in dashboard_snapshot.items() if k != "rows"
        }
        | {"row_count": len(dashboard_snapshot.get("rows") or [])},
        "dashboard_reconciliation": dashboard_reconciliation,
        "scope_overlap": scope_overlap if include_debug else None,
        "facility_entry_racks": entry_racks,
        "sections_under_review": sections_under_review,
        "rinse_sync": rinse_sync,
        "rush_checkout": rush_checkout,
        "scope_a_active_work": scope_a,
        "scope_b_performance_day": {
            "total_bags_worked": len(scope_b_ids),
            **split,
            "completed": scope_b_completed,
            "sent_to_rinse": scope_b_sent,
            "source": "Scan events",
        },
        "shift_status": shift_status,
        "current_facility_snapshot": current_facility_snapshot,
        "due_today_snapshot": due_today_snapshot,
        "vendor_home_parity": vendor_home_parity,
        "vendor_home_gap_analysis": gap_analysis,
        "live_baseline": baseline_payload,
        "shift_monitor_modules": shift_monitor_modules,
        "unified_at_facility_meta": unified_at_meta,
        "wip": wip_sections,
        "stage_audit": stage_audit if include_debug else {"reconciliation_ok": stage_audit.get("reconciliation_ok")},
        "employee_activity_summary": employee_summary,
        "employee_cards": employee_cards,
        "employee_diagnostics": employee_diagnostics,
        "exceptions_summary": exceptions_summary,
        "debug_audit": debug_audit,
        "drilldown_parity": drilldown_parity if include_debug else {"ok": drilldown_parity.get("ok")},
        "records": (
            [{k: v for k, v in r.items() if k != "activities"} for r in records]
            if slim_records
            else records
        ),
        "settings": {
            "weight_difference_threshold_lbs": threshold,
            "washing_minutes": settings.get("washing_minutes"),
            "drying_minutes": settings.get("drying_minutes"),
            "reject_after_create_issue_minutes": settings.get("reject_after_create_issue_minutes"),
            "shift_monitor_baseline_start_at_et": baseline_settings.get("shift_monitor_baseline_start_at_et"),
            "baseline_source": baseline_settings.get("baseline_source"),
            "baseline_note": baseline_settings.get("baseline_note"),
        },
    }
    payload["performance_meta"] = _build_performance_meta(
        total_build_ms=(time.perf_counter() - _build_t0) * 1000,
        at_vendor_build_ms=_step_ms.get("at_vendor_build_ms", 0.0),
        rfv_build_ms=_step_ms.get("rfv_build_ms", 0.0),
        records_build_ms=_step_ms.get("records_build_ms", 0.0),
        debug_build_ms=_step_ms.get("debug_build_ms", 0.0),
        drilldown_build_ms=_step_ms.get("drilldown_build_ms", 0.0),
        payload=payload,
        summary_only=False,
    )
    return payload
