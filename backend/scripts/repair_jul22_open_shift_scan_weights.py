#!/usr/bin/env python3
"""
Repair Jul 22 OPEN-shift weight-entry scans where portal weight_num is numeric
but rinse_bag_scan_events.weight_lbs is null.

Does not invent values: attaches only when the same-day ACCEPTED portal row
has a deterministic numeric weight_num (0 preserved) and a matching scan target.

Usage:
  python3 -m backend.scripts.repair_jul22_open_shift_scan_weights --org 3 --dry-run
  python3 -m backend.scripts.repair_jul22_open_shift_scan_weights --org 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_DATE = date(2026, 7, 22)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair OPEN-shift null scan.weight_lbs from portal")
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", default=DEFAULT_DATE.isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")

    selected = date.fromisoformat(args.date)
    org = int(args.org)
    repaired_at = datetime.now(timezone.utc).isoformat()

    from backend.db import get_db
    from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
    from backend.rinse_scan_purpose import is_weight_entry_purpose
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
    from backend.rinse_workload_bag_weight import (
        attach_portal_weight_to_post_processing_scan,
        load_latest_portal_weights_for_bags,
        load_portal_upload_weights_for_bags,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    day_start = naive_et_day_start(selected)
    day_end = naive_et_day_end_inclusive(selected)

    # Only bags with at least one null weight-entry on the selected day.
    cur.execute(
        """
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
          AND weight_lbs IS NULL
          AND (
            LOWER(TRIM(purpose)) = 'weight-entry'
            OR LOWER(TRIM(purpose)) LIKE 'weight-entry %%'
          )
        """,
        (org, day_start, day_end),
    )
    candidate_bags = sorted(
        {
            str(r.get("bag_id") or "").strip().upper()
            for r in (cur.fetchall() or [])
            if str(r.get("bag_id") or "").strip()
        }
    )

    same_day = load_portal_upload_weights_for_bags(
        cur, org, candidate_bags, selected_date_et=selected
    )
    latest = load_latest_portal_weights_for_bags(cur, org, candidate_bags)
    registry: dict[str, float] = {}
    if candidate_bags:
        ph = ",".join(["%s"] * len(candidate_bags))
        cur.execute(
            f"""
            SELECT bag_id, weight_num
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({ph})
              AND weight_num IS NOT NULL
            """,
            (org, *candidate_bags),
        )
        for row in cur.fetchall() or []:
            bid = str(row.get("bag_id") or "").strip().upper()
            lbs = normalize_scan_weight_lbs(row.get("weight_num"))
            if bid and lbs is not None:
                registry[bid] = lbs

    def resolve_source(bid: str) -> tuple[float | None, str | None]:
        if bid in same_day:
            return same_day[bid], "upload_batch_rows.weight_num"
        if bid in latest:
            return latest[bid], "upload_batch_rows.weight_num(latest)"
        if bid in registry:
            return registry[bid], "rinse_bag_registry.weight_num"
        return None, None

    repairs: list[dict] = []
    skipped: list[dict] = []

    for bid in candidate_bags:
        source_lbs, source_field = resolve_source(bid)
        if source_lbs is None or not source_field:
            skipped.append({"bag_id": bid, "reason": "no_deterministic_weight_source"})
            continue
        # Capture before state for weight-entry rows
        cur.execute(
            """
            SELECT id, purpose, scanned_at_parsed, weight_lbs
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id = %s
              AND scanned_at_parsed >= %s
              AND scanned_at_parsed <= %s
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (org, bid, day_start, day_end),
        )
        day_events = cur.fetchall() or []
        weight_entries = [
            r for r in day_events if is_weight_entry_purpose(r.get("purpose"))
        ]
        before_by_id = {
            int(r["id"]): normalize_scan_weight_lbs(r.get("weight_lbs"))
            for r in weight_entries
            if r.get("id") is not None
        }

        if args.dry_run:
            preview = attach_portal_weight_to_post_processing_scan(
                cur,
                org,
                bid,
                weight_lbs=source_lbs,
                selected_date_et=selected,
                events=day_events,
            )
            conn.rollback()
            scan_id = preview.get("scan_event_id") or (preview.get("trace") or {}).get(
                "completion_event_id"
            )
            repairs.append(
                {
                    "bag_id": bid,
                    "dry_run": True,
                    "old_value": before_by_id.get(int(scan_id)) if scan_id else None,
                    "new_value": float(source_lbs),
                    "source_field": source_field,
                    "event_id": scan_id,
                    "attach_target": preview.get("attach_target")
                    or (preview.get("trace") or {}).get("attach_target"),
                    "reason": preview.get("reason"),
                    "would_update": bool(preview.get("updated")),
                    "repair_timestamp": repaired_at,
                }
            )
            continue

        result = attach_portal_weight_to_post_processing_scan(
            cur,
            org,
            bid,
            weight_lbs=source_lbs,
            selected_date_et=selected,
            events=day_events,
        )
        scan_id = result.get("scan_event_id")
        if not result.get("updated") or scan_id is None:
            skipped.append(
                {
                    "bag_id": bid,
                    "reason": result.get("reason") or "not_updated",
                    "source_field": source_field,
                    "source_value": float(source_lbs),
                }
            )
            continue
        repairs.append(
            {
                "bag_id": bid,
                "dry_run": False,
                "old_value": before_by_id.get(int(scan_id)),
                "new_value": float(result.get("weight_lbs")),
                "source_field": source_field,
                "event_id": int(scan_id),
                "attach_target": result.get("attach_target"),
                "repair_timestamp": repaired_at,
            }
        )

    if args.apply:
        conn.commit()
    else:
        conn.rollback()

    applied = [r for r in repairs if (r.get("would_update") if r.get("dry_run") else True)]
    report = {
        "org": org,
        "date": selected.isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "repair_timestamp": repaired_at,
        "candidate_bags": len(candidate_bags),
        "repaired_count": len(applied),
        "repairs": repairs,
        "applied_repairs": applied,
        "skipped": skipped,
    }

    out_path = Path(
        args.out
        or (
            REPO
            / "data"
            / f"repair_jul22_open_shift_scan_weights_{selected.isoformat()}_org{org}_{'apply' if args.apply else 'dry_run'}.json"
        )
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mode", "date", "repaired_count", "candidate_bags")}, indent=2))
    print(f"wrote {out_path}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
