"""Read-only 3-mode folding productivity (bag-wise, work-span, clock-hour)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_folding_et import (
    eastern_now,
    naive_et_day_end_exclusive,
    period_datetime_bounds_et,
)
from backend.rinse_folding_period import sql_period_filter_sql_and_args
from backend.rinse_folding_registry import ensure_rinse_folding_tables
from backend.rinse_folding_scoring import row_included_in_scoring, sql_scoring_included_predicate

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


def _gap_from_previous(
    prev_end: datetime | None, cur_start: datetime | None
) -> tuple[float | None, str | None, bool, int]:
    if prev_end is None or cur_start is None:
        return None, "first_bag", False, 0
    sec = int((cur_start - prev_end).total_seconds())
    if sec < 0:
        return 0.0, "overlap", True, 0
    return round(sec / 60.0, 2), None, False, sec


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


def build_sequence_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seq_rows: list[dict[str, Any]] = []
    prev_end: datetime | None = None
    for i, row in enumerate(raw_rows, start=1):
        dur_sec = _stored_duration_seconds(row)
        dur_min = round(dur_sec / 60.0, 2) if dur_sec else None
        gap_min, gap_label, gap_overlap, gap_sec = _gap_from_previous(
            prev_end, row.get("folding_start_at")
        )
        included = row_included_in_scoring(row)
        code = str(row.get("exception_code") or "").strip() or None
        st = str(row.get("scoring_status") or row.get("status") or "").strip() or None
        seq_rows.append(
            {
                "sequence": i,
                "bag_id": row.get("bag_id"),
                "customer": row.get("name_clean"),
                "weight_lbs": _weight_lbs(row),
                "folding_start_at": row.get("folding_start_at"),
                "folding_end_at": row.get("folding_end_at"),
                "duration_seconds": dur_sec,
                "duration_minutes": dur_min,
                "gap_minutes_from_previous": gap_min,
                "gap_seconds_from_previous": gap_sec if i > 1 else None,
                "gap_label": gap_label or ("First bag" if i == 1 else "Gap since previous bag"),
                "gap_overlap": gap_overlap,
                "status": st,
                "exception_code": code,
                "included_in_scoring": included,
                "scoring_status": row.get("scoring_status"),
                "scoring_override": row.get("scoring_override"),
            }
        )
        end = row.get("folding_end_at")
        if isinstance(end, datetime):
            prev_end = end
    return seq_rows


def _aggregate_bag_totals(seq_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_bags = len(seq_rows)
    scoring_bags = sum(1 for r in seq_rows if r.get("included_in_scoring"))
    exception_bags = total_bags - scoring_bags
    total_lbs = round(sum(float(r.get("weight_lbs") or 0) for r in seq_rows), 2)
    scoring_lbs = round(
        sum(float(r.get("weight_lbs") or 0) for r in seq_rows if r.get("included_in_scoring")),
        2,
    )
    total_folding_sec = sum(int(r.get("duration_seconds") or 0) for r in seq_rows)
    scoring_folding_sec = sum(
        int(r.get("duration_seconds") or 0)
        for r in seq_rows
        if r.get("included_in_scoring")
    )
    total_gap_sec = sum(int(r.get("gap_seconds_from_previous") or 0) for r in seq_rows)
    gap_count = sum(1 for r in seq_rows if (r.get("gap_seconds_from_previous") or 0) > 0)
    folding_hours = total_folding_sec / 3600.0 if total_folding_sec > 0 else 0.0
    return {
        "total_bags": total_bags,
        "scoring_bags": scoring_bags,
        "exception_bags": exception_bags,
        "total_lbs": total_lbs,
        "scoring_lbs": scoring_lbs,
        "total_folding_minutes": round(total_folding_sec / 60.0, 2),
        "scoring_folding_minutes": round(scoring_folding_sec / 60.0, 2),
        "avg_minutes_per_bag": round((total_folding_sec / 60.0) / total_bags, 2)
        if total_bags > 0 and total_folding_sec > 0
        else None,
        "total_gap_minutes": round(total_gap_sec / 60.0, 2),
        "avg_gap_minutes": round((total_gap_sec / 60.0) / gap_count, 2)
        if gap_count > 0
        else None,
        "bags_per_folding_hour": round(total_bags / folding_hours, 4)
        if folding_hours > 0
        else None,
        "lbs_per_folding_hour": round(total_lbs / folding_hours, 4)
        if folding_hours > 0 and total_lbs
        else None,
        "total_folding_seconds": total_folding_sec,
        "total_gap_seconds": total_gap_sec,
    }


def build_mode_a_bag_wise(seq_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _aggregate_bag_totals(seq_rows)
    return {
        "label": "Bag-wise performance",
        "denominator_note": "Rates use sum of stored bag duration_seconds (per folding hour).",
        "summary": {
            **totals,
            "denominator_labels": {
                "bags_per_folding_hour": "Bags per folding hour",
                "lbs_per_folding_hour": "Lbs per folding hour",
            },
        },
        "rows": seq_rows,
    }


def build_mode_b_work_span(seq_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _aggregate_bag_totals(seq_rows)
    starts = [r.get("folding_start_at") for r in seq_rows if r.get("folding_start_at")]
    ends = [r.get("folding_end_at") for r in seq_rows if r.get("folding_end_at")]
    work_start = min(starts) if starts else None
    work_end = max(ends) if ends else None
    window_sec = (
        int((work_end - work_start).total_seconds())
        if isinstance(work_start, datetime) and isinstance(work_end, datetime)
        else 0
    )
    window_min = round(window_sec / 60.0, 2) if window_sec > 0 else 0.0
    folding_min = totals["total_folding_minutes"]
    gap_min = totals["total_gap_minutes"]
    idle_min = round(max(0.0, window_min - folding_min), 2) if window_min else 0.0
    window_hours = window_sec / 3600.0 if window_sec > 0 else 0.0
    folding_hours = totals["total_folding_seconds"] / 3600.0 if totals["total_folding_seconds"] > 0 else 0.0
    return {
        "label": "Work-span performance",
        "span_note": (
            "First recorded bag folding start → last recorded bag folding end "
            "(stored rinse_folding_performance only)."
        ),
        "summary": {
            "work_window_start": work_start,
            "work_window_end": work_end,
            "work_window_minutes": window_min,
            "folding_minutes": folding_min,
            "gap_minutes": gap_min,
            "idle_minutes": idle_min,
            "total_bags": totals["total_bags"],
            "scoring_bags": totals["scoring_bags"],
            "exception_bags": totals["exception_bags"],
            "total_lbs": totals["total_lbs"],
            "scoring_lbs": totals["scoring_lbs"],
            "bags_per_work_span_hour": round(totals["total_bags"] / window_hours, 4)
            if window_hours > 0
            else None,
            "lbs_per_work_span_hour": round(totals["total_lbs"] / window_hours, 4)
            if window_hours > 0 and totals["total_lbs"]
            else None,
            "bags_per_folding_hour": totals["bags_per_folding_hour"],
            "lbs_per_folding_hour": totals["lbs_per_folding_hour"],
            "denominator_labels": {
                "bags_per_work_span_hour": "Bags per work-span hour",
                "lbs_per_work_span_hour": "Lbs per work-span hour",
                "bags_per_folding_hour": "Bags per folding hour",
                "lbs_per_folding_hour": "Lbs per folding hour",
            },
        },
        "rows": seq_rows,
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
            "Active shift estimate through last Rinse sync",
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


def build_mode_c_clock_hours(
    cursor,
    organization_id: int,
    *,
    user_id: int,
    seq_rows: list[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    if not table_exists(cursor, "shift_sessions"):
        return {
            "available": False,
            "message": "shift_sessions table not available",
            "summary": None,
            "shifts": [],
            "timeline": [],
            "rows": [],
        }

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
    shifts_raw = list(cursor.fetchall() or [])
    last_sync = _last_rinse_sync_naive(cursor, org)

    shift_bag_rows: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    total_clocked_sec = 0
    shifts_out: list[dict[str, Any]] = []

    for sh in shifts_raw:
        cin = sh.get("clock_in_at")
        cout, is_est, est_label = _shift_effective_clock_out(sh, last_sync=last_sync)
        if not isinstance(cin, datetime) or cout is None:
            continue
        overlap_start = max(cin, start_dt)
        overlap_end = min(cout, end_incl)
        if overlap_end <= overlap_start:
            continue
        clocked_sec = int((overlap_end - overlap_start).total_seconds())
        total_clocked_sec += clocked_sec
        ordered = [r for r in seq_rows if _bag_overlaps_shift(r, cin, cout)]
        totals = _aggregate_bag_totals(ordered)
        shift_bag_rows.extend(ordered)
        shifts_out.append(
            {
                "shift_id": sh.get("id"),
                "clock_in_at": cin,
                "clock_out_at": sh.get("clock_out_at"),
                "effective_clock_out_at": cout,
                "is_active_estimate": is_est,
                "estimate_label": est_label,
                "clocked_minutes": round(clocked_sec / 60.0, 2),
                "bags_in_shift": totals["total_bags"],
                "scoring_bags_in_shift": totals["scoring_bags"],
            }
        )
        timeline.append(
            {
                "type": "clock_in",
                "at": cin,
                "shift_id": sh.get("id"),
                "label": est_label,
            }
        )
        for r in ordered:
            gap_sec = int(r.get("gap_seconds_from_previous") or 0)
            if gap_sec > 0:
                timeline.append(
                    {
                        "type": "gap",
                        "minutes": r.get("gap_minutes_from_previous"),
                    }
                )
            timeline.append(
                {
                    "type": "bag",
                    "bag_id": r.get("bag_id"),
                    "folding_start_at": r.get("folding_start_at"),
                    "folding_end_at": r.get("folding_end_at"),
                    "included_in_scoring": r.get("included_in_scoring"),
                }
            )
        timeline.append(
            {
                "type": "clock_out",
                "at": cout,
                "shift_id": sh.get("id"),
                "is_estimate": is_est,
            }
        )

    seen: dict[str, dict[str, Any]] = {}
    for r in shift_bag_rows:
        bid = str(r.get("bag_id") or "")
        if bid:
            seen[bid] = r
    deduped = sorted(
        seen.values(),
        key=lambda x: (
            x.get("folding_start_at") is None,
            x.get("folding_start_at") or datetime.min,
            x.get("bag_id") or "",
        ),
    )
    all_shift_totals = _aggregate_bag_totals(deduped)
    total_folding_sec = int(all_shift_totals["total_folding_seconds"])
    total_gap_sec = int(all_shift_totals["total_gap_seconds"])
    clocked_hours = total_clocked_sec / 3600.0 if total_clocked_sec > 0 else 0.0
    folding_hours = total_folding_sec / 3600.0 if total_folding_sec > 0 else 0.0
    non_folding_min = round(
        max(0.0, total_clocked_sec / 60.0 - total_folding_sec / 60.0), 2
    )

    return {
        "available": True,
        "summary": {
            "clocked_minutes": round(total_clocked_sec / 60.0, 2),
            "folding_minutes_in_shift": round(total_folding_sec / 60.0, 2),
            "gap_minutes_in_shift": round(total_gap_sec / 60.0, 2),
            "non_folding_minutes_in_shift": non_folding_min,
            "total_bags": all_shift_totals["total_bags"],
            "scoring_bags": all_shift_totals["scoring_bags"],
            "exception_bags": all_shift_totals["exception_bags"],
            "total_lbs": all_shift_totals["total_lbs"],
            "scoring_lbs": all_shift_totals["scoring_lbs"],
            "bags_per_clocked_hour": round(all_shift_totals["total_bags"] / clocked_hours, 4)
            if clocked_hours > 0
            else None,
            "lbs_per_clocked_hour": round(all_shift_totals["total_lbs"] / clocked_hours, 4)
            if clocked_hours > 0 and all_shift_totals["total_lbs"]
            else None,
            "bags_per_folding_hour": round(all_shift_totals["total_bags"] / folding_hours, 4)
            if folding_hours > 0
            else None,
            "lbs_per_folding_hour": round(all_shift_totals["total_lbs"] / folding_hours, 4)
            if folding_hours > 0 and all_shift_totals["total_lbs"]
            else None,
            "denominator_labels": {
                "bags_per_clocked_hour": "Bags per clocked hour",
                "lbs_per_clocked_hour": "Lbs per clocked hour",
                "bags_per_folding_hour": "Bags per folding hour",
                "lbs_per_folding_hour": "Lbs per folding hour",
            },
        },
        "shifts": shifts_out,
        "timeline": timeline,
        "rows": deduped,
    }


def _diagnostics_short_bags(
    cursor, organization_id: int, seq_rows: list[dict[str, Any]], *, user_name: str
) -> list[dict[str, Any]]:
    incl_sql = sql_scoring_included_predicate("p")
    out: list[dict[str, Any]] = []
    for r in seq_rows:
        dur = r.get("duration_seconds")
        code = str(r.get("exception_code") or "")
        if dur is not None and int(dur) < 600:
            flagged = True
        elif code == "FOLDING_DURATION_TOO_SHORT":
            flagged = True
        else:
            flagged = False
        if not flagged:
            continue
        bag_id = r.get("bag_id")
        in_leaderboard = bool(r.get("included_in_scoring"))
        out.append(
            {
                "bag_id": bag_id,
                "duration_seconds": dur,
                "duration_minutes": r.get("duration_minutes"),
                "folding_start_at": r.get("folding_start_at"),
                "folding_end_at": r.get("folding_end_at"),
                "status": r.get("status"),
                "exception_code": code or None,
                "included_in_scoring": int(bool(r.get("included_in_scoring"))),
                "in_leaderboard_scoring": in_leaderboard,
                "visible_in_all_records": True,
                "expected_rule": (
                    "EXCEPTION / FOLDING_DURATION_TOO_SHORT / included_in_scoring=0 "
                    "when below min duration"
                ),
            }
        )
    return out


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
) -> dict[str, Any]:
    uname = str(user_name or "").strip()
    if not uname:
        raise ValueError("user_name required")
    raw_rows = load_user_performance_rows(
        cursor,
        organization_id,
        user_name=uname,
        period_start=period_start,
        period_end=period_end,
        date_field=date_field,
    )
    seq_rows = build_sequence_rows(raw_rows)
    mode_a = build_mode_a_bag_wise(seq_rows)
    mode_b = build_mode_b_work_span(seq_rows)

    mapping = get_user_map(cursor, organization_id, uname)
    employee_mapping = {
        "mapped": mapping is not None,
        "user_id": mapping.get("user_id") if mapping else None,
        "display_name": (mapping.get("display_name") or mapping.get("username"))
        if mapping
        else None,
        "rinse_user_name": uname,
    }

    if mapping and mapping.get("user_id"):
        mode_c = build_mode_c_clock_hours(
            cursor,
            organization_id,
            user_id=int(mapping["user_id"]),
            seq_rows=seq_rows,
            period_start=period_start,
            period_end=period_end,
        )
    else:
        mode_c = {
            "available": False,
            "message": "No employee clock mapping for this Rinse user.",
            "summary": None,
            "shifts": [],
            "timeline": [],
            "rows": [],
        }

    diagnostics = {
        "short_duration_bags": _diagnostics_short_bags(
            cursor, organization_id, seq_rows, user_name=uname
        ),
    }

    return {
        "user_name": uname,
        "date_start": period_start.isoformat(),
        "date_end": period_end.isoformat(),
        "date_field": date_field,
        "timezone": RINSE_SCAN_TZ,
        "employee_mapping": employee_mapping,
        "mode_a_bag_wise": mode_a,
        "mode_b_work_span": mode_b,
        "mode_c_clock_hours": mode_c,
        "diagnostics": diagnostics,
    }
