"""True continue_from_time: freeze snapshot and resume the event queue from T."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.shift_capacity.models import SimulationInputs, SimulationState, new_id
from backend.shift_capacity.scheduler import run_scheduler
from backend.shift_capacity.timebase import label_seconds, parse_clock_seconds, sec_to_min_int
from backend.shift_capacity.validation import label_minutes


def build_freeze_snapshot(baseline: SimulationState) -> SimulationState:
    """Deep copy of a completed simulation used as immutable history."""
    return deepcopy(baseline)


def employees_present_before(inp: SimulationInputs, t: int) -> list:
    return [e for e in inp.employees if e.start_min() < t]


def prepare_continuation_inputs(data: dict[str, Any], t: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split payload into baseline (staff before T) and continued (all staff).

    `t` is seconds from midnight.
    """
    baseline = dict(data or {})
    continued = dict(data or {})
    employees = list(baseline.get("employees") or [])
    start_label = baseline.get("start_time") or (baseline.get("shift") or {}).get("start_time") or "7:00 AM"

    def start_of(emp: dict[str, Any]) -> int:
        return parse_clock_seconds(emp.get("start_time"), default=str(start_label))

    baseline["employees"] = [dict(e) for e in employees if isinstance(e, dict) and start_of(e) < t]
    baseline["mode"] = "full_run"
    baseline["sim_mode"] = "full_run"
    baseline.pop("continue_from_time", None)
    baseline.pop("continue_from_min", None)
    baseline.pop("continue_from_sec", None)

    continued["mode"] = "continue_from_time"
    continued["sim_mode"] = "continue_from_time"
    continued["continue_from_sec"] = t
    continued["continue_from_min"] = sec_to_min_int(t)
    continued["continue_from_time"] = label_minutes(t) or label_seconds(t)
    return baseline, continued


def continue_from_time(
    continued_inputs: SimulationInputs,
    freeze_snapshot: SimulationState,
    t: int,
) -> SimulationState:
    """Resume scheduling from T using frozen calendars and bag stages."""
    continued_inputs.mode = "continue_from_time"
    continued_inputs.continue_from_min = t
    continued_inputs.parent_scenario_id = freeze_snapshot.scenario_id
    continued_inputs.scenario_id = new_id("scn")
    state = run_scheduler(continued_inputs, frozen=freeze_snapshot, resume_from=t)
    state.mode = "continue_from_time"
    state.parent_scenario_id = freeze_snapshot.scenario_id
    if state.continuation.event_queue_starts_at_min is None:
        state.continuation.event_queue_starts_at_min = t
    return state
