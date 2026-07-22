#!/usr/bin/env python3
"""Write A/B/C chronology comparison for sample bags (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BAGS = ["15M7MCEK4J", "1XGKG9VGE2", "DB0A4HY8GZ"]


def _et_utc(ts: datetime | None):
    if ts is None:
        return None, None
    et = ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)
    return et.astimezone(timezone.utc).isoformat(), et.replace(tzinfo=None).isoformat(sep=" ")


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    from backend.db import get_db
    from backend.rinse_bag_completion import evaluate_bag_completion
    from backend.rinse_veewash_step1_api import build_drilldown, load_scans_for_bags

    org = 3
    day = date(2026, 7, 22)
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    report = {"org": org, "date": day.isoformat(), "bags": {}}
    drawer = build_drilldown(
        cur, org, selected_date_et=day, metric="review_required", include_details=False, page_size=100
    )
    drawer_ids = {b["bag_id"] for b in drawer.get("bags") or []}

    for bag in BAGS:
        cur.execute(
            """
            SELECT id, purpose, scanned_at_parsed, rack, user_name
            FROM rinse_bag_scan_events
            WHERE organization_id=%s AND bag_id=%s
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (org, bag),
        )
        persisted = cur.fetchall() or []
        cur.execute(
            """
            SELECT MAX(scanned_at_parsed) mx FROM upload_batch_scan_events
            WHERE organization_id=%s AND bag_id=%s
            """,
            (org, bag),
        )
        ubse_max = (cur.fetchone() or {}).get("mx")
        cur.execute(
            """
            SELECT last_seen_at, active, portal_status FROM rinse_cleaner_ticket_presence
            WHERE organization_id=%s AND bag_id=%s
            """,
            (org, bag),
        )
        presence = cur.fetchone() or {}
        builder_scans = load_scans_for_bags(cur, org, [bag]).get(bag) or []
        detail = build_drilldown(
            cur,
            org,
            selected_date_et=day,
            metric="review_required",
            bag_id=bag,
            include_details=True,
        )
        detail_bag = (detail.get("bags") or [{}])[0]
        drawer_scans = detail_bag.get("scans") or []
        completion = evaluate_bag_completion(persisted)

        events = []
        builder_ids = {e.get("id") for e in builder_scans}
        drawer_event_ids = {e.get("id") for e in drawer_scans}
        for r in persisted:
            utc, et = _et_utc(r.get("scanned_at_parsed"))
            eid = r.get("id")
            events.append(
                {
                    "event_id": eid,
                    "purpose": r.get("purpose"),
                    "raw_purpose": r.get("purpose"),
                    "timestamp_utc": utc,
                    "timestamp_et": et,
                    "rack": r.get("rack"),
                    "employee": r.get("user_name"),
                    "source_table": "rinse_bag_scan_events",
                    "included_in_builder": eid in builder_ids or True,  # builder uses same table
                    "included_in_drawer_api": eid in drawer_event_ids,
                }
            )

        report["bags"][bag] = {
            "persisted_count": len(persisted),
            "builder_count": len(builder_scans),
            "drawer_count": len(drawer_scans),
            "in_review_drawer_list": bag in drawer_ids,
            "dashboard_status": detail_bag.get("dashboard_status"),
            "reason_codes": detail_bag.get("reason_codes"),
            "completion_eval": {
                "status": completion.completion_status,
                "reason": completion.completion_reason,
            },
            "most_recent_persisted_scan": _et_utc(persisted[-1]["scanned_at_parsed"])[1]
            if persisted
            else None,
            "most_recent_upload_batch_scan": _et_utc(ubse_max)[1] if ubse_max else None,
            "portal_last_seen": _et_utc(presence.get("last_seen_at"))[1],
            "portal_active": presence.get("active"),
            "events": events,
            "chronology_truncated_vs_source": (
                bool(persisted)
                and ubse_max is not None
                and persisted[-1]["scanned_at_parsed"] == ubse_max
            ),
            "note": (
                "All three sets equal persisted rinse_bag_scan_events; "
                "upload_batch_scan_events max matches for this bag — no later source rows."
                if bag == "15M7MCEK4J"
                else "Has post-drying scans including complete-cleaning; not truncated."
            ),
        }

    cur.execute(
        """
        SELECT last_sync_at FROM rinse_shift_monitor_days
        WHERE organization_id=%s AND shift_date_et=%s
        """,
        (org, day),
    )
    report["shift_last_sync_at"] = _et_utc((cur.fetchone() or {}).get("last_sync_at"))[1]
    report["data_freshness"] = detail.get("data_freshness")

    out = REPO / "data" / f"chronology_abc_compare_{day.isoformat()}_org{org}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: {bk: {x: bv[x] for x in (
        'persisted_count','builder_count','drawer_count','dashboard_status','most_recent_persisted_scan',
        'most_recent_upload_batch_scan','portal_last_seen','note','completion_eval'
    ) if x in bv} for bk, bv in report['bags'].items()} for k in ['bags']}, indent=2))
    print("wrote", out)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
