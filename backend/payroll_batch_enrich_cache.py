"""Request-scoped bulk lookups for payout batch enrichment (N+1 elimination).

Reuses ``PayrollListLookupCache`` rate/category semantics (same as
``resolve_worker_hourly_rate`` / ``worker_category_for_user`` for list + batch
display). Does not change payroll math or persisted line amounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from backend.payroll_list_lookup_cache import (
    PayrollListLookupCache,
    build_payroll_list_lookup_cache,
)
from backend.ta_helpers import json_safe, table_has_column


@dataclass
class PayrollBatchEnrichCache:
    """Shared across one details/history request for the line user set."""

    organization_id: int
    lookup: PayrollListLookupCache
    user_meta: dict[int, dict[str, str]] = field(default_factory=dict)
    sick_by_user: dict[int, dict[str, Any]] = field(default_factory=dict)
    _resolved_rates: dict[int, dict[str, Any]] = field(default_factory=dict)

    def rate_info_for(self, conn, user_id: int) -> dict[str, Any]:
        """Prefer bulk cache; fall back to ``resolve_worker_hourly_rate`` for prefill."""
        uid = int(user_id)
        if uid in self._resolved_rates:
            return self._resolved_rates[uid]
        info = self.lookup.rate_for(uid)
        # List cache omits payroll_prefill fallback; match resolve when still missing.
        if info.get("rate_missing"):
            from backend.payroll_workflow import resolve_worker_hourly_rate

            info = resolve_worker_hourly_rate(conn, uid, self.organization_id)
        self._resolved_rates[uid] = info
        return info

    def meta_for(self, user_id: int) -> dict[str, str]:
        uid = int(user_id)
        return self.user_meta.get(uid) or {"display_name": "", "employee_id": ""}

    def sick_for(self, user_id: int) -> Optional[dict[str, Any]]:
        return self.sick_by_user.get(int(user_id))


def bulk_user_display_meta(conn, user_ids: list[int]) -> dict[int, dict[str, str]]:
    uids = sorted({int(u) for u in user_ids or [] if u is not None})
    out: dict[int, dict[str, str]] = {
        uid: {"display_name": "", "employee_id": ""} for uid in uids
    }
    if not uids:
        return out
    chk = conn.cursor()
    select_cols = ["id", "display_name", "username"]
    if table_has_column(chk, "users", "employee_id"):
        select_cols.insert(1, "employee_id")
    ph = ",".join(["%s"] * len(uids))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"SELECT {', '.join(select_cols)} FROM users WHERE id IN ({ph})",
        tuple(uids),
    )
    for row in c.fetchall() or []:
        uid = int(row["id"])
        name = str(row.get("display_name") or row.get("username") or "").strip()
        emp_id = str(row.get("employee_id") or "").strip()
        out[uid] = {"display_name": name, "employee_id": emp_id}
    return out


def bulk_sick_leave_balances(
    conn,
    organization_id: int,
    user_ids: list[int],
    *,
    year: Optional[int] = None,
) -> dict[int, dict[str, Any]]:
    """Same shape as ``get_sick_leave_balance``, one settings load + bulk ledger."""
    from backend.payroll_accrual import (
        ACCRUAL_DISCLAIMER,
        _d,
        _q2,
        ensure_payroll_accrual_ledger,
        sick_leave_annual_cap,
    )
    from backend.payroll_tax_settings import fetch_payroll_tax_settings

    uids = sorted({int(u) for u in user_ids or [] if u is not None})
    year = int(year or date.today().year)
    if not uids:
        return {}

    settings = fetch_payroll_tax_settings(conn, int(organization_id))
    cap = _q2(sick_leave_annual_cap(settings))
    carryover = bool(settings.get("sick_leave_carryover_enabled", True))
    base = {
        "annual_cap_hours": cap,
        "accrual_rate_label": "1 hour per 30 hours worked",
        "policy_label": "NYC/NY Paid Sick Leave",
        "disclaimer": ACCRUAL_DISCLAIMER,
        "carryover_enabled": carryover,
    }

    c = conn.cursor(dictionary=True)
    ensure_payroll_accrual_ledger(c)
    ph = ",".join(["%s"] * len(uids))

    balances: dict[int, Any] = {uid: 0 for uid in uids}
    c.execute(
        f"""
        SELECT user_id, balance_after
        FROM payroll_accrual_ledger
        WHERE organization_id=%s
          AND user_id IN ({ph})
          AND accrual_type='SICK_LEAVE'
          AND reversed=0
        ORDER BY id DESC
        """,
        (int(organization_id), *uids),
    )
    seen: set[int] = set()
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        if uid in seen:
            continue
        seen.add(uid)
        balances[uid] = row.get("balance_after")

    ytd: dict[int, dict[str, Any]] = {
        uid: {"accrued": 0, "used": 0} for uid in uids
    }
    c.execute(
        f"""
        SELECT
          user_id,
          COALESCE(SUM(amount_or_hours_accrued), 0) AS accrued,
          COALESCE(SUM(amount_or_hours_used), 0) AS used
        FROM payroll_accrual_ledger
        WHERE organization_id=%s
          AND user_id IN ({ph})
          AND accrual_type='SICK_LEAVE'
          AND reversed=0
          AND YEAR(COALESCE(period_end, created_at))=%s
        GROUP BY user_id
        """,
        (int(organization_id), *uids, int(year)),
    )
    for row in c.fetchall() or []:
        uid = int(row["user_id"])
        ytd[uid] = {"accrued": row.get("accrued"), "used": row.get("used")}

    out: dict[int, dict[str, Any]] = {}
    for uid in uids:
        out[uid] = json_safe(
            {
                **base,
                "balance_hours": _q2(_d(balances.get(uid))),
                "ytd_accrued_hours": _q2(_d(ytd[uid]["accrued"])),
                "ytd_used_hours": _q2(_d(ytd[uid]["used"])),
            }
        )
    return out


def build_payroll_batch_enrich_cache(
    conn,
    organization_id: int,
    user_ids: list[int],
    *,
    include_sick: bool = True,
) -> PayrollBatchEnrichCache:
    uids = sorted({int(u) for u in user_ids or [] if u is not None})
    lookup = build_payroll_list_lookup_cache(conn, int(organization_id), uids)
    meta = bulk_user_display_meta(conn, uids)
    sick: dict[int, dict[str, Any]] = {}
    if include_sick and uids:
        sick = bulk_sick_leave_balances(conn, int(organization_id), uids)
    return PayrollBatchEnrichCache(
        organization_id=int(organization_id),
        lookup=lookup,
        user_meta=meta,
        sick_by_user=sick,
    )
