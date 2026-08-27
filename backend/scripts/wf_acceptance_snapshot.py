#!/usr/bin/env python3
"""WF acceptance snapshot for a selected ET date (read-only metrics)."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORG = 3


def _norm_bid(v) -> str:
    return str(v or "").strip().upper()


def snapshot(cur, target: date) -> dict:
    from backend.business_time import system_datetime_to_et
    from backend.management_rinse_wf_review import compute_canonical_wf_review_membership
    from backend.rinse_veewash_shift_day import get_day_record, load_day_bags, summary_from_day_record
    from backend.rinse_wf_service_cycle_compat import _prior_day_terminal_completed_wf_bag_ids

    prior = target - timedelta(days=1)
    day = get_day_record(cur, ORG, target) or {}
    headline = summary_from_day_record(day, cursor=cur, organization_id=ORG) or {}
    wf = ((headline or {}).get("segments") or {}).get("wf") or {}

    from backend.rinse_wf_service_cycle_compat import wf_terminal_ineligible_bag_ids

    wf_rows = [
        r
        for r in (load_day_bags(cur, ORG, target) or [])
        if str(r.get("service_type") or "WF").upper() == "WF"
    ]
    bag_ids = sorted({_norm_bid(r.get("bag_id")) for r in wf_rows if _norm_bid(r.get("bag_id"))})
    prior_done = _prior_day_terminal_completed_wf_bag_ids(cur, ORG, target)
    terminal_ineligible = wf_terminal_ineligible_bag_ids(cur, ORG, target, bag_ids)
    stale_d1 = sorted(b for b in bag_ids if b in prior_done)
    historical_completed = sorted(b for b in bag_ids if b in terminal_ineligible)

    completed = int(wf.get("completed") or 0)
    pending = int(wf.get("pending") or 0)
    review = int(wf.get("review_required") or 0)
    workload = int(wf.get("total_workload") or wf.get("active_workload") or 0)

    review_mem = compute_canonical_wf_review_membership(cur, ORG, target) or {}
    missing_ids = sorted(
        {_norm_bid(b) for b in (review_mem.get("missing_from_portal") or []) if _norm_bid(b)}
    )
    missing_stale_prior = sorted(b for b in missing_ids if b in prior_done)

    bag_hash = hashlib.sha256(",".join(bag_ids).encode()).hexdigest()[:16]

    return {
        "target_date_et": target.isoformat(),
        "prior_date_et": prior.isoformat(),
        "workload": workload,
        "unique_bag_ids": len(bag_ids),
        "completed": completed,
        "pending": pending,
        "review": review,
        "workload_arithmetic_ok": workload == completed + pending + review,
        "missing_from_portal": len(missing_ids),
        "missing_stale_d1_count": len(missing_stale_prior),
        "d1_terminal_contamination": len(stale_d1),
        "d1_contamination_ids_sample": stale_d1[:5],
        "historical_completed_contamination": len(historical_completed),
        "historical_completed_ids_sample": historical_completed[:5],
        "bag_id_hash": bag_hash,
        "bag_ids": bag_ids,
        "last_sync_at_et": (
            str(system_datetime_to_et(day.get("last_sync_at")))
            if day.get("last_sync_at")
            else None
        ),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wf_acceptance_snapshot.py YYYY-MM-DD", file=sys.stderr)
        return 2
    target = date.fromisoformat(sys.argv[1])
    from backend.db import get_db

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        out = snapshot(cur, target)
        # omit full bag list from stdout summary unless requested
        summary = {k: v for k, v in out.items() if k != "bag_ids"}
        print(json.dumps(summary, indent=2, default=str))
        if "--with-ids" in sys.argv:
            print(json.dumps({"bag_ids": out["bag_ids"]}, indent=2))
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
