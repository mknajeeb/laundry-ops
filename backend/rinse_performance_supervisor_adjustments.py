"""Supervisor-adjusted folding performance that is not a manufactured session.

Raw scan values stay on the bag evidence. Corrected and approved figures are
stored on the adjustment. Bag credit is unique per processing-cycle
(order instance), so a later reprocess can be credited again and the same
cycle cannot be credited twice.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.management_wf_folder_attribution import move_bag_attribution
from backend.management_wf_folder_fold_attribution import resolve_day_bag_folder_oi
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_performance_approvals import (
    ensure_rinse_performance_approval_tables,
    upsert_approved_snapshot,
)
from backend.rinse_performance_auto_approve import SOURCE_MANUAL
from backend.rinse_performance_roles import ROLE_FOLDER, get_role
from backend.ta_helpers import table_exists

ADJUSTMENTS_TABLE = "rinse_performance_supervisor_adjustments"
EVENTS_TABLE = "rinse_performance_supervisor_adjustment_events"
CREDITS_TABLE = "rinse_performance_bag_credits"


def ensure_supervisor_adjustment_tables(cursor) -> bool:
    """True when the migration tables exist. Requests must not create them."""
    return bool(
        table_exists(cursor, ADJUSTMENTS_TABLE)
        and table_exists(cursor, EVENTS_TABLE)
        and table_exists(cursor, CREDITS_TABLE)
    )


def cycle_key_for_order_instance(order_instance_id: int | None) -> str | None:
    if order_instance_id is None:
        return None
    try:
        oi = int(order_instance_id)
    except (TypeError, ValueError):
        return None
    if oi <= 0:
        return None
    return f"oi:{oi}"


def resolve_bag_cycle(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    selected_date_et: date,
    completion_hint: datetime | None = None,
    order_instance_id: int | None = None,
) -> dict[str, Any] | None:
    if order_instance_id:
        key = cycle_key_for_order_instance(order_instance_id)
        if not key:
            return None
        return {"order_instance_id": int(order_instance_id), "cycle_key": key, "bag_id": normalize_bag_id(bag_id)}
    oi = resolve_day_bag_folder_oi(
        cursor,
        int(organization_id),
        bag_id=bag_id,
        selected_date_et=selected_date_et,
        completion_hint=completion_hint,
    )
    if not oi:
        return None
    key = cycle_key_for_order_instance(oi.get("order_instance_id"))
    if not key:
        return None
    return {
        "order_instance_id": int(oi["order_instance_id"]),
        "cycle_key": key,
        "bag_id": normalize_bag_id(bag_id),
        "cycle_anchor_at": oi.get("cycle_anchor_at"),
    }


def _audit(
    cursor,
    organization_id: int,
    *,
    adjustment_key: str,
    business_date_et: date,
    action: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    actor_user_id: int | None,
    actor_name: str | None,
    reason: str | None,
) -> None:
    cursor.execute(
        f"""
        INSERT INTO {EVENTS_TABLE} (
          organization_id, adjustment_key, business_date_et, action,
          actor_user_id, actor_name, reason, before_json, after_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            adjustment_key,
            business_date_et,
            action,
            actor_user_id,
            actor_name,
            (reason or None) and str(reason)[:255],
            json.dumps(before, default=str) if before is not None else None,
            json.dumps(after, default=str) if after is not None else None,
        ),
    )


def _row_public(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("before_json", "after_json"):
        out.pop(key, None)
    day = out.get("business_date_et")
    if isinstance(day, date):
        out["business_date_et"] = day.isoformat()
    return out


def get_adjustment(cursor, organization_id: int, adjustment_key: str) -> dict[str, Any] | None:
    if not ensure_supervisor_adjustment_tables(cursor):
        return None
    cursor.execute(
        f"""
        SELECT * FROM {ADJUSTMENTS_TABLE}
        WHERE organization_id=%s AND adjustment_key=%s
        LIMIT 1
        """,
        (int(organization_id), str(adjustment_key)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def list_adjustments_for_day(
    cursor, organization_id: int, business_date_et: date
) -> list[dict[str, Any]]:
    if not ensure_supervisor_adjustment_tables(cursor):
        return []
    cursor.execute(
        f"""
        SELECT * FROM {ADJUSTMENTS_TABLE}
        WHERE organization_id=%s AND business_date_et=%s
        ORDER BY employee_name, id
        """,
        (int(organization_id), business_date_et),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def active_credit_for_cycle(cursor, organization_id: int, cycle_key: str) -> dict[str, Any] | None:
    if not ensure_supervisor_adjustment_tables(cursor):
        return None
    cursor.execute(
        f"""
        SELECT * FROM {CREDITS_TABLE}
        WHERE organization_id=%s AND cycle_key=%s AND released_at IS NULL
        LIMIT 1
        """,
        (int(organization_id), cycle_key),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def release_cycle_credit(
    cursor,
    organization_id: int,
    cycle_key: str,
) -> None:
    cursor.execute(
        f"""
        UPDATE {CREDITS_TABLE}
        SET released_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND cycle_key=%s AND released_at IS NULL
        """,
        (int(organization_id), cycle_key),
    )


def claim_cycle_credit(
    cursor,
    organization_id: int,
    *,
    business_date_et: date,
    bag_id: str,
    cycle_key: str,
    order_instance_id: int,
    employee_user_id: int | None,
    employee_name: str,
    session_id: str | None,
    adjustment_key: str | None,
    weight_lbs: float | None,
    actor_user_id: int | None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """One active credit per cycle. Replacing releases the previous holder first."""
    if not ensure_supervisor_adjustment_tables(cursor):
        return {"ok": False, "status": "not_provisioned"}
    existing = active_credit_for_cycle(cursor, organization_id, cycle_key)
    if existing:
        same_holder = (
            str(existing.get("session_id") or "") == str(session_id or "")
            and str(existing.get("adjustment_key") or "") == str(adjustment_key or "")
            and str(existing.get("employee_name") or "") == employee_name
        )
        if same_holder:
            return {"ok": True, "already_credited": True, "cycle_key": cycle_key}
        if not replace_existing:
            return {
                "ok": False,
                "status": "cycle_already_credited",
                "cycle_key": cycle_key,
                "holder": existing.get("employee_name"),
                "session_id": existing.get("session_id"),
                "adjustment_key": existing.get("adjustment_key"),
            }
        release_cycle_credit(cursor, organization_id, cycle_key)
    cursor.execute(
        f"""
        INSERT INTO {CREDITS_TABLE} (
          organization_id, business_date_et, bag_id, order_instance_id, cycle_key,
          employee_user_id, employee_name, session_id, adjustment_key, weight_lbs, created_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            business_date_et,
            normalize_bag_id(bag_id),
            int(order_instance_id),
            cycle_key,
            employee_user_id,
            employee_name,
            session_id,
            adjustment_key,
            weight_lbs,
            actor_user_id,
        ),
    )
    return {"ok": True, "cycle_key": cycle_key, "replaced": bool(existing)}


def _rate(lbs: float | None, hours: float | None) -> float | None:
    if lbs is None or hours is None or hours <= 0:
        return None
    return round(float(lbs) / float(hours), 4)


def create_or_update_adjustment(
    cursor,
    organization_id: int,
    *,
    business_date_et: date,
    employee_user_id: int,
    employee_name: str,
    reason: str,
    notes: str | None = None,
    adjustment_key: str | None = None,
    target_session_id: str | None = None,
    raw_orders: int | None = None,
    raw_lbs: float | None = None,
    raw_hours: float | None = None,
    corrected_orders: int | None = None,
    corrected_lbs: float | None = None,
    corrected_hours: float | None = None,
    approved_lbs_per_hour: float | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    bag_cycles: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record a supervisor adjustment. Does not write scans, segments, or wages."""
    reason_text = str(reason or "").strip()
    if not reason_text:
        return {"ok": False, "status": "reason_required"}
    name = str(employee_name or "").strip()
    if not name or employee_user_id is None:
        return {"ok": False, "status": "employee_required"}
    if not ensure_supervisor_adjustment_tables(cursor):
        return {"ok": False, "status": "not_provisioned"}
    key = str(adjustment_key or "").strip() or f"ADJ-{int(organization_id)}-{business_date_et.isoformat()}-{int(employee_user_id)}"
    before = get_adjustment(cursor, organization_id, key)
    raw_rate = _rate(raw_lbs, raw_hours)
    corrected_rate = _rate(corrected_lbs, corrected_hours)
    approved_hours = corrected_hours if corrected_hours is not None else raw_hours
    approved_orders = corrected_orders if corrected_orders is not None else raw_orders
    approved_lbs = None
    if approved_lbs_per_hour is not None and approved_hours and approved_hours > 0:
        approved_lbs = round(float(approved_lbs_per_hour) * float(approved_hours), 4)
    elif corrected_lbs is not None:
        approved_lbs = corrected_lbs
    status = "NEEDS_APPROVAL"
    if before and str(before.get("publication_status") or "") == "APPROVED":
        status = "APPROVED"
    cursor.execute(
        f"""
        INSERT INTO {ADJUSTMENTS_TABLE} (
          organization_id, business_date_et, adjustment_key, employee_user_id, employee_name,
          target_session_id, raw_orders, raw_lbs, raw_hours, raw_lbs_per_hour,
          corrected_orders, corrected_lbs, corrected_hours, corrected_lbs_per_hour,
          approved_orders, approved_lbs, approved_hours, approved_lbs_per_hour,
          reason, notes, publication_status, created_by, updated_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          employee_user_id=VALUES(employee_user_id),
          employee_name=VALUES(employee_name),
          target_session_id=VALUES(target_session_id),
          raw_orders=VALUES(raw_orders),
          raw_lbs=VALUES(raw_lbs),
          raw_hours=VALUES(raw_hours),
          raw_lbs_per_hour=VALUES(raw_lbs_per_hour),
          corrected_orders=VALUES(corrected_orders),
          corrected_lbs=VALUES(corrected_lbs),
          corrected_hours=VALUES(corrected_hours),
          corrected_lbs_per_hour=VALUES(corrected_lbs_per_hour),
          approved_orders=VALUES(approved_orders),
          approved_lbs=VALUES(approved_lbs),
          approved_hours=VALUES(approved_hours),
          approved_lbs_per_hour=VALUES(approved_lbs_per_hour),
          reason=VALUES(reason),
          notes=VALUES(notes),
          updated_by=VALUES(updated_by),
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            int(organization_id),
            business_date_et,
            key,
            int(employee_user_id),
            name,
            target_session_id,
            raw_orders,
            raw_lbs,
            raw_hours,
            raw_rate,
            corrected_orders,
            corrected_lbs,
            corrected_hours,
            corrected_rate,
            approved_orders,
            approved_lbs,
            approved_hours,
            approved_lbs_per_hour,
            reason_text[:255],
            notes,
            status,
            actor_user_id,
            actor_user_id,
        ),
    )
    credited = []
    for bag in bag_cycles or []:
        cycle_key = str(bag.get("cycle_key") or "")
        oi = bag.get("order_instance_id")
        bid = normalize_bag_id(bag.get("bag_id"))
        if not cycle_key or not bid or oi is None:
            return {"ok": False, "status": "missing_cycle", "bag_id": bid}
        claim = claim_cycle_credit(
            cursor,
            organization_id,
            business_date_et=business_date_et,
            bag_id=bid,
            cycle_key=cycle_key,
            order_instance_id=int(oi),
            employee_user_id=int(employee_user_id),
            employee_name=name,
            session_id=target_session_id,
            adjustment_key=None if target_session_id else key,
            weight_lbs=bag.get("weight_lbs"),
            actor_user_id=actor_user_id,
            replace_existing=bool(bag.get("replace_existing")),
        )
        if not claim.get("ok"):
            return claim
        credited.append(claim)
        if target_session_id:
            move_bag_attribution(
                cursor,
                int(organization_id),
                bag_id=bid,
                selected_date_et=business_date_et,
                original_employee_name=str(bag.get("original_employee") or name),
                original_scanner_name=bag.get("original_employee"),
                original_completion_et=bag.get("completion_time"),
                from_employee_name=bag.get("original_employee"),
                from_session_id=bag.get("from_session_id"),
                to_employee_name=name,
                to_session_id=str(target_session_id),
                to_segment_id=bag.get("segment_id"),
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                note=reason_text[:512],
            )
    after = get_adjustment(cursor, organization_id, key)
    _audit(
        cursor,
        organization_id,
        adjustment_key=key,
        business_date_et=business_date_et,
        action="UPDATE" if before else "CREATE",
        before=before,
        after=after,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        reason=reason_text,
    )
    return {"ok": True, "adjustment": _row_public(after or {}), "credits": credited}


def set_adjustment_publication(
    cursor,
    organization_id: int,
    *,
    adjustment_key: str,
    status: str,
    actor_user_id: int | None,
    actor_name: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    if not ensure_supervisor_adjustment_tables(cursor):
        return {"ok": False, "status": "not_provisioned"}
    before = get_adjustment(cursor, organization_id, adjustment_key)
    if not before:
        return {"ok": False, "status": "not_found"}
    st = str(status or "").upper()
    if st not in {"APPROVED", "NEEDS_APPROVAL", "EXCLUDED", "UNAPPROVED"}:
        return {"ok": False, "status": "invalid_status"}
    if st == "APPROVED" and before.get("approved_lbs_per_hour") is None and not before.get("target_session_id"):
        return {"ok": False, "status": "approved_score_required"}
    if st == "APPROVED" and not str(before.get("reason") or "").strip():
        return {"ok": False, "status": "reason_required"}
    cursor.execute(
        f"""
        UPDATE {ADJUSTMENTS_TABLE}
        SET publication_status=%s, updated_by=%s, updated_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND adjustment_key=%s
        """,
        (st, actor_user_id, int(organization_id), adjustment_key),
    )
    after = get_adjustment(cursor, organization_id, adjustment_key)
    _audit(
        cursor,
        organization_id,
        adjustment_key=adjustment_key,
        business_date_et=before["business_date_et"]
        if isinstance(before.get("business_date_et"), date)
        else date.fromisoformat(str(before.get("business_date_et"))[:10]),
        action=st,
        before=before,
        after=after,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        reason=reason or before.get("reason"),
    )
    if st == "APPROVED" and not before.get("target_session_id"):
        _publish_adjustment_snapshot(cursor, organization_id, after or {}, actor_user_id, actor_name)
    return {"ok": True, "adjustment": _row_public(after or {})}


def _publish_adjustment_snapshot(
    cursor,
    organization_id: int,
    row: Mapping[str, Any],
    actor_user_id: int | None,
    actor_name: str | None,
) -> None:
    """Publish the approved score as its own snapshot. Session id is the adjustment key."""
    role = get_role(ROLE_FOLDER)
    if role is None:
        return
    ensure_rinse_performance_approval_tables(cursor)
    hours = float(row.get("approved_hours") or 0)
    rate = row.get("approved_lbs_per_hour")
    if rate is None or hours <= 0:
        # Speed-only approvals publish through the employee-day cache.
        # Do not invent a session, bag, or hour row for the approval table.
        return
    lbs = float(row.get("approved_lbs") or 0)
    biz = row.get("business_date_et")
    if not isinstance(biz, date):
        biz = date.fromisoformat(str(biz)[:10])
    snap = {
        "business_date_et": biz,
        "session_id": str(row.get("adjustment_key")),
        "segment_id": None,
        "employee_user_id": row.get("employee_user_id"),
        "employee_name": row.get("employee_name"),
        "metric_key": role["metric_key"],
        "metric_unit": role["unit"],
        "published_numerator": round(lbs, 4),
        "published_denominator": round(hours, 4),
        "published_metric_value": float(rate),
        "calculated_numerator": float(row.get("raw_lbs") or 0),
        "calculated_denominator": float(row.get("raw_hours") or hours),
        "calculated_metric_value": row.get("raw_lbs_per_hour"),
        "is_rate_override": True,
        "override_reason": row.get("reason"),
        "published_quantity": round(lbs, 4),
        "published_duration_hours": round(hours, 4),
        "content_fingerprint": f"adj:{row.get('adjustment_key')}:{rate}:{hours}",
        "approval_source": SOURCE_MANUAL,
    }
    upsert_approved_snapshot(
        cursor,
        int(organization_id),
        role_key=ROLE_FOLDER,
        snapshot=snap,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        approval_source=SOURCE_MANUAL,
    )


def attach_supervisor_adjustments(
    cursor,
    organization_id: int,
    day: dict[str, Any],
) -> dict[str, Any]:
    """Add approved adjustment contribution without double-counting session-linked bags."""
    selected = day.get("selected_date_et") or day.get("anchor_date_et")
    try:
        biz = selected if isinstance(selected, date) else date.fromisoformat(str(selected)[:10])
    except (TypeError, ValueError):
        return day
    rows = list_adjustments_for_day(cursor, organization_id, biz)
    if not rows:
        day["supervisor_adjustments"] = []
        return day
    by_name = {
        str(e.get("employee") or "").casefold(): e for e in (day.get("employees") or [])
    }
    public = []
    for raw in rows:
        row = _row_public(raw)
        public.append(row)
        if str(row.get("publication_status") or "").upper() != "APPROVED":
            continue
        if row.get("target_session_id"):
            continue
        name = str(row.get("employee_name") or "")
        emp = by_name.get(name.casefold())
        if emp is None:
            emp = {
                "employee": name,
                "user_id": row.get("employee_user_id"),
                "orders_completed": 0,
                "total_pre_lbs": 0.0,
                "performance_hours": 0.0,
                "session_hours": 0.0,
                "sessions": [],
                "approved_session_count": 0,
                "pending_session_count": 0,
                "day_publication_status": "NEEDS_APPROVAL",
                "publication_status": "NEEDS_APPROVAL",
                "selected_date_et": biz.isoformat(),
            }
            day.setdefault("employees", []).append(emp)
            by_name[name.casefold()] = emp
        hours = float(row.get("approved_hours") or 0)
        lbs = float(row.get("approved_lbs") or 0)
        orders = int(row.get("approved_orders") or 0)
        rate = row.get("approved_lbs_per_hour")
        speed_only = rate is not None and hours <= 0 and lbs <= 0 and orders <= 0
        emp["approved_adjustment_count"] = int(emp.get("approved_adjustment_count") or 0) + 1
        emp["raw_lbs_per_hour"] = row.get("raw_lbs_per_hour")
        emp["corrected_lbs_per_hour"] = row.get("corrected_lbs_per_hour")
        emp["approved_lbs_per_hour"] = rate
        if speed_only:
            # The approved speed replaces the published rate. Recorded bags,
            # pounds, and hours stay the evidence and are not added again.
            emp["speed_only_adjustment"] = True
            try:
                emp["lbs_per_hour"] = float(rate)
            except (TypeError, ValueError):
                emp["lbs_per_hour"] = None
        else:
            emp["orders_completed"] = int(emp.get("orders_completed") or 0) + orders
            emp["total_pre_lbs"] = round(float(emp.get("total_pre_lbs") or 0) + lbs, 2)
            emp["performance_hours"] = round(float(emp.get("performance_hours") or 0) + hours, 4)
            emp["session_hours"] = emp["performance_hours"]
            if hours > 0:
                emp["lbs_per_hour"] = round(
                    float(emp["total_pre_lbs"]) / float(emp["performance_hours"]), 4
                )
                emp["bags_per_hour"] = round(
                    int(emp["orders_completed"]) / float(emp["performance_hours"]), 4
                )
        pending = int(emp.get("pending_session_count") or 0)
        approved_sessions = int(emp.get("approved_session_count") or 0)
        if pending == 0 and approved_sessions == 0:
            emp["day_publication_status"] = "APPROVED"
            emp["publication_status"] = "APPROVED"
        elif pending > 0:
            emp["day_publication_status"] = "PARTIALLY_APPROVED"
            emp["publication_status"] = "PARTIALLY_APPROVED"
    day["supervisor_adjustments"] = public
    return day
