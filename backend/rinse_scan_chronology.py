"""
Unified scan chronology API — weighing and sorting stages.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.rinse_sorting_chronology import build_sorting_chronology_payload
from backend.rinse_weighing_chronology import build_weighing_chronology_payload

VALID_STAGES = frozenset({"weighing", "sorting"})


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


def build_scan_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    stage: str = "sorting",
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
) -> dict[str, Any]:
    stage_key = str(stage or "sorting").strip().lower()
    if stage_key not in VALID_STAGES:
        raise ValueError(f"stage must be one of: {', '.join(sorted(VALID_STAGES))}")

    if stage_key == "weighing":
        raw = build_weighing_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
        )
        sessions = [_normalize_weighing_session(r) for r in raw.get("sessions") or []]
        summary = _normalize_weighing_summary(raw.get("summary") or {})
        grouping_rules = raw.get("grouping_rules")
        event_purposes = raw.get("weighing_event_purposes")
        employees = raw.get("employees") or []
    else:
        raw = build_sorting_chronology_payload(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            employee_filter=employee_filter,
            bag_id_filter=bag_id_filter,
            confidence_filter=confidence_filter,
        )
        sessions = [_normalize_sorting_session(r) for r in raw.get("sessions") or []]
        summary = _normalize_sorting_summary(raw.get("summary") or {})
        grouping_rules = raw.get("grouping_rules")
        event_purposes = raw.get("sorting_event_purposes")
        employees = raw.get("employees") or []

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": stage_key,
        "summary": summary,
        "sessions": sessions,
        "employees": employees,
        "event_purposes": event_purposes,
        "grouping_rules": grouping_rules,
    }
