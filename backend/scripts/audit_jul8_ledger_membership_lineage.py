#!/usr/bin/env python3
"""Classify every bag in the immutable ET-day ledger by lifecycle lineage.

Proves what the Jul 8 immutable total is composed of: new-today vs carry-over
from the prior day vs older backlog vs already-completed-before-the-day. Uses
scan-event chronology (immutable) as the source of truth, independent of the
stored ledger status.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
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

    from backend.db import get_db
    from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid
    from backend.rinse_scan_purpose import is_sent_to_vendor_purpose
    from backend.rinse_folding_et import (
        naive_et_day_end_inclusive,
        naive_et_day_start,
    )
    from backend.rinse_at_vendor_module import (
        AV_STATUS_COMPLETED,
        _bag_status_as_of,
        _completion_date_et,
        _evaluate_bag_as_of,
        _latest_sent_to_vendor_ts,
        _load_at_vendor_scan_events_for_bags,
        _normalize_service,
    )
    from backend.rinse_workload_ledger import load_workload_ledger

    selected = date.fromisoformat(args.date)
    org = int(args.org)
    day_start = naive_et_day_start(selected)
    day_end_excl = naive_et_day_start(selected + timedelta(days=1))
    prior_day_end = naive_et_day_end_inclusive(selected - timedelta(days=1))

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    ledger = load_workload_ledger(cur, org, selected)
    bag_ids = sorted(ledger.keys())
    events_by_bag = _load_at_vendor_scan_events_for_bags(cur, org, bag_ids)

    def _sent_ts_list(events):
        out = []
        for ev in gaming_events_from_records(events):
            if not is_sent_to_vendor_purpose(ev.get("purpose")):
                continue
            ts = event_ts(ev)
            if ts_valid(ts):
                out.append(ts)
        return sorted(out)

    categories: Counter = Counter()
    details: list[dict] = []
    for bid in bag_ids:
        events = events_by_bag.get(bid) or []
        sent = _sent_ts_list(events)
        first_sent = sent[0] if sent else None
        sent_during = [t for t in sent if day_start <= t < day_end_excl]
        sent_before = [t for t in sent if t < day_start]
        last_sent_before = max(sent_before) if sent_before else None

        svc = _normalize_service(
            (ledger[bid].get("workflow"))
            or (ledger[bid].get("row_snapshot") or {}).get("service_type")
        )

        completed_before_day = False
        if last_sent_before is not None:
            st, _sig, comp_ts, _sent_ts, _ = _evaluate_bag_as_of(
                events,
                service_type=svc,
                as_of_end=prior_day_end,
                anchor_ts_override=last_sent_before,
            )
            if st == AV_STATUS_COMPLETED and comp_ts is not None:
                cdate = _completion_date_et(comp_ts)
                completed_before_day = cdate is not None and cdate < selected

        # Mutually exclusive classification, priority order.
        if completed_before_day and not sent_during:
            cat = "4_already_completed_before_jul8"
        elif sent_during and not sent_before:
            cat = "1_new_today_first_arrival"
        elif sent_during and sent_before:
            cat = "5_arrived_jul8_resend_of_prior"
        elif last_sent_before is not None and _completion_date_et(last_sent_before) == (
            selected - timedelta(days=1)
        ):
            cat = "2_carryover_from_jul7"
        elif last_sent_before is not None:
            cat = "3_older_backlog_jul6_or_earlier"
        elif not sent:
            cat = "6_no_sent_to_vendor_scan_portal_only"
        else:
            cat = "6_other"

        categories[cat] += 1
        details.append(
            {
                "bag_id": bid,
                "category": cat,
                "ledger_status": ledger[bid].get("current_status"),
                "population_inclusion": ledger[bid].get("population_inclusion"),
                "first_sent_to_vendor_et": first_sent.isoformat() if first_sent else None,
                "last_sent_before_day_et": last_sent_before.isoformat()
                if last_sent_before
                else None,
                "sent_during_day_count": len(sent_during),
                "completed_before_day": completed_before_day,
            }
        )

    # Distribution of the earliest sent-to-vendor ET date across the ledger.
    first_sent_by_date: Counter = Counter()
    for d in details:
        fs = d.get("first_sent_to_vendor_et")
        first_sent_by_date[fs[:10] if fs else "none"] += 1

    report = {
        "org": org,
        "et_date": selected.isoformat(),
        "ledger_total": len(bag_ids),
        "category_totals": dict(sorted(categories.items())),
        "first_sent_to_vendor_date_distribution": dict(
            sorted(first_sent_by_date.items())
        ),
        "ledger_status_distribution": dict(
            Counter(ledger[b].get("current_status") for b in bag_ids)
        ),
        "sample_older_backlog": [
            d for d in details if d["category"].startswith("3_")
        ][:25],
        "sample_carryover_jul7": [
            d for d in details if d["category"].startswith("2_")
        ][:25],
        "details": details,
    }
    out_path = args.out or f"data/audit_jul8_ledger_membership_lineage_org{org}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    printable = {k: v for k, v in report.items() if k != "details"}
    printable["sample_older_backlog"] = report["sample_older_backlog"][:6]
    printable["sample_carryover_jul7"] = report["sample_carryover_jul7"][:6]
    print(json.dumps(printable, indent=2))
    print(f"\nFull report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
