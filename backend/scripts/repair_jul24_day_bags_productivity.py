#!/usr/bin/env python3
"""Historical repair: restore org-3 2026-07-24 day bags wiped by bad Close.

Jul 24 headline_json is intact (WF 74 completed IDs match freeze fixture).
Only rinse_shift_monitor_day_bags was reduced to 21 HD review rows.

Strategy (Jul 24 only; no Jul 25 portal membership):
  1. Rebuild WF day-bag rows from Jul 24 same-day scrape membership + scans.
  2. Keep/restore HD rows from the immutable headline bag_ids + surviving
     day-bag snapshots / registry / edits (do not run live HD membership).
  3. Leave headline_json unchanged.
  4. Caller may reopen + freeze-close after validation.

Usage:
  python -m backend.scripts.repair_jul24_day_bags_productivity --dry-run
  python -m backend.scripts.repair_jul24_day_bags_productivity --apply
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import mysql.connector

ORG = 3
DAY = date(2026, 7, 24)
FREEZE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "wf_productivity_freeze_jul24_org3.json"
)
OUT_DIR = Path(__file__).resolve().parents[2] / "data"


def _load_env() -> None:
    for env_path in (
        Path("/Users/kamisb./laundry_app/.env"),
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _connect(*, autocommit: bool = False):
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        port=int(os.environ.get("MYSQL_PORT") or 3306),
        connection_timeout=40,
        autocommit=autocommit,
    )


def _json_load(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    if not v:
        return None
    return json.loads(v)


def _headline_bag_partitions(headline: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    segs = headline.get("segments") or {}
    out: dict[str, dict[str, list[str]]] = {}
    for svc in ("wf", "hd", "all"):
        bags = ((segs.get(svc) or {}).get("bag_ids") or {})
        out[svc] = {
            k: [str(x).strip().upper() for x in (bags.get(k) or []) if str(x).strip()]
            for k in (
                "new_today",
                "carryover",
                "completed",
                "pending",
                "review_required",
                "excluded",
            )
        }
    return out


def _build_wf_rows(cursor, organization_id: int, day: date) -> list[dict[str, Any]]:
    from backend.rinse_veewash_shift_day import _bag_rows_from_workload, _build_step1_workload_for_date
    from backend.rinse_veewash_workload import build_step1_headline_summary, get_step1_activation_date
    from backend.rinse_step1_productivity_fast import project_productivity_fields_for_day_bag

    wl = _build_step1_workload_for_date(cursor, organization_id, day)
    activation = get_step1_activation_date(cursor, organization_id) or day
    summary = build_step1_headline_summary(
        wl, selected_date_et=day, activation_date=activation
    )
    rows = _bag_rows_from_workload(wl, summary)
    out = []
    for b in rows:
        if str(b.get("service_type") or "").upper() != "WF":
            continue
        proj = project_productivity_fields_for_day_bag(b)
        row = dict(b)
        row.update(proj)
        out.append(row)
    return out


def _hydrate_hd_from_surviving(
    surviving: list[dict[str, Any]], hd_ids: set[str]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in surviving:
        bid = str(row.get("bag_id") or "").strip().upper()
        if bid in hd_ids:
            out[bid] = dict(row)
    return out


def _hd_row_stub(
    bag_id: str,
    *,
    effective_status: str,
    registry: dict[str, Any] | None,
    edit_after: dict[str, Any] | None,
) -> dict[str, Any]:
    reg = registry or {}
    edit = edit_after or {}
    emp = (
        edit.get("productivity_employee_name")
        or edit.get("canonical_completion_employee")
        or edit.get("completed_by")
        or reg.get("completed_by")
        or None
    )
    completed_at = (
        edit.get("productivity_completed_at")
        or edit.get("canonical_completion_timestamp")
        or edit.get("completion_at")
        or reg.get("completed_at")
    )
    snap = {
        "bag_id": bag_id,
        "service_type": "HD",
        "outcome": effective_status,
        "final_bucket": effective_status,
        "completed_by": emp,
        "completion_at": completed_at.isoformat(sep=" ")
        if hasattr(completed_at, "isoformat")
        else completed_at,
        "historical_restore": True,
        "restore_source": "headline_partition_plus_registry_edits",
    }
    credit = 1 if effective_status == "completed" and emp else 0
    return {
        "bag_id": bag_id,
        "service_type": "HD",
        "rush_status": None,
        "new_or_carryover": "workload",
        "workload_entry_type": None,
        "workload_entry_timestamp": None,
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "weight_lbs": None,
        "canonical_completion_status": reg.get("completion_status") or effective_status,
        "canonical_completion_timestamp": completed_at,
        "canonical_completion_employee": emp,
        "effective_status": effective_status,
        "review_reason_codes": ["HD_REVIEW_REQUIRED"]
        if effective_status == "review_required"
        else [],
        "portal_status_at_sync": None,
        "last_present_scrape": None,
        "first_confirmed_absent_scrape": None,
        "disposition": "COMPLETED" if effective_status == "completed" else None,
        "bag_snapshot": snap,
        "productivity_employee_name": emp if credit else None,
        "productivity_completed_at": completed_at if credit else None,
        "productivity_weight_lbs": 0.0 if credit and emp else None,
        "productivity_credit_eligible": credit,
        "productivity_exclusion_reason": None
        if credit
        else ("hd_not_credit_eligible" if effective_status != "completed" else "missing_employee"),
    }


def _load_registry(cursor, organization_id: int, bag_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not bag_ids:
        return {}
    ph = ",".join(["%s"] * len(bag_ids))
    cursor.execute(
        f"""
        SELECT bag_id, service_type, completion_status, completed_at, completion_reason
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id IN ({ph})
        """,
        (int(organization_id), *bag_ids),
    )
    return {str(r["bag_id"]).upper(): dict(r) for r in (cursor.fetchall() or [])}


def _load_latest_edits(cursor, organization_id: int, day: date, bag_ids: list[str]) -> dict[str, dict]:
    if not bag_ids:
        return {}
    ph = ",".join(["%s"] * len(bag_ids))
    cursor.execute(
        f"""
        SELECT bag_id, after_json, outcome_action, created_at
        FROM rinse_step1_bag_edits
        WHERE organization_id = %s AND shift_date_et = %s AND bag_id IN ({ph})
          AND COALESCE(is_undo, 0) = 0
        ORDER BY id DESC
        """,
        (int(organization_id), day, *bag_ids),
    )
    out: dict[str, dict] = {}
    for r in cursor.fetchall() or []:
        bid = str(r["bag_id"]).upper()
        if bid in out:
            continue
        after = _json_load(r.get("after_json")) or {}
        out[bid] = after if isinstance(after, dict) else {}
    return out


def build_restore_plan(cursor) -> dict[str, Any]:
    from backend.rinse_veewash_shift_day import get_day_record, load_day_bags
    from backend.rinse_bag_completion import normalize_bag_id

    freeze = json.loads(FREEZE_PATH.read_text())
    day_rec = get_day_record(cursor, ORG, DAY) or {}
    headline = day_rec.get("headline") or {}
    parts = _headline_bag_partitions(headline)
    surviving = load_day_bags(cursor, ORG, DAY)
    surv_ids = {normalize_bag_id(r.get("bag_id")) for r in surviving}

    wf_rows = _build_wf_rows(cursor, ORG, DAY)
    wf_by_id = {normalize_bag_id(r["bag_id"]): r for r in wf_rows}
    freeze_wf_completed = {
        normalize_bag_id(x) for x in freeze["wf"]["bag_ids"]["completed"]
    }
    headline_wf_completed = {normalize_bag_id(x) for x in parts["wf"]["completed"]}

    hd_completed = {normalize_bag_id(x) for x in parts["hd"]["completed"]}
    hd_pending = {normalize_bag_id(x) for x in parts["hd"]["pending"]}
    hd_review = {normalize_bag_id(x) for x in parts["hd"]["review_required"]}
    hd_ids = sorted(hd_completed | hd_pending | hd_review)
    hd_from_surv = _hydrate_hd_from_surviving(surviving, set(hd_ids))
    missing_hd = [b for b in hd_ids if b not in hd_from_surv]
    registry = _load_registry(cursor, ORG, missing_hd + sorted(hd_completed))
    edits = _load_latest_edits(cursor, ORG, DAY, missing_hd + sorted(hd_completed))

    hd_rows: dict[str, dict[str, Any]] = dict(hd_from_surv)
    unrecoverable: list[dict[str, Any]] = []
    for bid in hd_ids:
        if bid in hd_rows:
            # ensure status matches headline partition
            if bid in hd_completed:
                hd_rows[bid]["effective_status"] = "completed"
            elif bid in hd_pending:
                hd_rows[bid]["effective_status"] = "pending"
            else:
                hd_rows[bid]["effective_status"] = "review_required"
            continue
        if bid in hd_completed:
            status = "completed"
        elif bid in hd_pending:
            status = "pending"
        else:
            status = "review_required"
        stub = _hd_row_stub(
            bid,
            effective_status=status,
            registry=registry.get(bid),
            edit_after=edits.get(bid),
        )
        if status == "completed" and not stub.get("canonical_completion_employee"):
            # freeze says Jordan Graham / 0 lbs — use freeze attribution only when
            # registry completion exists for this bag on Jul 24.
            reg = registry.get(bid) or {}
            if reg.get("completion_status") == "COMPLETED" and reg.get("completed_at"):
                freeze_jordan = next(
                    (
                        e
                        for e in freeze["productivity_eligible"]["by_employee"]
                        if e["employee"] == "Jordan Graham"
                    ),
                    None,
                )
                if freeze_jordan and freeze_jordan["bags"] == 1:
                    stub["canonical_completion_employee"] = "Jordan Graham"
                    stub["productivity_employee_name"] = "Jordan Graham"
                    stub["productivity_credit_eligible"] = 1
                    stub["productivity_weight_lbs"] = 0.0
                    stub["productivity_completed_at"] = reg.get("completed_at")
                    stub["bag_snapshot"]["completed_by"] = "Jordan Graham"
                    stub["bag_snapshot"]["restore_note"] = (
                        "employee_from_freeze_fixture_single_hd_completed"
                    )
                else:
                    unrecoverable.append(
                        {"bag_id": bid, "reason": "hd_completed_missing_employee"}
                    )
            else:
                unrecoverable.append(
                    {"bag_id": bid, "reason": "hd_completed_missing_registry"}
                )
        hd_rows[bid] = stub

    # Final merged set: all WF rebuild rows that are in headline WF universe,
    # plus HD rows from headline partitions.
    headline_wf_universe = set(
        parts["wf"]["new_today"]
        + parts["wf"]["completed"]
        + parts["wf"]["pending"]
        + parts["wf"]["review_required"]
    )
    merged: dict[str, dict[str, Any]] = {}
    for bid, row in wf_by_id.items():
        if bid in headline_wf_universe or bid in freeze_wf_completed:
            merged[bid] = row
    for bid, row in hd_rows.items():
        merged[bid] = row

    credit = [
        r
        for r in merged.values()
        if int(r.get("productivity_credit_eligible") or 0) == 1
    ]
    by_emp: dict[str, dict[str, Any]] = defaultdict(lambda: {"bags": 0, "pre": 0.0})
    for r in credit:
        emp = str(
            r.get("productivity_employee_name")
            or r.get("canonical_completion_employee")
            or "Unknown"
        ).strip()
        by_emp[emp]["bags"] += 1
        if r.get("productivity_weight_lbs") is not None:
            by_emp[emp]["pre"] += float(r["productivity_weight_lbs"])

    wf_completed = {
        bid
        for bid, r in merged.items()
        if str(r.get("service_type") or "").upper() == "WF"
        and r.get("effective_status") == "completed"
    }
    status_c = Counter(str(r.get("effective_status")) for r in merged.values())
    svc_status = Counter(
        (
            str(r.get("service_type") or "").upper(),
            str(r.get("effective_status") or ""),
        )
        for r in merged.values()
    )

    freeze_by = {e["employee"]: e for e in freeze["productivity_eligible"]["by_employee"]}
    emp_conflicts = []
    for e, row in by_emp.items():
        fr = freeze_by.get(e)
        if not fr:
            emp_conflicts.append({"employee": e, "issue": "not_in_freeze", **row})
            continue
        # Bag counts must match; PRE lbs may differ under current authoritative resolver.
        if fr["bags"] != row["bags"]:
            emp_conflicts.append(
                {
                    "employee": e,
                    "issue": "bag_count_mismatch",
                    "rebuild_bags": row["bags"],
                    "freeze_bags": fr["bags"],
                    "rebuild_pre": round(row["pre"], 2),
                    "freeze_pre": fr["weight_lbs"],
                }
            )
    for e, fr in freeze_by.items():
        if e not in by_emp:
            emp_conflicts.append({"employee": e, "issue": "missing_from_rebuild", "freeze": fr})

    pre_notes = []
    for e, row in by_emp.items():
        fr = freeze_by.get(e)
        if fr and fr["bags"] == row["bags"] and abs(float(fr["weight_lbs"]) - row["pre"]) > 0.05:
            pre_notes.append(
                {
                    "employee": e,
                    "freeze_pre": fr["weight_lbs"],
                    "rebuild_pre": round(row["pre"], 2),
                    "delta": round(row["pre"] - float(fr["weight_lbs"]), 2),
                    "note": "bag_count_matches; PRE uses current authoritative resolver",
                }
            )

    post_vals = [
        float(r["post_weight_lbs"])
        for r in merged.values()
        if r.get("effective_status") == "completed" and r.get("post_weight_lbs") is not None
    ]

    plan = {
        "organization_id": ORG,
        "operations_date_et": DAY.isoformat(),
        "current_status": day_rec.get("status"),
        "surviving_day_bags": len(surv_ids),
        "surviving_by_status": dict(
            Counter(str(r.get("effective_status")) for r in surviving)
        ),
        "rebuild_total_bags": len(merged),
        "rebuild_by_status": dict(status_c),
        "rebuild_by_service_status": {
            f"{a}|{b}": n for (a, b), n in svc_status.items()
        },
        "wf": {
            "total": len(
                [
                    r
                    for r in merged.values()
                    if str(r.get("service_type") or "").upper() == "WF"
                ]
            ),
            "completed": len(wf_completed),
            "pending": sum(
                1
                for r in merged.values()
                if str(r.get("service_type") or "").upper() == "WF"
                and r.get("effective_status") == "pending"
            ),
            "review_required": sum(
                1
                for r in merged.values()
                if str(r.get("service_type") or "").upper() == "WF"
                and r.get("effective_status") == "review_required"
            ),
            "excluded": sum(
                1
                for r in merged.values()
                if str(r.get("service_type") or "").upper() == "WF"
                and str(r.get("effective_status")) in ("excluded", "exclude")
            ),
        },
        "hd": {
            "completed": len(hd_completed),
            "pending": len(hd_pending),
            "review_required": len(hd_review),
        },
        "freeze_wf": {
            "total": freeze["wf"]["active_workload"],
            "completed": freeze["wf"]["completed"],
            "pending": freeze["wf"]["pending"],
            "review_required": freeze["wf"]["review_required"],
        },
        "wf_completed_vs_freeze": {
            "equal": wf_completed == freeze_wf_completed,
            "equal_headline": wf_completed == headline_wf_completed,
            "missing_from_rebuild": sorted(freeze_wf_completed - wf_completed),
            "extra_in_rebuild": sorted(wf_completed - freeze_wf_completed),
        },
        "rows_to_restore": sorted(set(merged) - surv_ids),
        "rows_to_restore_count": len(set(merged) - surv_ids),
        "surviving_kept": sorted(surv_ids & set(merged)),
        "surviving_would_drop": sorted(surv_ids - set(merged)),
        "employee_attributed_completed_bags": len(credit),
        "credited_pre_pounds": round(sum(by_emp[e]["pre"] for e in by_emp), 2),
        "overall_post_pounds_completed_with_post": round(sum(post_vals), 2),
        "post_bags_with_value": len(post_vals),
        "productivity_by_employee": [
            {
                "employee": e,
                "bags": by_emp[e]["bags"],
                "weight_lbs": round(by_emp[e]["pre"], 2),
            }
            for e in sorted(by_emp, key=lambda x: (-by_emp[x]["bags"], x))
        ],
        "freeze_productivity_bag_counts": {
            e["employee"]: e["bags"] for e in freeze["productivity_eligible"]["by_employee"]
        },
        "employee_bag_count_conflicts": emp_conflicts,
        "pre_weight_notes_vs_freeze": pre_notes,
        "unrecoverable_rows": unrecoverable,
        "headline_unchanged": True,
        "reconcile_ok": (
            wf_completed == freeze_wf_completed
            and not emp_conflicts
            and not unrecoverable
            and len(surv_ids - set(merged)) == 0
        ),
        "_merged_rows": merged,
    }
    return plan


def _upsert_day_bag(cursor, row: dict[str, Any]) -> None:
    from backend.rinse_veewash_shift_day import _json_dump, _dt

    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_day_bags (
          organization_id, shift_date_et, bag_id, service_type, rush_status,
          new_or_carryover, workload_entry_type, workload_entry_timestamp,
          pre_weight_lbs, post_weight_lbs, weight_lbs,
          canonical_completion_status, canonical_completion_timestamp,
          canonical_completion_employee, effective_status,
          review_reason_codes_json, portal_status_at_sync,
          last_present_scrape, first_confirmed_absent_scrape, disposition,
          bag_snapshot_json,
          productivity_employee_name, productivity_completed_at,
          productivity_weight_lbs, productivity_credit_eligible,
          productivity_exclusion_reason,
          manager_edit_version
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,
          0
        )
        ON DUPLICATE KEY UPDATE
          service_type=VALUES(service_type),
          rush_status=VALUES(rush_status),
          new_or_carryover=VALUES(new_or_carryover),
          workload_entry_type=VALUES(workload_entry_type),
          workload_entry_timestamp=VALUES(workload_entry_timestamp),
          pre_weight_lbs=VALUES(pre_weight_lbs),
          post_weight_lbs=VALUES(post_weight_lbs),
          weight_lbs=VALUES(weight_lbs),
          canonical_completion_status=VALUES(canonical_completion_status),
          canonical_completion_timestamp=VALUES(canonical_completion_timestamp),
          canonical_completion_employee=VALUES(canonical_completion_employee),
          effective_status=VALUES(effective_status),
          review_reason_codes_json=VALUES(review_reason_codes_json),
          portal_status_at_sync=VALUES(portal_status_at_sync),
          last_present_scrape=VALUES(last_present_scrape),
          first_confirmed_absent_scrape=VALUES(first_confirmed_absent_scrape),
          disposition=VALUES(disposition),
          bag_snapshot_json=VALUES(bag_snapshot_json),
          productivity_employee_name=VALUES(productivity_employee_name),
          productivity_completed_at=VALUES(productivity_completed_at),
          productivity_weight_lbs=VALUES(productivity_weight_lbs),
          productivity_credit_eligible=VALUES(productivity_credit_eligible),
          productivity_exclusion_reason=VALUES(productivity_exclusion_reason),
          updated_at=updated_at,
          manager_edit_version=manager_edit_version
        """,
        (
            ORG,
            DAY,
            row["bag_id"],
            row.get("service_type"),
            row.get("rush_status"),
            row.get("new_or_carryover"),
            row.get("workload_entry_type"),
            _dt(row.get("workload_entry_timestamp")),
            row.get("pre_weight_lbs"),
            row.get("post_weight_lbs"),
            row.get("weight_lbs"),
            row.get("canonical_completion_status"),
            _dt(row.get("canonical_completion_timestamp")),
            row.get("canonical_completion_employee"),
            row.get("effective_status"),
            _json_dump(row.get("review_reason_codes") or []),
            row.get("portal_status_at_sync"),
            _dt(row.get("last_present_scrape")),
            _dt(row.get("first_confirmed_absent_scrape")),
            row.get("disposition"),
            _json_dump(row.get("bag_snapshot") or {}),
            row.get("productivity_employee_name"),
            _dt(row.get("productivity_completed_at")),
            row.get("productivity_weight_lbs"),
            int(row.get("productivity_credit_eligible") or 0),
            row.get("productivity_exclusion_reason"),
        ),
    )


def apply_repair(cursor, plan: dict[str, Any]) -> dict[str, Any]:
    from backend.rinse_veewash_shift_day import reopen_shift_day, ensure_shift_monitor_day_tables
    from backend.rinse_employee_completed_bags import clear_step1_productivity_cache

    ensure_shift_monitor_day_tables(cursor)
    merged = plan["_merged_rows"]
    # Reopen if closed so force persist path isn't blocked elsewhere.
    day = plan.get("current_status")
    if day == "CLOSED":
        reopen_shift_day(
            cursor,
            ORG,
            DAY,
            actor_user_id=None,
            actor_display_name="historical_repair_jul24",
            reason="Restore day bags wiped by legacy close force-persist; headline retained",
        )

    for row in merged.values():
        _upsert_day_bag(cursor, row)

    keep = sorted(merged.keys())
    placeholders = ",".join(["%s"] * len(keep))
    cursor.execute(
        f"""
        DELETE FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s
          AND bag_id NOT IN ({placeholders})
        """,
        (ORG, DAY, *keep),
    )
    deleted = cursor.rowcount

    # Audit marker on day meta (do not rewrite headline_json).
    cursor.execute(
        """
        UPDATE rinse_shift_monitor_days
        SET workload_meta_json = JSON_SET(
              COALESCE(workload_meta_json, JSON_OBJECT()),
              '$.historical_repair_jul24',
              CAST(%s AS JSON)
            ),
            review_required_count = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE organization_id = %s AND shift_date_et = %s
        """,
        (
            json.dumps(
                {
                    "repaired_at_utc": datetime.utcnow().isoformat(sep=" "),
                    "rows_upserted": len(merged),
                    "rows_deleted_orphans": deleted,
                    "source": "repair_jul24_day_bags_productivity",
                    "headline_preserved": True,
                }
            ),
            int(plan["hd"]["review_required"]),
            ORG,
            DAY,
        ),
    )
    clear_step1_productivity_cache(ORG, DAY)
    return {"upserted": len(merged), "deleted_orphans": deleted}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True

    _load_env()
    OUT_DIR.mkdir(exist_ok=True)
    conn = _connect(autocommit=False)
    cur = conn.cursor(dictionary=True)
    try:
        plan = build_restore_plan(cur)
        public = {k: v for k, v in plan.items() if not k.startswith("_")}
        dry_path = OUT_DIR / "repair_jul24_productivity_dry_run_org3.json"
        dry_path.write_text(json.dumps(public, indent=2, default=str))
        print(json.dumps({k: public[k] for k in public if k not in (
            "rows_to_restore", "surviving_kept", "productivity_by_employee"
        )}, indent=2, default=str))
        print("WROTE", dry_path)
        print("reconcile_ok", public["reconcile_ok"])

        if args.apply:
            if not public["reconcile_ok"]:
                raise SystemExit("Refusing apply: dry-run did not reconcile")
            result = apply_repair(cur, plan)
            conn.commit()
            apply_path = OUT_DIR / "repair_jul24_productivity_apply_org3.json"
            apply_path.write_text(
                json.dumps({**public, "apply_result": result}, indent=2, default=str)
            )
            print("APPLIED", result, "WROTE", apply_path)
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
