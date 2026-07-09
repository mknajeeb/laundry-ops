#!/usr/bin/env python3
"""Audit why an ET-day At Vendor workload total changes mid-day.

Reconstructs the immutable ET-day universe from scan-event evidence (which never
shrinks) and compares it against the current build_at_vendor_module output and
the live portal board, exposing every filter that removes membership.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", default="2026-07-08")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")

    selected = date.fromisoformat(args.date)
    org = int(args.org)

    from backend.db import get_db
    from backend.rinse_at_vendor_module import (
        _load_active_at_vendor_presence_by_bag,
        _load_at_vendor_bag_ids_seen_during_et_day,
        _load_off_portal_registry_terminal_bag_ids,
        _load_portal_scrape_rejected_bag_ids,
        _load_sent_to_vendor_bag_id_sets_for_et_day,
        build_at_vendor_module,
    )
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    av = build_at_vendor_module(cur, org, selected_date_et=selected, baseline_ctx=baseline)
    rows = av.get("rows") or []
    row_ids = {str(r.get("bag_id") or "").upper() for r in rows if r.get("bag_id")}

    # Immutable evidence (scan events never disappear)
    _, sent_during_day = _load_sent_to_vendor_bag_id_sets_for_et_day(
        cur, org, selected_date_et=selected
    )
    at_vendor_seen = _load_at_vendor_bag_ids_seen_during_et_day(
        cur, org, selected_date_et=selected
    )
    live_board = set(_load_active_at_vendor_presence_by_bag(cur, org).keys())
    rejected = _load_portal_scrape_rejected_bag_ids(cur, org)
    off_portal_terminal = _load_off_portal_registry_terminal_bag_ids(cur, org)

    ledger = av.get("workload_ledger") or {}
    meta = av.get("population_meta") or {}
    seed_ids = {str(b).upper() for b in (meta.get("baseline_snapshot_bag_ids") or [])}

    immutable_universe = seed_ids | sent_during_day | at_vendor_seen
    completed_ids = {
        str(r.get("bag_id") or "").upper()
        for r in rows
        if str(r.get("at_vendor_status") or "").lower() == "completed"
        or r.get("completed_during_et_day")
    }
    pending_ids = row_ids - completed_ids

    missing_from_build = sorted(immutable_universe - row_ids - rejected)
    left_portal_but_in_universe = sorted(immutable_universe - live_board)

    report = {
        "org": org,
        "date": selected.isoformat(),
        "current_build": {
            "total": av.get("total"),
            "pending": av.get("pending"),
            "completed": av.get("completed"),
            "rows": len(rows),
            "live_vendor_home_total": av.get("current_live_vendor_home_total"),
            "scan_only_arrivals_blocked_count": av.get("scan_only_arrivals_blocked_count"),
            "off_portal_stale_pending_excluded_count": av.get(
                "off_portal_stale_pending_excluded_count"
            ),
            "off_portal_completed_retained_count": av.get("off_portal_completed_retained_count"),
            "at_vendor_presence_stale": meta.get("at_vendor_presence_stale"),
            "daily_metrics_reliable": av.get("daily_metrics_reliable"),
        },
        "immutable_evidence": {
            "seed_ids": len(seed_ids),
            "sent_to_vendor_during_day": len(sent_during_day),
            "at_vendor_seen_during_day": len(at_vendor_seen),
            "immutable_universe_total": len(immutable_universe),
            "live_board_now": len(live_board),
            "rejected_explicit": len(rejected),
            "off_portal_terminal_ids": len(off_portal_terminal),
        },
        "reconciliation": {
            "immutable_universe_total": len(immutable_universe),
            "current_rows_total": len(rows),
            "shrink_vs_immutable": len(immutable_universe) - len(rows),
            "missing_from_build_count": len(missing_from_build),
            "missing_from_build_sample": missing_from_build[:40],
            "left_portal_but_in_universe_count": len(left_portal_but_in_universe),
            "completed_in_rows": len(completed_ids),
            "pending_in_rows": len(pending_ids),
        },
        "immutable_ledger": {
            "et_date": selected.isoformat(),
            "immutable_total": ledger.get("immutable_total"),
            "original_workload_total": av.get("original_workload_total"),
            "all_unique_bags_ever_seen": ledger.get("immutable_total"),
            "current_latest_portal_board_bags": len(live_board),
            "bags_completed": ledger.get("completed"),
            "bags_sent_to_rinse": ledger.get("sent_to_rinse"),
            "bags_pending": ledger.get("pending"),
            "bags_needs_verification": ledger.get("needs_verification"),
            "bags_explicitly_rejected": ledger.get("rejected"),
            "bucket_sum": ledger.get("bucket_sum"),
            "immutable_total_equals_bucket_sum": ledger.get("reconciles"),
            "persisted": ledger.get("persisted"),
        },
    }
    out_path = args.out or f"data/audit_jul8_workload_immutability_org{org}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
