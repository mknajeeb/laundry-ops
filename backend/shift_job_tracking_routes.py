"""API routes for shift job tracking."""

from __future__ import annotations

from datetime import datetime

from flask import g, jsonify, request

from backend.db import get_db
from backend.shift_job_tracking import (
    admin_allow_continuation,
    admin_override_force_checkout_time,
    admin_waive_session_force_checkout,
    create_job_name,
    delete_job_name,
    enrich_session_job_tracking,
    get_job_name,
    get_open_job_segment,
    job_tracking_report,
    list_job_names,
    reorder_job_names,
    seed_default_job_names,
    set_user_force_checkout_waiver,
    switch_job_role,
    update_job_name,
    user_force_checkout_waiver,
)
from backend.ta_routes import (
    _parse_mysql_dt,
    _tenant_id,
    require_any_perm,
    require_auth,
    require_perm,
    ta_bp,
    write_audit,
)


def _parse_force_checkout_dt(raw: str) -> datetime:
    val = _parse_mysql_dt(raw)
    if not val:
        raise ValueError("Invalid force check-out time")
    return val


@ta_bp.route("/job-tracking/job-names", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_list_names():
    conn = get_db()
    try:
        include_inactive = request.args.get("include_inactive") == "1"
        include_usage = request.args.get("include_usage") == "1"
        oid = _tenant_id()
        c = conn.cursor()
        seed_default_job_names(c, oid)
        conn.commit()
        rows = list_job_names(
            c, oid, include_inactive=include_inactive, include_usage=include_usage
        )
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/job-names", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_create_name():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    active = data.get("active", True)
    conn = get_db()
    try:
        c = conn.cursor()
        row = create_job_name(c, _tenant_id(), name, active=bool(active))
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_job_name",
            row.get("id"),
            "create",
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/job-names/<int:job_id>", methods=["PATCH"])
@require_auth
@require_perm("ta.settings")
def job_tracking_update_name(job_id: int):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor()
        old = list_job_names(c, _tenant_id(), include_inactive=True)
        old_row = next((x for x in old if int(x["id"]) == job_id), None)
        row = update_job_name(
            c,
            _tenant_id(),
            job_id,
            name=data.get("name"),
            active=data.get("active") if "active" in data else None,
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_job_name",
            job_id,
            "update",
            old=old_row,
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/job-names/<int:job_id>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def job_tracking_delete_name(job_id: int):
    conn = get_db()
    try:
        c = conn.cursor()
        old = get_job_name(c, _tenant_id(), job_id)
        if not old:
            return jsonify({"error": "Not found"}), 404
        delete_job_name(c, _tenant_id(), job_id)
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task",
            job_id,
            "delete",
            old=old,
            remarks=(request.json or {}).get("reason") or (request.json or {}).get("remarks"),
        )
        conn.commit()
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/job-names/reorder", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_reorder_names():
    data = request.json or {}
    ordered = data.get("ordered_ids") or []
    if not isinstance(ordered, list) or not ordered:
        return jsonify({"error": "ordered_ids required"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        rows = reorder_job_names(c, _tenant_id(), [int(x) for x in ordered])
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_job_name",
            0,
            "reorder",
            new={"ordered_ids": ordered},
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/sessions/current/switch-job", methods=["POST"])
@ta_bp.route("/job-tracking/sessions/current/switch-task", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def job_tracking_switch_job():
    data = request.json or {}
    job_name_id = data.get("job_name_id") or data.get("task_id")
    if not job_name_id:
        return jsonify({"error": "task_id required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active'
            ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active shift"}), 400
        old_seg = get_open_job_segment(conn, int(sess["id"]))
        seg = switch_job_role(conn, int(sess["id"]), _tenant_id(), int(job_name_id))
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_task_segment",
            seg.get("id"),
            "task_changed",
            old={
                "task_id": old_seg.get("job_name_id") if old_seg else None,
                "task_name": old_seg.get("job_name") if old_seg else None,
            },
            new={
                "task_id": job_name_id,
                "task_name": seg.get("job_name"),
                "shift_session_id": sess["id"],
            },
        )
        conn.commit()
        tracking = enrich_session_job_tracking(conn, sess, g.ta_user["id"])
        return jsonify({"segment": seg, "task_tracking": tracking, "job_tracking": tracking})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/sessions/current", methods=["GET"])
@require_auth
@require_perm("ta.clock")
def job_tracking_current_session():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active'
            ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"session": None, "job_tracking": None})
        tracking = enrich_session_job_tracking(conn, sess, g.ta_user["id"])
        return jsonify({"session": sess, "task_tracking": tracking, "job_tracking": tracking})
    finally:
        conn.close()


@ta_bp.route("/job-tracking/sessions/<int:sid>/continue", methods=["POST"])
@require_auth
@require_perm("ta.override")
def job_tracking_continue_session(sid: int):
    data = request.json or {}
    remarks = (data.get("remarks") or data.get("reason") or "").strip()
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM shift_sessions WHERE id=%s AND organization_id=%s",
            (sid, _tenant_id()),
        )
        old = c.fetchone()
        if not old:
            return jsonify({"error": "Not found"}), 404
        result = admin_allow_continuation(conn, sid)
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "allow_continuation_after_force_checkout",
            old={"status": old.get("status"), "force_checked_out_at": str(old.get("force_checked_out_at"))},
            new=result.get("session"),
            remarks=remarks or None,
        )
        conn.commit()
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/sessions/<int:sid>/waive-force-checkout", methods=["POST"])
@require_auth
@require_perm("ta.override")
def job_tracking_waive_session(sid: int):
    data = request.json or {}
    waived = bool(data.get("waived", True))
    remarks = (data.get("remarks") or data.get("reason") or "").strip()
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM shift_sessions WHERE id=%s AND organization_id=%s",
            (sid, _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Not found"}), 404
        result = admin_waive_session_force_checkout(conn, sid, waived)
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "waive_force_checkout",
            old=result.get("old"),
            new=result.get("new"),
            remarks=remarks or None,
        )
        conn.commit()
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/sessions/<int:sid>/override-force-checkout-time", methods=["POST"])
@require_auth
@require_perm("ta.override")
def job_tracking_override_force_time(sid: int):
    data = request.json or {}
    raw = data.get("force_checkout_at")
    remarks = (data.get("remarks") or data.get("reason") or "").strip()
    if not raw:
        return jsonify({"error": "force_checkout_at required"}), 400
    conn = get_db()
    try:
        force_at = _parse_force_checkout_dt(raw)
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM shift_sessions WHERE id=%s AND organization_id=%s",
            (sid, _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Not found"}), 404
        result = admin_override_force_checkout_time(conn, sid, force_at)
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "override_force_checkout_time",
            old=result.get("old"),
            new=result.get("new"),
            remarks=remarks or None,
        )
        conn.commit()
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/users/<int:uid>/force-checkout-waiver", methods=["POST"])
@require_auth
@require_perm("ta.override")
def job_tracking_user_waiver(uid: int):
    data = request.json or {}
    waived = bool(data.get("waived", True))
    remarks = (data.get("remarks") or data.get("reason") or "").strip()
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT force_checkout_waiver FROM payroll_profiles WHERE user_id=%s LIMIT 1",
            (uid,),
        )
        old_row = c.fetchone()
        old = bool(int(old_row.get("force_checkout_waiver") or 0)) if old_row else False
        set_user_force_checkout_waiver(conn, uid, waived)
        write_audit(
            conn,
            g.ta_user["id"],
            "payroll_profile",
            uid,
            "force_checkout_waiver",
            old={"force_checkout_waiver": old},
            new={"force_checkout_waiver": waived},
            remarks=remarks or None,
        )
        conn.commit()
        return jsonify({"user_id": uid, "force_checkout_waiver": waived})
    finally:
        conn.close()


@ta_bp.route("/job-tracking/users/<int:uid>/force-checkout-waiver", methods=["GET"])
@require_auth
@require_any_perm("ta.monitor", "ta.override", "ta.settings")
def job_tracking_user_waiver_get(uid: int):
    conn = get_db()
    try:
        waived = user_force_checkout_waiver(conn, uid)
        return jsonify({"user_id": uid, "force_checkout_waiver": waived})
    finally:
        conn.close()


@ta_bp.route("/job-tracking/reports", methods=["GET"])
@require_auth
@require_perm("ta.monitor")
def job_tracking_reports():
    conn = get_db()
    try:
        rows = job_tracking_report(
            conn,
            _tenant_id(),
            from_date=request.args.get("from_date"),
            to_date=request.args.get("to_date"),
            user_id=int(request.args["user_id"]) if request.args.get("user_id") else None,
            shift_session_id=int(request.args["shift_session_id"])
            if request.args.get("shift_session_id")
            else None,
            job_name_id=int(request.args["job_name_id"]) if request.args.get("job_name_id") else None,
            task_id=int(request.args["task_id"]) if request.args.get("task_id") else None,
        )
        return jsonify(rows)
    finally:
        conn.close()
