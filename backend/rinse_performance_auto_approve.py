"""Automatic Folder approval when a closed session meets the existing target.

Runs from session-close enqueue plus data finalization (Step-1 scrape refresh
and the existing change-jobs runner). Opening Performance does not approve.

The organization setting defaults off. Enabling it records an Eastern timestamp
and does not walk historical sessions that ended before that timestamp.
A supervisor unapprove or exclude for the current fingerprint wins.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_now
from backend.rinse_folding_settings import _get_setting, _set_setting
from backend.rinse_performance_approvals import (
    ACTION_EXCLUDE,
    ACTION_INVALIDATE,
    ACTION_UNAPPROVE,
    APPROVALS_TABLE,
    EVENTS_TABLE,
    folder_session_fingerprint,
    get_approval_row,
    session_is_approvable,
    upsert_approved_snapshot,
)
from backend.rinse_performance_folder_publisher import (
    get_folder_benchmark,
    session_card_to_snapshot,
)
from backend.rinse_performance_roles import ROLE_FOLDER
from backend.ta_helpers import table_exists

KEY_ENABLED = "rinse_folding_auto_approve_at_target"
KEY_ENABLED_AT = "rinse_folding_auto_approve_enabled_at"
QUEUE_TABLE = "rinse_performance_auto_approve_queue"
SOURCE_AUTO = "AUTO"
SOURCE_MANUAL = "MANUAL"
BLOCKING_ACTIONS = frozenset({ACTION_INVALIDATE, ACTION_UNAPPROVE, ACTION_EXCLUDE})


def business_now_wall() -> datetime:
    now = business_now()
    if now.tzinfo is not None:
        from backend.rinse_folding_et import ET

        return now.astimezone(ET).replace(tzinfo=None)
    return now


def auto_approve_enabled(cursor, organization_id: int) -> bool:
    raw = _get_setting(cursor, int(organization_id), KEY_ENABLED)
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def auto_approve_enabled_at(cursor, organization_id: int) -> datetime | None:
    raw = _get_setting(cursor, int(organization_id), KEY_ENABLED_AT)
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "")
    try:
        if "T" in text or " " in text:
            return datetime.fromisoformat(text[:19])
    except ValueError:
        return None
    return None


def get_auto_approve_setting(cursor, organization_id: int) -> dict[str, Any]:
    enabled = auto_approve_enabled(cursor, organization_id)
    enabled_at = auto_approve_enabled_at(cursor, organization_id)
    return {
        "auto_approve_at_target": enabled,
        "auto_approve_enabled_at": enabled_at.isoformat(sep=" ") if enabled_at else None,
        "target_lbs_per_hour": get_folder_benchmark(cursor, int(organization_id)),
        "target_setting_key": "rinse_folding_lbs_per_hour_target",
    }


def put_auto_approve_setting(cursor, organization_id: int, *, enabled: bool) -> dict[str, Any]:
    """Turn the flag on or off. Turning on stamps now and does not backfill."""
    org = int(organization_id)
    was = auto_approve_enabled(cursor, org)
    _set_setting(cursor, org, KEY_ENABLED, "1" if enabled else "0")
    if enabled and not was:
        _set_setting(cursor, org, KEY_ENABLED_AT, business_now_wall().isoformat(sep=" "))
    if not enabled:
        _set_setting(cursor, org, KEY_ENABLED_AT, "")
    return get_auto_approve_setting(cursor, org)


def ensure_auto_approve_queue(cursor) -> bool:
    """True when the migration created the queue. Requests must not create it."""
    return bool(table_exists(cursor, QUEUE_TABLE))


def session_evidence_is_complete(session: Mapping[str, Any]) -> tuple[bool, str]:
    """Closed, rated, and every credited order has PRE evidence and a clean assignment."""
    ok, reason = session_is_approvable(session)
    if not ok:
        return False, reason
    orders = session.get("orders")
    if not isinstance(orders, list) or not orders:
        return False, "incomplete_evidence"
    if int(session.get("orders_completed") or 0) <= 0:
        return False, "incomplete_evidence"
    for order in orders:
        if not isinstance(order, Mapping):
            return False, "incomplete_evidence"
        if order.get("needs_review"):
            return False, "needs_review"
        assignment = str(order.get("session_assignment") or "").lower()
        if assignment in {"needs_review", "unassigned"}:
            return False, "needs_review" if assignment == "needs_review" else "incomplete_evidence"
        usable, why = _order_pre_is_usable(order)
        if not usable:
            return False, why
    evidenced = []
    for order in orders:
        if isinstance(order, Mapping):
            evidenced.append(_order_evidence_lbs(order))
    if session.get("total_pre_lbs") is not None and all(v is not None for v in evidenced):
        try:
            session_lbs = float(session.get("total_pre_lbs") or 0)
        except (TypeError, ValueError):
            return False, "inconsistent_evidence"
        if abs(session_lbs - sum(evidenced)) > 0.05:
            return False, "inconsistent_evidence"
    return True, "ok"


_CANONICAL_PRE_KEYS = (
    "pre_weight_lbs",
    "credited_weight_lbs",
    "evidence_pre_weight_lbs",
    "pre_lbs",
)


def _numeric_pre_fields(order: Mapping[str, Any]) -> list[tuple[str, float]] | None:
    found: list[tuple[str, float]] = []
    for key in _CANONICAL_PRE_KEYS:
        raw = order.get(key)
        if raw is None or raw == "":
            continue
        try:
            found.append((key, float(raw)))
        except (TypeError, ValueError):
            return None
    return found


def _order_pre_is_usable(order: Mapping[str, Any]) -> tuple[bool, str]:
    """Canonical PRE must be present and agree across the fields that carry it.

    ``pre_lbs`` is the public copy of ``authoritative_evidence_pre_lbs``. A lone
    zero is the missing-weight placeholder, not a recorded PRE. Disagreeing
    numbers, or a POST source, are inconsistent and stay unapproved.
    """
    source = str(
        order.get("credited_weight_source") or order.get("credit_weight_source") or ""
    ).upper()
    if "POST" in source or source in {"AUTHORITATIVE_POST", "OUTPUT"}:
        return False, "inconsistent_evidence"
    if order.get("missing_production_credit_weight"):
        return False, "incomplete_evidence"
    found = _numeric_pre_fields(order)
    if found is None:
        return False, "inconsistent_evidence"
    if not found:
        return False, "incomplete_evidence"
    numbers = [value for _key, value in found]
    if max(numbers) - min(numbers) > 0.05:
        return False, "inconsistent_evidence"
    keys = {key for key, _value in found}
    if keys == {"pre_lbs"} and numbers[0] == 0.0:
        return False, "incomplete_evidence"
    return True, "ok"


def _order_evidence_lbs(order: Mapping[str, Any]) -> float | None:
    found = _numeric_pre_fields(order)
    if not found:
        return None
    return found[-1][1]


def combined_weighted_lbs_per_hour(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """SUM(pounds) / SUM(hours). Never the average of session rates."""
    lbs = 0.0
    hours = 0.0
    bags = 0
    for session in sessions or []:
        try:
            lbs += float(session.get("total_pre_lbs") or 0)
        except (TypeError, ValueError):
            pass
        if session.get("performance_hours") is not None:
            try:
                hours += float(session.get("performance_hours") or 0)
            except (TypeError, ValueError):
                pass
        try:
            bags += int(session.get("orders_completed") or 0)
        except (TypeError, ValueError):
            pass
    rate = round(lbs / hours, 4) if hours > 0 else None
    return {
        "orders_completed": bags,
        "total_pre_lbs": round(lbs, 4),
        "performance_hours": round(hours, 4),
        "lbs_per_hour": rate,
        "aggregate_method": "sum_pounds_over_sum_hours",
    }


def employee_day_predates_activation(
    sessions: Sequence[Mapping[str, Any]],
    enabled_at: datetime,
) -> bool:
    """True when the employee-day closed before auto-approve was turned on.

    An open session is still in progress, so the day is not historical yet.
    """
    if any(str(s.get("role_status") or "").lower() == "open" for s in sessions or []):
        return False
    ends = [ended for ended in (_session_end(s) for s in sessions or []) if ended is not None]
    if not ends:
        return True
    return max(ends) < enabled_at


def meets_target(session: Mapping[str, Any], target: float) -> bool:
    rate = session.get("lbs_per_hour")
    if rate is None:
        return False
    try:
        return float(rate) + 1e-9 >= float(target)
    except (TypeError, ValueError):
        return False


def manual_decision_blocks_auto(
    cursor,
    organization_id: int,
    *,
    session_id: str,
    fingerprint: str,
) -> bool:
    """Supervisor invalidate/exclude for this fingerprint outranks auto-approval."""
    if not table_exists(cursor, EVENTS_TABLE):
        return False
    cursor.execute(
        f"""
        SELECT action, content_fingerprint
        FROM {EVENTS_TABLE}
        WHERE organization_id=%s AND role_key=%s AND session_id=%s
        ORDER BY id DESC
        LIMIT 40
        """,
        (int(organization_id), ROLE_FOLDER, str(session_id)),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").upper()
        fp = str(row.get("content_fingerprint") or "")
        if action not in BLOCKING_ACTIONS:
            continue
        if not fp or fp == fingerprint:
            return True
    return False


def _session_end(session: Mapping[str, Any]) -> datetime | None:
    raw = session.get("end_time") or session.get("performance_end")
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    text = str(raw or "").strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _lock_approval_row(cursor, organization_id: int, session_id: str) -> None:
    if not table_exists(cursor, APPROVALS_TABLE):
        return
    cursor.execute(
        f"""
        SELECT id FROM {APPROVALS_TABLE}
        WHERE organization_id=%s AND role_key=%s AND session_id=%s
        LIMIT 1
        FOR UPDATE
        """,
        (int(organization_id), ROLE_FOLDER, str(session_id)),
    )
    cursor.fetchall()


def consider_session_for_auto_approve(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    session: Mapping[str, Any],
    target: float,
    enabled_at: datetime,
) -> dict[str, Any]:
    sid = str(session.get("session_id") or "").strip()
    ended = _session_end(session)
    if ended is None or ended < enabled_at:
        return {"session_id": sid, "status": "before_enable", "ok": False}
    complete, reason = session_evidence_is_complete(session)
    if not complete:
        return {"session_id": sid, "status": reason, "ok": False}
    if not meets_target(session, target):
        return {"session_id": sid, "status": "below_target", "ok": False}
    fp = folder_session_fingerprint(session)
    if manual_decision_blocks_auto(cursor, organization_id, session_id=sid, fingerprint=fp):
        return {"session_id": sid, "status": "manual_precedence", "ok": False}
    _lock_approval_row(cursor, organization_id, sid)
    existing = get_approval_row(cursor, organization_id, role_key=ROLE_FOLDER, session_id=sid)
    if existing and existing.get("excluded_at"):
        return {"session_id": sid, "status": "excluded", "ok": False}
    if (
        existing
        and existing.get("invalidated_at") is None
        and not existing.get("excluded_at")
        and str(existing.get("content_fingerprint") or "") == fp
    ):
        return {"session_id": sid, "status": "already_approved", "ok": True, "already_approved": True}
    snap = session_card_to_snapshot(session, business_date_et=selected_date_et)
    snap["approval_source"] = SOURCE_AUTO
    snap["applied_target_lbs_per_hour"] = float(target)
    result = upsert_approved_snapshot(
        cursor,
        int(organization_id),
        role_key=ROLE_FOLDER,
        snapshot=snap,
        actor_user_id=None,
        actor_name="auto-approval",
        approval_source=SOURCE_AUTO,
        applied_target_lbs_per_hour=float(target),
    )
    result["status"] = "auto_approved" if result.get("ok") else result.get("status")
    result["applied_target_lbs_per_hour"] = float(target)
    return result


def _session_is_excluded(session: Mapping[str, Any], existing: Mapping[str, Any] | None) -> bool:
    pub = str(
        session.get("publication_status")
        or (session.get("publication") or {}).get("status")
        or ""
    ).upper()
    if pub == "EXCLUDED" or (session.get("publication") or {}).get("excluded"):
        return True
    return bool(existing and existing.get("excluded_at"))


def _approve_one_session(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    session: Mapping[str, Any],
    target: float,
) -> dict[str, Any]:
    """Write one auto-approval. Caller already decided the employee-day qualifies."""
    sid = str(session.get("session_id") or "").strip()
    fp = folder_session_fingerprint(session)
    if manual_decision_blocks_auto(cursor, organization_id, session_id=sid, fingerprint=fp):
        return {"session_id": sid, "status": "manual_precedence", "ok": False}
    _lock_approval_row(cursor, organization_id, sid)
    existing = get_approval_row(cursor, organization_id, role_key=ROLE_FOLDER, session_id=sid)
    if _session_is_excluded(session, existing):
        return {"session_id": sid, "status": "excluded", "ok": False}
    if (
        existing
        and existing.get("invalidated_at") is None
        and str(existing.get("content_fingerprint") or "") == fp
    ):
        return {"session_id": sid, "status": "already_approved", "ok": True, "already_approved": True}
    snap = session_card_to_snapshot(session, business_date_et=selected_date_et)
    snap["approval_source"] = SOURCE_AUTO
    snap["applied_target_lbs_per_hour"] = float(target)
    result = upsert_approved_snapshot(
        cursor,
        int(organization_id),
        role_key=ROLE_FOLDER,
        snapshot=snap,
        actor_user_id=None,
        actor_name="auto-approval",
        approval_source=SOURCE_AUTO,
        applied_target_lbs_per_hour=float(target),
    )
    result["status"] = "auto_approved" if result.get("ok") else result.get("status")
    result["applied_target_lbs_per_hour"] = float(target)
    return result


def consider_employee_day_for_auto_approve(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_name: str,
    sessions: Sequence[Mapping[str, Any]],
    target: float,
    enabled_at: datetime,
) -> dict[str, Any]:
    """Approve an employee-day only from its combined closed-session rate.

    The decision uses SUM(eligible pounds) / SUM(eligible hours). A fast session
    does not approve the day while another session is open, incomplete, or
    while the combined rate is below target. Days that closed before activation
    stay manual.
    """
    rows = [s for s in sessions or [] if isinstance(s, Mapping)]
    base = {"employee": employee_name, "approved": 0, "already_approved": 0, "results": []}
    if any(str(s.get("role_status") or "").lower() == "open" for s in rows):
        return {**base, "status": "open", "ok": False, "retry": True}
    if employee_day_predates_activation(rows, enabled_at):
        return {**base, "status": "before_enable", "ok": False, "retry": False}
    countable: list[Mapping[str, Any]] = []
    for session in rows:
        if not session.get("include_in_authoritative_aggregate", True):
            continue
        status = str(session.get("role_status") or "").lower()
        if status == "unresolved":
            return {**base, "status": "unresolved", "ok": False, "retry": False}
        sid = str(session.get("session_id") or "").strip()
        existing = get_approval_row(cursor, organization_id, role_key=ROLE_FOLDER, session_id=sid)
        if _session_is_excluded(session, existing):
            continue
        complete, reason = session_evidence_is_complete(session)
        if not complete:
            return {**base, "status": reason, "ok": False, "retry": False}
        countable.append(session)
    if not countable:
        return {**base, "status": "excluded", "ok": False, "retry": False}
    totals = combined_weighted_lbs_per_hour(countable)
    rate = totals.get("lbs_per_hour")
    summary = {**base, **totals}
    if rate is None or float(rate) + 1e-9 < float(target):
        return {**summary, "status": "below_target", "ok": False, "retry": False}
    approved = 0
    already = 0
    results = []
    for session in countable:
        out = _approve_one_session(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            session=session,
            target=target,
        )
        status = str(out.get("status") or "")
        if status == "auto_approved" and out.get("ok"):
            approved += 1
        elif out.get("already_approved"):
            already += 1
        results.append(
            {"session_id": out.get("session_id"), "status": status, "ok": bool(out.get("ok"))}
        )
    day_status = "auto_approved" if approved or already else "manual_precedence"
    return {
        **summary,
        "status": day_status,
        "ok": day_status == "auto_approved",
        "approved": approved,
        "already_approved": already,
        "retry": False,
        "results": results,
    }


def auto_approve_finalized_folder_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> dict[str, Any]:
    """Evaluate closed Folder employee-days for one ET day. No historical backfill."""
    org = int(organization_id)
    if not auto_approve_enabled(cursor, org):
        return {"ok": True, "skipped": True, "reason": "disabled", "approved": 0}
    enabled_at = auto_approve_enabled_at(cursor, org)
    if enabled_at is None:
        return {"ok": True, "skipped": True, "reason": "enabled_at_missing", "approved": 0}
    from backend.management_wf_folder_performance import build_day_folder_performance

    day = build_day_folder_performance(
        cursor,
        org,
        selected_date_et=selected_date_et,
        attach_customers=False,
    )
    target = get_folder_benchmark(cursor, org)
    summary = {
        "ok": True,
        "selected_date_et": selected_date_et.isoformat(),
        "target_lbs_per_hour": target,
        "approved": 0,
        "already_approved": 0,
        "below_target": 0,
        "skipped": 0,
        "retry": False,
        "results": [],
    }
    employees = day.get("employees") or []
    if not employees:
        employees = [{"employee": "", "sessions": day.get("sessions") or []}]
    for emp in employees:
        sessions = emp.get("sessions") or []
        if not sessions:
            continue
        out = consider_employee_day_for_auto_approve(
            cursor,
            org,
            selected_date_et=selected_date_et,
            employee_name=str(emp.get("employee") or ""),
            sessions=sessions,
            target=target,
            enabled_at=enabled_at,
        )
        status = str(out.get("status") or "")
        if out.get("retry"):
            summary["retry"] = True
        summary["approved"] += int(out.get("approved") or 0)
        summary["already_approved"] += int(out.get("already_approved") or 0)
        if status == "below_target":
            summary["below_target"] += 1
        elif status not in {"auto_approved"}:
            summary["skipped"] += 1
        summary["results"].append(
            {
                "employee": out.get("employee"),
                "status": status,
                "ok": bool(out.get("ok")),
                "lbs_per_hour": out.get("lbs_per_hour"),
                "approved": out.get("approved"),
                "sessions": out.get("results") or [],
            }
        )
    if not summary["retry"]:
        _mark_queue_processed(cursor, org, selected_date_et)
    return summary


def _mark_queue_processed(cursor, organization_id: int, selected_date_et: date) -> None:
    if not table_exists(cursor, QUEUE_TABLE):
        return
    cursor.execute(
        f"""
        UPDATE {QUEUE_TABLE}
        SET processed_at=CURRENT_TIMESTAMP
        WHERE organization_id=%s AND business_date_et=%s AND processed_at IS NULL
        """,
        (int(organization_id), selected_date_et),
    )


def enqueue_folder_segment_close(conn, shift_session_id: int) -> None:
    """Fast enqueue when a Folder segment closes. Does not build the day."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT sjs.id AS segment_id, sjs.role_code, sjs.category_code, sjs.ended_at,
                   ss.organization_id
            FROM shift_job_segments sjs
            JOIN shift_sessions ss ON ss.id = sjs.shift_session_id
            WHERE sjs.shift_session_id=%s AND sjs.ended_at IS NOT NULL
            ORDER BY sjs.ended_at DESC
            LIMIT 1
            """,
            (int(shift_session_id),),
        )
        row = cursor.fetchone()
        if not isinstance(row, dict):
            return
        role = str(row.get("role_code") or "").upper()
        category = str(row.get("category_code") or "").upper()
        if role != "FOLDER" or category != "RINSE_WF":
            return
        org = int(row.get("organization_id") or 0)
        if org <= 0 or not auto_approve_enabled(cursor, org):
            return
        ended = row.get("ended_at")
        if isinstance(ended, datetime):
            day = ended.date()
        else:
            day = business_now_wall().date()
        if not ensure_auto_approve_queue(cursor):
            return
        cursor.execute(
            f"""
            INSERT INTO {QUEUE_TABLE} (
              organization_id, business_date_et, shift_session_id, segment_id
            ) VALUES (%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE enqueued_at=enqueued_at
            """,
            (org, day, int(shift_session_id), int(row.get("segment_id") or 0)),
        )
    finally:
        cursor.close()


def process_pending_auto_approve_queue(cursor, *, limit: int = 20) -> dict[str, Any]:
    """Existing change-jobs / retry path. One day build per pending org+date."""
    if not table_exists(cursor, QUEUE_TABLE):
        return {"ok": True, "processed_days": 0}
    cursor.execute(
        f"""
        SELECT organization_id, business_date_et
        FROM {QUEUE_TABLE}
        WHERE processed_at IS NULL
        GROUP BY organization_id, business_date_et
        ORDER BY MIN(id)
        LIMIT %s
        """,
        (int(limit),),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    processed = []
    for row in rows:
        org = int(row["organization_id"])
        day = row["business_date_et"]
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        if not isinstance(day, date):
            continue
        if not auto_approve_enabled(cursor, org):
            _mark_queue_processed(cursor, org, day)
            processed.append({"organization_id": org, "date_et": day.isoformat(), "skipped": True})
            continue
        summary = auto_approve_finalized_folder_day(cursor, org, selected_date_et=day)
        processed.append(
            {
                "organization_id": org,
                "date_et": day.isoformat(),
                "approved": summary.get("approved"),
            }
        )
    return {"ok": True, "processed_days": len(processed), "days": processed}


def stamp_approval_columns_on_ensure(cursor) -> None:
    """Columns come from the SQL migration. Requests must not ALTER production."""
    return None
