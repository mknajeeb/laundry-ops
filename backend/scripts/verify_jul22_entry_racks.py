#!/usr/bin/env python3
"""Rebuild Jul 22 Step-1 with multi entry racks and attribute first-entry rack."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from backend.db import get_db  # noqa: E402
from backend.rinse_processing_settings import (  # noqa: E402
    DEFAULT_FACILITY_ENTRY_RACKS,
    KEY_FACILITY_ENTRY_RACKS,
    get_processing_settings,
    put_processing_settings,
)
from backend.rinse_scan_time import normalize_rack_value  # noqa: E402
from backend.rinse_veewash_workload import (  # noqa: E402
    VEEWASH_ORG_ID,
    build_step1_headline_summary,
    build_veewash_daily_workload,
    get_step1_activation_date,
    load_presence_orders,
)


def _norm_bag(b: str) -> str:
    return str(b or "").strip().upper()


def first_configured_entry_rack_by_bag(cursor, organization_id: int, racks: list[str]) -> dict[str, str]:
    """First scan (by time) into any configured entry rack → canonical rack label."""
    keys = []
    label_by_key = {}
    for rack in racks:
        norm = normalize_rack_value(rack)
        if not norm:
            continue
        k = norm.casefold()
        keys.append(k)
        label_by_key[k] = norm
    if not keys:
        return {}
    placeholders = ",".join(["%s"] * len(keys))
    cursor.execute(
        f"""
        SELECT bag_id, rack, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND rack IS NOT NULL AND TRIM(rack) != ''
          AND LOWER(TRIM(rack)) IN ({placeholders})
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), *sorted(keys)),
    )
    out: dict[str, str] = {}
    for row in cursor.fetchall() or []:
        bid = _norm_bag(row.get("bag_id"))
        if not bid or bid in out:
            continue
        rack_norm = normalize_rack_value(row.get("rack"))
        if not rack_norm:
            continue
        out[bid] = label_by_key.get(rack_norm.casefold(), rack_norm)
    return out


def main() -> int:
    org = VEEWASH_ORG_ID
    D = date(2026, 7, 22)
    desired = list(DEFAULT_FACILITY_ENTRY_RACKS)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        before = get_processing_settings(cur, org).get("facility_entry_racks")
        put_processing_settings(cur, org, {"facility_entry_racks": desired})
        conn.commit()
        after = get_processing_settings(cur, org).get("facility_entry_racks")

        # Confirm stored setting key
        cur.execute(
            """
            SELECT svalue FROM system_settings
            WHERE organization_id = %s AND skey = %s
            LIMIT 1
            """,
            (org, KEY_FACILITY_ENTRY_RACKS),
        )
        row = cur.fetchone() or {}
        stored_raw = row.get("svalue")

        result = build_veewash_daily_workload(
            cur, org, selected_date_et=D, entry_racks=after
        )
        activation = get_step1_activation_date(cur, org) or D
        summary = build_step1_headline_summary(
            result, selected_date_et=D, activation_date=activation
        )

        members = set(result.get("new_today") or []) | set(result.get("carryover") or [])
        presence = load_presence_orders(cur, org, at_vendor_only=True)
        active_wf_hd = {
            bid
            for bid, p in presence.items()
            if int(p.get("active") or 0) == 1
            and str(p.get("service_type") or "").upper() in ("WF", "HD")
        }
        first_rack = first_configured_entry_rack_by_bag(cur, org, list(after or desired))

        by_rack = Counter()
        member_by_rack: dict[str, list[str]] = defaultdict(list)
        for bid in sorted(members):
            rack = first_rack.get(bid) or "(unknown)"
            by_rack[rack] += 1
            member_by_rack[rack].append(bid)

        # Active portal bags still outside workload (no configured entry scan)
        excluded_active = sorted(
            bid
            for bid in active_wf_hd
            if bid not in members and bid not in first_rack
        )
        # Presence bags classified not_in_workload with reason no_recognized_service_entry
        no_entry_rows = [
            r.get("bag_id")
            for r in (result.get("rows") or [])
            if r.get("final_bucket") == "not_in_workload"
            and r.get("reason") == "no_recognized_service_entry"
            and int(r.get("active") or 0) == 1
        ]

        # Dirty-only baseline for delta
        dirty_only = build_veewash_daily_workload(
            cur, org, selected_date_et=D, entry_racks=["VeeWash Dirty"]
        )
        dirty_members = set(dirty_only.get("new_today") or []) | set(
            dirty_only.get("carryover") or []
        )

        report = {
            "selected_date_et": D.isoformat(),
            "organization_id": org,
            "facility_entry_racks_before": before,
            "facility_entry_racks_after": after,
            "facility_entry_racks_stored_raw": stored_raw,
            "entry_racks_used": result.get("entry_racks"),
            "total_active_workload": int(summary.get("active_workload") or 0),
            "counts": {
                "new_today": summary.get("new_today"),
                "carryover": summary.get("carryover"),
                "completed": summary.get("completed"),
                "pending": summary.get("pending"),
                "review_required": (summary.get("exceptions") or {}).get("review_required"),
            },
            "segments": {
                "wf": summary.get("segments", {}).get("wf"),
                "hd": summary.get("segments", {}).get("hd"),
            },
            "entry_rack_attribution": {
                "by_first_entry_rack": dict(by_rack),
                "bags_by_first_entry_rack": {k: v for k, v in member_by_rack.items()},
            },
            "dirty_only_baseline_active": len(dirty_members),
            "added_vs_dirty_only": sorted(members - dirty_members),
            "added_vs_dirty_only_count": len(members - dirty_members),
            "active_portal_without_configured_entry_scan": excluded_active,
            "active_portal_without_configured_entry_scan_count": len(excluded_active),
            "not_in_workload_no_recognized_entry_active": sorted(no_entry_rows),
            "not_in_workload_no_recognized_entry_active_count": len(no_entry_rows),
            "reconciliation": result.get("reconciliation"),
        }

        out_path = ROOT / "tmp" / "deploy_verify" / "jul22_entry_racks_verify.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str))
        print(f"\nWrote {out_path}", file=sys.stderr)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
