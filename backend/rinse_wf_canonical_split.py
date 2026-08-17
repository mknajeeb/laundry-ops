"""Canonical WF Split evaluator — single owner for split yes/no / review / pending.

Business definition
-------------------
A WF bag is SPLIT when intentionally separated into multiple washer loads in the
SAME resolved WF processing cycle.

Evidence
  A. INTENT: purpose = split-load (exact normalized production purpose)
  B. PHYSICAL: ≥2 distinct qualifying W* washer-load scans in the same cycle

Classification matrix (after washing-phase close or disappearance):
  A  marker YES + loads ≥2 → CONFIRMED_SPLIT
  B  marker NO  + loads <2 → CONFIRMED_NOT_SPLIT
  C  marker YES + loads <2 → REVIEW (SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND)
  D  marker NO  + loads ≥2 → REVIEW (MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER)

Pending while washing open (no drying / complete-cleaning yet, not disappeared):
  → PENDING — do not send to Split Order Review on marker+1W mid-wash.

canonical_split is True only for CONFIRMED_SPLIT | MANAGER_SPLIT.
canonical_split is False for CONFIRMED_NOT_SPLIT | MANAGER_NOT_SPLIT.
REVIEW_REQUIRED / PENDING leave canonical_split unresolved (None).

Consumers (Management, Chronology, Supply, Split Review) MUST import from here.
Do not reimplement washer-load heuristics elsewhere for IS-SPLIT.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_now
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    gaming_events_from_records,
    lifecycle_anchor,
    ts_valid,
)
from backend.rinse_scan_purpose import (
    is_complete_cleaning_purpose,
    is_drying_purpose,
    is_split_load_purpose,
    is_start_cleaning_purpose,
    normalize_scan_purpose,
)
from backend.rinse_washing_chronology import extract_washing_rows_from_events
from backend.ta_helpers import table_exists

# ---------------------------------------------------------------------------
# States / reasons
# ---------------------------------------------------------------------------

STATE_PENDING = "PENDING"
STATE_CONFIRMED_SPLIT = "CONFIRMED_SPLIT"
STATE_CONFIRMED_NOT_SPLIT = "CONFIRMED_NOT_SPLIT"
STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATE_MANAGER_SPLIT = "MANAGER_SPLIT"
STATE_MANAGER_NOT_SPLIT = "MANAGER_NOT_SPLIT"

REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND = (
    "SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND"
)
REASON_MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER = (
    "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER"
)
REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE = (
    "SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE"
)

MANAGER_DECISION_SPLIT = "split"
MANAGER_DECISION_NOT_SPLIT = "not_split"

_SPLIT_DECISION_TABLES_READY = False


def _as_naive_et(ts: datetime | None) -> datetime | None:
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is not None:
        return ts.replace(tzinfo=None)
    return ts


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User", "employee"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _sort_key_ev(ev: Mapping[str, Any]) -> tuple:
    ts = _as_naive_et(event_ts(ev)) or datetime.min
    try:
        eid = int(ev.get("id") or 0)
    except (TypeError, ValueError):
        eid = 0
    try:
        idx = int(ev.get("scan_index") or 0)
    except (TypeError, ValueError):
        idx = 0
    return (ts, idx, eid)


def resolve_wf_cycle_events(
    events: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], datetime | None, Mapping[str, Any] | None]:
    """Return (cycle_events, anchor_ts, anchor_ev) for the current WF lifecycle."""
    enriched: list[dict[str, Any]] = []
    for ev in events or []:
        row = dict(ev)
        naive = _as_naive_et(event_ts(row))
        if naive is not None:
            row["scanned_at_parsed"] = naive
        enriched.append(row)
    timeline = gaming_events_from_records(enriched)
    anchor_ts, anchor_ev = lifecycle_anchor(timeline)
    if anchor_ts is None:
        # No STV: treat all visible timeline events as the open cycle.
        return list(timeline), None, None
    return events_on_or_after(timeline, anchor_ts), _as_naive_et(anchor_ts), anchor_ev


def find_split_marker(
    cycle_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Primary INTENT signal: exact normalized purpose split-load in the cycle."""
    markers = [
        ev
        for ev in cycle_events
        if is_split_load_purpose(ev.get("purpose")) and ts_valid(event_ts(ev))
    ]
    if not markers:
        return {
            "split_marker_present": False,
            "split_marker_event_id": None,
            "split_marker_at": None,
            "split_marker_employee": None,
            "split_marker_resource": None,
        }
    chosen = min(markers, key=_sort_key_ev)
    rack = chosen.get("rack") or chosen.get("last_location")
    return {
        "split_marker_present": True,
        "split_marker_event_id": chosen.get("id"),
        "split_marker_at": _as_naive_et(event_ts(chosen)),
        "split_marker_employee": _operator(chosen),
        "split_marker_resource": str(rack).strip() if rack else None,
    }


def count_qualifying_washer_loads(
    cycle_events: Sequence[Mapping[str, Any]],
    *,
    bag_id: str,
) -> dict[str, Any]:
    """
    PHYSICAL evidence: distinct qualifying W* washer-load scans in the cycle.

    Uses extract_washing_rows_from_events(require_direct_washer_rack=True):
    actual start-cleaning, valid W* pattern, deduped, capped — physical loads
    only (not inferred chronology display rows).
    """
    bid = normalize_bag_id(bag_id) or str(bag_id or "").strip()
    enriched: list[dict[str, Any]] = []
    for ev in cycle_events:
        row = dict(ev)
        if not row.get("bag_id"):
            row["bag_id"] = bid
        enriched.append(row)
    wash_rows = extract_washing_rows_from_events(
        enriched,
        require_direct_washer_rack=True,
    )
    # Restrict to this bag (extractor may see multi-bag batches).
    wash_rows = [
        r
        for r in wash_rows
        if normalize_bag_id(r.get("bag_id")) == bid
        or str(r.get("bag_id") or "").strip() == bid
    ]
    racks = sorted(
        {
            str(r.get("washer_rack") or "").strip()
            for r in wash_rows
            if str(r.get("washer_rack") or "").strip()
        }
    )
    latest_ts = None
    if wash_rows:
        latest_ts = max(
            (_as_naive_et(r.get("timestamp_et")) for r in wash_rows),
            default=None,
        )
    return {
        "washer_load_count": len(wash_rows),
        "washer_racks": racks,
        "washer_load_rows": wash_rows,
        "latest_washer_load_et": latest_ts,
    }


def find_washing_phase_close(
    cycle_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Washing phase closes at the first of: purpose=drying, else complete-cleaning
    (chronological in the resolved cycle).
    """
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for ev in cycle_events:
        if not ts_valid(event_ts(ev)):
            continue
        if is_drying_purpose(ev.get("purpose")):
            candidates.append(("drying", ev))
        elif is_complete_cleaning_purpose(ev.get("purpose")):
            candidates.append(("complete-cleaning", ev))
    if not candidates:
        return {
            "washing_closed": False,
            "close_event_purpose": None,
            "close_event_id": None,
            "close_event_at": None,
        }
    purpose, chosen = min(candidates, key=lambda pair: _sort_key_ev(pair[1]))
    return {
        "washing_closed": True,
        "close_event_purpose": purpose,
        "close_event_id": chosen.get("id"),
        "close_event_at": _as_naive_et(event_ts(chosen)),
    }


def _apply_matrix(
    *,
    marker: bool,
    loads: int,
    at_disappearance: bool,
    evidence_incomplete: bool,
) -> tuple[str, str | None]:
    """Return (state, review_reason)."""
    if evidence_incomplete and at_disappearance:
        return STATE_REVIEW_REQUIRED, REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE
    if marker and loads >= 2:
        return STATE_CONFIRMED_SPLIT, None
    if (not marker) and loads < 2:
        return STATE_CONFIRMED_NOT_SPLIT, None
    if marker and loads < 2:
        return (
            STATE_REVIEW_REQUIRED,
            REASON_SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND,
        )
    # marker NO + loads ≥ 2
    return (
        STATE_REVIEW_REQUIRED,
        REASON_MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER,
    )


def _canonical_split_from_state(state: str) -> bool | None:
    if state in (STATE_CONFIRMED_SPLIT, STATE_MANAGER_SPLIT):
        return True
    if state in (STATE_CONFIRMED_NOT_SPLIT, STATE_MANAGER_NOT_SPLIT):
        return False
    return None


def evaluate_bag_split(
    events: Sequence[Mapping[str, Any]],
    *,
    bag_id: str,
    manager_decision: Mapping[str, Any] | None = None,
    disappeared: bool = False,
    evidence_incomplete: bool = False,
) -> dict[str, Any]:
    """
    Single-bag canonical split evaluation.

    ``manager_decision`` keys (optional): decision ('split'|'not_split'),
    at, by, note — when present, overrides auto state to MANAGER_*.
    Marker evidence is always retained even under manager override.
    """
    bid = normalize_bag_id(bag_id) or str(bag_id or "").strip()
    cycle_events, anchor_ts, _anchor_ev = resolve_wf_cycle_events(events)
    marker = find_split_marker(cycle_events)
    loads = count_qualifying_washer_loads(cycle_events, bag_id=bid)
    close = find_washing_phase_close(cycle_events)
    load_count = int(loads.get("washer_load_count") or 0)
    marker_yes = bool(marker.get("split_marker_present"))

    mgr = manager_decision if isinstance(manager_decision, Mapping) else None
    mgr_decision = None
    if mgr:
        raw = str(mgr.get("decision") or mgr.get("manager_split_decision") or "").strip().lower()
        if raw in (MANAGER_DECISION_SPLIT, "yes", "true", "1", "manager_split"):
            mgr_decision = MANAGER_DECISION_SPLIT
        elif raw in (
            MANAGER_DECISION_NOT_SPLIT,
            "no",
            "false",
            "0",
            "manager_not_split",
            "not-split",
        ):
            mgr_decision = MANAGER_DECISION_NOT_SPLIT

    review_reason: str | None = None
    if mgr_decision == MANAGER_DECISION_SPLIT:
        state = STATE_MANAGER_SPLIT
    elif mgr_decision == MANAGER_DECISION_NOT_SPLIT:
        state = STATE_MANAGER_NOT_SPLIT
    elif not close["washing_closed"] and not disappeared:
        # Washing still open — never Split Review on incomplete wash phase.
        state = STATE_PENDING
    else:
        # Incomplete at disappearance when we cannot trust the physical count
        # (caller flag) or cycle has start-cleaning noise without any W*.
        incomplete = bool(evidence_incomplete)
        if disappeared and incomplete:
            state = STATE_REVIEW_REQUIRED
            review_reason = REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE
        else:
            # At disappearance with contradictory/ambiguous partial evidence:
            # prefer the normal matrix; incomplete only when explicitly flagged.
            if (
                disappeared
                and not incomplete
                and marker_yes
                and load_count == 0
                and any(
                    is_start_cleaning_purpose(ev.get("purpose"))
                    for ev in cycle_events
                )
            ):
                # Had start-cleaning activity but no qualifying W* → incomplete.
                state = STATE_REVIEW_REQUIRED
                review_reason = REASON_SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE
            else:
                state, review_reason = _apply_matrix(
                    marker=marker_yes,
                    loads=load_count,
                    at_disappearance=bool(disappeared),
                    evidence_incomplete=False,
                )

    canonical = _canonical_split_from_state(state)
    processing_units = 2 if canonical is True else 1

    return {
        "bag_id": bid,
        "state": state,
        "canonical_split": canonical,
        "review_required": state == STATE_REVIEW_REQUIRED,
        "review_reason": review_reason,
        "pending": state == STATE_PENDING,
        "processing_units": processing_units,
        "split_finalized": state
        in (
            STATE_CONFIRMED_SPLIT,
            STATE_CONFIRMED_NOT_SPLIT,
            STATE_MANAGER_SPLIT,
            STATE_MANAGER_NOT_SPLIT,
        ),
        "lifecycle_anchor_et": anchor_ts,
        "washing_closed": bool(close["washing_closed"]),
        "close_event_purpose": close.get("close_event_purpose"),
        "close_event_id": close.get("close_event_id"),
        "close_event_at": close.get("close_event_at"),
        "disappeared": bool(disappeared),
        "washer_load_count": load_count,
        "washer_racks": list(loads.get("washer_racks") or []),
        "latest_washer_load_et": loads.get("latest_washer_load_et"),
        **marker,
        "manager_split_decision": mgr_decision,
        "manager_split_decision_at": (mgr or {}).get("at")
        or (mgr or {}).get("manager_split_decision_at"),
        "manager_split_decision_by": (mgr or {}).get("by")
        or (mgr or {}).get("manager_split_decision_by"),
        "manager_split_decision_note": (mgr or {}).get("note")
        or (mgr or {}).get("manager_split_decision_note"),
    }


# ---------------------------------------------------------------------------
# Manager decision persistence (survives day rebuild)
# ---------------------------------------------------------------------------


def ensure_split_decision_tables(cursor) -> None:
    global _SPLIT_DECISION_TABLES_READY
    if _SPLIT_DECISION_TABLES_READY:
        return
    if table_exists(cursor, "rinse_wf_bag_split_decisions"):
        _SPLIT_DECISION_TABLES_READY = True
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_wf_bag_split_decisions (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          decision VARCHAR(32) NOT NULL,
          note TEXT NULL,
          decided_by_user_id INT NULL,
          decided_by_display_name VARCHAR(255) NULL,
          decided_at DATETIME NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_wf_split_decision (organization_id, shift_date_et, bag_id),
          KEY idx_wf_split_decision_day (organization_id, shift_date_et, decision)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _SPLIT_DECISION_TABLES_READY = True


def load_manager_split_decisions(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return bag_id → manager decision dict. Survives rebuild (dedicated table)."""
    ensure_split_decision_tables(cursor)
    if not table_exists(cursor, "rinse_wf_bag_split_decisions"):
        return {}
    params: list[Any] = [int(organization_id), shift_date_et]
    sql = """
        SELECT bag_id, decision, note, decided_by_user_id,
               decided_by_display_name, decided_at
        FROM rinse_wf_bag_split_decisions
        WHERE organization_id = %s AND shift_date_et = %s
    """
    if bag_ids is not None:
        ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
        if not ids:
            return {}
        ph = ",".join(["%s"] * len(ids))
        sql += f" AND UPPER(TRIM(bag_id)) IN ({ph})"
        params.extend(ids)
    cursor.execute(sql, tuple(params))
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        out[bid] = {
            "decision": str(row.get("decision") or "").strip().lower(),
            "note": row.get("note"),
            "by": row.get("decided_by_display_name"),
            "by_user_id": row.get("decided_by_user_id"),
            "at": row.get("decided_at"),
            "manager_split_decision": str(row.get("decision") or "").strip().lower(),
            "manager_split_decision_at": row.get("decided_at"),
            "manager_split_decision_by": row.get("decided_by_display_name"),
            "manager_split_decision_note": row.get("note"),
        }
    return out


def save_manager_split_decision(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_id: str,
    *,
    decision: str,
    note: str | None = None,
    decided_by_user_id: int | None = None,
    decided_by_display_name: str | None = None,
    decided_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist MARK AS SPLIT / MARK AS NOT SPLIT. Does not fabricate scans."""
    ensure_split_decision_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}
    raw = str(decision or "").strip().lower()
    if raw in ("split", "yes", "true", "1", "manager_split"):
        decided = MANAGER_DECISION_SPLIT
    elif raw in ("not_split", "no", "false", "0", "manager_not_split", "not-split"):
        decided = MANAGER_DECISION_NOT_SPLIT
    else:
        return {"ok": False, "error": "invalid_decision"}
    at = decided_at or business_now().replace(tzinfo=None)
    cursor.execute(
        """
        INSERT INTO rinse_wf_bag_split_decisions (
          organization_id, shift_date_et, bag_id, decision, note,
          decided_by_user_id, decided_by_display_name, decided_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          decision=VALUES(decision),
          note=VALUES(note),
          decided_by_user_id=VALUES(decided_by_user_id),
          decided_by_display_name=VALUES(decided_by_display_name),
          decided_at=VALUES(decided_at)
        """,
        (
            int(organization_id),
            shift_date_et,
            bid,
            decided,
            (str(note).strip() if note else None),
            decided_by_user_id,
            (str(decided_by_display_name).strip() if decided_by_display_name else None),
            at,
        ),
    )
    return {
        "ok": True,
        "bag_id": bid,
        "decision": decided,
        "decided_at": at,
        "decided_by_display_name": decided_by_display_name,
        "note": note,
    }


def clear_manager_split_decision(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_id: str,
) -> bool:
    ensure_split_decision_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_wf_bag_split_decisions"):
        return False
    cursor.execute(
        """
        DELETE FROM rinse_wf_bag_split_decisions
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        """,
        (int(organization_id), shift_date_et, bid),
    )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Day batch + Management / Supply helpers
# ---------------------------------------------------------------------------


def _load_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
               last_location, last_scan, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND UPPER(TRIM(bag_id)) IN ({ph})
        ORDER BY scanned_at_parsed, scan_index, id
        """,
        (int(organization_id), *ids),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid in out:
            out[bid].append(dict(row))
    return out


def evaluate_bags_split(
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    manager_decisions: Mapping[str, Mapping[str, Any]] | None = None,
    disappeared_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch evaluate. Keys are normalized bag ids."""
    mgr = manager_decisions or {}
    disappeared = disappeared_ids or set()
    out: dict[str, dict[str, Any]] = {}
    for raw_id, events in (events_by_bag or {}).items():
        bid = normalize_bag_id(raw_id) or str(raw_id or "").strip()
        if not bid:
            continue
        out[bid] = evaluate_bag_split(
            events,
            bag_id=bid,
            manager_decision=mgr.get(bid),
            disappeared=bid in disappeared,
        )
    return out


def evaluate_day_wf_splits(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
    *,
    disappeared_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Evaluate split for a day membership set (Management / Supply)."""
    ids = [normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)]
    if not ids:
        return {}
    events_by_bag = _load_events_for_bags(cursor, organization_id, ids)
    mgr = load_manager_split_decisions(
        cursor, organization_id, selected_date_et, ids
    )
    disappeared = {
        normalize_bag_id(b) for b in (disappeared_ids or []) if normalize_bag_id(b)
    }
    return evaluate_bags_split(
        events_by_bag,
        manager_decisions=mgr,
        disappeared_ids=disappeared,
    )


def pack_canonical_split_orders(
    evaluations: Mapping[str, Mapping[str, Any]],
    *,
    ctx_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    customers: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """
    Management SPLITS card pack: unique bags with canonical_split=YES.

    Also returns review / pending lists for secondary UI.
    """
    ctx_by_bag = ctx_by_bag or {}
    customers = customers or {}
    confirmed: dict[str, dict[str, Any]] = {}
    review: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}
    confirmed_not: dict[str, dict[str, Any]] = {}

    for bid, ev in sorted((evaluations or {}).items()):
        entry = {
            "bag_id": bid,
            "order_number": bid,
            "customer_name": customers.get(bid),
            "service": (ctx_by_bag.get(bid) or {}).get("service") or "WF",
            "rush": (ctx_by_bag.get(bid) or {}).get("rush"),
            "status": ev.get("state"),
            "split_order": ev.get("canonical_split") is True,
            "canonical_split": ev.get("canonical_split"),
            "split_state": ev.get("state"),
            "split_confirmed": ev.get("canonical_split") is True,
            "split_status": (
                "confirmed"
                if ev.get("canonical_split") is True
                else (
                    "pending"
                    if ev.get("state") == STATE_PENDING
                    else (
                        "review"
                        if ev.get("state") == STATE_REVIEW_REQUIRED
                        else "not_split"
                    )
                )
            ),
            "washer_load_count": ev.get("washer_load_count"),
            "washer_racks": list(ev.get("washer_racks") or []),
            "split_marker_present": ev.get("split_marker_present"),
            "review_reason": ev.get("review_reason"),
            "close_event_purpose": ev.get("close_event_purpose"),
            "close_event_at": ev.get("close_event_at"),
            "manager_split_decision": ev.get("manager_split_decision"),
        }
        if (ctx_by_bag.get(bid) or {}).get("customer_name") and not entry["customer_name"]:
            entry["customer_name"] = (ctx_by_bag.get(bid) or {}).get("customer_name")

        state = ev.get("state")
        if ev.get("canonical_split") is True:
            confirmed[bid] = entry
        elif state == STATE_REVIEW_REQUIRED:
            review[bid] = entry
        elif state == STATE_PENDING:
            pending[bid] = entry
        elif ev.get("canonical_split") is False:
            confirmed_not[bid] = entry

    def _pack(orders: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        ordered = [orders[k] for k in sorted(orders.keys())]
        return {
            "key": key,
            "count": len(ordered),
            "order_count": len(ordered),
            "total_quantity": float(len(ordered)),
            "order_ids": [o["bag_id"] for o in ordered],
            "orders": ordered,
        }

    return {
        "split_orders": _pack(confirmed, "split_orders"),
        "split_review": _pack(review, "split_review"),
        "split_pending": _pack(pending, "split_pending"),
        "confirmed_not_split": _pack(confirmed_not, "confirmed_not_split"),
        "evaluations": dict(evaluations),
    }


def supply_day_finalizable(
    evaluations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Authoritative Supply Usage must NOT finalize while any applicable WF order
    is PENDING or REVIEW_REQUIRED for split.
    """
    pending_ids: list[str] = []
    review_ids: list[str] = []
    finalized_ids: list[str] = []
    for bid, ev in (evaluations or {}).items():
        state = ev.get("state")
        if state == STATE_PENDING:
            pending_ids.append(bid)
        elif state == STATE_REVIEW_REQUIRED:
            review_ids.append(bid)
        elif ev.get("split_finalized"):
            finalized_ids.append(bid)
    finalizable = not pending_ids and not review_ids
    return {
        "finalizable": finalizable,
        "split_pending_count": len(pending_ids),
        "split_review_count": len(review_ids),
        "split_finalized_count": len(finalized_ids),
        "split_pending_ids": sorted(pending_ids),
        "split_review_ids": sorted(review_ids),
        "split_finalized_ids": sorted(finalized_ids),
        "supply_status": "final" if finalizable else "not_final",
        "supply_banner": (
            None
            if finalizable
            else (
                f"Not final · {len(review_ids)} split review"
                f"{'s' if len(review_ids) != 1 else ''}"
                if review_ids and not pending_ids
                else (
                    f"Pending split review · {len(pending_ids) + len(review_ids)} open"
                    if (pending_ids or review_ids)
                    else "Not final"
                )
            )
        ),
    }


def count_canonical_splits_from_events_by_bag(
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    manager_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Chronology / day summary: unique bags with canonical_split=YES."""
    evaluations = evaluate_bags_split(
        events_by_bag, manager_decisions=manager_decisions
    )
    split_ids = sorted(
        bid for bid, ev in evaluations.items() if ev.get("canonical_split") is True
    )
    return {
        "split_bags_washed": len(split_ids),
        "split_bag_ids": split_ids,
        "evaluations": evaluations,
    }


def invalidate_supply_after_split_resolution(
    organization_id: int,
    selected_date_et: date,
) -> None:
    """Clear Management Today supplies cache so summary recomputes immediately."""
    try:
        from backend.management_today import clear_management_today_cache

        clear_management_today_cache(
            int(organization_id), selected_date_et, include_supplies=True
        )
    except Exception:
        pass


def evaluation_to_jsonable(ev: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize datetimes for API payloads."""
    out = dict(ev)
    for key in (
        "lifecycle_anchor_et",
        "close_event_at",
        "split_marker_at",
        "latest_washer_load_et",
        "manager_split_decision_at",
    ):
        val = out.get(key)
        if isinstance(val, datetime):
            out[key] = val.isoformat(sep=" ")
    # Drop heavy wash rows from list payloads.
    out.pop("washer_load_rows", None)
    return out
