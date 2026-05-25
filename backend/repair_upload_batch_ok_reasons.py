"""
Repair ACCEPTED/OK upload_batch_rows that should be ACCEPTED/UPDATED_EXISTING_BAG.

Org-scoped; dry-run by default. Use --apply to UPDATE rows.

Rule (per batch, chronological):
  - row_status = ACCEPTED, reason = OK, ticket_id present
  - same ticket_id appeared in an earlier CONFIRMED batch in the run set
  - registry was not COMPLETED before this batch's anchor time
  - active staging exists for ticket_id (or registry last_staging) at repair evaluation
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from backend.db import get_db
from backend.rinse_bag_completion import (
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    normalize_bag_id,
)
from backend.rinse_bag_upload import (
    _ensure_ticket_id_columns,
    find_active_staging_for_portal_upload,
)
from backend.ta_helpers import table_exists, table_has_column


def _upload_batches_pk(cursor) -> str:
    return "id" if table_has_column(cursor, "upload_batches", "id") else "batch_id"


def _upload_batch_rows_pk(cursor) -> str:
    return "id" if table_has_column(cursor, "upload_batch_rows", "id") else "row_id"


def _orders_status_capabilities(cursor) -> dict[str, bool]:
    return {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }


def _active_where_sql(cap: dict[str, bool]) -> str:
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


def _batch_anchor(row: dict[str, Any]) -> datetime | None:
    for key in ("confirmed_at", "created_at", "uploaded_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            return val
    return None


def _registry_completed_before(
    reg: dict[str, Any] | None, anchor: datetime | None
) -> bool:
    if not reg:
        return False
    if str(reg.get("completion_status") or "").upper() != "COMPLETED":
        return False
    completed_at = reg.get("completed_at")
    if isinstance(completed_at, datetime) and isinstance(anchor, datetime):
        return completed_at < anchor
    return True


def load_batches(cursor, org_id: int, batch_ids: list[int]) -> list[dict[str, Any]]:
    pk = _upload_batches_pk(cursor)
    placeholders = ", ".join(["%s"] * len(batch_ids))
    has_org = table_has_column(cursor, "upload_batches", "organization_id")
    cols = [f"{pk} AS batch_id", "state", "batch_date"]
    if table_has_column(cursor, "upload_batches", "created_at"):
        cols.append("created_at")
    if table_has_column(cursor, "upload_batches", "confirmed_at"):
        cols.append("confirmed_at")
    org_clause = " AND organization_id = %s" if has_org else ""
    args: list[Any] = list(batch_ids)
    if has_org:
        args.append(org_id)
    cursor.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM upload_batches
        WHERE {pk} IN ({placeholders}){org_clause}
        """,
        tuple(args),
    )
    rows = [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]
    rows.sort(
        key=lambda b: (
            _batch_anchor(b) or datetime.min,
            int(b.get("batch_id") or 0),
        )
    )
    return rows


def load_batch_rows(cursor, batch_id: int) -> list[dict[str, Any]]:
    row_pk = _upload_batch_rows_pk(cursor)
    has_tid = table_has_column(cursor, "upload_batch_rows", "ticket_id")
    tid_col = ", ticket_id" if has_tid else ", NULL AS ticket_id"
    cursor.execute(
        f"""
        SELECT {row_pk} AS row_id, upload_batch_id, row_status, reason,
               date_clean, name_clean, weight_num, service_type, rush_type{tid_col}
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
        """,
        (int(batch_id),),
    )
    return [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def load_registry(cursor, org_id: int, bag_id: str) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_bag_registry"):
        return None
    cursor.execute(
        """
        SELECT bag_id, completion_status, completion_reason, completed_at,
               last_staging_order_id
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id = %s
        LIMIT 1
        """,
        (org_id, bag_id),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def tickets_in_prior_batches(
    prior_batch_ids: list[int], cursor
) -> set[str]:
    if not prior_batch_ids:
        return set()
    placeholders = ", ".join(["%s"] * len(prior_batch_ids))
    has_tid = table_has_column(cursor, "upload_batch_rows", "ticket_id")
    if not has_tid:
        return set()
    cursor.execute(
        f"""
        SELECT DISTINCT ticket_id
        FROM upload_batch_rows
        WHERE upload_batch_id IN ({placeholders})
          AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
          AND ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
        """,
        tuple(prior_batch_ids),
    )
    out: set[str] = set()
    for r in cursor.fetchall() or []:
        tid = normalize_bag_id(r.get("ticket_id") if isinstance(r, dict) else r[0])
        if tid:
            out.add(tid)
    return out


def analyze_repairs(
    cursor,
    org_id: int,
    batch_ids: list[int],
) -> dict[str, Any]:
    _ensure_ticket_id_columns(cursor)
    cap = _orders_status_capabilities(cursor)
    active_where = _active_where_sql(cap)
    has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")

    batches = load_batches(cursor, org_id, batch_ids)
    report: dict[str, Any] = {
        "organization_id": org_id,
        "batch_ids": batch_ids,
        "batches": [],
        "repeated_ticket_ids": [],
        "to_update": [],
        "unchanged": [],
        "duplicate_active_staging": [],
    }

    all_tickets_by_batch: dict[int, set[str]] = {}
    ticket_batch_appearances: dict[str, list[int]] = {}

    for b in batches:
        bid = int(b["batch_id"])
        rows = load_batch_rows(cursor, bid)
        tickets = set()
        for row in rows:
            tid = normalize_bag_id(row.get("ticket_id"))
            if tid:
                tickets.add(tid)
                ticket_batch_appearances.setdefault(tid, []).append(bid)
        all_tickets_by_batch[bid] = tickets

    for tid, appearances in ticket_batch_appearances.items():
        if len(set(appearances)) > 1:
            report["repeated_ticket_ids"].append(
                {"ticket_id": tid, "batch_ids": sorted(set(appearances))}
            )

    prior_ids: list[int] = []
    for b in batches:
        bid = int(b["batch_id"])
        anchor = _batch_anchor(b)
        prior_tickets = tickets_in_prior_batches(prior_ids, cursor)
        batch_summary = {
            "batch_id": bid,
            "state": b.get("state"),
            "anchor": anchor.isoformat() if anchor else None,
            "prior_batch_ids": list(prior_ids),
            "rows_to_update": 0,
        }
        prior_ids.append(bid)

        for row in load_batch_rows(cursor, bid):
            status = str(row.get("row_status") or "").upper()
            reason = str(row.get("reason") or "").upper()
            tid = normalize_bag_id(row.get("ticket_id"))
            if status != "ACCEPTED" or reason != REASON_OK or not tid:
                continue
            if tid not in prior_tickets:
                report["unchanged"].append(
                    {
                        "batch_id": bid,
                        "row_id": row.get("row_id"),
                        "ticket_id": tid,
                        "why": "first_seen_in_run_or_no_prior_batch_row",
                    }
                )
                continue

            reg = load_registry(cursor, org_id, tid)
            if _registry_completed_before(reg, anchor):
                report["unchanged"].append(
                    {
                        "batch_id": bid,
                        "row_id": row.get("row_id"),
                        "ticket_id": tid,
                        "why": "registry_completed_before_batch",
                    }
                )
                continue

            staging = find_active_staging_for_portal_upload(
                cursor,
                org_id,
                tid,
                active_where,
                has_staging_org=has_staging_org,
                portal_row={
                    "name_clean": row.get("name_clean"),
                    "weight_num": row.get("weight_num"),
                    "service_type": row.get("service_type"),
                    "date_clean": row.get("date_clean"),
                },
            )
            if not staging:
                report["unchanged"].append(
                    {
                        "batch_id": bid,
                        "row_id": row.get("row_id"),
                        "ticket_id": tid,
                        "why": "no_active_staging_for_ticket",
                        "registry_last_staging_order_id": (
                            reg.get("last_staging_order_id") if reg else None
                        ),
                    }
                )
                continue

            change = {
                "batch_id": bid,
                "row_id": row.get("row_id"),
                "ticket_id": tid,
                "from_reason": REASON_OK,
                "to_reason": REASON_UPDATED_EXISTING_BAG,
                "staging_order_id": staging.get("id"),
                "registry_completion_status": (
                    reg.get("completion_status") if reg else None
                ),
            }
            report["to_update"].append(change)
            batch_summary["rows_to_update"] += 1

        report["batches"].append(batch_summary)

    if cap.get("has_ticket_id"):
        org_clause = " AND organization_id = %s" if has_staging_org else ""
        args: list[Any] = []
        if has_staging_org:
            args.append(org_id)
        cursor.execute(
            f"""
            SELECT ticket_id, COUNT(*) AS cnt
            FROM orders_staging
            WHERE ticket_id IS NOT NULL AND TRIM(ticket_id) != ''
              AND ({active_where}){org_clause}
            GROUP BY ticket_id
            HAVING cnt > 1
            """,
            tuple(args),
        )
        for r in cursor.fetchall() or []:
            if isinstance(r, dict):
                report["duplicate_active_staging"].append(
                    {"ticket_id": r.get("ticket_id"), "count": r.get("cnt")}
                )

    report["counts"] = {
        "repeated_ticket_ids": len(report["repeated_ticket_ids"]),
        "rows_to_update": len(report["to_update"]),
        "unchanged_ok_rows": len(report["unchanged"]),
        "duplicate_active_staging_tickets": len(report["duplicate_active_staging"]),
    }
    return report


def apply_repairs(cursor, updates: list[dict[str, Any]]) -> int:
    row_pk = _upload_batch_rows_pk(cursor)
    n = 0
    for u in updates:
        cursor.execute(
            f"""
            UPDATE upload_batch_rows
            SET reason = %s, updated_at = NOW()
            WHERE {row_pk} = %s
              AND row_status = 'ACCEPTED'
              AND UPPER(COALESCE(reason,'')) = %s
            """,
            (REASON_UPDATED_EXISTING_BAG, int(u["row_id"]), REASON_OK),
        )
        n += cursor.rowcount
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=int, default=3)
    parser.add_argument("--batch-ids", type=int, nargs="+", default=[121, 122, 123, 124])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        report = analyze_repairs(cursor, args.org_id, args.batch_ids)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            c = report["counts"]
            print(f"Org {args.org_id} batches {args.batch_ids}")
            print(f"Repeated ticket_ids: {c['repeated_ticket_ids']}")
            print(f"Rows OK -> UPDATED_EXISTING_BAG: {c['rows_to_update']}")
            print(f"OK rows unchanged: {c['unchanged_ok_rows']}")
            print(f"Duplicate active staging tickets: {c['duplicate_active_staging_tickets']}")
            if report["to_update"][:20]:
                print("Sample updates:")
                for u in report["to_update"][:20]:
                    print(
                        f"  batch {u['batch_id']} row {u['row_id']} "
                        f"{u['ticket_id']} staging#{u.get('staging_order_id')}"
                    )

        if args.apply and report["to_update"]:
            n = apply_repairs(cursor, report["to_update"])
            conn.commit()
            print(f"Applied {n} row updates.")
        elif args.apply:
            print("Nothing to apply.")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
