#!/usr/bin/env python3
"""At-vendor portal scrape → inspect credible supply signal → confirm only when gate passes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.rinse_portal_confirm_gate import evaluate_portal_confirm_gate


def inspect_portal_csv(csv_path: Path) -> dict[str, Any]:
    return evaluate_portal_confirm_gate(csv_path, force_confirm=False)


def run_scrape_and_maybe_confirm(
    organization_id: int,
    *,
    run_type: str = "manual",
    max_pages: int = 500,
    execute_confirm: bool = True,
    force_confirm: bool = False,
) -> dict[str, Any]:
    from backend.db import get_db
    from backend.rinse_scheduled_scrape import (
        CYCLE_ALREADY_RUNNING,
        _TeeLog,
        _count_accepted_rows,
        _count_attention_rows,
        _run_bash_script,
        _subprocess_env_for_vendor,
        _today_et,
        _stamp_et,
        acquire_scrape_lock,
        build_run_paths,
        count_csv_data_rows,
        insert_scrape_run,
        release_scrape_lock,
        tenant_script_dir,
        _org_slug_name,
    )
    from backend.rinse_vendor_config import resolve_rinse_vendor

    org_id = int(organization_id)
    os.environ["RINSE_MAX_PAGES"] = str(max(1, min(500, int(max_pages))))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    slug, org_name = _org_slug_name(cursor, org_id)
    vendor = resolve_rinse_vendor(org_id, organization_slug=slug, organization_name=org_name)
    tenant_dir = tenant_script_dir(vendor)

    acquired, lock_reason = acquire_scrape_lock(cursor, org_id)
    conn.commit()
    if not acquired:
        return {"status": "skipped", "error": lock_reason or CYCLE_ALREADY_RUNNING}

    paths = build_run_paths(org_id, run_type, tenant_slug=slug, rinse_vendor=vendor)
    run_id = insert_scrape_run(
        cursor,
        org_id,
        tenant_slug=slug,
        rinse_vendor=vendor,
        run_type=run_type,
        log_path=str(paths.log_path),
    )
    conn.commit()
    log = _TeeLog(paths.log_path)

    out: dict[str, Any] = {
        "organization_id": org_id,
        "run_id": run_id,
        "paths": str(paths.run_dir),
        "max_pages": os.environ["RINSE_MAX_PAGES"],
    }

    try:
        env = _subprocess_env_for_vendor(
            org_id, vendor, paths, organization_slug=slug, organization_name=org_name
        )
        env["RINSE_MAX_PAGES"] = os.environ["RINSE_MAX_PAGES"]
        portal_script = tenant_dir / "run-production-scrape.sh"
        scan_script = tenant_dir / "run-scan-events.sh"

        log.write(f"At-vendor inspect scrape org={org_id} RINSE_MAX_PAGES={env['RINSE_MAX_PAGES']}\n")
        if _run_bash_script(portal_script, env, log) != 0:
            raise RuntimeError("Portal scrape subprocess failed")
        if not paths.portal_csv.is_file() or count_csv_data_rows(paths.portal_csv) < 1:
            raise RuntimeError("Portal CSV missing or empty after scrape")

        gate = evaluate_portal_confirm_gate(paths.portal_csv, force_confirm=force_confirm)
        out["inspection"] = gate
        log.write(json.dumps(gate, indent=2) + "\n")

        if not gate.get("should_create_batch"):
            out["status"] = "skipped_confirm"
            out["message"] = gate.get("warning") or gate.get("reason")
            log.write(f"{out['message']}\n")
            conn.commit()
            return out

        if gate.get("force_override"):
            log.write(f"WARNING: {gate.get('warning')}\n")

        if _run_bash_script(scan_script, env, log) != 0:
            raise RuntimeError("Scan-events scrape subprocess failed")
        if count_csv_data_rows(paths.scan_events_csv) < 1:
            raise RuntimeError("Scan-events CSV missing or empty after scrape")

        from backend.rinse_combined_upload import commit_rinse_combined_upload
        from backend.rinse_portal_csv import portal_csv_to_orders_df
        from backend.rinse_scan_events_upload import parse_scan_events_csv
        from backend.rinse_portal_scrape_meta import meta_path_for_portal_csv
        from backend.manual_checkout_eligibility import resolve_stale_portal_attention_rows_before_confirm

        batch_date = _today_et()
        portal_name = f"scheduled-rinse-portal-{_stamp_et()}.csv"
        events_name = f"scheduled-rinse-events-{_stamp_et()}.csv"
        orders_df = portal_csv_to_orders_df(str(paths.portal_csv))
        events_df, warnings = parse_scan_events_csv(str(paths.scan_events_csv))
        if len(orders_df) < 1:
            raise RuntimeError("Portal CSV parsed to zero order rows")

        draft_payload = commit_rinse_combined_upload(
            conn,
            cursor,
            org_id,
            batch_date,
            portal_name,
            orders_df,
            events_name,
            events_df,
            portal_scrape_meta_path=str(meta_path_for_portal_csv(paths.portal_csv)),
        )
        batch_id = int(draft_payload["batch_id"])
        out["batch_id"] = batch_id
        out["draft"] = draft_payload
        log.write(f"Draft batch_id={batch_id}\n")

        if not execute_confirm:
            out["status"] = "draft_only"
            conn.commit()
            return out

        resolve_stale_portal_attention_rows_before_confirm(cursor, org_id, batch_id)
        if _count_accepted_rows(cursor, batch_id) < 1:
            conn.rollback()
            raise RuntimeError("All portal rows rejected; nothing to apply")
        if _count_attention_rows(cursor, batch_id) > 0:
            out["status"] = "needs_attention"
            out["message"] = f"Draft batch {batch_id} has NEEDS_ATTENTION rows; not confirmed"
            conn.commit()
            return out

        from backend.upload_batch_confirm import confirm_upload_batch_core

        confirm_payload = confirm_upload_batch_core(cursor, org_id, batch_id, force_confirm=False)
        out["confirm"] = confirm_payload
        out["status"] = "confirmed"
        log.write(f"Confirmed batch_id={batch_id}\n")
        conn.commit()
        return out
    except Exception as exc:
        conn.rollback()
        out["status"] = "failed"
        out["error"] = str(exc)
        log.write(f"ERROR: {exc}\n")
        raise
    finally:
        log.close()
        try:
            release_scrape_lock(cursor, org_id)
            conn.commit()
        except Exception:
            conn.rollback()
        cursor.close()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--draft-only", action="store_true", help="Create draft but do not confirm")
    parser.add_argument("--force-confirm", action="store_true", help="Bypass credible-supply gate")
    parser.add_argument("--inspect-only", type=Path, help="Inspect existing portal.csv (skip scrape)")
    args = parser.parse_args()

    if args.inspect_only:
        report = inspect_portal_csv(args.inspect_only)
        print(json.dumps(report, indent=2))
        return 0

    report = run_scrape_and_maybe_confirm(
        args.org,
        max_pages=args.max_pages,
        execute_confirm=not args.draft_only,
        force_confirm=args.force_confirm,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("status") in ("confirmed", "skipped_confirm", "draft_only", "needs_attention") else 1


if __name__ == "__main__":
    raise SystemExit(main())
