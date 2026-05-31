"""
Live monitor alerts, step metrics, and staff performance for Shift Analysis.

Uses lifecycle status, bag gaming stages, and pending rows — no independent lifecycle logic.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_gaming_performance import (
    ACTIVITY_SORTING,
    ACTIVITY_WEIGHING,
    STAGE_COMPLETED,
    build_bag_activity_slices,
    evaluate_bag_gaming_performance,
)
from backend.rinse_bag_lifecycle_status import (
    CHECKOUT_STATUS_NEEDS_REVIEW,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    PENDING_WEIGHING,
    SORTED_READY_FOR_WASH,
)
from backend.rinse_bag_stage_bounds import event_ts, ts_valid
from backend.rinse_processing_settings import (
    DEFAULT_DRYING_MINUTES,
    DEFAULT_WASHING_MINUTES,
)
from backend.rinse_shift_analysis import enrich_record_scoring_fields
from backend.ta_helpers import table_exists

KEY_PENDING_WEIGHING_ALERT = "pending_weighing_alert_minutes"
KEY_SORTING_ALERT = "sorting_alert_minutes"
KEY_WAITING_WASHER_ALERT = "waiting_for_washer_alert_minutes"
KEY_WASHING_GRACE = "washing_grace_minutes"
KEY_DRYING_GRACE = "drying_grace_minutes"
KEY_FOLDING_ALERT = "folding_alert_minutes"
KEY_POST_CLEAN_HANDOFF = "post_clean_handoff_alert_minutes"

DEFAULT_PENDING_WEIGHING_ALERT = 30
DEFAULT_SORTING_ALERT = 45
DEFAULT_WAITING_WASHER_ALERT = 20
DEFAULT_WASHING_GRACE = 5
DEFAULT_DRYING_GRACE = 5
DEFAULT_FOLDING_ALERT = 60
DEFAULT_POST_CLEAN_HANDOFF = 30

ALERT_PENDING_WEIGHING = "PENDING_WEIGHING_OVER_LIMIT"
ALERT_WAITING_WASHER = "WAITING_FOR_WASHER_OVER_LIMIT"
ALERT_IN_WASHING = "IN_WASHING_OVER_LIMIT"
ALERT_IN_DRYING = "IN_DRYING_OVER_LIMIT"
ALERT_FOLDED_NOT_SENT = "FOLDED_NOT_SENT_TO_RINSE"
ALERT_CREATE_ISSUE = "HAS_CREATE_ISSUE"
ALERT_WORKITEM = "HAS_WORKITEM"
ALERT_CHECKOUT_REVIEW = "CHECKOUT_NEEDS_REVIEW"

STEP_DEFS: tuple[tuple[str, str, str], ...] = (
    ("weighing", "Weighing", "weighing"),
    ("sorting", "Sorting / Prep", "sorting"),
    ("load_washer", "Load Washer", "load_washer"),
    ("in_washing", "In Washing", "in_washing"),
    ("load_dryer", "Load Dryer", "load_dryer"),
    ("in_drying", "In Drying", "in_drying"),
    ("folding", "Folding", "folding"),
)

TASK_LABELS = {
    "weighing": "Weighing",
    "sorting": "Sorting / Prep",
    "load_washer": "Load Washer",
    "load_dryer": "Load Dryer",
    "wash_load": "Wash / Load",
    "folding": "Folding",
}


def _get_setting_int(cursor, organization_id: int, key: str, default: int) -> int:
    if not table_exists(cursor, "system_settings"):
        return default
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return default
    raw = row.get("svalue") if isinstance(row, dict) else row[0]
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return default


def get_monitor_settings(cursor, organization_id: int, proc_settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    proc = proc_settings or {}
    org = int(organization_id)
    return {
        "pending_weighing_alert_minutes": _get_setting_int(
            cursor, org, KEY_PENDING_WEIGHING_ALERT, DEFAULT_PENDING_WEIGHING_ALERT
        ),
        "sorting_alert_minutes": _get_setting_int(
            cursor, org, KEY_SORTING_ALERT, DEFAULT_SORTING_ALERT
        ),
        "waiting_for_washer_alert_minutes": _get_setting_int(
            cursor, org, KEY_WAITING_WASHER_ALERT, DEFAULT_WAITING_WASHER_ALERT
        ),
        "washing_grace_minutes": _get_setting_int(
            cursor, org, KEY_WASHING_GRACE, DEFAULT_WASHING_GRACE
        ),
        "drying_grace_minutes": _get_setting_int(
            cursor, org, KEY_DRYING_GRACE, DEFAULT_DRYING_GRACE
        ),
        "folding_alert_minutes": _get_setting_int(
            cursor, org, KEY_FOLDING_ALERT, DEFAULT_FOLDING_ALERT
        ),
        "post_clean_handoff_alert_minutes": _get_setting_int(
            cursor, org, KEY_POST_CLEAN_HANDOFF, DEFAULT_POST_CLEAN_HANDOFF
        ),
        "washing_minutes": int(proc.get("washing_minutes") or DEFAULT_WASHING_MINUTES),
        "drying_minutes": int(proc.get("drying_minutes") or DEFAULT_DRYING_MINUTES),
    }


def _parse_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def _delay_minutes(since: datetime | None, evaluation_time: datetime) -> float | None:
    if not ts_valid(since):
        return None
    sec = (evaluation_time - since).total_seconds()
    return round(sec / 60.0, 1) if sec >= 0 else None


def _agg_stats(durations: list[int]) -> dict[str, Any]:
    if not durations:
        return {
            "bag_count": 0,
            "avg_seconds": None,
            "median_seconds": None,
            "longest_seconds": None,
        }
    return {
        "bag_count": len(durations),
        "avg_seconds": round(statistics.mean(durations), 1),
        "median_seconds": round(statistics.median(durations), 1),
        "longest_seconds": max(durations),
    }


def _performance_label(diff_percent: float | None) -> str | None:
    if diff_percent is None:
        return None
    if diff_percent <= -10:
        return "Top performer"
    if diff_percent < -3:
        return "Above average"
    if diff_percent > 10:
        return "Below average"
    return None


def _bag_weight_lbs(row: Mapping[str, Any]) -> float | None:
    for key in ("weight_lbs", "registry_weight_num", "weight_num"):
        val = row.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def build_live_monitor_payload(
    pending_rows: Sequence[Mapping[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    monitor_settings: Mapping[str, Any],
    evaluation_time: datetime,
    proc_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    proc = proc_settings or {}
    eval_at = evaluation_time
    washing_limit = int(monitor_settings.get("washing_minutes") or DEFAULT_WASHING_MINUTES) + int(
        monitor_settings.get("washing_grace_minutes") or DEFAULT_WASHING_GRACE
    )
    drying_limit = int(monitor_settings.get("drying_minutes") or DEFAULT_DRYING_MINUTES) + int(
        monitor_settings.get("drying_grace_minutes") or DEFAULT_DRYING_GRACE
    )

    alert_buckets: dict[str, dict[str, Any]] = {}
    step_durations: dict[str, list[int]] = {k: [] for k, _, _ in STEP_DEFS}
    step_over: dict[str, int] = {k: 0 for k, _, _ in STEP_DEFS}
    step_rush: dict[str, int] = {k: 0 for k, _, _ in STEP_DEFS}

    def _add_alert(
        alert_type: str,
        *,
        severity: str,
        label: str,
        bag_id: str,
        delay_minutes: float | None,
        rush: bool,
        drilldown: dict[str, Any],
    ) -> None:
        bucket = alert_buckets.setdefault(
            alert_type,
            {
                "severity": severity,
                "type": alert_type,
                "label": label,
                "record_count": 0,
                "rush_count": 0,
                "delays_minutes": [],
                "longest_delay_minutes": None,
                "avg_delay_minutes": None,
                "drilldown_filter": drilldown,
                "bag_ids": [],
            },
        )
        bucket["record_count"] += 1
        if rush:
            bucket["rush_count"] += 1
        if delay_minutes is not None:
            bucket["delays_minutes"].append(delay_minutes)
        bucket["bag_ids"].append(bag_id)
        if severity == "critical" or bucket["severity"] != "critical":
            if severity == "critical":
                bucket["severity"] = "critical"
            elif severity == "warning" and bucket["severity"] == "info":
                bucket["severity"] = "warning"

    for row in pending_rows:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        rush = bool(row.get("rush"))
        status = str(row.get("current_lifecycle_status") or "").strip()
        status_ts = _parse_dt(row.get("status_timestamp"))
        delay = _delay_minutes(status_ts, eval_at)
        ops = row.get("operational_flags") or {}
        checkout = str(row.get("checkout_status") or "")

        events = events_by_bag.get(bid) or []
        gaming = evaluate_bag_gaming_performance(
            events,
            washing_minutes=int(proc.get("washing_minutes") or DEFAULT_WASHING_MINUTES),
            drying_minutes=int(proc.get("drying_minutes") or DEFAULT_DRYING_MINUTES),
        )
        for step_key, _, gaming_key in STEP_DEFS:
            stage = gaming.get(gaming_key) or {}
            dur = stage.get("duration_seconds")
            if isinstance(dur, int) and dur >= 0 and stage.get("status") == STAGE_COMPLETED:
                step_durations[step_key].append(dur)
                if rush:
                    step_rush[step_key] += 1
                threshold_sec = None
                if step_key == "in_washing":
                    threshold_sec = washing_limit * 60
                elif step_key == "in_drying":
                    threshold_sec = drying_limit * 60
                if threshold_sec is not None and dur > threshold_sec:
                    step_over[step_key] += 1

        if status == PENDING_WEIGHING:
            limit = int(monitor_settings.get("pending_weighing_alert_minutes") or DEFAULT_PENDING_WEIGHING_ALERT)
            if delay is not None and delay > limit:
                sev = "critical" if rush else "warning"
                _add_alert(
                    ALERT_PENDING_WEIGHING,
                    severity=sev,
                    label="Pending weighing too long",
                    bag_id=bid,
                    delay_minutes=delay,
                    rush=rush,
                    drilldown={"source": "monitor", "alert_type": ALERT_PENDING_WEIGHING, "bag_id": bid},
                )

        if status == SORTED_READY_FOR_WASH:
            limit = int(monitor_settings.get("waiting_for_washer_alert_minutes") or DEFAULT_WAITING_WASHER_ALERT)
            if delay is not None and delay > limit:
                sev = "critical" if rush else "warning"
                _add_alert(
                    ALERT_WAITING_WASHER,
                    severity=sev,
                    label="Waiting for washer too long",
                    bag_id=bid,
                    delay_minutes=delay,
                    rush=rush,
                    drilldown={
                        "source": "monitor",
                        "alert_type": ALERT_WAITING_WASHER,
                        "lifecycle_status": SORTED_READY_FOR_WASH,
                        "bag_id": bid,
                    },
                )

        if status == IN_WASHING and delay is not None and delay > washing_limit:
            sev = "critical" if rush else "warning"
            _add_alert(
                ALERT_IN_WASHING,
                severity=sev,
                label="In washing past expected time",
                bag_id=bid,
                delay_minutes=delay,
                rush=rush,
                drilldown={"source": "monitor", "alert_type": ALERT_IN_WASHING, "lifecycle_status": IN_WASHING, "bag_id": bid},
            )

        if status == IN_DRYING and delay is not None and delay > drying_limit:
            sev = "critical" if rush else "warning"
            _add_alert(
                ALERT_IN_DRYING,
                severity=sev,
                label="In drying past expected time",
                bag_id=bid,
                delay_minutes=delay,
                rush=rush,
                drilldown={"source": "monitor", "alert_type": ALERT_IN_DRYING, "lifecycle_status": IN_DRYING, "bag_id": bid},
            )

        if status == FOLDED_COMPLETED:
            limit = int(monitor_settings.get("post_clean_handoff_alert_minutes") or DEFAULT_POST_CLEAN_HANDOFF)
            if delay is not None and delay > limit:
                _add_alert(
                    ALERT_FOLDED_NOT_SENT,
                    severity="warning",
                    label="Folded but not sent to Rinse",
                    bag_id=bid,
                    delay_minutes=delay,
                    rush=rush,
                    drilldown={"source": "monitor", "alert_type": ALERT_FOLDED_NOT_SENT, "lifecycle_status": FOLDED_COMPLETED, "bag_id": bid},
                )

        if ops.get("has_create_issue"):
            _add_alert(
                ALERT_CREATE_ISSUE,
                severity="warning",
                label="Bag with create-issue",
                bag_id=bid,
                delay_minutes=None,
                rush=rush,
                drilldown={"source": "monitor", "alert_type": ALERT_CREATE_ISSUE, "bag_id": bid},
            )

        if ops.get("has_create_workitem") or ops.get("has_workitem") or ops.get("has_create_bulk_workitem"):
            _add_alert(
                ALERT_WORKITEM,
                severity="info",
                label="Bag with workitem",
                bag_id=bid,
                delay_minutes=None,
                rush=rush,
                drilldown={"source": "monitor", "alert_type": ALERT_WORKITEM, "bag_id": bid},
            )

        if checkout == CHECKOUT_STATUS_NEEDS_REVIEW:
            _add_alert(
                ALERT_CHECKOUT_REVIEW,
                severity="warning",
                label="Checkout needs review",
                bag_id=bid,
                delay_minutes=None,
                rush=rush,
                drilldown={"source": "monitor", "alert_type": ALERT_CHECKOUT_REVIEW, "bag_id": bid},
            )

    alerts: list[dict[str, Any]] = []
    for alert_type, bucket in alert_buckets.items():
        delays = bucket.pop("delays_minutes", [])
        bag_ids = bucket.pop("bag_ids", [])
        if delays:
            bucket["avg_delay_minutes"] = round(statistics.mean(delays), 1)
            bucket["longest_delay_minutes"] = round(max(delays), 1)
        count = bucket["record_count"]
        rush_n = bucket["rush_count"]
        base_label = bucket["label"]
        if alert_type == ALERT_WAITING_WASHER and rush_n:
            bucket["label"] = f"{rush_n} Rush bag{'s' if rush_n != 1 else ''} waiting for washer over limit"
        elif alert_type == ALERT_PENDING_WEIGHING:
            bucket["label"] = f"{count} bag{'s' if count != 1 else ''} pending weighing too long"
        else:
            bucket["label"] = f"{base_label} ({count})"
        bucket["drilldown_filter"]["bag_ids"] = bag_ids
        alerts.append(bucket)

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (severity_order.get(a.get("severity"), 9), -(a.get("record_count") or 0)))

    step_metrics: list[dict[str, Any]] = []
    for step_key, label, _ in STEP_DEFS:
        stats = _agg_stats(step_durations[step_key])
        step_metrics.append(
            {
                "step": step_key,
                "label": label,
                **stats,
                "over_limit_count": step_over[step_key],
                "rush_count": step_rush[step_key],
                "drilldown_filter": {"source": "monitor", "step": step_key},
            }
        )

    return {
        "alerts": alerts,
        "step_metrics": step_metrics,
        "transition_metrics": [],
        "monitor_settings": dict(monitor_settings),
        "evaluation_time": eval_at.isoformat(),
    }


def build_staff_performance_payload(
    pending_rows: Sequence[Mapping[str, Any]],
    *,
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    folding_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    folding_by_bag = {
        str(r.get("bag_id") or "").strip(): r
        for r in (folding_rows or [])
        if isinstance(r, dict) and r.get("bag_id")
    }

    task_records: list[dict[str, Any]] = []
    task_durations: dict[tuple[str, str], list[int]] = {}
    task_meta: dict[tuple[str, str], dict[str, Any]] = {}

    for row in pending_rows:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip()
        if not bid:
            continue
        events = events_by_bag.get(bid) or []
        if not events:
            continue
        fold_row = folding_by_bag.get(bid) or {}
        fold_enriched = enrich_record_scoring_fields(fold_row) if fold_row else {}
        in_scoring = bool(fold_enriched.get("in_scoring")) if fold_row else None
        weight = _bag_weight_lbs(row) or _bag_weight_lbs(fold_row)

        gaming = evaluate_bag_gaming_performance(events)
        slices = {sl.activity: sl for sl in build_bag_activity_slices(bid, events)}

        perf_stages = [
            ("weighing", gaming.get("weighing"), slices.get(ACTIVITY_WEIGHING)),
            ("sorting", gaming.get("sorting"), slices.get(ACTIVITY_SORTING)),
            ("load_washer", gaming.get("load_washer"), None),
            ("load_dryer", gaming.get("load_dryer"), None),
            ("folding", gaming.get("folding"), slices.get("folding")),
        ]
        for task, stage, sl in perf_stages:
            if not isinstance(stage, dict):
                continue
            dur = stage.get("duration_seconds")
            assigned = sl.assigned_user if sl else None
            if task == "folding":
                assigned = fold_row.get("assigned_user_name") or assigned

            employee = str(assigned or "Unassigned").strip() or "Unassigned"
            if dur is None and stage.get("status") != STAGE_COMPLETED:
                continue
            key = (employee, task)
            meta = task_meta.setdefault(
                key,
                {
                    "employee_name": employee,
                    "task": task,
                    "task_label": TASK_LABELS.get(task, task),
                    "bag_count": 0,
                    "lbs": 0.0,
                    "needs_review_count": 0,
                    "exception_count": 0,
                    "scoring_bags": 0,
                    "not_scoring_bags": 0,
                },
            )
            meta["bag_count"] += 1
            if weight:
                meta["lbs"] = round(float(meta["lbs"]) + weight, 2)
            if row.get("needs_review"):
                meta["needs_review_count"] += 1
            if row.get("exception_flags"):
                meta["exception_count"] += len(row.get("exception_flags") or [])
            if in_scoring is True:
                meta["scoring_bags"] += 1
            elif in_scoring is False:
                meta["not_scoring_bags"] += 1
            if isinstance(dur, int) and dur >= 0:
                task_durations.setdefault(key, []).append(dur)

            task_records.append(
                {
                    "bag_id": bid,
                    "customer": row.get("customer") or row.get("name_clean"),
                    "rush_label": row.get("rush_label"),
                    "task": task,
                    "task_label": TASK_LABELS.get(task, task),
                    "employee_name": employee,
                    "lifecycle_status": row.get("current_lifecycle_status"),
                    "start_time": stage.get("start_time"),
                    "end_time": stage.get("end_time"),
                    "duration_seconds": dur,
                    "weight_lbs": weight,
                    "in_scoring": in_scoring,
                    "reason_not_scoring": fold_enriched.get("reason_not_scoring"),
                    "exception_flags": list(row.get("exception_flags") or []),
                    "operational_flags": row.get("operational_flags") or {},
                    "needs_review": bool(row.get("needs_review")),
                }
            )

    shift_avg: dict[str, float] = {}
    by_task: dict[str, list[int]] = {}
    for (employee, task), durs in task_durations.items():
        if durs:
            by_task.setdefault(task, []).extend(durs)
    for task, durs in by_task.items():
        if durs:
            shift_avg[task] = statistics.mean(durs)

    tasks: list[dict[str, Any]] = []
    for (employee, task), meta in sorted(task_meta.items(), key=lambda x: (x[0][0].lower(), x[0][1])):
        durs = task_durations.get((employee, task), [])
        avg_sec = round(statistics.mean(durs), 1) if durs else None
        shift_task_avg = shift_avg.get(task)
        diff_pct = None
        if avg_sec is not None and shift_task_avg:
            diff_pct = round((avg_sec - shift_task_avg) / shift_task_avg * 100.0, 1)
        hours = sum(durs) / 3600.0 if durs else 0
        bags = meta["bag_count"]
        tasks.append(
            {
                **meta,
                "avg_seconds_per_bag": avg_sec,
                "bags_per_hour": round(bags / hours, 2) if hours > 0 else None,
                "lbs_per_hour": round(meta["lbs"] / hours, 2) if hours > 0 and meta["lbs"] else None,
                "shift_avg_seconds_per_bag": round(shift_task_avg, 1) if shift_task_avg else None,
                "difference_percent": diff_pct,
                "performance_label": _performance_label(diff_pct),
                "rank": None,
            }
        )

    by_task_rank: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        by_task_rank.setdefault(t["task"], []).append(t)
    for task_list in by_task_rank.values():
        ranked = sorted(
            task_list,
            key=lambda x: (x.get("avg_seconds_per_bag") is None, x.get("avg_seconds_per_bag") or 999999),
        )
        for i, t in enumerate(ranked, start=1):
            t["rank"] = i

    employees_map: dict[str, dict[str, Any]] = {}
    for t in tasks:
        name = t["employee_name"]
        emp = employees_map.setdefault(
            name,
            {
                "employee_name": name,
                "bag_count": 0,
                "lbs": 0.0,
                "tasks": [],
                "needs_review_count": 0,
                "exception_count": 0,
                "scoring_bags": 0,
                "not_scoring_bags": 0,
            },
        )
        emp["bag_count"] += t["bag_count"]
        emp["lbs"] = round(float(emp["lbs"]) + float(t.get("lbs") or 0), 2)
        emp["needs_review_count"] += t.get("needs_review_count") or 0
        emp["exception_count"] += t.get("exception_count") or 0
        emp["scoring_bags"] += t.get("scoring_bags") or 0
        emp["not_scoring_bags"] += t.get("not_scoring_bags") or 0
        emp["tasks"].append(t["task"])

    return {
        "tasks": tasks,
        "employees": list(employees_map.values()),
        "records": task_records,
    }


def filter_monitor_records(
    pending_rows: Sequence[Mapping[str, Any]],
    staff_records: Sequence[Mapping[str, Any]],
    drilldown: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not drilldown or drilldown.get("source") != "monitor":
        return []
    alert_type = drilldown.get("alert_type")
    bag_ids = set(drilldown.get("bag_ids") or [])
    if drilldown.get("bag_id"):
        bag_ids.add(str(drilldown.get("bag_id")))
    lifecycle_status = drilldown.get("lifecycle_status")
    step = drilldown.get("step")
    employee = drilldown.get("employee_name")
    task = drilldown.get("task")
    scoring_filter = drilldown.get("scoring_filter")

    if step or employee or task or scoring_filter:
        out = []
        for rec in staff_records:
            if not isinstance(rec, dict):
                continue
            if step and rec.get("task") != step:
                continue
            if employee and rec.get("employee_name") != employee:
                continue
            if task and rec.get("task") != task:
                continue
            if scoring_filter == "scoring" and not rec.get("in_scoring"):
                continue
            if scoring_filter == "not_scoring" and rec.get("in_scoring") is not False:
                continue
            if scoring_filter == "needs_review" and not rec.get("needs_review"):
                continue
            out.append({**rec, "activity": "staff"})
        return out

    out = []
    for row in pending_rows:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip()
        if bag_ids and bid not in bag_ids:
            continue
        if lifecycle_status and row.get("current_lifecycle_status") != lifecycle_status:
            continue
        if alert_type == ALERT_CREATE_ISSUE and not (row.get("operational_flags") or {}).get("has_create_issue"):
            continue
        if alert_type == ALERT_WORKITEM:
            ops = row.get("operational_flags") or {}
            if not (ops.get("has_create_workitem") or ops.get("has_workitem") or ops.get("has_create_bulk_workitem")):
                continue
        if alert_type == ALERT_CHECKOUT_REVIEW and row.get("checkout_status") != CHECKOUT_STATUS_NEEDS_REVIEW:
            continue
        out.append({**row, "activity": "lifecycle"})
    return out
