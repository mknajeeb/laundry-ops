#!/usr/bin/env python3
"""Reconcile Management Rinse HD stage population for a selected ET day.

Prints per-bag classification plus summary/chip parity counts.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from backend.db import get_db
from backend.management_rinse_hd import (
    STATUS_AWAITING_FOLD,
    STATUS_MISSING_FROM_PORTAL,
    STATUS_WASHED,
    build_rinse_hd_day,
    build_rinse_hd_summary,
)


def _parse_day(raw: str) -> date:
    return date.fromisoformat(str(raw).strip()[:10])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date-et", default="2026-08-24")
    args = parser.parse_args()
    day = _parse_day(args.date_et)
    org = int(args.org)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        day_payload = build_rinse_hd_day(cursor, org, day, status="all")
        summary_payload = build_rinse_hd_summary(
            cursor, org, start_et=day, end_et=day, snapshot_date_et=day
        )
        conn.commit()

        counts = day_payload.get("counts") or {}
        summary = day_payload.get("summary") or {}
        orders = day_payload.get("orders") or []

        awaiting_fold_rows = []
        true_fold = 0
        missing = 0
        other = 0
        for row in orders:
            st = str(row.get("status") or "")
            wf = str(row.get("workflow_status") or "")
            if st in (STATUS_AWAITING_FOLD, STATUS_WASHED) or wf == STATUS_WASHED:
                entry = {
                    "bag_id": row.get("bag_id"),
                    "customer_name": row.get("customer_name"),
                    "wash_timestamp": row.get("washed_at"),
                    "fold_timestamp": row.get("folded_at"),
                    "latest_source_presence": row.get("on_latest_portal"),
                    "last_seen_timestamp": row.get("last_portal_seen_at"),
                    "disappeared": bool(row.get("disappeared_from_portal")),
                    "on_latest_scrape": bool(row.get("on_latest_portal")),
                    "display_status": st,
                    "workflow_status": wf,
                }
                awaiting_fold_rows.append(entry)
                if st in (STATUS_AWAITING_FOLD, STATUS_WASHED):
                    true_fold += 1
                elif st == STATUS_MISSING_FROM_PORTAL and wf == STATUS_WASHED:
                    missing += 1
                else:
                    other += 1

        population = []
        for row in orders:
            population.append(
                {
                    "bag_id": row.get("bag_id"),
                    "customer_name": row.get("customer_name"),
                    "latest_source_presence": row.get("on_latest_portal"),
                    "last_portal_presence_timestamp": row.get("last_portal_seen_at"),
                    "canonical_workflow_stage": row.get("workflow_status"),
                    "wash_evidence": row.get("washed_at"),
                    "fold_evidence": row.get("folded_at"),
                    "entry_evidence": {
                        "items": row.get("items"),
                        "revenue": row.get("revenue"),
                    },
                    "completion_evidence": row.get("completion_at"),
                    "delivery_date": row.get("delivery_date_et"),
                    "summary_classification": summary,
                    "queue_chip_classification": row.get("status"),
                    "disappeared_from_source": bool(row.get("disappeared_from_portal")),
                    "disappeared_before_terminal_evidence": bool(
                        row.get("disappeared_from_portal")
                        and not row.get("completion_at")
                    ),
                }
            )

        parity = {
            key: {
                "summary": int(summary.get(key) or 0),
                "counts": int(counts.get(key) or counts.get(key.replace("awaiting_fold", "awaiting_fold")) or 0),
                "match": int(summary.get(key) or 0)
                == int(
                    counts.get(key)
                    or (counts.get(STATUS_AWAITING_FOLD) if key == "awaiting_fold" else 0)
                    or 0
                ),
            }
            for key in (
                "pending_wash",
                "awaiting_fold",
                "awaiting_entry",
                "complete",
                "missing_from_portal",
                "excluded",
            )
        }

        out = {
            "date_et": day.isoformat(),
            "totals": {
                "total_hd_orders": len(orders),
                "pending_wash": int(counts.get("pending_wash") or 0),
                "awaiting_fold": int(counts.get("awaiting_fold") or 0),
                "awaiting_entry": int(counts.get("awaiting_entry") or 0),
                "complete": int(counts.get("complete") or 0),
                "missing_from_portal": int(counts.get("missing_from_portal") or 0),
                "excluded": int(counts.get("excluded") or 0),
            },
            "summary_endpoint": {
                "pending_wash": summary_payload.get("pending_wash"),
                "awaiting_fold": summary_payload.get("awaiting_fold"),
                "awaiting_entry": summary_payload.get("awaiting_entry"),
                "complete": summary_payload.get("complete"),
                "missing_from_portal": summary_payload.get("missing_from_portal"),
            },
            "parity": parity,
            "awaiting_fold_audit": {
                "true_awaiting_fold": true_fold,
                "missing_from_portal": missing,
                "other": other,
                "rows": awaiting_fold_rows,
            },
            "population": population,
        }
        print(json.dumps(out, indent=2, default=str))
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
