"""Split Cost Simulator V1 — forward planning only (read-only).

Isolated from live Supply Cost dashboard formulas.
Historical baseline uses CLOSED ET business days only (not today-in-progress).
Avg lb/bag uses canonical PRE weight only (never POST).
Pricing uses current effective Supply Master (forward-looking).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.rinse_bag_registry import normalize_bag_id
from backend.rinse_veewash_shift_day import STATUS_CLOSED
from backend.rinse_wf_canonical_split import evaluate_day_wf_splits
from backend.supply_product_master import list_supply_products
from backend.supply_usage import get_supply_usage_mapping_rules, supplies_for_usage
from backend.ta_helpers import table_exists

WINDOW_7 = 7
WINDOW_30 = 30
VALID_WINDOWS = frozenset({WINDOW_7, WINDOW_30})


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
    return " + ".join(parts) if parts else "Tide"


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


def _load_completed_wf_bags(
    cursor,
    organization_id: int,
    shift_date_et: date,
) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT bag_id, effective_status, pre_weight_lbs, service_type
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s
          AND shift_date_et = %s
          AND service_type = 'WF'
        """,
        (int(organization_id), shift_date_et),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if not _is_completed_status(row.get("effective_status")):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid:
            continue
        out.append(
            {
                "bag_id": bid,
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "effective_status": row.get("effective_status"),
            }
        )
    return out


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
    # Keep identity: split + non_split = orders
    if split_orders > orders:
        split_orders = orders
    non_split_orders = orders - split_orders
    total_loads = non_split_orders + (split_orders * 2)
    estimated_lbs = round(orders * avg_lb, 1)

    # Normalize shares
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
    return {
        "baseline": dict(baseline),
        "target": dict(target),
        "loads_saved": loads_saved,
        "dollar_savings": dollar_savings,
        "savings_pct": savings_pct,
        "headline": {
            "split_pct_from": baseline.get("split_pct"),
            "split_pct_to": target.get("split_pct"),
            "loads_saved": loads_saved,
            "dollar_savings": dollar_savings,
            "est_cost_per_lb_from": baseline.get("est_cost_per_lb"),
            "est_cost_per_lb_to": target.get("est_cost_per_lb"),
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


def build_split_cost_simulator_baseline(
    cursor,
    organization_id: int,
    *,
    window_days: int = WINDOW_7,
    as_of_prices: date | None = None,
    today_workload_orders: int | None = None,
) -> dict[str, Any]:
    """Weighted historical baseline from last N CLOSED ET business days."""
    from backend.management_rinse_wf_supplies import _load_si_metadata_fast

    window = int(window_days) if int(window_days) in VALID_WINDOWS else WINDOW_7
    price_as_of = as_of_prices or business_today()
    org = int(organization_id)

    closed_days = list_closed_shift_dates(cursor, org, limit=window)
    product_by_legacy = _product_cost_map(cursor, org, as_of=price_as_of)
    try:
        rules = get_supply_usage_mapping_rules(cursor, org)
    except Exception:
        rules = []

    bag_count = 0
    pre_sum = 0.0
    pre_n = 0
    finalized = 0
    split_yes = 0
    split_no = 0
    mix_counter: Counter[str] = Counter()
    day_summaries: list[dict[str, Any]] = []

    for day in closed_days:
        bags = _load_completed_wf_bags(cursor, org, day)
        ids = [b["bag_id"] for b in bags]
        day_bags = len(ids)
        day_pre = 0.0
        day_pre_n = 0
        for b in bags:
            bag_count += 1
            try:
                pre = float(b["pre_weight_lbs"]) if b.get("pre_weight_lbs") is not None else None
            except (TypeError, ValueError):
                pre = None
            if pre is not None:
                pre_sum += pre
                pre_n += 1
                day_pre += pre
                day_pre_n += 1

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

        day_split = 0
        day_not = 0
        day_final = 0
        meta = _load_si_metadata_fast(cursor, org, ids) if ids else {}
        for bid in ids:
            ev = evaluations.get(bid) or {}
            if ev.get("split_finalized"):
                day_final += 1
                finalized += 1
                if ev.get("canonical_split") is True:
                    day_split += 1
                    split_yes += 1
                else:
                    day_not += 1
                    split_no += 1
            raw_si = None
            m = meta.get(bid) or {}
            raw_si = m.get("special_instructions_raw")
            mapped = supplies_for_usage(raw_si, rules)
            supplies = list((mapped or {}).get("supplies_used") or ["Tide"])
            if not supplies:
                supplies = ["Tide"]
            mix_counter[combo_key_from_supplies(supplies)] += 1

        day_summaries.append(
            {
                "date_et": day.isoformat(),
                "completed_bags": day_bags,
                "pre_lbs": round(day_pre, 1) if day_pre_n else None,
                "finalized_split_orders": day_final,
                "split_orders": day_split,
                "not_split_orders": day_not,
            }
        )

    # Weighted: Σ PRE lbs / Σ bags with PRE (never average-of-daily-averages).
    avg_lb = round(pre_sum / pre_n, 2) if pre_n else None
    # Weighted split among finalized only
    split_rate = (split_yes / finalized) if finalized else 0.0
    mix_total = sum(mix_counter.values()) or 1

    combinations: list[dict[str, Any]] = []
    for key, n in mix_counter.most_common():
        supplies = [p.strip() for p in key.split("+")]
        supplies = [p for p in supplies if p]
        # key already "A + B" form
        if " + " in key:
            supplies = [p.strip() for p in key.split(" + ") if p.strip()]
        cpl, products = _combo_cost_per_load(supplies, product_by_legacy)
        share = n / mix_total
        combinations.append(
            {
                "key": key,
                "label": key,
                "order_count": n,
                "share": round(share, 6),
                "share_pct": round(share * 100.0, 2),
                "cost_per_load": cpl,
                "cost_per_split_order": round(cpl * 2, 4) if cpl is not None else None,
                "products": products,
            }
        )

    # Cost-per-load reference (unique combos)
    cost_ref = [
        {
            "label": c["label"],
            "cost_per_load": c["cost_per_load"],
            "cost_per_split_order": c["cost_per_split_order"],
            "products": c["products"],
        }
        for c in combinations
        if c.get("cost_per_load") is not None
    ]

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
            "day_summaries": day_summaries,
            "completed_bags": bag_count,
            "pre_lbs_total": round(pre_sum, 1) if pre_n else None,
            "bags_with_pre": pre_n,
            "avg_lb_per_bag": avg_lb,
            "avg_lb_basis": "weighted_pre_lbs_over_bags_with_pre",
            "finalized_orders": finalized,
            "split_orders": split_yes,
            "not_split_orders": split_no,
            "split_rate": round(split_rate, 6),
            "split_pct": round(split_rate * 100.0, 2),
            "note": (
                "Last completed/closed ET business days only — "
                "today's in-progress day is excluded."
            ),
        },
        "combinations": combinations,
        "cost_per_load_reference": cost_ref,
        "products": list(product_by_legacy.values()),
        "defaults": {
            "total_orders": int(today_workload_orders)
            if today_workload_orders is not None
            else bag_count // max(len(closed_days), 1) if closed_days else 100,
            "split_pct": round(split_rate * 100.0, 2),
            "avg_lb_per_bag": avg_lb,
            "avg_lb_mode": f"last_{window}",
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
        },
    }


def run_split_cost_simulation(
    baseline: Mapping[str, Any],
    *,
    total_orders: int,
    baseline_split_pct: float,
    target_split_pct: float,
    avg_lb_per_bag: float,
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
        **compare_baseline_target(b, t),
        "historical_basis": baseline.get("basis"),
        "cost_per_load_reference": baseline.get("cost_per_load_reference"),
        "assumption": baseline.get("assumption"),
        "labels": baseline.get("labels"),
        "read_only": True,
        "estimated": True,
    }
