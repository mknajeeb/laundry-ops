"""Employee folding productivity: clocked time vs gaming/scoring records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_bag_folding import parse_stored_warning_codes
from backend.rinse_folding_et import (
    eastern_now,
    naive_et_day_end_exclusive,
    period_datetime_bounds_et,
)
from backend.rinse_folding_period import sql_period_filter_sql_and_args
from backend.rinse_folding_registry import ensure_rinse_folding_tables
from backend.rinse_folding_scoring import row_included_in_scoring, scoring_override_label

RINSE_SCAN_TZ = "America/New_York"


def _stored_duration_seconds(row: dict[str, Any]) -> int | None:
    dur = row.get("duration_seconds")
    if dur is None:
        return None
    try:
        d = int(dur)
        return d if d > 0 else None
    except (TypeError, ValueError):
        return None


def _weight_lbs(row: dict[str, Any]) -> float | None:
    w = row.get("weight_lbs")
    if w is None:
        w = row.get("registry_weight_num")
    if w is None:
        return None
    try:
        v = float(w)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def load_user_performance_rows(
    cursor,
    organization_id: int,
    *,
    user_name: str,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
) -> list[dict[str, Any]]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    uname = str(user_name or "").strip()
    period_sql, period_args = sql_period_filter_sql_and_args(
        date_field, period_start, period_end
    )
    cursor.execute(
        f"""
        SELECT p.*,
               r.name_clean,
               r.weight_num AS registry_weight_num
        FROM rinse_folding_performance p
        INNER JOIN rinse_bag_registry r
          ON r.organization_id = p.organization_id AND r.bag_id = p.bag_id
        WHERE p.organization_id = %s
          AND p.assigned_user_name = %s
          AND r.completion_status = %s
          {period_sql}
        ORDER BY
          CASE WHEN p.folding_start_at IS NULL THEN 1 ELSE 0 END,
          p.folding_start_at ASC,
          CASE WHEN p.folding_end_at IS NULL THEN 1 ELSE 0 END,
          p.folding_end_at ASC,
          p.bag_id ASC
        """,
        (org, uname, COMPLETION_COMPLETED, *period_args),
    )
    return list(cursor.fetchall() or [])


def _record_reason(row: dict[str, Any]) -> str | None:
    ov = scoring_override_label(row)
    if ov:
        return ov
    code = str(row.get("exception_code") or "").strip()
    if code:
        return code
    st = str(row.get("scoring_status") or row.get("status") or "").strip()
    return st or None


def build_gaming_record_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        dur_sec = _stored_duration_seconds(row)
        dur_min = round(dur_sec / 60.0, 2) if dur_sec else None
        included = row_included_in_scoring(row)
        code = str(row.get("exception_code") or "").strip() or None
        st = str(row.get("scoring_status") or row.get("status") or "").strip() or None
        is_warning = bool(code and included)
        out.append(
            {
                "bag_id": row.get("bag_id"),
                "customer": row.get("name_clean"),
                "weight_lbs": _weight_lbs(row),
                "folding_start_at": row.get("folding_start_at"),
                "folding_end_at": row.get("folding_end_at"),
                "duration_seconds": dur_sec,
                "duration_minutes": dur_min,
                "status": st,
                "exception_code": code,
                "warning_codes": parse_stored_warning_codes(row.get("warning_codes")),
                "is_warning": is_warning,
                "included_in_scoring": included,
                "scoring_status": row.get("scoring_status"),
                "scoring_override": row.get("scoring_override"),
                "reason": _record_reason(row),
            }
        )
    return out


def _aggregate_bag_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_bags = len(rows)
    scoring_bags = sum(1 for r in rows if r.get("included_in_scoring"))
    not_in_scoring_bags = total_bags - scoring_bags
    total_lbs = round(sum(float(r.get("weight_lbs") or 0) for r in rows), 2)
    scoring_lbs = round(
        sum(float(r.get("weight_lbs") or 0) for r in rows if r.get("included_in_scoring")),
        2,
    )
    scoring_dur = sum(
        int(r.get("duration_seconds") or 0) for r in rows if r.get("included_in_scoring")
    )
    warning_count = sum(1 for r in rows if r.get("is_warning"))
    exception_count = sum(1 for r in rows if not r.get("included_in_scoring"))
    return {
        "total_bags": total_bags,
        "scoring_bags": scoring_bags,
        "not_in_scoring_bags": not_in_scoring_bags,
        "exception_bags": not_in_scoring_bags,
        "total_lbs": total_lbs,
        "scoring_lbs": scoring_lbs,
        "warning_count": warning_count,
        "exception_count": exception_count,
        "avg_minutes_per_scoring_bag": round((scoring_dur / 60.0) / scoring_bags, 2)
        if scoring_bags > 0 and scoring_dur > 0
        else None,
        "lbs_per_scoring_bag": round(scoring_lbs / scoring_bags, 2)
        if scoring_bags > 0 and scoring_lbs
        else None,
    }


def build_gaming_scoring_view(
    record_rows: list[dict[str, Any]], *, shift_id: int | None = None
) -> dict[str, Any]:
    summary = _aggregate_bag_totals(record_rows)
    return {
        "label": "Gaming / scoring records",
        "shift_id": shift_id,
        "summary": {
            **summary,
            "denominator_labels": {
                "used_for_scoring": "Used for scoring",
                "excluded_from_scoring": "Excluded from scoring",
            },
        },
        "rows": record_rows,
    }


def _last_rinse_sync_naive(cursor, organization_id: int) -> datetime | None:
    from backend.rinse_scrape_status import get_scheduled_scrape_status

    st = get_scheduled_scrape_status(cursor, int(organization_id))
    raw = (st.get("last_success") or {}).get("data_last_updated_at_raw")
    if raw is None:
        fin = (st.get("last_success") or {}).get("scrape_finished_at")
        if fin:
            try:
                return datetime.fromisoformat(str(fin).replace("Z", "+00:00")[:26]).replace(
                    "+00:00", ""
                )
            except ValueError:
                pass
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        import pandas as pd

        p = pd.to_datetime(raw, errors="coerce")
        if pd.isna(p):
            return None
        return p.to_pydatetime()
    except Exception:
        return None


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


def _bag_overlaps_shift(
    row: dict[str, Any], clock_in: datetime, clock_out: datetime
) -> bool:
    start = row.get("folding_start_at")
    end = row.get("folding_end_at")
    if not isinstance(clock_in, datetime):
        return False
    if isinstance(start, datetime) and start > clock_out:
        return False
    if isinstance(end, datetime) and end < clock_in:
        return False
    if isinstance(start, datetime):
        return True
    if isinstance(end, datetime):
        return end >= clock_in
    return False


def _shift_summary_from_bags(
    *,
    shift_id: int,
    employee_name: str | None,
    clock_in: datetime,
    clock_out_raw: datetime | None,
    effective_clock_out: datetime,
    is_active_estimate: bool,
    estimate_label: str | None,
    clocked_sec: int,
    bag_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    totals = _aggregate_bag_totals(bag_rows)
    clocked_hours = clocked_sec / 3600.0 if clocked_sec > 0 else 0.0
    total_bags = totals["total_bags"]
    total_lbs = totals["total_lbs"]
    return {
        "shift_id": shift_id,
        "employee_name": employee_name,
        "clock_in_at": clock_in,
        "clock_out_at": clock_out_raw,
        "effective_clock_out_at": effective_clock_out,
        "is_active": clock_out_raw is None,
        "is_active_estimate": is_active_estimate,
        "estimate_label": estimate_label,
        "clocked_hours": round(clocked_hours, 4),
        "clocked_minutes": round(clocked_sec / 60.0, 2),
        "total_bags": total_bags,
        "total_lbs": total_lbs,
        "scoring_bags": totals["scoring_bags"],
        "scoring_lbs": totals["scoring_lbs"],
        "not_in_scoring_bags": totals["not_in_scoring_bags"],
        "exception_bags": totals["not_in_scoring_bags"],
        "bags_per_clocked_hour": round(total_bags / clocked_hours, 4)
        if clocked_hours > 0
        else None,
        "lbs_per_clocked_hour": round(total_lbs / clocked_hours, 4)
        if clocked_hours > 0 and total_lbs
        else None,
    }


def _load_shift_sessions(
    cursor,
    organization_id: int,
    user_id: int,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    from backend.ta_helpers import table_exists

    org = int(organization_id)
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
        (org, int(user_id), end_exclusive, start_dt),
    )
    return list(cursor.fetchall() or [])


def build_clocked_productivity(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    employee_name: str | None,
    gaming_rows: list[dict[str, Any]],
    period_start: date,
    period_end: date,
    shift_id: int | None = None,
    shift_filter: str = "all",
) -> dict[str, Any]:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "shift_sessions"):
        return {
            "available": False,
            "message": "shift_sessions table not available",
            "shifts": [],
            "summary": None,
            "selected_shift_id": shift_id,
        }

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
        if shift_filter == "active" and not is_active:
            continue
        if shift_filter == "completed" and is_active:
            continue
        overlap_start = max(cin, start_dt)
        overlap_end = min(cout, end_incl)
        if overlap_end <= overlap_start:
            continue
        clocked_sec = int((overlap_end - overlap_start).total_seconds())
        bags = [r for r in gaming_rows if _bag_overlaps_shift(r, cin, cout)]
        shifts_out.append(
            _shift_summary_from_bags(
                shift_id=int(sh.get("id") or 0),
                employee_name=employee_name,
                clock_in=cin,
                clock_out_raw=sh.get("clock_out_at"),
                effective_clock_out=cout,
                is_active_estimate=is_est,
                estimate_label=est_label,
                clocked_sec=clocked_sec,
                bag_rows=bags,
            )
        )

    selected = None
    if shift_id is not None:
        selected = next((s for s in shifts_out if s["shift_id"] == int(shift_id)), None)
    elif len(shifts_out) == 1:
        selected = shifts_out[0]

    if selected:
        summary = {k: v for k, v in selected.items() if k != "shift_id"}
        summary["denominator_labels"] = {
            "bags_per_clocked_hour": "Bags per clocked hour",
            "lbs_per_clocked_hour": "Lbs per clocked hour",
        }
    elif shifts_out:
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
            for r in gaming_rows:
                if _bag_overlaps_shift(r, s["clock_in_at"], s["effective_clock_out_at"]):
                    seen_bags[str(r.get("bag_id") or "")] = r
        deduped = list(seen_bags.values())
        totals = _aggregate_bag_totals(deduped)
        clocked_hours = total_clocked_sec / 3600.0 if total_clocked_sec > 0 else 0.0
        summary = {
            "employee_name": employee_name,
            "clocked_hours": round(clocked_hours, 4),
            "clocked_minutes": round(total_clocked_sec / 60.0, 2),
            "shift_count": len(shifts_out),
            "total_bags": totals["total_bags"],
            "total_lbs": totals["total_lbs"],
            "scoring_bags": totals["scoring_bags"],
            "scoring_lbs": totals["scoring_lbs"],
            "not_in_scoring_bags": totals["not_in_scoring_bags"],
            "exception_bags": totals["not_in_scoring_bags"],
            "bags_per_clocked_hour": round(totals["total_bags"] / clocked_hours, 4)
            if clocked_hours > 0
            else None,
            "lbs_per_clocked_hour": round(totals["total_lbs"] / clocked_hours, 4)
            if clocked_hours > 0 and totals["total_lbs"]
            else None,
            "denominator_labels": {
                "bags_per_clocked_hour": "Bags per clocked hour",
                "lbs_per_clocked_hour": "Lbs per clocked hour",
            },
        }
    else:
        summary = None

    return {
        "available": True,
        "message": None,
        "shifts": shifts_out,
        "summary": summary,
        "selected_shift_id": (
            int(shift_id)
            if shift_id is not None
            else (selected.get("shift_id") if selected else None)
        ),
    }


def _gaming_rows_for_shift(
    gaming_rows: list[dict[str, Any]],
    shifts: list[dict[str, Any]],
    *,
    shift_id: int | None,
) -> list[dict[str, Any]]:
    if shift_id is None:
        return gaming_rows
    sh = next((s for s in shifts if s["shift_id"] == int(shift_id)), None)
    if not sh:
        return []
    cin = sh["clock_in_at"]
    cout = sh["effective_clock_out_at"]
    if not isinstance(cin, datetime) or not isinstance(cout, datetime):
        return []
    return [r for r in gaming_rows if _bag_overlaps_shift(r, cin, cout)]


# --- User map ---


def ensure_rinse_folding_user_map_table(cursor) -> None:
    from backend.ta_helpers import table_exists

    if table_exists(cursor, "rinse_folding_user_map"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_folding_user_map (
            id INT AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            rinse_user_name VARCHAR(255) NOT NULL,
            user_id INT NOT NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            notes TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_rfum_org_name (organization_id, rinse_user_name),
            KEY idx_rfum_user (organization_id, user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def get_user_map(cursor, organization_id: int, rinse_user_name: str) -> dict[str, Any] | None:
    ensure_rinse_folding_user_map_table(cursor)
    cursor.execute(
        """
        SELECT m.*, u.display_name, u.username
        FROM rinse_folding_user_map m
        INNER JOIN users u ON u.id = m.user_id
        WHERE m.organization_id = %s AND m.rinse_user_name = %s AND m.active = 1
        LIMIT 1
        """,
        (int(organization_id), str(rinse_user_name).strip()),
    )
    return cursor.fetchone()


def list_user_maps(cursor, organization_id: int) -> list[dict[str, Any]]:
    ensure_rinse_folding_user_map_table(cursor)
    cursor.execute(
        """
        SELECT m.*, u.display_name, u.username
        FROM rinse_folding_user_map m
        LEFT JOIN users u ON u.id = m.user_id
        WHERE m.organization_id = %s
        ORDER BY m.rinse_user_name ASC
        """,
        (int(organization_id),),
    )
    return list(cursor.fetchall() or [])


def upsert_user_map(
    cursor,
    organization_id: int,
    *,
    rinse_user_name: str,
    user_id: int,
    active: bool = True,
    notes: str | None = None,
) -> dict[str, Any]:
    ensure_rinse_folding_user_map_table(cursor)
    org = int(organization_id)
    name = str(rinse_user_name or "").strip()
    if not name:
        raise ValueError("rinse_user_name required")
    uid = int(user_id)
    cursor.execute(
        """
        INSERT INTO rinse_folding_user_map (
            organization_id, rinse_user_name, user_id, active, notes
        ) VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            user_id = VALUES(user_id),
            active = VALUES(active),
            notes = VALUES(notes),
            updated_at = CURRENT_TIMESTAMP
        """,
        (org, name, uid, 1 if active else 0, notes),
    )
    return get_user_map(cursor, org, name) or {}


def delete_user_map(cursor, organization_id: int, map_id: int) -> bool:
    ensure_rinse_folding_user_map_table(cursor)
    cursor.execute(
        """
        DELETE FROM rinse_folding_user_map
        WHERE organization_id = %s AND id = %s
        """,
        (int(organization_id), int(map_id)),
    )
    return int(cursor.rowcount or 0) > 0


def build_user_folding_productivity(
    cursor,
    organization_id: int,
    *,
    user_name: str,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
    shift_id: int | None = None,
    shift_filter: str = "all",
) -> dict[str, Any]:
    uname = str(user_name or "").strip()
    if not uname:
        raise ValueError("user_name required")
    sf = str(shift_filter or "all").strip().lower()
    if sf not in ("all", "active", "completed"):
        sf = "all"

    raw_rows = load_user_performance_rows(
        cursor,
        organization_id,
        user_name=uname,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
    )
    gaming_rows = build_gaming_record_rows(raw_rows)

    mapping = get_user_map(cursor, organization_id, uname)
    display = (mapping.get("display_name") or mapping.get("username")) if mapping else None
    employee_mapping = {
        "mapped": mapping is not None,
        "user_id": mapping.get("user_id") if mapping else None,
        "display_name": display,
        "rinse_user_name": uname,
    }

    if mapping and mapping.get("user_id"):
        clocked = build_clocked_productivity(
            cursor,
            organization_id,
            user_id=int(mapping["user_id"]),
            employee_name=display or uname,
            gaming_rows=gaming_rows,
            period_start=period_start,
            period_end=period_end,
            shift_id=shift_id,
            shift_filter=sf,
        )
        gaming_for_view = _gaming_rows_for_shift(
            gaming_rows, clocked.get("shifts") or [], shift_id=shift_id
        )
    else:
        clocked = {
            "available": False,
            "message": "No employee clock mapping for this Rinse user.",
            "shifts": [],
            "summary": None,
            "selected_shift_id": None,
            "map_user_hint": True,
        }
        gaming_for_view = gaming_rows

    gaming = build_gaming_scoring_view(
        gaming_for_view, shift_id=shift_id
    )

    return {
        "user_name": uname,
        "date_start": period_start.isoformat(),
        "date_end": period_end.isoformat(),
        "date_field": date_field,
        "timezone": RINSE_SCAN_TZ,
        "employee_mapping": employee_mapping,
        "clocked_productivity": clocked,
        "gaming_scoring": gaming,
    }
