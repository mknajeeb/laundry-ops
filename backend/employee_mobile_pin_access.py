"""
Phase 5B.1 / 5B.2 — Employee Mobile PIN Access.

Controls which PIN-launcher applications an employee may open.
Independent of:
  - Organization pin_menu feature flags
  - Phase 5C Allowed Work Assignments
  - Weekday Tasks / Stock / Revenue & Cost assignments

Rollout / defaults (Phase 5B.2)
-------------------------------
Per-organization marker in ``employee_mobile_pin_access_backfill`` (no global cutover):

1. **Unmarked org:** missing access row → temporary all-allow (deploy window).
2. **Legacy migrated:** controlled operator backfill inserts all-true for eligible
   active PIN employees, verifies completeness, then writes marker
   ``init_mode=legacy_grant``. Request paths never auto-grant.
3. **New org:** platform create/bootstrap writes marker ``init_mode=new_org`` with
   zero grants. New / first-PIN employees get explicit rows with ``switch_role`` ON
   and other modules OFF (Role is the universal Mobile Ops default).
4. **Marked org:** missing row → all-deny (never "missing = allow all").
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

MODULE_KEYS = (
    "clock",
    "switch_role",
    "checklist",
    "inventory",
    "revenue_cost",
    "team_status",
)

# Hub / PIN enforcement AND-gates. Clock remains stored but not activated.
ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES = frozenset(
    {"switch_role", "checklist", "inventory", "revenue_cost", "team_status"}
)

# DB column ↔ API/feature key
COLUMN_BY_KEY = {
    "clock": "allow_clock",
    "switch_role": "allow_switch_role",
    "checklist": "allow_checklist",
    "inventory": "allow_inventory",
    "revenue_cost": "allow_revenue_cost",
    "team_status": "allow_team_status",
}

KEY_BY_COLUMN = {v: k for k, v in COLUMN_BY_KEY.items()}

BACKFILL_MARKER_TABLE = "employee_mobile_pin_access_backfill"
ACCESS_TABLE = "employee_mobile_pin_access"

INIT_MODE_LEGACY_GRANT = "legacy_grant"
INIT_MODE_NEW_ORG = "new_org"

_LOCK_PREFIX = "mpa_legacy_bf_"
_LOCK_TIMEOUT_SEC = 10

DENIED_MODULE_MESSAGE = "That application is not available for this employee."
AUDIT_ENTITY = "employee_mobile_pin_access"
AUDIT_ACTION = "employee_mobile_pin_access.updated"


class MobilePinAccessDeniedError(PermissionError):
    """Raised when an employee opens a PIN module they are not allowed to use."""

    def __init__(self, message: str = DENIED_MODULE_MESSAGE):
        super().__init__(message)
        self.status = 403


class MobilePinAccessBackfillError(RuntimeError):
    """Controlled legacy backfill failed; transaction rolled back when applicable."""


def _all_false() -> dict[str, bool]:
    return {k: False for k in MODULE_KEYS}


def _all_true() -> dict[str, bool]:
    """Temporary pre-marker allow-all — never includes manager-only team_status."""
    out = {k: True for k in MODULE_KEYS}
    out["team_status"] = False
    return out


def ensure_employee_mobile_pin_access_tables(cursor) -> None:
    """Idempotent schema only — never grants rows or marks organizations."""
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ACCESS_TABLE} (
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          allow_clock TINYINT(1) NOT NULL DEFAULT 0,
          allow_switch_role TINYINT(1) NOT NULL DEFAULT 0,
          allow_checklist TINYINT(1) NOT NULL DEFAULT 0,
          allow_inventory TINYINT(1) NOT NULL DEFAULT 0,
          allow_revenue_cost TINYINT(1) NOT NULL DEFAULT 0,
          allow_team_status TINYINT(1) NOT NULL DEFAULT 0,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          updated_by_user_id INT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (organization_id, user_id),
          INDEX idx_empa_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {BACKFILL_MARKER_TABLE} (
          organization_id INT NOT NULL PRIMARY KEY,
          backfilled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          employees_granted INT NOT NULL DEFAULT 0,
          init_mode VARCHAR(32) NOT NULL DEFAULT '{INIT_MODE_LEGACY_GRANT}'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    invalidate_schema_cache()
    if table_exists(cursor, ACCESS_TABLE) and not table_has_column(
        cursor, ACCESS_TABLE, "allow_team_status"
    ):
        cursor.execute(
            f"""
            ALTER TABLE {ACCESS_TABLE}
              ADD COLUMN allow_team_status TINYINT(1) NOT NULL DEFAULT 0
              AFTER allow_revenue_cost
            """
        )
        invalidate_schema_cache()
    if table_exists(cursor, BACKFILL_MARKER_TABLE) and not table_has_column(
        cursor, BACKFILL_MARKER_TABLE, "init_mode"
    ):
        cursor.execute(
            f"""
            ALTER TABLE {BACKFILL_MARKER_TABLE}
              ADD COLUMN init_mode VARCHAR(32) NOT NULL DEFAULT '{INIT_MODE_LEGACY_GRANT}'
            """
        )
        invalidate_schema_cache()


def _org_is_backfilled(cursor, organization_id: int) -> bool:
    if not table_exists(cursor, BACKFILL_MARKER_TABLE):
        return False
    cursor.execute(
        f"SELECT 1 FROM {BACKFILL_MARKER_TABLE} WHERE organization_id = %s LIMIT 1",
        (int(organization_id),),
    )
    return bool(cursor.fetchone())


def _mark_org_backfilled(
    cursor,
    organization_id: int,
    employees_granted: int,
    *,
    init_mode: str,
) -> None:
    cursor.execute(
        f"""
        INSERT INTO {BACKFILL_MARKER_TABLE}
          (organization_id, backfilled_at, employees_granted, init_mode)
        VALUES (%s, NOW(), %s, %s)
        """,
        (int(organization_id), int(employees_granted), str(init_mode)),
    )


def ensure_org_mobile_pin_access_backfill(cursor, organization_id: int) -> None:
    """
    Schema-only ensure for request paths.

    Does not grant employees or write markers. Legacy grants require
    ``run_org_mobile_pin_access_legacy_backfill``; new orgs use
    ``initialize_new_org_mobile_pin_access_marker``.

    Hot path: skip CREATE TABLE IF NOT EXISTS when both tables already exist
    (table_exists is process-cached). CREATE IF NOT EXISTS is ~300ms on Azure MySQL
    even when the table is present.
    """
    _ = int(organization_id)
    if table_exists(cursor, ACCESS_TABLE) and table_exists(cursor, BACKFILL_MARKER_TABLE):
        if not table_has_column(cursor, ACCESS_TABLE, "allow_team_status"):
            ensure_employee_mobile_pin_access_tables(cursor)
        return
    ensure_employee_mobile_pin_access_tables(cursor)


def initialize_new_org_mobile_pin_access_marker(cursor, organization_id: int) -> bool:
    """
    Explicit new-org policy: marker with zero grants (init_mode=new_org).
    Idempotent. Returns True when a marker row was inserted.
    """
    ensure_employee_mobile_pin_access_tables(cursor)
    oid = int(organization_id)
    if _org_is_backfilled(cursor, oid):
        return False
    cursor.execute(
        f"""
        INSERT IGNORE INTO {BACKFILL_MARKER_TABLE}
          (organization_id, backfilled_at, employees_granted, init_mode)
        VALUES (%s, NOW(), 0, %s)
        """,
        (oid, INIT_MODE_NEW_ORG),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def _lock_name(organization_id: int) -> str:
    return f"{_LOCK_PREFIX}{int(organization_id)}"


def _fetch_int_ids(rows) -> list[int]:
    out: list[int] = []
    for row in rows or []:
        try:
            if isinstance(row, dict):
                val = row.get("user_id", row.get("id"))
            else:
                val = row[0]
            out.append(int(val))
        except (TypeError, ValueError, IndexError, AttributeError, KeyError):
            continue
    return out


def _list_eligible_pin_employee_ids(cursor, organization_id: int) -> list[int]:
    if not table_exists(cursor, "payroll_profiles") or not table_exists(cursor, "users"):
        return []
    cursor.execute(
        """
        SELECT u.id AS user_id
        FROM users u
        INNER JOIN payroll_profiles pp ON pp.user_id = u.id
        WHERE u.organization_id = %s
          AND u.active = 1
          AND pp.attendance_pin_hash IS NOT NULL
        ORDER BY u.id
        """,
        (int(organization_id),),
    )
    return _fetch_int_ids(cursor.fetchall())


def _list_access_user_ids(
    cursor, organization_id: int, user_ids: list[int]
) -> set[int]:
    if not user_ids:
        return set()
    placeholders = ", ".join(["%s"] * len(user_ids))
    cursor.execute(
        f"""
        SELECT user_id FROM {ACCESS_TABLE}
        WHERE organization_id = %s AND user_id IN ({placeholders})
        """,
        (int(organization_id), *user_ids),
    )
    return set(_fetch_int_ids(cursor.fetchall()))


def _insert_all_true_rows(
    cursor, organization_id: int, user_ids: list[int]
) -> int:
    if not user_ids:
        return 0
    values_sql = ", ".join(["(%s, %s, 1, 1, 1, 1, 1, NOW())"] * len(user_ids))
    params: list[Any] = []
    for uid in user_ids:
        params.extend([int(organization_id), int(uid)])
    cursor.execute(
        f"""
        INSERT INTO {ACCESS_TABLE}
          (organization_id, user_id,
           allow_clock, allow_switch_role, allow_checklist,
           allow_inventory, allow_revenue_cost, created_at)
        VALUES {values_sql}
        """,
        tuple(params),
    )
    return len(user_ids)


def _organization_exists(cursor, organization_id: int) -> bool:
    if not table_exists(cursor, "organizations"):
        return True
    cursor.execute(
        "SELECT id FROM organizations WHERE id = %s LIMIT 1",
        (int(organization_id),),
    )
    return bool(cursor.fetchone())


def _skipped_non_eligible(cursor, organization_id: int, eligible: set[int]) -> list[dict]:
    """Users in-org who are not eligible (inactive or missing PIN) — reporting only."""
    if not table_exists(cursor, "users"):
        return []
    cursor.execute(
        """
        SELECT u.id AS user_id, u.active,
               CASE WHEN pp.attendance_pin_hash IS NULL THEN 0 ELSE 1 END AS has_pin
        FROM users u
        LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
        WHERE u.organization_id = %s
        ORDER BY u.id
        """,
        (int(organization_id),),
    )
    skipped: list[dict] = []
    for row in cursor.fetchall() or []:
        try:
            uid = int(row.get("user_id") if isinstance(row, dict) else row[0])
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        if uid in eligible:
            continue
        active = bool(row.get("active") if isinstance(row, dict) else True)
        has_pin = bool(row.get("has_pin") if isinstance(row, dict) else False)
        reasons = []
        if not active:
            reasons.append("inactive")
        if not has_pin:
            reasons.append("no_attendance_pin")
        skipped.append({"user_id": uid, "reasons": reasons or ["not_eligible"]})
    return skipped


def run_org_mobile_pin_access_legacy_backfill(
    conn,
    organization_id: int,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Transaction-owned, single-organization legacy all-true backfill.

    Marker is written only after every eligible employee has an access row.
    Never touches another organization.
    """
    oid = int(organization_id)
    report: dict[str, Any] = {
        "organization_id": oid,
        "dry_run": bool(dry_run),
        "eligible_employees": [],
        "eligible_count": 0,
        "rows_inserted": 0,
        "planned_inserts": [],
        "already_present": [],
        "skipped": [],
        "warnings": [],
        "completion_verified": False,
        "marker": "none",
        "init_mode": INIT_MODE_LEGACY_GRANT,
        "already_complete": False,
        "ok": False,
    }

    prior_autocommit = getattr(conn, "autocommit", True)
    lock_acquired = False
    cursor = None
    try:
        conn.autocommit = False
        cursor = conn.cursor(dictionary=True)

        # Schema outside the grant transaction semantics: DDL may implicit-commit.
        # Callers should prefer applying SQL first; this remains idempotent.
        ensure_employee_mobile_pin_access_tables(cursor)
        try:
            conn.commit()
        except Exception:
            pass

        if not _organization_exists(cursor, oid):
            report["warnings"].append("organization_not_found")
            report["ok"] = False
            return report

        if not dry_run:
            cursor.execute(
                "SELECT GET_LOCK(%s, %s) AS got",
                (_lock_name(oid), _LOCK_TIMEOUT_SEC),
            )
            lock_row = cursor.fetchone() or {}
            got = lock_row.get("got") if isinstance(lock_row, dict) else (
                lock_row[0] if lock_row else 0
            )
            if int(got or 0) != 1:
                report["warnings"].append("lock_timeout")
                report["ok"] = False
                return report
            lock_acquired = True

        if _org_is_backfilled(cursor, oid):
            report["already_complete"] = True
            report["marker"] = "already_present"
            report["completion_verified"] = True
            report["ok"] = True
            eligible = _list_eligible_pin_employee_ids(cursor, oid)
            report["eligible_employees"] = eligible
            report["eligible_count"] = len(eligible)
            present = sorted(_list_access_user_ids(cursor, oid, eligible))
            report["already_present"] = present
            report["skipped"] = _skipped_non_eligible(cursor, oid, set(eligible))
            return report

        eligible = _list_eligible_pin_employee_ids(cursor, oid)
        eligible_set = set(eligible)
        report["eligible_employees"] = eligible
        report["eligible_count"] = len(eligible)
        report["skipped"] = _skipped_non_eligible(cursor, oid, eligible_set)

        present = _list_access_user_ids(cursor, oid, eligible)
        report["already_present"] = sorted(present)
        to_insert = [uid for uid in eligible if uid not in present]
        report["planned_inserts"] = list(to_insert)

        if dry_run:
            report["rows_inserted"] = 0
            report["marker"] = "would_write"
            # Completeness after planned inserts
            report["completion_verified"] = True
            report["ok"] = True
            return report

        if to_insert:
            _insert_all_true_rows(cursor, oid, to_insert)
        report["rows_inserted"] = len(to_insert)

        verified = _list_access_user_ids(cursor, oid, eligible)
        missing = [uid for uid in eligible if uid not in verified]
        if missing:
            raise MobilePinAccessBackfillError(
                f"completeness check failed; missing access rows for user_ids={missing}"
            )
        report["completion_verified"] = True

        _mark_org_backfilled(
            cursor,
            oid,
            len(to_insert),
            init_mode=INIT_MODE_LEGACY_GRANT,
        )
        conn.commit()
        report["marker"] = "written"
        report["ok"] = True
        return report
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        report["completion_verified"] = False
        report["marker"] = "none"
        report["ok"] = False
        raise
    finally:
        if lock_acquired and cursor is not None:
            try:
                cursor.execute(
                    "SELECT RELEASE_LOCK(%s) AS released",
                    (_lock_name(oid),),
                )
                cursor.fetchone()
            except Exception:
                pass
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass
        try:
            conn.autocommit = prior_autocommit
        except Exception:
            pass


def _row_to_access(row: Optional[dict]) -> Optional[dict[str, bool]]:
    if not row:
        return None
    out = {}
    for key, col in COLUMN_BY_KEY.items():
        out[key] = bool(row.get(col))
    return out


def get_access_row(cursor, organization_id: int, user_id: int) -> Optional[dict]:
    """
    Hot-path read. Caller must ensure schema via ``ensure_org_mobile_pin_access_backfill``
    (skips CREATE TABLE IF NOT EXISTS when tables already exist).
    """
    if not table_exists(cursor, ACCESS_TABLE):
        return None
    cursor.execute(
        f"""
        SELECT organization_id, user_id,
               allow_clock, allow_switch_role, allow_checklist,
               allow_inventory, allow_revenue_cost, allow_team_status,
               updated_at, updated_by_user_id, created_at
        FROM {ACCESS_TABLE}
        WHERE organization_id = %s AND user_id = %s
        LIMIT 1
        """,
        (int(organization_id), int(user_id)),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) or row is None else None


def resolve_employee_mobile_pin_access(
    cursor, organization_id: int, user_id: int
) -> dict[str, bool]:
    """
    Effective employee module grants.

    After org marker exists: missing row → all false.
    Before org is marked (bounded deploy window): missing row → all true
    so staff are not locked out before controlled legacy backfill runs.
    """
    ensure_org_mobile_pin_access_backfill(cursor, int(organization_id))
    row = get_access_row(cursor, int(organization_id), int(user_id))
    parsed = _row_to_access(row if isinstance(row, dict) else None)
    if parsed is not None:
        return parsed
    if _org_is_backfilled(cursor, int(organization_id)):
        return _all_false()
    # Temporary pre-marker compatibility only.
    return _all_true()


def employee_allows_module(
    cursor, organization_id: int, user_id: int, module_key: str
) -> bool:
    key = str(module_key or "").strip()
    if key not in MODULE_KEYS:
        return False
    access = resolve_employee_mobile_pin_access(cursor, organization_id, user_id)
    return bool(access.get(key))


def employee_module_enforced(module_key: str) -> bool:
    """True when this Phase 5B.1 step activates employee gating for the module."""
    return str(module_key or "").strip() in ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES


def assert_employee_allows_module(
    cursor, organization_id: int, user_id: int, module_key: str
) -> None:
    """
    Enforce employee Mobile PIN Access for an activated module.
    No-op when the module is not yet in ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES
    (later Phase 5B.1 steps expand that set).
    """
    key = str(module_key or "").strip()
    if not employee_module_enforced(key):
        return
    if not employee_allows_module(cursor, organization_id, user_id, key):
        raise MobilePinAccessDeniedError()


def assert_optional_pin_hub_module(
    cursor, organization_id: int, user_id: int, pin_hub_module: Any
) -> None:
    """
    Unlock-time gate for PIN Hub feature unlocks.

    When ``pin_hub_module`` is omitted/blank (kiosk / generic unlock), no-op.
    When present, runs ``assert_employee_allows_module`` — inactive modules
    (Clock) remain no-ops until activated.
    """
    key = str(pin_hub_module or "").strip()
    if not key:
        return
    assert_employee_allows_module(cursor, organization_id, user_id, key)


def _new_employee_default_grants() -> dict[str, bool]:
    """Canonical defaults for newly created / newly PIN'd employees."""
    grants = _all_false()
    grants["switch_role"] = True
    return grants


def ensure_new_employee_mobile_pin_access(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    actor_user_id: Optional[int] = None,
) -> None:
    """
    Explicit default row for a new / newly PIN'd employee *after* the org is marked.

    Defaults: ``switch_role`` ON; clock / checklist / inventory / revenue_cost /
    team_status OFF.
    Before the org marker exists, do nothing so controlled legacy all-true backfill
    can still apply to employees present at migration.
    INSERT IGNORE so existing manager grants are never overwritten.
    """
    ensure_org_mobile_pin_access_backfill(cursor, int(organization_id))
    if not _org_is_backfilled(cursor, int(organization_id)):
        return
    defaults = _new_employee_default_grants()
    cursor.execute(
        f"""
        INSERT IGNORE INTO {ACCESS_TABLE}
          (organization_id, user_id,
           allow_clock, allow_switch_role, allow_checklist,
           allow_inventory, allow_revenue_cost, allow_team_status,
           updated_by_user_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            int(organization_id),
            int(user_id),
            1 if defaults["clock"] else 0,
            1 if defaults["switch_role"] else 0,
            1 if defaults["checklist"] else 0,
            1 if defaults["inventory"] else 0,
            1 if defaults["revenue_cost"] else 0,
            1 if defaults["team_status"] else 0,
            int(actor_user_id) if actor_user_id is not None else None,
        ),
    )


def _list_active_user_ids(cursor, organization_id: int) -> list[int]:
    if not table_exists(cursor, "users"):
        return []
    cursor.execute(
        """
        SELECT id AS user_id
        FROM users
        WHERE organization_id = %s AND active = 1
        ORDER BY id
        """,
        (int(organization_id),),
    )
    return _fetch_int_ids(cursor.fetchall())


def enable_switch_role_for_org_active_users(
    conn,
    organization_id: int,
    *,
    dry_run: bool = True,
    actor_user_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Enable Mobile PIN Access ``switch_role`` for every active user in an org.

    Does not grant checklist / inventory / revenue_cost / clock.
    INSERT missing rows with Role-only defaults; UPDATE existing rows to set
    ``allow_switch_role=1`` without changing other module flags.
    """
    oid = int(organization_id)
    report: dict[str, Any] = {
        "organization_id": oid,
        "dry_run": bool(dry_run),
        "active_users": 0,
        "role_on_before": 0,
        "role_on_after": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "already_on": 0,
        "excluded_inactive": 0,
        "user_ids_enabled": [],
        "excluded_users": [],
    }
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_employee_mobile_pin_access_tables(cursor)
        ensure_org_mobile_pin_access_backfill(cursor, oid)
        active_ids = _list_active_user_ids(cursor, oid)
        report["active_users"] = len(active_ids)

        if table_exists(cursor, "users"):
            cursor.execute(
                """
                SELECT id AS user_id
                FROM users
                WHERE organization_id = %s AND (active = 0 OR active IS NULL)
                ORDER BY id
                """,
                (oid,),
            )
            inactive = _fetch_int_ids(cursor.fetchall())
            report["excluded_inactive"] = len(inactive)
            report["excluded_users"] = [
                {"user_id": uid, "reasons": ["inactive"]} for uid in inactive
            ]

        before_on = 0
        to_insert: list[int] = []
        to_update: list[int] = []
        already: list[int] = []
        for uid in active_ids:
            row = get_access_row(cursor, oid, uid)
            if row is None:
                to_insert.append(uid)
                continue
            if bool(row.get("allow_switch_role")):
                before_on += 1
                already.append(uid)
            else:
                to_update.append(uid)
        report["role_on_before"] = before_on
        report["already_on"] = len(already)

        if dry_run:
            report["rows_inserted"] = len(to_insert)
            report["rows_updated"] = len(to_update)
            report["role_on_after"] = before_on + len(to_insert) + len(to_update)
            report["user_ids_enabled"] = sorted(to_insert + to_update)
            return report

        actor = int(actor_user_id) if actor_user_id is not None else None
        defaults = _new_employee_default_grants()
        for uid in to_insert:
            cursor.execute(
                f"""
                INSERT INTO {ACCESS_TABLE}
                  (organization_id, user_id,
                   allow_clock, allow_switch_role, allow_checklist,
                   allow_inventory, allow_revenue_cost, allow_team_status,
                   updated_by_user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    oid,
                    int(uid),
                    1 if defaults["clock"] else 0,
                    1 if defaults["switch_role"] else 0,
                    1 if defaults["checklist"] else 0,
                    1 if defaults["inventory"] else 0,
                    1 if defaults["revenue_cost"] else 0,
                    1 if defaults["team_status"] else 0,
                    actor,
                ),
            )
        for uid in to_update:
            cursor.execute(
                f"""
                UPDATE {ACCESS_TABLE}
                SET allow_switch_role = 1,
                    updated_by_user_id = %s
                WHERE organization_id = %s AND user_id = %s
                """,
                (actor, oid, int(uid)),
            )
        conn.commit()
        report["rows_inserted"] = len(to_insert)
        report["rows_updated"] = len(to_update)
        report["role_on_after"] = before_on + len(to_insert) + len(to_update)
        report["user_ids_enabled"] = sorted(to_insert + to_update)
        return report
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def serialize_mobile_pin_access(cursor, organization_id: int, user_id: int) -> dict[str, bool]:
    """Manager API payload — always module booleans (resolved effective grants)."""
    return resolve_employee_mobile_pin_access(cursor, organization_id, user_id)


def manager_mobile_pin_access_payload(
    cursor, organization_id: int, user_id: int
) -> dict[str, Any]:
    """Load for People UI; 404 if employee not in org."""
    ensure_employee_mobile_pin_access_tables(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    if table_exists(cursor, "users"):
        cursor.execute(
            "SELECT id FROM users WHERE id = %s AND organization_id = %s LIMIT 1",
            (uid, oid),
        )
        if not cursor.fetchone():
            raise LookupError("Employee not found")
    access = serialize_mobile_pin_access(cursor, oid, uid)
    row = get_access_row(cursor, oid, uid)
    return {
        **access,
        "has_explicit_row": row is not None,
        "org_backfilled": _org_is_backfilled(cursor, oid),
    }


def _coerce_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1, "0", "1"):
        return bool(int(value))
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError(f"{field} must be a boolean")


def save_employee_mobile_pin_access(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    grants: dict[str, Any],
    actor_user_id: Optional[int] = None,
    write_audit_fn: Optional[Callable] = None,
) -> dict[str, bool]:
    """
    Upsert all module booleans. Audits only changed modules.
    """
    ensure_employee_mobile_pin_access_tables(cursor)
    oid = int(organization_id)
    uid = int(user_id)

    if table_exists(cursor, "users"):
        cursor.execute(
            "SELECT id FROM users WHERE id = %s AND organization_id = %s LIMIT 1",
            (uid, oid),
        )
        if not cursor.fetchone():
            raise LookupError("Employee not found")

    before = serialize_mobile_pin_access(cursor, oid, uid)
    after: dict[str, bool] = {}
    for key in MODULE_KEYS:
        if key not in grants:
            raise ValueError(f"Missing required field: {key}")
        after[key] = _coerce_bool(grants[key], key)

    cursor.execute(
        f"""
        INSERT INTO {ACCESS_TABLE}
          (organization_id, user_id,
           allow_clock, allow_switch_role, allow_checklist,
           allow_inventory, allow_revenue_cost, allow_team_status,
           updated_by_user_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
          allow_clock = VALUES(allow_clock),
          allow_switch_role = VALUES(allow_switch_role),
          allow_checklist = VALUES(allow_checklist),
          allow_inventory = VALUES(allow_inventory),
          allow_revenue_cost = VALUES(allow_revenue_cost),
          allow_team_status = VALUES(allow_team_status),
          updated_by_user_id = VALUES(updated_by_user_id),
          updated_at = NOW()
        """,
        (
            oid,
            uid,
            1 if after["clock"] else 0,
            1 if after["switch_role"] else 0,
            1 if after["checklist"] else 0,
            1 if after["inventory"] else 0,
            1 if after["revenue_cost"] else 0,
            1 if after["team_status"] else 0,
            int(actor_user_id) if actor_user_id is not None else None,
        ),
    )

    changed = {
        k: {"prior": before[k], "new": after[k]}
        for k in MODULE_KEYS
        if before.get(k) != after.get(k)
    }
    if changed and write_audit_fn:
        write_audit_fn(
            actor_user_id,
            AUDIT_ENTITY,
            uid,
            AUDIT_ACTION,
            old={"modules": {k: v["prior"] for k, v in changed.items()}},
            new={"modules": {k: v["new"] for k, v in changed.items()}},
            organization_id=oid,
        )

    return after
