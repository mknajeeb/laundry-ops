"""Per-tenant folding users excluded from leaderboard / TV scoring."""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists


def ensure_rinse_folding_excluded_users_table(cursor) -> None:
    if table_exists(cursor, "rinse_folding_excluded_users"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_folding_excluded_users (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT UNSIGNED NOT NULL,
          user_name VARCHAR(255) NULL,
          employee_id VARCHAR(64) NULL,
          reason VARCHAR(512) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_user_id INT UNSIGNED NULL,
          UNIQUE KEY uq_rfeu_org_user (organization_id, user_name),
          KEY idx_rfeu_org_emp (organization_id, employee_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def list_excluded_folding_users(cursor, organization_id: int) -> list[dict[str, Any]]:
    ensure_rinse_folding_excluded_users_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, user_name, employee_id, reason, created_at
        FROM rinse_folding_excluded_users
        WHERE organization_id = %s
        ORDER BY user_name ASC
        """,
        (int(organization_id),),
    )
    return list(cursor.fetchall() or [])


def excluded_user_names_set(cursor, organization_id: int) -> set[str]:
    rows = list_excluded_folding_users(cursor, organization_id)
    return {
        str(r.get("user_name") or "").strip()
        for r in rows
        if isinstance(r, dict) and str(r.get("user_name") or "").strip()
    }


def is_user_excluded_from_scoring(
    cursor, organization_id: int, user_name: str | None
) -> bool:
    uname = str(user_name or "").strip()
    if not uname:
        return False
    return uname in excluded_user_names_set(cursor, organization_id)


def sql_exclude_scoring_users_clause(
    cursor, organization_id: int, *, user_column: str = "p.assigned_user_name"
) -> tuple[str, list[Any]]:
    """
    Returns SQL fragment AND ... plus bind args for leaderboard queries.
    """
    if not table_exists(cursor, "rinse_folding_excluded_users"):
        return "", []
    org = int(organization_id)
    return (
        f"""
        AND NOT EXISTS (
          SELECT 1 FROM rinse_folding_excluded_users ex
          WHERE ex.organization_id = %s
            AND ex.user_name IS NOT NULL
            AND TRIM(ex.user_name) != ''
            AND ex.user_name = {user_column}
        )
        """,
        [org],
    )
