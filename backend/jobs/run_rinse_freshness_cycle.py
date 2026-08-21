"""One freshness cycle child (fast | rolling | deep).

Invoked only by the supervisor. Never starts a successor.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _progress(msg: str) -> None:
    print(msg, flush=True)


def run_fast_cycle(conn, organization_id: int) -> dict[str, Any]:
    from backend.business_time import business_today
    from backend.rinse_freshness_portal_boundary import (
        load_known_fingerprints_from_presence,
        write_fingerprint_seed,
    )
    from backend.rinse_freshness_publish import (
        begin_snapshot_build,
        latest_published_snapshot,
        mark_snapshot_failed,
        publish_snapshot,
    )
    from backend.rinse_freshness_store import (
        LaneFencedError,
        assert_lane_writable,
        finish_cycle,
        insert_cycle,
        release_lane_lease_if_owner,
        take_lane_lease,
        touch_cycle_progress,
        touch_lane_lease,
        upsert_watermarks,
    )
    from backend.rinse_scheduled_scrape import run_rinse_combined_sync_for_org
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    org = int(organization_id)
    cursor = conn.cursor(dictionary=True, buffered=True)
    cycle_id = insert_cycle(cursor, organization_id=org, lane="fast")
    conn.commit()
    gen = take_lane_lease(cursor, org, "fast", cycle_id=cycle_id)
    conn.commit()
    started = _utcnow()
    result: dict[str, Any] = {
        "lane": "fast",
        "cycle_id": cycle_id,
        "lease_generation": gen,
        "cycle_status": "FAILED",
    }
    t0 = time.monotonic()
    portal_s = import_s = projection_s = publish_s = 0
    batch_id = None
    scrape_run_id = None
    source_complete = False
    affected_bags: list[str] = []
    affected_dates: list[str] = []

    try:
        # Seed fingerprints for portal early-stop (Node scraper reads this file).
        fps = load_known_fingerprints_from_presence(cursor, org)
        seed_path = Path(tempfile.gettempdir()) / f"rinse_fp_org_{org}.json"
        write_fingerprint_seed(str(seed_path), fps)
        os.environ["RINSE_FINGERPRINT_SEED"] = str(seed_path)
        # Fast path page budget is a latency safeguard; incomplete ⇒ rolling/deep.
        # Force (do not setdefault) so ACA/tenant defaults cannot keep 500 pages.
        budget = os.getenv("RINSE_FAST_PAGE_BUDGET", "2")
        os.environ["RINSE_MAX_PAGES"] = str(budget)
        os.environ.setdefault("RINSE_EARLY_STOP_UNCHANGED_PAGES", "2")
        os.environ["RINSE_PORTAL_EARLY_STOP"] = "1"
        # Prefer delta finalize when bags are known after scrape.
        os.environ["RINSE_FRESHNESS_DELTA_FINALIZE"] = "1"

        touch_cycle_progress(cursor, cycle_id, stage="portal_scrape", meaningful=True)
        touch_lane_lease(cursor, org, "fast", gen, stage="portal_scrape", meaningful=True)
        conn.commit()
        _progress(f"freshness cycle {cycle_id} portal_scrape start")

        t_portal = time.monotonic()
        scrape = run_rinse_combined_sync_for_org(
            conn,
            org,
            run_type="scheduled",
            dry_run=False,
        )
        portal_s = int(time.monotonic() - t_portal)
        import_s = portal_s  # combined sync includes import; refined below if detail present
        scrape_run_id = getattr(scrape, "run_id", None)
        batch_id = getattr(scrape, "batch_id", None)
        detail = getattr(scrape, "detail", None) or {}
        stopped_reason = None
        portal_pages = None
        portal_rows = int(getattr(scrape, "portal_rows_count", 0) or 0)
        finalize_s = None
        if isinstance(detail, dict):
            meta = (
                (detail.get("portal_scrape_meta") if isinstance(detail.get("portal_scrape_meta"), dict) else None)
                or ((detail.get("draft") or {}).get("portal_scrape_meta") if isinstance(detail.get("draft"), dict) else None)
                or {}
            )
            if isinstance(meta, dict) and meta:
                stopped_reason = meta.get("stopped_reason") or meta.get("stop_reason")
                portal_pages = meta.get("pages_scraped") or meta.get("max_pages_limit")
                if meta.get("row_count") is not None:
                    portal_rows = int(meta.get("row_count") or portal_rows)
                source_complete = bool(meta.get("source_inspected_complete"))
                if stopped_reason == "safe_unchanged_boundary":
                    source_complete = True
                # Page budget / max pages = incomplete (rolling/deep must cover).
                if stopped_reason in (
                    "page_budget",
                    "max_pages_reached",
                ) or bool(meta.get("reached_max_pages")):
                    source_complete = False
                    if not stopped_reason:
                        stopped_reason = "max_pages_reached"
            # affected bags from finalize / merge
            fin = None
            confirm = detail.get("confirm") if isinstance(detail.get("confirm"), dict) else {}
            if isinstance(confirm, dict):
                fin = confirm.get("rinse_finalize")
            if isinstance(fin, dict):
                affected_bags = list(fin.get("bag_ids") or fin.get("merge_bag_ids") or [])
                # Prefer explicit finalize timing if present
                if fin.get("finalize_seconds") is not None:
                    finalize_s = int(fin.get("finalize_seconds") or 0)
            sync = detail.get("sync_cycle") if isinstance(detail.get("sync_cycle"), dict) else {}
            life = detail.get("ingestion_lifecycle") if isinstance(detail.get("ingestion_lifecycle"), dict) else {}

        status = str(getattr(scrape, "status", "") or "")
        result.update(
            {
                "stopped_reason": stopped_reason,
                "portal_pages": portal_pages,
                "portal_rows": portal_rows,
                "finalize_seconds": finalize_s,
                "source_inspected_complete": source_complete,
            }
        )
        touch_cycle_progress(
            cursor,
            cycle_id,
            stage="imported",
            meaningful=True,
            extra={
                "portal_seconds": portal_s,
                "import_seconds": import_s,
                "portal_pages": portal_pages,
                "portal_rows": portal_rows,
                "batch_id": batch_id,
                "scrape_run_id": scrape_run_id,
                "source_inspected_complete": 1 if source_complete else 0,
                "bags_affected": len(affected_bags),
            },
        )
        touch_lane_lease(cursor, org, "fast", gen, stage="imported", meaningful=True)
        conn.commit()

        upsert_watermarks(
            cursor,
            org,
            source_inspected_through=_utcnow(),
            source_inspected_complete=1 if source_complete else 0,
            raw_imported_through=_utcnow() if batch_id else None,
            last_fast_cycle_id=cycle_id,
        )
        # Canonical watermark advances only after in-lock finalize (not mere import).
        fin = None
        if isinstance(detail, dict):
            confirm = detail.get("confirm") if isinstance(detail.get("confirm"), dict) else {}
            fin = (confirm or {}).get("rinse_finalize") if isinstance(confirm, dict) else None
            if not isinstance(fin, dict):
                fin = detail.get("rinse_finalize")
        if isinstance(fin, dict) and not fin.get("deferred"):
            upsert_watermarks(cursor, org, canonical_processed_through=_utcnow())
        conn.commit()

        if status not in ("success", "needs_attention", "partial_success"):
            result["cycle_status"] = "FAILED"
            result["error_message"] = getattr(scrape, "error_message", None) or status
            finish_cycle(
                cursor,
                cycle_id,
                cycle_status="FAILED",
                error_message=result["error_message"],
                result_json=result,
                started_at=started,
            )
            conn.commit()
            return result

        # Fast lane = change capture (not full day rebuild / absence inference).
        # last-good membership + additive delta → chronology reproject → publish.
        day = business_today()
        affected_dates = [day.isoformat()]
        if not affected_bags and batch_id:
            try:
                cursor.execute(
                    """
                    SELECT DISTINCT ticket_id
                    FROM upload_batch_rows
                    WHERE upload_batch_id = %s
                      AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
                    """,
                    (int(batch_id),),
                )
                affected_bags = [
                    str(r.get("ticket_id") or "").strip()
                    for r in (cursor.fetchall() or [])
                    if str(r.get("ticket_id") or "").strip()
                ]
            except Exception:
                affected_bags = list(affected_bags or [])

        touch_cycle_progress(cursor, cycle_id, stage="projection", meaningful=True)
        touch_lane_lease(cursor, org, "fast", gen, stage="projection", meaningful=True)
        conn.commit()
        assert_lane_writable(cursor, org, "fast", gen)

        from backend.rinse_freshness_incremental import incremental_project_and_publish

        t_proj = time.monotonic()
        inc = incremental_project_and_publish(
            cursor,
            organization_id=org,
            shift_date_et=day,
            affected_bag_ids=affected_bags,
            cycle_id=cycle_id,
            lease_generation=gen,
            lane="fast",
            batch_id=int(batch_id) if batch_id else None,
            source_inspected_complete=bool(source_complete),
            workload_meta_extra={
                "stopped_reason": stopped_reason,
                "portal_pages": portal_pages,
                "portal_rows": portal_rows,
                "scrape_run_id": scrape_run_id,
            },
        )
        conn.commit()
        projection_s = int(time.monotonic() - t_proj)
        publish_s = projection_s
        published = bool(inc.get("published"))
        ver = inc.get("snapshot_version")
        if published:
            result["cycle_status"] = "SUCCESS"
            result["error_message"] = None
        else:
            result["cycle_status"] = "DEGRADED" if not inc.get("fenced") else "FAILED"
            result["error_message"] = str(
                inc.get("reason") or "incremental_publish_failed"
            )

        result.update(
            {
                "portal_seconds": portal_s,
                "import_seconds": import_s,
                "projection_seconds": projection_s,
                "publish_seconds": publish_s,
                "batch_id": batch_id,
                "scrape_run_id": scrape_run_id,
                "source_inspected_complete": source_complete,
                "bags_affected": len(affected_bags),
                "dates_affected": affected_dates,
                "published": published,
                "snapshot_version": ver,
                "incremental": inc,
                "prior_published": bool(latest_published_snapshot(cursor, org, day)),
            }
        )
        if result["cycle_status"] == "SUCCESS":
            upsert_watermarks(cursor, org, last_fast_result="SUCCESS")
        elif result["cycle_status"] == "DEGRADED":
            upsert_watermarks(cursor, org, last_fast_result="DEGRADED")
        finish_cycle(
            cursor,
            cycle_id,
            cycle_status=result["cycle_status"],
            error_message=result.get("error_message"),
            result_json=result,
            started_at=started,
        )
        touch_cycle_progress(
            cursor,
            cycle_id,
            stage="done",
            meaningful=True,
            extra={
                "portal_seconds": portal_s,
                "projection_seconds": projection_s,
                "publish_seconds": publish_s,
                "published": 1 if published else 0,
                "bags_affected": len(affected_bags),
                "dates_affected": affected_dates,
            },
        )
        conn.commit()
        return result
    except Exception as exc:
        result["cycle_status"] = "FAILED"
        result["error_message"] = str(exc)
        try:
            finish_cycle(
                cursor,
                cycle_id,
                cycle_status="FAILED",
                error_message=str(exc),
                result_json=result,
                started_at=started,
            )
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        try:
            release_lane_lease_if_owner(cursor, org, "fast", gen)
            conn.commit()
        except Exception:
            pass
        try:
            cursor.close()
        except Exception:
            pass


def run_reconcile_cycle(conn, organization_id: int, *, kind: str) -> dict[str, Any]:
    """Rolling/deep reconciliation child — measures gaps and backfills idempotently."""
    from backend.rinse_freshness_portal_boundary import (
        load_known_fingerprints_from_presence,
        normalize_bag_id,
    )
    from backend.rinse_freshness_store import (
        ensure_freshness_tables,
        finish_cycle,
        insert_cycle,
        release_lane_lease_if_owner,
        take_lane_lease,
        upsert_watermarks,
    )

    org = int(organization_id)
    lane = "rolling" if kind == "rolling" else "deep"
    cursor = conn.cursor(dictionary=True, buffered=True)
    ensure_freshness_tables(cursor)
    cycle_id = insert_cycle(cursor, organization_id=org, lane=lane)
    conn.commit()
    gen = take_lane_lease(cursor, org, lane, cycle_id=cycle_id)
    conn.commit()
    started = _utcnow()
    stats = {
        "source_inspected": 0,
        "already_identical": 0,
        "changed": 0,
        "missing_in_db": 0,
        "backfilled": 0,
        "unresolved": 0,
        "duplicates_prevented": 0,
    }
    try:
        before_fps = load_known_fingerprints_from_presence(cursor, org)
        if kind == "deep":
            os.environ["RINSE_MAX_PAGES"] = os.getenv("RINSE_DEEP_PAGE_BUDGET", "20")
            os.environ["RINSE_PORTAL_EARLY_STOP"] = "0"
        else:
            os.environ["RINSE_MAX_PAGES"] = os.getenv("RINSE_ROLLING_PAGE_BUDGET", "8")
            os.environ["RINSE_PORTAL_EARLY_STOP"] = "1"
            os.environ.setdefault("RINSE_EARLY_STOP_UNCHANGED_PAGES", "3")

        from backend.rinse_scheduled_scrape import run_rinse_combined_sync_for_org

        scrape = run_rinse_combined_sync_for_org(conn, org, run_type="scheduled", dry_run=False)
        status = str(getattr(scrape, "status", "") or "")
        detail = getattr(scrape, "detail", None) or {}
        draft = detail.get("draft") if isinstance(detail, dict) else {}
        draft_bags = []
        if isinstance(draft, dict):
            draft_bags = list(draft.get("draft_bag_ids") or [])
        stats["source_inspected"] = int(
            getattr(scrape, "portal_rows_count", 0) or len(draft_bags) or 0
        )

        # Measurable gap accounting vs pre-scrape presence fingerprints.
        after_fps = load_known_fingerprints_from_presence(cursor, org)
        for bid in draft_bags:
            nb = normalize_bag_id({"bag_id": bid})
            if not nb:
                continue
            if nb not in before_fps:
                stats["missing_in_db"] += 1
                if nb in after_fps:
                    stats["backfilled"] += 1
                else:
                    stats["unresolved"] += 1
            elif before_fps.get(nb) != after_fps.get(nb):
                stats["changed"] += 1
            else:
                stats["already_identical"] += 1
        # Idempotent re-import of known bags counts as duplicate-prevented when unchanged.
        if status in ("success", "needs_attention", "partial_success"):
            stats["duplicates_prevented"] = int(stats["already_identical"])
            if kind == "rolling":
                upsert_watermarks(cursor, org, last_rolling_reconciliation=_utcnow())
            else:
                upsert_watermarks(cursor, org, last_deep_reconciliation=_utcnow())
            cursor.execute(
                """
                INSERT INTO rinse_reconcile_runs (
                  organization_id, reconcile_kind, started_at, finished_at, status,
                  source_inspected, already_identical, changed, missing_in_db,
                  backfilled, unresolved, duplicates_prevented, result_json
                ) VALUES (%s,%s,%s,UTC_TIMESTAMP(6),'SUCCESS',%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    org,
                    kind,
                    started,
                    stats["source_inspected"],
                    stats["already_identical"],
                    stats["changed"],
                    stats["missing_in_db"],
                    stats["backfilled"],
                    stats["unresolved"],
                    stats["duplicates_prevented"],
                    json.dumps(
                        {
                            "scrape_status": status,
                            "batch_id": getattr(scrape, "batch_id", None),
                            "fast_path_missed": stats["missing_in_db"],
                            "reconciled": stats["backfilled"],
                            "unresolved": stats["unresolved"],
                        }
                    ),
                ),
            )
            finish_cycle(
                cursor,
                cycle_id,
                cycle_status="SUCCESS",
                result_json={"lane": lane, "stats": stats},
                started_at=started,
            )
            conn.commit()
            return {"cycle_status": "SUCCESS", "stats": stats}
        finish_cycle(
            cursor,
            cycle_id,
            cycle_status="FAILED",
            error_message=getattr(scrape, "error_message", None) or status,
            result_json={"lane": lane, "stats": stats},
            started_at=started,
        )
        conn.commit()
        return {"cycle_status": "FAILED", "stats": stats}
    finally:
        try:
            release_lane_lease_if_owner(cursor, org, lane, gen)
            conn.commit()
        except Exception:
            pass
        try:
            cursor.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rinse freshness cycle child")
    p.add_argument("--organization-id", type=int, required=True)
    p.add_argument("--lane", choices=("fast", "rolling", "deep"), default="fast")
    args = p.parse_args(argv)

    from backend.db import get_db

    conn = get_db()
    try:
        if args.lane == "fast":
            out = run_fast_cycle(conn, args.organization_id)
        else:
            out = run_reconcile_cycle(conn, args.organization_id, kind=args.lane)
        print(json.dumps({"freshness_cycle": out}, default=str), flush=True)
        status = str(out.get("cycle_status") or "")
        if status == "SUCCESS":
            return 0
        if status == "DEGRADED":
            return 2
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
