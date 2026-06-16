"""Ticket-ID-first staging for checkout upload batches."""

from __future__ import annotations

from typing import Any, Mapping

from backend.manual_checkout_eligibility import staging_checkout_sent_reason, ticket_has_checkout_log
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_upload import find_staging_by_ticket_id, update_staging_from_upload_row


def insert_staging_from_upload_row(
    cursor,
    organization_id: int,
    row: Mapping[str, Any],
    batch_date,
    cap: dict[str, bool],
    *,
    ticket_id: str | None = None,
    has_staging_org: bool = False,
) -> int:
    """Insert a new orders_staging row; returns new staging id."""
    org = int(organization_id)
    tid = normalize_bag_id(ticket_id or row.get("ticket_id"))
    if tid:
        from backend.rinse_bag_operational_owner import assert_operational_write_allowed

        allowed, _, _ = assert_operational_write_allowed(
            cursor, org, tid, context="staging_import", assign_on_first=True
        )
        if not allowed:
            raise ValueError(f"operational_owner_mismatch: bag {tid} not owned by org {org}")

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
        row["date_clean"],
        row["name_clean"],
        row["weight_num"],
        row["service_type"],
        row.get("rush_type") or "NON-RUSH",
        batch_date,
    ]

    if has_staging_org:
        cols = ["organization_id"] + cols
        vals = ["%s"] + vals
        args = [org] + args

    if cap.get("has_logistics"):
        cols.append("logistics_status")
        vals.append("%s")
        args.append("AT_WASHPRO")
    if cap.get("has_processing"):
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

    from backend.rinse_bag_upload import _ensure_special_instruction_columns
    from backend.ta_helpers import table_has_column

    _ensure_special_instruction_columns(cursor)
    if table_has_column(cursor, "orders_staging", "special_instructions_raw"):
        from backend.rinse_upload_sql import bool_sql_flag, null_if_na

        cols.extend(["special_instructions_raw", "supply_interpretation", "special_instruction_review"])
        vals.extend(["%s", "%s", "%s"])
        args.extend(
            [
                null_if_na(row.get("special_instructions_raw")),
                null_if_na(row.get("supply_interpretation")),
                bool_sql_flag(row.get("special_instruction_review")),
            ]
        )

    cursor.execute(
        f"""
        INSERT INTO orders_staging ({", ".join(cols)})
        VALUES ({", ".join(vals)})
        """,
        tuple(args),
    )
    return int(cursor.lastrowid)


def _link_registry_staging(cursor, organization_id: int, ticket_id: str, staging_id: int) -> None:
    cursor.execute(
        """
        UPDATE rinse_bag_registry
        SET last_staging_order_id = %s, updated_at = NOW()
        WHERE organization_id = %s AND bag_id = %s
        """,
        (int(staging_id), int(organization_id), ticket_id),
    )


def upsert_staging_for_ticket_upload_row(
    cursor,
    organization_id: int,
    row: Mapping[str, Any],
    batch_date,
    cap: dict[str, bool],
    *,
    has_staging_org: bool = False,
    reactivate_sent: bool = True,
) -> tuple[str, int | None]:
    """
    Stage one accepted upload row by ticket_id only.

    Returns (action, staging_id) where action is 'updated', 'inserted', or 'skipped'.
    """
    tid = normalize_bag_id(row.get("ticket_id"))
    if not tid or not cap.get("has_ticket_id"):
        return "skipped", None

    org = int(organization_id)
    if ticket_has_checkout_log(cursor, org, tid):
        return "skipped", None

    existing = find_staging_by_ticket_id(
        cursor,
        org,
        tid,
        has_staging_org=has_staging_org,
        has_ticket_id_col=True,
    )

    if existing:
        sent_reason = staging_checkout_sent_reason(existing)
        if sent_reason and not reactivate_sent:
            return "skipped", None
        update_staging_from_upload_row(
            cursor,
            int(existing["id"]),
            dict(row),
            batch_date,
            cap,
            organization_id=org,
            has_staging_org=has_staging_org,
        )
        _link_registry_staging(cursor, org, tid, int(existing["id"]))
        return "updated", int(existing["id"])

    new_id = insert_staging_from_upload_row(
        cursor,
        org,
        row,
        batch_date,
        cap,
        ticket_id=tid,
        has_staging_org=has_staging_org,
    )
    _link_registry_staging(cursor, org, tid, new_id)
    return "inserted", new_id
