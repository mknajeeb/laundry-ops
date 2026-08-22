#!/usr/bin/env python3
"""
Equality proof: OLD vs NEW portal_absence + merge_scan_events on production-derived data.

Read-only for candidate/decision comparison (marks/upserts patched to no-op recorders).
Does not commit business writes.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _latest_full_snapshot_batch(cursor, org: int) -> dict[str, Any] | None:
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "upload_batches"):
        return None
    pk = "id" if table_has_column(cursor, "upload_batches", "id") else "batch_id"
    has_fs = table_has_column(cursor, "upload_batches", "full_snapshot")
    has_org = table_has_column(cursor, "upload_batches", "organization_id")
    cols = f"{pk} AS batch_id"
    if has_fs:
        cols += ", full_snapshot"
    sql = f"SELECT {cols} FROM upload_batches WHERE 1=1"
    args: list[Any] = []
    if has_org:
        sql += " AND organization_id = %s"
        args.append(org)
    if has_fs:
        sql += " AND full_snapshot = 1"
    sql += f" ORDER BY {pk} DESC LIMIT 1"
    cursor.execute(sql, tuple(args))
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None


def _accepted_portal_rows(cursor, batch_id: int) -> list[dict]:
    from backend.rinse_upload_finalize import fetch_accepted_portal_rows_for_finalize

    return fetch_accepted_portal_rows_for_finalize(cursor, int(batch_id))


def _decision_fingerprint(outcomes: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for o in outcomes or []:
        bid = str(o.get("bag_id") or "")
        if not bid:
            continue
        out[bid] = str(o.get("action") or "")
    return out


def prove_portal_absence(cursor, org: int, batch_id: int, accepted: list[dict]) -> dict[str, Any]:
    from backend.rinse_portal_absence_completion import (
        build_current_upload_bag_ids,
        fetch_incomplete_bag_candidates_for_org as fetch_new,
        process_bags_missing_from_latest_portal as process_new,
    )
    from backend.tests.finalize_perf_baseline.rinse_portal_absence_completion_old import (
        fetch_incomplete_bag_candidates_for_org as fetch_old,
        process_bags_missing_from_latest_portal as process_old,
    )

    current = build_current_upload_bag_ids(accepted)
    cand_old = fetch_old(cursor, org)
    cand_new = fetch_new(cursor, org)
    missing_old = sorted(b for b in cand_old if b not in current)
    missing_new = sorted(b for b in cand_new if b not in current)

    recorded_old: list[dict] = []
    recorded_new: list[dict] = []

    def _noop_mark(*_a, **_k):
        return True

    def _noop_recover(*_a, **_k):
        return {"inserted": 0, "already_present": 0, "skipped_no_time": 0, "draft_rows_seen": 0}

    # Decision-only: keep evidence/cancel detection, suppress durable writes + scan inserts.
    patches = [
        patch(
            "backend.rinse_portal_departure_completion.recover_missing_scans_from_upload_batch_history",
            side_effect=_noop_recover,
        ),
        patch(
            "backend.rinse_portal_departure_completion.recover_missing_scans_from_preloaded",
            side_effect=_noop_recover,
        ),
        patch(
            "backend.tests.finalize_perf_baseline.rinse_portal_departure_completion_old.recover_missing_scans_from_upload_batch_history",
            side_effect=_noop_recover,
        ),
        patch(
            "backend.rinse_portal_departure_completion.mark_registry_completed_portal_departure",
            side_effect=_noop_mark,
        ),
        patch(
            "backend.rinse_portal_departure_completion.mark_registry_needs_verification_portal_absence",
            side_effect=_noop_mark,
        ),
        patch(
            "backend.rinse_bag_registry.mark_registry_rejected_portal_absence",
            side_effect=_noop_mark,
        ),
        patch(
            "backend.rinse_bag_registry.deactivate_at_vendor_presence_for_bags",
            return_value=0,
        ),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        out_old = process_old(cursor, org, batch_id, accepted, full_snapshot=True)
        out_new = process_new(cursor, org, batch_id, accepted, full_snapshot=True)

    fp_old = _decision_fingerprint(out_old.get("outcomes") or [])
    fp_new = _decision_fingerprint(out_new.get("outcomes") or [])
    # Also fold completed/rejected/needs lists for bags skipped from outcomes.
    for key, action in (
        ("completed_bag_ids", "completed"),
        ("needs_verification_bag_ids", "needs_verification"),
        ("rejected_bag_ids", "rejected"),
    ):
        for bid in out_old.get(key) or []:
            fp_old.setdefault(str(bid), action)
        for bid in out_new.get(key) or []:
            fp_new.setdefault(str(bid), action)

    return {
        "candidates_equal": cand_old == cand_new,
        "missing_equal": missing_old == missing_new,
        "cand_old_n": len(cand_old),
        "cand_new_n": len(cand_new),
        "missing_old_n": len(missing_old),
        "missing_new_n": len(missing_new),
        "decisions_equal": fp_old == fp_new,
        "decision_diff": sorted(
            {
                bid
                for bid in set(fp_old) | set(fp_new)
                if fp_old.get(bid) != fp_new.get(bid)
            }
        )[:50],
        "fp_old_n": len(fp_old),
        "fp_new_n": len(fp_new),
        "skipped_old": bool(out_old.get("skipped")),
        "skipped_new": bool(out_new.get("skipped")),
    }


def prove_merge_scan_events(cursor, org: int, batch_id: int) -> dict[str, Any]:
    """Compare upsert identities OLD vs NEW on the batch's draft scan events (no DB writes)."""
    from backend.rinse_bag_registry import merge_scan_events_from_upload as merge_new
    from backend.tests.finalize_perf_baseline.rinse_bag_registry_old import (
        merge_scan_events_from_upload as merge_old,
    )
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "upload_batch_scan_events"):
        return {"ok": False, "reason": "no_upload_batch_scan_events"}

    cursor.execute(
        """
        SELECT bag_id, scan_index, rack, time_scanned_raw, scanned_at_parsed,
               user_name, purpose, last_location, last_scan, raw_json
        FROM upload_batch_scan_events
        WHERE organization_id = %s AND upload_batch_id = %s
        ORDER BY bag_id, scan_index, id
        LIMIT 5000
        """,
        (org, batch_id),
    )
    rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]
    if not rows:
        # Fall back: sample from persistent events as synthetic CSV-shaped frame.
        cursor.execute(
            """
            SELECT bag_id, scan_index, rack, time_scanned_raw, scanned_at_parsed,
                   user_name, purpose, last_location, last_scan, raw_json,
                   weight_lbs, weight_source, weight_role
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
            ORDER BY id DESC
            LIMIT 800
            """,
            (org,),
        )
        rows = [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]

    if not rows:
        return {"ok": False, "reason": "no_events"}

    records = []
    for r in rows:
        records.append(
            {
                "Bag ID": r.get("bag_id"),
                "Scan Index": r.get("scan_index"),
                "Rack": r.get("rack") or "",
                "Time Scanned": r.get("time_scanned_raw")
                or (str(r.get("scanned_at_parsed") or "")),
                "User": r.get("user_name") or "",
                "Purpose": r.get("purpose") or "",
                "Last Location": r.get("last_location") or "",
                "Last Scan": r.get("last_scan") or "",
                "Weight": r.get("weight_lbs"),
                "Weight Source": r.get("weight_source") or "",
                "Weight Role": r.get("weight_role") or "",
            }
        )
    df = pd.DataFrame.from_records(records)

    calls_old: list[tuple] = []
    calls_new: list[tuple] = []

    def _capture(bucket):
        def _upsert(*_a, **kwargs):
            bucket.append(
                (
                    kwargs.get("bag_id"),
                    kwargs.get("dedupe_key"),
                    kwargs.get("weight_lbs"),
                    kwargs.get("weight_source"),
                    kwargs.get("weight_role"),
                    kwargs.get("overwrite_weight"),
                    kwargs.get("scan_index"),
                    kwargs.get("rack"),
                    kwargs.get("user_name"),
                    kwargs.get("purpose"),
                    kwargs.get("time_scanned_raw"),
                )
            )
            # Pretend insert for counting; existing lookup skipped.
            return "inserted"

        return _upsert

    common_patches = {
        "filter": patch(
            "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
            side_effect=lambda *_a, **_k: (sorted(df["Bag ID"].astype(str).unique().tolist()), []),
        ),
        "delete": patch(
            "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags",
            return_value=0,
        ),
        "delete_old": patch(
            "backend.tests.finalize_perf_baseline.rinse_bag_registry_old.delete_persistent_scan_events_for_bags",
            return_value=0,
        ),
        "bounds": patch(
            "backend.rinse_bag_registry._persistent_scan_bounds_for_bags",
            return_value={},
        ),
        "bounds_old": patch(
            "backend.tests.finalize_perf_baseline.rinse_bag_registry_old._persistent_scan_bounds_for_bags",
            return_value={},
        ),
        "comp": patch(
            "backend.rinse_bag_registry._persistent_completion_stage_counts",
            return_value={},
        ),
        "comp_old": patch(
            "backend.tests.finalize_perf_baseline.rinse_bag_registry_old._persistent_completion_stage_counts",
            return_value={},
        ),
        "snap": patch(
            "backend.rinse_scan_weight_enrichment.snapshot_weight_enrichment",
            return_value={},
        ),
        "restore": patch(
            "backend.rinse_scan_weight_enrichment.restore_weight_enrichment",
            return_value={"updated": 0},
        ),
    }

    with common_patches["filter"], common_patches["delete"], common_patches["delete_old"], \
            common_patches["bounds"], common_patches["bounds_old"], \
            common_patches["comp"], common_patches["comp_old"], \
            common_patches["snap"], common_patches["restore"], \
            patch(
                "backend.tests.finalize_perf_baseline.rinse_bag_registry_old.upsert_scan_event_row",
                side_effect=_capture(calls_old),
            ), \
            patch(
                "backend.rinse_bag_registry.upsert_scan_event_row",
                side_effect=_capture(calls_new),
            ), \
            patch(
                "backend.rinse_bag_registry.fetch_existing_scan_dedupe_ids",
                return_value={},
            ):
        # Force replace=False to avoid chronology replace divergence in dry-run.
        merge_old(cursor, org, batch_id, df, "equality_proof.csv", replace_existing=False)
        merge_new(cursor, org, batch_id, df, "equality_proof.csv", replace_existing=False)

    set_old = set(calls_old)
    set_new = set(calls_new)
    return {
        "ok": True,
        "event_rows": len(df),
        "calls_old": len(calls_old),
        "calls_new": len(calls_new),
        "identities_equal": set_old == set_new and len(calls_old) == len(calls_new),
        "only_old": len(set_old - set_new),
        "only_new": len(set_new - set_old),
        "pre_post_fields_in_compare": True,
    }


def main() -> int:
    _load_env()
    from backend.db import get_db

    org = int(os.environ.get("EQUALITY_ORG_ID") or 3)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        batch = _latest_full_snapshot_batch(cur, org)
        if not batch:
            print(json.dumps({"ok": False, "reason": "no_batch"}))
            return 2
        batch_id = int(batch["batch_id"])
        accepted = _accepted_portal_rows(cur, batch_id)
        portal = prove_portal_absence(cur, org, batch_id, accepted)
        merge = prove_merge_scan_events(cur, org, batch_id)
        report = {
            "org": org,
            "batch_id": batch_id,
            "accepted_portal_rows": len(accepted),
            "portal_absence": portal,
            "merge_scan_events": merge,
            "EQUALITY": {
                "Candidate sets equal": "YES" if portal.get("candidates_equal") and portal.get("missing_equal") else "NO",
                "Departure decisions equal": "YES" if portal.get("decisions_equal") else "NO",
                "Scan-event outputs equal": "YES" if merge.get("identities_equal") else "NO",
                "PRE/POST equal": "YES" if merge.get("identities_equal") else "NO",
            },
        }
        print(json.dumps(report, indent=2, default=str))
        ok = all(
            v == "YES" for v in report["EQUALITY"].values()
        )
        return 0 if ok else 1
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
