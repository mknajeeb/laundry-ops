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
_RINSE_WF_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_RINSE_WF_PRIMARY_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_RINSE_WF_SECONDARY_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_RINSE_WF_HEADLINE_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any], dict[str, Any]]] = {}
_RINSE_WF_CACHE_TTL_LIVE_SEC = 45.0
_RINSE_WF_CACHE_TTL_CLOSED_SEC = 600.0
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
    *,
    include_supplies: bool = True,
) -> None:
    if organization_id is None and date_et is None:
        _TODAY_CACHE.clear()
        _RINSE_WF_CACHE.clear()
        _RINSE_WF_PRIMARY_CACHE.clear()
        _RINSE_WF_SECONDARY_CACHE.clear()
        _RINSE_WF_HEADLINE_CACHE.clear()
        if include_supplies:
            _SUPPLY_SUMMARY_CACHE.clear()
        return
    org = int(organization_id) if organization_id is not None else None
    day_key = date_et.isoformat() if isinstance(date_et, date) else (str(date_et) if date_et else None)
    for store in (
        _TODAY_CACHE,
        _RINSE_WF_CACHE,
        _RINSE_WF_PRIMARY_CACHE,
        _RINSE_WF_SECONDARY_CACHE,
        _RINSE_WF_HEADLINE_CACHE,
    ):
        for key in list(store):
            if org is not None and key[0] != org:
                continue
            if day_key is not None and key[1] != day_key:
                continue
            store.pop(key, None)
    if include_supplies:
        clear_management_supply_cache(organization_id=organization_id, date_et=date_et)


def clear_management_supply_cache(
    organization_id: int | None = None,
    date_et: date | str | None = None,
) -> None:
    if organization_id is None and date_et is None:
        _SUPPLY_SUMMARY_CACHE.clear()
    else:
        org = int(organization_id) if organization_id is not None else None
        day_key = date_et.isoformat() if isinstance(date_et, date) else (str(date_et) if date_et else None)
        for key in list(_SUPPLY_SUMMARY_CACHE):
            # Phase B keys: (org, date_et, rush_scope); legacy: (org, date_et)
            if org is not None and key[0] != org:
                continue
            if day_key is not None and (len(key) < 2 or key[1] != day_key):
                continue
            _SUPPLY_SUMMARY_CACHE.pop(key, None)
    try:
        from backend.management_rinse_wf_supplies import clear_wf_supply_workset

        clear_wf_supply_workset(organization_id=organization_id, date_et=date_et)
    except Exception:
        pass


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


# Compact scalar-code lists allowed on Current Workload / Completed item rows.
# These are short reason codes, not bag/order drilldown arrays.
_ALLOWED_COMPACT_SCALAR_LIST_KEYS = frozenset(
    {
        "items",  # tiny open-OI / completed-OI summary rows
        "review_reason_codes",  # e.g. REGISTRY_COMPLETED_WITHOUT_OI_EVIDENCE
    }
)


def assert_compact_today_payload(payload: Mapping[str, Any]) -> None:
    """Raise if the TODAY DTO ships collection payloads meant for later drilldowns.

    Scalar maps (WF/HD segment counts, specialty counts, reason counts) are allowed.
    Bag/order ID lists are not.

    Allowed compact lists:
      - ``items``: Current Workload / selected-date Completed row summaries
      - ``review_reason_codes``: short string codes on those rows
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
                    if key in _ALLOWED_COMPACT_SCALAR_LIST_KEYS:
                        if key == "items":
                            for entry in val:
                                if isinstance(entry, dict):
                                    stack.append(entry)
                        # review_reason_codes: list[str] only — do not recurse
                        continue
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
    """Normalize Supply summary for Management Rinse WF (Phase B shape)."""
    report = report or {}
    usage = dict(report.get("usage_by_supply") or {})
    products = list(report.get("products") or [])
    has_usage = bool(usage) or bool(products) or bool(report.get("available"))
    rush_supported = bool(report.get("rush_filtering_supported"))
    fin = report.get("split_finalizability") or {}
    raw_status = (
        report.get("supply_status")
        or fin.get("supply_status")
        or ("FINAL" if report.get("supply_finalizable") else None)
    )
    status_u = str(raw_status or "").strip().upper()
    if status_u in ("FINAL", "FINALIZABLE", "FINALIZED"):
        supply_status = "FINAL"
    elif status_u in ("PROVISIONAL", "NOT_FINAL", "NOT-FINAL"):
        supply_status = "PROVISIONAL"
    elif report.get("supply_finalizable") is False or fin.get("finalizable") is False:
        supply_status = "PROVISIONAL"
    elif has_usage:
        supply_status = "FINAL"
    else:
        supply_status = None

    pending = report.get("pending_split_reviews")
    if pending is None:
        pending = int(fin.get("split_pending_count") or 0) + int(
            fin.get("split_review_count") or 0
        )

    out: dict[str, Any] = {
        "cost_available": bool(report.get("cost_available")),
        "cost": report.get("cost"),
        "dashboard": dict(report.get("dashboard") or {}),
        "available": has_usage,
        "deferred": False,
        "rush_filtering_supported": rush_supported,
        "rush_filtering_reason": report.get("rush_filtering_reason")
        or (
            None
            if rush_supported
            else "supply_usage_engine_has_no_rush_status"
        ),
        "scope": report.get("scope") or "all",
        "scope_label": report.get("scope_label") or "DAY TOTALS",
        "supply_finalizable": bool(
            report.get("supply_finalizable")
            if report.get("supply_finalizable") is not None
            else fin.get("finalizable", True)
        ),
        "supply_status": supply_status,
        "supply_banner": report.get("supply_banner") or fin.get("supply_banner"),
        "supply_banner_detail": report.get("supply_banner_detail"),
        "pending_split_reviews": int(pending or 0),
        "split_decision_pending": int(
            report.get("split_decision_pending")
            if report.get("split_decision_pending") is not None
            else pending
            or 0
        ),
        "confirmed_split_orders": int(report.get("confirmed_split_orders") or 0),
        "confirmed_not_split_orders": int(
            report.get("confirmed_not_split_orders") or 0
        ),
        "supply_status_line": report.get("supply_status_line"),
        "loads_identity": report.get("loads_identity"),
        "split_pending_count": int(
            report.get("split_pending_count")
            if report.get("split_pending_count") is not None
            else fin.get("split_pending_count")
            or 0
        ),
        "split_review_count": int(
            report.get("split_review_count")
            if report.get("split_review_count") is not None
            else fin.get("split_review_count")
            or 0
        ),
        "population": dict(report.get("population") or {}),
        "products": products,
        "data_source": report.get("data_source"),
        "price_basis": report.get("price_basis"),
        "as_of_date_et": report.get("as_of_date_et") or report.get("date_et"),
        "terminology": dict(report.get("terminology") or {}),
        "potential_final_cost_min": report.get("potential_final_cost_min"),
        "potential_final_cost_max": report.get("potential_final_cost_max"),
    }
    # Legacy brand keys (Tide / Downy / …) for transitional cards / tests.
    for name in ("Tide", "Downy", "OxiClean", "All Free & Clear"):
        row = usage.get(name) or {}
        card = next(
            (p for p in products if str(p.get("legacy_report_key") or "") == name),
            None,
        )
        ounces = row.get("ounces")
        if ounces is None and card is not None:
            ounces = card.get("quantity_used")
        doses = row.get("doses")
        if doses is None and card is not None:
            doses = card.get("confirmed_doses")
        out[name] = {
            "ounces": None if ounces is None and not has_usage else float(ounces or 0),
            "doses": None if doses is None and not has_usage else int(doses or 0),
            "orders_using": (
                int(
                    (card or {}).get("orders_using")
                    or row.get("orders_using")
                    or row.get("orders")
                    or 0
                )
                if (card is not None or row)
                else (None if not has_usage else 0)
            ),
            "confirmed_loads": (
                int((card or {}).get("confirmed_loads") or doses or 0)
                if (card is not None or doses is not None)
                else (None if not has_usage else 0)
            ),
            "quantity_used": (
                float((card or {}).get("quantity_used") or ounces or 0)
                if (card is not None or ounces is not None)
                else (None if not has_usage else 0.0)
            ),
            "estimated_cost": (
                card.get("estimated_cost")
                if card is not None
                else row.get("estimated_cost")
            ),
            "cost_per_dose": (
                card.get("cost_per_dose")
                if card is not None
                else row.get("cost_per_dose")
            ),
            "average_dose": (
                card.get("average_dose")
                if card is not None
                else row.get("average_dose")
            ),
        }
    return out


def _deferred_supplies_stub() -> dict[str, Any]:
    out = extract_supplies(None)
    out["deferred"] = True
    out["available"] = False
    out["rush_filtering_supported"] = True
    out["rush_filtering_reason"] = None
    out["scope"] = "all"
    out["scope_label"] = "ALL"
    out["products"] = []
    return out


def _deferred_review_stub() -> dict[str, Any]:
    """Placeholder until GET /api/management/rinse-wf/secondary resolves."""
    return {
        "deferred": True,
        "split_available": False,
        "review_required": None,
        "specialty_items": None,
        "missing_from_portal": None,
        "split_order_review": None,
        "unknown_review": None,
        "manual_review": None,
    }


def _wf_cache_ttl(day: date) -> float:
    return _RINSE_WF_CACHE_TTL_LIVE_SEC if day == business_today() else _RINSE_WF_CACHE_TTL_CLOSED_SEC


def _cache_headline(org: int, day: date, day_rec: Mapping[str, Any], headline: Mapping[str, Any]) -> None:
    _RINSE_WF_HEADLINE_CACHE[(org, day.isoformat())] = (
        time.monotonic(),
        dict(day_rec),
        dict(headline),
    )


def _get_cached_headline(org: int, day: date) -> tuple[dict[str, Any], dict[str, Any]] | None:
    cached = _RINSE_WF_HEADLINE_CACHE.get((org, day.isoformat()))
    if not cached:
        return None
    if (time.monotonic() - cached[0]) >= _wf_cache_ttl(day):
        _RINSE_WF_HEADLINE_CACHE.pop((org, day.isoformat()), None)
        return None
    return dict(cached[1]), dict(cached[2])


def _phase_timing(
    phases: dict[str, Any],
    name: str,
    started: float,
    query_count: int,
    *,
    query_start: int,
) -> None:
    phases[name] = {
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "query_count": int(query_count - query_start),
    }


def _load_supplies(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = "all",
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Management WF Supply summary — membership-scoped, rush-aware, Product Master cost."""
    from backend.management_rinse_wf_supplies import (
        build_management_wf_supply_summary,
        normalize_rush_scope,
    )

    org = int(organization_id)
    day = selected_date_et
    scope = normalize_rush_scope(rush_scope)
    cache_key = (org, day.isoformat(), scope)
    is_live = day == business_today()
    ttl = _SUPPLY_SUMMARY_TTL_LIVE_SEC if is_live else _SUPPLY_SUMMARY_TTL_CLOSED_SEC
    now_mono = time.monotonic()
    if bypass_cache:
        clear_management_supply_cache(org, day)
    else:
        cached = _SUPPLY_SUMMARY_CACHE.get(cache_key)
        if cached and (now_mono - cached[0]) < ttl:
            out = dict(cached[1])
            out["cached"] = True
            out["deferred"] = False
            return out

    started = time.perf_counter()
    summary = build_management_wf_supply_summary(
        cursor, org, day, rush_scope=scope
    )
    out = extract_supplies(summary)
    out["deferred"] = False
    out["cached"] = False
    out["scope"] = scope
    out["scope_label"] = summary.get("scope_label") or scope.upper()
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    _SUPPLY_SUMMARY_CACHE[cache_key] = (time.monotonic(), dict(out))
    return out


def build_management_supply_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = "all",
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Dedicated Supply summary for async Rinse WF section."""
    counting = cursor if isinstance(cursor, CountingCursor) else CountingCursor(cursor)
    supplies = _load_supplies(
        counting,
        int(organization_id),
        selected_date_et,
        rush_scope=rush_scope,
        bypass_cache=bypass_cache,
    )
    return {
        "date_et": selected_date_et.isoformat(),
        "rush": supplies.get("scope") or "all",
        "supplies": supplies,
        "_meta": {
            "elapsed_ms": supplies.get("elapsed_ms"),
            "query_count": int(getattr(counting, "query_count", 0)),
            "cached": bool(supplies.get("cached")),
            "source": "management_wf_supplies_phase_b",
        },
    }


def build_management_supply_detail(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rush_scope: str = "all",
    product_id: int | None = None,
    legacy_report_key: str | None = None,
) -> dict[str, Any]:
    """Lazy product order detail — not part of WF core / summary path."""
    from backend.management_rinse_wf_supplies import build_management_wf_supply_detail

    counting = cursor if isinstance(cursor, CountingCursor) else CountingCursor(cursor)
    detail = build_management_wf_supply_detail(
        counting,
        int(organization_id),
        selected_date_et,
        rush_scope=rush_scope,
        product_id=product_id,
        legacy_report_key=legacy_report_key,
    )
    detail["_meta"] = {
        "query_count": int(getattr(counting, "query_count", 0)),
        "source": "management_wf_supplies_detail_phase_b",
    }
    return detail


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
    if seg.get("current_open") is not None:
        out["current_open"] = _int_or_zero(seg.get("current_open"))
    if seg.get("carried_forward") is not None:
        out["carried_forward"] = _int_or_zero(seg.get("carried_forward"))
    if seg.get("unfinished_at_close") is not None:
        out["unfinished_at_close"] = _int_or_zero(seg.get("unfinished_at_close"))
    if seg.get("partially_recorded") is not None:
        out["partially_recorded"] = _int_or_zero(seg.get("partially_recorded"))
    return out


def _overlay_lifecycle_wf_segment(
    rinse: dict[str, Any],
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> None:
    """Overlay WF KPIs: date-free Current Workload + separate selected-date Completed.

    current_workload / pending / current_open = open WF OIs (no selected date).
    selected_date_completed / completed = OI.completed_at on selected ET date.
    total_workload = Current Workload open only (not Completed+Pending+Review).
    """
    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload

    wl = get_canonical_wf_workload(cursor, int(organization_id), selected_date_et)
    counts = wl.get("counts") or {}
    current_open = _int_or_zero(counts.get("current_open"))
    completed = _int_or_zero(counts.get("completed"))
    review = _int_or_zero(counts.get("review"))
    pending = _int_or_zero(counts.get("pending"))
    workload = _int_or_zero(counts.get("workload"))  # open only
    current_workload = wl.get("current_workload") or {}
    selected_completed = wl.get("selected_date_completed") or {}
    segs = dict(rinse.get("segments") or {})
    for key in ("wf", "wf_rush", "wf_non_rush"):
        if key not in segs or not isinstance(segs.get(key), Mapping):
            continue
        # Rush-scoped overlays stay on persisted packs; only all-WF gets live lifecycle.
        if key != "wf":
            continue
        seg = dict(segs[key] or {})
        seg.pop("carried_forward", None)
        seg.pop("carried_forward_count", None)
        seg.pop("moved_forward_count", None)
        seg["pending"] = pending
        seg["current_open"] = current_open
        seg["completed"] = completed
        seg["exceptions"] = {
            "review_required": review,
            "total": review,
        }
        seg["total_workload"] = workload
        seg["active_workload"] = workload
        segs[key] = seg
    rinse["segments"] = segs
    # Explicit separate concepts — frontend must not reconstruct from day headline.
    rinse["current_workload"] = {
        "open": current_open,
        "pending": pending,
        "review": review,
        "items": list(current_workload.get("items") or []),
        "date_independent": True,
        "source": current_workload.get("source") or wl.get("source"),
    }
    rinse["selected_date_completed"] = {
        "date_et": selected_date_et.isoformat(),
        "completed": completed,
        "items": list(selected_completed.get("items") or []),
        "source": selected_completed.get("source") or wl.get("source"),
    }
    rinse["lifecycle_overlay"] = {
        "current_open": current_open,
        "completed_on_selected_date": completed,
        "review": review,
        "pending": pending,
        "current_workload_open": workload,
        "source": wl.get("source") or "canonical_wf_workload_v3_lifecycle",
    }


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
) -> dict[str, dict[str, Any]]:
    """Compact specialty packs: order_count and item_qty stay distinct.

    ``count`` / ``order_count`` = number of orders.
    ``item_qty`` / ``total_quantity`` = sum of line quantities.
    When ``member_ids`` is set (rush scope), both are recomputed from matching
    orders — never reuse the unscoped item total with a scoped order count.
    """
    out: dict[str, dict[str, Any]] = {}
    src = pack or {}
    for key in SPECIALTY_PACK_KEYS:
        row = src.get(key) or {}
        orders = [o for o in (row.get("orders") or []) if isinstance(o, dict)]
        raw_ids = [
            str(x).strip().upper()
            for x in (row.get("order_ids") or [])
            if str(x).strip()
        ]
        if not raw_ids and orders:
            raw_ids = [
                str(o.get("bag_id") or "").strip().upper()
                for o in orders
                if str(o.get("bag_id") or "").strip()
            ]

        if member_ids is not None:
            if orders:
                filtered = [
                    o
                    for o in orders
                    if str(o.get("bag_id") or "").strip().upper() in member_ids
                ]
                count = len(filtered)
                item_qty = 0.0
                for o in filtered:
                    try:
                        item_qty += float(o.get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
            else:
                count = len([bid for bid in raw_ids if bid in member_ids])
                # No per-order qty available under membership filter — do not
                # keep the unscoped total_quantity (would mix scopes).
                item_qty = float(count) if key in ("rejected_orders", "split_orders") else 0.0
                if key in ("comforter_orders", "bath_mat_orders") and count and row.get(
                    "total_quantity"
                ) is not None:
                    # Best-effort: if every order_id is in scope, keep pack total.
                    if raw_ids and all(bid in member_ids for bid in raw_ids):
                        try:
                            item_qty = float(row.get("total_quantity") or 0)
                        except (TypeError, ValueError):
                            item_qty = 0.0
        elif orders:
            count = len(orders)
            item_qty = 0.0
            for o in orders:
                try:
                    item_qty += float(o.get("quantity") or 0)
                except (TypeError, ValueError):
                    continue
        else:
            count = len(raw_ids) if raw_ids else _int_or_zero(row.get("count"))
            try:
                item_qty = float(
                    row.get("total_quantity")
                    if row.get("total_quantity") is not None
                    else row.get("item_qty")
                    if row.get("item_qty") is not None
                    else (count if key in ("rejected_orders", "split_orders") else 0)
                )
            except (TypeError, ValueError):
                item_qty = 0.0

        order_count = _int_or_zero(row.get("order_count")) or count
        if member_ids is not None or orders:
            order_count = count
        out[key] = {
            "count": count,
            "order_count": order_count,
            "item_qty": round(item_qty, 1) if item_qty else 0,
            "total_quantity": round(item_qty, 1) if item_qty else 0,
        }
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


def extract_review(
    day_rec: Mapping[str, Any] | None,
    headline: Mapping[str, Any] | None,
    *,
    cursor=None,
    organization_id: int | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """Review Required total + Specialty Items / Missing From Portal counts.

    Counts only (no bag ID arrays). Same canonical membership as the Review
    drawers (``review_category_count_payload`` with cursor when available).
    """
    from backend.management_rinse_wf_review import review_category_count_payload

    _ = day_rec
    payload = review_category_count_payload(
        headline,
        cursor=cursor,
        organization_id=organization_id,
        selected_date_et=selected_date_et,
    )
    # Strip internal membership IDs — compact TODAY payload forbids bag arrays.
    payload.pop("_membership", None)
    return payload


def _specialty_packs_current(headline: Mapping[str, Any] | None) -> bool:
    packs = (headline or {}).get("specialty_metrics")
    if not isinstance(packs, dict) or not packs:
        return False
    # Prefer WF pack when present; fall back to all.
    probe = packs.get("wf") or packs.get("all") or {}
    if not isinstance(probe.get("split_orders"), dict):
        return False
    try:
        from backend.rinse_hd_day_metrics import CLASSIFICATION_VERSION

        return int(probe.get("classification_version") or 0) >= CLASSIFICATION_VERSION
    except Exception:
        return False


def _load_headline(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    rebuild_specialty: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persisted Step-1 headline for Management Rinse WF (read-only).

    Fast path: day row + headline JSON only — skips the interactive Step-1
    shell (rollover archive, HD presentation heal, bag-row loads) when a
    usable snapshot already exists. Does not rebuild from raw scans.

    When ``rebuild_specialty`` is False (primary dashboard path), stale specialty
    packs are left untouched — secondary load rebuilds them without blocking KPIs.
    """
    from backend.rinse_veewash_shift_day import (
        build_or_load_step1_for_date,
        get_day_record,
        summary_from_day_record,
    )

    def _maybe_rebuild_specialty(headline_in: dict[str, Any]) -> dict[str, Any]:
        if not rebuild_specialty or _specialty_packs_current(headline_in):
            return headline_in
        from backend.rinse_hd_day_metrics import build_day_specialty_metrics

        packs = dict(headline_in.get("specialty_metrics") or {})
        packs["wf"] = build_day_specialty_metrics(
            cursor, organization_id, selected_date_et, headline_in, service="wf"
        )
        out = dict(headline_in)
        out["specialty_metrics"] = packs
        return out

    day = get_day_record(cursor, organization_id, selected_date_et)
    if day and day.get("headline"):
        # Omit cursor so summary_from_day_record skips HD presentation heal.
        headline = summary_from_day_record(day) or {}
        if headline and not headline.get("data_unavailable"):
            headline = _maybe_rebuild_specialty(headline)
            return dict(day), dict(headline)

    _wl, summary, day_rec = build_or_load_step1_for_date(
        cursor,
        organization_id,
        selected_date_et,
        persist_live=False,
        include_bag_rows=False,
    )
    headline = dict(summary or {})
    rec = dict(day_rec or {})
    if headline and not headline.get("data_unavailable"):
        headline = _maybe_rebuild_specialty(headline)
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
    """Compact PRE/POST lbs for WF day-bag scope.

    PRE uses the authoritative current-cycle resolver (never stale day_bag snap).
    POST sums day_bag post_weight_lbs projections (evidence availability, not completion).
    """
    empty = {
        **_weight_bucket_empty(),
        "rush_filtering_supported": True,
        "source": "canonical_pre_resolver+rinse_shift_monitor_day_bags.post_weight_lbs",
        "semantics": {
            "pre": "sum_authoritative_evidence_pre_lbs_for_wf_filter_scope",
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
    if not table_has_column(cursor, "rinse_shift_monitor_day_bags", "post_weight_lbs"):
        empty["rush_filtering_supported"] = False
        return empty

    cursor.execute(
        """
        SELECT bag_id, rush_status
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND UPPER(COALESCE(service_type, '')) = 'WF'
        """,
        (int(organization_id), selected_date_et),
    )
    bag_rows = cursor.fetchall() or []
    bag_ids = [str(r.get("bag_id") or "").strip().upper() for r in bag_rows if r.get("bag_id")]
    weight_map: dict[str, dict[str, Any]] = {}
    if bag_ids:
        from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs
        from backend.rinse_veewash_review import load_bag_weight_map

        weight_map = load_bag_weight_map(
            cursor,
            int(organization_id),
            bag_ids,
            selected_date_et=selected_date_et,
        )
    else:
        from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs

    pre_all = 0.0
    pre_count_all = 0
    bucket_pre = {"rush": 0.0, "non_rush": 0.0}
    bucket_pre_count = {"rush": 0, "non_rush": 0}
    for row in bag_rows:
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        pre = authoritative_evidence_pre_lbs(weight_map.get(bid) or {})
        if pre is None:
            continue
        bucket = _rush_bucket(row.get("rush_status"))
        pre_all += float(pre)
        pre_count_all += 1
        if bucket in bucket_pre:
            bucket_pre[bucket] += float(pre)
            bucket_pre_count[bucket] += 1

    cursor.execute(
        """
        SELECT rush_status,
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
    post_all = 0.0
    post_count_all = 0
    by_rush = {
        "all": _weight_bucket_empty(),
        "rush": _weight_bucket_empty(),
        "non_rush": _weight_bucket_empty(),
    }
    bucket_post = {"rush": 0.0, "non_rush": 0.0}
    bucket_post_count = {"rush": 0, "non_rush": 0}

    for row in cursor.fetchall() or []:
        bucket = _rush_bucket(row.get("rush_status"))
        post_count = int(row.get("post_bag_count") or 0)
        post = _lbs_or_none(row.get("post_lbs")) if post_count else None
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
        "source": "canonical_pre_resolver+rinse_shift_monitor_day_bags.post_weight_lbs",
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


def _extract_rinse_wf_only(
    headline: Mapping[str, Any] | None,
    day_rec: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """WF-only compact rinse block — no HD dashboard / labor / revenue side loads."""
    full = extract_rinse_step1(headline, None, day_rec)
    wf_seg_keys = ("wf", "wf_rush", "wf_non_rush")
    segs = full.get("segments") or {}
    full["segments"] = {k: segs[k] for k in wf_seg_keys if k in segs}
    spec = full.get("specialty_metrics") or {}
    full["specialty_metrics"] = {k: spec[k] for k in wf_seg_keys if k in spec}
    full.pop("hd_dashboard_totals", None)
    return full


def build_management_rinse_wf_primary_payload(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Rinse WF primary dashboard — workload segment counts only (no PRE/POST weights).

    Does not compute canonical review membership, specialty rebuilds, or weight totals.
    Weights load via ``build_management_rinse_wf_secondary_payload``.
    """
    org = int(organization_id)
    day = selected_date_et
    cache_key = (org, day.isoformat())
    ttl = _wf_cache_ttl(day)
    if bypass_cache:
        _RINSE_WF_PRIMARY_CACHE.pop(cache_key, None)
        _RINSE_WF_HEADLINE_CACHE.pop(cache_key, None)
    else:
        cached = _RINSE_WF_PRIMARY_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < ttl:
            out = dict(cached[1])
            meta = dict(out.get("_meta") or {})
            meta["cached"] = True
            out["_meta"] = meta
            return out

    counting = cursor if isinstance(cursor, CountingCursor) else CountingCursor(cursor)
    started = time.perf_counter()
    phases: dict[str, Any] = {}
    q0 = int(getattr(counting, "query_count", 0))

    t0 = time.perf_counter()
    day_rec, headline = _load_headline(
        counting, org, day, rebuild_specialty=False
    )
    _cache_headline(org, day, day_rec, headline)
    _phase_timing(phases, "headline", t0, counting.query_count, query_start=q0)

    rinse = _extract_rinse_wf_only(headline, day_rec)
    # Live lifecycle overlay: pending/current_open is date-independent;
    # completed is selected-date; workload is the canonical union.
    t_overlay = time.perf_counter()
    q_overlay = int(getattr(counting, "query_count", 0))
    _overlay_lifecycle_wf_segment(rinse, counting, org, day)
    _phase_timing(
        phases, "lifecycle_overlay", t_overlay, counting.query_count, query_start=q_overlay
    )
    # PRE/POST weights and specialty metrics load on the secondary request.
    rinse.pop("specialty_metrics", None)

    now_et = business_now()
    if getattr(now_et, "tzinfo", None) is None:
        generated_iso = now_et.isoformat(timespec="seconds")
    else:
        generated_iso = now_et.isoformat(timespec="seconds")

    payload = {
        "date_et": day.isoformat(),
        "generated_at_et": generated_iso,
        "rinse": rinse,
        "review": _deferred_review_stub(),
        "_meta": {
            "cached": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "query_count": int(getattr(counting, "query_count", 0)),
            "compartment": "rinse_wf",
            "tier": "primary",
            "phases": phases,
            "sources": {
                "rinse": "persisted_day_headline_compact_read+lifecycle_overlay",
                "wf_weights": "deferred_to_/api/management/rinse-wf/secondary",
                "review": "deferred_to_/api/management/rinse-wf/secondary",
                "specialty": "deferred_to_/api/management/rinse-wf/secondary",
            },
        },
    }
    assert_compact_today_payload(payload)
    _RINSE_WF_PRIMARY_CACHE[cache_key] = (time.monotonic(), dict(payload))
    # Keep legacy cache alias for callers/tests expecting monolithic key.
    _RINSE_WF_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def build_management_rinse_wf_secondary_payload(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Rinse WF secondary sections — PRE/POST weights, specialty metrics, review counts."""
    org = int(organization_id)
    day = selected_date_et
    cache_key = (org, day.isoformat())
    ttl = _wf_cache_ttl(day)
    if bypass_cache:
        _RINSE_WF_SECONDARY_CACHE.pop(cache_key, None)
        _RINSE_WF_HEADLINE_CACHE.pop(cache_key, None)
    else:
        cached = _RINSE_WF_SECONDARY_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < ttl:
            out = dict(cached[1])
            meta = dict(out.get("_meta") or {})
            meta["cached"] = True
            out["_meta"] = meta
            return out

    counting = cursor if isinstance(cursor, CountingCursor) else CountingCursor(cursor)
    started = time.perf_counter()
    phases: dict[str, Any] = {}
    q0 = int(getattr(counting, "query_count", 0))

    cached_headline = _get_cached_headline(org, day)
    t0 = time.perf_counter()
    if cached_headline:
        day_rec, headline = cached_headline
    else:
        day_rec, headline = _load_headline(
            counting, org, day, rebuild_specialty=True
        )
        _cache_headline(org, day, day_rec, headline)
    _phase_timing(phases, "headline", t0, counting.query_count, query_start=q0)

    from backend.management_rinse_wf_review import (
        enrich_review_counts_by_rush,
        review_category_count_payload,
    )

    t1 = time.perf_counter()
    q1 = int(counting.query_count)
    rinse_secondary = _extract_rinse_wf_only(headline, day_rec)
    specialty_metrics = rinse_secondary.get("specialty_metrics") or {}
    _phase_timing(phases, "specialty", t1, counting.query_count, query_start=q1)

    t2 = time.perf_counter()
    q2 = int(counting.query_count)
    weight_totals = load_wf_day_weight_totals(counting, org, day)
    _phase_timing(phases, "weights", t2, counting.query_count, query_start=q2)

    t3 = time.perf_counter()
    q3 = int(counting.query_count)
    review_base = review_category_count_payload(
        headline,
        cursor=counting,
        organization_id=org,
        selected_date_et=day,
    )
    review = enrich_review_counts_by_rush(
        counting, org, day, headline, review_base
    )
    review.pop("_membership", None)
    _phase_timing(phases, "review", t3, counting.query_count, query_start=q3)

    now_et = business_now()
    if getattr(now_et, "tzinfo", None) is None:
        generated_iso = now_et.isoformat(timespec="seconds")
    else:
        generated_iso = now_et.isoformat(timespec="seconds")

    payload = {
        "date_et": day.isoformat(),
        "generated_at_et": generated_iso,
        "rinse": {
            "weight_totals": weight_totals,
            "specialty_metrics": specialty_metrics,
        },
        "review": review,
        "_meta": {
            "cached": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "query_count": int(getattr(counting, "query_count", 0)),
            "compartment": "rinse_wf",
            "tier": "secondary",
            "phases": phases,
            "sources": {
                "wf_weights": "canonical_pre_resolver+rinse_shift_monitor_day_bags.post_weight_lbs",
                "specialty": "persisted_or_rebuilt_wf_specialty_pack",
                "review": "canonical_specialty_review_membership_shared_with_drawer",
            },
        },
    }
    assert_compact_today_payload(payload)
    _RINSE_WF_SECONDARY_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def build_management_rinse_wf_payload(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Rinse WF compartment core — primary dashboard path (backward-compatible name)."""
    return build_management_rinse_wf_primary_payload(
        cursor,
        organization_id,
        selected_date_et,
        bypass_cache=bypass_cache,
    )


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
        # Core refresh must not wait on / clear the independent supply cache.
        clear_management_today_cache(org, day, include_supplies=False)
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
    # Supplies are loaded via GET /api/management/today/supplies — never block core.
    supplies = _deferred_supplies_stub()

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

    from backend.management_rinse_wf_review import (
        enrich_review_counts_by_rush,
        review_category_count_payload,
    )

    review = enrich_review_counts_by_rush(
        counting,
        org,
        day,
        headline,
        review_category_count_payload(
            headline,
            cursor=counting,
            organization_id=org,
            selected_date_et=day,
        ),
    )
    review.pop("_membership", None)

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
        "review": review,
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
            "supplies": "deferred_to_/api/management/today/supplies",
            "review": "canonical_specialty_review_membership_shared_with_drawer",
            },
        },
    }
    assert_compact_today_payload(payload)
    _TODAY_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload
