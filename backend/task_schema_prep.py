"""Idempotent Task Management schema preparation.

Runtime ``ensure_*`` functions add missing tables and nullable columns.
This module lists the release-candidate shape and can validate it.
It does not connect to a database and does not backfill participation or acknowledgments.
NULL ``participation_sessions_json`` keeps the historical start, finish, and duration.
"""

from __future__ import annotations

from typing import Any

EXPECTED_COLUMNS = {
    "cleaning_task_activities": (
        "shared_session_id",
        "participation_sessions_json",
        "verification_required",
        "verification_method",
        "verification_timing",
    ),
    "cleaning_task_shared_sessions": ("participation_adjustments_json",),
    "cleaning_task_shared_session_items": ("acknowledgment_mode", "responsibility_snapshot_json", "definition_snapshot_json"),
    "cleaning_task_shared_item_checks": ("status", "completed_at", "user_id", "session_item_id"),
    "task_activity_groups": ("archived", "verification_inherits", "verification_method", "verification_timing"),
    "task_activity_group_items": (
        "acknowledgment_mode",
        "verification_inherits",
        "active",
        "required",
    ),
}


def prepare_task_management_schema(cursor) -> dict[str, Any]:
    """Create missing tables and columns. Safe to run more than once. Does not update old rows."""
    from backend.cleaning_task_record_management import ensure_record_management_schema
    from backend.cleaning_task_shared_execution import ensure_shared_activity_schema
    from backend.task_activity_groups import ensure_task_activity_group_tables
    from backend.task_verification_policy import ensure_verification_policy_schema

    ensure_task_activity_group_tables(cursor)
    ensure_verification_policy_schema(cursor)
    ensure_shared_activity_schema(cursor)
    ensure_record_management_schema(cursor)
    return validate_task_management_schema(cursor)


def validate_task_management_schema(cursor) -> dict[str, Any]:
    from backend.ta_helpers import table_exists, table_has_column

    missing: list[str] = []
    present: list[str] = []
    for table, columns in EXPECTED_COLUMNS.items():
        if not table_exists(cursor, table):
            missing.append(table)
            continue
        for column in columns:
            key = f"{table}.{column}"
            if table_has_column(cursor, table, column):
                present.append(key)
            else:
                missing.append(key)
    return {"ok": not missing, "present": present, "missing": missing}
