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
DISP_SKIPPED = "skipped"
DISP_RESCHEDULED = "rescheduled"
DISP_COMPLETED = "completed"

STATUS_ENTERED = "entered"
STATUS_COMPLETE = "complete"
STATUS_DRAFT = "draft"
STATUS_NO_ACTIVITY = "no_activity"
STATUS_MISSING = "missing"
STATUS_PENDING = "pending"
STATUS_OVERDUE = "overdue"
STATUS_RESCHEDULED = "rescheduled"
STATUS_SKIPPED = "skipped"

RESOLVED_DISPOSITIONS = (DISP_NO_ACTIVITY, DISP_EXCLUDED, DISP_COMPLETED, DISP_SKIPPED, DISP_NO_PICKUP)

DAILY_SOURCES = (
    {"key": "self_service", "label": "Self Service", "account_code": "self_service"},
    {"key": "drop_off", "label": "Drop Off", "account_code": "drop_off"},
    {"key": "rinse_wf", "label": "Rinse WF", "account_code": "rinse_wf"},
    {"key": "rinse_hd", "label": "Rinse HD", "account_code": "rinse_hd"},
)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

LOOKBACK_DAYS = 28
LOOKAHEAD_DAYS = 7
# Missing Work enforcement floor (America/New_York business dates).
MISSING_WORK_START = date(2026, 8, 1)


def missing_work_window_start(as_of: date, lookback_days: int = LOOKBACK_DAYS) -> date:
    """Bound obligation generation: default floor Aug 1, 2026 (org rollout)."""
    raw = as_of - timedelta(days=lookback_days)
    return raw if raw >= MISSING_WORK_START else MISSING_WORK_START


def account_schedule_obligation_start(cursor, account_id: int) -> date | None:
    """Earliest schedule effective_from for this account (pairs or legacy schedule).

    Account-specific starts may be before the org Aug 1 baseline when intentionally set.
    """
    ensure_obligation_tables(cursor)
    dates: list[date] = []
    cursor.execute(
        """
        SELECT MIN(effective_from) AS d FROM mgmt_revenue_account_schedules
        WHERE account_id = %s
        """,
        (account_id,),
    )
    row = cursor.fetchone()
    if row:
        d = row.get("d") if isinstance(row, dict) else row[0]
        if d:
            dates.append(d if isinstance(d, date) else date.fromisoformat(str(d)[:10]))
    if table_exists(cursor, "mgmt_revenue_pickup_pairs"):
        cursor.execute(
            """
            SELECT MIN(effective_from) AS d FROM mgmt_revenue_pickup_pairs
            WHERE account_id = %s AND active = 1
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        if row:
            d = row.get("d") if isinstance(row, dict) else row[0]
            if d:
                dates.append(d if isinstance(d, date) else date.fromisoformat(str(d)[:10]))
    return min(dates) if dates else None


def obligation_window_start_for_account(
    cursor,
    account_id: int,
    as_of: date,
    *,
    lookback_days: int = LOOKBACK_DAYS,
) -> date:
    """Per-account Missing Work floor: schedule start if set, else org Aug 1 baseline."""
    raw = as_of - timedelta(days=lookback_days)
    acct_start = account_schedule_obligation_start(cursor, account_id)
    floor = acct_start if acct_start is not None else MISSING_WORK_START
    return raw if raw >= floor else floor


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
    if not table_exists(cursor, "mgmt_revenue_pickup_pairs"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mgmt_revenue_pickup_pairs (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              account_id BIGINT NOT NULL,
              sequence_no INT NOT NULL DEFAULT 1,
              pickup_weekday TINYINT NOT NULL,
              delivery_weekday TINYINT NOT NULL,
              delivery_offset_days TINYINT NULL,
              effective_from DATE NOT NULL,
              effective_to DATE NULL,
              active TINYINT NOT NULL DEFAULT 1,
              created_by INT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_mgmt_rev_pairs_acct (account_id, effective_from, active),
              INDEX idx_mgmt_rev_pairs_active (account_id, active, effective_from, effective_to)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    elif not table_has_column(cursor, "mgmt_revenue_pickup_pairs", "delivery_offset_days"):
        try:
            cursor.execute(
                "ALTER TABLE mgmt_revenue_pickup_pairs ADD COLUMN delivery_offset_days TINYINT NULL"
            )
            invalidate_schema_cache()
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
    if not table_exists(cursor, "mgmt_revenue_manual_occurrences"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mgmt_revenue_manual_occurrences (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              account_id BIGINT NOT NULL,
              scheduled_pickup_date DATE NOT NULL,
              scheduled_delivery_date DATE NULL,
              note VARCHAR(255) NULL,
              active TINYINT NOT NULL DEFAULT 1,
              created_by INT NULL,
              created_by_name_snapshot VARCHAR(255) NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uq_mgmt_rev_manual_pickup (account_id, scheduled_pickup_date),
              INDEX idx_mgmt_rev_manual_org (organization_id, scheduled_pickup_date)
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


def _offset_from_weekdays(pickup_wd: int, delivery_wd: int) -> int:
    """Legacy weekday pair → day offset (0 = same day; 1–6 forward)."""
    if int(pickup_wd) == int(delivery_wd):
        return 0
    return (int(delivery_wd) - int(pickup_wd)) % 7


def _legacy_pairs_from_weekdays(
    pickup_days: list[int], delivery_days: list[int]
) -> tuple[list[dict[str, Any]], bool]:
    """Zip equal-length weekday lists into pairs with delivery_offset_days."""
    pickup_days = list(pickup_days or [])
    delivery_days = list(delivery_days or [])
    if not pickup_days:
        return [], False
    if len(pickup_days) == len(delivery_days):
        out = []
        for i, (p, d) in enumerate(zip(pickup_days, delivery_days)):
            off = _offset_from_weekdays(p, d)
            out.append({
                "sequence_no": i + 1,
                "pickup_weekday": int(p),
                "delivery_weekday": int(d),
                "delivery_offset_days": off,
            })
        return out, False
    if len(pickup_days) == 1 and delivery_days:
        off = _offset_from_weekdays(pickup_days[0], delivery_days[0])
        return [
            {
                "sequence_no": 1,
                "pickup_weekday": int(pickup_days[0]),
                "delivery_weekday": int(delivery_days[0]),
                "delivery_offset_days": off,
            }
        ], False
    return [], True


def get_pickup_pairs_for_account(cursor, account_id: int, as_of: date) -> list[dict[str, Any]]:
    ensure_obligation_tables(cursor)
    cursor.execute(
        """
        SELECT * FROM mgmt_revenue_pickup_pairs
        WHERE account_id = %s AND active = 1
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY sequence_no ASC, id ASC
        """,
        (account_id, as_of, as_of),
    )
    out = []
    for row in cursor.fetchall() or []:
        r = dict(row)
        pw = int(r["pickup_weekday"])
        dw = int(r["delivery_weekday"])
        off = r.get("delivery_offset_days")
        if off is None:
            off = _offset_from_weekdays(pw, dw)
        else:
            off = int(off)
        out.append({
            "id": int(r["id"]),
            "account_id": int(r["account_id"]),
            "sequence_no": int(r.get("sequence_no") or 1),
            "pickup_weekday": pw,
            "delivery_weekday": (pw + int(off)) % 7,
            "delivery_offset_days": int(off),
            "effective_from": _iso(r.get("effective_from")),
            "effective_to": _iso(r.get("effective_to")),
            "active": bool(r.get("active", 1)),
        })
    return out


def save_pickup_pairs(
    cursor,
    account_id: int,
    *,
    effective_from: date,
    pairs: list[dict],
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Persist pickup→delivery pairs for an effective date; preserve prior versions."""
    ensure_obligation_tables(cursor)
    cleaned = []
    for i, raw in enumerate(pairs or []):
        try:
            pw = int(raw.get("pickup_weekday"))
        except (TypeError, ValueError):
            continue
        if not (0 <= pw <= 6):
            continue
        off = raw.get("delivery_offset_days")
        if off is None and raw.get("delivery_weekday") is not None:
            try:
                off = _offset_from_weekdays(pw, int(raw.get("delivery_weekday")))
            except (TypeError, ValueError):
                off = 1
        try:
            off = int(off) if off is not None else 1
        except (TypeError, ValueError):
            off = 1
        if off < 0:
            off = 0
        if off > 30:
            off = 30
        dw = (pw + off) % 7
        cleaned.append((i + 1, pw, dw, off))

    cursor.execute(
        """
        SELECT DISTINCT effective_from FROM mgmt_revenue_pickup_pairs
        WHERE account_id = %s AND active = 1 AND effective_to IS NULL
        ORDER BY effective_from DESC LIMIT 1
        """,
        (account_id,),
    )
    open_from_row = cursor.fetchone()
    open_from = _as_date(
        (open_from_row or {}).get("effective_from")
        if isinstance(open_from_row, dict)
        else (open_from_row[0] if open_from_row else None)
    )

    cursor.execute(
        """
        SELECT COUNT(*) AS n FROM mgmt_revenue_pickup_pairs
        WHERE account_id = %s AND effective_from = %s AND active = 1
        """,
        (account_id, effective_from),
    )
    exact_n = cursor.fetchone()
    exact_count = int(
        (exact_n or {}).get("n") if isinstance(exact_n, dict) else (exact_n[0] if exact_n else 0)
    )

    if exact_count:
        # Same effective_from: replace pairs in place
        cursor.execute(
            """
            UPDATE mgmt_revenue_pickup_pairs
            SET active = 0, effective_to = %s
            WHERE account_id = %s AND effective_from = %s AND active = 1
            """,
            (effective_from, account_id, effective_from),
        )
    elif open_from and effective_from < open_from:
        # Backdate current open version
        cursor.execute(
            """
            UPDATE mgmt_revenue_pickup_pairs
            SET effective_from = %s
            WHERE account_id = %s AND effective_from = %s AND active = 1 AND effective_to IS NULL
            """,
            (effective_from, account_id, open_from),
        )
        cursor.execute(
            """
            UPDATE mgmt_revenue_pickup_pairs
            SET active = 0, effective_to = %s
            WHERE account_id = %s AND effective_from = %s AND active = 1
            """,
            (effective_from, account_id, effective_from),
        )
    elif open_from and effective_from > open_from:
        cursor.execute(
            """
            UPDATE mgmt_revenue_pickup_pairs
            SET effective_to = %s
            WHERE account_id = %s AND effective_to IS NULL AND effective_from < %s AND active = 1
            """,
            (effective_from - timedelta(days=1), account_id, effective_from),
        )
    else:
        cursor.execute(
            """
            UPDATE mgmt_revenue_pickup_pairs
            SET effective_to = %s
            WHERE account_id = %s AND effective_to IS NULL AND effective_from < %s AND active = 1
            """,
            (effective_from - timedelta(days=1), account_id, effective_from),
        )

    for seq, pw, dw, off in cleaned:
        cursor.execute(
            """
            INSERT INTO mgmt_revenue_pickup_pairs
              (account_id, sequence_no, pickup_weekday, delivery_weekday, delivery_offset_days,
               effective_from, active, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
            """,
            (account_id, seq, pw, dw, off, effective_from, user_id),
        )

    pickup_days = [p[1] for p in cleaned]
    delivery_days = [p[2] for p in cleaned]
    save_account_schedule(
        cursor,
        account_id,
        effective_from=effective_from,
        pickup_weekdays=pickup_days,
        delivery_weekdays=delivery_days,
        user_id=user_id,
    )
    return get_pickup_pairs_for_account(cursor, account_id, effective_from)


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
    pickup_days = _parse_weekdays(r.get("pickup_weekdays"))
    delivery_days = _parse_weekdays(r.get("delivery_weekdays"))
    pairs = get_pickup_pairs_for_account(cursor, account_id, as_of)
    needs_confirm = False
    if not pairs and (pickup_days or delivery_days):
        pairs, needs_confirm = _legacy_pairs_from_weekdays(pickup_days, delivery_days)
    if pairs and not needs_confirm:
        pickup_days = [int(p["pickup_weekday"]) for p in pairs]
        delivery_days = [int(p["delivery_weekday"]) for p in pairs]
    return {
        "id": int(r["id"]),
        "account_id": int(r["account_id"]),
        "effective_from": _iso(r.get("effective_from")),
        "effective_to": _iso(r.get("effective_to")),
        "pickup_weekdays": pickup_days,
        "delivery_weekdays": delivery_days,
        "pickup_pairs": pairs,
        "pickups_per_week": len(pairs) if pairs else len(pickup_days),
        "needs_schedule_confirm": needs_confirm,
    }


def _as_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


def save_account_schedule(
    cursor,
    account_id: int,
    *,
    effective_from: date,
    pickup_weekdays: list[int] | None,
    delivery_weekdays: list[int] | None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Persist weekday schedule with true effective dating (no silent today overwrite).

    - Same effective_from: update in place (no stack)
    - Newer effective_from: close prior open version, insert new
    - Earlier effective_from than current open: backdate/correct the open version
      (does not invent fake history; corrects mistaken "today" stamps)
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
        SELECT id, effective_from, effective_to FROM mgmt_revenue_account_schedules
        WHERE account_id = %s AND effective_to IS NULL
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (account_id,),
    )
    open_row = cursor.fetchone()
    open_d = dict(open_row) if open_row else None
    open_from = _as_date(open_d.get("effective_from")) if open_d else None
    open_id = int(open_d["id"]) if open_d else None

    cursor.execute(
        """
        SELECT id FROM mgmt_revenue_account_schedules
        WHERE account_id = %s AND effective_from = %s
        ORDER BY id DESC LIMIT 1
        """,
        (account_id, effective_from),
    )
    exact = cursor.fetchone()

    if exact:
        row_id = int(exact["id"] if isinstance(exact, dict) else exact[0])
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET pickup_weekdays = %s, delivery_weekdays = %s, effective_to = NULL
            WHERE id = %s
            """,
            (pickup_json, delivery_json, row_id),
        )
        # Close other open/overlapping rows that are not this version.
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET effective_to = %s
            WHERE account_id = %s AND id <> %s
              AND effective_from < %s
              AND (effective_to IS NULL OR effective_to >= %s)
            """,
            (effective_from - timedelta(days=1), account_id, row_id, effective_from, effective_from),
        )
        # If a newer open row exists after this historical version, close this one
        # at day before that newer version (preserve forward history).
        if open_id and open_from and open_from > effective_from and open_id != row_id:
            cursor.execute(
                """
                UPDATE mgmt_revenue_account_schedules
                SET effective_to = %s
                WHERE id = %s AND (effective_to IS NULL OR effective_to >= %s)
                """,
                (open_from - timedelta(days=1), row_id, open_from),
            )
    elif open_id and open_from and effective_from < open_from:
        # Backdate correction of the current open version (e.g. today → Aug 1).
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET effective_from = %s, pickup_weekdays = %s, delivery_weekdays = %s, effective_to = NULL
            WHERE id = %s
            """,
            (effective_from, pickup_json, delivery_json, open_id),
        )
    elif open_id and open_from and effective_from > open_from:
        cursor.execute(
            """
            UPDATE mgmt_revenue_account_schedules
            SET effective_to = %s
            WHERE id = %s
            """,
            (effective_from - timedelta(days=1), open_id),
        )
        cursor.execute(
            """
            INSERT INTO mgmt_revenue_account_schedules
              (account_id, effective_from, pickup_weekdays, delivery_weekdays, created_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (account_id, effective_from, pickup_json, delivery_json, user_id),
        )
    else:
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
    """Prefill pickup/delivery relative to processing date using paired schedule."""
    if not schedule:
        return {
            "pickup_date": None,
            "delivery_date": None,
            "scheduled_pickup_date": None,
            "scheduled_delivery_date": None,
        }
    pairs = schedule.get("pickup_pairs") or []
    pickup = None
    delivery = None
    if pairs:
        # Most recent paired pickup on/before processing date
        best = None
        for i in range(0, 14):
            d = processing_date - timedelta(days=i)
            for p in pairs:
                if d.weekday() == int(p["pickup_weekday"]):
                    best = (d, int(p["delivery_weekday"]))
                    break
            if best:
                break
        if best:
            pickup = best[0]
            # Delivery weekday relative to that pickup (may be next week)
            for i in range(0, 14):
                d = pickup + timedelta(days=i)
                if i == 0 and d.weekday() == best[1] and best[1] == pickup.weekday():
                    # same-day delivery allowed
                    delivery = d
                    break
                if i > 0 and d.weekday() == best[1]:
                    delivery = d
                    break
    else:
        pick_days = schedule.get("pickup_weekdays") or []
        del_days = schedule.get("delivery_weekdays") or []
        if pick_days:
            for i in range(0, 8):
                d = processing_date - timedelta(days=i)
                if d.weekday() in pick_days:
                    pickup = d
                    break
        if del_days and pickup:
            for i in range(0, 8):
                d = pickup + timedelta(days=i)
                if d.weekday() in del_days:
                    delivery = d
                    break
        elif del_days:
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


def _delivery_for_pickup(pickup: date, schedule: dict | None) -> date | None:
    if not schedule:
        return None
    pairs = schedule.get("pickup_pairs") or []
    for p in pairs:
        if pickup.weekday() == int(p["pickup_weekday"]):
            off = p.get("delivery_offset_days")
            if off is not None:
                try:
                    return pickup + timedelta(days=int(off))
                except (TypeError, ValueError):
                    pass
            dw = int(p["delivery_weekday"])
            for i in range(0, 14):
                d = pickup + timedelta(days=i)
                if d.weekday() == dw:
                    return d
    del_days = (schedule or {}).get("delivery_weekdays") or []
    for i in range(0, 8):
        d = pickup + timedelta(days=i)
        if d.weekday() in del_days:
            return d
    return None


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
        disp_kind = (disp or {}).get("disposition")
        if disp_kind in (DISP_NO_ACTIVITY, DISP_EXCLUDED):
            status = STATUS_NO_ACTIVITY
            complete += 1
        elif disp_kind == DISP_COMPLETED and entered:
            status = STATUS_COMPLETE
            complete += 1
        elif entered:
            # Saved values without Complete = draft (still Incomplete for 4/4).
            # Complete disposition with cleared required fields returns to draft.
            status = STATUS_DRAFT
        else:
            status = STATUS_MISSING
        sections.append({
            "key": key,
            "label": src["label"],
            "status": status,
            "entered": entered,
            "draft": status == STATUS_DRAFT,
            "complete": status in (STATUS_COMPLETE, STATUS_NO_ACTIVITY),
            "disposition": _disposition_public(disp),
            "entry_target": key,
        })
    return {
        "processing_date_et": processing_date.isoformat(),
        "complete": complete,
        "required": len(DAILY_SOURCES),
        "label": f"{complete}/{len(DAILY_SOURCES)}",
        "help": f"Expected for {processing_date.isoformat()}",
        "sections": sections,
    }


def build_dhs_day_summary(cursor, org_id: int, processing_date: date) -> dict[str, Any]:
    """DHS due/complete/pending for a Processing Date (pickup schedule), not in 4/4."""
    # Look at nearby pickups so processing-day obligations surface for the selected day.
    obs = build_dhs_obligations(cursor, org_id, as_of=processing_date, lookback_days=14)
    due = []
    for r in obs:
        pickup = r.get("scheduled_pickup_date")
        suggested = r.get("suggested_processing_date")
        if pickup == processing_date.isoformat() or suggested == processing_date.isoformat():
            due.append(r)
    complete = [r for r in due if r.get("resolved")]
    pending = [r for r in due if not r.get("resolved")]
    return {
        "processing_date_et": processing_date.isoformat(),
        "due": len(due),
        "complete": len(complete),
        "pending": len(pending),
        "nothing_due": len(due) == 0,
        "label": (
            "Nothing due"
            if not due
            else f"Due {len(due)} · Complete {len(complete)} · Pending {len(pending)}"
        ),
        "accounts": [
            {
                "account_id": r["account_id"],
                "name": r["name"],
                "status": r["status"],
                "resolved": bool(r.get("resolved")),
                "scheduled_pickup_date": r.get("scheduled_pickup_date"),
                "scheduled_delivery_date": r.get("scheduled_delivery_date"),
                "suggested_processing_date": r.get("suggested_processing_date"),
                "source_key": r.get("source_key"),
                "entry": r.get("entry"),
            }
            for r in due
        ],
    }


def build_dhs_obligations(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    through_date: date | None = None,
) -> list[dict[str, Any]]:
    """Build DHS pickup occurrences.

    ``as_of`` is the business day used for overdue vs pending classification.
    ``through_date`` extends generation into the future (board lookahead) without
    treating future pickups as overdue.
    """
    from backend.management_revenue_accounts import list_accounts

    ensure_account_obligation_columns(cursor)
    seed_default_cadences_and_schedules(cursor, org_id)
    as_of = as_of or business_today()
    end = through_date or as_of
    if end < as_of:
        end = as_of
    accounts = list_accounts(cursor, org_id, as_of=as_of, active_only=True)
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def _append_occurrence(
        *,
        acct: dict,
        pickup: date,
        delivery: date | None,
        occurrence_source: str,
        sched_p: dict | None,
    ) -> None:
        key = (int(acct["id"]), pickup.isoformat())
        if key in seen:
            return
        seen.add(key)
        source_key = dhs_source_key(acct["id"])
        disp = _active_disposition(
            cursor, org_id, source_key=source_key, scheduled_pickup_date=pickup,
        )
        entry = dhs_entry_for_pickup(cursor, org_id, acct, pickup)
        derived_delivery = delivery or _delivery_for_pickup(pickup, sched_p)
        skip_like = (DISP_NO_PICKUP, DISP_EXCLUDED, DISP_NO_ACTIVITY, DISP_SKIPPED)
        if disp and disp.get("disposition") == DISP_RESCHEDULED:
            status = STATUS_RESCHEDULED
            resolved = True
        elif disp and disp.get("disposition") in skip_like:
            status = (
                STATUS_SKIPPED
                if disp.get("disposition") == DISP_SKIPPED
                else STATUS_NO_ACTIVITY
            )
            resolved = True
        elif disp and disp.get("disposition") == DISP_COMPLETED and entry:
            status = STATUS_COMPLETE
            resolved = True
        elif entry:
            status = STATUS_DRAFT
            resolved = False
        elif pickup < as_of:
            status = STATUS_OVERDUE
            resolved = False
        else:
            status = STATUS_PENDING
            resolved = False
        out.append({
            "kind": "dhs",
            "occurrence_id": f"dhs:{acct['id']}:{pickup.isoformat()}",
            "occurrence_source": occurrence_source,
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
            "is_manual": occurrence_source == "manual",
        })

    for acct in accounts:
        if (acct.get("revenue_group") or "") != "dhs" or not acct.get("dr_commercial_account_id"):
            continue
        if default_cadence_for_account(acct) != CADENCE_SCHEDULED:
            continue
        start = obligation_window_start_for_account(
            cursor, int(acct["id"]), as_of, lookback_days=lookback_days,
        )
        sched = get_schedule_for_account(cursor, acct["id"], as_of)
        pickups = scheduled_pickup_dates(sched, start, end)
        for pickup in pickups:
            sched_p = get_schedule_for_account(cursor, acct["id"], pickup) or sched
            if not sched_p:
                continue
            sched_start = _as_date(sched_p.get("effective_from"))
            if sched_start and pickup < sched_start:
                continue
            pickup_days = ((sched_p or {}).get("pickup_weekdays") or [])
            if pickup.weekday() not in pickup_days:
                continue
            _append_occurrence(
                acct=acct,
                pickup=pickup,
                delivery=_delivery_for_pickup(pickup, sched_p),
                occurrence_source="generated",
                sched_p=sched_p,
            )

    # Manual one-off pickups (do not alter recurring schedule)
    if table_exists(cursor, "mgmt_revenue_manual_occurrences"):
        floor = as_of - timedelta(days=lookback_days)
        cursor.execute(
            """
            SELECT * FROM mgmt_revenue_manual_occurrences
            WHERE organization_id = %s AND active = 1
              AND scheduled_pickup_date >= %s
              AND scheduled_pickup_date <= %s
            ORDER BY scheduled_pickup_date ASC, id ASC
            """,
            (org_id, floor, end),
        )
        acct_by_id = {int(a["id"]): a for a in accounts}
        for row in cursor.fetchall() or []:
            r = dict(row)
            acct = acct_by_id.get(int(r["account_id"]))
            if not acct:
                continue
            pickup = _as_date(r.get("scheduled_pickup_date"))
            if not pickup:
                continue
            delivery = _as_date(r.get("scheduled_delivery_date"))
            sched_p = get_schedule_for_account(cursor, acct["id"], pickup)
            if delivery is None:
                delivery = _delivery_for_pickup(pickup, sched_p)
            _append_occurrence(
                acct=acct,
                pickup=pickup,
                delivery=delivery,
                occurrence_source="manual",
                sched_p=sched_p,
            )

    out.sort(key=lambda r: (r.get("scheduled_pickup_date") or "", r.get("name") or ""))
    return out



def build_missing_work(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
    filter_kind: str = "all",
) -> dict[str, Any]:
    as_of = as_of or business_today()
    daily_missing: list[dict[str, Any]] = []
    if as_of >= MISSING_WORK_START:
        daily = build_daily_completeness(cursor, org_id, as_of)
        daily_missing = [
            {
                "kind": "daily",
                "source_key": s["key"],
                "name": s["label"],
                "status": s["status"],
                "processing_date_et": as_of.isoformat(),
                "entry_target": s["entry_target"],
                "overdue": False,
            }
            for s in daily["sections"]
            if s["status"] in (STATUS_MISSING, STATUS_DRAFT)
        ]
    else:
        daily = {
            "processing_date_et": as_of.isoformat(),
            "complete": 0,
            "required": 4,
            "label": "—",
            "sections": [],
        }

    dhs_all = build_dhs_obligations(cursor, org_id, as_of=as_of)
    dhs_pending = [r for r in dhs_all if not r.get("resolved")]

    items: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
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
            if s["status"] in (STATUS_COMPLETE, STATUS_NO_ACTIVITY, STATUS_ENTERED):
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
                "processing_date_et": row.get("suggested_processing_date"),
                "entry_target": "dhs",
                "overdue": row["status"] == STATUS_OVERDUE,
            })
        if fk == "daily":
            items = [i for i in items if i["kind"] == "daily"]
        elif fk == "dhs":
            items = [i for i in items if i["kind"] == "dhs"]
        elif fk == "overdue":
            items = [i for i in items if i.get("overdue") or i.get("status") == STATUS_OVERDUE]
        groups = _group_missing_items(items, as_of)

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
        "groups": groups,
    }


def _group_missing_items(items: list[dict], as_of: date) -> list[dict[str, Any]]:
    """Group Missing Work by due/processing date → Daily/DHS → accounts."""
    buckets: dict[str, dict] = {}
    today = as_of
    yesterday = as_of - timedelta(days=1)

    def _bucket_key(item: dict) -> tuple[str, str]:
        if item.get("kind") == "dhs":
            d = item.get("scheduled_pickup_date") or item.get("processing_date_et") or as_of.isoformat()
        else:
            d = item.get("processing_date_et") or as_of.isoformat()
        try:
            dd = date.fromisoformat(str(d)[:10])
        except ValueError:
            dd = as_of
        if dd == today:
            return ("today", dd.isoformat())
        if dd == yesterday:
            return ("yesterday", dd.isoformat())
        if dd < yesterday:
            return ("older", dd.isoformat())
        return ("upcoming", dd.isoformat())

    for item in items:
        if item.get("resolved"):
            continue
        kind_key, date_iso = _bucket_key(item)
        if date_iso not in buckets:
            label = date_iso
            try:
                dd = date.fromisoformat(date_iso)
                if dd == today:
                    label = f"Today · {dd.strftime('%b')} {dd.day}"
                elif dd == yesterday:
                    label = f"Yesterday · {dd.strftime('%b')} {dd.day}"
                else:
                    label = f"{dd.strftime('%b')} {dd.day}"
            except ValueError:
                pass
            buckets[date_iso] = {
                "date_et": date_iso,
                "bucket": kind_key,
                "label": label,
                "count": 0,
                "daily": [],
                "dhs_by_account": {},
            }
        b = buckets[date_iso]
        b["count"] += 1
        if item.get("kind") == "daily":
            b["daily"].append(item)
        else:
            aid = str(item.get("account_id") or item.get("name"))
            acct = b["dhs_by_account"].setdefault(
                aid,
                {"account_id": item.get("account_id"), "name": item.get("name"), "items": []},
            )
            acct["items"].append(item)

    # Sort: overdue/older dates first, then yesterday, today, upcoming
    order = {"older": 0, "yesterday": 1, "today": 2, "upcoming": 3}
    out = []
    older_bucket = {
        "date_et": "older",
        "bucket": "older",
        "label": "Older",
        "count": 0,
        "daily": [],
        "dhs": [],
        "collapsed_default": True,
    }
    for date_iso in sorted(buckets.keys(), key=lambda d: (order.get(buckets[d]["bucket"], 9), d)):
        b = buckets[date_iso]
        b["dhs"] = list(b.pop("dhs_by_account").values())
        if b["bucket"] == "older":
            older_bucket["count"] += b["count"]
            older_bucket["daily"].extend(b["daily"])
            older_bucket["dhs"].extend(b["dhs"])
            continue
        b["collapsed_default"] = b["bucket"] not in ("today", "yesterday")
        out.append(b)
    if older_bucket["count"]:
        out.insert(0, older_bucket)
    return out


def build_missing_work_summary_only(
    cursor,
    org_id: int,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Badge counts without full grouped payload — for slim bootstrap."""
    as_of = as_of or business_today()
    daily_missing = 0
    if as_of >= MISSING_WORK_START:
        daily = build_daily_completeness(cursor, org_id, as_of)
        daily_missing = sum(
            1 for s in daily["sections"] if s["status"] in (STATUS_MISSING, STATUS_DRAFT)
        )
    dhs = build_dhs_obligations(cursor, org_id, as_of=as_of, lookback_days=7)
    pending = [r for r in dhs if not r.get("resolved")]
    overdue = sum(1 for r in pending if r.get("status") == STATUS_OVERDUE)
    return {
        "missing_total": daily_missing + len(pending),
        "daily_missing": daily_missing,
        "dhs_pending": len(pending),
        "overdue": overdue,
        "today": daily_missing + sum(
            1 for r in pending if r.get("scheduled_pickup_date") == as_of.isoformat()
        ),
        "yesterday": 0,
        "older": overdue,
        "missing_work_start": MISSING_WORK_START.isoformat(),
    }


def _friendly_day_label(d: date, *, as_of: date) -> str:
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{names[d.weekday()]}, {months[d.month - 1]} {d.day}"


def _dhs_lifecycle(pickup: date | None, delivery: date | None, as_of: date) -> dict[str, Any]:
    """Classify unresolved DHS occurrence: overdue | due | upcoming (+ today labels)."""
    if not pickup:
        return {
            "lifecycle": "due",
            "lifecycle_label": "Due",
            "pickup_today": False,
            "delivery_today": False,
        }
    delivery = delivery or pickup
    pickup_today = pickup == as_of
    delivery_today = delivery == as_of
    if as_of > delivery:
        lifecycle = "overdue"
        label = "Overdue"
    elif as_of < pickup:
        lifecycle = "upcoming"
        label = "Upcoming"
    else:
        # pickup <= today <= delivery (includes boundary days)
        lifecycle = "due"
        if pickup_today and delivery_today:
            label = "Pickup Today · Delivery Today"
        elif pickup_today:
            label = "Pickup Today"
        elif delivery_today:
            label = "Delivery Today"
        else:
            label = "Due"
    return {
        "lifecycle": lifecycle,
        "lifecycle_label": label,
        "pickup_today": pickup_today,
        "delivery_today": delivery_today,
    }


def build_dhs_board(cursor, org_id: int, *, as_of: date | None = None) -> dict[str, Any]:
    """DHS tab: one card per occurrence; groups Overdue / Due / Upcoming."""
    as_of = as_of or business_today()
    through = as_of + timedelta(days=LOOKAHEAD_DAYS)
    obs = build_dhs_obligations(
        cursor, org_id, as_of=as_of, lookback_days=LOOKBACK_DAYS, through_date=through,
    )

    def _card(r: dict) -> dict | None:
        if r.get("resolved"):
            return None
        pu = _as_date(r.get("scheduled_pickup_date"))
        de = _as_date(r.get("scheduled_delivery_date"))
        life = _dhs_lifecycle(pu, de, as_of)
        entry = r.get("entry") or {}
        return {
            "occurrence_id": r.get("occurrence_id") or f"{r['source_key']}:{r.get('scheduled_pickup_date')}",
            "account_id": r["account_id"],
            "name": r["name"],
            "status": life["lifecycle"],
            "lifecycle": life["lifecycle"],
            "lifecycle_label": life["lifecycle_label"],
            "pickup_today": life["pickup_today"],
            "delivery_today": life["delivery_today"],
            "source_key": r["source_key"],
            "scheduled_pickup_date": r.get("scheduled_pickup_date"),
            "scheduled_delivery_date": r.get("scheduled_delivery_date"),
            "suggested_processing_date": r.get("suggested_processing_date"),
            "resolved": False,
            "entry": entry,
            "volume_lbs": entry.get("volume_lbs") or entry.get("lbs"),
            "revenue": entry.get("revenue") or entry.get("total_revenue"),
            "is_manual": bool(r.get("is_manual")),
            "occurrence_source": r.get("occurrence_source") or "generated",
        }

    overdue: list[dict] = []
    due: list[dict] = []
    upcoming: list[dict] = []
    for r in obs:
        card = _card(r)
        if not card:
            continue
        # Only keep upcoming within lookahead; overdue/due from lookback window
        pu = card.get("scheduled_pickup_date") or ""
        if card["lifecycle"] == "upcoming" and pu > through.isoformat():
            continue
        if card["lifecycle"] == "overdue":
            overdue.append(card)
        elif card["lifecycle"] == "due":
            due.append(card)
        else:
            upcoming.append(card)

    def _group_by_pickup(cards: list[dict]) -> list[dict]:
        buckets: dict[str, list] = {}
        for c in cards:
            key = c.get("scheduled_pickup_date") or ""
            buckets.setdefault(key, []).append(c)
        out = []
        for key in sorted(buckets.keys()):
            if not key:
                continue
            d = date.fromisoformat(key)
            out.append({
                "pickup_date": key,
                "label": f"Pickup {_friendly_day_label(d, as_of=as_of)}",
                "items": sorted(buckets[key], key=lambda x: (x.get("name") or "").lower()),
            })
        return out

    overdue_groups = _group_by_pickup(overdue)
    due_groups = _group_by_pickup(due)
    upcoming_groups = _group_by_pickup(upcoming)

    confirm = []
    from backend.management_revenue_accounts import list_accounts
    dhs_accounts = []
    for acct in list_accounts(cursor, org_id, as_of=as_of, active_only=True):
        if (acct.get("revenue_group") or "") != "dhs":
            continue
        dhs_accounts.append({"id": acct["id"], "name": acct.get("name") or "DHS"})
        sched = get_schedule_for_account(cursor, acct["id"], as_of)
        if sched and sched.get("needs_schedule_confirm"):
            confirm.append({"account_id": acct["id"], "name": acct.get("name")})

    weekday_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    summary_label = f"{weekday_names[as_of.weekday()]}, {months[as_of.month - 1]} {as_of.day}"

    # Flatten legacy shapes for older clients (single card list, no duplicate delivery cards)
    legacy_today = [c for c in due if c.get("pickup_today") or c.get("delivery_today")]
    return {
        "as_of": as_of.isoformat(),
        "summary_label": summary_label,
        "missing_work_start": MISSING_WORK_START.isoformat(),
        "counts": {
            "overdue": len(overdue),
            "due": len(due),
            "upcoming": len(upcoming),
            "pickups_today": sum(1 for c in due if c.get("pickup_today")),
            "deliveries_today": sum(1 for c in due if c.get("delivery_today")),
            "needs_processing": 0,
            "pending_processing": 0,
        },
        "groups": {
            "overdue": overdue_groups,
            "due": due_groups,
            "upcoming": upcoming_groups,
        },
        "overdue": overdue,
        "due": due,
        "upcoming": upcoming,
        "accounts": dhs_accounts,
        # Legacy compatibility (no split pickup/delivery cards)
        "sections": [],
        "needs_schedule_confirm": confirm,
        "legacy_groups": {
            "today": legacy_today,
            "overdue": overdue,
            "upcoming": upcoming[:40],
        },
    }



def create_manual_occurrence(
    cursor,
    org_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """One-off pickup that does not change the recurring schedule."""
    ensure_obligation_tables(cursor)
    account_id = int(payload.get("account_id") or 0)
    if not account_id:
        raise ValueError("account_id is required")
    pickup = _as_date(payload.get("scheduled_pickup_date") or payload.get("pickup_date"))
    if not pickup:
        raise ValueError("pickup_date is required")
    delivery = _as_date(payload.get("scheduled_delivery_date") or payload.get("delivery_date"))
    use_rule = bool(payload.get("use_account_delivery_rule", True))
    if delivery is None and use_rule:
        sched = get_schedule_for_account(cursor, account_id, pickup)
        delivery = _delivery_for_pickup(pickup, sched)
    note = (payload.get("note") or payload.get("reason") or "").strip() or None
    if note and len(note) > 255:
        note = note[:255]
    cursor.execute(
        """
        INSERT INTO mgmt_revenue_manual_occurrences
          (organization_id, account_id, scheduled_pickup_date, scheduled_delivery_date,
           note, active, created_by, created_by_name_snapshot)
        VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
        ON DUPLICATE KEY UPDATE
          scheduled_delivery_date = VALUES(scheduled_delivery_date),
          note = VALUES(note),
          active = 1,
          created_by = VALUES(created_by),
          created_by_name_snapshot = VALUES(created_by_name_snapshot)
        """,
        (org_id, account_id, pickup, delivery, note, user_id, actor_name),
    )
    return {
        "ok": True,
        "account_id": account_id,
        "scheduled_pickup_date": pickup.isoformat(),
        "scheduled_delivery_date": _iso(delivery),
        "occurrence_source": "manual",
        "note": note,
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
    if disposition not in (
        DISP_NO_ACTIVITY, DISP_EXCLUDED, DISP_NO_PICKUP, DISP_SKIPPED,
        DISP_RESCHEDULED, DISP_COMPLETED,
    ):
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

    if disposition == DISP_COMPLETED:
        if source_key.startswith("dhs:"):
            from backend.management_revenue_accounts import list_accounts

            acct = next(
                (a for a in list_accounts(cursor, org_id, as_of=pickup_date, active_only=False)
                 if int(a["id"]) == int(account_id)),
                None,
            ) if account_id else None
            if not acct:
                raise ValueError("DHS account not found")
            entry = dhs_entry_for_pickup(cursor, org_id, acct, pickup_date)
            if not entry:
                raise ValueError("Enter DHS volume/revenue before Complete")
        else:
            if not daily_source_entered(cursor, org_id, processing_date, source_key):
                raise ValueError("Enter required values before Complete")

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
