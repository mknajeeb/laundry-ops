"""Supply Product Master — CRUD, cost calc, effective-dated pricing (Phase A).

inventory_items decision: NEW (not REUSE / not EXTEND).
Warehouse inventory (stock checks, on-hand, purchase orders, bags/retail) is a
different domain from laundry-process product identity (supply type, dose/load,
effective-dated package cost for historical usage reports). Optional
inventory_item_id can link later without duplicating masters.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.supply_product_constants import (
    FORM_LIQUID,
    LEGACY_REPORT_KEYS,
    PRODUCT_FORMS,
    SEED_PLACEHOLDER_SUMMARY,
    SEED_PRODUCTS,
    SUPPLY_TYPES,
    SUPPLY_TYPE_LABELS,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists

MONEY_Q = Decimal("0.0001")
QTY_Q = Decimal("0.0001")


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None:
        return Decimal(default)
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def _money(val: Any) -> float:
    return float(_d(val).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def _qty(val: Any) -> float:
    return float(_d(val).quantize(QTY_Q, rounding=ROUND_HALF_UP))


def _bool(val: Any, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes", "on")


def _parse_date(val: Any) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except (TypeError, ValueError):
        return None


def calculate_cost_metrics(
    *,
    package_qty: Any,
    average_dose: Any,
    purchase_price_per_package: Any,
) -> dict[str, float | None]:
    """
    doses_per_package = package_qty / average_dose
    cost_per_dose = purchase_price / doses_per_package
    cost_per_standard_load = cost_per_dose (1 dose per standard load)
    """
    pkg = _d(package_qty)
    dose = _d(average_dose)
    price = _d(purchase_price_per_package)
    if pkg <= 0 or dose <= 0:
        return {
            "doses_per_package": None,
            "cost_per_dose": None,
            "cost_per_standard_load": None,
        }
    doses = pkg / dose
    cost_dose = price / doses if doses > 0 else None
    return {
        "doses_per_package": _qty(doses),
        "cost_per_dose": _money(cost_dose) if cost_dose is not None else None,
        "cost_per_standard_load": _money(cost_dose) if cost_dose is not None else None,
    }


def ensure_supply_product_tables(cursor) -> None:
    """Create supply product master tables. Idempotent."""
    created = False
    if not table_exists(cursor, "supply_products"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS supply_products (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              product_code VARCHAR(64) NULL,
              supply_type VARCHAR(40) NOT NULL,
              brand VARCHAR(100) NOT NULL,
              product_name VARCHAR(150) NOT NULL,
              vendor VARCHAR(150) NULL,
              form VARCHAR(20) NOT NULL DEFAULT 'LIQUID',
              package_qty DECIMAL(12,4) NOT NULL,
              package_unit VARCHAR(20) NOT NULL DEFAULT 'oz',
              average_dose DECIMAL(12,4) NOT NULL,
              dose_unit VARCHAR(20) NOT NULL DEFAULT 'oz',
              is_active TINYINT(1) NOT NULL DEFAULT 1,
              legacy_report_key VARCHAR(64) NULL,
              inventory_item_id INT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              notes VARCHAR(500) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_supply_prod_org_legacy (organization_id, legacy_report_key),
              UNIQUE KEY uq_supply_prod_org_code (organization_id, product_code),
              KEY idx_supply_prod_org_type (organization_id, supply_type, is_active),
              KEY idx_supply_prod_org_active (organization_id, is_active, sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        created = True
    if not table_exists(cursor, "supply_product_prices"):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS supply_product_prices (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              product_id INT NOT NULL,
              purchase_price_per_package DECIMAL(12,4) NOT NULL,
              effective_from DATE NOT NULL,
              effective_to DATE NULL,
              notes VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_spp_org_product (organization_id, product_id),
              KEY idx_spp_product_dates (product_id, effective_from, effective_to),
              CONSTRAINT fk_spp_product
                FOREIGN KEY (product_id) REFERENCES supply_products(id)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        created = True
    if created:
        invalidate_schema_cache()


def _validate_product_payload(data: Mapping[str, Any], *, partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not partial or "supply_type" in data:
        st = str(data.get("supply_type") or "").strip().upper()
        if st not in SUPPLY_TYPES:
            raise ValueError(f"supply_type must be one of {', '.join(SUPPLY_TYPES)}")
        out["supply_type"] = st
    if not partial or "brand" in data:
        brand = str(data.get("brand") or "").strip()
        if not brand:
            raise ValueError("brand is required")
        out["brand"] = brand[:100]
    if not partial or "product_name" in data:
        name = str(data.get("product_name") or "").strip()
        if not name:
            raise ValueError("product_name is required")
        out["product_name"] = name[:150]
    if not partial or "form" in data:
        form = str(data.get("form") or FORM_LIQUID).strip().upper()
        if form not in PRODUCT_FORMS:
            raise ValueError(f"form must be one of {', '.join(PRODUCT_FORMS)}")
        out["form"] = form
    if not partial or "package_qty" in data:
        pkg = _d(data.get("package_qty"))
        if pkg <= 0:
            raise ValueError("package_qty must be > 0")
        out["package_qty"] = float(pkg)
    if not partial or "average_dose" in data:
        dose = _d(data.get("average_dose"))
        if dose <= 0:
            raise ValueError("average_dose must be > 0")
        out["average_dose"] = float(dose)
    if "product_code" in data or not partial:
        code = data.get("product_code")
        out["product_code"] = (str(code).strip()[:64] if code else None) or None
    if "vendor" in data or not partial:
        vendor = data.get("vendor")
        out["vendor"] = (str(vendor).strip()[:150] if vendor else None) or None
    if "package_unit" in data or not partial:
        out["package_unit"] = str(data.get("package_unit") or "oz").strip()[:20] or "oz"
    if "dose_unit" in data or not partial:
        out["dose_unit"] = str(data.get("dose_unit") or "oz").strip()[:20] or "oz"
    if "is_active" in data or not partial:
        out["is_active"] = 1 if _bool(data.get("is_active"), True) else 0
    if "legacy_report_key" in data or not partial:
        legacy = data.get("legacy_report_key")
        if legacy is None or str(legacy).strip() == "":
            out["legacy_report_key"] = None
        else:
            key = str(legacy).strip()
            if key not in LEGACY_REPORT_KEYS:
                # Allow custom legacy keys for future products; keep length-bounded.
                out["legacy_report_key"] = key[:64]
            else:
                out["legacy_report_key"] = key
    if "inventory_item_id" in data:
        raw = data.get("inventory_item_id")
        out["inventory_item_id"] = int(raw) if raw not in (None, "") else None
    if "sort_order" in data or not partial:
        try:
            out["sort_order"] = int(data.get("sort_order") or 0)
        except (TypeError, ValueError):
            out["sort_order"] = 0
    if "notes" in data or not partial:
        notes = data.get("notes")
        out["notes"] = (str(notes).strip()[:500] if notes else None) or None
    return out


def _price_row_applies(row: Mapping[str, Any], as_of: date) -> bool:
    start = _parse_date(row.get("effective_from"))
    end = _parse_date(row.get("effective_to"))
    if start is None or start > as_of:
        return False
    if end is not None and end < as_of:
        return False
    return True


def resolve_price_as_of(
    price_rows: Sequence[Mapping[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """
    Historical cost strategy: pick the price row whose effective window covers
    the business date (ET). Later price changes do not rewrite earlier reports.
    """
    day = as_of or business_today()
    applicable = [r for r in price_rows if _price_row_applies(r, day)]
    if not applicable:
        return None
    applicable.sort(
        key=lambda r: (
            _parse_date(r.get("effective_from")) or date.min,
            int(r.get("id") or 0),
        ),
        reverse=True,
    )
    return dict(applicable[0])


def _serialize_product(
    row: Mapping[str, Any],
    *,
    price_row: Mapping[str, Any] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    price = None
    price_meta: dict[str, Any] = {}
    if price_row:
        price = _money(price_row.get("purchase_price_per_package"))
        price_meta = {
            "price_id": price_row.get("id"),
            "effective_from": str(_parse_date(price_row.get("effective_from")) or ""),
            "effective_to": (
                str(_parse_date(price_row.get("effective_to")))
                if _parse_date(price_row.get("effective_to"))
                else None
            ),
            "price_notes": price_row.get("notes"),
        }
    metrics = calculate_cost_metrics(
        package_qty=row.get("package_qty"),
        average_dose=row.get("average_dose"),
        purchase_price_per_package=price if price is not None else 0,
    )
    if price is None:
        metrics = {
            "doses_per_package": metrics["doses_per_package"],
            "cost_per_dose": None,
            "cost_per_standard_load": None,
        }
    supply_type = str(row.get("supply_type") or "")
    return {
        "id": int(row["id"]),
        "organization_id": int(row["organization_id"]),
        "product_code": row.get("product_code"),
        "supply_type": supply_type,
        "supply_type_label": SUPPLY_TYPE_LABELS.get(supply_type, supply_type),
        "brand": row.get("brand"),
        "product_name": row.get("product_name"),
        "vendor": row.get("vendor"),
        "form": row.get("form"),
        "package_qty": _qty(row.get("package_qty")),
        "package_unit": row.get("package_unit") or "oz",
        "purchase_price_per_package": price,
        "average_dose": _qty(row.get("average_dose")),
        "dose_unit": row.get("dose_unit") or "oz",
        "is_active": bool(row.get("is_active")),
        "legacy_report_key": row.get("legacy_report_key"),
        "inventory_item_id": row.get("inventory_item_id"),
        "sort_order": int(row.get("sort_order") or 0),
        "notes": row.get("notes"),
        "as_of_date_et": str(as_of or business_today()),
        **price_meta,
        **metrics,
    }


def list_product_prices(cursor, organization_id: int, product_id: int) -> list[dict[str, Any]]:
    if not table_exists(cursor, "supply_product_prices"):
        return []
    cursor.execute(
        """
        SELECT id, organization_id, product_id, purchase_price_per_package,
               effective_from, effective_to, notes, created_at
        FROM supply_product_prices
        WHERE organization_id = %s AND product_id = %s
        ORDER BY effective_from DESC, id DESC
        """,
        (int(organization_id), int(product_id)),
    )
    rows = cursor.fetchall() or []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "organization_id": int(r["organization_id"]),
                "product_id": int(r["product_id"]),
                "purchase_price_per_package": _money(r.get("purchase_price_per_package")),
                "effective_from": str(_parse_date(r.get("effective_from")) or ""),
                "effective_to": (
                    str(_parse_date(r.get("effective_to")))
                    if _parse_date(r.get("effective_to"))
                    else None
                ),
                "notes": r.get("notes"),
            }
        )
    return out


def get_price_as_of(
    cursor,
    organization_id: int,
    product_id: int,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    rows = list_product_prices(cursor, organization_id, product_id)
    return resolve_price_as_of(rows, as_of)


def list_supply_products(
    cursor,
    organization_id: int,
    *,
    active_only: bool = False,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    ensure_supply_product_tables(cursor)
    day = as_of or business_today()
    sql = """
        SELECT id, organization_id, product_code, supply_type, brand, product_name,
               vendor, form, package_qty, package_unit, average_dose, dose_unit,
               is_active, legacy_report_key, inventory_item_id, sort_order, notes
        FROM supply_products
        WHERE organization_id = %s
    """
    params: list[Any] = [int(organization_id)]
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order ASC, id ASC"
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall() or []
    out: list[dict[str, Any]] = []
    for row in rows:
        price = get_price_as_of(cursor, organization_id, int(row["id"]), day)
        out.append(_serialize_product(row, price_row=price, as_of=day))
    return out


def get_supply_product(
    cursor,
    organization_id: int,
    product_id: int,
    *,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    ensure_supply_product_tables(cursor)
    day = as_of or business_today()
    cursor.execute(
        """
        SELECT id, organization_id, product_code, supply_type, brand, product_name,
               vendor, form, package_qty, package_unit, average_dose, dose_unit,
               is_active, legacy_report_key, inventory_item_id, sort_order, notes
        FROM supply_products
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(product_id)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    price = get_price_as_of(cursor, organization_id, int(row["id"]), day)
    return _serialize_product(row, price_row=price, as_of=day)


def create_supply_product(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_supply_product_tables(cursor)
    payload = _validate_product_payload(data, partial=False)
    cursor.execute(
        """
        INSERT INTO supply_products (
          organization_id, product_code, supply_type, brand, product_name, vendor,
          form, package_qty, package_unit, average_dose, dose_unit, is_active,
          legacy_report_key, inventory_item_id, sort_order, notes, created_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, NOW()
        )
        """,
        (
            int(organization_id),
            payload.get("product_code"),
            payload["supply_type"],
            payload["brand"],
            payload["product_name"],
            payload.get("vendor"),
            payload["form"],
            payload["package_qty"],
            payload["package_unit"],
            payload["average_dose"],
            payload["dose_unit"],
            payload["is_active"],
            payload.get("legacy_report_key"),
            payload.get("inventory_item_id"),
            payload.get("sort_order", 0),
            payload.get("notes"),
        ),
    )
    product_id = int(cursor.lastrowid)
    price = data.get("purchase_price_per_package")
    if price is not None and str(price).strip() != "":
        eff = _parse_date(data.get("effective_from")) or business_today()
        add_product_price(
            cursor,
            organization_id,
            product_id,
            {
                "purchase_price_per_package": price,
                "effective_from": eff,
                "effective_to": data.get("effective_to"),
                "notes": data.get("price_notes"),
            },
        )
    created = get_supply_product(cursor, organization_id, product_id)
    assert created is not None
    return created


def update_supply_product(
    cursor,
    organization_id: int,
    product_id: int,
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    ensure_supply_product_tables(cursor)
    existing = get_supply_product(cursor, organization_id, product_id)
    if not existing:
        return None
    payload = _validate_product_payload({**existing, **dict(data)}, partial=False)
    cursor.execute(
        """
        UPDATE supply_products SET
          product_code = %s,
          supply_type = %s,
          brand = %s,
          product_name = %s,
          vendor = %s,
          form = %s,
          package_qty = %s,
          package_unit = %s,
          average_dose = %s,
          dose_unit = %s,
          is_active = %s,
          legacy_report_key = %s,
          inventory_item_id = %s,
          sort_order = %s,
          notes = %s,
          updated_at = NOW()
        WHERE organization_id = %s AND id = %s
        """,
        (
            payload.get("product_code"),
            payload["supply_type"],
            payload["brand"],
            payload["product_name"],
            payload.get("vendor"),
            payload["form"],
            payload["package_qty"],
            payload["package_unit"],
            payload["average_dose"],
            payload["dose_unit"],
            payload["is_active"],
            payload.get("legacy_report_key"),
            payload.get("inventory_item_id"),
            payload.get("sort_order", 0),
            payload.get("notes"),
            int(organization_id),
            int(product_id),
        ),
    )
    # Optional inline price change: only when effective_from is provided (historical strategy).
    if (
        "purchase_price_per_package" in data
        and data.get("purchase_price_per_package") is not None
        and data.get("effective_from")
    ):
        eff = _parse_date(data.get("effective_from")) or business_today()
        add_product_price(
            cursor,
            organization_id,
            product_id,
            {
                "purchase_price_per_package": data.get("purchase_price_per_package"),
                "effective_from": eff,
                "effective_to": data.get("effective_to"),
                "notes": data.get("price_notes"),
            },
            close_prior_open=True,
        )
    return get_supply_product(cursor, organization_id, product_id)


def add_product_price(
    cursor,
    organization_id: int,
    product_id: int,
    data: Mapping[str, Any],
    *,
    close_prior_open: bool = True,
) -> dict[str, Any]:
    ensure_supply_product_tables(cursor)
    if not get_supply_product(cursor, organization_id, product_id):
        raise ValueError("product not found")
    price = _d(data.get("purchase_price_per_package"))
    if price < 0:
        raise ValueError("purchase_price_per_package must be >= 0")
    eff_from = _parse_date(data.get("effective_from"))
    if eff_from is None:
        raise ValueError("effective_from is required (YYYY-MM-DD ET)")
    eff_to = _parse_date(data.get("effective_to"))
    if eff_to is not None and eff_to < eff_from:
        raise ValueError("effective_to must be on or after effective_from")
    notes = data.get("notes")
    if close_prior_open:
        # Close open-ended prior rows the day before the new effective_from.
        prior_end = eff_from.fromordinal(eff_from.toordinal() - 1) if eff_from.toordinal() > 1 else eff_from
        cursor.execute(
            """
            UPDATE supply_product_prices
            SET effective_to = %s
            WHERE organization_id = %s
              AND product_id = %s
              AND effective_to IS NULL
              AND effective_from < %s
            """,
            (prior_end, int(organization_id), int(product_id), eff_from),
        )
    cursor.execute(
        """
        INSERT INTO supply_product_prices (
          organization_id, product_id, purchase_price_per_package,
          effective_from, effective_to, notes, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            int(organization_id),
            int(product_id),
            float(price),
            eff_from,
            eff_to,
            (str(notes).strip()[:255] if notes else None) or None,
        ),
    )
    price_id = int(cursor.lastrowid)
    return {
        "id": price_id,
        "organization_id": int(organization_id),
        "product_id": int(product_id),
        "purchase_price_per_package": _money(price),
        "effective_from": str(eff_from),
        "effective_to": str(eff_to) if eff_to else None,
        "notes": (str(notes).strip()[:255] if notes else None) or None,
    }


def seed_default_supply_products(cursor, organization_id: int) -> dict[str, Any]:
    """
    Seed operational set when org has no products yet.
    Idempotent: skips if any supply_products rows exist for the org.
    """
    ensure_supply_product_tables(cursor)
    cursor.execute(
        "SELECT COUNT(*) AS c FROM supply_products WHERE organization_id = %s",
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    count = int(row.get("c") if isinstance(row, dict) else (row[0] if row else 0))
    if count > 0:
        return {
            "seeded": False,
            "existing_count": count,
            "products": list_supply_products(cursor, organization_id),
            "placeholder_note": SEED_PLACEHOLDER_SUMMARY,
        }
    created: list[dict[str, Any]] = []
    for seed in SEED_PRODUCTS:
        created.append(
            create_supply_product(
                cursor,
                organization_id,
                {
                    **seed,
                    "is_active": True,
                    "purchase_price_per_package": seed["purchase_price_per_package"],
                    "effective_from": seed["price_effective_from"],
                    "price_notes": "Phase A seed PLACEHOLDER price",
                },
            )
        )
    return {
        "seeded": True,
        "existing_count": 0,
        "products": created,
        "placeholder_note": SEED_PLACEHOLDER_SUMMARY,
    }


def dosages_from_products(
    products: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Map legacy_report_key → average_dose for Supply Usage adapter."""
    out: dict[str, float] = {}
    for p in products:
        if not p.get("is_active", True):
            continue
        key = str(p.get("legacy_report_key") or "").strip()
        if not key:
            continue
        dose = _d(p.get("average_dose"))
        if dose > 0:
            out[key] = float(dose)
    return out


def active_products_by_supply_type(
    products: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """One active product per supply_type (lowest sort_order wins)."""
    by_type: dict[str, dict[str, Any]] = {}
    ordered = sorted(
        [p for p in products if p.get("is_active", True)],
        key=lambda p: (int(p.get("sort_order") or 0), int(p.get("id") or 0)),
    )
    for p in ordered:
        st = str(p.get("supply_type") or "")
        if st and st not in by_type:
            by_type[st] = dict(p)
    return by_type
