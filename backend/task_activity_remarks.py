"""Append-only remarks for an activity assignment and its checklist items.

The older employee_remark and supervisor_remark objects inside
completion_input_json stay as a latest-value cache. The log in
``task_activity_remarks`` is the history. A later remark inserts a row.
It does not replace an earlier author's row.

Rejection reasons stay on the activity row and are not remarks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from backend.ta_helpers import once_per_cursor, table_exists, table_has_column

ET = ZoneInfo("America/New_York")

TABLE = "task_activity_remarks"
ROLES = frozenset({"employee", "supervisor", "management"})
LEGACY_EMPLOYEE = "employee_remark"
LEGACY_SUPERVISOR = "supervisor_remark"
BODY_MAX = 1000


def _relax_schema(cursor, sql: str) -> None:
    try:
        cursor.execute(sql)
    except Exception as exc:
        text = str(exc).lower()
        if "duplicate" in text or "exists" in text or "check that column" in text:
            return
        raise


@once_per_cursor("task_activity_remarks")
def ensure_task_activity_remarks_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          activity_id INT NOT NULL,
          assignment_group_id VARCHAR(64) NULL,
          task_code VARCHAR(64) NULL,
          author_user_id INT NOT NULL,
          author_name VARCHAR(120) NULL,
          author_role VARCHAR(32) NOT NULL,
          body VARCHAR(1000) NOT NULL,
          created_at DATETIME NULL,
          created_at_utc DATETIME NULL,
          legacy_source VARCHAR(32) NULL,
          INDEX idx_tar_activity (organization_id, activity_id, id),
          INDEX idx_tar_assignment (organization_id, assignment_group_id, id),
          UNIQUE KEY uq_tar_legacy (organization_id, activity_id, legacy_source)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    if table_exists(cursor, TABLE) and not table_has_column(cursor, TABLE, "created_at_utc"):
        _relax_schema(cursor, f"ALTER TABLE {TABLE} ADD COLUMN created_at_utc DATETIME NULL")
    _relax_schema(
        cursor,
        f"ALTER TABLE {TABLE} MODIFY author_name VARCHAR(120) NULL, MODIFY created_at DATETIME NULL",
    )
    _relax_schema(cursor, f"ALTER TABLE {TABLE} ADD COLUMN remark_kind VARCHAR(32) NULL")


def _stamp(at) -> str:
    if at is None or at == "":
        return ""
    if hasattr(at, "strftime"):
        return at.strftime("%Y-%m-%d %H:%M:%S")
    return str(at)[:19]


def et_wall_to_utc(wall: datetime) -> datetime | None:
    """Convert an Eastern wall time to naive UTC when the instant is unique.

    The November fallback hour and the March gap have no single UTC instant.
    Those return None so a migration does not invent one.
    """
    if wall.tzinfo is not None:
        return wall.astimezone(timezone.utc).replace(tzinfo=None)
    first = wall.replace(tzinfo=ET)
    second = wall.replace(tzinfo=ET, fold=1)
    utc_first = first.astimezone(timezone.utc).replace(tzinfo=None)
    utc_second = second.astimezone(timezone.utc).replace(tzinfo=None)
    if utc_first != utc_second:
        return None
    # A spring-forward gap maps both folds onto the same later instant.
    back = utc_first.replace(tzinfo=timezone.utc).astimezone(ET).replace(tzinfo=None)
    if back != wall:
        return None
    return utc_first


def parse_et_wall(value: Any) -> datetime | None:
    text = _stamp(value)
    if len(text) < 19:
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def remark_now() -> tuple[datetime, datetime]:
    """Current Eastern wall time and its UTC instant."""
    from backend.rinse_folding_et import eastern_now

    aware = eastern_now()
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=ET)
    wall = aware.astimezone(ET).replace(tzinfo=None)
    utc = aware.astimezone(timezone.utc).replace(tzinfo=None)
    return wall, utc


def remark_time_label(wall: Any, utc_value: Any = None) -> str | None:
    utc = utc_value
    if isinstance(utc, datetime) and utc.tzinfo is not None:
        utc = utc.astimezone(timezone.utc).replace(tzinfo=None)
    if utc:
        shown = datetime.strptime(_stamp(utc), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(ET)
        return f"{shown.strftime('%Y-%m-%d %H:%M:%S')} ET ({_stamp(utc)} UTC)"
    text = _stamp(wall)
    return f"{text} ET" if text else None


def _parse_input(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _legacy_payload(raw: Any, key: str) -> dict[str, Any] | None:
    payload = _parse_input(raw)
    remark = payload.get(key)
    if not isinstance(remark, Mapping):
        return None
    text = str(remark.get("text") or "").strip()
    if not text:
        return None
    author = remark.get("author_user_id")
    return {
        "text": text[:BODY_MAX],
        "author_user_id": int(author) if author is not None else None,
        "author_name": (str(remark.get("author_name") or "").strip() or None),
        "at": str(remark.get("at") or "")[:19] or None,
        "role": "supervisor" if key == LEGACY_SUPERVISOR else "employee",
    }


def _row_out(row: Mapping[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": int(row.get("id") or 0),
        "activity_id": int(row.get("activity_id") or 0),
        "assignment_group_id": (str(row.get("assignment_group_id") or "").strip() or None),
        "task_code": (str(row.get("task_code") or "").strip() or None),
        "author_user_id": int(row["author_user_id"]) if row.get("author_user_id") is not None else None,
        "author_name": (str(row.get("author_name") or "").strip() or None),
        "author_role": str(row.get("author_role") or ""),
        "body": str(row.get("body") or ""),
        "created_at": _stamp(created) or None,
        "created_at_utc": _stamp(row.get("created_at_utc")) or None,
        "created_at_label": remark_time_label(created, row.get("created_at_utc")),
        "legacy_source": (str(row.get("legacy_source") or "").strip() or None),
        "remark_kind": (str(row.get("remark_kind") or "").strip() or None),
    }


def _virtual_legacy(activity: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = activity.get("completion_input_json")
    if raw is None:
        raw = activity.get("completion_input")
    out: list[dict[str, Any]] = []
    for key in (LEGACY_EMPLOYEE, LEGACY_SUPERVISOR):
        legacy = _legacy_payload(raw, key)
        if not legacy:
            continue
        out.append(
            {
                "id": None,
                "activity_id": int(activity.get("id") or 0),
                "assignment_group_id": (str(activity.get("assignment_group_id") or "").strip() or None),
                "task_code": None,
                "author_user_id": int(legacy["author_user_id"]) if legacy.get("author_user_id") is not None else None,
                "author_name": legacy.get("author_name"),
                "author_role": legacy["role"],
                "body": legacy["text"],
                "created_at": legacy.get("at"),
                "created_at_utc": None,
                "created_at_label": f"{legacy['at']} ET" if legacy.get("at") else None,
                "legacy_source": key,
                "remark_kind": None,
            }
        )
    return out


def list_remarks_for_activity(cursor, organization_id: int, activity: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Stored rows, or the unsaved legacy pair when the log is still empty."""
    ensure_task_activity_remarks_table(cursor)
    oid = int(organization_id)
    activity_id = int(activity.get("id") or 0)
    group_id = str(activity.get("assignment_group_id") or "").strip()
    if group_id:
        cursor.execute(
            f"""
            SELECT * FROM {TABLE}
            WHERE organization_id=%s AND assignment_group_id=%s
            ORDER BY created_at ASC, id ASC
            """,
            (oid, group_id),
        )
    elif activity_id:
        cursor.execute(
            f"""
            SELECT * FROM {TABLE}
            WHERE organization_id=%s AND activity_id=%s
            ORDER BY created_at ASC, id ASC
            """,
            (oid, activity_id),
        )
    else:
        return []
    rows = [_row_out(row) for row in cursor.fetchall() or [] if isinstance(row, Mapping)]
    present = {
        (int(row.get("activity_id") or 0), row.get("legacy_source"))
        for row in rows
        if row.get("legacy_source")
    }
    for legacy in _virtual_legacy(activity):
        key = (int(legacy.get("activity_id") or 0), legacy.get("legacy_source"))
        if key not in present:
            rows.append(legacy)
    return rows


def remarks_index_for_assignments(
    cursor,
    organization_id: int,
    assignments: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """One query for the assignment groups and parent activities on a dashboard payload."""
    ensure_task_activity_remarks_table(cursor)
    group_ids = sorted(
        {
            str(row.get("assignment_group_id") or "").strip()
            for row in assignments
            if str(row.get("assignment_group_id") or "").strip()
        }
    )
    activity_ids: set[int] = set()
    for row in assignments:
        for contrib in row.get("contributions") or []:
            act = contrib.get("activity") if isinstance(contrib, Mapping) else None
            if isinstance(act, Mapping) and act.get("id"):
                activity_ids.add(int(act["id"]))
            elif isinstance(contrib, Mapping) and contrib.get("activity_id"):
                activity_ids.add(int(contrib["activity_id"]))
    fetched: list[dict[str, Any]] = []
    oid = int(organization_id)
    if group_ids:
        placeholders = ", ".join(["%s"] * len(group_ids))
        cursor.execute(
            f"""
            SELECT * FROM {TABLE}
            WHERE organization_id=%s AND assignment_group_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            """,
            (oid, *group_ids),
        )
        fetched.extend(_row_out(row) for row in cursor.fetchall() or [] if isinstance(row, Mapping))
    if activity_ids:
        ids = sorted(activity_ids)
        placeholders = ", ".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT * FROM {TABLE}
            WHERE organization_id=%s AND activity_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            """,
            (oid, *ids),
        )
        fetched.extend(_row_out(row) for row in cursor.fetchall() or [] if isinstance(row, Mapping))
    by_key: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, int]] = set()
    for remark in fetched:
        keys = []
        if remark.get("assignment_group_id"):
            keys.append(f"group:{remark['assignment_group_id']}")
        if remark.get("activity_id"):
            keys.append(f"activity:{remark['activity_id']}")
        for key in keys:
            marker = (key, int(remark.get("id") or 0))
            if marker in seen:
                continue
            seen.add(marker)
            by_key.setdefault(key, []).append(remark)
    return by_key


def attach_remarks(assignments: Sequence[dict[str, Any]], index: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    for row in assignments:
        group_id = str(row.get("assignment_group_id") or "").strip()
        remarks: list[dict[str, Any]] = []
        seen: set[int] = set()
        if group_id:
            for remark in index.get(f"group:{group_id}") or []:
                rid = int(remark.get("id") or 0)
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                remarks.append(dict(remark))
        if not remarks:
            for contrib in row.get("contributions") or []:
                act = contrib.get("activity") if isinstance(contrib, Mapping) else None
                activity_id = None
                if isinstance(act, Mapping) and act.get("id"):
                    activity_id = int(act["id"])
                elif isinstance(contrib, Mapping) and contrib.get("activity_id"):
                    activity_id = int(contrib["activity_id"])
                if not activity_id:
                    continue
                for remark in index.get(f"activity:{activity_id}") or []:
                    rid = int(remark.get("id") or 0)
                    if rid and rid in seen:
                        continue
                    if rid:
                        seen.add(rid)
                    remarks.append(dict(remark))
                if isinstance(act, Mapping):
                    present = {
                        (int(remark.get("activity_id") or 0), remark.get("legacy_source"))
                        for remark in remarks
                        if remark.get("legacy_source")
                    }
                    for legacy in _virtual_legacy(act):
                        key = (int(legacy.get("activity_id") or 0), legacy.get("legacy_source"))
                        if key not in present:
                            remarks.append(legacy)
        row["remarks"] = remarks
        row["remark_count"] = len(remarks)


def _same_body_logged(cursor, organization_id: int, activity_id: int, role: str, body: str) -> bool:
    """True when this activity already has the same remark in the log.

    The latest-value JSON cache is not a second historical remark.
    """
    cursor.execute(
        f"""
        SELECT id FROM {TABLE}
        WHERE organization_id=%s AND activity_id=%s AND author_role=%s AND body=%s
        LIMIT 1
        """,
        (int(organization_id), int(activity_id), role, body),
    )
    return cursor.fetchone() is not None


def _legacy_already_imported(cursor, organization_id: int, activity_id: int, source: str) -> bool:
    cursor.execute(
        f"""
        SELECT id FROM {TABLE}
        WHERE organization_id=%s AND activity_id=%s AND legacy_source=%s
        LIMIT 1
        """,
        (int(organization_id), int(activity_id), source),
    )
    return cursor.fetchone() is not None


def import_legacy_remarks(cursor, organization_id: int, activity: Mapping[str, Any], names: Mapping[int, str] | None = None) -> int:
    """Copy stored employee and supervisor remarks into the log once.

    Missing author ids are left in the JSON cache and still shown from there.
    Missing names and timestamps stay empty. ``names`` is ignored so a current
    profile cannot replace a historical author who was not recorded.
    """
    del names
    ensure_task_activity_remarks_table(cursor)
    activity_id = int(activity.get("id") or 0)
    if not activity_id:
        return 0
    raw = activity.get("completion_input_json")
    if raw is None:
        raw = activity.get("completion_input")
    inserted = 0
    for key in (LEGACY_EMPLOYEE, LEGACY_SUPERVISOR):
        legacy = _legacy_payload(raw, key)
        if not legacy or legacy.get("author_user_id") is None:
            continue
        if _legacy_already_imported(cursor, organization_id, activity_id, key):
            continue
        if _same_body_logged(cursor, organization_id, activity_id, legacy["role"], legacy["text"]):
            continue
        wall = parse_et_wall(legacy.get("at"))
        utc = et_wall_to_utc(wall) if wall is not None else None
        cursor.execute(
            f"""
            INSERT INTO {TABLE}
              (organization_id, activity_id, assignment_group_id, task_code,
               author_user_id, author_name, author_role, body, created_at, created_at_utc, legacy_source,
               remark_kind)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                activity_id,
                (str(activity.get("assignment_group_id") or "").strip() or None),
                None,
                int(legacy["author_user_id"]),
                legacy.get("author_name"),
                legacy["role"],
                legacy["text"],
                wall,
                utc,
                key,
                None,
            ),
        )
        inserted += 1
    return inserted


def migrate_legacy_remarks(cursor, organization_id: int | None = None) -> dict[str, int]:
    """Copy every historical remark into the log. Repeating the call inserts nothing."""
    ensure_task_activity_remarks_table(cursor)
    sql = """
        SELECT id, organization_id, assignment_group_id, completion_input_json, rejection_reason
        FROM cleaning_task_activities
    """
    params: tuple[Any, ...] = ()
    if organization_id is not None:
        sql += " WHERE organization_id=%s"
        params = (int(organization_id),)
    cursor.execute(sql, params)
    rows = list(cursor.fetchall() or [])
    inserted = 0
    held_for_display = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        inserted += import_legacy_remarks(cursor, int(row["organization_id"]), row)
        raw = row.get("completion_input_json")
        for key in (LEGACY_EMPLOYEE, LEGACY_SUPERVISOR):
            legacy = _legacy_payload(raw, key)
            if legacy and legacy.get("author_user_id") is None:
                held_for_display += 1
    return {"inserted": inserted, "held_for_display": held_for_display}


def append_remark(
    cursor,
    *,
    organization_id: int,
    activity: Mapping[str, Any],
    author_user_id: int,
    author_name: str,
    author_role: str,
    body: str,
    task_code: str | None = None,
    names: Mapping[int, str] | None = None,
    remark_kind: str = "comment",
) -> dict[str, Any]:
    """Import any legacy single remarks, then insert this remark."""
    role = str(author_role or "").strip().lower()
    if role not in ROLES:
        raise ValueError("author_role must be employee, supervisor, or management")
    text = " ".join(str(body or "").split())
    if not text:
        raise ValueError("Remark text is required")
    if len(text) > BODY_MAX:
        raise ValueError("Remark is too long")
    import_legacy_remarks(cursor, organization_id, activity, names)
    wall, utc = remark_now()
    code = (str(task_code or "").strip() or None)
    stored_name = (str(author_name or "").strip() or None)
    kind = "verification" if str(remark_kind or "") == "verification" else "comment"
    cursor.execute(
        f"""
        INSERT INTO {TABLE}
          (organization_id, activity_id, assignment_group_id, task_code,
           author_user_id, author_name, author_role, body, created_at, created_at_utc, legacy_source,
           remark_kind)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(activity.get("id") or 0),
            (str(activity.get("assignment_group_id") or "").strip() or None),
            code,
            int(author_user_id),
            stored_name[:120] if stored_name else None,
            role,
            text[:BODY_MAX],
            wall,
            utc,
            None,
            kind,
        ),
    )
    remark_id = int(getattr(cursor, "lastrowid", 0) or 0)
    return _row_out(
        {
            "id": remark_id,
            "activity_id": int(activity.get("id") or 0),
            "assignment_group_id": activity.get("assignment_group_id"),
            "task_code": code,
            "author_user_id": int(author_user_id),
            "author_name": stored_name[:120] if stored_name else None,
            "author_role": role,
            "body": text[:BODY_MAX],
            "created_at": wall,
            "created_at_utc": utc,
            "legacy_source": None,
            "remark_kind": kind,
        }
    )
