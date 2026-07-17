"""
Completed-bags reconciliation — raw evidence vs dashboard (ET day).

Compares independent sources without treating the dashboard as ground truth:

  - Scan-evidence WF completions (post-processing weight chronology)
  - Registry COMPLETED with completed_at on the ET day
  - At Vendor / employee-productivity Completed Today
  - Near-complete signals (complete-cleaning today without post-weight)

Invariant (WF Only scope)::

    scan_evidence_completed
      == dashboard_completed
      == employee_attributed
      + unassigned
      + unreconciled   (should be empty when healthy)

Any bag that looks completed in raw evidence but is absent from the dashboard
must appear in ``unreconciled`` with an explicit exclusion reason — never silently
dropped.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.ta_helpers import table_exists


EXCLUSION_WRONG_ET_DAY = "wrong_et_day"
EXCLUSION_DIFFERENT_LIFECYCLE = "different_lifecycle"
EXCLUSION_MISSING_POST_WEIGHT = "missing_post_processing_weight"
EXCLUSION_REGISTRY_REJECTED = "registry_rejected"
EXCLUSION_PORTAL_DISAPPEARED = "portal_disappeared_scrape_rejected"
EXCLUSION_MISSING_EMPLOYEE = "missing_employee_credit"
EXCLUSION_MISSING_WEIGHT = "missing_weight_lbs"
EXCLUSION_HD_FILTER = "hd_filtered_from_wf_only"
EXCLUSION_DUPLICATE = "duplicate_suppression"
EXCLUSION_NOT_IN_WORKLOAD = "not_in_days_load_membership"
EXCLUSION_OTHER = "other"

_EXCLUSION_LABELS = {
    EXCLUSION_WRONG_ET_DAY: "Wrong ET day",
    EXCLUSION_DIFFERENT_LIFECYCLE: "Different lifecycle / prior trip",
    EXCLUSION_MISSING_POST_WEIGHT: "Missing post-processing weight",
    EXCLUSION_REGISTRY_REJECTED: "Registry rejected",
    EXCLUSION_PORTAL_DISAPPEARED: "Portal scrape rejected / disappeared",
    EXCLUSION_MISSING_EMPLOYEE: "Missing employee credit",
    EXCLUSION_MISSING_WEIGHT: "Missing weight lbs",
    EXCLUSION_HD_FILTER: "HD filtered out of WF Only scope",
    EXCLUSION_DUPLICATE: "Duplicate suppression",
    EXCLUSION_NOT_IN_WORKLOAD: "Not in Day's Load membership",
    EXCLUSION_OTHER: "Other",
}


def _norm(bid: Any) -> str:
    return str(bid or "").strip().upper()


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _load_registry_rows(cursor, org: int, bag_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({_norm(b) for b in bag_ids if _norm(b)})
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk = 400
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT UPPER(TRIM(bag_id)) AS bag_id, service_type, completion_status,
                   completion_reason, completed_at, date_clean, name_clean, weight_num
            FROM rinse_bag_registry
            WHERE organization_id = %s AND UPPER(TRIM(bag_id)) IN ({placeholders})
            """,
            (int(org), *part),
        )
        for row in cursor.fetchall() or []:
            if isinstance(row, dict) and row.get("bag_id"):
                out[_norm(row["bag_id"])] = row
    return out


def _load_wf_complete_cleaning_today(
    cursor, org: int, *, day_start: datetime, day_end: datetime
) -> dict[str, dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    cursor.execute(
        """
        SELECT UPPER(TRIM(s.bag_id)) AS bag_id, s.user_name, s.scanned_at_parsed,
               r.service_type, r.completion_status, r.completion_reason,
               r.name_clean, r.weight_num, r.completed_at, r.date_clean
        FROM rinse_bag_scan_events s
        LEFT JOIN rinse_bag_registry r
          ON r.organization_id = s.organization_id
         AND UPPER(TRIM(r.bag_id)) = UPPER(TRIM(s.bag_id))
        WHERE s.organization_id = %s
          AND s.scanned_at_parsed >= %s AND s.scanned_at_parsed < %s
          AND s.purpose = 'complete-cleaning'
          AND UPPER(COALESCE(r.service_type, 'WF')) = 'WF'
        ORDER BY s.scanned_at_parsed
        """,
        (int(org), day_start, day_end),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = _norm(row.get("bag_id"))
        if bid and bid not in out:
            out[bid] = row
    return out


def _load_registry_completed_et_day(
    cursor, org: int, *, day_start: datetime, day_end: datetime, service: str = "WF"
) -> dict[str, dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_registry"):
        return {}
    cursor.execute(
        """
        SELECT UPPER(TRIM(bag_id)) AS bag_id, service_type, completion_status,
               completion_reason, completed_at, date_clean, name_clean, weight_num
        FROM rinse_bag_registry
        WHERE organization_id = %s
          AND UPPER(COALESCE(service_type, '')) = %s
          AND UPPER(COALESCE(completion_status, '')) = 'COMPLETED'
          AND completed_at >= %s AND completed_at < %s
        """,
        (int(org), str(service).upper(), day_start, day_end),
    )
    return {
        _norm(r["bag_id"]): r
        for r in (cursor.fetchall() or [])
        if isinstance(r, dict) and r.get("bag_id")
    }


def _scan_evidence_wf_completed_ids(cursor, org: int, selected_date_et: date) -> set[str]:
    from backend.rinse_post_processing_weight_chronology import (
        build_post_processing_weight_chronology_payload,
    )

    payload = build_post_processing_weight_chronology_payload(
        cursor, int(org), selected_date_et=selected_date_et
    )
    sessions = payload.get("sessions") or []
    return {
        _norm(s.get("bag_id"))
        for s in sessions
        if isinstance(s, Mapping) and _norm(s.get("bag_id"))
    }


def _dashboard_completed_ids(
    at_vendor_module: Mapping[str, Any] | None, *, service: str = "WF"
) -> set[str]:
    svc = str(service or "WF").upper()
    out: set[str] = set()
    for row in (at_vendor_module or {}).get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("at_vendor_status") or "") != "Completed":
            continue
        if str(row.get("service_type") or "").upper() != svc:
            continue
        bid = _norm(row.get("bag_id"))
        if bid:
            out.add(bid)
    return out


def _employee_attributed_ids(employee_section: Mapping[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for emp in (employee_section or {}).get("employees") or []:
        if not isinstance(emp, Mapping):
            continue
        for bag in emp.get("bags") or []:
            if isinstance(bag, Mapping):
                bid = _norm(bag.get("bag_id"))
                if bid:
                    out.add(bid)
    return out


def _employee_by_bag(employee_section: Mapping[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for emp in (employee_section or {}).get("employees") or []:
        if not isinstance(emp, Mapping):
            continue
        name = str(emp.get("display_name") or emp.get("employee") or emp.get("employee_name") or "").strip()
        for bag in emp.get("bags") or []:
            if isinstance(bag, Mapping):
                bid = _norm(bag.get("bag_id"))
                if bid and name:
                    out[bid] = name
    return out


def _classify_unreconciled_bag(
    bid: str,
    *,
    reg: Mapping[str, Any] | None,
    cc_row: Mapping[str, Any] | None,
    in_scan_evidence: bool,
    in_dashboard: bool,
    in_attributed: bool,
    service_scope: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    status = str((reg or {}).get("completion_status") or "").upper()
    reason = str((reg or {}).get("completion_reason") or "")
    svc = str((reg or {}).get("service_type") or (cc_row or {}).get("service_type") or "").upper()

    if svc == "HD" and service_scope == "WF":
        reasons.append(EXCLUSION_HD_FILTER)
    if status == "REJECTED":
        reasons.append(EXCLUSION_REGISTRY_REJECTED)
        if "MISSING_FROM_LATEST_PORTAL" in reason:
            reasons.append(EXCLUSION_PORTAL_DISAPPEARED)
    if cc_row and not in_scan_evidence:
        reasons.append(EXCLUSION_MISSING_POST_WEIGHT)
    if (reg or {}).get("weight_num") in (None, 0, 0.0) and not in_scan_evidence:
        reasons.append(EXCLUSION_MISSING_WEIGHT)
    if in_scan_evidence and not in_dashboard:
        reasons.append(EXCLUSION_NOT_IN_WORKLOAD)
    if in_dashboard and not in_attributed:
        reasons.append(EXCLUSION_MISSING_EMPLOYEE)
    if not reasons:
        reasons.append(EXCLUSION_OTHER)

    fix = "Review scan chronology and registry state"
    if EXCLUSION_MISSING_POST_WEIGHT in reasons:
        fix = "Confirm post-processing weight-entry after complete-cleaning (or eligible near-complete recovery)"
    elif EXCLUSION_PORTAL_DISAPPEARED in reasons or EXCLUSION_REGISTRY_REJECTED in reasons:
        fix = "Do not show as Pending; keep in Unreconciled / exceptions until evidence is restored"
    elif EXCLUSION_HD_FILTER in reasons:
        fix = "Appears under HD scope, not WF Only"
    elif EXCLUSION_NOT_IN_WORKLOAD in reasons:
        fix = "Include in Day's Load Completed or explain membership exclusion"
    elif EXCLUSION_MISSING_EMPLOYEE in reasons:
        fix = "Attribute post-processing weight user or mark Unassigned"

    return {
        "bag_id": bid,
        "workflow": svc or None,
        "customer": (reg or {}).get("name_clean") or (cc_row or {}).get("name_clean"),
        "folder": (cc_row or {}).get("user_name"),
        "completed_timestamp": _as_iso(
            (cc_row or {}).get("scanned_at_parsed") or (reg or {}).get("completed_at")
        ),
        "registry_status": status or None,
        "registry_reason": reason or None,
        "portal_status": None,
        "dashboard_status": "Completed" if in_dashboard else "Absent",
        "employee": None,
        "in_scan_evidence": in_scan_evidence,
        "in_dashboard": in_dashboard,
        "in_employee_attributed": in_attributed,
        "exclusion_reasons": reasons,
        "exclusion_labels": [_EXCLUSION_LABELS.get(r, r) for r in reasons],
        "fix_recommendation": fix,
        "why_included_or_excluded": "; ".join(_EXCLUSION_LABELS.get(r, r) for r in reasons),
    }


def build_completed_bags_reconciliation(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    at_vendor_module: Mapping[str, Any] | None = None,
    employee_completed_section: Mapping[str, Any] | None = None,
    service_scope: str = "WF",
    claimed_portal_completed: int | None = None,
) -> dict[str, Any]:
    """Build Today's Completed Reconciliation from raw evidence + dashboard sets."""
    org = int(organization_id)
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_start(selected_date_et + timedelta(days=1))
    scope = str(service_scope or "WF").upper()

    scan_ids = _scan_evidence_wf_completed_ids(cursor, org, selected_date_et) if scope == "WF" else set()
    registry_ids = set(
        _load_registry_completed_et_day(
            cursor, org, day_start=day_start, day_end=day_end, service=scope
        )
    )
    dashboard_ids = _dashboard_completed_ids(at_vendor_module, service=scope)
    attributed_ids = _employee_attributed_ids(employee_completed_section)
    credit_by = _employee_by_bag(employee_completed_section)
    cc_today = _load_wf_complete_cleaning_today(
        cursor, org, day_start=day_start, day_end=day_end
    ) if scope == "WF" else {}

    # Candidate universe: anything that looks completed in any source
    candidates = set(scan_ids) | set(registry_ids) | set(dashboard_ids) | set(attributed_ids) | set(cc_today)
    reg_by = _load_registry_rows(cursor, org, sorted(candidates))

    unreconciled: list[dict[str, Any]] = []
    # Bags with complete-cleaning today (WF) that are not scan-evidence completed
    for bid, cc_row in sorted(cc_today.items()):
        if bid in scan_ids and bid in dashboard_ids and bid in attributed_ids:
            continue
        if bid in scan_ids and bid in dashboard_ids:
            continue
        item = _classify_unreconciled_bag(
            bid,
            reg=reg_by.get(bid) or cc_row,
            cc_row=cc_row,
            in_scan_evidence=bid in scan_ids,
            in_dashboard=bid in dashboard_ids,
            in_attributed=bid in attributed_ids,
            service_scope=scope,
        )
        item["employee"] = credit_by.get(bid)
        unreconciled.append(item)

    # Scan-evidence completed but missing from dashboard or attribution
    for bid in sorted(scan_ids - dashboard_ids):
        if any(u["bag_id"] == bid for u in unreconciled):
            continue
        item = _classify_unreconciled_bag(
            bid,
            reg=reg_by.get(bid),
            cc_row=cc_today.get(bid),
            in_scan_evidence=True,
            in_dashboard=False,
            in_attributed=bid in attributed_ids,
            service_scope=scope,
        )
        item["employee"] = credit_by.get(bid)
        unreconciled.append(item)

    for bid in sorted(dashboard_ids - attributed_ids):
        if any(u["bag_id"] == bid for u in unreconciled):
            continue
        item = _classify_unreconciled_bag(
            bid,
            reg=reg_by.get(bid),
            cc_row=cc_today.get(bid),
            in_scan_evidence=bid in scan_ids,
            in_dashboard=True,
            in_attributed=False,
            service_scope=scope,
        )
        item["employee"] = None
        unreconciled.append(item)

    # Registry COMPLETED on ET day not on dashboard (informational)
    registry_only = sorted(registry_ids - dashboard_ids)
    for bid in registry_only:
        if any(u["bag_id"] == bid for u in unreconciled):
            continue
        item = _classify_unreconciled_bag(
            bid,
            reg=reg_by.get(bid),
            cc_row=cc_today.get(bid),
            in_scan_evidence=bid in scan_ids,
            in_dashboard=False,
            in_attributed=bid in attributed_ids,
            service_scope=scope,
        )
        item["exclusion_reasons"] = list(
            dict.fromkeys([*(item.get("exclusion_reasons") or []), EXCLUSION_OTHER])
        )
        item["why_included_or_excluded"] = (
            "Registry COMPLETED on ET day but not in scan-evidence/dashboard Completed Today"
        )
        item["fix_recommendation"] = (
            "Compare registry completed_at source vs post-processing weight chronology"
        )
        unreconciled.append(item)

    scan_n = len(scan_ids)
    dash_n = len(dashboard_ids)
    attr_n = len(attributed_ids)
    reg_n = len(registry_ids)
    claimed = claimed_portal_completed
    claimed_gap = None if claimed is None else int(claimed) - dash_n

    # Healthy when scan evidence, dashboard, and attribution agree
    sources_agree = scan_n == dash_n == attr_n and not (scan_ids - dashboard_ids) and not (
        dashboard_ids - attributed_ids
    )

    rows_out = []
    for bid in sorted(scan_ids | dashboard_ids):
        reg = reg_by.get(bid) or {}
        cc = cc_today.get(bid) or {}
        rows_out.append(
            {
                "bag_id": bid,
                "workflow": str(reg.get("service_type") or scope).upper(),
                "customer": reg.get("name_clean") or cc.get("name_clean"),
                "folder": cc.get("user_name") or credit_by.get(bid),
                "completed_timestamp": _as_iso(cc.get("scanned_at_parsed") or reg.get("completed_at")),
                "registry_status": reg.get("completion_status"),
                "portal_status": None,
                "dashboard_status": "Completed" if bid in dashboard_ids else "Absent",
                "employee": credit_by.get(bid),
                "why_included_or_excluded": (
                    "Included — scan post-processing weight completion on ET day"
                    if bid in scan_ids
                    else "Excluded from scan evidence"
                ),
            }
        )

    return {
        "selected_date_et": selected_date_et.isoformat(),
        "service_scope": scope,
        "title": "Today's Completed Reconciliation",
        "counts": {
            "claimed_portal_completed": claimed,
            "scan_evidence_completed": scan_n,
            "registry_completed_et_day": reg_n,
            "dashboard_completed": dash_n,
            "employee_attributed": attr_n,
            "complete_cleaning_today_wf": len(cc_today),
            "unreconciled": len(unreconciled),
            "claimed_minus_dashboard": claimed_gap,
            "scan_minus_dashboard": scan_n - dash_n,
            "dashboard_minus_attributed": dash_n - attr_n,
        },
        "invariant": {
            "scan_equals_dashboard": scan_n == dash_n and scan_ids == dashboard_ids,
            "dashboard_equals_attributed": dash_n == attr_n and dashboard_ids == attributed_ids,
            "sources_agree": sources_agree,
            "formula": "scan_evidence_completed == dashboard_completed == employee_attributed (+ unreconciled when not)",
        },
        "bag_ids": {
            "scan_evidence": sorted(scan_ids),
            "registry_completed_et_day": sorted(registry_ids),
            "dashboard_completed": sorted(dashboard_ids),
            "employee_attributed": sorted(attributed_ids),
            "complete_cleaning_today_wf": sorted(cc_today),
        },
        "completed_rows": rows_out,
        "unreconciled": unreconciled,
        "notes": [
            "Scan evidence = post-processing weight chronology (canonical WF Completed Today).",
            "Registry completed_at can lag or use Clean-rack / portal-departure reasons — expect diffs.",
            "claimed_portal_completed is optional operator input; portal scrape has no native ET-day completed counter.",
            (
                f"Operator claimed {claimed} vs dashboard {dash_n} (gap {claimed_gap}). "
                "Gap must be explained by unreconciled rows or an external count not present in Events/Registry."
                if claimed is not None
                else "No claimed portal completed count supplied."
            ),
        ],
    }


def attach_completed_reconciliation_to_module(
    cursor,
    organization_id: int,
    module: dict[str, Any],
    *,
    selected_date_et: date,
    claimed_portal_completed: int | None = None,
) -> dict[str, Any]:
    """Attach reconciliation block onto an At Vendor module dict (mutates and returns)."""
    emp = module.get("employee_completed_bags_today")
    if isinstance(emp, Mapping):
        try:
            from backend.rinse_employee_productivity_presentation import (
                apply_employee_productivity_scope,
            )
            from backend.rinse_employee_productivity_settings import (
                include_hd_in_employee_productivity,
            )

            # Completed reconciliation for the ops WF card is WF-only unless HD is enabled.
            include_hd = bool(include_hd_in_employee_productivity(cursor, int(organization_id)))
            emp = apply_employee_productivity_scope(emp, include_hd=include_hd)
        except Exception:
            pass
    block = build_completed_bags_reconciliation(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        at_vendor_module=module,
        employee_completed_section=emp if isinstance(emp, Mapping) else None,
        service_scope="WF",
        claimed_portal_completed=claimed_portal_completed,
    )
    module["completed_bags_reconciliation"] = block
    return module
