"""
Rule-based auto roster builder — deterministic draft schedule generation.
Does not publish; returns proposed draft entries + explainable reports.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from backend.payroll_schedule import (
    _d,
    _enrich_entry,
    _overtime_threshold,
    _parse_time,
    _q2,
    _scheduled_hours_week,
    _time_to_str,
    check_schedule_warnings,
    compute_scheduled_hours,
    worker_profile_gaps,
)
from backend.payroll_schedule_planner import (
    _times_overlap,
    list_coverage_targets,
    load_plan_bundle,
)
from backend.ta_helpers import json_safe


def _date_range(start: str, end: str) -> list[date]:
    s = date.fromisoformat(start[:10])
    e = date.fromisoformat(end[:10])
    if e < s:
        return []
    out = []
    d = s
    while d <= e:
        out.append(d)
        d += timedelta(days=1)
    return out


def _stream_matches_filter(stream_id: int, stream_name: str, stream_ids: Optional[list]) -> bool:
    if not stream_ids:
        return True
    return int(stream_id) in [int(x) for x in stream_ids]


def _shift_matches_filter(shift_id: int, shift_ids: Optional[list]) -> bool:
    if not shift_ids:
        return True
    return int(shift_id) in [int(x) for x in shift_ids]


def _worker_eligible(
    worker: dict,
    *,
    active_only: bool,
    include_incomplete: bool,
) -> tuple[bool, str]:
    if active_only and not worker.get("active"):
        return False, "Worker inactive"
    gaps = worker.get("profile_gaps") or worker_profile_gaps(worker)
    if gaps and not include_incomplete:
        return False, f"Incomplete profile: {gaps[0]}"
    rate = _d(worker.get("default_hourly_rate") or 0)
    if rate <= 0:
        return False, "No hourly rate"
    return True, ""


def _day_availability(worker: dict, dow: int) -> Optional[dict]:
    for a in worker.get("availability") or []:
        if int(a.get("day_of_week", -1)) == dow:
            return a
    return None


def _score_worker_for_slot(
    conn,
    organization_id: int,
    worker: dict,
    *,
    work_date: date,
    shift: dict,
    work_stream_id: int,
    role_id: int,
    shift_hours: Decimal,
    week_start: date,
    week_end: date,
    simulated_week_hours: dict[int, Decimal],
    day_entries: list[dict],
    settings: dict,
    options: dict,
) -> tuple[float, list[str], list[str]]:
    """Return (score, positive_reasons, disqualifiers)."""
    reasons: list[str] = []
    disqualifiers: list[str] = []
    wpid = int(worker["id"])
    dow = work_date.weekday()

    ok, why = _worker_eligible(
        worker,
        active_only=options.get("active_workers_only", True),
        include_incomplete=options.get("include_incomplete_profiles", False),
    )
    if not ok:
        disqualifiers.append(why)
        return -9999.0, reasons, disqualifiers

    day_avail = _day_availability(worker, dow)
    if day_avail and day_avail.get("unavailable_flag"):
        disqualifiers.append("Not available on this day")
        return -9999.0, reasons, disqualifiers

    st = _time_to_str(_parse_time(shift.get("start_time_default")))
    et = _time_to_str(_parse_time(shift.get("end_time_default")))
    probe = {"start_time": st, "end_time": et}
    if any(_times_overlap(probe, e) for e in day_entries if int(e.get("worker_profile_id") or 0) == wpid):
        disqualifiers.append("Overlapping shift")
        return -9999.0, reasons, disqualifiers

    if day_avail and day_avail.get("available_from") and day_avail.get("available_to"):
        af = _parse_time(day_avail.get("available_from"))
        at = _parse_time(day_avail.get("available_to"))
        st_t = _parse_time(st)
        et_t = _parse_time(et)
        if af and at and st_t and et_t and (st_t < af or et_t > at):
            disqualifiers.append("Outside availability window")
            return -9999.0, reasons, disqualifiers

    reasons.append("Available")
    score = 50.0

    role_skills = [s for s in (worker.get("role_skills") or []) if s.get("active", True)]
    has_role = any(int(s.get("role_id") or 0) == int(role_id) for s in role_skills)
    if has_role:
        score += 30.0
        reasons.append("Role match")
    else:
        disqualifiers.append("Role mismatch")
        return -9999.0, reasons, disqualifiers

    has_stream = any(int(s.get("work_stream_id") or 0) == int(work_stream_id) for s in role_skills)
    if has_stream:
        score += 20.0
        reasons.append("Stream match")
    else:
        c = conn.cursor()
        c.execute("SELECT name FROM payroll_work_streams WHERE id=%s", (int(work_stream_id),))
        sn = ((c.fetchone() or {}).get("name") or "").lower()
        if "rinse" in sn and worker.get("can_work_rinse"):
            score += 15.0
            reasons.append("Stream flag: Rinse")
        elif "drop" in sn and worker.get("can_work_drop_off"):
            score += 15.0
            reasons.append("Stream flag: Drop Off")
        elif "both" in sn and worker.get("can_work_both"):
            score += 15.0
            reasons.append("Stream flag: Both")
        else:
            disqualifiers.append("Stream mismatch")
            return -9999.0, reasons, disqualifiers

    pref_shift = worker.get("preferred_shift_id")
    if pref_shift and int(pref_shift) == int(shift.get("id")):
        score += 15.0
        reasons.append(f"Preferred {shift.get('name') or 'shift'}")
    elif day_avail and day_avail.get("preferred_shift_id"):
        if int(day_avail["preferred_shift_id"]) == int(shift.get("id")):
            score += 12.0
            reasons.append("Day preferred shift")

    week_h = simulated_week_hours.get(wpid, Decimal("0"))
    ot_threshold = _overtime_threshold(conn, organization_id, worker)
    max_gen = options.get("max_hours_per_worker")
    if max_gen is not None and float(max_gen) > 0:
        cap = Decimal(str(max_gen))
        if week_h + shift_hours > cap:
            disqualifiers.append(f"Exceeds generator max {max_gen}h/week")
            return -9999.0, reasons, disqualifiers

    after = week_h + shift_hours
    ot_risk = after > ot_threshold
    reasons.append(f"{_q2(week_h)} projected weekly hours → {_q2(after)} after shift")
    if ot_risk:
        reasons.append("Overtime risk")
        if options.get("avoid_overtime", True):
            disqualifiers.append("Would cause overtime")
            return -9999.0, reasons, disqualifiers
        score -= 40.0
    else:
        reasons.append("No overtime risk")
        score += min(20.0, float(ot_threshold - after))

    if options.get("balance_hours", True):
        target = _d(settings.get("target_hours_per_week") or 32)
        if week_h < target:
            score += min(15.0, float(target - week_h) * 0.5)
            if week_h < _d(settings.get("underused_hours_threshold") or 15):
                reasons.append("Underused — balancing hours")

    perf = worker.get("performance_preview") or {}
    if options.get("prefer_strong_performers", True) and perf.get("available"):
        bags_h = perf.get("avg_bags_per_hour")
        if bags_h:
            score += min(25.0, float(bags_h) * 2.0)
            reasons.append(f"Strong folding performance ({bags_h} bags/hr)")
        else:
            score += 8.0
            reasons.append("Performance data available")
    rel = perf.get("attendance_reliability")
    if rel is not None:
        score += float(rel) * 10.0
        reasons.append(f"Reliability score {rel}")

    rate = _d(worker.get("default_hourly_rate") or 0)
    if rate > 0:
        score -= float(rate) * 0.3
    return score, reasons, disqualifiers


def _build_proposed_entry(
    worker: dict,
    *,
    work_date: date,
    shift: dict,
    target: dict,
    settings: dict,
    break_minutes: int,
    gen_id: str,
) -> dict:
    st = _time_to_str(_parse_time(shift.get("start_time_default")))
    et = _time_to_str(_parse_time(shift.get("end_time_default")))
    hours = compute_scheduled_hours(_parse_time(st), _parse_time(et), break_minutes)
    rate = _d(worker.get("default_hourly_rate") or 0)
    return json_safe(
        {
            "id": f"gen-{gen_id}",
            "work_date": work_date.isoformat(),
            "shift_id": int(shift["id"]),
            "work_stream_id": int(target["work_stream_id"]),
            "role_id": int(target["role_id"]),
            "worker_profile_id": int(worker["id"]),
            "geofence_id": None,
            "start_time": st,
            "end_time": et,
            "break_minutes": break_minutes,
            "scheduled_hours": _q2(hours),
            "hourly_rate_snapshot": _q2(rate) if rate > 0 else None,
            "worker_category_snapshot": worker.get("worker_category"),
            "shift_snapshot": shift.get("name"),
            "work_stream_snapshot": target.get("work_stream_name"),
            "role_snapshot": target.get("role_name"),
            "status": "scheduled",
            "publish_status": "draft",
            "change_note": "Auto roster draft",
            "_roster_generated": True,
            "worker_name": worker.get("worker_name") or worker.get("display_name"),
        }
    )


def generate_roster_draft(conn, organization_id: int, body: dict) -> dict[str, Any]:
    """
    Rule-based roster generation. Returns draft entries + reports; does not publish.
    """
    start_date = str(body.get("start_date") or "")[:10]
    end_date = str(body.get("end_date") or start_date)[:10]
    if not start_date:
        raise ValueError("start_date required")

    oid = int(organization_id)
    bundle = load_plan_bundle(conn, oid, start_date=start_date, end_date=end_date)
    settings = bundle["settings"]
    workers = bundle["workers"]
    coverage = list_coverage_targets(conn, oid)
    shift_ids = body.get("shift_ids") or []
    stream_ids = body.get("work_stream_ids") or []
    use_coverage = body.get("use_coverage_targets", True)
    break_minutes = int(body.get("break_minutes") or settings.get("default_break_minutes") or 0)
    gen_run_id = str(uuid.uuid4())[:8]

    shift_map = {int(s["id"]): s for s in (settings.get("shifts") or []) if s.get("active")}
    targets = [
        t
        for t in coverage
        if t.get("active")
        and _shift_matches_filter(int(t["shift_id"]), shift_ids)
        and _stream_matches_filter(int(t["work_stream_id"]), t.get("work_stream_name") or "", stream_ids)
    ]

    baseline = []
    for e in bundle.get("entries") or []:
        wd = str(e.get("work_date"))[:10]
        if wd < start_date or wd > end_date:
            continue
        if str(e.get("status")) in ("cancelled", "replaced"):
            continue
        if body.get("clear_existing_drafts_in_range") and str(e.get("publish_status")) != "published":
            continue
        baseline.append(e)

    simulated: list[dict] = list(baseline)
    proposed: list[dict] = []
    assignments: list[dict] = []
    gap_report: list[dict] = []

    from backend.payroll_identity import payroll_week_bounds

    for work_date in _date_range(start_date, end_date):
        dow = work_date.weekday()
        week_start, week_end = payroll_week_bounds(conn, work_date, oid)
        day_targets = [
            t
            for t in targets
            if t.get("day_of_week") is None or int(t.get("day_of_week")) == dow
        ]
        if not day_targets and use_coverage:
            continue

        if not use_coverage:
            day_targets = [
                {**t, "required_count": 1}
                for t in targets
                if t.get("day_of_week") is None or int(t.get("day_of_week")) == dow
            ]

        for target in day_targets:
            shift = shift_map.get(int(target["shift_id"]))
            if not shift:
                continue
            required = int(target.get("required_count") or 1) if use_coverage else 1
            st = _parse_time(shift.get("start_time_default"))
            et = _parse_time(shift.get("end_time_default"))
            shift_hours = compute_scheduled_hours(st, et, break_minutes)

            assigned = 0
            slot_day_entries = [
                e
                for e in simulated
                if str(e.get("work_date"))[:10] == work_date.isoformat()
            ]
            already = [
                e
                for e in slot_day_entries
                if int(e.get("shift_id") or 0) == int(target["shift_id"])
                and int(e.get("work_stream_id") or 0) == int(target["work_stream_id"])
                and int(e.get("role_id") or 0) == int(target["role_id"])
            ]
            assigned = len(already)
            need = max(0, required - assigned)

            for _ in range(need):
                week_hours: dict[int, Decimal] = {}
                for w in workers:
                    wpid = int(w["id"])
                    pub = _scheduled_hours_week(conn, oid, wpid, week_start, week_end)
                    extra = Decimal("0")
                    for e in simulated:
                        if int(e.get("worker_profile_id") or 0) != wpid:
                            continue
                        wd = str(e.get("work_date"))[:10]
                        if week_start.isoformat() <= wd <= week_end.isoformat():
                            extra += _d(e.get("scheduled_hours") or 0)
                    week_hours[wpid] = pub + extra

                best = None
                best_score = -99999.0
                best_reasons: list[str] = []
                for w in workers:
                    sc, reasons, disq = _score_worker_for_slot(
                        conn,
                        oid,
                        w,
                        work_date=work_date,
                        shift=shift,
                        work_stream_id=int(target["work_stream_id"]),
                        role_id=int(target["role_id"]),
                        shift_hours=shift_hours,
                        week_start=week_start,
                        week_end=week_end,
                        simulated_week_hours=week_hours,
                        day_entries=slot_day_entries,
                        settings=settings,
                        options=body,
                    )
                    if sc > best_score:
                        best_score = sc
                        best = w
                        best_reasons = reasons

                if not best or best_score < 0:
                    gap_report.append(
                        json_safe(
                            {
                                "work_date": work_date.isoformat(),
                                "day_label": work_date.strftime("%A"),
                                "shift_name": target.get("shift_name") or shift.get("name"),
                                "work_stream_name": target.get("work_stream_name"),
                                "role_name": target.get("role_name"),
                                "required": required,
                                "assigned": assigned,
                                "reason": "No available qualified worker found",
                            }
                        )
                    )
                    break

                entry = _build_proposed_entry(
                    best,
                    work_date=work_date,
                    shift=shift,
                    target=target,
                    settings=settings,
                    break_minutes=break_minutes,
                    gen_id=f"{gen_run_id}-{len(proposed)}",
                )
                enriched = _enrich_entry(conn, oid, entry)
                proposed.append(enriched)
                simulated.append(enriched)
                slot_day_entries.append(enriched)
                assigned += 1

                worker_label = best.get("worker_name") or best.get("display_name")
                assignments.append(
                    json_safe(
                        {
                            "worker_profile_id": int(best["id"]),
                            "worker_name": worker_label,
                            "work_date": work_date.isoformat(),
                            "shift_name": shift.get("name"),
                            "work_stream_name": target.get("work_stream_name"),
                            "role_name": target.get("role_name"),
                            "score": round(best_score, 1),
                            "reasons": best_reasons,
                            "summary": (
                                f"{worker_label} assigned to {work_date.strftime('%A')} "
                                f"{shift.get('name')} {target.get('work_stream_name')} {target.get('role_name')} "
                                f"because: " + "; ".join(best_reasons)
                            ),
                        }
                    )
                )

    conflict_report: list[dict] = []
    worker_by_id = {int(w["id"]): w for w in workers}
    for entry in proposed:
        w = worker_by_id.get(int(entry.get("worker_profile_id") or 0))
        issues = check_schedule_warnings(conn, oid, entry, w) if w else []
        overlap = False
        if w:
            same_day = [
                e
                for e in simulated
                if str(e.get("work_date"))[:10] == str(entry.get("work_date"))[:10]
                and int(e.get("worker_profile_id") or 0) == int(w["id"])
                and e is not entry
                and str(e.get("id")) != str(entry.get("id"))
            ]
            overlap = any(_times_overlap(entry, e) for e in same_day)
        if overlap:
            issues.append("Overlapping shift")
        if issues:
            conflict_report.append(
                json_safe(
                    {
                        "entry_id": entry.get("id"),
                        "worker_name": entry.get("worker_name"),
                        "work_date": entry.get("work_date"),
                        "shift_name": entry.get("shift_name") or entry.get("shift_snapshot"),
                        "issues": list(dict.fromkeys(issues)),
                    }
                )
            )

    assigned_worker_ids = {int(e.get("worker_profile_id")) for e in proposed}
    from backend.payroll_identity import payroll_week_bounds as pwb

    ws0 = date.fromisoformat(start_date)
    week_start0, week_end0 = pwb(conn, ws0, oid)

    workers_not_used = []
    workers_underused = []
    workers_incomplete_used = []
    under_thresh = _d(settings.get("underused_hours_threshold") or 15)

    for w in workers:
        wpid = int(w["id"])
        if not _worker_eligible(
            w,
            active_only=body.get("active_workers_only", True),
            include_incomplete=True,
        )[0]:
            continue
        week_h = Decimal("0")
        for e in simulated:
            if int(e.get("worker_profile_id") or 0) == wpid:
                wd = str(e.get("work_date"))[:10]
                if week_start0.isoformat() <= wd <= week_end0.isoformat():
                    week_h += _d(e.get("scheduled_hours") or 0)
        if wpid not in assigned_worker_ids:
            workers_not_used.append(
                json_safe(
                    {
                        "worker_profile_id": wpid,
                        "worker_name": w.get("worker_name") or w.get("display_name"),
                        "projected_week_hours": _q2(week_h),
                    }
                )
            )
        elif week_h < under_thresh:
            workers_underused.append(
                json_safe(
                    {
                        "worker_profile_id": wpid,
                        "worker_name": w.get("worker_name") or w.get("display_name"),
                        "projected_week_hours": _q2(week_h),
                    }
                )
            )
        gaps = w.get("profile_gaps") or worker_profile_gaps(w)
        if wpid in assigned_worker_ids and gaps:
            workers_incomplete_used.append(
                json_safe(
                    {
                        "worker_profile_id": wpid,
                        "worker_name": w.get("worker_name") or w.get("display_name"),
                        "profile_gaps": gaps,
                    }
                )
            )

    total_hours = sum(_d(e.get("scheduled_hours") or 0) for e in proposed)
    total_cost = sum(
        _d(e.get("scheduled_hours") or 0) * _d(e.get("hourly_rate_snapshot") or 0) for e in proposed
    )
    ot_risk_workers = set()
    for e in proposed:
        w = worker_by_id.get(int(e.get("worker_profile_id") or 0))
        if not w:
            continue
        wd = date.fromisoformat(str(e["work_date"])[:10])
        wk_s, wk_e = pwb(conn, wd, oid)
        wh = Decimal("0")
        for x in simulated:
            if int(x.get("worker_profile_id") or 0) == int(w["id"]):
                xd = str(x.get("work_date"))[:10]
                if wk_s.isoformat() <= xd <= wk_e.isoformat():
                    wh += _d(x.get("scheduled_hours") or 0)
        if wh > _overtime_threshold(conn, oid, w):
            ot_risk_workers.add(int(w["id"]))

    coverage_summary: dict[str, dict] = {}
    for e in proposed:
        key = f"{e.get('shift_snapshot')}|{e.get('work_stream_snapshot')}|{e.get('role_snapshot')}"
        coverage_summary.setdefault(
            key,
            {
                "shift": e.get("shift_snapshot"),
                "stream": e.get("work_stream_snapshot"),
                "role": e.get("role_snapshot"),
                "assignments": 0,
                "hours": Decimal("0"),
            },
        )
        coverage_summary[key]["assignments"] += 1
        coverage_summary[key]["hours"] += _d(e.get("scheduled_hours") or 0)

    return json_safe(
        {
            "generator_run_id": gen_run_id,
            "start_date": start_date,
            "end_date": end_date,
            "options": body,
            "proposed_entries": proposed,
            "assignments": assignments,
            "gap_report": gap_report,
            "conflict_report": conflict_report,
            "summary": {
                "assigned_count": len(proposed),
                "gap_count": len(gap_report),
                "conflict_count": len(conflict_report),
                "total_scheduled_hours": _q2(total_hours),
                "estimated_payroll_cost": _q2(total_cost),
                "overtime_risk_worker_count": len(ot_risk_workers),
                "workers_not_used": workers_not_used[:50],
                "workers_underused": workers_underused[:50],
                "workers_incomplete_profiles_used": workers_incomplete_used[:50],
                "coverage_by_shift_role_stream": [
                    {
                        "shift": v["shift"],
                        "stream": v["stream"],
                        "role": v["role"],
                        "assignments": v["assignments"],
                        "hours": _q2(v["hours"]),
                    }
                    for v in coverage_summary.values()
                ],
            },
            "notes": body.get("notes") or "",
            "message": "Draft roster generated — review before publish. Nothing was published.",
        }
    )
