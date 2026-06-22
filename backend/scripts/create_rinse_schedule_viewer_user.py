#!/usr/bin/env python3
"""
Create or update the Rinse schedule viewer login (RINSE role, org 3 VeeWash by default).

Usage (from repo root, with .env loaded):
  python3 -m backend.scripts.create_rinse_schedule_viewer_user
  python3 -m backend.scripts.create_rinse_schedule_viewer_user --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ORG_ID = 3
DEFAULT_USERNAME = "jordan@rinse.com"
DEFAULT_DISPLAY_NAME = "Jordan Allen"
DEFAULT_PASSWORD = "VeeWash123"
DEFAULT_ROLE = "RINSE"


def ensure_rinse_role(cursor) -> int:
    cursor.execute(
        """
        SELECT id FROM roles
        WHERE UPPER(TRIM(code)) = %s
        ORDER BY (CASE WHEN organization_id = 0 OR organization_id IS NULL THEN 0 ELSE 1 END), id
        LIMIT 1
        """,
        (DEFAULT_ROLE,),
    )
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])

    cursor.execute(
        """
        INSERT INTO roles (code, name, organization_id, is_system)
        VALUES (%s, %s, 0, 1)
        """,
        (DEFAULT_ROLE, "Rinse schedule viewer"),
    )
    return int(cursor.lastrowid)


def resolve_user(cursor, organization_id: int, username: str) -> dict | None:
    cursor.execute(
        """
        SELECT id, username, display_name, active, organization_id
        FROM users
        WHERE organization_id = %s AND LOWER(username) = LOWER(%s)
        LIMIT 1
        """,
        (int(organization_id), username),
    )
    return cursor.fetchone()


def assign_role(cursor, user_id: int, role_id: int) -> None:
    cursor.execute(
        "SELECT 1 FROM user_roles WHERE user_id = %s AND role_id = %s LIMIT 1",
        (int(user_id), int(role_id)),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
        (int(user_id), int(role_id)),
    )


def strip_payroll_worker_rows(cursor, user_id: int) -> None:
    """Portal system logins must not appear as W-2 employees or schedule workers."""
    uid = int(user_id)
    cursor.execute("DELETE FROM payroll_profiles WHERE user_id = %s", (uid,))
    cursor.execute(
        "DELETE FROM payroll_worker_profiles WHERE user_id = %s",
        (uid,),
    )
    cursor.execute(
        "DELETE FROM user_employment_categories WHERE user_id = %s",
        (uid,),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Rinse schedule viewer user")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--display-name", default=DEFAULT_DISPLAY_NAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    from backend.db import get_db

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, slug, display_name FROM organizations WHERE id = %s LIMIT 1",
            (int(args.org_id),),
        )
        org = cursor.fetchone()
        if not org:
            print(f"Organization id={args.org_id} not found", file=sys.stderr)
            return 1

        role_id = ensure_rinse_role(cursor)
        password_hash = generate_password_hash(args.password)
        existing = resolve_user(cursor, args.org_id, args.username)

        if args.dry_run:
            action = "update" if existing else "create"
            print(
                f"[dry-run] Would {action} user username={args.username!r} "
                f"display_name={args.display_name!r} org={org.get('slug')} role={DEFAULT_ROLE}"
            )
            return 0

        if existing:
            user_id = int(existing["id"])
            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    display_name = %s,
                    active = 1,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (password_hash, args.display_name, user_id),
            )
            action = "updated"
        else:
            cursor.execute(
                """
                INSERT INTO users
                (organization_id, username, password_hash, display_name, active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 1, NOW(), NOW())
                """,
                (int(args.org_id), args.username, password_hash, args.display_name),
            )
            user_id = int(cursor.lastrowid)
            action = "created"

        assign_role(cursor, user_id, role_id)
        strip_payroll_worker_rows(cursor, user_id)
        conn.commit()

        print(
            f"{action.capitalize()} user id={user_id} username={args.username!r} "
            f"display_name={args.display_name!r} org={org.get('slug')} role={DEFAULT_ROLE}"
        )
        print(f"Login URL: /login/{org.get('slug')}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
