"""Step-1 Employee Productivity from persisted day-bag snapshots (no scan chronology)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_at_vendor_module import AV_NON_RUSH, AV_RUSH
from backend.rinse_employee_workload_productivity import (
    UNASSIGNED_EMPLOYEE,
    normalize_rush_filter,
)

UNKNOWN_EMPLOYEE = "Unknown"
CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE = "EVIDENCE_PRE"


def _parse_weight(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rush_bucket_from_status(rush_status: Any) -> str:
    raw = str(rush_status or "").strip().upper().replace(" ", "_").replace("-", "_")
    if not raw:
        return ""
    if "NON" in raw:
        return AV_NON_RUSH
    if "RUSH" in raw:
        return AV_RUSH
    return raw


def _normalize_employee(name: Any) -> str:
    s = str(name or "").strip()
    if not s:
        return UNASSIGNED_EMPLOYEE
    return s


def _weight_lbs(row: Mapping[str, Any]) -> float | None:
    """
    Credited pounds for Employee Performance.

    WF: immutable Evidence PRE only (never POST / canonical / manager correction).
    HD and other services: preserve prior snapshot chain.
    """
    svc = str(row.get("service_type") or row.get("service_bucket") or "").upper()
    if svc == "WF":
        return _parse_weight(row.get("pre_weight_lbs"))
    for key in ("productivity_weight_lbs", "weight_lbs", "post_weight_lbs", "pre_weight_lbs"):
        lbs = _parse_weight(row.get(key))
        if lbs is not None:
            return lbs
    return None


def _wf_credited_weight_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Bag-level Evidence PRE credit fields for WF Employee Performance."""
    pre = _parse_weight(row.get("pre_weight_lbs"))
    # If projection already stored PRE into productivity_weight_lbs, prefer that
    # only when pre_weight_lbs is also present / equal — never invent from POST.
    projected = _parse_weight(row.get("productivity_weight_lbs"))
    credited = pre if pre is not None else None
    # Guard: if pre missing, do not use projected value that may be stale POST.
    if credited is None:
        return {
            "credited_weight_lbs": None,
            "credited_weight_source": None,
            "missing_production_credit_weight": True,
            "pre_weight_lbs": None,
            "pre_weight_at": None,
            "pre_weight_source": None,
        }
    # Prefer pre; projected may equal pre after re-sync.
    if projected is not None and abs(projected - credited) > 1e-6:
        # Prefer immutable pre_weight_lbs column over a stale projection.
        pass
    return {
        "credited_weight_lbs": credited,
        "credited_weight_source": CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE,
        "missing_production_credit_weight": False,
        "pre_weight_lbs": credited,
        "pre_weight_at": row.get("pre_weight_at") or row.get("productivity_pre_weight_at"),
        "pre_weight_source": row.get("pre_weight_source") or CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE,
    }

def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except (TypeError, ValueError):
        return None


def _row_matches_scope(
    row: Mapping[str, Any],
    *,
    include_hd: bool,
    rush_filter: str,
) -> bool:
    svc = str(row.get("service_type") or "").upper()
    if not include_hd and svc != "WF":
        return False
    rush = normalize_rush_filter(rush_filter)
    bucket = _rush_bucket_from_status(row.get("rush_status") or row.get("rush_bucket"))
    if rush == "rush" and bucket != AV_RUSH:
        return False
    if rush == "non_rush" and bucket != AV_NON_RUSH:
        return False
    return True


def _credit_eligible_day_bag(row: Mapping[str, Any]) -> bool:
    """Use persisted projection when present; else completed snapshot rows."""
    if row.get("productivity_credit_eligible") is not None:
        try:
            return int(row.get("productivity_credit_eligible")) == 1
        except (TypeError, ValueError):
            return bool(row.get("productivity_credit_eligible"))
    return str(row.get("effective_status") or "").lower() == "completed"


_HAS_PROD_PROJ_COLS: bool | None = None


def _day_bags_have_productivity_projection(cursor) -> bool:
    global _HAS_PROD_PROJ_COLS
    if _HAS_PROD_PROJ_COLS is not None:
        return _HAS_PROD_PROJ_COLS
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS c FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'rinse_shift_monitor_day_bags'
              AND COLUMN_NAME = 'productivity_credit_eligible'
            """
        )
        row = cursor.fetchone() or {}
        _HAS_PROD_PROJ_COLS = int((row.get("c") if isinstance(row, dict) else row[0]) or 0) > 0
    except Exception:
        _HAS_PROD_PROJ_COLS = False
    return _HAS_PROD_PROJ_COLS


def load_completed_productivity_day_bags(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    include_hd: bool = True,
    rush_filter: str = "all",
    employee: str | None = None,
) -> list[dict[str, Any]]:
    """Load credit-eligible day bags for productivity (no scan chronology)."""
    from backend.rinse_veewash_shift_day import ensure_shift_monitor_day_tables
    from backend.ta_helpers import table_exists

    ensure_shift_monitor_day_tables(cursor)
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return []

    has_proj = _day_bags_have_productivity_projection(cursor)
    if has_proj:
        where = [
            "organization_id = %s",
            "shift_date_et = %s",
            "(productivity_credit_eligible = 1 OR (productivity_credit_eligible IS NULL AND effective_status = 'completed'))",
        ]
    else:
        where = [
            "organization_id = %s",
            "shift_date_et = %s",
            "effective_status = 'completed'",
        ]
    params: list[Any] = [int(organization_id), selected_date_et]
    if employee:
        where.append(
            "COALESCE(NULLIF(TRIM(productivity_employee_name), ''), NULLIF(TRIM(canonical_completion_employee), ''), '') = %s"
            if has_proj
            else "COALESCE(NULLIF(TRIM(canonical_completion_employee), ''), '') = %s"
        )
        params.append(str(employee).strip())

    cols = """
        bag_id, service_type, rush_status, effective_status,
        pre_weight_lbs, post_weight_lbs, weight_lbs,
        canonical_completion_status, canonical_completion_timestamp,
        canonical_completion_employee, updated_at
    """
    if has_proj:
        cols += """,
        productivity_employee_name, productivity_completed_at,
        productivity_weight_lbs, productivity_credit_eligible,
        productivity_exclusion_reason
        """

    order_by = (
        "COALESCE(productivity_completed_at, canonical_completion_timestamp) ASC, bag_id ASC"
        if has_proj
        else "canonical_completion_timestamp ASC, bag_id ASC"
    )
    cursor.execute(
        f"""
        SELECT {cols}
        FROM rinse_shift_monitor_day_bags
        WHERE {' AND '.join(where)}
        ORDER BY {order_by}
        """,
        tuple(params),
    )
    out: list[dict[str, Any]] = []
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, dict):
            continue
        if not _credit_eligible_day_bag(raw):
            continue
        if not _row_matches_scope(raw, include_hd=include_hd, rush_filter=rush_filter):
            continue
        emp = _normalize_employee(
            raw.get("productivity_employee_name") or raw.get("canonical_completion_employee")
        )
        if employee and emp != str(employee).strip():
            continue
        ts = _parse_ts(raw.get("productivity_completed_at") or raw.get("canonical_completion_timestamp"))
        svc = str(raw.get("service_type") or "").upper()
        if svc == "WF":
            credit = _wf_credited_weight_fields(raw)
            lbs = credit["credited_weight_lbs"]
        else:
            credit = {
                "credited_weight_lbs": _weight_lbs(raw),
                "credited_weight_source": None,
                "missing_production_credit_weight": False,
                "pre_weight_lbs": _parse_weight(raw.get("pre_weight_lbs")),
                "pre_weight_at": None,
                "pre_weight_source": None,
            }
            lbs = credit["credited_weight_lbs"]
        bucket = _rush_bucket_from_status(raw.get("rush_status"))
        out.append(
            {
                "bag_id": str(raw.get("bag_id") or "").strip().upper(),
                "service_type": svc,
                "service_bucket": svc,
                "rush_status": raw.get("rush_status"),
                "rush_bucket": bucket,
                "rush_label": "Rush" if bucket == AV_RUSH else ("Non-Rush" if bucket == AV_NON_RUSH else None),
                "employee": emp,
                "credited_employee": emp,
                "completed_by_employee": emp,
                "completion_time": ts.isoformat(sep=" ") if ts else None,
                "completion_timestamp": ts.isoformat(sep=" ") if ts else None,
                "processed_time": ts.isoformat(sep=" ") if ts else None,
                # Display / totals: WF uses Evidence PRE only (null when missing).
                "weight_lbs": lbs,
                "completed_lbs": lbs,
                "credited_lbs": lbs,
                "processed_lbs": lbs,
                "credited_weight_lbs": credit.get("credited_weight_lbs"),
                "credited_weight_source": credit.get("credited_weight_source"),
                "missing_production_credit_weight": bool(
                    credit.get("missing_production_credit_weight")
                ),
                "pre_weight_lbs": credit.get("pre_weight_lbs")
                if svc == "WF"
                else (
                    float(raw["pre_weight_lbs"])
                    if raw.get("pre_weight_lbs") is not None
                    else None
                ),
                "pre_weight_at": credit.get("pre_weight_at"),
                "pre_weight_source": credit.get("pre_weight_source"),
                "evidence_pre_weight_lbs": credit.get("pre_weight_lbs")
                if svc == "WF"
                else (
                    float(raw["pre_weight_lbs"])
                    if raw.get("pre_weight_lbs") is not None
                    else None
                ),
                "post_weight_lbs": float(raw["post_weight_lbs"])
                if raw.get("post_weight_lbs") is not None
                else None,
                # Completed production output (POST) — independent of employee PRE credit.
                "output_weight_lbs": float(raw["post_weight_lbs"])
                if raw.get("post_weight_lbs") is not None
                else (
                    float(raw["weight_lbs"])
                    if raw.get("weight_lbs") is not None and svc != "WF"
                    else None
                ),
                "authoritative_post_weight_lbs": float(raw["post_weight_lbs"])
                if raw.get("post_weight_lbs") is not None
                else None,
                "evidence_post_weight_lbs": float(raw["post_weight_lbs"])
                if raw.get("post_weight_lbs") is not None
                else None,
                "output_weight_source": "day_bag_post_weight",
                "at_vendor_status": "Completed",
                "included_in_employee_productivity": True,
                "credit_from_day_snapshot": True,
                "updated_at": raw.get("updated_at"),
            }
        )
    return out


def _attach_roster_hours(
    cursor,
    organization_id: int,
    selected_date_et: date,
    employees: list[dict[str, Any]],
) -> None:
    """Lightweight hours from roster / payroll sessions — no employee day-scan walks."""
    from backend.daily_shift_roster import (
        calc_hours,
        list_roster_entries,
        parse_time_value,
        roster_entry_for_employee_name,
        roster_shift_datetimes,
    )
    from backend.rinse_processing_productivity import _load_shift_sessions_bulk
    from backend.rinse_simple_shift_performance import _employee_shift_window, _load_rinse_user_maps

    org = int(organization_id)
    roster_entries = list_roster_entries(cursor, org, roster_date=selected_date_et)
    user_maps = _load_rinse_user_maps(cursor, org)
    user_ids = [
        int(m["user_id"])
        for m in user_maps.values()
        if isinstance(m, dict) and m.get("user_id") is not None
    ]
    sessions_by_user = (
        _load_shift_sessions_bulk(cursor, org, user_ids, selected_date_et, selected_date_et)
        if user_ids
        else {}
    )
    window_cache: dict[Any, Any] = {}

    for emp in employees:
        name = str(emp.get("employee") or "")
        mapping = user_maps.get(name.casefold()) if name and name != UNASSIGNED_EMPLOYEE else None
        user_id = int(mapping["user_id"]) if mapping and mapping.get("user_id") else None
        clock_in = clock_out = None
        clock_diagnostic = None
        if user_id is not None:
            clock_in, clock_out, clock_diagnostic = _employee_shift_window(
                cursor,
                org,
                user_id=user_id,
                period_start=selected_date_et,
                period_end=selected_date_et,
                sessions_by_user=sessions_by_user,
                last_sync_loaded=True,
                window_cache=window_cache,
            )
        roster_entry = roster_entry_for_employee_name(name, roster_entries, user_maps=user_maps)
        if roster_entry:
            roster_in, roster_out = roster_shift_datetimes(roster_entry, selected_date_et)
            if clock_in is None and roster_in is not None:
                clock_in, clock_out = roster_in, roster_out
                clock_diagnostic = "Using daily shift roster times (no payroll clock-in)"
            start = parse_time_value(roster_entry.get("start_time"))
            end = parse_time_value(roster_entry.get("end_time"))
            break_min = int(roster_entry.get("break_minutes") or 0)
            roster_hours = calc_hours(start, end, break_min) if start and end else None
            if roster_hours and roster_hours > 0:
                productive_hours = round(float(roster_hours), 4)
                emp["productive_hours"] = productive_hours
                emp["worked_hours"] = productive_hours
                emp["wall_clock_hours"] = productive_hours
                bags = int(emp.get("completed_bags") or 0)
                lbs = float(emp.get("total_completed_lbs") or 0)
                emp["completed_bags_per_hour"] = round(bags / productive_hours, 4)
                emp["bags_per_hour"] = emp["completed_bags_per_hour"]
                emp["completed_lbs_per_hour"] = round(lbs / productive_hours, 4) if lbs else None
                emp["lbs_per_hour"] = emp["completed_lbs_per_hour"]
                emp["productivity_note"] = clock_diagnostic
                emp["clock_in_time"] = clock_in.isoformat() if clock_in else None
                emp["clock_out_time"] = clock_out.isoformat() if clock_out else None
                continue

        if clock_in is None:
            emp["productive_hours"] = None
            emp["worked_hours"] = None
            emp["bags_per_hour"] = None
            emp["lbs_per_hour"] = None
            emp["completed_bags_per_hour"] = None
            emp["completed_lbs_per_hour"] = None
            emp["productivity_note"] = clock_diagnostic or "Missing clock-in data"
            emp["clock_in_time"] = None
            emp["clock_out_time"] = None
            continue

        end = clock_out or emp.get("last_completion_time")
        end_ts = _parse_ts(end) if not isinstance(end, datetime) else end
        if end_ts is None:
            first = _parse_ts(emp.get("first_completion_time"))
            last = _parse_ts(emp.get("last_completion_time"))
            end_ts = last or first
        if end_ts is None or end_ts <= clock_in:
            emp["productive_hours"] = None
            emp["productivity_note"] = clock_diagnostic or "Missing clock-in data"
            continue
        productive_hours = round(max(0, (end_ts - clock_in).total_seconds()) / 3600.0, 4)
        emp["productive_hours"] = productive_hours
        emp["worked_hours"] = productive_hours
        emp["wall_clock_hours"] = productive_hours
        bags = int(emp.get("completed_bags") or 0)
        lbs = float(emp.get("total_completed_lbs") or 0)
        emp["completed_bags_per_hour"] = round(bags / productive_hours, 4) if productive_hours else None
        emp["bags_per_hour"] = emp["completed_bags_per_hour"]
        emp["completed_lbs_per_hour"] = (
            round(lbs / productive_hours, 4) if productive_hours and lbs else None
        )
        emp["lbs_per_hour"] = emp["completed_lbs_per_hour"]
        emp["productivity_note"] = clock_diagnostic
        emp["clock_in_time"] = clock_in.isoformat()
        emp["clock_out_time"] = clock_out.isoformat() if clock_out else None


def build_step1_snapshot_productivity_section(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    include_hd: bool = True,
    rush_filter: str = "all",
    include_bag_details: bool = False,
) -> dict[str, Any]:
    """
    Headline Employee Productivity from day-bag snapshot only.

    Does not load rinse_bag_scan_events chronology or rebuild at-vendor.
    """
    from backend.rinse_employee_productivity_presentation import _build_executive_summary

    bags = load_completed_productivity_day_bags(
        cursor,
        organization_id,
        selected_date_et,
        include_hd=include_hd,
        rush_filter=rush_filter,
    )
    by_emp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bag in bags:
        by_emp[str(bag["employee"])].append(bag)

    employees: list[dict[str, Any]] = []
    for emp_name, emp_bags in by_emp.items():
        emp_bags_sorted = sorted(
            emp_bags,
            key=lambda b: str(b.get("completion_timestamp") or b.get("bag_id") or ""),
        )
        lbs_vals = [float(b["weight_lbs"]) for b in emp_bags_sorted if b.get("weight_lbs") is not None]
        output_vals = [
            float(b["output_weight_lbs"])
            for b in emp_bags_sorted
            if b.get("output_weight_lbs") is not None
        ]
        first = emp_bags_sorted[0].get("completion_timestamp") if emp_bags_sorted else None
        last = emp_bags_sorted[-1].get("completion_timestamp") if emp_bags_sorted else None
        total_lbs = round(sum(lbs_vals), 2) if lbs_vals else 0.0
        total_output_lbs = round(sum(output_vals), 2) if output_vals else 0.0
        employees.append(
            {
                "employee": emp_name,
                "completed_bags": len(emp_bags_sorted),
                "credited_bags_count": len(emp_bags_sorted),
                "processed_bags_count": len(emp_bags_sorted),
                "total_completed_lbs": total_lbs,
                "total_credited_lbs": total_lbs,
                "total_output_lbs": total_output_lbs,
                "total_processed_lbs": total_lbs,
                "first_completion_time": first,
                "last_completion_time": last,
                "first_completed_time": first,
                "last_completed_time": last,
                "bags": emp_bags_sorted if include_bag_details else [],
                "workload_bags": emp_bags_sorted if include_bag_details else [],
                "processed_bags": emp_bags_sorted if include_bag_details else [],
                "bags_stripped_for_summary": not include_bag_details,
                "pending_completion_count": 0,
                "pending_completion_bags": [],
                "show_processed_completed_split": False,
                "weight_integrity_failure_count": 0,
                "credit_from_day_snapshot": True,
            }
        )

    _attach_roster_hours(cursor, organization_id, selected_date_et, employees)
    employees.sort(
        key=lambda e: (-(e.get("completed_bags") or 0), str(e.get("employee") or "").lower())
    )

    credited_total = len(bags)
    unassigned = sum(1 for b in bags if b.get("employee") == UNASSIGNED_EMPLOYEE)
    attributed = credited_total - unassigned
    missing_pre = sum(
        1
        for b in bags
        if str(b.get("service_type") or "").upper() == "WF"
        and b.get("missing_production_credit_weight")
    )
    wf_credited_lbs = round(
        sum(
            float(b["credited_weight_lbs"])
            for b in bags
            if str(b.get("service_type") or "").upper() == "WF"
            and b.get("credited_weight_lbs") is not None
        ),
        2,
    )
    recon = {
        "ok": True,
        "selected_date_et": selected_date_et.isoformat(),
        "rush_filter": normalize_rush_filter(rush_filter),
        "workload_completed_today": credited_total,
        "credited_total": credited_total,
        "credited_completed": credited_total,
        "employee_attributed_bag_count": attributed,
        "employee_credited_unique_bags": attributed,
        "unassigned_count": unassigned,
        "wf_credited_weight_source": CREDITED_WEIGHT_SOURCE_EVIDENCE_PRE,
        "wf_missing_production_credit_weight_count": missing_pre,
        "wf_credited_lbs_evidence_pre": wf_credited_lbs,
        "source": "shift_monitor_day_bags_snapshot",
    }
    banner = {
        "status": "reconciled",
        "workload_completed_today": credited_total,
        "employee_completed_bags_credited": attributed,
        "source": "shift_monitor_day_bags_snapshot",
    }

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "employees": employees,
        "executive_summary": _build_executive_summary(employees),
        "reconciliation": recon,
        "reconciliation_banner": banner,
        "completed_attribution_audit": [],
        "attribution_audit": [],
        "productivity_scope": "wf_plus_hd" if include_hd else "wf_only",
        "productivity_scope_label": "WF + HD" if include_hd else "WF Only",
        "include_hd_in_employee_productivity": include_hd,
        "productivity_rush_filter": normalize_rush_filter(rush_filter),
        "bags_stripped_for_summary": not include_bag_details,
        "snapshot_productivity": True,
    }


def build_employee_productivity_bags_page(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee: str,
    include_hd: bool = True,
    rush_filter: str = "all",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Paginated completed bags for one employee (summary expand)."""
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 25)))
    bags = load_completed_productivity_day_bags(
        cursor,
        organization_id,
        selected_date_et,
        include_hd=include_hd,
        rush_filter=rush_filter,
        employee=employee,
    )
    total = len(bags)
    start = (page - 1) * page_size
    chunk = bags[start : start + page_size]
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "employee": employee,
        "bags": chunk,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        },
    }


def project_productivity_fields_for_day_bag(row: Mapping[str, Any]) -> dict[str, Any]:
    """Compute productivity projection columns for snapshot upsert.

    WF credited pounds = immutable Evidence PRE only.
    HD / other services keep prior weight_lbs → post → pre chain.
    """
    eff = str(row.get("effective_status") or "").lower()
    eligible = eff == "completed"
    emp = row.get("canonical_completion_employee") or row.get("completed_by")
    ts = row.get("canonical_completion_timestamp") or row.get("completion_at")
    svc = str(row.get("service_type") or "").upper()
    if svc == "WF":
        lbs = _parse_weight(row.get("pre_weight_lbs"))
    else:
        lbs = _parse_weight(row.get("weight_lbs"))
        if lbs is None:
            lbs = _parse_weight(row.get("post_weight_lbs"))
        if lbs is None:
            lbs = _parse_weight(row.get("pre_weight_lbs"))
    return {
        "productivity_employee_name": (str(emp).strip() if emp else None) or None,
        "productivity_completed_at": ts,
        "productivity_weight_lbs": lbs,
        "productivity_credit_eligible": 1 if eligible else 0,
        "productivity_exclusion_reason": None
        if eligible
        else (f"effective_status={eff}" if eff else "not_completed"),
    }
