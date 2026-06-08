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
from backend.rinse_scan_purpose import is_start_cleaning_purpose, is_weight_entry_purpose
from backend.rinse_bag_stage_bounds import first_start_cleaning_after, gaming_events_from_records, lifecycle_anchor, events_on_or_after
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
    """Post-wash / in-process bags not yet completed on our side."""
    if completion.completed:
        return False
    if not pending_row:
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
) -> tuple[datetime | None, datetime | None, str | None]:
    """Earliest clock-in and latest effective clock-out overlapping ET day."""
    from backend.rinse_processing_productivity import _last_rinse_sync_naive

    sessions = _load_shift_sessions(cursor, organization_id, user_id, period_start, period_end)
    if not sessions:
        return None, None, "Clock-in missing"
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    last_sync = _last_rinse_sync_naive(cursor, organization_id)
    clock_ins: list[datetime] = []
    clock_outs: list[datetime] = []
    for sh in sessions:
        cin = sh.get("clock_in_at")
        if not isinstance(cin, datetime):
            continue
        cout, _, _ = _shift_effective_clock_out(sh, last_sync=last_sync)
        if cout is None:
            continue
        overlap_start = max(cin, start_dt)
        overlap_end = min(cout, end_incl)
        if overlap_end <= overlap_start:
            continue
        clock_ins.append(cin)
        clock_outs.append(cout)
    if not clock_ins:
        return None, None, "Clock-in missing"
    return min(clock_ins), max(clock_outs), None


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
    section["split_sum"] = parts
    section["counts_add_up"] = total == parts
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
    if stale:
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
    section["pending_wash_rush"] = _count_tag(recs, "pending_wash_rush")
    section["pending_wash_nonrush"] = _count_tag(recs, "pending_wash_nonrush")
    section["pending_wash_total"] = _count_tag(recs, "pending_wash")
    section["yet_to_fold"] = _count_tag(recs, "yet_to_fold")
    section["issues"] = _count_tag(recs, "issues")
    section["workitems"] = _count_tag(recs, "workitems")
    section["last_rush_wash"] = last_rush_wash
    section["last_nonrush_wash"] = last_nonrush_wash
    section["last_wash_overall"] = last_wash_overall
    section["pending_wash_rush_ids"] = sorted(
        str(r.get("bag_id")) for r in recs if "pending_wash_rush" in (r.get("drilldown_tags") or [])
    )
    section["pending_wash_nonrush_ids"] = sorted(
        str(r.get("bag_id")) for r in recs if "pending_wash_nonrush" in (r.get("drilldown_tags") or [])
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
    return {
        "at_vendor": av_sync,
        "ready_for_vendor": rfv_sync,
        "ready_for_vendor_enabled": bool(rfv_sync.get("enabled", True)),
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
                cursor, organization_id, user_id=user_id, period_start=period_start, period_end=period_end
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
    tags: set[str] = set()
    if in_incoming:
        tags.add("ready_for_vendor")
        if bucket:
            tags.add(f"rfv_{bucket}")
            if bucket.startswith("unknown") or bucket == "unknown_service":
                tags.add("rfv_unknown_needs_review")
    if in_facility_tracker:
        tags.add("facility_tracker")
        if bucket:
            tags.add(f"facility_{bucket}")
            if bucket.startswith("unknown") or bucket == "unknown_service":
                tags.add("facility_unknown_needs_review")
    active_eligible = in_pipeline
    if in_pipeline:
        tags.add("pipeline_work")
        tags.add("active_work")
        if bucket:
            tags.add(f"pipeline_{bucket}")
            tags.add(f"active_{bucket}")
        if has_weigh:
            tags.add("shift_weighed")
        else:
            tags.add("shift_not_weighed")
        if not has_start_cleaning:
            tags.add("pending_wash")
            if is_rush:
                tags.add("pending_wash_rush")
            elif rec_rush_label := _rush_label(bucket):
                if rec_rush_label == "Non-Rush":
                    tags.add("pending_wash_nonrush")
        if _qualifies_yet_to_fold(pending_row, events, completion):
            tags.add("yet_to_fold")
    if any(c.role == ROLE_ISSUES for c in period_credits):
        tags.add("issues")
    if any(c.role == ROLE_WORKITEMS for c in period_credits):
        tags.add("workitems")
    if wdiff.flagged:
        tags.add("weight_difference")
    elif active_eligible and wdiff.unavailable_reason:
        tags.add("weight_difference_unavailable")
    if completion.exception_code == "COMPLETED_WITHOUT_FINAL_CLEAN_SCAN":
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
    if not status and completion.completed:
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
    return {
        "bag_id": bid,
        "customer": customer,
        "service_type": _normalized_service_type(merged) or "UNKNOWN",
        "rush_bucket": bucket,
        "rush_label": _rush_label(bucket),
        "current_status": status or row_meta.get("lifecycle_status_label"),
        "last_scan_time": last_scan.isoformat() if isinstance(last_scan, datetime) else None,
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
    }


def _count_tag(records: list[dict[str, Any]], tag: str) -> int:
    return sum(1 for r in records if tag in (r.get("drilldown_tags") or []))


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
    flagged = _count_tag(records, "weight_difference")
    unavailable = _count_tag(active_records, "weight_difference_unavailable")
    return {
        "weighed": _metric_split_counts(active_records, "shift_weighed", active_only=True),
        "not_weighed": _metric_split_counts(active_records, "shift_not_weighed", active_only=True),
        "issues": _metric_split_counts(records, "issues"),
        "workitems": _metric_split_counts(records, "workitems"),
        "weight_difference": {
            "flagged": flagged,
            "unavailable": unavailable,
            "all": flagged,
            "rush": _count_tag_by_rush(records, "weight_difference", rush_filter="rush"),
            "non_rush": _count_tag_by_rush(records, "weight_difference", rush_filter="non_rush"),
        },
        "weight_difference_threshold_lbs": threshold,
        "weight_difference_status": (
            "flagged"
            if flagged
            else ("unavailable" if unavailable else "none")
        ),
        "rush_pending_wash": _metric_split_counts(active_records, "rush_pending_wash", active_only=True, rush_only_metric=True),
        "last_rush_wash": last_rush_wash,
        "yet_to_fold": _metric_split_counts(active_records, "yet_to_fold", active_only=True),
        "source": "Scan events + At Vendor staging",
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
        if "yet_to_fold" in (rec.get("drilldown_tags") or []):
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
    }


def _align_ready_for_vendor_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["total"] = _count_tag(records, "ready_for_vendor")
    section["rush_wf"] = _count_tag(records, "rfv_rush_wf")
    section["rush_hd"] = _count_tag(records, "rfv_rush_hd")
    section["nonrush_wf"] = _count_tag(records, "rfv_nonrush_wf")
    section["nonrush_hd"] = _count_tag(records, "rfv_nonrush_hd")
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
    section["pending_wash_rush"] = _count_tag(records, "pending_wash_rush")
    section["pending_wash_nonrush"] = _count_tag(records, "pending_wash_nonrush")
    section["pending_wash_total"] = _count_tag(records, "pending_wash")
    section["yet_to_fold"] = _count_tag(records, "yet_to_fold")
    section["issues"] = _count_tag(records, "issues")
    section["workitems"] = _count_tag(records, "workitems")
    _finalize_section_counts(section)


def _align_active_work_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    _align_pipeline_counts(section, records)


def _build_exceptions_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "completed_without_clean_rack": {"count": _count_tag(records, "completed_without_clean"), "drilldown_filter": "completed_without_clean", "source": "Scan events"},
        "create_issue": {"count": _count_tag(records, "issues"), "drilldown_filter": "issues", "source": "Scan events"},
        "workitems": {"count": _count_tag(records, "workitems"), "drilldown_filter": "workitems", "source": "Scan events"},
        "weight_difference": {"count": _count_tag(records, "weight_difference"), "drilldown_filter": "weight_difference", "source": "Scan events"},
        "unknown_service_speed": {"count": _count_tag(records, "unknown_speed_service"), "drilldown_filter": "unknown_speed_service", "source": "Portal scrape"},
        "checkout_not_recorded": {"count": _count_tag(records, "checkout_not_recorded"), "drilldown_filter": "checkout_not_recorded", "source": "Checkout staging"},
    }


def build_simple_shift_performance_payload(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    evaluation_time: datetime | None = None,
    include_debug: bool = False,
    slim_records: bool = False,
) -> dict[str, Any]:
    org = int(organization_id)
    settings = get_processing_settings(cursor, org)
    threshold = float(settings.get("weight_difference_threshold_lbs") or 5.0)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    target_date = period_end

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
    ready_for_vendor = _build_ready_for_vendor_section(pending, rfv_sync=rfv_sync)
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
    scope_b_ids = _load_bag_ids_with_et_activity(
        cursor, org, period_start=period_start, period_end=period_end
    )
    all_bag_ids = sorted(
        set(scope_b_ids)
        | set(incoming_rows.keys())
        | set(pending_by_bag.keys())
        | set(facility_entry_ids)
        | set(carryover_candidates)
    )

    meta_by_bag = _load_bag_metadata(cursor, org, all_bag_ids)
    for bid in all_bag_ids:
        base = meta_by_bag.get(bid) or {"bag_id": bid}
        pending_row = pending_by_bag.get(bid)
        merged = {**base, **{k: v for k, v in (pending_row or {}).items() if v is not None}}
        merged["effective_rush"] = resolve_effective_rush_for_row(merged, target_date)
        meta_by_bag[bid] = merged

    events_by_bag = _load_scan_events_for_bags(cursor, org, all_bag_ids)
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
        events = events_by_bag.get(bid) or []
        in_incoming = bid in incoming_rows
        in_staging = bid in active_candidates
        in_facility_tracker = bid in facility_entry_ids
        completion = evaluate_bag_completion_v2(events)
        completions_by_bag[bid] = completion
        in_pipeline = bag_is_pipeline_eligible(pending_row, completion, meta, events)
        if in_pipeline:
            pipeline_bag_ids.add(bid)
        elif in_staging and pending_row:
            if bag_is_sent_or_left(pending_row, completion, meta, events):
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

    employee_summary, employee_diagnostics = _build_employee_activity_summary(
        cursor, org, credits=all_credits, period_start=period_start, period_end=period_end, user_maps=user_maps
    )
    employee_cards = _build_employee_cards(employee_summary)
    exceptions_summary = _build_exceptions_summary(records)
    if ready_for_vendor.get("live"):
        _align_ready_for_vendor_counts(ready_for_vendor, records)
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
        )
        if include_debug
        else None
    )

    sections_under_review = {
        "shift_status": True,
        "employee_activity": True,
        "rush_checkout": True,
        "exceptions": True,
        "ready_for_vendor_live": bool(ready_for_vendor.get("live")),
    }

    return {
        "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "ready_for_vendor": ready_for_vendor,
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
        "employee_activity_summary": employee_summary,
        "employee_cards": employee_cards,
        "employee_diagnostics": employee_diagnostics,
        "exceptions_summary": exceptions_summary,
        "debug_audit": debug_audit,
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
        },
    }
