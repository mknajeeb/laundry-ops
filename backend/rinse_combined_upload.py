"""
Rinse upload batch orchestration: portal-only and combined dual-CSV flows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

REQUIRE_DUAL_CSV_CODE = "REQUIRE_DUAL_CSV"
REQUIRE_DUAL_CSV_MESSAGE = (
    "Both portal order CSV and Rinse scan-events CSV are required. "
    "Use Upload both / create draft."
)


def _active_staging_where_sql(cursor) -> str:
    """Active-at-Washpro filter without importing Flask app."""
    from backend.ta_helpers import table_has_column

    has_logistics = table_has_column(cursor, "orders_staging", "logistics_status")
    has_status = table_has_column(cursor, "orders_staging", "status")
    if has_logistics:
        if has_status:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if has_status:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def dual_csv_required_error() -> tuple[dict, int]:
    return (
        {
            "status": "error",
            "message": REQUIRE_DUAL_CSV_MESSAGE,
            "code": REQUIRE_DUAL_CSV_CODE,
        },
        400,
    )


@dataclass
class UploadBatchSchema:
    upload_batches_pk: str
    row_pk: str
    has_ub_org: bool
    has_state: bool
    has_closed_at: bool
    has_updated_at: bool
    has_rows_inserted: bool
    time_col: str | None
    cap: dict


def get_upload_batch_schema(cursor) -> UploadBatchSchema:
    from backend.app import (
        get_upload_batch_rows_pk,
        get_upload_batches_pk,
        orders_status_capabilities,
        table_has_column,
        upload_batches_time_col,
    )

    return UploadBatchSchema(
        upload_batches_pk=get_upload_batches_pk(cursor),
        row_pk=get_upload_batch_rows_pk(cursor),
        has_ub_org=table_has_column(cursor, "upload_batches", "organization_id"),
        has_state=table_has_column(cursor, "upload_batches", "state"),
        has_closed_at=table_has_column(cursor, "upload_batches", "closed_at"),
        has_updated_at=table_has_column(cursor, "upload_batches", "updated_at"),
        has_rows_inserted=table_has_column(cursor, "upload_batches", "rows_inserted"),
        time_col=upload_batches_time_col(cursor),
        cap=orders_status_capabilities(cursor),
    )


def prepare_orders_df(orders_df: pd.DataFrame) -> pd.DataFrame:
    from backend.app import build_fingerprint, normalize_weight

    df = orders_df.copy()
    df["Name_Clean"] = df["Name_Clean"].astype(str).str.strip()
    df["Weight_Num"] = df["Weight_Num"].apply(normalize_weight)
    df["fingerprint"] = df.apply(
        lambda row: build_fingerprint(
            row.get("Name_Clean"),
            row.get("Weight_Num"),
            row.get("ServiceType"),
        ),
        axis=1,
    )
    return df


def close_prior_draft_batches(
    cursor, tenant_oid: int, batch_date: date, schema: UploadBatchSchema
) -> None:
    if not schema.has_state:
        return
    close_clause = "state = 'CLOSED'"
    if schema.has_closed_at:
        close_clause += ", closed_at = NOW()"
    if schema.has_updated_at:
        close_clause += ", updated_at = NOW()"

    draft_where = "WHERE state = 'DRAFT'"
    draft_args: list[Any] = []
    if schema.has_ub_org:
        draft_where += " AND organization_id = %s"
        draft_args.append(tenant_oid)
    cursor.execute(
        f"""
        UPDATE upload_batches
        SET {close_clause}
        {draft_where}
        """,
        tuple(draft_args),
    )

    same_sql = f"""
        UPDATE upload_batches
        SET {close_clause}
        WHERE batch_date = %s
        AND state <> 'CONFIRMED'
    """
    same_args: list[Any] = [batch_date]
    if schema.has_ub_org:
        same_sql += " AND organization_id = %s"
        same_args.append(tenant_oid)
    cursor.execute(same_sql, tuple(same_args))


def create_draft_upload_batch_shell(
    cursor,
    tenant_oid: int,
    batch_date: date,
    file_name: str,
    schema: UploadBatchSchema,
) -> int:
    from backend.app import ensure_ticket_id_columns, ensure_upload_batch_rows_ticket_id

    ensure_ticket_id_columns(cursor)
    ensure_upload_batch_rows_ticket_id(cursor)
    close_prior_draft_batches(cursor, tenant_oid, batch_date, schema)

    insert_cols = ["file_name", "batch_date", "orders_loaded"]
    insert_vals = ["%s", "%s", "%s"]
    insert_args: list[Any] = [file_name, batch_date, 0]
    if schema.has_ub_org:
        insert_cols = ["organization_id"] + insert_cols
        insert_vals = ["%s"] + insert_vals
        insert_args = [tenant_oid] + insert_args
    if schema.has_state:
        insert_cols.append("state")
        insert_vals.append("'DRAFT'")
    if schema.time_col == "created_at":
        insert_cols.append("created_at")
        insert_vals.append("NOW()")

    cursor.execute(
        f"""
        INSERT INTO upload_batches
        ({", ".join(insert_cols)})
        VALUES ({", ".join(insert_vals)})
        """,
        tuple(insert_args),
    )
    return int(cursor.lastrowid)


def _duplicate_lookback_days() -> int:
    try:
        n = int(os.getenv("DUPLICATE_LOOKBACK_DAYS", "3"))
    except Exception:
        n = 3
    return max(1, min(n, 30))


def build_upload_duplicate_indexes(
    cursor, tenant_oid: int, schema: UploadBatchSchema
) -> tuple[set, dict, int]:
    from backend.app import (
        build_identity_key,
        orders_logistics_select_sql,
        orders_processing_select_sql,
        table_exists,
        table_has_column,
    )

    duplicate_lookback_days = _duplicate_lookback_days()
    cap = schema.cap
    logistics_sql = orders_logistics_select_sql(cap)
    processing_sql = orders_processing_select_sql(cap)
    staging_sql = f"""
        SELECT
            id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            {logistics_sql},
            {processing_sql},
            status
        FROM orders_staging
    """
    staging_args: list[Any] = []
    if table_has_column(cursor, "orders_staging", "organization_id"):
        staging_sql += " WHERE organization_id = %s"
        staging_args.append(tenant_oid)
    cursor.execute(staging_sql, tuple(staging_args))
    staging_rows = cursor.fetchall()
    existing_identity_reasons: dict = {}

    def staging_reason_for_status(raw_logistics, raw_status):
        logistics = (raw_logistics or "").strip().upper()
        status = (raw_status or "").strip().upper()
        if logistics:
            if logistics in ["SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"]:
                return "ALREADY_SENT_OR_FORCED"
            return "DUPLICATE_IN_STAGING"
        if status in ["CHECKED_OUT", "SENT_TO_RINSE", "FORCED_CHECKOUT", "FORCE_CHECKOUT"]:
            return "ALREADY_SENT_OR_FORCED"
        return "DUPLICATE_IN_STAGING"

    for r in staging_rows:
        identity_key = build_identity_key(
            r.get("name_clean"),
            r.get("weight_num"),
            r.get("service_type"),
            r.get("date_clean"),
        )
        next_reason = staging_reason_for_status(r.get("logistics_status"), r.get("status"))
        prev_reason = existing_identity_reasons.get(identity_key)
        if prev_reason != "ALREADY_SENT_OR_FORCED":
            existing_identity_reasons[identity_key] = next_reason

    final_cutoff = datetime.utcnow() - timedelta(days=duplicate_lookback_days)
    final_sql = """
        SELECT
            date_clean,
            name_clean,
            weight_num,
            service_type
        FROM orders_final
        WHERE cleaned_at >= %s
    """
    final_args: list[Any] = [final_cutoff]
    if table_exists(cursor, "orders_final") and table_has_column(
        cursor, "orders_final", "organization_id"
    ):
        final_sql += " AND organization_id = %s"
        final_args.append(tenant_oid)
    cursor.execute(final_sql, tuple(final_args))
    final_rows = cursor.fetchall()
    final_identity_keys = {
        build_identity_key(
            r.get("name_clean"),
            r.get("weight_num"),
            r.get("service_type"),
            r.get("date_clean"),
        )
        for r in final_rows
    }
    return final_identity_keys, existing_identity_reasons, duplicate_lookback_days


def collect_portal_ticket_ids(orders_df: pd.DataFrame) -> list[str]:
    from backend.rinse_bag_completion import normalize_bag_id

    if "ticket_id" not in orders_df.columns:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in orders_df["ticket_id"]:
        bid = normalize_bag_id(v)
        if bid and bid not in seen:
            seen.add(bid)
            out.append(bid)
    return out


def snapshot_pre_upload_completed_bag_ids(
    cursor, tenant_oid: int, orders_df: pd.DataFrame
) -> set[str]:
    """
    Portal bag IDs already COMPLETED in rinse_bag_registry before this upload begins.

    Reads registry only — no merge, no recompute, no scan-event writes in this transaction.
    Completion discovered during the same upload must not appear in this set.
    """
    from backend.rinse_bag_registry import fetch_pre_existing_completed_bag_ids

    return fetch_pre_existing_completed_bag_ids(
        cursor, tenant_oid, collect_portal_ticket_ids(orders_df)
    )


def collect_pre_existing_completed_bag_ids(
    cursor, tenant_oid: int, orders_df: pd.DataFrame
) -> set[str]:
    """Alias for snapshot_pre_upload_completed_bag_ids."""
    return snapshot_pre_upload_completed_bag_ids(cursor, tenant_oid, orders_df)


def collect_bag_ids_from_upload(orders_df: pd.DataFrame, events_df: pd.DataFrame) -> list[str]:
    from backend.rinse_bag_completion import normalize_bag_id

    bag_ids: set[str] = set()
    if "ticket_id" in orders_df.columns:
        for v in orders_df["ticket_id"]:
            bid = normalize_bag_id(v)
            if bid:
                bag_ids.add(bid)
    if "Bag ID" in events_df.columns:
        for v in events_df["Bag ID"]:
            bid = normalize_bag_id(v)
            if bid:
                bag_ids.add(bid)
    return sorted(bag_ids)


def insert_upload_batch_rows_from_orders_df(
    cursor,
    tenant_oid: int,
    upload_batch_id: int,
    batch_date: date,
    orders_df: pd.DataFrame,
    schema: UploadBatchSchema,
    final_identity_keys: set,
    existing_identity_reasons: dict,
    pre_existing_completed_bag_ids: set[str] | None = None,
    *,
    is_auto_scrape: bool = False,
    pending_events_df: pd.DataFrame | None = None,
) -> dict[str, int]:
    from backend.app import build_identity_key, parse_date_value, table_has_column
    from backend.rinse_bag_completion import classify_portal_upload_row, normalize_bag_id
    from backend.rinse_bag_upload import (
        _ensure_ticket_id_columns,
        _ensure_upload_batch_rows_special_instruction_columns,
        find_active_staging_for_portal_upload,
    )

    from backend.rinse_upload_sql import (
        build_upload_batch_row_insert_sql,
        null_if_na,
        special_instruction_insert_args,
        upload_batch_rows_timestamp_fragments,
    )

    if pre_existing_completed_bag_ids is None:
        pre_existing_completed_bag_ids = collect_pre_existing_completed_bag_ids(
            cursor, tenant_oid, orders_df
        )

    from backend.ta_helpers import table_exists

    _ensure_ticket_id_columns(cursor)
    _ensure_upload_batch_rows_special_instruction_columns(cursor)
    if table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        pass
    elif table_exists(cursor, "upload_batch_rows"):
        cursor.execute(
            "ALTER TABLE upload_batch_rows ADD COLUMN ticket_id VARCHAR(120) NULL"
        )
        from backend.ta_helpers import invalidate_schema_cache

        invalidate_schema_cache()

    cap = schema.cap
    active_where = _active_staging_where_sql(cursor)
    inserted = 0
    rejected = 0
    needs_attention = 0
    has_ticket_source = "ticket_id" in orders_df.columns
    from backend.ta_helpers import table_has_column as ta_table_has_column

    has_ubr_ticket = ta_table_has_column(cursor, "upload_batch_rows", "ticket_id")
    has_ubr_si = ta_table_has_column(cursor, "upload_batch_rows", "special_instructions_raw")
    include_tid = bool(has_ticket_source and has_ubr_ticket)
    has_staging_org = ta_table_has_column(cursor, "orders_staging", "organization_id")
    ts_cols_sql, ts_vals_sql = upload_batch_rows_timestamp_fragments(cursor)
    insert_sql = build_upload_batch_row_insert_sql(
        include_ticket_id=include_tid,
        include_special_instructions=has_ubr_si,
        timestamp_cols_sql=ts_cols_sql,
        timestamp_vals_sql=ts_vals_sql,
    )

    for _, row in orders_df.iterrows():
        date_clean = row.get("Date_Clean")
        name_clean = row.get("Name_Clean")
        weight_num = row.get("Weight_Num")
        service_type = null_if_na(row.get("ServiceType")) or "WF"
        rush_type_raw = row.get("RushType")

        if pd.isna(date_clean) or pd.isna(name_clean):
            continue

        if pd.isna(weight_num):
            weight_num = None

        if isinstance(date_clean, datetime):
            row_date = date_clean.date()
        elif isinstance(date_clean, date):
            row_date = date_clean
        else:
            row_date = parse_date_value(date_clean)
        is_batch_date_rush = row_date == batch_date
        rush_type = "RUSH" if (str(rush_type_raw).upper() == "RUSH" or is_batch_date_rush) else "NON-RUSH"

        identity_key = build_identity_key(name_clean, weight_num, service_type, row_date)

        ticket_id = None
        rinse_bag_row = False
        if include_tid:
            tv = row.get("ticket_id")
            if tv is not None and not (isinstance(tv, float) and pd.isna(tv)):
                ts = normalize_bag_id(tv)
                ticket_id = ts if ts else None
                if ticket_id:
                    rinse_bag_row = True
                    staging_hit = find_active_staging_for_portal_upload(
                        cursor,
                        tenant_oid,
                        ticket_id,
                        active_where,
                        has_staging_org=has_staging_org,
                        portal_row={
                            "name_clean": name_clean,
                            "weight_num": weight_num,
                            "service_type": service_type,
                            "date_clean": row_date,
                        },
                    )
                    was_completed_before = ticket_id in pre_existing_completed_bag_ids
                    from backend.manual_checkout_eligibility import classify_upload_row_for_checkout

                    row_status, reason = classify_upload_row_for_checkout(
                        cursor,
                        tenant_oid,
                        ticket_id=ticket_id,
                        has_active_staging=staging_hit is not None,
                        row_date_before_batch=row_date < batch_date,
                        was_completed_before_upload=was_completed_before,
                        pending_events_df=pending_events_df,
                        is_auto_scrape=is_auto_scrape,
                    )
                    if row_status == "REJECTED_DUPLICATE":
                        rejected += 1
                    elif row_status == "NEEDS_ATTENTION":
                        needs_attention += 1
                    elif row_status == "ACCEPTED":
                        inserted += 1

        if not rinse_bag_row:
            row_status = "ACCEPTED"
            reason = "OK"
            if row_date < batch_date:
                row_status = "NEEDS_ATTENTION"
                reason = "OLDER_THAN_BATCH_DATE"
                needs_attention += 1
            elif identity_key in final_identity_keys:
                row_status = "REJECTED_DUPLICATE"
                reason = "ALREADY_IN_FINAL"
                rejected += 1
            elif identity_key in existing_identity_reasons:
                row_status = "REJECTED_DUPLICATE"
                reason = existing_identity_reasons[identity_key]
                rejected += 1
            else:
                row_status = "ACCEPTED"
                reason = "OK"
                inserted += 1

            if include_tid and ticket_id is None:
                tv = row.get("ticket_id")
                if tv is not None and not (isinstance(tv, float) and pd.isna(tv)):
                    ts = normalize_bag_id(tv)
                    ticket_id = ts if ts else None

        if include_tid:
            row_args: list[Any] = [
                upload_batch_id,
                row_date,
                name_clean,
                null_if_na(weight_num),
                service_type,
                rush_type,
                row_status,
                reason,
                ticket_id,
                *special_instruction_insert_args(row, include=has_ubr_si),
            ]
        else:
            row_args = [
                upload_batch_id,
                row_date,
                name_clean,
                null_if_na(weight_num),
                service_type,
                rush_type,
                row_status,
                reason,
                *special_instruction_insert_args(row, include=has_ubr_si),
            ]
        cursor.execute(insert_sql, tuple(row_args))

    return {
        "rows_inserted": inserted,
        "rejected_rows": rejected,
        "needs_attention_rows": needs_attention,
    }


def finalize_upload_batch_row_counts(
    cursor,
    tenant_oid: int,
    upload_batch_id: int,
    inserted: int,
    schema: UploadBatchSchema,
) -> None:
    set_parts = ["orders_loaded = %s"]
    set_args: list[Any] = [inserted]
    if schema.has_rows_inserted:
        set_parts.append("rows_inserted = %s")
        set_args.append(inserted)
    if schema.has_state:
        set_parts.append("state = 'DRAFT'")
    if schema.has_updated_at:
        set_parts.append("updated_at = NOW()")

    set_args.append(upload_batch_id)
    upd_batch_where = f"WHERE {schema.upload_batches_pk} = %s"
    if schema.has_ub_org:
        upd_batch_where += " AND organization_id = %s"
        set_args.append(tenant_oid)
    cursor.execute(
        f"""
        UPDATE upload_batches
        SET {", ".join(set_parts)}
        {upd_batch_where}
        """,
        tuple(set_args),
    )


def commit_draft_upload_batch_from_orders_df(
    conn,
    cursor,
    tenant_oid: int,
    batch_date: date,
    orders_df: pd.DataFrame,
    file_name: str,
) -> dict:
    """Portal-only draft upload (caller commits)."""
    from backend.app import summarize_batch_rows

    schema = get_upload_batch_schema(cursor)
    orders_df = prepare_orders_df(orders_df)
    pre_existing_completed = snapshot_pre_upload_completed_bag_ids(
        cursor, tenant_oid, orders_df
    )
    upload_batch_id = create_draft_upload_batch_shell(
        cursor, tenant_oid, batch_date, file_name, schema
    )
    final_keys, existing_reasons, lookback = build_upload_duplicate_indexes(
        cursor, tenant_oid, schema
    )
    counts = insert_upload_batch_rows_from_orders_df(
        cursor,
        tenant_oid,
        upload_batch_id,
        batch_date,
        orders_df,
        schema,
        final_keys,
        existing_reasons,
        pre_existing_completed_bag_ids=pre_existing_completed,
        is_auto_scrape=False,
    )
    finalize_upload_batch_row_counts(
        cursor, tenant_oid, upload_batch_id, counts["rows_inserted"], schema
    )
    conn.commit()
    summary = summarize_batch_rows(cursor, upload_batch_id, schema.row_pk)
    return {
        "status": "draft_uploaded",
        "batch_id": upload_batch_id,
        "batch_state": "DRAFT",
        "rows_inserted": counts["rows_inserted"],
        "rejected_rows": counts["rejected_rows"],
        "needs_attention_rows": counts["needs_attention_rows"],
        "duplicate_lookback_days": lookback,
        "summary": summary,
    }


def commit_scheduled_scan_events_only(
    conn,
    cursor,
    tenant_oid: int,
    batch_date: date,
    events_filename: str,
    events_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Persist scheduled scan-events export when portal ACA gate blocks portal upload.

    Keeps rinse_bag_scan_events current so Shift Monitor completions/productivity
    do not stall when the portal CSV lacks credible supply SI/flags.
    """
    from backend.rinse_bag_registry import merge_scan_events_from_upload, recompute_completion_for_bags
    from backend.rinse_scan_events_upload import commit_scan_events_for_batch

    schema = get_upload_batch_schema(cursor)
    shell_name = f"scheduled-scan-events-only + {events_filename}"
    upload_batch_id = create_draft_upload_batch_shell(
        cursor, tenant_oid, batch_date, shell_name, schema
    )

    batch_events_payload = commit_scan_events_for_batch(
        cursor,
        tenant_oid,
        upload_batch_id,
        events_df,
        events_filename,
        replace_existing=True,
    )

    persistent_merge_payload: dict[str, Any] = {}
    if not events_df.empty:
        persistent_merge_payload = merge_scan_events_from_upload(
            cursor,
            tenant_oid,
            upload_batch_id,
            events_df,
            events_filename,
            replace_existing=True,
            credential_sourced=True,
        )
        bag_ids = list(persistent_merge_payload.get("bag_ids") or [])
        if bag_ids:
            recompute_completion_for_bags(cursor, tenant_oid, bag_ids)

    if schema.has_state:
        set_parts = ["state = 'CONFIRMED'", "confirmed_at = NOW()", "orders_loaded = 0"]
        if schema.has_rows_inserted:
            set_parts.append("rows_inserted = 0")
        cursor.execute(
            f"""
            UPDATE upload_batches
            SET {", ".join(set_parts)}
            WHERE batch_id = %s
            """,
            (int(upload_batch_id),),
        )

    conn.commit()
    return {
        "status": "scan_events_only",
        "source": "scheduled_scan_events_only",
        "batch_id": upload_batch_id,
        "scan_events_batch": batch_events_payload,
        "persistent_scan_merge": persistent_merge_payload,
    }


def commit_rinse_combined_upload(
    conn,
    cursor,
    tenant_oid: int,
    batch_date: date,
    portal_filename: str,
    orders_df: pd.DataFrame,
    events_filename: str,
    events_df: pd.DataFrame,
    *,
    portal_scrape_meta: dict | None = None,
    portal_scrape_meta_path: str | Path | None = None,
) -> dict:
    """
    Dual CSV: scan-events merged and completion recomputed before portal row classification.
    Single transaction; caller must not commit on failure (rollback in route).
    """
    from backend.app import summarize_batch_rows
    from backend.rinse_scan_events_upload import commit_scan_events_for_batch
    from backend.upload_batch_requirements import batch_upload_files_status

    schema = get_upload_batch_schema(cursor)
    orders_df = prepare_orders_df(orders_df)

    pre_existing_completed = snapshot_pre_upload_completed_bag_ids(
        cursor, tenant_oid, orders_df
    )

    combined_name = f"{portal_filename} + {events_filename}"
    upload_batch_id = create_draft_upload_batch_shell(
        cursor, tenant_oid, batch_date, combined_name, schema
    )

    from backend.rinse_portal_scrape_meta import (
        load_portal_scrape_meta_file,
        persist_portal_scrape_meta_on_batch,
    )

    meta = portal_scrape_meta
    if meta is None and portal_scrape_meta_path:
        meta = load_portal_scrape_meta_file(portal_scrape_meta_path)
    is_auto_scrape = meta not in (None, "", "null", "NULL")
    portal_meta_payload = persist_portal_scrape_meta_on_batch(
        cursor, upload_batch_id, tenant_oid, meta
    )

    bag_ids = collect_bag_ids_from_upload(orders_df, events_df)

    final_keys, existing_reasons, lookback = build_upload_duplicate_indexes(
        cursor, tenant_oid, schema
    )
    counts = insert_upload_batch_rows_from_orders_df(
        cursor,
        tenant_oid,
        upload_batch_id,
        batch_date,
        orders_df,
        schema,
        final_keys,
        existing_reasons,
        pre_existing_completed_bag_ids=pre_existing_completed,
        is_auto_scrape=is_auto_scrape,
        pending_events_df=events_df,
    )

    batch_events_payload = commit_scan_events_for_batch(
        cursor,
        tenant_oid,
        upload_batch_id,
        events_df,
        events_filename,
        replace_existing=True,
    )

    persistent_merge_payload: dict[str, Any] = {}
    if is_auto_scrape and not events_df.empty:
        from backend.rinse_bag_registry import merge_scan_events_from_upload

        persistent_merge_payload = merge_scan_events_from_upload(
            cursor,
            tenant_oid,
            upload_batch_id,
            events_df,
            events_filename,
            replace_existing=True,
            credential_sourced=True,
        )

    finalize_upload_batch_row_counts(
        cursor, tenant_oid, upload_batch_id, counts["rows_inserted"], schema
    )

    conn.commit()
    summary = summarize_batch_rows(cursor, upload_batch_id, schema.row_pk)
    upload_files = batch_upload_files_status(cursor, upload_batch_id, tenant_oid)

    return {
        "status": "draft_uploaded",
        "source": "upload_rinse_dual_csv",
        "batch_id": upload_batch_id,
        "batch_state": "DRAFT",
        "rows_inserted": counts["rows_inserted"],
        "rejected_rows": counts["rejected_rows"],
        "needs_attention_rows": counts["needs_attention_rows"],
        "duplicate_lookback_days": lookback,
        "summary": summary,
        "summary_rows": len(orders_df),
        "require_both_csv": True,
        "upload_files": upload_files,
        "scan_events_batch": batch_events_payload,
        "persistent_scan_merge": persistent_merge_payload,
        "draft_bag_ids": bag_ids,
        "finalize_on_confirm": True,
        "portal_scrape_meta": portal_meta_payload.get("portal_scrape_meta"),
        "portal_absence_allowed": portal_meta_payload.get("portal_absence_allowed"),
        "full_snapshot": portal_meta_payload.get("full_snapshot"),
    }
