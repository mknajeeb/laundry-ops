#!/usr/bin/env python3
"""Guarded restoration of Jul 28 org3 manager decisions overwritten by refresh.

Dry-run by default. Does NOT invent outcomes from scans — only restores the
latest rinse_step1_bag_edits after-state for the known overwritten IDs.

Usage:
  python -m backend.scripts.repair_manager_overwrite_jul28_org3
  python -m backend.scripts.repair_manager_overwrite_jul28_org3 --apply

Do not run --apply until the manager-lock UPSERT package is deployed and
pre-repair snapshots are recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

ORG = 3
DAY = date(2026, 7, 28)

# Manager-overwritten IDs only. CUR0CB8E78 is an unedited control — excluded.
RESTORE_BAG_IDS = (
    "37T41HXX6C",
    "DUBMZIT70D",
    "0T8Y79TD3T",
    "DDMR9M047N",
)


def _load_latest_manager_after_state(cursor, bag_id: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id, created_at, outcome_action, reason, after_json, before_json
        FROM rinse_step1_bag_edits
        WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
          AND outcome_action='mark_completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (ORG, DAY, bag_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    after = row.get("after_json")
    if isinstance(after, (bytes, bytearray)):
        after = after.decode()
    if isinstance(after, str):
        after = json.loads(after)
    return {
        "edit_id": row["id"],
        "created_at": str(row["created_at"]),
        "outcome_action": row["outcome_action"],
        "reason": row["reason"],
        "after": after or {},
    }


def _snapshot_bag(cursor, bag_id: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT bag_id, effective_status, manager_edit_version,
               canonical_completion_status, canonical_completion_employee,
               canonical_completion_timestamp, review_reason_codes_json,
               disposition, updated_at,
               JSON_EXTRACT(bag_snapshot_json, '$.outcome') AS snap_outcome
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
        """,
        (ORG, DAY, bag_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}


def plan_restorations(cursor) -> list[dict[str, Any]]:
    plans = []
    for bag_id in RESTORE_BAG_IDS:
        current = _snapshot_bag(cursor, bag_id)
        edit = _load_latest_manager_after_state(cursor, bag_id)
        if not edit:
            plans.append(
                {
                    "bag_id": bag_id,
                    "ok": False,
                    "error": "no_mark_completed_edit",
                    "current": current,
                }
            )
            continue
        after = edit["after"]
        target_status = str(
            after.get("dashboard_status") or after.get("outcome") or ""
        ).strip().lower()
        if target_status != "completed":
            plans.append(
                {
                    "bag_id": bag_id,
                    "ok": False,
                    "error": "latest_edit_after_not_completed",
                    "edit": edit,
                    "current": current,
                }
            )
            continue
        plans.append(
            {
                "bag_id": bag_id,
                "ok": True,
                "current": current,
                "edit": {
                    "edit_id": edit["edit_id"],
                    "created_at": edit["created_at"],
                    "reason": edit["reason"],
                    "after_status": target_status,
                    "after_version": after.get("manager_edit_version"),
                    "completed_by": after.get("completed_by"),
                    "completion_at": after.get("completion_at"),
                },
                "restore_to": {
                    "effective_status": "completed",
                    "canonical_completion_status": "completed",
                    "canonical_completion_employee": after.get("completed_by"),
                    "canonical_completion_timestamp": after.get("completion_at"),
                    "review_reason_codes_json": [],
                    "disposition": "COMPLETED",
                    "bag_snapshot_patch": {
                        "outcome": "completed",
                        "final_bucket": "completed",
                        "effective_status": "completed",
                        "reason_codes": [],
                        "completed_by": after.get("completed_by"),
                        "completion_at": after.get("completion_at"),
                    },
                    # Do not bump manager_edit_version — restore prior decision only.
                    "keep_manager_edit_version": True,
                },
                "needs_write": str((current or {}).get("effective_status") or "").lower()
                != "completed",
            }
        )
    return plans


def apply_restoration(cursor, plan: dict[str, Any]) -> None:
    if not plan.get("ok") or not plan.get("needs_write"):
        return
    bag_id = plan["bag_id"]
    restore = plan["restore_to"]
    cursor.execute(
        """
        SELECT bag_snapshot_json FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
        """,
        (ORG, DAY, bag_id),
    )
    row = cursor.fetchone() or {}
    snap = row.get("bag_snapshot_json")
    if isinstance(snap, (bytes, bytearray)):
        snap = snap.decode()
    if isinstance(snap, str):
        snap = json.loads(snap)
    if not isinstance(snap, dict):
        snap = {}
    snap.update(restore["bag_snapshot_patch"])
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_day_bags
        SET effective_status=%s,
            canonical_completion_status=%s,
            canonical_completion_employee=COALESCE(%s, canonical_completion_employee),
            canonical_completion_timestamp=COALESCE(%s, canonical_completion_timestamp),
            review_reason_codes_json=%s,
            disposition=%s,
            bag_snapshot_json=%s,
            updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
          AND manager_edit_version > 0
        """,
        (
            restore["effective_status"],
            restore["canonical_completion_status"],
            restore["canonical_completion_employee"],
            restore["canonical_completion_timestamp"],
            json.dumps(restore["review_reason_codes_json"]),
            restore["disposition"],
            json.dumps(snap),
            ORG,
            DAY,
            bag_id,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write restorations (default is dry-run only)",
    )
    args = parser.parse_args(argv)

    from backend.db import get_db
    from backend.rinse_veewash_shift_day import (
        _load_day_bag_status_projection,
        _sync_day_header_from_persisted_bags,
        get_day_record,
    )

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        plans = plan_restorations(cur)
        report = {
            "organization_id": ORG,
            "shift_date_et": DAY.isoformat(),
            "mode": "apply" if args.apply else "dry_run",
            "control_excluded": "CUR0CB8E78",
            "plans": plans,
        }
        if args.apply:
            for plan in plans:
                apply_restoration(cur, plan)
            day = get_day_record(cur, ORG, DAY) or {}
            _sync_day_header_from_persisted_bags(
                cur,
                ORG,
                DAY,
                summary=day.get("headline") or {},
                workload={"counts": {}, "review_reasons_by_bag": {}},
                next_status=str(day.get("status") or "OPEN"),
                opened_at=day.get("opened_at"),
                now=__import__("datetime").datetime.utcnow(),
            )
            status_by_bag = _load_day_bag_status_projection(cur, ORG, DAY)
            report["after_status_by_bag"] = {
                bid: status_by_bag.get(bid) for bid in RESTORE_BAG_IDS
            }
            conn.commit()
        else:
            conn.rollback()
        print(json.dumps(report, indent=2, default=str))
        bad = [p for p in plans if not p.get("ok")]
        return 1 if bad else 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
