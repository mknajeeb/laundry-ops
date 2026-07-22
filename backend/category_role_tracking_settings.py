"""Organization-level feature flag for Category & Role Tracking (Phase 1).

Default: disabled. Stored in system_settings as category_role_tracking_enabled.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.payroll_identity import eastern_now_naive
from backend.ta_helpers import table_exists, table_has_column

SETTING_KEY = "category_role_tracking_enabled"


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"0", "false", "off", "no", "disabled", ""}:
        return False
    if s in {"1", "true", "on", "yes", "enabled"}:
        return True
    return default


def _get_setting(cursor, organization_id: int, key: str) -> Optional[str]:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    v = row.get("svalue") if isinstance(row, dict) else row[0]
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def is_category_role_tracking_enabled(conn, organization_id: int) -> bool:
    """Default False when unset — feature must be explicitly enabled per org."""
    cursor = conn.cursor(dictionary=True)
    return _truthy(_get_setting(cursor, int(organization_id), SETTING_KEY), False)


def get_category_role_tracking_settings(conn, organization_id: int) -> dict:
    enabled = is_category_role_tracking_enabled(conn, organization_id)
    return {
        "category_role_tracking_enabled": enabled,
        "enabled": enabled,
    }


def close_open_task_segments_for_organization(
    conn,
    organization_id: int,
    *,
    ended_at=None,
    close_source: str = "feature_disabled",
) -> int:
    """Close all open task segments for the org. Idempotent. Does not touch attendance."""
    from backend.shift_job_tracking import ensure_shift_job_tracking_schema

    c = conn.cursor(dictionary=True)
    ensure_shift_job_tracking_schema(c)
    if not table_exists(c, "shift_job_segments"):
        return 0

    ended = ended_at or eastern_now_naive()
    # Find open segments scoped to this organization via session.
    c.execute(
        """
        SELECT sjs.id, sjs.shift_session_id
        FROM shift_job_segments sjs
        JOIN shift_sessions ss ON ss.id = sjs.shift_session_id
        WHERE ss.organization_id=%s AND sjs.ended_at IS NULL
        """,
        (int(organization_id),),
    )
    rows = c.fetchall() or []
    if not rows:
        return 0

    seg_ids = [int(r["id"]) for r in rows]
    session_ids = sorted({int(r["shift_session_id"]) for r in rows})

    upd = conn.cursor()
    if table_has_column(upd, "shift_job_segments", "close_source"):
        placeholders = ",".join(["%s"] * len(seg_ids))
        upd.execute(
            f"""
            UPDATE shift_job_segments
            SET ended_at=%s, close_source=%s
            WHERE id IN ({placeholders}) AND ended_at IS NULL
            """,
            (ended, close_source, *seg_ids),
        )
    else:
        placeholders = ",".join(["%s"] * len(seg_ids))
        upd.execute(
            f"""
            UPDATE shift_job_segments
            SET ended_at=%s
            WHERE id IN ({placeholders}) AND ended_at IS NULL
            """,
            (ended, *seg_ids),
        )
    closed = int(upd.rowcount or 0)

    # Clear current assignment pointers on affected sessions (attendance unchanged).
    sets = []
    if table_has_column(upd, "shift_sessions", "current_job_name_id"):
        sets.append("current_job_name_id=NULL")
    if table_has_column(upd, "shift_sessions", "current_category_id"):
        sets.append("current_category_id=NULL")
    if table_has_column(upd, "shift_sessions", "current_role_id"):
        sets.append("current_role_id=NULL")
    if table_has_column(upd, "shift_sessions", "current_category_role_id"):
        sets.append("current_category_role_id=NULL")
    if sets and session_ids:
        ph = ",".join(["%s"] * len(session_ids))
        upd.execute(
            f"UPDATE shift_sessions SET {', '.join(sets)} WHERE id IN ({ph})",
            tuple(session_ids),
        )
    return closed


def set_category_role_tracking_enabled(
    conn,
    organization_id: int,
    enabled: bool,
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Persist the flag. When disabling, close open task segments for the org.
    Idempotent: disabling twice does not reopen or duplicate closes.
    Returns audit payload details.
    """
    from backend.ta_routes import write_audit

    oid = int(organization_id)
    previous = is_category_role_tracking_enabled(conn, oid)
    new_val = bool(enabled)
    closed_count = 0
    ended_at = None
    c = conn.cursor(dictionary=True)

    if previous == new_val:
        # Still ensure stored value exists (explicit false for new orgs).
        _set_setting(c, oid, SETTING_KEY, "1" if new_val else "0")
        return {
            "category_role_tracking_enabled": new_val,
            "previous": previous,
            "changed": False,
            "open_segments_closed": 0,
        }

    if not new_val:
        ended_at = eastern_now_naive()
        closed_count = close_open_task_segments_for_organization(
            conn, oid, ended_at=ended_at, close_source="feature_disabled"
        )

    _set_setting(c, oid, SETTING_KEY, "1" if new_val else "0")

    action = "admin_feature_enabled" if new_val else "admin_feature_disabled"
    write_audit(
        conn,
        actor_user_id,
        "system_settings",
        oid,
        action,
        old={
            "category_role_tracking_enabled": previous,
            "organization_id": oid,
        },
        new={
            "category_role_tracking_enabled": new_val,
            "organization_id": oid,
            "open_segments_closed": closed_count,
            "closed_at": ended_at.isoformat() if ended_at else None,
        },
        remarks=reason,
        organization_id=oid,
    )

    return {
        "category_role_tracking_enabled": new_val,
        "previous": previous,
        "changed": True,
        "open_segments_closed": closed_count,
        "closed_at": ended_at.isoformat() if ended_at else None,
    }
