#!/usr/bin/env python3
"""Bounded C1PI050KEU / OI 3587 correction — dry-run by default.

Retires mistaken manager_exclude and marks the exact OI complete via the
audited convert_manager_exclude_to_complete path.

Usage (from repo root):
  PYTHONPATH=. python3 backend/scripts/correct_c1pi050keu_oi3587_exclude.py
  PYTHONPATH=. python3 backend/scripts/correct_c1pi050keu_oi3587_exclude.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Allow running as a plain script from repo root.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ORG = 3
BAG_ID = "C1PI050KEU"
ORDER_INSTANCE_ID = 3587
SELECTED_DATE = date(2026, 9, 13)
REASON_CODE = "BAG_ID_REASSIGNED"
NOTE = (
    "Original bag ID was unassigned; replacement bag ID was issued. "
    "Completion confirmed by manual research."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the correction (default is dry-run only).",
    )
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")

    from backend.db import get_db
    from backend.rinse_order_instances import get_order_instance_by_id
    from backend.rinse_veewash_step1_api import ensure_step1_correction_table
    from backend.rinse_wf_oi_manager_disposition import (
        convert_manager_exclude_to_complete,
        list_oi_manager_dispositions,
    )
    from backend.ta_helpers import table_exists

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    oi = get_order_instance_by_id(cur, ORDER_INSTANCE_ID)
    report: dict = {
        "bag_id": BAG_ID,
        "order_instance_id": ORDER_INSTANCE_ID,
        "selected_date_et": SELECTED_DATE.isoformat(),
        "apply": bool(args.apply),
        "current_oi": None,
        "existing_exclude_corrections": [],
        "existing_dispositions": [],
        "day_bag": None,
        "proposed": None,
        "result": None,
    }
    if isinstance(oi, dict):
        report["current_oi"] = {
            "order_instance_id": oi.get("order_instance_id"),
            "bag_id": oi.get("bag_id"),
            "completed_at": str(oi.get("completed_at") or ""),
            "completion_source": oi.get("completion_source"),
            "completed_by_employee_name": oi.get("completed_by_employee_name"),
        }

    if table_exists(cur, "rinse_step1_corrections"):
        ensure_step1_correction_table(cur)
        cur.execute(
            """
            SELECT id, action, reason_code, reason_text, actor_display_name,
                   created_at, new_values
            FROM rinse_step1_corrections
            WHERE organization_id = %s
              AND bag_id = %s
              AND action IN ('exclude', 'cw_exclude')
            ORDER BY id DESC
            LIMIT 20
            """,
            (ORG, BAG_ID),
        )
        report["existing_exclude_corrections"] = list(cur.fetchall() or [])

    report["existing_dispositions"] = list_oi_manager_dispositions(
        cur, ORG, order_instance_id=ORDER_INSTANCE_ID, active_only=False
    )

    if table_exists(cur, "rinse_shift_monitor_day_bags"):
        cur.execute(
            """
            SELECT bag_id, shift_date_et, effective_status, disposition,
                   post_weight_lbs, manager_edit_version
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
            LIMIT 1
            """,
            (ORG, SELECTED_DATE, BAG_ID),
        )
        report["day_bag"] = cur.fetchone()

    report["proposed"] = convert_manager_exclude_to_complete(
        cur,
        ORG,
        order_instance_id=ORDER_INSTANCE_ID,
        bag_id=BAG_ID,
        reason_code=REASON_CODE,
        manager_note=NOTE,
        actor_display_name="manager_correction_script",
        selected_date_et=SELECTED_DATE,
        dry_run=True,
    )

    if args.apply:
        report["result"] = convert_manager_exclude_to_complete(
            cur,
            ORG,
            order_instance_id=ORDER_INSTANCE_ID,
            bag_id=BAG_ID,
            reason_code=REASON_CODE,
            manager_note=NOTE,
            actor_display_name="manager_correction_script",
            selected_date_et=SELECTED_DATE,
            dry_run=False,
        )
        if report["result"].get("ok"):
            conn.commit()
        else:
            conn.rollback()
    else:
        report["result"] = {
            "ok": True,
            "dry_run": True,
            "message": "No writes. Re-run with --apply to execute.",
        }

    print(json.dumps(report, default=str, indent=2))
    return 0 if (report.get("proposed") or {}).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
