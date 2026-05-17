"""
Daily operational reset (EST): optional tenant setting archives staging / upload / checkout
into checkout history, then clears operational tables for a clean morning slate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import mysql.connector

from backend.ta_helpers import table_exists, table_has_column

EST = ZoneInfo("America/New_York")

SETTINGS_ENABLED = "daily_operational_reset_est_enabled"
SETTINGS_LAST_DATE = "daily_operational_reset_last_est_date"
SETTINGS_TRIGGER = "daily_operational_reset_trigger"

TRIGGER_LAZY = "lazy"
TRIGGER_MIDNIGHT_EST = "midnight_est"


def eastern_today() -> date:
    return datetime.now(EST).date()


def _get_setting(cursor, organization_id: int, key: str) -> Optional[str]:
    if not table_exists(cursor, "system_settings"):
        return None
    if not table_has_column(cursor, "system_settings", "organization_id"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    v = row.get("svalue") if isinstance(row, dict) else row[0]
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def ensure_checkout_history_schema(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_history_snapshots (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          business_date DATE NOT NULL COMMENT 'Eastern calendar day whose operational state was archived',
          archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          staging_count INT NOT NULL DEFAULT 0,
          checkout_log_count INT NOT NULL DEFAULT 0,
          upload_batch_count INT NOT NULL DEFAULT 0,
          upload_batch_row_count INT NOT NULL DEFAULT 0,
          UNIQUE KEY uq_ch_snap_org_day (organization_id, business_date),
          KEY ix_ch_snap_org_arch (organization_id, archived_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_history_orders (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          snapshot_id BIGINT NOT NULL,
          organization_id INT NOT NULL,
          source_order_id INT NULL,
          date_clean DATE NULL,
          name_clean VARCHAR(255) NULL,
          weight_num DECIMAL(10,2) NULL,
          service_type VARCHAR(20) NULL,
          rush_type VARCHAR(40) NULL,
          batch_date DATE NULL,
          logistics_status VARCHAR(64) NULL,
          processing_status VARCHAR(64) NULL,
          legacy_status VARCHAR(64) NULL,
          checked_out TINYINT(1) NOT NULL DEFAULT 0,
          KEY ix_ch_ord_snap (snapshot_id),
          KEY ix_ch_ord_org (organization_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_history_checkouts (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          snapshot_id BIGINT NOT NULL,
          organization_id INT NOT NULL,
          source_order_id INT NULL,
          name VARCHAR(255) NULL,
          weight VARCHAR(64) NULL,
          service VARCHAR(32) NULL,
          rush_date DATE NULL,
          checkout_time DATETIME NULL,
          employee VARCHAR(255) NULL,
          KEY ix_ch_co_snap (snapshot_id),
          KEY ix_ch_co_org (organization_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _normalize_trigger(raw: Any) -> str:
    s = ("" if raw is None else str(raw)).strip().lower()
    if s in ("midnight_est", "midnight", "cron"):
        return TRIGGER_MIDNIGHT_EST
    return TRIGGER_LAZY


def _get_trigger(cursor, tenant_oid: int) -> str:
    raw = _get_setting(cursor, tenant_oid, SETTINGS_TRIGGER)
    return _normalize_trigger(raw)


def _as_bool_setting(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _logistics_checked_sql(cap: dict) -> str:
    """SQL expression 1 if treated as checked out / sent to rinse."""
    if cap.get("has_logistics"):
        return (
            "CASE WHEN COALESCE(o.logistics_status, '') IN "
            "('SENT_TO_RINSE','FORCE_CHECKOUT','CHECKED_OUT') THEN 1 ELSE 0 END"
        )
    if cap.get("has_status"):
        return (
            "CASE WHEN COALESCE(o.status, '') IN "
            "('CHECKED_OUT','FORCED_CHECKOUT','SENT_TO_RINSE') THEN 1 ELSE 0 END"
        )
    return "0"


def _purge_operational_tables(cursor, tenant_oid: int) -> dict:
    """Clear rinse-flow ops for tenant. Does not touch orders_final.

    Never deletes rinse_bag_registry or rinse_bag_scan_events — persistent
    completion and scan history survive daily operational reset.
    """
    out = {
        "orders_staging": 0,
        "checkout_log": 0,
        "order_processing": 0,
        "upload_batches": 0,
        "upload_batch_rows": 0,
        "upload_batch_scan_events": 0,
    }
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")

    if has_staging_org:
        if table_exists(cursor, "order_process_submissions") and table_has_column(
            cursor, "order_process_submissions", "order_id"
        ):
            cursor.execute(
                """
                DELETE FROM order_process_submissions
                WHERE order_id IN (SELECT id FROM orders_staging WHERE organization_id=%s)
                """,
                (tenant_oid,),
            )
        if table_exists(cursor, "order_processing_exceptions") and table_has_column(
            cursor, "order_processing_exceptions", "order_id"
        ):
            cursor.execute(
                """
                DELETE FROM order_processing_exceptions
                WHERE order_id IN (SELECT id FROM orders_staging WHERE organization_id=%s)
                """,
                (tenant_oid,),
            )
        if table_exists(cursor, "order_processing"):
            cursor.execute(
                """
                DELETE FROM order_processing
                WHERE order_id IN (SELECT id FROM orders_staging WHERE organization_id=%s)
                """,
                (tenant_oid,),
            )
            out["order_processing"] = cursor.rowcount or 0
        if table_exists(cursor, "checkout_log"):
            cursor.execute(
                """
                DELETE FROM checkout_log
                WHERE order_id IN (SELECT id FROM orders_staging WHERE organization_id=%s)
                """,
                (tenant_oid,),
            )
            out["checkout_log"] = cursor.rowcount or 0
        cursor.execute(
            "SELECT COUNT(*) AS c FROM orders_staging WHERE organization_id=%s", (tenant_oid,)
        )
        r = cursor.fetchone() or {}
        out["orders_staging"] = int((r.get("c") if isinstance(r, dict) else r[0]) or 0)
        cursor.execute("DELETE FROM orders_staging WHERE organization_id=%s", (tenant_oid,))
    else:
        if table_exists(cursor, "order_process_submissions"):
            cursor.execute("DELETE FROM order_process_submissions")
        if table_exists(cursor, "order_processing_exceptions"):
            cursor.execute("DELETE FROM order_processing_exceptions")
        for t in ("order_processing", "checkout_log", "orders_staging"):
            if table_exists(cursor, t):
                cursor.execute(f"DELETE FROM {t}")
                out[t] = cursor.rowcount or 0

    from backend.upload_batch_cleanup import (
        delete_all_upload_batches_global,
        delete_upload_batches_for_organization,
    )

    if has_ub_org:
        ub_counts = delete_upload_batches_for_organization(cursor, tenant_oid)
        out["upload_batch_rows"] = ub_counts.get("upload_batch_rows", 0)
        out["upload_batch_scan_events"] = ub_counts.get("upload_batch_scan_events", 0)
        out["upload_batches"] = ub_counts.get("upload_batches", 0)
    else:
        ub_counts = delete_all_upload_batches_global(cursor)
        out["upload_batch_rows"] = ub_counts.get("upload_batch_rows", 0)
        out["upload_batch_scan_events"] = ub_counts.get("upload_batch_scan_events", 0)
        out["upload_batches"] = ub_counts.get("upload_batches", 0)

    if table_exists(cursor, "upload_conflicts") and table_has_column(
        cursor, "upload_conflicts", "organization_id"
    ):
        cursor.execute("DELETE FROM upload_conflicts WHERE organization_id=%s", (tenant_oid,))

    return out


def maybe_run_daily_operational_reset(
    conn, tenant_oid: int, *, source: str = "lazy"
) -> Optional[dict]:
    """
    If enabled and Eastern calendar has advanced since last run, archive operational data
    for the completed day (last_est_date) and purge ops. Returns a summary dict when a run
    happened, else None.

    source:
      - "lazy" (default): skipped when trigger is midnight_est (cron must run reset).
      - "cron": always eligible when enabled (used by POST /internal/jobs/daily-operational-reset).
    """
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_checkout_history_schema(cursor)
        if not table_exists(cursor, "system_settings") or not table_has_column(
            cursor, "system_settings", "organization_id"
        ):
            return None

        if not _as_bool_setting(_get_setting(cursor, tenant_oid, SETTINGS_ENABLED)):
            return None

        trig = _get_trigger(cursor, tenant_oid)
        if trig == TRIGGER_MIDNIGHT_EST and (source or "lazy") != "cron":
            return None

        today = eastern_today()
        last_raw = _get_setting(cursor, tenant_oid, SETTINGS_LAST_DATE)
        last_d: Optional[date] = None
        if last_raw:
            try:
                last_d = date.fromisoformat(str(last_raw)[:10])
            except ValueError:
                last_d = None

        # First time after enable: anchor to today (no purge) so we don't wipe mid-day.
        if last_d is None:
            _set_setting(cursor, tenant_oid, SETTINGS_LAST_DATE, today.isoformat())
            conn.commit()
            return None

        if last_d >= today:
            return None

        # Close out `last_d`: archive current ops as that business_date, then purge.
        business_date = last_d
        cap = {
            "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
            "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
            "has_status": table_has_column(cursor, "orders_staging", "status"),
        }
        chk_sql = _logistics_checked_sql(cap)
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_rush = table_has_column(cursor, "orders_staging", "rush_type")
        rush_sel = "o.rush_type" if has_rush else "NULL"
        has_batch_date = table_has_column(cursor, "orders_staging", "batch_date")
        batch_sel = "o.batch_date" if has_batch_date else "NULL"
        log_sel = "o.logistics_status" if cap["has_logistics"] else "NULL"
        proc_sel = "o.processing_status" if cap["has_processing"] else "NULL"
        st_sel = "o.status" if cap["has_status"] else "NULL"

        try:
            cursor.execute(
                """
                INSERT INTO checkout_history_snapshots (
                  organization_id, business_date, archived_at,
                  staging_count, checkout_log_count, upload_batch_count, upload_batch_row_count
                )
                VALUES (%s, %s, NOW(), 0, 0, 0, 0)
                """,
                (tenant_oid, business_date),
            )
            snap_id = cursor.lastrowid
        except mysql.connector.IntegrityError:
            conn.rollback()
            try:
                cursor.close()
            except Exception:
                pass
            cursor = conn.cursor(dictionary=True)
            ensure_checkout_history_schema(cursor)
            purge = _purge_operational_tables(cursor, tenant_oid)
            _set_setting(cursor, tenant_oid, SETTINGS_LAST_DATE, today.isoformat())
            conn.commit()
            return {
                "ran": True,
                "note": "duplicate_snapshot_recovered_purge_only",
                "purged": purge,
            }

        if has_staging_org:
            cursor.execute(
                f"""
                INSERT INTO checkout_history_orders (
                  snapshot_id, organization_id, source_order_id,
                  date_clean, name_clean, weight_num, service_type, rush_type, batch_date,
                  logistics_status, processing_status, legacy_status, checked_out
                )
                SELECT
                  %s, o.organization_id, o.id,
                  o.date_clean, o.name_clean, o.weight_num, o.service_type, {rush_sel}, {batch_sel},
                  {log_sel}, {proc_sel}, {st_sel}, ({chk_sql})
                FROM orders_staging o
                WHERE o.organization_id = %s
                """,
                (snap_id, tenant_oid),
            )
            staging_n = cursor.rowcount or 0
        else:
            cursor.execute(
                f"""
                INSERT INTO checkout_history_orders (
                  snapshot_id, organization_id, source_order_id,
                  date_clean, name_clean, weight_num, service_type, rush_type, batch_date,
                  logistics_status, processing_status, legacy_status, checked_out
                )
                SELECT
                  %s, 1, o.id,
                  o.date_clean, o.name_clean, o.weight_num, o.service_type, {rush_sel}, {batch_sel},
                  {log_sel}, {proc_sel}, {st_sel}, ({chk_sql})
                FROM orders_staging o
                """,
                (snap_id,),
            )
            staging_n = cursor.rowcount or 0

        checkout_n = 0
        if table_exists(cursor, "checkout_log") and has_staging_org:
            cursor.execute(
                """
                INSERT INTO checkout_history_checkouts (
                  snapshot_id, organization_id, source_order_id,
                  name, weight, service, rush_date, checkout_time, employee
                )
                SELECT %s, %s, c.order_id, c.name, c.weight, c.service, c.rush_date, c.checkout_time, c.employee
                FROM checkout_log c
                INNER JOIN orders_staging o ON o.id = c.order_id AND o.organization_id = %s
                """,
                (snap_id, tenant_oid, tenant_oid),
            )
            checkout_n = cursor.rowcount or 0
        elif table_exists(cursor, "checkout_log") and not has_staging_org:
            cursor.execute(
                """
                INSERT INTO checkout_history_checkouts (
                  snapshot_id, organization_id, source_order_id,
                  name, weight, service, rush_date, checkout_time, employee
                )
                SELECT %s, %s, c.order_id, c.name, c.weight, c.service, c.rush_date, c.checkout_time, c.employee
                FROM checkout_log c
                """,
                (snap_id, tenant_oid),
            )
            checkout_n = cursor.rowcount or 0

        ub_count = 0
        ubr_count = 0
        if table_exists(cursor, "upload_batches"):
            has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
            bpk = "id"
            cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'batch_id'")
            if cursor.fetchone():
                bpk = "batch_id"
            if has_ub_org:
                cursor.execute(
                    f"SELECT COUNT(*) AS c FROM upload_batches WHERE organization_id=%s", (tenant_oid,)
                )
                ub_count = int((cursor.fetchone() or {}).get("c") or 0)
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS c FROM upload_batch_rows
                    WHERE upload_batch_id IN (SELECT {bpk} FROM upload_batches WHERE organization_id=%s)
                    """,
                    (tenant_oid,),
                )
                ubr_count = int((cursor.fetchone() or {}).get("c") or 0)
            else:
                cursor.execute("SELECT COUNT(*) AS c FROM upload_batches")
                ub_count = int((cursor.fetchone() or {}).get("c") or 0)
                cursor.execute("SELECT COUNT(*) AS c FROM upload_batch_rows")
                ubr_count = int((cursor.fetchone() or {}).get("c") or 0)

        purge = _purge_operational_tables(cursor, tenant_oid)

        cursor.execute(
            """
            UPDATE checkout_history_snapshots
            SET staging_count=%s, checkout_log_count=%s, upload_batch_count=%s, upload_batch_row_count=%s
            WHERE id=%s
            """,
            (staging_n, checkout_n, ub_count, ubr_count, snap_id),
        )

        _set_setting(cursor, tenant_oid, SETTINGS_LAST_DATE, today.isoformat())
        conn.commit()
        return {
            "ran": True,
            "snapshot_id": snap_id,
            "business_date": business_date.isoformat(),
            "archived": {
                "staging_orders": staging_n,
                "checkout_log_rows": checkout_n,
                "upload_batches": ub_count,
                "upload_batch_rows": ubr_count,
            },
            "purged": purge,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def get_daily_reset_settings(cursor, tenant_oid: int) -> dict[str, Any]:
    ensure_checkout_history_schema(cursor)
    return {
        "enabled": _as_bool_setting(_get_setting(cursor, tenant_oid, SETTINGS_ENABLED)),
        "last_reset_est_date": _get_setting(cursor, tenant_oid, SETTINGS_LAST_DATE),
        "trigger": _get_trigger(cursor, tenant_oid),
    }


def set_daily_reset_enabled(cursor, tenant_oid: int, enabled: bool) -> None:
    _set_setting(
        cursor,
        tenant_oid,
        SETTINGS_ENABLED,
        "true" if enabled else "false",
    )


def set_daily_reset_trigger(cursor, tenant_oid: int, trigger: str) -> None:
    _set_setting(cursor, tenant_oid, SETTINGS_TRIGGER, _normalize_trigger(trigger))


def list_org_ids_for_midnight_cron_reset(cursor) -> list[int]:
    """Tenants with reset enabled and trigger=midnight_est (legacy; prefer list_org_ids_with_daily_reset_enabled)."""
    ensure_checkout_history_schema(cursor)
    if not table_exists(cursor, "system_settings") or not table_has_column(
        cursor, "system_settings", "organization_id"
    ):
        return []
    cursor.execute(
        """
        SELECT o_en.organization_id AS oid
        FROM system_settings o_en
        INNER JOIN system_settings o_tr ON o_tr.organization_id = o_en.organization_id
        WHERE o_en.skey = %s
          AND LOWER(TRIM(COALESCE(o_en.svalue, ''))) IN ('1', 'true', 'yes', 'on')
          AND o_tr.skey = %s
          AND LOWER(TRIM(COALESCE(o_tr.svalue, ''))) = %s
        """,
        (SETTINGS_ENABLED, SETTINGS_TRIGGER, TRIGGER_MIDNIGHT_EST),
    )
    rows = cursor.fetchall() or []
    out: list[int] = []
    for row in rows:
        oid = row.get("oid") if isinstance(row, dict) else row[0]
        if oid is not None:
            out.append(int(oid))
    return out


def list_org_ids_with_daily_reset_enabled(cursor) -> list[int]:
    """Every tenant with daily operational reset turned on (embedded midnight job + HTTP cron)."""
    ensure_checkout_history_schema(cursor)
    if not table_exists(cursor, "system_settings") or not table_has_column(
        cursor, "system_settings", "organization_id"
    ):
        return []
    cursor.execute(
        """
        SELECT DISTINCT organization_id AS oid
        FROM system_settings
        WHERE skey = %s
          AND LOWER(TRIM(COALESCE(svalue, ''))) IN ('1', 'true', 'yes', 'on')
        """,
        (SETTINGS_ENABLED,),
    )
    rows = cursor.fetchall() or []
    out: list[int] = []
    for row in rows:
        oid = row.get("oid") if isinstance(row, dict) else row[0]
        if oid is not None:
            out.append(int(oid))
    return out


def run_daily_operational_reset_scheduled_pass(conn) -> dict[str, Any]:
    """
    For each org with reset enabled, run rollover when Eastern calendar has advanced
    (source=cron). Used by embedded APScheduler and POST /internal/jobs/daily-operational-reset.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        oids = list_org_ids_with_daily_reset_enabled(cursor)
    finally:
        cursor.close()
    tenants: list[dict[str, Any]] = []
    for oid in oids:
        try:
            res = maybe_run_daily_operational_reset(conn, oid, source="cron")
            tenants.append({"organization_id": oid, "result": res})
        except Exception as e:
            tenants.append({"organization_id": oid, "error": str(e)})
    return {"ok": True, "tenant_count": len(oids), "tenants": tenants}


def run_daily_operational_reset_cron_all_tenants(conn) -> dict[str, Any]:
    """Same as run_daily_operational_reset_scheduled_pass (HTTP cron alias)."""
    return run_daily_operational_reset_scheduled_pass(conn)
