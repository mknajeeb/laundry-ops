"""Organization-scoped Saved Simulations for Management Shift Capacity Planner.

Separate from PARAMETERS (`shift_capacity_planner_params_v1`).
Persists scenario *inputs* only (mgmt_sim_v1). Opening always re-runs current DES.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.shift_capacity_planner_settings import (
    DEFAULT_PLANNER_PARAMS,
    validate_planner_params,
)
from backend.ta_helpers import table_exists

TABLE = "shift_capacity_saved_simulations"
PAYLOAD_VERSION = "mgmt_sim_v1"

MANAGEMENT_ROLES = ("weigher", "sorter", "washer", "dryer", "folder")

LEGACY_HYBRID_ROLES = {
    "weigh_wash": ["weigher", "washer"],
    "wash_dry": ["washer", "dryer"],
    "weigh_wash_dry": ["weigher", "washer", "dryer"],
}

SCENARIO_EXTRA_KEYS = (
    "avg_lbs_per_bag",
    "two_washer_split_pct",
    "two_dryer_split_pct",
    "batch_size",
)

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT NOT NULL AUTO_INCREMENT,
  organization_id INT NOT NULL,
  name VARCHAR(120) NOT NULL,
  scenario_payload JSON NOT NULL,
  payload_version VARCHAR(16) NOT NULL,
  created_by_user_id INT NULL,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_run_at DATETIME NULL,
  last_run_summary JSON NULL,
  PRIMARY KEY (id),
  KEY idx_scs_org_updated (organization_id, updated_at),
  KEY idx_scs_org_name (organization_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_saved_simulations_table(cursor) -> None:
    """Idempotent schema ensure. Skip CREATE when table already exists (Azure hot path)."""
    if table_exists(cursor, TABLE):
        return
    cursor.execute(_CREATE_SQL)


def _clock_ok(raw: Any) -> bool:
    if raw is None:
        return False
    text = str(raw).strip()
    return bool(re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$", text, re.I))


def _as_int(raw: Any, *, min_v: int | None = None, max_v: int | None = None) -> int | None:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if min_v is not None and n < min_v:
        return None
    if max_v is not None and n > max_v:
        return None
    return n


def _as_float(raw: Any, *, min_v: float | None = None, max_v: float | None = None) -> float | None:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if min_v is not None and n < min_v:
        return None
    if max_v is not None and n > max_v:
        return None
    return n


def _normalize_roles(raw: Any) -> list[str]:
    if isinstance(raw, str):
        legacy = LEGACY_HYBRID_ROLES.get(raw.strip().lower())
        return list(legacy) if legacy else []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        role = str(item or "").strip().lower()
        if role in MANAGEMENT_ROLES and role not in out:
            out.append(role)
    return out


def _normalize_staffing_interval(row: Mapping[str, Any]) -> dict[str, Any]:
    role = str(row.get("role") or "").strip().lower()
    if role not in MANAGEMENT_ROLES:
        raise ValueError(f"Invalid staffing role: {role or '(empty)'}")
    people = _as_int(row.get("people"), min_v=0)
    if people is None:
        raise ValueError("staffing people must be an integer >= 0")
    start = row.get("start") or row.get("start_time")
    end = row.get("end") or row.get("end_time")
    if not _clock_ok(start) or not _clock_ok(end):
        raise ValueError("staffing interval start/end must be clock times")
    mode = str(row.get("mode") or "base").strip().lower()
    if mode not in ("base", "additional"):
        mode = "base"
    out: dict[str, Any] = {
        "role": role,
        "people": people,
        "start": str(start).strip(),
        "end": str(end).strip(),
        "mode": mode,
    }
    if row.get("id") is not None:
        out["id"] = str(row.get("id"))
    return out


def _normalize_hybrid_interval(row: Mapping[str, Any]) -> dict[str, Any]:
    roles = _normalize_roles(row.get("roles") or row.get("hybrid") or row.get("hybrid_type"))
    if len(roles) < 2:
        raise ValueError("hybrid intervals require at least 2 roles")
    people = _as_int(row.get("people"), min_v=1)
    if people is None:
        raise ValueError("hybrid people must be an integer >= 1")
    start = row.get("start") or row.get("start_time")
    end = row.get("end") or row.get("end_time")
    if not _clock_ok(start) or not _clock_ok(end):
        raise ValueError("hybrid interval start/end must be clock times")
    mode = str(row.get("mode") or "base").strip().lower()
    if mode in ("hybrid",):
        mode = "base"
    if mode not in ("base", "additional"):
        mode = "base"
    out: dict[str, Any] = {
        "roles": roles,
        "people": people,
        "start": str(start).strip(),
        "end": str(end).strip(),
        "mode": mode,
    }
    if row.get("id") is not None:
        out["id"] = str(row.get("id"))
    return out


def normalize_scenario_payload(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize mgmt_sim_v1 input-only payload."""
    if not isinstance(raw, Mapping):
        raise ValueError("scenario_payload must be an object")
    version = str(raw.get("payload_version") or PAYLOAD_VERSION).strip()
    if version != PAYLOAD_VERSION:
        raise ValueError(f"Unsupported payload_version: {version}")

    # Plan/process core via existing validator
    params = validate_planner_params({**DEFAULT_PLANNER_PARAMS, **dict(raw)})

    avg = _as_float(raw.get("avg_lbs_per_bag", 20), min_v=0.1)
    if avg is None:
        raise ValueError("avg_lbs_per_bag must be > 0")
    wash_split = _as_float(raw.get("two_washer_split_pct", 80), min_v=0, max_v=100)
    dry_split = _as_float(raw.get("two_dryer_split_pct", 80), min_v=0, max_v=100)
    if wash_split is None:
        raise ValueError("two_washer_split_pct must be 0–100")
    if dry_split is None:
        raise ValueError("two_dryer_split_pct must be 0–100")
    batch_size = _as_int(raw.get("batch_size", 8), min_v=1)
    if batch_size is None:
        raise ValueError("batch_size must be >= 1")

    staffing_raw = raw.get("staffing_intervals") or []
    hybrid_raw = raw.get("hybrid_intervals") or []
    if not isinstance(staffing_raw, list):
        raise ValueError("staffing_intervals must be a list")
    if not isinstance(hybrid_raw, list):
        raise ValueError("hybrid_intervals must be a list")

    staffing = [_normalize_staffing_interval(r) for r in staffing_raw if isinstance(r, Mapping)]
    hybrids = [_normalize_hybrid_interval(r) for r in hybrid_raw if isinstance(r, Mapping)]

    return {
        "payload_version": PAYLOAD_VERSION,
        **params,
        "avg_lbs_per_bag": avg,
        "two_washer_split_pct": wash_split,
        "two_dryer_split_pct": dry_split,
        "batch_size": batch_size,
        "staffing_intervals": staffing,
        "hybrid_intervals": hybrids,
    }


def normalize_last_run_summary(raw: Any) -> dict[str, Any] | None:
    """Optional browse-only chip fields (never authoritative for open/recalc)."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("last_run_summary must be an object")
    out: dict[str, Any] = {}
    for key in (
        "projected_finish",
        "completed_by_target",
        "target_bags",
        "staff_hours",
        "productive_hours",
        "peak_staff",
        "labor_min_per_bag",
        "bottleneck_stage",
        "status_label",
        "name_hint",
    ):
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    return out or None


def _json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _row_to_dict(row: Mapping[str, Any], *, include_payload: bool = True) -> dict[str, Any]:
    out = {
        "id": int(row["id"]),
        "organization_id": int(row["organization_id"]),
        "name": str(row["name"]),
        "payload_version": str(row.get("payload_version") or PAYLOAD_VERSION),
        "created_by_user_id": row.get("created_by_user_id"),
        "updated_by_user_id": row.get("updated_by_user_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_run_at": row.get("last_run_at"),
        "last_run_summary": _json_load(row.get("last_run_summary")),
    }
    if include_payload:
        out["scenario_payload"] = _json_load(row.get("scenario_payload"))
    return out


def list_saved_simulations(cursor, organization_id: int) -> list[dict[str, Any]]:
    ensure_saved_simulations_table(cursor)
    cursor.execute(
        f"""
        SELECT id, organization_id, name, payload_version,
               created_by_user_id, updated_by_user_id,
               created_at, updated_at, last_run_at, last_run_summary
        FROM {TABLE}
        WHERE organization_id=%s
        ORDER BY updated_at DESC, id DESC
        """,
        (int(organization_id),),
    )
    rows = cursor.fetchall() or []
    return [_row_to_dict(r, include_payload=False) for r in rows]


def get_saved_simulation(
    cursor, organization_id: int, simulation_id: int
) -> dict[str, Any] | None:
    ensure_saved_simulations_table(cursor)
    cursor.execute(
        f"""
        SELECT id, organization_id, name, scenario_payload, payload_version,
               created_by_user_id, updated_by_user_id,
               created_at, updated_at, last_run_at, last_run_summary
        FROM {TABLE}
        WHERE organization_id=%s AND id=%s
        LIMIT 1
        """,
        (int(organization_id), int(simulation_id)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, include_payload=True)


def create_saved_simulation(
    cursor,
    organization_id: int,
    *,
    name: str,
    scenario_payload: Mapping[str, Any],
    user_id: int | None = None,
    last_run_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_saved_simulations_table(cursor)
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("name is required")
    if len(clean_name) > 120:
        raise ValueError("name must be 120 characters or fewer")
    payload = normalize_scenario_payload(scenario_payload)
    summary = normalize_last_run_summary(last_run_summary)
    cursor.execute(
        f"""
        INSERT INTO {TABLE}
          (organization_id, name, scenario_payload, payload_version,
           created_by_user_id, updated_by_user_id, last_run_at, last_run_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            clean_name,
            _json_dump(payload),
            PAYLOAD_VERSION,
            int(user_id) if user_id is not None else None,
            int(user_id) if user_id is not None else None,
            datetime.now(timezone.utc).replace(tzinfo=None) if summary else None,
            _json_dump(summary) if summary else None,
        ),
    )
    new_id = int(getattr(cursor, "lastrowid", None) or 0)
    if not new_id:
        # Some fakes / drivers: SELECT LAST_INSERT_ID()
        cursor.execute("SELECT LAST_INSERT_ID() AS id")
        row = cursor.fetchone() or {}
        new_id = int(row.get("id") if isinstance(row, dict) else row[0])
    created = get_saved_simulation(cursor, organization_id, new_id)
    if not created:
        raise RuntimeError("failed to load created simulation")
    return created


def update_saved_simulation(
    cursor,
    organization_id: int,
    simulation_id: int,
    *,
    scenario_payload: Mapping[str, Any] | None = None,
    name: str | None = None,
    user_id: int | None = None,
    last_run_summary: Mapping[str, Any] | None = None,
    clear_last_run_summary: bool = False,
) -> dict[str, Any]:
    ensure_saved_simulations_table(cursor)
    existing = get_saved_simulation(cursor, organization_id, simulation_id)
    if not existing:
        raise LookupError("simulation not found")

    clean_name = existing["name"]
    if name is not None:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("name is required")
        if len(clean_name) > 120:
            raise ValueError("name must be 120 characters or fewer")

    payload = existing["scenario_payload"]
    if scenario_payload is not None:
        payload = normalize_scenario_payload(scenario_payload)

    summary = existing.get("last_run_summary")
    last_run_at = existing.get("last_run_at")
    if clear_last_run_summary:
        summary = None
        last_run_at = None
    elif last_run_summary is not None:
        summary = normalize_last_run_summary(last_run_summary)
        last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)

    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET name=%s,
            scenario_payload=%s,
            payload_version=%s,
            updated_by_user_id=%s,
            last_run_at=%s,
            last_run_summary=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            clean_name,
            _json_dump(payload),
            PAYLOAD_VERSION,
            int(user_id) if user_id is not None else existing.get("updated_by_user_id"),
            last_run_at,
            _json_dump(summary) if summary else None,
            int(organization_id),
            int(simulation_id),
        ),
    )
    updated = get_saved_simulation(cursor, organization_id, simulation_id)
    if not updated:
        raise LookupError("simulation not found")
    return updated


def rename_saved_simulation(
    cursor,
    organization_id: int,
    simulation_id: int,
    *,
    name: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    return update_saved_simulation(
        cursor,
        organization_id,
        simulation_id,
        name=name,
        user_id=user_id,
    )


def delete_saved_simulation(cursor, organization_id: int, simulation_id: int) -> bool:
    ensure_saved_simulations_table(cursor)
    cursor.execute(
        f"DELETE FROM {TABLE} WHERE organization_id=%s AND id=%s",
        (int(organization_id), int(simulation_id)),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0
