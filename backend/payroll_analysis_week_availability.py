"""Manual Payroll Analysis week availability.

Week visibility in Analysis is controlled by an explicit manager flag keyed by
(organization_id, pay_period_start, pay_period_end). It does not change batch
statuses, approvals, payments, or payout lines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.ta_helpers import table_exists


def ensure_payroll_analysis_week_availability_schema(cursor) -> None:
    """Additive / idempotent. No historical payroll-row mutation."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_analysis_week_availability (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          pay_period_start DATE NOT NULL,
          pay_period_end DATE NOT NULL,
          analysis_available TINYINT(1) NOT NULL DEFAULT 0,
          analysis_available_at DATETIME NULL,
          analysis_available_by INT NULL,
          updated_at DATETIME NOT NULL,
          UNIQUE KEY uq_analysis_week (organization_id, pay_period_start, pay_period_end),
          KEY idx_analysis_week_org_avail (organization_id, analysis_available)
        )
        """
    )


def _norm_ymd(val: Any) -> str:
    s = str(val or "")[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s
    return s


def is_week_available_for_analysis(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
) -> bool:
    cur = conn.cursor()
    ensure_payroll_analysis_week_availability_schema(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT analysis_available
        FROM payroll_analysis_week_availability
        WHERE organization_id=%s
          AND pay_period_start=%s
          AND pay_period_end=%s
        LIMIT 1
        """,
        (
            int(organization_id),
            _norm_ymd(pay_period_start),
            _norm_ymd(pay_period_end),
        ),
    )
    row = c.fetchone()
    return bool(row and int(row.get("analysis_available") or 0) == 1)


def get_week_analysis_availability(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
) -> dict[str, Any]:
    cur = conn.cursor()
    ensure_payroll_analysis_week_availability_schema(cur)
    ps = _norm_ymd(pay_period_start)
    pe = _norm_ymd(pay_period_end)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT analysis_available, analysis_available_at, analysis_available_by
        FROM payroll_analysis_week_availability
        WHERE organization_id=%s
          AND pay_period_start=%s
          AND pay_period_end=%s
        LIMIT 1
        """,
        (int(organization_id), ps, pe),
    )
    row = c.fetchone() or {}
    available = bool(row and int(row.get("analysis_available") or 0) == 1)
    return {
        "pay_period_start": ps,
        "pay_period_end": pe,
        "analysis_available": available,
        "analysis_available_at": row.get("analysis_available_at"),
        "analysis_available_by": row.get("analysis_available_by"),
    }


def set_week_analysis_availability(
    conn,
    organization_id: int,
    pay_period_start: str,
    pay_period_end: str,
    *,
    available: bool,
    actor_id: Optional[int] = None,
) -> dict[str, Any]:
    """Flip week visibility for Analysis only. Never mutates payout batches."""
    cur = conn.cursor()
    ensure_payroll_analysis_week_availability_schema(cur)
    ps = _norm_ymd(pay_period_start)
    pe = _norm_ymd(pay_period_end)
    if not ps or not pe:
        raise ValueError("pay_period_start and pay_period_end are required")
    # Require the week to exist as at least one payout batch (manager context).
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT COUNT(*) AS c FROM payout_batches
        WHERE organization_id=%s
          AND pay_period_start=%s
          AND pay_period_end=%s
        """,
        (int(organization_id), ps, pe),
    )
    if int((c.fetchone() or {}).get("c") or 0) <= 0:
        raise ValueError("No payout batches found for that payroll week")

    now = datetime.utcnow()
    flag = 1 if available else 0
    available_at = now if available else None
    available_by = int(actor_id) if available and actor_id is not None else None
    c.execute(
        """
        INSERT INTO payroll_analysis_week_availability (
          organization_id, pay_period_start, pay_period_end,
          analysis_available, analysis_available_at, analysis_available_by, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          analysis_available=VALUES(analysis_available),
          analysis_available_at=VALUES(analysis_available_at),
          analysis_available_by=VALUES(analysis_available_by),
          updated_at=VALUES(updated_at)
        """,
        (
            int(organization_id),
            ps,
            pe,
            flag,
            available_at,
            available_by,
            now,
        ),
    )
    conn.commit()
    return get_week_analysis_availability(conn, organization_id, ps, pe)


def list_available_analysis_weeks_asc(
    conn,
    organization_id: int,
) -> list[tuple[str, str]]:
    cur = conn.cursor()
    ensure_payroll_analysis_week_availability_schema(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pay_period_start, pay_period_end
        FROM payroll_analysis_week_availability
        WHERE organization_id=%s
          AND analysis_available=1
        ORDER BY pay_period_start ASC, pay_period_end ASC
        """,
        (int(organization_id),),
    )
    out = []
    for r in c.fetchall() or []:
        ps = _norm_ymd(r.get("pay_period_start"))
        pe = _norm_ymd(r.get("pay_period_end"))
        if ps and pe:
            out.append((ps, pe))
    return out


def periods_currently_terminal_complete(
    conn,
    organization_id: int,
) -> list[tuple[str, str]]:
    """Periods that today's automatic terminal-gate would list (migration seed set)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pay_period_start, pay_period_end
        FROM payout_batches
        WHERE organization_id = %s
          AND pay_period_start IS NOT NULL
          AND pay_period_end IS NOT NULL
        GROUP BY pay_period_start, pay_period_end
        HAVING COUNT(*) > 0
           AND SUM(
                 CASE
                   WHEN LOWER(COALESCE(status, '')) IN ('paid', 'closed')
                     OR payout_details_finalized_at IS NOT NULL
                   THEN 0
                   ELSE 1
                 END
               ) = 0
        ORDER BY pay_period_start ASC, pay_period_end ASC
        """,
        (int(organization_id),),
    )
    out = []
    for r in c.fetchall() or []:
        ps = _norm_ymd(r.get("pay_period_start"))
        pe = _norm_ymd(r.get("pay_period_end"))
        if ps and pe:
            out.append((ps, pe))
    return out


def seed_terminal_periods_as_analysis_available(
    conn,
    organization_id: int,
    *,
    actor_id: Optional[int] = None,
) -> dict[str, Any]:
    """One-time migration helper: mark currently terminal weeks available.

    Does not invent weeks. Does not touch incomplete weeks (e.g. Sep 7–13 with
    an open supplemental batch). Idempotent — already-available rows stay set.
    """
    cur = conn.cursor()
    ensure_payroll_analysis_week_availability_schema(cur)
    periods = periods_currently_terminal_complete(conn, organization_id)
    now = datetime.utcnow()
    inserted = 0
    skipped = 0
    c = conn.cursor(dictionary=True)
    for ps, pe in periods:
        c.execute(
            """
            SELECT analysis_available FROM payroll_analysis_week_availability
            WHERE organization_id=%s AND pay_period_start=%s AND pay_period_end=%s
            LIMIT 1
            """,
            (int(organization_id), ps, pe),
        )
        existing = c.fetchone()
        if existing and int(existing.get("analysis_available") or 0) == 1:
            skipped += 1
            continue
        c.execute(
            """
            INSERT INTO payroll_analysis_week_availability (
              organization_id, pay_period_start, pay_period_end,
              analysis_available, analysis_available_at, analysis_available_by, updated_at
            ) VALUES (%s,%s,%s,1,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              analysis_available=1,
              analysis_available_at=COALESCE(analysis_available_at, VALUES(analysis_available_at)),
              analysis_available_by=COALESCE(analysis_available_by, VALUES(analysis_available_by)),
              updated_at=VALUES(updated_at)
            """,
            (
                int(organization_id),
                ps,
                pe,
                now,
                int(actor_id) if actor_id is not None else None,
                now,
            ),
        )
        inserted += 1
    conn.commit()
    return {
        "organization_id": int(organization_id),
        "seeded": inserted,
        "already_available": skipped,
        "periods": [{"pay_period_start": ps, "pay_period_end": pe} for ps, pe in periods],
    }
