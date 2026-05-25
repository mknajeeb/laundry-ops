"""
Upload batch confirm (staging apply + Rinse finalize).

Used by Flask route and scheduled Rinse scrape orchestrator.
"""

from __future__ import annotations

from typing import Any


class UploadBatchConfirmError(Exception):
    def __init__(self, message: str, status_code: int = 409, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {"error": message}


def confirm_upload_batch_core(
    cursor,
    tenant_oid: int,
    batch_id: int,
    *,
    force_confirm: bool = False,
) -> dict[str, Any]:
    """
    Confirm a draft upload batch for one organization.
    Caller must commit or rollback the connection.
  """
    from backend.app import (
        build_identity_key,
        ensure_ticket_id_columns,
        ensure_upload_batch_rows_ticket_id,
        get_upload_batch_rows_pk,
        get_upload_batches_pk,
        orders_logistics_select_sql,
        orders_processing_select_sql,
        orders_status_capabilities,
        table_exists,
        table_has_column,
        where_not_sent_or_forced_sql,
    )
    from backend.rinse_bag_completion import normalize_bag_id
    from backend.rinse_bag_upload import (
        find_active_staging_by_ticket_id,
        find_active_staging_for_portal_upload,
        update_staging_from_upload_row,
    )
    from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm
    from backend.upload_batch_requirements import validate_batch_confirm_dual_csv

    tenant_oid = int(tenant_oid)
    batch_id = int(batch_id)
    batch_pk = get_upload_batches_pk(cursor)
    row_pk = get_upload_batch_rows_pk(cursor)
    ensure_ticket_id_columns(cursor)
    ensure_upload_batch_rows_ticket_id(cursor)
    cap = orders_status_capabilities(cursor)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
    has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
    has_final_org = table_exists(cursor, "orders_final") and table_has_column(
        cursor, "orders_final", "organization_id"
    )

    bq = f"""
        SELECT {batch_pk} AS id, batch_date, state
        FROM upload_batches
        WHERE {batch_pk} = %s
    """
    barg = [batch_id]
    if has_ub_org:
        bq += " AND organization_id = %s"
        barg.append(tenant_oid)
    cursor.execute(bq, tuple(barg))
    batch = cursor.fetchone()
    if not batch:
        raise UploadBatchConfirmError("Batch not found", 404)

    if (batch.get("state") or "").upper() == "CONFIRMED":
        return {"status": "already_confirmed", "batch_id": batch_id}

    dual_block = validate_batch_confirm_dual_csv(cursor, batch_id, tenant_oid)
    if dual_block:
        raise UploadBatchConfirmError(
            dual_block.get("error") or "Dual CSV requirement not met",
            409,
            dual_block,
        )

    cursor.execute(
        """
        SELECT COUNT(*) AS attention_count
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        AND row_status = 'NEEDS_ATTENTION'
        """,
        (batch_id,),
    )
    attention_count = int((cursor.fetchone() or {}).get("attention_count", 0) or 0)
    if attention_count > 0 and not force_confirm:
        raise UploadBatchConfirmError(
            "Batch has NEEDS_ATTENTION rows",
            409,
            {"error": "Batch has NEEDS_ATTENTION rows", "attention_count": attention_count},
        )

    ubr_tid_sel = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
    cursor.execute(
        f"""
        SELECT
            {row_pk} AS id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type
            {ubr_tid_sel}
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """,
        (batch_id,),
    )
    accepted_rows = list(cursor.fetchall() or [])

    active_where = where_not_sent_or_forced_sql(cap)

    if len(accepted_rows) == 0:
        from backend.upload_batch_requirements import batch_upload_files_status

        ufs = batch_upload_files_status(cursor, batch_id, tenant_oid)
        if ufs.get("has_scan_events") and not ufs.get("require_both_csv"):
            pass
        else:
            raise UploadBatchConfirmError(
                "Batch has no ACCEPTED/OVERRIDDEN rows. Nothing to apply.",
                409,
                {"error": "Batch has no ACCEPTED/OVERRIDDEN rows. Nothing to apply.", "accepted_count": 0},
            )

    uploaded_identity_keys = set()
    for row in accepted_rows:
        uploaded_identity_keys.add(
            build_identity_key(
                row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"]
            )
        )

    logistics_sql = orders_logistics_select_sql(cap)
    processing_sql = orders_processing_select_sql(cap)
    not_sent_where = where_not_sent_or_forced_sql(cap)

    stag_sql = f"""
        SELECT
            id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            {logistics_sql},
            {processing_sql},
            status,
            batch_date
        FROM orders_staging
        WHERE {not_sent_where}
        AND (
            batch_date IS NULL
            OR batch_date < %s
        )
    """
    stag_args = [batch["batch_date"]]
    if has_staging_org:
        stag_sql += " AND organization_id = %s"
        stag_args.append(tenant_oid)
    cursor.execute(stag_sql, tuple(stag_args))
    staging_rows = cursor.fetchall()

    forced_pending = 0
    moved_to_final = 0
    for row in staging_rows:
        identity_key = build_identity_key(
            row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"]
        )
        if identity_key in uploaded_identity_keys:
            continue

        row_processing = (row.get("processing_status") or row.get("status") or "").upper()
        if row_processing == "PROCESSED":
            if has_final_org:
                cursor.execute(
                    """
                    INSERT INTO orders_final
                    (
                        organization_id,
                        date_clean,
                        name_clean,
                        weight_num,
                        service_type,
                        rush_type,
                        cleaned_by,
                        cleaned_at,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        tenant_oid,
                        row["date_clean"],
                        row["name_clean"],
                        row["weight_num"],
                        row["service_type"],
                        row["rush_type"],
                        "SYSTEM_FORCE",
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO orders_final
                    (
                        date_clean,
                        name_clean,
                        weight_num,
                        service_type,
                        rush_type,
                        cleaned_by,
                        cleaned_at,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        row["date_clean"],
                        row["name_clean"],
                        row["weight_num"],
                        row["service_type"],
                        row["rush_type"],
                        "SYSTEM_FORCE",
                    ),
                )
            del_sql = "DELETE FROM orders_staging WHERE id = %s"
            del_args = [row["id"]]
            if has_staging_org:
                del_sql += " AND organization_id = %s"
                del_args.append(tenant_oid)
            cursor.execute(del_sql, tuple(del_args))
            moved_to_final += 1
        else:
            set_parts = []
            if cap["has_logistics"]:
                set_parts.append("logistics_status = 'FORCE_CHECKOUT'")
            if cap["has_status"]:
                set_parts.append("status = 'FORCED_CHECKOUT'")
            if not set_parts:
                set_parts.append("status = 'FORCED_CHECKOUT'")

            upd_sql = f"""
                UPDATE orders_staging
                SET {", ".join(set_parts)}
                WHERE id = %s
            """
            upd_args = [row["id"]]
            if has_staging_org:
                upd_sql += " AND organization_id = %s"
                upd_args.append(tenant_oid)
            cursor.execute(upd_sql, tuple(upd_args))
            forced_pending += 1

    cur_sql = f"""
        SELECT date_clean, name_clean, weight_num, service_type
        FROM orders_staging
        WHERE {not_sent_where}
    """
    cur_args: list = []
    if has_staging_org:
        cur_sql += " AND organization_id = %s"
        cur_args.append(tenant_oid)
    cursor.execute(cur_sql, tuple(cur_args))
    current_staging_rows = cursor.fetchall()
    existing_identity_before_insert = set(
        build_identity_key(r["name_clean"], r["weight_num"], r["service_type"], r["date_clean"])
        for r in current_staging_rows
    )

    inserted = 0
    staging_updated = 0
    for row in accepted_rows:
        tid = normalize_bag_id(row.get("ticket_id")) if row.get("ticket_id") else ""
        if tid and cap.get("has_ticket_id"):
            existing_staging = find_active_staging_for_portal_upload(
                cursor,
                tenant_oid,
                tid,
                active_where,
                has_staging_org=has_staging_org,
                portal_row=row,
            )
            if existing_staging:
                update_staging_from_upload_row(
                    cursor,
                    int(existing_staging["id"]),
                    row,
                    batch["batch_date"],
                    cap,
                    organization_id=tenant_oid,
                    has_staging_org=has_staging_org,
                )
                staging_updated += 1
                cursor.execute(
                    """
                    UPDATE rinse_bag_registry
                    SET last_staging_order_id = %s, updated_at = NOW()
                    WHERE organization_id = %s AND bag_id = %s
                    """,
                    (int(existing_staging["id"]), tenant_oid, tid),
                )
                uploaded_identity_keys.add(
                    build_identity_key(
                        row["name_clean"],
                        row["weight_num"],
                        row["service_type"],
                        row["date_clean"],
                    )
                )
                continue

        identity_key = build_identity_key(
            row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"]
        )
        if identity_key in existing_identity_before_insert:
            if tid and cap.get("has_ticket_id"):
                by_tid = find_active_staging_by_ticket_id(
                    cursor,
                    tenant_oid,
                    tid,
                    active_where,
                    has_staging_org=has_staging_org,
                    has_ticket_id_col=True,
                )
                if not by_tid:
                    by_portal = find_active_staging_for_portal_upload(
                        cursor,
                        tenant_oid,
                        tid,
                        active_where,
                        has_staging_org=has_staging_org,
                        portal_row=row,
                    )
                    if by_portal:
                        update_staging_from_upload_row(
                            cursor,
                            int(by_portal["id"]),
                            row,
                            batch["batch_date"],
                            cap,
                            organization_id=tenant_oid,
                            has_staging_org=has_staging_org,
                        )
                        staging_updated += 1
                        cursor.execute(
                            """
                            UPDATE rinse_bag_registry
                            SET last_staging_order_id = %s, updated_at = NOW()
                            WHERE organization_id = %s AND bag_id = %s
                            """,
                            (int(by_portal["id"]), tenant_oid, tid),
                        )
            continue

        cols = [
            "date_clean",
            "name_clean",
            "weight_num",
            "service_type",
            "rush_type",
            "batch_date",
        ]
        vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
        args = [
            row["date_clean"],
            row["name_clean"],
            row["weight_num"],
            row["service_type"],
            row["rush_type"],
            batch["batch_date"],
        ]

        if has_staging_org:
            cols = ["organization_id"] + cols
            vals = ["%s"] + vals
            args = [tenant_oid] + args

        if cap["has_logistics"]:
            cols.append("logistics_status")
            vals.append("%s")
            args.append("AT_WASHPRO")
        if cap["has_processing"]:
            cols.append("processing_status")
            vals.append("%s")
            args.append("PENDING")
        if cap.get("has_status"):
            cols.append("status")
            vals.append("%s")
            args.append("PENDING")

        if cap.get("has_ticket_id") and tid:
            cols.append("ticket_id")
            vals.append("%s")
            args.append(tid[:120])

        cursor.execute(
            f"""
            INSERT INTO orders_staging
            ({", ".join(cols)})
            VALUES ({", ".join(vals)})
            """,
            tuple(args),
        )
        new_staging_id = cursor.lastrowid
        inserted += 1
        if tid:
            cursor.execute(
                """
                UPDATE rinse_bag_registry
                SET last_staging_order_id = %s, updated_at = NOW()
                WHERE organization_id = %s AND bag_id = %s
                """,
                (int(new_staging_id), tenant_oid, tid),
            )
        uploaded_identity_keys.add(identity_key)
        existing_identity_before_insert.add(identity_key)

    set_parts = ["state = 'CONFIRMED'"] if table_has_column(cursor, "upload_batches", "state") else []
    if table_has_column(cursor, "upload_batches", "confirmed_at"):
        set_parts.append("confirmed_at = NOW()")
    if table_has_column(cursor, "upload_batches", "closed_at"):
        set_parts.append("closed_at = NOW()")
    if table_has_column(cursor, "upload_batches", "updated_at"):
        set_parts.append("updated_at = NOW()")

    if set_parts:
        cursor.execute(
            f"""
            UPDATE upload_batches
            SET {", ".join(set_parts)}
            WHERE {batch_pk} = %s
            """,
            (batch_id,),
        )

    ubr_tid = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
    if ubr_tid:
        cursor.execute(
            f"""
            SELECT date_clean, name_clean, weight_num, service_type, rush_type, ticket_id
            FROM upload_batch_rows
            WHERE upload_batch_id = %s AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
            """,
            (batch_id,),
        )
        finalize_portal_rows = list(cursor.fetchall() or [])
    else:
        finalize_portal_rows = list(accepted_rows)

    rinse_finalize = finalize_rinse_after_batch_confirm(
        cursor,
        tenant_oid,
        batch_id,
        accepted_portal_rows=finalize_portal_rows,
        source_filename=f"batch_confirm_{batch_id}",
    )

    return {
        "status": "batch_confirmed",
        "batch_id": batch_id,
        "inserted_to_staging": inserted,
        "staging_updated_by_bag_id": staging_updated,
        "forced_checkout_pending": forced_pending,
        "moved_to_final": moved_to_final,
        "rinse_finalize": rinse_finalize,
        "missing_prior_bags_completed_count": int(
            rinse_finalize.get("missing_prior_bags_completed_count") or 0
        ),
        "missing_prior_bag_ids_completed": list(
            rinse_finalize.get("missing_prior_bag_ids_completed") or []
        ),
        "full_snapshot": bool(rinse_finalize.get("full_snapshot")),
        "folding_recompute_processed": int(rinse_finalize.get("folding_recompute_processed") or 0),
        "folding_recompute_calculated": int(rinse_finalize.get("folding_recompute_calculated") or 0),
        "folding_recompute_exceptions": int(rinse_finalize.get("folding_recompute_exceptions") or 0),
        "folding_recompute_skipped": int(rinse_finalize.get("folding_recompute_skipped") or 0),
        "folding_recompute_errors": int(rinse_finalize.get("folding_recompute_errors") or 0),
    }
