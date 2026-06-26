#!/usr/bin/env python3
"""Production closeout verification for scan-events decoupling from portal ACA gate."""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG = 3
FIX_SHA_PREFIX = "27c55f5"
API_HEALTH = "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net/health"


def _today_et() -> date:
    from backend.rinse_scheduled_scrape import _today_et

    return _today_et()


def _check_health() -> dict:
    with urllib.request.urlopen(API_HEALTH, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    selected = _today_et()
    if len(sys.argv) > 1:
        selected = date.fromisoformat(sys.argv[1])

    report: dict = {"selected_date_et": selected.isoformat(), "checks": [], "ok": True}

    def record(name: str, passed: bool, detail: str | dict) -> None:
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            report["ok"] = False

    health = _check_health()
    sha = str(health.get("git_sha") or "")
    record(
        "health_git_sha",
        sha.startswith(FIX_SHA_PREFIX),
        {"git_sha": sha, "required_prefix": FIX_SHA_PREFIX},
    )

    from backend.db import get_db
    from backend.rinse_at_vendor_module import build_at_vendor_module
    from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute(
        """
        SELECT id, status, started_at, finished_at, scan_events_count, imported_batch_id,
               error_message, result_json
        FROM rinse_scrape_runs
        WHERE organization_id = %s AND started_at >= %s
        ORDER BY started_at DESC LIMIT 5
        """,
        (ORG, datetime(2026, 6, 26, 15, 53, 0)),
    )
    post_deploy_scrapes = cur.fetchall()
    post_fix_scrape = None
    for row in post_deploy_scrapes:
        detail = row.get("result_json")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        row = dict(row)
        row["result_json"] = detail
        ops = {
            k: detail.get(k)
            for k in (
                "portal_confirm_blocked",
                "scan_events_import_attempted",
                "scan_events_imported_count",
                "scan_only_batch_id",
                "portal_confirm_block_reason",
            )
        }
        row["operational_log"] = ops
        if row["status"] == "inspect_only" and ops.get("scan_events_import_attempted"):
            post_fix_scrape = row
            break
        if row["status"] == "inspect_only" and (detail.get("scan_events_only_import") or {}).get(
            "status"
        ) == "scan_events_imported":
            post_fix_scrape = row
            break

    record(
        "post_deploy_inspect_only_scan_import",
        post_fix_scrape is not None,
        post_fix_scrape or {"message": "No post-deploy inspect_only scrape with scan import yet"},
    )

    if post_fix_scrape:
        ops = post_fix_scrape.get("operational_log") or {}
        record(
            "portal_gate_still_blocked",
            ops.get("portal_confirm_blocked") is True
            or post_fix_scrape.get("error_message"),
            ops,
        )
        record(
            "scan_events_imported_count_gt_zero",
            int(ops.get("scan_events_imported_count") or 0) > 0
            or int(post_fix_scrape.get("scan_events_count") or 0) > 0,
            {
                "scan_events_count": post_fix_scrape.get("scan_events_count"),
                "scan_events_imported_count": ops.get("scan_events_imported_count"),
            },
        )
        scan_batch = ops.get("scan_only_batch_id") or post_fix_scrape.get("imported_batch_id")
        record(
            "scan_only_batch_traceable",
            scan_batch is not None,
            {"scan_only_batch_id": scan_batch},
        )
        if scan_batch:
            cur.execute(
                "SELECT batch_id, state, file_name FROM upload_batches WHERE batch_id=%s",
                (int(scan_batch),),
            )
            batch_row = cur.fetchone()
            record(
                "scan_only_batch_not_portal_combined",
                batch_row
                and "scan-events-only" in str(batch_row.get("file_name") or "").lower(),
                batch_row,
            )
            record(
                "no_new_portal_batch_after_gate_block",
                batch_row and "scheduled-rinse-portal" not in str(batch_row.get("file_name") or ""),
                batch_row,
            )

    cur.execute(
        """
        SELECT COUNT(*) c FROM rinse_bag_scan_events
        WHERE organization_id=%s
          AND DATE(CONVERT_TZ(scanned_at_parsed,'UTC','America/New_York'))=%s
        """,
        (ORG, selected.isoformat()),
    )
    scan_today = int((cur.fetchone() or {}).get("c") or 0)
    record("scan_events_exist_selected_day", scan_today > 0, {"count": scan_today})

    baseline = build_baseline_context(cur, ORG, get_shift_monitor_baseline(cur, ORG))
    av = build_at_vendor_module(cur, ORG, selected_date_et=selected, baseline_ctx=baseline)
    completed = int(av.get("completed") or av.get("completed_today_count") or 0)
    pending = int(av.get("pending") or av.get("pending_count") or 0)
    emp_n = len((av.get("employee_completed_bags_today") or {}).get("employees") or [])

    record("shift_monitor_not_zero_zero", not (completed == 0 and pending >= 30), {
        "completed": completed,
        "pending": pending,
    })
    record("employee_productivity_populated", emp_n > 0 or completed == 0, {
        "employees": emp_n,
        "completed": completed,
    })

    report["summary"] = {
        "completed_today": completed,
        "pending": pending,
        "productivity_employees": emp_n,
        "scan_events_today": scan_today,
    }

    out = REPO_ROOT / "data" / "scan_events_gate_closeout_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
