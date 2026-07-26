#!/usr/bin/env python3
"""Historical repair: restore org-3 2026-07-25 HD closed snapshot from WIA.

Jul 25 was closed while Shift Monitor showed HD Total/Review/Completed/Items/
Revenue all zero. Immutable hd_work_item_instances still has five Jul-25
admits (all REVIEW_REQUIRED). Live EDD rebuild also yields zero HD — do not
use it. Restore HD from WIA only; freeze WF day bags and WF headline segments.

Does not change membership formulas in the live path. Jul-25-only restoration.

Usage:
  python -m backend.scripts.repair_jul25_hd_closed_snapshot --dry-run
  python -m backend.scripts.repair_jul25_hd_closed_snapshot --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

import mysql.connector

ORG = 3
DAY = date(2026, 7, 25)
JUL24 = date(2026, 7, 24)
OUT_DIR = Path(__file__).resolve().parents[2] / "data"
ACTOR = "historical_repair_jul25_hd"
REASON = (
    "Restore Jul 25 HD closed snapshot from immutable WIA membership after "
    "premature close froze zero-HD headline"
)


def _load_env() -> None:
    for env_path in (
        Path("/Users/kamisb./laundry_app/.env"),
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _connect(*, autocommit: bool = False):
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        port=int(os.environ.get("MYSQL_PORT") or 3306),
        connection_timeout=40,
        autocommit=autocommit,
    )


def _json_load(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    return json.loads(v)


def _ser(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ser(x) for x in v]
    return v


def _sha_ids(ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(ids)).encode()).hexdigest()[:16]


def _empty_bag_ids() -> dict[str, list[str]]:
    return {
        "new_today": [],
        "carryover": [],
        "completed": [],
        "pending": [],
        "review_required": [],
        "missing_workload_entry_scan": [],
        "disappeared_without_completion": [],
        "completed_awaiting_workload_assignment": [],
    }


def _hd_segment(ids: list[str], *, completed: list[str], review: list[str]) -> dict[str, Any]:
    bags = _empty_bag_ids()
    bags["new_today"] = sorted(ids)
    bags["completed"] = sorted(completed)
    bags["review_required"] = sorted(review)
    bags["disappeared_without_completion"] = sorted(review)
    n = len(ids)
    return {
        "new_today": n,
        "carryover": 0,
        "completed": len(completed),
        "pending": 0,
        "active_workload": n,
        "total_workload": n,
        "total_operational_orders": n,
        "exceptions": {
            "review_required": len(review),
            "disappeared_without_completion": len(review),
            "missing_workload_entry_scan": 0,
            "completed_awaiting_workload_assignment": 0,
            "total": len(review),
        },
        "bag_ids": bags,
    }


def _load_wia(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT *
        FROM hd_work_item_instances
        WHERE organization_id = %s AND admitted_date_et = %s
        ORDER BY bag_id
        """,
        (ORG, DAY),
    )
    return [dict(r) for r in (cursor.fetchall() or [])]


def _load_production(cursor, bag_ids: list[str]) -> dict[str, dict[str, Any]]:
    from backend.rinse_hd_step1_review import load_hd_production_status_map

    if not bag_ids:
        return {}
    return load_hd_production_status_map(cursor, ORG, DAY, bag_ids)


def _wf_fingerprint(cursor, day: date) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT bag_id, effective_status, productivity_credit_eligible,
               productivity_weight_lbs, productivity_employee_name
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND service_type='WF'
        ORDER BY bag_id
        """,
        (ORG, day),
    )
    rows = list(cursor.fetchall() or [])
    ids = [r["bag_id"] for r in rows]
    cursor.execute(
        """
        SELECT status, headline_json
        FROM rinse_shift_monitor_days
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (ORG, day),
    )
    day_row = cursor.fetchone() or {}
    headline = _json_load(day_row.get("headline_json")) or {}
    wf = ((headline.get("segments") or {}).get("wf") or {})
    return {
        "status": day_row.get("status"),
        "bag_count": len(ids),
        "bag_ids_sha": _sha_ids(ids),
        "bag_ids": ids,
        "status_counts": {
            str(r["effective_status"]): sum(
                1 for x in rows if x["effective_status"] == r["effective_status"]
            )
            for r in rows
        },
        "credit_eligible": sum(int(r.get("productivity_credit_eligible") or 0) for r in rows),
        "headline_wf": {
            "new_today": wf.get("new_today"),
            "completed": wf.get("completed"),
            "pending": wf.get("pending"),
            "review_required": (wf.get("exceptions") or {}).get("review_required"),
            "completed_ids_sha": _sha_ids(
                [str(x) for x in ((wf.get("bag_ids") or {}).get("completed") or [])]
            ),
        },
    }


def _jul24_fingerprint(cursor) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT service_type, effective_status, COUNT(*) c
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s
        GROUP BY 1,2 ORDER BY 1,2
        """,
        (ORG, JUL24),
    )
    bags = [dict(r) for r in (cursor.fetchall() or [])]
    cursor.execute(
        """
        SELECT status,
               JSON_EXTRACT(headline_json, '$.segments.wf.completed') wf_c,
               JSON_EXTRACT(headline_json, '$.segments.hd.total_workload') hd_t,
               JSON_EXTRACT(headline_json, '$.hd_dashboard_totals') hd_tot
        FROM rinse_shift_monitor_days
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (ORG, JUL24),
    )
    day = cursor.fetchone() or {}
    return {
        "status": day.get("status"),
        "bag_groups": bags,
        "wf_completed": day.get("wf_c"),
        "hd_total_workload": day.get("hd_t"),
        "hd_dashboard_totals": _json_load(day.get("hd_tot")),
    }


def _day_bag_to_row(bag: dict[str, Any]) -> dict[str, Any]:
    snap = _json_load(bag.get("bag_snapshot_json")) or {}
    if not isinstance(snap, dict):
        snap = {}
    row = dict(snap)
    row.update(
        {
            "bag_id": bag["bag_id"],
            "service_type": bag.get("service_type") or row.get("service_type"),
            "rush_flag": bag.get("rush_status") or row.get("rush_flag"),
            "entry_class": "new_today",
            "entry_source": bag.get("workload_entry_type") or row.get("entry_source"),
            "first_entry_at": bag.get("workload_entry_timestamp") or row.get("first_entry_at"),
            "pre_weight_lbs": bag.get("pre_weight_lbs"),
            "post_weight_lbs": bag.get("post_weight_lbs"),
            "weight_lbs": bag.get("weight_lbs"),
            "canonical_status": bag.get("canonical_completion_status"),
            "completion_at": bag.get("canonical_completion_timestamp"),
            "completed_by": bag.get("canonical_completion_employee"),
            "outcome": bag.get("effective_status"),
            "final_bucket": bag.get("effective_status"),
            "portal_status": bag.get("portal_status_at_sync"),
            "disposition": bag.get("disposition"),
        }
    )
    return row


def _hd_row_from_wia(inst: dict[str, Any], *, completed: bool) -> dict[str, Any]:
    bid = str(inst["bag_id"]).strip().upper()
    rush = str(inst.get("rush_flag") or "").upper()
    admit_ts = inst.get("admitted_scan_time") or inst.get("first_workitems_added_at")
    return {
        "bag_id": bid,
        "order_id": inst.get("order_id") or bid,
        "service_type": "HD",
        "rush_flag": rush,
        "customer_name": inst.get("customer_name_snapshot"),
        "estimated_delivery_date": (
            inst.get("estimated_delivery_date").isoformat()
            if isinstance(inst.get("estimated_delivery_date"), date)
            else (str(inst.get("estimated_delivery_date") or "")[:10] or None)
        ),
        "entry_class": "new_today",
        "inclusion_source": "ADDED_LATER_IN_DAY",
        "entry_source": "hd_workitems_added",
        "first_entry_at": admit_ts,
        "hd_membership_reason": "first_workitems_added",
        "hd_work_item_instance_key": inst.get("work_item_instance_key") or bid,
        "hd_instance_status": inst.get("status"),
        "hd_admitted_date_et": DAY.isoformat(),
        "outcome": "completed" if completed else "review_required",
        "final_bucket": "completed" if completed else "review_required",
        "reason_codes": [] if completed else ["COMPLETION_DETAILS_MISSING"],
    }


def _merge_all_segment(summary: dict[str, Any]) -> None:
    segs = summary.setdefault("segments", {})
    wf = segs.get("wf") or {}
    hd = segs.get("hd") or {}
    wf_bags = wf.get("bag_ids") or {}
    hd_bags = hd.get("bag_ids") or {}

    def union(key: str) -> list[str]:
        return sorted(
            {
                str(x).strip().upper()
                for x in list(wf_bags.get(key) or []) + list(hd_bags.get(key) or [])
                if str(x).strip()
            }
        )

    all_ids = union("new_today")
    completed = union("completed")
    review = union("review_required")
    pending = union("pending")
    bags = _empty_bag_ids()
    bags["new_today"] = all_ids
    bags["completed"] = completed
    bags["review_required"] = review
    bags["pending"] = pending
    bags["disappeared_without_completion"] = review
    segs["all"] = {
        "new_today": len(all_ids),
        "carryover": 0,
        "completed": len(completed),
        "pending": len(pending),
        "active_workload": len(all_ids),
        "total_workload": len(all_ids),
        "exceptions": {
            "review_required": len(review),
            "disappeared_without_completion": len(review),
            "missing_workload_entry_scan": 0,
            "completed_awaiting_workload_assignment": 0,
            "total": len(review),
        },
        "bag_ids": bags,
    }
    summary["exceptions"] = {
        **dict(summary.get("exceptions") or {}),
        "review_required": len(review),
        "total": len(review),
    }
    summary["completed"] = len(completed)
    summary["pending"] = len(pending)


def build_expected(cursor) -> dict[str, Any]:
    from backend.rinse_hd_step1_review import (
        build_hd_dashboard_totals,
        is_authoritative_hd_complete,
    )

    wia = _load_wia(cursor)
    bag_ids = [str(r["bag_id"]).strip().upper() for r in wia]
    prod = _load_production(cursor, bag_ids)
    completed: list[str] = []
    review: list[str] = []
    orders: list[dict[str, Any]] = []
    for inst in wia:
        bid = str(inst["bag_id"]).strip().upper()
        fact = prod.get(bid) or {}
        is_done = is_authoritative_hd_complete(fact)
        if is_done:
            completed.append(bid)
        else:
            review.append(bid)
        orders.append(
            {
                "bag_id": bid,
                "order_id": inst.get("order_id") or bid,
                "customer_name": inst.get("customer_name_snapshot"),
                "rush_flag": inst.get("rush_flag"),
                "estimated_delivery_date": _ser(inst.get("estimated_delivery_date")),
                "first_workitems_added_at": _ser(inst.get("first_workitems_added_at")),
                "first_workitems_added_date_et": _ser(inst.get("admitted_date_et")),
                "admitted_scan_id": inst.get("admitted_scan_id")
                or inst.get("first_workitems_added_event_id"),
                "wia_status": inst.get("status"),
                "production_status": fact.get("status") or fact.get("production_status"),
                "expected_step1_status": "completed" if is_done else "review_required",
                "total_items": fact.get("total_items") or fact.get("item_count"),
                "revenue": _ser(fact.get("revenue") or fact.get("total_revenue")),
            }
        )

    hd_seg = _hd_segment(bag_ids, completed=completed, review=review)
    totals = build_hd_dashboard_totals(cursor, ORG, DAY, hd_segment=hd_seg)
    return {
        "qualifying_orders": orders,
        "expected_membership_ids": sorted(bag_ids),
        "expected_membership_count": len(bag_ids),
        "expected_review_required": len(review),
        "expected_completed": len(completed),
        "expected_total_items": totals.get("total_items"),
        "expected_hd_revenue": totals.get("hd_revenue"),
        "expected_hd_dashboard_totals": totals,
        "hd_day_bag_production_facts": _ser(list(prod.values())),
        "production_row_count": len(prod),
    }


def build_current(cursor) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT status, reopen_count, closed_at, closed_by_display_name,
               review_required_count, headline_json
        FROM rinse_shift_monitor_days
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (ORG, DAY),
    )
    day = cursor.fetchone() or {}
    headline = _json_load(day.get("headline_json")) or {}
    hd = ((headline.get("segments") or {}).get("hd") or {})
    totals = headline.get("hd_dashboard_totals") or {}
    cursor.execute(
        """
        SELECT bag_id, service_type, effective_status
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s
        ORDER BY service_type, bag_id
        """,
        (ORG, DAY),
    )
    bags = [dict(r) for r in (cursor.fetchall() or [])]
    return {
        "status": day.get("status"),
        "reopen_count": day.get("reopen_count"),
        "closed_at": _ser(day.get("closed_at")),
        "closed_by_display_name": day.get("closed_by_display_name"),
        "review_required_count": day.get("review_required_count"),
        "persisted_hd_headline": {
            "new_today": hd.get("new_today"),
            "completed": hd.get("completed"),
            "pending": hd.get("pending"),
            "active_workload": hd.get("active_workload"),
            "total_workload": hd.get("total_workload"),
            "exceptions": hd.get("exceptions"),
            "bag_ids": hd.get("bag_ids"),
        },
        "persisted_hd_dashboard_totals": totals,
        "day_bags": bags,
        "hd_day_bag_count": sum(1 for b in bags if str(b.get("service_type")).upper() == "HD"),
        "wf_day_bag_count": sum(1 for b in bags if str(b.get("service_type")).upper() == "WF"),
    }


def snapshot_matches(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    ph = current.get("persisted_hd_headline") or {}
    pt = current.get("persisted_hd_dashboard_totals") or {}
    bags = ph.get("bag_ids") or {}
    cur_ids = sorted(
        {
            str(x).strip().upper()
            for x in list(bags.get("new_today") or [])
            + list(bags.get("review_required") or [])
            + list(bags.get("completed") or [])
            if str(x).strip()
        }
    )
    return (
        cur_ids == expected["expected_membership_ids"]
        and int(ph.get("total_workload") or 0) == expected["expected_membership_count"]
        and int((ph.get("exceptions") or {}).get("review_required") or 0)
        == expected["expected_review_required"]
        and int(ph.get("completed") or 0) == expected["expected_completed"]
        and int(pt.get("total_hd_orders") or 0) == expected["expected_membership_count"]
        and int(pt.get("review_required") or 0) == expected["expected_review_required"]
        and int(pt.get("completed") or 0) == expected["expected_completed"]
        and int(pt.get("total_items") or 0) == int(expected["expected_total_items"] or 0)
        and float(pt.get("hd_revenue") or 0) == float(expected["expected_hd_revenue"] or 0)
        and current.get("hd_day_bag_count") == expected["expected_membership_count"]
    )


def build_repaired_summary_and_workload(
    cursor, current_headline: dict[str, Any], expected: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    from backend.rinse_hd_step1_review import (
        apply_hd_review_status_to_summary,
        build_hd_dashboard_totals,
        is_authoritative_hd_complete,
    )
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

    wia = _load_wia(cursor)
    bag_ids = [str(r["bag_id"]).strip().upper() for r in wia]
    prod = _load_production(cursor, bag_ids)

    completed = [
        bid
        for bid in bag_ids
        if is_authoritative_hd_complete(prod.get(bid) or {})
    ]
    review = [bid for bid in bag_ids if bid not in set(completed)]

    summary = deepcopy(current_headline or {})
    segs = summary.setdefault("segments", {})
    # Preserve WF segments exactly.
    wf = deepcopy(segs.get("wf") or {})
    segs["wf"] = wf

    segs["hd"] = _hd_segment(bag_ids, completed=completed, review=review)

    rush_ids = [
        str(i["bag_id"]).strip().upper()
        for i in wia
        if "RUSH" in str(i.get("rush_flag") or "").upper()
        and "NON" not in str(i.get("rush_flag") or "").upper()
    ]
    non_rush_ids = [b for b in bag_ids if b not in set(rush_ids)]
    segs["hd_rush"] = _hd_segment(
        rush_ids,
        completed=[b for b in completed if b in set(rush_ids)],
        review=[b for b in review if b in set(rush_ids)],
    )
    segs["hd_non_rush"] = _hd_segment(
        non_rush_ids,
        completed=[b for b in completed if b in set(non_rush_ids)],
        review=[b for b in review if b in set(non_rush_ids)],
    )

    summary = apply_hd_review_status_to_summary(summary, production_by_bag=prod)
    summary["hd_dashboard_totals"] = build_hd_dashboard_totals(
        cursor, ORG, DAY, hd_segment=(summary.get("segments") or {}).get("hd")
    )
    summary["hd_policy"] = {
        **dict(summary.get("hd_policy") or {}),
        "no_carryover": True,
        "membership_source": "hd_work_item_instances.first_workitems_added",
        "historical_repair_jul25": True,
        "edd_admission": False,
    }
    _merge_all_segment(summary)
    summary = attach_specialty_metrics_to_summary(cursor, ORG, DAY, summary)

    # Workload rows: frozen WF day bags + WIA HD rows.
    cursor.execute(
        """
        SELECT *
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND service_type='WF'
        ORDER BY bag_id
        """,
        (ORG, DAY),
    )
    wf_bags = [dict(r) for r in (cursor.fetchall() or [])]
    rows = [_day_bag_to_row(b) for b in wf_bags]
    for inst in wia:
        bid = str(inst["bag_id"]).strip().upper()
        rows.append(
            _hd_row_from_wia(
                inst, completed=is_authoritative_hd_complete(prod.get(bid) or {})
            )
        )

    reasons = {
        str(r["bag_id"]): list(r.get("reason_codes") or [])
        for r in rows
        if r.get("reason_codes")
    }
    wl = {
        "from_snapshot": True,
        "rows": rows,
        "review_required": review,
        "review_reasons_by_bag": reasons,
        "counts": {"total": len(rows)},
        "selected_date_et": DAY.isoformat(),
        "organization_id": ORG,
        "membership": {
            "selected_date_et": DAY.isoformat(),
            "hd_wia_membership_ids": bag_ids,
            "ok": True,
        },
    }
    # Sanity vs expected
    assert sorted(bag_ids) == expected["expected_membership_ids"]
    return summary, wl


def apply_repair(cursor, report: dict[str, Any]) -> dict[str, Any]:
    from backend.rinse_veewash_shift_day import (
        STATUS_REOPENED,
        close_shift_day,
        get_day_record,
        load_day_bags,
        persist_day_snapshot,
        reopen_shift_day,
        validate_close,
    )

    before_wf = _wf_fingerprint(cursor, DAY)
    before_j24 = _jul24_fingerprint(cursor)
    current = build_current(cursor)
    expected = build_expected(cursor)

    reopen_result = None
    if current.get("status") == "CLOSED":
        reopen_result = reopen_shift_day(
            cursor,
            ORG,
            DAY,
            actor_user_id=None,
            actor_display_name=ACTOR,
            reason=REASON,
        )
        if not reopen_result.get("ok"):
            raise RuntimeError(f"reopen failed: {reopen_result}")

    day = get_day_record(cursor, ORG, DAY) or {}
    headline = day.get("headline") or _json_load(day.get("headline_json")) or {}
    summary, wl = build_repaired_summary_and_workload(cursor, headline, expected)
    persist_day_snapshot(
        cursor,
        ORG,
        DAY,
        workload=wl,
        summary=summary,
        status=STATUS_REOPENED,
        force=True,
    )

    after = build_current(cursor)
    after_expected = build_expected(cursor)
    after_wf = _wf_fingerprint(cursor, DAY)
    after_j24 = _jul24_fingerprint(cursor)

    bags = load_day_bags(cursor, ORG, DAY)
    gate = validate_close(
        summary,
        cursor=cursor,
        organization_id=ORG,
        shift_date_et=DAY,
        day_bags=bags,
    )
    close_result = None
    if gate.get("ok"):
        close_result = close_shift_day(
            cursor,
            ORG,
            DAY,
            actor_user_id=None,
            actor_display_name=ACTOR,
            reason="Freeze Jul 25 after HD WIA snapshot restoration",
        )
    else:
        close_result = {
            "ok": False,
            "skipped": True,
            "error": gate.get("error") or "shift_not_ready_to_close",
            "blocking_counts": gate.get("blocking_counts") or gate,
            "note": (
                "Strict close correctly blocked: HD reviews remain open. "
                "Day left REOPENED with restored HD membership."
            ),
        }

    final = build_current(cursor)
    final_wf = _wf_fingerprint(cursor, DAY)
    return {
        "reopen_result": _ser(reopen_result),
        "before": _ser(current),
        "expected": _ser(expected),
        "after_rebuild": _ser(after),
        "snapshot_matches_after_rebuild": snapshot_matches(after, after_expected),
        "wf_before": before_wf,
        "wf_after_rebuild": after_wf,
        "wf_unchanged": before_wf["bag_ids_sha"] == after_wf["bag_ids_sha"]
        and before_wf["headline_wf"] == after_wf["headline_wf"]
        and before_wf["credit_eligible"] == after_wf["credit_eligible"],
        "jul24_before": before_j24,
        "jul24_after": after_j24,
        "jul24_unchanged": before_j24 == after_j24,
        "close_gate": _ser(gate),
        "close_result": _ser(close_result),
        "final": _ser(final),
        "wf_final": final_wf,
        "fingerprints": {
            "before_status": current.get("status"),
            "after_rebuild_status": after.get("status"),
            "final_status": final.get("status"),
            "hd_before": current.get("persisted_hd_dashboard_totals"),
            "hd_after": after.get("persisted_hd_dashboard_totals"),
            "hd_final": final.get("persisted_hd_dashboard_totals"),
            "wf_ids_sha_before": before_wf["bag_ids_sha"],
            "wf_ids_sha_after": after_wf["bag_ids_sha"],
            "wf_ids_sha_final": final_wf["bag_ids_sha"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True

    _load_env()
    conn = _connect(autocommit=False)
    cur = conn.cursor(dictionary=True)
    try:
        current = build_current(cur)
        expected = build_expected(cur)
        wf = _wf_fingerprint(cur, DAY)
        j24 = _jul24_fingerprint(cur)
        matches = snapshot_matches(current, expected)
        report: dict[str, Any] = {
            "organization_id": ORG,
            "operations_date_et": DAY.isoformat(),
            "mode": "apply" if args.apply else "dry-run",
            "current_closed_shift_status": current.get("status"),
            "current_persisted_hd_headline": current.get("persisted_hd_headline"),
            "current_hd_dashboard_totals": current.get("persisted_hd_dashboard_totals"),
            "current_hd_work_item_instances": expected.get("qualifying_orders"),
            "current_hd_day_bag_production_facts": expected.get("hd_day_bag_production_facts"),
            "every_qualifying_jul25_hd_order": expected.get("qualifying_orders"),
            "expected_hd_membership": expected.get("expected_membership_ids"),
            "expected_review_required_count": expected.get("expected_review_required"),
            "expected_completed_count": expected.get("expected_completed"),
            "expected_total_items": expected.get("expected_total_items"),
            "expected_hd_revenue": expected.get("expected_hd_revenue"),
            "closed_snapshot_matches_facts": matches,
            "mismatch_reason": (
                None
                if matches
                else "Closed headline/day-bags show zero HD while WIA has five REVIEW_REQUIRED admits"
            ),
            "conflicts": [],
            "unrecoverable_rows": [],
            "wf_fingerprint": {
                "bag_count": wf["bag_count"],
                "bag_ids_sha": wf["bag_ids_sha"],
                "credit_eligible": wf["credit_eligible"],
                "headline_wf": wf["headline_wf"],
            },
            "jul24_fingerprint": j24,
            "notes": [
                "Membership authority: hd_work_item_instances.admitted_date_et == 2026-07-25",
                "No EDD admission; Victoria Panettiere admitted 2026-07-23 (excluded by no-carryover)",
                "Katie Giovale EDD 2026-07-27 but WIA admit 2026-07-25 (included)",
                "No hd_day_bag_production COMPLETE rows for Jul 25 → items/revenue remain 0",
                "Live EDD rebuild also yields 0 HD — not used for this repair",
            ],
        }

        out_dry = OUT_DIR / "repair_jul25_hd_closed_snapshot_dry_run_org3.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        if args.apply:
            if matches:
                report["applied"] = False
                report["apply_skipped"] = "already_matches"
            else:
                apply_out = apply_repair(cur, report)
                report["applied"] = True
                report["apply_result"] = apply_out
                conn.commit()
            out_apply = OUT_DIR / "repair_jul25_hd_closed_snapshot_apply_org3.json"
            out_apply.write_text(json.dumps(_ser(report), indent=2) + "\n")
            print(json.dumps(_ser(report), indent=2)[:4000])
            print("WROTE", out_apply)
        else:
            out_dry.write_text(json.dumps(_ser(report), indent=2) + "\n")
            print(json.dumps(_ser(report), indent=2)[:4000])
            print("WROTE", out_dry)
            conn.rollback()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
