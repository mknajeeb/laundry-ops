"""Management Hub TODAY compact read model.

Assembles scalar KPIs from existing authoritative builders. Does not rewrite
Shift Analysis, Process Flow, supply-usage, payroll, or HD completion formulas.
Does not ship bag/order/employee/scan arrays to the browser.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from backend.business_time import business_now, business_today
from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start
from backend.ta_helpers import table_exists, table_has_column

_TODAY_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_TODAY_CACHE_TTL_LIVE_SEC = 45.0
_TODAY_CACHE_TTL_CLOSED_SEC = 600.0
# Supply summary is expensive (~authoritative first-weight walk). Cache separately
# so warm Rinse WF stays fast while still using Supply Usage rules (no order rows).
_SUPPLY_SUMMARY_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_SUPPLY_SUMMARY_TTL_LIVE_SEC = 120.0
_SUPPLY_SUMMARY_TTL_CLOSED_SEC = 600.0

FORBIDDEN_COLLECTION_KEYS = frozenset(
    {
        "bag_ids",
        "order_ids",
        "orders",
        "employees",
        "sessions",
        "bags",
        "photos",
        "review_rows",
        "hd_order_rows",
        "supply_bag_rows",
        "chronology",
        "scan_events",
        "included_bags",
        "missing_post_bags",
        "orphan_production_facts",
        "review_by_reason",
        "review_reasons_by_bag",
    }
)

RINSE_SEGMENT_KEYS = (
    "all",
    "wf",
    "hd",
    "rush",
    "non_rush",
    "wf_rush",
    "wf_non_rush",
    "hd_rush",
    "hd_non_rush",
)

SPECIALTY_PACK_KEYS = (
    "comforter_orders",
    "bath_mat_orders",
    "rejected_orders",
    "split_orders",
)

LABOR_CATEGORY_KEYS = {
    "RINSE_WF": "rinse_wf_hours",
    "RINSE_HD": "rinse_hd_hours",
    "DROP_OFF": "drop_off_hours",
    "DHS": "dhs_hours",
}


class CountingCursor:
    """Proxy that counts execute() calls without changing query behavior."""

    def __init__(self, cursor: Any):
        self._cursor = cursor
        self.query_count = 0

    def execute(self, *args: Any, **kwargs: Any):
        self.query_count += 1
        return self._cursor.execute(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


def clear_management_today_cache(
    organization_id: int | None = None,
    date_et: date | str | None = None,
) -> None:
    if organization_id is None and date_et is None:
        _TODAY_CACHE.clear()
        _SUPPLY_SUMMARY_CACHE.clear()
        return
    org = int(organization_id) if organization_id is not None else None
    day_key = date_et.isoformat() if isinstance(date_et, date) else (str(date_et) if date_et else None)
    for key in list(_TODAY_CACHE):
        if org is not None and key[0] != org:
            continue
        if day_key is not None and key[1] != day_key:
            continue
        _TODAY_CACHE.pop(key, None)
    for key in list(_SUPPLY_SUMMARY_CACHE):
        if org is not None and key[0] != org:
            continue
        if day_key is not None and key[1] != day_key:
            continue
        _SUPPLY_SUMMARY_CACHE.pop(key, None)


def _money(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _hours(seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return round(seconds / 3600.0, 1)


def _pct(numerator: Any, denominator: Any) -> float | None:
    try:
        den = float(denominator or 0)
        num = float(numerator or 0)
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return round(100.0 * num / den, 1)


def _as_naive(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    if isinstance(dt, str):
        raw = dt.replace("T", " ")[:19]
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _clip_seconds(
    started_at: Any,
    ended_at: Any,
    *,
    day_start: datetime,
    clip_end: datetime,
) -> float:
    start = _as_naive(started_at)
    if start is None:
        return 0.0
    end = _as_naive(ended_at) or clip_end
    start = max(start, day_start)
    end = min(end, clip_end)
    return max(0.0, (end - start).total_seconds())


def assert_compact_today_payload(payload: Mapping[str, Any]) -> None:
    """Raise if the TODAY DTO ships collection payloads meant for later drilldowns.

    Scalar maps (WF/HD segment counts, specialty counts, reason counts) are allowed.
    Bag/order ID lists are not.
    """
    stack: list[Any] = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if key == "_meta":
                    continue
                if key in FORBIDDEN_COLLECTION_KEYS and isinstance(val, (list, tuple, dict)) and val:
                    raise AssertionError(f"TODAY payload leaked collection key {key!r}")
                if isinstance(val, (list, tuple)) and val:
                    raise AssertionError(f"TODAY payload leaked a non-empty list at {key!r}")
                if isinstance(val, dict):
                    stack.append(val)
        elif isinstance(cur, list) and cur:
            raise AssertionError("TODAY payload leaked a non-empty list")


def _unique_specialty_count(pack: Mapping[str, Any] | None, headline: Mapping[str, Any]) -> int:
    spec = pack or {}
    comforter = {
        str(b).strip().upper()
        for b in ((spec.get("comforter_orders") or {}).get("order_ids") or [])
        if str(b).strip()
    }
    bath = {
        str(b).strip().upper()
        for b in ((spec.get("bath_mat_orders") or {}).get("order_ids") or [])
        if str(b).strip()
    }
    union = comforter | bath
    if union:
        return len(union)
    return int(headline.get("comforter_order_count") or 0) + int(
        headline.get("bath_mat_order_count") or 0
    )


def extract_wf_kpis(
    headline: Mapping[str, Any] | None,
    *,
    lbs_processed: float | None,
) -> dict[str, Any]:
    hl = dict(headline or {})
    wf = ((hl.get("segments") or {}).get("wf") or {})
    bags = int(wf.get("total_workload") if wf.get("total_workload") is not None else (wf.get("active_workload") or 0))
    completed = int(wf.get("completed") or 0)
    spec_root = hl.get("specialty_metrics") or {}
    pack = spec_root.get("wf") or spec_root.get("all") or {}
    rejects = int((pack.get("rejected_orders") or {}).get("count") or hl.get("rejected_order_count") or 0)
    splits = int((pack.get("split_orders") or {}).get("count") or hl.get("split_order_count") or 0)
    specialty = _unique_specialty_count(pack, hl)
    return {
        "bags": bags,
        "lbs_processed": None if lbs_processed is None else float(lbs_processed),
        "completed": completed,
        "specialty": specialty,
        "rejects": rejects,
        "reject_pct": _pct(rejects, bags),
        "split_pct": _pct(splits, bags),
        "available": bool(hl),
    }


def extract_hd_kpis(
    headline: Mapping[str, Any] | None,
    hd_totals: Mapping[str, Any] | None,
) -> dict[str, Any]:
    hd_seg = (((headline or {}).get("segments") or {}).get("hd") or {})
    totals = dict(hd_totals or {})
    completed = hd_seg.get("completed")
    if completed is None:
        completed = totals.get("complete") or 0
    open_in_process = hd_seg.get("pending")
    if open_in_process is None:
        open_in_process = int(totals.get("not_recorded") or 0) + int(
            totals.get("partially_recorded") or 0
        )
    return {
        "completed_orders": int(completed or 0),
        "items": int(totals.get("complete_total_items") or 0),
        "revenue": _money(totals.get("complete_hd_revenue")),
        "open_in_process": int(open_in_process or 0),
        "available": bool(headline) or bool(hd_totals),
    }


def extract_other_revenue(lines: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    from backend.daily_revenue_cost import _line_amount
    from backend.daily_revenue_cost_constants import (
        LK_DROP_OFF_CARD,
        LK_DROP_OFF_CASH,
        LK_SELF_SERVICE_CARD,
        LK_SELF_SERVICE_CASH,
    )

    rows = dict(lines or {})
    self_service = _money(
        Decimal(str(_line_amount(rows, LK_SELF_SERVICE_CASH) or 0))
        + Decimal(str(_line_amount(rows, LK_SELF_SERVICE_CARD) or 0))
    )
    drop_off = _money(
        Decimal(str(_line_amount(rows, LK_DROP_OFF_CASH) or 0))
        + Decimal(str(_line_amount(rows, LK_DROP_OFF_CARD) or 0))
    )
    dhs = _money(
        sum(
            Decimal(str((row or {}).get("amount") or 0))
            for key, row in rows.items()
            if str(key).startswith("revenue.commercial.") and str(key).endswith(".amount")
        )
    )
    return {
        "self_service": self_service,
        "drop_off": drop_off,
        "dhs": dhs,
        "available": bool(rows),
    }


def extract_labor_kpis(
    segments: list[Mapping[str, Any]],
    *,
    day_start: datetime,
    clip_end: datetime,
    rates_by_user: Mapping[int, float] | None = None,
) -> dict[str, Any]:
    rates = dict(rates_by_user or {})
    seconds_by_cat: dict[str, float] = {k: 0.0 for k in LABOR_CATEGORY_KEYS}
    dollars_by_cat: dict[str, float] = {k: 0.0 for k in LABOR_CATEGORY_KEYS}
    total_seconds = 0.0
    total_dollars = 0.0
    for seg in segments or []:
        sec = _clip_seconds(
            seg.get("started_at"),
            seg.get("ended_at"),
            day_start=day_start,
            clip_end=clip_end,
        )
        if sec <= 0:
            continue
        total_seconds += sec
        uid = seg.get("user_id")
        try:
            rate = float(rates.get(int(uid), 0) or 0) if uid is not None else 0.0
        except (TypeError, ValueError):
            rate = 0.0
        dollars = (sec / 3600.0) * rate
        total_dollars += dollars
        cat = str(seg.get("category_code") or "").strip().upper()
        if cat in LABOR_CATEGORY_KEYS:
            seconds_by_cat[cat] += sec
            dollars_by_cat[cat] += dollars
    return {
        "total_hours": _hours(total_seconds),
        "total_dollars": _money(total_dollars),
        "rinse_wf_hours": _hours(seconds_by_cat["RINSE_WF"]),
        "rinse_hd_hours": _hours(seconds_by_cat["RINSE_HD"]),
        "drop_off_hours": _hours(seconds_by_cat["DROP_OFF"]),
        "dhs_hours": _hours(seconds_by_cat["DHS"]),
        "rinse_wf_dollars": _money(dollars_by_cat["RINSE_WF"]),
        "rinse_hd_dollars": _money(dollars_by_cat["RINSE_HD"]),
        "drop_off_dollars": _money(dollars_by_cat["DROP_OFF"]),
        "dhs_dollars": _money(dollars_by_cat["DHS"]),
    }


def extract_supplies(report: Mapping[str, Any] | None) -> dict[str, Any]:
    usage = dict((report or {}).get("usage_by_supply") or {})
    has_usage = bool(usage)
    rush_supported = bool((report or {}).get("rush_filtering_supported"))
    out: dict[str, Any] = {
        "cost_available": False,
        "cost": None,
        "available": has_usage,
        "rush_filtering_supported": rush_supported,
        "rush_filtering_reason": (report or {}).get("rush_filtering_reason")
        or (
            None
            if rush_supported
            else "supply_usage_engine_has_no_rush_status"
        ),
        "scope": "all",
    }
    for name in ("Tide", "Downy", "OxiClean", "All Free & Clear"):
        row = usage.get(name) or {}
        ounces = row.get("ounces")
        doses = row.get("doses")
        out[name] = {
            "ounces": None if ounces is None and not has_usage else float(ounces or 0),
            "doses": None if doses is None and not has_usage else int(doses or 0),
        }
    return out


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_segment(seg: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not seg:
        return None
    review = _int_or_zero((seg.get("exceptions") or {}).get("review_required"))
    if review == 0:
        review = _int_or_zero((seg.get("exceptions") or {}).get("total"))
    total = seg.get("total_workload")
    if total is None:
        total = seg.get("active_workload") or 0
    out = {
        "total_workload": _int_or_zero(total),
        "active_workload": _int_or_zero(seg.get("active_workload") or total),
        "completed": _int_or_zero(seg.get("completed")),
        "pending": _int_or_zero(seg.get("pending")),
        "exceptions": {"review_required": review, "total": review},
    }
    if seg.get("unfinished_at_close") is not None:
        out["unfinished_at_close"] = _int_or_zero(seg.get("unfinished_at_close"))
    if seg.get("partially_recorded") is not None:
        out["partially_recorded"] = _int_or_zero(seg.get("partially_recorded"))
    return out


def _segment_member_ids(seg: Mapping[str, Any] | None) -> set[str]:
    bags = ((seg or {}).get("bag_ids") or {}) if isinstance(seg, Mapping) else {}
    ids: set[str] = set()
    for bucket in ("new_today", "carryover", "completed", "pending", "review_required"):
        for raw in bags.get(bucket) or []:
            bid = str(raw or "").strip().upper()
            if bid:
                ids.add(bid)
    return ids


def _specialty_counts(
    pack: Mapping[str, Any] | None,
    member_ids: set[str] | None = None,
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    src = pack or {}
    for key in SPECIALTY_PACK_KEYS:
        row = src.get(key) or {}
        raw_ids = [
            str(x).strip().upper()
            for x in (row.get("order_ids") or [])
            if str(x).strip()
        ]
        if member_ids is not None and raw_ids:
            count = len([bid for bid in raw_ids if bid in member_ids])
        elif raw_ids:
            count = len(raw_ids)
        else:
            count = _int_or_zero(row.get("count"))
        out[key] = {"count": count}
    return out


def _compact_freshness(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or not raw:
        return None
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if isinstance(val, (list, dict)):
            continue
        out[key] = val
    return out or None


def _review_reason_counts(raw: Mapping[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, val in (raw or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(val, (list, tuple, set)):
            out[name] = len(val)
        else:
            out[name] = _int_or_zero(val)
    return out


def extract_rinse_step1(
    headline: Mapping[str, Any] | None,
    hd_totals: Mapping[str, Any] | None,
    day_rec: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compact Step-1 scalars for Management TODAY. Same headline math; no bag arrays."""
    hl = dict(headline or {})
    rec = dict(day_rec or {})
    segs = hl.get("segments") or {}
    compact_segs: dict[str, Any] = {}
    for key in RINSE_SEGMENT_KEYS:
        compact = _compact_segment(segs.get(key))
        if compact is not None:
            compact_segs[key] = compact

    spec_root = hl.get("specialty_metrics") or {}
    specialty: dict[str, Any] = {}
    spec_map = (
        ("wf", "wf", "wf"),
        ("wf_rush", "wf", "wf_rush"),
        ("wf_non_rush", "wf", "wf_non_rush"),
        ("hd", "hd", "hd"),
        ("all", "all", "all"),
        ("rush", "all", "rush"),
        ("non_rush", "all", "non_rush"),
    )
    for out_key, pack_key, seg_key in spec_map:
        pack = spec_root.get(pack_key) or spec_root.get("all") or {}
        seg = segs.get(seg_key)
        # Empty membership must stay empty (do not coerce set() to None).
        members = _segment_member_ids(seg) if seg is not None else None
        specialty[out_key] = _specialty_counts(pack, members)

    hd_seg = compact_segs.get("hd") or {}
    hd_dash_src = dict(hl.get("hd_dashboard_totals") or {})
    totals = dict(hd_totals or {})
    items = hd_dash_src.get("total_items")
    if items is None:
        items = totals.get("complete_total_items") or 0
    revenue = (
        hd_dash_src.get("hd_revenue")
        if hd_dash_src.get("hd_revenue") is not None
        else hd_dash_src.get("total_revenue")
    )
    if revenue is None:
        revenue = totals.get("complete_hd_revenue") or 0
    hd_dashboard = {
        "total_hd_orders": _int_or_zero(
            hd_dash_src.get("total_hd_orders")
            if hd_dash_src.get("total_hd_orders") is not None
            else hd_seg.get("total_workload")
        ),
        "completed": _int_or_zero(
            hd_dash_src.get("completed")
            if hd_dash_src.get("completed") is not None
            else hd_seg.get("completed")
        ),
        "review_required": _int_or_zero(
            hd_dash_src.get("review_required")
            if hd_dash_src.get("review_required") is not None
            else (hd_seg.get("exceptions") or {}).get("review_required")
        ),
        "total_items": _int_or_zero(items),
        "total_revenue": _money(revenue),
        "hd_revenue": _money(revenue),
    }

    status = str(rec.get("status") or hl.get("status") or "").upper() or None
    snapshot_missing = bool(
        hl.get("data_unavailable")
        or hl.get("snapshot_available") is False
        or hl.get("snapshot_missing")
        or hl.get("unavailable_reason") == "step1_snapshot_missing"
        or rec.get("data_unavailable")
        or rec.get("snapshot_available") is False
        or rec.get("snapshot_missing")
        or not hl
    )
    return {
        "selected_date_et": hl.get("selected_date_et"),
        "snapshot_available": not snapshot_missing,
        "data_unavailable": snapshot_missing,
        "snapshot_missing": snapshot_missing,
        "step1_history_unavailable": bool(hl.get("step1_history_unavailable")),
        "message": hl.get("message") or rec.get("message"),
        "shift_day": {
            "status": rec.get("status") or status,
            "read_only": status == "CLOSED",
            "review_required_count": rec.get("review_required_count"),
        },
        "segments": compact_segs,
        "specialty_metrics": specialty,
        "hd_dashboard_totals": hd_dashboard,
        "review_reason_counts": _review_reason_counts(hl.get("review_by_reason")),
        "data_freshness": _compact_freshness(hl.get("data_freshness") or rec.get("data_freshness")),
    }


def extract_review(day_rec: Mapping[str, Any] | None, headline: Mapping[str, Any] | None) -> dict[str, Any]:
    """Phase 1: expose the existing combined Review Required count only.

    Specialty Items vs Missing From Portal is not a persisted Review split.
    Existing reason codes do not map onto those two Hub buckets without
    changing membership semantics — that remains Phase 3.
    """
    rec = dict(day_rec or {})
    hl = dict(headline or {})
    count = rec.get("review_required_count")
    if count is None:
        count = ((hl.get("exceptions") or {}).get("review_required"))
    if count is None:
        count = (((hl.get("segments") or {}).get("all") or {}).get("exceptions") or {}).get(
            "review_required"
        )
    return {
        "split_available": False,
        "review_required": int(count or 0),
        "specialty_items": None,
        "missing_from_portal": None,
        "split_reason": "existing_review_is_one_combined_bucket",
    }


def _load_headline(cursor, organization_id: int, selected_date_et: date) -> tuple[dict[str, Any], dict[str, Any]]:
    """Same snapshot read path as Shift Analysis (persist_live=False).

    Does not rebuild from raw scans. Uses persisted Step-1 day + headline.
    """
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    _wl, summary, day_rec = build_or_load_step1_for_date(
        cursor,
        organization_id,
        selected_date_et,
        persist_live=False,
        include_bag_rows=False,
    )
    headline = dict(summary or {})
    rec = dict(day_rec or {})
    has_specialty = bool(headline.get("specialty_metrics")) or (
        headline.get("rejected_order_count") is not None
        or headline.get("comforter_order_count") is not None
    )
    if headline and not has_specialty and not headline.get("data_unavailable"):
        from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

        headline = attach_specialty_metrics_to_summary(
            cursor, organization_id, selected_date_et, headline
        )
    return rec, headline


def _load_wf_lbs(cursor, organization_id: int, selected_date_et: date) -> float | None:
    """Persisted Daily Ops completed pounds only — never the per-bag recompute on this path."""
    from backend.daily_operations import daily_operations_enabled_for_org, ensure_daily_operations_tables

    org = int(organization_id)
    if not daily_operations_enabled_for_org(org):
        return None
    ensure_daily_operations_tables(cursor)
    if not table_exists(cursor, "daily_operations_days"):
        return None
    cursor.execute(
        """
        SELECT today_wf_completed_pounds
        FROM daily_operations_days
        WHERE organization_id = %s AND operations_date_et = %s
        LIMIT 1
        """,
        (org, selected_date_et),
    )
    row = cursor.fetchone()
    if not row or row.get("today_wf_completed_pounds") is None:
        return None
    return float(row["today_wf_completed_pounds"])


def _rush_bucket(raw: Any) -> str:
    token = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    if token == "RUSH":
        return "rush"
    if token in {"NON_RUSH", "NONRUSH"}:
        return "non_rush"
    return "other"


def _lbs_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _weight_bucket_empty() -> dict[str, Any]:
    return {
        "pre_lbs": None,
        "post_lbs": None,
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "pre_weight_bag_count": 0,
        "post_weight_bag_count": 0,
    }


def load_wf_day_weight_totals(cursor, organization_id: int, selected_date_et: date) -> dict[str, Any]:
    """Compact PRE/POST lbs from day-bag projections — one GROUP BY, no per-bag scan walk.

    PRE WEIGHT = sum of pre_weight_lbs for WF bags in scope that have PRE evidence.
    POST WEIGHT = sum of post_weight_lbs for WF bags in scope that have POST evidence.

    Completion status is intentionally NOT used to gate POST — weight availability
    and completion are separate concepts. Bag counts expose coverage vs workload.
    """
    empty = {
        **_weight_bucket_empty(),
        "rush_filtering_supported": True,
        "source": "rinse_shift_monitor_day_bags.pre_weight_lbs/post_weight_lbs",
        "semantics": {
            "pre": "sum_pre_weight_lbs_where_present_for_wf_filter_scope",
            "post": "sum_post_weight_lbs_where_present_for_wf_filter_scope",
            "not": "pre_ne_workload_post_ne_completed",
        },
        "by_rush": {
            "all": _weight_bucket_empty(),
            "rush": _weight_bucket_empty(),
            "non_rush": _weight_bucket_empty(),
        },
    }
    if not table_exists(cursor, "rinse_shift_monitor_day_bags"):
        empty["rush_filtering_supported"] = False
        empty["source"] = None
        return empty
    if not table_has_column(cursor, "rinse_shift_monitor_day_bags", "pre_weight_lbs"):
        empty["rush_filtering_supported"] = False
        return empty

    cursor.execute(
        """
        SELECT rush_status,
               SUM(
                 CASE WHEN pre_weight_lbs IS NOT NULL THEN pre_weight_lbs ELSE 0 END
               ) AS pre_lbs,
               SUM(
                 CASE WHEN pre_weight_lbs IS NOT NULL THEN 1 ELSE 0 END
               ) AS pre_bag_count,
               SUM(
                 CASE WHEN post_weight_lbs IS NOT NULL THEN post_weight_lbs ELSE 0 END
               ) AS post_lbs,
               SUM(
                 CASE WHEN post_weight_lbs IS NOT NULL THEN 1 ELSE 0 END
               ) AS post_bag_count
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'WF'
        GROUP BY rush_status
        """,
        (int(organization_id), selected_date_et),
    )
    pre_all = 0.0
    post_all = 0.0
    pre_count_all = 0
    post_count_all = 0
    by_rush = {
        "all": _weight_bucket_empty(),
        "rush": _weight_bucket_empty(),
        "non_rush": _weight_bucket_empty(),
    }
    bucket_pre = {"rush": 0.0, "non_rush": 0.0}
    bucket_post = {"rush": 0.0, "non_rush": 0.0}
    bucket_pre_count = {"rush": 0, "non_rush": 0}
    bucket_post_count = {"rush": 0, "non_rush": 0}

    for row in cursor.fetchall() or []:
        bucket = _rush_bucket(row.get("rush_status"))
        pre_count = int(row.get("pre_bag_count") or 0)
        post_count = int(row.get("post_bag_count") or 0)
        pre = _lbs_or_none(row.get("pre_lbs")) if pre_count else None
        post = _lbs_or_none(row.get("post_lbs")) if post_count else None
        if pre is not None:
            pre_all += pre
            pre_count_all += pre_count
            if bucket in bucket_pre:
                bucket_pre[bucket] += pre
                bucket_pre_count[bucket] += pre_count
        if post is not None:
            post_all += post
            post_count_all += post_count
            if bucket in bucket_post:
                bucket_post[bucket] += post
                bucket_post_count[bucket] += post_count

    def _pack(pre: float | None, post: float | None, pre_n: int, post_n: int) -> dict[str, Any]:
        return {
            "pre_lbs": round(pre, 1) if pre is not None and pre_n else None,
            "post_lbs": round(post, 1) if post is not None and post_n else None,
            "pre_weight_lbs": round(pre, 1) if pre is not None and pre_n else None,
            "post_weight_lbs": round(post, 1) if post is not None and post_n else None,
            "pre_weight_bag_count": int(pre_n),
            "post_weight_bag_count": int(post_n),
        }

    by_rush["all"] = _pack(
        pre_all if pre_count_all else None,
        post_all if post_count_all else None,
        pre_count_all,
        post_count_all,
    )
    for key in ("rush", "non_rush"):
        by_rush[key] = _pack(
            bucket_pre[key] if bucket_pre_count[key] else None,
            bucket_post[key] if bucket_post_count[key] else None,
            bucket_pre_count[key],
            bucket_post_count[key],
        )

    return {
        **by_rush["all"],
        "rush_filtering_supported": True,
        "source": "rinse_shift_monitor_day_bags.pre_weight_lbs/post_weight_lbs",
        "semantics": empty["semantics"],
        "by_rush": by_rush,
    }


def _load_hd_totals(cursor, organization_id: int, selected_date_et: date) -> dict[str, Any]:
    from backend.daily_operations_hd import compute_hd_day_revenue_totals

    return compute_hd_day_revenue_totals(cursor, organization_id, selected_date_et)


def _load_drc_lines(cursor, organization_id: int, selected_date_et: date) -> dict[str, dict]:
    if not table_exists(cursor, "dr_daily_entries") or not table_exists(cursor, "dr_daily_entry_lines"):
        return {}
    cursor.execute(
        "SELECT id FROM dr_daily_entries WHERE organization_id = %s AND entry_date = %s LIMIT 1",
        (int(organization_id), selected_date_et),
    )
    header = cursor.fetchone()
    if not header:
        return {}
    from backend.daily_revenue_cost import _load_entry_lines

    return _load_entry_lines(cursor, int(header["id"]))


def _load_labor_rates(cursor, organization_id: int) -> dict[int, float]:
    rates: dict[int, float] = {}
    if not table_exists(cursor, "payroll_worker_profiles"):
        return rates
    if not table_has_column(cursor, "payroll_worker_profiles", "default_hourly_rate"):
        return rates
    cursor.execute(
        """
        SELECT user_id, default_hourly_rate
        FROM payroll_worker_profiles
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or row.get("user_id") is None:
            continue
        try:
            rates[int(row["user_id"])] = float(row.get("default_hourly_rate") or 0)
        except (TypeError, ValueError):
            continue
    return rates


def _load_labor_segments(cursor, organization_id: int, selected_date_et: date) -> list[dict[str, Any]]:
    if not table_exists(cursor, "shift_job_segments") or not table_exists(cursor, "shift_sessions"):
        return []
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_exclusive(selected_date_et)
    cursor.execute(
        """
        SELECT sjs.user_id, sjs.category_code, sjs.role_code,
               sjs.started_at, sjs.ended_at
        FROM shift_job_segments sjs
        JOIN shift_sessions ss ON ss.id = sjs.shift_session_id
        WHERE ss.organization_id = %s
          AND sjs.started_at < %s
          AND (sjs.ended_at IS NULL OR sjs.ended_at >= %s)
        """,
        (int(organization_id), day_end, day_start),
    )
    return [dict(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def _load_supplies(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Summary-only Supply Usage scalars (no order rows). Cached separately.

    Rush filtering is not supported by the authoritative Supply Usage engine.
    """
    org = int(organization_id)
    day = selected_date_et
    cache_key = (org, day.isoformat())
    is_live = day == business_today()
    ttl = _SUPPLY_SUMMARY_TTL_LIVE_SEC if is_live else _SUPPLY_SUMMARY_TTL_CLOSED_SEC
    now_mono = time.monotonic()
    if not bypass_cache:
        cached = _SUPPLY_SUMMARY_CACHE.get(cache_key)
        if cached and (now_mono - cached[0]) < ttl:
            return dict(cached[1])

    from backend.supply_usage import build_supply_usage_summary

    summary = build_supply_usage_summary(cursor, org, day)
    out = extract_supplies(summary)
    _SUPPLY_SUMMARY_CACHE[cache_key] = (time.monotonic(), dict(out))
    return out


def build_management_today_payload(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    org = int(organization_id)
    day = selected_date_et
    cache_key = (org, day.isoformat())
    now_mono = time.monotonic()
    is_live = day == business_today()
    ttl = _TODAY_CACHE_TTL_LIVE_SEC if is_live else _TODAY_CACHE_TTL_CLOSED_SEC
    if bypass_cache:
        clear_management_today_cache(org, day)
    elif not bypass_cache:
        cached = _TODAY_CACHE.get(cache_key)
        if cached and (now_mono - cached[0]) < ttl:
            out = dict(cached[1])
            meta = dict(out.get("_meta") or {})
            meta["cached"] = True
            out["_meta"] = meta
            return out

    counting = cursor if isinstance(cursor, CountingCursor) else CountingCursor(cursor)
    started = time.perf_counter()

    day_rec, headline = _load_headline(counting, org, day)
    lbs = _load_wf_lbs(counting, org, day)
    weight_totals = load_wf_day_weight_totals(counting, org, day)
    hd_totals = _load_hd_totals(counting, org, day)
    drc_lines = _load_drc_lines(counting, org, day)
    segments = _load_labor_segments(counting, org, day)
    rates = _load_labor_rates(counting, org)
    supplies = _load_supplies(counting, org, day, bypass_cache=bypass_cache)

    now_et = business_now()
    now_naive = now_et.replace(tzinfo=None) if getattr(now_et, "tzinfo", None) else now_et
    day_start = naive_et_day_start(day)
    day_end = naive_et_day_end_exclusive(day)
    clip_end = min(now_naive, day_end) if is_live else day_end

    generated_at = now_et
    if getattr(generated_at, "tzinfo", None) is None:
        generated_iso = generated_at.isoformat(timespec="seconds")
    else:
        generated_iso = generated_at.isoformat(timespec="seconds")

    rinse = extract_rinse_step1(headline, hd_totals, day_rec)
    rinse["weight_totals"] = weight_totals
    rinse["supplies"] = supplies

    # Prefer day-bag POST sum for operator-facing lbs; fall back to persisted Daily Ops.
    display_post = weight_totals.get("post_lbs")
    if display_post is None:
        display_post = lbs

    payload = {
        "date_et": day.isoformat(),
        "generated_at_et": generated_iso,
        "wf": extract_wf_kpis(headline, lbs_processed=display_post),
        "hd": extract_hd_kpis(headline, hd_totals),
        "rinse": rinse,
        "other_revenue": extract_other_revenue(drc_lines),
        "labor": extract_labor_kpis(
            segments, day_start=day_start, clip_end=clip_end, rates_by_user=rates
        ),
        "supplies": supplies,
        "review": extract_review(day_rec, headline),
        "_meta": {
            "cached": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "query_count": int(getattr(counting, "query_count", 0)),
            "sources": {
            "wf": "step1_build_or_load_persist_live_false+day_bag_weight_totals",
            "hd": "step1_headline+hd_day_bag_production",
            "rinse": "step1_headline_scalars_no_bag_arrays",
            "wf_weights": "rinse_shift_monitor_day_bags.pre_weight_lbs/post_weight_lbs_evidence",
            "other_revenue": "dr_daily_entry_lines",
            "labor": "shift_job_segments+payroll_worker_profiles",
            "supplies": "supply_usage_summary_no_order_rows",
            "review": "rinse_shift_monitor_days.review_required_count",
            },
        },
    }
    assert_compact_today_payload(payload)
    _TODAY_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload
