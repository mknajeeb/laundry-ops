"""
WF Bulk Workitem maintenance, bag assignments, and review resolution.

Price snapshots are always stored on bag lines. Historical revenue must use
snapshots — never current maintenance prices.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.ta_helpers import table_exists

BULK_PURPOSE_MARKERS = (
    "create-workitem-bulk",
    "create-bulk-workitem",
)

REASON_WF_BULK_WORKITEM_REVIEW = "WF_BULK_WORKITEM_REVIEW"

DEFAULT_WORKITEMS = (
    {"name": "Bath Mat", "current_unit_price": Decimal("4.00"), "display_order": 10},
    {"name": "Comforter", "current_unit_price": Decimal("18.00"), "display_order": 20},
)

RESOLUTION_ITEMS = "items"
RESOLUTION_NO_CHARGE = "no_charge"


def _money(v: Any) -> Decimal:
    try:
        d = Decimal(str(v))
    except Exception:
        d = Decimal("0")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


_BULK_TABLES_READY = False


def ensure_bulk_workitem_tables(cursor) -> None:
    global _BULK_TABLES_READY
    if _BULK_TABLES_READY or table_exists(cursor, "rinse_bulk_workitems"):
        _BULK_TABLES_READY = True
        return
    # Lightweight create if migration not yet applied (matches route bootstrap style).
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bulk_workitems (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          name VARCHAR(255) NOT NULL,
          current_unit_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          active TINYINT(1) NOT NULL DEFAULT 1,
          display_order INT NOT NULL DEFAULT 100,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          created_by_user_id INT NULL,
          created_by_display_name VARCHAR(255) NULL,
          updated_by_user_id INT NULL,
          updated_by_display_name VARCHAR(255) NULL,
          UNIQUE KEY uq_bulk_workitem_org_name (organization_id, name),
          KEY idx_bulk_workitem_org_active (organization_id, active, display_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitems (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          workitem_id BIGINT NULL,
          workitem_name_snapshot VARCHAR(255) NOT NULL,
          unit_price_snapshot DECIMAL(10,2) NOT NULL,
          quantity INT NOT NULL DEFAULT 0,
          line_total DECIMAL(12,2) NOT NULL DEFAULT 0.00,
          entered_by_user_id INT NULL,
          entered_by_display_name VARCHAR(255) NULL,
          entered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_by_user_id INT NULL,
          updated_by_display_name VARCHAR(255) NULL,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          KEY idx_bag_bulk_org_date_bag (organization_id, shift_date_et, bag_id),
          KEY idx_bag_bulk_workitem (organization_id, workitem_id),
          KEY idx_bag_bulk_bag (organization_id, bag_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitem_resolutions (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          resolution_type VARCHAR(32) NOT NULL,
          no_charge_reason VARCHAR(512) NULL,
          items_total DECIMAL(12,2) NULL,
          resolved_by_user_id INT NULL,
          resolved_by_display_name VARCHAR(255) NULL,
          resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_bag_bulk_resolution (organization_id, shift_date_et, bag_id),
          KEY idx_bag_bulk_resolution_date (organization_id, shift_date_et, resolution_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitem_audits (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          shift_date_et DATE NOT NULL,
          bag_id VARCHAR(64) NOT NULL,
          previous_items_json LONGTEXT NULL,
          new_items_json LONGTEXT NULL,
          previous_total DECIMAL(12,2) NULL,
          new_total DECIMAL(12,2) NULL,
          previous_resolution_type VARCHAR(32) NULL,
          new_resolution_type VARCHAR(32) NULL,
          reason TEXT NULL,
          actor_user_id INT NULL,
          actor_display_name VARCHAR(255) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          KEY idx_bag_bulk_audit_bag (organization_id, shift_date_et, bag_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


    _BULK_TABLES_READY = True


def seed_default_workitems(
    cursor,
    organization_id: int,
    *,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> None:
    ensure_bulk_workitem_tables(cursor)
    cursor.execute(
        "SELECT COUNT(*) AS c FROM rinse_bulk_workitems WHERE organization_id = %s",
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    if int(row.get("c") or 0) > 0:
        return
    for item in DEFAULT_WORKITEMS:
        cursor.execute(
            """
            INSERT INTO rinse_bulk_workitems (
              organization_id, name, current_unit_price, active, display_order,
              created_by_user_id, created_by_display_name,
              updated_by_user_id, updated_by_display_name
            ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s)
            """,
            (
                int(organization_id),
                item["name"],
                str(item["current_unit_price"]),
                int(item["display_order"]),
                actor_user_id,
                actor_display_name,
                actor_user_id,
                actor_display_name,
            ),
        )


def list_workitems(
    cursor,
    organization_id: int,
    *,
    include_inactive: bool = True,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    ensure_bulk_workitem_tables(cursor)
    seed_default_workitems(cursor, organization_id)
    sql = """
        SELECT id, organization_id, name, current_unit_price, active, display_order,
               created_at, updated_at, created_by_user_id, created_by_display_name,
               updated_by_user_id, updated_by_display_name
        FROM rinse_bulk_workitems
        WHERE organization_id = %s
    """
    params: list[Any] = [int(organization_id)]
    if active_only or not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY display_order ASC, name ASC"
    cursor.execute(sql, params)
    rows = []
    for r in cursor.fetchall() or []:
        rows.append(_workitem_row(r))
    return rows


def _workitem_row(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "organization_id": int(r["organization_id"]),
        "name": r.get("name"),
        "current_unit_price": float(_money(r.get("current_unit_price"))),
        "active": bool(int(r.get("active") or 0)),
        "display_order": int(r.get("display_order") or 0),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "created_by_user_id": r.get("created_by_user_id"),
        "created_by_display_name": r.get("created_by_display_name"),
        "updated_by_user_id": r.get("updated_by_user_id"),
        "updated_by_display_name": r.get("updated_by_display_name"),
    }


def get_workitem(cursor, organization_id: int, workitem_id: int) -> dict[str, Any] | None:
    ensure_bulk_workitem_tables(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, name, current_unit_price, active, display_order,
               created_at, updated_at, created_by_user_id, created_by_display_name,
               updated_by_user_id, updated_by_display_name
        FROM rinse_bulk_workitems
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(workitem_id)),
    )
    row = cursor.fetchone()
    return _workitem_row(row) if row else None


def create_workitem(
    cursor,
    organization_id: int,
    *,
    name: str,
    current_unit_price: Any,
    display_order: int = 100,
    active: bool = True,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    ensure_bulk_workitem_tables(cursor)
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("name_required")
    price = _money(current_unit_price)
    if price < 0:
        raise ValueError("price_must_be_non_negative")
    cursor.execute(
        """
        INSERT INTO rinse_bulk_workitems (
          organization_id, name, current_unit_price, active, display_order,
          created_by_user_id, created_by_display_name,
          updated_by_user_id, updated_by_display_name
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            nm,
            str(price),
            1 if active else 0,
            int(display_order),
            actor_user_id,
            actor_display_name,
            actor_user_id,
            actor_display_name,
        ),
    )
    wid = int(cursor.lastrowid)
    return get_workitem(cursor, organization_id, wid) or {"id": wid, "name": nm}


def update_workitem(
    cursor,
    organization_id: int,
    workitem_id: int,
    *,
    name: str | None = None,
    current_unit_price: Any = None,
    display_order: int | None = None,
    active: bool | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    existing = get_workitem(cursor, organization_id, workitem_id)
    if not existing:
        raise ValueError("workitem_not_found")
    nm = existing["name"] if name is None else str(name).strip()
    if not nm:
        raise ValueError("name_required")
    price = existing["current_unit_price"] if current_unit_price is None else float(_money(current_unit_price))
    if price < 0:
        raise ValueError("price_must_be_non_negative")
    order = existing["display_order"] if display_order is None else int(display_order)
    is_active = existing["active"] if active is None else bool(active)
    cursor.execute(
        """
        UPDATE rinse_bulk_workitems
        SET name = %s,
            current_unit_price = %s,
            display_order = %s,
            active = %s,
            updated_by_user_id = %s,
            updated_by_display_name = %s
        WHERE organization_id = %s AND id = %s
        """,
        (
            nm,
            str(_money(price)),
            order,
            1 if is_active else 0,
            actor_user_id,
            actor_display_name,
            int(organization_id),
            int(workitem_id),
        ),
    )
    return get_workitem(cursor, organization_id, workitem_id) or existing


def workitem_usage_count(cursor, organization_id: int, workitem_id: int) -> int:
    ensure_bulk_workitem_tables(cursor)
    if not table_exists(cursor, "rinse_bag_bulk_workitems"):
        return 0
    cursor.execute(
        """
        SELECT COUNT(*) AS c
        FROM rinse_bag_bulk_workitems
        WHERE organization_id = %s AND workitem_id = %s
        """,
        (int(organization_id), int(workitem_id)),
    )
    row = cursor.fetchone() or {}
    return int(row.get("c") or 0)


def delete_workitem(cursor, organization_id: int, workitem_id: int) -> dict[str, Any]:
    existing = get_workitem(cursor, organization_id, workitem_id)
    if not existing:
        raise ValueError("workitem_not_found")
    used = workitem_usage_count(cursor, organization_id, workitem_id)
    if used > 0:
        raise ValueError("workitem_in_use_cannot_delete")
    cursor.execute(
        "DELETE FROM rinse_bulk_workitems WHERE organization_id = %s AND id = %s",
        (int(organization_id), int(workitem_id)),
    )
    return {"ok": True, "deleted_id": int(workitem_id)}


def purpose_is_bulk_workitem(purpose: Any) -> bool:
    p = str(purpose or "").strip().lower()
    if not p:
        return False
    return any(m in p for m in BULK_PURPOSE_MARKERS)


def _bulk_event_in_cycle_window(
    ts: datetime | None,
    *,
    cycle_start: datetime | None,
    cycle_end_exclusive: datetime | None,
) -> bool:
    """True when ``cycle_start <= ts < cycle_end`` (open end when end is None)."""
    if ts is None or cycle_start is None:
        return False
    if ts < cycle_start:
        return False
    if cycle_end_exclusive is not None and ts >= cycle_end_exclusive:
        return False
    return True


def load_bulk_workitem_scan_map(
    cursor,
    organization_id: int,
    bag_ids: Iterable[str],
    *,
    selected_date_et: date,
) -> dict[str, dict[str, Any]]:
    """
    Return bag_id → {count, first_at, last_at, employee} for create-workitem-bulk
    scans in the **current resolved workload cycle** for ``selected_date_et``.

    Prior-cycle / lifetime bulk scans are ignored for WF review. Historical rows
    remain in ``rinse_bag_scan_events`` for chronology/audit.

    Cycle window = ``current_cycle_event_window`` from ``resolve_current_cycle``
    (anchor inclusive → next sent-to-vendor exclusive). Not calendar-day bounds.
    """
    from backend.rinse_cycle_boundary import current_cycle_event_window

    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, dict[str, Any]] = {}
    if not ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out

    raw_by_bag: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    chunk = 400
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT id, bag_id, purpose, scanned_at_parsed, user_name
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed IS NOT NULL
              AND (
                LOWER(COALESCE(purpose, '')) LIKE '%%create-workitem-bulk%%'
                OR LOWER(COALESCE(purpose, '')) LIKE '%%create-bulk-workitem%%'
              )
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *part),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid or bid not in raw_by_bag:
                continue
            if not purpose_is_bulk_workitem(row.get("purpose")):
                continue
            raw_by_bag[bid].append(dict(row))

    bags_with_bulk = sorted(b for b, rows in raw_by_bag.items() if rows)
    if not bags_with_bulk:
        return out

    # Full timelines only for bags that have any bulk history — cycle window
    # needs STV anchors from resolve_current_cycle (may cross ET midnight).
    timelines: dict[str, list[dict[str, Any]]] = {b: [] for b in bags_with_bulk}
    for i in range(0, len(bags_with_bulk), chunk):
        part = bags_with_bulk[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT id, bag_id, purpose, rack, user_name, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed IS NOT NULL
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *part),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(row.get("bag_id"))
            if bid in timelines:
                timelines[bid].append(dict(row))

    for bid in bags_with_bulk:
        cycle_start, cycle_end = current_cycle_event_window(
            timelines.get(bid) or [],
            selected_date_et=selected_date_et,
        )
        for row in raw_by_bag.get(bid) or []:
            ts = row.get("scanned_at_parsed")
            if isinstance(ts, datetime) and ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if not _bulk_event_in_cycle_window(
                ts if isinstance(ts, datetime) else None,
                cycle_start=cycle_start,
                cycle_end_exclusive=cycle_end,
            ):
                continue
            info = out.setdefault(
                bid,
                {
                    "count": 0,
                    "first_at": None,
                    "last_at": None,
                    "employee": None,
                    "events": [],
                    "cycle_anchor_at": cycle_start,
                    "next_cycle_anchor_at": cycle_end,
                },
            )
            info["count"] += 1
            if info["first_at"] is None:
                info["first_at"] = ts
                info["employee"] = row.get("user_name")
            info["last_at"] = ts
            if not info.get("employee") and row.get("user_name"):
                info["employee"] = row.get("user_name")
            info["events"].append(
                {
                    "id": row.get("id"),
                    "scanned_at_parsed": ts,
                    "purpose": row.get("purpose"),
                    "user_name": row.get("user_name"),
                }
            )
    return out


def load_bulk_resolutions(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_ids: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    ensure_bulk_workitem_tables(cursor)
    if not table_exists(cursor, "rinse_bag_bulk_workitem_resolutions"):
        return {}
    sql = """
        SELECT bag_id, resolution_type, no_charge_reason, items_total,
               resolved_by_user_id, resolved_by_display_name, resolved_at
        FROM rinse_bag_bulk_workitem_resolutions
        WHERE organization_id = %s AND shift_date_et = %s
    """
    params: list[Any] = [int(organization_id), shift_date_et]
    ids = sorted({normalize_bag_id(b) for b in (bag_ids or []) if normalize_bag_id(b)})
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        sql += f" AND bag_id IN ({placeholders})"
        params.extend(ids)
    cursor.execute(sql, params)
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out[bid] = dict(row)
            out[bid]["bag_id"] = bid
    return out


def load_bag_bulk_lines(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    ensure_bulk_workitem_tables(cursor)
    ids = sorted({normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)})
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    if not ids or not table_exists(cursor, "rinse_bag_bulk_workitems"):
        return out
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, bag_id, workitem_id, workitem_name_snapshot, unit_price_snapshot,
               quantity, line_total, entered_by_display_name, entered_at,
               updated_by_display_name, updated_at
        FROM rinse_bag_bulk_workitems
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id IN ({placeholders})
        ORDER BY id ASC
        """,
        (int(organization_id), shift_date_et, *ids),
    )
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if bid not in out:
            continue
        qty = int(row.get("quantity") or 0)
        unit = float(_money(row.get("unit_price_snapshot")))
        line = float(_money(row.get("line_total") if row.get("line_total") is not None else unit * qty))
        out[bid].append(
            {
                "id": int(row["id"]),
                "workitem_id": int(row["workitem_id"]) if row.get("workitem_id") is not None else None,
                "workitem_name": row.get("workitem_name_snapshot"),
                "unit_price": unit,
                "quantity": qty,
                "line_total": line,
                "entered_by": row.get("entered_by_display_name"),
                "entered_at": row.get("entered_at"),
                "updated_by": row.get("updated_by_display_name"),
                "updated_at": row.get("updated_at"),
            }
        )
    return out


def load_bag_bulk_audits(
    cursor,
    organization_id: int,
    shift_date_et: date,
    bag_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_bulk_workitem_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid or not table_exists(cursor, "rinse_bag_bulk_workitem_audits"):
        return []
    cursor.execute(
        """
        SELECT previous_items_json, new_items_json, previous_total, new_total,
               previous_resolution_type, new_resolution_type, reason,
               actor_display_name, created_at
        FROM rinse_bag_bulk_workitem_audits
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(organization_id), shift_date_et, bid, int(limit)),
    )
    rows = []
    for r in cursor.fetchall() or []:
        rows.append(
            {
                "previous_items": _json_load(r.get("previous_items_json")) or [],
                "new_items": _json_load(r.get("new_items_json")) or [],
                "previous_total": float(_money(r.get("previous_total") or 0)),
                "new_total": float(_money(r.get("new_total") or 0)),
                "previous_resolution_type": r.get("previous_resolution_type"),
                "new_resolution_type": r.get("new_resolution_type"),
                "reason": r.get("reason"),
                "actor_display_name": r.get("actor_display_name"),
                "created_at": r.get("created_at"),
            }
        )
    return rows


def bag_bulk_review_cleared(resolution: Mapping[str, Any] | None, lines: list[dict[str, Any]] | None) -> bool:
    if not resolution:
        # Fallback: items with qty>0 without resolution row still clear
        return any(int(x.get("quantity") or 0) > 0 for x in (lines or []))
    rtype = str(resolution.get("resolution_type") or "").strip().lower()
    if rtype == RESOLUTION_NO_CHARGE:
        return bool(str(resolution.get("no_charge_reason") or "").strip())
    if rtype == RESOLUTION_ITEMS:
        return any(int(x.get("quantity") or 0) > 0 for x in (lines or []))
    return False


def save_bag_bulk_workitems(
    cursor,
    organization_id: int,
    *,
    shift_date_et: date,
    bag_id: str,
    items: list[Mapping[str, Any]] | None,
    no_chargeable: bool = False,
    no_charge_reason: str | None = None,
    reason: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    allow_closed: bool = False,
    allow_empty_clear: bool = False,
    allow_system_audit_reason: bool = False,
) -> dict[str, Any]:
    """
    Save bulk workitem quantities for a bag, or mark no-chargeable.

    Clears WF_BULK_WORKITEM_REVIEW only (other reasons untouched).
    When ``allow_empty_clear`` is True, an empty ``items`` list clears all bag
    bulk lines (used by Edit Bag undo restore to an empty prior state).
    When ``allow_system_audit_reason`` is True, routine item saves may omit a
    free-text reason and use ``WORKITEMS_UPDATED`` for the audit trail.
    """
    from backend.rinse_veewash_shift_day import STATUS_CLOSED, get_day_record

    ensure_bulk_workitem_tables(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}

    # WF-only: reject HD bags (effective service after bulk/registry resolution).
    from backend.rinse_veewash_review import load_registry_service_classification
    from backend.rinse_veewash_workload import SERVICE_HD, SERVICE_WF, _norm_bag

    portal_svc = None
    try:
        cursor.execute(
            """
            SELECT service_type FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id = %s
            LIMIT 1
            """,
            (int(organization_id), bid),
        )
        prow = cursor.fetchone() or {}
        portal_svc = str(prow.get("service_type") or "").strip().upper()
    except Exception:
        portal_svc = None
    reg_map, reg_historical = load_registry_service_classification(
        cursor, organization_id, [bid]
    )
    reg_svc = (reg_map.get(bid) or "").upper()
    # COMPLETED prior-cycle registry must not force HD for current WF portal bags.
    if bid in {_norm_bag(b) for b in reg_historical}:
        reg_svc = ""
    bulk_map = load_bulk_workitem_scan_map(
        cursor, organization_id, [bid], selected_date_et=shift_date_et
    )
    has_bulk = bool(bulk_map.get(bid) and int((bulk_map.get(bid) or {}).get("count") or 0) > 0)
    if has_bulk or reg_svc == SERVICE_WF:
        effective = SERVICE_WF
    elif reg_svc == SERVICE_HD:
        effective = SERVICE_HD
    else:
        effective = portal_svc or SERVICE_WF
    if effective == SERVICE_HD:
        return {
            "ok": False,
            "error": "bulk_workitems_wf_only",
            "message": "Bulk workitem entry is only allowed for WF bags.",
            "service_type": effective,
        }

    day_rec = get_day_record(cursor, organization_id, shift_date_et)
    if day_rec and day_rec.get("status") == STATUS_CLOSED and not allow_closed:
        return {"ok": False, "error": "shift_closed_reopen_required", "day_status": STATUS_CLOSED}

    prior_lines = load_bag_bulk_lines(cursor, organization_id, shift_date_et, [bid]).get(bid) or []
    prior_res = load_bulk_resolutions(cursor, organization_id, shift_date_et, [bid]).get(bid)
    prior_total = sum(float(x.get("line_total") or 0) for x in prior_lines)

    audit_reason = str(reason or no_charge_reason or "").strip()

    if no_chargeable:
        ncr = str(no_charge_reason or "").strip()
        if not ncr:
            return {"ok": False, "error": "no_charge_reason_required"}
        # Clear any item lines for this bag/day
        cursor.execute(
            """
            DELETE FROM rinse_bag_bulk_workitems
            WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
            """,
            (int(organization_id), shift_date_et, bid),
        )
        cursor.execute(
            """
            INSERT INTO rinse_bag_bulk_workitem_resolutions (
              organization_id, shift_date_et, bag_id, resolution_type, no_charge_reason,
              items_total, resolved_by_user_id, resolved_by_display_name, resolved_at
            ) VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              resolution_type = VALUES(resolution_type),
              no_charge_reason = VALUES(no_charge_reason),
              items_total = 0,
              resolved_by_user_id = VALUES(resolved_by_user_id),
              resolved_by_display_name = VALUES(resolved_by_display_name),
              resolved_at = VALUES(resolved_at)
            """,
            (
                int(organization_id),
                shift_date_et,
                bid,
                RESOLUTION_NO_CHARGE,
                ncr,
                actor_user_id,
                actor_display_name,
                datetime.utcnow(),
            ),
        )
        new_lines: list[dict[str, Any]] = []
        new_total = 0.0
        resolution_type = RESOLUTION_NO_CHARGE
        if not audit_reason:
            audit_reason = ncr
    else:
        raw_items = list(items or [])
        built: list[dict[str, Any]] = []
        for raw in raw_items:
            wid = raw.get("workitem_id")
            qty = int(raw.get("quantity") or 0)
            if qty <= 0:
                continue
            wi = get_workitem(cursor, organization_id, int(wid)) if wid is not None else None
            if not wi:
                return {"ok": False, "error": "workitem_not_found", "workitem_id": wid}
            if not wi.get("active"):
                # Allow historical re-save of already-used inactive items only if line exists
                prior_has = any(int(x.get("workitem_id") or -1) == int(wi["id"]) for x in prior_lines)
                if not prior_has:
                    return {"ok": False, "error": "inactive_workitem_cannot_add", "workitem_id": wid}
            unit = _money(wi["current_unit_price"])
            # If editing an existing line for inactive item, keep prior snapshot price
            prior_line = next((x for x in prior_lines if int(x.get("workitem_id") or -1) == int(wi["id"])), None)
            if prior_line and not wi.get("active"):
                unit = _money(prior_line.get("unit_price"))
            line_total = _money(unit * qty)
            built.append(
                {
                    "workitem_id": int(wi["id"]),
                    "workitem_name_snapshot": wi["name"],
                    "unit_price_snapshot": unit,
                    "quantity": qty,
                    "line_total": line_total,
                }
            )
        if not built:
            if allow_empty_clear:
                cursor.execute(
                    """
                    DELETE FROM rinse_bag_bulk_workitems
                    WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                    """,
                    (int(organization_id), shift_date_et, bid),
                )
                cursor.execute(
                    """
                    DELETE FROM rinse_bag_bulk_workitem_resolutions
                    WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                    """,
                    (int(organization_id), shift_date_et, bid),
                )
                new_lines = []
                new_total = 0.0
                resolution_type = RESOLUTION_ITEMS
                if not audit_reason:
                    audit_reason = "clear_bulk_workitems"
            else:
                return {"ok": False, "error": "items_or_no_charge_required"}
        else:
            if not audit_reason:
                if allow_system_audit_reason:
                    audit_reason = "WORKITEMS_UPDATED"
                else:
                    return {"ok": False, "error": "reason_required"}

            cursor.execute(
                """
                DELETE FROM rinse_bag_bulk_workitems
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (int(organization_id), shift_date_et, bid),
            )
            new_total_d = Decimal("0.00")
            for line in built:
                cursor.execute(
                    """
                    INSERT INTO rinse_bag_bulk_workitems (
                      organization_id, shift_date_et, bag_id, workitem_id,
                      workitem_name_snapshot, unit_price_snapshot, quantity, line_total,
                      entered_by_user_id, entered_by_display_name,
                      updated_by_user_id, updated_by_display_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        int(organization_id),
                        shift_date_et,
                        bid,
                        line["workitem_id"],
                        line["workitem_name_snapshot"],
                        str(line["unit_price_snapshot"]),
                        int(line["quantity"]),
                        str(line["line_total"]),
                        actor_user_id,
                        actor_display_name,
                        actor_user_id,
                        actor_display_name,
                    ),
                )
                new_total_d += line["line_total"]
            new_total = float(new_total_d)
            cursor.execute(
                """
                INSERT INTO rinse_bag_bulk_workitem_resolutions (
                  organization_id, shift_date_et, bag_id, resolution_type, no_charge_reason,
                  items_total, resolved_by_user_id, resolved_by_display_name, resolved_at
                ) VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  resolution_type = VALUES(resolution_type),
                  no_charge_reason = NULL,
                  items_total = VALUES(items_total),
                  resolved_by_user_id = VALUES(resolved_by_user_id),
                  resolved_by_display_name = VALUES(resolved_by_display_name),
                  resolved_at = VALUES(resolved_at)
                """,
                (
                    int(organization_id),
                    shift_date_et,
                    bid,
                    RESOLUTION_ITEMS,
                    str(_money(new_total)),
                    actor_user_id,
                    actor_display_name,
                    datetime.utcnow(),
                ),
            )
            new_lines = [
                {
                    "workitem_id": x["workitem_id"],
                    "workitem_name": x["workitem_name_snapshot"],
                    "unit_price": float(x["unit_price_snapshot"]),
                    "quantity": x["quantity"],
                    "line_total": float(x["line_total"]),
                }
                for x in built
            ]
            resolution_type = RESOLUTION_ITEMS

    cursor.execute(
        """
        INSERT INTO rinse_bag_bulk_workitem_audits (
          organization_id, shift_date_et, bag_id,
          previous_items_json, new_items_json,
          previous_total, new_total,
          previous_resolution_type, new_resolution_type,
          reason, actor_user_id, actor_display_name
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            shift_date_et,
            bid,
            _json_dump(prior_lines),
            _json_dump(new_lines),
            str(_money(prior_total)),
            str(_money(new_total)),
            (prior_res or {}).get("resolution_type"),
            resolution_type,
            audit_reason,
            actor_user_id,
            actor_display_name,
        ),
    )

    return {
        "ok": True,
        "bag_id": bid,
        "shift_date_et": shift_date_et.isoformat(),
        "resolution_type": resolution_type,
        "items": new_lines,
        "total": float(_money(new_total)),
        "cleared_reason": REASON_WF_BULK_WORKITEM_REVIEW,
    }


def build_bulk_revenue_rows(
    cursor,
    organization_id: int,
    *,
    shift_date_et: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Revenue feed: quantity × stored unit_price_snapshot (never current price)."""
    ensure_bulk_workitem_tables(cursor)
    if not table_exists(cursor, "rinse_bag_bulk_workitems"):
        return []
    sql = """
        SELECT b.bag_id, b.shift_date_et, b.workitem_name_snapshot, b.unit_price_snapshot,
               b.quantity, b.line_total, b.workitem_id
        FROM rinse_bag_bulk_workitems b
        WHERE b.organization_id = %s AND b.quantity > 0
    """
    params: list[Any] = [int(organization_id)]
    if shift_date_et is not None:
        sql += " AND b.shift_date_et = %s"
        params.append(shift_date_et)
    else:
        if start_date is not None:
            sql += " AND b.shift_date_et >= %s"
            params.append(start_date)
        if end_date is not None:
            sql += " AND b.shift_date_et <= %s"
            params.append(end_date)
    sql += " ORDER BY b.shift_date_et ASC, b.bag_id ASC, b.id ASC"
    cursor.execute(sql, params)
    rows = list(cursor.fetchall() or [])
    bag_ids = sorted({normalize_bag_id(r.get("bag_id")) for r in rows if r.get("bag_id")})
    meta: dict[str, dict[str, Any]] = {}
    if bag_ids and table_exists(cursor, "rinse_cleaner_ticket_presence"):
        placeholders = ",".join(["%s"] * len(bag_ids))
        cursor.execute(
            f"""
            SELECT bag_id, service_type, rush_flag
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (int(organization_id), *bag_ids),
        )
        for r in cursor.fetchall() or []:
            bid = normalize_bag_id(r.get("bag_id"))
            if bid:
                meta[bid] = {
                    "service_type": r.get("service_type"),
                    "rush_flag": r.get("rush_flag"),
                }
    out = []
    for r in rows:
        bid = normalize_bag_id(r.get("bag_id"))
        m = meta.get(bid) or {}
        qty = int(r.get("quantity") or 0)
        unit = float(_money(r.get("unit_price_snapshot")))
        line = float(_money(r.get("line_total") if r.get("line_total") is not None else unit * qty))
        out.append(
            {
                "bag_id": bid,
                "workitem": r.get("workitem_name_snapshot"),
                "workitem_id": int(r["workitem_id"]) if r.get("workitem_id") is not None else None,
                "quantity": qty,
                "unit_price": unit,
                "line_total": line,
                "shift_date_et": str(r.get("shift_date_et"))[:10],
                "rush": m.get("rush_flag"),
                "service": m.get("service_type") or "WF",
            }
        )
    return out
