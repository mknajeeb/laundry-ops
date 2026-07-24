"""Daily Operations Phase 1C — HD bag production overlay."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from backend.daily_operations import (
    STEP1_AUTHORITATIVE_START_ET,
    TRACKING_STARTED_MESSAGE,
    build_daily_operations_day,
    daily_operations_enabled_for_org,
    ensure_daily_operations_tables,
    _norm_bag,
)
from backend.ta_helpers import table_exists
from backend.wf_mtd_pricing import money

MONEY_Q = Decimal("0.01")

STATUS_NOT_RECORDED = "NOT_RECORDED"
STATUS_PARTIALLY_RECORDED = "PARTIALLY_RECORDED"
STATUS_COMPLETE = "COMPLETE"

EXTERNAL_WORKER_OPTION_ID = "external_unknown"
EXTERNAL_WORKER_LABEL = "External / Unknown Worker"

ZERO_REVENUE_CODES = frozenset(
    {"NO_CHARGE", "REWASH", "TEST_ORDER", "MANAGER_OVERRIDE", "OTHER"}
)
ZERO_ITEMS_CODES = frozenset(
    {"EMPTY_BAG", "DATA_CORRECTION", "TEST_ORDER", "MANAGER_OVERRIDE", "OTHER"}
)

ACTION_CREATE = "CREATE"
ACTION_UPDATE = "UPDATE"
ACTION_UNDO = "UNDO"


def ensure_hd_production_tables(cursor) -> None:
    ensure_daily_operations_tables(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hd_day_bag_production (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              operations_date_et DATE NOT NULL,
              day_bag_id BIGINT NULL,
              bag_id VARCHAR(32) NOT NULL,
              washed_by_user_id INT NULL,
              washed_by_name_snapshot VARCHAR(255) NULL,
              washed_by_override_name VARCHAR(255) NULL,
              folded_by_user_id INT NULL,
              folded_by_name_snapshot VARCHAR(255) NULL,
              folded_by_override_name VARCHAR(255) NULL,
              total_items INT NULL,
              revenue DECIMAL(12,2) NULL,
              zero_items_reason_code VARCHAR(64) NULL,
              zero_items_reason_note VARCHAR(512) NULL,
              zero_revenue_reason_code VARCHAR(64) NULL,
              zero_revenue_reason_note VARCHAR(512) NULL,
              notes TEXT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'NOT_RECORDED',
              created_by_user_id INT NULL,
              updated_by_user_id INT NULL,
              version INT NOT NULL DEFAULT 1,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_hd_day_bag_prod (organization_id, operations_date_et, bag_id),
              INDEX idx_hd_day_bag_prod_status (organization_id, operations_date_et, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, "hd_day_bag_production_audits"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hd_day_bag_production_audits (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              operations_date_et DATE NOT NULL,
              bag_id VARCHAR(32) NOT NULL,
              production_fact_id BIGINT NULL,
              action VARCHAR(64) NOT NULL,
              version_before INT NULL,
              version_after INT NULL,
              before_json JSON NULL,
              after_json JSON NULL,
              reason VARCHAR(512) NULL,
              actor_user_id INT NULL,
              actor_display_name VARCHAR(255) NULL,
              is_undo TINYINT(1) NOT NULL DEFAULT 0,
              undone_audit_id BIGINT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_hd_bag_prod_aud_bag (organization_id, operations_date_et, bag_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _d(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def list_hd_day_membership_bags(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> list[dict[str, Any]]:
    """All HD bags on append-only ET-day membership. Does not rebuild membership."""
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return []
    org = int(organization_id)
    cursor.execute(
        """
        SELECT bag_id, service_type, rush_status, canonical_completion_status,
               canonical_completion_timestamp, workload_entry_timestamp,
               effective_status, id AS day_bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'HD'
        ORDER BY bag_id
        """,
        (org, operations_date_et),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    if table_exists(cursor, "rinse_et_day_workload_ledger"):
        cursor.execute(
            """
            SELECT bag_id FROM rinse_et_day_workload_ledger
            WHERE organization_id = %s AND et_date = %s
            """,
            (org, operations_date_et),
        )
        member = {_norm_bag(r.get("bag_id")) for r in (cursor.fetchall() or [])}
        if member:
            rows = [r for r in rows if _norm_bag(r.get("bag_id")) in member]
    return rows


def get_hd_production_row(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
) -> dict[str, Any] | None:
    ensure_hd_production_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
        LIMIT 1
        """,
        (int(organization_id), operations_date_et, _norm_bag(bag_id)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def list_org_employee_options(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Organization employee directory for HD pickers (not clocked-in-only)."""
    org = int(organization_id)
    options: list[dict[str, Any]] = []
    if not table_exists(cursor, "users"):
        options.append(
            {
                "id": EXTERNAL_WORKER_OPTION_ID,
                "user_id": None,
                "display_name": EXTERNAL_WORKER_LABEL,
                "is_external": True,
            }
        )
        return options

    # Prefer active org users; exclude obvious portal system accounts when helper exists.
    try:
        from backend.portal_system_users import is_portal_system_user
    except Exception:
        is_portal_system_user = None  # type: ignore

    has_active = False
    try:
        from backend.ta_helpers import table_has_column

        has_active = table_has_column(cursor, "users", "active")
    except Exception:
        has_active = False

    sql = """
        SELECT id, username, display_name, email
        FROM users
        WHERE organization_id = %s
    """
    if has_active:
        sql += " AND COALESCE(active, 1) = 1"
    sql += " ORDER BY COALESCE(display_name, username, email), id"
    cursor.execute(sql, (org,))
    for row in cursor.fetchall() or []:
        uid = int(row["id"])
        if is_portal_system_user is not None:
            try:
                if is_portal_system_user(cursor, org, uid):
                    continue
            except Exception:
                pass
        name = (
            str(row.get("display_name") or "").strip()
            or str(row.get("username") or "").strip()
            or str(row.get("email") or "").strip()
            or f"User {uid}"
        )
        options.append(
            {
                "id": uid,
                "user_id": uid,
                "display_name": name,
                "is_external": False,
            }
        )
    options.append(
        {
            "id": EXTERNAL_WORKER_OPTION_ID,
            "user_id": None,
            "display_name": EXTERNAL_WORKER_LABEL,
            "is_external": True,
        }
    )
    return options


def resolve_employee_display_name(cursor, organization_id: int, user_id: int) -> str:
    cursor.execute(
        """
        SELECT display_name, username, email FROM users
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(user_id), int(organization_id)),
    )
    row = cursor.fetchone() or {}
    return (
        str(row.get("display_name") or "").strip()
        or str(row.get("username") or "").strip()
        or str(row.get("email") or "").strip()
        or f"User {user_id}"
    )


def _has_worker(user_id: Any, override_name: Any) -> bool:
    if user_id is not None and str(user_id).strip() != "" and str(user_id) != EXTERNAL_WORKER_OPTION_ID:
        try:
            return int(user_id) > 0
        except Exception:
            return False
    return bool(str(override_name or "").strip())


def derive_hd_production_status(fields: Mapping[str, Any]) -> str:
    """Server-derived status from production field presence + validation readiness."""
    washed = _has_worker(fields.get("washed_by_user_id"), fields.get("washed_by_override_name"))
    folded = _has_worker(fields.get("folded_by_user_id"), fields.get("folded_by_override_name"))
    items = fields.get("total_items")
    revenue = fields.get("revenue")
    has_items = items is not None and str(items) != ""
    has_revenue = revenue is not None and str(revenue) != ""

    any_entered = washed or folded or has_items or has_revenue
    if not any_entered and not str(fields.get("notes") or "").strip():
        # Notes alone do not count as production fields for NOT_RECORDED.
        return STATUS_NOT_RECORDED
    if not any_entered:
        return STATUS_NOT_RECORDED

    errors = validate_hd_production_fields(fields, require_complete=True)
    if not errors and washed and folded and has_items and has_revenue:
        return STATUS_COMPLETE
    return STATUS_PARTIALLY_RECORDED


def validate_hd_production_fields(
    fields: Mapping[str, Any],
    *,
    require_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    washed_uid = fields.get("washed_by_user_id")
    folded_uid = fields.get("folded_by_user_id")
    washed_override = str(fields.get("washed_by_override_name") or "").strip()
    folded_override = str(fields.get("folded_by_override_name") or "").strip()
    washed_ext = bool(fields.get("washed_by_external"))
    folded_ext = bool(fields.get("folded_by_external"))

    # Reject free-text without controlled external option.
    if washed_override and not washed_ext and washed_uid is None:
        errors.append("washed_by_free_text_requires_external_option")
    if folded_override and not folded_ext and folded_uid is None:
        errors.append("folded_by_free_text_requires_external_option")
    if washed_ext and not washed_override:
        errors.append("washed_by_external_requires_override_name")
    if folded_ext and not folded_override:
        errors.append("folded_by_external_requires_override_name")
    if washed_ext and not str(fields.get("washed_by_external_reason") or fields.get("reason") or "").strip():
        errors.append("washed_by_external_requires_reason")
    if folded_ext and not str(fields.get("folded_by_external_reason") or fields.get("reason") or "").strip():
        errors.append("folded_by_external_requires_reason")

    items_raw = fields.get("total_items")
    if items_raw is not None and str(items_raw) != "":
        try:
            items_v = int(items_raw)
        except Exception:
            errors.append("invalid_total_items")
            items_v = None
        else:
            if items_v < 0:
                errors.append("negative_total_items_rejected")
            elif items_v == 0:
                code = str(fields.get("zero_items_reason_code") or "").strip().upper()
                if code not in ZERO_ITEMS_CODES:
                    errors.append("zero_items_reason_required")
                elif code == "OTHER" and not str(fields.get("zero_items_reason_note") or "").strip():
                    errors.append("zero_items_other_requires_note")

    rev_raw = fields.get("revenue")
    if rev_raw is not None and str(rev_raw) != "":
        rev = _d(rev_raw)
        if rev is None:
            errors.append("invalid_revenue")
        elif rev < 0:
            errors.append("negative_revenue_rejected")
        elif rev == 0:
            code = str(fields.get("zero_revenue_reason_code") or "").strip().upper()
            if code not in ZERO_REVENUE_CODES:
                errors.append("zero_revenue_reason_required")
            elif code == "OTHER" and not str(fields.get("zero_revenue_reason_note") or "").strip():
                errors.append("zero_revenue_other_requires_note")

    if require_complete:
        if not _has_worker(fields.get("washed_by_user_id"), fields.get("washed_by_override_name")):
            errors.append("washed_by_required")
        if not _has_worker(fields.get("folded_by_user_id"), fields.get("folded_by_override_name")):
            errors.append("folded_by_required")
        if items_raw is None or str(items_raw) == "":
            errors.append("total_items_required")
        if rev_raw is None or str(rev_raw) == "":
            errors.append("revenue_required")
    return errors


def _normalize_worker_fields(
    cursor,
    organization_id: int,
    payload: Mapping[str, Any],
    *,
    role: str,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve washed/folded worker to IDs + snapshots. role = washed|folded."""
    errors: list[str] = []
    prefix = f"{role}_by"
    raw_id = payload.get(f"{prefix}_user_id")
    external = bool(payload.get(f"{prefix}_external")) or str(raw_id) == EXTERNAL_WORKER_OPTION_ID
    override = str(payload.get(f"{prefix}_override_name") or "").strip()
    ext_reason = str(payload.get(f"{prefix}_external_reason") or payload.get("reason") or "").strip()

    out: dict[str, Any] = {
        f"{prefix}_user_id": None,
        f"{prefix}_name_snapshot": None,
        f"{prefix}_override_name": None,
        f"{prefix}_external": False,
        f"{prefix}_external_reason": None,
    }

    if external:
        out[f"{prefix}_external"] = True
        out[f"{prefix}_override_name"] = override or None
        out[f"{prefix}_external_reason"] = ext_reason or None
        out[f"{prefix}_name_snapshot"] = (
            f"{EXTERNAL_WORKER_LABEL}: {override}" if override else EXTERNAL_WORKER_LABEL
        )
        return out, errors

    if raw_id in (None, "", EXTERNAL_WORKER_OPTION_ID):
        # Free-text without external flag is rejected later.
        if override:
            out[f"{prefix}_override_name"] = override
        return out, errors

    try:
        uid = int(raw_id)
    except Exception:
        errors.append(f"{prefix}_invalid_user_id")
        return out, errors

    name = resolve_employee_display_name(cursor, organization_id, uid)
    # Verify org membership
    cursor.execute(
        "SELECT id FROM users WHERE id = %s AND organization_id = %s LIMIT 1",
        (uid, int(organization_id)),
    )
    if not cursor.fetchone():
        errors.append(f"{prefix}_user_not_in_organization")
        return out, errors
    out[f"{prefix}_user_id"] = uid
    out[f"{prefix}_name_snapshot"] = name
    return out, errors


def _fact_public(fact: Mapping[str, Any] | None, *, membership: Mapping[str, Any] | None = None) -> dict[str, Any]:
    mem = membership or {}
    if not fact:
        return {
            "bag_id": _norm_bag(mem.get("bag_id")),
            "day_bag_id": mem.get("day_bag_id"),
            "version": 0,
            "status": STATUS_NOT_RECORDED,
            "exists": False,
            "washed_by_user_id": None,
            "washed_by_name_snapshot": None,
            "washed_by_override_name": None,
            "folded_by_user_id": None,
            "folded_by_name_snapshot": None,
            "folded_by_override_name": None,
            "total_items": None,
            "revenue": None,
            "zero_items_reason_code": None,
            "zero_items_reason_note": None,
            "zero_revenue_reason_code": None,
            "zero_revenue_reason_note": None,
            "notes": None,
            "included_in_day_revenue": False,
            "updated_by_user_id": None,
            "updated_at": None,
        }
    status = str(fact.get("status") or STATUS_NOT_RECORDED)
    rev = fact.get("revenue")
    return {
        "bag_id": _norm_bag(fact.get("bag_id")),
        "day_bag_id": fact.get("day_bag_id") or mem.get("day_bag_id"),
        "id": fact.get("id"),
        "version": int(fact.get("version") or 1),
        "status": status,
        "exists": True,
        "washed_by_user_id": fact.get("washed_by_user_id"),
        "washed_by_name_snapshot": fact.get("washed_by_name_snapshot"),
        "washed_by_override_name": fact.get("washed_by_override_name"),
        "folded_by_user_id": fact.get("folded_by_user_id"),
        "folded_by_name_snapshot": fact.get("folded_by_name_snapshot"),
        "folded_by_override_name": fact.get("folded_by_override_name"),
        "total_items": int(fact["total_items"]) if fact.get("total_items") is not None else None,
        "revenue": float(rev) if rev is not None else None,
        "zero_items_reason_code": fact.get("zero_items_reason_code"),
        "zero_items_reason_note": fact.get("zero_items_reason_note"),
        "zero_revenue_reason_code": fact.get("zero_revenue_reason_code"),
        "zero_revenue_reason_note": fact.get("zero_revenue_reason_note"),
        "notes": fact.get("notes"),
        "included_in_day_revenue": status == STATUS_COMPLETE,
        "created_by_user_id": fact.get("created_by_user_id"),
        "updated_by_user_id": fact.get("updated_by_user_id"),
        "created_at": fact.get("created_at"),
        "updated_at": fact.get("updated_at"),
    }


def compute_hd_day_revenue_totals(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> dict[str, Any]:
    ensure_hd_production_tables(cursor)
    membership = list_hd_day_membership_bags(cursor, organization_id, operations_date_et)
    member_ids = {_norm_bag(r.get("bag_id")) for r in membership}
    cursor.execute(
        """
        SELECT bag_id, status, total_items, revenue
        FROM hd_day_bag_production
        WHERE organization_id = %s AND operations_date_et = %s
        """,
        (int(organization_id), operations_date_et),
    )
    facts = [dict(r) for r in (cursor.fetchall() or [])]
    orphan_facts = [f for f in facts if _norm_bag(f.get("bag_id")) not in member_ids]

    not_recorded = 0
    partial = 0
    complete = 0
    complete_items = 0
    complete_rev = Decimal("0")
    partial_rev = Decimal("0")

    fact_by_bag = {_norm_bag(f.get("bag_id")): f for f in facts}
    for row in membership:
        bid = _norm_bag(row.get("bag_id"))
        fact = fact_by_bag.get(bid)
        status = str((fact or {}).get("status") or STATUS_NOT_RECORDED)
        if status == STATUS_COMPLETE:
            complete += 1
            if fact and fact.get("total_items") is not None:
                complete_items += int(fact["total_items"])
            if fact and fact.get("revenue") is not None:
                complete_rev += Decimal(str(fact["revenue"]))
        elif status == STATUS_PARTIALLY_RECORDED:
            partial += 1
            if fact and fact.get("revenue") is not None:
                partial_rev += Decimal(str(fact["revenue"]))
        else:
            not_recorded += 1

    return {
        "hd_orders_available": len(membership),
        "not_recorded": not_recorded,
        "partially_recorded": partial,
        "complete": complete,
        "complete_total_items": complete_items,
        "complete_hd_revenue": money(complete_rev),
        "partial_hd_revenue_entered": money(partial_rev),
        "total_hd_revenue": money(complete_rev),
        "orphan_production_facts": [
            {
                "bag_id": _norm_bag(f.get("bag_id")),
                "status": f.get("status"),
                "reconciliation_exception": True,
                "note": "production_fact_exists_but_bag_not_hd_in_membership",
            }
            for f in orphan_facts
        ],
    }


def sum_reviewed_wf_workitem_revenue(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> float:
    """Authoritative bag-level WI revenue from reviewed Daily Ops facts only."""
    if not table_exists(cursor, "wf_day_bag_revenue"):
        return 0.0
    cursor.execute(
        """
        SELECT COALESCE(SUM(workitem_revenue), 0) AS total
        FROM wf_day_bag_revenue
        WHERE organization_id = %s
          AND operations_date_et = %s
          AND review_status IN ('REVIEWED', 'ACCEPTED_EXCEPTION')
        """,
        (int(organization_id), operations_date_et),
    )
    row = cursor.fetchone() or {}
    return money(_d(row.get("total")) or Decimal("0"))


def build_hd_production_queue(
    cursor,
    organization_id: int,
    operations_date_et: date,
    *,
    status: str | None = None,
    rush_type: str | None = None,
    washed_by_user_id: int | None = None,
    folded_by_user_id: int | None = None,
    search: str | None = None,
    can_undo: bool = False,
) -> dict[str, Any]:
    org = int(organization_id)
    ensure_hd_production_tables(cursor)
    if not daily_operations_enabled_for_org(org):
        return {"available": False, "reason": "not_enabled"}
    if operations_date_et < STEP1_AUTHORITATIVE_START_ET:
        return {"available": False, "message": TRACKING_STARTED_MESSAGE}

    membership = list_hd_day_membership_bags(cursor, org, operations_date_et)
    facts = {}
    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production
        WHERE organization_id = %s AND operations_date_et = %s
        """,
        (org, operations_date_et),
    )
    for r in cursor.fetchall() or []:
        facts[_norm_bag(r.get("bag_id"))] = dict(r)

    items: list[dict[str, Any]] = []
    for row in membership:
        bid = _norm_bag(row.get("bag_id"))
        fact = facts.get(bid)
        pub = _fact_public(fact, membership=row)
        rush = str(row.get("rush_status") or "").strip().upper()
        item = {
            **pub,
            "membership": {
                "service_type": "HD",
                "rush_status": row.get("rush_status"),
                "first_available": row.get("workload_entry_timestamp"),
                "canonical_completion_status": row.get("canonical_completion_status"),
                "canonical_completion_timestamp": row.get("canonical_completion_timestamp"),
            },
            "rush_type": rush,
        }
        if status and pub["status"] != status.upper():
            continue
        if rush_type:
            rt = rush_type.strip().upper().replace("-", "_")
            bag_rt = rush.replace("-", "_")
            if rt == "RUSH" and "NON" in bag_rt:
                continue
            if rt in ("NON_RUSH", "NONRUSH") and "NON" not in bag_rt and bag_rt:
                # only non-rush
                if bag_rt and "RUSH" in bag_rt and "NON" not in bag_rt:
                    continue
            if rt == "RUSH" and bag_rt and "RUSH" not in bag_rt:
                continue
        if washed_by_user_id is not None and int(pub.get("washed_by_user_id") or 0) != int(
            washed_by_user_id
        ):
            continue
        if folded_by_user_id is not None and int(pub.get("folded_by_user_id") or 0) != int(
            folded_by_user_id
        ):
            continue
        if search:
            q = search.strip().lower()
            hay = " ".join(
                [
                    bid.lower(),
                    str(pub.get("washed_by_name_snapshot") or "").lower(),
                    str(pub.get("folded_by_name_snapshot") or "").lower(),
                    str(pub.get("notes") or "").lower(),
                ]
            )
            if q not in hay:
                continue
        items.append(item)

    summary = compute_hd_day_revenue_totals(cursor, org, operations_date_et)
    return {
        "available": True,
        "operations_date_et": operations_date_et.isoformat(),
        "summary": summary,
        "filters": {
            "status": status,
            "rush_type": rush_type,
            "washed_by_user_id": washed_by_user_id,
            "folded_by_user_id": folded_by_user_id,
            "search": search,
        },
        "items": items,
        "count": len(items),
        "employee_options": list_org_employee_options(cursor, org),
        "reason_codes": {
            "zero_revenue": sorted(ZERO_REVENUE_CODES),
            "zero_items": sorted(ZERO_ITEMS_CODES),
        },
        "permissions": {
            "can_read": True,
            "can_save": True,
            "can_undo": can_undo,
        },
        "jul23_membership_rebuild": False,
    }


def get_hd_production_detail(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    *,
    can_undo: bool = False,
) -> dict[str, Any]:
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    ensure_hd_production_tables(cursor)
    membership = {
        _norm_bag(r.get("bag_id")): r
        for r in list_hd_day_membership_bags(cursor, org, operations_date_et)
    }
    row = membership.get(bid)
    fact = get_hd_production_row(cursor, org, operations_date_et, bid)
    if not row and not fact:
        return {"ok": False, "error": "bag_not_hd_on_day", "bag_id": bid}
    orphan = False
    if not row and fact:
        orphan = True
    pub = _fact_public(fact, membership=row or {"bag_id": bid, "day_bag_id": None})

    cursor.execute(
        """
        SELECT id, action, version_before, version_after, before_json, after_json,
               reason, actor_user_id, actor_display_name, is_undo, undone_audit_id, created_at
        FROM hd_day_bag_production_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
        ORDER BY id DESC
        LIMIT 25
        """,
        (org, operations_date_et, bid),
    )
    audits = []
    for a in cursor.fetchall() or []:
        audits.append(
            {
                **dict(a),
                "before": _json_load(a.get("before_json")),
                "after": _json_load(a.get("after_json")),
            }
        )

    return {
        "ok": True,
        "operations_date_et": operations_date_et.isoformat(),
        "bag_id": bid,
        "membership": {
            "in_hd_membership": bool(row),
            "service_type": "HD" if row else None,
            "rush_status": (row or {}).get("rush_status"),
            "first_available": (row or {}).get("workload_entry_timestamp"),
            "day_bag_id": (row or {}).get("day_bag_id"),
            "orphan_production_fact": orphan,
            "reconciliation_exception": orphan,
        },
        "production": pub,
        "audits": audits,
        "employee_options": list_org_employee_options(cursor, org),
        "reason_codes": {
            "zero_revenue": sorted(ZERO_REVENUE_CODES),
            "zero_items": sorted(ZERO_ITEMS_CODES),
        },
        "permissions": {"can_save": bool(row), "can_undo": can_undo and bool(fact)},
    }


def save_hd_production(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    ensure_hd_production_tables(cursor)

    membership = {
        _norm_bag(r.get("bag_id")): r
        for r in list_hd_day_membership_bags(cursor, org, operations_date_et)
    }
    row = membership.get(bid)
    if not row:
        return {"ok": False, "error": "non_hd_membership_bag", "status": 400}

    # Cross-org already scoped by organization_id in membership query.
    fact = get_hd_production_row(cursor, org, operations_date_et, bid)
    current_version = int(fact["version"]) if fact else 0
    expected = payload.get("version")
    if expected is None:
        return {"ok": False, "error": "version_required", "status": 400}
    if int(expected) != current_version:
        return {
            "ok": False,
            "error": "conflict",
            "status": 409,
            "current_version": current_version,
            "current_record": _fact_public(fact, membership=row),
        }

    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "reason_required", "errors": ["reason_required"]}

    # Ignore client-supplied status — always server-derived.
    washed, w_err = _normalize_worker_fields(cursor, org, payload, role="washed")
    folded, f_err = _normalize_worker_fields(cursor, org, payload, role="folded")
    errors = w_err + f_err

    fields: dict[str, Any] = {
        **washed,
        **folded,
        "total_items": payload.get("total_items"),
        "revenue": payload.get("revenue"),
        "zero_items_reason_code": str(payload.get("zero_items_reason_code") or "").strip().upper()
        or None,
        "zero_items_reason_note": str(payload.get("zero_items_reason_note") or "").strip() or None,
        "zero_revenue_reason_code": str(payload.get("zero_revenue_reason_code") or "").strip().upper()
        or None,
        "zero_revenue_reason_note": str(payload.get("zero_revenue_reason_note") or "").strip() or None,
        "notes": str(payload.get("notes") or "").strip() or None,
        "reason": reason,
    }
    errors.extend(validate_hd_production_fields(fields, require_complete=False))
    if errors:
        return {"ok": False, "error": "validation_failed", "errors": errors}

    # Normalize revenue/items
    items_v = None
    if fields["total_items"] is not None and str(fields["total_items"]) != "":
        items_v = int(fields["total_items"])
    rev_v = None
    if fields["revenue"] is not None and str(fields["revenue"]) != "":
        rev_v = (_d(fields["revenue"]) or Decimal("0")).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    status = derive_hd_production_status(
        {
            **fields,
            "total_items": items_v,
            "revenue": float(rev_v) if rev_v is not None else None,
        }
    )
    # If attempting COMPLETE-looking payload but status partial due to validation,
    # re-check with require_complete for clearer errors when all fields present.
    if (
        _has_worker(fields.get("washed_by_user_id"), fields.get("washed_by_override_name"))
        and _has_worker(fields.get("folded_by_user_id"), fields.get("folded_by_override_name"))
        and items_v is not None
        and rev_v is not None
        and status != STATUS_COMPLETE
    ):
        c_err = validate_hd_production_fields(
            {**fields, "total_items": items_v, "revenue": float(rev_v)},
            require_complete=True,
        )
        if c_err:
            return {"ok": False, "error": "validation_failed", "errors": c_err}

    before_state = _fact_public(fact, membership=row) if fact else None
    new_version = current_version + 1
    day_bag_id = row.get("day_bag_id")
    now = datetime.utcnow()

    if fact:
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              day_bag_id=%s,
              washed_by_user_id=%s, washed_by_name_snapshot=%s, washed_by_override_name=%s,
              folded_by_user_id=%s, folded_by_name_snapshot=%s, folded_by_override_name=%s,
              total_items=%s, revenue=%s,
              zero_items_reason_code=%s, zero_items_reason_note=%s,
              zero_revenue_reason_code=%s, zero_revenue_reason_note=%s,
              notes=%s, status=%s, updated_by_user_id=%s, version=%s
            WHERE id=%s
            """,
            (
                day_bag_id,
                fields.get("washed_by_user_id"),
                fields.get("washed_by_name_snapshot"),
                fields.get("washed_by_override_name"),
                fields.get("folded_by_user_id"),
                fields.get("folded_by_name_snapshot"),
                fields.get("folded_by_override_name"),
                items_v,
                float(rev_v) if rev_v is not None else None,
                fields.get("zero_items_reason_code"),
                fields.get("zero_items_reason_note"),
                fields.get("zero_revenue_reason_code"),
                fields.get("zero_revenue_reason_note"),
                fields.get("notes"),
                status,
                actor_user_id,
                new_version,
                int(fact["id"]),
            ),
        )
        action = ACTION_UPDATE
    else:
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production (
              organization_id, operations_date_et, day_bag_id, bag_id,
              washed_by_user_id, washed_by_name_snapshot, washed_by_override_name,
              folded_by_user_id, folded_by_name_snapshot, folded_by_override_name,
              total_items, revenue,
              zero_items_reason_code, zero_items_reason_note,
              zero_revenue_reason_code, zero_revenue_reason_note,
              notes, status, created_by_user_id, updated_by_user_id, version
            ) VALUES (
              %s,%s,%s,%s,
              %s,%s,%s,
              %s,%s,%s,
              %s,%s,
              %s,%s,
              %s,%s,
              %s,%s,%s,%s,%s
            )
            """,
            (
                org,
                operations_date_et,
                day_bag_id,
                bid,
                fields.get("washed_by_user_id"),
                fields.get("washed_by_name_snapshot"),
                fields.get("washed_by_override_name"),
                fields.get("folded_by_user_id"),
                fields.get("folded_by_name_snapshot"),
                fields.get("folded_by_override_name"),
                items_v,
                float(rev_v) if rev_v is not None else None,
                fields.get("zero_items_reason_code"),
                fields.get("zero_items_reason_note"),
                fields.get("zero_revenue_reason_code"),
                fields.get("zero_revenue_reason_note"),
                fields.get("notes"),
                status,
                actor_user_id,
                actor_user_id,
                new_version,
            ),
        )
        action = ACTION_CREATE

    after = get_hd_production_row(cursor, org, operations_date_et, bid)
    cursor.execute(
        """
        INSERT INTO hd_day_bag_production_audits (
          organization_id, operations_date_et, bag_id, production_fact_id,
          action, version_before, version_after, before_json, after_json,
          reason, actor_user_id, actor_display_name, is_undo
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
        """,
        (
            org,
            operations_date_et,
            bid,
            (after or {}).get("id"),
            action,
            current_version,
            new_version,
            _json_dump(before_state),
            _json_dump(_fact_public(after, membership=row)),
            reason,
            actor_user_id,
            actor_display_name,
        ),
    )

    day = build_daily_operations_day(cursor, org, operations_date_et, persist=True)
    return {
        "ok": True,
        "bag_id": bid,
        "version": new_version,
        "status": status,
        "production": _fact_public(after, membership=row),
        "day": {
            "hd_revenue": (day.get("revenue") or {}).get("hd_revenue"),
            "wf_workitem_revenue": (day.get("revenue") or {}).get("wf_workitem_revenue"),
            "total_revenue": (day.get("revenue") or {}).get("total_revenue"),
        },
        "summary": compute_hd_day_revenue_totals(cursor, org, operations_date_et),
    }


def undo_hd_production(
    cursor,
    organization_id: int,
    operations_date_et: date,
    bag_id: str,
    *,
    reason: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    reason_text = str(reason or "").strip()
    if not reason_text:
        return {"ok": False, "error": "reason_required"}
    ensure_hd_production_tables(cursor)
    fact = get_hd_production_row(cursor, org, operations_date_et, bid)
    if not fact:
        return {"ok": False, "error": "no_production_to_undo"}

    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
          AND is_undo = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (org, operations_date_et, bid),
    )
    latest = cursor.fetchone()
    if not latest:
        return {"ok": False, "error": "no_undoable_audit"}

    cursor.execute(
        """
        SELECT id FROM hd_day_bag_production_audits
        WHERE organization_id = %s AND operations_date_et = %s AND bag_id = %s
          AND id > %s AND is_undo = 0
        LIMIT 1
        """,
        (org, operations_date_et, bid, int(latest["id"])),
    )
    if cursor.fetchone():
        return {"ok": False, "error": "later_edit_depends"}

    before = _json_load(latest.get("before_json"))
    current_version = int(fact.get("version") or 1)
    new_version = current_version + 1
    membership_row = next(
        (
            r
            for r in list_hd_day_membership_bags(cursor, org, operations_date_et)
            if _norm_bag(r.get("bag_id")) == bid
        ),
        {"bag_id": bid, "day_bag_id": fact.get("day_bag_id")},
    )

    if not before or not before.get("exists"):
        # Undo first save → NOT_RECORDED zero-state fact (retain row + history).
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              washed_by_user_id=NULL, washed_by_name_snapshot=NULL, washed_by_override_name=NULL,
              folded_by_user_id=NULL, folded_by_name_snapshot=NULL, folded_by_override_name=NULL,
              total_items=NULL, revenue=NULL,
              zero_items_reason_code=NULL, zero_items_reason_note=NULL,
              zero_revenue_reason_code=NULL, zero_revenue_reason_note=NULL,
              notes=NULL, status=%s, updated_by_user_id=%s, version=%s
            WHERE id=%s
            """,
            (STATUS_NOT_RECORDED, actor_user_id, new_version, int(fact["id"])),
        )
    else:
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              washed_by_user_id=%s, washed_by_name_snapshot=%s, washed_by_override_name=%s,
              folded_by_user_id=%s, folded_by_name_snapshot=%s, folded_by_override_name=%s,
              total_items=%s, revenue=%s,
              zero_items_reason_code=%s, zero_items_reason_note=%s,
              zero_revenue_reason_code=%s, zero_revenue_reason_note=%s,
              notes=%s, status=%s, updated_by_user_id=%s, version=%s
            WHERE id=%s
            """,
            (
                before.get("washed_by_user_id"),
                before.get("washed_by_name_snapshot"),
                before.get("washed_by_override_name"),
                before.get("folded_by_user_id"),
                before.get("folded_by_name_snapshot"),
                before.get("folded_by_override_name"),
                before.get("total_items"),
                before.get("revenue"),
                before.get("zero_items_reason_code"),
                before.get("zero_items_reason_note"),
                before.get("zero_revenue_reason_code"),
                before.get("zero_revenue_reason_note"),
                before.get("notes"),
                before.get("status") or STATUS_NOT_RECORDED,
                actor_user_id,
                new_version,
                int(fact["id"]),
            ),
        )

    after = get_hd_production_row(cursor, org, operations_date_et, bid)
    # Re-derive status from restored fields for safety.
    if after:
        derived = derive_hd_production_status(after)
        if derived != after.get("status"):
            cursor.execute(
                "UPDATE hd_day_bag_production SET status=%s WHERE id=%s",
                (derived, int(after["id"])),
            )
            after = get_hd_production_row(cursor, org, operations_date_et, bid)

    cursor.execute(
        """
        INSERT INTO hd_day_bag_production_audits (
          organization_id, operations_date_et, bag_id, production_fact_id,
          action, version_before, version_after, before_json, after_json,
          reason, actor_user_id, actor_display_name, is_undo, undone_audit_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)
        """,
        (
            org,
            operations_date_et,
            bid,
            (after or {}).get("id"),
            ACTION_UNDO,
            current_version,
            new_version,
            _json_dump(_fact_public(fact, membership=membership_row)),
            _json_dump(_fact_public(after, membership=membership_row)),
            reason_text,
            actor_user_id,
            actor_display_name,
            int(latest["id"]),
        ),
    )
    day = build_daily_operations_day(cursor, org, operations_date_et, persist=True)
    return {
        "ok": True,
        "bag_id": bid,
        "version": new_version,
        "production": _fact_public(after, membership=membership_row),
        "day": {
            "hd_revenue": (day.get("revenue") or {}).get("hd_revenue"),
            "total_revenue": (day.get("revenue") or {}).get("total_revenue"),
        },
        "summary": compute_hd_day_revenue_totals(cursor, org, operations_date_et),
    }


def export_hd_production_csv(
    cursor,
    organization_id: int,
    operations_date_et: date,
) -> tuple[str, str]:
    queue = build_hd_production_queue(cursor, organization_id, operations_date_et)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Operations Date ET",
            "Bag ID",
            "Rush Type",
            "Workload Entry Timestamp",
            "Status",
            "Washed By",
            "Folded By",
            "Total Items",
            "Revenue",
            "Included in Day Revenue",
            "Zero Items Reason",
            "Zero Revenue Reason",
            "Notes",
            "Last Updated By",
            "Last Updated At",
            "Version",
        ]
    )
    for it in queue.get("items") or []:
        mem = it.get("membership") or {}
        writer.writerow(
            [
                operations_date_et.isoformat(),
                it.get("bag_id"),
                mem.get("rush_status"),
                mem.get("first_available"),
                it.get("status"),
                it.get("washed_by_name_snapshot") or it.get("washed_by_override_name"),
                it.get("folded_by_name_snapshot") or it.get("folded_by_override_name"),
                it.get("total_items"),
                it.get("revenue"),
                "Y" if it.get("included_in_day_revenue") else "N",
                it.get("zero_items_reason_code"),
                it.get("zero_revenue_reason_code"),
                it.get("notes"),
                it.get("updated_by_user_id"),
                it.get("updated_at"),
                it.get("version"),
            ]
        )
    summary = queue.get("summary") or {}
    writer.writerow([])
    writer.writerow(["Summary", "Value"])
    for key in (
        "hd_orders_available",
        "not_recorded",
        "partially_recorded",
        "complete",
        "complete_total_items",
        "complete_hd_revenue",
        "partial_hd_revenue_entered",
    ):
        writer.writerow([key, summary.get(key)])
    filename = f"hd_production_{operations_date_et.isoformat()}.csv"
    return filename, buf.getvalue()
