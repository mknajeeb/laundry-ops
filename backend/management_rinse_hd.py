"""Management Rinse HD — isolated new operating model.

Entry: first create-workitem-bulk in the current inbound cycle.
Completion: 2nd complete-cleaning else 1st (never garments-reviewed / add-photos).
Items + revenue: canonical writable store = hd_day_bag_production (+ audits).
Manual Mark Complete is a management override — never fabricates Rinse scans.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from backend.business_time import business_now, business_today
from backend.rinse_bulk_workitems import purpose_is_bulk_workitem
from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start
from backend.rinse_scan_purpose import (
    is_complete_cleaning_purpose,
    is_inbound_cycle_reset_purpose,
)
from backend.ta_helpers import table_exists, table_has_column

MONEY_Q = Decimal("0.01")
LOOKBACK_DAYS = 21
COMPLETION_SOURCE_SCAN = "SOURCE_COMPLETE_CLEANING"
COMPLETION_SOURCE_MANAGEMENT = "MANAGEMENT_OVERRIDE"
STATUS_OPEN = "open"
STATUS_COMPLETED = "completed"


def _norm_bag(bag_id: Any) -> str:
    return str(bag_id or "").strip().upper()


def _as_naive(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day)
    if isinstance(dt, str):
        raw = dt.replace("T", " ")[:19]
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def business_date_of(dt: Any) -> date | None:
    """Scan wall times are ET naive — business date is the calendar date of that wall."""
    naive = _as_naive(dt)
    if naive is None:
        return None
    return naive.date()


def current_cycle_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Events after the latest inbound cycle reset (load-in / bag-picked-up / …)."""
    rows = [dict(e) for e in (events or []) if e]
    rows.sort(key=lambda r: (_as_naive(r.get("scanned_at_parsed")) or datetime.min, int(r.get("id") or 0)))
    cut = 0
    for i, row in enumerate(rows):
        if is_inbound_cycle_reset_purpose(row.get("purpose")):
            cut = i + 1
    return rows[cut:]


def select_hd_processing_entry(events: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """First create-workitem-bulk in the current cycle — HD queue entry."""
    for row in current_cycle_events(events):
        if purpose_is_bulk_workitem(row.get("purpose")):
            return row
    return None


def select_hd_completion_event(
    events: Sequence[Mapping[str, Any]],
    *,
    entry_at: Any = None,
) -> dict[str, Any] | None:
    """2nd complete-cleaning else 1st, at/after processing entry. Ignores other purposes."""
    entry_ts = _as_naive(entry_at)
    completes: list[dict[str, Any]] = []
    for row in current_cycle_events(events):
        if not is_complete_cleaning_purpose(row.get("purpose")):
            continue
        ts = _as_naive(row.get("scanned_at_parsed"))
        if entry_ts is not None and ts is not None and ts < entry_ts:
            continue
        completes.append(dict(row))
    completes.sort(key=lambda r: (_as_naive(r.get("scanned_at_parsed")) or datetime.min, int(r.get("id") or 0)))
    if len(completes) >= 2:
        return completes[1]
    if len(completes) == 1:
        return completes[0]
    return None


def bag_looks_hd(events: Sequence[Mapping[str, Any]], service_hint: str | None = None) -> bool:
    if str(service_hint or "").strip().upper() == "HD":
        return True
    for row in events or []:
        purpose = str(row.get("purpose") or "").strip().lower()
        if "workitems-added" in purpose:
            return True
    return False


def _money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def ensure_management_hd_columns(cursor) -> None:
    """Additive columns on hd_day_bag_production for management override completion."""
    from backend.daily_operations_hd import ensure_hd_production_tables
    from backend.ta_helpers import invalidate_schema_cache

    ensure_hd_production_tables(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return
    altered = False
    specs = (
        ("management_completed_at", "DATETIME NULL"),
        ("management_completed_by_user_id", "INT NULL"),
        ("management_completed_by_name", "VARCHAR(255) NULL"),
        ("completion_source", "VARCHAR(64) NULL"),
        ("source_completion_at", "DATETIME NULL"),
        ("source_completion_user_name", "VARCHAR(255) NULL"),
        ("processing_started_at", "DATETIME NULL"),
        ("processing_operator_name", "VARCHAR(255) NULL"),
    )
    for col, ddl in specs:
        if table_has_column(cursor, "hd_day_bag_production", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE hd_day_bag_production ADD COLUMN {col} {ddl}")
            altered = True
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
            altered = True
    if altered:
        invalidate_schema_cache()


def _event_public(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "scan_event_id": int(row["id"]) if row.get("id") is not None else None,
        "at": row.get("scanned_at_parsed"),
        "user_name": row.get("user_name"),
        "purpose": row.get("purpose"),
    }


def resolve_order_state(
    events: Sequence[Mapping[str, Any]],
    *,
    service_hint: str | None = None,
    production: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Derive compact HD order state. None when bag is not in the HD processing queue."""
    if not bag_looks_hd(events, service_hint):
        return None
    entry = select_hd_processing_entry(events)
    if not entry:
        return None
    entry_at = entry.get("scanned_at_parsed")
    source_complete = select_hd_completion_event(events, entry_at=entry_at)
    prod = dict(production or {})
    mgmt_at = prod.get("management_completed_at")
    source_at = source_complete.get("scanned_at_parsed") if source_complete else prod.get("source_completion_at")
    if source_complete:
        completion_source = COMPLETION_SOURCE_SCAN
        completed_at = source_at
        completion_user = source_complete.get("user_name")
    elif mgmt_at:
        completion_source = COMPLETION_SOURCE_MANAGEMENT
        completed_at = mgmt_at
        completion_user = prod.get("management_completed_by_name")
    else:
        completion_source = None
        completed_at = None
        completion_user = None

    status = STATUS_COMPLETED if completed_at else STATUS_OPEN
    return {
        "bag_id": _norm_bag(entry.get("bag_id") or prod.get("bag_id")),
        "status": status,
        "started_at": entry_at,
        "start_operator": entry.get("user_name"),
        "completion_at": completed_at,
        "completion_operator": completion_user,
        "completion_source": completion_source,
        "source_completion_at": source_at,
        "management_completed_at": mgmt_at,
        "items": prod.get("total_items"),
        "revenue": _money(prod.get("revenue")),
        "production_version": int(prod.get("version") or 0),
        "production_status": prod.get("status"),
        "attribution_date_et": business_date_of(completed_at) if completed_at else business_date_of(entry_at),
    }


def order_visible_on_day(order: Mapping[str, Any], selected_date_et: date) -> str | None:
    """Return 'open' / 'completed' if order belongs on the selected business day list."""
    start_day = business_date_of(order.get("started_at"))
    done_day = business_date_of(order.get("completion_at"))
    if done_day == selected_date_et:
        return STATUS_COMPLETED
    if order.get("status") == STATUS_OPEN and start_day is not None and start_day <= selected_date_et:
        return STATUS_OPEN
    # Still open as of selected day if completion is after selected day
    if done_day is not None and done_day > selected_date_et and start_day is not None and start_day <= selected_date_et:
        return STATUS_OPEN
    return None


def _compact_order(order: Mapping[str, Any]) -> dict[str, Any]:
    """List payload — no chronology arrays."""
    return {
        "bag_id": order.get("bag_id"),
        "status": order.get("status"),
        "started_at": order.get("started_at"),
        "start_operator": order.get("start_operator"),
        "completion_at": order.get("completion_at"),
        "completion_operator": order.get("completion_operator"),
        "completion_source": order.get("completion_source"),
        "items": order.get("items"),
        "revenue": order.get("revenue"),
        "production_version": order.get("production_version"),
        "attribution_date_et": (
            order.get("attribution_date_et").isoformat()
            if hasattr(order.get("attribution_date_et"), "isoformat")
            else order.get("attribution_date_et")
        ),
    }


def _load_candidate_events_for_bags(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Load purpose-filtered scans only for known HD candidate bags (fast path)."""
    ids = [_norm_bag(b) for b in bag_ids if _norm_bag(b)]
    if not ids:
        return []
    day_start = naive_et_day_start(selected_date_et - timedelta(days=LOOKBACK_DAYS))
    day_end = naive_et_day_end_exclusive(selected_date_et)
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, bag_id, purpose, scanned_at_parsed, user_name, rack
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IN ({placeholders})
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
          AND (
            LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
            OR LOWER(purpose) LIKE %s
          )
        ORDER BY bag_id ASC, scanned_at_parsed ASC, id ASC
        """,
        (
            int(organization_id),
            *ids,
            day_start,
            day_end,
            "%create-workitem-bulk%",
            "%create-bulk-workitem%",
            "%complete-cleaning%",
            "%workitems-added%",
            "%load-in%",
            "%bag-picked-up%",
            "%received-from-vendor%",
            "%sent-to-vendor%",
        ),
    )
    return [dict(r) for r in (cursor.fetchall() or [])]


def _load_hd_service_hints(cursor, organization_id: int, selected_date_et: date) -> dict[str, str]:
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return {}
    start = selected_date_et - timedelta(days=LOOKBACK_DAYS)
    cursor.execute(
        """
        SELECT bag_id, service_type
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et >= %s
          AND shift_date_et <= %s
          AND UPPER(COALESCE(service_type,'')) = 'HD'
        """,
        (int(organization_id), start, selected_date_et),
    )
    out: dict[str, str] = {}
    for row in cursor.fetchall() or []:
        bid = _norm_bag(row.get("bag_id"))
        if bid:
            out[bid] = "HD"
    return out


def _load_production_by_bag(cursor, organization_id: int, bag_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    ensure_management_hd_columns(cursor)
    ids = [_norm_bag(b) for b in bag_ids if _norm_bag(b)]
    if not ids or not table_exists(cursor, "hd_day_bag_production"):
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT *
        FROM hd_day_bag_production
        WHERE organization_id = %s AND bag_id IN ({placeholders})
        ORDER BY updated_at DESC, id DESC
        """,
        (int(organization_id), *ids),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        bid = _norm_bag(row.get("bag_id"))
        if bid and bid not in out:
            out[bid] = dict(row)
    return out


def build_rinse_hd_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    """Compact Rinse HD day list + summary. No per-order chronology arrays."""
    started = time.perf_counter()
    org = int(organization_id)
    hints = _load_hd_service_hints(cursor, org, selected_date_et)
    candidate_ids = list(hints.keys())
    events = _load_candidate_events_for_bags(cursor, org, selected_date_et, candidate_ids)
    by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        bid = _norm_bag(ev.get("bag_id"))
        if not bid:
            continue
        by_bag.setdefault(bid, []).append(ev)

    production = _load_production_by_bag(cursor, org, list(by_bag.keys()) or candidate_ids)

    open_orders: list[dict[str, Any]] = []
    completed_orders: list[dict[str, Any]] = []
    items_today = 0
    revenue_today = Decimal("0")
    started_today = 0

    for bid, bag_events in by_bag.items():
        state = resolve_order_state(
            bag_events,
            service_hint=hints.get(bid),
            production=production.get(bid),
        )
        if not state:
            continue
        bucket = order_visible_on_day(state, selected_date_et)
        if bucket is None:
            continue
        if business_date_of(state.get("started_at")) == selected_date_et:
            started_today += 1
        compact = _compact_order(state)
        # Open-on-day view: hide future completion so Monday stays OPEN.
        if bucket == STATUS_OPEN:
            compact["status"] = STATUS_OPEN
            compact["completion_at"] = None
            compact["completion_operator"] = None
            compact["completion_source"] = None
            open_orders.append(compact)
        else:
            compact["status"] = STATUS_COMPLETED
            completed_orders.append(compact)
            if state.get("items") is not None:
                items_today += int(state["items"])
            if state.get("revenue") is not None:
                revenue_today += Decimal(str(state["revenue"]))

    open_orders.sort(key=lambda r: (_as_naive(r.get("started_at")) or datetime.min, r.get("bag_id") or ""))
    completed_orders.sort(
        key=lambda r: (_as_naive(r.get("completion_at")) or datetime.min, r.get("bag_id") or ""),
        reverse=True,
    )

    status_key = str(status or "all").strip().lower()
    if status_key == STATUS_OPEN:
        orders = open_orders
    elif status_key in (STATUS_COMPLETED, "complete", "completed"):
        orders = completed_orders
    else:
        orders = open_orders + completed_orders

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {
        "date_et": selected_date_et.isoformat(),
        "generated_at_et": (
            business_now().isoformat(timespec="seconds")
            if business_now().tzinfo
            else business_now().isoformat(timespec="seconds")
        ),
        "summary": {
            "open_orders": len(open_orders),
            "completed_today": len(completed_orders),
            "items_completed_today": items_today,
            "revenue_completed_today": float(revenue_today.quantize(MONEY_Q, rounding=ROUND_HALF_UP)),
            "started_today": started_today,
        },
        "orders": orders,
        "model": {
            "entry": "create-workitem-bulk",
            "completion": "2nd_complete_cleaning_else_1st",
            "items_revenue_table": "hd_day_bag_production",
            "manual_complete": "management override on hd_day_bag_production (no fabricated scan)",
        },
        "_meta": {"elapsed_ms": elapsed_ms, "order_count": len(orders)},
    }


def get_rinse_hd_order_detail(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """Detail on demand — includes filtered chronology for one bag."""
    bid = _norm_bag(bag_id)
    day = selected_date_et or business_today()
    bag_events = _load_candidate_events_for_bags(cursor, organization_id, day, [bid])
    # If lookback missed older start, load bag-scoped events
    if not bag_events:
        cursor.execute(
            """
            SELECT id, bag_id, purpose, scanned_at_parsed, user_name, rack
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id = %s
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), bid),
        )
        bag_events = [dict(r) for r in (cursor.fetchall() or [])]
    hints = _load_hd_service_hints(cursor, organization_id, day)
    production = _load_production_by_bag(cursor, organization_id, [bid]).get(bid)
    state = resolve_order_state(bag_events, service_hint=hints.get(bid), production=production)
    return {
        "bag_id": bid,
        "date_et": day.isoformat(),
        "order": _compact_order(state) if state else None,
        "entry": _event_public(select_hd_processing_entry(bag_events)),
        "completion": _event_public(
            select_hd_completion_event(
                bag_events,
                entry_at=(select_hd_processing_entry(bag_events) or {}).get("scanned_at_parsed"),
            )
        ),
        "production": {
            "items": (production or {}).get("total_items"),
            "revenue": _money((production or {}).get("revenue")),
            "version": int((production or {}).get("version") or 0),
            "status": (production or {}).get("status"),
            "completion_source": (production or {}).get("completion_source"),
            "management_completed_at": (production or {}).get("management_completed_at"),
        }
        if production
        else None,
        "chronology": [
            {
                "id": int(e["id"]) if e.get("id") is not None else None,
                "purpose": e.get("purpose"),
                "at": e.get("scanned_at_parsed"),
                "user_name": e.get("user_name"),
            }
            for e in bag_events
        ],
    }


def save_rinse_hd_items_revenue(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    total_items: Any,
    revenue: Any,
    version: int,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Canonical writable path for HD #items + order revenue → hd_day_bag_production."""
    from backend.daily_operations_hd import (
        ACTION_CREATE,
        ACTION_UPDATE,
        STATUS_COMPLETE,
        STATUS_NOT_RECORDED,
        STATUS_PARTIALLY_RECORDED,
        ensure_hd_production_tables,
    )

    ensure_management_hd_columns(cursor)
    ensure_hd_production_tables(cursor)
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    detail = get_rinse_hd_order_detail(cursor, org, bid, selected_date_et=selected_date_et)
    order = detail.get("order")
    if not order:
        return {"ok": False, "error": "not_in_hd_queue", "status": 400}

    attribution = selected_date_et
    if order.get("completion_at"):
        attribution = business_date_of(order.get("completion_at")) or selected_date_et
    elif order.get("started_at"):
        attribution = business_date_of(order.get("started_at")) or selected_date_et

    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production
        WHERE organization_id=%s AND operations_date_et=%s AND bag_id=%s
        LIMIT 1
        """,
        (org, attribution, bid),
    )
    fact = cursor.fetchone()
    if not fact:
        # Fall back to latest bag fact for versioning continuity
        fact = _load_production_by_bag(cursor, org, [bid]).get(bid)
        if fact and fact.get("operations_date_et") != attribution:
            # Move/upsert onto attribution day — keep simple: update in place if same bag unique allows
            pass

    current_version = int((fact or {}).get("version") or 0)
    if int(version) != current_version:
        return {
            "ok": False,
            "error": "conflict",
            "status": 409,
            "current_version": current_version,
        }

    items_v = None if total_items in (None, "") else int(total_items)
    rev_v = None
    if revenue not in (None, ""):
        rev_v = (Decimal(str(revenue))).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    if items_v is not None and items_v < 0:
        return {"ok": False, "error": "validation_failed", "errors": ["items_negative"]}
    if rev_v is not None and rev_v < 0:
        return {"ok": False, "error": "validation_failed", "errors": ["revenue_negative"]}

    if items_v is not None and rev_v is not None:
        status = STATUS_COMPLETE if order.get("completion_at") else STATUS_PARTIALLY_RECORDED
    elif items_v is not None or rev_v is not None:
        status = STATUS_PARTIALLY_RECORDED
    else:
        status = STATUS_NOT_RECORDED

    new_version = current_version + 1
    entry = detail.get("entry") or {}
    completion = detail.get("completion") or {}

    before = dict(fact) if fact else None
    if fact and str(fact.get("operations_date_et")) == str(attribution):
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              total_items=%s, revenue=%s, status=%s,
              processing_started_at=COALESCE(processing_started_at, %s),
              processing_operator_name=COALESCE(processing_operator_name, %s),
              source_completion_at=COALESCE(%s, source_completion_at),
              source_completion_user_name=COALESCE(%s, source_completion_user_name),
              completion_source=COALESCE(%s, completion_source),
              updated_by_user_id=%s, version=%s
            WHERE id=%s
            """,
            (
                items_v,
                float(rev_v) if rev_v is not None else None,
                status,
                entry.get("at"),
                entry.get("user_name"),
                completion.get("at"),
                completion.get("user_name"),
                COMPLETION_SOURCE_SCAN if completion.get("at") else None,
                actor_user_id,
                new_version,
                int(fact["id"]),
            ),
        )
        action = ACTION_UPDATE
        fact_id = int(fact["id"])
    else:
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production (
              organization_id, operations_date_et, bag_id,
              total_items, revenue, status,
              processing_started_at, processing_operator_name,
              source_completion_at, source_completion_user_name, completion_source,
              created_by_user_id, updated_by_user_id, version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              total_items=VALUES(total_items),
              revenue=VALUES(revenue),
              status=VALUES(status),
              processing_started_at=COALESCE(processing_started_at, VALUES(processing_started_at)),
              processing_operator_name=COALESCE(processing_operator_name, VALUES(processing_operator_name)),
              source_completion_at=COALESCE(VALUES(source_completion_at), source_completion_at),
              source_completion_user_name=COALESCE(VALUES(source_completion_user_name), source_completion_user_name),
              completion_source=COALESCE(VALUES(completion_source), completion_source),
              updated_by_user_id=VALUES(updated_by_user_id),
              version=VALUES(version)
            """,
            (
                org,
                attribution,
                bid,
                items_v,
                float(rev_v) if rev_v is not None else None,
                status,
                entry.get("at"),
                entry.get("user_name"),
                completion.get("at"),
                completion.get("user_name"),
                COMPLETION_SOURCE_SCAN if completion.get("at") else None,
                actor_user_id,
                actor_user_id,
                new_version,
            ),
        )
        action = ACTION_CREATE if not fact else ACTION_UPDATE
        cursor.execute(
            """
            SELECT id FROM hd_day_bag_production
            WHERE organization_id=%s AND operations_date_et=%s AND bag_id=%s
            LIMIT 1
            """,
            (org, attribution, bid),
        )
        fact_id = int((cursor.fetchone() or {}).get("id") or 0)

    if table_exists(cursor, "hd_day_bag_production_audits"):
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production_audits (
              organization_id, operations_date_et, bag_id, production_fact_id,
              action, version_before, version_after, before_json, after_json,
              reason, actor_user_id, actor_display_name
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                org,
                attribution,
                bid,
                fact_id,
                action,
                current_version,
                new_version,
                json.dumps(before, default=str) if before else None,
                json.dumps(
                    {"total_items": items_v, "revenue": float(rev_v) if rev_v is not None else None, "status": status},
                    default=str,
                ),
                "management_rinse_hd_items_revenue",
                actor_user_id,
                actor_display_name,
            ),
        )

    return {
        "ok": True,
        "bag_id": bid,
        "operations_date_et": attribution.isoformat(),
        "total_items": items_v,
        "revenue": float(rev_v) if rev_v is not None else None,
        "version": new_version,
        "status": status,
        "canonical_table": "hd_day_bag_production",
    }


def mark_rinse_hd_complete(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    version: int,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Management Mark Complete — override only; does not insert Rinse scan events."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    detail = get_rinse_hd_order_detail(cursor, org, bid, selected_date_et=selected_date_et)
    order = detail.get("order")
    if not order:
        return {"ok": False, "error": "not_in_hd_queue", "status": 400}
    if detail.get("completion") and detail["completion"].get("at"):
        return {
            "ok": False,
            "error": "source_completion_exists",
            "status": 400,
            "message": "Source complete-cleaning already present; source remains authoritative.",
            "fabricated_scan": False,
        }

    attribution = business_date_of(order.get("started_at")) or selected_date_et
    cursor.execute(
        """
        SELECT id, version, total_items, revenue FROM hd_day_bag_production
        WHERE organization_id=%s AND operations_date_et=%s AND bag_id=%s
        LIMIT 1
        """,
        (org, attribution, bid),
    )
    fact = cursor.fetchone()
    current_version = int((fact or {}).get("version") or 0)
    if int(version) != current_version:
        return {"ok": False, "error": "conflict", "status": 409, "current_version": current_version}

    now = business_now()
    now_naive = now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now
    new_version = current_version + 1
    entry = detail.get("entry") or {}

    if fact:
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              management_completed_at=%s,
              management_completed_by_user_id=%s,
              management_completed_by_name=%s,
              completion_source=%s,
              processing_started_at=COALESCE(processing_started_at, %s),
              processing_operator_name=COALESCE(processing_operator_name, %s),
              updated_by_user_id=%s,
              version=%s
            WHERE id=%s
            """,
            (
                now_naive,
                actor_user_id,
                actor_display_name,
                COMPLETION_SOURCE_MANAGEMENT,
                entry.get("at"),
                entry.get("user_name"),
                actor_user_id,
                new_version,
                int(fact["id"]),
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production (
              organization_id, operations_date_et, bag_id,
              total_items, revenue, status,
              processing_started_at, processing_operator_name,
              management_completed_at, management_completed_by_user_id,
              management_completed_by_name, completion_source,
              created_by_user_id, updated_by_user_id, version
            ) VALUES (%s,%s,%s,%s,%s,'PARTIALLY_RECORDED',%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                org,
                attribution,
                bid,
                order.get("items"),
                order.get("revenue"),
                entry.get("at"),
                entry.get("user_name"),
                now_naive,
                actor_user_id,
                actor_display_name,
                COMPLETION_SOURCE_MANAGEMENT,
                actor_user_id,
                actor_user_id,
                new_version,
            ),
        )

    if table_exists(cursor, "hd_day_bag_production_audits"):
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production_audits (
              organization_id, operations_date_et, bag_id, action,
              version_before, version_after, after_json, reason,
              actor_user_id, actor_display_name
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                org,
                attribution,
                bid,
                "MANAGEMENT_MARK_COMPLETE",
                current_version,
                new_version,
                json.dumps(
                    {
                        "management_completed_at": str(now_naive),
                        "completion_source": COMPLETION_SOURCE_MANAGEMENT,
                        "fabricated_scan": False,
                    }
                ),
                "management_rinse_hd_mark_complete",
                actor_user_id,
                actor_display_name,
            ),
        )

    return {
        "ok": True,
        "bag_id": bid,
        "completion_source": COMPLETION_SOURCE_MANAGEMENT,
        "management_completed_at": now_naive,
        "fabricated_scan": False,
        "version": new_version,
        "canonical_table": "hd_day_bag_production",
    }
