"""FOLDER role publisher — translates Management WF Folder session cards to snapshots.

Does not recalculate Folder performance; reads canonical Management cards.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from backend.management_wf_folder_performance import build_day_folder_performance
from backend.rinse_folding_settings import get_rinse_folding_benchmarks, put_rinse_folding_benchmarks
from backend.rinse_performance_approvals import (
    approval_status_map,
    folder_session_fingerprint,
    invalidate_approvals,
    session_is_approvable,
    upsert_approved_snapshot,
)
from backend.rinse_performance_roles import (
    FOLDER_BENCHMARK_SETTING_KEY,
    FOLDER_DEFAULT_BENCHMARK,
    ROLE_FOLDER,
    get_role,
    role_is_publishable,
)


def get_folder_benchmark(cursor, organization_id: int) -> float:
    benches = get_rinse_folding_benchmarks(cursor, int(organization_id))
    try:
        return float(benches.get("lbs_per_hour_target") or FOLDER_DEFAULT_BENCHMARK)
    except (TypeError, ValueError):
        return float(FOLDER_DEFAULT_BENCHMARK)


def put_folder_benchmark(cursor, organization_id: int, lbs_per_hour: float) -> dict[str, Any]:
    """Write existing rinse_folding_lbs_per_hour_target — does not invalidate approvals."""
    out = put_rinse_folding_benchmarks(
        cursor, int(organization_id), lbs_per_hour=float(lbs_per_hour)
    )
    try:
        from backend.rinse_dashboard_performance import clear_benchmark_cache

        clear_benchmark_cache(int(organization_id))
    except Exception:
        pass
    return {
        "benchmark_setting_key": FOLDER_BENCHMARK_SETTING_KEY,
        "lbs_per_hour_target": float(out.get("lbs_per_hour_target") or FOLDER_DEFAULT_BENCHMARK),
    }


def session_card_to_snapshot(session: Mapping[str, Any], *, business_date_et: date) -> dict[str, Any]:
    role = get_role(ROLE_FOLDER)
    assert role is not None
    hours = float(session.get("performance_hours") or 0)
    lbs = float(session.get("total_pre_lbs") or 0)
    rate = session.get("lbs_per_hour")
    if rate is None and hours > 0:
        rate = round(lbs / hours, 4)
    uid = session.get("user_id") or session.get("employee_user_id")
    try:
        uid_i = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_i = None
    seg = session.get("segment_id")
    try:
        seg_i = int(seg) if seg is not None else None
    except (TypeError, ValueError):
        seg_i = None
    snap = {
        "business_date_et": business_date_et,
        "selected_date_et": business_date_et,
        "role_key": ROLE_FOLDER,
        "session_id": str(session.get("session_id") or "").strip(),
        "segment_id": seg_i,
        "employee_user_id": uid_i,
        "employee_name": str(session.get("employee") or "").strip(),
        "metric_key": role["metric_key"],
        "metric_unit": role["unit"],
        "published_numerator": round(lbs, 4),
        "published_denominator": round(hours, 4),
        "published_metric_value": float(rate) if rate is not None else None,
        "calculated_numerator": round(lbs, 4),
        "calculated_denominator": round(hours, 4),
        "calculated_metric_value": float(rate) if rate is not None else None,
        "is_rate_override": False,
        "published_quantity": round(lbs, 4),
        "published_duration_hours": round(hours, 4),
        "published_session_start_et": session.get("start_time"),
        "published_session_end_et": session.get("end_time") or session.get("performance_end"),
        "content_fingerprint": folder_session_fingerprint(session),
    }
    return snap


def _find_session(day: Mapping[str, Any], session_id: str) -> dict[str, Any] | None:
    sid = str(session_id).strip()
    for sess in day.get("sessions") or []:
        if str(sess.get("session_id") or "") == sid:
            return dict(sess)
    for emp in day.get("employees") or []:
        for sess in emp.get("sessions") or []:
            if str(sess.get("session_id") or "") == sid:
                out = dict(sess)
                if not out.get("employee"):
                    out["employee"] = emp.get("employee")
                if out.get("user_id") is None and emp.get("user_id") is not None:
                    out["user_id"] = emp.get("user_id")
                return out
    return None


def approve_folder_session(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    session_id: str,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    day: Mapping[str, Any] | None = None,
    session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Approve one Folder session.

    Prefer ``session`` (already-rendered Management card) to avoid a full-day
    Folder rebuild. Fall back to ``day`` or ``build_day_folder_performance``.
    """
    if not role_is_publishable(ROLE_FOLDER):
        raise ValueError("FOLDER is not publishable")
    sid = str(session_id).strip()
    sess = None
    if session is not None and str(session.get("session_id") or "").strip() == sid:
        sess = dict(session)
    elif day is not None:
        sess = _find_session(day, sid)
    else:
        day_payload = build_day_folder_performance(
            cursor,
            int(organization_id),
            selected_date_et=selected_date_et,
            attach_customers=False,
        )
        sess = _find_session(day_payload, sid)
    if not sess:
        return {"ok": False, "status": "failed", "reason": "session_not_found", "session_id": sid}
    ok, reason = session_is_approvable(sess)
    if not ok:
        return {"ok": False, "status": reason, "session_id": sid}
    snap = session_card_to_snapshot(sess, business_date_et=selected_date_et)
    if snap.get("published_metric_value") is None:
        return {"ok": False, "status": "invalid_empty", "session_id": sid}
    result = upsert_approved_snapshot(
        cursor,
        int(organization_id),
        role_key=ROLE_FOLDER,
        snapshot=snap,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    result["status"] = "approved"
    return result


def approve_folder_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Approve all eligible closed FOLDER sessions for one ET day."""
    day = build_day_folder_performance(
        cursor,
        int(organization_id),
        selected_date_et=selected_date_et,
        attach_customers=False,
    )
    sessions = list(day.get("sessions") or [])
    if not sessions:
        # flatten from employees
        seen = set()
        for emp in day.get("employees") or []:
            for sess in emp.get("sessions") or []:
                sid = str(sess.get("session_id") or "")
                if sid and sid not in seen:
                    seen.add(sid)
                    row = dict(sess)
                    if not row.get("employee"):
                        row["employee"] = emp.get("employee")
                    if row.get("user_id") is None:
                        row["user_id"] = emp.get("user_id")
                    sessions.append(row)

    summary = {
        "approved": 0,
        "already_approved": 0,
        "open": 0,
        "invalid_empty": 0,
        "failed": 0,
        "unresolved": 0,
        "results": [],
    }
    for sess in sessions:
        sid = str(sess.get("session_id") or "")
        ok, reason = session_is_approvable(sess)
        if not ok:
            summary[reason] = int(summary.get(reason) or 0) + 1
            summary["results"].append({"session_id": sid, "status": reason, "ok": False})
            continue
        try:
            out = approve_folder_session(
                cursor,
                organization_id,
                selected_date_et=selected_date_et,
                session_id=sid,
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                day=day,
            )
        except Exception as exc:  # noqa: BLE001 — report per-session failure
            summary["failed"] += 1
            summary["results"].append(
                {"session_id": sid, "status": "failed", "ok": False, "error": str(exc)}
            )
            continue
        if out.get("already_approved"):
            summary["already_approved"] += 1
            summary["results"].append({**out, "status": "already_approved"})
        elif out.get("ok"):
            summary["approved"] += 1
            summary["results"].append(out)
        else:
            st = str(out.get("status") or "failed")
            summary[st] = int(summary.get(st) or 0) + 1
            summary["results"].append(out)
    summary["ok"] = True
    summary["selected_date_et"] = selected_date_et.isoformat()
    summary["role_key"] = ROLE_FOLDER
    return summary


def attach_publication_status_to_day(
    cursor,
    organization_id: int,
    day: dict[str, Any],
) -> dict[str, Any]:
    """Annotate sessions + derive employee-day publication status (set-based)."""
    from backend.rinse_performance_approvals import derive_employee_day_publication_status

    sids: list[str] = []
    for sess in day.get("sessions") or []:
        sid = str(sess.get("session_id") or "")
        if sid:
            sids.append(sid)
    for emp in day.get("employees") or []:
        for sess in emp.get("sessions") or []:
            sid = str(sess.get("session_id") or "")
            if sid:
                sids.append(sid)
    status = approval_status_map(
        cursor, organization_id, role_key=ROLE_FOLDER, session_ids=sorted(set(sids))
    )
    for sess in day.get("sessions") or []:
        sid = str(sess.get("session_id") or "")
        pub = status.get(sid) or {"status": "UNAPPROVED"}
        sess["publication_status"] = pub["status"]
        sess["publication"] = pub
    for emp in day.get("employees") or []:
        for sess in emp.get("sessions") or []:
            sid = str(sess.get("session_id") or "")
            pub = status.get(sid) or {"status": "UNAPPROVED"}
            sess["publication_status"] = pub["status"]
            sess["publication"] = pub
        day_pub = derive_employee_day_publication_status(emp.get("sessions") or [])
        emp["day_publication_status"] = day_pub["status"]
        emp["day_publication"] = day_pub
        emp["publication_status"] = day_pub["status"]
    day["folder_benchmark_lbs_hr"] = get_folder_benchmark(cursor, organization_id)
    return day


def _recompute_summary_from_employees(employees: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.management_wf_folder_performance import weighted_aggregate_rates

    total_orders = sum(int(e.get("orders_completed") or 0) for e in employees)
    total_lbs = round(sum(float(e.get("total_pre_lbs") or 0) for e in employees), 2)
    total_hours = round(
        sum(
            float(e.get("performance_hours") or e.get("session_hours") or 0)
            for e in employees
            if (e.get("performance_hours") is not None or e.get("session_hours") is not None)
        ),
        4,
    )
    rates = weighted_aggregate_rates(
        total_orders=total_orders,
        total_pre_lbs=total_lbs,
        total_session_hours=total_hours if total_hours > 0 else None,
    )
    return {
        "orders_completed": total_orders,
        "total_pre_lbs": total_lbs,
        "total_hours": total_hours if total_hours > 0 else None,
        "session_hours": total_hours if total_hours > 0 else None,
        "bags_per_hour": rates["bags_per_hour"],
        "lbs_per_hour": rates["lbs_per_hour"],
        "employee_count": len(employees),
        "average_basis": "weighted_sum_orders_lbs_over_sum_hours",
    }


def partition_employees_by_exclusion(day: dict[str, Any]) -> dict[str, Any]:
    """Split active vs excluded employee-days; recompute active summary."""
    employees = list(day.get("employees") or [])
    active = [
        e
        for e in employees
        if str(e.get("day_publication_status") or e.get("publication_status") or "") != "EXCLUDED"
    ]
    excluded = [
        e
        for e in employees
        if str(e.get("day_publication_status") or e.get("publication_status") or "") == "EXCLUDED"
    ]
    summary = dict(day.get("summary") or {})
    summary.update(_recompute_summary_from_employees(active))
    # Preserve unmapped counts from original summary.
    for key in (
        "needs_attribution_count",
        "outside_folder_session_count",
        "unmapped_count",
        "session_count",
    ):
        if key in (day.get("summary") or {}):
            summary[key] = day["summary"][key]
    day["employees"] = active
    day["excluded_employees"] = excluded
    day["excluded_employee_count"] = len(excluded)
    day["summary"] = summary
    day["summary_active"] = summary
    day["summary_all_including_excluded"] = _recompute_summary_from_employees(employees)
    return day


def approve_folder_employee_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_user_id: int | None = None,
    employee_name: str | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    day: Mapping[str, Any] | None = None,
    sessions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Approve all eligible closed Folder sessions for one employee on one ET day."""
    day_payload = day or build_day_folder_performance(
        cursor,
        int(organization_id),
        selected_date_et=selected_date_et,
        attach_customers=False,
    )
    emp = _find_employee(
        day_payload,
        employee_user_id=employee_user_id,
        employee_name=employee_name,
    )
    if not emp and sessions:
        emp = {
            "employee": employee_name,
            "user_id": employee_user_id,
            "sessions": list(sessions),
        }
    if not emp:
        return {
            "ok": False,
            "error": "employee_not_found",
            "status": "employee_not_found",
        }
    sess_list = list(sessions) if sessions is not None else list(emp.get("sessions") or [])
    summary = {
        "ok": True,
        "approved": 0,
        "already_approved": 0,
        "open": 0,
        "invalid_empty": 0,
        "failed": 0,
        "results": [],
        "employee": emp.get("employee"),
        "user_id": emp.get("user_id"),
        "selected_date_et": selected_date_et.isoformat(),
        "role_key": ROLE_FOLDER,
    }
    # Wrap as a fake day for approve_folder_session reuse.
    fake_day = {"sessions": sess_list, "employees": [emp]}
    for sess in sess_list:
        sid = str(sess.get("session_id") or "")
        ok, reason = session_is_approvable(sess)
        if not ok:
            summary[reason] = int(summary.get(reason) or 0) + 1
            summary["results"].append({"session_id": sid, "status": reason, "ok": False})
            continue
        out = approve_folder_session(
            cursor,
            organization_id,
            selected_date_et=selected_date_et,
            session_id=sid,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            session=sess,
            day=fake_day,
        )
        if out.get("already_approved"):
            summary["already_approved"] += 1
        elif out.get("ok"):
            summary["approved"] += 1
        else:
            st = str(out.get("status") or "failed")
            summary[st] = int(summary.get(st) or 0) + 1
        summary["results"].append(out)
    return summary


def exclude_folder_employee_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_user_id: int | None = None,
    employee_name: str | None = None,
    reason: str | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    sessions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Exclude all countable sessions for an employee-day via existing session exclude."""
    from backend.rinse_performance_approvals import (
        exclude_session_publication,
        session_counts_toward_employee_day,
    )

    sess_list = list(sessions or [])
    if not sess_list:
        day = build_day_folder_performance(
            cursor,
            int(organization_id),
            selected_date_et=selected_date_et,
            attach_customers=False,
        )
        emp = _find_employee(
            day, employee_user_id=employee_user_id, employee_name=employee_name
        )
        if not emp:
            return {"ok": False, "error": "employee_not_found", "status": "employee_not_found"}
        sess_list = list(emp.get("sessions") or [])
        employee_name = emp.get("employee") or employee_name
        employee_user_id = emp.get("user_id") if emp.get("user_id") is not None else employee_user_id

    results = []
    excluded = 0
    for sess in sess_list:
        if not session_counts_toward_employee_day(sess) and str(
            sess.get("role_status") or ""
        ).lower() == "open":
            continue
        sid = str(sess.get("session_id") or "")
        if not sid:
            continue
        snap = session_card_to_snapshot(sess, business_date_et=selected_date_et)
        # Allow exclude even when hours/rate empty by forcing a 0 placeholder snap.
        if snap.get("published_metric_value") is None:
            snap["published_metric_value"] = 0.0
            snap["calculated_metric_value"] = 0.0
            snap["published_numerator"] = float(sess.get("total_pre_lbs") or 0)
            snap["published_denominator"] = float(sess.get("performance_hours") or 0) or 0.0001
            snap["calculated_numerator"] = snap["published_numerator"]
            snap["calculated_denominator"] = snap["published_denominator"]
        out = exclude_session_publication(
            cursor,
            organization_id,
            role_key=ROLE_FOLDER,
            session_id=sid,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            snapshot=snap,
        )
        if out.get("ok"):
            excluded += 1
        results.append(out)
    return {
        "ok": excluded > 0 or not results,
        "excluded": excluded,
        "results": results,
        "employee": employee_name,
        "user_id": employee_user_id,
        "selected_date_et": selected_date_et.isoformat(),
        "day_publication_status": "EXCLUDED" if excluded else "NEEDS_APPROVAL",
        "publication": {"status": "EXCLUDED", "excluded": True},
    }


def include_folder_employee_day(
    cursor,
    organization_id: int,
    *,
    employee_user_id: int | None = None,
    employee_name: str | None = None,
    session_ids: Sequence[str] | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    from backend.rinse_performance_approvals import include_session_publication

    sids = [str(s).strip() for s in (session_ids or []) if str(s).strip()]
    if not sids:
        return {"ok": False, "error": "session_ids required", "status": "session_ids_required"}
    results = []
    included = 0
    for sid in sids:
        out = include_session_publication(
            cursor,
            organization_id,
            role_key=ROLE_FOLDER,
            session_id=sid,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            reason=reason,
        )
        if out.get("ok"):
            included += 1
        results.append(out)
    return {
        "ok": included > 0,
        "included": included,
        "results": results,
        "employee": employee_name,
        "user_id": employee_user_id,
        "publication": {"status": "APPROVED" if included else "NEEDS_APPROVAL"},
    }


def _find_employee(
    day: Mapping[str, Any],
    *,
    employee_user_id: int | None = None,
    employee_name: str | None = None,
) -> dict[str, Any] | None:
    name = str(employee_name or "").strip().casefold()
    uid = None
    try:
        uid = int(employee_user_id) if employee_user_id is not None else None
    except (TypeError, ValueError):
        uid = None
    for emp in day.get("employees") or []:
        if uid is not None and emp.get("user_id") is not None and int(emp["user_id"]) == uid:
            return dict(emp)
        if name and str(emp.get("employee") or "").strip().casefold() == name:
            return dict(emp)
    return None


def reconcile_folder_approvals_for_day(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    day: Mapping[str, Any] | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Invalidate approved snapshots whose fingerprint no longer matches live calc."""
    day_payload = day or build_day_folder_performance(
        cursor,
        int(organization_id),
        selected_date_et=selected_date_et,
        attach_customers=False,
    )
    live_fp: dict[str, str] = {}
    sessions = list(day_payload.get("sessions") or [])
    if not sessions:
        for emp in day_payload.get("employees") or []:
            for sess in emp.get("sessions") or []:
                sessions.append(sess)
    for sess in sessions:
        sid = str(sess.get("session_id") or "")
        if sid:
            live_fp[sid] = folder_session_fingerprint(sess)

    from backend.rinse_performance_approvals import list_active_approvals

    active = list_active_approvals(
        cursor,
        organization_id,
        role_key=ROLE_FOLDER,
        week_start=selected_date_et,
        week_end=selected_date_et,
    )
    stale: list[str] = []
    for row in active:
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        current = live_fp.get(sid)
        if current is None:
            # Session disappeared from day — invalidate
            stale.append(sid)
        elif str(row.get("content_fingerprint") or "") != current:
            stale.append(sid)
    if not stale:
        return {"ok": True, "invalidated": 0, "session_ids": []}
    return invalidate_approvals(
        cursor,
        organization_id,
        role_key=ROLE_FOLDER,
        session_ids=stale,
        business_date_et=selected_date_et,
        reason="fingerprint_mismatch",
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )


def invalidate_folder_approvals_for_date(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    reason: str,
    session_ids: list[str] | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    return invalidate_approvals(
        cursor,
        organization_id,
        role_key=ROLE_FOLDER,
        session_ids=session_ids,
        business_date_et=selected_date_et if not session_ids else None,
        reason=reason,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
