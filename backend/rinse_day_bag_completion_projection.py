"""Day-bag completion attribution normalization and scan-backed backfill.

After order-data reset, workload rows may carry completion facts only on
alternate keys (``canonical_completion_timestamp`` in snapshot JSON) while
``_bag_rows_from_workload`` historically mapped only ``completion_at`` /
``completed_by``. Performance attribution reads the persisted columns.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id


def _snapshot_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    snap = row.get("bag_snapshot")
    if isinstance(snap, dict):
        return dict(snap)
    if isinstance(snap, str) and snap.strip():
        try:
            parsed = json.loads(snap)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _iso_ts(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def normalize_completion_fields(row: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Return (completion_timestamp, employee_name) from row + snapshot aliases."""
    snap = _snapshot_dict(row)
    ts = (
        row.get("completion_at")
        or row.get("canonical_completion_timestamp")
        or row.get("productivity_completed_at")
        or snap.get("completion_at")
        or snap.get("canonical_completion_timestamp")
        or snap.get("productivity_completed_at")
    )
    emp_raw = (
        row.get("completed_by")
        or row.get("canonical_completion_employee")
        or row.get("productivity_employee_name")
        or snap.get("completed_by")
        or snap.get("canonical_completion_employee")
        or snap.get("productivity_employee_name")
    )
    emp = str(emp_raw).strip() if emp_raw is not None else None
    if emp == "":
        emp = None
    return ts, emp


def apply_normalized_completion_fields(bag: dict[str, Any]) -> dict[str, Any]:
    """Write normalized completion fields onto bag dict + embedded snapshot."""
    out = dict(bag)
    ts, emp = normalize_completion_fields(out)
    snap = _snapshot_dict(out)
    if ts is not None:
        out["canonical_completion_timestamp"] = ts
        snap["completion_at"] = _iso_ts(ts)
        snap["canonical_completion_timestamp"] = snap["completion_at"]
    if emp:
        out["canonical_completion_employee"] = emp
        snap["completed_by"] = emp
        snap["canonical_completion_employee"] = emp
    out["bag_snapshot"] = snap
    return out


def enrich_bags_completion_from_scans(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bags: Sequence[dict[str, Any]],
) -> None:
    """Fill missing completion employee/timestamp from canonical scan resolver."""
    from backend.rinse_veewash_workload import load_canonical_completions_v2

    need: list[str] = []
    svc_by_bag: dict[str, str] = {}
    for b in bags:
        bid = normalize_bag_id(b.get("bag_id"))
        if not bid or str(b.get("effective_status") or "").lower() != "completed":
            continue
        ts, emp = normalize_completion_fields(b)
        if ts is not None and emp:
            continue
        need.append(bid)
        svc_by_bag[bid] = str(b.get("service_type") or "WF").strip().upper() or "WF"
    if not need:
        return

    comps = load_canonical_completions_v2(
        cursor,
        int(organization_id),
        need,
        selected_date_et=selected_date_et,
        service_type_by_bag=svc_by_bag,
    )
    for b in bags:
        bid = normalize_bag_id(b.get("bag_id"))
        comp = comps.get(bid) if bid else None
        snap = _snapshot_dict(b)
        if comp:
            if comp.get("completion_at") is not None:
                b["canonical_completion_timestamp"] = comp["completion_at"]
                snap["completion_at"] = _iso_ts(comp["completion_at"])
                snap["canonical_completion_timestamp"] = snap["completion_at"]
            if comp.get("completed_by"):
                b["canonical_completion_employee"] = comp["completed_by"]
                snap["completed_by"] = comp["completed_by"]
                snap["canonical_completion_employee"] = comp["completed_by"]
            if comp.get("completion_source"):
                snap["completion_source"] = comp["completion_source"]
        b["bag_snapshot"] = snap
        apply_normalized_completion_fields(b)


def reconcile_day_bag_completion_projection(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Backfill persisted day-bag completion + productivity projection from scans."""
    from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag
    from backend.rinse_veewash_shift_day import load_day_bags, load_day_bags_by_ids

    org = int(organization_id)
    if bag_ids:
        rows = load_day_bags_by_ids(cursor, org, selected_date_et, list(bag_ids))
    else:
        rows = [dict(r) for r in (load_day_bags(cursor, org, selected_date_et) or [])]

    bags: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bag = dict(row)
        snap = bag.get("bag_snapshot")
        if not isinstance(snap, dict):
            bag["bag_snapshot"] = _snapshot_dict(bag)
        bags.append(bag)

    enrich_bags_completion_from_scans(cursor, org, selected_date_et, bags)

    examined = 0
    updated = 0
    still_missing = 0
    for bag in bags:
        if str(bag.get("effective_status") or "").lower() != "completed":
            continue
        examined += 1
        normalized = apply_normalized_completion_fields(bag)
        ts, emp = normalize_completion_fields(normalized)
        if ts is None or not emp:
            still_missing += 1
            continue
        proj = project_productivity_fields_for_day_bag(normalized)
        snap_json = json.dumps(normalized.get("bag_snapshot") or {})
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET canonical_completion_timestamp = %s,
                canonical_completion_employee = %s,
                productivity_employee_name = %s,
                productivity_completed_at = %s,
                productivity_weight_lbs = %s,
                productivity_credit_eligible = %s,
                productivity_exclusion_reason = %s,
                bag_snapshot_json = %s
            WHERE organization_id = %s
              AND shift_date_et = %s
              AND bag_id = %s
              AND manager_edit_version = 0
            """,
            (
                ts,
                emp,
                proj.get("productivity_employee_name"),
                proj.get("productivity_completed_at"),
                proj.get("productivity_weight_lbs"),
                proj.get("productivity_credit_eligible"),
                proj.get("productivity_exclusion_reason"),
                snap_json,
                org,
                selected_date_et,
                normalize_bag_id(normalized.get("bag_id")),
            ),
        )
        if cursor.rowcount:
            updated += 1

    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(org, selected_date_et)
    except Exception:
        pass

    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "examined_completed": examined,
        "updated": updated,
        "still_missing_attribution": still_missing,
    }
