"""Unified Step-1 Edit Bag: single entry point for bag-level corrections + undo.

Consolidates the previously separate correction actions (service/rush, entry,
weights, bulk workitems, outcome) into one atomic edit that records a single
parent audit row (``rinse_step1_bag_edits``) with per-field deltas
(``rinse_step1_bag_edit_deltas``) and supports one-step undo.

All DB writes happen on the caller's cursor; the caller is responsible for
commit/rollback. Sub-operations that fail (return ``ok: False`` or raise) do
so before the parent edit row is written, so a failed edit never leaves a
partial audit trail.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_workload import SERVICE_HD, SERVICE_WF
from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
from backend.ta_helpers import table_exists

OUTCOME_MARK_COMPLETED = "mark_completed"
OUTCOME_RETURN_PENDING = "return_pending"
OUTCOME_KEEP_REVIEW = "keep_review"
OUTCOME_EXCLUDE = "exclude"

VALID_OUTCOME_ACTIONS = {
    OUTCOME_MARK_COMPLETED,
    OUTCOME_RETURN_PENDING,
    OUTCOME_KEEP_REVIEW,
    OUTCOME_EXCLUDE,
}

# Outcomes that always require a structured reason.
ALWAYS_REASONED_OUTCOMES = {
    OUTCOME_RETURN_PENDING,
    OUTCOME_EXCLUDE,
}

# Legacy alias — mark_completed is conditional (see classify_edit_reason_requirements).
EXCEPTIONAL_OUTCOME_ACTIONS = {
    OUTCOME_MARK_COMPLETED,
    OUTCOME_RETURN_PENDING,
    OUTCOME_EXCLUDE,
}

REASON_CODES_POST_CORRECTION = (
    {"code": "INCORRECT_CAPTURED_WEIGHT", "label": "Incorrect captured weight"},
    {"code": "SCALE_ISSUE", "label": "Scale issue"},
    {"code": "WRONG_BAG_ASSOCIATION", "label": "Wrong bag association"},
    {"code": "OTHER", "label": "Other"},
)
REASON_CODES_PRE_CORRECTION = (
    {"code": "INCORRECT_CAPTURED_WEIGHT", "label": "Incorrect captured weight"},
    {"code": "SCALE_ISSUE", "label": "Scale issue"},
    {"code": "MISSING_PRE_EVIDENCE", "label": "Missing PRE evidence"},
    {"code": "OTHER", "label": "Other"},
)
REASON_CODES_RETURN_PENDING = (
    {"code": "COMPLETION_ASSIGNED_INCORRECTLY", "label": "Completion assigned incorrectly"},
    {"code": "BAG_NOT_ACTUALLY_COMPLETED", "label": "Bag not actually completed"},
    {"code": "COMPLETION_EVIDENCE_INVALID", "label": "Completion evidence invalid"},
    {"code": "OTHER", "label": "Other"},
)
REASON_CODES_EXCLUDE = (
    {"code": "NOT_VEEWASH_BAG", "label": "Not a VeeWash bag"},
    {"code": "DUPLICATE_RECORD", "label": "Duplicate record"},
    {"code": "TEST_RECORD", "label": "Test record"},
    {"code": "WRONG_SERVICE_DAY", "label": "Wrong service/day"},
    {"code": "OTHER", "label": "Other"},
)
REASON_CODES_COMPLETION_CHANGE = (
    {"code": "COMPLETION_ASSIGNED_INCORRECTLY", "label": "Completion assigned incorrectly"},
    {"code": "CORRECT_COMPLETION_DETAILS", "label": "Correct completion details"},
    {"code": "OTHER", "label": "Other"},
)
REASON_CODES_MANUAL_MARK_COMPLETED = (
    {"code": "MARK_COMPLETED", "label": "Manually mark completed"},
    {"code": "STATUS_OVERRIDE", "label": "Manual status override"},
    {"code": "OTHER", "label": "Other"},
)

# Flat union for label lookup / backward-compatible codes.
REASON_CODE_OPTIONS = (
    {"code": "POST_CORRECTION", "label": "POST weight correction"},
    {"code": "PRE_CORRECTION", "label": "PRE weight correction"},
    {"code": "EXCLUDE", "label": "Exclude bag"},
    {"code": "MARK_COMPLETED", "label": "Manually mark completed"},
    {"code": "RETURN_PENDING", "label": "Return to pending"},
    {"code": "ACCEPT_EXCEPTION", "label": "Accept exception"},
    {"code": "STATUS_OVERRIDE", "label": "Manual status override"},
    {"code": "INCORRECT_CAPTURED_WEIGHT", "label": "Incorrect captured weight"},
    {"code": "SCALE_ISSUE", "label": "Scale issue"},
    {"code": "WRONG_BAG_ASSOCIATION", "label": "Wrong bag association"},
    {"code": "MISSING_PRE_EVIDENCE", "label": "Missing PRE evidence"},
    {"code": "COMPLETION_ASSIGNED_INCORRECTLY", "label": "Completion assigned incorrectly"},
    {"code": "BAG_NOT_ACTUALLY_COMPLETED", "label": "Bag not actually completed"},
    {"code": "COMPLETION_EVIDENCE_INVALID", "label": "Completion evidence invalid"},
    {"code": "NOT_VEEWASH_BAG", "label": "Not a VeeWash bag"},
    {"code": "DUPLICATE_RECORD", "label": "Duplicate record"},
    {"code": "TEST_RECORD", "label": "Test record"},
    {"code": "WRONG_SERVICE_DAY", "label": "Wrong service/day"},
    {"code": "CORRECT_COMPLETION_DETAILS", "label": "Correct completion details"},
    {"code": "OTHER", "label": "Other"},
)

SYSTEM_ACTION_WORKITEMS_UPDATED = "WORKITEMS_UPDATED"
SYSTEM_ACTION_REVIEW_UPDATED = "REVIEW_UPDATED"
SYSTEM_ACTION_REVIEW_CONFIRMED_COMPLETED = "REVIEW_CONFIRMED_COMPLETED"
# Legacy alias kept for older audits / callers
SYSTEM_ACTION_REVIEW_SAVED = SYSTEM_ACTION_REVIEW_UPDATED

# Fields tracked for before/after delta rows on every edit.
_TRACKED_FIELDS = (
    "service_type",
    "rush_flag",
    "entry_at",
    "entry_source",
    "rack",
    "pre_weight_lbs",
    "post_weight_lbs",
    "bulk_items",
    "no_chargeable",
    "no_charge_reason",
    "dashboard_status",
    "completion_at",
    "completed_by",
)

_BAG_EDIT_TABLES_READY = False


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _weight_changed(before_val: Any, draft_val: Any) -> bool:
    b = normalize_scan_weight_lbs(before_val)
    d = normalize_scan_weight_lbs(draft_val)
    if b is None and d is None:
        return False
    if b is None or d is None:
        return True
    return float(b) != float(d)


def _normalize_completion_key(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    text = text.replace("Z", "").replace(" ", "T", 1)
    # Compare to minute precision so picker truncation doesn't force a reason.
    m = text[:16] if len(text) >= 16 and "T" in text else text
    return m.lower()


def _completion_employee_changed(draft: Mapping[str, Any], before: Mapping[str, Any]) -> bool:
    if "completed_by" not in draft and "completion_employee" not in draft:
        return False
    draft_emp = str(
        draft.get("completion_employee")
        if draft.get("completion_employee") is not None
        else draft.get("completed_by")
        or ""
    ).strip().lower()
    before_emp = str(before.get("completed_by") or "").strip().lower()
    return draft_emp != before_emp


def _completion_timestamp_changed(draft: Mapping[str, Any], before: Mapping[str, Any]) -> bool:
    if "completion_at" not in draft:
        return False
    return _normalize_completion_key(draft.get("completion_at")) != _normalize_completion_key(
        before.get("completion_at")
    )


def _has_canonical_completion(before: Mapping[str, Any]) -> bool:
    emp = str(before.get("completed_by") or "").strip()
    ts = before.get("completion_at")
    if emp and ts not in (None, ""):
        return True
    status = str(before.get("dashboard_status") or before.get("outcome") or "").strip().lower()
    return status in {"completed", "complete", "done"} and bool(emp or ts)


def _reason_options_for_triggers(triggers: list[str]) -> list[dict[str, str]]:
    if "post_weight_correction" in triggers:
        return list(REASON_CODES_POST_CORRECTION)
    if "pre_weight_correction" in triggers:
        return list(REASON_CODES_PRE_CORRECTION)
    if "return_pending" in triggers or OUTCOME_RETURN_PENDING in triggers:
        return list(REASON_CODES_RETURN_PENDING)
    if "exclude" in triggers or OUTCOME_EXCLUDE in triggers:
        return list(REASON_CODES_EXCLUDE)
    if "completion_employee_changed" in triggers or "completion_timestamp_changed" in triggers:
        return list(REASON_CODES_COMPLETION_CHANGE)
    if "mark_completed" in triggers or "status_override" in triggers:
        return list(REASON_CODES_MANUAL_MARK_COMPLETED)
    return list(REASON_CODE_OPTIONS)


def classify_edit_reason_requirements(
    draft: Mapping[str, Any],
    before: Mapping[str, Any],
    outcome: str | None,
) -> dict[str, Any]:
    """
    Decide whether a manager reason_code is required for this Edit Bag save.

    Routine work-item / review saves and confirming an existing canonical
    completion do not require a reason. Weight corrections, return/exclude,
    completion-field changes from source, and manual mark-completed without
    canonical evidence do.
    """
    draft = dict(draft or {})
    before = dict(before or {})
    triggers: list[str] = []

    if "post_weight_lbs" in draft and _weight_changed(
        before.get("post_weight_lbs"), draft.get("post_weight_lbs")
    ):
        triggers.append("post_weight_correction")
    if "pre_weight_lbs" in draft and _weight_changed(
        before.get("pre_weight_lbs"), draft.get("pre_weight_lbs")
    ):
        triggers.append("pre_weight_correction")

    emp_changed = _completion_employee_changed(draft, before)
    ts_changed = _completion_timestamp_changed(draft, before)
    if emp_changed:
        triggers.append("completion_employee_changed")
    if ts_changed:
        triggers.append("completion_timestamp_changed")

    confirm_completed = False
    weight_override = any(
        t in triggers for t in ("post_weight_correction", "pre_weight_correction")
    )
    if outcome == OUTCOME_MARK_COMPLETED:
        has_canonical = _has_canonical_completion(before)
        if (
            has_canonical
            and not emp_changed
            and not ts_changed
            and not weight_override
            and not draft.get("manual_status_override")
        ):
            # Confirming existing completion evidence — not a manual override.
            confirm_completed = True
        else:
            triggers.append("mark_completed")
    elif outcome in ALWAYS_REASONED_OUTCOMES:
        triggers.append(str(outcome))

    if draft.get("manual_status_override"):
        triggers.append("status_override")

    required = bool(triggers)
    suggested = None
    if "post_weight_correction" in triggers:
        suggested = "INCORRECT_CAPTURED_WEIGHT"
    elif "pre_weight_correction" in triggers:
        suggested = "INCORRECT_CAPTURED_WEIGHT"
    elif outcome == OUTCOME_EXCLUDE or "exclude" in triggers:
        suggested = "NOT_VEEWASH_BAG"
    elif outcome == OUTCOME_RETURN_PENDING or "return_pending" in triggers:
        suggested = "BAG_NOT_ACTUALLY_COMPLETED"
    elif "completion_employee_changed" in triggers or "completion_timestamp_changed" in triggers:
        suggested = "CORRECT_COMPLETION_DETAILS"
    elif "mark_completed" in triggers:
        suggested = "MARK_COMPLETED"
    elif "status_override" in triggers:
        suggested = "STATUS_OVERRIDE"

    bulk_changed = "bulk_items" in draft or "no_chargeable" in draft
    if confirm_completed and not required:
        system_action = SYSTEM_ACTION_REVIEW_CONFIRMED_COMPLETED
        save_path = "confirm_completed"
    elif required:
        system_action = (
            SYSTEM_ACTION_WORKITEMS_UPDATED if bulk_changed else SYSTEM_ACTION_REVIEW_UPDATED
        )
        save_path = "manager_override"
    else:
        system_action = (
            SYSTEM_ACTION_WORKITEMS_UPDATED if bulk_changed else SYSTEM_ACTION_REVIEW_UPDATED
        )
        save_path = "routine_review"

    reason_codes = _reason_options_for_triggers(triggers) if required else []
    return {
        "reason_required": required,
        "triggers": triggers,
        "suggested_reason_code": suggested,
        "system_action": system_action,
        "save_path": save_path,
        "confirm_completed": confirm_completed,
        "reason_codes": reason_codes,
    }


def resolve_edit_audit_reason(
    *,
    reason: str | None,
    reason_code: str | None,
    reason_note: str | None,
    draft: Mapping[str, Any],
    before: Mapping[str, Any],
    outcome: str | None,
) -> dict[str, Any]:
    """Validate + resolve audit reason text for Edit Bag (server-side policy)."""
    policy = classify_edit_reason_requirements(draft, before, outcome)
    code = str(reason_code or "").strip().upper() or None
    note = str(reason_note or reason or "").strip() or None
    legacy_reason = str(reason or "").strip() or None
    allowed = {str(x["code"]).upper() for x in (policy.get("reason_codes") or [])}
    # Accept legacy generic codes when context list is active.
    legacy_aliases = {
        "POST_CORRECTION",
        "PRE_CORRECTION",
        "EXCLUDE",
        "RETURN_PENDING",
        "MARK_COMPLETED",
        "STATUS_OVERRIDE",
        "ACCEPT_EXCEPTION",
        "OTHER",
    }

    if policy["reason_required"]:
        if not code and legacy_reason:
            # Backward compatible: free-text reason alone is accepted as OTHER note.
            code = "OTHER"
            note = legacy_reason
        if not code:
            return {
                "ok": False,
                "error": "reason_code_required",
                "policy": policy,
            }
        if allowed and code not in allowed and code not in legacy_aliases:
            return {
                "ok": False,
                "error": "reason_code_not_allowed_for_action",
                "policy": policy,
            }
        if code == "OTHER" and not note:
            return {
                "ok": False,
                "error": "reason_note_required_for_other",
                "policy": policy,
            }
        label = next(
            (x["label"] for x in REASON_CODE_OPTIONS if x["code"] == code),
            code,
        )
        audit = f"{code}: {note}" if note else f"{code}: {label}"
        return {
            "ok": True,
            "reason": audit,
            "reason_code": code,
            "reason_note": note,
            "policy": policy,
        }

    # Routine / confirm-completed — system action; optional note preserved.
    system = policy["system_action"]
    if note:
        audit = f"{system}: {note}"
    else:
        audit = system
    return {
        "ok": True,
        "reason": audit,
        "reason_code": None if policy.get("confirm_completed") or not code else code,
        "reason_note": note,
        "policy": policy,
    }


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip().replace("Z", "")
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        if " " in text:
            return datetime.fromisoformat(text.replace(" ", "T", 1))
        d = date.fromisoformat(text[:10])
        return datetime(d.year, d.month, d.day, 12, 0, 0)
    except ValueError:
        return None


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _normalize_outcome_action(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if not s or s in ("none", "null", "decide_later"):
        return None
    return s


def ensure_step1_bag_edit_tables(cursor) -> None:
    """CREATE IF NOT EXISTS for the unified edit-bag audit tables."""
    global _BAG_EDIT_TABLES_READY
    if _BAG_EDIT_TABLES_READY:
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_bag_edits (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            shift_date_et DATE NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            reason TEXT NOT NULL,
            actor_user_id INT NULL,
            actor_display_name VARCHAR(255) NULL,
            before_json LONGTEXT NULL,
            after_json LONGTEXT NULL,
            outcome_action VARCHAR(64) NULL,
            expected_updated_at DATETIME NULL,
            parent_edit_id BIGINT NULL,
            is_undo TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_step1_bag_edits_bag (organization_id, shift_date_et, bag_id, created_at),
            KEY idx_step1_bag_edits_parent (parent_edit_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_bag_edit_deltas (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            edit_id BIGINT NOT NULL,
            field_name VARCHAR(128) NOT NULL,
            before_value TEXT NULL,
            after_value TEXT NULL,
            KEY idx_step1_bag_edit_deltas_edit (edit_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _BAG_EDIT_TABLES_READY = True


def capture_bag_edit_state(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_id: str,
) -> dict[str, Any]:
    """Snapshot the current editable state of a bag for before/after audit + FE drawer."""
    from backend.rinse_bulk_workitems import (
        RESOLUTION_NO_CHARGE,
        load_bag_bulk_lines,
        load_bulk_resolutions,
    )
    from backend.rinse_veewash_shift_day import load_day_bags_by_ids

    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"bag_id": bid}

    day_rows = load_day_bags_by_ids(cursor, organization_id, shift_date_et, [bid])
    day_row = day_rows[0] if day_rows else {}
    snap = day_row.get("bag_snapshot") or {}

    service_type = str(day_row.get("service_type") or snap.get("service_type") or "").upper() or None
    rush_flag = day_row.get("rush_status") or snap.get("rush_flag")
    entry_at = (
        day_row.get("workload_entry_timestamp")
        or snap.get("original_entry_date")
        or snap.get("first_entry_at")
    )
    entry_source = day_row.get("workload_entry_type") or snap.get("entry_source")
    rack = snap.get("rack")

    if (not service_type or not rush_flag) and table_exists(cursor, "rinse_cleaner_ticket_presence"):
        cursor.execute(
            """
            SELECT service_type, rush_flag FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id = %s
            LIMIT 1
            """,
            (int(organization_id), bid),
        )
        prow = cursor.fetchone() or {}
        service_type = service_type or prow.get("service_type")
        rush_flag = rush_flag or prow.get("rush_flag")

    bulk_lines = (load_bag_bulk_lines(cursor, organization_id, shift_date_et, [bid]) or {}).get(bid) or []
    bulk_items = [
        {
            "workitem_id": x.get("workitem_id"),
            "name": x.get("workitem_name"),
            "quantity": x.get("quantity"),
            "unit_price": x.get("unit_price"),
            "line_total": x.get("line_total"),
        }
        for x in bulk_lines
    ]
    resolution = (load_bulk_resolutions(cursor, organization_id, shift_date_et, [bid]) or {}).get(bid) or {}
    no_chargeable = str(resolution.get("resolution_type") or "").strip().lower() == RESOLUTION_NO_CHARGE
    no_charge_reason = resolution.get("no_charge_reason")

    dashboard_status = day_row.get("effective_status") or snap.get("outcome") or snap.get("final_bucket")
    completion_at = day_row.get("canonical_completion_timestamp") or snap.get("completion_at")
    completed_by = day_row.get("canonical_completion_employee") or snap.get("completed_by")
    updated_at = day_row.get("updated_at")

    def _iso(v: Any) -> Any:
        return v.isoformat() if hasattr(v, "isoformat") else v

    pre_weight = day_row.get("pre_weight_lbs")
    post_weight = day_row.get("post_weight_lbs")

    return {
        "bag_id": bid,
        "service_type": service_type,
        "rush_flag": rush_flag,
        "entry_at": _iso(entry_at),
        "entry_source": entry_source,
        "rack": rack,
        "pre_weight_lbs": float(pre_weight) if pre_weight is not None else None,
        "post_weight_lbs": float(post_weight) if post_weight is not None else None,
        "bulk_items": bulk_items,
        "no_chargeable": no_chargeable,
        "no_charge_reason": no_charge_reason,
        "dashboard_status": dashboard_status,
        "outcome": dashboard_status,
        "completion_at": _iso(completion_at),
        "completed_by": completed_by,
        "updated_at": _iso(updated_at),
    }


def validate_edit_draft(draft: Mapping[str, Any], *, service_type: str | None = None) -> list[str]:
    """Validate a proposed Edit Bag draft. Returns a list of error codes (empty = valid).

    Note: ``reason`` is required by the caller (``apply_unified_bag_edit``), not here.
    """
    errors: list[str] = []
    svc = str(draft.get("service_type") or service_type or "").strip().upper()

    bulk_items = draft.get("bulk_items")
    if bulk_items is not None:
        positive_qty_total = 0
        for item in bulk_items:
            qty_raw = (item or {}).get("quantity")
            try:
                qty_f = float(qty_raw)
            except (TypeError, ValueError):
                errors.append("bulk_quantity_must_be_integer")
                continue
            if qty_f != int(qty_f):
                errors.append("bulk_quantity_must_be_integer")
                continue
            qty = int(qty_f)
            if qty < 0:
                errors.append("bulk_quantity_must_be_non_negative")
                continue
            if qty > 0:
                positive_qty_total += qty
        if positive_qty_total > 0 and svc == SERVICE_HD:
            errors.append("bulk_workitems_wf_only")
        if draft.get("no_chargeable") and positive_qty_total > 0:
            errors.append("no_chargeable_conflicts_with_items")

    for weight_key in ("pre_weight_lbs", "post_weight_lbs"):
        if weight_key in draft:
            normalized = normalize_scan_weight_lbs(draft.get(weight_key))
            if normalized is not None and normalized < 0:
                errors.append(f"{weight_key}_must_be_non_negative")

    # De-dupe while preserving first-seen order.
    return list(dict.fromkeys(errors))


def _apply_service_rush_update(
    cursor,
    organization_id: int,
    bag_id: str,
    shift_date_et: date,
    *,
    service_type: Any,
    rush_flag: Any,
) -> None:
    svc = str(service_type).strip().upper() if service_type else None
    cursor.execute(
        """
        SELECT bag_snapshot_json FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), shift_date_et, bag_id),
    )
    row = cursor.fetchone() or {}
    snap = _json_load(row.get("bag_snapshot_json")) or {}
    snap["service_type"] = svc
    snap["rush_flag"] = rush_flag
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_day_bags
        SET service_type = %s, rush_status = %s, bag_snapshot_json = %s
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        """,
        (svc, rush_flag, _json_dump(snap), int(organization_id), shift_date_et, bag_id),
    )
    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        cursor.execute(
            """
            UPDATE rinse_cleaner_ticket_presence
            SET service_type = %s, rush_flag = %s
            WHERE organization_id = %s AND bag_id = %s
            """,
            (svc, rush_flag, int(organization_id), bag_id),
        )


def _apply_entry_correction(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    service_type: Any,
    entry_at: Any,
    rack: Any,
    employee: Any,
) -> None:
    ts = _parse_dt(entry_at)
    if ts is None:
        return
    from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
    from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
    from backend.rinse_scan_event_identity import dedupe_key_from_row

    svc = str(service_type or SERVICE_WF).upper()
    if svc == SERVICE_HD:
        purpose = "workitems-added"
        rack_val = None
    else:
        purpose = "move-bag"
        rack_val = str(
            rack or (DEFAULT_FACILITY_ENTRY_RACKS[0] if DEFAULT_FACILITY_ENTRY_RACKS else "VeeWash Dirty")
        )

    ensure_rinse_bag_scan_events_table(cursor)
    time_raw = ts.strftime("%Y-%m-%d %H:%M:%S")
    emp = str(employee or "manager").strip()
    row = {
        "organization_id": int(organization_id),
        "bag_id": bag_id,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "time_scanned_raw": time_raw,
        "user_name": emp,
        "rack": rack_val,
    }
    dedupe = dedupe_key_from_row(row)
    cursor.execute(
        """
        INSERT INTO rinse_bag_scan_events (
            organization_id, bag_id, purpose, scanned_at_parsed, time_scanned_raw,
            user_name, rack, dedupe_key, raw_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE scanned_at_parsed=VALUES(scanned_at_parsed),
            rack=VALUES(rack), purpose=VALUES(purpose)
        """,
        (
            int(organization_id),
            bag_id,
            purpose,
            ts,
            time_raw,
            emp,
            rack_val,
            dedupe,
            json.dumps(
                {
                    "backfill_source": "step1_edit_bag",
                    "service_type": svc,
                    "operator_approved": True,
                }
            ),
        ),
    )


def _apply_weight_update(
    cursor,
    organization_id: int,
    bag_id: str,
    shift_date_et: date,
    *,
    pre_weight_lbs: float | None,
    post_weight_lbs: float | None,
    before: Mapping[str, Any],
    reason: str,
    actor_user_id: int | None,
    actor_display_name: str | None,
) -> None:
    new_weight = post_weight_lbs if post_weight_lbs is not None else pre_weight_lbs
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_day_bags
        SET pre_weight_lbs = %s, post_weight_lbs = %s, weight_lbs = %s
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        """,
        (pre_weight_lbs, post_weight_lbs, new_weight, int(organization_id), shift_date_et, bag_id),
    )
    # Also record on rinse_step1_corrections so existing weight-map loaders that
    # read that table for reconciliation history stay in sync.
    from backend.rinse_veewash_step1_api import _record_correction

    _record_correction(
        cursor,
        organization_id,
        bag_id=bag_id,
        action="correct_weight",
        reason_text=reason,
        reason_code="EDIT_BAG_WEIGHT",
        previous_values={
            "pre_weight_lbs": before.get("pre_weight_lbs"),
            "post_weight_lbs": before.get("post_weight_lbs"),
        },
        new_values={
            "pre_weight_lbs": pre_weight_lbs,
            "post_weight_lbs": post_weight_lbs,
        },
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )


def apply_unified_bag_edit(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    reason: str,
    draft: Mapping[str, Any],
    expected_updated_at: Any = None,
    outcome_action: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    reason_code: str | None = None,
    reason_note: str | None = None,
) -> dict[str, Any]:
    """Apply a unified Edit Bag draft as one atomic edit with a single audit row.

    Returns ``{"ok": False, "error": ...}`` (with ``status: 409`` + ``latest`` on
    ``updated_at`` conflict) or ``{"ok": True, "edit_id", "before", "after",
    "undo_token", "bag", "deltas"}``.
    """
    ensure_step1_bag_edit_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}

    draft = dict(draft or {})
    outcome = _normalize_outcome_action(outcome_action)
    if outcome is not None and outcome not in VALID_OUTCOME_ACTIONS:
        return {"ok": False, "error": "invalid_outcome_action"}

    before = capture_bag_edit_state(cursor, organization_id, selected_date_et, bid)

    if expected_updated_at not in (None, ""):
        expected_dt = _parse_dt(expected_updated_at)
        current_dt = _parse_dt(before.get("updated_at"))
        if expected_dt is not None and current_dt is not None and expected_dt != current_dt:
            return {
                "ok": False,
                "error": "conflict",
                "status": 409,
                "current_version": before.get("updated_at"),
                "latest": before,
            }

    resolved = resolve_edit_audit_reason(
        reason=reason,
        reason_code=reason_code,
        reason_note=reason_note,
        draft=draft,
        before=before,
        outcome=outcome,
    )
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error") or "reason_required",
            "policy": resolved.get("policy"),
        }
    reason_text = str(resolved["reason"])

    effective_service = str(draft.get("service_type") or before.get("service_type") or "").strip().upper()
    errors = validate_edit_draft(draft, service_type=effective_service)
    if errors:
        return {"ok": False, "error": "validation_failed", "errors": errors}

    # a. service / rush ---------------------------------------------------
    if "service_type" in draft or "rush_flag" in draft:
        _apply_service_rush_update(
            cursor,
            organization_id,
            bid,
            selected_date_et,
            service_type=draft.get("service_type", before.get("service_type")),
            rush_flag=draft.get("rush_flag", before.get("rush_flag")),
        )

    # b. entry --------------------------------------------------------------
    if "entry_at" in draft:
        _apply_entry_correction(
            cursor,
            organization_id,
            bid,
            service_type=draft.get("service_type", before.get("service_type")) or SERVICE_WF,
            entry_at=draft.get("entry_at"),
            rack=draft.get("rack"),
            employee=draft.get("employee") or actor_display_name,
        )

    # c. weights --------------------------------------------------------------
    if "pre_weight_lbs" in draft or "post_weight_lbs" in draft:
        new_pre = normalize_scan_weight_lbs(draft.get("pre_weight_lbs", before.get("pre_weight_lbs")))
        new_post = normalize_scan_weight_lbs(draft.get("post_weight_lbs", before.get("post_weight_lbs")))
        _apply_weight_update(
            cursor,
            organization_id,
            bid,
            selected_date_et,
            pre_weight_lbs=new_pre,
            post_weight_lbs=new_post,
            before=before,
            reason=reason_text,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )

    # d. bulk workitems -------------------------------------------------------
    if "bulk_items" in draft or "no_chargeable" in draft or "no_charge_reason" in draft:
        from backend.rinse_bulk_workitems import save_bag_bulk_workitems

        bulk_out = save_bag_bulk_workitems(
            cursor,
            organization_id,
            shift_date_et=selected_date_et,
            bag_id=bid,
            items=list(draft.get("bulk_items") or []),
            no_chargeable=bool(draft.get("no_chargeable")),
            no_charge_reason=draft.get("no_charge_reason"),
            reason=reason_text,
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
            allow_closed=False,
            allow_empty_clear=True,
            allow_system_audit_reason=True,
        )
        if not bulk_out.get("ok"):
            return {
                "ok": False,
                "error": bulk_out.get("error") or "bulk_update_failed",
                "detail": bulk_out,
            }

    # e/f. completion + outcome ------------------------------------------------
    outcome_result: dict[str, Any] | None = None
    if outcome == OUTCOME_MARK_COMPLETED:
        from backend.rinse_operator_manual_correction import apply_operator_approved_manual_completion

        emp = str(
            draft.get("completion_employee")
            or draft.get("completed_by")
            or draft.get("employee")
            or actor_display_name
            or ""
        ).strip()
        if not emp:
            return {"ok": False, "error": "completion_employee_required"}
        ts = _parse_dt(draft.get("completion_at")) or datetime.utcnow()
        weight_for_completion = normalize_scan_weight_lbs(
            draft.get("post_weight_lbs", before.get("post_weight_lbs"))
        )
        if not weight_for_completion or weight_for_completion <= 0:
            weight_for_completion = 0.1
        outcome_result = apply_operator_approved_manual_completion(
            cursor,
            organization_id,
            bid,
            credited_employee=emp,
            weight_lbs=weight_for_completion,
            selected_date_et=selected_date_et,
            completion_timestamp=ts,
            upload_batch_id=int(draft.get("upload_batch_id") or 0),
            remarks=reason_text,
            actor_user_id=actor_user_id,
        )
    elif outcome in (OUTCOME_RETURN_PENDING, OUTCOME_EXCLUDE):
        from backend.rinse_veewash_step1_api import _record_correction

        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=outcome,
            reason_text=reason_text,
            reason_code=outcome.upper(),
            previous_values=before,
            new_values={"status": outcome},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
    # OUTCOME_KEEP_REVIEW / None: no bucket change beyond draft field updates.

    after = capture_bag_edit_state(cursor, organization_id, selected_date_et, bid)

    try:
        from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

        proj = project_productivity_fields_for_day_bag(
            {
                "effective_status": after.get("dashboard_status"),
                "canonical_completion_employee": after.get("completed_by"),
                "canonical_completion_timestamp": after.get("completion_at"),
                "weight_lbs": after.get("post_weight_lbs") or after.get("pre_weight_lbs"),
                "post_weight_lbs": after.get("post_weight_lbs"),
            }
        )
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET productivity_employee_name = %s,
                productivity_completed_at = %s,
                productivity_weight_lbs = %s,
                productivity_credit_eligible = %s,
                productivity_exclusion_reason = %s
            WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
            """,
            (
                proj.get("productivity_employee_name"),
                _parse_dt(proj.get("productivity_completed_at")),
                proj.get("productivity_weight_lbs"),
                proj.get("productivity_credit_eligible"),
                proj.get("productivity_exclusion_reason"),
                int(organization_id),
                selected_date_et,
                bid,
            ),
        )
    except ImportError:
        pass
    except Exception:
        pass

    deltas: list[dict[str, Any]] = []
    for field in _TRACKED_FIELDS:
        b_val = before.get(field)
        a_val = after.get(field)
        if _normalize_for_compare(b_val) != _normalize_for_compare(a_val):
            deltas.append({"field_name": field, "before_value": b_val, "after_value": a_val})
    if outcome:
        deltas.append({"field_name": "outcome_action", "before_value": None, "after_value": outcome})

    cursor.execute(
        """
        INSERT INTO rinse_step1_bag_edits (
            organization_id, shift_date_et, bag_id, reason, actor_user_id, actor_display_name,
            before_json, after_json, outcome_action, expected_updated_at, parent_edit_id, is_undo
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
        """,
        (
            int(organization_id),
            selected_date_et,
            bid,
            reason_text,
            actor_user_id,
            actor_display_name,
            _json_dump(before),
            _json_dump(after),
            outcome,
            _parse_dt(expected_updated_at),
            None,
        ),
    )
    edit_id = int(cursor.lastrowid)
    for d in deltas:
        cursor.execute(
            """
            INSERT INTO rinse_step1_bag_edit_deltas (edit_id, field_name, before_value, after_value)
            VALUES (%s,%s,%s,%s)
            """,
            (edit_id, d["field_name"], _stringify(d["before_value"]), _stringify(d["after_value"])),
        )

    try:
        from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

        clear_step1_productivity_cache(organization_id, selected_date_et)
    except Exception:
        pass

    return {
        "ok": True,
        "edit_id": edit_id,
        "before": before,
        "after": after,
        "undo_token": edit_id,
        "bag": after,
        "deltas": deltas,
        "outcome_result": outcome_result,
    }


def _load_edit(cursor, organization_id: int, edit_id: int) -> dict[str, Any] | None:
    ensure_step1_bag_edit_tables(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, shift_date_et, bag_id, reason, actor_user_id, actor_display_name,
               before_json, after_json, outcome_action, expected_updated_at, parent_edit_id, is_undo,
               created_at
        FROM rinse_step1_bag_edits
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(edit_id)),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _load_latest_edit_for_bag(
    cursor, organization_id: int, bag_id: str, shift_date_et: date
) -> dict[str, Any] | None:
    ensure_step1_bag_edit_tables(cursor)
    cursor.execute(
        """
        SELECT id, bag_id, shift_date_et, created_at
        FROM rinse_step1_bag_edits
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(organization_id), shift_date_et, normalize_bag_id(bag_id)),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _draft_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a restore draft from a captured before/after state snapshot."""
    draft: dict[str, Any] = {
        "service_type": state.get("service_type"),
        "rush_flag": state.get("rush_flag"),
        "pre_weight_lbs": state.get("pre_weight_lbs"),
        "post_weight_lbs": state.get("post_weight_lbs"),
        # Always include bulk so undo can clear lines added by the edit.
        "bulk_items": [
            {"workitem_id": x.get("workitem_id"), "quantity": x.get("quantity")}
            for x in (state.get("bulk_items") or [])
        ],
        "no_chargeable": bool(state.get("no_chargeable")),
        "no_charge_reason": state.get("no_charge_reason"),
    }
    if state.get("entry_at"):
        draft["entry_at"] = state.get("entry_at")
        draft["rack"] = state.get("rack")
    if state.get("completion_at") is not None:
        draft["completion_at"] = state.get("completion_at")
    if state.get("completed_by") is not None:
        draft["completed_by"] = state.get("completed_by")
    return draft


def undo_bag_edit(
    cursor,
    organization_id: int,
    *,
    edit_id: int,
    reason: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Undo a prior Edit Bag by re-applying its ``before_json`` state as a new edit.

    Blocked (``newer_edit_exists``) unless ``edit_id`` is the latest edit for that
    bag/date, so undo never clobbers a subsequent edit.
    """
    ensure_step1_bag_edit_tables(cursor)
    edit = _load_edit(cursor, organization_id, edit_id)
    if not edit:
        return {"ok": False, "error": "edit_not_found"}

    bag_id = normalize_bag_id(edit.get("bag_id"))
    shift_date_et = edit.get("shift_date_et")

    latest = _load_latest_edit_for_bag(cursor, organization_id, bag_id, shift_date_et)
    if not latest or int(latest["id"]) != int(edit_id):
        return {"ok": False, "error": "newer_edit_exists"}

    before_state = _json_load(edit.get("before_json")) or {}
    draft = _draft_from_state(before_state)
    undo_reason = str(reason or "").strip() or f"Undo edit #{edit_id}"

    result = apply_unified_bag_edit(
        cursor,
        organization_id,
        bag_id=bag_id,
        selected_date_et=shift_date_et,
        reason=undo_reason,
        draft=draft,
        expected_updated_at=None,
        outcome_action=None,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )
    if not result.get("ok"):
        return result

    new_edit_id = result["edit_id"]
    cursor.execute(
        """
        UPDATE rinse_step1_bag_edits
        SET is_undo = 1, parent_edit_id = %s
        WHERE organization_id = %s AND id = %s
        """,
        (int(edit_id), int(organization_id), int(new_edit_id)),
    )
    result["is_undo"] = True
    result["restored_from_edit_id"] = int(edit_id)
    return result
