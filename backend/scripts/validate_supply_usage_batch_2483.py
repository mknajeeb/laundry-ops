#!/usr/bin/env python3
"""Validate Supply Usage membership vs Batch #2483 upload rows (first-weight ET day)."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_bag_stage_bounds import (
    events_after_ts,
    events_on_or_after,
    first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor,
)
from backend.rinse_scan_purpose import is_split_load_purpose
from backend.supply_usage import first_weight_on_et_day, load_orders_for_supply_usage
from backend.ta_helpers import table_has_column


def _connect():
    from backend.db import get_db

    return get_db()


def main() -> int:
    org_id = int(os.environ.get("SUPPLY_USAGE_ORG_ID") or os.environ.get("ORG_ID") or 3)
    batch_id = int(os.environ.get("SUPPLY_USAGE_BATCH_ID") or 2483)
    selected = date.fromisoformat(os.environ.get("SUPPLY_USAGE_DATE_ET") or "2026-07-14")

    conn = _connect()
    cur = conn.cursor(dictionary=True)
    try:
        ub_pk = "id" if table_has_column(cur, "upload_batches", "id") else "batch_id"
        cur.execute(
            f"""
            SELECT ubr.ticket_id, ubr.date_clean, ubr.row_status, ubr.name_clean,
                   ubr.special_instructions_raw
            FROM upload_batch_rows ubr
            INNER JOIN upload_batches ub ON ub.{ub_pk} = ubr.upload_batch_id
            WHERE ubr.upload_batch_id = %s
              AND ub.organization_id = %s
            ORDER BY ubr.name_clean, ubr.ticket_id
            """,
            (batch_id, org_id),
        )
        batch_rows = [dict(r) for r in (cur.fetchall() or []) if isinstance(r, dict)]

        report_orders = {
            normalize_bag_id(o.get("ticket_id")): o
            for o in load_orders_for_supply_usage(cur, org_id, selected)
        }

        from backend.rinse_shift_analysis import _load_scan_events_for_bags

        bag_ids = [
            normalize_bag_id(r.get("ticket_id"))
            for r in batch_rows
            if normalize_bag_id(r.get("ticket_id"))
        ]
        events_by_bag = _load_scan_events_for_bags(cur, org_id, bag_ids)

        rows_out = []
        for r in batch_rows:
            bag = normalize_bag_id(r.get("ticket_id"))
            events = events_by_bag.get(bag) or []
            tl = gaming_events_from_records(events)
            anchor_ts, _ = lifecycle_anchor(tl)
            anchored = events_on_or_after(tl, anchor_ts) if anchor_ts else []
            _, fw_ts = first_weight_after_anchor(anchored) if anchored else (None, None)
            membership = first_weight_on_et_day(events, selected)
            post = events_after_ts(anchored, fw_ts) if fw_ts else []
            latest_split = None
            for ev in post:
                if is_split_load_purpose(ev.get("purpose")):
                    latest_split = ev.get("scanned_at_parsed")
            su = report_orders.get(bag)
            rows_out.append(
                {
                    "bag_id": bag,
                    "customer": r.get("name_clean"),
                    "upload_row_status": r.get("row_status"),
                    "upload_date_clean": str(r.get("date_clean") or ""),
                    "lifecycle_anchor_et": str(anchor_ts) if anchor_ts else None,
                    "first_weight_et": str(fw_ts) if fw_ts else None,
                    "selected_et_day": selected.isoformat(),
                    "in_supply_usage_for_selected_day": bool(su),
                    "latest_split_related_scan_et": str(latest_split) if latest_split else None,
                    "current_split_state": (
                        "confirmed"
                        if su and su.get("split_confirmed")
                        else ("pending" if membership and membership.get("split_pending") else "n/a")
                    ),
                    "processing_units": (su or {}).get("processing_units")
                    or (membership or {}).get("processing_units"),
                    "supply_doses_counted": (su or {}).get("doses_by_supply"),
                    "supplies_used": (su or {}).get("supplies_used"),
                }
            )

        payload = {
            "organization_id": org_id,
            "batch_id": batch_id,
            "selected_date_et": selected.isoformat(),
            "batch_row_count": len(batch_rows),
            "supply_usage_order_count": len(report_orders),
            "rows": rows_out,
        }
        out_path = ROOT / "data" / f"validate_supply_usage_batch_{batch_id}_{selected.isoformat()}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print(json.dumps({"wrote": str(out_path), **{k: payload[k] for k in (
            "organization_id", "batch_id", "selected_date_et",
            "batch_row_count", "supply_usage_order_count",
        )}}, indent=2))
        return 0
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
