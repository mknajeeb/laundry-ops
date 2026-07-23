#!/usr/bin/env python3
"""Jul 23 evidence + Pre/Post weight validation after evidence-first cutover."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET = date(2026, 7, 23)
ORG = 3


def main() -> int:
    from backend.db import get_db
    from backend.rinse_bag_completion import normalize_bag_id
    from backend.rinse_scan_purpose import is_weight_entry_purpose
    from backend.rinse_veewash_day_membership import build_append_only_membership
    from backend.rinse_veewash_review import resolve_weight_entry_pair
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
    from backend.ta_helpers import table_has_column

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    report: dict = {"organization_id": ORG, "date_et": TARGET.isoformat()}
    try:
        cur.execute(
            """
            SELECT id, status, rows_found,
                   CONVERT_TZ(COALESCE(finished_at, created_at), '+00:00', 'America/New_York') AS finished_et
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id=%s AND portal_status='at_vendor' AND dry_run=0
              AND DATE(CONVERT_TZ(COALESCE(finished_at, created_at), '+00:00', 'America/New_York'))=%s
            ORDER BY id
            """,
            (ORG, TARGET.isoformat()),
        )
        runs = [dict(r) for r in (cur.fetchall() or []) if isinstance(r, dict)]
        report["jul23_runs"] = [
            {"id": r["id"], "status": r["status"], "rows_found": r["rows_found"], "finished_et": str(r.get("finished_et"))}
            for r in runs
        ]
        report["total_valid_jul23_runs"] = len(
            [r for r in runs if str(r.get("status") or "").lower() in ("success", "partial")]
        )
        cur.execute("SELECT id FROM rinse_cleaner_ticket_presence_runs WHERE id=3472")
        report["baseline_3472_exists"] = cur.fetchone() is not None

        membership = build_append_only_membership(cur, ORG, TARGET)
        from backend.rinse_veewash_day_membership import membership_bag_ids

        baseline_id = membership.get("baseline_presence_run_id")
        report["membership_ok"] = bool(membership.get("ok"))
        report["membership_error"] = membership.get("error")
        report["membership_baseline_run_id"] = baseline_id
        report["membership_baseline_exists"] = baseline_id is not None
        report["membership_delayed_baseline"] = bool(membership.get("baseline_delayed"))
        bag_ids = membership_bag_ids(membership)

        # Source-run reconstruction gaps (bags whose introducing run is missing).
        missing_source = []
        for bag in bag_ids:
            cur.execute(
                """
                SELECT rr.presence_run_id
                FROM rinse_cleaner_ticket_presence_run_rows rr
                JOIN rinse_cleaner_ticket_presence_runs r ON r.id=rr.presence_run_id
                WHERE rr.organization_id=%s AND rr.bag_id=%s
                  AND DATE(CONVERT_TZ(COALESCE(r.finished_at, r.created_at), '+00:00', 'America/New_York'))=%s
                ORDER BY r.id ASC LIMIT 1
                """,
                (ORG, bag, TARGET.isoformat()),
            )
            row = cur.fetchone()
            if not row:
                missing_source.append(bag)
        report["membership_bag_count"] = len(bag_ids)
        report["membership_bags_missing_source_run"] = missing_source

        cur.execute(
            """
            SELECT COUNT(*) AS c,
                   SUM(CASE WHEN rr.weight_num IS NOT NULL THEN 1 ELSE 0 END) AS with_weight
            FROM rinse_cleaner_ticket_presence_run_rows rr
            JOIN rinse_cleaner_ticket_presence_runs r ON r.id=rr.presence_run_id
            WHERE r.organization_id=%s
              AND DATE(CONVERT_TZ(COALESCE(r.finished_at, r.created_at), '+00:00', 'America/New_York'))=%s
            """,
            (ORG, TARGET.isoformat()),
        )
        rr = cur.fetchone() or {}
        report["total_jul23_run_rows"] = int(rr.get("c") or 0)
        report["run_rows_with_weight_num"] = int(rr.get("with_weight") or 0)

        # Ensure columns exist for weight_num query honesty
        has_weight_col = table_has_column(cur, "rinse_cleaner_ticket_presence_run_rows", "weight_num")
        report["weight_num_column_present"] = has_weight_col

        pre = post = both = missing_pre = missing_post = third = 0
        manager_preserved = 0
        for bag in bag_ids:
            cur.execute(
                """
                SELECT id, purpose, scanned_at_parsed AS scanned_at, weight_lbs, weight_source, weight_role
                FROM rinse_bag_scan_events
                WHERE organization_id=%s AND bag_id=%s
                ORDER BY scanned_at_parsed ASC, id ASC
                """,
                (ORG, bag),
            )
            events = [
                dict(e)
                for e in (cur.fetchall() or [])
                if isinstance(e, dict) and is_weight_entry_purpose(e.get("purpose"))
            ]
            if len(events) >= 3:
                third += 1
            pair = resolve_weight_entry_pair(events)
            pre_w = normalize_scan_weight_lbs(pair.get("pre_weight_lbs"))
            post_w = normalize_scan_weight_lbs(pair.get("post_weight_lbs"))
            svc = None
            cur.execute(
                """
                SELECT service_type FROM rinse_cleaner_ticket_presence_run_rows
                WHERE organization_id=%s AND bag_id=%s ORDER BY id DESC LIMIT 1
                """,
                (ORG, bag),
            )
            srow = cur.fetchone() or {}
            svc = str(srow.get("service_type") or "").upper()
            if svc != "WF":
                continue
            if pre_w is not None:
                pre += 1
            else:
                missing_pre += 1
            if pair.get("post_weight_event_exists") and post_w is not None:
                post += 1
            elif pair.get("post_weight_event_exists"):
                missing_post += 1
            if pre_w is not None and post_w is not None:
                both += 1
            if any(
                str(e.get("weight_source") or "").startswith("manager")
                or str(e.get("weight_source") or "") == "correct_weight"
                for e in events
            ):
                manager_preserved += 1

        report["wf_bags_with_pre"] = pre
        report["wf_bags_with_post"] = post
        report["wf_bags_with_both"] = both
        report["wf_missing_pre"] = missing_pre
        report["wf_missing_post"] = missing_post
        report["third_or_later_weight_events"] = third
        report["manager_corrected_weights_seen"] = manager_preserved

        if table_has_column(cur, "rinse_weight_observation_migration_archive", "status"):
            cur.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM rinse_weight_observation_migration_archive
                WHERE organization_id=%s
                GROUP BY status
                """,
                (ORG,),
            )
            report["migration_by_status"] = {
                str(r.get("status")): int(r.get("c") or 0)
                for r in (cur.fetchall() or [])
                if isinstance(r, dict)
            }
        else:
            report["migration_by_status"] = {}

        out = Path("data/jul23_evidence_weight_validation.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str))
        print(f"wrote {out}")
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
