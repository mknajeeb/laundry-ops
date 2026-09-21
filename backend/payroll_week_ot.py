"""Employee-week overtime override for payroll.

Keyed by (organization_id, user_id, payroll_week_start).

Modes:
  default    — use existing chronological weekly OT calculation
  disable_ot — weekly OT hours = 0; all eligible hours stay straight-time

Does not change classifications, rates, permanent OT profile settings, or
move sessions between batches. Feeds into allocate_session_overtime(enabled=...).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

OT_MODE_DEFAULT = "default"
OT_MODE_DISABLE = "disable_ot"
ALLOWED_OT_MODES = frozenset({OT_MODE_DEFAULT, OT_MODE_DISABLE})


def normalize_ot_week_mode(value: Any) -> str:
    if value is None:
        return OT_MODE_DEFAULT
    raw = str(value).strip().lower()
    if raw in ("", "null", "none", "default", "standard", "enabled", "normal"):
        return OT_MODE_DEFAULT
    if raw in ("disable_ot", "disabled", "off", "no_ot", "disable"):
        return OT_MODE_DISABLE
    raise ValueError("Overtime week mode must be default or disable_ot")


def ensure_payroll_week_ot_schema(cursor) -> None:
    """Additive only — no backfill."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_payroll_week_ot_overrides (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          payroll_week_start DATE NOT NULL,
          ot_mode VARCHAR(32) NOT NULL DEFAULT 'default',
          updated_at DATETIME NOT NULL,
          updated_by INT NULL,
          UNIQUE KEY uq_emp_week_ot (organization_id, user_id, payroll_week_start),
          KEY idx_emp_week_ot_week (organization_id, payroll_week_start)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_payroll_week_ot_override_audit (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          payroll_week_start DATE NOT NULL,
          actor_id INT NULL,
          created_at DATETIME NOT NULL,
          old_value VARCHAR(32) NULL,
          new_value VARCHAR(32) NULL,
          reason VARCHAR(500) NULL,
          KEY idx_emp_week_ot_audit (organization_id, user_id, payroll_week_start, id)
        )
        """
    )
    if table_exists(cursor, "payout_batch_lines") and not table_has_column(
        cursor, "payout_batch_lines", "ot_week_override_snapshot"
    ):
        try:
            cursor.execute(
                """
                ALTER TABLE payout_batch_lines
                ADD COLUMN ot_week_override_snapshot VARCHAR(32) NULL
                """
            )
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()


def get_employee_week_ot_mode(
    conn,
    organization_id: int,
    user_id: int,
    payroll_week_start: date,
) -> str:
    cur = conn.cursor()
    ensure_payroll_week_ot_schema(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT ot_mode FROM employee_payroll_week_ot_overrides
        WHERE organization_id=%s AND user_id=%s AND payroll_week_start=%s
        LIMIT 1
        """,
        (int(organization_id), int(user_id), payroll_week_start),
    )
    row = c.fetchone()
    if not row:
        return OT_MODE_DEFAULT
    try:
        return normalize_ot_week_mode(row.get("ot_mode"))
    except ValueError:
        return OT_MODE_DEFAULT


def load_employee_week_ot_modes(
    conn,
    organization_id: int,
    user_ids: list[int],
    week_starts: list[date],
) -> dict[tuple[int, str], str]:
    """Map (user_id, week_start_iso) -> ot_mode for bulk Time Records display."""
    out: dict[tuple[int, str], str] = {}
    uids = sorted({int(u) for u in user_ids if u is not None})
    weeks = sorted({w for w in week_starts if w is not None})
    if not uids or not weeks:
        return out
    cur = conn.cursor()
    ensure_payroll_week_ot_schema(cur)
    ph_u = ",".join(["%s"] * len(uids))
    ph_w = ",".join(["%s"] * len(weeks))
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT user_id, payroll_week_start, ot_mode
        FROM employee_payroll_week_ot_overrides
        WHERE organization_id=%s
          AND user_id IN ({ph_u})
          AND payroll_week_start IN ({ph_w})
        """,
        (int(organization_id), *uids, *weeks),
    )
    for row in c.fetchall() or []:
        ws = row.get("payroll_week_start")
        if hasattr(ws, "isoformat"):
            ws_s = ws.isoformat()
        else:
            ws_s = str(ws)[:10]
        try:
            mode = normalize_ot_week_mode(row.get("ot_mode"))
        except ValueError:
            mode = OT_MODE_DEFAULT
        out[(int(row["user_id"]), ws_s)] = mode
    return out


def _clear_week_session_approvals(
    conn,
    organization_id: int,
    user_id: int,
    week_start: date,
) -> int:
    """Clear payroll_hours_approved for this employee's sessions in the payroll week only."""
    from backend.payroll_operations import _date_end_exclusive_dt, _date_start_dt

    week_end = week_start + timedelta(days=6)
    chk = conn.cursor()
    if not table_has_column(chk, "shift_sessions", "payroll_hours_approved"):
        return 0
    has_ss_org = table_has_column(chk, "shift_sessions", "organization_id")
    c = conn.cursor()
    if has_ss_org:
        c.execute(
            """
            UPDATE shift_sessions
            SET payroll_hours_approved=0
            WHERE organization_id=%s
              AND user_id=%s
              AND payroll_hours_approved=1
              AND clock_in_at >= %s
              AND clock_in_at < %s
            """,
            (
                int(organization_id),
                int(user_id),
                _date_start_dt(week_start.isoformat()),
                _date_end_exclusive_dt(week_end.isoformat()),
            ),
        )
    else:
        c.execute(
            """
            UPDATE shift_sessions s
            JOIN users u ON u.id = s.user_id
            SET s.payroll_hours_approved=0
            WHERE u.organization_id=%s
              AND s.user_id=%s
              AND s.payroll_hours_approved=1
              AND s.clock_in_at >= %s
              AND s.clock_in_at < %s
            """,
            (
                int(organization_id),
                int(user_id),
                _date_start_dt(week_start.isoformat()),
                _date_end_exclusive_dt(week_end.isoformat()),
            ),
        )
    return int(c.rowcount or 0)


def set_employee_week_ot_override(
    conn,
    organization_id: int,
    user_id: int,
    payroll_week_start: date | str,
    *,
    ot_mode: Any,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """Set employee-week OT mode. Clears approvals for that week only when changed."""
    from backend.payroll_identity import payroll_week_bounds

    if isinstance(payroll_week_start, str):
        ws = date.fromisoformat(payroll_week_start[:10])
    else:
        ws = payroll_week_start
    # Normalize to org payroll week start for the given date.
    ws, _ = payroll_week_bounds(conn, ws, int(organization_id))
    new_mode = normalize_ot_week_mode(ot_mode)
    cur = conn.cursor()
    ensure_payroll_week_ot_schema(cur)
    old_mode = get_employee_week_ot_mode(conn, organization_id, user_id, ws)
    if old_mode == new_mode:
        return {
            "user_id": int(user_id),
            "payroll_week_start": ws.isoformat(),
            "ot_mode": new_mode,
            "approval_cleared_count": 0,
            "audit_appended": False,
        }

    now = datetime.utcnow()
    c = conn.cursor()
    if new_mode == OT_MODE_DEFAULT:
        c.execute(
            """
            DELETE FROM employee_payroll_week_ot_overrides
            WHERE organization_id=%s AND user_id=%s AND payroll_week_start=%s
            """,
            (int(organization_id), int(user_id), ws),
        )
    else:
        c.execute(
            """
            INSERT INTO employee_payroll_week_ot_overrides (
              organization_id, user_id, payroll_week_start, ot_mode, updated_at, updated_by
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              ot_mode=VALUES(ot_mode),
              updated_at=VALUES(updated_at),
              updated_by=VALUES(updated_by)
            """,
            (
                int(organization_id),
                int(user_id),
                ws,
                new_mode,
                now,
                int(actor_id) if actor_id is not None else None,
            ),
        )
    cleared = _clear_week_session_approvals(conn, organization_id, user_id, ws)
    reason_text = str(reason or "").strip()[:500] or None
    c.execute(
        """
        INSERT INTO employee_payroll_week_ot_override_audit (
          organization_id, user_id, payroll_week_start, actor_id, created_at,
          old_value, new_value, reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(user_id),
            ws,
            int(actor_id) if actor_id is not None else None,
            now,
            old_mode,
            new_mode,
            reason_text,
        ),
    )
    conn.commit()
    return {
        "user_id": int(user_id),
        "payroll_week_start": ws.isoformat(),
        "ot_mode": new_mode,
        "approval_cleared_count": cleared,
        "audit_appended": True,
    }


def write_line_ot_week_snapshot(conn, line_id: int, ot_mode: Optional[str]) -> None:
    cur = conn.cursor()
    ensure_payroll_week_ot_schema(cur)
    if not table_has_column(cur, "payout_batch_lines", "ot_week_override_snapshot"):
        return
    mode = normalize_ot_week_mode(ot_mode) if ot_mode else OT_MODE_DEFAULT
    cur.execute(
        "UPDATE payout_batch_lines SET ot_week_override_snapshot=%s WHERE id=%s",
        (mode if mode != OT_MODE_DEFAULT else None, int(line_id)),
    )
