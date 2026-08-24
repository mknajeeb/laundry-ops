#!/usr/bin/env python3
"""Re-sync WF Review headline + day-bag rows from canonical evidence (idempotent)."""
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
        apply_canonical_wf_review_day_bag_fixes,
        build_management_review_list,
        compute_canonical_wf_review_membership,
        persist_canonical_wf_review_on_headline,
        review_category_count_payload,
        split_review_categories,
    )
    from backend.rinse_veewash_shift_day import (
        _json_dump,
        _sync_day_header_from_persisted_bags,
        get_day_record,
        summary_from_day_record,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        day = get_day_record(cur, org, selected) or {}
        headline_before = dict(day.get("headline") or {})
        before_payload = review_category_count_payload(
            headline_before,
            cursor=cur,
            organization_id=org,
            selected_date_et=selected,
        )
        before_drawers = {}
        for cat in ("specialty_items", "missing_from_portal", "split_order_review"):
            lst = build_management_review_list(cur, org, selected, category=cat)
            before_drawers[cat] = len(lst.get("bags") or [])

        membership = compute_canonical_wf_review_membership(
            cur, org, selected, headline=headline_before
        )
        from collections import Counter

        report = {
            "organization_id": org,
            "date_et": selected.isoformat(),
            "mode": "apply" if args.apply else "dry_run",
            "before_payload": {
                k: before_payload.get(k)
                for k in (
                    "review_required",
                    "specialty_items",
                    "missing_from_portal",
                    "split_order_review",
                    "unknown_review",
                )
            },
            "before_drawers": before_drawers,
            "canonical_membership": {
                "specialty_items": membership.get("specialty_items"),
                "missing_from_portal": membership.get("missing_from_portal"),
                "split_order_review": membership.get("split_order_review"),
                "unknown_review": membership.get("unknown_review"),
                "excluded": membership.get("excluded"),
            },
            "disposition_summary": dict(Counter((membership.get("disposition") or {}).values())),
        }

        if args.apply:
            fix_stats = apply_canonical_wf_review_day_bag_fixes(
                cur, org, selected, membership
            )
            sync = _sync_day_header_from_persisted_bags(
                cur,
                org,
                selected,
                summary=headline_before,
                workload=day.get("workload_meta") or {},
                next_status=str(day.get("status") or "OPEN"),
                opened_at=day.get("opened_at"),
                now=datetime.utcnow(),
            )
            headline_after = persist_canonical_wf_review_on_headline(
                sync.get("headline") or headline_before,
                membership,
            )
            review_n = int((membership.get("counts") or {}).get("review_required") or 0)
            cur.execute(
                """
                UPDATE rinse_shift_monitor_days
                SET headline_json = %s, review_required_count = %s, last_sync_at = %s
                WHERE organization_id = %s AND shift_date_et = %s
                """,
                (
                    _json_dump(headline_after),
                    review_n,
                    datetime.utcnow(),
                    org,
                    selected,
                ),
            )
            conn.commit()
            after_payload = review_category_count_payload(
                headline_after,
                cursor=cur,
                organization_id=org,
                selected_date_et=selected,
            )
            after_drawers = {}
            for cat in ("specialty_items", "missing_from_portal", "split_order_review"):
                lst = build_management_review_list(cur, org, selected, category=cat)
                after_drawers[cat] = len(lst.get("bags") or [])
            wf = ((headline_after.get("segments") or {}).get("wf") or {})
            report["after_payload"] = {
                k: after_payload.get(k)
                for k in (
                    "review_required",
                    "specialty_items",
                    "missing_from_portal",
                    "split_order_review",
                    "unknown_review",
                )
            }
            report["after_drawers"] = after_drawers
            report["fix_stats"] = fix_stats
            report["wf_workload"] = {
                "total": wf.get("total_workload"),
                "completed": wf.get("completed"),
                "pending": wf.get("pending"),
                "review_required_segment": (wf.get("exceptions") or {}).get(
                    "review_required"
                ),
            }
            union = set(after_payload.get("_membership", {}).get("specialty_items") or [])
            union |= set(after_payload.get("_membership", {}).get("missing_from_portal") or [])
            union |= set(after_payload.get("_membership", {}).get("split_order_review") or [])
            report["headline_union_count"] = len(union)
            report["headline_equals_drawer"] = {
                cat: int(after_payload.get(cat) or 0) == int(after_drawers.get(cat) or 0)
                for cat in ("specialty_items", "missing_from_portal", "split_order_review")
            }
            report["headline_review_required"] = after_payload.get("review_required")

        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
