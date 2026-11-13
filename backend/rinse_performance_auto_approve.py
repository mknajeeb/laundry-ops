"""Automatic Folder approval when a closed session meets the existing target.

Runs from session-close enqueue plus data finalization (Step-1 scrape refresh
and the existing change-jobs runner). Opening Performance does not approve.

The organization setting defaults off. Enabling it records an Eastern timestamp
and does not walk historical sessions that ended before that timestamp.
A supervisor unapprove or exclude for the current fingerprint wins.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from backend.business_time import business_now
from backend.rinse_folding_settings import _get_setting, _set_setting
from backend.rinse_performance_approvals import (
    ACTION_EXCLUDE,
    ACTION_INVALIDATE,
    ACTION_UNAPPROVE,
    APPROVALS_TABLE,
    EVENTS_TABLE,
    ensure_rinse_performance_approval_tables,
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


def ensure_auto_approve_queue(cursor) -> None:
    if table_exists(cursor, QUEUE_TABLE):
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {QUEUE_TABLE} (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          business_date_et DATE NOT NULL,
          shift_session_id INT NULL,
          segment_id INT NULL,
          enqueued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          processed_at DATETIME NULL,
          UNIQUE KEY uq_perf_auto_q (organization_id, business_date_et, segment_id),
          KEY idx_perf_auto_q_open (organization_id, processed_at, business_date_et)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


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
        if order.get("missing_production_credit_weight"):
            return False, "incomplete_evidence"
        if order.get("needs_review"):
            return False, "needs_review"
        assignment = str(order.get("session_assignment") or "").lower()
        if assignment in {"needs_review", "unassigned"}:
            return False, "needs_review" if assignment == "needs_review" else "incomplete_evidence"
        pre = order.get("pre_weight_lbs")
        if pre is None:
            pre = order.get("credited_weight_lbs")
        if pre is None:
            pre = order.get("evidence_pre_weight_lbs")
        if pre is None:
            return False, "incomplete_evidence"
    return True, "ok"


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


def auto_approve_finalized_folder_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
) -> dict[str, Any]:
    """Evaluate closed Folder sessions for one finalized ET day. No historical scan."""
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
        "results": [],
    }
    for sess in day.get("sessions") or []:
        out = consider_session_for_auto_approve(
            cursor,
            org,
            selected_date_et=selected_date_et,
            session=sess,
            target=target,
            enabled_at=enabled_at,
        )
        status = str(out.get("status") or "")
        if status == "auto_approved" and out.get("ok"):
            summary["approved"] += 1
        elif out.get("already_approved"):
            summary["already_approved"] += 1
        elif status == "below_target":
            summary["below_target"] += 1
        else:
            summary["skipped"] += 1
        summary["results"].append(
            {"session_id": out.get("session_id"), "status": status, "ok": bool(out.get("ok"))}
        )
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
        ensure_auto_approve_queue(cursor)
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
    """Idempotent columns. Not invoked against production by this workstream's tests."""
    ensure_rinse_performance_approval_tables(cursor)
    if not table_exists(cursor, APPROVALS_TABLE):
        return
    cursor.execute(f"SHOW COLUMNS FROM {APPROVALS_TABLE}")
    have = set()
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            have.add(str(row.get("Field") or row.get("field") or "").lower())
    if "approval_source" not in have:
        try:
            cursor.execute(
                f"ALTER TABLE {APPROVALS_TABLE} ADD COLUMN approval_source VARCHAR(16) NULL"
            )
        except Exception:
            pass
    if "applied_target_lbs_per_hour" not in have:
        try:
            cursor.execute(
                f"ALTER TABLE {APPROVALS_TABLE} "
                "ADD COLUMN applied_target_lbs_per_hour DECIMAL(14,4) NULL"
            )
        except Exception:
            pass
