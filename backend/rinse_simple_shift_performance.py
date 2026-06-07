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
    FOLDED_COMPLETED,
    IN_WASHING,
    PENDING_WEIGHING,
    SENT_TO_RINSE,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
)
from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et
from backend.rinse_processing_productivity import _load_shift_sessions, _shift_effective_clock_out
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_start_cleaning_purpose
from backend.rinse_bag_stage_bounds import first_start_cleaning_after, gaming_events_from_records, lifecycle_anchor, events_on_or_after
from backend.rinse_scan_time import RINSE_SCAN_SOURCE_TIMEZONE
from backend.rinse_shift_analysis import (
    _load_scan_events_for_bags,
    _rush_bucket_key,
    _staging_logistics_expr,
    get_pending_bag_status,
)
from backend.ta_helpers import table_exists, table_has_column


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
    svc = str(row.get("service_type") or "WF").upper()
    if svc not in ("WF", "HD"):
        return "unknown_service"
    if rush == "rush":
        return f"rush_{svc.lower()}"
    if rush == "non_rush":
        return f"nonrush_{svc.lower()}"
    return f"unknown_rush_{svc.lower()}"


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
    for key in ("presence_last_refreshed_at", "last_refreshed_at", "last_seen_at"):
        raw = summary.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            return raw.isoformat()
        return str(raw)
    portal = pending.get("portal_alignment") or {}
    raw = portal.get("presence_last_refreshed_at")
    if isinstance(raw, datetime):
        return raw.isoformat()
    if raw:
        return str(raw)
    return None


def _build_ready_for_vendor_section(pending: Mapping[str, Any]) -> dict[str, Any]:
    incoming = pending.get("incoming") or {}
    rows = [r for r in (incoming.get("rows") or []) if isinstance(r, dict)]
    splits = _count_splits_from_rows(rows)
    return {
        "total": int(splits.get("total") or 0),
        "rush_wf": int(splits.get("rush_wf") or 0),
        "rush_hd": int(splits.get("rush_hd") or 0),
        "nonrush_wf": int(splits.get("nonrush_wf") or 0),
        "nonrush_hd": int(splits.get("nonrush_hd") or 0),
        "unknown_needs_review": int(splits.get("unknown_rush_wf") or 0)
        + int(splits.get("unknown_rush_hd") or 0)
        + int(splits.get("unknown_service") or 0),
        "source": "Rinse Ready for Vendor scrape",
        "last_refreshed_at": _presence_last_refreshed(pending),
        "drilldown_filter": "ready_for_vendor",
    }


def _build_active_work_section(pending: Mapping[str, Any]) -> dict[str, Any]:
    active_rows = [
        r
        for r in (pending.get("rows") or [])
        if isinstance(r, dict) and str(r.get("record_scope") or "") != "incoming"
    ]
    hd_rows = [
        r
        for r in (pending.get("rows") or [])
        if isinstance(r, dict) and str(r.get("record_scope") or "") == "hd_lifecycle"
    ]
    wf_rows = [r for r in active_rows if r not in hd_rows]
    splits = _count_splits_from_rows(wf_rows + hd_rows)
    checkout = pending.get("checkout_rush") or {}
    checkout_pending = int(checkout.get("checkout_pending") or 0)
    return {
        "total": int(splits.get("total") or 0),
        "rush_wf": int(splits.get("rush_wf") or 0),
        "rush_hd": int(splits.get("rush_hd") or 0),
        "nonrush_wf": int(splits.get("nonrush_wf") or 0),
        "nonrush_hd": int(splits.get("nonrush_hd") or 0),
        "unknown_needs_review": int(splits.get("unknown_rush_wf") or 0)
        + int(splits.get("unknown_rush_hd") or 0)
        + int(splits.get("unknown_service") or 0),
        "checkout_pending": checkout_pending,
        "source": "Latest confirmed Rinse scrape + active staging",
        "drilldown_filter": "active_work",
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
    for cr in credits:
        if not credit_in_et_period(cr, period_start=start_dt, period_end_exclusive=end_exclusive):
            continue
        emp = str(cr.employee or "").strip()
        if not emp:
            continue
        by_emp_role[(emp, cr.role)].append(cr)

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
                "diagnostic": diagnostic,
            }
        )

    return summaries


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
        cards.append(
            {
                "employee": employee,
                "clock_in_time": clock_in_raw,
                "last_activity_time": last_meta.get("last_activity_time"),
                "last_activity_type": last_meta.get("last_activity_type"),
                "last_activity_bag_id": last_meta.get("last_activity_bag_id"),
                "total_bags_touched": len(all_bags),
                "performance_hours": perf_hours,
                "bags_per_hour": bags_per_hour,
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
    in_active: bool,
    in_incoming: bool,
) -> dict[str, Any]:
    row_meta = dict(pending_row or {})
    merged = {**row_meta, **dict(meta)}
    customer = merged.get("name_clean") or merged.get("customer")
    bucket = _bucket_for_row(merged)
    completion = evaluate_bag_completion_v2(events)
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
    if in_active:
        tags.add("active_work")
        if bucket:
            tags.add(f"active_{bucket}")
        if has_weigh:
            tags.add("shift_weighed")
        else:
            tags.add("shift_not_weighed")
        if is_rush and not has_start_cleaning:
            tags.add("rush_pending_wash")
        if not completion.completed:
            tags.add("yet_to_fold")
        checkout = str(row_meta.get("checkout_status") or "")
        if checkout.endswith("NOT_CHECKED_OUT") or checkout == "CHECKOUT_PENDING":
            tags.add("checkout_pending")
    if any(c.role == ROLE_ISSUES for c in period_credits):
        tags.add("issues")
    if any(c.role == ROLE_WORKITEMS for c in period_credits):
        tags.add("workitems")
    if wdiff.flagged:
        tags.add("weight_difference")
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
        "service_type": str(merged.get("service_type") or "WF").upper(),
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
        "in_scope_a_active": in_active,
        "in_ready_for_vendor": in_incoming,
        "weight_difference": {
            "flagged": wdiff.flagged,
            "first_weight_lbs": wdiff.first_weight_lbs,
            "second_weight_lbs": wdiff.second_weight_lbs,
            "difference_lbs": wdiff.difference_lbs,
            "threshold_lbs": wdiff.threshold_lbs,
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
        "drilldown_tags": sorted(tags),
        "checkout_status": row_meta.get("checkout_status"),
        "source": "Scan events" if events else "Portal scrape",
    }


def _count_tag(records: list[dict[str, Any]], tag: str) -> int:
    return sum(1 for r in records if tag in (r.get("drilldown_tags") or []))


def _align_ready_for_vendor_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["total"] = _count_tag(records, "ready_for_vendor")
    section["rush_wf"] = _count_tag(records, "rfv_rush_wf")
    section["rush_hd"] = _count_tag(records, "rfv_rush_hd")
    section["nonrush_wf"] = _count_tag(records, "rfv_nonrush_wf")
    section["nonrush_hd"] = _count_tag(records, "rfv_nonrush_hd")
    section["unknown_needs_review"] = _count_tag(records, "rfv_unknown_needs_review")


def _align_active_work_counts(section: dict[str, Any], records: list[dict[str, Any]]) -> None:
    section["total"] = _count_tag(records, "active_work")
    section["rush_wf"] = _count_tag(records, "active_rush_wf")
    section["rush_hd"] = _count_tag(records, "active_rush_hd")
    section["nonrush_wf"] = _count_tag(records, "active_nonrush_wf")
    section["nonrush_hd"] = _count_tag(records, "active_nonrush_hd")
    section["checkout_pending"] = _count_tag(records, "checkout_pending")


def _build_exceptions_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "completed_without_clean_rack": {"count": _count_tag(records, "completed_without_clean"), "drilldown_filter": "completed_without_clean", "source": "Scan events"},
        "create_issue": {"count": _count_tag(records, "issues"), "drilldown_filter": "issues", "source": "Scan events"},
        "workitems": {"count": _count_tag(records, "workitems"), "drilldown_filter": "workitems", "source": "Scan events"},
        "weight_difference": {"count": _count_tag(records, "weight_difference"), "drilldown_filter": "weight_difference", "source": "Scan events"},
        "unknown_service_speed": {"count": _count_tag(records, "unknown_speed_service"), "drilldown_filter": "unknown_speed_service", "source": "Portal scrape"},
        "checkout_not_recorded": {"count": _count_tag(records, "checkout_pending"), "drilldown_filter": "checkout_pending", "source": "Checkout staging"},
    }


def build_simple_shift_performance_payload(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    evaluation_time: datetime | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    settings = get_processing_settings(cursor, org)
    threshold = float(settings.get("weight_difference_threshold_lbs") or 5.0)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    target_date = period_end

    pending = get_pending_bag_status(
        cursor, org, target_date=target_date, evaluation_time=evaluation_time
    )
    ready_for_vendor = _build_ready_for_vendor_section(pending)
    active_work = _build_active_work_section(pending)
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
    active_ids = set(pending_by_bag.keys()) - set(incoming_rows.keys())
    scope_b_ids = _load_bag_ids_with_et_activity(
        cursor, org, period_start=period_start, period_end=period_end
    )
    all_bag_ids = sorted(set(scope_b_ids) | set(incoming_rows.keys()) | active_ids)

    meta_by_bag = _load_bag_metadata(cursor, org, all_bag_ids)
    events_by_bag = _load_scan_events_for_bags(cursor, org, all_bag_ids)
    user_maps = _load_rinse_user_maps(cursor, org)

    records: list[dict[str, Any]] = []
    all_credits: list[BagActivityCredit] = []
    split = _split_counts()
    scope_b_completed = 0
    scope_b_sent = 0
    last_rush_wash: dict[str, Any] | None = None

    for bid in all_bag_ids:
        meta = meta_by_bag.get(bid) or {"bag_id": bid}
        pending_row = pending_by_bag.get(bid)
        if pending_row:
            meta = {**meta, **{k: v for k, v in pending_row.items() if v is not None}}
        events = events_by_bag.get(bid) or []
        in_incoming = bid in incoming_rows
        in_active = bid in active_ids
        rec = _record_from_bag(
            bid=bid,
            meta=meta,
            events=events,
            pending_row=pending_row,
            threshold=threshold,
            period_start=start_dt,
            period_end_exclusive=end_exclusive,
            in_active=in_active,
            in_incoming=in_incoming,
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
            is_rush = rec.get("rush_label") == "Rush"
            for ev in events:
                if not is_start_cleaning_purpose(ev.get("purpose")):
                    continue
                ts = ev.get("scanned_at_parsed")
                if not isinstance(ts, datetime) or not (start_dt <= ts < end_exclusive):
                    continue
                if is_rush and (last_rush_wash is None or ts > datetime.fromisoformat(last_rush_wash["at"])):
                    last_rush_wash = {
                        "at": ts.isoformat(),
                        "bag_id": bid,
                        "customer": rec.get("customer"),
                        "user": ev.get("user_name"),
                    }

    active_records = [r for r in records if r.get("in_scope_a_active")]
    shift_status = {
        "weighed": _count_tag(active_records, "shift_weighed"),
        "not_weighed": _count_tag(active_records, "shift_not_weighed"),
        "issues": _count_tag(records, "issues"),
        "workitems": _count_tag(records, "workitems"),
        "weight_difference": _count_tag(records, "weight_difference"),
        "weight_difference_threshold_lbs": threshold,
        "rush_pending_wash": _count_tag(active_records, "rush_pending_wash"),
        "last_rush_wash": last_rush_wash,
        "yet_to_fold": _count_tag(active_records, "yet_to_fold"),
        "source": "Scan events + active staging",
    }

    employee_summary = _build_employee_activity_summary(
        cursor, org, credits=all_credits, period_start=period_start, period_end=period_end, user_maps=user_maps
    )
    employee_cards = _build_employee_cards(employee_summary)
    exceptions_summary = _build_exceptions_summary(records)
    _align_ready_for_vendor_counts(ready_for_vendor, records)
    _align_active_work_counts(active_work, records)

    return {
        "timezone": RINSE_SCAN_SOURCE_TIMEZONE,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "ready_for_vendor": ready_for_vendor,
        "current_active_work": active_work,
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
        "exceptions_summary": exceptions_summary,
        "records": records,
        "settings": {
            "weight_difference_threshold_lbs": threshold,
            "washing_minutes": settings.get("washing_minutes"),
            "drying_minutes": settings.get("drying_minutes"),
            "reject_after_create_issue_minutes": settings.get("reject_after_create_issue_minutes"),
        },
    }
