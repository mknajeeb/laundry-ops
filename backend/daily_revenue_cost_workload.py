"""Workload integration adapter for Daily Revenue & Cost (Rinse WF pounds)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.daily_revenue_cost_constants import LK_RINSE_WF_POUNDS, SOURCE_WORKLOAD

LBS_Q = Decimal("0.01")


def _cursor_connection(cursor_or_conn) -> Any:
    if cursor_or_conn is None:
        return None
    if callable(getattr(cursor_or_conn, "cursor", None)) and not hasattr(cursor_or_conn, "fetchone"):
        return cursor_or_conn
    parent = getattr(cursor_or_conn, "_dict_connection", None)
    if parent is not None:
        return parent
    return (
        getattr(cursor_or_conn, "connection", None)
        or getattr(cursor_or_conn, "_conn", None)
        or cursor_or_conn
    )


def _wf_service_type(bag: dict) -> str:
    return str(
        bag.get("service_type")
        or bag.get("service_bucket")
        or bag.get("workflow")
        or ""
    ).upper()


def build_workload_wf_daily_pounds(
    employee_completed_section: dict,
    *,
    workload_summary: dict | None = None,
) -> tuple[float, list[dict], dict]:
    """Sum WF post-processing weight_lbs from employee_completed_bags_today."""
    total = Decimal("0")
    records: list[dict] = []
    missing_weight = 0
    for emp in employee_completed_section.get("employees") or []:
        if not isinstance(emp, dict):
            continue
        employee_name = emp.get("employee")
        for bag in emp.get("bags") or []:
            if not isinstance(bag, dict):
                continue
            if _wf_service_type(bag) != "WF":
                continue
            bid = str(bag.get("bag_id") or "").strip().upper()
            lbs_raw = bag.get("weight_lbs")
            if lbs_raw is None:
                missing_weight += 1
                records.append(
                    {
                        "bag_id": bid,
                        "employee": employee_name,
                        "weight_lbs": None,
                        "weight_source": bag.get("weight_source"),
                        "weight_missing": True,
                    }
                )
                continue
            lbs = Decimal(str(lbs_raw)).quantize(LBS_Q, rounding=ROUND_HALF_UP)
            total += lbs
            records.append(
                {
                    "bag_id": bid,
                    "employee": employee_name,
                    "weight_lbs": float(lbs),
                    "weight_source": bag.get("weight_source"),
                    "completion_timestamp": bag.get("completion_timestamp"),
                    "rush_bucket": bag.get("rush_bucket"),
                }
            )

    summary = workload_summary or {}
    counts = {
        "wf_completed_bag_count": len(records),
        "wf_completed_bags_with_weight": len(records) - missing_weight,
        "wf_completed_bags_missing_weight": missing_weight,
        "workload_wf_completed_count": summary.get("wf_completed"),
        "workload_completed_today_count": summary.get("completed_today"),
    }
    return float(total.quantize(LBS_Q, rounding=ROUND_HALF_UP)), records, counts


def fetch_workload_wf_pounds_suggestion(cursor_or_conn, org_id: int, entry_date: date) -> dict | None:
    """Build revenue.rinse_wf.pounds suggestion from ET-day workload completions."""
    conn = _cursor_connection(cursor_or_conn)
    if conn is None:
        return None
    try:
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else cursor_or_conn
        from backend.rinse_at_vendor_module import build_at_vendor_module
        from backend.rinse_shift_monitor_baseline import build_baseline_context, get_shift_monitor_baseline

        baseline = build_baseline_context(cur, int(org_id), get_shift_monitor_baseline(cur, int(org_id)))
        av = build_at_vendor_module(
            cur,
            int(org_id),
            selected_date_et=entry_date,
            baseline_ctx=baseline,
        )
        section = av.get("employee_completed_bags_today") or {}
        workload_summary = {
            "wf_completed": av.get("wf_completed"),
            "completed_today": av.get("completed") or av.get("completed_today_count"),
        }
        total, records, counts = build_workload_wf_daily_pounds(section, workload_summary=workload_summary)
    except Exception:
        return None

    if total <= 0:
        return None

    day = entry_date.isoformat()
    bag_ids = sorted(r["bag_id"] for r in records if r.get("bag_id") and not r.get("weight_missing"))
    source_ref = f"workload-day:{day}:org={int(org_id)}"
    if bag_ids:
        source_ref = f"{source_ref}:bags={','.join(bag_ids[:25])}"

    captured = datetime.utcnow()
    return {
        "line_key": LK_RINSE_WF_POUNDS,
        "source_system": SOURCE_WORKLOAD,
        "quantity": total,
        "source_ref": source_ref,
        "source_captured_at": captured.isoformat(sep=" "),
        "source_payload": {
            "entry_date": day,
            "organization_id": int(org_id),
            "total_pounds": total,
            "calculation": "sum(weight_lbs) for WF completed bags on ET day",
            **counts,
            "records": records[:100],
        },
    }


def workload_line_is_manual_override(line: dict | None) -> bool:
    return bool(line and line.get("is_manual_override"))


def workload_line_is_imported_frozen(line: dict | None) -> bool:
    if not line:
        return False
    source = str(line.get("source_system") or "manual")
    return source != "manual" and not bool(line.get("is_manual_override"))


def should_apply_workload_wf_suggestion(existing_line: dict | None) -> bool:
    """True when GET may auto-fill revenue.rinse_wf.pounds from the adapter."""
    if workload_line_is_manual_override(existing_line):
        return False
    if workload_line_is_imported_frozen(existing_line):
        return False
    if not existing_line:
        return True
    qty = float(existing_line.get("quantity") or 0)
    source = str(existing_line.get("source_system") or "manual")
    if qty == 0 and source == "manual":
        return True
    return False


def suggestion_to_line_row(suggestion: dict) -> dict:
    return {
        "amount": 0,
        "quantity": suggestion["quantity"],
        "source_system": suggestion["source_system"],
        "source_ref": suggestion.get("source_ref"),
        "source_captured_at": suggestion.get("source_captured_at"),
        "source_payload": suggestion.get("source_payload"),
        "is_manual_override": 0,
    }


def resolve_workload_wf_line_for_save(
    *,
    payload_quantity: float,
    overrides: dict,
    existing_line: dict | None,
    suggestion: dict | None,
) -> dict:
    """Resolve quantity + source metadata for revenue.rinse_wf.pounds on save."""
    from backend.daily_revenue_cost_constants import SOURCE_MANUAL

    override_info = overrides.get(LK_RINSE_WF_POUNDS) or {}
    is_override = bool(override_info.get("is_manual_override"))
    override_reason = override_info.get("reason")

    if workload_line_is_manual_override(existing_line) or is_override:
        return {
            "quantity": payload_quantity,
            "source_system": (existing_line or {}).get("source_system") or SOURCE_WORKLOAD,
            "source_ref": (existing_line or {}).get("source_ref"),
            "source_payload": (existing_line or {}).get("source_payload"),
            "source_captured_at": (existing_line or {}).get("source_captured_at"),
            "is_override": True,
            "override_reason": override_reason or (existing_line or {}).get("override_reason"),
        }

    if workload_line_is_imported_frozen(existing_line):
        return {
            "quantity": float(existing_line.get("quantity") or 0),
            "source_system": existing_line.get("source_system"),
            "source_ref": existing_line.get("source_ref"),
            "source_payload": existing_line.get("source_payload"),
            "source_captured_at": existing_line.get("source_captured_at"),
            "is_override": False,
            "override_reason": None,
        }

    if suggestion and should_apply_workload_wf_suggestion(existing_line):
        if payload_quantity == suggestion["quantity"] or (
            not existing_line and payload_quantity == suggestion["quantity"]
        ):
            return {
                "quantity": suggestion["quantity"],
                "source_system": suggestion["source_system"],
                "source_ref": suggestion.get("source_ref"),
                "source_payload": suggestion.get("source_payload"),
                "source_captured_at": suggestion.get("source_captured_at"),
                "is_override": False,
                "override_reason": None,
            }

    return {
        "quantity": payload_quantity,
        "source_system": SOURCE_MANUAL,
        "source_ref": None,
        "source_payload": None,
        "source_captured_at": None,
        "is_override": False,
        "override_reason": None,
    }
