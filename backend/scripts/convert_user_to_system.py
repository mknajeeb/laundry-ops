#!/usr/bin/env python3
"""
Convert an existing login to a People "System user (not on payroll)".

Assigns the SYSTEM role, EC_SYSTEM employment category, and strips schedule
worker rows while keeping payroll_profiles so the person still appears in People.

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.convert_user_to_system --username veetest --org-id 3
  python3 -m backend.scripts.convert_user_to_system --username veetest --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a user to system-only (not on payroll)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--org-id", type=int, default=3)
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--drop-profile",
        action="store_true",
        help="Also delete payroll_profiles (hides from People TA list)",
    )
    args = parser.parse_args()

    from backend.db import get_db
    from backend.portal_system_users import convert_user_to_system_only, is_portal_system_user

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, username, display_name, organization_id, active
            FROM users
            WHERE organization_id = %s AND LOWER(username) = LOWER(%s)
            LIMIT 1
            """,
            (int(args.org_id), args.username),
        )
        user = cursor.fetchone()
        if not user:
            print(
                f"User username={args.username!r} not found in organization_id={args.org_id}",
                file=sys.stderr,
            )
            return 1

        uid = int(user["id"])
        already = is_portal_system_user(conn, uid)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "user": user,
                        "already_system": already,
                        "would_keep_profile": not args.drop_profile,
                    },
                    default=str,
                    indent=2,
                )
            )
            return 0

        result = convert_user_to_system_only(
            cursor,
            user_id=uid,
            organization_id=int(user["organization_id"]),
            keep_profile=not args.drop_profile,
        )
        conn.commit()
        print(json.dumps({"ok": True, "user": user, **result}, default=str, indent=2))
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
