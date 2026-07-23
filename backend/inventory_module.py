"""Inventory v2 — weekly stock checks, ordering, and settings."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.inventory_constants import (
    ADJUSTMENT_BAG_SALE,
    ADJUSTMENT_MANUAL,
    ADJUSTMENT_ORDER_RECEIVE,
    ADJUSTMENT_STOCK_CHECK,
    BAG_PRICE_SETTING_KEY,
    DEFAULT_CATEGORIES,
    DEFAULT_VARIANCE_THRESHOLD,
    LEGACY_CATEGORY_MAP,
    ORDER_CANCELLED,
    ORDER_DRAFT,
    ORDER_ORDERED,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    STATUS_LEVELS,
    STATUS_LOW,
    STATUS_OK,
    STATUS_OUT,
    STOCK_CHECK_DRAFT,
    STOCK_CHECK_SUBMITTED,
    TRACKING_MODES,
    TRACKING_QUANTITY,
    TRACKING_STATUS,
    VARIANCE_REASONS,
    VARIANCE_THRESHOLD_KEY,
    ADJUSTMENT_REASONS,
    LEGACY_MIGRATION_SETTING_KEY,
    PURCHASE_SPEND_STATUSES,
)
from backend.ta_helpers import table_exists

MONEY_Q = Decimal("0.01")


class StockCheckConflictError(ValueError):
    """Stock check submit conflicts with current draft/submitted state (HTTP 409)."""


def _d(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _money(val: Any) -> float:
    return float(_d(val).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def _int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _bool(val: Any, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes", "on")


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    row = cursor.fetchone() or {}
    return int(row.get("c") or 0) > 0


def ensure_inventory_tables(cursor) -> None:
    """Create v2 inventory tables and extend legacy inventory_items. Idempotent."""
    if not table_exists(cursor, "inventory_categories"):
        _create_inventory_core_tables(cursor)
    _ensure_item_extensions(cursor)
    _ensure_v2_5_extensions(cursor)


def _create_inventory_core_tables(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_categories (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL DEFAULT 1,
          name VARCHAR(100) NOT NULL,
          sort_order INT NOT NULL DEFAULT 0,
          is_active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_inv_cat_org_name (organization_id, name),
          INDEX idx_inv_cat_org_sort (organization_id, is_active, sort_order)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_vendors (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL DEFAULT 1,
          name VARCHAR(150) NOT NULL,
          phone VARCHAR(50) NULL,
          email VARCHAR(150) NULL,
          payment_method VARCHAR(80) NULL,
          notes VARCHAR(500) NULL,
          is_active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_inv_vendor_org_name (organization_id, name),
          INDEX idx_inv_vendor_org_active (organization_id, is_active)
        ) ENGINE=InnoDB
        """
    )
    _ensure_item_extensions(cursor)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_stock_checks (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL DEFAULT 1,
          checked_by_user_id INT NULL,
          checked_by_name VARCHAR(150) NOT NULL,
          check_date DATE NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
          notes VARCHAR(500) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          submitted_at DATETIME NULL,
          INDEX idx_inv_sc_org_date (organization_id, check_date DESC),
          INDEX idx_inv_sc_org_status (organization_id, status)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_stock_check_lines (
          id INT AUTO_INCREMENT PRIMARY KEY,
          stock_check_id INT NOT NULL,
          item_id INT NOT NULL,
          counted_qty DECIMAL(10,2) NULL,
          previous_on_hand DECIMAL(10,2) NOT NULL DEFAULT 0,
          note VARCHAR(255) NULL,
          INDEX idx_inv_scl_check (stock_check_id),
          INDEX idx_inv_scl_item (item_id),
          CONSTRAINT fk_inv_scl_check FOREIGN KEY (stock_check_id)
            REFERENCES inventory_stock_checks(id) ON DELETE CASCADE,
          CONSTRAINT fk_inv_scl_item FOREIGN KEY (item_id)
            REFERENCES inventory_items(id)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_orders (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL DEFAULT 1,
          vendor_id INT NULL,
          vendor_name VARCHAR(150) NULL,
          order_date DATE NULL,
          expected_date DATE NULL,
          received_date DATE NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
          subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
          tax DECIMAL(12,2) NOT NULL DEFAULT 0,
          shipping_charge DECIMAL(12,2) NOT NULL DEFAULT 0,
          additional_charge DECIMAL(12,2) NOT NULL DEFAULT 0,
          discount DECIMAL(12,2) NOT NULL DEFAULT 0,
          grand_total DECIMAL(12,2) NOT NULL DEFAULT 0,
          ordered_by_user_id INT NULL,
          ordered_by_name VARCHAR(150) NULL,
          received_by_user_id INT NULL,
          received_by_name VARCHAR(150) NULL,
          notes VARCHAR(500) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_inv_ord_org_status (organization_id, status),
          INDEX idx_inv_ord_org_dates (organization_id, order_date, received_date)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_order_lines (
          id INT AUTO_INCREMENT PRIMARY KEY,
          order_id INT NOT NULL,
          item_id INT NOT NULL,
          qty_ordered DECIMAL(10,2) NOT NULL DEFAULT 0,
          qty_received DECIMAL(10,2) NOT NULL DEFAULT 0,
          unit_cost DECIMAL(12,4) NOT NULL DEFAULT 0,
          line_total DECIMAL(12,2) NOT NULL DEFAULT 0,
          notes VARCHAR(255) NULL,
          INDEX idx_inv_ol_order (order_id),
          INDEX idx_inv_ol_item (item_id),
          CONSTRAINT fk_inv_ol_order FOREIGN KEY (order_id)
            REFERENCES inventory_orders(id) ON DELETE CASCADE,
          CONSTRAINT fk_inv_ol_item FOREIGN KEY (item_id)
            REFERENCES inventory_items(id)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_adjustments (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL DEFAULT 1,
          item_id INT NOT NULL,
          adjustment_type VARCHAR(30) NOT NULL,
          qty_change DECIMAL(10,2) NOT NULL,
          reason VARCHAR(255) NULL,
          reference_type VARCHAR(30) NULL,
          reference_id INT NULL,
          created_by_user_id INT NULL,
          created_by_name VARCHAR(150) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_inv_adj_org_item (organization_id, item_id),
          CONSTRAINT fk_inv_adj_item FOREIGN KEY (item_id)
            REFERENCES inventory_items(id)
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_settings (
          organization_id INT NOT NULL DEFAULT 1,
          setting_key VARCHAR(100) NOT NULL,
          setting_value VARCHAR(255) NULL,
          updated_by VARCHAR(100) NULL,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (organization_id, setting_key)
        ) ENGINE=InnoDB
        """
    )
    _ensure_settings_org_column(cursor)


def _ensure_v2_5_extensions(cursor) -> None:
    """v2.5 operational columns — safe to run on every request."""
    if table_exists(cursor, "inventory_items"):
        item_cols = [
            ("sku", "VARCHAR(80) NULL"),
            ("barcode", "VARCHAR(80) NULL"),
            ("pack_size", "DECIMAL(10,2) NOT NULL DEFAULT 1"),
            ("target_stock", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
            ("average_unit_cost", "DECIMAL(12,4) NOT NULL DEFAULT 0"),
            ("last_count_date", "DATE NULL"),
            ("last_purchase_date", "DATE NULL"),
            ("tracking_mode", "VARCHAR(20) NOT NULL DEFAULT 'QUANTITY'"),
            ("status_level", "VARCHAR(20) NULL"),
            ("needs_recount", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("last_counted_by", "VARCHAR(150) NULL"),
            ("last_count_at", "DATETIME NULL"),
        ]
        for col, ddl in item_cols:
            if not _column_exists(cursor, "inventory_items", col):
                cursor.execute(f"ALTER TABLE inventory_items ADD COLUMN {col} {ddl}")

    if table_exists(cursor, "inventory_vendors"):
        vendor_cols = [
            ("website", "VARCHAR(255) NULL"),
            ("default_lead_time_days", "INT NULL"),
            ("payment_terms", "VARCHAR(120) NULL"),
        ]
        for col, ddl in vendor_cols:
            if not _column_exists(cursor, "inventory_vendors", col):
                cursor.execute(f"ALTER TABLE inventory_vendors ADD COLUMN {col} {ddl}")

    if table_exists(cursor, "inventory_stock_check_lines"):
        line_cols = [
            ("variance_qty", "DECIMAL(10,2) NULL"),
            ("variance_reason", "VARCHAR(50) NULL"),
            ("status_level", "VARCHAR(20) NULL"),
            ("needs_recount", "TINYINT(1) NOT NULL DEFAULT 0"),
        ]
        for col, ddl in line_cols:
            if not _column_exists(cursor, "inventory_stock_check_lines", col):
                cursor.execute(f"ALTER TABLE inventory_stock_check_lines ADD COLUMN {col} {ddl}")

    if table_exists(cursor, "inventory_adjustments"):
        if not _column_exists(cursor, "inventory_adjustments", "reason_code"):
            cursor.execute("ALTER TABLE inventory_adjustments ADD COLUMN reason_code VARCHAR(50) NULL")


def _ensure_settings_org_column(cursor) -> None:
    if not table_exists(cursor, "inventory_settings"):
        return
    if not _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute("ALTER TABLE inventory_settings ADD COLUMN organization_id INT NOT NULL DEFAULT 1")
        try:
            cursor.execute("ALTER TABLE inventory_settings DROP PRIMARY KEY")
        except Exception:
            pass
        try:
            cursor.execute(
                "ALTER TABLE inventory_settings ADD PRIMARY KEY (organization_id, setting_key)"
            )
        except Exception:
            pass


def _ensure_item_extensions(cursor) -> None:
    """Extend legacy inventory_items with v2 columns."""
    if not table_exists(cursor, "inventory_items"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_items (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL DEFAULT 1,
              item_name VARCHAR(150) NOT NULL,
              category VARCHAR(20) NOT NULL DEFAULT 'SUPPLY',
              category_id INT NULL,
              vendor_name VARCHAR(150) NULL,
              default_vendor_id INT NULL,
              unit_label VARCHAR(50) NOT NULL DEFAULT 'unit',
              reorder_threshold DECIMAL(10,2) NOT NULL DEFAULT 0,
              suggested_order_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
              default_unit_cost DECIMAL(12,4) NOT NULL DEFAULT 0,
              on_hand_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
              track_weekly_check TINYINT(1) NOT NULL DEFAULT 1,
              track_retail_sale TINYINT(1) NOT NULL DEFAULT 0,
              active BOOLEAN NOT NULL DEFAULT TRUE,
              notes VARCHAR(500) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL
            ) ENGINE=InnoDB
            """
        )
        return

    cols = [
        ("organization_id", "INT NOT NULL DEFAULT 1"),
        ("category_id", "INT NULL"),
        ("default_vendor_id", "INT NULL"),
        ("suggested_order_qty", "DECIMAL(10,2) NOT NULL DEFAULT 0"),
        ("default_unit_cost", "DECIMAL(12,4) NOT NULL DEFAULT 0"),
        ("track_weekly_check", "TINYINT(1) NOT NULL DEFAULT 1"),
        ("track_retail_sale", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("notes", "VARCHAR(500) NULL"),
    ]
    for col, ddl in cols:
        if not _column_exists(cursor, "inventory_items", col):
            cursor.execute(f"ALTER TABLE inventory_items ADD COLUMN {col} {ddl}")


def migrate_legacy_inventory(cursor, org_id: int) -> None:
    """One-time migration from legacy flat schema. Idempotent per org."""
    ensure_inventory_tables(cursor)
    if get_org_setting(cursor, org_id, LEGACY_MIGRATION_SETTING_KEY) == "1":
        return
    cursor.execute(
        "SELECT COUNT(*) AS c FROM inventory_categories WHERE organization_id = %s",
        (org_id,),
    )
    if int((cursor.fetchone() or {}).get("c") or 0) > 0:
        save_org_setting(cursor, org_id, LEGACY_MIGRATION_SETTING_KEY, "1")
        return

    cat_ids: dict[str, int] = {}
    for name, sort_order in DEFAULT_CATEGORIES:
        cursor.execute(
            """
            INSERT IGNORE INTO inventory_categories (organization_id, name, sort_order, is_active, created_at)
            VALUES (%s, %s, %s, 1, NOW())
            """,
            (org_id, name, sort_order),
        )
        cursor.execute(
            "SELECT id FROM inventory_categories WHERE organization_id = %s AND name = %s LIMIT 1",
            (org_id, name),
        )
        row = cursor.fetchone()
        if row:
            cat_ids[name] = row["id"]

    cursor.execute("SELECT DISTINCT vendor_name FROM inventory_items WHERE vendor_name IS NOT NULL AND vendor_name != ''")
    vendor_ids: dict[str, int] = {}
    for row in cursor.fetchall() or []:
        vname = (row.get("vendor_name") or "").strip()
        if not vname or vname in vendor_ids:
            continue
        cursor.execute(
            """
            INSERT IGNORE INTO inventory_vendors (organization_id, name, is_active, created_at)
            VALUES (%s, %s, 1, NOW())
            """,
            (org_id, vname),
        )
        cursor.execute(
            "SELECT id FROM inventory_vendors WHERE organization_id = %s AND name = %s LIMIT 1",
            (org_id, vname),
        )
        vrow = cursor.fetchone()
        if vrow:
            vendor_ids[vname] = vrow["id"]

    cursor.execute("SELECT * FROM inventory_items")
    for item in cursor.fetchall() or []:
        legacy_cat = str(item.get("category") or "SUPPLY").upper()
        cat_name = LEGACY_CATEGORY_MAP.get(legacy_cat, "Other Supplies")
        if "poly" in (item.get("item_name") or "").lower():
            cat_name = "Poly Bags"
        elif "detergent" in (item.get("item_name") or "").lower() or "free and clear" in (item.get("item_name") or "").lower():
            cat_name = "Detergent"
        elif "downy" in (item.get("item_name") or "").lower() or "softener" in (item.get("item_name") or "").lower():
            cat_name = "Softener"

        cat_id = cat_ids.get(cat_name) or cat_ids["Other Supplies"]
        vendor_id = None
        vname = (item.get("vendor_name") or "").strip()
        if vname:
            vendor_id = vendor_ids.get(vname)

        track_retail = legacy_cat == "BAG"
        track_weekly = legacy_cat != "BAG" or track_retail

        cursor.execute(
            """
            UPDATE inventory_items
            SET organization_id = %s,
                category_id = %s,
                default_vendor_id = %s,
                track_weekly_check = %s,
                track_retail_sale = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (org_id, cat_id, vendor_id, 1 if track_weekly else 0, 1 if track_retail else 0, item["id"]),
        )

    _migrate_legacy_bag_price(cursor, org_id)
    save_org_setting(cursor, org_id, LEGACY_MIGRATION_SETTING_KEY, "1")


def _migrate_legacy_bag_price(cursor, org_id: int) -> None:
    if not table_exists(cursor, "inventory_settings"):
        return
    if _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute(
            "SELECT setting_value FROM inventory_settings WHERE organization_id = %s AND setting_key = %s LIMIT 1",
            (org_id, BAG_PRICE_SETTING_KEY),
        )
        if cursor.fetchone():
            return
        cursor.execute(
            "SELECT setting_value, updated_by FROM inventory_settings WHERE setting_key = %s LIMIT 1",
            (BAG_PRICE_SETTING_KEY,),
        )
        legacy = cursor.fetchone()
        if legacy:
            cursor.execute(
                """
                INSERT INTO inventory_settings (organization_id, setting_key, setting_value, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """,
                (org_id, BAG_PRICE_SETTING_KEY, legacy.get("setting_value"), legacy.get("updated_by")),
            )
    else:
        cursor.execute(
            "SELECT setting_value, updated_by FROM inventory_settings WHERE setting_key = %s LIMIT 1",
            (BAG_PRICE_SETTING_KEY,),
        )
        legacy = cursor.fetchone()
        if legacy:
            cursor.execute(
                """
                INSERT INTO inventory_settings (organization_id, setting_key, setting_value, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (org_id, BAG_PRICE_SETTING_KEY, legacy.get("setting_value"), legacy.get("updated_by")),
            )


def get_org_setting(cursor, org_id: int, key: str, default: str | None = None) -> str | None:
    ensure_inventory_tables(cursor)
    if _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute(
            "SELECT setting_value FROM inventory_settings WHERE organization_id = %s AND setting_key = %s LIMIT 1",
            (org_id, key),
        )
    else:
        cursor.execute(
            "SELECT setting_value FROM inventory_settings WHERE setting_key = %s LIMIT 1",
            (key,),
        )
    row = cursor.fetchone() or {}
    val = row.get("setting_value")
    return val if val is not None else default


def save_org_setting(cursor, org_id: int, key: str, value: str, updated_by: str | None = None) -> None:
    ensure_inventory_tables(cursor)
    if _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute(
            """
            INSERT INTO inventory_settings (organization_id, setting_key, setting_value, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_by = VALUES(updated_by), updated_at = NOW()
            """,
            (org_id, key, value, updated_by),
        )
    else:
        cursor.execute(
            """
            INSERT INTO inventory_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_by = VALUES(updated_by), updated_at = NOW()
            """,
            (key, value, updated_by),
        )


def get_variance_threshold(cursor, org_id: int) -> float:
    raw = get_org_setting(cursor, org_id, VARIANCE_THRESHOLD_KEY, str(DEFAULT_VARIANCE_THRESHOLD))
    try:
        return max(0.0, float(raw or DEFAULT_VARIANCE_THRESHOLD))
    except Exception:
        return float(DEFAULT_VARIANCE_THRESHOLD)


def _compute_item_usage_map(cursor, org_id: int) -> dict[int, dict]:
    """Average weekly usage from submitted stock checks (last 56 days)."""
    usage: dict[int, dict] = {}
    cursor.execute(
        """
        SELECT scl.item_id, scl.counted_qty, scl.previous_on_hand, sc.submitted_at
        FROM inventory_stock_check_lines scl
        JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
        WHERE sc.organization_id = %s AND sc.status = %s
          AND sc.submitted_at >= DATE_SUB(NOW(), INTERVAL 56 DAY)
          AND scl.counted_qty IS NOT NULL
        ORDER BY sc.submitted_at ASC
        """,
        (org_id, STOCK_CHECK_SUBMITTED),
    )
    by_item: dict[int, list[float]] = {}
    for row in cursor.fetchall() or []:
        iid = int(row["item_id"])
        delta = abs(_float(row["counted_qty"]) - _float(row["previous_on_hand"]))
        by_item.setdefault(iid, []).append(delta)
    for iid, deltas in by_item.items():
        weeks = max(len(deltas), 1)
        usage[iid] = {"avg_weekly_usage": sum(deltas) / weeks}
    return usage


def _refresh_item_average_cost(cursor, org_id: int, item_id: int) -> None:
    cursor.execute(
        """
        SELECT COALESCE(SUM(ol.qty_received * ol.unit_cost), 0) AS cost_sum,
               COALESCE(SUM(ol.qty_received), 0) AS qty_sum
        FROM inventory_order_lines ol
        JOIN inventory_orders o ON o.id = ol.order_id
        WHERE o.organization_id = %s AND ol.item_id = %s AND ol.qty_received > 0
        """,
        (org_id, item_id),
    )
    row = cursor.fetchone() or {}
    qty_sum = _float(row.get("qty_sum"))
    if qty_sum > 0:
        avg = _money(_d(row.get("cost_sum")) / _d(qty_sum))
        cursor.execute(
            "UPDATE inventory_items SET average_unit_cost = %s, updated_at = NOW() WHERE id = %s",
            (avg, item_id),
        )


def _normalize_tracking_mode(raw: Any) -> str:
    mode = str(raw or TRACKING_QUANTITY).strip().upper()
    return mode if mode in TRACKING_MODES else TRACKING_QUANTITY


def _normalize_status_level(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    level = str(raw).strip().upper()
    return level if level in STATUS_LEVELS else None


def _item_needs_reorder(item: dict) -> bool:
    if _normalize_tracking_mode(item.get("tracking_mode")) == TRACKING_STATUS:
        return _normalize_status_level(item.get("status_level")) in (STATUS_LOW, STATUS_OUT)
    on_hand = _float(item.get("current_on_hand"))
    reorder = _float(item.get("reorder_level"))
    return on_hand <= reorder


def _item_row(row: dict | None, *, usage: dict | None = None) -> dict | None:
    if not row:
        return None
    on_hand = _float(row.get("on_hand_qty"))
    avg_cost = _money(row.get("average_unit_cost") or row.get("default_unit_cost"))
    default_cost = _money(row.get("default_unit_cost"))
    usage = usage or {}
    avg_weekly = _float(usage.get("avg_weekly_usage"))
    weeks_remaining = None
    if avg_weekly > 0:
        weeks_remaining = round(on_hand / avg_weekly, 1)
    lcd = row.get("last_count_date")
    lpd = row.get("last_purchase_date")
    lca = row.get("last_count_at") or row.get("last_count_at_derived")
    tracking_mode = _normalize_tracking_mode(row.get("tracking_mode"))
    status_level = _normalize_status_level(row.get("status_level"))
    if tracking_mode == TRACKING_STATUS and not status_level:
        status_level = STATUS_OK
    last_counted_by = row.get("last_counted_by") or row.get("last_counted_by_derived")
    return {
        "id": row["id"],
        "name": row.get("item_name"),
        "item_name": row.get("item_name"),
        "sku": row.get("sku"),
        "barcode": row.get("barcode"),
        "category_id": row.get("category_id"),
        "category_name": row.get("category_name"),
        "category": row.get("category_name") or row.get("category"),
        "legacy_category": row.get("category"),
        "unit": row.get("unit_label") or "unit",
        "unit_label": row.get("unit_label") or "unit",
        "pack_size": _float(row.get("pack_size"), 1),
        "default_vendor_id": row.get("default_vendor_id"),
        "vendor_name": row.get("vendor_name") or row.get("default_vendor_name"),
        "default_vendor_name": row.get("default_vendor_name"),
        "reorder_level": _float(row.get("reorder_threshold")),
        "reorder_threshold": _float(row.get("reorder_threshold")),
        "target_stock": _float(row.get("target_stock")),
        "suggested_order_qty": _float(row.get("suggested_order_qty")),
        "default_unit_cost": default_cost,
        "average_unit_cost": avg_cost,
        "estimated_value": _money(_d(on_hand) * _d(avg_cost or default_cost)),
        "current_on_hand": on_hand,
        "on_hand_qty": on_hand,
        "tracking_mode": tracking_mode,
        "status_level": status_level,
        "needs_recount": bool(row.get("needs_recount", 0)),
        "track_weekly_check": bool(row.get("track_weekly_check", 1)),
        "track_inventory": bool(row.get("track_weekly_check", 1)),
        "track_retail_sale": bool(row.get("track_retail_sale", 0)),
        "retail_item": bool(row.get("track_retail_sale", 0)),
        "is_active": bool(row.get("active", True)),
        "active": bool(row.get("active", True)),
        "notes": row.get("notes"),
        "last_counted_qty": _float(row.get("last_counted_qty")) if row.get("last_counted_qty") is not None else None,
        "last_count_date": lcd.isoformat() if hasattr(lcd, "isoformat") else (str(lcd)[:10] if lcd else None),
        "last_count_at": lca.isoformat(sep=" ") if hasattr(lca, "isoformat") else (str(lca) if lca else None),
        "last_counted_by": last_counted_by,
        "last_purchase_date": lpd.isoformat() if hasattr(lpd, "isoformat") else (str(lpd)[:10] if lpd else None),
        "avg_weekly_usage": avg_weekly,
        "weeks_remaining": weeks_remaining,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _items_base_sql() -> str:
    return """
        SELECT
            i.*,
            c.name AS category_name,
            c.sort_order AS category_sort,
            v.name AS default_vendor_name,
            (
                SELECT scl.counted_qty
                FROM inventory_stock_check_lines scl
                JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
                WHERE scl.item_id = i.id
                  AND sc.status = 'SUBMITTED'
                  AND sc.organization_id = i.organization_id
                ORDER BY sc.submitted_at DESC
                LIMIT 1
            ) AS last_counted_qty,
            (
                SELECT sc.checked_by_name
                FROM inventory_stock_check_lines scl
                JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
                WHERE scl.item_id = i.id
                  AND sc.status = 'SUBMITTED'
                  AND sc.organization_id = i.organization_id
                ORDER BY sc.submitted_at DESC
                LIMIT 1
            ) AS last_counted_by_derived,
            (
                SELECT sc.submitted_at
                FROM inventory_stock_check_lines scl
                JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
                WHERE scl.item_id = i.id
                  AND sc.status = 'SUBMITTED'
                  AND sc.organization_id = i.organization_id
                ORDER BY sc.submitted_at DESC
                LIMIT 1
            ) AS last_count_at_derived
        FROM inventory_items i
        LEFT JOIN inventory_categories c ON c.id = i.category_id
        LEFT JOIN inventory_vendors v ON v.id = i.default_vendor_id
    """


def list_categories(cursor, org_id: int, *, active_only: bool = False) -> list[dict]:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    sql = """
        SELECT id, organization_id, name, sort_order, is_active, created_at, updated_at
        FROM inventory_categories
        WHERE organization_id = %s
    """
    params: list[Any] = [org_id]
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, name"
    cursor.execute(sql, tuple(params))
    return cursor.fetchall() or []


def save_category(cursor, org_id: int, data: dict) -> dict:
    ensure_inventory_tables(cursor)
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    sort_order = _int(data.get("sort_order"), 0)
    is_active = _bool(data.get("is_active"), True)
    cat_id = data.get("id")
    if cat_id:
        cursor.execute(
            """
            UPDATE inventory_categories
            SET name = %s, sort_order = %s, is_active = %s, updated_at = NOW()
            WHERE id = %s AND organization_id = %s
            """,
            (name, sort_order, 1 if is_active else 0, int(cat_id), org_id),
        )
        return {"id": int(cat_id), "status": "updated"}
    cursor.execute(
        """
        INSERT INTO inventory_categories (organization_id, name, sort_order, is_active, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (org_id, name, sort_order, 1 if is_active else 0),
    )
    return {"id": cursor.lastrowid, "status": "created"}


def list_vendors(cursor, org_id: int, *, active_only: bool = False, with_stats: bool = False) -> list[dict]:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    sql = """
        SELECT id, organization_id, name, phone, email, website, payment_method, payment_terms,
               default_lead_time_days, notes, is_active, created_at, updated_at
        FROM inventory_vendors
        WHERE organization_id = %s
    """
    params: list[Any] = [org_id]
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY name"
    cursor.execute(sql, tuple(params))
    vendors = cursor.fetchall() or []
    if not with_stats:
        return vendors
    for v in vendors:
        vid = v["id"]
        cursor.execute(
            """
            SELECT COALESCE(SUM(grand_total), 0) AS total_spend, COUNT(*) AS order_count,
                   MAX(order_date) AS last_order_date, COALESCE(AVG(grand_total), 0) AS avg_order_value
            FROM inventory_orders
            WHERE organization_id = %s AND vendor_id = %s AND status NOT IN (%s)
            """,
            (org_id, vid, ORDER_CANCELLED),
        )
        stats = cursor.fetchone() or {}
        v["total_spend"] = _money(stats.get("total_spend"))
        v["order_count"] = int(stats.get("order_count") or 0)
        v["avg_order_value"] = _money(stats.get("avg_order_value"))
        v["last_order_date"] = stats.get("last_order_date").isoformat() if stats.get("last_order_date") else None
    return vendors


def get_vendor_detail(cursor, org_id: int, vendor_id: int) -> dict | None:
    vendors = list_vendors(cursor, org_id, with_stats=True)
    vendor = next((v for v in vendors if int(v["id"]) == int(vendor_id)), None)
    if not vendor:
        return None
    cursor.execute(
        """
        SELECT i.item_name, COALESCE(SUM(ol.qty_ordered), 0) AS qty, COALESCE(SUM(ol.line_total), 0) AS total
        FROM inventory_order_lines ol
        JOIN inventory_orders o ON o.id = ol.order_id
        JOIN inventory_items i ON i.id = ol.item_id
        WHERE o.organization_id = %s AND o.vendor_id = %s AND o.status NOT IN (%s)
        GROUP BY i.id, i.item_name
        ORDER BY total DESC
        LIMIT 50
        """,
        (org_id, vendor_id, ORDER_CANCELLED),
    )
    vendor["items_purchased"] = [
        {"item_name": r["item_name"], "qty": _float(r["qty"]), "total": _money(r["total"])}
        for r in (cursor.fetchall() or [])
    ]
    cursor.execute(
        """
        SELECT id, order_date, status, grand_total
        FROM inventory_orders
        WHERE organization_id = %s AND vendor_id = %s
        ORDER BY order_date DESC, id DESC
        LIMIT 20
        """,
        (org_id, vendor_id),
    )
    vendor["recent_orders"] = [
        {**r, "grand_total": _money(r.get("grand_total")), "order_date": r.get("order_date").isoformat() if r.get("order_date") else None}
        for r in (cursor.fetchall() or [])
    ]
    return vendor


def save_vendor(cursor, org_id: int, data: dict) -> dict:
    ensure_inventory_tables(cursor)
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    phone = (data.get("phone") or "").strip() or None
    email = (data.get("email") or "").strip() or None
    website = (data.get("website") or "").strip() or None
    payment_method = (data.get("payment_method") or data.get("payment_terms") or "").strip() or None
    payment_terms = (data.get("payment_terms") or payment_method or "").strip() or None
    lead_time = data.get("default_lead_time_days")
    lead_time = int(lead_time) if lead_time not in (None, "") else None
    notes = (data.get("notes") or "").strip() or None
    is_active = _bool(data.get("is_active"), True)
    vendor_id = data.get("id")
    if vendor_id:
        cursor.execute(
            """
            UPDATE inventory_vendors
            SET name = %s, phone = %s, email = %s, website = %s, payment_method = %s,
                payment_terms = %s, default_lead_time_days = %s, notes = %s,
                is_active = %s, updated_at = NOW()
            WHERE id = %s AND organization_id = %s
            """,
            (name, phone, email, website, payment_method, payment_terms, lead_time, notes,
             1 if is_active else 0, int(vendor_id), org_id),
        )
        return {"id": int(vendor_id), "status": "updated"}
    cursor.execute(
        """
        INSERT INTO inventory_vendors
        (organization_id, name, phone, email, website, payment_method, payment_terms,
         default_lead_time_days, notes, is_active, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (org_id, name, phone, email, website, payment_method, payment_terms, lead_time, notes, 1 if is_active else 0),
    )
    return {"id": cursor.lastrowid, "status": "created"}


def list_items(cursor, org_id: int, *, active_only: bool = False, weekly_check_only: bool = False, search: str | None = None) -> list[dict]:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    usage_map = _compute_item_usage_map(cursor, org_id)
    sql = _items_base_sql() + " WHERE i.organization_id = %s"
    params: list[Any] = [org_id]
    if active_only:
        sql += " AND i.active = TRUE"
    if weekly_check_only:
        sql += " AND i.track_weekly_check = 1"
    if search:
        sql += " AND (i.item_name LIKE %s OR i.sku LIKE %s OR c.name LIKE %s)"
        q = f"%{search.strip()}%"
        params.extend([q, q, q])
    sql += " ORDER BY COALESCE(c.sort_order, 999), c.name, i.item_name"
    cursor.execute(sql, tuple(params))
    return [_item_row(r, usage=usage_map.get(r["id"], {})) for r in (cursor.fetchall() or [])]


def get_item(cursor, org_id: int, item_id: int) -> dict | None:
    usage_map = _compute_item_usage_map(cursor, org_id)
    cursor.execute(_items_base_sql() + " WHERE i.organization_id = %s AND i.id = %s LIMIT 1", (org_id, item_id))
    row = cursor.fetchone()
    return _item_row(row, usage=usage_map.get(item_id, {})) if row else None


def save_item(cursor, org_id: int, data: dict) -> dict:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    name = (data.get("name") or data.get("item_name") or "").strip()
    if not name:
        raise ValueError("name is required")
    category_id = data.get("category_id")
    if not category_id:
        raise ValueError("category_id is required")
    unit = (data.get("unit") or data.get("unit_label") or "unit").strip()
    default_vendor_id = data.get("default_vendor_id") or None
    vendor_name = (data.get("vendor_name") or "").strip() or None
    reorder_level = _float(data.get("reorder_level") or data.get("reorder_threshold"))
    target_stock = _float(data.get("target_stock"))
    suggested_order_qty = _float(data.get("suggested_order_qty"))
    default_unit_cost = _money(data.get("default_unit_cost"))
    sku = (data.get("sku") or "").strip() or None
    barcode = (data.get("barcode") or "").strip() or None
    pack_size = _float(data.get("pack_size"), 1) or 1
    current_on_hand = _float(data.get("current_on_hand") or data.get("on_hand_qty"))
    track_weekly_check = _bool(data.get("track_weekly_check") if data.get("track_weekly_check") is not None else data.get("track_inventory"), True)
    track_retail_sale = _bool(data.get("track_retail_sale") if data.get("track_retail_sale") is not None else data.get("retail_item"), False)
    is_active = _bool(data.get("is_active") if data.get("is_active") is not None else data.get("active"), True)
    notes = (data.get("notes") or "").strip() or None
    item_id = data.get("id")
    tracking_mode = _normalize_tracking_mode(data.get("tracking_mode"))
    status_level = _normalize_status_level(data.get("status_level"))
    if tracking_mode == TRACKING_STATUS:
        status_level = status_level or STATUS_OK
        if not item_id:
            current_on_hand = 0.0
    else:
        status_level = None

    legacy_category = "BAG" if track_retail_sale else "SUPPLY"
    if item_id:
        cursor.execute(
            """
            UPDATE inventory_items
            SET item_name = %s, category_id = %s, category = %s, default_vendor_id = %s,
                vendor_name = %s, unit_label = %s, sku = %s, barcode = %s, pack_size = %s,
                reorder_threshold = %s, target_stock = %s, suggested_order_qty = %s,
                default_unit_cost = %s, track_weekly_check = %s, track_retail_sale = %s,
                tracking_mode = %s, status_level = %s,
                active = %s, notes = %s, updated_at = NOW()
            WHERE id = %s AND organization_id = %s
            """,
            (
                name, int(category_id), legacy_category, default_vendor_id, vendor_name, unit,
                sku, barcode, pack_size, reorder_level, target_stock, suggested_order_qty,
                default_unit_cost, 1 if track_weekly_check else 0, 1 if track_retail_sale else 0,
                tracking_mode, status_level,
                is_active, notes, int(item_id), org_id,
            ),
        )
        return {"id": int(item_id), "status": "updated"}
    cursor.execute(
        """
        INSERT INTO inventory_items
        (organization_id, item_name, category, category_id, default_vendor_id, vendor_name, unit_label,
         sku, barcode, pack_size, reorder_threshold, target_stock, suggested_order_qty, default_unit_cost,
         on_hand_qty, track_weekly_check, track_retail_sale, tracking_mode, status_level,
         active, notes, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (
            org_id, name, legacy_category, int(category_id), default_vendor_id, vendor_name, unit,
            sku, barcode, pack_size, reorder_level, target_stock, suggested_order_qty, default_unit_cost,
            current_on_hand, 1 if track_weekly_check else 0, 1 if track_retail_sale else 0,
            tracking_mode, status_level, is_active, notes,
        ),
    )
    new_id = cursor.lastrowid
    if current_on_hand > 0:
        cursor.execute(
            """
            INSERT INTO inventory_adjustments
            (organization_id, item_id, adjustment_type, qty_change, reason, reason_code, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (org_id, new_id, ADJUSTMENT_MANUAL, current_on_hand, "Initial on-hand", "CORRECTION"),
        )
    return {"id": new_id, "status": "created"}


def deactivate_item(cursor, org_id: int, item_id: int) -> dict:
    cursor.execute(
        "UPDATE inventory_items SET active = FALSE, updated_at = NOW() WHERE id = %s AND organization_id = %s",
        (int(item_id), org_id),
    )
    return {"status": "removed"}


def get_bag_price(cursor, org_id: int) -> dict:
    ensure_inventory_tables(cursor)
    migrate_legacy_inventory(cursor, org_id)
    if _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute(
            """
            SELECT setting_value, updated_by, updated_at
            FROM inventory_settings
            WHERE organization_id = %s AND setting_key = %s
            LIMIT 1
            """,
            (org_id, BAG_PRICE_SETTING_KEY),
        )
    else:
        cursor.execute(
            """
            SELECT setting_value, updated_by, updated_at
            FROM inventory_settings
            WHERE setting_key = %s
            LIMIT 1
            """,
            (BAG_PRICE_SETTING_KEY,),
        )
    row = cursor.fetchone() or {}
    return {
        "bag_default_price": _money(row.get("setting_value")),
        "updated_by": row.get("updated_by"),
        "updated_at": row.get("updated_at"),
    }


def save_bag_price(cursor, org_id: int, price: float, updated_by: str) -> dict:
    ensure_inventory_tables(cursor)
    if _column_exists(cursor, "inventory_settings", "organization_id"):
        cursor.execute(
            """
            INSERT INTO inventory_settings (organization_id, setting_key, setting_value, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value),
                updated_by = VALUES(updated_by),
                updated_at = NOW()
            """,
            (org_id, BAG_PRICE_SETTING_KEY, str(round(price, 2)), updated_by),
        )
    else:
        cursor.execute(
            """
            INSERT INTO inventory_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value),
                updated_by = VALUES(updated_by),
                updated_at = NOW()
            """,
            (BAG_PRICE_SETTING_KEY, str(round(price, 2)), updated_by),
        )
    return {"status": "updated", "bag_default_price": round(price, 2)}


def get_latest_stock_check(cursor, org_id: int) -> dict | None:
    ensure_inventory_tables(cursor)
    cursor.execute(
        """
        SELECT id, checked_by_name, check_date, status, notes, created_at, submitted_at
        FROM inventory_stock_checks
        WHERE organization_id = %s AND status = %s
        ORDER BY submitted_at DESC
        LIMIT 1
        """,
        (org_id, STOCK_CHECK_SUBMITTED),
    )
    return cursor.fetchone()


def get_draft_stock_check(cursor, org_id: int) -> dict | None:
    ensure_inventory_tables(cursor)
    cursor.execute(
        """
        SELECT id, checked_by_name, check_date, status, notes, created_at, submitted_at
        FROM inventory_stock_checks
        WHERE organization_id = %s AND status = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (org_id, STOCK_CHECK_DRAFT),
    )
    check = cursor.fetchone()
    if not check:
        return None
    line_cols = "item_id, counted_qty, previous_on_hand, note, variance_qty, variance_reason"
    if _column_exists(cursor, "inventory_stock_check_lines", "status_level"):
        line_cols += ", status_level"
    if _column_exists(cursor, "inventory_stock_check_lines", "needs_recount"):
        line_cols += ", needs_recount"
    cursor.execute(
        f"""
        SELECT {line_cols}
        FROM inventory_stock_check_lines
        WHERE stock_check_id = %s
        """,
        (check["id"],),
    )
    lines = {r["item_id"]: r for r in (cursor.fetchall() or [])}
    check["lines"] = lines
    return check


def save_stock_check_draft(cursor, org_id: int, data: dict, user_id: int | None, user_name: str) -> dict:
    ensure_inventory_tables(cursor)
    lines = data.get("lines") or []
    notes = (data.get("notes") or "").strip() or None
    check_date = data.get("check_date") or date.today().isoformat()

    cursor.execute(
        """
        SELECT id FROM inventory_stock_checks
        WHERE organization_id = %s AND status = %s
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (org_id, STOCK_CHECK_DRAFT),
    )
    row = cursor.fetchone()
    if row:
        check_id = row["id"]
        cursor.execute(
            "UPDATE inventory_stock_checks SET notes = %s, check_date = %s WHERE id = %s",
            (notes, check_date, check_id),
        )
        cursor.execute("DELETE FROM inventory_stock_check_lines WHERE stock_check_id = %s", (check_id,))
    else:
        cursor.execute(
            """
            INSERT INTO inventory_stock_checks
            (organization_id, checked_by_user_id, checked_by_name, check_date, status, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (org_id, user_id, user_name, check_date, STOCK_CHECK_DRAFT, notes),
        )
        check_id = cursor.lastrowid

    for line in lines:
        item_id = line.get("item_id")
        if not item_id:
            continue
        item = get_item(cursor, org_id, int(item_id))
        if not item:
            continue
        counted_raw = line.get("counted_qty")
        counted_qty = None if counted_raw in (None, "") else _float(counted_raw)
        note = (line.get("note") or "").strip() or None
        status_level = _normalize_status_level(line.get("status_level"))
        needs_recount = 1 if _bool(line.get("needs_recount"), False) else 0
        if item.get("tracking_mode") == TRACKING_STATUS:
            counted_qty = None
            status_level = status_level or _normalize_status_level(item.get("status_level")) or STATUS_OK
        prev = item["current_on_hand"]
        variance_qty = None
        if counted_qty is not None:
            variance_qty = counted_qty - prev
        variance_reason = (line.get("variance_reason") or "").strip() or None
        has_recount_col = _column_exists(cursor, "inventory_stock_check_lines", "needs_recount")
        if has_recount_col:
            cursor.execute(
                """
                INSERT INTO inventory_stock_check_lines
                (stock_check_id, item_id, counted_qty, previous_on_hand, note, variance_qty, variance_reason, status_level, needs_recount)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (check_id, int(item_id), counted_qty, prev, note, variance_qty, variance_reason, status_level, needs_recount),
            )
        else:
            cursor.execute(
                """
                INSERT INTO inventory_stock_check_lines
                (stock_check_id, item_id, counted_qty, previous_on_hand, note, variance_qty, variance_reason, status_level)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (check_id, int(item_id), counted_qty, prev, note, variance_qty, variance_reason, status_level),
            )

    return {"id": check_id, "status": "draft_saved"}


def _sum_purchase_orders(cursor, org_id: int, start: date, end: date) -> float:
    placeholders = ", ".join(["%s"] * len(PURCHASE_SPEND_STATUSES))
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(grand_total), 0) AS total
        FROM inventory_orders
        WHERE organization_id = %s
          AND status IN ({placeholders})
          AND order_date IS NOT NULL
          AND order_date >= %s AND order_date <= %s
        """,
        (org_id, *PURCHASE_SPEND_STATUSES, start, end),
    )
    return _money((cursor.fetchone() or {}).get("total"))


def _lock_stock_check_row(cursor, check_id: int, org_id: int) -> dict:
    cursor.execute(
        """
        SELECT id, status FROM inventory_stock_checks
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        FOR UPDATE
        """,
        (check_id, org_id),
    )
    row = cursor.fetchone()
    if not row:
        raise StockCheckConflictError("Stock check not found")
    return row


def submit_stock_check(cursor, org_id: int, data: dict, user_id: int | None, user_name: str) -> dict:
    threshold = get_variance_threshold(cursor, org_id)
    lines_in = data.get("lines") or []
    for line in lines_in:
        item = get_item(cursor, org_id, int(line["item_id"])) if line.get("item_id") else None
        if not item:
            continue
        if _bool(line.get("needs_recount"), False):
            continue
        if item.get("tracking_mode") == TRACKING_STATUS:
            level = _normalize_status_level(line.get("status_level"))
            if level is None and line.get("counted_qty") in (None, ""):
                continue
            if level is not None and level not in STATUS_LEVELS:
                raise ValueError(f"Invalid status for {item['name']}")
            continue
        if line.get("counted_qty") in (None, ""):
            continue
        counted = _float(line["counted_qty"])
        prev = _float(item["current_on_hand"])
        diff = abs(counted - prev)
        if diff > threshold:
            reason = (line.get("variance_reason") or "").strip().upper()
            if reason not in VARIANCE_REASONS:
                raise ValueError(
                    f"Variance reason required for {item['name']} (difference {diff:.0f}, threshold {threshold:.0f})"
                )

    draft = get_draft_stock_check(cursor, org_id)
    if draft:
        if lines_in:
            save_stock_check_draft(cursor, org_id, data, user_id, user_name)
            draft = get_draft_stock_check(cursor, org_id)
    elif lines_in and data.get("oneshot"):
        if not get_draft_stock_check(cursor, org_id):
            save_stock_check_draft(cursor, org_id, data, user_id, user_name)
        draft = get_draft_stock_check(cursor, org_id)
    else:
        raise StockCheckConflictError("No draft stock check to submit")

    if not draft:
        raise StockCheckConflictError("No draft to submit")

    check_id = int(draft["id"])
    locked = _lock_stock_check_row(cursor, check_id, org_id)
    if locked.get("status") != STOCK_CHECK_DRAFT:
        raise StockCheckConflictError("Stock check already submitted")

    lines = list((draft.get("lines") or {}).values())
    submitted = 0
    recount_flagged = 0
    for line in lines:
        item_id = int(line["item_id"])
        item = get_item(cursor, org_id, item_id)
        if not item:
            continue

        needs_recount = bool(line.get("needs_recount"))
        if needs_recount:
            if _column_exists(cursor, "inventory_items", "needs_recount"):
                cursor.execute(
                    "UPDATE inventory_items SET needs_recount = 1, updated_at = NOW() WHERE id = %s AND organization_id = %s",
                    (item_id, org_id),
                )
            # Audit only — do not change on_hand_qty / status_level.
            cursor.execute(
                """
                INSERT INTO inventory_adjustments
                (organization_id, item_id, adjustment_type, qty_change, reason, reason_code, reference_type, reference_id,
                 created_by_user_id, created_by_name, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    org_id, item_id, ADJUSTMENT_STOCK_CHECK, 0,
                    "Marked for recount — quantity not applied", "COUNT_CORRECTION",
                    "stock_check", check_id, user_id, user_name,
                ),
            )
            recount_flagged += 1
            submitted += 1
            continue

        if item.get("tracking_mode") == TRACKING_STATUS:
            status_level = _normalize_status_level(line.get("status_level"))
            if status_level is None:
                continue
            cursor.execute(
                """
                UPDATE inventory_items
                SET status_level = %s, last_count_date = CURDATE(), last_count_at = NOW(),
                    last_counted_by = %s, needs_recount = 0, updated_at = NOW()
                WHERE id = %s AND organization_id = %s
                """,
                (status_level, user_name, item_id, org_id),
            )
            cursor.execute(
                """
                INSERT INTO inventory_adjustments
                (organization_id, item_id, adjustment_type, qty_change, reason, reason_code, reference_type, reference_id,
                 created_by_user_id, created_by_name, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    org_id, item_id, ADJUSTMENT_STOCK_CHECK, 0,
                    f"Weekly stock check status → {status_level}", "COUNT_CORRECTION",
                    "stock_check", check_id, user_id, user_name,
                ),
            )
            submitted += 1
            continue

        if line.get("counted_qty") is None:
            continue
        counted_qty = _float(line["counted_qty"])
        prev = _float(item["current_on_hand"])
        cursor.execute(
            "UPDATE inventory_items SET on_hand_qty = %s, last_count_date = CURDATE(), last_count_at = NOW(), "
            "last_counted_by = %s, needs_recount = 0, updated_at = NOW() "
            "WHERE id = %s AND organization_id = %s",
            (counted_qty, user_name, item_id, org_id),
        )
        qty_change = counted_qty - prev
        cursor.execute(
            """
            INSERT INTO inventory_adjustments
            (organization_id, item_id, adjustment_type, qty_change, reason, reference_type, reference_id,
             created_by_user_id, created_by_name, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                org_id, item_id, ADJUSTMENT_STOCK_CHECK, qty_change, "Weekly stock check",
                "stock_check", check_id, user_id, user_name,
            ),
        )
        submitted += 1

    cursor.execute(
        """
        UPDATE inventory_stock_checks
        SET status = %s, submitted_at = NOW(), checked_by_user_id = %s, checked_by_name = %s
        WHERE id = %s AND organization_id = %s AND status = %s
        """,
        (STOCK_CHECK_SUBMITTED, user_id, user_name, check_id, org_id, STOCK_CHECK_DRAFT),
    )
    if cursor.rowcount != 1:
        raise StockCheckConflictError("Stock check already submitted")

    reorder_suggestions = list_reorder_suggestions(cursor, org_id)
    return {
        "id": check_id,
        "status": "submitted",
        "lines_submitted": submitted,
        "recount_flagged": recount_flagged,
        "reorder_suggestions": reorder_suggestions,
    }


def list_reorder_suggestions(cursor, org_id: int) -> list[dict]:
    items = list_items(cursor, org_id, active_only=True, weekly_check_only=True)
    out = []
    for item in items:
        if not _item_needs_reorder(item):
            continue
        if item.get("tracking_mode") == TRACKING_STATUS:
            suggested = _float(item["suggested_order_qty"]) or 1
        else:
            on_hand = _float(item["current_on_hand"])
            reorder = _float(item["reorder_level"])
            suggested = _float(item["suggested_order_qty"]) or max(reorder - on_hand, 1)
        out.append({
            **item,
            "suggested_qty": suggested,
            "estimated_total": _money(_d(suggested) * _d(item["default_unit_cost"])),
        })
    return out


def get_orders_summary(cursor, org_id: int) -> dict:
    ensure_inventory_tables(cursor)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start - timedelta(days=1)

    def _sum_orders(start: date, end: date) -> float:
        return _sum_purchase_orders(cursor, org_id, start, end)

    this_week_total = _sum_orders(week_start, today)
    last_week_total = _sum_orders(last_week_start, last_week_end)
    month_start = today.replace(day=1)
    this_month_total = _sum_orders(month_start, today)

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM inventory_orders
        WHERE organization_id = %s AND status IN (%s, %s)
        """,
        (org_id, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED),
    )
    pending = int((cursor.fetchone() or {}).get("c") or 0)

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM inventory_orders
        WHERE organization_id = %s AND status = %s AND received_date >= %s
        """,
        (org_id, ORDER_RECEIVED, week_start),
    )
    received_this_week = int((cursor.fetchone() or {}).get("c") or 0)

    reorder_count = len(list_reorder_suggestions(cursor, org_id))

    return {
        "items_needing_reorder": reorder_count,
        "last_week_ordered_total": last_week_total,
        "this_week_ordered_total": this_week_total,
        "this_month_ordered_total": this_month_total,
        "pending_orders": pending,
        "received_this_week": received_this_week,
        "last_week_range": {"start": last_week_start.isoformat(), "end": last_week_end.isoformat()},
        "this_week_range": {"start": week_start.isoformat(), "end": today.isoformat()},
    }


def _order_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        **row,
        "subtotal": _money(row.get("subtotal")),
        "tax": _money(row.get("tax")),
        "shipping_charge": _money(row.get("shipping_charge")),
        "additional_charge": _money(row.get("additional_charge")),
        "discount": _money(row.get("discount")),
        "grand_total": _money(row.get("grand_total")),
        "order_date": row.get("order_date").isoformat() if row.get("order_date") else None,
        "expected_date": row.get("expected_date").isoformat() if row.get("expected_date") else None,
        "received_date": row.get("received_date").isoformat() if row.get("received_date") else None,
    }


def list_orders(cursor, org_id: int, *, status: str | None = None, limit: int = 100) -> list[dict]:
    ensure_inventory_tables(cursor)
    sql = """
        SELECT o.*, v.name AS vendor_display_name
        FROM inventory_orders o
        LEFT JOIN inventory_vendors v ON v.id = o.vendor_id
        WHERE o.organization_id = %s
    """
    params: list[Any] = [org_id]
    if status:
        sql += " AND o.status = %s"
        params.append(status)
    sql += " ORDER BY COALESCE(o.order_date, o.created_at) DESC, o.id DESC LIMIT %s"
    params.append(limit)
    cursor.execute(sql, tuple(params))
    orders = [_order_row(r) for r in (cursor.fetchall() or [])]
    for order in orders:
        cursor.execute(
            """
            SELECT ol.*, i.item_name, i.on_hand_qty AS current_on_hand
            FROM inventory_order_lines ol
            JOIN inventory_items i ON i.id = ol.item_id
            WHERE ol.order_id = %s
            ORDER BY ol.id
            """,
            (order["id"],),
        )
        order["lines"] = [
            {
                **ln,
                "qty_ordered": _float(ln.get("qty_ordered")),
                "qty_received": _float(ln.get("qty_received")),
                "qty_outstanding": max(_float(ln.get("qty_ordered")) - _float(ln.get("qty_received")), 0),
                "unit_cost": _money(ln.get("unit_cost")),
                "line_total": _money(ln.get("line_total")),
                "current_on_hand": _float(ln.get("current_on_hand")),
            }
            for ln in (cursor.fetchall() or [])
        ]
        order["qty_ordered_total"] = sum(l["qty_ordered"] for l in order["lines"])
        order["qty_received_total"] = sum(l["qty_received"] for l in order["lines"])
        order["qty_outstanding_total"] = sum(l["qty_outstanding"] for l in order["lines"])
    return orders


def _calc_order_totals(lines: list[dict], extras: dict) -> dict:
    subtotal = Decimal("0")
    for line in lines:
        qty = _d(line.get("qty_ordered"))
        unit = _d(line.get("unit_cost"))
        line_total = (qty * unit).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        line["line_total"] = float(line_total)
        subtotal += line_total
    tax = _d(extras.get("tax"))
    shipping = _d(extras.get("shipping_charge"))
    additional = _d(extras.get("additional_charge"))
    discount = _d(extras.get("discount"))
    grand = subtotal + tax + shipping + additional - discount
    return {
        "subtotal": _money(subtotal),
        "tax": _money(tax),
        "shipping_charge": _money(shipping),
        "additional_charge": _money(additional),
        "discount": _money(discount),
        "grand_total": _money(grand),
    }


def save_order(cursor, org_id: int, data: dict, user_id: int | None, user_name: str) -> dict:
    ensure_inventory_tables(cursor)
    lines_in = data.get("lines") or []
    if not lines_in:
        raise ValueError("At least one order line is required")

    vendor_id = data.get("vendor_id") or None
    vendor_name = (data.get("vendor_name") or "").strip() or None
    if vendor_id:
        cursor.execute("SELECT name FROM inventory_vendors WHERE id = %s AND organization_id = %s", (vendor_id, org_id))
        vrow = cursor.fetchone()
        if vrow:
            vendor_name = vrow.get("name")

    status = (data.get("status") or ORDER_DRAFT).upper()
    if status not in {ORDER_DRAFT, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED, ORDER_RECEIVED, ORDER_CANCELLED}:
        raise ValueError("Invalid order status")

    order_date = data.get("order_date") or date.today().isoformat()
    expected_date = data.get("expected_date") or None
    notes = (data.get("notes") or "").strip() or None

    lines = []
    for ln in lines_in:
        item_id = ln.get("item_id")
        qty = _float(ln.get("qty_ordered"))
        if not item_id or qty <= 0:
            continue
        unit_cost = _money(ln.get("unit_cost") if ln.get("unit_cost") not in (None, "") else ln.get("default_unit_cost"))
        if unit_cost == 0:
            item = get_item(cursor, org_id, int(item_id))
            if item:
                unit_cost = item["default_unit_cost"]
        lines.append({
            "item_id": int(item_id),
            "qty_ordered": qty,
            "unit_cost": unit_cost,
            "notes": (ln.get("notes") or "").strip() or None,
        })

    if not lines:
        raise ValueError("Valid order lines required")

    totals = _calc_order_totals(lines, data)
    order_id = data.get("id")

    if order_id:
        cursor.execute(
            """
            UPDATE inventory_orders
            SET vendor_id = %s, vendor_name = %s, order_date = %s, expected_date = %s, status = %s,
                subtotal = %s, tax = %s, shipping_charge = %s, additional_charge = %s, discount = %s,
                grand_total = %s, notes = %s, ordered_by_user_id = %s, ordered_by_name = %s, updated_at = NOW()
            WHERE id = %s AND organization_id = %s
            """,
            (
                vendor_id, vendor_name, order_date, expected_date, status,
                totals["subtotal"], totals["tax"], totals["shipping_charge"],
                totals["additional_charge"], totals["discount"], totals["grand_total"],
                notes, user_id, user_name, int(order_id), org_id,
            ),
        )
        cursor.execute("DELETE FROM inventory_order_lines WHERE order_id = %s", (int(order_id),))
        oid = int(order_id)
    else:
        cursor.execute(
            """
            INSERT INTO inventory_orders
            (organization_id, vendor_id, vendor_name, order_date, expected_date, status,
             subtotal, tax, shipping_charge, additional_charge, discount, grand_total,
             ordered_by_user_id, ordered_by_name, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (
                org_id, vendor_id, vendor_name, order_date, expected_date, status,
                totals["subtotal"], totals["tax"], totals["shipping_charge"],
                totals["additional_charge"], totals["discount"], totals["grand_total"],
                user_id, user_name, notes,
            ),
        )
        oid = cursor.lastrowid

    for ln in lines:
        cursor.execute(
            """
            INSERT INTO inventory_order_lines
            (order_id, item_id, qty_ordered, qty_received, unit_cost, line_total, notes)
            VALUES (%s, %s, %s, 0, %s, %s, %s)
            """,
            (oid, ln["item_id"], ln["qty_ordered"], ln["unit_cost"], ln["line_total"], ln.get("notes")),
        )

    if status == ORDER_ORDERED:
        cursor.execute(
            "UPDATE inventory_orders SET ordered_by_user_id = %s, ordered_by_name = %s WHERE id = %s",
            (user_id, user_name, oid),
        )

    return {"id": oid, "status": status, **totals}


def receive_order(cursor, org_id: int, order_id: int, data: dict, user_id: int | None, user_name: str) -> dict:
    ensure_inventory_tables(cursor)
    cursor.execute(
        "SELECT * FROM inventory_orders WHERE id = %s AND organization_id = %s LIMIT 1",
        (int(order_id), org_id),
    )
    order = cursor.fetchone()
    if not order:
        raise ValueError("Order not found")
    if order.get("status") == ORDER_CANCELLED:
        raise ValueError("Cannot receive cancelled order")
    if order.get("status") == ORDER_RECEIVED:
        raise ValueError("Order already fully received")

    received_date = data.get("received_date") or date.today().isoformat()
    lines_in = {int(ln["line_id"]): ln for ln in (data.get("lines") or []) if ln.get("line_id")}

    cursor.execute("SELECT * FROM inventory_order_lines WHERE order_id = %s", (int(order_id),))
    db_lines = cursor.fetchall() or []
    total_received_delta = 0
    all_complete = True
    any_received = False

    for ln in db_lines:
        line_id = ln["id"]
        prev_received = _float(ln.get("qty_received"))
        override = lines_in.get(line_id, {})
        ordered = _float(ln.get("qty_ordered"))
        raw_received = override.get("qty_received") if override.get("qty_received") is not None else ordered
        new_received = min(_float(raw_received), ordered)
        delta = new_received - prev_received
        note = (override.get("notes") or "").strip() or None
        if new_received < prev_received:
            raise ValueError("Cannot reduce received quantity; use adjustment instead")
        cursor.execute(
            "UPDATE inventory_order_lines SET qty_received = %s, notes = COALESCE(%s, notes) WHERE id = %s",
            (new_received, note, line_id),
        )
        if new_received < ordered:
            all_complete = False
        if new_received > 0:
            any_received = True
        if delta <= 0:
            continue
        item_id = ln["item_id"]
        item = get_item(cursor, org_id, item_id)
        if item:
            new_qty = _float(item["current_on_hand"]) + delta
            cursor.execute(
                "UPDATE inventory_items SET on_hand_qty = %s, last_purchase_date = %s, updated_at = NOW() WHERE id = %s",
                (new_qty, received_date, item_id),
            )
            _refresh_item_average_cost(cursor, org_id, item_id)
            cursor.execute(
                """
                INSERT INTO inventory_adjustments
                (organization_id, item_id, adjustment_type, qty_change, reason, reason_code,
                 reference_type, reference_id, created_by_user_id, created_by_name, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    org_id, item_id, ADJUSTMENT_ORDER_RECEIVE, delta,
                    f"Received order #{order_id}", "CORRECTION",
                    "order", int(order_id), user_id, user_name,
                ),
            )
            total_received_delta += delta

    if total_received_delta <= 0:
        raise ValueError("No new quantities to receive")

    new_status = ORDER_RECEIVED if all_complete and any_received else ORDER_PARTIALLY_RECEIVED
    if not any_received:
        new_status = order.get("status") or ORDER_ORDERED

    cursor.execute(
        """
        UPDATE inventory_orders
        SET status = %s, received_date = %s, received_by_user_id = %s, received_by_name = %s, updated_at = NOW()
        WHERE id = %s
        """,
        (new_status, received_date if any_received else order.get("received_date"), user_id, user_name, int(order_id)),
    )
    return {"id": int(order_id), "status": new_status, "qty_received_total": total_received_delta}


def duplicate_order(cursor, org_id: int, order_id: int, user_id: int | None, user_name: str) -> dict:
    ensure_inventory_tables(cursor)
    cursor.execute(
        "SELECT * FROM inventory_orders WHERE id = %s AND organization_id = %s LIMIT 1",
        (int(order_id), org_id),
    )
    src = cursor.fetchone()
    if not src:
        raise ValueError("Order not found")
    cursor.execute("SELECT * FROM inventory_order_lines WHERE order_id = %s", (int(order_id),))
    src_lines = cursor.fetchall() or []
    lines = [
        {
            "item_id": ln["item_id"],
            "qty_ordered": _float(ln.get("qty_ordered")),
            "unit_cost": _money(ln.get("unit_cost")),
            "notes": ln.get("notes"),
        }
        for ln in src_lines
    ]
    return save_order(cursor, org_id, {
        "vendor_id": src.get("vendor_id"),
        "vendor_name": src.get("vendor_name"),
        "order_date": date.today().isoformat(),
        "expected_date": src.get("expected_date").isoformat() if src.get("expected_date") else None,
        "status": ORDER_DRAFT,
        "tax": src.get("tax"),
        "shipping_charge": src.get("shipping_charge"),
        "additional_charge": src.get("additional_charge"),
        "discount": src.get("discount"),
        "notes": f"Duplicated from PO #{order_id}",
        "lines": lines,
    }, user_id, user_name)


def manual_adjustment(cursor, org_id: int, data: dict, user_id: int | None, user_name: str) -> dict:
    item_id = data.get("item_id")
    qty_change = _float(data.get("qty_change"))
    reason_code = (data.get("reason_code") or "").strip().upper()
    if reason_code not in ADJUSTMENT_REASONS:
        raise ValueError(f"reason_code is required and must be one of: {', '.join(ADJUSTMENT_REASONS)}")
    reason = (data.get("reason") or reason_code.replace("_", " ").title()).strip()
    if not item_id or qty_change == 0:
        raise ValueError("item_id and non-zero qty_change required")
    item = get_item(cursor, org_id, int(item_id))
    if not item:
        raise ValueError("Item not found")
    new_qty = max(0, _float(item["current_on_hand"]) + qty_change)
    cursor.execute(
        "UPDATE inventory_items SET on_hand_qty = %s, updated_at = NOW() WHERE id = %s AND organization_id = %s",
        (new_qty, int(item_id), org_id),
    )
    cursor.execute(
        """
        INSERT INTO inventory_adjustments
        (organization_id, item_id, adjustment_type, qty_change, reason, reason_code,
         reference_type, reference_id, created_by_user_id, created_by_name, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s, NOW())
        """,
        (org_id, int(item_id), ADJUSTMENT_MANUAL, qty_change, reason, reason_code, user_id, user_name),
    )
    return {"item_id": int(item_id), "new_on_hand": new_qty}


def get_weekly_order_report(cursor, org_id: int, start_date: date, end_date: date) -> dict:
    ensure_inventory_tables(cursor)
    cursor.execute(
        """
        SELECT COALESCE(SUM(grand_total), 0) AS total, COUNT(*) AS order_count
        FROM inventory_orders
        WHERE organization_id = %s
          AND status IN (%s, %s)
          AND order_date >= %s AND order_date <= %s
        """,
        (org_id, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED, ORDER_RECEIVED, start_date, end_date),
    )
    summary = cursor.fetchone() or {}

    cursor.execute(
        """
        SELECT COALESCE(o.vendor_name, v.name, 'Unknown') AS vendor_name,
               COALESCE(SUM(o.grand_total), 0) AS total
        FROM inventory_orders o
        LEFT JOIN inventory_vendors v ON v.id = o.vendor_id
        WHERE o.organization_id = %s
          AND o.status IN (%s, %s)
          AND o.order_date >= %s AND o.order_date <= %s
        GROUP BY COALESCE(o.vendor_name, v.name, 'Unknown')
        ORDER BY total DESC
        """,
        (org_id, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED, ORDER_RECEIVED, start_date, end_date),
    )
    vendors = [{"vendor_name": r["vendor_name"], "total": _money(r["total"])} for r in (cursor.fetchall() or [])]

    cursor.execute(
        """
        SELECT i.item_name, COALESCE(SUM(ol.qty_ordered), 0) AS qty, COALESCE(SUM(ol.line_total), 0) AS total
        FROM inventory_order_lines ol
        JOIN inventory_orders o ON o.id = ol.order_id
        JOIN inventory_items i ON i.id = ol.item_id
        WHERE o.organization_id = %s
          AND o.status IN (%s, %s)
          AND o.order_date >= %s AND o.order_date <= %s
        GROUP BY i.id, i.item_name
        ORDER BY total DESC
        """,
        (org_id, ORDER_ORDERED, ORDER_PARTIALLY_RECEIVED, ORDER_RECEIVED, start_date, end_date),
    )
    items = [
        {"item_name": r["item_name"], "qty": _float(r["qty"]), "total": _money(r["total"])}
        for r in (cursor.fetchall() or [])
    ]

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_ordered": _money(summary.get("total")),
        "order_count": int(summary.get("order_count") or 0),
        "vendors": vendors,
        "items": items,
    }


def list_bag_sales(cursor, limit: int = 500) -> list[dict]:
    if not table_exists(cursor, "bag_sales"):
        return []
    cursor.execute(
        """
        SELECT id, sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at
        FROM bag_sales
        ORDER BY sale_date DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return cursor.fetchall() or []


def create_bag_sale(cursor, org_id: int, data: dict) -> dict:
    sale_date = data.get("sale_date") or date.today().isoformat()
    customer_name = (data.get("customer_name") or "").strip()
    sale_type = (data.get("sale_type") or "DROP_OFF").strip().upper()
    qty = int(data.get("qty") or 0)
    amount_paid = (data.get("amount_paid") or "").strip() or None
    entered_by = (data.get("entered_by") or "").strip() or None
    if not customer_name or qty <= 0:
        raise ValueError("customer_name and qty>0 are required")

    cursor.execute(
        """
        INSERT INTO bag_sales (sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (sale_date, customer_name, sale_type, qty, amount_paid, entered_by),
    )

    cursor.execute(
        """
        SELECT id, on_hand_qty FROM inventory_items
        WHERE organization_id = %s AND track_retail_sale = 1 AND active = TRUE
        ORDER BY id ASC LIMIT 1
        """,
        (org_id,),
    )
    bag_item = cursor.fetchone()
    if bag_item:
        new_qty = _float(bag_item["on_hand_qty"]) - qty
        cursor.execute(
            "UPDATE inventory_items SET on_hand_qty = %s, updated_at = NOW() WHERE id = %s",
            (new_qty, bag_item["id"]),
        )
        cursor.execute(
            """
            INSERT INTO inventory_adjustments
            (organization_id, item_id, adjustment_type, qty_change, reason, reference_type, reference_id,
             created_by_user_id, created_by_name, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, %s, NOW())
            """,
            (org_id, bag_item["id"], ADJUSTMENT_BAG_SALE, -qty, f"Bag sale: {customer_name}", "bag_sale", entered_by),
        )

    return {"status": "sale_saved"}


def get_activity_report(cursor, org_id: int, *, start_date: str | None = None, end_date: str | None = None, item_id: int | None = None, limit: int = 250) -> dict:
    ensure_inventory_tables(cursor)
    items = list_items(cursor, org_id, active_only=True)

    bag_totals = {"total_bags_sold": 0, "bags_sales_amount": 0.0}
    if table_exists(cursor, "bag_sales"):
        cursor.execute(
            """
            SELECT COALESCE(SUM(qty), 0) AS total_bags_sold,
                   COALESCE(SUM(CASE WHEN amount_paid REGEXP '^[0-9]+(\\.[0-9]+)?$'
                                THEN CAST(amount_paid AS DECIMAL(10,2)) ELSE 0 END), 0) AS bags_sales_amount
            FROM bag_sales
            """
        )
        row = cursor.fetchone() or {}
        bag_totals = {
            "total_bags_sold": int(row.get("total_bags_sold") or 0),
            "bags_sales_amount": _money(row.get("bags_sales_amount")),
        }

    activity: list[dict] = []

    sc_where = ["sc.organization_id = %s", "sc.status = %s"]
    sc_params: list[Any] = [org_id, STOCK_CHECK_SUBMITTED]
    if start_date:
        sc_where.append("sc.check_date >= %s")
        sc_params.append(start_date)
    if end_date:
        sc_where.append("sc.check_date <= %s")
        sc_params.append(end_date)
    if item_id:
        sc_where.append("scl.item_id = %s")
        sc_params.append(item_id)

    cursor.execute(
        f"""
        SELECT scl.id, 'STOCK_CHECK' AS activity_type, sc.submitted_at AS activity_at,
               sc.checked_by_name AS actor, i.item_name, scl.counted_qty AS qty, scl.note AS notes
        FROM inventory_stock_check_lines scl
        JOIN inventory_stock_checks sc ON sc.id = scl.stock_check_id
        JOIN inventory_items i ON i.id = scl.item_id
        WHERE {' AND '.join(sc_where)} AND scl.counted_qty IS NOT NULL
        ORDER BY sc.submitted_at DESC
        LIMIT {limit}
        """,
        tuple(sc_params),
    )
    activity.extend(cursor.fetchall() or [])

    ord_where = ["o.organization_id = %s"]
    ord_params: list[Any] = [org_id]
    if start_date:
        ord_where.append("o.order_date >= %s")
        ord_params.append(start_date)
    if end_date:
        ord_where.append("o.order_date <= %s")
        ord_params.append(end_date)
    if item_id:
        ord_where.append("ol.item_id = %s")
        ord_params.append(item_id)

    cursor.execute(
        f"""
        SELECT ol.id, 'ORDER' AS activity_type, o.created_at AS activity_at,
               o.ordered_by_name AS actor, i.item_name, ol.qty_ordered AS qty,
               o.status AS extra_value, ol.notes
        FROM inventory_order_lines ol
        JOIN inventory_orders o ON o.id = ol.order_id
        JOIN inventory_items i ON i.id = ol.item_id
        WHERE {' AND '.join(ord_where)}
        ORDER BY o.created_at DESC
        LIMIT {limit}
        """,
        tuple(ord_params),
    )
    activity.extend(cursor.fetchall() or [])

    if table_exists(cursor, "bag_sales"):
        bs_where = []
        bs_params: list[Any] = []
        if start_date:
            bs_where.append("sale_date >= %s")
            bs_params.append(start_date)
        if end_date:
            bs_where.append("sale_date <= %s")
            bs_params.append(end_date)
        bs_sql = f"SELECT id, 'BAG_SALE' AS activity_type, created_at AS activity_at, entered_by AS actor, 'Bag Sale' AS item_name, qty, customer_name AS extra_value FROM bag_sales"
        if bs_where:
            bs_sql += f" WHERE {' AND '.join(bs_where)}"
        bs_sql += f" ORDER BY created_at DESC LIMIT {limit}"
        cursor.execute(bs_sql, tuple(bs_params))
        activity.extend(cursor.fetchall() or [])

    activity.sort(key=lambda r: r.get("activity_at") or datetime.min, reverse=True)
    activity = activity[:limit]

    latest = get_latest_stock_check(cursor, org_id)
    latest_count = None
    if latest:
        latest_count = {
            "counted_by": latest.get("checked_by_name"),
            "counted_at": latest.get("submitted_at"),
        }

    return {
        "items": items,
        "bag_totals": bag_totals,
        "latest_count": latest_count,
        "activity": activity,
    }
