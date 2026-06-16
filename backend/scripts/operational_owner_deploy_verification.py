#!/usr/bin/env python3
"""Post-deploy verification for operational owner isolation (Steps 3–5)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ORG = 3


def _parse_json(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _owner_table_summary(cursor, org: int) -> dict:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "rinse_bag_operational_owner"):
        return {"table_exists": False}
    cursor.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN owner_organization_id = %s THEN 1 ELSE 0 END) AS owned_by_org,
          SUM(CASE WHEN owner_organization_id != %s THEN 1 ELSE 0 END) AS owned_by_other
        FROM rinse_bag_operational_owner
        """,
        (org, org),
    )
    row = dict(cursor.fetchone() or {})
    return {"table_exists": True, **row}


def _mismatched_bag_ids(cursor, org: int) -> list[str]:
    from backend.rinse_bag_operational_owner import audit_org_operational_isolation

    audit = audit_org_operational_isolation(cursor, org)
    out = []
    for entry in audit.get("mismatched_bags") or []:
        owner_org = entry.get("canonical_owner_organization_id")
        if owner_org is not None and int(owner_org) != org:
            out.append(str(entry["bag_id"]).upper())
    return sorted(out)


def _rejection_report_from_presence_run(cursor, org: int, run_id: int | None = None) -> dict:
    if run_id is None:
        cursor.execute(
            """
            SELECT id, finished_at, rows_found, errors_json, scrape_meta_json
            FROM rinse_cleaner_ticket_presence_runs
            WHERE organization_id = %s AND portal_status = 'at_vendor'
            ORDER BY id DESC LIMIT 1
            """,
            (org,),
        )
        run = cursor.fetchone()
    else:
        cursor.execute(
            """
            SELECT id, finished_at, rows_found, errors_json, scrape_meta_json
            FROM rinse_cleaner_ticket_presence_runs
            WHERE id = %s AND organization_id = %s
            """,
            (run_id, org),
        )
        run = cursor.fetchone()
    if not run:
        return {"run_found": False}

    errors = _parse_json(run.get("errors_json")) or []
    rejected = []
    for e in errors:
        if not isinstance(e, dict):
            continue
        err = str(e.get("error") or "")
        if err in ("operational_owner_mismatch", "cross_org_washpro_owned"):
            rejected.append(
                {
                    "bag_id": e.get("bag_id"),
                    "error": err,
                    "context": "presence_scrape",
                }
            )

    meta = _parse_json(run.get("scrape_meta_json")) or {}
    cross = meta.get("cross_org_presence_excluded") or meta.get("operational_owner_rejected") or []

    return {
        "run_found": True,
        "run_id": run.get("id"),
        "finished_at": str(run.get("finished_at")),
        "rows_found": run.get("rows_found"),
        "presence_scrape_rejected": rejected,
        "meta_owner_rejected_count": len(cross),
        "meta_owner_rejected": cross,
    }


def _new_rows_on_mismatched_bags(cursor, org: int, bag_ids: list[str], since_utc: str | None) -> dict:
    from backend.ta_helpers import table_exists, table_has_column

    if not bag_ids:
        return {}
    ph = ",".join(["%s"] * len(bag_ids))
    out: dict[str, dict] = {}
    since_clause = ""
    args_base: list = [org]
    if since_utc:
        since_clause = " AND created_at >= %s"
        args_base.append(since_utc)

    checks = []
    if table_exists(cursor, "rinse_bag_registry"):
        checks.append(
            (
                "rinse_bag_registry",
                f"SELECT COUNT(*) AS c FROM rinse_bag_registry WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph}){since_clause.replace('created_at', 'updated_at')}",
            )
        )
    if table_exists(cursor, "rinse_bag_scan_events"):
        checks.append(
            (
                "rinse_bag_scan_events",
                f"SELECT COUNT(*) AS c FROM rinse_bag_scan_events WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph}){since_clause}",
            )
        )
    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        checks.append(
            (
                "rinse_cleaner_ticket_presence",
                f"SELECT COUNT(*) AS c FROM rinse_cleaner_ticket_presence WHERE organization_id=%s AND UPPER(TRIM(bag_id)) IN ({ph}){since_clause.replace('created_at', 'updated_at')}",
            )
        )

    for table, sql in checks:
        args = list(args_base) + list(bag_ids)
        if since_utc and "since" in sql:
            # args_base already has since for tables using since_clause
            pass
        cursor.execute(sql, tuple(args))
        out[table] = int((cursor.fetchone() or {}).get("c") or 0)
    return out


def _portal_snapshot_report(cursor, org: int, today: date) -> dict:
    from backend.rinse_current_facility_snapshot import build_portal_snapshot_vendor_home_fields

    fields = build_portal_snapshot_vendor_home_fields(cursor, org, today=today, module={})
    recon = fields.get("portal_snapshot_presence_reconciliation") or {}
    return {
        "portal_reported_orders_at_veewash": fields.get("portal_reported_orders_at_veewash"),
        "operational_orders_at_veewash": fields.get("orders_at_veewash"),
        "operational_source": fields.get("orders_at_veewash_source"),
        "reconciliation": recon,
        "difference": recon.get("difference"),
        "portal_reported_yet_to_process": fields.get("portal_reported_orders_at_veewash_yet_to_process"),
        "operational_yet_to_process": fields.get("orders_at_veewash_yet_to_process"),
        "portal_reported_due_today": fields.get("portal_reported_due_today"),
        "operational_due_today": fields.get("due_today"),
    }


def _cleanup_dry_run(cursor, org: int) -> dict:
    from backend.scripts.cleanup_operational_owner_org_rows import build_cleanup_plan

    return build_cleanup_plan(cursor, org)


def main() -> None:
    parser = argparse.ArgumentParser(description="Operational owner deploy verification")
    parser.add_argument("--org", type=int, default=ORG)
    parser.add_argument(
        "--run-presence-scrape",
        action="store_true",
        help="Run at_vendor presence scrape before gate verification",
    )
    parser.add_argument("--today", type=str, default=None, help="ET date YYYY-MM-DD for portal snapshot")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    from backend.db import get_db
    from backend.rinse_bag_operational_owner import (
        audit_org_operational_isolation,
        operational_owner_gate_enabled,
    )

    org = int(args.org)
    today = date.fromisoformat(args.today) if args.today else date.today()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    report: dict = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "organization_id": org,
        "gate_enabled": operational_owner_gate_enabled(),
        "owner_table": _owner_table_summary(cursor, org),
    }

    audit = audit_org_operational_isolation(cursor, org)
    report["audit_summary"] = {
        "bag_ids_in_org_tables": audit.get("bag_ids_in_org_tables"),
        "canonical_owner_matches_org": audit.get("canonical_owner_matches_org"),
        "canonical_owner_mismatch_count": audit.get("canonical_owner_mismatch_count"),
        "no_canonical_evidence_count": audit.get("no_canonical_evidence_count"),
    }
    mismatched = _mismatched_bag_ids(cursor, org)
    report["mismatched_bag_ids"] = mismatched

    scrape_result = None
    if args.run_presence_scrape:
        from backend.rinse_presence_scrape import run_presence_scrape_for_org

        scrape_result = run_presence_scrape_for_org(
            conn,
            org,
            portal_status="at_vendor",
            dry_run=False,
            mark_missing=False,
            run_type="manual_operational_owner_verify",
        )
        conn.commit()
        report["presence_scrape"] = {
            "status": scrape_result.status,
            "stats": scrape_result.stats,
            "error_message": scrape_result.error_message,
        }

    report["step3_gate_verification"] = _rejection_report_from_presence_run(cursor, org)
    report["step3_new_rows_on_mismatched_since_deploy"] = _new_rows_on_mismatched_bags(
        cursor, org, mismatched, None
    )

    report["step4_portal_snapshot"] = _portal_snapshot_report(cursor, org, today)
    report["step5_cleanup_dry_run"] = _cleanup_dry_run(cursor, org)

    out_path = Path(args.output or REPO / "data" / f"operational_owner_deploy_verification_org{org}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps({k: report[k] for k in report if k != "step5_cleanup_dry_run"}, indent=2, default=str))
    print(f"\nFull report: {out_path}")
    print(f"Cleanup dry-run bags: {report['step5_cleanup_dry_run'].get('bag_count')}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
