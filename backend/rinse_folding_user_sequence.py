"""Per-user folding sequence, gaps, and activity/scoring summary (ET date range)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_folding_period import sql_period_filter_sql_and_args
from backend.rinse_folding_registry import ensure_rinse_folding_tables
from backend.rinse_bag_folding import (
    EXCEPTION_FOLDING_DURATION_TOO_LONG,
    EXCEPTION_FOLDING_DURATION_TOO_SHORT,
    EXCEPTION_MULTIPLE_FOLDING_SCANS,
)
from backend.rinse_folding_exception_rules import get_folding_exception_rules_typed
from backend.rinse_folding_scoring import row_included_in_scoring

RINSE_SCAN_TZ = "America/New_York"

DURATION_EXCEPTION_CODES = frozenset(
    {
        EXCEPTION_FOLDING_DURATION_TOO_SHORT,
        EXCEPTION_FOLDING_DURATION_TOO_LONG,
    }
)


def _effective_duration_seconds(row: dict[str, Any]) -> int | None:
    dur = row.get("duration_seconds")
    if dur is not None:
        try:
            d = int(dur)
            return d if d > 0 else None
        except (TypeError, ValueError):
            pass
    start = row.get("folding_start_at")
    end = row.get("folding_end_at")
    if isinstance(start, datetime) and isinstance(end, datetime):
        sec = int((end - start).total_seconds())
        return sec if sec > 0 else None
    return None


def _scoring_reason(row: dict[str, Any]) -> str:
    if int(row.get("excluded_from_performance") or 0):
        return "Excluded from performance"
    if row_included_in_scoring(row):
        code = str(row.get("exception_code") or "").strip()
        if code:
            return f"In scoring with warning: {code}"
        return "Included in scoring"
    st = str(row.get("scoring_status") or row.get("status") or "").upper()
    code = str(row.get("exception_code") or "").strip()
    if code:
        return f"Not in scoring: {code}"
    if st == "EXCEPTION":
        return "Exception — not in scoring"
    return "Not in scoring"


def _gap_from_previous(
    prev_end: datetime | None, cur_start: datetime | None
) -> tuple[float | None, str | None, bool]:
    if prev_end is None or cur_start is None:
        return None, "first_bag", False
    sec = int((cur_start - prev_end).total_seconds())
    if sec < 0:
        return 0.0, "overlap", True
    return round(sec / 60.0, 2), None, False


def build_user_folding_sequence(
    cursor,
    organization_id: int,
    *,
    user_name: str,
    period_start: date,
    period_end: date,
    date_field: str = "folding_work_date",
) -> dict[str, Any]:
    ensure_rinse_folding_tables(cursor)
    org = int(organization_id)
    uname = str(user_name or "").strip()
    if not uname:
        raise ValueError("user_name required")

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
    raw_rows = list(cursor.fetchall() or [])
    rules = get_folding_exception_rules_typed(cursor, org)
    min_duration_seconds = rules.min_duration_seconds
    max_duration_seconds = rules.max_duration_seconds

    seq_rows: list[dict[str, Any]] = []
    prev_end: datetime | None = None
    total_folding_sec = 0
    total_gap_sec = 0
    gap_count = 0
    scoring_folding_sec = 0
    scoring_lbs = 0.0
    scoring_bags = 0
    exception_codes: dict[str, int] = {}

    for i, row in enumerate(raw_rows, start=1):
        dur_sec = _effective_duration_seconds(row)
        dur_min = round(dur_sec / 60.0, 2) if dur_sec else None
        gap_min, gap_label, gap_overlap = _gap_from_previous(
            prev_end, row.get("folding_start_at")
        )
        if gap_min is not None and gap_label != "first_bag":
            gap_sec = int(gap_min * 60) if not gap_overlap else 0
            if gap_sec > 0:
                total_gap_sec += gap_sec
                gap_count += 1

        if dur_sec:
            total_folding_sec += dur_sec

        included = row_included_in_scoring(row)
        w = row.get("weight_lbs")
        if w is None:
            w = row.get("registry_weight_num")
        try:
            wlbs = float(w) if w is not None else 0.0
        except (TypeError, ValueError):
            wlbs = 0.0

        if included:
            scoring_bags += 1
            scoring_lbs += wlbs
            if dur_sec:
                scoring_folding_sec += dur_sec

        code = str(row.get("exception_code") or "").strip()
        if code:
            exception_codes[code] = exception_codes.get(code, 0) + 1

        below_min = bool(
            dur_sec is not None
            and min_duration_seconds > 0
            and dur_sec < min_duration_seconds
        )
        above_max = bool(
            dur_sec is not None
            and max_duration_seconds is not None
            and dur_sec > max_duration_seconds
        )
        multiple_folding_scans = code == EXCEPTION_MULTIPLE_FOLDING_SCANS
        duration_exception_code = (
            code
            if code in DURATION_EXCEPTION_CODES
            else (
                EXCEPTION_FOLDING_DURATION_TOO_SHORT
                if below_min
                else (
                    EXCEPTION_FOLDING_DURATION_TOO_LONG
                    if above_max
                    else None
                )
            )
        )
        other_exception_code = (
            code
            if code
            and not multiple_folding_scans
            and code not in DURATION_EXCEPTION_CODES
            else None
        )

        st = str(row.get("scoring_status") or row.get("status") or "").upper()
        scoring_reason = _scoring_reason(row)
        if below_min and included:
            scoring_reason = (
                f"Below {rules.min_duration_minutes} min minimum — should not be in scoring"
            )

        seq_rows.append(
            {
                "sequence": i,
                "bag_id": row.get("bag_id"),
                "customer": row.get("name_clean"),
                "weight_lbs": wlbs if wlbs else None,
                "folding_start_at": row.get("folding_start_at"),
                "folding_end_at": row.get("folding_end_at"),
                "duration_seconds": dur_sec,
                "duration_minutes": dur_min,
                "below_min_duration": below_min,
                "above_max_duration": above_max,
                "gap_minutes_from_previous": gap_min,
                "gap_label": gap_label or (
                    "Gap since previous bag" if i > 1 else "First bag"
                ),
                "gap_overlap": gap_overlap,
                "status": st or row.get("status"),
                "exception_code": code or None,
                "duration_exception_code": duration_exception_code,
                "multiple_folding_scans": multiple_folding_scans,
                "multiple_folding_scans_label": (
                    "Warning — in scoring"
                    if multiple_folding_scans and included
                    else (
                        "Exception — not in scoring"
                        if multiple_folding_scans
                        else None
                    )
                ),
                "other_exception_code": other_exception_code,
                "included_in_scoring": included,
                "scoring_reason": scoring_reason,
            }
        )
        end = row.get("folding_end_at")
        if isinstance(end, datetime):
            prev_end = end

    total_bags = len(seq_rows)
    not_in_scoring = sum(1 for r in seq_rows if not r.get("included_in_scoring"))
    exception_bags = sum(
        1
        for r in seq_rows
        if str(r.get("status") or "").upper() == "EXCEPTION"
        or not r.get("included_in_scoring")
    )
    scoring_hours = scoring_folding_sec / 3600.0 if scoring_folding_sec > 0 else 0.0
    scoring_bags_per_hour = (
        round(scoring_bags / scoring_hours, 4) if scoring_hours > 0 else None
    )
    scoring_lbs_per_hour = (
        round(scoring_lbs / scoring_hours, 4) if scoring_hours > 0 else None
    )

    below_min_count = sum(1 for r in seq_rows if r.get("below_min_duration"))
    multi_fold_warn = sum(
        1
        for r in seq_rows
        if r.get("multiple_folding_scans") and r.get("included_in_scoring")
    )
    multi_fold_exc = sum(
        1
        for r in seq_rows
        if r.get("multiple_folding_scans") and not r.get("included_in_scoring")
    )

    return {
        "user_name": uname,
        "date_start": period_start.isoformat(),
        "date_end": period_end.isoformat(),
        "date_field": date_field,
        "timezone": RINSE_SCAN_TZ,
        "rules": {
            "min_duration_minutes": rules.min_duration_minutes,
            "max_duration_minutes": rules.max_duration_minutes,
            "multiple_folding_scans_behavior": rules.multiple_folding_scans_behavior,
        },
        "summary": {
            "total_bags": total_bags,
            "total_lbs": round(
                sum(float(r.get("weight_lbs") or 0) for r in seq_rows), 2
            ),
            "total_folding_minutes": round(total_folding_sec / 60.0, 2),
            "total_gap_minutes": round(total_gap_sec / 60.0, 2),
            "avg_gap_minutes": round((total_gap_sec / 60.0) / gap_count, 2)
            if gap_count > 0
            else None,
            "scoring_bags": scoring_bags,
            "scoring_lbs": round(scoring_lbs, 2),
            "scoring_minutes": round(scoring_folding_sec / 60.0, 2),
            "scoring_bags_per_hour": scoring_bags_per_hour,
            "scoring_lbs_per_hour": scoring_lbs_per_hour,
            "exception_bags": exception_bags,
            "not_in_scoring_bags": not_in_scoring,
            "too_short_count": max(
                exception_codes.get("FOLDING_DURATION_TOO_SHORT", 0),
                below_min_count,
            ),
            "below_min_duration_count": below_min_count,
            "too_long_count": exception_codes.get("FOLDING_DURATION_TOO_LONG", 0),
            "missing_folding_count": exception_codes.get("MISSING_FOLDING", 0),
            "missing_clean_count": exception_codes.get("MISSING_CLEAN", 0),
            "multiple_folding_scans_count": exception_codes.get(
                "MULTIPLE_FOLDING_SCANS", 0
            ),
            "multiple_folding_scans_warnings": multi_fold_warn,
            "multiple_folding_scans_exceptions": multi_fold_exc,
            "multiple_clean_scans_count": exception_codes.get(
                "MULTIPLE_CLEAN_SCANS", 0
            ),
        },
        "rows": seq_rows,
    }
