"""Shift Analysis Dashboard: pending work, team summary, overall vs scoring."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_folding_registry import aggregate_folding_leaderboard
from backend.rinse_folding_scoring import row_included_in_scoring
from backend.rinse_operations_dashboard import effective_rush_expr
from backend.rinse_processing_productivity import build_processing_productivity
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_start_cleaning_purpose, is_weight_entry_purpose
from backend.ta_helpers import table_exists, table_has_column


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


def get_pending_bag_status(
    cursor,
    organization_id: int,
    *,
    target_date: date,
) -> dict[str, Any]:
    """
    Pending/completed bag counts by rush group using registry completion_status
    and purpose-based processing buckets.
    """
    org = int(organization_id)
    td = target_date
    rush = _empty_pending_group()
    non_rush = _empty_pending_group()
    combined = _empty_pending_group()
    drilldown_rows: list[dict[str, Any]] = []

    if not table_exists(cursor, "rinse_bag_registry"):
        return {
            "date": td.isoformat(),
            "completion_field": "registry.completion_status",
            "groups": {"rush": rush, "non_rush": non_rush, "combined": combined},
            "rows": [],
        }

    rush_expr = effective_rush_expr("r")
    done_expr = f"UPPER(COALESCE(r.completion_status, '')) = '{COMPLETION_COMPLETED}'"
    cursor.execute(
        f"""
        SELECT r.bag_id, r.name_clean, r.weight_num, {rush_expr} AS effective_rush,
               CASE WHEN {done_expr} THEN 1 ELSE 0 END AS is_completed
        FROM rinse_bag_registry r
        WHERE r.organization_id = %s AND r.date_clean = %s
        """,
        (org, td),
    )
    registry_rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    bag_ids = [str(r.get("bag_id") or "").strip() for r in registry_rows if r.get("bag_id")]
    purpose_flags = _bag_purpose_flags(cursor, org, bag_ids)

    for row in registry_rows:
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
    proc_settings = get_processing_settings(cursor, org)
    clock_hours = _sum_shift_clock_hours(cursor, org, period_start, period_end)

    lb_rows = leaderboard.get("users") or []
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
