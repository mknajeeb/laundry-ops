#!/usr/bin/env python3
"""Classify/stamp open WF OIs with OI-window canonical completion evidence.

Usage:
  PYTHONPATH=. python3 backend/scripts/stamp_org3_oi_lifecycle_completions.py --dry-run
  PYTHONPATH=. python3 backend/scripts/stamp_org3_oi_lifecycle_completions.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _load_env() -> None:
    for candidate in (
        Path("/Users/kamisb./laundry_app-revenue-cash-prod-fix/.env"),
        Path(".env"),
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--org", type=int, default=3)
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and args.dry_run:
        raise SystemExit("pass only one of --dry-run / --apply")

    _load_env()
    from backend.db import get_db
    from backend.rinse_order_instances import classify_and_stamp_open_ois_lifecycle_completion
    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload
    from backend.business_time import business_today
    from datetime import timedelta

    dry_run = not args.apply
    org = int(args.org)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        before = get_canonical_wf_workload(cur, org, business_today())
        cw_before = before.get("current_workload") or {}
        report = classify_and_stamp_open_ois_lifecycle_completion(
            cur, org, dry_run=dry_run
        )
        if args.apply:
            conn.commit()
        after = get_canonical_wf_workload(cur, org, business_today())
        cw_after = after.get("current_workload") or {}
        yday = get_canonical_wf_workload(
            cur, org, business_today() - timedelta(days=1)
        )
        cw_yday = yday.get("current_workload") or {}

        def _summ(cw: dict) -> dict:
            items = list(cw.get("items") or [])
            review = [
                {
                    "bag_id": i.get("bag_id"),
                    "order_instance_id": i.get("order_instance_id"),
                    "review_reason_codes": i.get("review_reason_codes"),
                }
                for i in items
                if i.get("status") == "review_required"
            ]
            return {
                "open": int((cw.get("counts") or {}).get("open") or 0),
                "pending": int((cw.get("counts") or {}).get("pending") or 0),
                "review": int((cw.get("counts") or {}).get("review") or 0),
                "review_rows": review,
            }

        out = {
            "dry_run": dry_run,
            "classify": {
                "counts": report.get("counts"),
                "should_close_examples": (report.get("should_close") or [])[:12],
                "pending_examples": (report.get("pending") or [])[:12],
                "review_examples": (report.get("review") or [])[:12],
                "stamped_count": len(report.get("stamped") or []),
                "error_count": len(report.get("errors") or []),
            },
            "cw_before": _summ(cw_before),
            "cw_after": _summ(cw_after),
            "cw_yesterday": _summ(cw_yday),
            "focus_should_close": [
                e
                for e in (report.get("should_close") or [])
                if e.get("bag_id")
                in {
                    "005649CRSL",
                    "00CY9RP1K6",
                    "061FK8HNNO",
                    "0CKPTHXUT9",
                    "0EWIIKL2ZM",
                    "0FEVKTTNJO",
                    "0MX6MR02FW",
                    "0N8Y2ZKPO7",
                }
            ],
        }
        out_dir = Path("backups")
        out_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"stamp_org{org}_oi_lifecycle_completions_{stamp}.json"
        # Full classify report is large — write separately
        path.write_text(json.dumps({**out, "full_classify": report}, indent=2, default=str))
        print(
            json.dumps(
                {
                    "ok": True,
                    "report_path": str(path),
                    **{k: out[k] for k in out if k != "full_classify"},
                },
                indent=2,
                default=str,
            )
        )
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
