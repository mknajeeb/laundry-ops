"""Simulation-backed recommendations — every suggestion is run before/after."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from backend.shift_capacity.models import SimulationState
from backend.shift_capacity.summaries import compute_kpis
from backend.shift_capacity.validation import label_minutes


RunFn = Callable[[dict[str, Any]], SimulationState]


def build_recommendations(
    state: SimulationState,
    raw_inputs: dict[str, Any],
    run_fn: RunFn,
) -> list[dict[str, Any]]:
    kpis = compute_kpis(state)
    recs: list[dict[str, Any]] = []

    # Candidate: add washer person mid-shift if washer wait is high
    avg_wash_wait = float(kpis.get("average_bag_wait_for_washer") or 0)
    if avg_wash_wait >= 5:
        inject_at = state.inputs.shift.start_min + 90 * 60
        rec = _try_staff_injection(
            raw_inputs,
            run_fn,
            baseline_kpis=kpis,
            role="washer",
            inject_at=inject_at,
            title=f"Add washer person at {label_minutes(inject_at)}",
            reason=f"Average washer wait is {avg_wash_wait} min",
            rec_type="ADD_WASHER_PERSON",
        )
        if rec:
            recs.append(rec)

    avg_folder_wait = float(kpis.get("average_bag_wait_for_folder") or 0)
    if avg_folder_wait >= 8 or int(kpis.get("maximum_fold_backlog") or 0) >= 4:
        inject_at = state.inputs.shift.start_min + 120 * 60
        rec = _try_staff_injection(
            raw_inputs,
            run_fn,
            baseline_kpis=kpis,
            role="folder",
            inject_at=inject_at,
            title=f"Add folder at {label_minutes(inject_at)}",
            reason=f"Folder wait {avg_folder_wait} min / backlog {kpis.get('maximum_fold_backlog')}",
            rec_type="ADD_FOLDER",
        )
        if rec:
            recs.append(rec)

    sorter_util = float(kpis.get("sorter_utilization_pct") or 0)
    if sorter_util >= 85:
        inject_at = state.inputs.shift.start_min + 60 * 60
        rec = _try_staff_injection(
            raw_inputs,
            run_fn,
            baseline_kpis=kpis,
            role="sorter",
            inject_at=inject_at,
            title=f"Add sorter at {label_minutes(inject_at)}",
            reason=f"Sorter utilization is {sorter_util}%",
            rec_type="ADD_SORTER",
        )
        if rec:
            recs.append(rec)

    return recs


def _try_staff_injection(
    raw_inputs: dict[str, Any],
    run_fn: RunFn,
    *,
    baseline_kpis: dict[str, Any],
    role: str,
    inject_at: int,
    title: str,
    reason: str,
    rec_type: str,
) -> dict[str, Any] | None:
    candidate = deepcopy(raw_inputs)
    employees = list(candidate.get("employees") or [])
    emp_id = f"REC-{role.upper()}-{uuid4().hex[:6]}"
    employees.append(
        {
            "id": emp_id,
            "name": f"Extra {role.title()}",
            "primary_role": role,
            "start_time": label_minutes(inject_at),
            "end_time": candidate.get("end_time") or "3:00 PM",
            "fold_lbs_per_hour": 40 if role == "folder" else None,
        }
    )
    candidate["employees"] = employees
    candidate["mode"] = "continue_from_time"
    candidate["sim_mode"] = "continue_from_time"
    candidate["continue_from_time"] = label_minutes(inject_at)
    candidate["continue_from_min"] = inject_at

    projected_state = run_fn(candidate)
    if not projected_state.validation.accepted:
        return None
    projected = compute_kpis(projected_state)
    impact = {
        "bags_ready_by_target_delta": int(projected["bags_ready_by_target"]) - int(baseline_kpis["bags_ready_by_target"]),
        "bags_folded_by_target_delta": int(projected["bags_folded_by_target"]) - int(baseline_kpis["bags_folded_by_target"]),
        "final_completion_minutes_delta": _completion_delta(
            baseline_kpis.get("final_completion_time"), projected.get("final_completion_time")
        ),
        "max_backlog_delta": int(projected.get("maximum_fold_backlog") or 0)
        - int(baseline_kpis.get("maximum_fold_backlog") or 0),
    }
    benefit = (
        impact["bags_ready_by_target_delta"] > 0
        or impact["bags_folded_by_target_delta"] > 0
        or (impact["final_completion_minutes_delta"] is not None and impact["final_completion_minutes_delta"] < 0)
        or impact["max_backlog_delta"] < 0
    )
    if not benefit:
        return None

    action = {
        "add_employee": {
            "id": emp_id,
            "name": f"Extra {role.title()}",
            "primary_role": role,
            "start_time": label_minutes(inject_at),
            "fold_lbs_per_hour": 40 if role == "folder" else None,
        },
        "sim_mode": "continue_from_time",
        "continue_from_time": label_minutes(inject_at),
    }
    return {
        "recommendation_id": f"rec_{uuid4().hex[:10]}",
        "type": rec_type,
        "title": title,
        "reason": reason,
        "proposed_action": action,
        "action": action,  # compat
        "baseline_metrics": baseline_kpis,
        "projected_metrics": projected,
        "impact": impact,
        "buttons": [
            {"id": "apply", "label": "Apply"},
            {"id": "peak_only", "label": "Apply for peak window only"},
            {"id": "change_start", "label": "Change start time"},
            {"id": "dismiss", "label": "Dismiss"},
            {"id": "undo", "label": "Undo"},
        ],
    }


def _completion_delta(before_label: Any, after_label: Any) -> int | None:
    from backend.shift_capacity.validation import parse_clock_minutes

    if not before_label or not after_label:
        return None
    return parse_clock_minutes(after_label) - parse_clock_minutes(before_label)
