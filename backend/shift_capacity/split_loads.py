"""Deterministic 2-washer / 2-dryer split assignment for management planning.

Matches the legacy planner convention: N of bag_count bags require two machine
positions. Assignment is ordered (first N), never random.
"""

from __future__ import annotations

from typing import Any


# Validated planner default: 80% of bags/orders use 2 machines (40 of 50).
DEFAULT_TWO_MACHINE_SPLIT_PCT = 80.0


def default_two_machine_count(bag_count: int) -> int:
    n = max(0, int(bag_count))
    return min(n, int(round(n * DEFAULT_TWO_MACHINE_SPLIT_PCT / 100.0)))


def parse_split_count(
    raw_count: Any,
    raw_pct: Any,
    *,
    bag_count: int,
    count_name: str,
    pct_name: str,
    default_count: int | None = None,
) -> int:
    """Parse absolute count or percentage into an integer bag count in [0, bag_count]."""
    n_bags = max(0, int(bag_count))
    if default_count is None:
        default_count = 0
    has_count = raw_count is not None and str(raw_count).strip() != ""
    has_pct = raw_pct is not None and str(raw_pct).strip() != ""
    if has_count and has_pct:
        raise ValueError(f"Provide either {count_name} or {pct_name}, not both")
    if has_count:
        try:
            n = int(float(raw_count))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{count_name} must be a whole number") from exc
        if n < 0:
            raise ValueError(f"{count_name} must be >= 0")
    elif has_pct:
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{pct_name} must be a number") from exc
        if pct < 0:
            raise ValueError(f"{pct_name} must be >= 0")
        if pct > 100.0001:
            raise ValueError(f"{pct_name} must be <= 100")
        n = int(round(n_bags * pct / 100.0))
    else:
        n = int(default_count)
    if n > n_bags:
        raise ValueError(f"{count_name} must be <= bag_count ({n_bags})")
    return n


def deterministic_two_machine_flags(bag_count: int, orders_using_2: int) -> list[bool]:
    """First N bags True, remainder False — stable across repeated simulations."""
    n_bags = max(0, int(bag_count))
    n_two = max(0, min(n_bags, int(orders_using_2)))
    return [True] * n_two + [False] * (n_bags - n_two)


def resolve_management_split_counts(raw: dict[str, Any], bag_count: int) -> tuple[int, int]:
    """Resolve washer/dryer split counts for management_mode synthetic bags.

    Accepts management field names and legacy planner aliases.
    Default when omitted: validated 80% (same as legacy planner).
    """
    default_n = default_two_machine_count(bag_count)
    wash_n = parse_split_count(
        raw.get("bags_using_2_washers")
        if raw.get("bags_using_2_washers") is not None
        else raw.get("orders_using_2_washers"),
        raw.get("two_washer_split_pct")
        if raw.get("two_washer_split_pct") is not None
        else raw.get("orders_using_2_washers_pct"),
        bag_count=bag_count,
        count_name="bags_using_2_washers",
        pct_name="two_washer_split_pct",
        default_count=default_n,
    )
    dry_n = parse_split_count(
        raw.get("bags_using_2_dryers")
        if raw.get("bags_using_2_dryers") is not None
        else raw.get("orders_using_2_dryers"),
        raw.get("two_dryer_split_pct")
        if raw.get("two_dryer_split_pct") is not None
        else raw.get("orders_using_2_dryers_pct"),
        bag_count=bag_count,
        count_name="bags_using_2_dryers",
        pct_name="two_dryer_split_pct",
        default_count=default_n,
    )
    return wash_n, dry_n
