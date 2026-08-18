"""Canonical Supply Cost Simulator engine — one math, contextual presets.

Modes (UI only):
  - shift: prefill from selected day/shift workload
  - planning: free-hand + historical Last 7 / 30 / Manual

Manager model (not combination cards):
  Tide % + Ultra Clean % ≈ 100% (base detergent)
  Downy % and OxiClean % are independent order rates

Cost model (independence assumption, labeled in UI):
  E[cost/load] = p_tide·c_tide + p_ultra·c_ultra + p_downy·c_downy + p_oxi·c_oxi
  loads = non_split + split×2
  cost = loads × E[cost/load]

Isolated from live Supply Cost dashboard formulas.
PRE weight only for avg lb/bag. Pricing = current Supply Master.
"""

from __future__ import annotations

import copy
import time
from collections import Counter
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.rinse_bag_registry import normalize_bag_id
from backend.rinse_veewash_shift_day import STATUS_CLOSED
from backend.rinse_wf_canonical_split import evaluate_day_wf_splits
from backend.supply_product_constants import (
    LEGACY_KEY_DOWNY,
    LEGACY_KEY_OXICLEAN,
    LEGACY_KEY_TIDE,
    SUPPLY_TYPE_BOOSTER_OXI,
    SUPPLY_TYPE_DETERGENT,
    SUPPLY_TYPE_FABRIC_SOFTENER,
    SUPPLY_TYPE_HYPO_DETERGENT,
)
from backend.supply_product_master import list_supply_products
from backend.supply_usage import get_supply_usage_mapping_rules, supplies_for_usage
from backend.ta_helpers import table_exists

WINDOW_7 = 7
WINDOW_30 = 30
VALID_WINDOWS = frozenset({WINDOW_7, WINDOW_30})

SERVICE_WF = "WF"
SERVICE_HD = "HD"
VALID_SERVICES = frozenset({SERVICE_WF, SERVICE_HD})

# Closed-day aggregates — do not recompute from raw events every open.
_DAY_AGG_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_PLAN_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEC = 6 * 60 * 60
_CACHE_MAX = 128


def clear_split_cost_simulator_cache(organization_id: int | None = None) -> None:
    if organization_id is None:
        _DAY_AGG_CACHE.clear()
        _PLAN_CACHE.clear()
        return
    oid = int(organization_id)
    for store in (_DAY_AGG_CACHE, _PLAN_CACHE):
        for key in list(store.keys()):
            if key and key[0] == oid:
                store.pop(key, None)


def _money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _is_completed_status(status: Any) -> bool:
    st = str(status or "").strip().lower()
    if not st:
        return False
    if "carried_forward" in st.replace(" ", "_") or st in ("carried_forward", "stale"):
        return False
    if "review" in st:
        return False
    return "complet" in st


def period_savings(
    dollar_savings_per_shift: float,
    *,
    shifts_per_week: float = 7.0,
) -> dict[str, Any]:
    shift = round(float(dollar_savings_per_shift or 0), 2)
    spw = max(0.0, float(shifts_per_week))
    weekly = round(shift * spw, 2)
    monthly = round(weekly * 52.0 / 12.0, 2)
    return {
        "shifts_per_week": spw,
        "per_shift": shift,
        "per_day": shift,  # alias for planning UI
        "per_week": weekly,
        "per_month": monthly,
        "monthly_basis": "weekly × 52 / 12",
    }


def normalize_detergent_pcts(tide_pct: float, ultra_pct: float) -> tuple[float, float]:
    t = max(0.0, float(tide_pct or 0))
    u = max(0.0, float(ultra_pct or 0))
    s = t + u
    if s <= 0:
        return 100.0, 0.0
    return round(t / s * 100.0, 4), round(u / s * 100.0, 4)


def expected_cost_per_load(
    *,
    tide_pct: float,
    ultra_clean_pct: float,
    downy_pct: float,
    oxiclean_pct: float,
    unit_costs: Mapping[str, Any],
) -> float:
    """Independence model — primary simulator cost basis."""
    t, u = normalize_detergent_pcts(tide_pct, ultra_clean_pct)
    c_tide = float(unit_costs.get("tide") or unit_costs.get(LEGACY_KEY_TIDE) or 0)
    c_ultra = float(
        unit_costs.get("ultra_clean")
        or unit_costs.get("kirkland")
        or unit_costs.get("All Free & Clear")
        or 0
    )
    c_downy = float(unit_costs.get("downy") or unit_costs.get(LEGACY_KEY_DOWNY) or 0)
    c_oxi = float(unit_costs.get("oxiclean") or unit_costs.get(LEGACY_KEY_OXICLEAN) or 0)
    return round(
        (t / 100.0) * c_tide
        + (u / 100.0) * c_ultra
        + (max(0.0, float(downy_pct)) / 100.0) * c_downy
        + (max(0.0, float(oxiclean_pct)) / 100.0) * c_oxi,
        6,
    )


def simulate_supply_cost(
    *,
    total_orders: int,
    split_pct: float,
    avg_lb_per_bag: float,
    tide_pct: float,
    ultra_clean_pct: float,
    downy_pct: float,
    oxiclean_pct: float,
    unit_costs: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonical simulation — used by Shift and Planning modes."""
    orders = max(0, int(total_orders))
    rate = max(0.0, min(1.0, float(split_pct) / 100.0))
    avg_lb = max(0.0, float(avg_lb_per_bag or 0))
    t, u = normalize_detergent_pcts(tide_pct, ultra_clean_pct)
    d_pct = max(0.0, min(100.0, float(downy_pct or 0)))
    o_pct = max(0.0, min(100.0, float(oxiclean_pct or 0)))

    split_orders = round(orders * rate)
    if split_orders > orders:
        split_orders = orders
    non_split = orders - split_orders
    total_loads = non_split + (split_orders * 2)
    estimated_lbs = round(orders * avg_lb, 1)
    cpl = expected_cost_per_load(
        tide_pct=t,
        ultra_clean_pct=u,
        downy_pct=d_pct,
        oxiclean_pct=o_pct,
        unit_costs=unit_costs,
    )
    total_cost = round(total_loads * cpl, 2)

    return {
        "simulation": True,
        "estimated": True,
        "engine": "supply_cost_v2_independent_mix",
        "total_orders": orders,
        "split_pct": round(rate * 100.0, 2),
        "split_orders": split_orders,
        "non_split_orders": non_split,
        "total_loads": total_loads,
        "avg_lb_per_bag": round(avg_lb, 2),
        "estimated_lbs": estimated_lbs,
        "mix": {
            "tide_pct": round(t, 2),
            "ultra_clean_pct": round(u, 2),
            "downy_pct": round(d_pct, 2),
            "oxiclean_pct": round(o_pct, 2),
            "basis": "orders",
            "note": (
                "Tide + Ultra Clean ≈ 100% base detergent. "
                "Downy and OxiClean are independent order rates."
            ),
        },
        "cost_per_load_expected": round(cpl, 4),
        "estimated_supply_cost": total_cost,
        "cost_per_order": round(total_cost / orders, 4) if orders else None,
        "cost_per_load": round(total_cost / total_loads, 4) if total_loads else None,
        "est_cost_per_lb": (
            round(total_cost / estimated_lbs, 4) if estimated_lbs > 0 else None
        ),
        "unit_costs": {
            "tide": _money(unit_costs.get("tide") or unit_costs.get(LEGACY_KEY_TIDE)),
            "ultra_clean": _money(
                unit_costs.get("ultra_clean")
                or unit_costs.get("kirkland")
                or unit_costs.get("All Free & Clear")
            ),
            "downy": _money(unit_costs.get("downy") or unit_costs.get(LEGACY_KEY_DOWNY)),
            "oxiclean": _money(
                unit_costs.get("oxiclean") or unit_costs.get(LEGACY_KEY_OXICLEAN)
            ),
        },
        "assumption": (
            "Expected cost/load uses independent detergent + addon rates "
            "(not joint combination shares)."
        ),
    }


def compare_scenarios(
    current: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    shifts_per_week: float = 7.0,
) -> dict[str, Any]:
    c_loads = int(current.get("total_loads") or 0)
    t_loads = int(target.get("total_loads") or 0)
    c_cost = float(current.get("estimated_supply_cost") or 0)
    t_cost = float(target.get("estimated_supply_cost") or 0)
    loads_delta = c_loads - t_loads  # positive = saved
    dollar_delta = round(c_cost - t_cost, 2)  # positive = savings
    periods = period_savings(dollar_delta, shifts_per_week=shifts_per_week)
    return {
        "current": dict(current),
        "target": dict(target),
        "loads_saved": loads_delta,
        "dollar_savings": dollar_delta,
        "savings_pct": (
            round((dollar_delta / c_cost) * 100.0, 2) if c_cost > 0 else None
        ),
        "period_savings": periods,
        "headline": {
            "split_pct_from": current.get("split_pct"),
            "split_pct_to": target.get("split_pct"),
            "loads_from": c_loads,
            "loads_to": t_loads,
            "loads_saved": loads_delta,
            "cost_from": c_cost,
            "cost_to": t_cost,
            "dollar_savings": dollar_delta,
            "est_cost_per_lb_from": current.get("est_cost_per_lb"),
            "est_cost_per_lb_to": target.get("est_cost_per_lb"),
            "per_week": periods["per_week"],
            "per_month": periods["per_month"],
        },
    }


# --- product / classification helpers ---------------------------------------


def _product_unit_costs(
    cursor,
    organization_id: int,
    *,
    as_of: date,
) -> dict[str, float | None]:
    try:
        products = list_supply_products(
            cursor, int(organization_id), active_only=True, as_of=as_of
        )
    except Exception:
        products = []
    costs: dict[str, float | None] = {
        "tide": None,
        "ultra_clean": None,
        "downy": None,
        "oxiclean": None,
    }
    labels: dict[str, str] = {
        "tide": "Tide",
        "ultra_clean": "Ultra Clean",
        "downy": "Downy",
        "oxiclean": "OxiClean",
    }
    for p in products or []:
        legacy = str(p.get("legacy_report_key") or "").strip()
        st = str(p.get("supply_type") or "").upper()
        cpd = _money(p.get("cost_per_dose"))
        brand = str(p.get("brand") or p.get("product_name") or legacy)
        if st == SUPPLY_TYPE_DETERGENT or legacy == LEGACY_KEY_TIDE:
            costs["tide"] = cpd
            labels["tide"] = brand or "Tide"
        elif st == SUPPLY_TYPE_HYPO_DETERGENT or legacy in (
            "Kirkland",
            "All Free & Clear",
        ):
            costs["ultra_clean"] = cpd
            labels["ultra_clean"] = brand or "Ultra Clean"
        elif st == SUPPLY_TYPE_FABRIC_SOFTENER or legacy == LEGACY_KEY_DOWNY:
            costs["downy"] = cpd
            labels["downy"] = brand or "Downy"
        elif st == SUPPLY_TYPE_BOOSTER_OXI or legacy == LEGACY_KEY_OXICLEAN:
            costs["oxiclean"] = cpd
            labels["oxiclean"] = brand or "OxiClean"
    return {**costs, "_labels": labels}  # type: ignore[return-value]


def _classify_supplies(
    supplies: Sequence[str],
    product_types: Mapping[str, str] | None = None,
) -> tuple[str, bool, bool]:
    """(detergent standard|hypo, has_downy, has_oxi)."""
    detergent = "standard"
    has_downy = False
    has_oxi = False
    saw = False
    types = product_types or {}
    for legacy in supplies:
        st = str(types.get(legacy) or "").upper()
        if not st:
            if legacy == LEGACY_KEY_DOWNY:
                st = SUPPLY_TYPE_FABRIC_SOFTENER
            elif legacy == LEGACY_KEY_OXICLEAN:
                st = SUPPLY_TYPE_BOOSTER_OXI
            elif legacy in ("All Free & Clear", "Kirkland"):
                st = SUPPLY_TYPE_HYPO_DETERGENT
            elif legacy == LEGACY_KEY_TIDE:
                st = SUPPLY_TYPE_DETERGENT
        if st == SUPPLY_TYPE_FABRIC_SOFTENER:
            has_downy = True
        elif st == SUPPLY_TYPE_BOOSTER_OXI:
            has_oxi = True
        elif st == SUPPLY_TYPE_HYPO_DETERGENT:
            detergent = "hypo"
            saw = True
        elif st == SUPPLY_TYPE_DETERGENT:
            if not saw:
                detergent = "standard"
            saw = True
    return detergent, has_downy, has_oxi


def mix_pcts_from_counts(
    *,
    total: int,
    tide_n: int,
    ultra_n: int,
    downy_n: int,
    oxi_n: int,
) -> dict[str, Any]:
    denom = max(int(total), 1)

    def pct(n: int) -> float:
        return round((n / denom) * 100.0, 2)

    return {
        "total_orders": int(total),
        "tide_pct": pct(tide_n),
        "ultra_clean_pct": pct(ultra_n),
        "downy_pct": pct(downy_n),
        "oxiclean_pct": pct(oxi_n),
        "tide_orders": tide_n,
        "ultra_clean_orders": ultra_n,
        "downy_orders": downy_n,
        "oxiclean_orders": oxi_n,
        "basis": "orders",
        "note": (
            "Tide + Ultra Clean ≈ 100% of orders with a base detergent. "
            "Downy / OxiClean are independent (may overlap)."
        ),
    }


# --- day aggregate (cached) -------------------------------------------------


def list_closed_shift_dates(
    cursor,
    organization_id: int,
    *,
    limit: int,
    before: date | None = None,
) -> list[date]:
    if not table_exists(cursor, "rinse_shift_monitor_days"):
        return []
    cutoff = before or business_today()
    n = max(1, min(int(limit), 60))
    cursor.execute(
        """
        SELECT shift_date_et
        FROM rinse_shift_monitor_days
        WHERE organization_id = %s
          AND status = %s
          AND shift_date_et < %s
        ORDER BY shift_date_et DESC
        LIMIT %s
        """,
        (int(organization_id), STATUS_CLOSED, cutoff, n),
    )
    out: list[date] = []
    for row in cursor.fetchall() or []:
        d = row.get("shift_date_et") if isinstance(row, dict) else None
        if isinstance(d, date):
            out.append(d)
    return out


def _load_completed_wf_bags(cursor, organization_id: int, shift_date_et: date) -> list[dict]:
    cursor.execute(
        """
        SELECT bag_id, effective_status, pre_weight_lbs
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND service_type = 'WF'
        """,
        (int(organization_id), shift_date_et),
    )
    out = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or not _is_completed_status(row.get("effective_status")):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if bid:
            out.append({"bag_id": bid, "pre_weight_lbs": row.get("pre_weight_lbs")})
    return out


def _compute_day_aggregate(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    rules: Sequence[Mapping[str, Any]],
    product_types: Mapping[str, str],
) -> dict[str, Any]:
    from backend.management_rinse_wf_supplies import _load_si_metadata_fast

    bags = _load_completed_wf_bags(cursor, organization_id, shift_date_et)
    ids = [b["bag_id"] for b in bags]
    pre_sum = 0.0
    pre_n = 0
    for b in bags:
        try:
            pre = float(b["pre_weight_lbs"]) if b.get("pre_weight_lbs") is not None else None
        except (TypeError, ValueError):
            pre = None
        if pre is not None:
            pre_sum += pre
            pre_n += 1

    finalized = split_yes = 0
    tide_n = ultra_n = downy_n = oxi_n = 0
    if ids:
        evaluations = evaluate_day_wf_splits(
            cursor,
            organization_id,
            shift_date_et,
            ids,
            slim_events=True,
            truncate_to_selected_day=True,
        )
        meta = _load_si_metadata_fast(cursor, organization_id, ids)
        for bid in ids:
            ev = evaluations.get(bid) or {}
            if ev.get("split_finalized"):
                finalized += 1
                if ev.get("canonical_split") is True:
                    split_yes += 1
            raw = (meta.get(bid) or {}).get("special_instructions_raw")
            mapped = supplies_for_usage(raw, rules)
            supplies = list((mapped or {}).get("supplies_used") or [LEGACY_KEY_TIDE])
            if not supplies:
                supplies = [LEGACY_KEY_TIDE]
            kind, has_d, has_o = _classify_supplies(supplies, product_types)
            if kind == "hypo":
                ultra_n += 1
            else:
                tide_n += 1
            if has_d:
                downy_n += 1
            if has_o:
                oxi_n += 1

    n = len(ids)
    split_rate = (split_yes / finalized) if finalized else 0.0
    return {
        "date_et": shift_date_et.isoformat(),
        "orders": n,
        "pre_lbs": round(pre_sum, 1) if pre_n else 0.0,
        "bags_with_pre": pre_n,
        "finalized": finalized,
        "split_orders": split_yes,
        "split_pct": round(split_rate * 100.0, 2),
        "tide_n": tide_n,
        "ultra_n": ultra_n,
        "downy_n": downy_n,
        "oxi_n": oxi_n,
    }


def get_day_aggregate(
    cursor,
    organization_id: int,
    shift_date_et: date,
    *,
    rules: Sequence[Mapping[str, Any]] | None = None,
    product_types: Mapping[str, str] | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    org = int(organization_id)
    key = (org, shift_date_et.isoformat())
    if not bypass_cache:
        hit = _DAY_AGG_CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < _CACHE_TTL_SEC:
            return copy.deepcopy(hit[1])

    if rules is None:
        try:
            rules = get_supply_usage_mapping_rules(cursor, org)
        except Exception:
            rules = []
    if product_types is None:
        costs = _product_unit_costs(cursor, org, as_of=shift_date_et)
        # rebuild types from products list
        product_types = {}
        try:
            for p in list_supply_products(cursor, org, active_only=True, as_of=shift_date_et) or []:
                legacy = str(p.get("legacy_report_key") or "").strip()
                if legacy:
                    product_types[legacy] = str(p.get("supply_type") or "").upper()
        except Exception:
            pass
        _ = costs

    agg = _compute_day_aggregate(
        cursor, org, shift_date_et, rules=rules or [], product_types=product_types or {}
    )
    _DAY_AGG_CACHE[key] = (time.monotonic(), copy.deepcopy(agg))
    while len(_DAY_AGG_CACHE) > _CACHE_MAX:
        oldest = min(_DAY_AGG_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _DAY_AGG_CACHE.pop(oldest, None)
    return agg


def _sum_aggregates(aggs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    orders = pre = pre_n = finalized = split_yes = 0
    tide_n = ultra_n = downy_n = oxi_n = 0
    dates = []
    for a in aggs:
        orders += int(a.get("orders") or 0)
        pre += float(a.get("pre_lbs") or 0)
        pre_n += int(a.get("bags_with_pre") or 0)
        finalized += int(a.get("finalized") or 0)
        split_yes += int(a.get("split_orders") or 0)
        tide_n += int(a.get("tide_n") or 0)
        ultra_n += int(a.get("ultra_n") or 0)
        downy_n += int(a.get("downy_n") or 0)
        oxi_n += int(a.get("oxi_n") or 0)
        if a.get("date_et"):
            dates.append(a["date_et"])
    avg_lb = round(pre / pre_n, 2) if pre_n else None
    split_pct = round((split_yes / finalized) * 100.0, 2) if finalized else 0.0
    mix = mix_pcts_from_counts(
        total=orders, tide_n=tide_n, ultra_n=ultra_n, downy_n=downy_n, oxi_n=oxi_n
    )
    return {
        "orders": orders,
        "pre_lbs": round(pre, 1) if pre_n else None,
        "bags_with_pre": pre_n,
        "avg_lb_per_bag": avg_lb,
        "finalized": finalized,
        "split_orders": split_yes,
        "split_pct": split_pct,
        "mix": mix,
        "dates_et": sorted(dates),
        "days_used": len(dates),
    }


def build_planning_preset(
    cursor,
    organization_id: int,
    *,
    window_days: int = WINDOW_7,
    as_of_prices: date | None = None,
    today_workload_orders: int | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Historical planning preset from last N CLOSED ET days."""
    window = int(window_days) if int(window_days) in VALID_WINDOWS else WINDOW_7
    price_as_of = as_of_prices or business_today()
    org = int(organization_id)
    cache_key = (org, window, price_as_of.isoformat(), business_today().isoformat())

    cached = False
    payload = None
    if not bypass_cache:
        hit = _PLAN_CACHE.get(cache_key)
        if hit and (time.monotonic() - hit[0]) < _CACHE_TTL_SEC:
            payload = copy.deepcopy(hit[1])
            cached = True

    if payload is None:
        closed = list_closed_shift_dates(cursor, org, limit=window)
        try:
            rules = get_supply_usage_mapping_rules(cursor, org)
        except Exception:
            rules = []
        product_types: dict[str, str] = {}
        try:
            for p in list_supply_products(cursor, org, active_only=True, as_of=price_as_of) or []:
                legacy = str(p.get("legacy_report_key") or "").strip()
                if legacy:
                    product_types[legacy] = str(p.get("supply_type") or "").upper()
        except Exception:
            pass
        unit_costs = _product_unit_costs(cursor, org, as_of=price_as_of)
        aggs = [
            get_day_aggregate(
                cursor,
                org,
                d,
                rules=rules,
                product_types=product_types,
                bypass_cache=bypass_cache,
            )
            for d in closed
        ]
        summed = _sum_aggregates(aggs)
        labels = unit_costs.pop("_labels", {}) if isinstance(unit_costs, dict) else {}
        payload = {
            "available": bool(closed),
            "mode": "planning",
            "service": SERVICE_WF,
            "window_days": window,
            "price_as_of_et": price_as_of.isoformat(),
            "basis": {
                "label": f"Last {window} closed business days",
                "days_used": summed["days_used"],
                "dates_et": summed["dates_et"],
                "orders": summed["orders"],
                "pre_lbs": summed["pre_lbs"],
                "avg_lb_per_bag": summed["avg_lb_per_bag"],
                "split_pct": summed["split_pct"],
                "note": "Closed ET days only — today excluded.",
            },
            "mix": summed["mix"],
            "unit_costs": {
                "tide": unit_costs.get("tide"),
                "ultra_clean": unit_costs.get("ultra_clean"),
                "downy": unit_costs.get("downy"),
                "oxiclean": unit_costs.get("oxiclean"),
            },
            "product_labels": labels,
            "defaults": {
                "total_orders": summed["orders"] // max(summed["days_used"], 1)
                if summed["days_used"]
                else 100,
                "split_pct": summed["split_pct"],
                "avg_lb_per_bag": summed["avg_lb_per_bag"],
                "tide_pct": (summed["mix"] or {}).get("tide_pct"),
                "ultra_clean_pct": (summed["mix"] or {}).get("ultra_clean_pct"),
                "downy_pct": (summed["mix"] or {}).get("downy_pct"),
                "oxiclean_pct": (summed["mix"] or {}).get("oxiclean_pct"),
                "shifts_per_week": 7,
            },
            "read_only": True,
            "estimated": True,
        }
        _PLAN_CACHE[cache_key] = (time.monotonic(), copy.deepcopy(payload))
        while len(_PLAN_CACHE) > _CACHE_MAX:
            oldest = min(_PLAN_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _PLAN_CACHE.pop(oldest, None)

    defaults = dict(payload.get("defaults") or {})
    if today_workload_orders is not None:
        defaults["total_orders"] = int(today_workload_orders)
    out = dict(payload)
    out["defaults"] = defaults
    out["cached"] = cached
    return out


def build_shift_preset_from_live_summary(
    supplies_payload: Mapping[str, Any] | None,
    *,
    selected_date_et: date | None = None,
    service: str = SERVICE_WF,
) -> dict[str, Any]:
    """Build Shift-mode preset from already-loaded Management supplies summary.

    Instant open — no extra historical recompute.
    """
    supplies = supplies_payload or {}
    dash = supplies.get("dashboard") or {}
    pop = supplies.get("population") or {}
    products = supplies.get("products") or []

    orders = int(
        dash.get("workload_orders")
        or dash.get("unique_orders")
        or pop.get("workload_orders")
        or pop.get("orders")
        or 0
    )
    split_y = int(dash.get("confirmed_split_orders") or pop.get("confirmed_split_orders") or 0)
    split_n = int(
        dash.get("confirmed_not_split_orders") or pop.get("confirmed_not_split_orders") or 0
    )
    finalized = split_y + split_n
    split_pct = round((split_y / finalized) * 100.0, 2) if finalized else 0.0

    pre_lbs = pop.get("pre_weight_lbs")
    pre_n = int(pop.get("pre_weight_bag_count") or 0)
    try:
        pre_lbs_f = float(pre_lbs) if pre_lbs is not None else None
    except (TypeError, ValueError):
        pre_lbs_f = None
    avg_lb = round(pre_lbs_f / pre_n, 2) if pre_lbs_f is not None and pre_n else None

    tide_n = ultra_n = downy_n = oxi_n = 0
    unit_costs: dict[str, float | None] = {
        "tide": None,
        "ultra_clean": None,
        "downy": None,
        "oxiclean": None,
    }
    labels = {
        "tide": "Tide",
        "ultra_clean": "Ultra Clean",
        "downy": "Downy",
        "oxiclean": "OxiClean",
    }
    for p in products:
        legacy = str(p.get("legacy_report_key") or "").strip()
        st = str(p.get("supply_type") or "").upper()
        n = int(p.get("orders_using") or p.get("orders") or 0)
        cpd = _money(p.get("cost_per_dose"))
        name = str(p.get("product_name") or p.get("label") or p.get("brand") or legacy)
        if st == SUPPLY_TYPE_DETERGENT or legacy == LEGACY_KEY_TIDE:
            tide_n = n
            unit_costs["tide"] = cpd
            labels["tide"] = name or "Tide"
        elif st == SUPPLY_TYPE_HYPO_DETERGENT or legacy in ("Kirkland", "All Free & Clear"):
            ultra_n = n
            unit_costs["ultra_clean"] = cpd
            labels["ultra_clean"] = name or "Ultra Clean"
        elif st == SUPPLY_TYPE_FABRIC_SOFTENER or legacy == LEGACY_KEY_DOWNY:
            downy_n = n
            unit_costs["downy"] = cpd
        elif st == SUPPLY_TYPE_BOOSTER_OXI or legacy == LEGACY_KEY_OXICLEAN:
            oxi_n = n
            unit_costs["oxiclean"] = cpd

    # Detergent counts should be vs workload; if product cards under-count, fall back
    det_total = tide_n + ultra_n
    mix_base = det_total if det_total > 0 else orders
    mix = mix_pcts_from_counts(
        total=mix_base if mix_base else 1,
        tide_n=tide_n,
        ultra_n=ultra_n,
        downy_n=downy_n,
        oxi_n=oxi_n,
    )
    # Re-express addon % on workload orders when available
    if orders > 0:
        mix["downy_pct"] = round((downy_n / orders) * 100.0, 2)
        mix["oxiclean_pct"] = round((oxi_n / orders) * 100.0, 2)
        mix["total_orders"] = orders
        if det_total > 0:
            mix["tide_pct"] = round((tide_n / det_total) * 100.0, 2)
            mix["ultra_clean_pct"] = round((ultra_n / det_total) * 100.0, 2)

    day = selected_date_et.isoformat() if isinstance(selected_date_et, date) else None
    return {
        "available": orders > 0 or bool(products),
        "mode": "shift",
        "service": service if service in VALID_SERVICES else SERVICE_WF,
        "date_et": day,
        "basis": {
            "label": "Selected shift / day",
            "orders": orders,
            "pre_lbs": pre_lbs_f,
            "avg_lb_per_bag": avg_lb,
            "split_pct": split_pct,
            "finalized_split_orders": finalized,
            "note": "Prefill from live Management supplies for this day.",
        },
        "mix": mix,
        "unit_costs": unit_costs,
        "product_labels": labels,
        "defaults": {
            "total_orders": orders or 100,
            "split_pct": split_pct,
            "avg_lb_per_bag": avg_lb or 20.0,
            "tide_pct": mix.get("tide_pct") or 100.0,
            "ultra_clean_pct": mix.get("ultra_clean_pct") or 0.0,
            "downy_pct": mix.get("downy_pct") or 0.0,
            "oxiclean_pct": mix.get("oxiclean_pct") or 0.0,
            "shifts_per_week": 7,
        },
        "read_only": True,
        "estimated": True,
        "cached": False,
    }


# --- period dashboard -------------------------------------------------------


def resolve_period_dates(
    period: str,
    *,
    today: date | None = None,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date, str]:
    """Return (start_et, end_et inclusive, label). Business ET calendar."""
    day = today or business_today()
    p = str(period or "today").strip().lower()
    if p == "yesterday":
        d = day - timedelta(days=1)
        return d, d, "Yesterday"
    if p == "last_7":
        return day - timedelta(days=6), day, "Last 7 Days"
    if p == "this_week":
        start = day - timedelta(days=day.weekday())  # Monday
        return start, day, "This Week"
    if p == "previous_week":
        this_mon = day - timedelta(days=day.weekday())
        start = this_mon - timedelta(days=7)
        end = this_mon - timedelta(days=1)
        return start, end, "Previous Week"
    if p == "mtd":
        start = day.replace(day=1)
        return start, day, "Month-to-Date"
    if p == "previous_month":
        first = day.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return start, end, "Previous Month"
    if p == "custom" and custom_start and custom_end:
        a, b = (custom_start, custom_end) if custom_start <= custom_end else (custom_end, custom_start)
        return a, b, "Custom"
    return day, day, "Today"


def build_supplies_period_dashboard(
    cursor,
    organization_id: int,
    *,
    period: str = "today",
    custom_start: date | None = None,
    custom_end: date | None = None,
    service: str = SERVICE_WF,
) -> dict[str, Any]:
    """Compact multi-day supplies reporting for the Supplies Dashboard."""
    org = int(organization_id)
    start, end, label = resolve_period_dates(
        period, custom_start=custom_start, custom_end=custom_end
    )
    unit_costs = _product_unit_costs(cursor, org, as_of=end)
    labels = unit_costs.pop("_labels", {}) if isinstance(unit_costs, dict) else {}

    # Prefer closed-day aggregates inside range; include open today via live path caller.
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)

    try:
        rules = get_supply_usage_mapping_rules(cursor, org)
    except Exception:
        rules = []
    product_types: dict[str, str] = {}
    try:
        for p in list_supply_products(cursor, org, active_only=True, as_of=end) or []:
            legacy = str(p.get("legacy_report_key") or "").strip()
            if legacy:
                product_types[legacy] = str(p.get("supply_type") or "").upper()
    except Exception:
        pass

    aggs = []
    for day in days:
        # Skip future; for today still try aggregate from day bags (may be in progress)
        if day > business_today():
            continue
        try:
            aggs.append(
                get_day_aggregate(
                    cursor, org, day, rules=rules, product_types=product_types
                )
            )
        except Exception:
            continue

    summed = _sum_aggregates(aggs)
    mix = summed.get("mix") or {}
    orders = int(summed.get("orders") or 0)
    split_pct = float(summed.get("split_pct") or 0)
    avg_lb = summed.get("avg_lb_per_bag") or 0.0

    # Estimated period cost at observed split (planning estimate, not live confirmed)
    sim = simulate_supply_cost(
        total_orders=orders,
        split_pct=split_pct,
        avg_lb_per_bag=float(avg_lb or 0),
        tide_pct=float(mix.get("tide_pct") or 100),
        ultra_clean_pct=float(mix.get("ultra_clean_pct") or 0),
        downy_pct=float(mix.get("downy_pct") or 0),
        oxiclean_pct=float(mix.get("oxiclean_pct") or 0),
        unit_costs=unit_costs,
    )

    return {
        "available": orders > 0,
        "period": period,
        "period_label": label,
        "period_start_et": start.isoformat(),
        "period_end_et": end.isoformat(),
        "service": service if service in VALID_SERVICES else SERVICE_WF,
        "wf_orders": orders if service != SERVICE_HD else 0,
        "hd_orders": 0,  # HD supply rules not wired yet
        "orders": orders,
        "pre_lbs": summed.get("pre_lbs"),
        "avg_lb_per_bag": avg_lb,
        "loads": sim["total_loads"],
        "split_pct": split_pct,
        "tide_pct": mix.get("tide_pct"),
        "ultra_clean_pct": mix.get("ultra_clean_pct"),
        "downy_pct": mix.get("downy_pct"),
        "oxiclean_pct": mix.get("oxiclean_pct"),
        "estimated_supply_cost": sim["estimated_supply_cost"],
        "cost_per_order": sim["cost_per_order"],
        "cost_per_load": sim["cost_per_load"],
        "est_cost_per_lb": sim["est_cost_per_lb"],
        "unit_costs": {
            "tide": unit_costs.get("tide"),
            "ultra_clean": unit_costs.get("ultra_clean"),
            "downy": unit_costs.get("downy"),
            "oxiclean": unit_costs.get("oxiclean"),
        },
        "product_labels": labels,
        "mix": mix,
        "estimated": True,
        "note": (
            "Period totals from day aggregates (PRE · order mix · finalized split). "
            "Cost is simulated from Supply Master doses — not live confirmed supply cost."
        ),
        "planning_defaults": {
            "total_orders": orders // max(len(aggs), 1) if aggs else orders,
            "split_pct": split_pct,
            "avg_lb_per_bag": avg_lb,
            "tide_pct": mix.get("tide_pct"),
            "ultra_clean_pct": mix.get("ultra_clean_pct"),
            "downy_pct": mix.get("downy_pct"),
            "oxiclean_pct": mix.get("oxiclean_pct"),
            "shifts_per_week": 7,
        },
    }


# --- backward-compatible aliases -------------------------------------------


def simulate_split_cost(
    *,
    total_orders: int,
    split_rate: float,
    avg_lb_per_bag: float,
    combinations: Sequence[Mapping[str, Any]] | None = None,
    tide_pct: float | None = None,
    ultra_clean_pct: float | None = None,
    downy_pct: float | None = None,
    oxiclean_pct: float | None = None,
    unit_costs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compat wrapper. Prefer simulate_supply_cost."""
    if unit_costs is not None and tide_pct is not None:
        return simulate_supply_cost(
            total_orders=total_orders,
            split_pct=float(split_rate) * 100.0,
            avg_lb_per_bag=avg_lb_per_bag,
            tide_pct=tide_pct,
            ultra_clean_pct=ultra_clean_pct or 0,
            downy_pct=downy_pct or 0,
            oxiclean_pct=oxiclean_pct or 0,
            unit_costs=unit_costs,
        )
    # Derive effective cost/load from combination shares if provided
    cpl = 0.0
    share_sum = 0.0
    for c in combinations or []:
        share = float(c.get("share") or 0)
        share_sum += max(0.0, share)
        cpl += max(0.0, share) * float(c.get("cost_per_load") or 0)
    if share_sum > 0:
        cpl = cpl / share_sum
    return simulate_supply_cost(
        total_orders=total_orders,
        split_pct=float(split_rate) * 100.0,
        avg_lb_per_bag=avg_lb_per_bag,
        tide_pct=100.0,
        ultra_clean_pct=0.0,
        downy_pct=0.0,
        oxiclean_pct=0.0,
        unit_costs={"tide": cpl, "ultra_clean": 0, "downy": 0, "oxiclean": 0},
    )


def compare_baseline_target(baseline, target, *, shifts_per_week: float = 7.0):
    return compare_scenarios(baseline, target, shifts_per_week=shifts_per_week)


def build_split_cost_simulator_baseline(
    cursor,
    organization_id: int,
    *,
    window_days: int = WINDOW_7,
    as_of_prices: date | None = None,
    today_workload_orders: int | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Compat — returns planning preset shaped for older clients."""
    plan = build_planning_preset(
        cursor,
        organization_id,
        window_days=window_days,
        as_of_prices=as_of_prices,
        today_workload_orders=today_workload_orders,
        bypass_cache=bypass_cache,
    )
    mix = plan.get("mix") or {}
    return {
        **plan,
        "combinations": [],  # no longer primary
        "order_mix": {
            "total_completed_wf_orders": mix.get("total_orders"),
            "detergent_standard_order_pct": mix.get("tide_pct"),
            "detergent_hypo_order_pct": mix.get("ultra_clean_pct"),
            "downy_order_pct": mix.get("downy_pct"),
            "oxiclean_order_pct": mix.get("oxiclean_pct"),
            "basis": "orders",
        },
        "cost_per_load_reference": [
            {"label": "Tide only", "cost_per_load": (plan.get("unit_costs") or {}).get("tide")},
            {
                "label": "Ultra Clean only",
                "cost_per_load": (plan.get("unit_costs") or {}).get("ultra_clean"),
            },
            {"label": "Downy add-on", "cost_per_load": (plan.get("unit_costs") or {}).get("downy")},
            {
                "label": "OxiClean add-on",
                "cost_per_load": (plan.get("unit_costs") or {}).get("oxiclean"),
            },
        ],
        "basis": {
            **(plan.get("basis") or {}),
            "completed_bags": (plan.get("basis") or {}).get("orders"),
            "pre_lbs_total": (plan.get("basis") or {}).get("pre_lbs"),
        },
    }


def run_split_cost_simulation(
    baseline: Mapping[str, Any],
    *,
    total_orders: int,
    baseline_split_pct: float,
    target_split_pct: float,
    avg_lb_per_bag: float,
    shifts_per_week: float = 7.0,
    tide_pct: float | None = None,
    ultra_clean_pct: float | None = None,
    downy_pct: float | None = None,
    oxiclean_pct: float | None = None,
) -> dict[str, Any]:
    defaults = baseline.get("defaults") or {}
    mix = baseline.get("mix") or {}
    costs = baseline.get("unit_costs") or {}
    t = tide_pct if tide_pct is not None else float(defaults.get("tide_pct") or mix.get("tide_pct") or 100)
    u = (
        ultra_clean_pct
        if ultra_clean_pct is not None
        else float(defaults.get("ultra_clean_pct") or mix.get("ultra_clean_pct") or 0)
    )
    d = downy_pct if downy_pct is not None else float(defaults.get("downy_pct") or mix.get("downy_pct") or 0)
    o = (
        oxiclean_pct
        if oxiclean_pct is not None
        else float(defaults.get("oxiclean_pct") or mix.get("oxiclean_pct") or 0)
    )
    cur = simulate_supply_cost(
        total_orders=total_orders,
        split_pct=baseline_split_pct,
        avg_lb_per_bag=avg_lb_per_bag,
        tide_pct=t,
        ultra_clean_pct=u,
        downy_pct=d,
        oxiclean_pct=o,
        unit_costs=costs,
    )
    tgt = simulate_supply_cost(
        total_orders=total_orders,
        split_pct=target_split_pct,
        avg_lb_per_bag=avg_lb_per_bag,
        tide_pct=t,
        ultra_clean_pct=u,
        downy_pct=d,
        oxiclean_pct=o,
        unit_costs=costs,
    )
    return {
        **compare_scenarios(cur, tgt, shifts_per_week=shifts_per_week),
        "baseline": cur,
        "target": tgt,
        "read_only": True,
        "estimated": True,
    }
