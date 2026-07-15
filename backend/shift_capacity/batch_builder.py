"""Weight-aware and bag-count-aware batch construction."""

from __future__ import annotations

from backend.shift_capacity.models import Bag, Batch, BatchOverride, SimulationInputs
from backend.shift_capacity.validation import validate_batch_override


def expand_bags(inp: SimulationInputs) -> list[Bag]:
    bags: list[Bag] = []
    for order in inp.orders:
        n = max(1, int(order.bag_count))
        weights: list[float] = []
        sources: list[str] = []
        if order.bags:
            for i in range(n):
                spec = order.bags[i] if i < len(order.bags) else None
                if spec and spec.weight_lb is not None:
                    weights.append(float(spec.weight_lb))
                    sources.append("exact")
                elif i < len(order.bag_weights):
                    weights.append(float(order.bag_weights[i]))
                    sources.append("exact")
                elif order.total_weight_lb:
                    weights.append(float(order.total_weight_lb) / n)
                    sources.append("estimated")
                else:
                    weights.append(float(inp.shift.avg_lbs_per_bag))
                    sources.append("estimated")
        else:
            if order.bag_weights and len(order.bag_weights) >= n:
                weights = [float(x) for x in order.bag_weights[:n]]
                sources = ["exact"] * n
            elif order.total_weight_lb:
                each = float(order.total_weight_lb) / n
                weights = [each] * n
                sources = ["estimated"] * n
            else:
                base = list(order.bag_weights)
                while len(base) < n:
                    base.append(inp.shift.avg_lbs_per_bag)
                weights = [float(x) for x in base[:n]]
                sources = ["exact" if order.bag_weights else "estimated"] * n

        for i in range(n):
            spec = order.bags[i] if order.bags and i < len(order.bags) else None
            bag_id = (spec.bag_id if spec and spec.bag_id else None) or f"{order.order_id}-{i + 1}"
            bags.append(
                Bag(
                    bag_id=bag_id,
                    order_id=order.order_id,
                    sequence_in_order=i + 1,
                    weight_lb=float(weights[i]),
                    weight_source=sources[i],  # type: ignore[arg-type]
                    priority=spec.priority if spec else order.priority,
                    rush=bool(spec.rush if spec else order.rush),
                    requires_two_washers=order.requires_two_washers,
                    requires_two_dryers=order.requires_two_dryers,
                    required_by=order.required_by_min,
                    manual_batch_lock=spec.manual_batch_lock if spec else None,
                )
            )
    return bags


def effective_override(overrides: list[BatchOverride], batch_number: int) -> BatchOverride | None:
    exact = [o for o in overrides if o.batch_number == batch_number]
    if exact:
        return exact[-1]
    cascading = [
        o
        for o in overrides
        if o.batch_number <= batch_number and o.apply_scope in ("from_this_batch", "all_future_unlocked")
    ]
    return cascading[-1] if cascading else None


def batch_fits(
    group: list[Bag],
    candidate: Bag,
    *,
    batch_size: int,
    max_pounds: float,
    dryer_capacity: float,
    mode: str,
) -> bool:
    if not group:
        return True
    next_count = len(group) + 1
    next_lbs = sum(b.weight_lb for b in group) + candidate.weight_lb
    if next_lbs > dryer_capacity + 1e-6:
        return False
    if mode == "bags":
        return next_count <= batch_size
    if mode == "pounds":
        return next_lbs <= max_pounds + 1e-6
    # whichever_first
    return next_count <= batch_size and next_lbs <= max_pounds + 1e-6


def build_batches(
    bags: list[Bag],
    inp: SimulationInputs,
    *,
    locked_batches: list[Batch] | None = None,
    skip_bag_ids: set[str] | None = None,
) -> tuple[list[Batch], list]:
    """Build batches for bags that are not already locked. Returns (batches, validation_errors)."""
    from backend.shift_capacity.models import ValidationError

    errors: list[ValidationError] = []
    bags_by_id = {b.bag_id: b for b in bags}
    washers = [m.machine_id for m in inp.machines if m.kind == "washer"]
    dryers = [m.machine_id for m in inp.machines if m.kind == "dryer"]

    for override in inp.batch_overrides:
        result = validate_batch_override(
            override,
            bags_by_id=bags_by_id,
            employees=inp.employees,
            washers=washers,
            dryers=dryers,
            washer_capacity=inp.shift.washer_capacity_lb,
            frozen_through=inp.continue_from_min if inp.mode == "continue_from_time" else None,
        )
        if not result.accepted:
            errors.extend(result.errors)

    if errors:
        return list(locked_batches or []), errors

    batches: list[Batch] = list(locked_batches or [])
    used = set(skip_bag_ids or [])
    for batch in batches:
        used.update(batch.bag_ids)
        for bid in batch.bag_ids:
            bag = bags_by_id.get(bid)
            if bag:
                bag.batch_id = batch.batch_id
                bag.batch_sequence = batch.sequence

    # Sort eligibility: rush first, priority, then sort_end, order, bag
    eligible = [
        b
        for b in bags
        if b.bag_id not in used and b.sort_end is not None
    ]
    eligible.sort(
        key=lambda b: (
            0 if b.rush else 1,
            b.priority,
            b.sort_end or 0,
            b.order_id,
            b.sequence_in_order,
            b.bag_id,
        )
    )
    queue = list(eligible)
    batch_num = (max((b.sequence for b in batches), default=0) + 1)

    while queue:
        override = effective_override(inp.batch_overrides, batch_num)
        group: list[Bag] = []
        explicit_ids = override.bag_ids if override and override.apply_scope == "this_batch_only" and override.bag_ids else None
        excluded = set(override.excluded_bag_ids or []) if override else set()

        if explicit_ids:
            wanted = set(explicit_ids)
            group = [b for b in queue if b.bag_id in wanted]
            queue = [b for b in queue if b.bag_id not in wanted]
            if not group:
                errors.append(ValidationError("EMPTY_BATCH", f"Batch {batch_num} has no selected bags"))
                break
        else:
            size = override.batch_size if override and override.batch_size else inp.shift.batch_size
            cap = override.max_pounds if override and override.max_pounds is not None else inp.shift.washer_capacity_lb
            while queue:
                candidate = queue[0]
                if candidate.bag_id in excluded:
                    queue.pop(0)
                    continue
                if candidate.manual_batch_lock and candidate.manual_batch_lock != batch_num and not group:
                    # Hold locked bag for its batch number
                    if candidate.manual_batch_lock > batch_num:
                        break
                if group and not batch_fits(
                    group,
                    candidate,
                    batch_size=size,
                    max_pounds=cap,
                    dryer_capacity=inp.shift.dryer_capacity_lb,
                    mode=inp.shift.batch_limit_mode,
                ):
                    break
                group.append(queue.pop(0))
                lbs = sum(b.weight_lb for b in group)
                if inp.shift.batch_limit_mode in ("pounds", "whichever_first") and lbs >= cap - 1e-6:
                    break
                if len(group) >= size and inp.shift.batch_limit_mode in ("bags", "whichever_first"):
                    break
            if not group:
                # Skip a stuck locked bag to avoid infinite loop
                if queue and queue[0].manual_batch_lock and queue[0].manual_batch_lock != batch_num:
                    batch_num = queue[0].manual_batch_lock
                    continue
                break

        size = override.batch_size if override and override.batch_size else inp.shift.batch_size
        cap = override.max_pounds if override and override.max_pounds is not None else inp.shift.washer_capacity_lb
        total_lbs = round(sum(b.weight_lb for b in group), 2)
        if total_lbs > cap + 1e-6:
            errors.append(
                ValidationError(
                    "OVERWEIGHT_BATCH",
                    f"Batch {batch_num} exceeds washer capacity ({total_lbs:.1f} lb > {cap:.1f} lb)",
                    {"batch_number": batch_num, "total_weight_lb": total_lbs, "capacity_lb": cap},
                )
            )
            break

        batch = Batch(
            batch_id=f"B{batch_num}",
            sequence=batch_num,
            bag_ids=[b.bag_id for b in group],
            order_ids=sorted({b.order_id for b in group}),
            total_bags=len(group),
            total_weight_lb=total_lbs,
            locked=bool(override.locked) if override else False,
            override_source=f"override:{override.batch_number}" if override else None,
            provenance="manual_override" if override else "recalculated",
        )
        for b in group:
            b.batch_id = batch.batch_id
            b.batch_sequence = batch.sequence
            b.available_to_wash = max((x.sort_end or 0) for x in group)
        batches.append(batch)
        batch_num += 1

    return batches, errors


def split_bags_by_weight(bags: list[Bag], parts: int) -> list[list[Bag]]:
    if parts <= 1 or len(bags) <= 1:
        return [bags]
    ordered = sorted(bags, key=lambda b: b.weight_lb, reverse=True)
    groups = [[] for _ in range(parts)]  # type: ignore[var-annotated]
    loads = [0.0] * parts
    for bag in ordered:
        idx = loads.index(min(loads))
        groups[idx].append(bag)
        loads[idx] += bag.weight_lb
    return [g for g in groups if g]
