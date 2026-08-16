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
        "segments",
        "specialty_metrics",
        "review_by_reason",
        "review_reasons_by_bag",
    }
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
        return
    org = int(organization_id) if organization_id is not None else None
    day_key = date_et.isoformat() if isinstance(date_et, date) else (str(date_et) if date_et else None)
    for key in list(_TODAY_CACHE):
        if org is not None and key[0] != org:
            continue
        if day_key is not None and key[1] != day_key:
            continue
        _TODAY_CACHE.pop(key, None)


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
    """Raise if the TODAY DTO ships collection payloads meant for later drilldowns."""
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
    out: dict[str, Any] = {"cost_available": False, "cost": None}
    for name in ("Tide", "Downy", "OxiClean", "All Free & Clear"):
        row = usage.get(name) or {}
        out[name] = {
            "ounces": float(row.get("ounces") or 0),
            "doses": int(row.get("doses") or 0),
        }
    return out


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
    from backend.rinse_veewash_shift_day import get_day_headline

    rec = get_day_headline(cursor, organization_id, selected_date_et) or {}
    headline = dict(rec.get("headline") or {})
    if headline and not headline.get("specialty_metrics"):
        from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary

        headline = attach_specialty_metrics_to_summary(
            cursor, organization_id, selected_date_et, headline
        )
    return rec, headline


def _load_wf_lbs(cursor, organization_id: int, selected_date_et: date) -> float | None:
    from backend.daily_operations import compute_day_wf_pound_totals, daily_operations_enabled_for_org

    if not daily_operations_enabled_for_org(int(organization_id)):
        return None
    totals = compute_day_wf_pound_totals(cursor, organization_id, selected_date_et)
    lbs = totals.get("today_wf_completed_pounds")
    return None if lbs is None else float(lbs)


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


def _load_supplies(cursor, organization_id: int, selected_date_et: date) -> dict[str, Any]:
    from backend.supply_usage import build_supply_usage_report

    report = build_supply_usage_report(cursor, organization_id, selected_date_et)
    return extract_supplies(report)


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
    if not bypass_cache:
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
    hd_totals = _load_hd_totals(counting, org, day)
    drc_lines = _load_drc_lines(counting, org, day)
    segments = _load_labor_segments(counting, org, day)
    rates = _load_labor_rates(counting, org)
    supplies = _load_supplies(counting, org, day)

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

    payload = {
        "date_et": day.isoformat(),
        "generated_at_et": generated_iso,
        "wf": extract_wf_kpis(headline, lbs_processed=lbs),
        "hd": extract_hd_kpis(headline, hd_totals),
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
                "wf": "step1_headline+daily_ops_completed_pounds",
                "hd": "step1_headline+hd_day_bag_production",
                "other_revenue": "dr_daily_entry_lines",
                "labor": "shift_job_segments+payroll_worker_profiles",
                "supplies": "supply_usage_report",
                "review": "rinse_shift_monitor_days.review_required_count",
            },
        },
    }
    assert_compact_today_payload(payload)
    _TODAY_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload
