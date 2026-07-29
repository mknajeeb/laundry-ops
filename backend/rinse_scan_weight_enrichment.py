"""
Portal weight enrichment: preserve/restore + interval-based Pre/Post attach.

Rinse "Events CSV" never carries a Weight column. Portal ``weight_num`` arrives
later via Presence Run Rows (authoritative observation stream) and must be
attached onto the correct weight-entry scan row using chronological intervals:

    index 0 = PRE
    index 1 = POST
    index 2+ = WEIGHT_RECHECK  (preserved; does not alter PRE/POST projection)

Timeline rebuilds (delete-then-reinsert) must never erase weight enrichment.
``snapshot_weight_enrichment`` / ``restore_weight_enrichment`` bracket any such
delete+reinsert so enrichment survives; restore reports unmatched keys instead
of silently dropping them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
from backend.ta_helpers import table_exists, table_has_column

OUTCOME_RECOVERED = "RECOVERED_FROM_HISTORICAL_PORTAL_OBSERVATION"
OUTCOME_CURRENT_LATEST = "CURRENT_WEIGHT_ATTACHED_TO_LATEST_EVENT"
OUTCOME_PRE_NOT_RECOVERABLE = "PRE_WEIGHT_NOT_RECOVERABLE"
OUTCOME_MANAGER_REQUIRED = "MANAGER_CORRECTION_REQUIRED"

WEIGHT_SOURCE_PORTAL_CURRENT = "portal_weight_num"
WEIGHT_SOURCE_PORTAL_HISTORICAL = "portal_weight_num_historical"
WEIGHT_SOURCE_PRESENCE_RUN = "presence_run_weight_num"

REASON_LATEST_ELIGIBLE = "latest_eligible_at_portal_observation"
REASON_INTERVAL_ATTACH = "interval_eligible_presence_observation"
REASON_POST_RECONCILE = "current_cycle_post_reconcile_correction"

WEIGHT_ROLE_PRE = "PRE"
WEIGHT_ROLE_POST = "POST"
WEIGHT_ROLE_RECHECK = "WEIGHT_RECHECK"

_MANAGER_WEIGHT_SOURCES = frozenset(
    {
        "manager_correction",
        "correct_weight",
        "step1_edit",
        "rinse_step1_edit",
    }
)

_INF = datetime.max.replace(microsecond=0)


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
        ("weight_presence_run_id", "BIGINT NULL"),
        ("weight_presence_run_row_id", "BIGINT NULL"),
        ("weight_role", "VARCHAR(32) NULL"),
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
                   weight_source, weight_attach_batch_id, weight_attach_reason,
                   weight_presence_run_id, weight_presence_run_row_id, weight_role
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
                "weight_presence_run_id": row.get("weight_presence_run_id"),
                "weight_presence_run_row_id": row.get("weight_presence_run_row_id"),
                "weight_role": row.get("weight_role"),
            }
    return out


def restore_weight_enrichment(
    cursor,
    organization_id: int,
    preserved: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Re-apply preserved enrichment after a delete+reinsert.

    Never overwrites a populated weight_lbs — COALESCE plus an explicit
    ``weight_lbs IS NULL`` guard on every column.

    On dedupe_key miss, records an ``unmatched`` entry (never silently drops).
    """
    stats: dict[str, Any] = {
        "updated": 0,
        "skipped_already_populated": 0,
        "unmatched": [],
        "preserved_count": len(preserved or {}),
    }
    if not preserved:
        return stats
    ensure_scan_weight_enrichment_columns(cursor)
    org = int(organization_id)
    for (bag_id, dedupe_key), values in preserved.items():
        if not bag_id or not dedupe_key:
            stats["unmatched"].append(
                {
                    "bag_id": bag_id,
                    "dedupe_key": dedupe_key,
                    "reason": "missing_bag_or_dedupe_key",
                    "weight_lbs": (values or {}).get("weight_lbs"),
                }
            )
            continue
        lbs = (values or {}).get("weight_lbs")
        if lbs is None:
            # Never clear / never write NULL onto a scan row.
            stats["unmatched"].append(
                {
                    "bag_id": bag_id,
                    "dedupe_key": str(dedupe_key),
                    "reason": "preserved_weight_lbs_null",
                    "weight_lbs": None,
                }
            )
            continue

        cursor.execute(
            """
            SELECT id, weight_lbs FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id = %s AND dedupe_key = %s
            LIMIT 1
            """,
            (org, bag_id, dedupe_key),
        )
        existing = cursor.fetchone()
        if not existing:
            stats["unmatched"].append(
                {
                    "bag_id": bag_id,
                    "dedupe_key": str(dedupe_key),
                    "reason": "dedupe_key_not_found",
                    "weight_lbs": lbs,
                    "weight_observed_at": (values or {}).get("weight_observed_at"),
                    "weight_source": (values or {}).get("weight_source"),
                    "weight_presence_run_id": (values or {}).get("weight_presence_run_id"),
                    "weight_presence_run_row_id": (values or {}).get(
                        "weight_presence_run_row_id"
                    ),
                    "weight_role": (values or {}).get("weight_role"),
                }
            )
            continue

        if isinstance(existing, Mapping):
            existing_lbs = existing.get("weight_lbs")
        else:
            existing_lbs = existing[1] if len(existing) > 1 else None
        if existing_lbs is not None:
            stats["skipped_already_populated"] += 1
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
                weight_presence_run_id = COALESCE(weight_presence_run_id, %s),
                weight_presence_run_row_id = COALESCE(weight_presence_run_row_id, %s),
                weight_role = COALESCE(NULLIF(weight_role, ''), %s),
                updated_at = NOW()
            WHERE organization_id = %s AND bag_id = %s AND dedupe_key = %s
              AND weight_lbs IS NULL
            """,
            (
                lbs,
                (values or {}).get("weight_observed_at"),
                (values or {}).get("weight_source"),
                (values or {}).get("weight_attach_batch_id"),
                (values or {}).get("weight_attach_reason"),
                (values or {}).get("weight_presence_run_id"),
                (values or {}).get("weight_presence_run_row_id"),
                (values or {}).get("weight_role"),
                org,
                bag_id,
                dedupe_key,
            ),
        )
        stats["updated"] += int(getattr(cursor, "rowcount", 0) or 0)
    return stats


# ---------------------------------------------------------------------------
# Attach helpers
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


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if isinstance(ts, datetime) else None


def _weight_role_for_index(index: int) -> str:
    if index == 0:
        return WEIGHT_ROLE_PRE
    if index == 1:
        return WEIGHT_ROLE_POST
    return WEIGHT_ROLE_RECHECK


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


def _manager_corrected_roles(
    cursor,
    organization_id: int,
    bag_id: str,
) -> frozenset[str]:
    """
    Roles locked by manager correct_weight / step1 edit audit.

    Mirrors load_bag_weight_map (rinse_veewash_review) correct_weight reads so
    automatic portal attach never overwrites a manager-corrected weight.
    """
    roles: set[str] = set()
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return frozenset()

    if table_exists(cursor, "rinse_step1_corrections"):
        cursor.execute(
            """
            SELECT new_values
            FROM rinse_step1_corrections
            WHERE organization_id = %s AND bag_id = %s AND action = 'correct_weight'
            ORDER BY created_at ASC, id ASC
            """,
            (org, bid),
        )
        for row in cursor.fetchall() or []:
            raw = row.get("new_values") if isinstance(row, Mapping) else None
            if isinstance(raw, str):
                try:
                    import json

                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if not isinstance(raw, dict):
                continue
            # correct_weight always targets effective POST (API + edit-bag).
            if any(
                k in raw
                for k in (
                    "corrected_post_weight_lbs",
                    "post_weight_lbs",
                    "weight_lbs",
                )
            ):
                roles.add(WEIGHT_ROLE_POST)
            # Explicit corrected_pre (if present) locks PRE; bare pre_weight_lbs on
            # correct_weight rows is often just the detected value, not a lock.
            if raw.get("corrected_pre_weight_lbs") is not None:
                roles.add(WEIGHT_ROLE_PRE)

    if table_exists(cursor, "rinse_step1_bag_edit_deltas") and table_exists(
        cursor, "rinse_step1_bag_edits"
    ):
        cursor.execute(
            """
            SELECT d.field_name
            FROM rinse_step1_bag_edit_deltas d
            INNER JOIN rinse_step1_bag_edits e ON e.id = d.edit_id
            WHERE e.organization_id = %s AND e.bag_id = %s
              AND e.is_undo = 0
              AND d.field_name IN ('pre_weight_lbs', 'post_weight_lbs')
            """,
            (org, bid),
        )
        for row in cursor.fetchall() or []:
            field = row.get("field_name") if isinstance(row, Mapping) else None
            if field == "pre_weight_lbs":
                roles.add(WEIGHT_ROLE_PRE)
            elif field == "post_weight_lbs":
                roles.add(WEIGHT_ROLE_POST)

    return frozenset(roles)


def _event_is_manager_locked(ev: Mapping[str, Any], locked_roles: frozenset[str]) -> bool:
    role = str(ev.get("weight_role") or "").strip().upper()
    source = str(ev.get("weight_source") or "").strip().lower()
    if source in _MANAGER_WEIGHT_SOURCES:
        return True
    if role and role in locked_roles:
        return True
    return False


def _build_event_intervals(
    weight_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Valid observation intervals for weight-entry events (oldest first).

    PRE:   [pre_ts, post_ts) if post exists else [pre_ts, +inf)
    POST:  [post_ts, third_ts) if third else [post_ts, +inf)
    EXTRA: [event_i_ts, event_{i+1}_ts) or +inf
    """
    out: list[dict[str, Any]] = []
    n = len(weight_events)
    for i, ev in enumerate(weight_events):
        ts = _event_ts(ev)
        next_ts = _event_ts(weight_events[i + 1]) if i + 1 < n else None
        end = next_ts if next_ts is not None else _INF
        out.append(
            {
                "index": i,
                "event": ev,
                "event_ts": ts,
                "interval_start": ts,
                "interval_end": end,
                "role": _weight_role_for_index(i),
            }
        )
    return out


def _observation_in_interval(
    observed_at: datetime,
    interval_start: datetime | None,
    interval_end: datetime | None,
) -> bool:
    if interval_start is None:
        return False
    if observed_at < interval_start:
        return False
    end = interval_end if interval_end is not None else _INF
    return observed_at < end


def _apply_weight_to_scan_event(
    cursor,
    organization_id: int,
    bag_id: str,
    scan_event_id: Any,
    *,
    weight_lbs: float,
    weight_source: str,
    weight_attach_reason: str,
    observed_at: Any,
    upload_batch_id: Any = None,
    presence_run_id: Any = None,
    presence_run_row_id: Any = None,
    weight_role: str | None = None,
    allow_overwrite: bool = False,
) -> bool:
    if scan_event_id is None or weight_lbs is None:
        return False
    ensure_scan_weight_enrichment_columns(cursor)
    if allow_overwrite:
        cursor.execute(
            """
            UPDATE rinse_bag_scan_events
            SET weight_lbs = %s,
                weight_observed_at = %s,
                weight_source = %s,
                weight_attach_batch_id = %s,
                weight_attach_reason = %s,
                weight_presence_run_id = %s,
                weight_presence_run_row_id = %s,
                weight_role = %s,
                updated_at = NOW()
            WHERE id = %s AND organization_id = %s AND bag_id = %s
              AND (
                weight_lbs IS NULL
                OR ABS(COALESCE(weight_lbs, 0) - %s) > 0.05
              )
              AND COALESCE(weight_source, '') NOT IN (
                'manager_correction', 'correct_weight', 'step1_edit',
                'rinse_step1_edit', 'operator_manual_correction',
                'OPERATOR_MANUAL_CORRECTION'
              )
            """,
            (
                weight_lbs,
                observed_at,
                weight_source,
                int(upload_batch_id) if upload_batch_id is not None else None,
                weight_attach_reason,
                int(presence_run_id) if presence_run_id is not None else None,
                int(presence_run_row_id) if presence_run_row_id is not None else None,
                weight_role,
                int(scan_event_id),
                int(organization_id),
                bag_id,
                float(weight_lbs),
            ),
        )
    else:
        cursor.execute(
            """
            UPDATE rinse_bag_scan_events
            SET weight_lbs = %s,
                weight_observed_at = %s,
                weight_source = %s,
                weight_attach_batch_id = %s,
                weight_attach_reason = %s,
                weight_presence_run_id = %s,
                weight_presence_run_row_id = %s,
                weight_role = %s,
                updated_at = NOW()
            WHERE id = %s AND organization_id = %s AND bag_id = %s AND weight_lbs IS NULL
            """,
            (
                weight_lbs,
                observed_at,
                weight_source,
                int(upload_batch_id) if upload_batch_id is not None else None,
                weight_attach_reason,
                int(presence_run_id) if presence_run_id is not None else None,
                int(presence_run_row_id) if presence_run_row_id is not None else None,
                weight_role,
                int(scan_event_id),
                int(organization_id),
                bag_id,
            ),
        )
    return bool(getattr(cursor, "rowcount", 0))


def attach_observations_to_weight_events(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    observations: Sequence[Mapping[str, Any]] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    dry_run: bool = False,
    weight_source: str | None = None,
) -> dict[str, Any]:
    """
    Interval-based attach of portal/presence weight observations onto weight-entry scans.

    Process observations oldest-first. Each observation attaches to at most one
    event: the most recent eligible unfilled weight-entry with
    ``event_ts <= observed_at`` and ``observed_at`` inside that event's interval.

    Third+ weight-entry events are ``WEIGHT_RECHECK`` — preserved with provenance,
    never treated as another POST, and never alter PRE/POST projection.
    """
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    result: dict[str, Any] = {
        "bag_id": bid,
        "organization_id": org,
        "dry_run": dry_run,
        "attached": [],
        "skipped_observations": [],
        "updated_count": 0,
    }
    if not bid:
        result["reason"] = "invalid_bag_id"
        return result

    weight_events = _weight_entry_events_for_bag(cursor, org, bid, events)
    if not weight_events:
        result["reason"] = "no_weight_entry_events"
        return result

    if observations is None:
        observations = _load_portal_weight_observations_for_bag(cursor, org, bid)

    numeric_obs: list[dict[str, Any]] = []
    for o in observations or []:
        if not isinstance(o, Mapping):
            continue
        lbs = normalize_scan_weight_lbs(o.get("weight_num"))
        observed_at = _coerce_dt(o.get("observed_at"))
        if lbs is None or observed_at is None:
            result["skipped_observations"].append(
                {
                    "reason": "invalid_observation",
                    "weight_num": o.get("weight_num"),
                    "observed_at": o.get("observed_at"),
                }
            )
            continue
        numeric_obs.append(
            {
                "weight_num": lbs,
                "observed_at": observed_at,
                "upload_batch_id": o.get("upload_batch_id"),
                "presence_run_id": o.get("presence_run_id"),
                "presence_run_row_id": o.get("presence_run_row_id"),
            }
        )
    numeric_obs.sort(
        key=lambda o: (
            o["observed_at"],
            o.get("presence_run_row_id") or 0,
            o.get("upload_batch_id") or 0,
        )
    )

    locked_roles = _manager_corrected_roles(cursor, org, bid)
    intervals = _build_event_intervals(weight_events)
    # Mutable fill state (index → weight_lbs once attached / already present).
    filled: dict[int, float | None] = {}
    for i, ev in enumerate(weight_events):
        existing = normalize_scan_weight_lbs(ev.get("weight_lbs"))
        filled[i] = existing

    default_source = weight_source or WEIGHT_SOURCE_PRESENCE_RUN
    pre_lbs = filled.get(0)

    def _can_reconcile_post(idx: int, role: str, current: float | None, new_lbs: float) -> bool:
        """POST may correct when still provisional (equals PRE) and a later obs differs."""
        if role != WEIGHT_ROLE_POST:
            return False
        if current is None:
            return False
        if abs(float(current) - float(new_lbs)) <= 0.05:
            return False
        # Provisional = still equal to PRE (or PRE unknown and we see a change from first fill).
        if pre_lbs is not None and abs(float(current) - float(pre_lbs)) <= 0.05:
            return True
        return False

    for obs in numeric_obs:
        observed_at: datetime = obs["observed_at"]
        lbs: float = obs["weight_num"]
        candidates: list[dict[str, Any]] = []
        reconcile_candidates: list[dict[str, Any]] = []
        for slot in intervals:
            idx = int(slot["index"])
            ev = slot["event"]
            ev_ts = slot["event_ts"]
            role = slot["role"]
            if ev_ts is None or ev_ts > observed_at:
                continue
            if not _observation_in_interval(
                observed_at, slot["interval_start"], slot["interval_end"]
            ):
                continue
            if _event_is_manager_locked(ev, locked_roles) or role in locked_roles:
                continue
            current = filled.get(idx)
            if current is None:
                candidates.append(slot)
            elif _can_reconcile_post(idx, role, current, lbs):
                reconcile_candidates.append(slot)

        target = None
        allow_overwrite = False
        attach_reason = REASON_INTERVAL_ATTACH
        if candidates:
            target = candidates[-1]
        elif reconcile_candidates:
            target = reconcile_candidates[-1]
            allow_overwrite = True
            attach_reason = REASON_POST_RECONCILE

        if target is None:
            result["skipped_observations"].append(
                {
                    "reason": "no_eligible_unfilled_event",
                    "weight_num": lbs,
                    "observed_at": _iso(observed_at),
                    "presence_run_id": obs.get("presence_run_id"),
                    "presence_run_row_id": obs.get("presence_run_row_id"),
                }
            )
            continue

        # Most recent eligible unfilled (or reconcilable POST) event.
        idx = int(target["index"])
        ev = target["event"]
        role = target["role"]
        scan_id = ev.get("id")
        src = default_source
        if obs.get("presence_run_id") is None and obs.get("upload_batch_id") is not None:
            src = WEIGHT_SOURCE_PORTAL_CURRENT
        if weight_source:
            src = weight_source

        attached_row = {
            "scan_event_id": scan_id,
            "scan_event_ts": _iso(target["event_ts"]),
            "position": idx,
            "weight_role": role,
            "weight_lbs": lbs,
            "weight_source": src,
            "weight_attach_reason": attach_reason,
            "weight_observed_at": _iso(observed_at),
            "weight_presence_run_id": obs.get("presence_run_id"),
            "weight_presence_run_row_id": obs.get("presence_run_row_id"),
            "upload_batch_id": obs.get("upload_batch_id"),
            "updated": False,
            "reconciled": allow_overwrite,
        }
        if not dry_run:
            ok = _apply_weight_to_scan_event(
                cursor,
                org,
                bid,
                scan_id,
                weight_lbs=lbs,
                weight_source=src,
                weight_attach_reason=attach_reason,
                observed_at=observed_at,
                upload_batch_id=obs.get("upload_batch_id"),
                presence_run_id=obs.get("presence_run_id"),
                presence_run_row_id=obs.get("presence_run_row_id"),
                weight_role=role,
                allow_overwrite=allow_overwrite,
            )
            attached_row["updated"] = ok
            if ok:
                result["updated_count"] += 1
                filled[idx] = lbs
                ev["weight_lbs"] = lbs
                ev["weight_role"] = role
                ev["weight_source"] = src
        else:
            attached_row["updated"] = True
            result["updated_count"] += 1
            filled[idx] = lbs
            ev["weight_lbs"] = lbs

        result["attached"].append(attached_row)

    result["reason"] = "ok"
    result["weight_entry_count"] = len(weight_events)
    result["manager_locked_roles"] = sorted(locked_roles)
    return result


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
    presence_run_id: int | None = None,
    presence_run_row_id: int | None = None,
) -> dict[str, Any]:
    """
    Confirm-path compatibility wrapper: interval-attach a single observation.

    Prefer ``attach_observations_to_weight_events`` for multi-observation / presence
    run flows. This keeps upload finalize / combined upload callers working.
    """
    del selected_date_et  # accepted for signature parity
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    lbs = normalize_scan_weight_lbs(weight_lbs)
    if not bid or lbs is None:
        return {"updated": False, "reason": "invalid_bag_or_weight"}

    observed_at = portal_observed_at or datetime.utcnow()
    obs = [
        {
            "weight_num": lbs,
            "observed_at": observed_at,
            "upload_batch_id": upload_batch_id,
            "presence_run_id": presence_run_id,
            "presence_run_row_id": presence_run_row_id,
        }
    ]
    attach = attach_observations_to_weight_events(
        cursor,
        org,
        bid,
        observations=obs,
        events=events,
        dry_run=False,
        weight_source=WEIGHT_SOURCE_PORTAL_CURRENT,
    )
    attached = attach.get("attached") or []
    if not attached:
        reason = "no_eligible_weight_entry"
        skipped = attach.get("skipped_observations") or []
        if skipped:
            reason = str(skipped[-1].get("reason") or reason)
        if attach.get("reason") == "no_weight_entry_events":
            reason = "no_eligible_weight_entry"
        # Preserve prior confirm-path reason when every weight-entry is already filled.
        weight_events = _weight_entry_events_for_bag(cursor, org, bid, events)
        if weight_events and all(
            normalize_scan_weight_lbs(ev.get("weight_lbs")) is not None
            for ev in weight_events
        ):
            latest = weight_events[-1]
            return {
                "updated": False,
                "reason": "scan_already_has_weight",
                "bag_id": bid,
                "scan_event_id": latest.get("id"),
                "scan_event_ts": _iso(_event_ts(latest)),
                "existing_weight_lbs": normalize_scan_weight_lbs(latest.get("weight_lbs")),
                "interval_attach": attach,
            }
        return {
            "updated": False,
            "reason": reason,
            "bag_id": bid,
            "portal_observed_at": observed_at.isoformat() if observed_at else None,
            "interval_attach": attach,
        }

    hit = attached[-1]
    if not hit.get("updated"):
        # Event may already have weight (race / pre-filled).
        return {
            "updated": False,
            "reason": "scan_already_has_weight",
            "bag_id": bid,
            "scan_event_id": hit.get("scan_event_id"),
            "scan_event_ts": hit.get("scan_event_ts"),
            "existing_weight_lbs": None,
            "interval_attach": attach,
        }

    return {
        "updated": True,
        "reason": REASON_INTERVAL_ATTACH,
        "bag_id": bid,
        "scan_event_id": hit.get("scan_event_id"),
        "scan_event_ts": hit.get("scan_event_ts"),
        "weight_lbs": lbs,
        "weight_source": WEIGHT_SOURCE_PORTAL_CURRENT,
        "weight_attach_batch_id": upload_batch_id,
        "weight_role": hit.get("weight_role"),
        "weight_presence_run_id": presence_run_id,
        "weight_presence_run_row_id": presence_run_row_id,
        "portal_observed_at": observed_at.isoformat() if observed_at else None,
        "interval_attach": attach,
    }


# ---------------------------------------------------------------------------
# Presence Run Rows observation stream (authoritative; not upload_batch_rows)
# ---------------------------------------------------------------------------


def _load_portal_weight_observations_for_bag(
    cursor,
    organization_id: int,
    bag_id: str,
) -> list[dict[str, Any]]:
    """
    Chronological Presence Run Row weight observations for a bag, oldest first.

    ``weight_num IS NOT NULL`` (0 is valid). observed_at =
    COALESCE(run_rows.observed_at, runs.finished_at, runs.created_at).

    Does **not** read ``upload_batch_rows`` on the normal path.
    """
    org = int(organization_id)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return []
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        return []
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_runs"):
        return []

    cursor.execute(
        """
        SELECT
            rr.id AS presence_run_row_id,
            rr.presence_run_id AS presence_run_id,
            rr.weight_num AS weight_num,
            COALESCE(rr.observed_at, r.finished_at, r.created_at) AS observed_at
        FROM rinse_cleaner_ticket_presence_run_rows rr
        INNER JOIN rinse_cleaner_ticket_presence_runs r
            ON r.id = rr.presence_run_id
        WHERE rr.organization_id = %s
          AND rr.bag_id = %s
          AND rr.weight_num IS NOT NULL
        ORDER BY COALESCE(rr.observed_at, r.finished_at, r.created_at) ASC,
                 rr.id ASC
        """,
        (org, bid),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        lbs = normalize_scan_weight_lbs(row.get("weight_num"))
        if lbs is None:
            continue
        out.append(
            {
                "weight_num": lbs,
                "observed_at": _coerce_dt(row.get("observed_at")),
                "presence_run_id": row.get("presence_run_id"),
                "presence_run_row_id": row.get("presence_run_row_id"),
                "upload_batch_id": None,
            }
        )
    return out


def classify_and_backfill_bag(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Recover missing weight-entry weights from Presence Run Row observations via
    interval attach (never upload_batch_rows on the normal path).

    Third+ weight-entry events are WEIGHT_RECHECK and do not alter PRE/POST.
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
    attach = attach_observations_to_weight_events(
        cursor,
        org,
        bid,
        observations=observations,
        events=weight_events,
        dry_run=dry_run,
        weight_source=WEIGHT_SOURCE_PRESENCE_RUN,
    )
    result["interval_attach"] = attach

    attached_by_pos = {
        int(a["position"]): a for a in (attach.get("attached") or []) if "position" in a
    }

    outcomes: list[dict[str, Any]] = []
    for idx, ev in enumerate(weight_events):
        role = _weight_role_for_index(idx)
        existing = normalize_scan_weight_lbs(ev.get("weight_lbs"))
        entry: dict[str, Any] = {
            "scan_event_id": ev.get("id"),
            "scan_event_ts": _iso(_event_ts(ev)),
            "position": idx,
            "weight_role": role,
        }
        hit = attached_by_pos.get(idx)
        if existing is not None and hit is None:
            entry["outcome"] = "already_has_weight"
            entry["weight_lbs"] = existing
        elif hit is not None:
            # Interval attach filled (or would fill) this slot.
            if role == WEIGHT_ROLE_PRE and idx == 0:
                # Historical pre recovered vs current — prefer recovered label when
                # observation is not the chronologically last observation overall.
                entry["outcome"] = (
                    OUTCOME_RECOVERED
                    if idx < len(weight_events) - 1
                    else OUTCOME_CURRENT_LATEST
                )
            elif role == WEIGHT_ROLE_POST:
                entry["outcome"] = (
                    OUTCOME_CURRENT_LATEST
                    if idx == len(weight_events) - 1
                    else OUTCOME_RECOVERED
                )
            else:
                entry["outcome"] = OUTCOME_RECOVERED
            entry["weight_lbs"] = hit.get("weight_lbs")
            entry["weight_source"] = hit.get("weight_source")
            entry["weight_presence_run_id"] = hit.get("weight_presence_run_id")
            entry["weight_presence_run_row_id"] = hit.get("weight_presence_run_row_id")
        else:
            if role == WEIGHT_ROLE_RECHECK:
                entry["outcome"] = "recheck_unfilled"
            else:
                entry["outcome"] = OUTCOME_PRE_NOT_RECOVERABLE
                entry["manager_correction_required"] = True
        outcomes.append(entry)

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
