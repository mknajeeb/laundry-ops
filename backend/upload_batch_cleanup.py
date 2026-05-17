"""
Upload batch child cleanup, orphan detection, and optional FK CASCADE migration.

Child tables:
  upload_batch_rows.upload_batch_id -> upload_batches.{id|batch_id}
  upload_batch_scan_events.upload_batch_id -> upload_batches.{id|batch_id}

Delete order (when not relying on FK CASCADE):
  1) upload_batch_rows
  2) upload_batch_scan_events
  3) upload_batches
"""

from __future__ import annotations

from typing import Any

from backend.ta_helpers import table_exists


def resolve_upload_batches_pk(cursor) -> str:
    """Primary key column on upload_batches (id preferred, else batch_id)."""
    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'id'")
    if cursor.fetchone():
        return "id"
    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'batch_id'")
    if cursor.fetchone():
        return "batch_id"
    raise ValueError("upload_batches must have id or batch_id column")


def _table_has_column(cursor, table_name: str, col_name: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (col_name,))
    return cursor.fetchone() is not None


def _fk_exists(cursor, table_name: str, constraint_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = %s
          AND CONSTRAINT_TYPE = 'FOREIGN KEY'
        """,
        (table_name, constraint_name),
    )
    row = cursor.fetchone()
    n = int(row["c"] if isinstance(row, dict) else row[0])
    return n > 0


def count_orphan_upload_batch_children(
    cursor, *, organization_id: int | None = None
) -> dict[str, Any]:
    """
    Count child rows whose upload_batch_id has no matching upload_batches parent.
    Scan-event orphans are grouped by organization_id when available.
    """
    if not table_exists(cursor, "upload_batches"):
        return {
            "upload_batch_rows": {"total": 0, "by_organization_id": {}},
            "upload_batch_scan_events": {"total": 0, "by_organization_id": {}},
        }

    pk = resolve_upload_batches_pk(cursor)
    out: dict[str, Any] = {
        "upload_batch_rows": {"total": 0, "by_organization_id": {}},
        "upload_batch_scan_events": {"total": 0, "by_organization_id": {}},
    }

    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM upload_batch_rows ubr
            LEFT JOIN upload_batches ub ON ubr.upload_batch_id = ub.{pk}
            WHERE ub.{pk} IS NULL
            """
        )
        row = cursor.fetchone() or {}
        out["upload_batch_rows"]["total"] = int(
            (row.get("c") if isinstance(row, dict) else row[0]) or 0
        )

    if table_exists(cursor, "upload_batch_scan_events"):
        org_filter = ""
        args: list[Any] = []
        if organization_id is not None:
            org_filter = " AND ubse.organization_id = %s"
            args.append(int(organization_id))
        cursor.execute(
            f"""
            SELECT ubse.organization_id, COUNT(*) AS c
            FROM upload_batch_scan_events ubse
            LEFT JOIN upload_batches ub ON ubse.upload_batch_id = ub.{pk}
            WHERE ub.{pk} IS NULL{org_filter}
            GROUP BY ubse.organization_id
            """,
            tuple(args),
        )
        by_org: dict[str, int] = {}
        total = 0
        for r in cursor.fetchall() or []:
            if not isinstance(r, dict):
                continue
            oid = int(r.get("organization_id") or 0)
            c = int(r.get("c") or 0)
            by_org[str(oid)] = c
            total += c
        out["upload_batch_scan_events"]["total"] = total
        out["upload_batch_scan_events"]["by_organization_id"] = by_org

    return out


def delete_orphan_upload_batch_children(
    cursor, *, organization_id: int | None = None
) -> dict[str, int]:
    """Delete only child rows with no parent upload_batches row."""
    deleted = {"upload_batch_rows": 0, "upload_batch_scan_events": 0}
    if not table_exists(cursor, "upload_batches"):
        return deleted

    pk = resolve_upload_batches_pk(cursor)

    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            f"""
            DELETE ubr FROM upload_batch_rows ubr
            LEFT JOIN upload_batches ub ON ubr.upload_batch_id = ub.{pk}
            WHERE ub.{pk} IS NULL
            """
        )
        deleted["upload_batch_rows"] = int(cursor.rowcount or 0)

    if table_exists(cursor, "upload_batch_scan_events"):
        org_filter = ""
        args: list[Any] = []
        if organization_id is not None:
            org_filter = " AND ubse.organization_id = %s"
            args.append(int(organization_id))
        cursor.execute(
            f"""
            DELETE ubse FROM upload_batch_scan_events ubse
            LEFT JOIN upload_batches ub ON ubse.upload_batch_id = ub.{pk}
            WHERE ub.{pk} IS NULL{org_filter}
            """,
            tuple(args),
        )
        deleted["upload_batch_scan_events"] = int(cursor.rowcount or 0)

    return deleted


def ensure_upload_batch_child_fk_cascade(
    cursor, *, cleanup_orphans: bool = True
) -> dict[str, Any]:
    """
    Remove orphan children, then add ON DELETE CASCADE FKs when missing.
    Safe to call repeatedly (idempotent).
    """
    result: dict[str, Any] = {
        "orphans_deleted": {},
        "fks_added": [],
        "fks_skipped": [],
        "errors": [],
    }
    if not table_exists(cursor, "upload_batches"):
        return result

    if cleanup_orphans:
        result["orphans_deleted"] = delete_orphan_upload_batch_children(cursor)

    pk = resolve_upload_batches_pk(cursor)
    for child_table, fk_name in (
        ("upload_batch_rows", "fk_ubr_upload_batch"),
        ("upload_batch_scan_events", "fk_ubse_upload_batch"),
    ):
        if not table_exists(cursor, child_table):
            result["fks_skipped"].append(f"{child_table}:missing")
            continue
        if not _table_has_column(cursor, child_table, "upload_batch_id"):
            result["fks_skipped"].append(f"{child_table}:no_upload_batch_id")
            continue
        if _fk_exists(cursor, child_table, fk_name):
            result["fks_skipped"].append(fk_name)
            continue
        try:
            cursor.execute(
                f"""
                ALTER TABLE {child_table}
                ADD CONSTRAINT {fk_name}
                FOREIGN KEY (upload_batch_id) REFERENCES upload_batches({pk})
                ON DELETE CASCADE
                """
            )
            result["fks_added"].append(fk_name)
        except Exception as exc:
            result["errors"].append(f"{fk_name}:{exc}")

    return result


def delete_upload_batch_rows_for_batch(cursor, upload_batch_id: int) -> int:
    if not table_exists(cursor, "upload_batch_rows"):
        return 0
    cursor.execute(
        "DELETE FROM upload_batch_rows WHERE upload_batch_id = %s",
        (int(upload_batch_id),),
    )
    return int(cursor.rowcount or 0)


def delete_upload_batch_rows_for_organization(cursor, organization_id: int) -> int:
    if not table_exists(cursor, "upload_batch_rows") or not table_exists(
        cursor, "upload_batches"
    ):
        return 0
    if not _table_has_column(cursor, "upload_batches", "organization_id"):
        cursor.execute("DELETE FROM upload_batch_rows")
        return int(cursor.rowcount or 0)
    pk = resolve_upload_batches_pk(cursor)
    cursor.execute(
        f"""
        DELETE FROM upload_batch_rows
        WHERE upload_batch_id IN (
            SELECT {pk} FROM upload_batches WHERE organization_id = %s
        )
        """,
        (int(organization_id),),
    )
    return int(cursor.rowcount or 0)


def delete_children_for_upload_batch(
    cursor,
    upload_batch_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, int]:
    """Delete upload_batch_rows then upload_batch_scan_events for one batch."""
    rows_deleted = delete_upload_batch_rows_for_batch(cursor, upload_batch_id)
    from backend.rinse_scan_events_upload import delete_upload_batch_scan_events_for_batch

    scan_deleted = delete_upload_batch_scan_events_for_batch(
        cursor, upload_batch_id, organization_id
    )
    return {
        "upload_batch_rows": rows_deleted,
        "upload_batch_scan_events": scan_deleted,
    }


def delete_upload_batch_cascade(
    cursor,
    upload_batch_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, int]:
    """
    Delete all child rows for a batch, then the upload_batches row.
  Tenant-safe when organization_id is provided and upload_batches.organization_id exists.
    """
    children = delete_children_for_upload_batch(
        cursor, upload_batch_id, organization_id=organization_id
    )
    if not table_exists(cursor, "upload_batches"):
        return {**children, "upload_batches": 0}

    pk = resolve_upload_batches_pk(cursor)
    if (
        organization_id is not None
        and _table_has_column(cursor, "upload_batches", "organization_id")
    ):
        cursor.execute(
            f"""
            DELETE FROM upload_batches
            WHERE {pk} = %s AND organization_id = %s
            """,
            (int(upload_batch_id), int(organization_id)),
        )
    else:
        cursor.execute(
            f"DELETE FROM upload_batches WHERE {pk} = %s",
            (int(upload_batch_id),),
        )
    return {**children, "upload_batches": int(cursor.rowcount or 0)}


def delete_upload_batch_children_for_organization(
    cursor, organization_id: int
) -> dict[str, int]:
    """Delete all child rows for batches belonging to organization_id."""
    rows_deleted = delete_upload_batch_rows_for_organization(cursor, organization_id)
    from backend.rinse_scan_events_upload import (
        delete_upload_batch_scan_events_for_organization,
    )

    scan_deleted = delete_upload_batch_scan_events_for_organization(
        cursor, organization_id
    )
    return {
        "upload_batch_rows": rows_deleted,
        "upload_batch_scan_events": scan_deleted,
    }


def delete_upload_batches_for_organization(cursor, organization_id: int) -> dict[str, int]:
    """Delete children then all upload_batches for a tenant."""
    children = delete_upload_batch_children_for_organization(cursor, organization_id)
    if not table_exists(cursor, "upload_batches"):
        return {**children, "upload_batches": 0}
    if not _table_has_column(cursor, "upload_batches", "organization_id"):
        cursor.execute("DELETE FROM upload_batches")
    else:
        cursor.execute(
            "DELETE FROM upload_batches WHERE organization_id = %s",
            (int(organization_id),),
        )
    return {**children, "upload_batches": int(cursor.rowcount or 0)}


def delete_all_upload_batches_global(cursor) -> dict[str, int]:
    """Delete all batches and children (no organization_id on upload_batches)."""
    rows_deleted = 0
    scan_deleted = 0
    if table_exists(cursor, "upload_batch_rows"):
        cursor.execute("DELETE FROM upload_batch_rows")
        rows_deleted = int(cursor.rowcount or 0)
    from backend.rinse_scan_events_upload import delete_all_upload_batch_scan_events

    scan_deleted = delete_all_upload_batch_scan_events(cursor)
    batches_deleted = 0
    if table_exists(cursor, "upload_batches"):
        cursor.execute("DELETE FROM upload_batches")
        batches_deleted = int(cursor.rowcount or 0)
    return {
        "upload_batch_rows": rows_deleted,
        "upload_batch_scan_events": scan_deleted,
        "upload_batches": batches_deleted,
    }
