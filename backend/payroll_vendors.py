"""Staffing vendors for temp / 1099 workers.

A vendor is the source company a temporary or 1099 contractor comes from
(e.g. "Washmate Inc"). Vendors drive the branding (name, address, logo) shown
on the Contractor Invoice & Payment Receipt that replaces the paystub for
temp/1099 workers. Vendors never affect wages, taxes, gross, net, OT, or YTD
amounts — only which letterhead the receipt is issued under.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.ta_helpers import invalidate_schema_cache, json_safe, table_has_column

# Seeded default vendor. Existing temp/1099 workers default to this.
DEFAULT_VENDOR_NAME = "Washmate Inc"
DEFAULT_VENDOR_ADDRESS = "921 2nd Avenue, Franklin Square, NY 11010"
DEFAULT_VENDOR_LOGO_URL = "/assets/washmate-logo.png"


def ensure_payroll_vendor_tables(cursor) -> None:
    """Create payroll_vendors and add vendor linkage columns (idempotent)."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_vendors (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          name VARCHAR(255) NOT NULL,
          address TEXT NULL,
          logo_url VARCHAR(1024) NULL,
          representative_name VARCHAR(255) NULL,
          representative_title VARCHAR(255) NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_vendor_org_name (organization_id, name)
        )
        """
    )
    # Authorized signer for the vendor (additive; nullable for existing rows).
    for col in ("representative_name", "representative_title"):
        if not table_has_column(cursor, "payroll_vendors", col):
            try:
                cursor.execute(
                    f"ALTER TABLE payroll_vendors ADD COLUMN {col} VARCHAR(255) NULL"
                )
            except Exception as exc:  # pragma: no cover - column race
                if getattr(exc, "args", (None,))[0] != 1060:
                    raise
            invalidate_schema_cache()
    # Worker-level default vendor (payroll_profiles is keyed by user_id).
    if not table_has_column(cursor, "payroll_profiles", "default_vendor_id"):
        try:
            cursor.execute(
                "ALTER TABLE payroll_profiles ADD COLUMN default_vendor_id INT NULL"
            )
        except Exception as exc:  # pragma: no cover - column race
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()
    # Per batch-line override.
    if not table_has_column(cursor, "payout_batch_lines", "vendor_id"):
        try:
            cursor.execute(
                "ALTER TABLE payout_batch_lines ADD COLUMN vendor_id INT NULL"
            )
        except Exception as exc:  # pragma: no cover - column race
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()


def _vendor_row(row: dict) -> dict:
    return json_safe(
        {
            "id": int(row["id"]),
            "name": row.get("name"),
            "address": row.get("address"),
            "logo_url": row.get("logo_url"),
            "representative_name": row.get("representative_name"),
            "representative_title": row.get("representative_title"),
            "active": bool(row.get("active", 1)),
        }
    )


def list_vendors(
    conn, organization_id: int, *, include_inactive: bool = True
) -> list[dict]:
    ensure_payroll_vendor_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    q = "SELECT * FROM payroll_vendors WHERE organization_id=%s"
    params: list[Any] = [int(organization_id)]
    if not include_inactive:
        q += " AND active=1"
    q += " ORDER BY active DESC, name"
    c.execute(q, tuple(params))
    return [_vendor_row(r) for r in c.fetchall() or []]


def get_vendor(conn, organization_id: int, vendor_id: int) -> Optional[dict]:
    ensure_payroll_vendor_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payroll_vendors WHERE id=%s AND organization_id=%s",
        (int(vendor_id), int(organization_id)),
    )
    row = c.fetchone()
    return _vendor_row(row) if row else None


def ensure_payment_vendors(conn, organization_id: int) -> list[dict]:
    """Ensure VeeWash and Washmate exist. Does not rename existing Washmate Inc rows."""
    ensure_default_vendor(conn, organization_id)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payroll_vendors WHERE organization_id=%s AND name=%s",
        (int(organization_id), "VeeWash"),
    )
    if not c.fetchone():
        ins = conn.cursor()
        try:
            ins.execute(
                """
                INSERT INTO payroll_vendors (organization_id, name, active)
                VALUES (%s, 'VeeWash', 1)
                """,
                (int(organization_id),),
            )
            conn.commit()
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1062:
                raise
    return list_vendors(conn, organization_id, include_inactive=False)


def list_payment_vendors(conn, organization_id: int) -> list[dict]:
    """VeeWash / Washmate only, for Finalize Payment."""
    from backend.payroll_worker_categories import is_payment_vendor_name, payment_vendor_display_name

    ensure_payment_vendors(conn, organization_id)
    out = []
    for v in list_vendors(conn, organization_id, include_inactive=False):
        if not is_payment_vendor_name(v.get("name")):
            continue
        item = dict(v)
        item["display_name"] = payment_vendor_display_name(v.get("name"))
        out.append(item)
    out.sort(key=lambda x: str(x.get("display_name") or ""))
    return out


def ensure_default_vendor(conn, organization_id: int) -> dict:
    """Return the seeded default vendor for the org, creating it if absent."""
    ensure_payroll_vendor_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payroll_vendors WHERE organization_id=%s AND name=%s",
        (int(organization_id), DEFAULT_VENDOR_NAME),
    )
    row = c.fetchone()
    if row:
        return _vendor_row(row)
    ins = conn.cursor()
    ins.execute(
        """
        INSERT INTO payroll_vendors (organization_id, name, address, logo_url, active)
        VALUES (%s, %s, %s, %s, 1)
        """,
        (
            int(organization_id),
            DEFAULT_VENDOR_NAME,
            DEFAULT_VENDOR_ADDRESS,
            DEFAULT_VENDOR_LOGO_URL,
        ),
    )
    conn.commit()
    return get_vendor(conn, organization_id, int(ins.lastrowid))  # type: ignore[arg-type]


def create_vendor(
    conn,
    organization_id: int,
    *,
    name: str,
    address: Optional[str] = None,
    logo_url: Optional[str] = None,
    representative_name: Optional[str] = None,
    representative_title: Optional[str] = None,
) -> dict:
    ensure_payroll_vendor_tables(conn.cursor())
    clean_name = str(name or "").strip()
    if len(clean_name) < 2:
        raise ValueError("Vendor name is required")
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO payroll_vendors
              (organization_id, name, address, logo_url,
               representative_name, representative_title, active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (
                int(organization_id),
                clean_name,
                str(address or "").strip() or None,
                str(logo_url or "").strip() or None,
                str(representative_name or "").strip() or None,
                str(representative_title or "").strip() or None,
            ),
        )
    except Exception as exc:
        if getattr(exc, "args", (None,))[0] == 1062:
            raise ValueError("A vendor with this name already exists")
        raise
    conn.commit()
    return get_vendor(conn, organization_id, int(c.lastrowid))  # type: ignore[arg-type]


def update_vendor(
    conn,
    organization_id: int,
    vendor_id: int,
    *,
    name: Optional[str] = None,
    address: Optional[str] = None,
    logo_url: Optional[str] = None,
    representative_name: Optional[str] = None,
    representative_title: Optional[str] = None,
    active: Optional[bool] = None,
) -> dict:
    existing = get_vendor(conn, organization_id, vendor_id)
    if not existing:
        raise ValueError("Vendor not found")
    fields: list[str] = []
    params: list[Any] = []
    if name is not None:
        clean = str(name).strip()
        if len(clean) < 2:
            raise ValueError("Vendor name is required")
        fields.append("name=%s")
        params.append(clean)
    if address is not None:
        fields.append("address=%s")
        params.append(str(address).strip() or None)
    if logo_url is not None:
        fields.append("logo_url=%s")
        params.append(str(logo_url).strip() or None)
    if representative_name is not None:
        fields.append("representative_name=%s")
        params.append(str(representative_name).strip() or None)
    if representative_title is not None:
        fields.append("representative_title=%s")
        params.append(str(representative_title).strip() or None)
    if active is not None:
        fields.append("active=%s")
        params.append(1 if active else 0)
    if not fields:
        return existing
    params.extend([int(vendor_id), int(organization_id)])
    c = conn.cursor()
    try:
        c.execute(
            f"UPDATE payroll_vendors SET {', '.join(fields)}, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s",
            tuple(params),
        )
    except Exception as exc:
        if getattr(exc, "args", (None,))[0] == 1062:
            raise ValueError("A vendor with this name already exists")
        raise
    conn.commit()
    return get_vendor(conn, organization_id, vendor_id)  # type: ignore[return-value]


def set_worker_default_vendor(
    conn, organization_id: int, user_id: int, vendor_id: Optional[int]
) -> Optional[int]:
    """Set (or clear) the worker-level default vendor. Validates org ownership."""
    ensure_payroll_vendor_tables(conn.cursor())
    resolved: Optional[int] = None
    if vendor_id is not None:
        vendor = get_vendor(conn, organization_id, int(vendor_id))
        if not vendor:
            raise ValueError("Vendor not found")
        resolved = int(vendor_id)
    c = conn.cursor()
    c.execute(
        "UPDATE payroll_profiles SET default_vendor_id=%s WHERE user_id=%s",
        (resolved, int(user_id)),
    )
    conn.commit()
    return resolved


def _worker_default_vendor_id(conn, user_id: int) -> Optional[int]:
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            "SELECT default_vendor_id FROM payroll_profiles WHERE user_id=%s",
            (int(user_id),),
        )
    except Exception:
        return None
    row = c.fetchone()
    if not row:
        return None
    val = row.get("default_vendor_id")
    return int(val) if val is not None else None


def resolve_line_vendor(
    conn, organization_id: int, line: dict, batch: Optional[dict] = None
) -> Optional[dict]:
    """Resolve a line's vendor: line override → worker default → org default.

    Only temp / contractor_1099 batches use vendors. Returns None for W-2.
    """
    cat = str((batch or {}).get("worker_category") or line.get("worker_category") or "")
    from backend.payroll_worker_categories import is_vendor_receipt_category

    if not is_vendor_receipt_category(cat):
        return None
    # 1) Immutable snapshot if already finalized onto the line JSON.
    snap = _line_vendor_snapshot(line)
    if snap:
        return snap
    # 2) Explicit per-line override column.
    line_vendor_id = line.get("vendor_id")
    if line_vendor_id:
        v = get_vendor(conn, organization_id, int(line_vendor_id))
        if v and v.get("active"):
            return v
        if v:
            return v
    # 3) Worker-level default.
    uid = line.get("user_id")
    if uid:
        wv = _worker_default_vendor_id(conn, int(uid))
        if wv:
            v = get_vendor(conn, organization_id, wv)
            if v:
                return v
    # 4) Org default (Washmate Inc).
    return ensure_default_vendor(conn, organization_id)


def _line_vendor_snapshot(line: dict) -> Optional[dict]:
    details = line.get("payout_details")
    if not isinstance(details, dict):
        return None
    snap = details.get("vendor")
    if isinstance(snap, dict) and snap.get("name"):
        return json_safe(
            {
                "id": snap.get("id"),
                "name": snap.get("name"),
                "address": snap.get("address"),
                "logo_url": snap.get("logo_url"),
                "representative_name": snap.get("representative_name"),
                "representative_title": snap.get("representative_title"),
                "active": True,
                "snapshot": True,
            }
        )
    return None


def vendor_snapshot_for_finalize(vendor: Optional[dict]) -> Optional[dict]:
    """Compact, immutable branding snapshot to store in payout_details_json."""
    if not vendor:
        return None
    return {
        "id": vendor.get("id"),
        "name": vendor.get("name"),
        "address": vendor.get("address"),
        "logo_url": vendor.get("logo_url"),
        "representative_name": vendor.get("representative_name"),
        "representative_title": vendor.get("representative_title"),
    }
