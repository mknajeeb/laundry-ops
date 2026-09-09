"""Request-scoped bulk lookups for ``list_time_records`` (N+1 elimination).

Preserves exact as-of semantics:
- Row ``worker_category``: employment history covering the session work day
  (America/New_York), with the same CURDATE lane fallback as
  ``worker_category_for_user``.
- Hourly rate: same precedence as ``resolve_worker_hourly_rate``, including
  category-for-rate resolved as **business today** (no work-day ``on=``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from backend.payroll_worker_categories import CATEGORY_LABELS, classify_employment_category
from backend.portal_system_users import (
    SYSTEM_EMPLOYMENT_CATEGORY_CODES,
    is_portal_system_only_user,
)
from backend.ta_helpers import table_exists, table_has_column


def _lanes_from_covering_kinds(kinds: list[str]) -> list[str]:
    """Mirror ``infer_user_form_lanes`` mapping from classified kinds."""
    if "system" in kinds:
        return []
    out: list[str] = []
    if "w2" in kinds:
        out.append("employee_w2")
    if "contractor_1099" in kinds:
        out.append("contractor_1099")
    if "temp" in kinds:
        out.append("temp_worker")
    if "tryout" in kinds:
        out.append("tryout")
    if not out:
        return ["employee_w2"]
    return out


def _category_from_lanes(lanes: list[str]) -> str:
    if "tryout" in lanes:
        return "tryout"
    has_1099 = "contractor_1099" in lanes
    has_temp = "temp_worker" in lanes
    if has_temp and not has_1099:
        return "temp"
    if has_1099:
        return "contractor_1099"
    return "w2"


def _covering_assignment_kinds(rows: list[dict], on_day: date) -> list[str]:
    from backend.employment_category_history import _parse_ymd

    kinds: list[str] = []
    for r in rows or []:
        start = _parse_ymd(r.get("effective_from"))
        end = _parse_ymd(r.get("effective_to"))
        if start and start > on_day:
            continue
        if end and end < on_day:
            continue
        kind = str(r.get("worker_category") or "") or classify_employment_category(
            r.get("code"), r.get("name")
        )
        if kind:
            kinds.append(kind)
    return kinds


@dataclass
class PayrollListLookupCache:
    organization_id: int
    today: date
    assignments_by_user: dict[int, list[dict]] = field(default_factory=dict)
    portal_system_ids: set[int] = field(default_factory=set)
    schedule_rate: dict[int, Optional[float]] = field(default_factory=dict)
    contractor_json: dict[int, dict] = field(default_factory=dict)
    user_rate: dict[int, Optional[float]] = field(default_factory=dict)
    employee_pay_rate: dict[int, Optional[float]] = field(default_factory=dict)
    _rate_result: dict[int, dict] = field(default_factory=dict)
    _cat_by_day: dict[tuple[int, str], str] = field(default_factory=dict)

    def category_for(self, user_id: int, on: Optional[date] = None) -> str:
        uid = int(user_id)
        on_day = on or self.today
        key = (uid, on_day.isoformat())
        cached = self._cat_by_day.get(key)
        if cached is not None:
            return cached
        if uid in self.portal_system_ids:
            self._cat_by_day[key] = "system"
            return "system"
        from backend.employment_category_history import category_from_employment_history

        rows = self.assignments_by_user.get(uid) or []
        from_history = category_from_employment_history(rows, on_day)
        if from_history:
            self._cat_by_day[key] = from_history
            return from_history
        # Legacy lane inference is CURDATE-only (same as worker_category_for_user).
        kinds_today = _covering_assignment_kinds(rows, self.today)
        if not kinds_today and not rows:
            lanes = ["employee_w2"]
        elif not kinds_today:
            lanes = ["employee_w2"]
        else:
            lanes = _lanes_from_covering_kinds(kinds_today)
        cat = _category_from_lanes(lanes) if lanes else "w2"
        self._cat_by_day[key] = cat
        return cat

    def rate_for(self, user_id: int) -> dict[str, Any]:
        uid = int(user_id)
        if uid in self._rate_result:
            return self._rate_result[uid]
        cat = self.category_for(uid, on=None)
        rate: Optional[float] = None
        source = "missing"
        sched = self.schedule_rate.get(uid)
        if sched and sched > 0:
            rate = sched
            source = "payroll_schedule"
        cj = self.contractor_json.get(uid) or {}
        if rate is None:
            cj_rate = cj.get("rate_per_hour") or cj.get("hourly_rate")
            if cj_rate is not None:
                try:
                    val = float(cj_rate)
                    if val > 0:
                        rate = val
                        source = "contractor_profile"
                except (TypeError, ValueError):
                    pass
        if rate is None:
            ur = self.user_rate.get(uid)
            if ur and ur > 0:
                rate = ur
                source = "user_rates"
        if rate is None and cat == "w2":
            ep = self.employee_pay_rate.get(uid)
            if ep and ep > 0:
                rate = ep
                source = "employee_profile"
        # Prefill fallback mirrors resolve_worker_hourly_rate: same cj / user_rates
        # sources already applied above; leave rate missing when those miss.
        out = {
            "user_id": uid,
            "worker_category": cat,
            "worker_category_label": CATEGORY_LABELS.get(cat, cat),
            "hourly_rate": rate,
            "rate_source": source,
            "rate_missing": rate is None or rate <= 0,
            "payment_method": str(cj.get("payment_method") or "").strip(),
        }
        self._rate_result[uid] = out
        return out


def _bulk_portal_system_user_ids(conn, user_ids: list[int]) -> set[int]:
    uids = sorted({int(u) for u in user_ids})
    if not uids:
        return set()
    ph = ",".join(["%s"] * len(uids))
    roles_by_user: dict[int, list[str]] = {uid: [] for uid in uids}
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            f"""
            SELECT ur.user_id, r.code
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id IN ({ph})
            ORDER BY ur.user_id, r.code
            """,
            tuple(uids),
        )
        for row in c.fetchall() or []:
            uid = int(row["user_id"])
            code = row.get("code")
            if code:
                roles_by_user.setdefault(uid, []).append(str(code).upper())
    except Exception:
        pass

    system_ids = {
        uid for uid, codes in roles_by_user.items() if is_portal_system_only_user(codes)
    }

    remaining = [uid for uid in uids if uid not in system_ids]
    if not remaining:
        return system_ids
    codes = sorted(SYSTEM_EMPLOYMENT_CATEGORY_CODES)
    code_ph = ",".join(["%s"] * len(codes))
    rem_ph = ",".join(["%s"] * len(remaining))
    try:
        c.execute(
            f"""
            SELECT DISTINCT uec.user_id
            FROM user_employment_categories uec
            JOIN employment_categories ec ON ec.id = uec.employment_category_id
            WHERE uec.user_id IN ({rem_ph})
              AND UPPER(TRIM(ec.code)) IN ({code_ph})
              AND uec.effective_from <= CURDATE()
              AND (uec.effective_to IS NULL OR uec.effective_to >= CURDATE())
            """,
            (*remaining, *codes),
        )
        for row in c.fetchall() or []:
            system_ids.add(int(row["user_id"]))
    except Exception:
        pass
    return system_ids


def _bulk_schedule_rates(
    conn, organization_id: int, user_ids: list[int]
) -> dict[int, Optional[float]]:
    out: dict[int, Optional[float]] = {uid: None for uid in user_ids}
    if not user_ids:
        return out
    chk = conn.cursor()
    if not table_exists(chk, "payroll_worker_profiles"):
        return out
    ph = ",".join(["%s"] * len(user_ids))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT user_id, default_hourly_rate
        FROM payroll_worker_profiles
        WHERE organization_id=%s AND user_id IN ({ph}) AND active=1
        """,
        (int(organization_id), *user_ids),
    )
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        if row.get("default_hourly_rate") is None:
            continue
        val = float(row["default_hourly_rate"])
        if val > 0:
            out[uid] = val
    return out


def _bulk_contractor_json(conn, user_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {uid: {} for uid in user_ids}
    if not user_ids:
        return out
    from backend.contractor_management import _json_load
    from backend.hr_compliance import ensure_hr_extended_profiles_table

    chk = conn.cursor()
    ensure_hr_extended_profiles_table(chk)
    ph = ",".join(["%s"] * len(user_ids))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT user_id, contractor_json
        FROM hr_extended_profiles
        WHERE user_id IN ({ph})
        """,
        tuple(user_ids),
    )
    for row in c.fetchall() or []:
        cj = _json_load(row.get("contractor_json")) or {}
        out[int(row["user_id"])] = cj if isinstance(cj, dict) else {}
    return out


def _bulk_user_rates(conn, user_ids: list[int]) -> dict[int, Optional[float]]:
    out: dict[int, Optional[float]] = {uid: None for uid in user_ids}
    if not user_ids:
        return out
    chk = conn.cursor()
    if not table_exists(chk, "user_rates"):
        return out
    ph = ",".join(["%s"] * len(user_ids))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT ur.user_id, ur.hourly_rate, ur.effective_date, ur.id
        FROM user_rates ur
        WHERE ur.user_id IN ({ph})
          AND (ur.end_date IS NULL OR ur.end_date >= CURDATE())
        ORDER BY ur.user_id ASC, ur.effective_date DESC, ur.id DESC
        """,
        tuple(user_ids),
    )
    seen: set[int] = set()
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        if uid in seen:
            continue
        seen.add(uid)
        if row.get("hourly_rate") is None:
            continue
        val = float(row["hourly_rate"])
        if val > 0:
            out[uid] = val
    return out


def _bulk_employee_pay_rates(conn, user_ids: list[int]) -> dict[int, Optional[float]]:
    out: dict[int, Optional[float]] = {uid: None for uid in user_ids}
    if not user_ids:
        return out
    chk = conn.cursor()
    if not table_exists(chk, "employee_profiles") or not table_has_column(
        chk, "users", "employee_id"
    ):
        return out
    ph = ",".join(["%s"] * len(user_ids))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT u.id AS user_id, ep.pay_rate
        FROM users u
        JOIN employee_profiles ep ON ep.employee_id = u.employee_id
        WHERE u.id IN ({ph})
          AND u.employee_id IS NOT NULL
        """,
        tuple(user_ids),
    )
    for row in c.fetchall() or []:
        if row.get("pay_rate") is None:
            continue
        val = float(row["pay_rate"])
        if val > 0:
            out[int(row["user_id"])] = val
    return out


def build_payroll_list_lookup_cache(
    conn,
    organization_id: int,
    user_ids: list[int],
) -> PayrollListLookupCache:
    from backend.business_time import business_today
    from backend.employment_category_history import load_employment_assignments_for_users

    uids = sorted({int(u) for u in user_ids or [] if u is not None})
    today = business_today()
    if not uids:
        return PayrollListLookupCache(organization_id=int(organization_id), today=today)

    assignments = load_employment_assignments_for_users(conn, uids)
    return PayrollListLookupCache(
        organization_id=int(organization_id),
        today=today,
        assignments_by_user=assignments,
        portal_system_ids=_bulk_portal_system_user_ids(conn, uids),
        schedule_rate=_bulk_schedule_rates(conn, int(organization_id), uids),
        contractor_json=_bulk_contractor_json(conn, uids),
        user_rate=_bulk_user_rates(conn, uids),
        employee_pay_rate=_bulk_employee_pay_rates(conn, uids),
    )
