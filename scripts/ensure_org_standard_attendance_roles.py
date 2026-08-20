#!/usr/bin/env python3
"""Ensure attendance STANDARD_ROLES (Operator/Sort/Folder) exist for an org.

Usage:
  python scripts/ensure_org_standard_attendance_roles.py --org 3
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
from backend.shift_job_tracking import (  # noqa: E402
    STANDARD_ROLE_CODES,
    list_active_selection_tree,
    seed_default_categories_and_roles,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, required=True)
    args = parser.parse_args()
    oid = int(args.org)

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        seed_default_categories_and_roles(cur, oid)
        conn.commit()
        tree = list_active_selection_tree(cur, oid)
        report = {
            "organization_id": oid,
            "standard_role_codes": list(STANDARD_ROLE_CODES),
            "categories": [
                {
                    "id": c.get("id"),
                    "code": c.get("code"),
                    "name": c.get("name"),
                    "roles": [
                        {
                            "role_id": r.get("role_id"),
                            "role_code": r.get("role_code"),
                            "role_name": r.get("role_name"),
                        }
                        for r in (c.get("roles") or [])
                    ],
                }
                for c in tree
            ],
        }
        print(json.dumps(report, indent=2, default=str))
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
