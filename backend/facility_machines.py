"""Authoritative machine register built from the existing rack identifiers.

Scan chronology, machine configuration, and Report Incident already use the
same washer and dryer codes. This register gives those codes a stable row,
status, and cleaning eligibility. It does not invent codes and does not
rewrite a code that is already stored.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from backend.machine_configuration_settings import get_machine_rack_config
from backend.ta_helpers import invalidate_table_schema, once_per_cursor, table_exists

MACHINES = "facility_machines"
EVENTS = "facility_machine_events"
EXCLUSIONS = "facility_machine_exclusions"

STATUSES = frozenset(
    {"operational", "needs_attention", "out_of_service", "under_repair", "retired"}
)


@once_per_cursor("facility_machines")
def ensure_facility_machine_tables(cursor) -> None:
    if not table_exists(cursor, MACHINES):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MACHINES} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              machine_code VARCHAR(40) NOT NULL,
              machine_type VARCHAR(16) NOT NULL,
              display_number VARCHAR(40) NOT NULL,
              area VARCHAR(80) NULL,
              capacity_lbs DECIMAL(8,2) NULL,
              operational_status VARCHAR(32) NOT NULL DEFAULT 'operational',
              cleaning_eligible TINYINT(1) NOT NULL DEFAULT 1,
              exclusion_review TINYINT(1) NOT NULL DEFAULT 0,
              remarks VARCHAR(500) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_facility_machine (organization_id, machine_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(MACHINES)
    if not table_exists(cursor, EVENTS):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EVENTS} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              machine_code VARCHAR(40) NOT NULL,
              event_type VARCHAR(40) NOT NULL,
              actor_user_id INT NULL,
              detail VARCHAR(500) NULL,
              before_json TEXT NULL,
              after_json TEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_machine_events (organization_id, machine_code, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(EVENTS)
    if not table_exists(cursor, EXCLUSIONS):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EXCLUSIONS} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              machine_code VARCHAR(40) NOT NULL,
              reason VARCHAR(255) NOT NULL,
              effective_start DATE NOT NULL,
              effective_end DATE NULL,
              actor_user_id INT NULL,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_machine_excl (organization_id, machine_code, active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(EXCLUSIONS)


def codes_missing_from_register(
    existing_codes: set[str],
    rack: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """New rows only. An existing code keeps its status, remarks, and eligibility."""
    rows: list[dict[str, Any]] = []
    for machine_type, key in (("washer", "washers"), ("dryer", "dryers")):
        for code, capacity in (rack.get(key) or {}).items():
            token = str(code or "").strip()
            if not token or token in existing_codes:
                continue
            rows.append(
                {
                    "machine_code": token,
                    "machine_type": machine_type,
                    "display_number": token,
                    "capacity_lbs": capacity,
                    "operational_status": "operational",
                    "cleaning_eligible": True,
                }
            )
            existing_codes.add(token)
    return rows


def sync_register_from_racks(cursor, organization_id: int) -> int:
    """Add rack codes that are not yet registered. Does not update existing rows."""
    ensure_facility_machine_tables(cursor)
    rack = get_machine_rack_config(cursor, int(organization_id))
    cursor.execute(
        f"SELECT machine_code FROM {MACHINES} WHERE organization_id=%s",
        (int(organization_id),),
    )
    existing = set()
    for row in cursor.fetchall() or []:
        code = row.get("machine_code") if isinstance(row, dict) else row[0]
        if code:
            existing.add(str(code))
    fresh = codes_missing_from_register(existing, rack)
    for row in fresh:
        cursor.execute(
            f"""
            INSERT IGNORE INTO {MACHINES} (
              organization_id, machine_code, machine_type, display_number, capacity_lbs,
              operational_status, cleaning_eligible
            ) VALUES (%s,%s,%s,%s,%s,%s,1)
            """,
            (
                int(organization_id),
                row["machine_code"],
                row["machine_type"],
                row["display_number"],
                row["capacity_lbs"],
                row["operational_status"],
            ),
        )
    return len(fresh)


def list_machines(cursor, organization_id: int, *, machine_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    ensure_facility_machine_tables(cursor)
    sync_register_from_racks(cursor, int(organization_id))
    sql = f"SELECT * FROM {MACHINES} WHERE organization_id=%s"
    params: list[Any] = [int(organization_id)]
    if machine_type in ("washer", "dryer"):
        sql += " AND machine_type=%s"
        params.append(machine_type)
    if status in STATUSES:
        sql += " AND operational_status=%s"
        params.append(status)
    sql += " ORDER BY machine_type, display_number"
    cursor.execute(sql, tuple(params))
    rows = [_public_machine(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]
    reasons = {}
    for exclusion in list_exclusions(cursor, int(organization_id)):
        reasons.setdefault(str(exclusion.get("machine_code") or ""), str(exclusion.get("reason") or ""))
    cleaned = set()
    if table_exists(cursor, "task_machine_cleanings"):
        from backend.business_time import business_today
        from backend.planned_weekly_schedule import normalize_week_start
        from backend.rinse_scan_time import system_datetime_to_et

        week = normalize_week_start(business_today())
        cursor.execute(
            """
            SELECT machine_code, completed_at FROM task_machine_cleanings
            WHERE organization_id=%s
            """,
            (int(organization_id),),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            completed = system_datetime_to_et(row.get("completed_at"))
            if not completed or not week or normalize_week_start(completed.date()) != week:
                continue
            if row.get("machine_code"):
                cleaned.add(str(row["machine_code"]))
    for row in rows:
        row["exclusion_reason"] = reasons.get(row["machine_code"])
        if row["exclusion_reason"]:
            row["cleaning_eligible"] = False
        row["cleaned_this_week"] = row["machine_code"] in cleaned
    return rows


def _public_machine(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "machine_code": str(row.get("machine_code") or ""),
        "machine_type": str(row.get("machine_type") or ""),
        "display_number": str(row.get("display_number") or row.get("machine_code") or ""),
        "area": row.get("area"),
        "capacity_lbs": float(row["capacity_lbs"]) if row.get("capacity_lbs") not in (None, "") else None,
        "operational_status": str(row.get("operational_status") or "operational"),
        "cleaning_eligible": bool(row.get("cleaning_eligible", True)),
        "exclusion_review": bool(row.get("exclusion_review")),
        "remarks": row.get("remarks"),
    }


def _audit(cursor, organization_id: int, machine_code: str, event_type: str, actor_user_id: int | None, detail: str, before: Any, after: Any) -> None:
    cursor.execute(
        f"""
        INSERT INTO {EVENTS} (
          organization_id, machine_code, event_type, actor_user_id, detail, before_json, after_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            machine_code,
            event_type,
            int(actor_user_id) if actor_user_id else None,
            detail[:500],
            json.dumps(before, default=str),
            json.dumps(after, default=str),
        ),
    )


def update_machine(cursor, organization_id: int, machine_code: str, data: Mapping[str, Any], *, actor_user_id: int | None) -> dict[str, Any]:
    ensure_facility_machine_tables(cursor)
    cursor.execute(
        f"SELECT * FROM {MACHINES} WHERE organization_id=%s AND machine_code=%s LIMIT 1",
        (int(organization_id), machine_code),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        raise ValueError("Machine is not in the register")
    status = str(data.get("operational_status") or row.get("operational_status") or "operational")
    if status not in STATUSES:
        raise ValueError("Unknown machine status")
    remarks = data.get("remarks", row.get("remarks"))
    area = data.get("area", row.get("area"))
    review = 1 if status in ("out_of_service", "under_repair") else int(row.get("exclusion_review") or 0)
    if "clear_exclusion_review" in data and data.get("clear_exclusion_review"):
        review = 0
    before = _public_machine(row)
    cursor.execute(
        f"""
        UPDATE {MACHINES}
        SET operational_status=%s, remarks=%s, area=%s, exclusion_review=%s
        WHERE organization_id=%s AND machine_code=%s
        """,
        (status, remarks, area, review, int(organization_id), machine_code),
    )
    after = {**before, "operational_status": status, "remarks": remarks, "area": area, "exclusion_review": bool(review)}
    _audit(cursor, organization_id, machine_code, "status_changed", actor_user_id, status, before, after)
    return after


def exclude_machine(
    cursor,
    organization_id: int,
    machine_code: str,
    *,
    reason: str,
    effective_start: str,
    effective_end: str | None,
    actor_user_id: int | None,
) -> None:
    text = " ".join(str(reason or "").split())
    if not text:
        raise ValueError("An exclusion reason is required")
    ensure_facility_machine_tables(cursor)
    cursor.execute(
        f"""
        INSERT INTO {EXCLUSIONS} (
          organization_id, machine_code, reason, effective_start, effective_end, actor_user_id
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            machine_code,
            text[:255],
            effective_start,
            effective_end or None,
            int(actor_user_id) if actor_user_id else None,
        ),
    )
    _audit(
        cursor,
        organization_id,
        machine_code,
        "cleaning_excluded",
        actor_user_id,
        text,
        None,
        {"effective_start": effective_start, "effective_end": effective_end},
    )


def end_exclusion(cursor, organization_id: int, exclusion_id: int, *, actor_user_id: int | None) -> None:
    ensure_facility_machine_tables(cursor)
    cursor.execute(
        f"""
        UPDATE {EXCLUSIONS}
        SET active=0, effective_end=COALESCE(effective_end, CURRENT_DATE)
        WHERE organization_id=%s AND id=%s
        """,
        (int(organization_id), int(exclusion_id)),
    )
    _audit(cursor, organization_id, "", "cleaning_exclusion_ended", actor_user_id, str(exclusion_id), None, {"id": exclusion_id})


def list_events(cursor, organization_id: int, machine_code: str) -> list[dict[str, Any]]:
    ensure_facility_machine_tables(cursor)
    cursor.execute(
        f"""
        SELECT event_type, actor_user_id, detail, created_at
        FROM {EVENTS}
        WHERE organization_id=%s AND machine_code=%s
        ORDER BY id DESC
        LIMIT 40
        """,
        (int(organization_id), machine_code),
    )
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def list_exclusions(cursor, organization_id: int, machine_code: str | None = None) -> list[dict[str, Any]]:
    ensure_facility_machine_tables(cursor)
    sql = f"SELECT * FROM {EXCLUSIONS} WHERE organization_id=%s AND active=1"
    params: list[Any] = [int(organization_id)]
    if machine_code:
        sql += " AND machine_code=%s"
        params.append(machine_code)
    cursor.execute(sql, tuple(params))
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def related_issue_reports(cursor, organization_id: int, machine_code: str) -> list[dict[str, Any]]:
    """Every report that names this machine. Reports are not merged."""
    if not table_exists(cursor, "found_items"):
        return []
    cursor.execute(
        """
        SELECT id, status, report_category, location_kind, location_number, location_label,
               description, created_at, reported_by_user_id
        FROM found_items
        WHERE organization_id=%s AND (location_number=%s OR location_label LIKE %s)
        ORDER BY id DESC
        LIMIT 50
        """,
        (int(organization_id), machine_code, f"%{machine_code}%"),
    )
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]
