"""
Repair the latest Rinse upload batch for one organization (Washpro).

Fixes stale ALREADY_COMPLETED rejections, reapplies staging, recomputes completion + folding.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import (
    REASON_ALREADY_COMPLETED,
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    ROW_ACCEPTED,
    classify_portal_upload_row,
    normalize_bag_id,
)
from backend.rinse_bag_registry import merge_scan_events_from_upload, recompute_completion_for_bags
from backend.rinse_bag_upload import (
    find_active_staging_by_ticket_id,
    find_staging_by_ticket_id,
    update_staging_from_upload_row,
)
from backend.rinse_folding_registry import (
    folding_recompute_summary_for_response,
    recompute_folding_after_upload,
)
from backend.rinse_upload_finalize import (
    apply_registry_from_accepted_portal_rows,
    load_upload_batch_scan_events_as_dataframe,
)
from backend.ta_helpers import table_exists, table_has_column


def _orders_status_capabilities(cursor) -> dict[str, bool]:
    return {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }


def _where_active_at_washpro_sql(cap: dict[str, bool]) -> str:
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if cap["has_status"]:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def _normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().split())


def _normalize_measure_by_service(weight_num: Any, service_type: Any) -> str:
    service = str(service_type or "").strip().upper()
    if weight_num is None:
        return "0" if service == "HD" else ""
    try:
        n = float(weight_num)
    except Exception:
        return ""
    if service == "HD":
        return str(int(round(n)))
    return f"{round(n, 2):.2f}"


def _normalize_date_key(date_value: Any) -> str:
    if date_value is None or date_value == "":
        return ""
    if isinstance(date_value, datetime):
        return date_value.date().isoformat()
    if isinstance(date_value, date):
        return date_value.isoformat()
    return str(date_value).strip()


def _build_identity_key(name_clean, weight_num, service_type, date_clean) -> str:
    return "|".join(
        [
            _normalize_name(name_clean),
            _normalize_measure_by_service(weight_num, service_type),
            str(service_type or "").strip().upper(),
            _normalize_date_key(date_clean),
        ]
    )


def _upload_batches_pk(cursor) -> str:
    if table_has_column(cursor, "upload_batches", "id"):
        return "id"
    if table_has_column(cursor, "upload_batches", "batch_id"):
        return "batch_id"
    raise ValueError("upload_batches must have id or batch_id")


def _upload_batch_rows_pk(cursor) -> str:
    if table_has_column(cursor, "upload_batch_rows", "id"):
        return "id"
    if table_has_column(cursor, "upload_batch_rows", "row_id"):
        return "row_id"
    raise ValueError("upload_batch_rows must have id or row_id")


def resolve_organization_id(
    cursor,
    *,
    organization_id: int | None = None,
    tenant: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Resolve org by explicit id or organizations.slug / display_name (case-insensitive)."""
    if organization_id is not None:
        org_id = int(organization_id)
        if table_exists(cursor, "organizations"):
            cursor.execute(
                "SELECT id, slug, display_name FROM organizations WHERE id = %s LIMIT 1",
                (org_id,),
            )
            row = cursor.fetchone()
            if row:
                return org_id, dict(row)
        return org_id, {"id": org_id, "slug": None, "display_name": None}

    if not tenant or not str(tenant).strip():
        raise ValueError("Provide --org or --tenant")

    if not table_exists(cursor, "organizations"):
        raise ValueError("organizations table not found; use --org")

    needle = str(tenant).strip().lower()
    cursor.execute(
        """
        SELECT id, slug, display_name
        FROM organizations
        WHERE LOWER(COALESCE(slug, '')) = %s
           OR LOWER(COALESCE(display_name, '')) = %s
           OR LOWER(COALESCE(display_name, '')) LIKE %s
        ORDER BY id ASC
        LIMIT 5
        """,
        (needle, needle, f"%{needle}%"),
    )
    matches = list(cursor.fetchall() or [])
    if not matches:
        raise ValueError(f"No organization matched tenant {tenant!r}")
    if len(matches) > 1:
        exact = [
            m
            for m in matches
            if str(m.get("slug") or "").lower() == needle
            or str(m.get("display_name") or "").lower() == needle
        ]
        if len(exact) == 1:
            matches = exact
        elif len(matches) > 1:
            ids = [m.get("id") for m in matches]
            raise ValueError(
                f"Ambiguous tenant {tenant!r}; matches org ids {ids}. Use --org explicitly."
            )
    row = matches[0]
    return int(row["id"]), dict(row)


def find_latest_upload_batch(cursor, organization_id: int) -> dict[str, Any] | None:
    """Latest upload_batches row for this org only."""
    if not table_exists(cursor, "upload_batches"):
        return None
    pk = _upload_batches_pk(cursor)
    org_filter = ""
    args: list[Any] = []
    if table_has_column(cursor, "upload_batches", "organization_id"):
        org_filter = "WHERE organization_id = %s"
        args.append(int(organization_id))

    order_bits = [f"{pk} DESC"]
    if table_has_column(cursor, "upload_batches", "batch_date"):
        order_bits.insert(0, "batch_date DESC")

    cursor.execute(
        f"""
        SELECT *
        FROM upload_batches
        {org_filter}
        ORDER BY {", ".join(order_bits)}
        LIMIT 1
        """,
        tuple(args),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _batch_scan_events_already_merged(
    cursor, organization_id: int, upload_batch_id: int
) -> bool:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return False
    if not table_has_column(cursor, "rinse_bag_scan_events", "source_upload_batch_id"):
        return False
    cursor.execute(
        """
        SELECT 1 FROM rinse_bag_scan_events
        WHERE organization_id = %s AND source_upload_batch_id = %s
        LIMIT 1
        """,
        (int(organization_id), int(upload_batch_id)),
    )
    return cursor.fetchone() is not None


def _collect_bag_ids_from_batch(
    cursor, organization_id: int, upload_batch_id: int
) -> set[str]:
    bags: set[str] = set()
    cursor.execute(
        """
        SELECT ticket_id FROM upload_batch_rows
        WHERE upload_batch_id = %s
        """,
        (int(upload_batch_id),),
    )
    for r in cursor.fetchall() or []:
        bid = normalize_bag_id((r or {}).get("ticket_id"))
        if bid:
            bags.add(bid)

    if table_exists(cursor, "upload_batch_scan_events"):
        cursor.execute(
            """
            SELECT DISTINCT bag_id FROM upload_batch_scan_events
            WHERE organization_id = %s AND upload_batch_id = %s
            """,
            (int(organization_id), int(upload_batch_id)),
        )
        for r in cursor.fetchall() or []:
            bid = normalize_bag_id((r or {}).get("bag_id"))
            if bid:
                bags.add(bid)
    return bags


def _load_portal_rows(cursor, upload_batch_id: int) -> list[dict[str, Any]]:
    row_pk = _upload_batch_rows_pk(cursor)
    tid_col = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
    cursor.execute(
        f"""
        SELECT
            {row_pk} AS row_id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            row_status,
            reason
            {tid_col}
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        ORDER BY {row_pk} ASC
        """,
        (int(upload_batch_id),),
    )
    return [dict(r) for r in cursor.fetchall() or []]


def _fix_stale_already_completed_rows(
    cursor,
    organization_id: int,
    portal_rows: list[dict[str, Any]],
    *,
    cap: dict,
    active_where: str,
    has_staging_org: bool,
    dry_run: bool,
    upload_batch_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return list of row change records for ALREADY_COMPLETED → ACCEPTED repairs."""
    from backend.checkout_batch_source import upload_batch_is_auto_scrape

    if upload_batch_id is not None and not upload_batch_is_auto_scrape(
        cursor, int(upload_batch_id), int(organization_id)
    ):
        return []
    changes: list[dict[str, Any]] = []
    row_pk = _upload_batch_rows_pk(cursor)

    for row in portal_rows:
        status = str(row.get("row_status") or "").upper()
        reason = str(row.get("reason") or "")
        tid = normalize_bag_id(row.get("ticket_id"))
        if not tid:
            continue

        staging_hit = find_active_staging_by_ticket_id(
            cursor,
            organization_id,
            tid,
            active_where,
            has_staging_org=has_staging_org,
            has_ticket_id_col=bool(cap.get("has_ticket_id")),
        )

        if (
            status == "REJECTED_DUPLICATE"
            and reason == REASON_ALREADY_COMPLETED
        ):
            new_status, new_reason = classify_portal_upload_row(
                ticket_id=tid,
                was_completed_before_upload=False,
                has_active_staging=bool(staging_hit),
                row_date_before_batch=False,
            )
            update_status = True
        elif (
            status in ("ACCEPTED", "OVERRIDDEN")
            and reason == "COMPLETED_NEEDS_CHECKOUT"
        ):
            new_status = status
            new_reason = (
                REASON_UPDATED_EXISTING_BAG if staging_hit else REASON_OK
            )
            update_status = False
        else:
            continue

        change = {
            "row_id": row.get("row_id"),
            "bag_id": tid,
            "from_status": status,
            "from_reason": reason,
            "to_status": new_status,
            "to_reason": new_reason,
        }
        changes.append(change)

        if dry_run:
            row["row_status"] = new_status
            row["reason"] = new_reason
            continue

        if update_status:
            cursor.execute(
                f"""
                UPDATE upload_batch_rows
                SET row_status = %s, reason = %s, updated_at = NOW()
                WHERE {row_pk} = %s
                """,
                (new_status, new_reason, int(row["row_id"])),
            )
        else:
            cursor.execute(
                f"""
                UPDATE upload_batch_rows
                SET reason = %s, updated_at = NOW()
                WHERE {row_pk} = %s
                """,
                (new_reason, int(row["row_id"])),
            )
        row["row_status"] = new_status
        row["reason"] = new_reason

    return changes


def staging_row_values_differ(
    existing: dict[str, Any],
    portal: dict[str, Any],
    batch_date: date | datetime | None,
) -> bool:
    """True when update_staging_from_upload_row would change meaningful fields."""
    pairs = [
        (_normalize_date_key(existing.get("date_clean")), _normalize_date_key(portal.get("date_clean"))),
        (_normalize_name(existing.get("name_clean")), _normalize_name(portal.get("name_clean"))),
        (
            _normalize_measure_by_service(
                existing.get("weight_num"), existing.get("service_type")
            ),
            _normalize_measure_by_service(
                portal.get("weight_num"), portal.get("service_type")
            ),
        ),
        (
            str(existing.get("service_type") or "").strip().upper(),
            str(portal.get("service_type") or "").strip().upper(),
        ),
        (
            str(existing.get("rush_type") or "NON-RUSH").strip().upper(),
            str(portal.get("rush_type") or "NON-RUSH").strip().upper(),
        ),
    ]
    return any(a != b for a, b in pairs)


def _apply_staging_for_accepted_rows(
    cursor,
    organization_id: int,
    batch: dict[str, Any],
    accepted_rows: list[dict[str, Any]],
    *,
    cap: dict,
    active_where: str,
    has_staging_org: bool,
    dry_run: bool,
) -> dict[str, int]:
    batch_date = batch.get("batch_date")
    if isinstance(batch_date, datetime):
        batch_date = batch_date.date()

    not_sent_where = active_where
    cur_sql = f"""
        SELECT date_clean, name_clean, weight_num, service_type
        FROM orders_staging
        WHERE ({not_sent_where})
    """
    cur_args: list[Any] = []
    if has_staging_org:
        cur_sql += " AND organization_id = %s"
        cur_args.append(int(organization_id))
    cursor.execute(cur_sql, tuple(cur_args))
    existing_identity = {
        _build_identity_key(
            r["name_clean"], r["weight_num"], r["service_type"], r["date_clean"]
        )
        for r in cursor.fetchall() or []
    }

    inserted = 0
    updated = 0
    skipped_identity = 0

    for row in accepted_rows:
        status = str(row.get("row_status") or "").upper()
        if status not in ("ACCEPTED", "OVERRIDDEN"):
            continue

        tid = normalize_bag_id(row.get("ticket_id")) if row.get("ticket_id") else ""
        portal = {
            "date_clean": row["date_clean"],
            "name_clean": row["name_clean"],
            "weight_num": row["weight_num"],
            "service_type": row["service_type"],
            "rush_type": row.get("rush_type") or "NON-RUSH",
            "ticket_id": tid or row.get("ticket_id"),
        }

        if tid and cap.get("has_ticket_id"):
            existing_staging = find_staging_by_ticket_id(
                cursor,
                organization_id,
                tid,
                has_staging_org=has_staging_org,
                has_ticket_id_col=True,
            )
            if existing_staging:
                if not dry_run:
                    update_staging_from_upload_row(
                        cursor,
                        int(existing_staging["id"]),
                        portal,
                        batch_date,
                        cap,
                        organization_id=organization_id,
                        has_staging_org=has_staging_org,
                    )
                    cursor.execute(
                        """
                        UPDATE rinse_bag_registry
                        SET last_staging_order_id = %s, updated_at = NOW()
                        WHERE organization_id = %s AND bag_id = %s
                        """,
                        (int(existing_staging["id"]), int(organization_id), tid),
                    )
                updated += 1
                continue

        identity_key = _build_identity_key(
            portal["name_clean"],
            portal["weight_num"],
            portal["service_type"],
            portal["date_clean"],
        )
        # Same customer/day may have multiple Bag IDs — only dedupe non-ticket rows.
        if identity_key in existing_identity and not tid:
            skipped_identity += 1
            continue

        if dry_run:
            inserted += 1
            existing_identity.add(identity_key)
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
        args: list[Any] = [
            portal["date_clean"],
            portal["name_clean"],
            portal["weight_num"],
            portal["service_type"],
            portal["rush_type"],
            batch_date,
        ]
        if has_staging_org:
            cols = ["organization_id"] + cols
            vals = ["%s"] + vals
            args = [int(organization_id)] + args
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
            INSERT INTO orders_staging ({", ".join(cols)})
            VALUES ({", ".join(vals)})
            """,
            tuple(args),
        )
        new_id = cursor.lastrowid
        inserted += 1
        if tid:
            cursor.execute(
                """
                UPDATE rinse_bag_registry
                SET last_staging_order_id = %s, updated_at = NOW()
                WHERE organization_id = %s AND bag_id = %s
                """,
                (int(new_id), int(organization_id), tid),
            )
        existing_identity.add(identity_key)

    return {
        "staging_rows_inserted": inserted,
        "staging_rows_updated": updated,
        "staging_rows_skipped_identity_dup": skipped_identity,
    }


def repair_latest_upload_batch(
    cursor,
    *,
    organization_id: int | None = None,
    tenant: str | None = None,
    upload_batch_id: int | None = None,
    dry_run: bool = False,
    force_scan_merge: bool = False,
) -> dict[str, Any]:
    org_id, org_meta = resolve_organization_id(
        cursor, organization_id=organization_id, tenant=tenant
    )

    if upload_batch_id is not None:
        pk = _upload_batches_pk(cursor)
        cursor.execute(
            f"SELECT * FROM upload_batches WHERE {pk} = %s LIMIT 1",
            (int(upload_batch_id),),
        )
        batch = cursor.fetchone()
        if not batch:
            raise ValueError(f"upload batch {upload_batch_id} not found")
        batch = dict(batch)
        if table_has_column(cursor, "upload_batches", "organization_id"):
            batch_org = int(batch.get("organization_id") or 0)
            if batch_org and batch_org != org_id:
                raise ValueError(
                    f"Batch {upload_batch_id} belongs to org {batch_org}, not {org_id}"
                )
    else:
        batch = find_latest_upload_batch(cursor, org_id)
        if not batch:
            raise ValueError(f"No upload_batches rows for organization_id={org_id}")

    batch_pk = _upload_batches_pk(cursor)
    batch_id = int(batch[batch_pk])

    portal_rows = _load_portal_rows(cursor, batch_id)
    bag_ids = sorted(_collect_bag_ids_from_batch(cursor, org_id, batch_id))

    cap = _orders_status_capabilities(cursor)
    active_where = _where_active_at_washpro_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "organization_id": org_id,
        "organization": org_meta,
        "latest_batch_id": batch_id,
        "batch_state": batch.get("state"),
        "batch_date": str(batch.get("batch_date") or ""),
        "bag_ids_checked": bag_ids,
        "completion_recomputed_count": 0,
        "rows_changed_from_ALREADY_COMPLETED_to_ACCEPTED": 0,
        "row_status_changes": [],
        "staging_rows_inserted": 0,
        "staging_rows_updated": 0,
        "staging_rows_skipped_identity_dup": 0,
        "scan_events_merged": False,
        "folding_calculated": 0,
        "folding_exceptions": 0,
        "folding_skipped": 0,
        "remaining_rejected_rows": [],
        "completion_summaries": [],
    }

    events_df = load_upload_batch_scan_events_as_dataframe(cursor, org_id, batch_id)
    already_merged = (
        not force_scan_merge
        and _batch_scan_events_already_merged(cursor, org_id, batch_id)
    )
    if already_merged:
        summary["scan_events_merged"] = False
        summary["scan_events_merge_skipped"] = "already_in_rinse_bag_scan_events"
    elif not events_df.empty and not dry_run:
        merge_scan_events_from_upload(
            cursor,
            org_id,
            batch_id,
            events_df,
            source_filename=f"repair_batch_{batch_id}",
        )
        summary["scan_events_merged"] = True
    elif not events_df.empty:
        summary["scan_events_merged"] = "would_merge"

    if bag_ids and not dry_run:
        completion_payload = recompute_completion_for_bags(cursor, org_id, bag_ids)
        summary["completion_recomputed_count"] = int(
            completion_payload.get("bags_recomputed") or 0
        )
        summary["completion_summaries"] = list(completion_payload.get("bags") or [])
    elif bag_ids:
        summary["completion_recomputed_count"] = len(bag_ids)
        summary["completion_summaries"] = "would_recompute"

    row_changes = _fix_stale_already_completed_rows(
        cursor,
        org_id,
        portal_rows,
        cap=cap,
        active_where=active_where,
        has_staging_org=has_staging_org,
        dry_run=dry_run,
        upload_batch_id=batch_id,
    )
    summary["row_status_changes"] = row_changes
    summary["rows_changed_from_ALREADY_COMPLETED_to_ACCEPTED"] = len(row_changes)

    accepted_rows = [
        r
        for r in portal_rows
        if str(r.get("row_status") or "").upper() in ("ACCEPTED", "OVERRIDDEN")
    ]

    staging_stats = _apply_staging_for_accepted_rows(
        cursor,
        org_id,
        batch,
        accepted_rows,
        cap=cap,
        active_where=active_where,
        has_staging_org=has_staging_org,
        dry_run=dry_run,
    )
    summary.update(staging_stats)

    if accepted_rows and not dry_run:
        apply_registry_from_accepted_portal_rows(
            cursor, org_id, batch_id, accepted_rows
        )

    if bag_ids and not dry_run:
        completion_summaries = (
            summary["completion_summaries"]
            if isinstance(summary["completion_summaries"], list)
            else []
        )
        folding_payload = recompute_folding_after_upload(
            cursor,
            org_id,
            bag_ids,
            completion_summaries=completion_summaries,
        )
        folding_summary = folding_recompute_summary_for_response(folding_payload)
        summary["folding_calculated"] = int(folding_summary.get("folding_recompute_calculated") or 0)
        summary["folding_exceptions"] = int(
            folding_summary.get("folding_recompute_exceptions") or 0
        )
        summary["folding_skipped"] = int(folding_summary.get("folding_recompute_skipped") or 0)
    elif bag_ids:
        summary["folding_calculated"] = "would_recompute"
        summary["folding_exceptions"] = "would_recompute"

    summary["remaining_rejected_rows"] = [
        {
            "row_id": r.get("row_id"),
            "bag_id": normalize_bag_id(r.get("ticket_id")),
            "row_status": r.get("row_status"),
            "reason": r.get("reason"),
        }
        for r in portal_rows
        if str(r.get("row_status") or "").upper().startswith("REJECTED")
    ]

    return summary


def repair_summary_json(summary: dict[str, Any]) -> str:
    def _default(o: Any) -> str:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)

    return json.dumps(summary, indent=2, default=_default)
