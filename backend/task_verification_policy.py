"""Verification policy hierarchy for Task Management.

Resolution order (prospective):
  Global org default → Activity Group override → Individual Task override

Effective policy is snapshotted onto cleaning_task_activities at start/submit time
so later config edits do not rewrite historical records.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column
from backend.task_catalog import (
    VERIFY_EMPLOYEE,
    VERIFY_METHODS,
    VERIFY_NONE,
    VERIFY_ROLE,
    VERIFY_SUPERVISOR,
    VERIFY_TIMING_SAME_SHIFT,
    VERIFY_TIMINGS,
)

ORG_SETTINGS_TABLE = "task_verification_org_settings"

DEFAULT_GLOBAL_POLICY: dict[str, Any] = {
    "verification_required": True,
    "verification_method": VERIFY_SUPERVISOR,
    "verification_timing": VERIFY_TIMING_SAME_SHIFT,
    "verifier_config": {},
}


class VerificationPolicyError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ensure_verification_policy_schema(cursor) -> None:
    """Additive schema for global defaults + inherit/override columns."""
    if not table_exists(cursor, ORG_SETTINGS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SETTINGS_TABLE} (
              organization_id INT NOT NULL PRIMARY KEY,
              verification_required TINYINT(1) NOT NULL DEFAULT 1,
              verification_method VARCHAR(32) NOT NULL DEFAULT 'supervisor',
              verification_timing VARCHAR(32) NOT NULL DEFAULT 'same_shift',
              verifier_config_json TEXT NULL,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              updated_by_user_id INT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if table_exists(cursor, "task_activity_groups"):
        _ensure_column(
            cursor,
            "task_activity_groups",
            "verification_inherits",
            "TINYINT(1) NOT NULL DEFAULT 1",
        )
        _ensure_column(cursor, "task_activity_groups", "verification_required", "TINYINT(1) NULL")
        _ensure_column(cursor, "task_activity_groups", "verification_method", "VARCHAR(32) NULL")
        _ensure_column(cursor, "task_activity_groups", "verification_timing", "VARCHAR(32) NULL")
        _ensure_column(cursor, "task_activity_groups", "verifier_config_json", "TEXT NULL")
    if table_exists(cursor, "weekly_schedule_roles"):
        _ensure_column(
            cursor,
            "weekly_schedule_roles",
            "verification_inherits",
            "TINYINT(1) NOT NULL DEFAULT 0",
        )
    invalidate_schema_cache()


def _ensure_column(cursor, table: str, column: str, ddl: str) -> None:
    if table_has_column(cursor, table, column):
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _parse_json(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _normalize_policy_fields(
    *,
    verification_required: Any,
    verification_method: Any,
    verification_timing: Any,
    verifier_config: Any = None,
) -> dict[str, Any]:
    method = str(verification_method or VERIFY_SUPERVISOR).strip().lower()
    if method not in VERIFY_METHODS:
        raise VerificationPolicyError("Invalid verification_method.")
    timing = str(verification_timing or VERIFY_TIMING_SAME_SHIFT).strip().lower()
    if timing not in VERIFY_TIMINGS:
        raise VerificationPolicyError("Invalid verification_timing.")
    required = bool(verification_required) if verification_required is not None else method != VERIFY_NONE
    if method == VERIFY_NONE:
        required = False
    elif not required:
        # Explicit "not required" must use method=none (no silent none with required flag).
        method = VERIFY_NONE
        required = False
    config = verifier_config if isinstance(verifier_config, dict) else _parse_json(verifier_config, {})
    if not isinstance(config, dict):
        config = {}
    return {
        "verification_required": required,
        "verification_method": method if required else VERIFY_NONE,
        "verification_timing": timing,
        "verifier_config": config,
    }


def get_global_verification_policy(cursor, organization_id: int) -> dict[str, Any]:
    ensure_verification_policy_schema(cursor)
    oid = int(organization_id)
    cursor.execute(
        f"SELECT * FROM {ORG_SETTINGS_TABLE} WHERE organization_id=%s LIMIT 1",
        (oid,),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        policy = dict(DEFAULT_GLOBAL_POLICY)
        policy.update(
            {
                "organization_id": oid,
                "source": "global_default",
                "inherited": False,
                "is_default": True,
            }
        )
        return policy
    normalized = _normalize_policy_fields(
        verification_required=row.get("verification_required"),
        verification_method=row.get("verification_method"),
        verification_timing=row.get("verification_timing"),
        verifier_config=row.get("verifier_config_json"),
    )
    normalized.update(
        {
            "organization_id": oid,
            "source": "global",
            "inherited": False,
            "is_default": False,
            "updated_by_user_id": (
                int(row["updated_by_user_id"]) if row.get("updated_by_user_id") is not None else None
            ),
        }
    )
    return normalized


def upsert_global_verification_policy(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
    *,
    updated_by_user_id: int | None = None,
) -> dict[str, Any]:
    ensure_verification_policy_schema(cursor)
    oid = int(organization_id)
    method = str(data.get("verification_method") or VERIFY_SUPERVISOR)
    # Intentional "not required" only via explicit none / verification_required=false.
    if data.get("verification_required") is False or method == VERIFY_NONE:
        method = VERIFY_NONE
    normalized = _normalize_policy_fields(
        verification_required=data.get("verification_required", method != VERIFY_NONE),
        verification_method=method,
        verification_timing=data.get("verification_timing"),
        verifier_config=data.get("verifier_config")
        if "verifier_config" in data
        else data.get("verifier_config_json"),
    )
    config_json = json.dumps(normalized["verifier_config"])
    cursor.execute(
        f"""
        INSERT INTO {ORG_SETTINGS_TABLE} (
          organization_id, verification_required, verification_method,
          verification_timing, verifier_config_json, updated_by_user_id
        ) VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          verification_required=VALUES(verification_required),
          verification_method=VALUES(verification_method),
          verification_timing=VALUES(verification_timing),
          verifier_config_json=VALUES(verifier_config_json),
          updated_by_user_id=VALUES(updated_by_user_id)
        """,
        (
            oid,
            1 if normalized["verification_required"] else 0,
            normalized["verification_method"],
            normalized["verification_timing"],
            config_json,
            int(updated_by_user_id) if updated_by_user_id is not None else None,
        ),
    )
    return get_global_verification_policy(cursor, oid)


def policy_from_mapping(
    row: Mapping[str, Any] | None,
    *,
    inherits_key: str = "verification_inherits",
) -> tuple[bool, dict[str, Any] | None]:
    """Return (inherits, explicit_policy_or_None)."""
    if not row:
        return True, None
    inherits = bool(row.get(inherits_key, True))
    if inherits:
        return True, None
    return False, _normalize_policy_fields(
        verification_required=row.get("verification_required"),
        verification_method=row.get("verification_method"),
        verification_timing=row.get("verification_timing"),
        verifier_config=row.get("verifier_config")
        if "verifier_config" in row
        else row.get("verifier_config_json"),
    )


def resolve_verification_policy(
    cursor,
    organization_id: int,
    *,
    task_code: str | None = None,
    activity_group: Mapping[str, Any] | None = None,
    task_definition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve Global → Group → Task. Does not mutate historical activity rows."""
    ensure_verification_policy_schema(cursor)
    global_policy = get_global_verification_policy(cursor, int(organization_id))
    chain: list[str] = ["global"]
    effective = {
        "verification_required": bool(global_policy["verification_required"]),
        "verification_method": str(global_policy["verification_method"]),
        "verification_timing": str(global_policy["verification_timing"]),
        "verifier_config": dict(global_policy.get("verifier_config") or {}),
    }
    inherited_from = "global"

    if activity_group is not None:
        group_inherits, group_policy = policy_from_mapping(activity_group)
        if not group_inherits and group_policy:
            effective = dict(group_policy)
            inherited_from = "activity_group"
            chain.append("activity_group_override")
        else:
            chain.append("activity_group_inherit")

    task_row = task_definition
    if task_row is None and task_code:
        from backend.task_catalog import get_task_definition

        # Load raw-ish definition; may include verification_inherits after catalog update.
        task_row = get_task_definition(cursor, int(organization_id), str(task_code))

    if task_row is not None:
        # Synthetic agroup_* roles are containers — don't treat as task overrides.
        code = str(task_row.get("code") or task_code or "")
        if not code.startswith("agroup_"):
            task_inherits = bool(task_row.get("verification_inherits", False))
            if not task_inherits:
                task_policy = _normalize_policy_fields(
                    verification_required=task_row.get("verification_required"),
                    verification_method=task_row.get("verification_method"),
                    verification_timing=task_row.get("verification_timing"),
                    verifier_config=task_row.get("verifier_config"),
                )
                effective = dict(task_policy)
                inherited_from = "task"
                chain.append("task_override")
            else:
                chain.append("task_inherit")

    return {
        **effective,
        "source": inherited_from,
        "resolution_chain": chain,
        "inherited": inherited_from != "task",
        "policy_snapshot": {
            "verification_required": effective["verification_required"],
            "verification_method": effective["verification_method"],
            "verification_timing": effective["verification_timing"],
            "verifier_config": effective["verifier_config"],
            "source": inherited_from,
        },
    }


def snapshot_columns(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Values to persist on a new activity row."""
    required = bool(policy.get("verification_required"))
    method = str(policy.get("verification_method") or VERIFY_SUPERVISOR)
    if not required:
        method = VERIFY_NONE
    return {
        "verification_required": 1 if required and method != VERIFY_NONE else 0,
        "verification_method": method if required and method != VERIFY_NONE else VERIFY_NONE,
        "verification_timing": str(policy.get("verification_timing") or VERIFY_TIMING_SAME_SHIFT),
        "verifier_config": dict(policy.get("verifier_config") or {}),
    }


def shared_assignment_participant_user_ids(
    cursor,
    *,
    organization_id: int,
    assignment_group_id: str | None,
    business_date: date | str | None,
) -> set[int]:
    """Employees on the same shared assignment for the business date (schedule + activities)."""
    gid = str(assignment_group_id or "").strip()
    if not gid:
        return set()
    oid = int(organization_id)
    day = business_date
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day[:10])
        except ValueError:
            day = None
    out: set[int] = set()

    cursor.execute(
        """
        SELECT DISTINCT user_id
        FROM planned_weekly_schedule_responsibilities
        WHERE organization_id=%s AND assignment_group_id=%s
        """,
        (oid, gid),
    )
    for row in cursor.fetchall() or []:
        if row.get("user_id") is not None:
            out.add(int(row["user_id"]))

    if day is not None:
        cursor.execute(
            """
            SELECT DISTINCT user_id
            FROM cleaning_task_activities
            WHERE organization_id=%s
              AND assignment_group_id=%s
              AND business_date=%s
            """,
            (oid, gid, day),
        )
        for row in cursor.fetchall() or []:
            if row.get("user_id") is not None:
                out.add(int(row["user_id"]))
    return out


def verifier_is_shared_co_participant(
    cursor,
    *,
    organization_id: int,
    activity: Mapping[str, Any],
    verifier_user_id: int,
) -> bool:
    """True when verifier is another participant on the same shared assignment."""
    vid = int(verifier_user_id)
    owner = int(activity.get("user_id") or 0)
    if vid == owner:
        return True
    participants = shared_assignment_participant_user_ids(
        cursor,
        organization_id=int(organization_id),
        assignment_group_id=activity.get("assignment_group_id"),
        business_date=activity.get("business_date"),
    )
    return vid in participants


def annotate_policy_for_api(policy: Mapping[str, Any], *, layer: str) -> dict[str, Any]:
    """UI helper: inherited vs overridden label."""
    source = str(policy.get("source") or layer)
    inherits = source in {"global", "activity_group"} and layer == "task"
    if layer == "activity_group":
        inherits = source == "global"
    if layer == "global":
        inherits = False
    return {
        **dict(policy),
        "verification_policy_label": (
            "Inherited"
            if inherits or (layer != "global" and source == "global")
            else "Overridden"
            if source in {"task", "activity_group"} and layer != "global"
            else "Global default"
        ),
        "verification_inherits_effective": bool(
            (layer == "task" and source != "task")
            or (layer == "activity_group" and source == "global")
        ),
    }
