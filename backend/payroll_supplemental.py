"""Employee-specific supplemental payout batches.

A supplemental batch pays approved time that is not already on another payout
batch. It keeps the original payroll week, category, rates, and overtime
allocation. It is created as a draft and is never marked paid here.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.payroll_period_coverage import _parse_session_ids
from backend.payroll_worker_categories import (
    WORKER_CATEGORIES,
    batch_send_to_accountant_enabled,
    default_send_to_accountant_for_category,
)

_CATEGORY_PREFIX = {
    "temp": "TEMP",
    "w2": "W2",
    "contractor_1099": "1099",
    "tryout": "TRYOUT",
}


def attached_session_ids(
    conn,
    organization_id: int,
    *,
    except_batch_id: Optional[int] = None,
) -> set[int]:
    """Session ids on lines of other live payout batches.

    Joining to ``payout_batches`` ignores orphan lines whose batch is gone.
    The current batch is excluded so a refresh can reclaim its own sessions.
    """
    c = conn.cursor(dictionary=True)
    q = """
        SELECT pbl.source_shift_session_ids
        FROM payout_batch_lines pbl
        INNER JOIN payout_batches pb
          ON pb.id = pbl.batch_id AND pb.organization_id = pbl.organization_id
        WHERE pb.organization_id = %s
          AND pbl.source_shift_session_ids IS NOT NULL
    """
    params: list[Any] = [int(organization_id)]
    if except_batch_id is not None:
        q += " AND pb.id <> %s"
        params.append(int(except_batch_id))
    c.execute(q, params)
    rows = c.fetchall()
    if not isinstance(rows, (list, tuple)):
        return set()
    found: set[int] = set()
    for row in rows:
        found |= _parse_session_ids(row.get("source_shift_session_ids"))
    return found


def _clock_signature(user_id, approved, ot, rate, session_ids) -> tuple:
    return (
        int(user_id),
        round(float(approved or 0), 2),
        round(float(ot or 0), 2),
        round(float(rate or 0), 2),
        tuple(sorted(int(sid) for sid in session_ids)),
    )


def eligibility_conflict(expected: list[dict], stored_lines: list[dict]) -> Optional[str]:
    """Return a message when stored clock lines no longer match current eligibility."""
    expected_sigs = sorted(
        _clock_signature(
            row.get("user_id"),
            row.get("approved_hours"),
            row.get("ot_hours"),
            row.get("rate"),
            row.get("session_ids") or [],
        )
        for row in expected
    )
    stored_sigs = []
    for line in stored_lines or []:
        if str(line.get("source_type") or "clock_records") != "clock_records":
            continue
        ids = _parse_session_ids(line.get("source_shift_session_ids"))
        if not ids and line.get("source_type") not in (None, "", "clock_records"):
            continue
        stored_sigs.append(
            _clock_signature(
                line.get("user_id"),
                line.get("approved_hours"),
                line.get("ot_hours"),
                line.get("rate"),
                ids,
            )
        )
    stored_sigs.sort()
    if expected_sigs == stored_sigs:
        return None
    return (
        "Supplemental payout no longer matches approved unpaid time. "
        "Refresh this draft before finalizing. Paid batches were not changed."
    )


def validate_batch_sessions_for_finalize(conn, organization_id: int, batch: dict) -> None:
    """Refuse finalize when sessions are duplicated or a supplemental is stale.

    Does not update amounts, time records, or any other batch.
    """
    if batch.get("id") is None:
        return
    batch_id = int(batch["id"])
    lines = batch.get("lines") or []
    own: set[int] = set()
    for line in lines:
        ids = _parse_session_ids(line.get("source_shift_session_ids"))
        overlap = own & ids
        if overlap:
            raise ValueError(
                "This payout lists the same time record more than once: "
                + ", ".join(str(sid) for sid in sorted(overlap))
            )
        own |= ids
    others = attached_session_ids(conn, organization_id, except_batch_id=batch_id)
    duplicated = own & others
    if duplicated:
        raise ValueError(
            "These time records are already on another payout batch and cannot be paid again: "
            + ", ".join(str(sid) for sid in sorted(duplicated))
        )
    if batch.get("supplemental_for_user_id") in (None, "", 0, "0"):
        return
    from backend.payroll_operations import _planned_clock_payloads, list_time_records

    records = list_time_records(
        conn,
        organization_id,
        from_date=str(batch.get("pay_period_start") or "")[:10],
        to_date=str(batch.get("pay_period_end") or "")[:10],
        status_filter="approved",
    )
    expected = _planned_clock_payloads(
        conn,
        organization_id,
        batch,
        records,
        omit_session_ids=others,
    )
    conflict = eligibility_conflict(expected, lines)
    if conflict:
        raise ValueError(conflict)


def _require_supplemental_columns(cursor) -> None:
    """Refuse a supplemental payout until the explicit migration has been applied."""
    from backend.ta_helpers import table_has_column

    missing = [
        col
        for col in ("supplemental_for_user_id", "supplemental_reason")
        if not table_has_column(cursor, "payout_batches", col)
    ]
    if missing:
        raise ValueError(
            "Supplemental payout columns are not installed. "
            "Run backend/sql/payout_batch_supplemental_v1.sql before creating a supplemental payout."
        )


def create_supplemental_payout_batch(
    conn, organization_id: int, body: dict, *, created_by: Optional[int] = None
) -> dict:
    """Create a draft supplemental payout for one employee and one payroll week.

    Eligibility is calculated at creation. A repeated request that finds the
    same sessions already attached does not leave an empty batch behind.
    """
    from backend.payroll_operations import (
        build_batch_from_time_records,
        delete_payout_batch,
        ensure_payout_batches_tables,
    )

    ensure_payout_batches_tables(conn.cursor())
    _require_supplemental_columns(conn.cursor())
    try:
        user_id = int(body.get("supplemental_for_user_id"))
    except (TypeError, ValueError):
        raise ValueError("Select the employee for this supplemental payout")
    if user_id <= 0:
        raise ValueError("Select the employee for this supplemental payout")
    cat = str(body.get("worker_category") or "").strip()
    if cat not in WORKER_CATEGORIES:
        raise ValueError("worker_category must be w2, contractor_1099, temp, or tryout")
    start = str(body.get("pay_period_start") or "").strip()[:10]
    end = str(body.get("pay_period_end") or "").strip()[:10]
    if not start or not end:
        raise ValueError("A supplemental payout needs the original payroll week")
    freq = str(body.get("payout_frequency") or "weekly").strip()
    if freq not in ("weekly", "biweekly"):
        freq = "weekly"
    reason = str(body.get("supplemental_reason") or body.get("notes") or "").strip()
    name = str(body.get("batch_name") or "").strip()
    if not name or "SUPP" not in name.upper():
        name = f"{_CATEGORY_PREFIX.get(cat, cat.upper())}-SUPP-{start}-U{user_id}"
    if "send_to_accountant" in body and body.get("send_to_accountant") is not None:
        send_flag = (
            1
            if batch_send_to_accountant_enabled(
                {"send_to_accountant": body.get("send_to_accountant"), "worker_category": cat}
            )
            else 0
        )
    else:
        send_flag = 1 if default_send_to_accountant_for_category(cat) else 0
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO payout_batches (
          organization_id, batch_name, worker_category, pay_period_start, pay_period_end,
          payout_frequency, status, notes, send_to_accountant, created_by,
          supplemental_for_user_id, supplemental_reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            name[:255],
            cat,
            start,
            end,
            freq,
            "draft",
            reason or None,
            send_flag,
            created_by,
            user_id,
            reason[:500] or None,
        ),
    )
    batch_id = int(c.lastrowid)
    try:
        result = build_batch_from_time_records(
            conn,
            organization_id,
            batch_id,
            from_date=start,
            to_date=end,
            allow_empty=False,
        )
    except ValueError as exc:
        delete_payout_batch(conn, organization_id, batch_id)
        text = str(exc)
        if "No approved" in text or "not included again" in text:
            raise ValueError(
                "No approved time records for this employee are available for a supplemental payout. "
                "Hours already on another payout batch are not included again."
            ) from exc
        raise
    if created_by:
        from backend.ta_routes import write_audit

        session_ids = []
        for line in result.get("lines") or []:
            session_ids.extend(sorted(_parse_session_ids(line.get("source_shift_session_ids"))))
        write_audit(
            conn,
            int(created_by),
            "payout_batch",
            batch_id,
            "supplemental_batch_created",
            new={
                "batch_id": batch_id,
                "batch_name": result.get("batch_name") or name,
                "user_id": user_id,
                "worker_category": cat,
                "pay_period_start": start,
                "pay_period_end": end,
                "session_ids": session_ids,
                "status": "draft",
                "reason": reason,
            },
            remarks=reason or "Supplemental payout created as draft",
            organization_id=int(organization_id),
        )
        conn.commit()
    return result
