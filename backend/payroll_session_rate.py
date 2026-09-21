"""Session-level payroll rate override.

Resolution for a shift session:

1. shift_sessions.payroll_rate_override when set (> 0)
2. otherwise the normal effective employee/profile rate

Classification and rate are independent. Role segments inherit the session rate.
Changing the override clears payroll-hours approval for that session only.
Frozen payout lines are not rewritten.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

RATE_SOURCE_PROFILE = "profile"
RATE_SOURCE_SESSION = "session_override"


def _q2(val: Any) -> Decimal:
    try:
        return Decimal(str(val if val is not None else 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except Exception:
        return Decimal("0.00")


def normalize_payroll_rate_override(value: Any) -> Optional[Decimal]:
    """NULL/blank = use profile rate. Otherwise a positive hourly rate."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        rate = _q2(value)
    except Exception as exc:
        raise ValueError("Rate override must be a number or blank") from exc
    if rate <= 0:
        raise ValueError("Rate override must be blank or greater than zero")
    return rate


def resolve_session_hourly_rate(
    profile_rate: Any,
    session_override: Any,
) -> tuple[Decimal, str, Optional[Decimal]]:
    """Return (resolved_rate, rate_source, override_or_none)."""
    override = None
    if session_override is not None and str(session_override).strip() != "":
        try:
            override = normalize_payroll_rate_override(session_override)
        except ValueError:
            override = None
    profile = _q2(profile_rate) if profile_rate is not None and str(profile_rate).strip() != "" else Decimal("0.00")
    if override is not None:
        return override, RATE_SOURCE_SESSION, override
    return profile, RATE_SOURCE_PROFILE, None


def ensure_payroll_session_rate_schema(cursor) -> None:
    """Additive only — no backfill."""
    if table_exists(cursor, "shift_sessions") and not table_has_column(
        cursor, "shift_sessions", "payroll_rate_override"
    ):
        try:
            cursor.execute(
                """
                ALTER TABLE shift_sessions
                ADD COLUMN payroll_rate_override DECIMAL(10,2) NULL
                """
            )
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_session_rate_audit (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_session_id INT NOT NULL,
          actor_id INT NULL,
          created_at DATETIME NOT NULL,
          old_value DECIMAL(10,2) NULL,
          new_value DECIMAL(10,2) NULL,
          reason VARCHAR(500) NULL,
          KEY idx_ss_rate_audit_session (shift_session_id, id)
        )
        """
    )


def set_session_payroll_rate_override(
    conn,
    organization_id: int,
    session_id: int,
    *,
    value: Any,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """Set or clear the session rate override. Does not change classification."""
    from backend.payroll_operations import _session_in_org
    from backend.payroll_workflow import resolve_worker_hourly_rate

    sid = int(session_id)
    cur = conn.cursor()
    ensure_payroll_session_rate_schema(cur)
    if not _session_in_org(conn, organization_id, sid):
        raise ValueError("Time record not found")
    new_value = normalize_payroll_rate_override(value)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, user_id, clock_in_at, payroll_hours_approved, payroll_rate_override
        FROM shift_sessions
        WHERE id=%s
        """,
        (sid,),
    )
    row = c.fetchone()
    if not row:
        raise ValueError("Time record not found")
    old_raw = row.get("payroll_rate_override")
    old_value = None
    if old_raw is not None and str(old_raw).strip() != "":
        try:
            old_value = normalize_payroll_rate_override(old_raw)
        except ValueError:
            old_value = _q2(old_raw) if _q2(old_raw) > 0 else None

    profile_info = resolve_worker_hourly_rate(
        conn, int(row["user_id"]), int(organization_id)
    )
    profile_rate = profile_info.get("hourly_rate")
    resolved, source, _ = resolve_session_hourly_rate(profile_rate, new_value)

    if old_value == new_value:
        return {
            "id": sid,
            "payroll_rate_override": float(new_value) if new_value is not None else None,
            "resolved_hourly_rate": float(resolved) if resolved > 0 else None,
            "profile_hourly_rate": float(_q2(profile_rate)) if profile_rate else None,
            "rate_source": source,
            "payroll_hours_approved": bool(row.get("payroll_hours_approved")),
            "approval_cleared": False,
            "audit_appended": False,
        }

    approved = bool(row.get("payroll_hours_approved"))
    sets = ["payroll_rate_override=%s"]
    params: list[Any] = [float(new_value) if new_value is not None else None]
    if approved:
        sets.append("payroll_hours_approved=0")
    params.append(sid)
    c.execute(
        f"UPDATE shift_sessions SET {', '.join(sets)} WHERE id=%s",
        tuple(params),
    )
    reason_text = str(reason or "").strip()[:500] or None
    c.execute(
        """
        INSERT INTO shift_session_rate_audit (
          organization_id, shift_session_id, actor_id, created_at,
          old_value, new_value, reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            sid,
            int(actor_id) if actor_id is not None else None,
            datetime.utcnow(),
            float(old_value) if old_value is not None else None,
            float(new_value) if new_value is not None else None,
            reason_text,
        ),
    )
    conn.commit()
    return {
        "id": sid,
        "payroll_rate_override": float(new_value) if new_value is not None else None,
        "resolved_hourly_rate": float(resolved) if resolved > 0 else None,
        "profile_hourly_rate": float(_q2(profile_rate)) if profile_rate else None,
        "rate_source": source,
        "payroll_hours_approved": False if approved else bool(row.get("payroll_hours_approved")),
        "approval_cleared": approved,
        "audit_appended": True,
    }
