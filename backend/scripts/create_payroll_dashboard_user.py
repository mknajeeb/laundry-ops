#!/usr/bin/env python3
"""
Create or update a Payroll Dashboard–only portal login (no employee-level access).

Password is read ONLY from PAYROLL_DASHBOARD_PASSWORD, hashed with werkzeug
(same as all other users), and never printed. After create/update a one-time
password-reset token is always issued so the shared/temp password is not a
permanent credential — complete reset via /auth/password-reset/complete.

Usage (from repo root, with .env loaded):
  PAYROLL_DASHBOARD_PASSWORD='…' python3 -m backend.scripts.create_payroll_dashboard_user --org-id 3
  PAYROLL_DASHBOARD_PASSWORD='…' PAYROLL_DASHBOARD_EMIT_RESET_TOKEN=1 \\
    python3 -m backend.scripts.create_payroll_dashboard_user --org-id 3
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ORG_ID = 3
DEFAULT_USERNAME = "blake.rinse@veewash.com"
DEFAULT_FIRST_NAME = "Blake"
DEFAULT_LAST_NAME = "Rinse"
DEFAULT_ROLE = "PAYROLL_ANALYTICS"

# Dashboard summary only — no users.view / payroll.update / finance.payments.
DASHBOARD_PERMISSION_KEYS = (
    "payroll.view",
    "payroll.analytics.view",
)


def display_name(first_name: str, last_name: str) -> str:
    return f"{first_name.strip()} {last_name.strip()}".strip()


def ensure_permission(cursor, perm_key: str, description: str) -> int:
    cursor.execute("SELECT id FROM permissions WHERE perm_key = %s LIMIT 1", (perm_key,))
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])
    cursor.execute(
        "INSERT INTO permissions (perm_key, description) VALUES (%s, %s)",
        (perm_key, description),
    )
    return int(cursor.lastrowid)


def ensure_role(cursor) -> int:
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
        (DEFAULT_ROLE, "Payroll Analytics Dashboard"),
    )
    return int(cursor.lastrowid)


def sync_permissions(cursor, role_id: int) -> None:
    ensure_permission(cursor, "payroll.view", "Open payroll management workspace")
    ensure_permission(
        cursor,
        "payroll.analytics.view",
        "View payroll analytics dashboard & summary exports (read-only)",
    )
    perm_ids: list[int] = []
    for perm_key in DASHBOARD_PERMISSION_KEYS:
        cursor.execute("SELECT id FROM permissions WHERE perm_key = %s LIMIT 1", (perm_key,))
        prow = cursor.fetchone()
        if not prow:
            continue
        perm_ids.append(int(prow["id"] if isinstance(prow, dict) else prow[0]))

    cursor.execute("DELETE FROM role_permissions WHERE role_id = %s", (int(role_id),))
    for perm_id in perm_ids:
        cursor.execute(
            "INSERT INTO role_permissions (role_id, permission_id) VALUES (%s, %s)",
            (int(role_id), int(perm_id)),
        )


def resolve_user(cursor, organization_id: int, username: str):
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
    cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (int(user_id),))
    cursor.execute(
        "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
        (int(user_id), int(role_id)),
    )
    try:
        cursor.execute("UPDATE users SET role_id = %s WHERE id = %s", (int(role_id), int(user_id)))
    except Exception:
        pass


def strip_payroll_worker_rows(cursor, user_id: int) -> None:
    uid = int(user_id)
    for table in (
        "payroll_profiles",
        "payroll_worker_profiles",
        "user_employment_categories",
    ):
        try:
            cursor.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid,))
        except Exception:
            pass


def ensure_password_reset_tokens_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          token_hash CHAR(64) NOT NULL,
          expires_at DATETIME NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          consumed_at DATETIME NULL,
          INDEX idx_lookup (token_hash, expires_at),
          INDEX idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def issue_password_reset_token(cursor, user_id: int) -> tuple[str, datetime]:
    """Return (raw_token, expires_at). Raw token is never logged by callers unless emit flag."""
    ensure_password_reset_tokens_table(cursor)
    raw = secrets.token_urlsafe(32)
    th = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    exp = datetime.utcnow() + timedelta(hours=1)
    cursor.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
        """,
        (int(user_id), th, exp),
    )
    return raw, exp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Payroll Dashboard–only user (hashed password, no employee detail)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--first-name", default=DEFAULT_FIRST_NAME)
    parser.add_argument("--last-name", default=DEFAULT_LAST_NAME)
    args = parser.parse_args()

    password = os.environ.get("PAYROLL_DASHBOARD_PASSWORD") or ""
    if not password:
        print(
            "Password required via PAYROLL_DASHBOARD_PASSWORD only "
            "(do not pass passwords on the CLI or commit them).",
            file=sys.stderr,
        )
        return 2

    emit_reset = os.environ.get("PAYROLL_DASHBOARD_EMIT_RESET_TOKEN", "").lower() in (
        "1",
        "true",
        "yes",
    )

    name = display_name(args.first_name, args.last_name)
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

        role_id = ensure_role(cursor)
        sync_permissions(cursor, role_id)
        password_hash = generate_password_hash(password)
        existing = resolve_user(cursor, args.org_id, args.username)

        if args.dry_run:
            action = "update" if existing else "create"
            print(
                f"[dry-run] Would {action} user username={args.username!r} "
                f"display_name={name!r} org={org.get('slug')} role={DEFAULT_ROLE}"
            )
            print(f"[dry-run] Permissions: {', '.join(DASHBOARD_PERMISSION_KEYS)}")
            print("[dry-run] password_reset_required=true (token not created in dry-run)")
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
                (password_hash, name, user_id),
            )
            action = "updated"
        else:
            cursor.execute(
                """
                INSERT INTO users
                (organization_id, username, password_hash, display_name, active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 1, NOW(), NOW())
                """,
                (int(args.org_id), args.username, password_hash, name),
            )
            user_id = int(cursor.lastrowid)
            action = "created"

        assign_role(cursor, user_id, role_id)
        strip_payroll_worker_rows(cursor, user_id)
        raw_token, exp = issue_password_reset_token(cursor, user_id)
        conn.commit()

        print(
            f"{action} user id={user_id} username={args.username!r} "
            f"role={DEFAULT_ROLE} perms={','.join(DASHBOARD_PERMISSION_KEYS)}"
        )
        print(f"Login URL: /login/{org.get('slug')}")
        print("password_reset_required=true")
        print(
            "Complete password change via POST /auth/password-reset/complete "
            f"(token expires_at={exp.isoformat()}Z)."
        )
        if emit_reset:
            print(f"reset_token={raw_token}")
        else:
            print(
                "reset_token omitted "
                "(set PAYROLL_DASHBOARD_EMIT_RESET_TOKEN=1 to print one-time token)."
            )
        return 0
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
