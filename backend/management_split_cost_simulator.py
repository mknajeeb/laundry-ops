"""Split Cost Simulator — forward planning only (read-only).

Isolated from live Supply Cost dashboard formulas.
Historical baseline uses CLOSED ET business days only (not today-in-progress).
Avg lb/bag uses canonical PRE weight only (never POST).
Pricing uses current effective Supply Master (forward-looking).

Closed-day baselines are cached aggressively (immutable during the business day).
"""

from __future__ import annotations

import copy
import time
from collections import Counter
from datetime import date
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

# Closed-day history does not change mid-day; warm modal opens from memory.
_BASELINE_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_BASELINE_CACHE_TTL_SEC = 6 * 60 * 60  # 6h
_BASELINE_CACHE_MAX = 48


def clear_split_cost_simulator_cache(
    organization_id: int | None = None,
) -> None:
    if organization_id is None:
        _BASELINE_CACHE.clear()
        return
    oid = int(organization_id)
    for key in list(_BASELINE_CACHE.keys()):
        if key and key[0] == oid:
            _BASELINE_CACHE.pop(key, None)


def _money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _qty(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
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


def combo_key_from_supplies(supplies: Sequence[str] | None) -> str:
    parts = [str(s).strip() for s in (supplies or []) if str(s).strip()]
    return " + ".join(parts) if parts else LEGACY_KEY_TIDE


def short_combo_label(
    key: str,
    product_by_legacy: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Compact display: Tide only, Hypo + Oxi, etc."""
    parts = [p.strip() for p in str(key or "").split(" + ") if p.strip()]
    if not parts:
        return "Tide only"
    labels: list[str] = []
    for p in parts:
        meta = (product_by_legacy or {}).get(p) or {}
        st = str(meta.get("supply_type") or "").upper()
        if st == SUPPLY_TYPE_HYPO_DETERGENT or p in ("All Free & Clear", "Kirkland"):
            brand = str(meta.get("brand") or "").strip()
            labels.append("Hypo" if not brand else ("Hypo" if brand == "Kirkland" else brand))
        elif st == SUPPLY_TYPE_DETERGENT or p == LEGACY_KEY_TIDE:
            labels.append("Tide")
        elif st == SUPPLY_TYPE_FABRIC_SOFTENER or p == LEGACY_KEY_DOWNY:
            labels.append("Downy")
        elif st == SUPPLY_TYPE_BOOSTER_OXI or p == LEGACY_KEY_OXICLEAN:
            labels.append("Oxi")
        else:
            labels.append(str(meta.get("brand") or p))
    if len(labels) == 1:
        return f"{labels[0]} only"
    return " + ".join(labels)


def period_savings(
    dollar_savings_per_shift: float,
    *,
    shifts_per_week: float = 7.0,
) -> dict[str, Any]:
    """Weekly = shift × shifts/week; Monthly = weekly × 52/12."""
    shift = round(float(dollar_savings_per_shift or 0), 2)
    spw = max(0.0, float(shifts_per_week))
    weekly = round(shift * spw, 2)
    monthly = round(weekly * 52.0 / 12.0, 2)
    return {
        "shifts_per_week": spw,
        "per_shift": shift,
        "per_week": weekly,
        "per_month": monthly,
        "monthly_basis": "weekly × 52 / 12",
    }


def list_closed_shift_dates(
    cursor,
    organization_id: int,
    *,
    limit: int,
    before: date | None = None,
) -> list[date]:
    """Most recent CLOSED ET business days, excluding `before` (default: today)."""
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


def _load_completed_wf_bags_multi(
    cursor,
    organization_id: int,
    shift_dates: Sequence[date],
) -> dict[date, list[dict[str, Any]]]:
    """One query for all closed days → bags by date."""
    by_day: dict[date, list[dict[str, Any]]] = {d: [] for d in shift_dates}
    if not shift_dates:
        return by_day
    ph = ",".join(["%s"] * len(shift_dates))
    cursor.execute(
        f"""
        SELECT shift_date_et, bag_id, effective_status, pre_weight_lbs
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et IN ({ph})
          AND service_type = 'WF'
        """,
        (int(organization_id), *shift_dates),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if not _is_completed_status(row.get("effective_status")):
            continue
        day = row.get("shift_date_et")
        if not isinstance(day, date) or day not in by_day:
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        by_day[day].append(
            {
                "bag_id": bid,
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "effective_status": row.get("effective_status"),
            }
        )
    return by_day


def simulate_split_cost(
    *,
    total_orders: int,
    split_rate: float,
    avg_lb_per_bag: float,
    combinations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pure simulation — no DB. Split rate applied uniformly across combinations."""
    orders = max(0, int(total_orders))
    rate = max(0.0, min(1.0, float(split_rate)))
    avg_lb = max(0.0, float(avg_lb_per_bag))

    split_orders = round(orders * rate)
    if split_orders > orders:
        split_orders = orders
    non_split_orders = orders - split_orders
    total_loads = non_split_orders + (split_orders * 2)
    estimated_lbs = round(orders * avg_lb, 1)

    raw = []
    for c in combinations or []:
        share = float(c.get("share") or 0)
        if share < 0:
            share = 0.0
        raw.append((c, share))
    share_sum = sum(s for _, s in raw) or 1.0

    combo_rows: list[dict[str, Any]] = []
    total_cost = 0.0
    assigned = 0
    for i, (c, share) in enumerate(raw):
        norm = share / share_sum
        if i == len(raw) - 1:
            c_orders = max(0, orders - assigned)
        else:
            c_orders = int(round(orders * norm))
            assigned += c_orders
        c_split = int(round(c_orders * rate))
        if c_split > c_orders:
            c_split = c_orders
        c_non = c_orders - c_split
        c_loads = c_non + (c_split * 2)
        cpl = _money(c.get("cost_per_load")) or 0.0
        c_cost = round(c_loads * cpl, 2)
        total_cost += c_cost
        combo_rows.append(
            {
                "key": c.get("key") or c.get("label"),
                "label": c.get("label") or c.get("key"),
                "short_label": c.get("short_label") or c.get("label") or c.get("key"),
                "share": round(norm, 6),
                "share_pct": round(norm * 100.0, 2),
                "estimated_orders": c_orders,
                "split_orders": c_split,
                "non_split_orders": c_non,
                "estimated_loads": c_loads,
                "cost_per_load": cpl,
                "cost_per_split_order": round(cpl * 2, 4),
                "estimated_cost": c_cost,
                "products": list(c.get("products") or []),
            }
        )

    total_cost = round(total_cost, 2)
    cost_per_order = round(total_cost / orders, 4) if orders else None
    cost_per_load = round(total_cost / total_loads, 4) if total_loads else None
    cost_per_lb = (
        round(total_cost / estimated_lbs, 4) if estimated_lbs and estimated_lbs > 0 else None
    )

    return {
        "simulation": True,
        "estimated": True,
        "total_orders": orders,
        "split_rate": rate,
        "split_pct": round(rate * 100.0, 2),
        "split_orders": split_orders,
        "non_split_orders": non_split_orders,
        "total_loads": total_loads,
        "avg_lb_per_bag": round(avg_lb, 2),
        "estimated_lbs": estimated_lbs,
        "estimated_supply_cost": total_cost,
        "cost_per_order": cost_per_order,
        "cost_per_load": cost_per_load,
        "est_cost_per_lb": cost_per_lb,
        "combinations": combo_rows,
        "assumption": (
            "Split rate applied uniformly across all supply combinations."
        ),
    }


def compare_baseline_target(
    baseline: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    shifts_per_week: float = 7.0,
) -> dict[str, Any]:
    b_loads = int(baseline.get("total_loads") or 0)
    t_loads = int(target.get("total_loads") or 0)
    b_cost = float(baseline.get("estimated_supply_cost") or 0)
    t_cost = float(target.get("estimated_supply_cost") or 0)
    loads_saved = b_loads - t_loads
    dollar_savings = round(b_cost - t_cost, 2)
    savings_pct = (
        round((dollar_savings / b_cost) * 100.0, 2) if b_cost > 0 else None
    )
    periods = period_savings(dollar_savings, shifts_per_week=shifts_per_week)
    return {
        "baseline": dict(baseline),
        "target": dict(target),
        "loads_saved": loads_saved,
        "dollar_savings": dollar_savings,
        "savings_pct": savings_pct,
        "period_savings": periods,
        "headline": {
            "split_pct_from": baseline.get("split_pct"),
            "split_pct_to": target.get("split_pct"),
            "loads_saved": loads_saved,
            "dollar_savings": dollar_savings,
            "est_cost_per_lb_from": baseline.get("est_cost_per_lb"),
            "est_cost_per_lb_to": target.get("est_cost_per_lb"),
            "per_week": periods["per_week"],
            "per_month": periods["per_month"],
        },
        "labels": {
            "est_cost_per_lb": (
                "EST. COST / LB — planning metric from PRE avg lb/bag; "
                "not live Cost / Completed Lb (POST)"
            ),
        },
    }


def _product_cost_map(
    cursor,
    organization_id: int,
    *,
    as_of: date,
) -> dict[str, dict[str, Any]]:
    try:
        products = list_supply_products(
            cursor, int(organization_id), active_only=True, as_of=as_of
        )
    except Exception:
        products = []
    by_legacy: dict[str, dict[str, Any]] = {}
    for p in products or []:
        legacy = str(p.get("legacy_report_key") or "").strip()
        if not legacy:
            continue
        by_legacy[legacy] = {
            "legacy_report_key": legacy,
            "label": str(p.get("product_name") or p.get("brand") or legacy),
            "brand": p.get("brand"),
            "product_name": p.get("product_name"),
            "supply_type": str(p.get("supply_type") or "").upper(),
            "average_dose": _qty(p.get("average_dose")),
            "dose_unit": p.get("dose_unit") or "oz",
            "cost_per_dose": _money(p.get("cost_per_dose")),
        }
    return by_legacy


def _combo_cost_per_load(
    supplies: Sequence[str],
    product_by_legacy: Mapping[str, Mapping[str, Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    parts: list[dict[str, Any]] = []
    total = 0.0
    any_cost = False
    for legacy in supplies:
        meta = product_by_legacy.get(legacy) or {
            "legacy_report_key": legacy,
            "label": legacy,
            "cost_per_dose": None,
            "average_dose": None,
            "dose_unit": "oz",
        }
        cpd = _money(meta.get("cost_per_dose"))
        parts.append(
            {
                "legacy_report_key": legacy,
                "label": meta.get("label") or legacy,
                "cost_per_dose": cpd,
                "average_dose": meta.get("average_dose"),
                "dose_unit": meta.get("dose_unit") or "oz",
            }
        )
        if cpd is not None:
            total += float(cpd)
            any_cost = True
    return (round(total, 4) if any_cost else None, parts)


def _classify_order_supplies(
    supplies: Sequence[str],
    product_by_legacy: Mapping[str, Mapping[str, Any]],
) -> tuple[str, bool, bool]:
    """Return (detergent_kind standard|hypo, has_downy, has_oxi)."""
    detergent = "standard"
    has_downy = False
    has_oxi = False
    saw_detergent = False
    for legacy in supplies:
        meta = product_by_legacy.get(legacy) or {}
        st = str(meta.get("supply_type") or "").upper()
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
            saw_detergent = True
        elif st == SUPPLY_TYPE_DETERGENT:
            if not saw_detergent:
                detergent = "standard"
            saw_detergent = True
    return detergent, has_downy, has_oxi


def _build_order_mix(
    *,
    total_orders: int,
    standard_n: int,
    hypo_n: int,
    downy_n: int,
    oxi_n: int,
    no_addon_n: int,
    both_addon_n: int,
) -> dict[str, Any]:
    denom = max(int(total_orders), 1)

    def pct(n: int) -> float:
        return round((n / denom) * 100.0, 2)

    return {
        "basis": "orders",
        "note": (
            "Percentages of ORDERS (one bag = one order even if split). "
            "Not loads or doses."
        ),
        "total_completed_wf_orders": int(total_orders),
        "detergent_standard_order_pct": pct(standard_n),
        "detergent_hypo_order_pct": pct(hypo_n),
        "detergent_standard_orders": standard_n,
        "detergent_hypo_orders": hypo_n,
        "downy_order_pct": pct(downy_n),
        "oxiclean_order_pct": pct(oxi_n),
        "no_addon_order_pct": pct(no_addon_n),
        "downy_and_oxi_order_pct": pct(both_addon_n),
        "downy_orders": downy_n,
        "oxiclean_orders": oxi_n,
        "no_addon_orders": no_addon_n,
        "downy_and_oxi_orders": both_addon_n,
    }


def _compute_baseline(
    cursor,
    organization_id: int,
    *,
    window_days: int,
    as_of_prices: date,
) -> dict[str, Any]:
    """Heavy path — called only on cache miss."""
    from backend.management_rinse_wf_supplies import _load_si_metadata_fast

    window = int(window_days) if int(window_days) in VALID_WINDOWS else WINDOW_7
    price_as_of = as_of_prices
    org = int(organization_id)

    closed_days = list_closed_shift_dates(cursor, org, limit=window)
    product_by_legacy = _product_cost_map(cursor, org, as_of=price_as_of)
    try:
        rules = get_supply_usage_mapping_rules(cursor, org)
    except Exception:
        rules = []

    bags_by_day = _load_completed_wf_bags_multi(cursor, org, closed_days)
    all_ids: list[str] = []
    for day in closed_days:
        all_ids.extend(b["bag_id"] for b in bags_by_day.get(day) or [])
    # Dedup for SI load (same bag across days is rare but possible)
    unique_ids = sorted(set(all_ids))
    meta_all = (
        _load_si_metadata_fast(cursor, org, unique_ids) if unique_ids else {}
    )

    bag_count = 0
    pre_sum = 0.0
    pre_n = 0
    finalized = 0
    split_yes = 0
    split_no = 0
    mix_counter: Counter[str] = Counter()
    standard_n = hypo_n = downy_n = oxi_n = no_addon_n = both_addon_n = 0

    for day in closed_days:
        bags = bags_by_day.get(day) or []
        ids = [b["bag_id"] for b in bags]
        for b in bags:
            bag_count += 1
            try:
                pre = (
                    float(b["pre_weight_lbs"])
                    if b.get("pre_weight_lbs") is not None
                    else None
                )
            except (TypeError, ValueError):
                pre = None
            if pre is not None:
                pre_sum += pre
                pre_n += 1

        evaluations: dict[str, dict[str, Any]] = {}
        if ids:
            evaluations = evaluate_day_wf_splits(
                cursor,
                org,
                day,
                ids,
                slim_events=True,
                truncate_to_selected_day=True,
            )

        for bid in ids:
            ev = evaluations.get(bid) or {}
            if ev.get("split_finalized"):
                finalized += 1
                if ev.get("canonical_split") is True:
                    split_yes += 1
                else:
                    split_no += 1
            m = meta_all.get(bid) or {}
            raw_si = m.get("special_instructions_raw")
            mapped = supplies_for_usage(raw_si, rules)
            supplies = list((mapped or {}).get("supplies_used") or [LEGACY_KEY_TIDE])
            if not supplies:
                supplies = [LEGACY_KEY_TIDE]
            mix_counter[combo_key_from_supplies(supplies)] += 1
            kind, has_downy, has_oxi = _classify_order_supplies(
                supplies, product_by_legacy
            )
            if kind == "hypo":
                hypo_n += 1
            else:
                standard_n += 1
            if has_downy:
                downy_n += 1
            if has_oxi:
                oxi_n += 1
            if has_downy and has_oxi:
                both_addon_n += 1
            if not has_downy and not has_oxi:
                no_addon_n += 1

    avg_lb = round(pre_sum / pre_n, 2) if pre_n else None
    split_rate = (split_yes / finalized) if finalized else 0.0
    mix_total = sum(mix_counter.values()) or 1

    combinations: list[dict[str, Any]] = []
    for key, n in mix_counter.most_common():
        if " + " in key:
            supplies = [p.strip() for p in key.split(" + ") if p.strip()]
        else:
            supplies = [key] if key else [LEGACY_KEY_TIDE]
        cpl, products = _combo_cost_per_load(supplies, product_by_legacy)
        share = n / mix_total
        short = short_combo_label(key, product_by_legacy)
        combinations.append(
            {
                "key": key,
                "label": short,
                "short_label": short,
                "full_label": key,
                "order_count": n,
                "share": round(share, 6),
                "share_pct": round(share * 100.0, 2),
                "cost_per_load": cpl,
                "cost_per_split_order": round(cpl * 2, 4) if cpl is not None else None,
                # Keep product dose lines for detail sheet only (still compact).
                "products": products,
            }
        )

    cost_ref = [
        {
            "key": c["key"],
            "label": c["short_label"],
            "cost_per_load": c["cost_per_load"],
            "cost_per_split_order": c["cost_per_split_order"],
        }
        for c in combinations
        if c.get("cost_per_load") is not None
    ]

    order_mix = _build_order_mix(
        total_orders=bag_count,
        standard_n=standard_n,
        hypo_n=hypo_n,
        downy_n=downy_n,
        oxi_n=oxi_n,
        no_addon_n=no_addon_n,
        both_addon_n=both_addon_n,
    )

    return {
        "available": bool(closed_days),
        "read_only": True,
        "estimated": True,
        "window_days": window,
        "price_as_of_et": price_as_of.isoformat(),
        "basis": {
            "label": f"{window}-Day Baseline",
            "days_used": len(closed_days),
            "dates_et": [d.isoformat() for d in closed_days],
            "completed_bags": bag_count,
            "total_completed_wf_orders": bag_count,
            "pre_lbs_total": round(pre_sum, 1) if pre_n else None,
            "total_pre_lbs": round(pre_sum, 1) if pre_n else None,
            "bags_with_pre": pre_n,
            "avg_lb_per_bag": avg_lb,
            "avg_pre_lb_per_bag": avg_lb,
            "avg_lb_basis": "weighted_pre_lbs_over_bags_with_pre",
            "finalized_orders": finalized,
            "split_orders": split_yes,
            "not_split_orders": split_no,
            "split_rate": round(split_rate, 6),
            "split_pct": round(split_rate * 100.0, 2),
            "finalized_split_rate": round(split_rate, 6),
            "note": (
                "Last completed/closed ET business days only — "
                "today's in-progress day is excluded."
            ),
        },
        "order_mix": order_mix,
        "combinations": combinations,
        "cost_per_load_reference": cost_ref,
        "defaults": {
            "split_pct": round(split_rate * 100.0, 2),
            "avg_lb_per_bag": avg_lb,
            "avg_lb_mode": f"last_{window}",
            "shifts_per_week": 7,
        },
        "assumption": (
            "V1 applies the overall split rate uniformly across all "
            "supply combinations."
        ),
        "labels": {
            "est_cost_per_lb": "EST. COST / LB",
            "disclaimer": (
                "Planning simulation using PRE avg lb/bag. Separate from live "
                "Cost / Completed Lb (actual POST)."
            ),
            "order_mix": "Order % — not loads or doses",
        },
    }


def build_split_cost_simulator_baseline(
    cursor,
    organization_id: int,
    *,
    window_days: int = WINDOW_7,
    as_of_prices: date | None = None,
    today_workload_orders: int | None = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Weighted historical baseline from last N CLOSED ET business days."""
    window = int(window_days) if int(window_days) in VALID_WINDOWS else WINDOW_7
    price_as_of = as_of_prices or business_today()
    org = int(organization_id)
    # Cutoff date is part of the key so midnight ET rotates naturally.
    cache_key = (org, window, price_as_of.isoformat(), business_today().isoformat())

    cached_hit = False
    payload: dict[str, Any] | None = None
    if not bypass_cache:
        hit = _BASELINE_CACHE.get(cache_key)
        if hit and (time.monotonic() - hit[0]) < _BASELINE_CACHE_TTL_SEC:
            payload = copy.deepcopy(hit[1])
            cached_hit = True

    if payload is None:
        payload = _compute_baseline(
            cursor, org, window_days=window, as_of_prices=price_as_of
        )
        _BASELINE_CACHE[cache_key] = (time.monotonic(), copy.deepcopy(payload))
        # Bound cache size
        while len(_BASELINE_CACHE) > _BASELINE_CACHE_MAX:
            oldest = min(_BASELINE_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _BASELINE_CACHE.pop(oldest, None)

    # today_orders is request-specific — apply after cache
    bag_count = int((payload.get("basis") or {}).get("completed_bags") or 0)
    days_used = int((payload.get("basis") or {}).get("days_used") or 1) or 1
    defaults = dict(payload.get("defaults") or {})
    defaults["total_orders"] = (
        int(today_workload_orders)
        if today_workload_orders is not None
        else (bag_count // days_used if days_used else 100)
    )
    out = dict(payload)
    out["defaults"] = defaults
    out["cached"] = cached_hit
    return out


def run_split_cost_simulation(
    baseline: Mapping[str, Any],
    *,
    total_orders: int,
    baseline_split_pct: float,
    target_split_pct: float,
    avg_lb_per_bag: float,
    shifts_per_week: float = 7.0,
) -> dict[str, Any]:
    combos = baseline.get("combinations") or []
    b = simulate_split_cost(
        total_orders=total_orders,
        split_rate=float(baseline_split_pct) / 100.0,
        avg_lb_per_bag=avg_lb_per_bag,
        combinations=combos,
    )
    t = simulate_split_cost(
        total_orders=total_orders,
        split_rate=float(target_split_pct) / 100.0,
        avg_lb_per_bag=avg_lb_per_bag,
        combinations=combos,
    )
    return {
        **compare_baseline_target(b, t, shifts_per_week=shifts_per_week),
        "historical_basis": baseline.get("basis"),
        "order_mix": baseline.get("order_mix"),
        "cost_per_load_reference": baseline.get("cost_per_load_reference"),
        "assumption": baseline.get("assumption"),
        "labels": baseline.get("labels"),
        "read_only": True,
        "estimated": True,
    }
