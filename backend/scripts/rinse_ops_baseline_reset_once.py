#!/usr/bin/env python3
"""Scoped org-3 Rinse operational archive/reset (clean baseline).

Dry-run (default):
  python -m backend.scripts.rinse_ops_baseline_reset_once --org 3

Apply once:
  python -m backend.scripts.rinse_ops_baseline_reset_once --org 3 --apply
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
        description="Archive then clear org-scoped Rinse operational state"
    )
    parser.add_argument("--org", type=int, required=True, help="Must be 3")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Archive + clear (default is dry-run inventory only)",
    )
    parser.add_argument(
        "--archive-root",
        default=str(REPO / "backups"),
        help="Directory for archive folders",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional JSON report path",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.rinse_ops_baseline_reset import (
        format_inventory_table,
        run_org_rinse_ops_baseline_reset,
    )

    conn = get_db()
    try:
        report = run_org_rinse_ops_baseline_reset(
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

    print(format_inventory_table(report))
    print()
    if report.get("stop_reasons"):
        print("STOP — unsafe targets; no mutation performed.")
        for s in report["stop_reasons"]:
            print(f"  {s}")
        return 2

    if not args.apply:
        print(
            "DRY RUN only — no rows archived or cleared. "
            "Re-run with --apply to execute."
        )
        print(
            f"Would archive/clear ~{report.get('totals', {}).get('clear_rows', 0)} rows "
            f"for organization_id={args.org}."
        )
    else:
        print(f"ARCHIVE DIR: {report.get('archive_dir')}")
        print(f"APPLIED: {report.get('applied')}")
        rem = report.get("active_remaining") or {}
        if rem:
            print("WARNING — remaining active rows after clear:")
            for k, v in rem.items():
                print(f"  {k}: {v}")
            return 1
        print("Active Rinse ops targets cleared to 0 for org.")
        before = report.get("preserved_counts") or {}
        after = report.get("preserved_counts_after") or {}
        drift = {
            k: (before.get(k), after.get(k))
            for k in sorted(set(before) | set(after))
            if before.get(k) != after.get(k)
        }
        if drift:
            print("STOP — preserved table counts changed:")
            for k, (b, a) in drift.items():
                print(f"  {k}: {b} -> {a}")
            return 1
        print("Preserved employees/payroll/auth/config counts unchanged.")

    out = args.out or str(
        Path(args.archive_root)
        / f"rinse_ops_baseline_reset_org{args.org}_report.json"
    )
    Path(out).write_text(json.dumps(report, indent=2, default=str))
    print(f"Report written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
