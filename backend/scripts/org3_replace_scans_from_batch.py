#!/usr/bin/env python3
"""
One-time org-3 persistent scan reset from a confirmed upload batch export.

Deletes stacked duplicate timelines and reinserts only the canonical rows from
the chosen batch (default: 1631 from production investigation).

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.org3_replace_scans_from_batch --dry-run
  python3 -m backend.scripts.org3_replace_scans_from_batch --apply
  python3 -m backend.scripts.org3_replace_scans_from_batch --apply --batch-id 1631
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG_ID = 3
DEFAULT_BATCH_ID = 1631


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace org-3 persistent scans from confirmed batch export"
    )
    parser.add_argument(
        "--batch-id",
        type=int,
        default=DEFAULT_BATCH_ID,
        help=f"Confirmed batch (default: {DEFAULT_BATCH_ID})",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("Specify exactly one of --dry-run or --apply")

    cmd = [
        sys.executable,
        "-m",
        "backend.scripts.replace_persistent_scans_from_batch",
        "--org",
        str(ORG_ID),
        "--batch-id",
        str(int(args.batch_id)),
        "--dry-run" if args.dry_run else "--apply",
    ]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
