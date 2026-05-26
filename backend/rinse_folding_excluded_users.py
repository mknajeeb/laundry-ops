"""Per-tenant folding users excluded from leaderboard / TV scoring."""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists, table_has_column


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


def list_folding_user_options(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Users for dropdowns: performance, exceptions, scan-only, excluded."""
    org = int(organization_id)
    excluded = excluded_user_names_set(cursor, org)
    seen: dict[str, dict[str, Any]] = {}

    def add(name: str, *, source: str, has_exception: bool = False, has_calculated: bool = False) -> None:
        n = str(name or "").strip()
        if not n:
            return
        row = seen.get(n)
        if not row:
            row = {
                "user_name": n,
                "label": f"{n}{' (excluded)' if n in excluded else ''}",
                "excluded_from_scoring": n in excluded,
                "sources": [],
                "has_exception": False,
                "has_calculated": False,
            }
            seen[n] = row
        if source not in row["sources"]:
            row["sources"].append(source)
        row["has_exception"] = row["has_exception"] or has_exception
        row["has_calculated"] = row["has_calculated"] or has_calculated

    if table_exists(cursor, "rinse_folding_performance"):
        cursor.execute(
            """
            SELECT TRIM(assigned_user_name) AS user_name,
                   UPPER(COALESCE(status,'')) AS st,
                   COUNT(*) AS cnt
            FROM rinse_folding_performance
            WHERE organization_id = %s
              AND assigned_user_name IS NOT NULL AND TRIM(assigned_user_name) != ''
            GROUP BY assigned_user_name, status
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            if not isinstance(r, dict):
                continue
            un = str(r.get("user_name") or "").strip()
            st = str(r.get("st") or "").upper()
            add(un, source="performance", has_exception=st == "EXCEPTION", has_calculated=st == "CALCULATED")

    if table_exists(cursor, "rinse_bag_scan_events") and table_has_column(
        cursor, "rinse_bag_scan_events", "user_name"
    ):
        cursor.execute(
            """
            SELECT DISTINCT TRIM(user_name) AS user_name
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND user_name IS NOT NULL AND TRIM(user_name) != ''
            ORDER BY user_name
            LIMIT 500
            """,
            (org,),
        )
        for r in cursor.fetchall() or []:
            un = str(r.get("user_name") if isinstance(r, dict) else r[0] or "").strip()
            add(un, source="scan_events")

    out = sorted(seen.values(), key=lambda x: str(x.get("user_name") or "").lower())
    return out


def list_distinct_folding_user_names(cursor, organization_id: int) -> list[str]:
    """Users seen in folding performance (for maintenance dropdown)."""
    if not table_exists(cursor, "rinse_folding_performance"):
        return []
    org = int(organization_id)
    cursor.execute(
        """
        SELECT DISTINCT TRIM(assigned_user_name) AS user_name
        FROM rinse_folding_performance
        WHERE organization_id = %s
          AND assigned_user_name IS NOT NULL
          AND TRIM(assigned_user_name) != ''
        ORDER BY user_name ASC
        """,
        (org,),
    )
    names: list[str] = []
    for r in cursor.fetchall() or []:
        n = str(r.get("user_name") if isinstance(r, dict) else r[0] or "").strip()
        if n:
            names.append(n)
    return names


def remove_excluded_folding_user(
    cursor,
    organization_id: int,
    *,
    user_name: str | None = None,
    row_id: int | None = None,
) -> int:
    ensure_rinse_folding_excluded_users_table(cursor)
    org = int(organization_id)
    if row_id is not None:
        cursor.execute(
            "DELETE FROM rinse_folding_excluded_users WHERE organization_id = %s AND id = %s",
            (org, int(row_id)),
        )
        return cursor.rowcount
    uname = str(user_name or "").strip()
    if not uname:
        return 0
    cursor.execute(
        "DELETE FROM rinse_folding_excluded_users WHERE organization_id = %s AND user_name = %s",
        (org, uname),
    )
    return cursor.rowcount


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
