"""Immutable ET-day workload ledger.

The At Vendor / Today's Workload module recomputes its population from the live
portal board and scan evidence on every request. That makes the *total* volatile:
bags that leave the portal, get sent to Rinse, complete, or briefly disappear from
a stale scrape can drop out of the day's count.

This module persists an **immutable membership ledger** keyed by
``(organization_id, et_date, bag_id)``. Once a bag is recorded as part of an ET
day's workload it stays there forever. Only its ``current_status`` and
``membership_tier`` may be refined on later builds — rows are never deleted.

Rules enforced here:

* Membership is append-only. ``record_workload_membership`` never deletes a row.
* ``first_seen_at`` is preserved on the first insert and never overwritten.
* Status is re-derived on every build and may move between buckets, but a bag is
  never silently removed. Explicit rejection/cancellation moves it to the
  ``rejected`` bucket instead of dropping it.
* **Headline Today's Workload = Active Today** (new today + carry-over from
  yesterday + re-sends today). Historical backlog and excluded cleanup are visible
  separately and do not inflate the headline.

Status buckets (mutually exclusive within each membership tier):

    Total = Pending + Completed + Sent to Rinse + Needs Verification + Rejected
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable, Mapping

LEDGER_TABLE = "rinse_et_day_workload_ledger"

LEDGER_STATUS_PENDING = "pending"
LEDGER_STATUS_COMPLETED = "completed"
LEDGER_STATUS_SENT_TO_RINSE = "sent_to_rinse"
LEDGER_STATUS_NEEDS_VERIFICATION = "needs_verification"
LEDGER_STATUS_REJECTED = "rejected"

LEDGER_STATUS_ORDER = (
    LEDGER_STATUS_PENDING,
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_SENT_TO_RINSE,
    LEDGER_STATUS_NEEDS_VERIFICATION,
    LEDGER_STATUS_REJECTED,
)

# Reasons a bag was removed from the live rows by downstream filters. These map to
# ledger statuses so removed bags are retained as membership instead of dropped.
REMOVAL_REASON_REJECTED = "rejected"
REMOVAL_REASON_NEEDS_VERIFICATION = "needs_verification"

# Membership lineage — determines headline vs backlog vs excluded.
MEMBERSHIP_NEW_TODAY = "new_today"
MEMBERSHIP_CARRYOVER_YESTERDAY = "carryover_yesterday"
MEMBERSHIP_RESEND_TODAY = "resend_today"
MEMBERSHIP_HISTORICAL_BACKLOG = "historical_backlog"
MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY = "excluded_completed_before_day"
MEMBERSHIP_EXCLUDED_REJECTED = "excluded_rejected"

ACTIVE_MEMBERSHIP_TIERS = frozenset(
    {
        MEMBERSHIP_NEW_TODAY,
        MEMBERSHIP_CARRYOVER_YESTERDAY,
        MEMBERSHIP_RESEND_TODAY,
    }
)
HISTORICAL_MEMBERSHIP_TIERS = frozenset({MEMBERSHIP_HISTORICAL_BACKLOG})
EXCLUDED_MEMBERSHIP_TIERS = frozenset(
    {
        MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY,
        MEMBERSHIP_EXCLUDED_REJECTED,
    }
)


def ensure_workload_ledger_table(cursor) -> None:
    from backend.ta_helpers import table_has_column

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
            organization_id INT NOT NULL,
            et_date DATE NOT NULL,
            bag_id VARCHAR(64) NOT NULL,
            workflow VARCHAR(8) NULL,
            rush_bucket VARCHAR(16) NULL,
            membership_tier VARCHAR(48) NULL,
            current_status VARCHAR(32) NOT NULL,
            first_seen_at DATETIME(6) NULL,
            last_seen_at DATETIME(6) NULL,
            completed_at DATETIME(6) NULL,
            sent_to_rinse_at DATETIME(6) NULL,
            rejected_at DATETIME(6) NULL,
            rejection_reason VARCHAR(255) NULL,
            population_inclusion VARCHAR(128) NULL,
            source_batch_ids TEXT NULL,
            row_snapshot JSON NULL,
            created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            PRIMARY KEY (organization_id, et_date, bag_id),
            KEY idx_workload_ledger_org_date (organization_id, et_date),
            KEY idx_workload_ledger_status (organization_id, et_date, current_status),
            KEY idx_workload_ledger_tier (organization_id, et_date, membership_tier)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    if not table_has_column(cursor, LEDGER_TABLE, "membership_tier"):
        cursor.execute(
            f"ALTER TABLE {LEDGER_TABLE} ADD COLUMN membership_tier VARCHAR(48) NULL"
        )


# ---------------------------------------------------------------------------
# Pure helpers (no DB) — unit testable in isolation.
# ---------------------------------------------------------------------------


def _norm_bag_id(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_completed_row(row: Mapping[str, Any]) -> bool:
    from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, MOD_AT_VENDOR_COMPLETED

    if bool(row.get("completed_during_et_day")):
        return True
    if str(row.get("at_vendor_status") or "").strip().lower() == str(AV_STATUS_COMPLETED).lower():
        return True
    tags = row.get("module_tags") or []
    return MOD_AT_VENDOR_COMPLETED in tags


def _row_workflow(row: Mapping[str, Any]) -> str:
    svc = str(row.get("service_type") or row.get("service_bucket") or "").strip().upper()
    if svc in ("WF", "HD"):
        return svc
    if svc.startswith("WF"):
        return "WF"
    if svc.startswith("HD"):
        return "HD"
    return svc or ""


def _has_sent_to_rinse_evidence(row: Mapping[str, Any]) -> bool:
    """Positive evidence the bag was dispatched onward to Rinse (not merely absent).

    Being off the portal board is NOT sufficient — that is treated as Needs
    Verification. Sent to Rinse requires an explicit dispatch/departure signal.
    """
    status_text = " ".join(
        str(row.get(key) or "")
        for key in ("facility_status", "portal_status", "monitoring_bucket", "at_vendor_status")
    ).lower()
    if "sent-to-rinse" in status_text or "sent_to_rinse" in status_text:
        return True
    if ("rinse" in status_text or "vendor" in status_text) and (
        "sent" in status_text or "depart" in status_text or "dispatch" in status_text
    ):
        return True
    return bool(row.get("sent_to_rinse_at") or row.get("dispatched_to_rinse"))


def _is_off_portal(row: Mapping[str, Any]) -> bool:
    return row.get("currently_on_vendor_home") is False


def derive_ledger_status(
    row: Mapping[str, Any],
    *,
    removal_reason: str | None = None,
) -> str:
    """Map a built workload row (and any downstream-removal reason) to a ledger status.

    Mutually exclusive; the five statuses partition the immutable membership so the
    dashboard total always equals the sum of the buckets. Ordering matters:

    1. Completed  — a valid completion signal exists (highest precedence).
    2. Rejected   — explicit cancellation evidence only.
    3. Sent to Rinse — positive dispatch/departure evidence.
    4. Needs Verification — left the board / removed by a soft filter, unexplained.
    5. Pending    — still on the board, in process.
    """
    if _is_completed_row(row):
        return LEDGER_STATUS_COMPLETED
    if removal_reason == REMOVAL_REASON_REJECTED:
        return LEDGER_STATUS_REJECTED
    if _has_sent_to_rinse_evidence(row):
        return LEDGER_STATUS_SENT_TO_RINSE
    if removal_reason == REMOVAL_REASON_NEEDS_VERIFICATION or _is_off_portal(row):
        return LEDGER_STATUS_NEEDS_VERIFICATION
    return LEDGER_STATUS_PENDING


def _coerce_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


    return LEDGER_STATUS_PENDING


def _sent_to_vendor_timestamps(
    events: Iterable[Mapping[str, Any]],
) -> list[datetime]:
    from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid
    from backend.rinse_scan_purpose import is_sent_to_vendor_purpose

    out: list[datetime] = []
    for ev in gaming_events_from_records(events):
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            out.append(ts)
    return sorted(out)


def classify_bag_membership_tier(
    events: Iterable[Mapping[str, Any]],
    *,
    service_type: str,
    selected_date_et: date,
    explicit_rejected: bool = False,
) -> str:
    """Classify one bag's ET-day membership lineage from scan chronology.

    Mutually exclusive tiers used for headline vs backlog vs excluded breakout.
    """
    from datetime import timedelta

    from backend.rinse_at_vendor_module import (
        AV_STATUS_COMPLETED,
        _evaluate_bag_as_of,
    )
    from backend.rinse_folding_et import (
        naive_et_day_end_inclusive,
        naive_et_day_start,
    )

    if explicit_rejected:
        return MEMBERSHIP_EXCLUDED_REJECTED

    day_start = naive_et_day_start(selected_date_et)
    day_end_excl = naive_et_day_start(selected_date_et + timedelta(days=1))
    prior_day = selected_date_et - timedelta(days=1)
    prior_day_end = naive_et_day_end_inclusive(prior_day)

    sent = _sent_to_vendor_timestamps(events)
    sent_during = [t for t in sent if day_start <= t < day_end_excl]
    sent_before = [t for t in sent if t < day_start]
    last_sent_before = max(sent_before) if sent_before else None

    svc = str(service_type or "").strip().upper() or "WF"
    completed_before_day = False
    if last_sent_before is not None:
        st, _sig, comp_ts, _sent_ts, _ = _evaluate_bag_as_of(
            list(events),
            service_type=svc,
            as_of_end=prior_day_end,
            anchor_ts_override=last_sent_before,
        )
        if st == AV_STATUS_COMPLETED and comp_ts is not None:
            completed_before_day = True

    if completed_before_day and not sent_during:
        return MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY
    if sent_during and not sent_before:
        return MEMBERSHIP_NEW_TODAY
    if sent_during and sent_before:
        return MEMBERSHIP_RESEND_TODAY
    if last_sent_before is not None and last_sent_before.date() == prior_day:
        return MEMBERSHIP_CARRYOVER_YESTERDAY
    if last_sent_before is not None:
        return MEMBERSHIP_HISTORICAL_BACKLOG
    if not sent:
        # Portal-only presence without sent-to-vendor scan — treat as new today.
        return MEMBERSHIP_NEW_TODAY
    return MEMBERSHIP_HISTORICAL_BACKLOG


def is_active_membership_tier(tier: str | None) -> bool:
    return str(tier or "") in ACTIVE_MEMBERSHIP_TIERS


def build_membership_record(
    row: Mapping[str, Any],
    *,
    removal_reason: str | None = None,
    membership_tier: str | None = None,
) -> dict[str, Any]:
    """Produce a ledger snapshot record for a single built/removed row."""
    bid = _norm_bag_id(row.get("bag_id"))
    status = derive_ledger_status(row, removal_reason=removal_reason)
    tier = membership_tier or row.get("membership_tier")
    if removal_reason == REMOVAL_REASON_REJECTED:
        tier = MEMBERSHIP_EXCLUDED_REJECTED
    completed_at = None
    if status == LEDGER_STATUS_COMPLETED:
        completed_at = row.get("completion_timestamp") or row.get("completed_at")
    source_batches = row.get("source_batch_ids") or row.get("source_batch_id")
    if isinstance(source_batches, str):
        source_batches = [source_batches] if source_batches.strip() else []
    return {
        "bag_id": bid,
        "workflow": _row_workflow(row),
        "rush_bucket": str(row.get("rush_bucket") or "") or None,
        "membership_tier": tier,
        "current_status": status,
        "completed_at": completed_at,
        "rejection_reason": (
            row.get("rejection_reason")
            if status == LEDGER_STATUS_REJECTED
            else None
        ),
        "population_inclusion": row.get("population_inclusion")
        or row.get("inclusion_reason"),
        "source_batch_ids": list(source_batches) if source_batches else [],
        "row_snapshot": dict(row),
    }


def build_membership_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    removed: Mapping[str, str] | None = None,
    removed_rows: Mapping[str, Mapping[str, Any]] | None = None,
    membership_tiers: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build ledger records for surviving rows plus downstream-removed rows.

    ``removed`` maps bag_id -> removal reason. ``removed_rows`` optionally supplies
    the original built row for removed bags so we retain a full snapshot.
    """
    removed = {(_norm_bag_id(k)): v for k, v in (removed or {}).items()}
    removed_rows = {(_norm_bag_id(k)): v for k, v in (removed_rows or {}).items()}
    tiers = {(_norm_bag_id(k)): v for k, v in (membership_tiers or {}).items()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        bid = _norm_bag_id(row.get("bag_id"))
        if not bid or bid in seen:
            continue
        seen.add(bid)
        out.append(
            build_membership_record(
                row,
                membership_tier=tiers.get(bid) or row.get("membership_tier"),
            )
        )
    for bid, reason in removed.items():
        if not bid or bid in seen:
            continue
        seen.add(bid)
        base = dict(removed_rows.get(bid) or {"bag_id": bid})
        base.setdefault("bag_id", bid)
        out.append(
            build_membership_record(
                base,
                removal_reason=reason,
                membership_tier=tiers.get(bid) or base.get("membership_tier"),
            )
        )
    return out


def reconcile_ledger_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute status buckets and verify immutable_total == sum(buckets)."""
    buckets = {status: 0 for status in LEDGER_STATUS_ORDER}
    total = 0
    for rec in records:
        total += 1
        status = str(rec.get("current_status") or LEDGER_STATUS_PENDING)
        if status not in buckets:
            buckets[status] = 0
        buckets[status] += 1
    bucket_sum = sum(buckets.values())
    return {
        "immutable_total": total,
        "pending": buckets.get(LEDGER_STATUS_PENDING, 0),
        "completed": buckets.get(LEDGER_STATUS_COMPLETED, 0),
        "sent_to_rinse": buckets.get(LEDGER_STATUS_SENT_TO_RINSE, 0),
        "needs_verification": buckets.get(LEDGER_STATUS_NEEDS_VERIFICATION, 0),
        "rejected": buckets.get(LEDGER_STATUS_REJECTED, 0),
        "bucket_sum": bucket_sum,
        "reconciles": bucket_sum == total,
    }


def reconcile_active_ledger_breakout(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute Active Today headline, historical backlog, excluded cleanup, and proofs."""
    recs = list(records)
    status = reconcile_ledger_records(recs)

    def _tier_count(tier: str) -> int:
        return sum(1 for r in recs if str(r.get("membership_tier") or "") == tier)

    def _tier_ids(tier: str) -> list[str]:
        return sorted(str(r.get("bag_id")) for r in recs if str(r.get("membership_tier") or "") == tier)

    def _tier_status_count(tier: str, st: str) -> int:
        return sum(
            1
            for r in recs
            if str(r.get("membership_tier") or "") == tier
            and str(r.get("current_status") or "") == st
        )

    new_today = _tier_count(MEMBERSHIP_NEW_TODAY)
    carryover_yesterday = _tier_count(MEMBERSHIP_CARRYOVER_YESTERDAY)
    resends_today = _tier_count(MEMBERSHIP_RESEND_TODAY)
    active_today_total = new_today + carryover_yesterday + resends_today

    historical_backlog_total = _tier_count(MEMBERSHIP_HISTORICAL_BACKLOG)
    historical_needs_verification = _tier_status_count(
        MEMBERSHIP_HISTORICAL_BACKLOG, LEDGER_STATUS_NEEDS_VERIFICATION
    )

    excluded_completed_before_day = _tier_count(MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY)
    excluded_rejected = _tier_count(MEMBERSHIP_EXCLUDED_REJECTED)
    excluded_total = excluded_completed_before_day + excluded_rejected

    ledger_total = len(recs)
    ledger_segment_sum = active_today_total + historical_backlog_total + excluded_total

    active_records = [
        r for r in recs if is_active_membership_tier(str(r.get("membership_tier") or ""))
    ]
    active_status = reconcile_ledger_records(active_records)

    return {
        **status,
        "active_today_total": active_today_total,
        "new_today": new_today,
        "carryover_yesterday": carryover_yesterday,
        "resends_today": resends_today,
        "active_today_reconciles": active_today_total
        == (new_today + carryover_yesterday + resends_today),
        "new_today_bag_ids": _tier_ids(MEMBERSHIP_NEW_TODAY),
        "carryover_yesterday_bag_ids": _tier_ids(MEMBERSHIP_CARRYOVER_YESTERDAY),
        "resends_today_bag_ids": _tier_ids(MEMBERSHIP_RESEND_TODAY),
        "historical_backlog_total": historical_backlog_total,
        "historical_backlog_needs_verification": historical_needs_verification,
        "historical_backlog_bag_ids": _tier_ids(MEMBERSHIP_HISTORICAL_BACKLOG),
        "excluded_completed_before_day": excluded_completed_before_day,
        "excluded_rejected": excluded_rejected,
        "excluded_total": excluded_total,
        "excluded_completed_before_day_bag_ids": _tier_ids(
            MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY
        ),
        "excluded_rejected_bag_ids": _tier_ids(MEMBERSHIP_EXCLUDED_REJECTED),
        "ledger_total": ledger_total,
        "ledger_total_reconciles": ledger_segment_sum == ledger_total,
        "active_pending": active_status["pending"],
        "active_completed": active_status["completed"],
        "active_sent_to_rinse": active_status["sent_to_rinse"],
        "active_needs_verification": active_status["needs_verification"],
        "active_rejected": active_status["rejected"],
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


_INSERT_SQL = f"""
    INSERT INTO {LEDGER_TABLE}
        (organization_id, et_date, bag_id, workflow, rush_bucket, membership_tier,
         current_status, first_seen_at, last_seen_at, completed_at,
         sent_to_rinse_at, rejected_at, rejection_reason,
         population_inclusion, source_batch_ids, row_snapshot,
         created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        workflow = COALESCE(VALUES(workflow), workflow),
        rush_bucket = COALESCE(VALUES(rush_bucket), rush_bucket),
        membership_tier = VALUES(membership_tier),
        current_status = VALUES(current_status),
        last_seen_at = VALUES(last_seen_at),
        completed_at = COALESCE({LEDGER_TABLE}.completed_at, VALUES(completed_at)),
        sent_to_rinse_at = COALESCE({LEDGER_TABLE}.sent_to_rinse_at, VALUES(sent_to_rinse_at)),
        rejected_at = CASE
            WHEN VALUES(current_status) = '{LEDGER_STATUS_REJECTED}'
            THEN COALESCE({LEDGER_TABLE}.rejected_at, VALUES(rejected_at))
            ELSE NULL END,
        rejection_reason = VALUES(rejection_reason),
        population_inclusion = COALESCE(VALUES(population_inclusion), {LEDGER_TABLE}.population_inclusion),
        source_batch_ids = COALESCE(VALUES(source_batch_ids), {LEDGER_TABLE}.source_batch_ids),
        row_snapshot = COALESCE(VALUES(row_snapshot), {LEDGER_TABLE}.row_snapshot),
        updated_at = VALUES(updated_at)
"""


def _membership_params(rec: Mapping[str, Any], org: int, et_date: date, now: datetime):
    bid = _norm_bag_id(rec.get("bag_id"))
    if not bid:
        return None
    status = str(rec.get("current_status") or LEDGER_STATUS_PENDING)
    completed_at = _coerce_dt(rec.get("completed_at"))
    rejected_at = now if status == LEDGER_STATUS_REJECTED else None
    sent_to_rinse_at = now if status == LEDGER_STATUS_SENT_TO_RINSE else None
    snapshot = rec.get("row_snapshot")
    snapshot_json = json.dumps(_json_safe(snapshot)) if snapshot is not None else None
    source_batches = rec.get("source_batch_ids") or []
    source_json = json.dumps(list(source_batches)) if source_batches else None
    return (
        org,
        et_date,
        bid,
        rec.get("workflow") or None,
        rec.get("rush_bucket") or None,
        rec.get("membership_tier") or None,
        status,
        now,
        now,
        completed_at,
        sent_to_rinse_at,
        rejected_at,
        rec.get("rejection_reason"),
        rec.get("population_inclusion"),
        source_json,
        snapshot_json,
        now,
        now,
    )


def record_workload_membership(
    cursor,
    organization_id: int,
    et_date: date,
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Upsert membership records. Append-only: never deletes existing membership.

    * ``first_seen_at`` preserved on conflict.
    * ``current_status`` and ``last_seen_at`` refreshed.
    * Status transition timestamps (``completed_at``/``rejected_at``) set once.
    """
    ensure_workload_ledger_table(cursor)
    now = now or datetime.utcnow()
    org = int(organization_id)
    params = [
        p
        for p in (_membership_params(rec, org, et_date, now) for rec in records)
        if p is not None
    ]
    if not params:
        return {"written": 0}
    if hasattr(cursor, "executemany"):
        cursor.executemany(_INSERT_SQL, params)
    else:  # pragma: no cover - defensive
        for p in params:
            cursor.execute(_INSERT_SQL, p)
    return {"written": len(params)}


def persist_workload_membership_isolated(
    organization_id: int,
    et_date: date,
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> bool:
    """Persist membership on a dedicated connection so the caller's request
    transaction is never committed or rolled back as a side effect. Returns True
    when the write committed."""
    from backend.db import get_db

    records = list(records)
    if not records:
        return False
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            record_workload_membership(cur, organization_id, et_date, records, now=now)
            conn.commit()
            return True
        finally:
            cur.close()
    finally:
        conn.close()


def load_workload_ledger(
    cursor,
    organization_id: int,
    et_date: date,
) -> dict[str, dict[str, Any]]:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, LEDGER_TABLE):
        return {}
    org = int(organization_id)
    cursor.execute(
        f"""
        SELECT organization_id, et_date, bag_id, workflow, rush_bucket, membership_tier,
               current_status, first_seen_at, last_seen_at, completed_at,
               sent_to_rinse_at, rejected_at, rejection_reason,
               population_inclusion, source_batch_ids, row_snapshot
        FROM {LEDGER_TABLE}
        WHERE organization_id = %s AND et_date = %s
        """,
        (org, et_date),
    )
    out: dict[str, dict[str, Any]] = {}
    for raw in cursor.fetchall() or []:
        if not isinstance(raw, Mapping):
            continue
        bid = _norm_bag_id(raw.get("bag_id"))
        if not bid:
            continue
        rec = dict(raw)
        snapshot = rec.get("row_snapshot")
        if isinstance(snapshot, str) and snapshot.strip():
            try:
                rec["row_snapshot"] = json.loads(snapshot)
            except json.JSONDecodeError:
                rec["row_snapshot"] = None
        batches = rec.get("source_batch_ids")
        if isinstance(batches, str) and batches.strip():
            try:
                rec["source_batch_ids"] = json.loads(batches)
            except json.JSONDecodeError:
                rec["source_batch_ids"] = []
        out[bid] = rec
    return out


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
