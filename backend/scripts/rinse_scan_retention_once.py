#!/usr/bin/env python3
"""Scan / upload-history retention — dry-run by default, DISABLED for production.

  python -m backend.scripts.rinse_scan_retention_once --org 3
  python -m backend.scripts.rinse_scan_retention_once --org 3 --out /tmp/scan_ret.json

Apply remains hard-blocked (``APPLY_BLOCKED``) and requires:
  RINSE_SCAN_RETENTION_ENABLED=1
  RINSE_SCAN_RETENTION_APPLY_UNLOCK=1
  --apply

Do NOT enable a production cron until separately approved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for env_path in (REPO / ".env", Path("/Users/kamisb./laundry_app/.env")):
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break

sys.path.insert(0, str(REPO))


def main() -> int:
    p = argparse.ArgumentParser(description="Lifecycle-safe scan retention (dry-run default)")
    p.add_argument("--org", type=int, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--upload-days", type=int, default=None)
    p.add_argument("--canonical-days", type=int, default=None)
    p.add_argument("--out", default="")
    p.add_argument(
        "--force-enable-for-plan",
        action="store_true",
        help="Treat retention as enabled for planning display only (still no apply)",
    )
    args = p.parse_args()

    from backend.db import get_db
    from backend.rinse_scan_retention import (
        APPLY_BLOCKED,
        apply_scan_retention,
        format_retention_report,
        resolve_retention_config,
    )

    conn = get_db()
    try:
        if not args.apply:
            try:
                c = conn.cursor()
                c.execute("SET SESSION TRANSACTION READ ONLY")
                c.close()
            except Exception:
                pass
        cursor = conn.cursor(dictionary=True)
        cfg = resolve_retention_config(
            cursor,
            args.org,
            enabled_override=True if args.force_enable_for_plan else None,
            upload_days=args.upload_days,
            canonical_days=args.canonical_days,
        )
        report = apply_scan_retention(
            cursor, args.org, config=cfg, dry_run=not args.apply
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(format_retention_report(report))
    print()
    if args.apply:
        print(f"applied={report.get('applied')} stopped={report.get('stopped_reason')}")
        print(
            f"deleted canonical={report.get('deleted_canonical')} "
            f"upload_scans={report.get('deleted_upload_scan_events')} "
            f"upload_rows={report.get('deleted_upload_batch_rows')}"
        )
        if APPLY_BLOCKED or not report.get("applied"):
            return 2
    else:
        print("DRY RUN only — no rows deleted. Apply is hard-blocked until approved.")

    out = args.out or f"/tmp/rinse_scan_retention_org{args.org}_dryrun.json"
    Path(out).write_text(json.dumps(report, indent=2, default=str))
    print(f"Report written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
