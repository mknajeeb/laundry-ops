#!/usr/bin/env python3
"""Reconcile Management HD performance attribution for one ET day.

Compares build_hd_employee_performance() against canonical hd_day_bag_production
operation fields (washed_by_user_id/washed_at, folded_by_user_id/folded_at).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from typing import Any

from backend.db import get_db
from backend.management_hd_performance import build_hd_employee_performance
from backend.management_rinse_hd import build_rinse_hd_day
from backend.rinse_employee_productivity_sessions import resolve_customer_names_for_bags


def _parse_day(raw: str) -> date:
    return date.fromisoformat(str(raw).strip()[:10])


def _op_day(ts: Any) -> date | None:
    if ts is None:
        return None
    if hasattr(ts, "date"):
        return ts.date()
    return None


def _perf_credit_maps(perf: dict[str, Any]) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int | None]]]:
    wash_by_bag: dict[str, int | None] = {}
    fold_by_bag: dict[str, int | None] = {}
    for emp in perf.get("employees") or []:
        uid = emp.get("user_id")
        for row in emp.get("wash_bags") or []:
            wash_by_bag[str(row.get("bag_id") or "").upper()] = uid
        for row in emp.get("fold_bags") or []:
            fold_by_bag[str(row.get("bag_id") or "").upper()] = uid
    return wash_by_bag, fold_by_bag, {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date-et", default="2026-08-24")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    day = _parse_day(args.date_et)
    org = int(args.org)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        day_payload = build_rinse_hd_day(cursor, org, day, status="all")
        perf = build_hd_employee_performance(cursor, org, day, summary_only=False)
        conn.commit()

        perf_wash: dict[str, int | None] = {}
        perf_fold: dict[str, int | None] = {}
        current_wash_totals: dict[int, int] = defaultdict(int)
        current_fold_totals: dict[int, int] = defaultdict(int)
        name_by_uid = {int(e["user_id"]): e.get("display_name") for e in perf.get("employees") or []}
        for emp in perf.get("employees") or []:
            uid = int(emp["user_id"])
            for row in emp.get("wash_bags") or []:
                bid = str(row.get("bag_id") or "").upper()
                perf_wash[bid] = uid
                current_wash_totals[uid] += 1
            for row in emp.get("fold_bags") or []:
                bid = str(row.get("bag_id") or "").upper()
                perf_fold[bid] = uid
                current_fold_totals[uid] += 1

        orders = day_payload.get("orders") or []
        name_rows = resolve_customer_names_for_bags(
            cursor, org, [{"bag_id": o.get("bag_id")} for o in orders], selected_date_et=day
        )
        customer_by_bag = {str(r["bag_id"]).upper(): r.get("customer_name") for r in name_rows}

        bag_rows: list[dict[str, Any]] = []
        correct_wash_totals: dict[int, int] = defaultdict(int)
        correct_fold_totals: dict[int, int] = defaultdict(int)
        mismatch_ids: list[str] = []

        for order in orders:
            bid = str(order.get("bag_id") or "").upper()
            washed_at = order.get("washed_at")
            folded_at = order.get("folded_at")
            wash_uid = order.get("washed_by_user_id")
            fold_uid = order.get("folded_by_user_id")
            wash_day = _op_day(washed_at)
            fold_day = _op_day(folded_at)
            wash_credit_day = wash_day == day
            fold_credit_day = fold_day == day

            canonical_wash_uid = int(wash_uid) if wash_credit_day and wash_uid not in (None, "") else None
            canonical_fold_uid = int(fold_uid) if fold_credit_day and fold_uid not in (None, "") else None
            if canonical_wash_uid is not None:
                correct_wash_totals[canonical_wash_uid] += 1
            if canonical_fold_uid is not None:
                correct_fold_totals[canonical_fold_uid] += 1

            perf_wash_uid = perf_wash.get(bid)
            perf_fold_uid = perf_fold.get(bid)
            wash_ok = perf_wash_uid == canonical_wash_uid
            fold_ok = perf_fold_uid == canonical_fold_uid
            if not wash_ok or not fold_ok:
                mismatch_ids.append(bid)

            bag_rows.append(
                {
                    "bag_id": bid,
                    "customer": customer_by_bag.get(bid),
                    "canonical_wash_employee_id": canonical_wash_uid,
                    "canonical_washed_at": washed_at,
                    "canonical_fold_employee_id": canonical_fold_uid,
                    "canonical_folded_at": folded_at,
                    "entry_or_complete_at": order.get("management_completed_at") or order.get("completed_at"),
                    "hd_status": order.get("status"),
                    "wash_credit_aug24": wash_credit_day,
                    "fold_credit_aug24": fold_credit_day,
                    "performance_wash_employee_id": perf_wash_uid,
                    "performance_fold_employee_id": perf_fold_uid,
                    "attribution_correct": wash_ok and fold_ok,
                }
            )

        def _fmt_totals(totals: dict[int, int]) -> dict[str, int]:
            out: dict[str, int] = {}
            for uid, count in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
                label = name_by_uid.get(uid) or f"User {uid}"
                out[label] = count
            return out

        report = {
            "date_et": day.isoformat(),
            "org": org,
            "hd_bags_checked": len(bag_rows),
            "current_wash_totals_by_employee": _fmt_totals(current_wash_totals),
            "correct_wash_totals_by_employee": _fmt_totals(correct_wash_totals),
            "current_fold_totals_by_employee": _fmt_totals(current_fold_totals),
            "correct_fold_totals_by_employee": _fmt_totals(correct_fold_totals),
            "mismatch_bag_ids": mismatch_ids,
            "root_cause": None if not mismatch_ids else "performance_credit_differs_from_canonical_operation_fields",
            "canonical_hd_performance_source": "hd_day_bag_production",
            "bags": bag_rows,
        }

        if args.json:
            print(json.dumps(report, default=str, indent=2))
        else:
            print(f"HD BAGS CHECKED: {report['hd_bags_checked']}")
            print(f"CURRENT WASH TOTALS BY EMPLOYEE: {report['current_wash_totals_by_employee']}")
            print(f"CORRECT WASH TOTALS BY EMPLOYEE: {report['correct_wash_totals_by_employee']}")
            print(f"CURRENT FOLD TOTALS BY EMPLOYEE: {report['current_fold_totals_by_employee']}")
            print(f"CORRECT FOLD TOTALS BY EMPLOYEE: {report['correct_fold_totals_by_employee']}")
            print(f"MISMATCH BAG IDS: {mismatch_ids}")
            print(f"ROOT CAUSE: {report['root_cause'] or 'none — attribution matches canonical operation fields'}")
            print(f"CANONICAL HD PERFORMANCE SOURCE: {report['canonical_hd_performance_source']}")
        return 1 if mismatch_ids else 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
