#!/usr/bin/env python3
"""Bag-level Rush WF reconciliation for Jul 8 operational workload vs UI."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

AV_RUSH = "RUSH"
AV_WF = "WF"


def _is_rush_wf(row: dict) -> tuple[bool, str]:
    rush = str(row.get("rush_bucket") or "").strip().upper()
    svc = str(row.get("service_type") or row.get("service_bucket") or "").strip().upper()
    if svc not in ("WF",) and not svc.startswith("WF"):
        return False, f"service={svc or 'missing'}"
    if rush != AV_RUSH:
        return False, f"rush={rush or 'missing'}"
    return True, "rush_wf"


def _operational_bucket(
    *,
    bid: str,
    tier: str,
    ledger_status: str,
    row: dict | None,
    nv_ids: set[str],
    ui_row_ids: set[str],
) -> tuple[str, str, bool]:
    """Return (bucket_label, reason, shown_in_ui_rush_wf)."""
    in_ui = bid in ui_row_ids
    in_nv = bid in nv_ids

    if tier in ("excluded_completed_before_day", "excluded_rejected"):
        return "Excluded / Rejected", f"membership_tier={tier}", False
    if tier == "historical_backlog":
        return "Historical Backlog", f"membership_tier={tier}", False
    if in_nv:
        return "Needs Verification", "off_portal_stale_pending_or_scrape_rejected", False
    if row is None:
        if ledger_status == "completed":
            return (
                "Operational Completed (missing from UI)",
                "active_tier_completed_not_reinjected",
                False,
            )
        if ledger_status == "pending":
            return (
                "Operational Pending (missing from UI)",
                "active_tier_pending_not_on_rows",
                False,
            )
        if ledger_status == "sent_to_rinse":
            return (
                "Operational Completed (missing from UI)",
                "active_tier_sent_to_rinse_not_reinjected",
                False,
            )
        return f"Ledger-only ({ledger_status})", f"active_tier_status={ledger_status}", False

    tags = row.get("module_tags") or []
    if "mod_at_vendor_completed" in tags or str(row.get("at_vendor_status") or "").lower() == "completed":
        if in_ui:
            return "Operational Completed", "in module.rows", True
        return "Operational Completed (missing from UI)", "completed_row_not_in_module.rows", False
    if "mod_at_vendor_pending" in tags or str(row.get("at_vendor_status") or "").lower() == "pending":
        if in_ui:
            return "Operational Pending", "in module.rows", True
        return "Operational Pending (missing from UI)", "pending_row_not_in_module.rows", False
    return "Other operational row", f"tags={tags}", in_ui


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--date", default="2026-07-08")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")

    selected = date.fromisoformat(args.date)
    org = int(args.org)

    from backend.db import get_db
    from backend.rinse_at_vendor_module import (
        AV_RUSH as MOD_RUSH,
        MOD_AT_VENDOR_COMPLETED,
        MOD_AT_VENDOR_PENDING,
        _load_at_vendor_scan_events_for_bags,
        _normalize_service,
        build_at_vendor_module,
        classify_at_vendor_rush,
    )
    from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
    from backend.rinse_shift_monitor_baseline import (
        build_baseline_context,
        get_shift_monitor_baseline,
    )
    from backend.rinse_workload_ledger import (
        classify_bag_membership_tier,
        is_active_membership_tier,
        load_workload_ledger,
    )

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    baseline = build_baseline_context(cur, org, get_shift_monitor_baseline(cur, org))
    av = build_at_vendor_module(cur, org, selected_date_et=selected, baseline_ctx=baseline)

    ledger = load_workload_ledger(cur, org, selected)
    ui_rows = av.get("rows") or []
    ui_row_by_bag = {str(r["bag_id"]).upper(): r for r in ui_rows if r.get("bag_id")}
    nv_rows = (av.get("operational_exceptions") or {}).get("needs_verification_rows") or []
    nv_by_bag = {str(r["bag_id"]).upper(): r for r in nv_rows if r.get("bag_id")}
    nv_ids = set(nv_by_bag)

    # Rush+WF filter matching frontend countAtVendorBucket(rush=rush, service=wf)
    def ui_rush_wf_match(row: dict) -> bool:
        rush = str(row.get("rush_bucket") or "").upper()
        svc = str(row.get("service_type") or row.get("service_bucket") or "").upper()
        return rush == MOD_RUSH and svc == "WF"

    ui_rush_wf_ids = {bid for bid, r in ui_row_by_bag.items() if ui_rush_wf_match(r)}

    # Universe: all ledger bags + NV + UI rows (dedupe)
    all_bag_ids = sorted(set(ledger.keys()) | set(ui_row_by_bag) | set(nv_by_bag))
    events_by_bag = _load_at_vendor_scan_events_for_bags(cur, org, all_bag_ids)

    day_start = naive_et_day_start(selected)
    day_end_excl = naive_et_day_start(selected + timedelta(days=1))

    def sent_to_vendor_today(events: list) -> bool:
        from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records
        from backend.rinse_scan_purpose import is_sent_to_vendor_purpose

        for ev in gaming_events_from_records(events):
            if not is_sent_to_vendor_purpose(ev.get("purpose")):
                continue
            ts = event_ts(ev)
            if ts and day_start <= ts < day_end_excl:
                return True
        return False

    bags: list[dict] = []
    for bid in all_bag_ids:
        rec = ledger.get(bid) or {}
        snap = rec.get("row_snapshot") or {}
        row = ui_row_by_bag.get(bid) or nv_by_bag.get(bid)
        if row is None and snap:
            row = dict(snap)
            row["bag_id"] = bid

        # Prefer live row rush/svc; fall back to ledger
        rush = (row or snap or rec).get("rush_bucket") or rec.get("rush_bucket")
        svc = _normalize_service(
            (row or snap or rec).get("service_type") or (row or snap or rec).get("service_bucket")
            or rec.get("workflow")
        )
        probe = {"rush_bucket": rush, "service_type": svc, "service_bucket": svc}
        is_rw, rw_reason = _is_rush_wf(probe)

        tier = str(rec.get("membership_tier") or (row or {}).get("membership_tier") or "")
        if not tier and row:
            tier = classify_bag_membership_tier(
                events_by_bag.get(bid) or [],
                service_type=svc or "WF",
                selected_date_et=selected,
            )

        ledger_status = str(rec.get("current_status") or "")
        bucket, reason, in_ui = _operational_bucket(
            bid=bid,
            tier=tier,
            ledger_status=ledger_status,
            row=ui_row_by_bag.get(bid),
            nv_ids=nv_ids,
            ui_row_ids=ui_rush_wf_ids,
        )

        evs = events_by_bag.get(bid) or []
        customer = (row or snap or {}).get("customer_name") or (row or snap or {}).get("customer")

        bags.append(
            {
                "bag_id": bid,
                "customer": customer,
                "is_rush_wf": is_rw,
                "rush_wf_skip_reason": None if is_rw else rw_reason,
                "rush_bucket": rush,
                "rush_bucket_source": "row" if ui_row_by_bag.get(bid) else "ledger_snapshot",
                "workflow": svc,
                "membership_tier": tier,
                "ledger_status": ledger_status,
                "active_tier": is_active_membership_tier(tier),
                "sent_to_vendor_today": sent_to_vendor_today(evs),
                "completed_today": bool(
                    (row or snap or {}).get("completed_during_et_day")
                    or MOD_AT_VENDOR_COMPLETED in ((row or snap or {}).get("module_tags") or [])
                    or ledger_status == "completed"
                ),
                "latest_status": (row or snap or {}).get("at_vendor_status") or ledger_status,
                "operational_bucket": bucket,
                "bucket_reason": reason,
                "shown_in_ui_rush_wf": in_ui,
                "on_portal": (ui_row_by_bag.get(bid) or {}).get("currently_on_vendor_home"),
            }
        )

    rush_wf_bags = [b for b in bags if b["is_rush_wf"]]

    bucket_counts = Counter(b["operational_bucket"] for b in rush_wf_bags)
    ui_shown = sum(1 for b in rush_wf_bags if b["shown_in_ui_rush_wf"])
    active_rw = [b for b in rush_wf_bags if b["active_tier"]]

    op_pending = sum(1 for b in rush_wf_bags if b["operational_bucket"] == "Operational Pending")
    op_completed = sum(
        1 for b in rush_wf_bags if b["operational_bucket"].startswith("Operational Completed")
    )
    op_pending_ui = sum(
        1
        for b in rush_wf_bags
        if b["operational_bucket"] == "Operational Pending" and b["shown_in_ui_rush_wf"]
    )
    op_completed_ui = sum(
        1
        for b in rush_wf_bags
        if b["operational_bucket"] == "Operational Completed" and b["shown_in_ui_rush_wf"]
    )

    missing_from_ui = [b for b in rush_wf_bags if not b["shown_in_ui_rush_wf"] and b["active_tier"]]

    report = {
        "org": org,
        "et_date": selected.isoformat(),
        "ui_counts": {
            "module_total": av.get("total"),
            "module_pending": av.get("pending"),
            "module_completed": av.get("completed"),
            "wf_total_all_rush": av.get("wf_total"),
            "rush_wf_total_ui_filter": len(ui_rush_wf_ids),
            "rush_wf_pending_ui": sum(
                1
                for bid in ui_rush_wf_ids
                if MOD_AT_VENDOR_PENDING in (ui_row_by_bag[bid].get("module_tags") or [])
            ),
            "rush_wf_completed_ui": sum(
                1
                for bid in ui_rush_wf_ids
                if MOD_AT_VENDOR_COMPLETED in (ui_row_by_bag[bid].get("module_tags") or [])
            ),
            "needs_verification_total": len(nv_ids),
        },
        "reconciliation": {
            "rush_wf_universe_all_tiers": len(rush_wf_bags),
            "rush_wf_active_tier": len(active_rw),
            "rush_wf_operational_pending": op_pending,
            "rush_wf_operational_completed": op_completed,
            "rush_wf_operational_total": op_pending + op_completed,
            "rush_wf_in_ui": ui_shown,
            "rush_wf_missing_from_ui_active_tier": len(missing_from_ui),
            "bucket_totals": dict(sorted(bucket_counts.items())),
        },
        "gap_analysis": {
            "ui_vs_operational_total": len(ui_rush_wf_ids) - (op_pending_ui + op_completed_ui),
            "active_missing_breakdown": Counter(
                b["operational_bucket"] for b in missing_from_ui
            ),
            "active_missing_reasons": Counter(b["bucket_reason"] for b in missing_from_ui),
        },
        "key_checks": {
            "nv_rush_wf_count": sum(
                1 for b in rush_wf_bags if b["operational_bucket"] == "Needs Verification"
            ),
            "historical_backlog_rush_wf": sum(
                1 for b in rush_wf_bags if b["operational_bucket"] == "Historical Backlog"
            ),
            "excluded_rush_wf": sum(
                1 for b in rush_wf_bags if b["operational_bucket"] == "Excluded / Rejected"
            ),
            "completed_not_reinjected": sum(
                1
                for b in rush_wf_bags
                if "not_reinjected" in b["bucket_reason"] or b["operational_bucket"].endswith("(missing from UI)")
            ),
            "sent_today_but_historical_backlog": [
                b["bag_id"]
                for b in rush_wf_bags
                if b["membership_tier"] == "historical_backlog" and b["sent_to_vendor_today"]
            ][:20],
            "non_rush_wf_in_universe_skipped": sum(1 for b in bags if not b["is_rush_wf"]),
        },
        "missing_from_ui_active_rush_wf": missing_from_ui,
        "all_rush_wf_bags": rush_wf_bags,
    }

    out_path = args.out or REPO / f"data/audit_jul8_rush_wf_reconciliation_org{org}.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    summary = {k: v for k, v in report.items() if k not in ("missing_from_ui_active_rush_wf", "all_rush_wf_bags")}
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nFull bag list written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
