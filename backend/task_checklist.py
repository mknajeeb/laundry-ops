"""Checklist-level verification for Task Management (e.g. End of Day → next morning)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Mapping, Optional, Sequence

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    CleaningTaskError,
    _employee_names,
    _role_catalog,
    approve_activity,
    reject_activity,
    serialize_activity,
    ensure_cleaning_task_activity_tables,
    TABLE,
)
from backend.payroll_identity import eastern_now_naive
from backend.task_catalog import (
    CHECKLIST_ITEMS_TABLE,
    CHECKLIST_VERIFICATIONS_TABLE,
    CHECKLISTS_TABLE,
    VERIFY_EMPLOYEE,
    VERIFY_SUPERVISOR,
    VERIFY_TIMING_NEXT_DAY,
    ensure_task_catalog_tables,
    list_categories,
    TaskCatalogError,
)

CHECKLIST_PENDING = "pending_verification"
CHECKLIST_VERIFIED = "verified"
CHECKLIST_PARTIAL = "partial"
CHECKLIST_INCOMPLETE = "incomplete"


def list_checklists(cursor, organization_id: int, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    sql = f"""
        SELECT * FROM {CHECKLISTS_TABLE}
        WHERE organization_id = %s
    """
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY name ASC"
    cursor.execute(sql, (int(organization_id),))
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    cats = {c["id"]: c for c in list_categories(cursor, int(organization_id))}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = int(row["id"])
        items = list_checklist_items(cursor, int(organization_id), cid)
        cat = cats.get(int(row["category_id"])) if row.get("category_id") is not None else None
        out.append(
            {
                "id": cid,
                "organization_id": int(row["organization_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "category_id": int(row["category_id"]) if row.get("category_id") is not None else None,
                "category_code": cat.get("code") if cat else None,
                "category_name": cat.get("name") if cat else None,
                "verification_required": bool(row.get("verification_required", True)),
                "verification_method": str(row.get("verification_method") or VERIFY_EMPLOYEE),
                "verification_timing": str(row.get("verification_timing") or VERIFY_TIMING_NEXT_DAY),
                "verifier_config": _parse_json(row.get("verifier_config_json"), {}),
                "active": bool(row.get("active", True)),
                "items": items,
            }
        )
    return out


def list_checklist_items(cursor, organization_id: int, checklist_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT id, checklist_id, task_code, display_order, required
        FROM {CHECKLIST_ITEMS_TABLE}
        WHERE organization_id = %s AND checklist_id = %s
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), int(checklist_id)),
    )
    return [
        {
            "id": int(r["id"]),
            "checklist_id": int(r["checklist_id"]),
            "task_code": str(r["task_code"]),
            "display_order": int(r.get("display_order") or 0),
            "required": bool(r.get("required", True)),
        }
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict)
    ]


def _parse_json(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def upsert_checklist(cursor, organization_id: int, data: Mapping[str, Any], *, checklist_id: int | None = None) -> dict[str, Any]:
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise TaskCatalogError("Checklist name is required.")
    code = str(data.get("code") or name).strip().lower().replace(" ", "_")[:40]
    method = str(data.get("verification_method") or VERIFY_EMPLOYEE)
    timing = str(data.get("verification_timing") or VERIFY_TIMING_NEXT_DAY)
    active = 1 if data.get("active", True) else 0
    verify_required = 1 if data.get("verification_required", True) else 0
    category_id = data.get("category_id")
    verifier_config = data.get("verifier_config")
    if isinstance(verifier_config, (dict, list)):
        verifier_config = json.dumps(verifier_config)
    if checklist_id is not None:
        cursor.execute(
            f"""
            UPDATE {CHECKLISTS_TABLE}
            SET name=%s, category_id=%s, verification_required=%s, verification_method=%s,
                verification_timing=%s, verifier_config_json=%s, active=%s
            WHERE organization_id=%s AND id=%s
            """,
            (
                name,
                int(category_id) if category_id not in (None, "") else None,
                verify_required,
                method,
                timing,
                verifier_config,
                active,
                oid,
                int(checklist_id),
            ),
        )
        cid = int(checklist_id)
    else:
        cursor.execute(
            f"""
            INSERT INTO {CHECKLISTS_TABLE} (
              organization_id, code, name, category_id, verification_required,
              verification_method, verification_timing, verifier_config_json, active
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), category_id=VALUES(category_id),
              verification_required=VALUES(verification_required),
              verification_method=VALUES(verification_method),
              verification_timing=VALUES(verification_timing),
              verifier_config_json=VALUES(verifier_config_json), active=VALUES(active)
            """,
            (
                oid,
                code,
                name,
                int(category_id) if category_id not in (None, "") else None,
                verify_required,
                method,
                timing,
                verifier_config,
                active,
            ),
        )
        cursor.execute(
            f"SELECT id FROM {CHECKLISTS_TABLE} WHERE organization_id=%s AND code=%s",
            (oid, code),
        )
        row = cursor.fetchone() or {}
        cid = int(row["id"])

    items = data.get("items")
    if isinstance(items, list):
        cursor.execute(
            f"DELETE FROM {CHECKLIST_ITEMS_TABLE} WHERE organization_id=%s AND checklist_id=%s",
            (oid, cid),
        )
        for idx, item in enumerate(items):
            if isinstance(item, str):
                task_code, required = item, True
            elif isinstance(item, dict):
                task_code = str(item.get("task_code") or item.get("code") or "").strip()
                required = bool(item.get("required", True))
            else:
                continue
            if not task_code:
                continue
            cursor.execute(
                f"""
                INSERT INTO {CHECKLIST_ITEMS_TABLE}
                  (organization_id, checklist_id, task_code, display_order, required)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (oid, cid, task_code, idx * 10, 1 if required else 0),
            )
        # Link task definitions to this checklist
        for item in list_checklist_items(cursor, oid, cid):
            cursor.execute(
                """
                UPDATE weekly_schedule_roles
                SET checklist_id = %s
                WHERE organization_id = %s AND code = %s
                """,
                (cid, oid, item["task_code"]),
            )

    for cl in list_checklists(cursor, oid):
        if cl["id"] == cid:
            return cl
    raise TaskCatalogError("Could not load checklist after save.", status=500)


def _activities_for_checklist_day(
    cursor,
    organization_id: int,
    checklist_id: int,
    business_date: date,
) -> list[dict[str, Any]]:
    ensure_cleaning_task_activity_tables(cursor)
    items = list_checklist_items(cursor, int(organization_id), int(checklist_id))
    codes = [i["task_code"] for i in items]
    if not codes:
        return []
    placeholders = ", ".join(["%s"] * len(codes))
    cursor.execute(
        f"""
        SELECT * FROM {TABLE}
        WHERE organization_id = %s
          AND business_date = %s
          AND (
            checklist_id = %s
            OR role IN ({placeholders})
          )
          AND status <> 'cancelled'
        ORDER BY id ASC
        """,
        (int(organization_id), business_date, int(checklist_id), *codes),
    )
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _checklist_verification_row(cursor, organization_id: int, checklist_id: int, business_date: date) -> dict | None:
    cursor.execute(
        f"""
        SELECT * FROM {CHECKLIST_VERIFICATIONS_TABLE}
        WHERE organization_id=%s AND checklist_id=%s AND business_date=%s
        LIMIT 1
        """,
        (int(organization_id), int(checklist_id), business_date),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def build_checklist_day_status(
    cursor,
    organization_id: int,
    checklist: Mapping[str, Any],
    business_date: date,
) -> dict[str, Any]:
    catalog = _role_catalog(cursor, int(organization_id))
    items = checklist.get("items") or list_checklist_items(cursor, int(organization_id), int(checklist["id"]))
    activities = _activities_for_checklist_day(
        cursor, int(organization_id), int(checklist["id"]), business_date
    )
    # Latest non-cancelled per responsibility, prefer completed statuses
    by_role_user: dict[tuple[str, int], dict] = {}
    for act in activities:
        key = (str(act.get("role") or ""), int(act.get("user_id") or 0))
        prev = by_role_user.get(key)
        if prev is None or int(act.get("id") or 0) > int(prev.get("id") or 0):
            by_role_user[key] = act

    name_ids = {int(a["user_id"]) for a in by_role_user.values()}
    names = _employee_names(cursor, int(organization_id), sorted(name_ids))

    member_rows = []
    required_incomplete = 0
    required_rejected = 0
    required_done = 0
    required_total = 0
    for item in items:
        code = item["task_code"]
        matching = [a for (role, _), a in by_role_user.items() if role == code]
        label = (catalog.get(code) or {}).get("name") or code
        if not matching:
            required_total += 1 if item.get("required", True) else 0
            if item.get("required", True):
                required_incomplete += 1
            member_rows.append(
                {
                    "task_code": code,
                    "task_label": label,
                    "required": bool(item.get("required", True)),
                    "status": "not_started",
                    "activities": [],
                }
            )
            continue
        act_list = []
        for act in matching:
            st = str(act.get("status") or "")
            ser = serialize_activity(act, catalog=catalog)
            ser["employee_name"] = names.get(int(act["user_id"]), f"User #{act['user_id']}")
            act_list.append(ser)
            if item.get("required", True):
                required_total += 1
                if st in (STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_COMPLETED):
                    required_done += 1
                elif st == STATUS_REJECTED:
                    required_rejected += 1
                else:
                    required_incomplete += 1
        # rollup for this task code
        statuses = {str(a.get("status")) for a in matching}
        if STATUS_REJECTED in statuses:
            rollup = "rejected"
        elif statuses <= {STATUS_APPROVED, STATUS_COMPLETED}:
            rollup = "completed"
        elif STATUS_PENDING_APPROVAL in statuses:
            rollup = "pending_verification"
        elif "in_progress" in statuses:
            rollup = "in_progress"
        else:
            rollup = "not_started"
        member_rows.append(
            {
                "task_code": code,
                "task_label": label,
                "required": bool(item.get("required", True)),
                "status": rollup,
                "activities": act_list,
            }
        )

    ver = _checklist_verification_row(cursor, int(organization_id), int(checklist["id"]), business_date)
    if ver and str(ver.get("status")) == CHECKLIST_VERIFIED:
        overall = CHECKLIST_VERIFIED
    elif required_incomplete > 0:
        overall = CHECKLIST_INCOMPLETE
    elif required_rejected > 0:
        overall = CHECKLIST_PARTIAL
    elif required_total and required_done >= required_total:
        overall = CHECKLIST_PENDING
    else:
        overall = CHECKLIST_INCOMPLETE

    return {
        "checklist_id": int(checklist["id"]),
        "checklist_code": checklist.get("code"),
        "checklist_name": checklist.get("name"),
        "business_date": str(business_date),
        "status": overall,
        "required_total": required_total,
        "required_done": required_done,
        "required_incomplete": required_incomplete,
        "required_rejected": required_rejected,
        "can_verify_all": overall == CHECKLIST_PENDING and required_incomplete == 0 and required_rejected == 0,
        "items": member_rows,
        "verification": (
            {
                "status": ver.get("status"),
                "verified_by_user_id": ver.get("verified_by_user_id"),
                "verified_at": str(ver.get("verified_at") or "")[:19] if ver.get("verified_at") else None,
                "rejection_reason": ver.get("rejection_reason"),
            }
            if ver
            else None
        ),
    }


def list_checklists_to_verify(
    cursor,
    organization_id: int,
    verifier_user_id: int,
    *,
    as_of: date | None = None,
    has_supervisor_review: bool = False,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Checklists awaiting verification for this verifier (incl. prior business dates)."""
    day = as_of or business_today()
    checklists = [c for c in list_checklists(cursor, int(organization_id), include_inactive=False) if c.get("active")]
    pending = []
    for offset in range(0, max(1, int(lookback_days) + 1)):
        biz = day - timedelta(days=offset)
        for cl in checklists:
            timing = str(cl.get("verification_timing") or VERIFY_TIMING_NEXT_DAY)
            if timing == VERIFY_TIMING_NEXT_DAY and biz >= day:
                continue
            method = str(cl.get("verification_method") or VERIFY_EMPLOYEE)
            config = cl.get("verifier_config") or {}
            if method == VERIFY_SUPERVISOR and not has_supervisor_review:
                continue
            if method == VERIFY_EMPLOYEE:
                allowed = {int(x) for x in (config.get("user_ids") or config.get("employee_ids") or []) if x}
                if allowed and int(verifier_user_id) not in allowed and not has_supervisor_review:
                    continue
            status = build_checklist_day_status(cursor, int(organization_id), cl, biz)
            if status["status"] in (CHECKLIST_PENDING, CHECKLIST_PARTIAL, CHECKLIST_INCOMPLETE):
                # Only surface if there is something to review (any activity or pending)
                if status["required_done"] or status["required_rejected"] or status["status"] == CHECKLIST_PENDING:
                    if status["status"] != CHECKLIST_VERIFIED:
                        pending.append(status)
    # Prefer actionable pending/partial first
    pending.sort(key=lambda x: (0 if x["status"] == CHECKLIST_PENDING else 1, x["business_date"]))
    return {
        "as_of": str(day),
        "verifier_user_id": int(verifier_user_id),
        "checklists": pending,
        "count": len(pending),
    }


def verify_checklist(
    cursor,
    *,
    organization_id: int,
    checklist_id: int,
    business_date: date,
    verifier_user_id: int,
    has_supervisor_review: bool = False,
) -> dict[str, Any]:
    ensure_task_catalog_tables(cursor)
    checklists = {c["id"]: c for c in list_checklists(cursor, int(organization_id))}
    cl = checklists.get(int(checklist_id))
    if not cl:
        raise CleaningTaskError("Checklist not found.", status=404)
    status = build_checklist_day_status(cursor, int(organization_id), cl, business_date)
    if not status["can_verify_all"]:
        raise CleaningTaskError(
            "Cannot verify checklist until all required items are completed and none are rejected.",
            status=400,
        )
    # Verify each pending contribution (not already verified)
    for item in status["items"]:
        for act in item.get("activities") or []:
            if act.get("status") == STATUS_PENDING_APPROVAL:
                if int(act.get("user_id") or 0) == int(verifier_user_id):
                    raise CleaningTaskError(
                        "You cannot verify a checklist that includes your own completion.",
                        status=403,
                    )
                approve_activity(
                    cursor,
                    organization_id=int(organization_id),
                    activity_id=int(act["id"]),
                    supervisor_user_id=int(verifier_user_id),
                )
    at = eastern_now_naive()
    cursor.execute(
        f"""
        INSERT INTO {CHECKLIST_VERIFICATIONS_TABLE} (
          organization_id, checklist_id, business_date, status,
          verified_by_user_id, verified_at, payload_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          status=VALUES(status),
          verified_by_user_id=VALUES(verified_by_user_id),
          verified_at=VALUES(verified_at),
          rejection_reason=NULL,
          payload_json=VALUES(payload_json)
        """,
        (
            int(organization_id),
            int(checklist_id),
            business_date,
            CHECKLIST_VERIFIED,
            int(verifier_user_id),
            at,
            json.dumps({"item_count": len(status["items"])}),
        ),
    )
    return build_checklist_day_status(cursor, int(organization_id), cl, business_date)


def reject_checklist_item(
    cursor,
    *,
    organization_id: int,
    activity_id: int,
    verifier_user_id: int,
    reason: str,
) -> dict[str, Any]:
    """Reject one contribution inside a checklist; does not verify the checklist."""
    return reject_activity(
        cursor,
        organization_id=int(organization_id),
        activity_id=int(activity_id),
        supervisor_user_id=int(verifier_user_id),
        reason=reason,
    )
