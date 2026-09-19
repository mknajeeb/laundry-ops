"""
Unified scan chronology API — weighing, sorting, washing, drying, folder, and machine utilization.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.rinse_drying_chronology import (
    build_dryer_utilization_payload,
    build_drying_chronology_payload,
)
from backend.rinse_folder_chronology import build_folder_chronology_payload
from backend.rinse_ready_to_fold_chronology import build_ready_to_fold_chronology_payload
from backend.rinse_process_flow_chronology import build_process_flow_chronology_payload
from backend.rinse_sorting_chronology import build_sorting_chronology_payload
from backend.rinse_washing_chronology import (
    build_washer_utilization_payload,
    build_washing_chronology_payload,
)
from backend.rinse_post_processing_weight_chronology import (
    build_post_processing_weight_chronology_payload,
)
from backend.rinse_weighing_chronology import build_weighing_chronology_payload

VALID_STAGES = frozenset(
    {
        "weighing",
        "sorting",
        "washing",
        "drying",
        "folder",
        "washer_utilization",
        "dryer_utilization",
        "coverage_audit",
        "user_activity",
        "ready_to_fold",
        "process_flow",
    }
)

ACTIVITY_TYPES = frozenset(
    {"weighing", "sorting", "washing", "drying", "folder", "post_processing_weight"}
)
VALID_ACTIVITY_TYPE_FILTERS = frozenset({"all", *ACTIVITY_TYPES})

DURATION_STAGES = frozenset({"weighing", "sorting", "folder"})
EVENT_STAGES = frozenset({"washing", "drying"})
UTIL_STAGES = frozenset({"washer_utilization", "dryer_utilization"})

_ACTIVITY_LABELS = {
    "weighing": "Weighing",
    "sorting": "Sorting",
    "washing": "Washing",
    "drying": "Drying",
    "folder": "Folder",
    "post_processing_weight": "Post-processing weight",
}

_UNKNOWN_EMPLOYEE = "Unknown"


def _normalize_sorting_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": row.get("index"),
        "bag_id": row.get("bag_id"),
        "employee": row.get("employee"),
        "start_et": row.get("sort_start_et"),
        "end_et": row.get("sort_end_et"),
        "duration_seconds": row.get("duration_seconds"),
        "next_start_et": row.get("next_sort_start_et"),
        "gap_until_next_seconds": row.get("gap_until_next_seconds"),
        "confidence": row.get("confidence"),
        "source": row.get("source"),
        "start_event_purpose": None,
        "end_event_purpose": row.get("end_event_purpose"),
    }


def _normalize_weighing_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": row.get("index"),
        "bag_id": row.get("bag_id"),
        "employee": row.get("employee"),
        "start_et": row.get("weigh_start_et"),
        "end_et": row.get("weigh_end_et"),
        "duration_seconds": row.get("duration_seconds"),
        "next_start_et": row.get("next_weigh_start_et"),
        "gap_until_next_seconds": row.get("gap_until_next_seconds"),
        "confidence": row.get("confidence"),
        "source": row.get("source"),
        "start_event_purpose": row.get("start_event_purpose"),
        "end_event_purpose": row.get("end_event_purpose"),
    }


def _normalize_sorting_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_start_et": summary.get("first_sort_start_et"),
        "last_end_et": summary.get("last_sort_end_et"),
        "total_sessions": summary.get("total_sessions", 0),
        "total_stage_seconds": summary.get("total_sorting_seconds", 0),
        "average_duration_seconds": summary.get("average_sort_duration_seconds"),
        "total_gap_seconds": summary.get("total_gap_seconds", 0),
    }


def _normalize_weighing_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_start_et": summary.get("first_weigh_start_et"),
        "last_end_et": summary.get("last_weigh_end_et"),
        "total_sessions": summary.get("total_sessions", 0),
        "total_stage_seconds": summary.get("total_weighing_seconds", 0),
        "average_duration_seconds": summary.get("average_weigh_duration_seconds"),
        "total_gap_seconds": summary.get("total_gap_seconds", 0),
    }


def _normalize_folder_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": row.get("index"),
        "bag_id": row.get("bag_id"),
        "employee": row.get("employee"),
        "start_et": row.get("folder_start_et"),
        "end_et": row.get("folder_end_et"),
        "duration_seconds": row.get("duration_seconds"),
        "next_start_et": row.get("next_folder_start_et"),
        "gap_until_next_seconds": row.get("gap_until_next_seconds"),
        "confidence": row.get("confidence"),
        "source": row.get("source"),
        "status": row.get("status"),
        "start_event_purpose": row.get("start_event_purpose"),
        "end_event_purpose": row.get("end_event_purpose"),
        "start_rack": row.get("start_rack"),
        "end_rack": row.get("end_rack"),
        "weight_lbs": row.get("weight_lbs"),
    }


def _normalize_folder_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_start_et": summary.get("first_folder_start_et"),
        "last_end_et": summary.get("last_folder_end_et"),
        "total_sessions": summary.get("total_sessions", 0),
        "complete_sessions": summary.get("complete_sessions", 0),
        "incomplete_sessions": summary.get("incomplete_sessions", 0),
        "total_stage_seconds": summary.get("total_folder_seconds", 0),
        "average_duration_seconds": summary.get("average_folder_duration_seconds"),
        "total_gap_seconds": summary.get("total_gap_seconds", 0),
    }


def _employee_key(name: str | None) -> str:
    cleaned = str(name or "").strip()
    return cleaned or _UNKNOWN_EMPLOYEE


def _activity_from_weighing_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_type": "weighing",
        "activity_label": _ACTIVITY_LABELS["weighing"],
        "time_et": row.get("start_et"),
        "end_et": row.get("end_et"),
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("employee")),
        "machine_or_rack": None,
        "duration_seconds": row.get("duration_seconds"),
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "start_event_purpose": row.get("start_event_purpose"),
        "end_event_purpose": row.get("end_event_purpose"),
    }


def _activity_from_sorting_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_type": "sorting",
        "activity_label": _ACTIVITY_LABELS["sorting"],
        "time_et": row.get("start_et"),
        "end_et": row.get("end_et"),
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("employee")),
        "machine_or_rack": None,
        "duration_seconds": row.get("duration_seconds"),
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "start_event_purpose": row.get("start_event_purpose"),
        "end_event_purpose": row.get("end_event_purpose"),
    }


def _activity_from_washing_session(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("wash_dry_row") and not row.get("washer_rack") and not row.get("wash_time_et"):
        return None
    purpose = "start-cleaning" if row.get("wash_dry_row") else (row.get("event_purpose") or "start-cleaning")
    when = row.get("wash_time_et") if row.get("wash_dry_row") else row.get("timestamp_et")
    return {
        "activity_type": "washing",
        "activity_label": _ACTIVITY_LABELS["washing"],
        "time_et": when,
        "end_et": None,
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("washer_employee") or row.get("employee")),
        "machine_or_rack": row.get("washer_rack"),
        "duration_seconds": None,
        "source": purpose,
        "confidence": row.get("confidence"),
        "start_event_purpose": purpose,
        "end_event_purpose": None,
    }


def _activity_from_drying_session(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("wash_dry_row") and not row.get("dryer_rack") and not row.get("dry_time_et"):
        return None
    purpose = "drying" if row.get("wash_dry_row") else (row.get("event_purpose") or "drying")
    when = row.get("dry_time_et") if row.get("wash_dry_row") else row.get("timestamp_et")
    return {
        "activity_type": "drying",
        "activity_label": _ACTIVITY_LABELS["drying"],
        "time_et": when,
        "end_et": None,
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("dryer_employee") or row.get("employee")),
        "machine_or_rack": row.get("dryer_rack"),
        "duration_seconds": None,
        "source": purpose,
        "confidence": row.get("confidence"),
        "start_event_purpose": purpose,
        "end_event_purpose": None,
    }


def _activity_from_folder_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_type": "folder",
        "activity_label": _ACTIVITY_LABELS["folder"],
        "time_et": row.get("start_et") or row.get("end_et"),
        "end_et": row.get("end_et"),
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("employee")),
        "machine_or_rack": row.get("end_rack") or row.get("start_rack"),
        "duration_seconds": row.get("duration_seconds"),
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "status": row.get("status"),
        "start_event_purpose": row.get("start_event_purpose"),
        "end_event_purpose": row.get("end_event_purpose"),
        "weight_lbs": row.get("weight_lbs"),
    }


def _activity_from_post_processing_weight_row(row: dict[str, Any]) -> dict[str, Any]:
    purpose = row.get("event_purpose") or "post_processing_weight"
    return {
        "activity_type": "post_processing_weight",
        "activity_label": _ACTIVITY_LABELS["post_processing_weight"],
        "time_et": row.get("timestamp_et"),
        "end_et": None,
        "bag_id": row.get("bag_id"),
        "employee": _employee_key(row.get("employee")),
        "machine_or_rack": None,
        "duration_seconds": None,
        "source": purpose,
        "confidence": row.get("confidence"),
        "start_event_purpose": purpose,
        "end_event_purpose": None,
    }


def _activity_sort_key(row: dict[str, Any]) -> tuple:
    ts = row.get("time_et")
    return (
        ts is None,
        ts or datetime.min,
        str(row.get("activity_type") or ""),
        str(row.get("bag_id") or ""),
    )


def _employee_activity_summary(activities: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [a["time_et"] for a in activities if a.get("time_et") is not None]
    return {
        "total_activities": len(activities),
        "weighing_count": sum(1 for a in activities if a.get("activity_type") == "weighing"),
        "sorting_sessions": sum(1 for a in activities if a.get("activity_type") == "sorting"),
        "washer_loads": sum(1 for a in activities if a.get("activity_type") == "washing"),
        "dryer_loads": sum(1 for a in activities if a.get("activity_type") == "drying"),
        "folder_sessions": sum(1 for a in activities if a.get("activity_type") == "folder"),
        "post_processing_weight_count": sum(
            1 for a in activities if a.get("activity_type") == "post_processing_weight"
        ),
        "first_activity_et": min(timestamps) if timestamps else None,
        "last_activity_et": max(timestamps) if timestamps else None,
    }


def build_user_activity_summary(activities: list[dict[str, Any]]) -> dict[str, Any]:
    employees = {a.get("employee") for a in activities if a.get("employee")}
    timestamps = [a["time_et"] for a in activities if a.get("time_et") is not None]
    return {
        "active_employees": len(employees),
        "total_activities": len(activities),
        "weighing_count": sum(1 for a in activities if a.get("activity_type") == "weighing"),
        "sorting_sessions": sum(1 for a in activities if a.get("activity_type") == "sorting"),
        "washer_loads": sum(1 for a in activities if a.get("activity_type") == "washing"),
        "dryer_loads": sum(1 for a in activities if a.get("activity_type") == "drying"),
        "folder_sessions": sum(1 for a in activities if a.get("activity_type") == "folder"),
        "post_processing_weight_count": sum(
            1 for a in activities if a.get("activity_type") == "post_processing_weight"
        ),
        "first_activity_et": min(timestamps) if timestamps else None,
        "last_activity_et": max(timestamps) if timestamps else None,
    }


def group_activities_by_employee(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_employee: dict[str, list[dict[str, Any]]] = {}
    for row in activities:
        key = _employee_key(row.get("employee"))
        by_employee.setdefault(key, []).append(row)

    grouped: list[dict[str, Any]] = []
    for employee, rows in by_employee.items():
        ordered = sorted(rows, key=_activity_sort_key)
        grouped.append(
            {
                "employee": employee,
                "summary": _employee_activity_summary(ordered),
                "activities": ordered,
            }
        )

    grouped.sort(
        key=lambda g: (
            g["summary"].get("first_activity_et") is None,
            g["summary"].get("first_activity_et") or datetime.min,
            str(g.get("employee") or "").casefold(),
        )
    )
    return grouped


def merge_stage_sessions_to_activities(
    *,
    weighing_sessions: list[dict[str, Any]] | None = None,
    sorting_sessions: list[dict[str, Any]] | None = None,
    washing_sessions: list[dict[str, Any]] | None = None,
    drying_sessions: list[dict[str, Any]] | None = None,
    folder_sessions: list[dict[str, Any]] | None = None,
    post_processing_weight_sessions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for row in weighing_sessions or []:
        activities.append(_activity_from_weighing_session(row))
    for row in sorting_sessions or []:
        activities.append(_activity_from_sorting_session(row))
    for row in washing_sessions or []:
        act = _activity_from_washing_session(row)
        if act:
            activities.append(act)
    for row in drying_sessions or []:
        act = _activity_from_drying_session(row)
        if act:
            activities.append(act)
    for row in folder_sessions or []:
        activities.append(_activity_from_folder_session(row))
    for row in post_processing_weight_sessions or []:
        activities.append(_activity_from_post_processing_weight_row(row))
    activities.sort(key=_activity_sort_key)
    return activities


def build_user_activity_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
    activity_type_filter: str | None = None,
) -> dict[str, Any]:
    type_filter = str(activity_type_filter or "all").strip().lower()
    if type_filter not in VALID_ACTIVITY_TYPE_FILTERS:
        raise ValueError(
            f"activity_type must be one of: {', '.join(sorted(VALID_ACTIVITY_TYPE_FILTERS))}"
        )

    common_kwargs = {
        "employee_filter": employee_filter,
        "bag_id_filter": bag_id_filter,
        "confidence_filter": confidence_filter,
        "machine_filter": machine_filter,
    }

    weighing_sessions: list[dict[str, Any]] = []
    sorting_sessions: list[dict[str, Any]] = []
    washing_sessions: list[dict[str, Any]] = []
    drying_sessions: list[dict[str, Any]] = []
    folder_sessions: list[dict[str, Any]] = []
    post_processing_weight_sessions: list[dict[str, Any]] = []

    needs_ops = type_filter in ("all", "weighing", "sorting", "washing", "drying")
    ops_views = None
    if needs_ops:
        from backend.rinse_operational_day import (
            chronology_payload_from_views,
            load_operational_day,
        )

        ops_views = load_operational_day(cursor, organization_id, selected_date_et)
        ops_filters = {
            "employee_filter": employee_filter,
            "bag_id_filter": bag_id_filter,
            "confidence_filter": confidence_filter,
            "machine_filter": machine_filter,
        }
        if type_filter in ("all", "weighing"):
            weighing_sessions = chronology_payload_from_views(
                ops_views, "weighing", **{k: v for k, v in ops_filters.items() if k != "machine_filter"}
            ).get("sessions") or []
        if type_filter in ("all", "sorting"):
            sorting_sessions = chronology_payload_from_views(
                ops_views, "sorting", **{k: v for k, v in ops_filters.items() if k != "machine_filter"}
            ).get("sessions") or []
        if type_filter in ("all", "washing"):
            washing_sessions = chronology_payload_from_views(
                ops_views, "washing", **ops_filters
            ).get("sessions") or []
        if type_filter in ("all", "drying"):
            drying_sessions = chronology_payload_from_views(
                ops_views, "drying", **ops_filters
            ).get("sessions") or []

    if type_filter in ("all", "folder"):
        folder_payload = build_scan_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            stage="folder",
            **{k: v for k, v in common_kwargs.items() if k != "machine_filter"},
        )
        folder_sessions = folder_payload.get("sessions") or []

    if type_filter in ("all", "post_processing_weight"):
        ppw_payload = build_post_processing_weight_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
        )
        post_processing_weight_sessions = ppw_payload.get("sessions") or []

    activities = merge_stage_sessions_to_activities(
        weighing_sessions=weighing_sessions,
        sorting_sessions=sorting_sessions,
        washing_sessions=washing_sessions,
        drying_sessions=drying_sessions,
        folder_sessions=folder_sessions,
        post_processing_weight_sessions=post_processing_weight_sessions,
    )

    employee_names = sorted(
        {a.get("employee") for a in activities if a.get("employee")},
        key=lambda name: str(name).casefold(),
    )

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "user_activity",
        "activity_type_filter": type_filter,
        "summary": build_user_activity_summary(activities),
        "employees": employee_names,
        "employee_groups": group_activities_by_employee(activities),
        "machines": [],
        "event_purposes": None,
        "grouping_rules": (
            "User activity merges weighing, sorting, washing, drying, folder, and "
            "post-processing weight chronology builders for the selected ET day; "
            "activities are grouped by employee and ordered chronologically within "
            "each employee."
        ),
    }


def build_scan_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    stage: str = "sorting",
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
    activity_type_filter: str | None = None,
    drying_duration_minutes: int | None = None,
    order_type_filter: str | None = None,
    status_filter: str | None = None,
    view_mode: str | None = None,
) -> dict[str, Any]:
    stage_key = str(stage or "sorting").strip().lower()
    if stage_key not in VALID_STAGES:
        raise ValueError(f"stage must be one of: {', '.join(sorted(VALID_STAGES))}")

    if stage_key == "user_activity":
        return build_user_activity_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
            machine_filter=machine_filter,
            activity_type_filter=activity_type_filter,
        )

    if stage_key == "ready_to_fold":
        return build_ready_to_fold_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            drying_duration_minutes=drying_duration_minutes,
            bag_id_filter=bag_id_filter,
            machine_filter=machine_filter,
            order_type_filter=order_type_filter,
            status_filter=status_filter,
            view_mode=view_mode,
            employee_filter=employee_filter,
            confidence_filter=confidence_filter,
        )

    if stage_key == "process_flow":
        return build_process_flow_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
            drying_duration_minutes=drying_duration_minutes,
            employee_filter=employee_filter,
            machine_filter=machine_filter,
            activity_type_filter=activity_type_filter,
            order_type_filter=order_type_filter,
            status_filter=status_filter,
            view_mode=view_mode,
        )

    if stage_key == "coverage_audit":
        from backend.rinse_scan_coverage_audit import build_scan_coverage_audit_payload

        return build_scan_coverage_audit_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
        )

    operational_stages = {
        "weighing",
        "sorting",
        "washing",
        "drying",
        "washer_utilization",
        "dryer_utilization",
    }
    operational_performance = None
    if stage_key in operational_stages:
        from backend.rinse_operational_day import build_operational_chronology_payload

        raw = build_operational_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            stage=stage_key,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
            machine_filter=machine_filter,
        )
        sessions = raw.get("sessions") or []
        summary = raw.get("summary") or {}
        grouping_rules = raw.get("grouping_rules")
        event_purposes = raw.get("event_purposes")
        employees = raw.get("employees") or []
        machines = raw.get("machines") or []
        operational_performance = raw.get("operational_performance")
    elif stage_key == "folder":
        raw = build_folder_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
        )
        sessions = [_normalize_folder_session(r) for r in raw.get("sessions") or []]
        summary = _normalize_folder_summary(raw.get("summary") or {})
        grouping_rules = raw.get("grouping_rules")
        event_purposes = raw.get("event_purposes")
        employees = raw.get("employees") or []
        machines = []
    else:
        raise ValueError(f"stage must be one of: {', '.join(sorted(VALID_STAGES))}")
    payload = {
        "date_et": selected_date_et.isoformat(),
        "stage": stage_key,
        "summary": summary,
        "sessions": sessions,
        "employees": employees,
        "machines": machines,
        "event_purposes": event_purposes,
        "grouping_rules": grouping_rules,
    }
    if operational_performance is not None:
        payload["operational_performance"] = operational_performance
        payload["raw_json_loaded"] = False
    return payload
