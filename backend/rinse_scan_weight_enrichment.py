"""
Portal weight enrichment: preserve/restore + latest-eligible attach.

Rinse "Events CSV" never carries a Weight column. The portal's weight_num
value arrives later (batch confirm, off-portal refresh, manual correction)
and must be attached onto the correct weight-entry scan row — the
chronologically *latest* eligible weight-entry event that is still missing a
weight, not necessarily "the first" or "the only" one.

Timeline rebuilds (delete-then-reinsert of a bag's scan history from a fresh
portal export) must never erase weight enrichment that was already attached
to a scan row. ``snapshot_weight_enrichment`` / ``restore_weight_enrichment``
bracket any such delete+reinsert so enrichment survives.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
from backend.ta_helpers import table_has_column

OUTCOME_RECOVERED = "RECOVERED_FROM_HISTORICAL_PORTAL_OBSERVATION"
OUTCOME_CURRENT_LATEST = "CURRENT_WEIGHT_ATTACHED_TO_LATEST_EVENT"
OUTCOME_PRE_NOT_RECOVERABLE = "PRE_WEIGHT_NOT_RECOVERABLE"
OUTCOME_MANAGER_REQUIRED = "MANAGER_CORRECTION_REQUIRED"

WEIGHT_SOURCE_PORTAL_CURRENT = "portal_weight_num"
WEIGHT_SOURCE_PORTAL_HISTORICAL = "portal_weight_num_historical"
REASON_LATEST_ELIGIBLE = "latest_eligible_at_portal_observation"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def ensure_scan_weight_enrichment_columns(cursor) -> None:
    """weight_lbs already exists via ensure_scan_events_weight_lbs_column; add provenance cols."""
    from backend.rinse_workload_bag_weight import ensure_scan_events_weight_lbs_column

    ensure_scan_events_weight_lbs_column(cursor)

    for col, ddl in (
        ("weight_observed_at", "DATETIME NULL"),
        ("weight_source", "VARCHAR(64) NULL"),
        ("weight_attach_batch_id", "BIGINT NULL"),
        ("weight_attach_reason", "VARCHAR(128) NULL"),
    ):
        if table_has_column(cursor, "rinse_bag_scan_events", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE rinse_bag_scan_events ADD COLUMN {col} {ddl}")
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            if errno != 1060 and "Duplicate column" not in str(exc):
                raise
        from backend.ta_helpers import _column_cache, _schema_lock

        with _schema_lock:
            _column_cache[("rinse_bag_scan_events", col)] = True


# ---------------------------------------------------------------------------
# Preserve / restore (survive timeline delete+reinsert)
# ---------------------------------------------------------------------------


def snapshot_weight_enrichment(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Capture enriched (weight_lbs IS NOT NULL) scan rows before a full timeline replace.

    Keyed by (bag_id, dedupe_key) so restore can re-attach onto the corresponding
    freshly re-inserted row even though its DB id changed.
    """
    ensure_scan_weight_enrichment_columns(cursor)
    org = int(organization_id)
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not ids or not hasattr(cursor, "execute"):
        return out

    chunk = 200
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        ph = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, dedupe_key, weight_lbs, weight_observed_at,
                   weight_source, weight_attach_batch_id, weight_attach_reason
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({ph})
              AND weight_lbs IS NOT NULL
              AND dedupe_key IS NOT NULL
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, Mapping):
                continue
            bag_id = normalize_bag_id(row.get("bag_id"))
            dedupe_key = row.get("dedupe_key")
            if not bag_id or not dedupe_key:
                continue
            out[(bag_id, str(dedupe_key))] = {
                "weight_lbs": row.get("weight_lbs"),
                "weight_observed_at": row.get("weight_observed_at"),
                "weight_source": row.get("weight_source"),
                "weight_attach_batch_id": row.get("weight_attach_batch_id"),
                "weight_attach_reason": row.get("weight_attach_reason"),
            }
    return out


def restore_weight_enrichment(
    cursor,
    organization_id: int,
    preserved: Mapping[tuple[str, str], Mapping[str, Any]],
) -> int:
    """
    Re-apply preserved enrichment after a delete+reinsert.

    Never overwrites a populated weight_lbs — COALESCE plus an explicit
    ``weight_lbs IS NULL`` guard on every column.
    """
    if not preserved:
        return 0
    ensure_scan_weight_enrichment_columns(cursor)
    org = int(organization_id)
    updated = 0
    for (bag_id, dedupe_key), values in preserved.items():
        if not bag_id or not dedupe_key:
            continue
        cursor.execute(
            """
            UPDATE rinse_bag_scan_events
            SET
                weight_lbs = COALESCE(weight_lbs, %s),
                weight_observed_at = COALESCE(weight_observed_at, %s),
                weight_source = COALESCE(NULLIF(weight_source, ''), %s),
                weight_attach_batch_id = COALESCE(weight_attach_batch_id, %s),
                weight_attach_reason = COALESCE(NULLIF(weight_attach_reason, ''), %s),
                updated_at = NOW()
            WHERE organization_id = %s AND bag_id = %s AND dedupe_key = %s
              AND weight_lbs IS NULL
            """,
            (
                values.get("weight_lbs"),
                values.get("weight_observed_at"),
                values.get("weight_source"),
                values.get("weight_attach_batch_id"),
                values.get("weight_attach_reason"),
                org,
                bag_id,
                dedupe_key,
            ),
        )
        updated += int(getattr(cursor, "rowcount", 0) or 0)
    return updated


# ---------------------------------------------------------------------------
# Attach: latest eligible null weight-entry
# ---------------------------------------------------------------------------


def _coerce_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _event_ts(ev: Mapping[str, Any]) -> datetime | None:
    return _coerce_dt(ev.get("scanned_at_parsed") or ev.get("scanned_at"))


def _weight_entry_events_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    events: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Chronologically ordered weight-entry events for a bag (asc)."""
    if events is None:
        from backend.rinse_post_processing_weight_chronology import _load_scan_events_for_bags

        events = _load_scan_events_for_bags(cursor, organization_id, [bag_id])

    out: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, Mapping):
            continue
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        out.append(dict(ev))
    out.sort(key=lambda e: (_event_ts(e) or datetime.min, e.get("id") or 0))
    return out


def attach_portal_weight_to_latest_eligible(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    weight_lbs: float,
    portal_observed_at: datetime | None = None,
    upload_batch_id: int | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """
    Attach a portal weight_num onto the latest eligible weight-entry scan.

    Eligible = weight-entry events at or before ``portal_observed_at`` (or all
    events, chronologically, when no observation time is given). The target is
    always the *latest* eligible event — never an earlier one — so a second
    (or third) weight-entry never receives a portal value meant for an
    earlier scan, and an earlier still-null scan is never overwritten with a
    later/current portal value.
    """
    del selected_date_et  # accepted for signature parity; not required for eligibility
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    lbs = normalize_scan_weight_lbs(weight_lbs)
    if not bid or lbs is None:
        return {"updated": False, "reason": "invalid_bag_or_weight"}

    observed_at = portal_observed_at or datetime.utcnow()
    weight_events = _weight_entry_events_for_bag(cursor, org, bid, events)

    eligible = weight_events
    if portal_observed_at is not None:
        eligible = [
            ev
            for ev in weight_events
            if (_event_ts(ev) or datetime.max) <= portal_observed_at
        ]

    if not eligible:
        return {
            "updated": False,
            "reason": "no_eligible_weight_entry",
            "bag_id": bid,
            "portal_observed_at": observed_at.isoformat() if observed_at else None,
        }

    target = eligible[-1]
    scan_id = target.get("id")
    target_ts = _event_ts(target)
    existing_lbs = normalize_scan_weight_lbs(target.get("weight_lbs"))

    if existing_lbs is not None:
        return {
            "updated": False,
            "reason": "scan_already_has_weight",
            "bag_id": bid,
            "scan_event_id": scan_id,
            "scan_event_ts": target_ts.isoformat() if target_ts else None,
            "existing_weight_lbs": existing_lbs,
        }

    if scan_id is None:
        return {"updated": False, "reason": "no_eligible_weight_entry", "bag_id": bid}

    ensure_scan_weight_enrichment_columns(cursor)
    cursor.execute(
        """
        UPDATE rinse_bag_scan_events
        SET weight_lbs = %s,
            weight_observed_at = %s,
            weight_source = %s,
            weight_attach_batch_id = %s,
            weight_attach_reason = %s,
            updated_at = NOW()
        WHERE id = %s AND organization_id = %s AND bag_id = %s AND weight_lbs IS NULL
        """,
        (
            lbs,
            observed_at,
            WEIGHT_SOURCE_PORTAL_CURRENT,
            int(upload_batch_id) if upload_batch_id is not None else None,
            REASON_LATEST_ELIGIBLE,
            int(scan_id),
            org,
            bid,
        ),
    )
    updated = bool(getattr(cursor, "rowcount", 0))
    return {
        "updated": updated,
        "reason": REASON_LATEST_ELIGIBLE if updated else "concurrent_write_lost",
        "bag_id": bid,
        "scan_event_id": scan_id,
        "scan_event_ts": target_ts.isoformat() if target_ts else None,
        "weight_lbs": lbs,
        "weight_source": WEIGHT_SOURCE_PORTAL_CURRENT,
        "weight_attach_batch_id": upload_batch_id,
        "portal_observed_at": observed_at.isoformat() if observed_at else None,
    }


# ---------------------------------------------------------------------------
# Backfill: recover historical pre-clean weights without ever misattributing
# the current/final portal value onto an earlier event.
# ---------------------------------------------------------------------------


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if isinstance(ts, datetime) else None


def _load_portal_weight_observations_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[dict[str, Any]]:
    """
    Chronological portal upload_batch_rows history for a bag: distinct
    (weight_num, observed_at, upload_batch_id) rows, oldest first.

    observed_at prefers the confirming batch's confirmed_at, falling back to
    the row's created_at when the batch isn't confirmed (or joins are absent).
    """
    from backend.checkout_batch_scope import _batch_pk, _row_batch_col
    from backend.ta_helpers import table_exists

    org = int(organization_id)
    if not table_exists(cursor, "upload_batch_rows") or not table_has_column(
        cursor, "upload_batch_rows", "ticket_id"
    ):
        return []

    row_batch_col = _row_batch_col(cursor)
    batch_pk = _batch_pk(cursor)
    join = ""
    confirmed_expr = "ubr.created_at"
    org_clause = ""
    args: list[Any] = []
    if row_batch_col and table_exists(cursor, "upload_batches"):
        join = f" LEFT JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}"
        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            confirmed_expr = "COALESCE(ub.confirmed_at, ubr.created_at)"
        if table_has_column(cursor, "upload_batches", "organization_id"):
            org_clause = " AND ub.organization_id = %s"
            args.append(org)

    batch_order_col = f"ubr.{row_batch_col}" if row_batch_col else "ubr.id"
    cursor.execute(
        f"""
        SELECT ubr.weight_num AS weight_num, {confirmed_expr} AS observed_at,
               {batch_order_col} AS upload_batch_id
        FROM upload_batch_rows ubr{join}
        WHERE ubr.ticket_id = %s{org_clause}
        ORDER BY {batch_order_col} ASC, ubr.id ASC
        """,
        (bag_id, *args),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        out.append(
            {
                "weight_num": normalize_scan_weight_lbs(row.get("weight_num")),
                "observed_at": _coerce_dt(row.get("observed_at")),
                "upload_batch_id": row.get("upload_batch_id"),
            }
        )
    return out


def _apply_backfill_weight(
    cursor,
    organization_id: int,
    bag_id: str,
    scan_event_id: Any,
    *,
    weight_lbs: float,
    weight_source: str,
    weight_attach_reason: str,
    observed_at: Any,
    upload_batch_id: Any,
) -> bool:
    if scan_event_id is None:
        return False
    ensure_scan_weight_enrichment_columns(cursor)
    cursor.execute(
        """
        UPDATE rinse_bag_scan_events
        SET weight_lbs = %s,
            weight_observed_at = %s,
            weight_source = %s,
            weight_attach_batch_id = %s,
            weight_attach_reason = %s,
            updated_at = NOW()
        WHERE id = %s AND organization_id = %s AND bag_id = %s AND weight_lbs IS NULL
        """,
        (
            weight_lbs,
            observed_at,
            weight_source,
            int(upload_batch_id) if upload_batch_id is not None else None,
            weight_attach_reason,
            int(scan_event_id),
            int(organization_id),
            bag_id,
        ),
    )
    return bool(getattr(cursor, "rowcount", 0))


def classify_and_backfill_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Recover missing weight-entry weights for one bag without ever attaching the
    CURRENT/final portal weight to an earlier weight-entry event.

    For chronologically ordered weight-entry events W1, W2, ...:
      * The LATEST event, if null, gets the current/latest portal weight_num
        -> OUTCOME_CURRENT_LATEST.
      * Each earlier null event Wi is checked against historical portal
        observations strictly between Wi.scanned_at and W(i+1).scanned_at.
        Exactly one distinct historical weight_num in that window -> recovered
        (OUTCOME_RECOVERED). Otherwise -> OUTCOME_PRE_NOT_RECOVERABLE /
        manager correction required.
    """
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    result: dict[str, Any] = {
        "bag_id": bid,
        "organization_id": org,
        "dry_run": dry_run,
        "events": [],
    }
    if not bid:
        result["outcome"] = "invalid_bag_id"
        return result

    weight_events = _weight_entry_events_for_bag(cursor, org, bid, None)
    if not weight_events:
        result["outcome"] = "no_weight_entry_events"
        return result

    observations = _load_portal_weight_observations_for_bag(cursor, org, bid)
    numeric_obs = [
        o
        for o in observations
        if o.get("weight_num") is not None and isinstance(o.get("observed_at"), datetime)
    ]

    n = len(weight_events)
    outcomes: list[dict[str, Any]] = []

    # 1) Latest weight-entry: current/latest portal weight, only if still null.
    latest_ev = weight_events[-1]
    latest_existing = normalize_scan_weight_lbs(latest_ev.get("weight_lbs"))
    latest_obs = numeric_obs[-1] if numeric_obs else None
    latest_outcome: dict[str, Any] = {
        "scan_event_id": latest_ev.get("id"),
        "scan_event_ts": _iso(_event_ts(latest_ev)),
        "position": n - 1,
    }
    if latest_existing is not None:
        latest_outcome["outcome"] = "already_has_weight"
        latest_outcome["weight_lbs"] = latest_existing
    elif latest_obs is None:
        latest_outcome["outcome"] = OUTCOME_PRE_NOT_RECOVERABLE
        latest_outcome["manager_correction_required"] = True
    else:
        latest_outcome["outcome"] = OUTCOME_CURRENT_LATEST
        latest_outcome["weight_lbs"] = latest_obs["weight_num"]
        latest_outcome["weight_source"] = WEIGHT_SOURCE_PORTAL_CURRENT
        if not dry_run:
            _apply_backfill_weight(
                cursor,
                org,
                bid,
                latest_ev.get("id"),
                weight_lbs=latest_obs["weight_num"],
                weight_source=WEIGHT_SOURCE_PORTAL_CURRENT,
                weight_attach_reason=OUTCOME_CURRENT_LATEST,
                observed_at=latest_obs.get("observed_at"),
                upload_batch_id=latest_obs.get("upload_batch_id"),
            )
    outcomes.append(latest_outcome)

    # 2) Earlier weight-entries: only recover from observations strictly
    #    between this event and the NEXT weight-entry — never the final value.
    for idx in range(n - 1):
        ev = weight_events[idx]
        existing = normalize_scan_weight_lbs(ev.get("weight_lbs"))
        ev_ts = _event_ts(ev)
        next_ts = _event_ts(weight_events[idx + 1])
        entry: dict[str, Any] = {
            "scan_event_id": ev.get("id"),
            "scan_event_ts": _iso(ev_ts),
            "position": idx,
        }
        if existing is not None:
            entry["outcome"] = "already_has_weight"
            entry["weight_lbs"] = existing
            outcomes.append(entry)
            continue

        window = [
            o
            for o in numeric_obs
            if ev_ts is not None
            and o["observed_at"] > ev_ts
            and (next_ts is None or o["observed_at"] < next_ts)
        ]
        distinct_values = sorted({o["weight_num"] for o in window})
        if len(distinct_values) == 1:
            recovered = distinct_values[0]
            src = window[0]
            entry["outcome"] = OUTCOME_RECOVERED
            entry["weight_lbs"] = recovered
            entry["weight_source"] = WEIGHT_SOURCE_PORTAL_HISTORICAL
            if not dry_run:
                _apply_backfill_weight(
                    cursor,
                    org,
                    bid,
                    ev.get("id"),
                    weight_lbs=recovered,
                    weight_source=WEIGHT_SOURCE_PORTAL_HISTORICAL,
                    weight_attach_reason=OUTCOME_RECOVERED,
                    observed_at=src.get("observed_at"),
                    upload_batch_id=src.get("upload_batch_id"),
                )
        else:
            entry["outcome"] = OUTCOME_PRE_NOT_RECOVERABLE
            entry["manager_correction_required"] = True
            entry["candidate_values"] = distinct_values
        outcomes.append(entry)

    outcomes.sort(key=lambda o: o["position"])
    result["events"] = outcomes
    result["manager_correction_required_count"] = sum(
        1 for o in outcomes if o.get("outcome") == OUTCOME_PRE_NOT_RECOVERABLE
    )
    result["recovered_count"] = sum(1 for o in outcomes if o.get("outcome") == OUTCOME_RECOVERED)
    result["current_latest_count"] = sum(
        1 for o in outcomes if o.get("outcome") == OUTCOME_CURRENT_LATEST
    )
    result["outcome"] = (
        OUTCOME_MANAGER_REQUIRED if result["manager_correction_required_count"] else "ok"
    )
    return result
