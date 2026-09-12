"""FOLDER role publisher — translates Management WF Folder session cards to snapshots.

Does not recalculate Folder performance; reads canonical Management cards.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

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
    """Annotate Management day payload with publication status per session."""
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
    day["folder_benchmark_lbs_hr"] = get_folder_benchmark(cursor, organization_id)
    return day


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
