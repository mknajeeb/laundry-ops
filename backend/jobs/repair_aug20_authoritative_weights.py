#!/usr/bin/env python3
"""Non-destructive Aug 20 authoritative PRE/POST repair (org 3).

1) Targeted ?q= scrape for WF day bags
2) Import missing chronology + enrich authoritative weights on weigh-entries
3) Reproject day_bags from resolver (frozen membership)
4) Republish Management snapshot for the day

Usage:
  /path/to/venv/bin/python -m backend.jobs.repair_aug20_authoritative_weights
  DRY_RUN=1 ...  # scrape+report only
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _connect():
    import mysql.connector

    env: dict[str, str] = {}
    for line in Path("/Users/kamisb./laundry_app/.env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    # Scrape/vendor routing needs RINSE_* in process env (org 3 → veewash).
    for k, v in env.items():
        if k.startswith("RINSE_") or k.startswith("MYSQL_"):
            os.environ.setdefault(k, v)
    return mysql.connector.connect(
        host=env["MYSQL_HOST"],
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        port=int(env.get("MYSQL_PORT") or 3306),
        connection_timeout=60,
    )


def _day_bag_vs_resolver(cursor, org: int, day: date) -> dict:
    from backend.rinse_current_cycle_weight import resolve_current_cycle_weights

    cursor.execute(
        """
        SELECT bag_id, pre_weight_lbs, post_weight_lbs
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND UPPER(COALESCE(service_type,''))='WF'
        """,
        (org, day),
    )
    bags = cursor.fetchall() or []
    mism = []
    agree = 0
    for r in bags:
        bid = r["bag_id"]
        cursor.execute(
            """
            SELECT id, purpose, scanned_at_parsed AS scanned_at, user_name, rack,
                   weight_lbs, weight_role, weight_source, weight_observed_at,
                   weight_attach_reason, weight_presence_run_id
            FROM rinse_bag_scan_events
            WHERE organization_id=%s AND bag_id=%s
            ORDER BY scanned_at_parsed, id
            """,
            (org, bid),
        )
        timeline = cursor.fetchall() or []
        info = resolve_current_cycle_weights(
            timeline, selected_date_et=day, allow_portal_weight_fallback=False
        ).as_weight_info()

        def eq(a, b):
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            return abs(float(a) - float(b)) < 0.05

        mp = float(r["pre_weight_lbs"]) if r["pre_weight_lbs"] is not None else None
        mpo = float(r["post_weight_lbs"]) if r["post_weight_lbs"] is not None else None
        if eq(mp, info.get("pre_weight_lbs")) and eq(mpo, info.get("post_weight_lbs")):
            agree += 1
        else:
            mism.append(
                {
                    "bag_id": bid,
                    "mgmt_pre": mp,
                    "res_pre": info.get("pre_weight_lbs"),
                    "mgmt_post": mpo,
                    "res_post": info.get("post_weight_lbs"),
                    "pre_src": info.get("pre_weight_source"),
                    "post_src": info.get("post_weight_source"),
                }
            )
    return {"total": len(bags), "agree": agree, "mismatch": len(mism), "mismatches": mism}


def _proxy_counts(cursor, org: int, day: date) -> dict:
    cursor.execute(
        """
        SELECT bag_id FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND UPPER(COALESCE(service_type,''))='WF'
        """,
        (org, day),
    )
    bag_ids = [r["bag_id"] for r in (cursor.fetchall() or [])]
    proxy_pre = proxy_post = auth_pre = auth_post = unavail_pre = unavail_post = 0
    for bid in bag_ids:
        cursor.execute(
            """
            SELECT weight_lbs, weight_role, weight_source, purpose, scanned_at_parsed
            FROM rinse_bag_scan_events
            WHERE organization_id=%s AND bag_id=%s AND purpose LIKE 'weight-entry%%'
              AND scanned_at_parsed >= %s AND scanned_at_parsed < DATE_ADD(%s, INTERVAL 1 DAY)
            ORDER BY scanned_at_parsed, id
            """,
            (org, bid, day.isoformat(), day.isoformat()),
        )
        wes = cursor.fetchall() or []
        pre = next((e for e in wes if e.get("weight_role") == "PRE"), wes[0] if wes else None)
        post = next((e for e in wes if e.get("weight_role") == "POST"), None)
        if len(wes) >= 2 and post is None:
            post = wes[-1] if wes[-1] is not pre else None

        def classify(ev, role):
            nonlocal proxy_pre, proxy_post, auth_pre, auth_post, unavail_pre, unavail_post
            if ev is None or ev.get("weight_lbs") is None:
                if role == "PRE":
                    unavail_pre += 1
                else:
                    unavail_post += 1
                return
            src = str(ev.get("weight_source") or "")
            if src.startswith("rinse_"):
                if role == "PRE":
                    auth_pre += 1
                else:
                    auth_post += 1
            elif "portal" in src or "presence_run" in src:
                if role == "PRE":
                    proxy_pre += 1
                else:
                    proxy_post += 1
            else:
                if role == "PRE":
                    unavail_pre += 1
                else:
                    unavail_post += 1

        classify(pre, "PRE")
        if post is not None:
            classify(post, "POST")
        else:
            unavail_post += 1
    return {
        "authoritative_pre": auth_pre,
        "authoritative_post": auth_post,
        "proxy_pre": proxy_pre,
        "proxy_post": proxy_post,
        "unavailable_pre": unavail_pre,
        "unavailable_post": unavail_post,
        "bags": len(bag_ids),
    }


def main() -> int:
    org = int(os.getenv("ORG_ID", "3"))
    day = date.fromisoformat(os.getenv("SHIFT_DATE_ET", "2026-08-20"))
    dry = str(os.getenv("DRY_RUN", "") or "").strip().lower() in ("1", "true", "yes")
    max_bags = int(os.getenv("MAX_BAGS", "120") or 120)
    skip_before = str(os.getenv("SKIP_BEFORE_AUDIT", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    def log(msg: str) -> None:
        print(msg, flush=True)

    from backend.rinse_off_portal_scan_refresh import (
        get_latest_successful_crawl_batch_id,
        refresh_off_portal_pending_scans,
    )
    from backend.rinse_veewash_shift_day import reproject_day_bag_completions_from_chronology
    from backend.rinse_freshness_publish import begin_snapshot_build, publish_snapshot
    from backend.management_today import load_wf_day_weight_totals

    log("connecting…")
    cnx = _connect()
    cur = cnx.cursor(dictionary=True)
    log("connected")

    before_mism = {"mismatch": None, "mismatches": []}
    before_proxy = {}
    if not skip_before:
        log("=== BEFORE ===")
        before_mism = _day_bag_vs_resolver(cur, org, day)
        before_proxy = _proxy_counts(cur, org, day)
        log(f"mismatches {before_mism['mismatch']} proxy {before_proxy}")
    else:
        log("=== BEFORE skipped (SKIP_BEFORE_AUDIT=1) ===")

    cur.execute(
        """
        SELECT bag_id FROM rinse_shift_monitor_day_bags
        WHERE organization_id=%s AND shift_date_et=%s AND UPPER(COALESCE(service_type,''))='WF'
        ORDER BY bag_id
        """,
        (org, day),
    )
    bag_ids = [r["bag_id"] for r in (cur.fetchall() or [])]
    env_bags = [
        b.strip().upper()
        for b in str(os.getenv("BAG_IDS", "") or "").replace(",", " ").split()
        if b.strip()
    ]
    if env_bags:
        bag_ids = [b for b in bag_ids if b in set(env_bags)] or env_bags
    bag_ids = bag_ids[:max_bags]
    log(f"targeted bags: {len(bag_ids)}")

    batch_id = get_latest_successful_crawl_batch_id(cur, org)
    if batch_id is None:
        log("ERROR: no successful crawl batch for import lineage")
        return 2
    log(f"upload_batch_id {batch_id}")

    refresh = refresh_off_portal_pending_scans(
        cur,
        org,
        upload_batch_id=batch_id,
        selected_date_et=day,
        bag_ids=bag_ids,
        dry_run=dry,
        max_bags=max_bags,
        target_scope="authoritative_weight_repair",
        log_fn=log,
        timeout_sec=int(os.getenv("TIMEOUT_SEC", "7200") or 7200),
    )
    print(
        "refresh",
        {
            k: refresh.get(k)
            for k in (
                "bags_processed",
                "events_inserted",
                "lookup_failed",
                "dry_run",
            )
        },
    )
    auth_enriched = sum(int(b.get("authoritative_weight_enriched") or 0) for b in (refresh.get("bags") or []))
    print("authoritative_weight_enriched_events", auth_enriched)

    if dry:
        print("DRY_RUN — skip reproject/publish")
        cnx.rollback()
        return 0

    cnx.commit()

    print("=== REPROJECT DAY BAGS ===")
    proj = reproject_day_bag_completions_from_chronology(cur, org, day, chronology_complete=True)
    print(proj)
    cnx.commit()

    print("=== PUBLISH SNAPSHOT ===")
    totals = load_wf_day_weight_totals(cur, org, day)
    headline = {
        "shift_date_et": day.isoformat(),
        "weights": totals,
        "repair": "authoritative_pre_post_weights",
    }
    try:
        from backend.rinse_freshness_store import (
            ensure_freshness_tables,
            insert_cycle,
            take_lane_lease,
            release_lane_lease_if_owner,
            finish_cycle,
        )

        ensure_freshness_tables(cur)
        cnx.commit()
        lane = "deep"
        cycle_id = insert_cycle(cur, organization_id=org, lane=lane)
        cnx.commit()
        gen = take_lane_lease(cur, org, lane, cycle_id=int(cycle_id))
        cnx.commit()
        version = begin_snapshot_build(
            cur,
            organization_id=org,
            shift_date_et=day,
            cycle_id=int(cycle_id),
            lease_generation=int(gen),
        )
        publish_snapshot(
            cur,
            organization_id=org,
            shift_date_et=day,
            version=int(version),
            lease_generation=int(gen),
            lane=lane,
            headline=headline,
            workload_meta={
                "source": "authoritative_weight_repair",
                "bag_count": len(bag_ids),
            },
        )
        finish_cycle(cur, int(cycle_id), cycle_status="SUCCESS")
        release_lane_lease_if_owner(cur, org, lane, int(gen))
        cnx.commit()
        print("published version", version, "cycle", cycle_id, "gen", gen)
    except Exception as exc:
        print("publish_snapshot failed (day_bags still updated):", exc)
        try:
            cnx.rollback()
        except Exception:
            pass

    print("=== AFTER ===")
    after_mism = _day_bag_vs_resolver(cur, org, day)
    after_proxy = _proxy_counts(cur, org, day)
    after_totals = load_wf_day_weight_totals(cur, org, day)
    print("mismatches", after_mism["mismatch"], "proxy", after_proxy)
    print("totals", after_totals.get("by_rush", {}).get("all") or after_totals)

    # 10-bag proof
    proof_ids = [
        "32GSYJK2BA",
        "1D4JXZOAY5",
        "6KXB7FH5AV",
        "A239LN0J7E",
        "2TE5LH5FGY",
        "8WTJ8DBOAB",
        "58ZZ0QS9OF",
        "7FL9CATKUV",
        "2LI902AJM1",
        "5T65AVO8G9",
    ]
    from backend.rinse_current_cycle_weight import resolve_current_cycle_weights

    print("\nBag|MgmtPRE|MgmtPOST|ResPRE|ResPOST|pre_src|post_src")
    for bid in proof_ids:
        cur.execute(
            """
            SELECT pre_weight_lbs, post_weight_lbs FROM rinse_shift_monitor_day_bags
            WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
            """,
            (org, day, bid),
        )
        db = cur.fetchone() or {}
        cur.execute(
            """
            SELECT id, purpose, scanned_at_parsed AS scanned_at, user_name, rack,
                   weight_lbs, weight_role, weight_source, weight_observed_at,
                   weight_attach_reason, weight_presence_run_id
            FROM rinse_bag_scan_events WHERE organization_id=%s AND bag_id=%s
            ORDER BY scanned_at_parsed, id
            """,
            (org, bid),
        )
        info = resolve_current_cycle_weights(
            cur.fetchall() or [], selected_date_et=day, allow_portal_weight_fallback=False
        ).as_weight_info()
        print(
            f"{bid}|{db.get('pre_weight_lbs')}|{db.get('post_weight_lbs')}|"
            f"{info.get('pre_weight_lbs')}|{info.get('post_weight_lbs')}|"
            f"{info.get('pre_weight_source')}|{info.get('post_weight_source')}"
        )

    out = {
        "before_mismatches": before_mism["mismatch"],
        "after_mismatches": after_mism["mismatch"],
        "before_proxy": before_proxy,
        "after_proxy": after_proxy,
        "refresh": {
            "events_inserted": refresh.get("events_inserted"),
            "bags_processed": refresh.get("bags_processed"),
            "authoritative_weight_enriched": auth_enriched,
        },
        "reproject": proj,
        "mismatches_after": after_mism["mismatches"][:20],
    }
    Path("/tmp/aug20_authoritative_weight_repair.json").write_text(json.dumps(out, default=str, indent=2))
    print("wrote /tmp/aug20_authoritative_weight_repair.json")
    cnx.close()
    return 0 if after_mism["mismatch"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
