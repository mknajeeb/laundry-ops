#!/usr/bin/env python3
"""Re-sync headline review_reasons_by_bag from persisted day-bag rows (idempotent)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ORG_DEFAULT = 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=ORG_DEFAULT)
    parser.add_argument("--date-et", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    selected = date.fromisoformat(args.date_et)
    org = int(args.org)

    from backend.db import get_db
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
        split_review_categories,
    )
    from backend.rinse_veewash_shift_day import (
        _load_persisted_review_reasons_by_bag,
        _sync_day_header_from_persisted_bags,
        get_day_record,
        summary_from_day_record,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        day = get_day_record(cur, org, selected) or {}
        headline_before = dict(day.get("headline") or {})
        before = split_review_categories(headline_before)
        before_drawers = {}
        for cat in ("specialty_items", "missing_from_portal", "split_order_review"):
            lst = build_management_review_list(cur, org, selected, category=cat)
            before_drawers[cat] = len(lst.get("bags") or [])

        reasons_preview = _load_persisted_review_reasons_by_bag(cur, org, selected)
        report = {
            "organization_id": org,
            "date_et": selected.isoformat(),
            "mode": "apply" if args.apply else "dry_run",
            "before_counts": before.get("counts"),
            "before_drawers": before_drawers,
            "preview_reason_bags": len(reasons_preview),
            "preview_specialty_bags": [
                bid
                for bid, codes in reasons_preview.items()
                if "WF_BULK_WORKITEM_REVIEW" in (codes or [])
            ],
        }

        if args.apply:
            _sync_day_header_from_persisted_bags(
                cur,
                org,
                selected,
                summary=headline_before,
                workload=day.get("workload_meta") or {},
                next_status=str(day.get("status") or "OPEN"),
                opened_at=day.get("opened_at"),
                now=datetime.utcnow(),
            )
            conn.commit()
            day = get_day_record(cur, org, selected) or {}
            headline_after = summary_from_day_record(day) or {}
            after = split_review_categories(headline_after)
            review = review_category_count_payload(headline_after)
            after_drawers = {}
            for cat in ("specialty_items", "missing_from_portal", "split_order_review"):
                lst = build_management_review_list(cur, org, selected, category=cat)
                after_drawers[cat] = len(lst.get("bags") or [])
            wf = ((headline_after.get("segments") or {}).get("wf") or {})
            report["after_counts"] = after.get("counts")
            report["after_review_payload"] = review
            report["after_drawers"] = after_drawers
            report["wf_workload"] = {
                "total": wf.get("total_workload"),
                "completed": wf.get("completed"),
                "pending": wf.get("pending"),
                "review_required_segment": (wf.get("exceptions") or {}).get(
                    "review_required"
                ),
            }
            report["headline_equals_drawer"] = {
                cat: int(review.get(cat) or 0) == int(after_drawers.get(cat) or 0)
                for cat in ("specialty_items", "missing_from_portal", "split_order_review")
            }

        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
