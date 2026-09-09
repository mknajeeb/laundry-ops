#!/usr/bin/env python3
"""Bounded acceptance: payroll bulk + scan chronology opts. 170s hard wall."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

for line in Path("/Users/kamisb./laundry_app/.env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import mysql.connector

from backend.rinse_bag_stage_bounds import event_ts, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_chronology import build_scan_chronology_payload

ORG = 3
DAY = date(2026, 9, 8)
PAY_FROM = "2026-08-26"
PAY_TO = "2026-09-08"
WALL_SEC = 170
BASELINE = {
    "payroll": {"total_ms": 95200, "queries": 1005},
    "weighing": {"total_ms": 2100, "queries": 5, "bytes": 52109},
    "sorting": {"total_ms": 2400, "queries": 4, "bytes": 50230},
    "folder": {"total_ms": 3400, "queries": 3, "bytes": 70509},
    "washing": {"total_ms": 6400, "queries": 2, "bytes": 46337},
    "process_flow": {"total_ms": 9200, "queries": 3, "bytes": 2966768},
    "coverage_audit": {"total_ms": 20600, "queries": 35, "bytes": 517895},
}


class WallTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise WallTimeout(f"wall clock exceeded {WALL_SEC}s")


def _conn():
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        connection_timeout=20,
    )


class QueryProbe:
    def __init__(self, conn):
        self.conn = conn
        self.queries = 0
        self.db_ms = 0.0
        self._orig = conn.cursor

    def __enter__(self):
        probe = self

        def cursor(*args, **kwargs):
            kwargs.setdefault("buffered", True)
            cur = probe._orig(*args, **kwargs)
            orig_ex = cur.execute

            def execute(sql, params=None):
                t0 = time.perf_counter()
                out = orig_ex(sql) if params is None else orig_ex(sql, params)
                probe.db_ms += (time.perf_counter() - t0) * 1000
                probe.queries += 1
                return out

            cur.execute = execute  # type: ignore
            return cur

        self.conn.cursor = cursor  # type: ignore
        return self

    def __exit__(self, *exc):
        self.conn.cursor = self._orig  # type: ignore


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _load_git_module(name: str, relpath: str):
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{relpath}"], cwd=str(ROOT), text=True
    )
    path = Path(f"/tmp/_old_{name}.py")
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register so inner imports of same file work if any
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fp(stage: str, payload: dict) -> list[dict]:
    sessions = payload.get("sessions") or payload.get("bags") or []
    out = []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "bag_id": str(s.get("bag_id") or "").strip().upper(),
                "index": s.get("index"),
                "employee": (
                    s.get("employee")
                    or s.get("folder")
                    or s.get("sort_employee")
                    or s.get("wash_employee")
                    or s.get("dry_employee")
                ),
                "ts": str(
                    s.get("timestamp_et")
                    or s.get("sort_scan_et")
                    or s.get("wash_scan_et")
                    or s.get("dry_scan_et")
                    or s.get("weigh_start_et")
                    or s.get("sort_start_et")
                    or s.get("folder_start_et")
                    or s.get("start_et")
                    or ""
                ),
                "stage_field": s.get("current_stage") or s.get("confidence"),
                "exception": s.get("has_sequence_exception") or s.get("sequence_status"),
                "washer": s.get("washer") or s.get("washer_rack"),
                "dryer": s.get("dryer") or s.get("dryer_rack"),
                "hourly_like": s.get("weight_lbs"),
            }
        )
    out.sort(key=lambda r: (r["bag_id"], r["ts"], str(r["index"])))
    return out


def _parity_fields(rec: dict) -> dict:
    return {
        "id": rec.get("id"),
        "user_id": rec.get("user_id"),
        "clock_in_at": str(rec.get("clock_in_at") or ""),
        "clock_out_at": str(rec.get("clock_out_at") or ""),
        "approved_hours": rec.get("approved_hours"),
        "worker_category": rec.get("worker_category"),
        "hourly_rate": rec.get("hourly_rate"),
        "rate_source": rec.get("rate_source"),
        "rate_missing": bool(rec.get("rate_missing")),
        "status": rec.get("status"),
        "total_hours_display": rec.get("total_hours_display"),
    }


def list_time_records_legacy_n1(conn, organization_id: int, *, from_date, to_date, limit=500):
    """Exact HEAD loop semantics for parity (N+1). Loaded from git HEAD source."""
    # Import HEAD module under a unique name; call its list_time_records.
    # HEAD file uses `from backend.X` — those resolve to current package (resolve_worker
    # and worker_category_for_user unchanged). Only the list loop differs.
    old = _load_git_module("old_payroll_operations_head", "backend/payroll_operations.py")
    return old.list_time_records(
        conn,
        organization_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


def payroll(conn) -> dict:
    from backend.payroll_operations import list_time_records

    with QueryProbe(conn) as probe:
        t0 = time.perf_counter()
        new_items = list_time_records(
            conn, ORG, from_date=PAY_FROM, to_date=PAY_TO, limit=500
        )
        new_ms = (time.perf_counter() - t0) * 1000
        new_q = probe.queries
        new_db = probe.db_ms

    # Reset probe counts for legacy
    with QueryProbe(conn) as probe:
        t0 = time.perf_counter()
        try:
            old_items = list_time_records_legacy_n1(
                conn, ORG, from_date=PAY_FROM, to_date=PAY_TO, limit=500
            )
            old_ms = (time.perf_counter() - t0) * 1000
            old_err = None
        except WallTimeout:
            raise
        except Exception as exc:
            old_items = []
            old_ms = (time.perf_counter() - t0) * 1000
            old_err = f"{type(exc).__name__}: {exc}"

    new_by_id = {_parity_fields(r)["id"]: _parity_fields(r) for r in new_items}
    old_by_id = {_parity_fields(r)["id"]: _parity_fields(r) for r in old_items}
    mismatches = []
    if not old_err:
        if set(new_by_id) != set(old_by_id):
            mismatches.append(
                {
                    "field": "id_set",
                    "only_new": sorted(set(new_by_id) - set(old_by_id))[:20],
                    "only_old": sorted(set(old_by_id) - set(new_by_id))[:20],
                }
            )
        for rid, nr in new_by_id.items():
            o = old_by_id.get(rid)
            if not o:
                continue
            for k in nr:
                if nr[k] != o.get(k):
                    mismatches.append(
                        {"id": rid, "field": k, "got": nr[k], "exp": o.get(k)}
                    )
                    if len(mismatches) >= 30:
                        break
            if len(mismatches) >= 30:
                break

    return {
        "new_total_ms": round(new_ms, 1),
        "new_db_ms": round(new_db, 1),
        "new_python_ms": round(new_ms - new_db, 1),
        "new_queries": new_q,
        "new_rows": len(new_items),
        "new_bytes": len(json.dumps(_jsonable(new_items), default=str)),
        "old_total_ms": round(old_ms, 1) if not old_err else None,
        "old_rows": len(old_items),
        "old_error": old_err,
        "baseline_total_ms": BASELINE["payroll"]["total_ms"],
        "baseline_queries": BASELINE["payroll"]["queries"],
        "parity_ok": (not old_err) and (not mismatches),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def stage_new(conn, stage: str) -> dict:
    cur = conn.cursor(dictionary=True, buffered=True)
    with QueryProbe(conn) as probe:
        t0 = time.perf_counter()
        payload = build_scan_chronology_payload(
            cur, ORG, selected_date_et=DAY, stage=stage
        )
        total_ms = (time.perf_counter() - t0) * 1000
    sessions = payload.get("sessions") or payload.get("bags") or []
    return {
        "total_ms": round(total_ms, 1),
        "db_ms": round(probe.db_ms, 1),
        "python_ms": round(total_ms - probe.db_ms, 1),
        "queries": probe.queries,
        "rows": len(sessions),
        "response_bytes": len(json.dumps(_jsonable(payload), default=str)),
        "fingerprint": _fp(stage, payload),
        "summary": _jsonable(payload.get("summary")),
    }


def stage_old_payload(conn, stage: str):
    cur = conn.cursor(dictionary=True, buffered=True)
    if stage == "process_flow":
        old = _load_git_module("old_pf", "backend/rinse_process_flow_chronology.py")
        return old.build_process_flow_chronology_payload(cur, ORG, selected_date_et=DAY)
    if stage == "folder":
        old = _load_git_module("old_folder", "backend/rinse_folder_chronology.py")
        return old.build_folder_chronology_payload(cur, ORG, selected_date_et=DAY)
    if stage == "washing":
        old = _load_git_module("old_wash", "backend/rinse_washing_chronology.py")
        return old.build_washing_chronology_payload(cur, ORG, selected_date_et=DAY)
    if stage == "coverage_audit":
        old = _load_git_module("old_cov", "backend/rinse_scan_coverage_audit.py")
        return old.build_scan_coverage_audit_payload(cur, ORG, selected_date_et=DAY)
    return build_scan_chronology_payload(cur, ORG, selected_date_et=DAY, stage=stage)


def history_window(conn) -> dict:
    from backend.rinse_bag_completion import normalize_bag_id
    from backend.rinse_folder_chronology import (
        _load_scan_events_for_bags as folder_load,
        build_folder_chronology_payload,
    )
    from backend.rinse_shift_analysis import _load_scan_events_for_bags
    from backend.rinse_sorting_chronology import build_sorting_chronology_payload
    from backend.rinse_washing_chronology import (
        _load_washing_split_events_sargable,
        build_washing_chronology_payload,
    )
    from backend.rinse_weighing_chronology import build_weighing_chronology_payload

    cur = conn.cursor(dictionary=True, buffered=True)
    day_start = naive_et_day_start(DAY)
    day_end = naive_et_day_end_inclusive(DAY)
    out: dict[str, Any] = {}

    def count_off(events_by_bag):
        on = off = 0
        for evs in (events_by_bag or {}).values():
            for ev in evs or []:
                ts = event_ts(ev)
                if not ts_valid(ts):
                    continue
                if day_start <= ts <= day_end:
                    on += 1
                else:
                    off += 1
        return on, off

    w = build_weighing_chronology_payload(cur, ORG, selected_date_et=DAY)
    bags = sorted({str(s.get("bag_id") or "").strip() for s in (w.get("sessions") or []) if s.get("bag_id")})
    on, off = count_off(_load_scan_events_for_bags(cur, ORG, bags) if bags else {})
    out["weighing"] = {
        "bags": len(bags),
        "sessions": len(w.get("sessions") or []),
        "on_day": on,
        "outside_day": off,
        "day_only_changes_output": off > 0,
        "why": "Full timelines bound multi-scan weigh sessions across midnight.",
        "history_window_changed": False,
    }

    s = build_sorting_chronology_payload(cur, ORG, selected_date_et=DAY)
    bags = sorted({str(x.get("bag_id") or "").strip() for x in (s.get("sessions") or []) if x.get("bag_id")})
    on, off = count_off(_load_scan_events_for_bags(cur, ORG, bags) if bags else {})
    out["sorting"] = {
        "bags": len(bags),
        "sessions": len(s.get("sessions") or []),
        "on_day": on,
        "outside_day": off,
        "day_only_changes_output": off > 0,
        "why": "Current-cycle sorting selectors need prior/next scans.",
        "history_window_changed": False,
    }

    f = build_folder_chronology_payload(cur, ORG, selected_date_et=DAY)
    bags = sorted({str(x.get("bag_id") or "").strip() for x in (f.get("sessions") or []) if x.get("bag_id")})
    on, off = count_off(folder_load(cur, ORG, bags) if bags else {})
    out["folder"] = {
        "bags": len(bags),
        "sessions": len(f.get("sessions") or []),
        "on_day": on,
        "outside_day": off,
        "day_only_changes_output": off > 0,
        "why": "Folder cycle may start before selected ET day.",
        "history_window_changed": False,
    }

    wash = build_washing_chronology_payload(cur, ORG, selected_date_et=DAY)
    bags = sorted(
        {
            normalize_bag_id(x.get("bag_id")) or str(x.get("bag_id") or "").strip()
            for x in (wash.get("sessions") or [])
            if x.get("bag_id")
        }
    )
    on, off = count_off(
        _load_washing_split_events_sargable(cur, ORG, bags) if bags else {}
    )
    out["washing"] = {
        "bags": len(bags),
        "sessions": len(wash.get("sessions") or []),
        "on_day": on,
        "outside_day": off,
        "day_only_changes_output": off > 0,
        "why": "Split summary needs STV/lifecycle anchors before selected day.",
        "history_window_changed": False,
    }
    out["process_flow"] = {
        "day_only_changes_output": True,
        "why": "Full bag history required after day±1 candidate discovery.",
        "history_window_changed": False,
    }
    out["coverage_audit"] = {
        "day_only_changes_output": True,
        "why": "Coverage still reads multi-source day + bag evidence.",
        "history_window_changed": False,
    }
    return out


def main():
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(WALL_SEC)
    result: dict[str, Any] = {
        "day": str(DAY),
        "org": ORG,
        "wall_sec": WALL_SEC,
        "canonical_split_modified": False,
    }
    conn = _conn()
    try:
        print("PAYROLL new+legacy parity...", flush=True)
        result["payroll"] = payroll(conn)
        p = result["payroll"]
        print(
            json.dumps(
                {k: p[k] for k in p if k != "mismatches"},
                indent=2,
            ),
            flush=True,
        )

        result["chronology"] = {}
        modified = {"process_flow", "folder", "washing", "coverage_audit"}
        for stage in [
            "weighing",
            "sorting",
            "folder",
            "washing",
            "process_flow",
            "coverage_audit",
        ]:
            print(f"STAGE {stage}...", flush=True)
            new = stage_new(conn, stage)
            entry: dict[str, Any] = {
                "new": {k: new[k] for k in new if k != "fingerprint"},
                "baseline": BASELINE.get(stage),
            }
            if stage in modified:
                old_payload = stage_old_payload(conn, stage)
                old_fp = _fp(stage, old_payload)
                new_fp = new["fingerprint"]
                entry["parity_ok"] = old_fp == new_fp
                if old_fp != new_fp:
                    entry["parity_diff"] = {
                        "old_n": len(old_fp),
                        "new_n": len(new_fp),
                        "only_old_bags": sorted(
                            {r["bag_id"] for r in old_fp} - {r["bag_id"] for r in new_fp}
                        )[:30],
                        "only_new_bags": sorted(
                            {r["bag_id"] for r in new_fp} - {r["bag_id"] for r in old_fp}
                        )[:30],
                    }
            result["chronology"][stage] = entry
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "ms": entry["new"]["total_ms"],
                        "q": entry["new"]["queries"],
                        "bytes": entry["new"]["response_bytes"],
                        "parity_ok": entry.get("parity_ok"),
                    }
                ),
                flush=True,
            )

        print("HISTORY WINDOW...", flush=True)
        result["history_window"] = history_window(conn)
        print(json.dumps(result["history_window"], indent=2), flush=True)
    except WallTimeout as exc:
        result["error"] = str(exc)
        result["blocked_at"] = list(result.keys())[-1]
        print("WALL TIMEOUT", exc, "keys=", list(result.keys()), flush=True)
    except Exception as exc:
        result["error"] = str(exc)
        result["trace"] = traceback.format_exc()[-1500:]
        print("ERROR", exc, flush=True)
        print(result.get("trace"), flush=True)
    finally:
        signal.alarm(0)
        try:
            conn.close()
        except Exception:
            pass

    Path("/tmp/payroll_scan_opt_acceptance.json").write_text(
        json.dumps(result, indent=2, default=str)
    )
    print("WROTE /tmp/payroll_scan_opt_acceptance.json", flush=True)

    pay_ok = (result.get("payroll") or {}).get("parity_ok")
    chron_ok = all(
        (result.get("chronology") or {}).get(s, {}).get("parity_ok", True)
        for s in ("process_flow", "folder", "washing", "coverage_audit")
    )
    if result.get("error") or not pay_ok or not chron_ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
