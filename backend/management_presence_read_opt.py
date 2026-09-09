"""Management-only presence read accelerators.

Temporarily wraps day-membership COUNT loops and presence snapshot loaders for
the duration of a Management API request. ACA / scraper processes never enter
this scope, so their imported originals remain unchanged.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from backend.rinse_folding_et import naive_et_day_start

_DELAYED_AFTER = __import__(
    "backend.rinse_veewash_day_membership", fromlist=["_DELAYED_AFTER"]
)._DELAYED_AFTER


def _candidate_run_ids_for_day(cursor, organization_id: int, selected_date_et: date) -> list[int]:
    from backend.rinse_shift_monitor_baseline import (
        _presence_run_finished_naive_et,
        list_clean_at_vendor_presence_scrapes,
    )

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_start(selected_date_et + timedelta(days=1))
    ids: list[int] = []
    for row in list_clean_at_vendor_presence_scrapes(cursor, organization_id):
        finished = _presence_run_finished_naive_et(row)
        if finished is None:
            continue
        if finished >= day_end:
            continue
        if finished < day_start - timedelta(days=1):
            continue
        rid = int(row.get("id") or 0)
        if rid > 0:
            ids.append(rid)
    return ids


def _preload_run_rows(
    cursor, organization_id: int, run_ids: list[int]
) -> tuple[dict[int, int], dict[int, list[dict[str, Any]]], dict[int, dict[str, dict[str, Any]]]]:
    """One bulk read → counts, load_run_bag_rows shape, snapshot-by-bag shape."""
    from backend.rinse_current_facility_snapshot import portal_at_vendor_yet_to_process

    ids = sorted({int(r) for r in run_ids if int(r or 0) > 0})
    counts: dict[int, int] = {i: 0 for i in ids}
    rows_cache: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    snap_cache: dict[int, dict[str, dict[str, Any]]] = {i: {} for i in ids}
    if not ids:
        return counts, rows_cache, snap_cache

    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        ph = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"""
            SELECT presence_run_id, bag_id, portal_status, customer_name,
                   estimated_delivery_date, rush_flag, service_type, raw_row_json,
                   source_batch_id, rinse_vendor
            FROM rinse_cleaner_ticket_presence_run_rows
            WHERE organization_id = %s
              AND presence_run_id IN ({ph})
            """,
            (int(organization_id), *chunk),
        )
        for raw in cursor.fetchall() or []:
            if not isinstance(raw, dict):
                continue
            rid = int(raw.get("presence_run_id") or 0)
            if rid <= 0:
                continue
            bid = str(raw.get("bag_id") or "").strip().upper()
            if not bid:
                continue
            counts[rid] = int(counts.get(rid, 0)) + 1
            d = dict(raw)
            d["bag_id"] = bid
            rows_cache.setdefault(rid, []).append(d)
            rj = raw.get("raw_row_json")
            if isinstance(rj, str):
                try:
                    rj = json.loads(rj)
                except (json.JSONDecodeError, TypeError):
                    rj = {}
            if not isinstance(rj, dict):
                rj = {}
            snap_cache.setdefault(rid, {})[bid] = {
                "bag_id": bid,
                "customer_name": raw.get("customer_name"),
                "service_type": raw.get("service_type"),
                "estimated_delivery_date": raw.get("estimated_delivery_date"),
                "rush_flag": raw.get("rush_flag"),
                "raw_row_json": rj,
                "delivery_source": "presence_run_snapshot",
                "portal_status": raw.get("portal_status"),
                "presence_run_id": rid,
                "source_batch_id": raw.get("source_batch_id"),
                "rinse_vendor": raw.get("rinse_vendor"),
                "active_presence": False,
                "portal_yet_to_process": portal_at_vendor_yet_to_process(
                    {"raw_row_json": rj}
                ),
            }
    return counts, rows_cache, snap_cache


@contextmanager
def management_presence_read_opt_scope(
    cursor, organization_id: int, selected_date_et: date
) -> Iterator[None]:
    """Bulk-load presence snapshots for Management membership rebuilds."""
    import backend.rinse_cleaner_ticket_presence as presence_mod
    import backend.rinse_veewash_day_membership as membership_mod
    from backend.rinse_veewash_day_membership import is_valid_baseline_scrape
    from backend.ta_helpers import table_exists

    run_ids = _candidate_run_ids_for_day(cursor, int(organization_id), selected_date_et)
    ensure_once_state = {"ok": False}
    orig_ensure = presence_mod.ensure_presence_run_rows_table

    def ensure_once(cur) -> None:
        if ensure_once_state["ok"]:
            return
        orig_ensure(cur)
        ensure_once_state["ok"] = True

    ensure_once(cursor)
    counts, rows_cache, snap_cache = _preload_run_rows(
        cursor, int(organization_id), run_ids
    )

    orig_select = membership_mod.select_first_valid_scrape_after_midnight
    orig_later = membership_mod.list_later_valid_scrapes_same_day
    orig_snap = presence_mod.load_presence_run_snapshot_by_bag
    orig_rows = membership_mod.load_run_bag_rows

    def load_presence_run_snapshot_by_bag(
        cur,
        org_id: int,
        *,
        presence_run_id: int,
    ) -> dict[str, dict[str, Any]]:
        rid = int(presence_run_id)
        if rid in snap_cache:
            return snap_cache[rid]
        ensure_once(cur)
        out = orig_snap(cur, org_id, presence_run_id=rid)
        snap_cache[rid] = out
        return out

    def load_run_bag_rows(cur, presence_run_id: int) -> list[dict[str, Any]]:
        rid = int(presence_run_id)
        if rid in rows_cache:
            return rows_cache[rid]
        out = orig_rows(cur, rid)
        rows_cache[rid] = out
        return out

    def select_first_valid_scrape_after_midnight(
        cur,
        org_id: int,
        day: date,
    ) -> tuple[dict[str, Any] | None, bool, str | None]:
        from backend.rinse_shift_monitor_baseline import (
            _presence_run_finished_naive_et,
            list_clean_at_vendor_presence_scrapes,
        )

        day_start = naive_et_day_start(day)
        day_end = naive_et_day_start(day + timedelta(days=1))
        has_rows_table = table_exists(cur, "rinse_cleaner_ticket_presence_run_rows")
        candidates: list[dict[str, Any]] = []
        for row in list_clean_at_vendor_presence_scrapes(cur, org_id):
            finished = _presence_run_finished_naive_et(row)
            if finished is None:
                continue
            if not (day_start <= finished < day_end):
                continue
            ok, _why = is_valid_baseline_scrape(row)
            if not ok:
                continue
            if has_rows_table:
                snap_n = int(counts.get(int(row["id"]), 0))
                if snap_n <= 0:
                    continue
                row = {**row, "_run_row_count": snap_n}
            candidates.append(row)
        if not candidates:
            return None, False, "no_valid_scrape_after_midnight"
        candidates.sort(
            key=lambda r: (
                _presence_run_finished_naive_et(r) or datetime.max,
                int(r.get("id") or 0),
            )
        )
        baseline = candidates[0]
        finished = _presence_run_finished_naive_et(baseline)
        delayed = bool(finished and finished.time() > _DELAYED_AFTER)
        return baseline, delayed, None

    def list_later_valid_scrapes_same_day(
        cur,
        org_id: int,
        day: date,
        *,
        after_run_id: int,
        after_finished_et: datetime,
    ) -> list[dict[str, Any]]:
        from backend.rinse_shift_monitor_baseline import (
            _presence_run_finished_naive_et,
            list_clean_at_vendor_presence_scrapes,
        )

        day_end = naive_et_day_start(day + timedelta(days=1))
        has_rows_table = table_exists(cur, "rinse_cleaner_ticket_presence_run_rows")
        out: list[dict[str, Any]] = []
        for row in list_clean_at_vendor_presence_scrapes(cur, org_id):
            rid = int(row.get("id") or 0)
            if rid == int(after_run_id):
                continue
            finished = _presence_run_finished_naive_et(row)
            if finished is None:
                continue
            if finished <= after_finished_et or finished >= day_end:
                continue
            ok, _why = is_valid_baseline_scrape(row)
            if not ok:
                if int(row.get("rows_found") or 0) <= 0:
                    continue
            if int(row.get("rows_found") or 0) <= 0:
                continue
            if has_rows_table and int(counts.get(rid, 0)) <= 0:
                continue
            out.append(row)
        out.sort(
            key=lambda r: (
                _presence_run_finished_naive_et(r) or datetime.max,
                int(r.get("id") or 0),
            )
        )
        return out

    presence_mod.ensure_presence_run_rows_table = ensure_once  # type: ignore[method-assign]
    presence_mod.load_presence_run_snapshot_by_bag = (  # type: ignore[method-assign]
        load_presence_run_snapshot_by_bag
    )
    membership_mod.select_first_valid_scrape_after_midnight = (  # type: ignore[method-assign]
        select_first_valid_scrape_after_midnight
    )
    membership_mod.list_later_valid_scrapes_same_day = (  # type: ignore[method-assign]
        list_later_valid_scrapes_same_day
    )
    membership_mod.load_run_bag_rows = load_run_bag_rows  # type: ignore[method-assign]
    try:
        yield
    finally:
        presence_mod.ensure_presence_run_rows_table = orig_ensure  # type: ignore[method-assign]
        presence_mod.load_presence_run_snapshot_by_bag = orig_snap  # type: ignore[method-assign]
        membership_mod.select_first_valid_scrape_after_midnight = orig_select  # type: ignore[method-assign]
        membership_mod.list_later_valid_scrapes_same_day = orig_later  # type: ignore[method-assign]
        membership_mod.load_run_bag_rows = orig_rows  # type: ignore[method-assign]
