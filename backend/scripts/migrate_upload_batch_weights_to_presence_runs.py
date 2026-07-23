"""Migrate historical portal weights from upload_batch_rows onto Presence Run Rows.

Migration-only. After this, attachment reads Presence Run Rows, not upload_batch_rows.

Rules:
- migrate only when bag identity + observation timestamp are known
- if an exact retained run row exists for (bag, observed_at near run finished_at), fill weight_num when NULL
- never overwrite non-null authoritative run-row weight_num
- unmatched observations go to rinse_weight_observation_migration_archive
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _connect():
    from backend.db import get_db

    return get_db()


def migrate_upload_batch_weights_to_presence_run_rows(
    cursor,
    organization_id: int,
    *,
    dry_run: bool = True,
    match_window_seconds: int = 6 * 3600,
    only_bags_with_run_rows: bool = True,
    observed_at_on_or_after: datetime | None = None,
) -> dict[str, Any]:
    from backend.checkout_batch_scope import _batch_pk, _row_batch_col
    from backend.rinse_bag_completion import normalize_bag_id
    from backend.rinse_cleaner_ticket_presence import ensure_weight_observation_migration_archive
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs
    from backend.ta_helpers import table_exists, table_has_column

    org = int(organization_id)
    ensure_weight_observation_migration_archive(cursor)
    report: dict[str, Any] = {
        "organization_id": org,
        "dry_run": dry_run,
        "candidates": 0,
        "applied_to_run_row": 0,
        "already_present": 0,
        "archived_unmatched": 0,
        "skipped_no_timestamp": 0,
        "conflicts": 0,
        "details": [],
    }
    if not table_exists(cursor, "upload_batch_rows") or not table_has_column(
        cursor, "upload_batch_rows", "weight_num"
    ):
        report["error"] = "upload_batch_rows.weight_num unavailable"
        return report
    if not table_exists(cursor, "rinse_cleaner_ticket_presence_run_rows"):
        report["error"] = "presence_run_rows missing"
        return report

    bag_filter: set[str] | None = None
    if only_bags_with_run_rows:
        cursor.execute(
            """
            SELECT DISTINCT bag_id FROM rinse_cleaner_ticket_presence_run_rows
            WHERE organization_id=%s AND (weight_num IS NULL)
            """,
            (org,),
        )
        bag_filter = {
            normalize_bag_id(r.get("bag_id"))
            for r in (cursor.fetchall() or [])
            if isinstance(r, dict) and normalize_bag_id(r.get("bag_id"))
        }
        report["null_weight_run_row_bags"] = len(bag_filter or [])
        if not bag_filter:
            report["note"] = "no run rows with null weight_num"
            return report

    # Preload run-row observations by bag for matching (avoid N+1).
    cursor.execute(
        """
        SELECT rr.id AS run_row_id, rr.presence_run_id, rr.bag_id, rr.weight_num,
               COALESCE(rr.observed_at, r.finished_at, r.created_at) AS obs
        FROM rinse_cleaner_ticket_presence_run_rows rr
        JOIN rinse_cleaner_ticket_presence_runs r ON r.id = rr.presence_run_id
        WHERE rr.organization_id=%s
        """,
        (org,),
    )
    by_bag: dict[str, list[dict[str, Any]]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bag = normalize_bag_id(row.get("bag_id"))
        if not bag:
            continue
        if bag_filter is not None and bag not in bag_filter:
            continue
        by_bag.setdefault(bag, []).append(dict(row))

    row_batch_col = _row_batch_col(cursor)
    batch_pk = _batch_pk(cursor)
    join = ""
    confirmed_expr = "ubr.created_at"
    org_clause = ""
    args: list[Any] = []
    if row_batch_col and table_exists(cursor, "upload_batches"):
        join = f" LEFT JOIN upload_batches ub ON ub.{batch_pk} = ubr.{row_batch_col}"
        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            confirmed_expr = "COALESCE(ub.confirmed_at, ubr.created_at)"
        if table_has_column(cursor, "upload_batches", "organization_id"):
            org_clause = " AND ub.organization_id = %s"
            args.append(org)

    date_clause = ""
    if observed_at_on_or_after is not None:
        date_clause = f" AND {confirmed_expr} >= %s"
        args.append(observed_at_on_or_after)

    batch_order_col = f"ubr.{row_batch_col}" if row_batch_col else "ubr.id"
    cursor.execute(
        f"""
        SELECT ubr.ticket_id AS bag_id, ubr.weight_num AS weight_num,
               {confirmed_expr} AS observed_at, {batch_order_col} AS upload_batch_id
        FROM upload_batch_rows ubr{join}
        WHERE ubr.weight_num IS NOT NULL{org_clause}{date_clause}
        ORDER BY {batch_order_col} ASC, ubr.id ASC
        """,
        tuple(args),
    )
    window = timedelta(seconds=int(match_window_seconds))
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bag = normalize_bag_id(row.get("bag_id"))
        lbs = normalize_scan_weight_lbs(row.get("weight_num"))
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, datetime):
            report["skipped_no_timestamp"] += 1
            continue
        if not bag or lbs is None:
            continue
        if bag_filter is not None and bag not in bag_filter:
            continue
        report["candidates"] += 1
        matches = by_bag.get(bag) or []
        chosen = None
        best_delta = None
        for m in matches:
            obs = m.get("obs")
            if not isinstance(obs, datetime):
                continue
            delta = abs(obs - observed_at)
            if delta <= window and (best_delta is None or delta < best_delta):
                best_delta = delta
                chosen = m
        if chosen is None:
            report["archived_unmatched"] += 1
            detail = {
                "bag_id": bag,
                "weight_num": lbs,
                "observed_at": observed_at.isoformat(),
                "upload_batch_id": row.get("upload_batch_id"),
                "status": "unmatched",
            }
            if len(report["details"]) < 50:
                report["details"].append(detail)
            if not dry_run:
                cursor.execute(
                    """
                    INSERT INTO rinse_weight_observation_migration_archive (
                        organization_id, bag_id, weight_num, observed_at, upload_batch_id,
                        matched_presence_run_id, matched_presence_run_row_id, status, detail_json
                    ) VALUES (%s,%s,%s,%s,%s,NULL,NULL,'unmatched',%s)
                    """,
                    (
                        org,
                        bag,
                        lbs,
                        observed_at,
                        row.get("upload_batch_id"),
                        json.dumps(detail),
                    ),
                )
            continue

        existing = normalize_scan_weight_lbs(chosen.get("weight_num"))
        if existing is not None:
            if existing == lbs:
                report["already_present"] += 1
            else:
                report["conflicts"] += 1
                detail = {
                    "bag_id": bag,
                    "weight_num": lbs,
                    "existing_weight_num": existing,
                    "observed_at": observed_at.isoformat(),
                    "run_row_id": chosen.get("run_row_id"),
                    "status": "conflict_existing_authoritative",
                }
                if len(report["details"]) < 50:
                    report["details"].append(detail)
                if not dry_run:
                    cursor.execute(
                        """
                        INSERT INTO rinse_weight_observation_migration_archive (
                            organization_id, bag_id, weight_num, observed_at, upload_batch_id,
                            matched_presence_run_id, matched_presence_run_row_id, status, detail_json
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,'conflict',%s)
                        """,
                        (
                            org,
                            bag,
                            lbs,
                            observed_at,
                            row.get("upload_batch_id"),
                            chosen.get("presence_run_id"),
                            chosen.get("run_row_id"),
                            json.dumps(detail),
                        ),
                    )
            continue

        report["applied_to_run_row"] += 1
        # Update in-memory so subsequent candidates see filled weight.
        chosen["weight_num"] = lbs
        if not dry_run:
            cursor.execute(
                """
                UPDATE rinse_cleaner_ticket_presence_run_rows
                SET weight_num=%s
                WHERE id=%s AND organization_id=%s AND weight_num IS NULL
                """,
                (lbs, chosen.get("run_row_id"), org),
            )
            cursor.execute(
                """
                INSERT INTO rinse_weight_observation_migration_archive (
                    organization_id, bag_id, weight_num, observed_at, upload_batch_id,
                    matched_presence_run_id, matched_presence_run_row_id, status, detail_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'applied',%s)
                """,
                (
                    org,
                    bag,
                    lbs,
                    observed_at,
                    row.get("upload_batch_id"),
                    chosen.get("presence_run_id"),
                    chosen.get("run_row_id"),
                    json.dumps({"bag_id": bag, "run_row_id": chosen.get("run_row_id")}),
                ),
            )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=int(os.environ.get("ORG_ID") or 3))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--since", type=str, default="2026-07-23")
    args = parser.parse_args()
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since)
    conn = _connect()
    cur = conn.cursor(dictionary=True)
    try:
        report = migrate_upload_batch_weights_to_presence_run_rows(
            cur,
            args.org,
            dry_run=not args.apply,
            observed_at_on_or_after=since,
        )
        print(json.dumps({k: v for k, v in report.items() if k != "details"}, default=str, indent=2))
        if report.get("details"):
            print("details_sample=", json.dumps(report["details"][:10], default=str))
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
