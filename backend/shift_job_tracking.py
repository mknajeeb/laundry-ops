"""Shift task tracking — Category + Role history during attendance shifts.

Phase 1: capture accurate category/role segments for the future Employee
Performance Dashboard. No productivity or payroll calculations here.
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from backend.payroll_identity import eastern_now_naive
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column

DEFAULT_CATEGORIES = (
    ("RINSE_WF", "Rinse WF"),
    ("RINSE_HD", "Rinse HD"),
    ("DHS", "DHS"),
    ("DROP_OFF", "Drop Off"),
)

# Attendance roles persisted on shift_job_segments (distinct role_id / role_code).
# Employee-facing labels map Operator→Wash-Dry, Sort→Sort, Folder→Fold.
STANDARD_ROLES = (
    ("OPERATOR", "Operator"),
    ("SORT", "Sort"),
    ("FOLDER", "Folder"),
)
STANDARD_ROLE_CODES = tuple(code for code, _ in STANDARD_ROLES)

# Legacy alias used by older tests / imports
DEFAULT_TASKS = tuple(f"{name} — {role}" for _, name in DEFAULT_CATEGORIES for _, role in STANDARD_ROLES)
DEFAULT_JOB_NAMES = DEFAULT_TASKS

CHECKOUT_TYPES = (
    "manual",
    "force_scheduled",
    "force_admin",
    "auto_max_hours",
    "auto_midnight",
)

_SESSION_COLS = (
    ("scheduled_end_at", "DATETIME NULL"),
    ("force_checkout_at", "DATETIME NULL"),
    ("force_checkout_waived", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("force_checked_out_at", "DATETIME NULL"),
    ("checkout_type", "VARCHAR(32) NULL"),
    ("continuation_allowed", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("continued_after_force_at", "DATETIME NULL"),
    ("current_job_name_id", "INT NULL"),
    ("current_category_id", "INT NULL"),
    ("current_role_id", "INT NULL"),
    ("current_category_role_id", "INT NULL"),
)

_SEGMENT_COLS = (
    ("user_id", "INT NULL"),
    ("category_id", "INT NULL"),
    ("role_id", "INT NULL"),
    ("category_role_id", "INT NULL"),
    ("category_code", "VARCHAR(64) NULL"),
    ("role_code", "VARCHAR(64) NULL"),
    ("category_name_snapshot", "VARCHAR(128) NULL"),
    ("role_name_snapshot", "VARCHAR(128) NULL"),
    ("change_source", "VARCHAR(64) NULL"),
    ("close_source", "VARCHAR(64) NULL"),
    ("idempotency_key", "VARCHAR(64) NULL"),
)

# Process-local gate: avoid re-running DDL (especially ALTER) on every request.
# Unconditional MODIFY COLUMN under load can wait on metadata locks for minutes.
_SCHEMA_ENSURED = False
_SCHEMA_ENSURE_LOCK = threading.Lock()


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")[:19])
    except Exception:
        return None


def _combine_date_time(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)


def _scalar(row) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _slug_code(name: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip().upper()).strip("_")
    return raw[:64] or "CATEGORY"


def _add_column_if_missing(cursor, table: str, column: str, ddl: str) -> bool:
    """Return True when a column was added."""
    if not table_exists(cursor, table):
        return False
    if table_has_column(cursor, table, column):
        return False
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except Exception as exc:
        if getattr(exc, "args", (None,))[0] != 1060:
            raise
        return False
    invalidate_schema_cache()
    return True


def _column_is_not_null(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table, column),
    )
    row = cursor.fetchone()
    if not row:
        return False
    val = row.get("IS_NULLABLE") if isinstance(row, dict) else row[0]
    return str(val or "").upper() == "NO"


def _add_index_if_missing(cursor, table: str, index_name: str, create_sql: str) -> bool:
    if not table_exists(cursor, table):
        return False
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table, index_name),
    )
    if cursor.fetchone():
        return False
    try:
        cursor.execute(create_sql)
    except Exception as exc:
        # 1061 duplicate key name
        if getattr(exc, "args", (None,))[0] != 1061:
            raise
        return False
    return True


def reset_shift_job_tracking_schema_gate_for_tests() -> None:
    """Test helper: allow ensure_shift_job_tracking_schema to run again."""
    global _SCHEMA_ENSURED
    with _SCHEMA_ENSURE_LOCK:
        _SCHEMA_ENSURED = False


def ensure_shift_job_tracking_schema(cursor) -> None:
    """Idempotent DDL. Safe to call often; runs at most once per process after success."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with _SCHEMA_ENSURE_LOCK:
        if _SCHEMA_ENSURED:
            return
        _ensure_shift_job_tracking_schema_unlocked(cursor)
        _SCHEMA_ENSURED = True


def _ensure_shift_job_tracking_schema_unlocked(cursor) -> None:
    changed = False
    if not table_exists(cursor, "ta_task_categories"):
        cursor.execute(
            """
            CREATE TABLE ta_task_categories (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              code VARCHAR(64) NOT NULL,
              name VARCHAR(128) NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ttc_org_code (organization_id, code),
              INDEX idx_ttc_org_active (organization_id, active, sort_order)
            ) ENGINE=InnoDB
            """
        )
        changed = True
    if not table_exists(cursor, "ta_task_roles"):
        cursor.execute(
            """
            CREATE TABLE ta_task_roles (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              code VARCHAR(64) NOT NULL,
              name VARCHAR(128) NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ttr_org_code (organization_id, code),
              INDEX idx_ttr_org_active (organization_id, active, sort_order)
            ) ENGINE=InnoDB
            """
        )
        changed = True
    if not table_exists(cursor, "ta_task_category_roles"):
        cursor.execute(
            """
            CREATE TABLE ta_task_category_roles (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              category_id INT NOT NULL,
              role_id INT NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ttcr_cat_role (category_id, role_id),
              INDEX idx_ttcr_org (organization_id, active, sort_order),
              CONSTRAINT fk_ttcr_category FOREIGN KEY (category_id)
                REFERENCES ta_task_categories(id),
              CONSTRAINT fk_ttcr_role FOREIGN KEY (role_id) REFERENCES ta_task_roles(id)
            ) ENGINE=InnoDB
            """
        )
        changed = True
    # Keep legacy flat table for any historical FKs; new orgs use category/role.
    if not table_exists(cursor, "ta_job_names"):
        cursor.execute(
            """
            CREATE TABLE ta_job_names (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              name VARCHAR(128) NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_tjn_org_name (organization_id, name)
            ) ENGINE=InnoDB
            """
        )
        changed = True
    if not table_exists(cursor, "shift_job_segments"):
        cursor.execute(
            """
            CREATE TABLE shift_job_segments (
              id INT AUTO_INCREMENT PRIMARY KEY,
              shift_session_id INT NOT NULL,
              user_id INT NULL,
              category_id INT NULL,
              role_id INT NULL,
              category_role_id INT NULL,
              category_code VARCHAR(64) NULL,
              role_code VARCHAR(64) NULL,
              category_name_snapshot VARCHAR(128) NULL,
              role_name_snapshot VARCHAR(128) NULL,
              job_name_id INT NULL,
              started_at DATETIME NOT NULL,
              ended_at DATETIME NULL,
              change_source VARCHAR(64) NULL,
              close_source VARCHAR(64) NULL,
              idempotency_key VARCHAR(64) NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_sjs_session (shift_session_id, started_at),
              UNIQUE KEY uq_sjs_session_idempotency (shift_session_id, idempotency_key),
              CONSTRAINT fk_sjs_session FOREIGN KEY (shift_session_id)
                REFERENCES shift_sessions(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )
        changed = True
    else:
        # Legacy table may have NOT NULL job_name_id — only MODIFY when required.
        # Unconditional MODIFY acquires metadata locks and can hang requests for minutes.
        if table_has_column(cursor, "shift_job_segments", "job_name_id") and _column_is_not_null(
            cursor, "shift_job_segments", "job_name_id"
        ):
            try:
                cursor.execute(
                    "ALTER TABLE shift_job_segments MODIFY COLUMN job_name_id INT NULL"
                )
                changed = True
            except Exception:
                pass
        for col, ddl in _SEGMENT_COLS:
            if _add_column_if_missing(cursor, "shift_job_segments", col, ddl):
                changed = True
        if _add_index_if_missing(
            cursor,
            "shift_job_segments",
            "uq_sjs_session_idempotency",
            "ALTER TABLE shift_job_segments "
            "ADD UNIQUE KEY uq_sjs_session_idempotency (shift_session_id, idempotency_key)",
        ):
            changed = True

    for col, ddl in _SESSION_COLS:
        if _add_column_if_missing(cursor, "shift_sessions", col, ddl):
            changed = True
    if _add_column_if_missing(
        cursor, "payroll_profiles", "force_checkout_waiver", "TINYINT(1) NOT NULL DEFAULT 0"
    ):
        changed = True
    if changed:
        invalidate_schema_cache()


def seed_default_categories_and_roles(cursor, organization_id: int) -> None:
    """Seed four categories + Operator/Folder, assign Operator/Folder to each category."""
    ensure_shift_job_tracking_schema(cursor)
    oid = int(organization_id)
    cursor.execute(
        "SELECT COUNT(*) FROM ta_task_categories WHERE organization_id=%s", (oid,)
    )
    if int(_scalar(cursor.fetchone()) or 0) > 0:
        # Still ensure standard roles exist and are assigned.
        _ensure_standard_roles(cursor, oid)
        _ensure_standard_assignments(cursor, oid)
        return

    for idx, (code, name) in enumerate(DEFAULT_CATEGORIES):
        cursor.execute(
            """
            INSERT INTO ta_task_categories (organization_id, code, name, sort_order, active)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (oid, code, name, idx),
        )
    _ensure_standard_roles(cursor, oid)
    _ensure_standard_assignments(cursor, oid)


# Alias for older call sites
def seed_default_job_names(cursor, organization_id: int) -> None:
    seed_default_categories_and_roles(cursor, organization_id)


def _ensure_standard_roles(cursor, organization_id: int) -> dict[str, int]:
    oid = int(organization_id)
    role_ids: dict[str, int] = {}
    for idx, (code, name) in enumerate(STANDARD_ROLES):
        cursor.execute(
            """
            SELECT id FROM ta_task_roles
            WHERE organization_id=%s AND code=%s LIMIT 1
            """,
            (oid, code),
        )
        row = cursor.fetchone()
        if row:
            rid = int(row["id"] if isinstance(row, dict) else row[0])
            role_ids[code] = rid
            cursor.execute(
                """
                UPDATE ta_task_roles
                SET name=%s, sort_order=%s, active=1
                WHERE id=%s AND organization_id=%s
                """,
                (name, idx, rid, oid),
            )
            continue
        cursor.execute(
            """
            INSERT INTO ta_task_roles (organization_id, code, name, sort_order, active)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (oid, code, name, idx),
        )
        role_ids[code] = int(cursor.lastrowid)
    return role_ids


def _ensure_standard_assignments(cursor, organization_id: int) -> None:
    oid = int(organization_id)
    role_ids = _ensure_standard_roles(cursor, oid)
    cursor.execute(
        "SELECT id FROM ta_task_categories WHERE organization_id=%s ORDER BY sort_order, id",
        (oid,),
    )
    cats = cursor.fetchall() or []
    for cat in cats:
        cat_id = int(cat["id"] if isinstance(cat, dict) else cat[0])
        for sort_idx, code in enumerate(STANDARD_ROLE_CODES):
            role_id = role_ids.get(code)
            if not role_id:
                continue
            cursor.execute(
                """
                SELECT id FROM ta_task_category_roles
                WHERE category_id=%s AND role_id=%s LIMIT 1
                """,
                (cat_id, role_id),
            )
            existing = cursor.fetchone()
            if existing:
                asg_id = int(existing["id"] if isinstance(existing, dict) else existing[0])
                cursor.execute(
                    """
                    UPDATE ta_task_category_roles
                    SET sort_order=%s, active=1
                    WHERE id=%s AND organization_id=%s
                    """,
                    (sort_idx, asg_id, oid),
                )
                continue
            cursor.execute(
                """
                INSERT INTO ta_task_category_roles
                  (organization_id, category_id, role_id, sort_order, active)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (oid, cat_id, role_id, sort_idx),
            )


# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------


def list_categories(
    cursor, organization_id: int, *, include_inactive: bool = False, include_usage: bool = False
) -> list[dict]:
    ensure_shift_job_tracking_schema(cursor)
    seed_default_categories_and_roles(cursor, organization_id)
    q = """
        SELECT id, organization_id, code, name, sort_order, active, created_at, updated_at
        FROM ta_task_categories
        WHERE organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if not include_inactive:
        q += " AND active=1"
    q += " ORDER BY sort_order ASC, name ASC"
    cursor.execute(q, params)
    rows = [json_safe(r) for r in (cursor.fetchall() or [])]
    if include_usage:
        for row in rows:
            count = category_usage_count(cursor, int(row["id"]))
            row["usage_count"] = count
            row["can_delete"] = count == 0
    return rows


def get_category(cursor, organization_id: int, category_id: int) -> Optional[dict]:
    ensure_shift_job_tracking_schema(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, code, name, sort_order, active
        FROM ta_task_categories
        WHERE id=%s AND organization_id=%s
        """,
        (int(category_id), int(organization_id)),
    )
    row = cursor.fetchone()
    return json_safe(row) if row else None


def create_category(
    cursor, organization_id: int, name: str, *, code: Optional[str] = None, active: bool = True
) -> dict:
    ensure_shift_job_tracking_schema(cursor)
    oid = int(organization_id)
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name is required")
    code = (code or _slug_code(name)).strip().upper()
    if not code:
        raise ValueError("Category code is required")
    cursor.execute(
        "SELECT id FROM ta_task_categories WHERE organization_id=%s AND code=%s",
        (oid, code),
    )
    if cursor.fetchone():
        raise ValueError(f"Category code '{code}' already exists")
    cursor.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM ta_task_categories WHERE organization_id=%s",
        (oid,),
    )
    sort_order = int(_scalar(cursor.fetchone()) or 0)
    cursor.execute(
        """
        INSERT INTO ta_task_categories (organization_id, code, name, sort_order, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (oid, code, name, sort_order, 1 if active else 0),
    )
    cat_id = int(cursor.lastrowid)
    # Auto-assign Operator + Sort + Folder (same set as STANDARD_ROLES)
    role_ids = _ensure_standard_roles(cursor, oid)
    for idx, role_code in enumerate(STANDARD_ROLE_CODES):
        rid = role_ids.get(role_code)
        if not rid:
            continue
        cursor.execute(
            """
            INSERT INTO ta_task_category_roles
              (organization_id, category_id, role_id, sort_order, active)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (oid, cat_id, rid, idx),
        )
    return get_category(cursor, oid, cat_id) or {"id": cat_id, "code": code, "name": name}


def update_category(
    cursor,
    organization_id: int,
    category_id: int,
    *,
    name: Optional[str] = None,
    active: Optional[bool] = None,
) -> dict:
    existing = get_category(cursor, organization_id, category_id)
    if not existing:
        raise ValueError("Category not found")
    fields = []
    vals: list[Any] = []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Category name is required")
        fields.append("name=%s")
        vals.append(name)
    if active is not None:
        fields.append("active=%s")
        vals.append(1 if active else 0)
    if not fields:
        return existing
    vals.extend([int(category_id), int(organization_id)])
    cursor.execute(
        f"UPDATE ta_task_categories SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
        vals,
    )
    return get_category(cursor, organization_id, category_id) or existing


def reorder_categories(cursor, organization_id: int, ordered_ids: list[int]) -> list[dict]:
    for idx, cid in enumerate(ordered_ids):
        cursor.execute(
            """
            UPDATE ta_task_categories SET sort_order=%s
            WHERE id=%s AND organization_id=%s
            """,
            (idx, int(cid), int(organization_id)),
        )
    return list_categories(cursor, organization_id, include_inactive=True)


def category_usage_count(cursor, category_id: int) -> int:
    if not table_exists(cursor, "shift_job_segments"):
        return 0
    if not table_has_column(cursor, "shift_job_segments", "category_id"):
        return 0
    cursor.execute(
        "SELECT COUNT(*) FROM shift_job_segments WHERE category_id=%s",
        (int(category_id),),
    )
    return int(_scalar(cursor.fetchone()) or 0)


def delete_category(cursor, organization_id: int, category_id: int) -> None:
    existing = get_category(cursor, organization_id, category_id)
    if not existing:
        raise ValueError("Category not found")
    if category_usage_count(cursor, category_id) > 0:
        raise ValueError(
            "Category has been used on a shift and cannot be deleted. Deactivate it instead."
        )
    cursor.execute(
        "DELETE FROM ta_task_category_roles WHERE category_id=%s AND organization_id=%s",
        (int(category_id), int(organization_id)),
    )
    cursor.execute(
        "DELETE FROM ta_task_categories WHERE id=%s AND organization_id=%s",
        (int(category_id), int(organization_id)),
    )


# ---------------------------------------------------------------------------
# Role CRUD
# ---------------------------------------------------------------------------


def list_roles(
    cursor, organization_id: int, *, include_inactive: bool = False, include_usage: bool = False
) -> list[dict]:
    ensure_shift_job_tracking_schema(cursor)
    seed_default_categories_and_roles(cursor, organization_id)
    q = """
        SELECT id, organization_id, code, name, sort_order, active, created_at, updated_at
        FROM ta_task_roles
        WHERE organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if not include_inactive:
        q += " AND active=1"
    q += " ORDER BY sort_order ASC, name ASC"
    cursor.execute(q, params)
    rows = [json_safe(r) for r in (cursor.fetchall() or [])]
    if include_usage:
        for row in rows:
            count = role_usage_count(cursor, int(row["id"]))
            row["usage_count"] = count
            row["can_delete"] = count == 0
    return rows


def get_role(cursor, organization_id: int, role_id: int) -> Optional[dict]:
    cursor.execute(
        """
        SELECT id, organization_id, code, name, sort_order, active
        FROM ta_task_roles
        WHERE id=%s AND organization_id=%s
        """,
        (int(role_id), int(organization_id)),
    )
    row = cursor.fetchone()
    return json_safe(row) if row else None


def create_role(
    cursor, organization_id: int, name: str, *, code: Optional[str] = None, active: bool = True
) -> dict:
    ensure_shift_job_tracking_schema(cursor)
    oid = int(organization_id)
    name = (name or "").strip()
    if not name:
        raise ValueError("Role name is required")
    code = (code or _slug_code(name)).strip().upper()
    if not code:
        raise ValueError("Role code is required")
    cursor.execute(
        "SELECT id FROM ta_task_roles WHERE organization_id=%s AND code=%s",
        (oid, code),
    )
    if cursor.fetchone():
        raise ValueError(f"Role code '{code}' already exists")
    cursor.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM ta_task_roles WHERE organization_id=%s",
        (oid,),
    )
    sort_order = int(_scalar(cursor.fetchone()) or 0)
    cursor.execute(
        """
        INSERT INTO ta_task_roles (organization_id, code, name, sort_order, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (oid, code, name, sort_order, 1 if active else 0),
    )
    return get_role(cursor, oid, int(cursor.lastrowid)) or {"code": code, "name": name}


def update_role(
    cursor,
    organization_id: int,
    role_id: int,
    *,
    name: Optional[str] = None,
    active: Optional[bool] = None,
) -> dict:
    existing = get_role(cursor, organization_id, role_id)
    if not existing:
        raise ValueError("Role not found")
    fields = []
    vals: list[Any] = []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Role name is required")
        fields.append("name=%s")
        vals.append(name)
    if active is not None:
        fields.append("active=%s")
        vals.append(1 if active else 0)
    if not fields:
        return existing
    vals.extend([int(role_id), int(organization_id)])
    cursor.execute(
        f"UPDATE ta_task_roles SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
        vals,
    )
    return get_role(cursor, organization_id, role_id) or existing


def reorder_roles(cursor, organization_id: int, ordered_ids: list[int]) -> list[dict]:
    for idx, rid in enumerate(ordered_ids):
        cursor.execute(
            """
            UPDATE ta_task_roles SET sort_order=%s
            WHERE id=%s AND organization_id=%s
            """,
            (idx, int(rid), int(organization_id)),
        )
    return list_roles(cursor, organization_id, include_inactive=True)


def role_usage_count(cursor, role_id: int) -> int:
    if not table_exists(cursor, "shift_job_segments"):
        return 0
    if not table_has_column(cursor, "shift_job_segments", "role_id"):
        return 0
    cursor.execute(
        "SELECT COUNT(*) FROM shift_job_segments WHERE role_id=%s",
        (int(role_id),),
    )
    return int(_scalar(cursor.fetchone()) or 0)


def delete_role(cursor, organization_id: int, role_id: int) -> None:
    existing = get_role(cursor, organization_id, role_id)
    if not existing:
        raise ValueError("Role not found")
    if role_usage_count(cursor, role_id) > 0:
        raise ValueError(
            "Role has been used on a shift and cannot be deleted. Deactivate it instead."
        )
    cursor.execute(
        "DELETE FROM ta_task_category_roles WHERE role_id=%s AND organization_id=%s",
        (int(role_id), int(organization_id)),
    )
    cursor.execute(
        "DELETE FROM ta_task_roles WHERE id=%s AND organization_id=%s",
        (int(role_id), int(organization_id)),
    )


# ---------------------------------------------------------------------------
# Category–role assignments
# ---------------------------------------------------------------------------


def list_category_roles(
    cursor,
    organization_id: int,
    category_id: int,
    *,
    include_inactive: bool = False,
) -> list[dict]:
    ensure_shift_job_tracking_schema(cursor)
    q = """
        SELECT cr.id, cr.organization_id, cr.category_id, cr.role_id,
               cr.sort_order, cr.active,
               c.code AS category_code, c.name AS category_name, c.active AS category_active,
               r.code AS role_code, r.name AS role_name, r.active AS role_active
        FROM ta_task_category_roles cr
        JOIN ta_task_categories c ON c.id = cr.category_id
        JOIN ta_task_roles r ON r.id = cr.role_id
        WHERE cr.organization_id=%s AND cr.category_id=%s
    """
    params: list[Any] = [int(organization_id), int(category_id)]
    if not include_inactive:
        q += " AND cr.active=1 AND c.active=1 AND r.active=1"
    q += " ORDER BY cr.sort_order ASC, r.name ASC"
    cursor.execute(q, params)
    rows = []
    for row in cursor.fetchall() or []:
        r = json_safe(row)
        r["display_label"] = f"{r.get('category_name')} — {r.get('role_name')}"
        rows.append(r)
    return rows


def list_active_selection_tree(cursor, organization_id: int) -> list[dict]:
    """
    Employee-facing tree: active categories with their active assigned roles.

    Read-only hot path for Role open — one JOIN query, no seed, no DDL.
    """
    oid = int(organization_id)
    if not table_exists(cursor, "ta_task_categories") or not table_exists(
        cursor, "ta_task_category_roles"
    ):
        return []
    if not table_exists(cursor, "ta_task_roles"):
        return []
    cursor.execute(
        """
        SELECT
          c.id AS category_id,
          c.organization_id,
          c.code AS category_code,
          c.name AS category_name,
          c.sort_order AS category_sort_order,
          c.active AS category_active,
          c.created_at AS category_created_at,
          c.updated_at AS category_updated_at,
          cr.id AS assignment_id,
          cr.role_id,
          cr.sort_order AS role_sort_order,
          cr.active AS assignment_active,
          r.code AS role_code,
          r.name AS role_name,
          r.active AS role_active
        FROM ta_task_categories c
        INNER JOIN ta_task_category_roles cr
          ON cr.category_id = c.id
         AND cr.organization_id = c.organization_id
         AND cr.active = 1
        INNER JOIN ta_task_roles r
          ON r.id = cr.role_id
         AND r.organization_id = c.organization_id
         AND r.active = 1
        WHERE c.organization_id = %s
          AND c.active = 1
        ORDER BY c.sort_order ASC, c.name ASC, cr.sort_order ASC, r.name ASC
        """,
        (oid,),
    )
    by_cat: dict[int, dict] = {}
    order: list[int] = []
    for row in cursor.fetchall() or []:
        r = json_safe(row)
        cat_id = int(r["category_id"])
        if cat_id not in by_cat:
            by_cat[cat_id] = {
                "id": cat_id,
                "organization_id": r.get("organization_id"),
                "code": r.get("category_code"),
                "name": r.get("category_name"),
                "sort_order": r.get("category_sort_order"),
                "active": r.get("category_active"),
                "created_at": r.get("category_created_at"),
                "updated_at": r.get("category_updated_at"),
                "roles": [],
            }
            order.append(cat_id)
        role = {
            "id": r.get("assignment_id"),
            "organization_id": r.get("organization_id"),
            "category_id": cat_id,
            "role_id": r.get("role_id"),
            "sort_order": r.get("role_sort_order"),
            "active": r.get("assignment_active"),
            "category_code": r.get("category_code"),
            "category_name": r.get("category_name"),
            "category_active": r.get("category_active"),
            "role_code": r.get("role_code"),
            "role_name": r.get("role_name"),
            "role_active": r.get("role_active"),
            "display_label": f"{r.get('category_name')} — {r.get('role_name')}",
        }
        by_cat[cat_id]["roles"].append(role)
    return [by_cat[cid] for cid in order]


def get_assignment(cursor, organization_id: int, assignment_id: int) -> Optional[dict]:
    cursor.execute(
        """
        SELECT cr.id, cr.organization_id, cr.category_id, cr.role_id,
               cr.sort_order, cr.active,
               c.code AS category_code, c.name AS category_name, c.active AS category_active,
               r.code AS role_code, r.name AS role_name, r.active AS role_active
        FROM ta_task_category_roles cr
        JOIN ta_task_categories c ON c.id = cr.category_id
        JOIN ta_task_roles r ON r.id = cr.role_id
        WHERE cr.id=%s AND cr.organization_id=%s
        """,
        (int(assignment_id), int(organization_id)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    r = json_safe(row)
    r["display_label"] = f"{r.get('category_name')} — {r.get('role_name')}"
    return r


def assign_role_to_category(
    cursor,
    organization_id: int,
    category_id: int,
    role_id: int,
    *,
    active: bool = True,
) -> dict:
    ensure_shift_job_tracking_schema(cursor)
    oid = int(organization_id)
    cat = get_category(cursor, oid, category_id)
    role = get_role(cursor, oid, role_id)
    if not cat:
        raise ValueError("Category not found")
    if not role:
        raise ValueError("Role not found")
    cursor.execute(
        """
        SELECT id FROM ta_task_category_roles
        WHERE category_id=%s AND role_id=%s LIMIT 1
        """,
        (int(category_id), int(role_id)),
    )
    existing = cursor.fetchone()
    if existing:
        aid = int(existing["id"] if isinstance(existing, dict) else existing[0])
        cursor.execute(
            "UPDATE ta_task_category_roles SET active=%s WHERE id=%s",
            (1 if active else 0, aid),
        )
        return get_assignment(cursor, oid, aid) or {}
    cursor.execute(
        """
        SELECT COALESCE(MAX(sort_order), -1) + 1 FROM ta_task_category_roles
        WHERE category_id=%s
        """,
        (int(category_id),),
    )
    sort_order = int(_scalar(cursor.fetchone()) or 0)
    cursor.execute(
        """
        INSERT INTO ta_task_category_roles
          (organization_id, category_id, role_id, sort_order, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (oid, int(category_id), int(role_id), sort_order, 1 if active else 0),
    )
    return get_assignment(cursor, oid, int(cursor.lastrowid)) or {}


def update_category_role_assignment(
    cursor,
    organization_id: int,
    assignment_id: int,
    *,
    active: Optional[bool] = None,
) -> dict:
    existing = get_assignment(cursor, organization_id, assignment_id)
    if not existing:
        raise ValueError("Assignment not found")
    if active is not None:
        cursor.execute(
            """
            UPDATE ta_task_category_roles SET active=%s
            WHERE id=%s AND organization_id=%s
            """,
            (1 if active else 0, int(assignment_id), int(organization_id)),
        )
    return get_assignment(cursor, organization_id, assignment_id) or existing


def reorder_category_roles(
    cursor, organization_id: int, category_id: int, ordered_ids: list[int]
) -> list[dict]:
    for idx, aid in enumerate(ordered_ids):
        cursor.execute(
            """
            UPDATE ta_task_category_roles SET sort_order=%s
            WHERE id=%s AND category_id=%s AND organization_id=%s
            """,
            (idx, int(aid), int(category_id), int(organization_id)),
        )
    return list_category_roles(cursor, organization_id, category_id, include_inactive=True)


def remove_category_role_assignment(cursor, organization_id: int, assignment_id: int) -> None:
    existing = get_assignment(cursor, organization_id, assignment_id)
    if not existing:
        raise ValueError("Assignment not found")
    cursor.execute(
        "SELECT COUNT(*) FROM shift_job_segments WHERE category_role_id=%s",
        (int(assignment_id),),
    )
    if int(_scalar(cursor.fetchone()) or 0) > 0:
        raise ValueError(
            "This category-role assignment has been used and cannot be deleted. Deactivate it instead."
        )
    cursor.execute(
        "DELETE FROM ta_task_category_roles WHERE id=%s AND organization_id=%s",
        (int(assignment_id), int(organization_id)),
    )


def resolve_active_assignment(
    cursor, organization_id: int, *, category_id: int, role_id: int
) -> dict:
    """Resolve and validate an active category+role selection for check-in/switch."""
    ensure_shift_job_tracking_schema(cursor)
    cursor.execute(
        """
        SELECT cr.id, cr.organization_id, cr.category_id, cr.role_id,
               cr.sort_order, cr.active,
               c.code AS category_code, c.name AS category_name, c.active AS category_active,
               r.code AS role_code, r.name AS role_name, r.active AS role_active
        FROM ta_task_category_roles cr
        JOIN ta_task_categories c ON c.id = cr.category_id
        JOIN ta_task_roles r ON r.id = cr.role_id
        WHERE cr.organization_id=%s AND cr.category_id=%s AND cr.role_id=%s
        LIMIT 1
        """,
        (int(organization_id), int(category_id), int(role_id)),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError("That role is not available under the selected category")
    r = json_safe(row)
    if not int(r.get("active") or 0):
        raise ValueError("That category-role assignment is inactive")
    if not int(r.get("category_active") or 0):
        raise ValueError("That category is inactive")
    if not int(r.get("role_active") or 0):
        raise ValueError("That role is inactive")
    r["display_label"] = f"{r.get('category_name')} — {r.get('role_name')}"
    return r


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def close_open_job_segment(
    conn,
    session_id: int,
    ended_at: Optional[datetime] = None,
    *,
    close_source: Optional[str] = None,
) -> None:
    c = conn.cursor()
    if not table_exists(c, "shift_job_segments"):
        return
    ended = ended_at or eastern_now_naive()
    if close_source and table_has_column(c, "shift_job_segments", "close_source"):
        c.execute(
            """
            UPDATE shift_job_segments SET ended_at=%s, close_source=%s
            WHERE shift_session_id=%s AND ended_at IS NULL
            """,
            (ended, close_source, int(session_id)),
        )
    else:
        c.execute(
            """
            UPDATE shift_job_segments SET ended_at=%s
            WHERE shift_session_id=%s AND ended_at IS NULL
            """,
            (ended, int(session_id)),
        )
    sets = []
    if table_has_column(c, "shift_sessions", "current_job_name_id"):
        sets.append("current_job_name_id=NULL")
    if table_has_column(c, "shift_sessions", "current_category_id"):
        sets.append("current_category_id=NULL")
    if table_has_column(c, "shift_sessions", "current_role_id"):
        sets.append("current_role_id=NULL")
    if table_has_column(c, "shift_sessions", "current_category_role_id"):
        sets.append("current_category_role_id=NULL")
    if sets:
        c.execute(
            f"UPDATE shift_sessions SET {', '.join(sets)} WHERE id=%s",
            (int(session_id),),
        )


class IdempotencyConflictError(ValueError):
    """Same idempotency key reused with a conflicting category/role payload."""


def _lock_shift_session_for_switch(cursor, session_id: int) -> None:
    """Serialize concurrent switches on one attendance shift (InnoDB row lock)."""
    cursor.execute(
        "SELECT id FROM shift_sessions WHERE id=%s FOR UPDATE",
        (int(session_id),),
    )
    cursor.fetchone()


def _segment_response_from_row(
    row: dict,
    *,
    assignment: Optional[dict] = None,
    replayed: bool = False,
    noop: bool = False,
) -> dict:
    r = json_safe(row) if row else {}
    cat = (assignment or {}).get("category_name") or r.get("category_name_snapshot")
    role = (assignment or {}).get("role_name") or r.get("role_name_snapshot")
    cat_code = r.get("category_code") or (assignment or {}).get("category_code")
    role_code = r.get("role_code") or (assignment or {}).get("role_code")
    # Internal snapshot label (manager / history).
    label = None
    if cat and role:
        label = f"{cat} — {role}"
    from backend.mobile_ops_labels import employee_assignment_label

    employee_label = employee_assignment_label(
        role_name=role,
        role_code=role_code,
        category_name=cat,
        category_code=cat_code,
    )
    started = r.get("started_at")
    if isinstance(started, datetime):
        started = started.isoformat()
    return {
        "id": r.get("id"),
        "shift_session_id": r.get("shift_session_id"),
        "category_id": r.get("category_id"),
        "role_id": r.get("role_id"),
        "category_role_id": r.get("category_role_id"),
        "category_code": cat_code,
        "role_code": role_code,
        "category_name": cat,
        "role_name": role,
        "display_label": label or (assignment or {}).get("display_label"),
        "employee_display_label": employee_label or None,
        "started_at": started,
        "ended_at": r.get("ended_at"),
        "change_source": r.get("change_source"),
        "idempotency_key": r.get("idempotency_key"),
        "replayed": bool(replayed),
        "noop": bool(noop),
        "unchanged": bool(noop or replayed),
    }


def _find_segment_by_idempotency_key(
    cursor, session_id: int, idempotency_key: str
) -> Optional[dict]:
    if not table_has_column(cursor, "shift_job_segments", "idempotency_key"):
        return None
    cursor.execute(
        """
        SELECT * FROM shift_job_segments
        WHERE shift_session_id=%s AND idempotency_key=%s
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(session_id), idempotency_key),
    )
    return cursor.fetchone()


def start_category_role_segment(
    conn,
    session_id: int,
    organization_id: int,
    user_id: int,
    category_id: int,
    role_id: int,
    *,
    started_at: Optional[datetime] = None,
    change_source: str = "switch",
    idempotency_key: Optional[str] = None,
) -> dict:
    c = conn.cursor(dictionary=True)
    ensure_shift_job_tracking_schema(c)
    key = (idempotency_key or "").strip()[:64] or None

    # Hold the attendance session row for the rest of the transaction so concurrent
    # switches cannot create overlapping opens or double-close races.
    _lock_shift_session_for_switch(c, session_id)

    if key:
        existing = _find_segment_by_idempotency_key(c, session_id, key)
        if existing:
            if int(existing.get("category_id") or 0) != int(category_id) or int(
                existing.get("role_id") or 0
            ) != int(role_id):
                raise IdempotencyConflictError(
                    "idempotency_key already used for a different category/role on this shift"
                )
            return _segment_response_from_row(existing, replayed=True, noop=False)

    assignment = resolve_active_assignment(
        c, organization_id, category_id=int(category_id), role_id=int(role_id)
    )

    # Same open assignment: no-op (must not close/reopen; start time unchanged).
    open_seg = get_open_job_segment(conn, session_id)
    if (
        open_seg
        and int(open_seg.get("category_id") or 0) == int(assignment["category_id"])
        and int(open_seg.get("role_id") or 0) == int(assignment["role_id"])
    ):
        return _segment_response_from_row(
            open_seg, assignment=assignment, replayed=False, noop=True
        )

    started = started_at or eastern_now_naive()
    close_open_job_segment(conn, session_id, started)
    ins = conn.cursor()
    has_idem_col = table_has_column(ins, "shift_job_segments", "idempotency_key")
    if has_idem_col and key:
        cols = (
            "shift_session_id, user_id, category_id, role_id, category_role_id, "
            "category_code, role_code, category_name_snapshot, role_name_snapshot, "
            "started_at, change_source, idempotency_key"
        )
        placeholders = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
        values = (
            int(session_id),
            int(user_id),
            int(assignment["category_id"]),
            int(assignment["role_id"]),
            int(assignment["id"]),
            assignment.get("category_code"),
            assignment.get("role_code"),
            assignment.get("category_name"),
            assignment.get("role_name"),
            started,
            change_source,
            key,
        )
    else:
        cols = (
            "shift_session_id, user_id, category_id, role_id, category_role_id, "
            "category_code, role_code, category_name_snapshot, role_name_snapshot, "
            "started_at, change_source"
        )
        placeholders = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
        values = (
            int(session_id),
            int(user_id),
            int(assignment["category_id"]),
            int(assignment["role_id"]),
            int(assignment["id"]),
            assignment.get("category_code"),
            assignment.get("role_code"),
            assignment.get("category_name"),
            assignment.get("role_name"),
            started,
            change_source,
        )
    try:
        ins.execute(
            f"INSERT INTO shift_job_segments ({cols}) VALUES ({placeholders})",
            values,
        )
    except Exception as exc:
        # Concurrent retry with the same key: return the winner's row.
        if key and getattr(exc, "args", (None,))[0] == 1062:
            raced = _find_segment_by_idempotency_key(c, session_id, key)
            if raced:
                return _segment_response_from_row(
                    raced, assignment=assignment, replayed=True, noop=False
                )
        raise
    seg_id = ins.lastrowid
    upd = []
    vals: list[Any] = []
    if table_has_column(ins, "shift_sessions", "current_category_id"):
        upd.append("current_category_id=%s")
        vals.append(int(assignment["category_id"]))
    if table_has_column(ins, "shift_sessions", "current_role_id"):
        upd.append("current_role_id=%s")
        vals.append(int(assignment["role_id"]))
    if table_has_column(ins, "shift_sessions", "current_category_role_id"):
        upd.append("current_category_role_id=%s")
        vals.append(int(assignment["id"]))
    if upd:
        vals.append(int(session_id))
        ins.execute(f"UPDATE shift_sessions SET {', '.join(upd)} WHERE id=%s", vals)
    return {
        "id": seg_id,
        "shift_session_id": session_id,
        "category_id": assignment["category_id"],
        "role_id": assignment["role_id"],
        "category_role_id": assignment["id"],
        "category_code": assignment.get("category_code"),
        "role_code": assignment.get("role_code"),
        "category_name": assignment.get("category_name"),
        "role_name": assignment.get("role_name"),
        "display_label": assignment.get("display_label"),
        "started_at": started.isoformat() if isinstance(started, datetime) else started,
        "change_source": change_source,
        "idempotency_key": key,
        "replayed": False,
        "noop": False,
        "unchanged": False,
    }


def switch_category_role(
    conn,
    session_id: int,
    organization_id: int,
    user_id: int,
    category_id: int,
    role_id: int,
) -> dict:
    return start_category_role_segment(
        conn,
        session_id,
        organization_id,
        user_id,
        category_id,
        role_id,
        change_source="switch",
    )


# Legacy aliases used by older routes/tests
def switch_job_role(conn, session_id: int, organization_id: int, job_name_id: int) -> dict:
    raise ValueError("Use category_id and role_id to switch tasks")


def start_job_segment(conn, session_id, organization_id, job_name_id, started_at=None):
    raise ValueError("Use start_category_role_segment with category_id and role_id")


def get_open_job_segment(conn, session_id: int) -> Optional[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return None
    c.execute(
        """
        SELECT * FROM shift_job_segments
        WHERE shift_session_id=%s AND ended_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (int(session_id),),
    )
    row = c.fetchone()
    if not row:
        return None
    r = json_safe(row)
    cat = r.get("category_name_snapshot")
    role = r.get("role_name_snapshot")
    if cat and role:
        r["display_label"] = f"{cat} — {role}"
        r["job_name"] = r["display_label"]  # legacy
        r["task_name"] = r["display_label"]
    return r


def list_session_segments(conn, session_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return []
    c.execute(
        """
        SELECT * FROM shift_job_segments
        WHERE shift_session_id=%s
        ORDER BY started_at ASC, id ASC
        """,
        (int(session_id),),
    )
    rows = c.fetchall() or []
    out = []
    now = eastern_now_naive()
    for row in rows:
        r = json_safe(row)
        start = _parse_dt(r.get("started_at"))
        end = _parse_dt(r.get("ended_at"))
        if start:
            end_eff = end or now
            r["duration_seconds"] = max(0, int((end_eff - start).total_seconds()))
        else:
            r["duration_seconds"] = 0
        cat = r.get("category_name_snapshot")
        role = r.get("role_name_snapshot")
        if cat and role:
            r["display_label"] = f"{cat} — {role}"
            r["job_name"] = r["display_label"]
            r["task_name"] = r["display_label"]
        out.append(r)
    return out


def get_last_check_in_assignment(conn, user_id: int) -> Optional[dict]:
    """First segment of the employee's most recent shift."""
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_job_segments"):
        return None
    if not table_has_column(c, "shift_job_segments", "category_id"):
        return None
    c.execute(
        """
        SELECT sjs.category_id, sjs.role_id, sjs.category_role_id,
               sjs.category_code, sjs.role_code,
               sjs.category_name_snapshot, sjs.role_name_snapshot
        FROM shift_sessions ss
        JOIN shift_job_segments sjs ON sjs.shift_session_id = ss.id
        WHERE ss.user_id=%s AND sjs.category_id IS NOT NULL AND sjs.role_id IS NOT NULL
        ORDER BY ss.clock_in_at DESC, sjs.started_at ASC, sjs.id ASC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = c.fetchone()
    if not row:
        return None
    r = json_safe(row)
    r["display_label"] = (
        f"{r.get('category_name_snapshot')} — {r.get('role_name_snapshot')}"
        if r.get("category_name_snapshot") and r.get("role_name_snapshot")
        else None
    )
    return r


def get_last_check_in_task_id(conn, user_id: int) -> Optional[int]:
    """Legacy helper — returns last category_role_id if available."""
    last = get_last_check_in_assignment(conn, user_id)
    if not last:
        return None
    return int(last["category_role_id"]) if last.get("category_role_id") else None


# ---------------------------------------------------------------------------
# Session init + enrichment
# ---------------------------------------------------------------------------


def resolve_scheduled_end_at(
    conn, organization_id: int, user_id: int, clock_in_at: datetime
) -> Optional[datetime]:
    if not table_exists(conn.cursor(), "payroll_schedule_entries"):
        return None
    c = conn.cursor(dictionary=True)
    work_date = clock_in_at.date()
    clock_t = clock_in_at.time().replace(microsecond=0)
    c.execute(
        """
        SELECT pse.end_time, pse.start_time, pse.work_date
        FROM payroll_schedule_entries pse
        JOIN payroll_worker_profiles pwp ON pwp.id = pse.worker_profile_id
        WHERE pwp.user_id=%s AND pse.organization_id=%s
          AND pse.work_date=%s
          AND pse.status NOT IN ('cancelled', 'canceled')
        ORDER BY pse.start_time ASC
        """,
        (int(user_id), int(organization_id), work_date),
    )
    rows = c.fetchall() or []
    if not rows:
        return None

    def _as_time(val):
        if isinstance(val, time):
            return val.replace(microsecond=0)
        if isinstance(val, timedelta):
            sec = int(val.total_seconds()) % 86400
            return (datetime.min + timedelta(seconds=sec)).time()
        s = str(val)
        if len(s) >= 5:
            parts = s.split(":")
            return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        return None

    best_end: Optional[time] = None
    for row in rows:
        st = _as_time(row.get("start_time"))
        et = _as_time(row.get("end_time"))
        if et is None:
            continue
        if st is not None and st <= clock_t <= et:
            best_end = et
            break
        if best_end is None or et > best_end:
            best_end = et
    if best_end is None:
        return None
    return _combine_date_time(work_date, best_end)


def init_session_job_tracking(
    conn,
    session_id: int,
    organization_id: int,
    user_id: int,
    clock_in_at: datetime,
    job_name_id: Optional[int] = None,
    *,
    category_id: Optional[int] = None,
    role_id: Optional[int] = None,
) -> None:
    """Open the first category/role segment for a newly created attendance shift.

    Phase 1 does not attach attendance-policy deadlines (force checkout, etc.).
    """
    c = conn.cursor()
    ensure_shift_job_tracking_schema(c)
    seed_default_categories_and_roles(c, organization_id)
    if category_id and role_id:
        start_category_role_segment(
            conn,
            int(session_id),
            int(organization_id),
            int(user_id),
            int(category_id),
            int(role_id),
            started_at=clock_in_at,
            change_source="check_in",
        )


def enrich_session_job_tracking(conn, sess: dict, user_id: int) -> dict:
    """Attach current category/role assignment to an attendance session payload."""
    if not sess:
        return {}
    sid = int(sess["id"])
    open_seg = get_open_job_segment(conn, sid)
    segments = list_session_segments(conn, sid)

    current_label = None
    current_category_id = sess.get("current_category_id")
    current_role_id = sess.get("current_role_id")
    current_category_name = None
    current_role_name = None
    current_started_at = None
    if open_seg:
        from backend.mobile_ops_labels import employee_assignment_label_from_segment

        current_label = employee_assignment_label_from_segment(open_seg) or open_seg.get(
            "display_label"
        )
        current_category_id = open_seg.get("category_id") or current_category_id
        current_role_id = open_seg.get("role_id") or current_role_id
        current_category_name = open_seg.get("category_name_snapshot")
        current_role_name = open_seg.get("role_name_snapshot")
        current_started_at = open_seg.get("started_at")

    out = {
        "current_category_id": current_category_id,
        "current_role_id": current_role_id,
        "current_category_name": current_category_name,
        "current_role_name": current_role_name,
        "current_display_label": current_label,
        "current_assignment_started_at": current_started_at,
        "current_task_segment": open_seg,
        "task_segments": segments,
        "needs_current_assignment": open_seg is None,
        # Legacy aliases
        "current_task_id": open_seg.get("category_role_id") if open_seg else None,
        "current_task_name": current_label,
        "current_job_name": current_label,
        "current_job_name_id": open_seg.get("category_role_id") if open_seg else None,
        "job_segments": segments,
    }
    return json_safe(out)


# ---------------------------------------------------------------------------
# Force checkout (unchanged behavior)
# ---------------------------------------------------------------------------


def user_force_checkout_waiver(conn, user_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    if not table_has_column(c, "payroll_profiles", "force_checkout_waiver"):
        return False
    c.execute(
        "SELECT force_checkout_waiver FROM payroll_profiles WHERE user_id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone()
    return bool(row and int(row.get("force_checkout_waiver") or 0))


def set_user_force_checkout_waiver(conn, user_id: int, waived: bool) -> bool:
    c = conn.cursor()
    ensure_shift_job_tracking_schema(c)
    c.execute(
        "UPDATE payroll_profiles SET force_checkout_waiver=%s WHERE user_id=%s",
        (1 if waived else 0, int(user_id)),
    )
    return bool(c.rowcount)


def effective_force_checkout_at(sess: dict, employee_waiver: bool) -> Optional[datetime]:
    if employee_waiver:
        return None
    if bool(int(sess.get("force_checkout_waived") or 0)):
        return None
    fc = _parse_dt(sess.get("force_checkout_at"))
    if fc:
        return fc
    return _parse_dt(sess.get("scheduled_end_at"))


def _sum_break_seconds(conn, shift_id: int) -> int:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "shift_breaks"):
        return 0
    c.execute(
        "SELECT break_start_at, break_end_at FROM shift_breaks WHERE shift_session_id=%s",
        (int(shift_id),),
    )
    total = 0
    for row in c.fetchall() or []:
        start = _parse_dt(row.get("break_start_at"))
        end = _parse_dt(row.get("break_end_at"))
        if start and end:
            total += int((end - start).total_seconds())
    return total


def _compute_net_seconds(conn, sess: dict, clock_out_at: datetime) -> tuple[int, int]:
    br = _sum_break_seconds(conn, int(sess["id"]))
    clock_in = _parse_dt(sess.get("clock_in_at"))
    if not clock_in:
        return br, 0
    elapsed = int((clock_out_at - clock_in).total_seconds())
    return br, max(0, elapsed - br)


def perform_force_checkout(
    conn,
    sess: dict,
    user_id: int,
    checkout_type: str = "force_scheduled",
    *,
    clock_out_at: Optional[datetime] = None,
    message: Optional[str] = None,
) -> dict:
    if str(sess.get("status")) != "active":
        raise ValueError("Session is not active")
    sid = int(sess["id"])
    now = clock_out_at or eastern_now_naive()
    br, net = _compute_net_seconds(conn, sess, now)
    close_open_job_segment(conn, sid, now)
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, status='auto_closed', total_break_seconds=%s,
            net_work_seconds=%s, force_checked_out_at=%s, checkout_type=%s,
            continuation_allowed=0
        WHERE id=%s
        """,
        (now, br, net, now, checkout_type, sid),
    )
    msg = message or f"Force check-out ({checkout_type}) at scheduled end."
    c.execute(
        """
        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message, severity)
        VALUES (%s,%s,'scheduled_force_checkout',%s,'warning')
        """,
        (sid, int(user_id), msg),
    )
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
    return json_safe(c2.fetchone() or {})


def maybe_force_checkout_scheduled_end(
    conn, sess: dict, user_id: int, organization_id: int
) -> Optional[dict]:
    if not sess or str(sess.get("status")) != "active":
        return None
    ensure_shift_job_tracking_schema(conn.cursor())
    employee_waiver = user_force_checkout_waiver(conn, user_id)
    deadline = effective_force_checkout_at(sess, employee_waiver)
    if not deadline:
        return None
    now = eastern_now_naive()
    if now < deadline:
        return None
    return perform_force_checkout(
        conn,
        sess,
        user_id,
        checkout_type="force_scheduled",
        clock_out_at=deadline,
        message=f"Scheduled shift end at {deadline.strftime('%I:%M %p')} — automatic check-out.",
    )


def admin_waive_session_force_checkout(conn, session_id: int, waived: bool) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    old = bool(int(sess.get("force_checkout_waived") or 0))
    uc = conn.cursor()
    uc.execute(
        "UPDATE shift_sessions SET force_checkout_waived=%s WHERE id=%s",
        (1 if waived else 0, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    return {
        "session": json_safe(c.fetchone()),
        "old": {"force_checkout_waived": old},
        "new": {"force_checkout_waived": waived},
    }


def admin_override_force_checkout_time(conn, session_id: int, force_checkout_at: datetime) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    old = _parse_dt(sess.get("force_checkout_at"))
    uc = conn.cursor()
    uc.execute(
        "UPDATE shift_sessions SET force_checkout_at=%s, manual_override=1 WHERE id=%s",
        (force_checkout_at, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    return {
        "session": json_safe(c.fetchone()),
        "old": {"force_checkout_at": old.isoformat() if old else None},
        "new": {"force_checkout_at": force_checkout_at.isoformat()},
    }


def admin_allow_continuation(conn, session_id: int) -> dict:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    sess = c.fetchone()
    if not sess:
        raise ValueError("Session not found")
    if not _parse_dt(sess.get("force_checked_out_at")):
        raise ValueError("Session was not force checked out")
    now = eastern_now_naive()
    uc = conn.cursor()
    uc.execute(
        """
        UPDATE shift_sessions
        SET status='active', clock_out_at=NULL, net_work_seconds=NULL,
            continuation_allowed=1, continued_after_force_at=%s,
            checkout_type=NULL
        WHERE id=%s
        """,
        (now, int(session_id)),
    )
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (int(session_id),))
    return {"session": json_safe(c.fetchone())}


def on_manual_clock_out(conn, session_id: int) -> None:
    """Close any open task segment; never blocks attendance checkout if none exists."""
    close_open_job_segment(conn, int(session_id), close_source="checkout")
    c = conn.cursor()
    if table_has_column(c, "shift_sessions", "checkout_type"):
        c.execute(
            """
            UPDATE shift_sessions SET checkout_type='manual'
            WHERE id=%s AND (checkout_type IS NULL OR checkout_type='')
            """,
            (int(session_id),),
        )


# ---------------------------------------------------------------------------
# History / timeline
# ---------------------------------------------------------------------------


def build_shift_timeline(rec: dict, segments: list[dict]) -> list[dict]:
    timeline: list[dict] = []
    clock_in = _parse_dt(rec.get("clock_in_at"))
    clock_out = _parse_dt(rec.get("clock_out_at"))
    force_checked = bool(_parse_dt(rec.get("force_checked_out_at")))

    if clock_in:
        timeline.append({"type": "check_in", "at": clock_in.isoformat(), "label": "Check In"})

    for seg in segments:
        label = seg.get("display_label") or seg.get("task_name") or seg.get("job_name")
        timeline.append(
            {
                "type": "task",
                "category_id": seg.get("category_id"),
                "role_id": seg.get("role_id"),
                "category_code": seg.get("category_code"),
                "role_code": seg.get("role_code"),
                "task_name": label,
                "display_label": label,
                "started_at": seg.get("started_at"),
                "ended_at": seg.get("ended_at"),
            }
        )

    if clock_out:
        if force_checked or rec.get("checkout_type") == "force_scheduled":
            timeline.append(
                {
                    "type": "force_check_out",
                    "at": clock_out.isoformat(),
                    "label": "Force Checked Out",
                }
            )
        else:
            timeline.append(
                {"type": "check_out", "at": clock_out.isoformat(), "label": "Checked Out"}
            )
    return timeline


def _role_time_summary(segments: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for seg in segments:
        key = f"{seg.get('category_id')}:{seg.get('role_id')}"
        label = seg.get("display_label") or seg.get("task_name") or "Unknown"
        if key not in totals:
            totals[key] = {
                "category_id": seg.get("category_id"),
                "role_id": seg.get("role_id"),
                "category_code": seg.get("category_code"),
                "role_code": seg.get("role_code"),
                "task_name": label,
                "display_label": label,
                "job_name_id": seg.get("category_role_id"),
                "job_name": label,
                "total_seconds": 0,
            }
        totals[key]["total_seconds"] += int(seg.get("duration_seconds") or 0)
    return sorted(totals.values(), key=lambda x: x.get("display_label") or "")


def job_tracking_report(
    conn,
    organization_id: int,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user_id: Optional[int] = None,
    shift_session_id: Optional[int] = None,
    job_name_id: Optional[int] = None,
    task_id: Optional[int] = None,
    category_id: Optional[int] = None,
    role_id: Optional[int] = None,
) -> list[dict]:
    ensure_shift_job_tracking_schema(conn.cursor())
    c = conn.cursor(dictionary=True)
    q = """
        SELECT s.*, pp.first_name, pp.last_name, pp.email
        FROM shift_sessions s
        JOIN payroll_profiles pp ON pp.user_id = s.user_id
        WHERE s.organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if shift_session_id:
        q += " AND s.id=%s"
        params.append(int(shift_session_id))
    if user_id:
        q += " AND s.user_id=%s"
        params.append(int(user_id))
    if from_date:
        q += " AND DATE(s.clock_in_at) >= %s"
        params.append(from_date)
    if to_date:
        q += " AND DATE(s.clock_in_at) <= %s"
        params.append(to_date)
    q += " ORDER BY s.clock_in_at DESC, s.id DESC LIMIT 500"
    c.execute(q, params)
    rows = c.fetchall() or []
    filter_assignment = task_id or job_name_id
    out = []
    for row in rows:
        rec = json_safe(row)
        sid = int(rec["id"])
        segments = list_session_segments(conn, sid)
        if category_id:
            segments = [s for s in segments if int(s.get("category_id") or 0) == int(category_id)]
        if role_id:
            segments = [s for s in segments if int(s.get("role_id") or 0) == int(role_id)]
        if filter_assignment:
            segments = [
                s
                for s in segments
                if int(s.get("category_role_id") or 0) == int(filter_assignment)
            ]
        if (category_id or role_id or filter_assignment) and not segments:
            continue
        summary = _role_time_summary(segments)
        task_breakdown = [
            {
                "task_id": t.get("job_name_id"),
                "task_name": t.get("display_label"),
                "display_label": t.get("display_label"),
                "category_id": t.get("category_id"),
                "role_id": t.get("role_id"),
                "category_code": t.get("category_code"),
                "role_code": t.get("role_code"),
                "duration_seconds": t["total_seconds"],
            }
            for t in summary
        ]
        clock_in = _parse_dt(rec.get("clock_in_at"))
        clock_out = _parse_dt(rec.get("clock_out_at"))
        total_seconds = int(rec.get("net_work_seconds") or 0)
        if not total_seconds and clock_in and clock_out:
            total_seconds = max(0, int((clock_out - clock_in).total_seconds()))
        rec["shift_date"] = str(clock_in.date()) if clock_in else str(rec.get("clock_in_at") or "")[:10]
        rec["total_shift_seconds"] = total_seconds
        rec["task_breakdown"] = task_breakdown
        rec["shift_timeline"] = build_shift_timeline(rec, segments)
        rec["was_force_checked_out"] = bool(_parse_dt(rec.get("force_checked_out_at")))
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Legacy flat-task stubs (keep imports from older routes/tests from exploding)
# ---------------------------------------------------------------------------


def list_job_names(cursor, organization_id: int, **kwargs) -> list[dict]:
    """Legacy: return active category-role assignments as selectable 'tasks'."""
    tree = list_active_selection_tree(cursor, organization_id)
    out = []
    for cat in tree:
        for role in cat.get("roles") or []:
            out.append(
                {
                    "id": role["id"],
                    "name": role.get("display_label"),
                    "category_id": role["category_id"],
                    "role_id": role["role_id"],
                    "active": role.get("active", 1),
                    "sort_order": role.get("sort_order", 0),
                }
            )
    return out


def get_job_name(cursor, organization_id: int, job_name_id: int) -> Optional[dict]:
    return get_assignment(cursor, organization_id, job_name_id)


def create_job_name(cursor, organization_id: int, name: str, *, active: bool = True) -> dict:
    raise ValueError("Use create_category / create_role instead of flat task names")


def update_job_name(cursor, organization_id: int, job_name_id: int, **kwargs) -> dict:
    raise ValueError("Use update_category / update_role instead of flat task names")


def reorder_job_names(cursor, organization_id: int, ordered_ids: list[int]) -> list[dict]:
    raise ValueError("Use reorder_categories / reorder_category_roles")


def delete_job_name(cursor, organization_id: int, task_id: int) -> None:
    raise ValueError("Use delete_category / delete_role")


def task_usage_count(cursor, task_id: int) -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM shift_job_segments WHERE category_role_id=%s",
        (int(task_id),),
    )
    return int(_scalar(cursor.fetchone()) or 0)
