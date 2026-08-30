"""Payroll period work-coverage completeness (eligible clocks ↔ effective batches).

A work period is historically complete only when every payroll-eligible approved
time record for that period is represented on a terminal/finalized payout batch.
Having every *existing* batch paid is not enough if Temp/W-2/1099 work was never
batched (or a paid batch was nuclear-deleted).

Uses the same category-as-of-work-date path as batch build
(`worker_category_for_user(..., on=work_date)`). Does not change period totals.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from backend.payroll_worker_categories import WORKER_CATEGORIES

# Categories that belong on payroll batches (exclude system).
_PAYROLL_ELIGIBLE_CATEGORIES = frozenset(c for c in WORKER_CATEGORIES if c != "system")


def _parse_session_ids(raw: Any) -> set[int]:
    if raw is None or raw == "":
        return set()
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return set()
    if isinstance(raw, (list, tuple, set)):
        out: set[int] = set()
        for x in raw:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out
    return set()


def _batch_is_effective(batch: dict) -> bool:
    """Paid/closed or payout-details finalized — same rule as analytics terminal."""
    st = str(batch.get("status") or "").strip().lower()
    if st in ("paid", "closed"):
        return True
    if batch.get("payout_details_finalized_at"):
        return True
    return False


def list_eligible_approved_session_facts(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
) -> list[dict]:
    """Lightweight approved session facts for coverage (same category-as-of as batches).

    Avoids full ``list_time_records`` (rates / role segments) so Period Comparison
    can check several weeks without multi-minute latency.
    """
    from backend.employment_category_history import (
        category_from_employment_history,
        load_employment_assignments_for_users,
    )
    from backend.payroll_operations import (
        _date_end_exclusive_dt,
        _date_start_dt,
        _session_work_date_et,
        ensure_payroll_hours_approved_column,
        time_record_status,
        worker_category_for_user,
    )
    from backend.ta_helpers import table_has_column

    chk = conn.cursor()
    ensure_payroll_hours_approved_column(chk)
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    has_hours_approved = table_has_column(chk, "shift_sessions", "payroll_hours_approved")
    has_override = table_has_column(chk, "shift_sessions", "manual_override")
    has_review = table_has_column(chk, "payroll_cycles", "review_state")
    org_clause = (
        "s.organization_id = %s" if has_ss_org else "u.organization_id = %s"
    )
    hours_sel = (
        ", s.payroll_hours_approved"
        if has_hours_approved
        else ", 0 AS payroll_hours_approved"
    )
    override_sel = ", s.manual_override" if has_override else ", 0 AS manual_override"
    review_sel = (
        ", pc.review_state AS payroll_cycle_review_state" if has_review else ""
    )
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT s.id, s.user_id, s.clock_in_at, s.status, s.net_work_seconds
               {hours_sel}{override_sel}{review_sel}
        FROM shift_sessions s
        JOIN users u ON u.id = s.user_id
        JOIN payroll_profiles pp ON pp.user_id = s.user_id
        JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
        WHERE {org_clause}
          AND s.clock_in_at >= %s
          AND s.clock_in_at < %s
        ORDER BY s.clock_in_at ASC, s.id ASC
        """,
        (
            int(organization_id),
            _date_start_dt(pay_period_start),
            _date_end_exclusive_dt(pay_period_end),
        ),
    )
    rows = c.fetchall() or []
    approved_rows = [r for r in rows if time_record_status(r) == "approved"]
    uids = sorted({int(r["user_id"]) for r in approved_rows})
    try:
        assignment_cache = load_employment_assignments_for_users(conn, uids)
    except Exception:
        assignment_cache = {uid: [] for uid in uids}

    cat_cache: dict[tuple[int, str], str] = {}
    out: list[dict] = []
    for row in approved_rows:
        uid = int(row["user_id"])
        work_day = _session_work_date_et(row.get("clock_in_at"))
        if not isinstance(work_day, date):
            continue
        day_key = work_day.isoformat()
        cache_key = (uid, day_key)
        if cache_key not in cat_cache:
            assigns = assignment_cache.get(uid) or []
            cat = category_from_employment_history(assigns, work_day)
            if not cat:
                # Rare: no covering history — same lane fallback as batch build.
                cat = worker_category_for_user(
                    conn, uid, on=work_day, assignments=assigns
                )
            cat_cache[cache_key] = cat
        cat = cat_cache[cache_key]
        if cat not in _PAYROLL_ELIGIBLE_CATEGORIES:
            continue
        hours = round(max(0, int(row.get("net_work_seconds") or 0)) / 3600.0, 2)
        if hours <= 0:
            continue
        out.append(
            {
                "id": int(row["id"]),
                "user_id": uid,
                "worker_category": cat,
                "approved_hours": hours,
                "work_date": day_key,
            }
        )
    return out


def load_effective_batch_coverage(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
) -> tuple[set[int], set[tuple[int, str]]]:
    """Return (session_ids, (user_id, worker_category)) on effective batches."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pb.id, pb.worker_category, pb.status, pb.payout_details_finalized_at,
               pbl.user_id, pbl.source_shift_session_ids
        FROM payout_batches pb
        LEFT JOIN payout_batch_lines pbl
          ON pbl.batch_id = pb.id AND pbl.organization_id = pb.organization_id
        WHERE pb.organization_id = %s
          AND pb.pay_period_start = %s
          AND pb.pay_period_end = %s
        """,
        (
            int(organization_id),
            str(pay_period_start)[:10],
            str(pay_period_end)[:10],
        ),
    )
    sessions: set[int] = set()
    user_cats: set[tuple[int, str]] = set()
    for row in c.fetchall() or []:
        if not _batch_is_effective(row):
            continue
        cat = str(row.get("worker_category") or "")
        uid = row.get("user_id")
        if uid is not None and cat:
            try:
                user_cats.add((int(uid), cat))
            except (TypeError, ValueError):
                continue
        sessions |= _parse_session_ids(row.get("source_shift_session_ids"))
    return sessions, user_cats


def iter_unbatched_eligible_records(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
    *,
    covered_sessions: Optional[set[int]] = None,
    covered_user_cats: Optional[set[tuple[int, str]]] = None,
    eligible_records: Optional[list[dict]] = None,
) -> list[dict]:
    """Approved payroll-eligible time records not on an effective batch.

    Representation: session id on an effective batch line, or (user, category)
    present on an effective batch (covers aggregated lines that omit an id).
    """
    if covered_sessions is None or covered_user_cats is None:
        sessions, user_cats = load_effective_batch_coverage(
            conn, organization_id, pay_period_start, pay_period_end
        )
        if covered_sessions is None:
            covered_sessions = sessions
        if covered_user_cats is None:
            covered_user_cats = user_cats

    records = eligible_records
    if records is None:
        records = list_eligible_approved_session_facts(
            conn, organization_id, pay_period_start, pay_period_end
        )
    unbatched: list[dict] = []
    for rec in records or []:
        cat = str(rec.get("worker_category") or "")
        if cat not in _PAYROLL_ELIGIBLE_CATEGORIES:
            continue
        try:
            hours = float(rec.get("approved_hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        if hours <= 0:
            continue
        try:
            sid = int(rec["id"])
            uid = int(rec["user_id"])
        except (TypeError, ValueError, KeyError):
            continue
        if sid in covered_sessions:
            continue
        if (uid, cat) in covered_user_cats:
            continue
        unbatched.append(rec)
    return unbatched


def period_eligible_work_fully_batched(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
) -> bool:
    """True when no approved eligible work remains outside effective batches."""
    return not iter_unbatched_eligible_records(
        conn, organization_id, pay_period_start, pay_period_end
    )


def period_completeness_status(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
    *,
    batches_terminal: bool,
) -> dict[str, Any]:
    """Return completeness flags for a work period (does not alter totals)."""
    if not batches_terminal:
        return {
            "is_complete": False,
            "completeness_status": "incomplete",
            "completeness_label": "Incomplete / payroll pending",
            "unbatched_eligible_hours": None,
            "unbatched_eligible_count": None,
        }
    unbatched = iter_unbatched_eligible_records(
        conn, organization_id, pay_period_start, pay_period_end
    )
    if unbatched:
        hours = round(sum(float(r.get("approved_hours") or 0) for r in unbatched), 2)
        return {
            "is_complete": False,
            "completeness_status": "incomplete",
            "completeness_label": "Incomplete / payroll pending",
            "unbatched_eligible_hours": hours,
            "unbatched_eligible_count": len(unbatched),
        }
    return {
        "is_complete": True,
        "completeness_status": "complete",
        "completeness_label": "Complete",
        "unbatched_eligible_hours": 0.0,
        "unbatched_eligible_count": 0,
    }


def filter_periods_with_full_work_coverage(
    conn,
    organization_id: int,
    periods: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Keep only periods whose eligible approved work is fully batched."""
    out: list[tuple[str, str]] = []
    for ps, pe in periods or []:
        if period_eligible_work_fully_batched(conn, organization_id, ps, pe):
            out.append((ps, pe))
    return out
