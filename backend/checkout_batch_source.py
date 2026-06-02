"""Per-tenant checkout batch source: manual upload file vs auto portal scrape."""

from __future__ import annotations

from typing import Any, Literal

from backend.ta_helpers import table_exists, table_has_column

CheckoutBatchSource = Literal["manual", "auto"]

KEY_CHECKOUT_BATCH_SOURCE = "ops_checkout_batch_source"
VALID_SOURCES: frozenset[str] = frozenset({"manual", "auto"})


def normalize_checkout_batch_source(raw: Any, *, default: CheckoutBatchSource = "manual") -> CheckoutBatchSource:
    s = str(raw or "").strip().lower()
    if s in VALID_SOURCES:
        return s  # type: ignore[return-value]
    return default


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def get_checkout_batch_source(cursor, organization_id: int) -> CheckoutBatchSource:
    return normalize_checkout_batch_source(
        _get_setting(cursor, organization_id, KEY_CHECKOUT_BATCH_SOURCE),
        default="manual",
    )


def upload_batch_is_auto_scrape(
    cursor,
    batch_id: int,
    organization_id: int | None = None,
) -> bool:
    """
    True when batch came from scheduled Rinse scrape (ACA job / scrape.mjs).

    Manual Washpro dual-CSV portal uploads are NOT auto — only scrape-run linkage or
    portal_scrape_meta from scrape.mjs counts.
    """
    bid = int(batch_id)
    org = int(organization_id) if organization_id is not None else None

    if table_exists(cursor, "rinse_scrape_runs"):
        for col in ("imported_batch_id", "upload_batch_id", "batch_id"):
            if not table_has_column(cursor, "rinse_scrape_runs", col):
                continue
            sql = f"SELECT 1 AS ok FROM rinse_scrape_runs WHERE {col} = %s"
            args: list[Any] = [bid]
            if org is not None and table_has_column(cursor, "rinse_scrape_runs", "organization_id"):
                sql += " AND organization_id = %s"
                args.append(org)
            sql += " LIMIT 1"
            cursor.execute(sql, tuple(args))
            if cursor.fetchone():
                return True

    if not table_exists(cursor, "upload_batches"):
        return False

    batch_pk = "batch_id"
    if table_has_column(cursor, "upload_batches", "id") and not table_has_column(
        cursor, "upload_batches", "batch_id"
    ):
        batch_pk = "id"

    cols = []
    if table_has_column(cursor, "upload_batches", "portal_scrape_meta"):
        cols.append("portal_scrape_meta")
    if table_has_column(cursor, "upload_batches", "file_name"):
        cols.append("file_name")
    if not cols:
        return False

    sql = f"SELECT {', '.join(cols)} FROM upload_batches WHERE {batch_pk} = %s"
    args = [bid]
    if org is not None and table_has_column(cursor, "upload_batches", "organization_id"):
        sql += " AND organization_id = %s"
        args.append(org)
    sql += " LIMIT 1"
    cursor.execute(sql, tuple(args))
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return False

    meta = row.get("portal_scrape_meta")
    if meta not in (None, "", "null", "NULL"):
        return True

    return False
