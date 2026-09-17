#!/usr/bin/env python3
"""WF-only operational clean reset — dry-run by default.

Dry-run (read-only; SELECT only):
  python -m backend.scripts.wf_ops_clean_reset_once --org 3
  python -m backend.scripts.wf_ops_clean_reset_once --org 3 --out /tmp/wf_dryrun.json

Apply is hard-blocked in code (``wf_ops_clean_reset.APPLY_BLOCKED``) and would
additionally require ``WF_CLEAN_RESET_APPLY_UNLOCK=1`` plus ``wf_ops_maintenance``
already ON for the org.
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
    parser = argparse.ArgumentParser(
        description="Archive then clear WF-only Rinse operational state (HD untouched)"
    )
    parser.add_argument("--org", type=int, required=True, help="Must be 3")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Archive + WF-scoped clear (currently hard-blocked; default is dry-run)",
    )
    parser.add_argument(
        "--archive-root",
        default=str(REPO / "backups"),
        help="Directory for archive folders",
    )
    parser.add_argument("--out", default="", help="Optional JSON report path")
    parser.add_argument(
        "--read-only-session",
        action="store_true",
        default=True,
        help="Set the MySQL session read-only for dry-run (default on)",
    )
    parser.add_argument(
        "--no-read-only-session",
        action="store_false",
        dest="read_only_session",
        help="Do not attempt SET SESSION TRANSACTION READ ONLY",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.wf_ops_clean_reset import (
        APPLY_BLOCKED,
        format_dry_run_report,
        run_wf_clean_reset,
    )

    conn = get_db()
    read_only_note = "not requested"
    try:
        if not args.apply and args.read_only_session:
            try:
                cur = conn.cursor()
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.close()
                read_only_note = "session transaction read only"
            except Exception as exc:
                read_only_note = f"unavailable ({exc})"
        report = run_wf_clean_reset(
            conn,
            args.org,
            dry_run=not args.apply,
            archive_root=Path(args.archive_root),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    report["session_read_only"] = read_only_note
    print(format_dry_run_report(report))
    print()
    print(f"SESSION READ ONLY: {read_only_note}")

    exit_code = 0
    if report.get("stop_reasons"):
        print("STOP — unsafe targets; no mutation performed.")
        for reason in report["stop_reasons"]:
            print(f"  {reason}")
        exit_code = 2
    elif not args.apply:
        totals = report.get("totals") or {}
        print(
            "DRY RUN only — nothing archived, cleared, or updated. "
            f"Would archive ~{totals.get('archive_rows', 0)} rows, "
            f"clear ~{totals.get('clear_rows', 0)} rows, and reset "
            f"~{totals.get('registry_update_rows', 0)} registry rows "
            f"for organization_id={args.org}."
        )
    elif report.get("error"):
        print(f"APPLY REFUSED: {report['error']}")
        exit_code = 3
    else:
        print(f"ARCHIVE DIR: {report.get('archive_dir')}")
        print(f"APPLIED: {report.get('applied')}")

    if args.apply and APPLY_BLOCKED:
        print("NOTE: APPLY_BLOCKED=True — no production apply path is reachable.")

    out = args.out or str(
        Path(args.archive_root) / f"wf_ops_clean_reset_org{args.org}_dryrun.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2, default=str))
    print(f"Report written: {out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
