"""
Default payroll values for worker profiles (Payroll Management / scheduling profile).

Idempotent backfill only fills null/blank fields — never overwrites custom values.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from backend.ta_helpers import table_has_column

PAYROLL_DEFAULT_REGULAR_RATE = Decimal("17.00")
PAYROLL_DEFAULT_OT_RATE = Decimal("25.50")
PAYROLL_DEFAULT_MAX_HOURS = Decimal("40")
PAYROLL_DEFAULT_OT_THRESHOLD = Decimal("30")

PAYROLL_DEFAULT_FIELDS = (
    ("default_hourly_rate", PAYROLL_DEFAULT_REGULAR_RATE, "rate"),
    ("default_overtime_rate", PAYROLL_DEFAULT_OT_RATE, "ot_rate"),
    ("max_hours_per_week", PAYROLL_DEFAULT_MAX_HOURS, "max_hours"),
    ("overtime_threshold", PAYROLL_DEFAULT_OT_THRESHOLD, "threshold_hours"),
)


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def is_blank_rate(val: Any) -> bool:
    return val is None or val == "" or _d(val) <= 0


def is_blank_hours(val: Any) -> bool:
    return val is None or val == ""


def field_needs_default(field: str, val: Any) -> bool:
    if field in ("default_hourly_rate", "default_overtime_rate"):
        return is_blank_rate(val)
    return is_blank_hours(val)


def default_for_field(field: str) -> Decimal:
    for db_field, default, _ in PAYROLL_DEFAULT_FIELDS:
        if db_field == field:
            return default
    raise KeyError(field)


def apply_payroll_defaults_to_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with display defaults applied for null/blank fields only."""
    out = dict(row)
    for db_field, default, _ in PAYROLL_DEFAULT_FIELDS:
        if field_needs_default(db_field, out.get(db_field)):
            out[db_field] = default
    return out


def audit_custom_payroll_values(cursor, organization_id: int) -> dict[str, Any]:
    """Report workers that already have custom (non-blank) payroll field values."""
    c = cursor if hasattr(cursor, "execute") else cursor.cursor(dictionary=True)
    if not table_has_column(c, "payroll_worker_profiles", "default_overtime_rate"):
        ot_col = "NULL AS default_overtime_rate"
    else:
        ot_col = "default_overtime_rate"
    c.execute(
        f"""
        SELECT id, user_id, default_hourly_rate, {ot_col},
               max_hours_per_week, overtime_threshold
        FROM payroll_worker_profiles
        WHERE organization_id=%s
        """,
        (int(organization_id),),
    )
    rows = c.fetchall() if hasattr(c, "fetchall") else []
    workers: list[dict[str, Any]] = []
    for row in rows:
        custom: dict[str, Any] = {}
        for db_field, _default, label in PAYROLL_DEFAULT_FIELDS:
            val = row.get(db_field)
            if not field_needs_default(db_field, val):
                custom[label] = float(_d(val)) if db_field.endswith("_rate") or "hours" in db_field or "threshold" in db_field else val
        if custom:
            workers.append(
                {
                    "worker_profile_id": int(row["id"]),
                    "user_id": int(row["user_id"]),
                    "custom_fields": custom,
                }
            )
    return {
        "organization_id": int(organization_id),
        "custom_count": len(workers),
        "workers": workers,
    }


def backfill_payroll_worker_defaults(conn, organization_id: int) -> dict[str, Any]:
    """
    Idempotent DB backfill: set default payroll values only where fields are null/blank.
    Returns audit of existing custom values plus per-field update counts.
    """
    audit = audit_custom_payroll_values(conn.cursor(dictionary=True), organization_id)
    c = conn.cursor()
    oid = int(organization_id)
    updated_by_field: dict[str, int] = {}
    for db_field, default, label in PAYROLL_DEFAULT_FIELDS:
        if db_field == "default_overtime_rate" and not table_has_column(
            c, "payroll_worker_profiles", "default_overtime_rate"
        ):
            updated_by_field[label] = 0
            continue
        if db_field in ("default_hourly_rate", "default_overtime_rate"):
            blank_sql = f"({db_field} IS NULL OR {db_field} <= 0)"
        else:
            blank_sql = f"{db_field} IS NULL"
        c.execute(
            f"""
            UPDATE payroll_worker_profiles
            SET {db_field}=%s
            WHERE organization_id=%s AND {blank_sql}
            """,
            (default, oid),
        )
        updated_by_field[label] = int(c.rowcount or 0)
    total_updated = sum(updated_by_field.values())
    return {
        "audit": audit,
        "updated_by_field": updated_by_field,
        "total_field_updates": total_updated,
        "custom_values_preserved": audit["custom_count"],
    }


def ensure_worker_profile_payroll_defaults(conn, organization_id: int, profile_id: int) -> None:
    """Fill missing payroll fields on a single profile row (idempotent)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM payroll_worker_profiles WHERE id=%s AND organization_id=%s",
        (int(profile_id), int(organization_id)),
    )
    row = c.fetchone()
    if not row:
        return
    sets = []
    params: list[Any] = []
    for db_field, default, _ in PAYROLL_DEFAULT_FIELDS:
        if db_field == "default_overtime_rate" and not table_has_column(
            c, "payroll_worker_profiles", "default_overtime_rate"
        ):
            continue
        if field_needs_default(db_field, row.get(db_field)):
            sets.append(f"{db_field}=%s")
            params.append(default)
    if not sets:
        return
    params.extend([int(profile_id), int(organization_id)])
    conn.cursor().execute(
        f"UPDATE payroll_worker_profiles SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
        tuple(params),
    )


def new_worker_payroll_defaults(*, hourly_rate: Optional[Any] = None) -> dict[str, Decimal]:
    """Defaults for a newly created worker profile."""
    rate = None if is_blank_rate(hourly_rate) else _d(hourly_rate)
    return {
        "default_hourly_rate": rate or PAYROLL_DEFAULT_REGULAR_RATE,
        "default_overtime_rate": PAYROLL_DEFAULT_OT_RATE,
        "max_hours_per_week": PAYROLL_DEFAULT_MAX_HOURS,
        "overtime_threshold": PAYROLL_DEFAULT_OT_THRESHOLD,
    }
