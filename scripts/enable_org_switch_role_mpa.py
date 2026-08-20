#!/usr/bin/env python3
"""Enable Mobile PIN Access switch_role for all active users in an org.

Usage:
  python scripts/enable_org_switch_role_mpa.py --org 3 --dry-run
  python scripts/enable_org_switch_role_mpa.py --org 3 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import get_db  # noqa: E402
from backend.employee_mobile_pin_access import (  # noqa: E402
    enable_switch_role_for_org_active_users,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_db()
    try:
        report = enable_switch_role_for_org_active_users(
            conn,
            int(args.org),
            dry_run=bool(args.dry_run),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
