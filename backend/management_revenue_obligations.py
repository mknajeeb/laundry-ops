"""Management Revenue — obligation / completeness / Missing Work model.

Daily-required sources (Self Service, Drop Off, Rinse WF, Rinse HD) and
schedule-driven DHS accounts produce obligations that resolve to:

  entered | no_activity/excluded | missing

Blank money is never treated as zero. Dispositions are auditable and reversible.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from backend.business_time import business_today
from backend.daily_operations_hd import compute_hd_day_revenue_totals
from backend.daily_revenue_cost import _load_entry_lines, ensure_daily_revenue_cost_tables
from backend.daily_revenue_cost_constants import (
    LK_DROP_OFF_CARD,
    LK_DROP_OFF_CASH,
    LK_RINSE_WF_POUNDS,
    LK_SELF_SERVICE_CARD,
    LK_SELF_SERVICE_CASH,
    commercial_amount_key,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

CADENCE_DAILY = "daily"
CADENCE_SCHEDULED = "scheduled"
CADENCE_OPTIONAL = "optional"

DISP_NO_ACTIVITY = "no_activity"
DISP_EXCLUDED = "excluded"
DISP_NO_PICKUP = "no_pickup"
DISP_RESCHEDULED = "rescheduled"

STATUS_ENTERED = "entered"
STATUS_NO_ACTIVITY = "no_activity"
STATUS_MISSING = "missing"
STATUS_PENDING = "pending"
STATUS_OVERDUE = "overdue"
STATUS_RESCHEDULED = "rescheduled"

DAILY_SOURCES = (
    {"key": "self_service", "label": "Self Service", "account_code": "self_service"},
    {"key": "drop_off", "label": "Drop Off", "account_code": "drop_off"},
    {"key": "rinse_wf", "label": "Rinse WF", "account_code": "rinse_wf"},
    {"key": "rinse_hd", "label": "Rinse HD", "account_code": "rinse_hd"},
)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

LOOKBACK_DAYS = 28
LOOKAHEAD_DAYS = 7


def ensure_obligation_tables(cursor) -> None:
    if not table_exists(cursor, "mgmt_revenue_account_schedules"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mgmt_revenue_account_schedules (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              account_id BIGINT NOT NULL,
              effective_from DATE NOT NULL,
              effective_to DATE NULL,
              pickup_weekdays JSON NULL,
              delivery_weekdays JSON NULL,
              created_by INT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_mgmt_rev_sched_acct (account_id, effective_from),
              INDEX idx_mgmt_rev_sched_active (account_id, effective_from, effective_to)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, "mgmt_revenue_dispositions"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mgmt_revenue_dispositions (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              source_key VARCHAR(64) NOT NULL,
              account_id BIGINT NULL,
              processing_date_et DATE NULL,
              scheduled_pickup_date DATE NULL,
              scheduled_delivery_date DATE NULL,
              disposition VARCHAR(32) NOT NULL,
              reason VARCHAR(255) NULL,
              new_pickup_date DATE NULL,
              metadata_json JSON NULL,
              entered_by_user_id INT NULL,
              entered_by_name_snapshot VARCHAR(255) NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              reversed_at TIMESTAMP NULL,
              reversed_by_user_id INT NULL,
              reversed_by_name_snapshot VARCHAR(255) NULL,
              INDEX idx_mgmt_rev_disp_org_src (organization_id, source_key, processing_date_et),
              INDEX idx_mgmt_rev_disp_pickup (organization_id, account_id, scheduled_pickup_date),
              INDEX idx_mgmt_rev_disp_active (organization_id, reversed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def ensure_account_obligation_columns(cursor) -> None:
    """Additive columns on mgmt_revenue_accounts for cadence."""
    from backend.management_revenue_accounts import ensure_mgmt_revenue_account_tables

    ensure_mgmt_revenue_account_tables(cursor)
    ensure_obligation_tables(cursor)
    if not table_exists(cursor, "mgmt_revenue_accounts"):
        return
    cols = (
        ("entry_cadence", "VARCHAR(16) NULL"),
    )
    altered = False
    for col, ddl in cols:
        if table_has_column(cursor, "mgmt_revenue_accounts", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE mgmt_revenue_accounts ADD COLUMN {col} {ddl}")
            altered = True
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
            altered = True
    if altered:
        invalidate_schema_cache()


def _parse_weekdays(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for x in raw:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 6:
            out.append(n)
    return sorted(set(out))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def dhs_source_key(account_id: int) -> str:
    return f"dhs:{int(account_id)}"


def default_cadence_for_account(acct: dict) -> str:
    existing = (acct.get("entry_cadence") or "").strip().lower()
    if existing in (CADENCE_DAILY, CADENCE_SCHEDULED, CADENCE_OPTIONAL):
        return existing
    code = acct.get("account_code") or ""
    group = acct.get("revenue_group") or ""
    if code in ("self_service", "drop_off", "rinse_wf", "rinse_hd"):
        return CADENCE_DAILY
    if group == "dhs" and acct.get("dr_commercial_account_id"):
        return CADENCE_SCHEDULED
    if group == "dhs" and code == "dhs":
        return CADENCE_OPTIONAL
    return CADENCE_OPTIONAL


def seed_default_cadences_and_schedules(cursor, org_id: int, *, user_id: int | None = None) -> None:
    """Idempotent cadence defaults + empty/seed schedules for DHS children."""
    from backend.management_revenue_accounts import seed_mgmt_revenue_accounts

    ensure_account_obligation_columns(cursor)
    seed_mgmt_revenue_accounts(cursor, org_id, user_id=user_id)
    cursor.execute(
        "SELECT * FROM mgmt_revenue_accounts WHERE organization_id = %s",
        (org_id,),
    )
    accounts = [dict(r) for r in (cursor.fetchall() or [])]
    for acct in accounts:
        cadence = default_cadence_for_account(acct)
        if not acct.get("entry_cadence"):
            cursor.execute(
                "UPDATE mgmt_revenue_accounts SET entry_cadence = %s WHERE id = %s",
                (cadence, acct["id"]),
            )
        if cadence != CADENCE_SCHEDULED or not acct.get("dr_commercial_account_id"):
            continue
        cursor.execute(
            "SELECT id FROM mgmt_revenue_account_schedules WHERE account_id = %s LIMIT 1",
            (acct["id"],),
        )
        if cursor.fetchone():
            continue
        name = (acct.get("name") or "").lower()
        pickup, delivery = [], []
        if "clarkson" in name:
            pickup, delivery = [0, 3], [1, 4]
        elif "skillman" in name:
            pickup, delivery = [1, 4], [2]
        elif "auburn" in name:
            pickup, delivery = [2], [3]
        elif "bedford" in name:
            pickup, delivery = [0, 3], [1, 4]
        elif "bellevue" in name:
            pickup, delivery = [3], [4]
        cursor.execute(
            """
            INSERT INTO mgmt_revenue_account_schedules
              (account_id, effective_from, pickup_weekdays, delivery_weekdays, created_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                acct["id"],
                date(2020, 1, 1),
                json.dumps(pickup) if pickup else None,
                json.dumps(delivery) if delivery else None,
                user_id,
            ),
        )


def get_schedule_for_account(cursor, account_id: int, as_of: date) -> dict[str, Any] | None:
    ensure_obligation_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM mgmt_revenue_account_schedules
        WHERE account_id = %s
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (account_id, as_of, as_of),
    )
    row = cursor.fetchone()
    if not row:
        return None
    r = dict(row)
    return {
        "id": int(r["id"]),
        "account_id": int(r["account_id"]),
        "effective_from": _iso(r.get("effective_from")),
        "effective_to": _iso(r.get("effective_to")),
        "pickup_weekdays": _parse_weekdays(r.get("pickup_weekdays")),
        "delivery_weekdays": _parse_weekdays(r.get("delivery_weekdays")),
    }


def save_account_schedule(
    cursor,
    account_id: int,
    *,
    effective_from: date,
    pickup_weekdays: list[int] | None,
    delivery_weekdays: list[int] | None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Persist multi-select weekday schedule (effective-dated).

    Same-day re-saves UPDATE the existing row for that effective_from so multi-select
    weekdays always stick. Prior open rows with earlier effective_from are closed.
    """
    ensure_obligation_tables(cursor)
    pickup_json = (
        json.dumps(_parse_weekdays(pickup_weekdays)) if pickup_weekdays is not None else None
    )
    delivery_json = (
        json.dumps(_parse_weekdays(delivery_weekdays)) if delivery_weekdays is not None else None
    )

    cursor.execute(
        """
        SELECT id FROM mgmt_revenue_account_schedules
        WHERE account_id = %s AND effective_from = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (account_id, effective_from),
    )
    existing = cursor.fetchone()
    if existing:
        row_id = int(existing["id"] if isinstance(existing, dict) else existing[0])
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET pickup_weekdays = %s, delivery_weekdays = %s, effective_to = NULL
            WHERE id = %s
            """,
            (pickup_json, delivery_json, row_id),
        )
        # Close any other open rows that would compete on this date.
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET effective_to = %s
            WHERE account_id = %s
              AND id <> %s
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to >= %s)
            """,
            (effective_from - timedelta(days=1), account_id, row_id, effective_from, effective_from),
        )
    else:
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET effective_to = %s
            WHERE account_id = %s
              AND effective_from < %s
              AND (effective_to IS NULL OR effective_to >= %s)
            """,
            (effective_from - timedelta(days=1), account_id, effective_from, effective_from),
        )
        cursor.execute(
            """
            INSERT INTO mgmt_revenue_account_schedules
              (account_id, effective_from, pickup_weekdays, delivery_weekdays, created_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (account_id, effective_from, pickup_json, delivery_json, user_id),
        )
    return get_schedule_for_account(cursor, account_id, effective_from) or {}


def derive_dates_from_schedule(
    processing_date: date,
    schedule: dict | None,
) -> dict[str, str | None]:
    """Prefill pickup/delivery relative to processing date using weekly schedule.

    Pickup = most recent scheduled weekday on or before processing date.
    Delivery = next scheduled weekday on or after processing date.
    """
    if not schedule:
        return {"pickup_date": None, "delivery_date": None, "scheduled_pickup_date": None, "scheduled_delivery_date": None}
    pick_days = schedule.get("pickup_weekdays") or []
    del_days = schedule.get("delivery_weekdays") or []
    pickup = None
    delivery = None
    if pick_days:
        for i in range(0, 8):
            d = processing_date - timedelta(days=i)
            if d.weekday() in pick_days:
                pickup = d
                break
    if del_days:
        for i in range(0, 8):
            d = processing_date + timedelta(days=i)
            if d.weekday() in del_days:
                delivery = d
                break
    return {
        "pickup_date": _iso(pickup),
        "delivery_date": _iso(delivery),
        "scheduled_pickup_date": _iso(pickup),
        "scheduled_delivery_date": _iso(delivery),
    }


def _iter_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def scheduled_pickup_dates(schedule: dict | None, start: date, end: date) -> list[date]:
    days = (schedule or {}).get("pickup_weekdays") or []
    if not days:
        return []
    return [d for d in _iter_dates(start, end) if d.weekday() in days]


def _line_present(lines: dict, key: str) -> bool:
    row = lines.get(key)
    if not row:
        return False
    return row.get("amount") is not None or row.get("quantity") is not None


def _load_lines_for_day(cursor, org_id: int, day: date) -> dict:
    ensure_daily_revenue_cost_tables(cursor)
    cursor.execute(
        "SELECT id FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s",
        (org_id, day),
    )
    row = cursor.fetchone()
    if not row:
        return {}
    entry_id = int(row["id"] if isinstance(row, dict) else row[0])
    return _load_entry_lines(cursor, entry_id)


def _active_disposition(
    cursor,
    org_id: int,
    *,
    source_key: str,
    processing_date: date | None = None,
    scheduled_pickup_date: date | None = None,
) -> dict | None:
    ensure_obligation_tables(cursor)
    if scheduled_pickup_date is not None:
        cursor.execute(
            """
            SELECT * FROM mgmt_revenue_dispositions
            WHERE organization_id = %s AND source_key = %s
              AND scheduled_pickup_date = %s AND reversed_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (org_id, source_key, scheduled_pickup_date),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM mgmt_revenue_dispositions
            WHERE organization_id = %s AND source_key = %s
              AND processing_date_et = %s AND reversed_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (org_id, source_key, processing_date),
        )
    row = cursor.fetchone()
    return dict(row) if row else None


def _disposition_public(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "source_key": row.get("source_key"),
        "account_id": int(row["account_id"]) if row.get("account_id") else None,
        "processing_date_et": _iso(row.get("processing_date_et")),
        "scheduled_pickup_date": _iso(row.get("scheduled_pickup_date")),
        "scheduled_delivery_date": _iso(row.get("scheduled_delivery_date")),
        "disposition": row.get("disposition"),
        "reason": row.get("reason"),
        "new_pickup_date": _iso(row.get("new_pickup_date")),
        "entered_by": row.get("entered_by_name_snapshot"),
        "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
    }


def daily_source_entered(cursor, org_id: int, day: date, source_key: str, lines: dict | None = None) -> bool:
    lines = lines if lines is not None else _load_lines_for_day(cursor, org_id, day)
    if source_key == "self_service":
        return _line_present(lines, LK_SELF_SERVICE_CASH) or _line_present(lines, LK_SELF_SERVICE_CARD)
    if source_key == "drop_off":
        return _line_present(lines, LK_DROP_OFF_CASH) or _line_present(lines, LK_DROP_OFF_CARD)
    if source_key == "rinse_wf":
        return _line_present(lines, LK_RINSE_WF_POUNDS)
    if source_key == "rinse_hd":
        hd = compute_hd_day_revenue_totals(cursor, org_id, day)
        orders = int(hd.get("complete") or 0)
        rev = hd.get("complete_hd_revenue")
        if rev is None:
            rev = hd.get("total_hd_revenue")
        return orders > 0 or rev is not None
    return False


def dhs_entry_for_pickup(cursor, org_id: int, account: dict, pickup: date) -> dict | None:
    """Find a DHS commercial line whose snapshot pickup_date matches."""
    cid = account.get("dr_commercial_account_id")
    if not cid:
        return None
    # Scan recent entry days around pickup for matching snapshot
    ensure_daily_revenue_cost_tables(cursor)
    start = pickup - timedelta(days=3)
    end = pickup + timedelta(days=10)
    cursor.execute(
        """
        SELECT e.entry_date, l.amount, l.quantity, l.rate_snapshot_json
        FROM dr_daily_entries e
        JOIN dr_daily_entry_lines l ON l.daily_entry_id = e.id
        WHERE e.organization_id = %s
          AND e.entry_date BETWEEN %s AND %s
          AND l.line_key = %s
        ORDER BY e.entry_date DESC
        """,
        (org_id, start, end, commercial_amount_key(int(cid))),
    )
    for row in cursor.fetchall() or []:
        r = dict(row)
        raw = r.get("rate_snapshot_json")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        snap_pickup = raw.get("pickup_date") or raw.get("scheduled_pickup_date")
        entry_date = r.get("entry_date")
        if hasattr(entry_date, "isoformat"):
            entry_date_d = entry_date
        else:
            entry_date_d = date.fromisoformat(str(entry_date)[:10]) if entry_date else None
        if snap_pickup == pickup.isoformat():
            return {
                "entry_date": _iso(entry_date_d),
                "pickup_date": snap_pickup,
                "processing_date": raw.get("processing_date"),
                "delivery_date": raw.get("delivery_date"),
                "amount": r.get("amount"),
                "quantity": r.get("quantity"),
            }
        # Legacy: entry on pickup day with volume/revenue present
        if entry_date_d == pickup and (r.get("amount") is not None or r.get("quantity") is not None):
            return {
                "entry_date": _iso(entry_date_d),
                "pickup_date": snap_pickup or pickup.isoformat(),
                "processing_date": raw.get("processing_date"),
                "delivery_date": raw.get("delivery_date"),
                "amount": r.get("amount"),
                "quantity": r.get("quantity"),
            }
    return None


def build_daily_completeness(cursor, org_id: int, processing_date: date) -> dict[str, Any]:
    ensure_account_obligation_columns(cursor)
    seed_default_cadences_and_schedules(cursor, org_id)
    lines = _load_lines_for_day(cursor, org_id, processing_date)
    sections = []
    complete = 0
    for src in DAILY_SOURCES:
        key = src["key"]
        entered = daily_source_entered(cursor, org_id, processing_date, key, lines)
        disp = _active_disposition(cursor, org_id, source_key=key, processing_date=processing_date)
        if entered:
            status = STATUS_ENTERED
            complete += 1
        elif disp and disp.get("disposition") in (DISP_NO_ACTIVITY, DISP_EXCLUDED):
            status = STATUS_NO_ACTIVITY
            complete += 1
        else:
            status = STATUS_MISSING
        sections.append({
            "key": key,
            "label": src["label"],
            "status": status,
            "entered": entered,
            "disposition": _disposition_public(disp),
            "entry_target": key,
        })
    return {
        "processing_date_et": processing_date.isoformat(),
        "complete": complete,
        "required": len(DAILY_SOURCES),
        "label": f"{complete}/{len(DAILY_SOURCES)}",
        "sections": sections,
    }


def build_dhs_obligations(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    from backend.management_revenue_accounts import list_accounts

    ensure_account_obligation_columns(cursor)
    seed_default_cadences_and_schedules(cursor, org_id)
    as_of = as_of or business_today()
    start = as_of - timedelta(days=lookback_days)
    accounts = list_accounts(cursor, org_id, as_of=as_of, active_only=True)
    out = []
    for acct in accounts:
        if (acct.get("revenue_group") or "") != "dhs" or not acct.get("dr_commercial_account_id"):
            continue
        if default_cadence_for_account(acct) != CADENCE_SCHEDULED:
            continue
        sched = get_schedule_for_account(cursor, acct["id"], as_of)
        pickups = scheduled_pickup_dates(sched, start, as_of)
        for pickup in pickups:
            # schedule effective on pickup day
            sched_p = get_schedule_for_account(cursor, acct["id"], pickup) or sched
            if pickup.weekday() not in ((sched_p or {}).get("pickup_weekdays") or []):
                continue
            source_key = dhs_source_key(acct["id"])
            disp = _active_disposition(
                cursor, org_id, source_key=source_key, scheduled_pickup_date=pickup,
            )
            entry = dhs_entry_for_pickup(cursor, org_id, acct, pickup)
            derived_delivery = None
            del_days = (sched_p or {}).get("delivery_weekdays") or []
            if del_days:
                for i in range(0, 8):
                    d = pickup + timedelta(days=i)
                    if d.weekday() in del_days:
                        derived_delivery = d
                        break
            if entry:
                status = STATUS_ENTERED
                resolved = True
            elif disp and disp.get("disposition") == DISP_RESCHEDULED:
                status = STATUS_RESCHEDULED
                resolved = True
            elif disp and disp.get("disposition") in (DISP_NO_PICKUP, DISP_EXCLUDED, DISP_NO_ACTIVITY):
                status = STATUS_NO_ACTIVITY
                resolved = True
            elif pickup < as_of:
                status = STATUS_OVERDUE
                resolved = False
            else:
                status = STATUS_PENDING
                resolved = False
            out.append({
                "kind": "dhs",
                "source_key": source_key,
                "account_id": acct["id"],
                "name": acct.get("name") or "DHS",
                "status": status,
                "resolved": resolved,
                "scheduled_pickup_date": pickup.isoformat(),
                "scheduled_delivery_date": _iso(derived_delivery),
                "suggested_processing_date": (pickup + timedelta(days=1)).isoformat(),
                "entry_target": "dhs",
                "disposition": _disposition_public(disp),
                "entry": entry,
            })
    return out


def build_missing_work(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
    filter_kind: str = "all",
) -> dict[str, Any]:
    as_of = as_of or business_today()
    daily = build_daily_completeness(cursor, org_id, as_of)
    daily_missing = [
        {
            "kind": "daily",
            "source_key": s["key"],
            "name": s["label"],
            "status": STATUS_MISSING,
            "processing_date_et": as_of.isoformat(),
            "entry_target": s["entry_target"],
            "overdue": False,
        }
        for s in daily["sections"]
        if s["status"] == STATUS_MISSING
    ]

    dhs_all = build_dhs_obligations(cursor, org_id, as_of=as_of)
    dhs_pending = [r for r in dhs_all if not r.get("resolved")]

    items: list[dict[str, Any]] = []
    fk = (filter_kind or "all").lower()

    if fk == "resolved":
        for row in dhs_all:
            if row.get("resolved"):
                items.append({
                    "kind": "dhs",
                    "source_key": row["source_key"],
                    "account_id": row["account_id"],
                    "name": row["name"],
                    "status": row["status"],
                    "scheduled_pickup_date": row["scheduled_pickup_date"],
                    "entry_target": "dhs",
                    "disposition": row.get("disposition"),
                    "resolved": True,
                })
        for s in daily["sections"]:
            if s["status"] in (STATUS_ENTERED, STATUS_NO_ACTIVITY):
                items.append({
                    "kind": "daily",
                    "source_key": s["key"],
                    "name": s["label"],
                    "status": s["status"],
                    "processing_date_et": as_of.isoformat(),
                    "entry_target": s["entry_target"],
                    "disposition": s.get("disposition"),
                    "resolved": True,
                })
    else:
        items.extend(daily_missing)
        for row in dhs_pending:
            items.append({
                "kind": "dhs",
                "source_key": row["source_key"],
                "account_id": row["account_id"],
                "name": row["name"],
                "status": row["status"],
                "scheduled_pickup_date": row["scheduled_pickup_date"],
                "scheduled_delivery_date": row.get("scheduled_delivery_date"),
                "suggested_processing_date": row.get("suggested_processing_date"),
                "entry_target": "dhs",
                "overdue": row["status"] == STATUS_OVERDUE,
            })
        if fk == "daily":
            items = [i for i in items if i["kind"] == "daily"]
        elif fk == "dhs":
            items = [i for i in items if i["kind"] == "dhs"]
        elif fk == "overdue":
            items = [i for i in items if i.get("overdue") or i.get("status") == STATUS_OVERDUE]

    unresolved = [i for i in items if not i.get("resolved")]
    return {
        "as_of": as_of.isoformat(),
        "filter": fk,
        "summary": {
            "missing_total": len(unresolved) if fk != "resolved" else len(items),
            "daily_missing": len([i for i in unresolved if i["kind"] == "daily"]),
            "dhs_pending": len([i for i in unresolved if i["kind"] == "dhs"]),
            "overdue": len([i for i in unresolved if i.get("overdue") or i.get("status") == STATUS_OVERDUE]),
        },
        "daily_completeness": daily,
        "items": items,
    }


def create_disposition(
    cursor,
    org_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    ensure_obligation_tables(cursor)
    source_key = str(payload.get("source_key") or "").strip()
    disposition = str(payload.get("disposition") or "").strip().lower()
    if disposition not in (DISP_NO_ACTIVITY, DISP_EXCLUDED, DISP_NO_PICKUP, DISP_RESCHEDULED):
        raise ValueError("Invalid disposition")
    if not source_key:
        raise ValueError("source_key is required")

    processing_raw = payload.get("processing_date_et") or payload.get("processing_date")
    pickup_raw = payload.get("scheduled_pickup_date")
    delivery_raw = payload.get("scheduled_delivery_date")
    new_pickup_raw = payload.get("new_pickup_date")

    def _d(v):
        if not v:
            return None
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v)[:10])

    processing_date = _d(processing_raw)
    pickup_date = _d(pickup_raw)
    delivery_date = _d(delivery_raw)
    new_pickup = _d(new_pickup_raw)

    if source_key.startswith("dhs:"):
        if disposition == DISP_RESCHEDULED and not new_pickup:
            raise ValueError("new_pickup_date is required to reschedule")
        if not pickup_date:
            raise ValueError("scheduled_pickup_date is required for DHS dispositions")
    else:
        if not processing_date:
            raise ValueError("processing_date_et is required for daily dispositions")

    account_id = payload.get("account_id")
    if source_key.startswith("dhs:") and not account_id:
        try:
            account_id = int(source_key.split(":", 1)[1])
        except ValueError:
            account_id = None

    meta = {
        "scheduled_pickup_date": _iso(pickup_date),
        "scheduled_delivery_date": _iso(delivery_date),
        "override": bool(payload.get("date_override")),
    }

    cursor.execute(
        """
        INSERT INTO mgmt_revenue_dispositions
          (organization_id, source_key, account_id, processing_date_et,
           scheduled_pickup_date, scheduled_delivery_date, disposition, reason,
           new_pickup_date, metadata_json, entered_by_user_id, entered_by_name_snapshot)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            org_id,
            source_key,
            int(account_id) if account_id else None,
            processing_date,
            pickup_date,
            delivery_date,
            disposition,
            str(payload.get("reason") or "").strip() or None,
            new_pickup,
            json.dumps(meta),
            user_id,
            actor_name,
        ),
    )
    disp_id = int(cursor.lastrowid)
    cursor.execute("SELECT * FROM mgmt_revenue_dispositions WHERE id = %s", (disp_id,))
    return _disposition_public(dict(cursor.fetchone()))


def reverse_disposition(
    cursor,
    org_id: int,
    disposition_id: int,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    ensure_obligation_tables(cursor)
    cursor.execute(
        "SELECT * FROM mgmt_revenue_dispositions WHERE id = %s AND organization_id = %s",
        (disposition_id, org_id),
    )
    row = cursor.fetchone()
    if not row:
        raise LookupError("Disposition not found")
    if row.get("reversed_at"):
        return _disposition_public(dict(row))
    cursor.execute(
        """
        UPDATE mgmt_revenue_dispositions
        SET reversed_at = CURRENT_TIMESTAMP,
            reversed_by_user_id = %s,
            reversed_by_name_snapshot = %s
        WHERE id = %s
        """,
        (user_id, actor_name, disposition_id),
    )
    cursor.execute("SELECT * FROM mgmt_revenue_dispositions WHERE id = %s", (disposition_id,))
    return _disposition_public(dict(cursor.fetchone()))
