"""MySQL persistence for the supervisor portal. Requests never create tables."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.supervisor_portal.quality import (
    STARTER_ISSUE_TYPES,
    points_for,
    week_start,
)
from backend.supervisor_portal.roles import primary_role_on
from backend.supervisor_portal.scoring import ACTIVATION_ERROR
from backend.ta_helpers import table_exists, table_has_column

MIGRATION = "backend/sql/supervisor_portal_v1.sql"


class MigrationRequired(RuntimeError):
    def __init__(self, table: str):
        super().__init__(f"Apply {MIGRATION} before using {table}")
        self.table = table


def _require(cursor, *tables: str) -> None:
    for table in tables:
        if not table_exists(cursor, table):
            raise MigrationRequired(table)


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


def _row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    return {key: _iso(value) for key, value in dict(row).items()}


def _rows(rows: Sequence[Any] | None) -> list[dict[str, Any]]:
    return [item for item in (_row(row) for row in (rows or [])) if item]


def list_adjustments(cursor, organization_id: int, business_date: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_session_adjustments"):
        return []
    cursor.execute(
        """
        SELECT * FROM supervisor_session_adjustments
        WHERE organization_id=%s AND business_date_et=%s
        ORDER BY id
        """,
        (int(organization_id), business_date),
    )
    return _rows(cursor.fetchall())


def insert_adjustment(cursor, organization_id: int, business_date: date, payload: Mapping[str, Any], actor: Mapping[str, Any]) -> dict[str, Any]:
    _require(cursor, "supervisor_session_adjustments")
    cursor.execute(
        """
        INSERT INTO supervisor_session_adjustments (
          organization_id, business_date_et, session_id, employee_user_id, employee_name,
          kind, original_start, original_end, original_hours, original_rate, original_lbs,
          eligible_start, eligible_end, eligible_hours, eligible_percent,
          reallocated_role_key, reallocated_hours, manual_rate, reason, notes,
          actor_user_id, actor_name
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            business_date,
            payload.get("session_id"),
            payload.get("employee_user_id"),
            payload.get("employee_name"),
            payload.get("kind"),
            _text(payload.get("original_start")),
            _text(payload.get("original_end")),
            payload.get("original_hours"),
            payload.get("original_rate"),
            payload.get("original_lbs"),
            _text(payload.get("eligible_start")),
            _text(payload.get("eligible_end")),
            payload.get("eligible_hours"),
            payload.get("eligible_percent"),
            payload.get("reallocated_role_key"),
            payload.get("reallocated_hours"),
            payload.get("manual_rate"),
            payload.get("reason"),
            payload.get("notes"),
            actor.get("id"),
            actor.get("name"),
        ),
    )
    return {"id": cursor.lastrowid, "ok": True}


def reverse_adjustment(cursor, organization_id: int, adjustment_id: int, *, actor_id: int | None, reason: str) -> dict[str, Any]:
    _require(cursor, "supervisor_session_adjustments")
    if not str(reason or "").strip():
        raise ValueError("A reversal reason is required")
    cursor.execute(
        """
        UPDATE supervisor_session_adjustments
        SET reversed_at=CURRENT_TIMESTAMP, reversed_by=%s, reversal_reason=%s
        WHERE organization_id=%s AND id=%s AND reversed_at IS NULL
        """,
        (actor_id, str(reason).strip()[:255], int(organization_id), int(adjustment_id)),
    )
    if getattr(cursor, "rowcount", 1) == 0:
        return {"ok": False, "error": "Adjustment is already reversed or missing"}
    return {"ok": True, "id": int(adjustment_id)}


def list_issue_types(cursor, organization_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_quality_issue_types"):
        return []
    cursor.execute(
        """
        SELECT code, label, active FROM supervisor_quality_issue_types
        WHERE organization_id=%s ORDER BY label
        """,
        (int(organization_id),),
    )
    return _rows(cursor.fetchall())


def install_starter_issue_types(cursor, organization_id: int) -> int:
    _require(cursor, "supervisor_quality_issue_types")
    count = 0
    for item in STARTER_ISSUE_TYPES:
        cursor.execute(
            """
            INSERT IGNORE INTO supervisor_quality_issue_types (organization_id, code, label, active)
            VALUES (%s,%s,%s,1)
            """,
            (int(organization_id), item["code"], item["label"]),
        )
        count += 1
    return count


def add_issue_type(cursor, organization_id: int, *, code: str, label: str) -> None:
    _require(cursor, "supervisor_quality_issue_types")
    cursor.execute(
        """
        INSERT INTO supervisor_quality_issue_types (organization_id, code, label, active)
        VALUES (%s,%s,%s,1)
        ON DUPLICATE KEY UPDATE label=VALUES(label), active=1
        """,
        (int(organization_id), code.strip().lower()[:64], label.strip()[:128]),
    )


def list_weight_versions(cursor, organization_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_quality_weight_versions"):
        return []
    cursor.execute(
        """
        SELECT id, effective_from, status, weights_json, severity_json, created_at
        FROM supervisor_quality_weight_versions
        WHERE organization_id=%s
        ORDER BY effective_from, id
        """,
        (int(organization_id),),
    )
    out = []
    for row in _rows(cursor.fetchall()):
        row["weights"] = _json(row.pop("weights_json", None))
        row["severity"] = _json(row.pop("severity_json", None))
        out.append(row)
    return out


def published_weight_version(cursor, organization_id: int, day: date) -> dict[str, Any] | None:
    versions = [
        row
        for row in list_weight_versions(cursor, organization_id)
        if row.get("status") == "published" and str(row.get("effective_from") or "") <= day.isoformat()
    ]
    return versions[-1] if versions else None


def insert_weight_version(cursor, organization_id: int, body: Mapping[str, Any], *, actor_id: int | None) -> dict[str, Any]:
    _require(cursor, "supervisor_quality_weight_versions")
    if body.get("active") in (True, 1, "1", "true"):
        raise ValueError(ACTIVATION_ERROR)
    status = str(body.get("status") or "draft").strip().lower()
    if status not in {"draft", "published"}:
        raise ValueError("Weight status must be draft or published")
    weights = body.get("weights") or {}
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("Weights are required")
    effective = date.fromisoformat(str(body.get("effective_from"))[:10])
    cursor.execute(
        """
        INSERT INTO supervisor_quality_weight_versions (
          organization_id, effective_from, status, weights_json, severity_json, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            effective,
            status,
            json.dumps(dict(weights)),
            json.dumps(dict(body.get("severity") or {})),
            actor_id,
        ),
    )
    return {"id": cursor.lastrowid, "status": status}


def list_incidents(cursor, organization_id: int, week: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_quality_incidents"):
        return []
    start = week_start(week)
    cursor.execute(
        """
        SELECT * FROM supervisor_quality_incidents
        WHERE organization_id=%s AND week_start=%s
        ORDER BY id
        """,
        (int(organization_id), start),
    )
    incidents = _rows(cursor.fetchall())
    if not incidents or not table_exists(cursor, "supervisor_quality_incident_employees"):
        return incidents
    ids = [int(row["id"]) for row in incidents]
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT incident_id, user_id, employee_name, role_key
        FROM supervisor_quality_incident_employees
        WHERE organization_id=%s AND incident_id IN ({placeholders})
        ORDER BY id
        """,
        tuple([int(organization_id), *ids]),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in _rows(cursor.fetchall()):
        grouped.setdefault(int(row["incident_id"]), []).append(row)
    for incident in incidents:
        incident["employees"] = grouped.get(int(incident["id"]), [])
        incident["employee_points"] = incident.get("points")
    return incidents


def save_incident(cursor, organization_id: int, incident: Mapping[str, Any], *, actor_id: int | None, version: Mapping[str, Any] | None) -> dict[str, Any]:
    _require(cursor, "supervisor_quality_incidents", "supervisor_quality_incident_employees")
    points = points_for(
        int(incident["quantity"]),
        str(incident["issue_type"]),
        incident.get("severity"),
        version,
    )
    cursor.execute(
        """
        SELECT id FROM supervisor_quality_incidents
        WHERE organization_id=%s AND incident_key=%s LIMIT 1
        """,
        (int(organization_id), incident["incident_key"]),
    )
    existing = cursor.fetchone()
    if isinstance(existing, Mapping) and existing.get("id"):
        incident_id = int(existing["id"])
        created = False
    else:
        cursor.execute(
            """
            INSERT INTO supervisor_quality_incidents (
              organization_id, week_start, issue_type, severity, quantity, incident_key,
              reference, notes, role_key, weight_version_id, points, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                incident["week_start"],
                incident["issue_type"],
                incident.get("severity"),
                incident["quantity"],
                incident["incident_key"],
                incident.get("reference"),
                incident.get("notes"),
                incident.get("role_key") or "GENERAL",
                (version or {}).get("id"),
                points,
                actor_id,
            ),
        )
        incident_id = int(cursor.lastrowid)
        created = True
    for employee in incident.get("employees") or []:
        cursor.execute(
            """
            SELECT id FROM supervisor_quality_incident_employees
            WHERE incident_id=%s AND (user_id <=> %s) AND (employee_name <=> %s)
            LIMIT 1
            """,
            (incident_id, employee.get("user_id"), employee.get("employee_name")),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO supervisor_quality_incident_employees (
              incident_id, organization_id, user_id, employee_name, role_key
            ) VALUES (%s,%s,%s,%s,%s)
            """,
            (
                incident_id,
                int(organization_id),
                employee.get("user_id"),
                employee.get("employee_name"),
                employee.get("role_key") or "GENERAL",
            ),
        )
    return {"ok": True, "id": incident_id, "created": created, "points": points}


def void_incident(cursor, organization_id: int, incident_id: int, *, actor_id: int | None, reason: str) -> dict[str, Any]:
    _require(cursor, "supervisor_quality_incidents")
    if not str(reason or "").strip():
        raise ValueError("A reversal reason is required")
    cursor.execute(
        """
        UPDATE supervisor_quality_incidents
        SET voided_at=CURRENT_TIMESTAMP, voided_by=%s, void_reason=%s
        WHERE organization_id=%s AND id=%s AND voided_at IS NULL
        """,
        (actor_id, str(reason).strip()[:255], int(organization_id), int(incident_id)),
    )
    return {"ok": True, "id": int(incident_id)}


def scoring_target_for(cursor, organization_id: int, role_key: str, day: date) -> float | None:
    if not table_exists(cursor, "supervisor_role_targets"):
        return None
    cursor.execute(
        """
        SELECT target_value FROM supervisor_role_targets
        WHERE organization_id=%s AND role_key=%s AND status='published'
          AND effective_from<=%s AND (effective_to IS NULL OR effective_to>=%s)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (int(organization_id), role_key, day, day),
    )
    row = cursor.fetchone()
    if not isinstance(row, Mapping) or row.get("target_value") is None:
        return None
    return float(row["target_value"])


def insert_scoring_target(cursor, organization_id: int, body: Mapping[str, Any], *, actor_id: int | None) -> dict[str, Any]:
    _require(cursor, "supervisor_role_targets")
    role_key = str(body.get("role_key") or "").strip().upper()
    if not role_key:
        raise ValueError("Role is required")
    target = float(body.get("target_value"))
    if target <= 0:
        raise ValueError("Target must be positive")
    policy = str(body.get("above_target_policy") or "uncapped")
    if policy not in {"cap", "uncapped"}:
        raise ValueError("Above-target policy must be cap or uncapped")
    effective = date.fromisoformat(str(body.get("effective_from"))[:10])
    cursor.execute(
        """
        INSERT INTO supervisor_role_targets (
          organization_id, role_key, unit, target_value, effective_from,
          above_target_policy, status, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,'published',%s)
        ON DUPLICATE KEY UPDATE
          target_value=VALUES(target_value),
          unit=VALUES(unit),
          above_target_policy=VALUES(above_target_policy)
        """,
        (
            int(organization_id),
            role_key,
            body.get("unit"),
            target,
            effective,
            policy,
            actor_id,
        ),
    )
    return {
        "ok": True,
        "role_key": role_key,
        "target_value": target,
        "separate_from_auto_approval": True,
    }


def list_primary_roles(cursor, organization_id: int, user_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_employee_primary_roles"):
        return []
    cursor.execute(
        """
        SELECT * FROM supervisor_employee_primary_roles
        WHERE organization_id=%s AND user_id=%s
        ORDER BY effective_from, id
        """,
        (int(organization_id), int(user_id)),
    )
    return _rows(cursor.fetchall())


def set_primary_role(cursor, organization_id: int, body: Mapping[str, Any], *, actor_id: int | None) -> dict[str, Any]:
    _require(cursor, "supervisor_employee_primary_roles")
    user_id = int(body["user_id"])
    role_key = str(body.get("role_key") or "").strip().upper()
    if not role_key:
        raise ValueError("Role is required")
    effective = date.fromisoformat(str(body.get("effective_from"))[:10])
    previous_end = effective - timedelta(days=1)
    cursor.execute(
        """
        UPDATE supervisor_employee_primary_roles
        SET effective_to=%s
        WHERE organization_id=%s AND user_id=%s AND effective_to IS NULL AND effective_from<%s
        """,
        (previous_end, int(organization_id), user_id, effective),
    )
    cursor.execute(
        """
        INSERT INTO supervisor_employee_primary_roles (
          organization_id, user_id, role_key, effective_from, notes, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            user_id,
            role_key,
            effective,
            (str(body.get("notes")).strip()[:500] if body.get("notes") else None),
            actor_id,
        ),
    )
    history = list_primary_roles(cursor, organization_id, user_id)
    return {"ok": True, "current": _row(primary_role_on(history, effective) or {}), "history": history}


def save_training_template(cursor, organization_id: int, template: Mapping[str, Any], *, actor_id: int | None) -> dict[str, Any]:
    _require(cursor, "supervisor_training_templates", "supervisor_training_versions", "supervisor_training_items")
    template_id = template.get("template_id")
    if template_id:
        cursor.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) AS n
            FROM supervisor_training_versions WHERE template_id=%s
            """,
            (int(template_id),),
        )
        found = cursor.fetchone() or {}
        version_number = int((found.get("n") if isinstance(found, Mapping) else 0) or 0) + 1
    else:
        cursor.execute(
            """
            INSERT INTO supervisor_training_templates (
              organization_id, title, role_key, category, created_by
            ) VALUES (%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                template["title"],
                template["role_key"],
                template["category"],
                actor_id,
            ),
        )
        template_id = int(cursor.lastrowid)
        version_number = 1
    cursor.execute(
        """
        INSERT INTO supervisor_training_versions (
          organization_id, template_id, version_number, instructions, practical_required, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(template_id),
            version_number,
            template.get("instructions"),
            1 if template.get("practical_required") else 0,
            actor_id,
        ),
    )
    version_id = int(cursor.lastrowid)
    for item in template.get("items") or []:
        cursor.execute(
            """
            INSERT INTO supervisor_training_items (version_id, label, required_step, needs_evidence, sort_order)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                version_id,
                item["label"],
                1 if item.get("required", True) else 0,
                1 if item.get("needs_evidence") else 0,
                int(item.get("sort_order") or 0),
            ),
        )
    return {"ok": True, "template_id": int(template_id), "version_id": version_id, "version_number": version_number}


def list_training_templates(cursor, organization_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_training_templates"):
        return []
    cursor.execute(
        """
        SELECT t.id, t.title, t.role_key, t.category, t.active,
               v.id AS version_id, v.version_number, v.practical_required, v.instructions
        FROM supervisor_training_templates t
        LEFT JOIN supervisor_training_versions v ON v.id = (
          SELECT id FROM supervisor_training_versions
          WHERE template_id=t.id ORDER BY version_number DESC LIMIT 1
        )
        WHERE t.organization_id=%s
        ORDER BY t.title
        """,
        (int(organization_id),),
    )
    templates = _rows(cursor.fetchall())
    if templates and table_exists(cursor, "supervisor_training_items"):
        version_ids = [int(row["version_id"]) for row in templates if row.get("version_id")]
        if version_ids:
            placeholders = ",".join(["%s"] * len(version_ids))
            cursor.execute(
                f"""
                SELECT version_id, id, label, required_step, needs_evidence, sort_order
                FROM supervisor_training_items
                WHERE version_id IN ({placeholders})
                ORDER BY sort_order, id
                """,
                tuple(version_ids),
            )
            grouped: dict[int, list[dict[str, Any]]] = {}
            for row in _rows(cursor.fetchall()):
                grouped.setdefault(int(row["version_id"]), []).append(row)
            for template in templates:
                if template.get("version_id"):
                    template["items"] = grouped.get(int(template["version_id"]), [])
    return templates


def create_assignments(cursor, organization_id: int, body: Mapping[str, Any], *, actor_id: int | None) -> dict[str, Any]:
    _require(cursor, "supervisor_training_assignments")
    version_id = int(body["version_id"])
    trainees = body.get("trainee_user_ids") or []
    if body.get("trainee_user_id"):
        trainees = list(trainees) + [body.get("trainee_user_id")]
    reason = str(body.get("reason") or "onboarding").strip().lower()
    if reason not in {"onboarding", "new_role", "sop_update", "issue_based"}:
        raise ValueError("Assignment reason is not recognized")
    assigned_on = date.fromisoformat(str(body.get("assigned_on"))[:10]) if body.get("assigned_on") else date.today()
    due_on = date.fromisoformat(str(body.get("due_on"))[:10]) if body.get("due_on") else None
    created = []
    for trainee in trainees:
        cursor.execute(
            """
            INSERT INTO supervisor_training_assignments (
              organization_id, version_id, trainee_user_id, trainer_user_id, reason,
              assigned_on, due_on, status, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,'assigned',%s)
            """,
            (
                int(organization_id),
                version_id,
                int(trainee),
                int(body["trainer_user_id"]) if body.get("trainer_user_id") else None,
                reason,
                assigned_on,
                due_on,
                actor_id,
            ),
        )
        created.append(int(cursor.lastrowid))
    return {"ok": True, "ids": created}


def list_assignments(cursor, organization_id: int, *, trainee_user_id: int | None = None, mine_only: bool = False) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supervisor_training_assignments"):
        return []
    sql = """
        SELECT a.*, v.version_number, v.practical_required, v.instructions, t.title
        FROM supervisor_training_assignments a
        JOIN supervisor_training_versions v ON v.id=a.version_id
        JOIN supervisor_training_templates t ON t.id=v.template_id
        WHERE a.organization_id=%s
    """
    params: list[Any] = [int(organization_id)]
    if trainee_user_id is not None:
        sql += " AND a.trainee_user_id=%s"
        params.append(int(trainee_user_id))
    sql += " ORDER BY a.due_on IS NULL, a.due_on, a.id DESC"
    cursor.execute(sql, tuple(params))
    rows = _rows(cursor.fetchall())
    if mine_only:
        for row in rows:
            row.pop("supervisor_notes", None)
    return rows


def assignment_items(cursor, assignment_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT i.id, i.label, i.required_step, i.needs_evidence, i.sort_order,
               COALESCE(p.done, 0) AS done
        FROM supervisor_training_assignments a
        JOIN supervisor_training_items i ON i.version_id=a.version_id
        LEFT JOIN supervisor_training_progress p ON p.assignment_id=a.id AND p.item_id=i.id
        WHERE a.id=%s
        ORDER BY i.sort_order, i.id
        """,
        (int(assignment_id),),
    )
    return _rows(cursor.fetchall())


def set_progress(cursor, assignment_id: int, item_id: int, *, done: bool, actor_id: int | None) -> None:
    _require(cursor, "supervisor_training_progress")
    cursor.execute(
        """
        INSERT INTO supervisor_training_progress (assignment_id, item_id, done, done_at, done_by)
        VALUES (%s,%s,%s, CASE WHEN %s=1 THEN CURRENT_TIMESTAMP ELSE NULL END, %s)
        ON DUPLICATE KEY UPDATE done=VALUES(done), done_at=VALUES(done_at), done_by=VALUES(done_by)
        """,
        (int(assignment_id), int(item_id), 1 if done else 0, 1 if done else 0, actor_id),
    )


def update_assignment_status(cursor, organization_id: int, assignment_id: int, *, status: str, competency_result: str | None, actor_id: int | None, notes: str | None) -> None:
    _require(cursor, "supervisor_training_assignments")
    cursor.execute(
        """
        UPDATE supervisor_training_assignments
        SET status=%s,
            started_at=CASE WHEN %s='in_progress' AND started_at IS NULL THEN CURRENT_TIMESTAMP ELSE started_at END,
            completed_at=CASE WHEN %s='completed' THEN CURRENT_TIMESTAMP ELSE completed_at END,
            competency_result=COALESCE(%s, competency_result),
            verified_by=CASE WHEN %s='completed' THEN %s ELSE verified_by END,
            verified_at=CASE WHEN %s='completed' THEN CURRENT_TIMESTAMP ELSE verified_at END,
            supervisor_notes=COALESCE(%s, supervisor_notes)
        WHERE organization_id=%s AND id=%s
        """,
        (
            status,
            status,
            status,
            competency_result,
            status,
            actor_id,
            status,
            notes,
            int(organization_id),
            int(assignment_id),
        ),
    )


def get_assignment(cursor, organization_id: int, assignment_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT a.*, v.practical_required, v.instructions, t.title
        FROM supervisor_training_assignments a
        JOIN supervisor_training_versions v ON v.id=a.version_id
        JOIN supervisor_training_templates t ON t.id=v.template_id
        WHERE a.organization_id=%s AND a.id=%s
        LIMIT 1
        """,
        (int(organization_id), int(assignment_id)),
    )
    return _row(cursor.fetchone())


def read_flags(cursor, organization_id: int) -> dict[str, bool]:
    """Rollout switches. Scoring stays off even if a row tries to enable it."""
    flags = {
        "supervisor_portal": True,
        "quality_assignments": True,
        "training": True,
        "scoring_active": False,
        "rinse_employee_detail": False,
    }
    if not table_exists(cursor, "supervisor_feature_flags"):
        return flags
    cursor.execute(
        """
        SELECT flag_key, enabled FROM supervisor_feature_flags
        WHERE organization_id=%s
        """,
        (int(organization_id),),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("flag_key") or "")
        if key == "scoring_active" or key not in flags:
            continue
        flags[key] = bool(row.get("enabled"))
    flags["scoring_active"] = False
    return flags


def training_due_count(cursor, organization_id: int, day: date) -> int | None:
    if not table_exists(cursor, "supervisor_training_assignments"):
        return None
    cursor.execute(
        """
        SELECT COUNT(*) AS n FROM supervisor_training_assignments
        WHERE organization_id=%s AND due_on IS NOT NULL AND due_on<%s
          AND status NOT IN ('completed', 'failed')
        """,
        (int(organization_id), day),
    )
    row = cursor.fetchone() or {}
    return int((row.get("n") if isinstance(row, Mapping) else 0) or 0)


def stamp_approval_sources(cursor, organization_id: int, day: dict[str, Any]) -> None:
    if not table_exists(cursor, "rinse_performance_session_approvals"):
        return
    if not table_has_column(cursor, "rinse_performance_session_approvals", "approval_source"):
        return
    ids: list[str] = []
    for employee in day.get("employees") or []:
        for session in employee.get("sessions") or []:
            sid = str(session.get("session_id") or "")
            if sid:
                ids.append(sid)
    if not ids:
        return
    unique = sorted(set(ids))
    placeholders = ",".join(["%s"] * len(unique))
    cursor.execute(
        f"""
        SELECT session_id, approval_source, is_rate_override
        FROM rinse_performance_session_approvals
        WHERE organization_id=%s AND role_key='FOLDER' AND session_id IN ({placeholders})
        """,
        tuple([int(organization_id), *unique]),
    )
    found = {}
    for row in cursor.fetchall() or []:
        if isinstance(row, Mapping):
            found[str(row.get("session_id"))] = row
    for employee in day.get("employees") or []:
        for session in employee.get("sessions") or []:
            meta = found.get(str(session.get("session_id") or ""))
            if not meta:
                continue
            publication = session.get("publication") if isinstance(session.get("publication"), dict) else {}
            publication = dict(publication)
            publication["approval_source"] = meta.get("approval_source")
            publication["is_rate_override"] = bool(meta.get("is_rate_override"))
            session["publication"] = publication
            session["approval_source"] = meta.get("approval_source")
            session["is_rate_override"] = bool(meta.get("is_rate_override"))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:40]


def _json(value: Any) -> Any:
    if not value:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
