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
    CHECKLIST_GROUPS_TABLE,
    CHECKLIST_ITEMS_TABLE,
    CHECKLIST_VERIFICATIONS_TABLE,
    CHECKLISTS_TABLE,
    DEFAULT_CHECKLIST_GROUP_NAME,
    VERIFY_EMPLOYEE,
    VERIFY_SUPERVISOR,
    VERIFY_TIMING_NEXT_DAY,
    ensure_task_catalog_tables,
    list_categories,
    TaskCatalogError,
)
from backend.ta_helpers import table_has_column

CHECKLIST_PENDING = "pending_verification"
CHECKLIST_VERIFIED = "verified"
CHECKLIST_PARTIAL = "partial"
CHECKLIST_INCOMPLETE = "incomplete"


def _items_have_group_id(cursor) -> bool:
    return table_has_column(cursor, CHECKLIST_ITEMS_TABLE, "group_id")


def ensure_default_checklist_groups(cursor, organization_id: int, checklist_id: int) -> None:
    """Migrate flat checklist items into a default named group (additive, idempotent)."""
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    cid = int(checklist_id)
    if not _items_have_group_id(cursor):
        return
    cursor.execute(
        f"""
        SELECT COUNT(*) AS c FROM {CHECKLIST_GROUPS_TABLE}
        WHERE organization_id=%s AND checklist_id=%s
        """,
        (oid, cid),
    )
    row = cursor.fetchone() or {}
    group_count = int(row.get("c") or 0) if isinstance(row, dict) else int(row[0] if row else 0)
    if group_count == 0:
        cursor.execute(
            f"""
            INSERT INTO {CHECKLIST_GROUPS_TABLE}
              (organization_id, checklist_id, name, display_order)
            VALUES (%s,%s,%s,%s)
            """,
            (oid, cid, DEFAULT_CHECKLIST_GROUP_NAME, 0),
        )
    cursor.execute(
        f"""
        SELECT id FROM {CHECKLIST_GROUPS_TABLE}
        WHERE organization_id=%s AND checklist_id=%s
        ORDER BY display_order ASC, id ASC
        LIMIT 1
        """,
        (oid, cid),
    )
    g = cursor.fetchone() or {}
    default_gid = int(g["id"]) if isinstance(g, dict) and g.get("id") is not None else None
    if default_gid is None:
        return
    cursor.execute(
        f"""
        UPDATE {CHECKLIST_ITEMS_TABLE}
        SET group_id=%s
        WHERE organization_id=%s AND checklist_id=%s AND (group_id IS NULL OR group_id=0)
        """,
        (default_gid, oid, cid),
    )


def list_checklist_groups(cursor, organization_id: int, checklist_id: int) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    ensure_default_checklist_groups(cursor, int(organization_id), int(checklist_id))
    cursor.execute(
        f"""
        SELECT id, checklist_id, name, display_order
        FROM {CHECKLIST_GROUPS_TABLE}
        WHERE organization_id=%s AND checklist_id=%s
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), int(checklist_id)),
    )
    groups = [
        {
            "id": int(r["id"]),
            "checklist_id": int(r["checklist_id"]),
            "name": str(r.get("name") or DEFAULT_CHECKLIST_GROUP_NAME),
            "display_order": int(r.get("display_order") or 0),
            "items": [],
        }
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict)
    ]
    items = list_checklist_items(cursor, int(organization_id), int(checklist_id))
    by_gid: dict[int | None, list[dict[str, Any]]] = {}
    for item in items:
        by_gid.setdefault(item.get("group_id"), []).append(item)
    if not groups and items:
        # Should not happen after ensure_default, but keep a virtual group for safety.
        return [
            {
                "id": None,
                "checklist_id": int(checklist_id),
                "name": DEFAULT_CHECKLIST_GROUP_NAME,
                "display_order": 0,
                "items": items,
            }
        ]
    for group in groups:
        group["items"] = by_gid.get(group["id"]) or []
    orphan = by_gid.get(None) or []
    if orphan and groups:
        groups[0]["items"] = list(groups[0]["items"]) + orphan
    return groups


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
        groups = list_checklist_groups(cursor, int(organization_id), cid)
        items = [item for g in groups for item in (g.get("items") or [])]
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
                "groups": groups,
                "items": items,
            }
        )
    return out


def list_checklist_items(cursor, organization_id: int, checklist_id: int) -> list[dict[str, Any]]:
    has_group = _items_have_group_id(cursor)
    cols = "id, checklist_id, task_code, display_order, required"
    if has_group:
        cols = "id, checklist_id, group_id, task_code, display_order, required"
    cursor.execute(
        f"""
        SELECT {cols}
        FROM {CHECKLIST_ITEMS_TABLE}
        WHERE organization_id = %s AND checklist_id = %s
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), int(checklist_id)),
    )
    out = []
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        gid = r.get("group_id") if has_group else None
        out.append(
            {
                "id": int(r["id"]),
                "checklist_id": int(r["checklist_id"]),
                "group_id": int(gid) if gid not in (None, "") else None,
                "task_code": str(r["task_code"]),
                "display_order": int(r.get("display_order") or 0),
                "required": bool(r.get("required", True)),
            }
        )
    return out


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

    groups_payload = data.get("groups")
    items = data.get("items")
    if isinstance(groups_payload, list) or isinstance(items, list):
        cursor.execute(
            f"DELETE FROM {CHECKLIST_ITEMS_TABLE} WHERE organization_id=%s AND checklist_id=%s",
            (oid, cid),
        )
        cursor.execute(
            f"DELETE FROM {CHECKLIST_GROUPS_TABLE} WHERE organization_id=%s AND checklist_id=%s",
            (oid, cid),
        )
        normalized_groups: list[tuple[str, list[Any]]] = []
        if isinstance(groups_payload, list) and groups_payload:
            for g in groups_payload:
                if not isinstance(g, Mapping):
                    continue
                gname = " ".join(str(g.get("name") or DEFAULT_CHECKLIST_GROUP_NAME).split()) or DEFAULT_CHECKLIST_GROUP_NAME
                normalized_groups.append((gname[:80], list(g.get("items") or [])))
        else:
            # Flat items → single default group (backward compatible).
            normalized_groups.append((DEFAULT_CHECKLIST_GROUP_NAME, list(items or [])))

        has_group = _items_have_group_id(cursor)
        global_idx = 0
        for g_idx, (gname, g_items) in enumerate(normalized_groups):
            cursor.execute(
                f"""
                INSERT INTO {CHECKLIST_GROUPS_TABLE}
                  (organization_id, checklist_id, name, display_order)
                VALUES (%s,%s,%s,%s)
                """,
                (oid, cid, gname, g_idx * 10),
            )
            cursor.execute("SELECT LAST_INSERT_ID() AS id")
            grow = cursor.fetchone() or {}
            gid = int(grow.get("id") or 0) if isinstance(grow, dict) else int(grow[0] if grow else 0)
            for item in g_items:
                if isinstance(item, str):
                    task_code, required = item, True
                elif isinstance(item, dict):
                    task_code = str(item.get("task_code") or item.get("code") or "").strip()
                    required = bool(item.get("required", True))
                else:
                    continue
                if not task_code:
                    continue
                if has_group:
                    cursor.execute(
                        f"""
                        INSERT INTO {CHECKLIST_ITEMS_TABLE}
                          (organization_id, checklist_id, group_id, task_code, display_order, required)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (oid, cid, gid or None, task_code, global_idx * 10, 1 if required else 0),
                    )
                else:
                    cursor.execute(
                        f"""
                        INSERT INTO {CHECKLIST_ITEMS_TABLE}
                          (organization_id, checklist_id, task_code, display_order, required)
                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        (oid, cid, task_code, global_idx * 10, 1 if required else 0),
                    )
                global_idx += 1
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

    # Nest items under configured groups for PIN + dashboard reporting.
    groups_cfg = checklist.get("groups")
    if not isinstance(groups_cfg, list):
        groups_cfg = list_checklist_groups(cursor, int(organization_id), int(checklist["id"]))
    items_by_code = {str(row["task_code"]): row for row in member_rows}
    grouped_rows: list[dict[str, Any]] = []
    used_codes: set[str] = set()
    for g in groups_cfg or []:
        if not isinstance(g, Mapping):
            continue
        g_items = []
        for raw in g.get("items") or []:
            code = str(raw.get("task_code") if isinstance(raw, Mapping) else raw or "").strip()
            if not code or code not in items_by_code:
                continue
            g_items.append(items_by_code[code])
            used_codes.add(code)
        g_req = [i for i in g_items if i.get("required")]
        g_done = sum(
            1
            for i in g_req
            if i.get("status") in ("completed", "pending_verification", CHECKLIST_VERIFIED, "verified")
        )
        g_rejected = sum(1 for i in g_req if i.get("status") == "rejected")
        g_incomplete = sum(1 for i in g_req if i.get("status") in ("not_started", "in_progress"))
        if g_rejected:
            g_status = "rejected"
        elif g_incomplete:
            g_status = CHECKLIST_INCOMPLETE
        elif g_req and g_done >= len(g_req):
            g_status = (
                CHECKLIST_PENDING
                if any(i.get("status") == "pending_verification" for i in g_items)
                else "completed"
            )
        else:
            g_status = CHECKLIST_INCOMPLETE
        pct = round((g_done / len(g_req)) * 100, 1) if g_req else None
        grouped_rows.append(
            {
                "group_id": g.get("id"),
                "group_name": g.get("name") or DEFAULT_CHECKLIST_GROUP_NAME,
                "display_order": int(g.get("display_order") or 0),
                "status": g_status,
                "required_total": len(g_req),
                "required_done": g_done,
                "required_incomplete": g_incomplete,
                "required_rejected": g_rejected,
                "completion_pct": pct,
                "can_verify_group": g_status in (CHECKLIST_PENDING, "completed")
                and g_incomplete == 0
                and g_rejected == 0
                and bool(g_req),
                "items": g_items,
            }
        )
    leftovers = [row for code, row in items_by_code.items() if code not in used_codes]
    if leftovers:
        grouped_rows.append(
            {
                "group_id": None,
                "group_name": DEFAULT_CHECKLIST_GROUP_NAME,
                "display_order": 9999,
                "status": CHECKLIST_INCOMPLETE,
                "required_total": sum(1 for i in leftovers if i.get("required")),
                "required_done": 0,
                "required_incomplete": sum(1 for i in leftovers if i.get("required")),
                "required_rejected": 0,
                "completion_pct": None,
                "can_verify_group": False,
                "items": leftovers,
            }
        )

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
        "completion_pct": round((required_done / required_total) * 100, 1) if required_total else None,
        "can_verify_all": overall == CHECKLIST_PENDING and required_incomplete == 0 and required_rejected == 0,
        "items": member_rows,
        "groups": grouped_rows,
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


def _approve_pending_items(
    cursor,
    *,
    organization_id: int,
    items: Sequence[Mapping[str, Any]],
    verifier_user_id: int,
) -> int:
    approved = 0
    for item in items or []:
        for act in item.get("activities") or []:
            if act.get("status") != STATUS_PENDING_APPROVAL:
                continue
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
            approved += 1
    return approved


def verify_checklist_group(
    cursor,
    *,
    organization_id: int,
    checklist_id: int,
    group_id: int,
    business_date: date,
    verifier_user_id: int,
    has_supervisor_review: bool = False,
) -> dict[str, Any]:
    """Verify all pending contributions in one named checklist group."""
    del has_supervisor_review  # reserved for future method-specific gates
    ensure_task_catalog_tables(cursor)
    checklists = {c["id"]: c for c in list_checklists(cursor, int(organization_id))}
    cl = checklists.get(int(checklist_id))
    if not cl:
        raise CleaningTaskError("Checklist not found.", status=404)
    status = build_checklist_day_status(cursor, int(organization_id), cl, business_date)
    group = next(
        (
            g
            for g in (status.get("groups") or [])
            if g.get("group_id") is not None and int(g["group_id"]) == int(group_id)
        ),
        None,
    )
    if not group:
        raise CleaningTaskError("Checklist group not found.", status=404)
    if not group.get("can_verify_group"):
        raise CleaningTaskError(
            "Cannot verify group until all required items are completed and none are rejected.",
            status=400,
        )
    _approve_pending_items(
        cursor,
        organization_id=int(organization_id),
        items=group.get("items") or [],
        verifier_user_id=int(verifier_user_id),
    )
    return build_checklist_day_status(cursor, int(organization_id), cl, business_date)


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
    _approve_pending_items(
        cursor,
        organization_id=int(organization_id),
        items=status.get("items") or [],
        verifier_user_id=int(verifier_user_id),
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
            json.dumps({"item_count": len(status["items"]), "groups": len(status.get("groups") or [])}),
        ),
    )
    return build_checklist_day_status(cursor, int(organization_id), cl, business_date)


def verify_checklist_group(
    cursor,
    *,
    organization_id: int,
    checklist_id: int,
    group_id: int,
    business_date: date,
    verifier_user_id: int,
    has_supervisor_review: bool = False,
) -> dict[str, Any]:
    """Verify all pending contributions inside one checklist group."""
    ensure_task_catalog_tables(cursor)
    checklists = {c["id"]: c for c in list_checklists(cursor, int(organization_id))}
    cl = checklists.get(int(checklist_id))
    if not cl:
        raise CleaningTaskError("Checklist not found.", status=404)
    status = build_checklist_day_status(cursor, int(organization_id), cl, business_date)
    group = next(
        (g for g in (status.get("groups") or []) if g.get("group_id") is not None and int(g["group_id"]) == int(group_id)),
        None,
    )
    if not group:
        raise CleaningTaskError("Checklist group not found.", status=404)
    if not group.get("can_verify_group"):
        raise CleaningTaskError(
            "Cannot verify group until all required items are completed and none are rejected.",
            status=400,
        )
    for item in group.get("items") or []:
        for act in item.get("activities") or []:
            if act.get("status") == STATUS_PENDING_APPROVAL:
                if int(act.get("user_id") or 0) == int(verifier_user_id):
                    raise CleaningTaskError(
                        "You cannot verify a checklist group that includes your own completion.",
                        status=403,
                    )
                approve_activity(
                    cursor,
                    organization_id=int(organization_id),
                    activity_id=int(act["id"]),
                    supervisor_user_id=int(verifier_user_id),
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
