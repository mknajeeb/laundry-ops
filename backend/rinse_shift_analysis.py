"""Shift Analysis Dashboard: pending work, team summary, overall vs scoring."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_folding_registry import aggregate_folding_leaderboard
from backend.rinse_folding_scoring import row_included_in_scoring
from backend.rinse_operations_dashboard import (
    _completed_expr,
    _service_expr,
    effective_rush_expr,
)
from backend.rinse_order_search import _active_staging_where_sql
from backend.rinse_processing_productivity import build_processing_productivity
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_start_cleaning_purpose, is_weight_entry_purpose
from backend.rinse_shift_operational_exceptions import (
    OPERATIONAL_STAT_LABELS,
    aggregate_operational_stats,
    evaluate_bag_operational_profile,
)
from backend.ta_helpers import table_exists, table_has_column


def _load_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    org = int(organization_id)
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    chunk = 100
    for i in range(0, len(bag_ids), chunk):
        part = [b for b in bag_ids[i : i + chunk] if b]
        if not part:
            continue
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                out.setdefault(bid, []).append(row)
    return out


def build_operational_dashboard_data(
    cursor,
    organization_id: int,
    *,
    pending_payload: dict[str, Any],
    reject_no_start_cleaning_minutes: int | None = None,
) -> dict[str, Any]:
    """Evaluate operational exceptions and workitem stats for pending WF bags."""
    from backend.rinse_processing_settings import DEFAULT_REJECT_NO_START

    pending_rows = pending_payload.get("rows") or []
    if not isinstance(pending_rows, list):
        pending_rows = []
    reject_limit = int(reject_no_start_cleaning_minutes or DEFAULT_REJECT_NO_START)
    bag_ids = [
        str(r.get("bag_id") or "").strip()
        for r in pending_rows
        if isinstance(r, dict) and r.get("bag_id")
    ]
    events_by_bag = _load_scan_events_for_bags(cursor, int(organization_id), bag_ids)

    records: list[dict[str, Any]] = []
    for prow in pending_rows:
        if not isinstance(prow, dict):
            continue
        bid = str(prow.get("bag_id") or "").strip()
        if not bid:
            continue
        records.append(
            evaluate_bag_operational_profile(
                events_by_bag.get(bid) or [],
                bag_meta=prow,
                reject_no_start_cleaning_minutes=reject_limit,
            )
        )

    stats = aggregate_operational_stats(records)
    return {
        "stats": stats,
        "stat_labels": OPERATIONAL_STAT_LABELS,
        "records": records,
        "reject_no_start_cleaning_minutes": reject_limit,
        "total_operational_exceptions": (
            stats.get("order_reject_no_start_cleaning_after_limit", 0)
            + stats.get("completed_without_final_clean_scan", 0)
        ),
    }


def _empty_pending_group() -> dict[str, int]:
    return {
        "total": 0,
        "completed": 0,
        "pending": 0,
        "not_weighed": 0,
        "weighed_not_washed": 0,
        "in_washing": 0,
    }


def _accumulate_group(group: dict[str, int], *, completed: bool, bucket: str | None) -> None:
    group["total"] += 1
    if completed:
        group["completed"] += 1
    else:
        group["pending"] += 1
        if bucket == "not_weighed":
            group["not_weighed"] += 1
        elif bucket == "weighed_not_washed":
            group["weighed_not_washed"] += 1
        elif bucket == "in_washing":
            group["in_washing"] += 1


def _classify_pending_bucket(
    *,
    is_completed: bool,
    has_weight_entry: bool,
    has_start_cleaning: bool,
) -> str | None:
    if is_completed:
        return None
    if not has_weight_entry:
        return "not_weighed"
    if not has_start_cleaning:
        return "weighed_not_washed"
    return "in_washing"


def _bag_purpose_flags(cursor, organization_id: int, bag_ids: list[str]) -> dict[str, dict[str, bool]]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    org = int(organization_id)
    flags: dict[str, dict[str, bool]] = {}
    chunk = 200
    for i in range(0, len(bag_ids), chunk):
        part = bag_ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, purpose
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip()
            if not bid:
                continue
            st = flags.setdefault(bid, {"weight_entry": False, "start_cleaning": False})
            purpose = row.get("purpose")
            if is_weight_entry_purpose(purpose):
                st["weight_entry"] = True
            if is_start_cleaning_purpose(purpose):
                st["start_cleaning"] = True
    return flags


def _load_pending_bag_rows(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Portal-aligned WF bags: active orders_staging (same population as GET /dashboard),
    excluding HD service type, with registry completion when available. Also includes
    registry-only WF rows for target_date not already counted.
    """
    org = int(organization_id)
    td = target_date
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    portal_active_total = 0
    hd_excluded = 0

    has_staging = table_exists(cursor, "orders_staging") and table_has_column(
        cursor, "orders_staging", "ticket_id"
    )
    has_reg = table_exists(cursor, "rinse_bag_registry")

    if has_staging:
        active_where = _active_staging_where_sql(cursor)
        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_rush = table_has_column(cursor, "orders_staging", "rush_type")
        has_name = table_has_column(cursor, "orders_staging", "name_clean")
        has_weight = table_has_column(cursor, "orders_staging", "weight_num")
        rush_s = (
            effective_rush_expr("s", date_col="date_clean")
            if has_rush
            else "CASE WHEN s.date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
        )
        svc_s = _service_expr("s")
        org_clause = " AND s.organization_id = %s" if has_org else ""
        st_args: list[Any] = [org] if has_org else []

        if has_reg:
            reg_join = (
                "LEFT JOIN rinse_bag_registry r ON r.bag_id = s.ticket_id AND r.organization_id = s.organization_id"
                if has_org
                else "LEFT JOIN rinse_bag_registry r ON r.bag_id = s.ticket_id"
            )
            rush_final = f"COALESCE(NULLIF({effective_rush_expr('r')}, ''), UPPER({rush_s}))"
            name_expr = (
                "COALESCE(r.name_clean, s.name_clean)"
                if has_name
                else "r.name_clean"
            )
            weight_expr = (
                "COALESCE(r.weight_num, s.weight_num)"
                if has_weight
                else "r.weight_num"
            )
            completed_expr = f"CASE WHEN {_completed_expr('r')} THEN 1 ELSE 0 END"
        else:
            reg_join = ""
            rush_final = f"UPPER({rush_s})"
            name_expr = "s.name_clean" if has_name else "NULL"
            weight_expr = "s.weight_num" if has_weight else "NULL"
            completed_expr = "0"

        cursor.execute(
            f"""
            SELECT
                s.ticket_id AS bag_id,
                {svc_s} AS service_type,
                {rush_final} AS effective_rush,
                {completed_expr} AS is_completed,
                {name_expr} AS name_clean,
                {weight_expr} AS weight_num
            FROM orders_staging s
            {reg_join}
            WHERE ({active_where}){org_clause}
              AND s.ticket_id IS NOT NULL AND TRIM(s.ticket_id) != ''
            """,
            tuple(st_args),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            portal_active_total += 1
            svc = str(row.get("service_type") or "WF").upper()
            if svc != "WF":
                hd_excluded += 1
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if not bid or bid in seen:
                continue
            seen.add(bid)
            rows.append(row)

    if has_reg:
        rush_r = effective_rush_expr("r")
        svc_r = _service_expr("r")
        done_r = _completed_expr("r")
        cursor.execute(
            f"""
            SELECT
                r.bag_id,
                {svc_r} AS service_type,
                {rush_r} AS effective_rush,
                CASE WHEN {done_r} THEN 1 ELSE 0 END AS is_completed,
                r.name_clean,
                r.weight_num
            FROM rinse_bag_registry r
            WHERE r.organization_id = %s AND r.date_clean = %s
            """,
            (org, td),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            svc = str(row.get("service_type") or "WF").upper()
            if svc != "WF":
                continue
            bid = str(row.get("bag_id") or "").strip().upper()
            if not bid or bid in seen:
                continue
            seen.add(bid)
            rows.append(row)

    meta = {
        "scope": "active_portal_wf",
        "portal_active_total": portal_active_total,
        "hd_excluded": hd_excluded,
        "wf_total": len(rows),
    }
    return rows, meta


def get_pending_bag_status(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> dict[str, Any]:
    """
    Pending/completed WF bag counts by rush group. Population matches vendor portal
    active orders (GET /dashboard) with HD excluded; completion from registry when present.
    """
    org = int(organization_id)
    td = target_date
    rush = _empty_pending_group()
    non_rush = _empty_pending_group()
    combined = _empty_pending_group()
    drilldown_rows: list[dict[str, Any]] = []

    bag_rows, portal_meta = _load_pending_bag_rows(cursor, org, target_date=td)
    bag_ids = [str(r.get("bag_id") or "").strip() for r in bag_rows if r.get("bag_id")]
    purpose_flags = _bag_purpose_flags(cursor, org, bag_ids)

    for row in bag_rows:
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        is_rush = str(row.get("effective_rush") or "").upper() == "RUSH"
        is_completed = int(row.get("is_completed") or 0) == 1
        pf = purpose_flags.get(bid, {})
        bucket = _classify_pending_bucket(
            is_completed=is_completed,
            has_weight_entry=bool(pf.get("weight_entry")),
            has_start_cleaning=bool(pf.get("start_cleaning")),
        )
        group_key = "rush" if is_rush else "non_rush"
        for g in (rush if is_rush else non_rush, combined):
            _accumulate_group(g, completed=is_completed, bucket=bucket)
        drilldown_rows.append(
            {
                "bag_id": bid,
                "customer": row.get("name_clean"),
                "weight_lbs": row.get("weight_num"),
                "rush": is_rush,
                "rush_label": "Rush" if is_rush else "Non-Rush",
                "group": group_key,
                "is_completed": is_completed,
                "pending_bucket": bucket,
                "has_weight_entry": bool(pf.get("weight_entry")),
                "has_start_cleaning": bool(pf.get("start_cleaning")),
            }
        )

    return {
        "date": td.isoformat(),
        "completion_field": "registry.completion_status (COMPLETED = done)",
        "service_scope": "WF only (HD excluded)",
        "portal_alignment": portal_meta,
        "groups": {"rush": rush, "non_rush": non_rush, "combined": combined},
        "rows": drilldown_rows,
    }


def _sum_shift_clock_hours(cursor, organization_id: int, period_start: date, period_end: date) -> float:
    if not table_exists(cursor, "shift_sessions"):
        return 0.0
    from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et

    org = int(organization_id)
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    org_clause = ""
    args: list[Any] = [end_exclusive, start_dt]
    if table_has_column(cursor, "shift_sessions", "organization_id"):
        org_clause = " AND organization_id = %s"
        args = [org, end_exclusive, start_dt]
    cursor.execute(
        f"""
        SELECT clock_in_at, clock_out_at
        FROM shift_sessions
        WHERE clock_in_at < %s
          AND (clock_out_at IS NULL OR clock_out_at >= %s)
          AND status IN ('completed', 'active', 'auto_closed')
          {org_clause}
        """,
        tuple(args),
    )
    total_sec = 0
    for sh in cursor.fetchall() or []:
        if not isinstance(sh, dict):
            continue
        cin = sh.get("clock_in_at")
        cout = sh.get("clock_out_at") or end_incl
        if isinstance(cin, datetime) and isinstance(cout, datetime):
            os = max(cin, start_dt)
            oe = min(cout, end_incl)
            if oe > os:
                total_sec += int((oe - os).total_seconds())
    return round(total_sec / 3600.0, 4)


def build_shift_analysis_summary(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
    processing_activities: list[str] | None = None,
) -> dict[str, Any]:
    """Team/day summary combining clock hours, processing, and folding metrics."""
    org = int(organization_id)
    acts = processing_activities or ["weighing", "sorting", "wash_load"]

    leaderboard = aggregate_folding_leaderboard(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
    )
    processing = build_processing_productivity(
        cursor,
        org,
        period_start=period_start,
        period_end=period_end,
    )
    if not isinstance(processing, dict):
        processing = {}
    proc_settings = get_processing_settings(cursor, org)
    clock_hours = _sum_shift_clock_hours(cursor, org, period_start, period_end)

    lb_rows = leaderboard.get("users") if isinstance(leaderboard, dict) else []
    if not isinstance(lb_rows, list):
        lb_rows = []
    team = leaderboard.get("team") if isinstance(leaderboard.get("team"), dict) else {}
    rules_impact = leaderboard.get("period_bag_summary")
    if not isinstance(rules_impact, dict):
        rules_impact = {}
    scoring_bags = int(rules_impact.get("included_in_scoring") or team.get("bag_count") or 0)
    scoring_lbs = float(team.get("total_lbs") or 0)
    total_bags = int(team.get("bag_count") or 0)
    total_lbs = float(team.get("total_lbs") or 0)
    fold_hours = float(team.get("total_folding_seconds") or 0) / 3600.0

    proc_summary = processing.get("summary_all_users")
    if not isinstance(proc_summary, dict):
        proc_summary = {}
    proc_bags = int(proc_summary.get("total_bags") or 0)
    proc_hours = float(proc_summary.get("clocked_hours") or proc_summary.get("estimated_hours") or 0)
    proc_people = len(processing.get("users") or [])

    fold_people = len(lb_rows)

    overall = {
        "clocked_labor_hours": clock_hours,
        "processing_labor_hours": proc_hours,
        "folding_labor_hours": round(fold_hours, 4),
        "processing_people_count": proc_people,
        "folding_people_count": fold_people,
        "total_bags_processed": proc_bags,
        "total_bags_completed": total_bags,
        "total_lbs_processed": proc_summary.get("total_lbs"),
        "total_lbs_folded": total_lbs,
        "processing_bags_per_hour": proc_summary.get("bags_per_clocked_hour"),
        "folding_bags_per_hour": team.get("bags_per_hour"),
    }
    scoring = {
        "scoring_bags": scoring_bags,
        "scoring_lbs": scoring_lbs,
        "scoring_folding_hours": fold_hours,
        "scoring_processing_hours": proc_hours,
        "scoring_folding_bags_per_hour": team.get("bags_per_hour"),
        "scoring_folding_lbs_per_hour": team.get("lbs_per_hour"),
        "scoring_quality_percent": team.get("issue_free_percent"),
        "excluded_records": int(rules_impact.get("excluded_from_scoring") or 0),
        "exception_records_not_counted": int(rules_impact.get("excluded_from_scoring") or 0),
    }

    employees: list[dict[str, Any]] = []
    for row in lb_rows:
        if not isinstance(row, dict):
            continue
        uname = str(row.get("user_name") or "").strip()
        if not uname:
            continue
        employees.append(
            {
                "user_name": uname,
                "role": "folding",
                "clocked_hours": row.get("clocked_hours"),
                "overall_bags": row.get("bag_count"),
                "scoring_bags": row.get("bag_count"),
                "overall_lbs": row.get("total_lbs"),
                "scoring_lbs": row.get("scoring_lbs") or row.get("total_lbs"),
                "overall_bags_per_hour": row.get("bags_per_hour"),
                "scoring_bags_per_hour": row.get("bags_per_hour"),
                "overall_lbs_per_hour": row.get("lbs_per_hour"),
                "scoring_lbs_per_hour": row.get("lbs_per_hour"),
                "exceptions": row.get("exception_count") or row.get("issue_count"),
                "needs_review": row.get("exception_count") or 0,
            }
        )

    pending = get_pending_bag_status(cursor, org, target_date=period_end)
    reject_limit = int(proc_settings.get("reject_no_start_cleaning_minutes") or 30)
    operational = build_operational_dashboard_data(
        cursor,
        org,
        pending_payload=pending,
        reject_no_start_cleaning_minutes=reject_limit,
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "date_field": date_field,
        "selected_processing_activities": acts,
        "overall_production": overall,
        "scoring_data": scoring,
        "speed": {
            "processing": {
                "bags_per_hour": proc_summary.get("bags_per_clocked_hour"),
                "lbs_per_hour": proc_summary.get("lbs_per_clocked_hour"),
                "minutes_per_bag": proc_summary.get("minutes_per_bag"),
                "people_count": proc_people,
                "labor_hours": proc_hours,
            },
            "folding": {
                "bags_per_hour": team.get("bags_per_hour"),
                "lbs_per_hour": team.get("lbs_per_hour"),
                "minutes_per_bag": team.get("avg_minutes_per_bag"),
                "people_count": fold_people,
                "labor_hours": round(fold_hours, 4),
            },
            "combined": {
                "bags_per_hour": None,
                "lbs_per_hour": None,
                "labor_hours": round(clock_hours, 4),
                "people_count": max(proc_people, fold_people),
            },
        },
        "employees": employees,
        "pending": pending,
        "operational": operational,
        "processing_settings": proc_settings,
    }


def enrich_record_scoring_fields(row: dict[str, Any]) -> dict[str, Any]:
    included = row_included_in_scoring(row)
    code = str(row.get("exception_code") or "").strip()
    reason = code or (None if included else str(row.get("status") or ""))
    return {
        **row,
        "in_scoring": included,
        "reason_not_scoring": None if included else (reason or "Excluded"),
    }
