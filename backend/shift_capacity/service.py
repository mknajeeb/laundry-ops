"""Engine orchestration for bag_des_v2."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.shift_capacity.continuation import (
    build_freeze_snapshot,
    continue_from_time,
    prepare_continuation_inputs,
)
from backend.shift_capacity.models import SimulationState, ValidationError, ValidationResult, new_id
from backend.shift_capacity.recommendations import build_recommendations
from backend.shift_capacity.scheduler import run_scheduler
from backend.shift_capacity.serialization import serialize_state
from backend.shift_capacity.validation import parse_clock_minutes, parse_inputs

# In-memory scenario store for undo / parent lookup within process lifetime.
_SCENARIOS: dict[str, dict[str, Any]] = {}


def run_shift_capacity(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(data or {})
    mode = str(raw.get("mode") or raw.get("sim_mode") or "full_run").strip().lower()

    if mode == "undo":
        return _undo(raw)

    if isinstance(raw.get("apply_action"), dict):
        raw = apply_action(raw, raw["apply_action"])
        raw.pop("apply_action", None)
        mode = str(raw.get("mode") or raw.get("sim_mode") or mode).strip().lower()

    if mode in ("continue", "continue_from_time") or (
        raw.get("continue_from_time") is not None and mode not in ("reoptimize_entire_shift", "reoptimize_full")
    ):
        return _run_continue(raw)

    if mode in ("reoptimize_entire_shift", "reoptimize_full"):
        raw = dict(raw)
        raw["mode"] = "reoptimize_entire_shift"
        raw.pop("continue_from_time", None)
        raw.pop("continue_from_min", None)
        return _run_full(raw, mode="reoptimize_entire_shift")

    if mode == "apply_batch_override":
        return _run_full(raw, mode="apply_batch_override")

    if mode == "apply_recommendation":
        return _run_full(raw, mode="apply_recommendation")

    return _run_full(raw, mode="full_run")


def _run_full(raw: dict[str, Any], *, mode: str) -> dict[str, Any]:
    try:
        inp = parse_inputs(raw)
    except ValueError as exc:
        return _rejection(str(exc), mode=mode)

    inp.mode = mode  # type: ignore[assignment]
    parent_id = raw.get("parent_scenario_id") or raw.get("scenario_id")
    inp.parent_scenario_id = parent_id
    inp.scenario_id = new_id("scn")

    state = run_scheduler(inp)
    state.mode = mode  # type: ignore[assignment]
    state.parent_scenario_id = parent_id

    if not state.validation.accepted:
        payload = serialize_state(state)
        payload["overlap_errors"] = payload.get("overlap_errors") or [
            e.code for e in state.validation.errors
        ]
        return _wrap(payload, raw_inputs=raw, state=state)

    # Bags moved vs baseline without overrides
    bags_moved = []
    if inp.batch_overrides:
        baseline_raw = dict(raw)
        baseline_raw.pop("batch_overrides", None)
        baseline_state = run_scheduler(parse_inputs(baseline_raw))
        before = {b.bag_id: b.batch_sequence for b in baseline_state.bags}
        bags_moved = [
            {"bag_id": b.bag_id, "from_batch": before.get(b.bag_id), "to_batch": b.batch_sequence}
            for b in state.bags
            if before.get(b.bag_id) != b.batch_sequence
        ]

    def _inner_run(candidate: dict[str, Any]) -> SimulationState:
        # Nested recommendation sims should not recurse infinitely on recommendations.
        nested = dict(candidate)
        nested["_skip_recommendations"] = True
        if nested.get("continue_from_time") or nested.get("mode") in ("continue_from_time", "continue"):
            return _run_continue_state(nested)
        return run_scheduler(parse_inputs(nested))

    recommendations = []
    if not raw.get("_skip_recommendations"):
        recommendations = build_recommendations(state, raw, _inner_run)

    payload = serialize_state(state, recommendations=recommendations, bags_moved=bags_moved)
    return _wrap(payload, raw_inputs=raw, state=state)


def _run_continue(raw: dict[str, Any]) -> dict[str, Any]:
    state = _run_continue_state(raw)
    if not state.validation.accepted:
        payload = serialize_state(state)
        return _wrap(payload, raw_inputs=raw, state=state)

    def _inner_run(candidate: dict[str, Any]) -> SimulationState:
        nested = dict(candidate)
        nested["_skip_recommendations"] = True
        return _run_continue_state(nested) if (
            nested.get("continue_from_time") or nested.get("mode") in ("continue_from_time", "continue")
        ) else run_scheduler(parse_inputs(nested))

    recommendations = []
    if not raw.get("_skip_recommendations"):
        recommendations = build_recommendations(state, raw, _inner_run)
    payload = serialize_state(state, recommendations=recommendations)
    return _wrap(payload, raw_inputs=raw, state=state)


def _run_continue_state(raw: dict[str, Any]) -> SimulationState:
    t = (
        int(raw["continue_from_min"])
        if raw.get("continue_from_min") is not None
        else parse_clock_minutes(raw.get("continue_from_time"))
    )
    parent_id = raw.get("parent_scenario_id")
    freeze: SimulationState | None = None
    if parent_id and parent_id in _SCENARIOS:
        freeze = _SCENARIOS[parent_id].get("state")

    if freeze is None:
        baseline_raw, continued_raw = prepare_continuation_inputs(raw, t)
        baseline_inp = parse_inputs(baseline_raw)
        baseline_inp.mode = "full_run"
        freeze = build_freeze_snapshot(run_scheduler(baseline_inp))
        continued_raw = dict(raw)
    else:
        continued_raw = dict(raw)

    continued_inp = parse_inputs(continued_raw)
    return continue_from_time(continued_inp, freeze, t)


def apply_action(raw: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(raw)
    out["parent_scenario_id"] = raw.get("scenario_id") or raw.get("parent_scenario_id")

    if "add_employee" in action and isinstance(action["add_employee"], dict):
        employees = [dict(e) for e in (out.get("employees") or []) if isinstance(e, dict)]
        employees.append(dict(action["add_employee"]))
        out["employees"] = employees
        out["change_type"] = "STAFF_INJECTION"
        out["change_payload"] = action["add_employee"]
        if action.get("sim_mode") in ("continue_from_time", "continue") or action.get("continue_from_time"):
            out["mode"] = "continue_from_time"
            out["sim_mode"] = "continue_from_time"
            out["continue_from_time"] = action.get("continue_from_time") or action["add_employee"].get("start_time")
        elif action.get("sim_mode") in ("reoptimize_entire_shift", "reoptimize_full"):
            out["mode"] = "reoptimize_entire_shift"
            out.pop("continue_from_time", None)

    if "batch_override" in action and isinstance(action["batch_override"], dict):
        overrides = [dict(r) for r in (out.get("batch_overrides") or []) if isinstance(r, dict)]
        number = int(action["batch_override"].get("batch_number"))
        overrides = [r for r in overrides if int(r.get("batch_number", -1)) != number]
        overrides.append(dict(action["batch_override"]))
        out["batch_overrides"] = overrides
        out["mode"] = "apply_batch_override"
        out["change_type"] = "BATCH_OVERRIDE"
        out["change_payload"] = action["batch_override"]

    if "reset_override" in action:
        number = int(action["reset_override"])
        out["batch_overrides"] = [
            r for r in (out.get("batch_overrides") or []) if int(r.get("batch_number", -1)) != number
        ]
        out["mode"] = "apply_batch_override"
        out["change_type"] = "BATCH_OVERRIDE"

    if "role_schedule" in action and isinstance(action["role_schedule"], dict):
        emp_id = str(action["role_schedule"].get("employee_id") or "")
        employees = []
        for row in out.get("employees") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            if str(item.get("id") or item.get("employee_id")) == emp_id:
                item["role_schedule"] = list(action["role_schedule"].get("windows") or [])
            employees.append(item)
        out["employees"] = employees
        out["change_type"] = "ROLE_SWITCH"
        out["change_payload"] = action["role_schedule"]

    for key, value in action.items():
        if key in ("add_employee", "batch_override", "reset_override", "role_schedule"):
            continue
        out[key] = value
    return out


def merge_batch_override(inputs: dict[str, Any], override_dict: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(inputs)
    if override_dict.get("reset_override"):
        number = int(override_dict["reset_override"])
        out["batch_overrides"] = [
            r for r in (out.get("batch_overrides") or []) if int(r.get("batch_number", -1)) != number
        ]
        return out
    existing = [dict(r) for r in (out.get("batch_overrides") or []) if isinstance(r, dict)]
    number = int(override_dict.get("batch_number"))
    existing = [r for r in existing if int(r.get("batch_number", -1)) != number]
    existing.append(dict(override_dict))
    out["batch_overrides"] = existing
    return out


def _wrap(payload: dict[str, Any], *, raw_inputs: dict[str, Any], state: SimulationState) -> dict[str, Any]:
    scenario_id = payload["scenario_id"]
    _SCENARIOS[scenario_id] = {
        "parent_scenario_id": payload.get("parent_scenario_id"),
        "raw_inputs": deepcopy(raw_inputs),
        "payload": deepcopy(payload),
        "state": state,
        "change_type": raw_inputs.get("change_type"),
        "change_payload": raw_inputs.get("change_payload"),
    }
    # Successful runs must not report overlaps.
    if payload.get("simulation_valid"):
        payload["overlap_errors"] = []
    return payload


def _undo(raw: dict[str, Any]) -> dict[str, Any]:
    scenario_id = raw.get("scenario_id")
    if not scenario_id or scenario_id not in _SCENARIOS:
        return _rejection("Unknown scenario_id for undo", mode="undo")
    current = _SCENARIOS[scenario_id]
    parent_id = current.get("parent_scenario_id")
    if not parent_id or parent_id not in _SCENARIOS:
        return _rejection("No parent scenario to restore", mode="undo")
    parent = _SCENARIOS[parent_id]
    restored = deepcopy(parent["payload"])
    restored["mode"] = "undo"
    return restored


def _rejection(message: str, *, mode: str) -> dict[str, Any]:
    return {
        "engine": "bag_des_v2",
        "scenario_id": new_id("scn"),
        "parent_scenario_id": None,
        "mode": mode,
        "validation": ValidationResult(
            accepted=False,
            errors=[ValidationError("INVALID_REQUEST", message)],
        ).as_dict(),
        "continuation": {},
        "kpis": {},
        "summary": {},
        "bags": [],
        "bag_rows": [],
        "batches": [],
        "time_summary": [],
        "staffing_summary": [],
        "employee_timeline": [],
        "machine_timeline": [],
        "recommendations": [],
        "overlap_errors": [],
        "simulation_valid": False,
        "validation_errors": [message],
    }
