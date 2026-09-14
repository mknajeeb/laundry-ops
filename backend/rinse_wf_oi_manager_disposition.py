"""OI-scoped manager dispositions — Exclude vs Manual Complete audit.

Stores disposition at ``order_instance_id`` (+ bag_id snapshot). Does not delete
PRE/POST evidence or prior exclude audits. Used by Management aggregates to omit
excluded OIs from Processed Pounds without touching scraper/ACA/completion precedence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_now
from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists

DISPOSITION_TABLE = "rinse_wf_oi_manager_dispositions"

DISPOSITION_EXCLUDE = "exclude"
DISPOSITION_MARK_COMPLETED = "mark_completed"
DISPOSITION_RETIRE_EXCLUDE = "retire_exclude"

EXCLUDE_REASON_CODES = (
    {
        "code": "EXTRA_OR_DUPLICATE_BAG",
        "label": "Extra bag / duplicate bag used",
    },
    {
        "code": "REJECTED_NOT_PROCESSED",
        "label": "Rejected / not processed",
    },
    {"code": "OTHER", "label": "Other"},
)

COMPLETE_REASON_CODES = (
    {
        "code": "BAG_ID_REASSIGNED",
        "label": "Bag ID unassigned / reassigned",
    },
    {
        "code": "MANUAL_RESEARCH_CONFIRMED",
        "label": "Manually researched and confirmed complete",
    },
    {"code": "OTHER", "label": "Other"},
)

EXCLUDE_REASON_CODE_SET = {str(x["code"]).upper() for x in EXCLUDE_REASON_CODES}
COMPLETE_REASON_CODE_SET = {str(x["code"]).upper() for x in COMPLETE_REASON_CODES}


def ensure_oi_manager_disposition_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DISPOSITION_TABLE} (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            order_instance_id BIGINT NOT NULL,
            bag_id VARCHAR(32) NOT NULL,
            disposition_type VARCHAR(32) NOT NULL,
            reason_code VARCHAR(64) NOT NULL,
            comment VARCHAR(1024) NULL,
            actor_user_id INT NULL,
            actor_display_name VARCHAR(255) NULL,
            created_at_et DATETIME NOT NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            superseded_at_et DATETIME NULL,
            superseded_by_disposition_id BIGINT NULL,
            INDEX idx_oi_mgr_disp_oi (organization_id, order_instance_id, active),
            INDEX idx_oi_mgr_disp_bag (organization_id, bag_id, active),
            INDEX idx_oi_mgr_disp_type (organization_id, disposition_type, active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    try:
        from backend.ta_helpers import invalidate_schema_cache

        invalidate_schema_cache()
    except Exception:
        pass


def _now_et_naive() -> datetime:
    now = business_now()
    if getattr(now, "tzinfo", None) is not None:
        return now.replace(tzinfo=None, microsecond=0)
    return now.replace(microsecond=0)


def _as_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    oid = row.get("order_instance_id")
    bid = normalize_bag_id(row.get("bag_id"))
    dtype = str(row.get("disposition_type") or "").strip().lower()
    if oid is None or not bid or not dtype:
        return None
    try:
        oid_i = int(oid)
    except (TypeError, ValueError):
        return None
    return {
        "id": row.get("id"),
        "organization_id": row.get("organization_id"),
        "order_instance_id": oid_i,
        "bag_id": bid,
        "disposition_type": dtype,
        "reason_code": str(row.get("reason_code") or "").strip().upper() or None,
        "comment": str(row.get("comment") or "").strip() or None,
        "actor_user_id": row.get("actor_user_id"),
        "actor_display_name": (
            str(row.get("actor_display_name") or "").strip() or None
        ),
        "created_at_et": row.get("created_at_et"),
        "active": bool(int(row.get("active") or 0)),
        "superseded_at_et": row.get("superseded_at_et"),
        "superseded_by_disposition_id": row.get("superseded_by_disposition_id"),
    }


def resolve_order_instance_id_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    order_instance_id: int | None = None,
    prefer_open: bool = True,
) -> int | None:
    """Resolve OI for disposition — prefer explicit id, then open WF OI, then latest."""
    from backend.rinse_order_instances import (
        get_order_instance_by_id,
        list_order_instances_for_bag,
    )

    if order_instance_id is not None:
        try:
            oi = get_order_instance_by_id(cursor, int(order_instance_id))
        except Exception:
            oi = None
        if isinstance(oi, dict) and oi.get("order_instance_id") is not None:
            return int(oi["order_instance_id"])

    bid = normalize_bag_id(bag_id)
    if not bid:
        return None
    try:
        rows = list_order_instances_for_bag(
            cursor, int(organization_id), bid, service_type="WF"
        )
    except Exception:
        return None
    if not rows:
        return None
    if prefer_open:
        open_ois = [r for r in rows if r.get("completed_at") is None]
        if len(open_ois) == 1:
            return int(open_ois[0]["order_instance_id"])
        if open_ois:
            return int(
                max(open_ois, key=lambda r: int(r.get("order_instance_id") or 0))[
                    "order_instance_id"
                ]
            )
    return int(
        max(rows, key=lambda r: int(r.get("order_instance_id") or 0))[
            "order_instance_id"
        ]
    )


def validate_exclude_reason(
    reason_code: str | None, comment: str | None
) -> dict[str, Any]:
    code = str(reason_code or "").strip().upper() or None
    note = str(comment or "").strip() or None
    if not code:
        return {"ok": False, "error": "reason_code_required"}
    if code not in EXCLUDE_REASON_CODE_SET:
        return {"ok": False, "error": "reason_code_not_allowed_for_exclude"}
    if code == "OTHER" and not note:
        return {"ok": False, "error": "reason_note_required_for_other"}
    label = next(
        (x["label"] for x in EXCLUDE_REASON_CODES if x["code"] == code),
        code,
    )
    return {
        "ok": True,
        "reason_code": code,
        "comment": note,
        "label": label,
        "audit_text": f"{code}: {note}" if note else f"{code}: {label}",
    }


def validate_complete_reason(
    reason_code: str | None, comment: str | None
) -> dict[str, Any]:
    code = str(reason_code or "").strip().upper() or None
    note = str(comment or "").strip() or None
    if not code:
        return {"ok": False, "error": "reason_code_required"}
    if code not in COMPLETE_REASON_CODE_SET:
        return {"ok": False, "error": "reason_code_not_allowed_for_complete"}
    if not note:
        return {"ok": False, "error": "manager_note_required"}
    if code == "OTHER" and not note:
        return {"ok": False, "error": "reason_note_required_for_other"}
    label = next(
        (x["label"] for x in COMPLETE_REASON_CODES if x["code"] == code),
        code,
    )
    return {
        "ok": True,
        "reason_code": code,
        "comment": note,
        "label": label,
        "audit_text": f"{code}: {note}",
    }


def record_oi_manager_disposition(
    cursor,
    organization_id: int,
    *,
    order_instance_id: int,
    bag_id: str,
    disposition_type: str,
    reason_code: str,
    comment: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    supersede_active_excludes: bool = False,
) -> dict[str, Any]:
    """Insert OI-scoped disposition row. Optionally supersede active exclude rows."""
    ensure_oi_manager_disposition_table(cursor)
    bid = normalize_bag_id(bag_id)
    dtype = str(disposition_type or "").strip().lower()
    code = str(reason_code or "").strip().upper()
    if not bid or not dtype or not code:
        return {"ok": False, "error": "invalid_disposition"}
    try:
        oid = int(order_instance_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "order_instance_id_required"}

    now = _now_et_naive()
    cursor.execute(
        f"""
        INSERT INTO {DISPOSITION_TABLE} (
            organization_id, order_instance_id, bag_id, disposition_type,
            reason_code, comment, actor_user_id, actor_display_name,
            created_at_et, active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """,
        (
            int(organization_id),
            oid,
            bid,
            dtype,
            code,
            (str(comment).strip() if comment else None) or None,
            actor_user_id,
            (str(actor_display_name).strip() if actor_display_name else None) or None,
            now,
        ),
    )
    new_id = int(cursor.lastrowid or 0)
    superseded = 0
    if supersede_active_excludes and new_id:
        cursor.execute(
            f"""
            UPDATE {DISPOSITION_TABLE}
            SET active = 0,
                superseded_at_et = %s,
                superseded_by_disposition_id = %s
            WHERE organization_id = %s
              AND order_instance_id = %s
              AND disposition_type = %s
              AND active = 1
              AND id <> %s
            """,
            (
                now,
                new_id,
                int(organization_id),
                oid,
                DISPOSITION_EXCLUDE,
                new_id,
            ),
        )
        superseded = int(cursor.rowcount or 0)

    return {
        "ok": True,
        "id": new_id,
        "order_instance_id": oid,
        "bag_id": bid,
        "disposition_type": dtype,
        "reason_code": code,
        "comment": (str(comment).strip() if comment else None) or None,
        "created_at_et": now,
        "superseded_exclude_rows": superseded,
    }


def list_oi_manager_dispositions(
    cursor,
    organization_id: int,
    *,
    order_instance_id: int | None = None,
    bag_id: str | None = None,
    active_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, DISPOSITION_TABLE):
        return []
    clauses = ["organization_id = %s"]
    params: list[Any] = [int(organization_id)]
    if order_instance_id is not None:
        clauses.append("order_instance_id = %s")
        params.append(int(order_instance_id))
    bid = normalize_bag_id(bag_id) if bag_id else None
    if bid:
        clauses.append("bag_id = %s")
        params.append(bid)
    if active_only:
        clauses.append("active = 1")
    if not order_instance_id and not bid:
        return []
    params.append(max(1, min(int(limit or 50), 200)))
    cursor.execute(
        f"""
        SELECT *
        FROM {DISPOSITION_TABLE}
        WHERE {' AND '.join(clauses)}
        ORDER BY id DESC
        LIMIT %s
        """,
        tuple(params),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        parsed = _as_row(row if isinstance(row, Mapping) else None)
        if parsed:
            out.append(parsed)
    return out


def active_excluded_bag_ids(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> set[str]:
    """Bag ids with an active Exclude disposition (OI-scoped table)."""
    bids = [normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)]
    if not bids or not table_exists(cursor, DISPOSITION_TABLE):
        return set()
    ph = ",".join(["%s"] * len(bids))
    cursor.execute(
        f"""
        SELECT DISTINCT bag_id
        FROM {DISPOSITION_TABLE}
        WHERE organization_id = %s
          AND active = 1
          AND disposition_type = %s
          AND bag_id IN ({ph})
        """,
        (int(organization_id), DISPOSITION_EXCLUDE, *bids),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, Mapping) else None
        )
        if bid:
            out.add(bid)
    return out


def bag_ids_with_manager_exclude_oi(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> set[str]:
    """Bags whose WF OI is closed with completion_source=manager_exclude."""
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE

    bids = [normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)]
    if not bids or not table_exists(cursor, ORDER_INSTANCES_TABLE):
        return set()
    ph = ",".join(["%s"] * len(bids))
    cursor.execute(
        f"""
        SELECT DISTINCT bag_id
        FROM {ORDER_INSTANCES_TABLE}
        WHERE organization_id = %s
          AND UPPER(COALESCE(service_type, 'WF')) = 'WF'
          AND completion_source = 'manager_exclude'
          AND bag_id IN ({ph})
        """,
        (int(organization_id), *bids),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(
            row.get("bag_id") if isinstance(row, Mapping) else None
        )
        if bid:
            out.add(bid)
    return out


def collect_processed_pounds_excluded_bag_ids(
    cursor,
    organization_id: int,
    bag_rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    """Union of exclude signals for Processed Pounds filtering.

    Sources (additive):
    - day_bag disposition EXCLUDE / effective_status excluded
    - active CW soft-exclude override
    - active OI disposition exclude rows
    - OI completion_source=manager_exclude
    """
    excluded: set[str] = set()
    bids: list[str] = []
    for row in bag_rows or []:
        bid = normalize_bag_id(row.get("bag_id") if isinstance(row, Mapping) else None)
        if not bid:
            continue
        bids.append(bid)
        disp = str(row.get("disposition") or "").strip().upper()
        eff = str(row.get("effective_status") or "").strip().lower()
        if disp == "EXCLUDE" or eff in ("excluded", "exclude"):
            excluded.add(bid)

    if not bids:
        return excluded

    try:
        from backend.management_wf_cw_controls import (
            OVERRIDE_EXCLUDE,
            bulk_load_active_cw_overrides,
        )

        ov_map = bulk_load_active_cw_overrides(cursor, organization_id, bids)
        for bid, ov in (ov_map or {}).items():
            if ov and str(ov.get("override_type") or "") == OVERRIDE_EXCLUDE:
                nb = normalize_bag_id(bid)
                if nb:
                    excluded.add(nb)
    except Exception:
        pass

    excluded |= active_excluded_bag_ids(cursor, organization_id, bids)
    excluded |= bag_ids_with_manager_exclude_oi(cursor, organization_id, bids)
    return excluded


def convert_manager_exclude_to_complete(
    cursor,
    organization_id: int,
    *,
    order_instance_id: int,
    bag_id: str,
    reason_code: str,
    manager_note: str,
    completion_at: datetime | None = None,
    completed_by: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    selected_date_et=None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bounded correction: retire mistaken exclude → audited manager complete.

    Preserves prior exclude audit / disposition history (supersede, do not delete).
    Does not mutate scan evidence. ``dry_run=True`` reports only.
    """
    from backend.rinse_order_instances import (
        ORDER_INSTANCES_TABLE,
        get_order_instance_by_id,
    )
    from backend.rinse_veewash_step1_api import _record_correction

    validated = validate_complete_reason(reason_code, manager_note)
    if not validated.get("ok"):
        return validated

    oi = get_order_instance_by_id(cursor, int(order_instance_id))
    if not isinstance(oi, dict):
        return {"ok": False, "error": "order_instance_not_found"}
    bid = normalize_bag_id(bag_id) or normalize_bag_id(oi.get("bag_id"))
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}
    src = str(oi.get("completion_source") or "").strip()
    if src != "manager_exclude":
        return {
            "ok": False,
            "error": "not_manager_exclude",
            "completion_source": src or None,
            "order_instance_id": int(order_instance_id),
        }

    plan = {
        "ok": True,
        "dry_run": bool(dry_run),
        "order_instance_id": int(order_instance_id),
        "bag_id": bid,
        "previous_completion_source": src,
        "previous_completed_at": oi.get("completed_at"),
        "new_completion_source": "manager_correct_completion",
        "reason_code": validated["reason_code"],
        "manager_note": validated["comment"],
        "completion_at": completion_at or oi.get("completed_at"),
        "completed_by": completed_by or actor_display_name,
    }
    if dry_run:
        return plan

    ensure_oi_manager_disposition_table(cursor)
    new_completed_at = completion_at or oi.get("completed_at")
    emp = (
        str(completed_by or actor_display_name or oi.get("completed_by_employee_name") or "")
        .strip()
        or None
    )
    cursor.execute(
        f"""
        UPDATE {ORDER_INSTANCES_TABLE}
        SET completion_source = %s,
            completed_at = COALESCE(%s, completed_at),
            completed_by_employee_name = COALESCE(%s, completed_by_employee_name),
            updated_at = CURRENT_TIMESTAMP
        WHERE order_instance_id = %s
          AND completion_source = 'manager_exclude'
        """,
        (
            "manager_correct_completion",
            new_completed_at,
            emp,
            int(order_instance_id),
        ),
    )
    if int(cursor.rowcount or 0) < 1:
        return {"ok": False, "error": "oi_update_failed"}

    disp = record_oi_manager_disposition(
        cursor,
        organization_id,
        order_instance_id=int(order_instance_id),
        bag_id=bid,
        disposition_type=DISPOSITION_MARK_COMPLETED,
        reason_code=validated["reason_code"],
        comment=validated["comment"],
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        supersede_active_excludes=True,
    )
    # Also stamp an explicit retire row for history clarity.
    record_oi_manager_disposition(
        cursor,
        organization_id,
        order_instance_id=int(order_instance_id),
        bag_id=bid,
        disposition_type=DISPOSITION_RETIRE_EXCLUDE,
        reason_code=validated["reason_code"],
        comment=validated["comment"],
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        supersede_active_excludes=False,
    )

    _record_correction(
        cursor,
        organization_id,
        bag_id=bid,
        action="retire_exclude_mark_complete",
        reason_text=validated["audit_text"],
        reason_code=validated["reason_code"],
        previous_values={
            "order_instance_id": int(order_instance_id),
            "completion_source": src,
            "completed_at": oi.get("completed_at"),
        },
        new_values={
            "order_instance_id": int(order_instance_id),
            "completion_source": "manager_correct_completion",
            "completed_at": new_completed_at,
            "completed_by": emp,
            "manager_note": validated["comment"],
            "disposition_id": disp.get("id"),
        },
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )

    try:
        from backend.management_wf_cw_controls import (
            OVERRIDE_EXCLUDE,
            clear_cw_override,
        )

        clear_cw_override(
            cursor,
            organization_id,
            bag_id=bid,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            clear_reason_text="Retire mistaken exclude — mark complete",
            only_types=[OVERRIDE_EXCLUDE],
        )
    except Exception:
        pass

    if selected_date_et is not None:
        try:
            from backend.rinse_veewash_shift_day import apply_manager_edit_day_bag_patch

            apply_manager_edit_day_bag_patch(
                cursor,
                organization_id,
                selected_date_et,
                bid,
                outcome_action="mark_completed",
                completion_at=new_completed_at
                if isinstance(new_completed_at, datetime)
                else None,
                completed_by=emp,
            )
        except Exception:
            pass

    try:
        from backend.rinse_wf_service_cycle import (
            apply_manager_review_resolution_to_canonical_cycle,
        )

        apply_manager_review_resolution_to_canonical_cycle(
            cursor,
            organization_id,
            bid,
            completed_at=new_completed_at
            if isinstance(new_completed_at, datetime)
            else datetime.utcnow(),
            completion_source="manager_correct_completion",
            resolved_by=actor_display_name,
            resolution_note=validated["audit_text"],
        )
    except Exception:
        pass

    plan["applied"] = True
    plan["disposition"] = disp
    return plan
