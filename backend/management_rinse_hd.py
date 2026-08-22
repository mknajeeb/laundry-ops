"""Management Rinse HD — wash → fold → entry → Complete workflow.

Status model:
  pending_wash → washed → awaiting_entry (folded) → complete

Wash evidence: first create-workitem-bulk in the current inbound cycle.
Fold evidence: 2nd complete-cleaning else 1st (never garments-reviewed / add-photos).
Items + revenue: writable only after fold; autosave is draft; Complete is explicit.
Revenue business date = fold date (server-side).
Canonical store: hd_day_bag_production (+ audits). Never fabricates Rinse scans.
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

# Hard production cutoff — new HD Management/Mobile workflow starts this ET day.
# Pre-activation membership / scans must not appear in operational queues.
HD_WORKFLOW_ACTIVATION_DATE = date(2026, 8, 21)
WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED = "PRE_ACTIVATION_EXCLUDED"

# Workflow statuses (API / UI)
STATUS_PENDING_WASH = "pending_wash"
STATUS_WASHED = "washed"
STATUS_AWAITING_ENTRY = "awaiting_entry"
STATUS_COMPLETE = "complete"

# Production row status (legacy COMPLETE / PARTIAL vocabulary on hd_day_bag_production.status)
PROD_NOT_RECORDED = "NOT_RECORDED"
PROD_PARTIAL = "PARTIALLY_RECORDED"
PROD_COMPLETE = "COMPLETE"

ATTR_SOURCE_SCAN = "SCAN"
ATTR_SOURCE_MANAGER = "MANAGER"

ACTION_ATTRIBUTION_EDIT = "ATTRIBUTION_EDIT"
ACTION_EXPLICIT_COMPLETE = "EXPLICIT_COMPLETE"
ACTION_ITEMS_REVENUE = "ITEMS_REVENUE_DRAFT"


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


def select_hd_wash_event(events: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """First create-workitem-bulk in the current cycle — HD wash evidence."""
    for row in current_cycle_events(events):
        if purpose_is_bulk_workitem(row.get("purpose")):
            return row
    return None


# Back-compat aliases used by older tests / callers
select_hd_processing_entry = select_hd_wash_event


def select_hd_fold_event(
    events: Sequence[Mapping[str, Any]],
    *,
    wash_at: Any = None,
) -> dict[str, Any] | None:
    """2nd complete-cleaning else 1st, at/after wash. Ignores other purposes."""
    wash_ts = _as_naive(wash_at)
    completes: list[dict[str, Any]] = []
    for row in current_cycle_events(events):
        if not is_complete_cleaning_purpose(row.get("purpose")):
            continue
        ts = _as_naive(row.get("scanned_at_parsed"))
        if wash_ts is not None and ts is not None and ts < wash_ts:
            continue
        completes.append(dict(row))
    completes.sort(key=lambda r: (_as_naive(r.get("scanned_at_parsed")) or datetime.min, int(r.get("id") or 0)))
    if len(completes) >= 2:
        return completes[1]
    if len(completes) == 1:
        return completes[0]
    return None


select_hd_completion_event = select_hd_fold_event


def bag_looks_hd(events: Sequence[Mapping[str, Any]], service_hint: str | None = None) -> bool:
    if str(service_hint or "").strip().upper() == "HD":
        return True
    for row in events or []:
        purpose = str(row.get("purpose") or "").strip().lower()
        if "workitems-added" in purpose:
            return True
        if purpose_is_bulk_workitem(row.get("purpose")):
            return True
    return False


def _money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def ensure_management_hd_columns(cursor) -> None:
    """Additive columns on hd_day_bag_production for workflow + attribution timestamps."""
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
        ("washed_at", "DATETIME NULL"),
        ("folded_at", "DATETIME NULL"),
        ("workflow_status", "VARCHAR(32) NULL"),
        ("washed_attribution_source", "VARCHAR(32) NULL"),
        ("folded_attribution_source", "VARCHAR(32) NULL"),
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


def _friendly_name(
    *,
    user_id: Any,
    name_snapshot: Any,
    override_name: Any,
    scan_user_name: Any,
    user_names: Mapping[int, str] | None,
) -> str | None:
    if override_name:
        return str(override_name).strip() or None
    uid = None
    try:
        if user_id not in (None, ""):
            uid = int(user_id)
    except (TypeError, ValueError):
        uid = None
    if uid is not None and user_names and uid in user_names:
        return user_names[uid]
    if name_snapshot:
        return str(name_snapshot).strip() or None
    if scan_user_name:
        return str(scan_user_name).strip() or None
    return None


def _map_rinse_name_to_user(
    rinse_name: str | None,
    user_maps: Mapping[str, Mapping[str, Any]],
) -> tuple[int | None, str | None]:
    key = str(rinse_name or "").strip().casefold()
    if not key:
        return None, rinse_name
    mapped = user_maps.get(key) or {}
    uid = mapped.get("user_id")
    try:
        uid_i = int(uid) if uid not in (None, "") else None
    except (TypeError, ValueError):
        uid_i = None
    display = mapped.get("display_name") or rinse_name
    return uid_i, str(display).strip() if display else rinse_name


def derive_workflow_status(
    *,
    washed_at: Any,
    folded_at: Any,
    explicitly_complete: bool,
) -> str:
    if explicitly_complete:
        return STATUS_COMPLETE
    if folded_at:
        return STATUS_AWAITING_ENTRY
    if washed_at:
        return STATUS_WASHED
    return STATUS_PENDING_WASH


def _on_or_after_activation(dt: Any, activation: date | None) -> bool:
    if activation is None:
        return True
    day = business_date_of(dt)
    return day is not None and day >= activation


def resolve_order_state(
    events: Sequence[Mapping[str, Any]],
    *,
    service_hint: str | None = None,
    production: Mapping[str, Any] | None = None,
    user_maps: Mapping[str, Mapping[str, Any]] | None = None,
    user_names: Mapping[int, str] | None = None,
    activation_date: date | None = None,
) -> dict[str, Any] | None:
    """Derive compact HD order state. None when bag is not an HD candidate."""
    if not bag_looks_hd(events, service_hint):
        return None

    prod = dict(production or {})
    if str(prod.get("workflow_status") or "").strip().upper() == WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED:
        return None
    maps = user_maps or {}
    names = user_names or {}

    wash_ev = select_hd_wash_event(events)
    wash_at_scan = wash_ev.get("scanned_at_parsed") if wash_ev else None
    if wash_ev and not _on_or_after_activation(wash_at_scan, activation_date):
        wash_ev = None
        wash_at_scan = None
    fold_ev = select_hd_fold_event(events, wash_at=wash_at_scan)
    fold_at_scan = fold_ev.get("scanned_at_parsed") if fold_ev else None
    if fold_ev and not _on_or_after_activation(fold_at_scan, activation_date):
        fold_ev = None
        fold_at_scan = None

    wash_src = str(prod.get("washed_attribution_source") or "").strip().upper()
    fold_src = str(prod.get("folded_attribution_source") or "").strip().upper()

    # Manager attribution wins when flagged; else prefer persisted then scan.
    if wash_src == ATTR_SOURCE_MANAGER and (prod.get("washed_at") or prod.get("washed_by_user_id")):
        washed_at = prod.get("washed_at")
        washed_uid = prod.get("washed_by_user_id")
        washed_name = _friendly_name(
            user_id=washed_uid,
            name_snapshot=prod.get("washed_by_name_snapshot"),
            override_name=prod.get("washed_by_override_name"),
            scan_user_name=None,
            user_names=names,
        )
        washed_attr_source = ATTR_SOURCE_MANAGER
    else:
        washed_at = prod.get("washed_at") or wash_at_scan
        if wash_ev:
            mapped_uid, mapped_name = _map_rinse_name_to_user(wash_ev.get("user_name"), maps)
            washed_uid = prod.get("washed_by_user_id") or mapped_uid
            washed_name = _friendly_name(
                user_id=washed_uid,
                name_snapshot=prod.get("washed_by_name_snapshot") or mapped_name,
                override_name=prod.get("washed_by_override_name"),
                scan_user_name=wash_ev.get("user_name"),
                user_names=names,
            )
            washed_attr_source = ATTR_SOURCE_SCAN if not prod.get("washed_by_user_id") else (
                wash_src or ATTR_SOURCE_SCAN
            )
        else:
            washed_uid = prod.get("washed_by_user_id")
            washed_name = _friendly_name(
                user_id=washed_uid,
                name_snapshot=prod.get("washed_by_name_snapshot"),
                override_name=prod.get("washed_by_override_name"),
                scan_user_name=None,
                user_names=names,
            )
            washed_attr_source = wash_src or (ATTR_SOURCE_MANAGER if washed_uid else None)

    if fold_src == ATTR_SOURCE_MANAGER and (prod.get("folded_at") or prod.get("folded_by_user_id")):
        folded_at = prod.get("folded_at")
        folded_uid = prod.get("folded_by_user_id")
        folded_name = _friendly_name(
            user_id=folded_uid,
            name_snapshot=prod.get("folded_by_name_snapshot"),
            override_name=prod.get("folded_by_override_name"),
            scan_user_name=None,
            user_names=names,
        )
        folded_attr_source = ATTR_SOURCE_MANAGER
    else:
        folded_at = prod.get("folded_at") or fold_at_scan
        if fold_ev:
            mapped_uid, mapped_name = _map_rinse_name_to_user(fold_ev.get("user_name"), maps)
            folded_uid = prod.get("folded_by_user_id") or mapped_uid
            folded_name = _friendly_name(
                user_id=folded_uid,
                name_snapshot=prod.get("folded_by_name_snapshot") or mapped_name,
                override_name=prod.get("folded_by_override_name"),
                scan_user_name=fold_ev.get("user_name"),
                user_names=names,
            )
            folded_attr_source = ATTR_SOURCE_SCAN if not prod.get("folded_by_user_id") else (
                fold_src or ATTR_SOURCE_SCAN
            )
        else:
            folded_uid = prod.get("folded_by_user_id")
            folded_name = _friendly_name(
                user_id=folded_uid,
                name_snapshot=prod.get("folded_by_name_snapshot"),
                override_name=prod.get("folded_by_override_name"),
                scan_user_name=None,
                user_names=names,
            )
            folded_attr_source = fold_src or (ATTR_SOURCE_MANAGER if folded_uid else None)

    # Activation cutoff: ignore persisted wash/fold before the new workflow starts.
    if activation_date is not None:
        if washed_at and not _on_or_after_activation(washed_at, activation_date):
            washed_at = None
            washed_uid = None
            washed_name = None
            washed_attr_source = None
        if folded_at and not _on_or_after_activation(folded_at, activation_date):
            folded_at = None
            folded_uid = None
            folded_name = None
            folded_attr_source = None
        # Fold requires wash; drop orphan fold if wash was cut.
        if folded_at and not washed_at:
            folded_at = None
            folded_uid = None
            folded_name = None
            folded_attr_source = None

    explicit = bool(prod.get("management_completed_at")) or (
        str(prod.get("workflow_status") or "").strip().lower() == STATUS_COMPLETE
        and str(prod.get("status") or "").strip().upper() == PROD_COMPLETE
    )
    if activation_date is not None and explicit:
        done_at = prod.get("management_completed_at") or folded_at
        if not _on_or_after_activation(done_at, activation_date) and not (
            folded_at and _on_or_after_activation(folded_at, activation_date)
        ):
            explicit = False

    # Legacy COMPLETE without management_completed_at still counts as complete when
    # both items+revenue exist AND fold exists (older saves); prefer explicit flag.
    if (
        not explicit
        and str(prod.get("status") or "").strip().upper() == PROD_COMPLETE
        and prod.get("management_completed_at")
    ):
        explicit = True
        if activation_date is not None and not _on_or_after_activation(
            prod.get("management_completed_at") or folded_at, activation_date
        ):
            explicit = False

    status = derive_workflow_status(
        washed_at=washed_at,
        folded_at=folded_at,
        explicitly_complete=explicit,
    )

    fold_day = business_date_of(folded_at)
    revenue_date = fold_day  # server rule: revenue = fold date

    return {
        "bag_id": _norm_bag(
            (wash_ev or fold_ev or {}).get("bag_id")
            or prod.get("bag_id")
            or ""
        ),
        "status": status,
        "washed_at": washed_at,
        "washed_by_user_id": washed_uid,
        "washed_by_name": washed_name,
        "washed_attribution_source": washed_attr_source,
        "folded_at": folded_at,
        "folded_by_user_id": folded_uid,
        "folded_by_name": folded_name,
        "folded_attribution_source": folded_attr_source,
        "items": prod.get("total_items"),
        "revenue": _money(prod.get("revenue")),
        "revenue_date_et": revenue_date,
        "completion_at": prod.get("management_completed_at") if explicit else None,
        "completion_operator": prod.get("management_completed_by_name") if explicit else None,
        "production_version": int(prod.get("version") or 0),
        "production_status": prod.get("status"),
        "operations_date_et": prod.get("operations_date_et") or revenue_date,
        # legacy fields kept for older mobile clients during transition
        "started_at": washed_at,
        "start_operator": washed_name,
        "completion_source": "EXPLICIT_COMPLETE" if explicit else None,
    }


def order_visible_on_day(
    order: Mapping[str, Any],
    selected_date_et: date,
    *,
    activation_date: date | None = HD_WORKFLOW_ACTIVATION_DATE,
) -> str | None:
    """Return workflow status if order belongs on the selected business day list."""
    if activation_date is not None and selected_date_et < activation_date:
        return None

    status = str(order.get("status") or "")
    wash_day = business_date_of(order.get("washed_at"))
    fold_day = business_date_of(order.get("folded_at"))
    done_day = business_date_of(order.get("completion_at"))
    ops_day = order.get("operations_date_et")
    if hasattr(ops_day, "isoformat"):
        ops_day = ops_day
    elif ops_day:
        try:
            ops_day = date.fromisoformat(str(ops_day)[:10])
        except ValueError:
            ops_day = None

    if activation_date is not None:
        if wash_day is not None and wash_day < activation_date:
            wash_day = None
        if fold_day is not None and fold_day < activation_date:
            fold_day = None
        if done_day is not None and done_day < activation_date:
            done_day = None
        if ops_day is not None and ops_day < activation_date:
            ops_day = None

    if status == STATUS_COMPLETE:
        if done_day == selected_date_et or fold_day == selected_date_et or ops_day == selected_date_et:
            return STATUS_COMPLETE
        return None

    if status == STATUS_AWAITING_ENTRY:
        # Stay visible from fold day forward until Complete
        if fold_day is not None and fold_day <= selected_date_et:
            return STATUS_AWAITING_ENTRY
        return None

    if status == STATUS_WASHED:
        if wash_day is not None and wash_day <= selected_date_et:
            # Not folded yet — still active
            if fold_day is None or fold_day > selected_date_et:
                return STATUS_WASHED
        return None

    # pending_wash: HD candidate not washed — show if membership/ops day covers selected day
    if wash_day is None:
        if ops_day == selected_date_et or ops_day is None:
            # Membership bags without wash stay on selected day when hinted for that window
            return STATUS_PENDING_WASH
        if ops_day is not None and ops_day <= selected_date_et:
            return STATUS_PENDING_WASH
    return None


def _compact_order(order: Mapping[str, Any]) -> dict[str, Any]:
    """List payload — no chronology arrays."""
    rev_date = order.get("revenue_date_et")
    ops_date = order.get("operations_date_et")
    return {
        "bag_id": order.get("bag_id"),
        "status": order.get("status"),
        "washed_at": order.get("washed_at"),
        "washed_by_user_id": order.get("washed_by_user_id"),
        "washed_by_name": order.get("washed_by_name"),
        "folded_at": order.get("folded_at"),
        "folded_by_user_id": order.get("folded_by_user_id"),
        "folded_by_name": order.get("folded_by_name"),
        "items": order.get("items"),
        "revenue": order.get("revenue"),
        "revenue_date_et": rev_date.isoformat() if hasattr(rev_date, "isoformat") else rev_date,
        "completion_at": order.get("completion_at"),
        "completion_operator": order.get("completion_operator"),
        "production_version": order.get("production_version"),
        "operations_date_et": ops_date.isoformat() if hasattr(ops_date, "isoformat") else ops_date,
        # legacy aliases
        "started_at": order.get("washed_at"),
        "start_operator": order.get("washed_by_name"),
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
    if start < HD_WORKFLOW_ACTIVATION_DATE:
        start = HD_WORKFLOW_ACTIVATION_DATE
    if selected_date_et < HD_WORKFLOW_ACTIVATION_DATE:
        return {}
    cursor.execute(
        """
        SELECT bag_id, service_type, shift_date_et
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


def _batch_user_names(cursor, user_ids: Sequence[int]) -> dict[int, str]:
    ids = sorted({int(u) for u in user_ids if u is not None})
    if not ids or not table_exists(cursor, "users"):
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    has_display = table_has_column(cursor, "users", "display_name")
    has_username = table_has_column(cursor, "users", "username")
    cols = ["id"]
    if has_display:
        cols.append("display_name")
    if has_username:
        cols.append("username")
    cursor.execute(
        f"SELECT {', '.join(cols)} FROM users WHERE id IN ({placeholders})",
        tuple(ids),
    )
    out: dict[int, str] = {}
    for row in cursor.fetchall() or []:
        uid = int(row["id"])
        label = None
        if has_display:
            label = row.get("display_name")
        if not label and has_username:
            label = row.get("username")
        if label:
            out[uid] = str(label).strip()
    return out


def _load_user_maps(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    try:
        from backend.rinse_simple_shift_performance import _load_rinse_user_maps

        return _load_rinse_user_maps(cursor, int(organization_id)) or {}
    except Exception:
        return {}


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
    activation = HD_WORKFLOW_ACTIVATION_DATE
    if selected_date_et < activation:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return {
            "date_et": selected_date_et.isoformat(),
            "generated_at_et": business_now().isoformat(timespec="seconds"),
            "summary": {
                "pending_wash": 0,
                "washed": 0,
                "folded": 0,
                "awaiting_entry": 0,
                "complete": 0,
                "items": 0,
                "revenue": 0.0,
                "open_orders": 0,
                "completed_today": 0,
                "items_completed_today": 0,
                "revenue_completed_today": 0.0,
            },
            "counts": {
                STATUS_PENDING_WASH: 0,
                STATUS_WASHED: 0,
                STATUS_AWAITING_ENTRY: 0,
                STATUS_COMPLETE: 0,
            },
            "orders": [],
            "model": {
                "wash": "create-workitem-bulk",
                "fold": "2nd_complete_cleaning_else_1st",
                "revenue_date": "fold_date",
                "items_revenue_table": "hd_day_bag_production",
                "complete": "explicit after fold + items + revenue",
                "activation_date_et": activation.isoformat(),
            },
            "_meta": {
                "elapsed_ms": elapsed_ms,
                "order_count": 0,
                "activation_date_et": activation.isoformat(),
            },
        }

    hints = _load_hd_service_hints(cursor, org, selected_date_et)
    candidate_ids = set(hints.keys())

    # Durable admitted production rows (activation+) remain after portal disappearance.
    if table_exists(cursor, "hd_day_bag_production"):
        ensure_management_hd_columns(cursor)
        cursor.execute(
            """
            SELECT bag_id FROM hd_day_bag_production
            WHERE organization_id = %s
              AND COALESCE(workflow_status, '') <> %s
              AND operations_date_et >= %s
              AND (
                operations_date_et = %s
                OR DATE(folded_at) = %s
                OR DATE(washed_at) = %s
                OR DATE(management_completed_at) = %s
              )
            """,
            (
                org,
                WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
                activation,
                selected_date_et,
                selected_date_et,
                selected_date_et,
                selected_date_et,
            ),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if bid:
                candidate_ids.add(bid)

    events = _load_candidate_events_for_bags(cursor, org, selected_date_et, list(candidate_ids))
    by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        bid = _norm_bag(ev.get("bag_id"))
        if not bid:
            continue
        by_bag.setdefault(bid, []).append(ev)
        candidate_ids.add(bid)

    # Bags with HD hint but no scans yet still appear as pending_wash
    for bid in list(candidate_ids):
        by_bag.setdefault(bid, [])

    production = _load_production_by_bag(cursor, org, list(candidate_ids))
    filtered_prod: dict[str, dict[str, Any]] = {}
    for bid, row in production.items():
        if str(row.get("workflow_status") or "").strip().upper() == WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED:
            continue
        ops = row.get("operations_date_et")
        if isinstance(ops, date):
            ops_day = ops
        elif ops:
            try:
                ops_day = date.fromisoformat(str(ops)[:10])
            except ValueError:
                ops_day = None
        else:
            ops_day = None
        if ops_day is not None and ops_day < activation:
            continue
        filtered_prod[bid] = row
    production = filtered_prod
    user_maps = _load_user_maps(cursor, org)

    # First pass: collect user ids for batch name resolve
    uid_seed: set[int] = set()
    for prod in production.values():
        for key in ("washed_by_user_id", "folded_by_user_id"):
            try:
                if prod.get(key) not in (None, ""):
                    uid_seed.add(int(prod[key]))
            except (TypeError, ValueError):
                pass
    for mapped in user_maps.values():
        try:
            if mapped.get("user_id") not in (None, ""):
                uid_seed.add(int(mapped["user_id"]))
        except (TypeError, ValueError):
            pass
    user_names = _batch_user_names(cursor, list(uid_seed))

    buckets: dict[str, list[dict[str, Any]]] = {
        STATUS_PENDING_WASH: [],
        STATUS_WASHED: [],
        STATUS_AWAITING_ENTRY: [],
        STATUS_COMPLETE: [],
    }
    items_complete = 0
    revenue_complete = Decimal("0")
    washed_count = 0
    folded_count = 0

    for bid, bag_events in by_bag.items():
        hint = hints.get(bid) or ("HD" if bid in production else None)
        state = resolve_order_state(
            bag_events,
            service_hint=hint,
            production=production.get(bid),
            user_maps=user_maps,
            user_names=user_names,
            activation_date=activation,
        )
        if not state and (bid in hints or bid in production):
            # Membership / production HD with no wash yet → Pending Wash skeleton
            prod = production.get(bid) or {}
            state = resolve_order_state(
                bag_events,
                service_hint="HD",
                production=prod,
                user_maps=user_maps,
                user_names=user_names,
                activation_date=activation,
            ) or {
                "bag_id": bid,
                "status": STATUS_PENDING_WASH,
                "washed_at": None,
                "washed_by_name": None,
                "folded_at": None,
                "folded_by_name": None,
                "items": prod.get("total_items"),
                "revenue": _money(prod.get("revenue")),
                "production_version": int(prod.get("version") or 0),
                "operations_date_et": selected_date_et,
            }
        if not state:
            continue
        state["bag_id"] = state.get("bag_id") or bid
        if not state.get("operations_date_et"):
            state["operations_date_et"] = selected_date_et

        bucket = order_visible_on_day(state, selected_date_et, activation_date=activation)
        if bucket is None:
            continue
        compact = _compact_order(state)
        compact["status"] = bucket
        buckets.setdefault(bucket, []).append(compact)
        if state.get("washed_at") and business_date_of(state.get("washed_at")) == selected_date_et:
            washed_count += 1
        if state.get("folded_at") and business_date_of(state.get("folded_at")) == selected_date_et:
            folded_count += 1
        if bucket == STATUS_COMPLETE:
            if state.get("items") is not None:
                items_complete += int(state["items"])
            if state.get("revenue") is not None:
                revenue_complete += Decimal(str(state["revenue"]))

    for key in buckets:
        buckets[key].sort(
            key=lambda r: (
                _as_naive(r.get("folded_at") or r.get("washed_at")) or datetime.min,
                r.get("bag_id") or "",
            ),
            reverse=(key == STATUS_COMPLETE),
        )

    status_key = str(status or "all").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "open": STATUS_PENDING_WASH,
        "pending": STATUS_PENDING_WASH,
        "pending_wash": STATUS_PENDING_WASH,
        "washed": STATUS_WASHED,
        "awaiting": STATUS_AWAITING_ENTRY,
        "awaiting_entry": STATUS_AWAITING_ENTRY,
        "folded": STATUS_AWAITING_ENTRY,
        "completed": STATUS_COMPLETE,
        "complete": STATUS_COMPLETE,
    }
    status_key = aliases.get(status_key, status_key)

    if status_key in buckets:
        orders = buckets[status_key]
    else:
        orders = (
            buckets[STATUS_PENDING_WASH]
            + buckets[STATUS_WASHED]
            + buckets[STATUS_AWAITING_ENTRY]
            + buckets[STATUS_COMPLETE]
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {
        "date_et": selected_date_et.isoformat(),
        "generated_at_et": business_now().isoformat(timespec="seconds"),
        "summary": {
            "pending_wash": len(buckets[STATUS_PENDING_WASH]),
            "washed": washed_count,
            "folded": folded_count,
            "awaiting_entry": len(buckets[STATUS_AWAITING_ENTRY]),
            "complete": len(buckets[STATUS_COMPLETE]),
            "items": items_complete,
            "revenue": float(revenue_complete.quantize(MONEY_Q, rounding=ROUND_HALF_UP)),
            # legacy keys
            "open_orders": len(buckets[STATUS_PENDING_WASH]) + len(buckets[STATUS_WASHED]) + len(buckets[STATUS_AWAITING_ENTRY]),
            "completed_today": len(buckets[STATUS_COMPLETE]),
            "items_completed_today": items_complete,
            "revenue_completed_today": float(revenue_complete.quantize(MONEY_Q, rounding=ROUND_HALF_UP)),
        },
        "counts": {
            STATUS_PENDING_WASH: len(buckets[STATUS_PENDING_WASH]),
            STATUS_WASHED: len(buckets[STATUS_WASHED]),
            STATUS_AWAITING_ENTRY: len(buckets[STATUS_AWAITING_ENTRY]),
            STATUS_COMPLETE: len(buckets[STATUS_COMPLETE]),
        },
        "orders": orders,
        "model": {
            "wash": "create-workitem-bulk",
            "fold": "2nd_complete_cleaning_else_1st",
            "revenue_date": "fold_date",
            "items_revenue_table": "hd_day_bag_production",
            "complete": "explicit after fold + items + revenue",
            "activation_date_et": activation.isoformat(),
        },
        "_meta": {
            "elapsed_ms": elapsed_ms,
            "order_count": len(orders),
            "activation_date_et": activation.isoformat(),
        },
    }


def build_rinse_hd_summary(
    cursor,
    organization_id: int,
    *,
    start_et: date,
    end_et: date,
) -> dict[str, Any]:
    """Non-blocking summary for a date range — production aggregates only (fast)."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    if not table_exists(cursor, "hd_day_bag_production"):
        return {
            "start_et": start_et.isoformat(),
            "end_et": end_et.isoformat(),
            "pending_wash": 0,
            "washed": 0,
            "folded": 0,
            "awaiting_entry": 0,
            "complete": 0,
            "items": 0,
            "revenue": 0.0,
        }
    cursor.execute(
        """
        SELECT
          SUM(CASE WHEN COALESCE(workflow_status,'') = 'complete'
                     OR management_completed_at IS NOT NULL THEN 1 ELSE 0 END) AS complete_n,
          SUM(CASE WHEN folded_at IS NOT NULL
                     AND management_completed_at IS NULL
                     AND COALESCE(workflow_status,'') <> 'complete' THEN 1 ELSE 0 END) AS awaiting_n,
          SUM(CASE WHEN washed_at IS NOT NULL
                     AND folded_at IS NULL
                     AND management_completed_at IS NULL THEN 1 ELSE 0 END) AS washed_n,
          SUM(CASE WHEN washed_at IS NULL AND folded_at IS NULL
                     AND management_completed_at IS NULL THEN 1 ELSE 0 END) AS pending_n,
          SUM(CASE WHEN washed_at IS NOT NULL
                     AND DATE(washed_at) BETWEEN %s AND %s THEN 1 ELSE 0 END) AS washed_in_range,
          SUM(CASE WHEN folded_at IS NOT NULL
                     AND DATE(folded_at) BETWEEN %s AND %s THEN 1 ELSE 0 END) AS folded_in_range,
          COALESCE(SUM(CASE WHEN management_completed_at IS NOT NULL
                              OR COALESCE(workflow_status,'') = 'complete'
                            THEN total_items ELSE 0 END), 0) AS items_n,
          COALESCE(SUM(CASE WHEN management_completed_at IS NOT NULL
                              OR COALESCE(workflow_status,'') = 'complete'
                            THEN revenue ELSE 0 END), 0) AS revenue_n
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND COALESCE(workflow_status, '') <> %s
          AND operations_date_et >= %s
          AND (
            operations_date_et BETWEEN %s AND %s
            OR DATE(folded_at) BETWEEN %s AND %s
            OR DATE(washed_at) BETWEEN %s AND %s
            OR DATE(management_completed_at) BETWEEN %s AND %s
          )
        """,
        (
            start_et,
            end_et,
            start_et,
            end_et,
            org,
            WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
            HD_WORKFLOW_ACTIVATION_DATE,
            start_et,
            end_et,
            start_et,
            end_et,
            start_et,
            end_et,
            start_et,
            end_et,
        ),
    )
    row = dict(cursor.fetchone() or {})
    return {
        "start_et": start_et.isoformat(),
        "end_et": end_et.isoformat(),
        "pending_wash": int(row.get("pending_n") or 0),
        "washed": int(row.get("washed_in_range") or 0),
        "folded": int(row.get("folded_in_range") or 0),
        "awaiting_entry": int(row.get("awaiting_n") or 0),
        "complete": int(row.get("complete_n") or 0),
        "items": int(row.get("items_n") or 0),
        "revenue": float(Decimal(str(row.get("revenue_n") or 0)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)),
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
    user_maps = _load_user_maps(cursor, organization_id)
    uids: list[int] = []
    if production:
        for key in ("washed_by_user_id", "folded_by_user_id"):
            try:
                if production.get(key) not in (None, ""):
                    uids.append(int(production[key]))
            except (TypeError, ValueError):
                pass
    user_names = _batch_user_names(cursor, uids)
    state = resolve_order_state(
        bag_events,
        service_hint=hints.get(bid) or "HD",
        production=production,
        user_maps=user_maps,
        user_names=user_names,
        activation_date=HD_WORKFLOW_ACTIVATION_DATE if day >= HD_WORKFLOW_ACTIVATION_DATE else None,
    )
    wash = select_hd_wash_event(bag_events)
    if wash and day >= HD_WORKFLOW_ACTIVATION_DATE and not _on_or_after_activation(
        wash.get("scanned_at_parsed"), HD_WORKFLOW_ACTIVATION_DATE
    ):
        wash = None
    fold = select_hd_fold_event(
        bag_events,
        wash_at=(wash or {}).get("scanned_at_parsed"),
    )
    if fold and day >= HD_WORKFLOW_ACTIVATION_DATE and not _on_or_after_activation(
        fold.get("scanned_at_parsed"), HD_WORKFLOW_ACTIVATION_DATE
    ):
        fold = None
    employees = []
    try:
        from backend.daily_operations_hd import list_org_employee_options

        employees = list_org_employee_options(cursor, int(organization_id))
    except Exception:
        employees = []
    return {
        "bag_id": bid,
        "date_et": day.isoformat(),
        "order": _compact_order(state) if state else None,
        "wash": _event_public(wash),
        "fold": _event_public(fold),
        "entry": _event_public(wash),  # legacy alias
        "completion": _event_public(fold),  # legacy alias = fold evidence, not Complete
        "production": {
            "items": (production or {}).get("total_items"),
            "revenue": _money((production or {}).get("revenue")),
            "version": int((production or {}).get("version") or 0),
            "status": (production or {}).get("status"),
            "workflow_status": (production or {}).get("workflow_status")
            or (state or {}).get("status"),
            "washed_at": (production or {}).get("washed_at") or (state or {}).get("washed_at"),
            "folded_at": (production or {}).get("folded_at") or (state or {}).get("folded_at"),
            "washed_by_user_id": (state or {}).get("washed_by_user_id"),
            "folded_by_user_id": (state or {}).get("folded_by_user_id"),
            "washed_by_name": (state or {}).get("washed_by_name"),
            "folded_by_name": (state or {}).get("folded_by_name"),
            "management_completed_at": (production or {}).get("management_completed_at"),
            "operations_date_et": (
                (production or {}).get("operations_date_et").isoformat()
                if hasattr((production or {}).get("operations_date_et"), "isoformat")
                else (production or {}).get("operations_date_et")
            ),
            "revenue_date_et": (
                (state or {}).get("revenue_date_et").isoformat()
                if hasattr((state or {}).get("revenue_date_et"), "isoformat")
                else (state or {}).get("revenue_date_et")
            ),
        }
        if production or state
        else None,
        "employees": employees,
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


def _ensure_production_row_for_fold_date(
    cursor,
    *,
    org: int,
    bid: str,
    fold_date: date,
    actor_user_id: int | None,
) -> dict[str, Any]:
    """Get or create production row keyed by fold-date revenue attribution."""
    ensure_management_hd_columns(cursor)
    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production
        WHERE organization_id=%s AND operations_date_et=%s AND bag_id=%s
        LIMIT 1
        """,
        (org, fold_date, bid),
    )
    fact = cursor.fetchone()
    if fact:
        return dict(fact)
    # Prefer latest existing bag row (may need re-key to fold date)
    existing = _load_production_by_bag(cursor, org, [bid]).get(bid)
    if existing:
        existing_ops = existing.get("operations_date_et")
        if hasattr(existing_ops, "isoformat"):
            existing_day = existing_ops
        else:
            try:
                existing_day = date.fromisoformat(str(existing_ops)[:10]) if existing_ops else None
            except ValueError:
                existing_day = None
        if existing_day == fold_date:
            return existing
        # Move row onto fold date when unique key allows
        cursor.execute(
            """
            UPDATE hd_day_bag_production
            SET operations_date_et=%s
            WHERE id=%s
            """,
            (fold_date, int(existing["id"])),
        )
        existing["operations_date_et"] = fold_date
        return existing
    cursor.execute(
        """
        INSERT INTO hd_day_bag_production (
          organization_id, operations_date_et, bag_id, status,
          created_by_user_id, updated_by_user_id, version, workflow_status
        ) VALUES (%s,%s,%s,%s,%s,%s,1,%s)
        """,
        (org, fold_date, bid, PROD_NOT_RECORDED, actor_user_id, actor_user_id, STATUS_PENDING_WASH),
    )
    cursor.execute(
        """
        SELECT * FROM hd_day_bag_production
        WHERE organization_id=%s AND operations_date_et=%s AND bag_id=%s
        LIMIT 1
        """,
        (org, fold_date, bid),
    )
    return dict(cursor.fetchone() or {})


def _sync_scan_attribution_onto_fact(
    cursor,
    fact: Mapping[str, Any],
    detail: Mapping[str, Any],
    *,
    actor_user_id: int | None,
) -> None:
    """Persist wash/fold scan evidence onto the production row when not manager-locked."""
    order = detail.get("order") or {}
    wash = detail.get("wash") or detail.get("entry") or {}
    fold = detail.get("fold") or detail.get("completion") or {}
    wash_src = str(fact.get("washed_attribution_source") or "").strip().upper()
    fold_src = str(fact.get("folded_attribution_source") or "").strip().upper()

    washed_at = fact.get("washed_at")
    washed_uid = fact.get("washed_by_user_id")
    washed_name = fact.get("washed_by_name_snapshot")
    if wash_src != ATTR_SOURCE_MANAGER:
        washed_at = washed_at or wash.get("at") or order.get("washed_at")
        washed_uid = washed_uid or order.get("washed_by_user_id")
        washed_name = washed_name or order.get("washed_by_name") or wash.get("user_name")

    folded_at = fact.get("folded_at")
    folded_uid = fact.get("folded_by_user_id")
    folded_name = fact.get("folded_by_name_snapshot")
    if fold_src != ATTR_SOURCE_MANAGER:
        folded_at = folded_at or fold.get("at") or order.get("folded_at")
        folded_uid = folded_uid or order.get("folded_by_user_id")
        folded_name = folded_name or order.get("folded_by_name") or fold.get("user_name")

    washed_date = business_date_of(washed_at)
    folded_date = business_date_of(folded_at)
    explicit = bool(fact.get("management_completed_at"))
    wf = derive_workflow_status(
        washed_at=washed_at,
        folded_at=folded_at,
        explicitly_complete=explicit,
    )
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          washed_at=COALESCE(%s, washed_at),
          washed_by_user_id=COALESCE(%s, washed_by_user_id),
          washed_by_name_snapshot=COALESCE(%s, washed_by_name_snapshot),
          washed_date_et=COALESCE(%s, washed_date_et),
          washed_attribution_source=COALESCE(washed_attribution_source, %s),
          folded_at=COALESCE(%s, folded_at),
          folded_by_user_id=COALESCE(%s, folded_by_user_id),
          folded_by_name_snapshot=COALESCE(%s, folded_by_name_snapshot),
          folded_date_et=COALESCE(%s, folded_date_et),
          folded_attribution_source=COALESCE(folded_attribution_source, %s),
          source_completion_at=COALESCE(%s, source_completion_at),
          source_completion_user_name=COALESCE(%s, source_completion_user_name),
          processing_started_at=COALESCE(processing_started_at, %s),
          processing_operator_name=COALESCE(processing_operator_name, %s),
          workflow_status=%s,
          updated_by_user_id=COALESCE(%s, updated_by_user_id)
        WHERE id=%s
        """,
        (
            washed_at,
            washed_uid,
            washed_name,
            washed_date,
            ATTR_SOURCE_SCAN if washed_at else None,
            folded_at,
            folded_uid,
            folded_name,
            folded_date,
            ATTR_SOURCE_SCAN if folded_at else None,
            fold.get("at"),
            fold.get("user_name"),
            wash.get("at"),
            wash.get("user_name"),
            wf,
            actor_user_id,
            int(fact["id"]),
        ),
    )


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
    """Draft save of HD #items + revenue. Does NOT mark Complete. Requires fold."""
    from backend.daily_operations_hd import ACTION_CREATE, ACTION_UPDATE

    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    detail = get_rinse_hd_order_detail(cursor, org, bid, selected_date_et=selected_date_et)
    order = detail.get("order")
    if not order:
        return {"ok": False, "error": "not_in_hd_queue", "status": 400}

    folded_at = order.get("folded_at") or (detail.get("fold") or {}).get("at")
    if not folded_at:
        return {
            "ok": False,
            "error": "not_folded",
            "status": 400,
            "message": "Items/revenue entry allowed only after Folded / Awaiting Entry.",
        }

    fold_date = business_date_of(folded_at) or selected_date_et
    fact = _ensure_production_row_for_fold_date(
        cursor, org=org, bid=bid, fold_date=fold_date, actor_user_id=actor_user_id
    )
    _sync_scan_attribution_onto_fact(cursor, fact, detail, actor_user_id=actor_user_id)
    # Reload after sync
    cursor.execute("SELECT * FROM hd_day_bag_production WHERE id=%s", (int(fact["id"]),))
    fact = dict(cursor.fetchone() or fact)

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

    # Autosave is always draft — never COMPLETE
    if items_v is not None or rev_v is not None:
        prod_status = PROD_PARTIAL
    else:
        prod_status = PROD_NOT_RECORDED
    wf = STATUS_AWAITING_ENTRY
    if fact.get("management_completed_at"):
        # Editing after complete demotes to draft awaiting re-complete
        wf = STATUS_AWAITING_ENTRY
        cursor.execute(
            """
            UPDATE hd_day_bag_production SET
              management_completed_at=NULL,
              management_completed_by_user_id=NULL,
              management_completed_by_name=NULL
            WHERE id=%s
            """,
            (int(fact["id"]),),
        )

    new_version = current_version + 1
    before = dict(fact)
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          total_items=%s, revenue=%s, status=%s,
          workflow_status=%s,
          operations_date_et=%s,
          updated_by_user_id=%s, version=%s
        WHERE id=%s
        """,
        (
            items_v,
            float(rev_v) if rev_v is not None else None,
            prod_status,
            wf,
            fold_date,
            actor_user_id,
            new_version,
            int(fact["id"]),
        ),
    )
    action = ACTION_UPDATE if before.get("id") else ACTION_CREATE
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
                fold_date,
                bid,
                int(fact["id"]),
                ACTION_ITEMS_REVENUE,
                current_version,
                new_version,
                json.dumps(before, default=str),
                json.dumps(
                    {
                        "total_items": items_v,
                        "revenue": float(rev_v) if rev_v is not None else None,
                        "status": prod_status,
                        "workflow_status": wf,
                        "operations_date_et": fold_date.isoformat(),
                    },
                    default=str,
                ),
                "management_rinse_hd_items_revenue_draft",
                actor_user_id,
                actor_display_name,
            ),
        )

    return {
        "ok": True,
        "bag_id": bid,
        "operations_date_et": fold_date.isoformat(),
        "revenue_date_et": fold_date.isoformat(),
        "total_items": items_v,
        "revenue": float(rev_v) if rev_v is not None else None,
        "version": new_version,
        "status": prod_status,
        "workflow_status": wf,
        "complete": False,
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
    """Explicit Complete after fold + items + revenue. Does not fabricate scans."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    detail = get_rinse_hd_order_detail(cursor, org, bid, selected_date_et=selected_date_et)
    order = detail.get("order")
    if not order:
        return {"ok": False, "error": "not_in_hd_queue", "status": 400}

    folded_at = order.get("folded_at") or (detail.get("fold") or {}).get("at")
    if not folded_at:
        return {
            "ok": False,
            "error": "not_folded",
            "status": 400,
            "message": "Complete requires Folded / Awaiting Entry.",
        }

    fold_date = business_date_of(folded_at) or selected_date_et
    fact = _ensure_production_row_for_fold_date(
        cursor, org=org, bid=bid, fold_date=fold_date, actor_user_id=actor_user_id
    )
    _sync_scan_attribution_onto_fact(cursor, fact, detail, actor_user_id=actor_user_id)
    cursor.execute("SELECT * FROM hd_day_bag_production WHERE id=%s", (int(fact["id"]),))
    fact = dict(cursor.fetchone() or fact)

    current_version = int((fact or {}).get("version") or 0)
    if int(version) != current_version:
        return {"ok": False, "error": "conflict", "status": 409, "current_version": current_version}

    items = fact.get("total_items")
    rev = fact.get("revenue")
    if items is None or rev is None:
        return {
            "ok": False,
            "error": "entry_incomplete",
            "status": 400,
            "message": "Complete requires items and revenue.",
            "missing": [
                *(["total_items"] if items is None else []),
                *(["revenue"] if rev is None else []),
            ],
        }

    now = business_now()
    now_naive = now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now
    new_version = current_version + 1
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          status=%s,
          workflow_status=%s,
          operations_date_et=%s,
          management_completed_at=%s,
          management_completed_by_user_id=%s,
          management_completed_by_name=%s,
          completion_source=%s,
          updated_by_user_id=%s,
          version=%s
        WHERE id=%s
        """,
        (
            PROD_COMPLETE,
            STATUS_COMPLETE,
            fold_date,
            now_naive,
            actor_user_id,
            actor_display_name,
            "EXPLICIT_COMPLETE",
            actor_user_id,
            new_version,
            int(fact["id"]),
        ),
    )
    if table_exists(cursor, "hd_day_bag_production_audits"):
        cursor.execute(
            """
            INSERT INTO hd_day_bag_production_audits (
              organization_id, operations_date_et, bag_id, production_fact_id,
              action, version_before, version_after, after_json, reason,
              actor_user_id, actor_display_name
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                org,
                fold_date,
                bid,
                int(fact["id"]),
                ACTION_EXPLICIT_COMPLETE,
                current_version,
                new_version,
                json.dumps(
                    {
                        "management_completed_at": str(now_naive),
                        "workflow_status": STATUS_COMPLETE,
                        "operations_date_et": fold_date.isoformat(),
                        "fabricated_scan": False,
                    }
                ),
                "management_rinse_hd_explicit_complete",
                actor_user_id,
                actor_display_name,
            ),
        )

    return {
        "ok": True,
        "bag_id": bid,
        "workflow_status": STATUS_COMPLETE,
        "operations_date_et": fold_date.isoformat(),
        "revenue_date_et": fold_date.isoformat(),
        "management_completed_at": now_naive,
        "fabricated_scan": False,
        "version": new_version,
        "canonical_table": "hd_day_bag_production",
    }


def update_rinse_hd_attribution(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    selected_date_et: date,
    version: int,
    washed_by_user_id: Any = None,
    washed_at: Any = None,
    folded_by_user_id: Any = None,
    folded_at: Any = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    """Manager edit of wash/fold attribution with audit (old/new/changed by/at)."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    bid = _norm_bag(bag_id)
    detail = get_rinse_hd_order_detail(cursor, org, bid, selected_date_et=selected_date_et)
    order = detail.get("order") or {}

    fold_hint = _as_naive(folded_at) or _as_naive(order.get("folded_at")) or _as_naive(
        (detail.get("fold") or {}).get("at")
    )
    wash_hint = _as_naive(washed_at) or _as_naive(order.get("washed_at")) or _as_naive(
        (detail.get("wash") or {}).get("at")
    )
    fold_date = business_date_of(fold_hint) or business_date_of(wash_hint) or selected_date_et
    fact = _ensure_production_row_for_fold_date(
        cursor, org=org, bid=bid, fold_date=fold_date, actor_user_id=actor_user_id
    )
    current_version = int((fact or {}).get("version") or 0)
    if int(version) != current_version:
        return {"ok": False, "error": "conflict", "status": 409, "current_version": current_version}

    names = _batch_user_names(
        cursor,
        [
            x
            for x in (
                fact.get("washed_by_user_id"),
                fact.get("folded_by_user_id"),
                washed_by_user_id,
                folded_by_user_id,
            )
            if x not in (None, "")
        ],
    )

    def _uid(v):
        if v in (None, ""):
            return None
        return int(v)

    new_washed_uid = _uid(washed_by_user_id) if washed_by_user_id is not None else fact.get("washed_by_user_id")
    new_folded_uid = _uid(folded_by_user_id) if folded_by_user_id is not None else fact.get("folded_by_user_id")
    new_washed_at = _as_naive(washed_at) if washed_at is not None else _as_naive(fact.get("washed_at"))
    new_folded_at = _as_naive(folded_at) if folded_at is not None else _as_naive(fact.get("folded_at"))

    before = {
        "washed_by_user_id": fact.get("washed_by_user_id"),
        "washed_by_name": fact.get("washed_by_name_snapshot"),
        "washed_at": fact.get("washed_at"),
        "folded_by_user_id": fact.get("folded_by_user_id"),
        "folded_by_name": fact.get("folded_by_name_snapshot"),
        "folded_at": fact.get("folded_at"),
    }
    after = {
        "washed_by_user_id": new_washed_uid,
        "washed_by_name": names.get(int(new_washed_uid)) if new_washed_uid else None,
        "washed_at": new_washed_at,
        "folded_by_user_id": new_folded_uid,
        "folded_by_name": names.get(int(new_folded_uid)) if new_folded_uid else None,
        "folded_at": new_folded_at,
    }

    wf = derive_workflow_status(
        washed_at=new_washed_at,
        folded_at=new_folded_at,
        explicitly_complete=bool(fact.get("management_completed_at")),
    )
    # Revenue date follows fold
    ops_date = business_date_of(new_folded_at) or fold_date
    new_version = current_version + 1
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          washed_by_user_id=%s,
          washed_by_name_snapshot=%s,
          washed_at=%s,
          washed_date_et=%s,
          washed_attribution_source=%s,
          folded_by_user_id=%s,
          folded_by_name_snapshot=%s,
          folded_at=%s,
          folded_date_et=%s,
          folded_attribution_source=%s,
          operations_date_et=%s,
          workflow_status=%s,
          updated_by_user_id=%s,
          version=%s
        WHERE id=%s
        """,
        (
            new_washed_uid,
            after["washed_by_name"],
            new_washed_at,
            business_date_of(new_washed_at),
            ATTR_SOURCE_MANAGER,
            new_folded_uid,
            after["folded_by_name"],
            new_folded_at,
            business_date_of(new_folded_at),
            ATTR_SOURCE_MANAGER,
            ops_date,
            wf if not fact.get("management_completed_at") else STATUS_COMPLETE,
            actor_user_id,
            new_version,
            int(fact["id"]),
        ),
    )
    changed_at = business_now()
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
                ops_date,
                bid,
                int(fact["id"]),
                ACTION_ATTRIBUTION_EDIT,
                current_version,
                new_version,
                json.dumps(before, default=str),
                json.dumps(
                    {
                        **after,
                        "changed_by_user_id": actor_user_id,
                        "changed_by_name": actor_display_name,
                        "changed_at": str(changed_at),
                    },
                    default=str,
                ),
                "management_rinse_hd_attribution_edit",
                actor_user_id,
                actor_display_name,
            ),
        )

    return {
        "ok": True,
        "bag_id": bid,
        "version": new_version,
        "before": before,
        "after": after,
        "changed_by_user_id": actor_user_id,
        "changed_by_name": actor_display_name,
        "changed_at": changed_at,
        "workflow_status": wf,
        "operations_date_et": ops_date.isoformat() if ops_date else None,
        "canonical_table": "hd_day_bag_production",
    }


# Back-compat constants referenced by older tests
COMPLETION_SOURCE_SCAN = "SOURCE_COMPLETE_CLEANING"
COMPLETION_SOURCE_MANAGEMENT = "MANAGEMENT_OVERRIDE"
STATUS_OPEN = "open"
STATUS_COMPLETED = "completed"


def soft_quarantine_pre_activation_hd_workflow(cursor, organization_id: int) -> dict[str, Any]:
    """Mark pre-activation HD production rows excluded from the new workflow (no DELETE)."""
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    if not table_exists(cursor, "hd_day_bag_production"):
        return {"updated": 0}
    cursor.execute(
        """
        UPDATE hd_day_bag_production
        SET workflow_status = %s
        WHERE organization_id = %s
          AND operations_date_et < %s
          AND COALESCE(workflow_status, '') <> %s
        """,
        (
            WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
            org,
            HD_WORKFLOW_ACTIVATION_DATE,
            WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
        ),
    )
    return {"updated": int(cursor.rowcount or 0)}


def seed_hd_workflow_opening_day(
    cursor,
    organization_id: int,
    opening_date_et: date | None = None,
    *,
    scrape_run_id: int | None = None,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Admit Aug-21 HD membership into durable production with activation+ state only.

    Opening population = rinse_shift_monitor_day_bags HD for the opening day.
    Wash/fold timestamps come only from scans on/after activation (not historical).
    """
    ensure_management_hd_columns(cursor)
    org = int(organization_id)
    day = opening_date_et or HD_WORKFLOW_ACTIVATION_DATE
    activation = HD_WORKFLOW_ACTIVATION_DATE
    if day < activation:
        return {"ok": False, "error": "opening_date_before_activation", "seeded": 0}

    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        return {"ok": False, "error": "missing_day_bags", "seeded": 0}

    cursor.execute(
        """
        SELECT bag_id
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'HD'
        ORDER BY bag_id
        """,
        (org, day),
    )
    bag_ids = [_norm_bag(r.get("bag_id")) for r in (cursor.fetchall() or []) if _norm_bag(r.get("bag_id"))]
    user_maps = _load_user_maps(cursor, org)
    seeded: list[dict[str, Any]] = []

    for bid in bag_ids:
        events = _load_candidate_events_for_bags(cursor, org, day, [bid])
        state = resolve_order_state(
            events,
            service_hint="HD",
            production=None,
            user_maps=user_maps,
            user_names={},
            activation_date=activation,
        ) or {
            "bag_id": bid,
            "status": STATUS_PENDING_WASH,
            "washed_at": None,
            "folded_at": None,
            "washed_by_user_id": None,
            "folded_by_user_id": None,
            "washed_by_name": None,
            "folded_by_name": None,
            "washed_attribution_source": None,
            "folded_attribution_source": None,
        }

        washed_at = state.get("washed_at")
        folded_at = state.get("folded_at")
        washed_uid = state.get("washed_by_user_id")
        folded_uid = state.get("folded_by_user_id")
        washed_name = state.get("washed_by_name")
        folded_name = state.get("folded_by_name")
        wf = derive_workflow_status(
            washed_at=washed_at,
            folded_at=folded_at,
            explicitly_complete=False,
        )
        # Revenue ops date: fold date when folded, else opening/admission day.
        ops_date = business_date_of(folded_at) or day

        cursor.execute(
            """
            SELECT id, version FROM hd_day_bag_production
            WHERE organization_id=%s AND bag_id=%s AND operations_date_et=%s
            LIMIT 1
            """,
            (org, bid, ops_date),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE hd_day_bag_production SET
                  washed_at=%s,
                  washed_by_user_id=%s,
                  washed_by_name_snapshot=%s,
                  washed_date_et=%s,
                  folded_at=%s,
                  folded_by_user_id=%s,
                  folded_by_name_snapshot=%s,
                  folded_date_et=%s,
                  washed_attribution_source=%s,
                  folded_attribution_source=%s,
                  workflow_status=%s,
                  management_completed_at=NULL,
                  management_completed_by_user_id=NULL,
                  management_completed_by_name=NULL,
                  updated_by_user_id=%s,
                  version=version+1
                WHERE id=%s
                """,
                (
                    washed_at,
                    washed_uid,
                    washed_name,
                    business_date_of(washed_at),
                    folded_at,
                    folded_uid,
                    folded_name,
                    business_date_of(folded_at),
                    state.get("washed_attribution_source") or (ATTR_SOURCE_SCAN if washed_at else None),
                    state.get("folded_attribution_source") or (ATTR_SOURCE_SCAN if folded_at else None),
                    wf,
                    actor_user_id,
                    int(existing["id"]),
                ),
            )
        else:
            # Prefer single durable row per bag for opening: upsert by bag if another ops date exists.
            other = _load_production_by_bag(cursor, org, [bid]).get(bid)
            if other and str(other.get("workflow_status") or "").upper() != WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED:
                cursor.execute(
                    """
                    UPDATE hd_day_bag_production SET
                      operations_date_et=%s,
                      washed_at=%s,
                      washed_by_user_id=%s,
                      washed_by_name_snapshot=%s,
                      washed_date_et=%s,
                      folded_at=%s,
                      folded_by_user_id=%s,
                      folded_by_name_snapshot=%s,
                      folded_date_et=%s,
                      washed_attribution_source=%s,
                      folded_attribution_source=%s,
                      workflow_status=%s,
                      management_completed_at=NULL,
                      management_completed_by_user_id=NULL,
                      management_completed_by_name=NULL,
                      updated_by_user_id=%s,
                      version=version+1
                    WHERE id=%s
                    """,
                    (
                        ops_date,
                        washed_at,
                        washed_uid,
                        washed_name,
                        business_date_of(washed_at),
                        folded_at,
                        folded_uid,
                        folded_name,
                        business_date_of(folded_at),
                        state.get("washed_attribution_source") or (ATTR_SOURCE_SCAN if washed_at else None),
                        state.get("folded_attribution_source") or (ATTR_SOURCE_SCAN if folded_at else None),
                        wf,
                        actor_user_id,
                        int(other["id"]),
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO hd_day_bag_production (
                      organization_id, operations_date_et, bag_id, status, workflow_status,
                      washed_at, washed_by_user_id, washed_by_name_snapshot, washed_date_et,
                      folded_at, folded_by_user_id, folded_by_name_snapshot, folded_date_et,
                      washed_attribution_source, folded_attribution_source,
                      created_by_user_id, updated_by_user_id, version
                    ) VALUES (
                      %s,%s,%s,%s,%s,
                      %s,%s,%s,%s,
                      %s,%s,%s,%s,
                      %s,%s,
                      %s,%s,1
                    )
                    """,
                    (
                        org,
                        ops_date,
                        bid,
                        PROD_NOT_RECORDED,
                        wf,
                        washed_at,
                        washed_uid,
                        washed_name,
                        business_date_of(washed_at),
                        folded_at,
                        folded_uid,
                        folded_name,
                        business_date_of(folded_at),
                        state.get("washed_attribution_source") or (ATTR_SOURCE_SCAN if washed_at else None),
                        state.get("folded_attribution_source") or (ATTR_SOURCE_SCAN if folded_at else None),
                        actor_user_id,
                        actor_user_id,
                    ),
                )
        seeded.append(
            {
                "bag_id": bid,
                "workflow_status": wf,
                "operations_date_et": ops_date.isoformat(),
                "washed_at": str(washed_at) if washed_at else None,
                "folded_at": str(folded_at) if folded_at else None,
            }
        )

    counts = {
        STATUS_PENDING_WASH: sum(1 for s in seeded if s["workflow_status"] == STATUS_PENDING_WASH),
        STATUS_WASHED: sum(1 for s in seeded if s["workflow_status"] == STATUS_WASHED),
        STATUS_AWAITING_ENTRY: sum(1 for s in seeded if s["workflow_status"] == STATUS_AWAITING_ENTRY),
        STATUS_COMPLETE: sum(1 for s in seeded if s["workflow_status"] == STATUS_COMPLETE),
    }
    return {
        "ok": True,
        "opening_date_et": day.isoformat(),
        "activation_date_et": activation.isoformat(),
        "scrape_run_id": scrape_run_id,
        "seeded": len(seeded),
        "counts": counts,
        "orders": seeded,
    }
