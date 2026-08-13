"""Post-DES management executive summary (no scheduler changes).

Derives staffed/productive labor, peak staff, bottleneck, and status labels
from management_outcome + work_coverage + compiled resources + queue telemetry.
Hybrids count once for staffed hours and peak headcount.
"""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.staffing_plan import (
    MANAGEMENT_ROLES,
)
from backend.shift_capacity.validation import label_minutes

ROLE_STAGE_LABEL = {
    "weigher": "WEIGH",
    "sorter": "SORT",
    "washer": "WASH",
    "dryer": "DRY",
    "folder": "FOLD",
}

WAITING_FIELD_BY_STAGE = {
    "weigher": None,  # no upstream wait for weigh in POSITION waiting_to_*
    "sorter": "waiting_to_sort",
    "washer": "waiting_to_wash",
    "dryer": "waiting_to_dry",
    "folder": "waiting_to_fold",
}

CHECKPOINT_STAGE_IDS = ("weigh", "sort", "wash", "dry", "fold")
CHECKPOINT_TO_ROLE = {
    "weigh": "weigher",
    "sort": "sorter",
    "wash": "washer",
    "dry": "dryer",
    "fold": "folder",
}


def build_management_executive_summary(
    state: Any,
    *,
    work_coverage: list[dict[str, Any]] | None = None,
    block_positions: list[dict[str, Any]] | None = None,
    kpis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return executive summary for management_mode runs; None otherwise."""
    if not getattr(getattr(state, "inputs", None), "management_mode", False):
        return None

    kpis = kpis or {}
    outcome = kpis.get("management_outcome") or {}
    coverage = list(work_coverage or [])
    blocks = list(block_positions or [])

    target_bags = int(outcome.get("target_bags") or state.inputs.shift.bag_count or 0)
    completed_by_target = int(
        outcome.get("completed_by_target")
        or outcome.get("bags_completed_by_target")
        or 0
    )
    bags_completed = int(outcome.get("bags_completed") or completed_by_target)
    status = str(outcome.get("completion_status") or "stalled")
    projected_finish = outcome.get("projected_finish")
    blocking = outcome.get("first_blocking_role")
    target_sec = int(state.inputs.shift.target_min)
    start_sec = int(state.inputs.shift.start_min)
    target_finish = label_minutes(target_sec)

    finish_sec = _parse_finish_sec(projected_finish, state)
    minutes_early = None
    minutes_late = None
    if finish_sec is not None and status != "stalled":
        delta = finish_sec - target_sec
        if delta < 0:
            minutes_early = int(round((-delta) / 60.0))
        elif delta > 0:
            minutes_late = int(round(delta / 60.0))
        else:
            minutes_early = 0

    status_label, tone = _status_label(
        status=status,
        minutes_early=minutes_early,
        minutes_late=minutes_late,
        blocking=blocking,
    )
    short_bags = max(0, target_bags - completed_by_target)
    pct_by_target = (
        int(round((completed_by_target / target_bags) * 100)) if target_bags > 0 else 0
    )

    labor = _labor_totals(coverage)
    peak_staff = _peak_concurrent_staff(state)
    denom_bags = bags_completed if bags_completed > 0 else (
        completed_by_target if completed_by_target > 0 else target_bags
    )
    labor_min_per_bag = None
    if denom_bags > 0 and labor["productive_hours"] is not None:
        labor_min_per_bag = round(
            (float(labor["productive_hours"]) * 60.0) / float(denom_bags), 1
        )

    bottleneck = _bottleneck(
        status=status,
        blocking=blocking,
        blocks=blocks,
        time_summary_rows=kpis.get("_time_summary_rows"),
        state=state,
    )
    machines = _machine_peaks(state, start_sec, max(target_sec, finish_sec or target_sec))

    return {
        "target_bags": target_bags,
        "target_finish": target_finish,
        "completed_by_target": completed_by_target,
        "bags_completed": bags_completed,
        "completion_status": status,
        "status_label": status_label,
        "tone": tone,
        "projected_finish": projected_finish if status != "stalled" else None,
        "minutes_early": minutes_early,
        "minutes_late": minutes_late,
        "short_bags": short_bags,
        "pct_by_target": pct_by_target,
        "staff_hours": labor["staff_hours"],
        "productive_hours": labor["productive_hours"],
        "utilization_pct": labor["utilization_pct"],
        "peak_staff": peak_staff,
        "labor_min_per_bag": labor_min_per_bag,
        "labor_by_role": labor["labor_by_role"],
        "bottleneck": bottleneck,
        "machines": machines,
        # Compact fields useful for Saved Simulations list chips / future compare
        "compare": {
            "projected_finish": projected_finish if status != "stalled" else None,
            "completed_by_target": completed_by_target,
            "target_bags": target_bags,
            "staff_hours": labor["staff_hours"],
            "productive_hours": labor["productive_hours"],
            "peak_staff": peak_staff,
            "labor_min_per_bag": labor_min_per_bag,
            "bottleneck_stage": (bottleneck or {}).get("stage"),
            "status_label": status_label,
        },
    }


def _parse_finish_sec(projected_finish: Any, state: Any) -> int | None:
    if projected_finish:
        try:
            from backend.shift_capacity.timebase import parse_clock_seconds

            return parse_clock_seconds(str(projected_finish))
        except Exception:
            pass
    folded = [b.completed_at for b in (state.bags or []) if b.completed_at is not None]
    return max(folded) if folded else None


def _status_label(
    *,
    status: str,
    minutes_early: int | None,
    minutes_late: int | None,
    blocking: str | None,
) -> tuple[str, str]:
    if status == "stalled":
        if blocking:
            return f"STALLED — needs {ROLE_STAGE_LABEL.get(blocking, blocking)}", "danger"
        return "STALLED", "danger"
    if status == "completed":
        if minutes_early and minutes_early > 0:
            return "TARGET MET EARLY", "success"
        if minutes_late and minutes_late > 0:
            # finished all bags but after target window classification edge
            return "TARGET MET LATE", "warning"
        return "TARGET MET ON TIME", "success"
    # incomplete_by_target — all bags eventually complete after target
    if minutes_late and minutes_late > 0:
        return "TARGET MET LATE", "warning"
    return "TARGET NOT MET", "warning"


def _labor_totals(coverage: list[dict[str, Any]]) -> dict[str, Any]:
    staff_min = 0.0
    used_min = 0.0
    by_role: dict[str, dict[str, float]] = {
        r: {"staff_min": 0.0, "productive_min": 0.0} for r in MANAGEMENT_ROLES
    }
    hybrid_staff_min = 0.0
    hybrid_productive_min = 0.0
    hybrid_details: list[dict[str, Any]] = []

    for row in coverage:
        s = float(row.get("staff_min") or 0)
        u = float(row.get("used_min") or 0)
        staff_min += s
        used_min += u
        if row.get("hybrid") or (row.get("roles") and len(row.get("roles") or []) >= 2):
            hybrid_staff_min += s
            hybrid_productive_min += u
            alloc = row.get("role_allocation_min") or {}
            for role in MANAGEMENT_ROLES:
                v = float(alloc.get(role) or 0)
                if v > 0:
                    by_role[role]["productive_min"] += v
            hybrid_details.append(
                {
                    "hybrid": row.get("hybrid"),
                    "roles": list(row.get("roles") or []),
                    "people": row.get("people"),
                    "start": row.get("start"),
                    "end": row.get("end"),
                    "staff_hours": round(s / 60.0, 2),
                    "productive_hours": round(u / 60.0, 2),
                    "allocation_min": alloc,
                }
            )
        else:
            role = str(row.get("role") or "")
            if role in by_role:
                by_role[role]["staff_min"] += s
                by_role[role]["productive_min"] += u

    labor_by_role = []
    for role in MANAGEMENT_ROLES:
        labor_by_role.append(
            {
                "role": role,
                "label": ROLE_STAGE_LABEL[role],
                "staff_hours": round(by_role[role]["staff_min"] / 60.0, 2),
                "productive_hours": round(by_role[role]["productive_min"] / 60.0, 2),
            }
        )
    if hybrid_staff_min > 0 or hybrid_productive_min > 0 or hybrid_details:
        labor_by_role.append(
            {
                "role": "hybrid",
                "label": "HYBRID",
                "staff_hours": round(hybrid_staff_min / 60.0, 2),
                "productive_hours": round(hybrid_productive_min / 60.0, 2),
                "details": hybrid_details,
            }
        )

    util = int(round((used_min / staff_min) * 100)) if staff_min > 0 else 0
    return {
        "staff_hours": round(staff_min / 60.0, 2),
        "productive_hours": round(used_min / 60.0, 2),
        "utilization_pct": util,
        "labor_by_role": labor_by_role,
    }


def _peak_concurrent_staff(state: Any) -> int:
    """Max distinct management employees with an open schedule window."""
    employees = list(getattr(state.inputs, "employees", None) or [])
    events: list[tuple[int, int]] = []
    for emp in employees:
        eid = str(getattr(emp, "employee_id", "") or "")
        if not eid.startswith("MGMT_"):
            continue
        for win in getattr(emp, "schedule_windows", None) or []:
            s = int(getattr(win, "start_min", 0) or 0)
            e = int(getattr(win, "end_min", 0) or 0)
            if e <= s:
                continue
            events.append((s, 1))
            events.append((e, -1))
    if not events:
        return 0
    events.sort(key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def _bottleneck(
    *,
    status: str,
    blocking: str | None,
    blocks: list[dict[str, Any]],
    time_summary_rows: Any,
    state: Any,
) -> dict[str, Any]:
    if status == "stalled" and blocking:
        return {
            "stage": CHECKPOINT_TO_ROLE.get(blocking, blocking),
            "stage_label": ROLE_STAGE_LABEL.get(blocking, str(blocking).upper()),
            "peak_queue": None,
            "first_seen": None,
            "note": f"Insufficient {ROLE_STAGE_LABEL.get(blocking, blocking)} capacity",
        }

    peaks: dict[str, dict[str, Any]] = {
        sid: {"peak": 0, "first_seen": None, "role": CHECKPOINT_TO_ROLE[sid]}
        for sid in CHECKPOINT_STAGE_IDS
        if sid != "weigh"
    }

    for block in blocks:
        for cp in block.get("availability_checkpoints") or []:
            stages = cp.get("stages") or {}
            tlabel = cp.get("time")
            for sid, meta in peaks.items():
                stage = stages.get(sid) or {}
                q = int(stage.get("waiting_next") or 0)
                if q > meta["peak"]:
                    meta["peak"] = q
                    meta["first_seen"] = tlabel
                elif q == meta["peak"] and q > 0 and meta["first_seen"] is None:
                    meta["first_seen"] = tlabel
        # End-of-block waiting fallback
        waiting = block.get("waiting") or {}
        mapping = {
            "sort": waiting.get("waiting_to_sort") or waiting.get("to_sort"),
            "wash": waiting.get("waiting_to_wash") or waiting.get("to_wash"),
            "dry": waiting.get("waiting_to_dry") or waiting.get("to_dry"),
            "fold": waiting.get("waiting_to_fold") or waiting.get("to_fold"),
        }
        for sid, qraw in mapping.items():
            if sid not in peaks:
                continue
            q = int(qraw or 0)
            if q > peaks[sid]["peak"]:
                peaks[sid]["peak"] = q
                peaks[sid]["first_seen"] = block.get("block_end")

    # Prefer later stage on ties (downstream pressure).
    order = ["fold", "dry", "wash", "sort"]
    best_sid = None
    best_peak = 0
    for sid in order:
        peak = peaks.get(sid, {}).get("peak") or 0
        if peak > best_peak:
            best_peak = peak
            best_sid = sid

    if not best_sid or best_peak <= 0:
        return {
            "stage": None,
            "stage_label": "NONE",
            "peak_queue": 0,
            "first_seen": None,
            "note": "No sustained queue pressure",
        }

    role = peaks[best_sid]["role"]
    label = ROLE_STAGE_LABEL[role]
    return {
        "stage": role,
        "stage_label": label,
        "peak_queue": best_peak,
        "first_seen": peaks[best_sid]["first_seen"],
        "note": f"Peak available for {label.title()}",
    }


def _machine_peaks(state: Any, start_sec: int, end_sec: int) -> dict[str, Any]:
    washers = list(getattr(state.inputs, "washers", None) or [])
    dryers = list(getattr(state.inputs, "dryers", None) or [])
    washer_ids = [
        str(getattr(w, "machine_id", None) or getattr(w, "id", None) or w)
        for w in washers
    ]
    dryer_ids = [
        str(getattr(d, "machine_id", None) or getattr(d, "id", None) or d)
        for d in dryers
    ]
    calendars = getattr(state, "machine_calendars", None) or {}
    if not washer_ids:
        washer_ids = [rid for rid in calendars if str(rid).startswith("W")]
    if not dryer_ids:
        dryer_ids = [rid for rid in calendars if str(rid).startswith("D")]
    shift = getattr(state.inputs, "shift", None)
    washer_count = len(washer_ids) or int(getattr(shift, "washer_count", 0) or 0)
    dryer_count = len(dryer_ids) or int(getattr(shift, "dryer_count", 0) or 0)

    def peak_active(ids: list[str]) -> int:
        events: list[tuple[int, int]] = []
        for rid in ids:
            for r in calendars.get(rid) or []:
                s = int(getattr(r, "start", 0) or 0)
                e = int(getattr(r, "end", 0) or 0)
                if e <= s:
                    continue
                if e <= start_sec or s >= end_sec:
                    continue
                events.append((max(s, start_sec), 1))
                events.append((min(e, end_sec), -1))
        if not events:
            return 0
        events.sort(key=lambda x: (x[0], x[1]))
        cur = peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        return peak

    return {
        "peak_washers_active": peak_active(washer_ids),
        "washer_count": washer_count,
        "peak_dryers_active": peak_active(dryer_ids),
        "dryer_count": dryer_count,
    }
