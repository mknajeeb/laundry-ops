"""Generic performance session publication (approve / invalidate / Rinse reads).

Rinse never reads live Management Performance — only approved snapshots.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_performance_roles import ROLE_FOLDER, get_role, role_is_publishable
from backend.ta_helpers import table_exists

ACTION_APPROVE = "APPROVE"
ACTION_INVALIDATE = "INVALIDATE"
ACTION_REAPPROVE = "REAPPROVE"
ACTION_UNAPPROVE = "UNAPPROVE"

APPROVALS_TABLE = "rinse_performance_session_approvals"
EVENTS_TABLE = "rinse_performance_approval_events"


def ensure_rinse_performance_approval_tables(cursor) -> None:
    if not table_exists(cursor, APPROVALS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {APPROVALS_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              business_date_et DATE NOT NULL,
              role_key VARCHAR(32) NOT NULL,
              session_id VARCHAR(64) NOT NULL,
              segment_id INT NULL,
              employee_user_id INT NULL,
              employee_name VARCHAR(255) NOT NULL,
              metric_key VARCHAR(64) NOT NULL,
              metric_unit VARCHAR(32) NOT NULL,
              published_numerator DECIMAL(14,4) NOT NULL,
              published_denominator DECIMAL(14,4) NOT NULL,
              published_metric_value DECIMAL(14,4) NOT NULL,
              published_quantity DECIMAL(14,4) NULL,
              published_duration_hours DECIMAL(14,4) NULL,
              published_session_start_et DATETIME NULL,
              published_session_end_et DATETIME NULL,
              approved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              approved_by INT NULL,
              content_fingerprint VARCHAR(128) NOT NULL,
              invalidated_at DATETIME NULL,
              invalidated_reason VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_rinse_perf_appr_org_role_session
                (organization_id, role_key, session_id),
              KEY idx_rinse_perf_appr_org_role_date
                (organization_id, role_key, business_date_et),
              KEY idx_rinse_perf_appr_org_emp_date
                (organization_id, employee_user_id, business_date_et),
              KEY idx_rinse_perf_appr_active
                (organization_id, role_key, invalidated_at, business_date_et),
              KEY idx_rinse_perf_read_role_week
                (organization_id, role_key, invalidated_at, business_date_et),
              KEY idx_rinse_perf_read_emp_hist
                (organization_id, role_key, employee_user_id, invalidated_at,
                 business_date_et, published_session_start_et, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, EVENTS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              role_key VARCHAR(32) NOT NULL,
              session_id VARCHAR(64) NOT NULL,
              business_date_et DATE NULL,
              action VARCHAR(32) NOT NULL,
              actor_user_id INT NULL,
              actor_name VARCHAR(255) NULL,
              reason VARCHAR(255) NULL,
              snapshot_metric_value DECIMAL(14,4) NULL,
              content_fingerprint VARCHAR(128) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_rinse_perf_ev_org_role_session
                (organization_id, role_key, session_id),
              KEY idx_rinse_perf_ev_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def folder_session_fingerprint(session: Mapping[str, Any]) -> str:
    """Stable hash of values that define published Folder performance."""
    parts = [
        str(session.get("session_id") or "").strip(),
        ROLE_FOLDER,
        str(session.get("employee") or "").strip().casefold(),
        f"{float(session.get('total_pre_lbs') or 0):.4f}",
        f"{float(session.get('performance_hours') or 0):.4f}",
        f"{float(session.get('lbs_per_hour') or 0):.4f}",
        str(session.get("orders_completed") or 0),
        str(session.get("start_time") or ""),
        str(session.get("end_time") or ""),
        str(session.get("performance_basis") or ""),
        str(session.get("role_status") or ""),
    ]
    bag_ids = []
    for o in session.get("orders") or []:
        bid = str(o.get("bag_id") or "").strip().upper()
        if bid:
            bag_ids.append(bid)
    parts.append("|".join(sorted(bag_ids)))
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_event(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    session_id: str,
    action: str,
    business_date_et: date | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    reason: str | None = None,
    snapshot_metric_value: float | None = None,
    content_fingerprint: str | None = None,
) -> None:
    ensure_rinse_performance_approval_tables(cursor)
    cursor.execute(
        f"""
        INSERT INTO {EVENTS_TABLE} (
          organization_id, role_key, session_id, business_date_et,
          action, actor_user_id, actor_name, reason,
          snapshot_metric_value, content_fingerprint
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            str(role_key).upper(),
            str(session_id),
            business_date_et,
            action,
            actor_user_id,
            actor_name,
            reason,
            snapshot_metric_value,
            content_fingerprint,
        ),
    )


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip().replace("Z", "")
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text[:19])
        if " " in text:
            return datetime.fromisoformat(text[:19])
    except ValueError:
        return None
    return None


def session_is_approvable(session: Mapping[str, Any]) -> tuple[bool, str]:
    """Closed Folder sessions with positive hours and a rate are approvable."""
    if str(session.get("role_status") or "").lower() == "open":
        return False, "open"
    if str(session.get("role_status") or "").lower() == "unresolved":
        return False, "unresolved"
    hours = session.get("performance_hours")
    try:
        hours_f = float(hours) if hours is not None else 0.0
    except (TypeError, ValueError):
        hours_f = 0.0
    if hours_f <= 0:
        return False, "invalid_empty"
    rate = session.get("lbs_per_hour")
    if rate is None:
        return False, "invalid_empty"
    sid = str(session.get("session_id") or "").strip()
    if not sid:
        return False, "invalid_empty"
    emp = str(session.get("employee") or "").strip()
    if not emp:
        return False, "invalid_empty"
    return True, "ok"


def upsert_approved_snapshot(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    snapshot: Mapping[str, Any],
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Insert or replace an APPROVED snapshot (clears invalidation)."""
    if not role_is_publishable(role_key):
        raise ValueError(f"role_key {role_key!r} is not publishable")
    role = get_role(role_key)
    assert role is not None
    ensure_rinse_performance_approval_tables(cursor)

    sid = str(snapshot["session_id"]).strip()
    org = int(organization_id)
    rk = str(role_key).upper()
    biz = _parse_date(snapshot.get("business_date_et") or snapshot.get("selected_date_et"))
    if biz is None:
        raise ValueError("business_date_et required")

    existing = get_approval_row(cursor, org, role_key=rk, session_id=sid)
    was_active = bool(existing and existing.get("invalidated_at") is None)
    action = ACTION_REAPPROVE if existing else ACTION_APPROVE

    fp = str(snapshot.get("content_fingerprint") or "")
    metric_value = float(snapshot["published_metric_value"])
    cursor.execute(
        f"""
        INSERT INTO {APPROVALS_TABLE} (
          organization_id, business_date_et, role_key, session_id, segment_id,
          employee_user_id, employee_name, metric_key, metric_unit,
          published_numerator, published_denominator, published_metric_value,
          published_quantity, published_duration_hours,
          published_session_start_et, published_session_end_et,
          approved_at, approved_by, content_fingerprint,
          invalidated_at, invalidated_reason
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,NULL,NULL
        )
        ON DUPLICATE KEY UPDATE
          business_date_et = VALUES(business_date_et),
          segment_id = VALUES(segment_id),
          employee_user_id = VALUES(employee_user_id),
          employee_name = VALUES(employee_name),
          metric_key = VALUES(metric_key),
          metric_unit = VALUES(metric_unit),
          published_numerator = VALUES(published_numerator),
          published_denominator = VALUES(published_denominator),
          published_metric_value = VALUES(published_metric_value),
          published_quantity = VALUES(published_quantity),
          published_duration_hours = VALUES(published_duration_hours),
          published_session_start_et = VALUES(published_session_start_et),
          published_session_end_et = VALUES(published_session_end_et),
          approved_at = NOW(),
          approved_by = VALUES(approved_by),
          content_fingerprint = VALUES(content_fingerprint),
          invalidated_at = NULL,
          invalidated_reason = NULL,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            org,
            biz,
            rk,
            sid,
            snapshot.get("segment_id"),
            snapshot.get("employee_user_id"),
            str(snapshot.get("employee_name") or ""),
            str(snapshot.get("metric_key") or role["metric_key"]),
            str(snapshot.get("metric_unit") or role["unit"]),
            float(snapshot["published_numerator"]),
            float(snapshot["published_denominator"]),
            metric_value,
            snapshot.get("published_quantity"),
            snapshot.get("published_duration_hours"),
            _parse_dt(snapshot.get("published_session_start_et")),
            _parse_dt(snapshot.get("published_session_end_et")),
            actor_user_id,
            fp,
        ),
    )
    _record_event(
        cursor,
        org,
        role_key=rk,
        session_id=sid,
        action=action,
        business_date_et=biz,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        reason=None,
        snapshot_metric_value=metric_value,
        content_fingerprint=fp,
    )
    return {
        "ok": True,
        "action": action,
        "session_id": sid,
        "role_key": rk,
        "already_approved": was_active and action == ACTION_REAPPROVE and existing
        and str(existing.get("content_fingerprint") or "") == fp,
        "published_metric_value": metric_value,
        "content_fingerprint": fp,
    }


def invalidate_approvals(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    session_ids: Sequence[str] | None = None,
    business_date_et: date | None = None,
    reason: str,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Mark matching active approvals invalidated (remain in table for audit)."""
    ensure_rinse_performance_approval_tables(cursor)
    org = int(organization_id)
    rk = str(role_key).upper()
    clauses = [
        "organization_id=%s",
        "role_key=%s",
        "invalidated_at IS NULL",
    ]
    params: list[Any] = [org, rk]
    if business_date_et is not None:
        clauses.append("business_date_et=%s")
        params.append(business_date_et)
    sids = [str(s).strip() for s in (session_ids or []) if str(s).strip()]
    if sids:
        placeholders = ",".join(["%s"] * len(sids))
        clauses.append(f"session_id IN ({placeholders})")
        params.extend(sids)
    where = " AND ".join(clauses)

    cursor.execute(
        f"""
        SELECT session_id, business_date_et, published_metric_value, content_fingerprint
        FROM {APPROVALS_TABLE}
        WHERE {where}
        """,
        tuple(params),
    )
    rows = list(cursor.fetchall() or [])
    if not rows:
        return {"ok": True, "invalidated": 0, "session_ids": []}

    cursor.execute(
        f"""
        UPDATE {APPROVALS_TABLE}
        SET invalidated_at = NOW(),
            invalidated_reason = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE {where}
        """,
        tuple([reason[:255]] + params),
    )
    out_ids = []
    for row in rows:
        sid = str(row["session_id"] if isinstance(row, dict) else row[0])
        out_ids.append(sid)
        biz = row["business_date_et"] if isinstance(row, dict) else row[1]
        metric = row["published_metric_value"] if isinstance(row, dict) else row[2]
        fp = row["content_fingerprint"] if isinstance(row, dict) else row[3]
        _record_event(
            cursor,
            org,
            role_key=rk,
            session_id=sid,
            action=ACTION_INVALIDATE,
            business_date_et=_parse_date(biz),
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            reason=reason[:255],
            snapshot_metric_value=float(metric) if metric is not None else None,
            content_fingerprint=str(fp) if fp else None,
        )
    return {"ok": True, "invalidated": len(out_ids), "session_ids": out_ids}


def unapprove_session(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    session_id: str,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    reason: str = "manual_unapprove",
) -> dict[str, Any]:
    return invalidate_approvals(
        cursor,
        organization_id,
        role_key=role_key,
        session_ids=[session_id],
        reason=reason,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )


def get_approval_row(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    session_id: str,
) -> dict[str, Any] | None:
    ensure_rinse_performance_approval_tables(cursor)
    cursor.execute(
        f"""
        SELECT *
        FROM {APPROVALS_TABLE}
        WHERE organization_id=%s AND role_key=%s AND session_id=%s
        LIMIT 1
        """,
        (int(organization_id), str(role_key).upper(), str(session_id).strip()),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_active_approvals(
    cursor,
    organization_id: int,
    *,
    role_key: str | None = None,
    week_start: date | None = None,
    week_end: date | None = None,
    employee_user_id: int | None = None,
    employee_name: str | None = None,
    session_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Active = not invalidated. Used by Rinse dashboard reads."""
    ensure_rinse_performance_approval_tables(cursor)
    clauses = ["organization_id=%s", "invalidated_at IS NULL"]
    params: list[Any] = [int(organization_id)]
    if role_key:
        clauses.append("role_key=%s")
        params.append(str(role_key).upper())
    if week_start is not None:
        clauses.append("business_date_et >= %s")
        params.append(week_start)
    if week_end is not None:
        clauses.append("business_date_et <= %s")
        params.append(week_end)
    if employee_user_id is not None:
        clauses.append("employee_user_id=%s")
        params.append(int(employee_user_id))
    if employee_name:
        clauses.append("employee_name=%s")
        params.append(str(employee_name).strip())
    sids = [str(s).strip() for s in (session_ids or []) if str(s).strip()]
    if sids:
        placeholders = ",".join(["%s"] * len(sids))
        clauses.append(f"session_id IN ({placeholders})")
        params.extend(sids)
    cursor.execute(
        f"""
        SELECT *
        FROM {APPROVALS_TABLE}
        WHERE {" AND ".join(clauses)}
        ORDER BY business_date_et ASC, published_session_start_et ASC, id ASC
        """,
        tuple(params),
    )
    return [dict(r) for r in (cursor.fetchall() or [])]


def approval_status_map(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    session_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Map session_id → {status: APPROVED|UNAPPROVED, ...} for Management UI."""
    ensure_rinse_performance_approval_tables(cursor)
    sids = [str(s).strip() for s in session_ids if str(s).strip()]
    if not sids:
        return {}
    placeholders = ",".join(["%s"] * len(sids))
    cursor.execute(
        f"""
        SELECT session_id, invalidated_at, approved_at, content_fingerprint,
               published_metric_value
        FROM {APPROVALS_TABLE}
        WHERE organization_id=%s AND role_key=%s AND session_id IN ({placeholders})
        """,
        tuple([int(organization_id), str(role_key).upper()] + sids),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        r = dict(row)
        sid = str(r["session_id"])
        active = r.get("invalidated_at") is None
        out[sid] = {
            "status": "APPROVED" if active else "UNAPPROVED",
            "approved_at": r.get("approved_at"),
            "content_fingerprint": r.get("content_fingerprint"),
            "published_metric_value": (
                float(r["published_metric_value"])
                if r.get("published_metric_value") is not None
                else None
            ),
        }
    for sid in sids:
        out.setdefault(sid, {"status": "UNAPPROVED"})
    return out


def weighted_rate_from_rows(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Σ numerator / Σ denominator — never average of rates."""
    num = 0.0
    den = 0.0
    for r in rows:
        try:
            n = float(r.get("published_numerator") or 0)
            d = float(r.get("published_denominator") or 0)
        except (TypeError, ValueError):
            continue
        if d <= 0:
            continue
        num += n
        den += d
    if den <= 0:
        return None
    return round(num / den, 4)


def et_week_bounds(week_start: date) -> tuple[date, date]:
    """Monday–Sunday ET week (normalize to Monday)."""
    start = week_start - timedelta(days=week_start.weekday())
    end = start + timedelta(days=6)
    return start, end


def current_et_week_start() -> date:
    from backend.business_time import business_today

    today = business_today()
    return today - timedelta(days=today.weekday())
