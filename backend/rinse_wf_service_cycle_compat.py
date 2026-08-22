"""One-way compatibility projection: canonical WF cycles → legacy day_bags / Management."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.rinse_folding_et import naive_et_day_start
from backend.rinse_veewash_shift_day import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    ensure_shift_monitor_day_tables,
    get_day_record,
    persist_day_snapshot,
)
from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_REVIEW,
    ensure_wf_service_cycles_table,
    reporting_counts_for_date,
)

OUTCOME_CARRYOVER_QUERY = "opening_backlog_query_only"


def project_canonical_cycles_to_day_snapshot(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Write compatibility day_bags from canonical cycles for selected date D.

    Includes cycles:
      - admitted on D
      - completed on D
      - opening backlog (admitted before D, still ACTIVE/REVIEW at day start)
    """
    ensure_wf_service_cycles_table(cursor)
    ensure_shift_monitor_day_tables(cursor)
    org = int(organization_id)
    day_start = naive_et_day_start(shift_date_et)
    day_end = day_start + timedelta(days=1)

    cur = cursor
    cur.execute(
        """
        SELECT * FROM rinse_wf_service_cycles
        WHERE organization_id = %s
          AND (
            (admitted_at >= %s AND admitted_at < %s)
            OR (completed_at >= %s AND completed_at < %s)
            OR (
              admitted_at < %s
              AND status IN (%s, %s)
              AND (completed_at IS NULL OR completed_at >= %s)
            )
          )
        ORDER BY cycle_anchor_at ASC
        """,
        (
            org,
            day_start,
            day_end,
            day_start,
            day_end,
            day_start,
            STATUS_ACTIVE,
            STATUS_REVIEW,
            day_start,
        ),
    )
    cycles = [dict(r) for r in (cur.fetchall() or []) if isinstance(r, dict)]

    bags: list[dict[str, Any]] = []
    for c in cycles:
        bid = c.get("bag_id")
        if not bid:
            continue
        admitted_at = c.get("admitted_at")
        status = str(c.get("status") or STATUS_ACTIVE)
        if status == STATUS_COMPLETED:
            eff = OUTCOME_COMPLETED
        elif status == STATUS_REVIEW:
            eff = OUTCOME_REVIEW_REQUIRED
        else:
            eff = OUTCOME_PENDING

        new_or_carry = "new_today"
        if isinstance(admitted_at, datetime) and admitted_at < day_start:
            new_or_carry = OUTCOME_CARRYOVER_QUERY

        bags.append(
            {
                "bag_id": bid,
                "service_type": "WF",
                "rush_status": c.get("rush_status"),
                "new_or_carryover": new_or_carry,
                "pre_weight_lbs": c.get("pre_weight_lbs"),
                "post_weight_lbs": c.get("post_weight_lbs"),
                "canonical_completion_status": (
                    OUTCOME_COMPLETED if eff == OUTCOME_COMPLETED else eff
                ),
                "canonical_completion_timestamp": c.get("completed_at"),
                "effective_status": eff,
                "review_reason_codes": (
                    [c.get("review_reason")] if c.get("review_reason") else []
                ),
                "bag_snapshot": {
                    "cycle_id": c.get("id"),
                    "cycle_anchor_at": str(c.get("cycle_anchor_at")),
                    "admitted_at": str(admitted_at),
                    "completion_source": c.get("completion_source"),
                    "canonical_projection": True,
                },
            }
        )

    counts = reporting_counts_for_date(cursor, org, shift_date_et)
    summary = {
        "total_workload": len(bags),
        "active_workload": sum(1 for b in bags if b["effective_status"] == OUTCOME_PENDING),
        "completed": sum(1 for b in bags if b["effective_status"] == OUTCOME_COMPLETED),
        "pending": sum(1 for b in bags if b["effective_status"] == OUTCOME_PENDING),
        "exceptions": {"review_required": sum(1 for b in bags if b["effective_status"] == OUTCOME_REVIEW_REQUIRED)},
        "membership": {
            "admitted_on_date": counts.get("admitted_on_date"),
            "completed_on_date": counts.get("completed_on_date"),
            "opening_backlog_query": counts.get("opening_backlog"),
            "active_now": counts.get("active_now"),
            "canonical_source": True,
        },
    }
    workload = {
        "bags": bags,
        "new_today": [b["bag_id"] for b in bags if b.get("new_or_carryover") == "new_today"],
        "carryover": [b["bag_id"] for b in bags if b.get("new_or_carryover") == OUTCOME_CARRYOVER_QUERY],
        "membership": summary.get("membership"),
    }

    existing = get_day_record(cursor, org, shift_date_et)
    return persist_day_snapshot(
        cursor,
        org,
        shift_date_et,
        workload=workload,
        summary=summary,
        force=force,
        chronology_complete=True,
    )
