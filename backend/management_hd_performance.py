"""Management Rinse HD employee performance — wash/fold credit by operation timestamps.

Wash credit → washed_by_user_id on washed_at business date.
Fold credit → folded_by_user_id on folded_at business date.
Never uses revenue-entry / Complete date for performance attribution.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.management_rinse_hd import (
    HD_WORKFLOW_ACTIVATION_DATE,
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    ensure_management_hd_columns,
    _batch_user_names,
    _money,
)
from backend.ta_helpers import table_exists

MONEY_Q = Decimal("0.01")


def _hd_performance_summary_totals(employees: list[dict[str, Any]]) -> dict[str, int]:
    wash_employees = sum(1 for e in employees if int(e.get("wash_count") or 0) > 0)
    fold_employees = sum(1 for e in employees if int(e.get("fold_count") or 0) > 0)
    return {
        "bags_washed": sum(int(e.get("wash_count") or 0) for e in employees),
        "bags_folded": sum(int(e.get("fold_count") or 0) for e in employees),
        "wash_employees": wash_employees,
        "fold_employees": fold_employees,
    }


def _first_last_ts(values: list[Any]) -> tuple[Any | None, Any | None]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    ordered = sorted(clean, key=lambda v: v)
    return ordered[0], ordered[-1]


def _strip_employee_bag_lists(employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for emp in employees:
        wash_bags = emp.get("wash_bags") or []
        fold_bags = emp.get("fold_bags") or []
        first_wash, last_wash = _first_last_ts([b.get("washed_at") for b in wash_bags])
        first_fold, last_fold = _first_last_ts([b.get("folded_at") for b in fold_bags])
        row = {k: v for k, v in emp.items() if k not in ("wash_bags", "fold_bags")}
        row["first_wash_at"] = first_wash
        row["last_wash_at"] = last_wash
        row["first_fold_at"] = first_fold
        row["last_fold_at"] = last_fold
        out.append(row)
    return out


def build_hd_employee_performance(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    summary_only: bool = False,
) -> dict[str, Any]:
    """List-first HD performance for one ET day. Batch name resolve; no N+1."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    if selected_date_et < HD_WORKFLOW_ACTIVATION_DATE:
        return {
            "date_et": selected_date_et.isoformat(),
            "employees": [],
            "summary": {
                "bags_washed": 0,
                "bags_folded": 0,
                "wash_employees": 0,
                "fold_employees": 0,
            },
            "unmapped": {"washes": [], "folds": []},
            "model": {
                "wash_credit": "washed_by_user_id + washed_at date",
                "fold_credit": "folded_by_user_id + folded_at date",
                "not_used": "revenue entry / explicit Complete date",
                "activation_date_et": HD_WORKFLOW_ACTIVATION_DATE.isoformat(),
                "source": "hd_day_bag_production",
            },
        }
    if not table_exists(cursor, "hd_day_bag_production"):
        return {
            "date_et": selected_date_et.isoformat(),
            "employees": [],
            "summary": {
                "bags_washed": 0,
                "bags_folded": 0,
                "wash_employees": 0,
                "fold_employees": 0,
            },
            "unmapped": {"washes": [], "folds": []},
        }

    cursor.execute(
        """
        SELECT bag_id, washed_by_user_id, washed_by_name_snapshot, washed_at,
               folded_by_user_id, folded_by_name_snapshot, folded_at,
               total_items, revenue, operations_date_et, workflow_status, status
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND COALESCE(workflow_status, '') NOT IN (%s, %s)
          AND operations_date_et >= %s
          AND (
            (washed_at IS NOT NULL AND DATE(washed_at) = %s)
            OR (folded_at IS NOT NULL AND DATE(folded_at) = %s)
          )
        ORDER BY bag_id
        """,
        (
            org,
            WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
            "excluded",
            HD_WORKFLOW_ACTIVATION_DATE,
            selected_date_et,
            selected_date_et,
        ),
    )
    rows = [dict(r) for r in (cursor.fetchall() or [])]

    uid_set: set[int] = set()
    for r in rows:
        for key in ("washed_by_user_id", "folded_by_user_id"):
            try:
                if r.get(key) not in (None, ""):
                    uid_set.add(int(r[key]))
            except (TypeError, ValueError):
                pass
    names = _batch_user_names(cursor, list(uid_set))

    by_user: dict[int, dict[str, Any]] = {}
    unmapped_washes: list[dict[str, Any]] = []
    unmapped_folds: list[dict[str, Any]] = []

    def _bucket(uid: int | None) -> dict[str, Any] | None:
        if uid is None:
            return None
        if uid not in by_user:
            by_user[uid] = {
                "user_id": uid,
                "display_name": names.get(uid) or f"User {uid}",
                "wash_count": 0,
                "fold_count": 0,
                "wash_bags": [],
                "fold_bags": [],
                "items_on_fold": 0,
                "revenue_on_fold": 0.0,
            }
        return by_user[uid]

    for r in rows:
        bag = str(r.get("bag_id") or "").strip().upper()
        washed_at = r.get("washed_at")
        folded_at = r.get("folded_at")
        wash_uid = None
        fold_uid = None
        try:
            if r.get("washed_by_user_id") not in (None, ""):
                wash_uid = int(r["washed_by_user_id"])
        except (TypeError, ValueError):
            wash_uid = None
        try:
            if r.get("folded_by_user_id") not in (None, ""):
                fold_uid = int(r["folded_by_user_id"])
        except (TypeError, ValueError):
            fold_uid = None

        if washed_at is not None:
            wash_day = washed_at.date() if hasattr(washed_at, "date") else None
            if wash_day == selected_date_et:
                entry = {
                    "bag_id": bag,
                    "washed_at": washed_at,
                    "washed_by_name": names.get(wash_uid) if wash_uid else r.get("washed_by_name_snapshot"),
                }
                b = _bucket(wash_uid)
                if b:
                    b["wash_count"] += 1
                    b["wash_bags"].append(entry)
                else:
                    unmapped_washes.append(entry)

        if folded_at is not None:
            fold_day = folded_at.date() if hasattr(folded_at, "date") else None
            if fold_day == selected_date_et:
                items = int(r["total_items"]) if r.get("total_items") is not None else 0
                rev = _money(r.get("revenue")) or 0.0
                entry = {
                    "bag_id": bag,
                    "folded_at": folded_at,
                    "folded_by_name": names.get(fold_uid) if fold_uid else r.get("folded_by_name_snapshot"),
                    "items": r.get("total_items"),
                    "revenue": rev if r.get("revenue") is not None else None,
                }
                b = _bucket(fold_uid)
                if b:
                    b["fold_count"] += 1
                    b["fold_bags"].append(entry)
                    b["items_on_fold"] += items
                    b["revenue_on_fold"] = float(
                        (Decimal(str(b["revenue_on_fold"])) + Decimal(str(rev))).quantize(
                            MONEY_Q, rounding=ROUND_HALF_UP
                        )
                    )
                else:
                    unmapped_folds.append(entry)

    employees = sorted(
        by_user.values(),
        key=lambda e: (-(e["wash_count"] + e["fold_count"]), e["display_name"] or ""),
    )
    summary = _hd_performance_summary_totals(employees)
    if summary_only:
        employees = _strip_employee_bag_lists(employees)
    payload = {
        "date_et": selected_date_et.isoformat(),
        "employees": employees,
        "summary": summary,
        "unmapped": {"washes": unmapped_washes, "folds": unmapped_folds},
        "model": {
            "wash_credit": "washed_by_user_id + washed_at date",
            "fold_credit": "folded_by_user_id + folded_at date",
            "not_used": "revenue entry / explicit Complete date",
            "source": "hd_day_bag_production",
        },
    }
    return payload


def build_hd_employee_performance_detail(
    cursor,
    organization_id: int,
    selected_date_et: date,
    user_id: int,
) -> dict[str, Any]:
    """Lazy employee drill-down with customer names; no extra per-bag queries."""
    perf = build_hd_employee_performance(cursor, organization_id, selected_date_et, summary_only=False)
    target = None
    for emp in perf.get("employees") or []:
        if int(emp.get("user_id") or 0) == int(user_id):
            target = dict(emp)
            break
    if not target:
        return {"ok": False, "status": 404, "error": "employee_not_found"}

    from backend.rinse_employee_productivity_sessions import resolve_customer_names_for_bags

    wash_bags = list(target.get("wash_bags") or [])
    fold_bags = list(target.get("fold_bags") or [])
    if wash_bags:
        wash_bags = resolve_customer_names_for_bags(
            cursor, int(organization_id), wash_bags, selected_date_et=selected_date_et
        )
    if fold_bags:
        fold_bags = resolve_customer_names_for_bags(
            cursor, int(organization_id), fold_bags, selected_date_et=selected_date_et
        )
    target["wash_bags"] = wash_bags
    target["fold_bags"] = fold_bags
    return {
        "ok": True,
        "date_et": perf.get("date_et"),
        "employee": target,
    }
