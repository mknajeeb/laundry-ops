#!/usr/bin/env python3
"""Bounded org-3 heal: delete proven same-lifecycle portal-discovery OI orphans.

Usage:
  PYTHONPATH=. python3 backend/scripts/heal_org3_portal_oi_orphans.py --dry-run
  PYTHONPATH=. python3 backend/scripts/heal_org3_portal_oi_orphans.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _load_env() -> None:
    for candidate in (
        Path("/Users/kamisb./laundry_app-revenue-cash-prod-fix/.env"),
        Path(".env"),
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--org", type=int, default=3)
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and args.dry_run:
        raise SystemExit("pass only one of --dry-run / --apply")

    _load_env()
    from backend.db import get_db
    from backend.rinse_order_instances import heal_same_lifecycle_portal_orphan_ois

    dry_run = not args.apply
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        report = heal_same_lifecycle_portal_orphan_ois(
            cur, int(args.org), dry_run=dry_run
        )
        if args.apply:
            conn.commit()
        out_dir = Path("backups")
        out_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"heal_org{args.org}_portal_oi_orphans_{stamp}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": dry_run,
                    "report_path": str(path),
                    "candidates": len(report.get("candidates") or []),
                    "healed": len(report.get("healed") or []),
                    "ambiguous": len(report.get("ambiguous") or []),
                },
                indent=2,
            )
        )
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
