#!/usr/bin/env python3
"""Discover washer/dryer rack codes from rinse_bag_scan_events and merge into machine_rack_config."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--org",
        type=int,
        default=3,
        help="Organization id (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report discovered racks without writing system_settings",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.machine_configuration_settings import merge_discovered_racks_into_config

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        merged, stats = merge_discovered_racks_into_config(
            cursor,
            args.org,
            commit=not args.dry_run,
        )
        if args.dry_run:
            conn.rollback()
        report = {
            "organization_id": args.org,
            "dry_run": args.dry_run,
            **stats,
            "washers": dict(sorted(merged["washers"].items())),
            "dryers": dict(sorted(merged["dryers"].items())),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        cursor.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
