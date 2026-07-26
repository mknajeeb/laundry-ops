#!/usr/bin/env python3
"""Backfill durable PRE / completion locks from rinse_step1_bag_edits (Jul 26).

Saves before 591b7b1e toasted ok but rebuild wiped day_bag because corrections
lacked corrected_pre_weight_lbs / correct_completion rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _parse_json(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", type=int, default=3)
    ap.add_argument("--date", default="2026-07-26")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    day = date.fromisoformat(args.date)

    from backend.db import get_db
    from backend.rinse_veewash_step1_api import _record_correction

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, bag_id, before_json, after_json, reason, actor_user_id, actor_display_name, created_at
        FROM rinse_step1_bag_edits
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND COALESCE(is_undo, 0) = 0
        ORDER BY id ASC
        """,
        (int(args.org), day),
    )
    edits = cur.fetchall() or []

    # Latest after-state per bag wins.
    latest: dict[str, dict] = {}
    for row in edits:
        bid = str(row["bag_id"] if isinstance(row, dict) else row[1]).strip().upper()
        before = _parse_json(row["before_json"] if isinstance(row, dict) else row[2])
        after = _parse_json(row["after_json"] if isinstance(row, dict) else row[3])
        latest[bid] = {
            "edit_id": row["id"] if isinstance(row, dict) else row[0],
            "before": before,
            "after": after,
            "reason": row["reason"] if isinstance(row, dict) else row[4],
            "actor_user_id": row["actor_user_id"] if isinstance(row, dict) else row[5],
            "actor_display_name": row["actor_display_name"] if isinstance(row, dict) else row[6],
            "created_at": row["created_at"] if isinstance(row, dict) else row[7],
        }

    # Compare desired after-state to current day_bag (rebuild may already have wiped it).
    day_by_bag: dict[str, dict] = {}
    if latest:
        bids = sorted(latest.keys())
        ph = ",".join(["%s"] * len(bids))
        cur.execute(
            f"""
            SELECT bag_id, pre_weight_lbs, post_weight_lbs,
                   canonical_completion_employee, productivity_employee_name
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND shift_date_et = %s AND bag_id IN ({ph})
            """,
            (int(args.org), day, *bids),
        )
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                day_by_bag[str(row["bag_id"]).upper()] = row
            else:
                day_by_bag[str(row[0]).upper()] = {
                    "bag_id": row[0],
                    "pre_weight_lbs": row[1],
                    "post_weight_lbs": row[2],
                    "canonical_completion_employee": row[3],
                    "productivity_employee_name": row[4],
                }

    plan = []
    for bid, info in sorted(latest.items()):
        before = info["before"]
        after = info["after"]
        day_row = day_by_bag.get(bid) or {}
        be = str(before.get("completed_by") or "").strip()
        ae = str(after.get("completed_by") or "").strip()
        de = str(
            day_row.get("canonical_completion_employee")
            or day_row.get("productivity_employee_name")
            or ""
        ).strip()
        bp = before.get("pre_weight_lbs")
        ap = after.get("pre_weight_lbs")
        dp = day_row.get("pre_weight_lbs")
        bpost = before.get("post_weight_lbs")
        apost = after.get("post_weight_lbs")
        dpost = day_row.get("post_weight_lbs")
        emp_needs_lock = bool(ae) and (ae.lower() != be.lower() or ae.lower() != de.lower())
        pre_needs_lock = ap is not None and (
            ap != bp or dp is None or float(dp) != float(ap)
        )
        post_needs_lock = apost is not None and (
            apost != bpost or dpost is None or float(dpost) != float(apost)
        )
        plan.append(
            {
                "bag_id": bid,
                "edit_id": info["edit_id"],
                "emp_changed": emp_needs_lock,
                "pre_changed": pre_needs_lock,
                "post_changed": post_needs_lock,
                "completed_by": ae or None,
                "completion_at": after.get("completion_at"),
                "pre_weight_lbs": ap,
                "post_weight_lbs": apost,
                "reason": info["reason"],
                "actor_user_id": info["actor_user_id"],
                "actor_display_name": info["actor_display_name"],
            }
        )

    print(f"bags_with_edits={len(plan)} apply={args.apply}")
    for p in plan:
        if p["emp_changed"] or p["pre_changed"] or p["post_changed"]:
            print(
                f"{p['bag_id']}: emp_changed={p['emp_changed']} -> {p['completed_by']!r} "
                f"pre_changed={p['pre_changed']} -> {p['pre_weight_lbs']!r} "
                f"post_changed={p['post_changed']} -> {p['post_weight_lbs']!r}"
            )

    if not args.apply:
        print("dry-run only; pass --apply to write locks + day_bag")
        conn.close()
        return 0

    for p in plan:
        bid = p["bag_id"]
        if p["emp_changed"] and p["completed_by"]:
            _record_correction(
                cur,
                int(args.org),
                bag_id=bid,
                action="correct_completion",
                reason_text=str(p["reason"] or "backfill_manager_completion"),
                reason_code="CORRECT_COMPLETION_DETAILS",
                previous_values={"source": "bag_edit_backfill", "edit_id": p["edit_id"]},
                new_values={
                    "completed_by": p["completed_by"],
                    "completion_at": p["completion_at"],
                },
                actor_user_id=p["actor_user_id"],
                actor_display_name=p["actor_display_name"],
            )
            cur.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET canonical_completion_employee = %s,
                    productivity_employee_name = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (p["completed_by"], p["completed_by"], int(args.org), day, bid),
            )
        if p["pre_changed"] or p["post_changed"]:
            new_values = {
                "pre_weight_lbs": p["pre_weight_lbs"],
                "post_weight_lbs": p["post_weight_lbs"],
            }
            if p["pre_weight_lbs"] is not None:
                new_values["corrected_pre_weight_lbs"] = p["pre_weight_lbs"]
            if p["post_weight_lbs"] is not None:
                new_values["corrected_post_weight_lbs"] = p["post_weight_lbs"]
            _record_correction(
                cur,
                int(args.org),
                bag_id=bid,
                action="correct_weight",
                reason_text=str(p["reason"] or "backfill_manager_weight"),
                reason_code="EDIT_BAG_WEIGHT",
                previous_values={"source": "bag_edit_backfill", "edit_id": p["edit_id"]},
                new_values=new_values,
                actor_user_id=p["actor_user_id"],
                actor_display_name=p["actor_display_name"],
            )
            cur.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET pre_weight_lbs = COALESCE(%s, pre_weight_lbs),
                    post_weight_lbs = COALESCE(%s, post_weight_lbs),
                    weight_lbs = COALESCE(%s, weight_lbs),
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (
                    p["pre_weight_lbs"],
                    p["post_weight_lbs"],
                    p["post_weight_lbs"] if p["post_weight_lbs"] is not None else p["pre_weight_lbs"],
                    int(args.org),
                    day,
                    bid,
                ),
            )

    conn.commit()
    print("applied")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
