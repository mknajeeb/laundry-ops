"""Processing productivity: start-cleaning scans vs clocked hours."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_dedupe_schema
from backend.rinse_folding_et import (
    eastern_now,
    naive_et_day_end_exclusive,
    period_datetime_bounds_et,
)
from backend.rinse_processing_settings import get_processing_settings
from backend.rinse_scan_purpose import is_start_cleaning_purpose

RINSE_SCAN_TZ = "America/New_York"


def _weight_lbs(row: dict[str, Any]) -> float | None:
    w = row.get("weight_num")
    if w is None:
        return None
    try:
        v = float(w)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def load_start_cleaning_scan_rows(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    user_name: str | None = None,
) -> list[dict[str, Any]]:
    ensure_rinse_bag_scan_events_dedupe_schema(cursor)
    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)

    sql = """
        SELECT e.id AS scan_event_id,
               e.bag_id,
               e.user_name,
               e.purpose,
               e.scanned_at_parsed,
               e.scan_index,
               r.name_clean,
               r.weight_num
        FROM rinse_bag_scan_events e
        LEFT JOIN rinse_bag_registry r
          ON r.organization_id = e.organization_id AND r.bag_id = e.bag_id
        WHERE e.organization_id = %s
          AND e.scanned_at_parsed IS NOT NULL
          AND e.scanned_at_parsed >= %s
          AND e.scanned_at_parsed < %s
          AND LOWER(COALESCE(e.purpose, '')) LIKE %s
    """
    args: list[Any] = [org, start_dt, end_exclusive, "%start-cleaning%"]
    if user_name:
        sql += " AND e.user_name = %s"
        args.append(str(user_name).strip())
    sql += " ORDER BY e.user_name ASC, e.bag_id ASC, e.scanned_at_parsed ASC, e.scan_index ASC, e.id ASC"
    cursor.execute(sql, tuple(args))
    raw = list(cursor.fetchall() or [])
    return [r for r in raw if is_start_cleaning_purpose(r.get("purpose"))]


def dedupe_processing_scans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Earliest start-cleaning per (user_name, bag_id) in the loaded set."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        uname = str(row.get("user_name") or "").strip()
        bid = str(row.get("bag_id") or "").strip()
        if not uname or not bid:
            continue
        key = (uname, bid)
        prev = best.get(key)
        if prev is None:
            best[key] = row
            continue
        cur_ts = row.get("scanned_at_parsed")
        prev_ts = prev.get("scanned_at_parsed")
        if isinstance(cur_ts, datetime) and isinstance(prev_ts, datetime):
            if cur_ts < prev_ts:
                best[key] = row
            elif cur_ts == prev_ts:
                if int(row.get("scan_index") or 0) < int(prev.get("scan_index") or 0):
                    best[key] = row
        elif cur_ts is not None and prev_ts is None:
            best[key] = row
    return list(best.values())


def _estimated_seconds(settings: dict[str, Any]) -> int:
    return int(settings.get("total_seconds_per_bag") or 0)


def build_processing_record_rows(
    deduped: list[dict[str, Any]],
    *,
    settings: dict[str, Any],
    shift_windows: list[tuple[datetime, datetime]] | None = None,
) -> list[dict[str, Any]]:
    est_sec = _estimated_seconds(settings)
    est_min = round(est_sec / 60.0, 2) if est_sec else 0.0
    out: list[dict[str, Any]] = []
    for row in deduped:
        scan_at = row.get("scanned_at_parsed")
        shift_linked = False
        if shift_windows and isinstance(scan_at, datetime):
            for cin, cout in shift_windows:
                if cin <= scan_at <= cout:
                    shift_linked = True
                    break
        out.append(
            {
                "bag_id": row.get("bag_id"),
                "customer": row.get("name_clean"),
                "weight_lbs": _weight_lbs(row),
                "start_cleaning_at": scan_at,
                "scan_user_name": str(row.get("user_name") or "").strip() or None,
                "scan_event_id": row.get("scan_event_id"),
                "estimated_processing_seconds": est_sec,
                "estimated_processing_minutes": est_min,
                "shift_linked": shift_linked,
                "included_in_processing_count": True,
            }
        )
    out.sort(
        key=lambda r: (
            r.get("start_cleaning_at") is None,
            r.get("start_cleaning_at") or datetime.min,
            str(r.get("bag_id") or ""),
        )
    )
    return out


def _aggregate_bag_level(records: list[dict[str, Any]], *, settings: dict[str, Any]) -> dict[str, Any]:
    total_bags = len(records)
    total_lbs = round(sum(float(r.get("weight_lbs") or 0) for r in records), 2)
    est_sec = total_bags * _estimated_seconds(settings)
    est_hours = est_sec / 3600.0 if est_sec > 0 else 0.0
    return {
        "total_bags": total_bags,
        "total_lbs": total_lbs,
        "estimated_processing_seconds": est_sec,
        "estimated_processing_minutes": round(est_sec / 60.0, 2),
        "estimated_processing_hours": round(est_hours, 4),
        "avg_estimated_minutes_per_bag": round((est_sec / 60.0) / total_bags, 2)
        if total_bags and est_sec
        else None,
        "bags_per_estimated_processing_hour": round(total_bags / est_hours, 4)
        if est_hours > 0
        else None,
        "lbs_per_estimated_processing_hour": round(total_lbs / est_hours, 4)
        if est_hours > 0 and total_lbs
        else None,
        "denominator_labels": {
            "bags_per_estimated_processing_hour": "Bags per estimated processing hour",
            "lbs_per_estimated_processing_hour": "Lbs per estimated processing hour",
        },
    }


def _scan_in_shift(scan_at: datetime, clock_in: datetime, clock_out: datetime) -> bool:
    return clock_in <= scan_at <= clock_out


def _last_rinse_sync_naive(cursor, organization_id: int) -> datetime | None:
    from backend.rinse_folding_user_productivity import _last_rinse_sync_naive as _fold_sync

    return _fold_sync(cursor, organization_id)


def _as_naive_et(dt: datetime | None) -> datetime | None:
    if dt is None or not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _shift_effective_clock_out(
    shift: dict[str, Any], *, last_sync: datetime | None
) -> tuple[datetime | None, bool, str | None]:
    clock_out = shift.get("clock_out_at")
    if clock_out is not None:
        return clock_out, False, None
    if last_sync is not None:
        return (
            _as_naive_et(last_sync),
            True,
            "Active shift estimate through last successful Rinse sync",
        )
    return (
        _as_naive_et(eastern_now()),
        True,
        "Active shift estimate through current ET time",
    )


def _load_shift_sessions(
    cursor,
    organization_id: int,
    user_id: int,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "shift_sessions"):
        return []
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    cursor.execute(
        """
        SELECT id, clock_in_at, clock_out_at, status, net_work_seconds
        FROM shift_sessions
        WHERE organization_id = %s AND user_id = %s
          AND clock_in_at < %s
          AND (clock_out_at IS NULL OR clock_out_at >= %s)
        ORDER BY clock_in_at ASC
        """,
        (int(organization_id), int(user_id), end_exclusive, start_dt),
    )
    return list(cursor.fetchall() or [])


def _load_shift_sessions_bulk(
    cursor,
    organization_id: int,
    user_ids: list[int],
    period_start: date,
    period_end: date,
) -> dict[int, list[dict[str, Any]]]:
    """Load overlapping shift sessions for many users in one or few SQL round trips."""
    from backend.ta_helpers import table_exists

    ids = sorted({int(uid) for uid in user_ids if uid})
    if not ids or not table_exists(cursor, "shift_sessions"):
        return {}
    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    out: dict[int, list[dict[str, Any]]] = {uid: [] for uid in ids}
    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT user_id, id, clock_in_at, clock_out_at, status, net_work_seconds
            FROM shift_sessions
            WHERE organization_id = %s
              AND user_id IN ({placeholders})
              AND clock_in_at < %s
              AND (clock_out_at IS NULL OR clock_out_at >= %s)
            ORDER BY user_id, clock_in_at ASC
            """,
            (org, *part, end_exclusive, start_dt),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            uid_raw = row.get("user_id")
            if uid_raw is None:
                continue
            uid = int(uid_raw)
            if uid in out:
                out[uid].append(row)
    return out


def _employee_shift_window_from_sessions(
    sessions: list[dict[str, Any]],
    *,
    period_start: date,
    period_end: date,
    last_sync: datetime | None,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Earliest clock-in and latest effective clock-out overlapping ET day."""
    if not sessions:
        return None, None, "Clock-in missing"
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)
    day_clock_ins: list[datetime] = []
    span_clock_ins: list[datetime] = []
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
        if cin >= start_dt:
            day_clock_ins.append(cin)
        else:
            span_clock_ins.append(overlap_start)
        clock_outs.append(overlap_end)
    if day_clock_ins:
        clock_in = min(day_clock_ins)
    elif span_clock_ins:
        clock_in = min(span_clock_ins)
    else:
        return None, None, "Clock-in missing"
    return clock_in, max(clock_outs), None


def build_clocked_processing_summary(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    records: list[dict[str, Any]],
    period_start: date,
    period_end: date,
    employee_name: str | None = None,
    shift_filter: str = "all",
) -> dict[str, Any]:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "shift_sessions"):
        return {
            "available": False,
            "message": "shift_sessions table not available",
            "shifts": [],
            "summary": None,
        }

    sf = str(shift_filter or "all").strip().lower()
    shifts_raw = _load_shift_sessions(
        cursor, organization_id, user_id, period_start, period_end
    )
    last_sync = _last_rinse_sync_naive(cursor, organization_id)
    start_dt, end_incl = period_datetime_bounds_et(period_start, period_end)

    shifts_out: list[dict[str, Any]] = []
    for sh in shifts_raw:
        cin = sh.get("clock_in_at")
        cout, is_est, est_label = _shift_effective_clock_out(sh, last_sync=last_sync)
        if not isinstance(cin, datetime) or cout is None:
            continue
        is_active = sh.get("clock_out_at") is None
        if sf == "active" and not is_active:
            continue
        if sf == "completed" and is_active:
            continue
        overlap_start = max(cin, start_dt)
        overlap_end = min(cout, end_incl)
        if overlap_end <= overlap_start:
            continue
        clocked_sec = int((overlap_end - overlap_start).total_seconds())
        bags_in_shift = [
            r
            for r in records
            if isinstance(r.get("start_cleaning_at"), datetime)
            and _scan_in_shift(r["start_cleaning_at"], cin, cout)
        ]
        total_lbs = round(sum(float(r.get("weight_lbs") or 0) for r in bags_in_shift), 2)
        clocked_hours = clocked_sec / 3600.0 if clocked_sec > 0 else 0.0
        total_bags = len(bags_in_shift)
        shifts_out.append(
            {
                "shift_id": int(sh.get("id") or 0),
                "employee_name": employee_name,
                "clock_in_at": cin,
                "clock_out_at": sh.get("clock_out_at"),
                "effective_clock_out_at": cout,
                "is_active": is_active,
                "is_active_estimate": is_est,
                "estimate_label": est_label,
                "clocked_hours": round(clocked_hours, 4),
                "clocked_minutes": round(clocked_sec / 60.0, 2),
                "total_bags": total_bags,
                "total_lbs": total_lbs,
                "bags_per_clocked_hour": round(total_bags / clocked_hours, 4)
                if clocked_hours > 0
                else None,
                "lbs_per_clocked_hour": round(total_lbs / clocked_hours, 4)
                if clocked_hours > 0 and total_lbs
                else None,
            }
        )

    total_clocked_sec = 0
    seen_bags: dict[str, dict[str, Any]] = {}
    for s in shifts_out:
        cin = s["clock_in_at"]
        cout = s["effective_clock_out_at"]
        if isinstance(cin, datetime) and isinstance(cout, datetime):
            os = max(cin, start_dt)
            oe = min(cout, end_incl)
            if oe > os:
                total_clocked_sec += int((oe - os).total_seconds())
        for r in records:
            if isinstance(r.get("start_cleaning_at"), datetime) and _scan_in_shift(
                r["start_cleaning_at"], cin, cout
            ):
                seen_bags[str(r.get("bag_id") or "")] = r
    deduped = list(seen_bags.values())
    clocked_hours = total_clocked_sec / 3600.0 if total_clocked_sec > 0 else 0.0
    total_bags = len(deduped)
    total_lbs = round(sum(float(r.get("weight_lbs") or 0) for r in deduped), 2)

    summary = {
        "employee_name": employee_name,
        "clocked_hours": round(clocked_hours, 4),
        "clocked_minutes": round(total_clocked_sec / 60.0, 2),
        "shift_count": len(shifts_out),
        "total_bags": total_bags,
        "total_lbs": total_lbs,
        "bags_per_clocked_hour": round(total_bags / clocked_hours, 4)
        if clocked_hours > 0
        else None,
        "lbs_per_clocked_hour": round(total_lbs / clocked_hours, 4)
        if clocked_hours > 0 and total_lbs
        else None,
        "denominator_labels": {
            "bags_per_clocked_hour": "Bags per clocked hour",
            "lbs_per_clocked_hour": "Lbs per clocked hour",
        },
    }

    return {
        "available": True,
        "message": None,
        "shifts": shifts_out,
        "summary": summary,
    }


def _user_block(
    cursor,
    organization_id: int,
    *,
    user_name: str,
    period_start: date,
    period_end: date,
    settings: dict[str, Any],
    shift_filter: str,
    include_unmapped: bool,
) -> dict[str, Any] | None:
    from backend.rinse_folding_user_productivity import get_user_map

    uname = str(user_name or "").strip()
    if not uname:
        return None

    raw = load_start_cleaning_scan_rows(
        cursor,
        organization_id,
        period_start=period_start,
        period_end=period_end,
        user_name=uname,
    )
    deduped = dedupe_processing_scans(raw)
    mapping = get_user_map(cursor, organization_id, uname)
    display = (mapping.get("display_name") or mapping.get("username")) if mapping else None
    employee_mapping = {
        "mapped": mapping is not None,
        "user_id": mapping.get("user_id") if mapping else None,
        "display_name": display,
        "rinse_user_name": uname,
    }

    shift_windows: list[tuple[datetime, datetime]] = []
    clocked: dict[str, Any]
    if mapping and mapping.get("user_id"):
        clocked = build_clocked_processing_summary(
            cursor,
            organization_id,
            user_id=int(mapping["user_id"]),
            records=build_processing_record_rows(
                deduped, settings=settings, shift_windows=None
            ),
            period_start=period_start,
            period_end=period_end,
            employee_name=display or uname,
            shift_filter=shift_filter,
        )
        for sh in clocked.get("shifts") or []:
            cin = sh.get("clock_in_at")
            cout = sh.get("effective_clock_out_at")
            if isinstance(cin, datetime) and isinstance(cout, datetime):
                shift_windows.append((cin, cout))
    else:
        if not include_unmapped:
            return None
        clocked = {
            "available": False,
            "message": "No employee clock mapping for this Rinse user.",
            "shifts": [],
            "summary": None,
            "map_user_hint": True,
        }

    records = build_processing_record_rows(
        deduped, settings=settings, shift_windows=shift_windows or None
    )
    bag_level = _aggregate_bag_level(records, settings=settings)

    return {
        "user_name": uname,
        "employee_mapping": employee_mapping,
        "clocked_productivity": clocked,
        "bag_level": bag_level,
        "records": records,
    }


def build_processing_productivity(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    user_name: str | None = None,
    shift_filter: str = "all",
    include_unmapped: bool = True,
) -> dict[str, Any]:
    settings = get_processing_settings(cursor, organization_id)
    org = int(organization_id)

    if user_name and str(user_name).strip():
        block = _user_block(
            cursor,
            org,
            user_name=str(user_name).strip(),
            period_start=period_start,
            period_end=period_end,
            settings=settings,
            shift_filter=shift_filter,
            include_unmapped=True,
        )
        users = [block] if block else []
        records = (block or {}).get("records") or []
        summary_all = _team_summary_from_users(users, settings=settings)
        return {
            "role": "processing",
            "date_start": period_start.isoformat(),
            "date_end": period_end.isoformat(),
            "timezone": RINSE_SCAN_TZ,
            "settings": settings,
            "summary_all_users": summary_all,
            "users": users,
            "records": records,
        }

    raw = load_start_cleaning_scan_rows(
        cursor, org, period_start=period_start, period_end=period_end
    )
    deduped = dedupe_processing_scans(raw)
    by_user: dict[str, list[dict[str, Any]]] = {}
    for row in deduped:
        uname = str(row.get("user_name") or "").strip()
        if not uname:
            continue
        by_user.setdefault(uname, []).append(row)

    users: list[dict[str, Any]] = []
    for uname in sorted(by_user.keys()):
        block = _user_block(
            cursor,
            org,
            user_name=uname,
            period_start=period_start,
            period_end=period_end,
            settings=settings,
            shift_filter=shift_filter,
            include_unmapped=include_unmapped,
        )
        if block:
            users.append(block)

    all_records: list[dict[str, Any]] = []
    for u in users:
        all_records.extend(u.get("records") or [])

    return {
        "role": "processing",
        "date_start": period_start.isoformat(),
        "date_end": period_end.isoformat(),
        "timezone": RINSE_SCAN_TZ,
        "settings": settings,
        "summary_all_users": _team_summary_from_users(users, settings=settings),
        "users": users,
        "records": all_records,
    }


def _team_summary_from_users(
    users: list[dict[str, Any]], *, settings: dict[str, Any]
) -> dict[str, Any]:
    total_clocked_sec = 0.0
    total_bags = 0
    total_lbs = 0.0
    for u in users:
        clocked = u.get("clocked_productivity") or {}
        summ = clocked.get("summary") or {}
        if summ.get("clocked_hours"):
            total_clocked_sec += float(summ["clocked_hours"]) * 3600.0
        for r in u.get("records") or []:
            total_bags += 1
            total_lbs += float(r.get("weight_lbs") or 0)
    clocked_hours = total_clocked_sec / 3600.0 if total_clocked_sec > 0 else 0.0
    est_sec = total_bags * _estimated_seconds(settings)
    est_hours = est_sec / 3600.0 if est_sec > 0 else 0.0
    return {
        "clocked_hours": round(clocked_hours, 4),
        "total_bags": total_bags,
        "total_lbs": round(total_lbs, 2),
        "bags_per_clocked_hour": round(total_bags / clocked_hours, 4) if clocked_hours > 0 else None,
        "lbs_per_clocked_hour": round(total_lbs / clocked_hours, 4)
        if clocked_hours > 0 and total_lbs
        else None,
        "estimated_processing_minutes": round(est_sec / 60.0, 2),
        "estimated_processing_hours": round(est_hours, 4),
        "bags_per_estimated_processing_hour": round(total_bags / est_hours, 4)
        if est_hours > 0
        else None,
        "lbs_per_estimated_processing_hour": round(total_lbs / est_hours, 4)
        if est_hours > 0 and total_lbs
        else None,
    }
