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
    ensure_management_hd_columns,
    _batch_user_names,
    _money,
)
from backend.ta_helpers import table_exists

MONEY_Q = Decimal("0.01")


def build_hd_employee_performance(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, Any]:
    """List-first HD performance for one ET day. Batch name resolve; no N+1."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    if not table_exists(cursor, "hd_day_bag_production"):
        return {
            "date_et": selected_date_et.isoformat(),
            "employees": [],
            "unmapped": {"washes": [], "folds": []},
        }

    cursor.execute(
        """
        SELECT bag_id, washed_by_user_id, washed_by_name_snapshot, washed_at,
               folded_by_user_id, folded_by_name_snapshot, folded_at,
               total_items, revenue, operations_date_et, workflow_status, status
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND (
            (washed_at IS NOT NULL AND DATE(washed_at) = %s)
            OR (folded_at IS NOT NULL AND DATE(folded_at) = %s)
          )
        ORDER BY bag_id
        """,
        (org, selected_date_et, selected_date_et),
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
    return {
        "date_et": selected_date_et.isoformat(),
        "employees": employees,
        "unmapped": {"washes": unmapped_washes, "folds": unmapped_folds},
        "model": {
            "wash_credit": "washed_by_user_id + washed_at date",
            "fold_credit": "folded_by_user_id + folded_at date",
            "not_used": "revenue entry / explicit Complete date",
        },
    }
