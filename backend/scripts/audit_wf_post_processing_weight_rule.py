#!/usr/bin/env python3
"""Pre-deploy audit: post-processing weight WF completion rule."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ORG = 3


def _old_wf_status(events, anchor, as_of_end):
    from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, AV_STATUS_PENDING
    from backend.rinse_bag_stage_bounds import gaming_events_from_records
    from backend.rinse_wf_weight_events import wf_operational_completion, wf_processing_final_weight_completion

    tl = gaming_events_from_records(events)
    hit = wf_processing_final_weight_completion(tl, anchor_ts=anchor, as_of_end=as_of_end)
    if hit is None:
        hit = wf_operational_completion(tl, anchor_ts=anchor, as_of_end=as_of_end)
    if hit:
        return AV_STATUS_COMPLETED, hit.signal, hit.completion_ts
    return AV_STATUS_PENDING, None, None


def main() -> None:
    from backend.db import get_db
    from backend.rinse_at_vendor_module import (
        AV_STATUS_COMPLETED,
        _evaluate_bag_as_of,
        _merge_wf_completion_events_by_bag,
        _normalize_service,
        _resolve_selected_day_anchor_ts,
        build_at_vendor_module,
        naive_et_day_end_exclusive,
    )
    from backend.rinse_folding_et import naive_et_day_end_inclusive
    from backend.rinse_scheduled_scrape import _today_et
    from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline
    from backend.rinse_wf_weight_events import derive_wf_clean_weight_fields

    selected = _today_et()
    as_of = naive_et_day_end_inclusive(selected)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        baseline_ctx = build_baseline_context(cur, ORG, get_shift_monitor_baseline(cur, ORG))
        av = build_at_vendor_module(cur, ORG, selected_date_et=selected, baseline_ctx=baseline_ctx)
        wf_rows = [
            r for r in av["rows"]
            if _normalize_service(r.get("service_type") or r.get("service_bucket")) == "WF"
        ]
        bag_ids = [str(r["bag_id"]).upper() for r in wf_rows]
        from backend.rinse_at_vendor_module import _load_at_vendor_scan_events_for_bags, _load_wf_completion_supplement_for_bags

        events_by = _load_at_vendor_scan_events_for_bags(cur, ORG, bag_ids)
        supp = _load_wf_completion_supplement_for_bags(
            cur, ORG, bag_ids, scanned_before=naive_et_day_end_exclusive(selected)
        )
        merged = _merge_wf_completion_events_by_bag(events_by, supp)

        old_c = old_p = new_c = new_p = 0
        completed_to_pending = []
        pre_only = []
        both_weights = []

        for row in wf_rows:
            bid = str(row["bag_id"]).upper()
            events = merged.get(bid) or []
            anchor = _resolve_selected_day_anchor_ts(events, selected)
            old_st, old_sig, old_ts = _old_wf_status(events, anchor, as_of)
            new_st, new_sig, new_ts, _, fields = _evaluate_bag_as_of(
                events, service_type="WF", as_of_end=as_of, anchor_ts_override=anchor
            )
            if old_st == AV_STATUS_COMPLETED:
                old_c += 1
            else:
                old_p += 1
            if new_st == AV_STATUS_COMPLETED:
                new_c += 1
            else:
                new_p += 1

            weight_fields = fields or {}
            has_pre = weight_fields.get("pre_clean_weight_time") is not None
            has_post = weight_fields.get("post_clean_weight_time") is not None
            entry = {
                "bag_id": bid,
                "customer_name": row.get("customer_name"),
                "old_status": old_st,
                "new_status": new_st,
                "old_completion_signal": old_sig,
                "new_completion_signal": new_sig,
                "old_completion_ts": old_ts.isoformat() if old_ts else None,
                "new_completion_ts": new_ts.isoformat() if new_ts else None,
                "latest_processing_time": weight_fields.get("latest_processing_time"),
                "latest_processing_purpose": weight_fields.get("latest_processing_purpose"),
                "pre_clean_weight_time": weight_fields.get("pre_clean_weight_time"),
                "post_clean_weight_time": weight_fields.get("post_clean_weight_time"),
            }
            if has_pre and not has_post:
                pre_only.append(entry)
            if has_pre and has_post:
                both_weights.append(entry)
            if old_st == AV_STATUS_COMPLETED and new_st != AV_STATUS_COMPLETED:
                completed_to_pending.append(entry)

        report = {
            "selected_date_et": str(selected),
            "before": {"completed": old_c, "pending": old_p, "total": old_c + old_p},
            "after": {"completed": new_c, "pending": new_p, "total": new_c + new_p},
            "completed_to_pending": completed_to_pending,
            "pre_clean_only_pending": pre_only,
            "pre_and_post_clean_weight": both_weights,
        }
        out = REPO / "data" / "wf_post_processing_weight_audit.json"
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
