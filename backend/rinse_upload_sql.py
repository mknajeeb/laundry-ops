"""SQL helpers for Rinse upload batch row inserts (NaN-safe, schema-aware)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def null_if_na(value: Any) -> Any:
    """Coerce pandas NA/NaN to None for MySQL bind parameters."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def bool_sql_flag(value: Any) -> int:
    value = null_if_na(value)
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    return 1 if value else 0


def upload_batch_rows_timestamp_fragments(cursor) -> tuple[str, str]:
    """Schema-safe created_at/updated_at fragments for upload_batch_rows INSERT."""
    from backend.ta_helpers import table_has_column

    cols: list[str] = []
    vals: list[str] = []
    if table_has_column(cursor, "upload_batch_rows", "created_at"):
        cols.append("created_at")
        vals.append("NOW()")
    if table_has_column(cursor, "upload_batch_rows", "updated_at"):
        cols.append("updated_at")
        vals.append("NOW()")
    if not cols:
        return "", ""
    return ", " + ", ".join(cols), ", " + ", ".join(vals)


def build_upload_batch_row_insert_sql(
    *,
    include_ticket_id: bool,
    include_special_instructions: bool,
    timestamp_cols_sql: str,
    timestamp_vals_sql: str,
) -> str:
    """Build INSERT SQL using fixed column names only (never pandas/dynamic identifiers)."""
    cols = [
        "upload_batch_id",
        "date_clean",
        "name_clean",
        "weight_num",
        "service_type",
        "rush_type",
        "row_status",
        "reason",
    ]
    placeholders = ["%s"] * len(cols)
    if include_ticket_id:
        cols.append("ticket_id")
        placeholders.append("%s")
    if include_special_instructions:
        cols.extend(
            [
                "special_instructions_raw",
                "supply_interpretation",
                "special_instruction_review",
            ]
        )
        placeholders.extend(["%s", "%s", "%s"])
    col_sql = ", ".join(cols) + timestamp_cols_sql
    val_sql = ", ".join(placeholders) + timestamp_vals_sql
    return f"INSERT INTO upload_batch_rows ({col_sql}) VALUES ({val_sql})"


def special_instruction_insert_args(row: Any, *, include: bool) -> list[Any]:
    if not include:
        return []
    return [
        null_if_na(row.get("special_instructions_raw")),
        null_if_na(row.get("supply_interpretation")),
        bool_sql_flag(row.get("special_instruction_review")),
    ]
