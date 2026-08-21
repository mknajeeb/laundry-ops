"""API routes for shift Category + Role task tracking."""

from __future__ import annotations

from flask import g, jsonify, request

from backend.db import get_db
from backend.shift_job_tracking import (
    assign_role_to_category,
    create_category,
    create_role,
    delete_category,
    delete_role,
    enrich_session_job_tracking,
    get_assignment,
    get_category,
    get_open_job_segment,
    get_role,
    job_tracking_report,
    list_active_selection_tree,
    list_categories,
    list_category_roles,
    list_roles,
    remove_category_role_assignment,
    reorder_categories,
    reorder_category_roles,
    reorder_roles,
    seed_default_categories_and_roles,
    update_category,
    update_category_role_assignment,
    update_role,
)
from backend.ta_routes import (
    _tenant_id,
    require_any_perm,
    require_auth,
    require_perm,
    ta_bp,
    write_audit,
)


def _ensure_seeded(conn):
    c = conn.cursor()
    seed_default_categories_and_roles(c, _tenant_id())
    conn.commit()


# --- Feature flag ---


@ta_bp.route("/job-tracking/feature-flag", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_feature_flag_get():
    from backend.category_role_tracking_settings import get_category_role_tracking_settings

    conn = get_db()
    try:
        return jsonify(get_category_role_tracking_settings(conn, _tenant_id()))
    finally:
        conn.close()


@ta_bp.route("/job-tracking/feature-flag", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def job_tracking_feature_flag_put():
    from backend.category_role_tracking_settings import set_category_role_tracking_enabled

    data = request.json or {}
    if "category_role_tracking_enabled" in data:
        enabled = bool(data.get("category_role_tracking_enabled"))
    elif "enabled" in data:
        enabled = bool(data.get("enabled"))
    else:
        return jsonify({"error": "category_role_tracking_enabled required"}), 400
    reason = (data.get("reason") or data.get("remarks") or data.get("note") or "").strip() or None
    conn = get_db()
    try:
        result = set_category_role_tracking_enabled(
            conn,
            _tenant_id(),
            enabled,
            actor_user_id=g.ta_user["id"],
            reason=reason,
        )
        conn.commit()
        return jsonify(result)
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


# --- Selection tree (employee-facing) ---


@ta_bp.route("/job-tracking/selection-tree", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings", "ta.override", "users.edit")
def job_tracking_selection_tree():
    conn = get_db()
    try:
        _ensure_seeded(conn)
        c = conn.cursor(dictionary=True)
        tree = list_active_selection_tree(c, _tenant_id())
        return jsonify(tree)
    finally:
        conn.close()


# --- Categories ---


@ta_bp.route("/job-tracking/categories", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_list_categories():
    conn = get_db()
    try:
        _ensure_seeded(conn)
        c = conn.cursor(dictionary=True)
        rows = list_categories(
            c,
            _tenant_id(),
            include_inactive=request.args.get("include_inactive") == "1",
            include_usage=request.args.get("include_usage") == "1",
        )
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_create_category():
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        row = create_category(
            c,
            _tenant_id(),
            data.get("name") or "",
            code=data.get("code"),
            active=bool(data.get("active", True)),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category",
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


@ta_bp.route("/job-tracking/categories/<int:cid>", methods=["PATCH"])
@require_auth
@require_perm("ta.settings")
def job_tracking_update_category(cid: int):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_category(c, _tenant_id(), cid)
        row = update_category(
            c,
            _tenant_id(),
            cid,
            name=data.get("name"),
            active=data.get("active") if "active" in data else None,
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category",
            cid,
            "update",
            old=old,
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories/<int:cid>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def job_tracking_delete_category(cid: int):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_category(c, _tenant_id(), cid)
        delete_category(c, _tenant_id(), cid)
        write_audit(conn, g.ta_user["id"], "ta_task_category", cid, "delete", old=old)
        conn.commit()
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories/reorder", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_reorder_categories():
    data = request.json or {}
    ordered = data.get("ordered_ids") or []
    if not isinstance(ordered, list) or not ordered:
        return jsonify({"error": "ordered_ids required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        rows = reorder_categories(c, _tenant_id(), [int(x) for x in ordered])
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category",
            0,
            "reorder",
            new={"ordered_ids": ordered},
        )
        conn.commit()
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories/<int:cid>/roles", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_list_category_roles(cid: int):
    conn = get_db()
    try:
        _ensure_seeded(conn)
        c = conn.cursor(dictionary=True)
        rows = list_category_roles(
            c,
            _tenant_id(),
            cid,
            include_inactive=request.args.get("include_inactive") == "1",
        )
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories/<int:cid>/roles", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_assign_role(cid: int):
    data = request.json or {}
    role_id = data.get("role_id")
    if not role_id:
        return jsonify({"error": "role_id required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        row = assign_role_to_category(
            c,
            _tenant_id(),
            cid,
            int(role_id),
            active=bool(data.get("active", True)),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category_role",
            row.get("id"),
            "assign",
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/categories/<int:cid>/roles/reorder", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_reorder_category_roles(cid: int):
    data = request.json or {}
    ordered = data.get("ordered_ids") or []
    if not isinstance(ordered, list) or not ordered:
        return jsonify({"error": "ordered_ids required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        rows = reorder_category_roles(c, _tenant_id(), cid, [int(x) for x in ordered])
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category_role",
            cid,
            "reorder",
            new={"ordered_ids": ordered},
        )
        conn.commit()
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/category-roles/<int:aid>", methods=["PATCH"])
@require_auth
@require_perm("ta.settings")
def job_tracking_update_assignment(aid: int):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_assignment(c, _tenant_id(), aid)
        row = update_category_role_assignment(
            c,
            _tenant_id(),
            aid,
            active=data.get("active") if "active" in data else None,
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_category_role",
            aid,
            "update",
            old=old,
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/category-roles/<int:aid>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def job_tracking_delete_assignment(aid: int):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_assignment(c, _tenant_id(), aid)
        remove_category_role_assignment(c, _tenant_id(), aid)
        write_audit(conn, g.ta_user["id"], "ta_task_category_role", aid, "delete", old=old)
        conn.commit()
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


# --- Roles ---


@ta_bp.route("/job-tracking/roles", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_list_roles():
    conn = get_db()
    try:
        _ensure_seeded(conn)
        c = conn.cursor(dictionary=True)
        rows = list_roles(
            c,
            _tenant_id(),
            include_inactive=request.args.get("include_inactive") == "1",
            include_usage=request.args.get("include_usage") == "1",
        )
        return jsonify(rows)
    finally:
        conn.close()


@ta_bp.route("/job-tracking/roles", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_create_role():
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        row = create_role(
            c,
            _tenant_id(),
            data.get("name") or "",
            code=data.get("code"),
            active=bool(data.get("active", True)),
        )
        # Optional: assign to categories on create
        category_ids = data.get("category_ids") or []
        if isinstance(category_ids, list) and category_ids and row.get("id"):
            for cid in category_ids:
                assign_role_to_category(c, _tenant_id(), int(cid), int(row["id"]))
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_role",
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


@ta_bp.route("/job-tracking/roles/<int:rid>", methods=["PATCH"])
@require_auth
@require_perm("ta.settings")
def job_tracking_update_role(rid: int):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_role(c, _tenant_id(), rid)
        row = update_role(
            c,
            _tenant_id(),
            rid,
            name=data.get("name"),
            active=data.get("active") if "active" in data else None,
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_role",
            rid,
            "update",
            old=old,
            new=row,
            remarks=data.get("reason") or data.get("remarks"),
        )
        conn.commit()
        return jsonify(row)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/roles/<int:rid>", methods=["DELETE"])
@require_auth
@require_perm("ta.settings")
def job_tracking_delete_role(rid: int):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        old = get_role(c, _tenant_id(), rid)
        delete_role(c, _tenant_id(), rid)
        write_audit(conn, g.ta_user["id"], "ta_task_role", rid, "delete", old=old)
        conn.commit()
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/job-tracking/roles/reorder", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def job_tracking_reorder_roles():
    data = request.json or {}
    ordered = data.get("ordered_ids") or []
    if not isinstance(ordered, list) or not ordered:
        return jsonify({"error": "ordered_ids required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        rows = reorder_roles(c, _tenant_id(), [int(x) for x in ordered])
        write_audit(
            conn,
            g.ta_user["id"],
            "ta_task_role",
            0,
            "reorder",
            new={"ordered_ids": ordered},
        )
        conn.commit()
        return jsonify(rows)
    finally:
        conn.close()


# --- Switch / current ---


@ta_bp.route("/job-tracking/sessions/current/switch-job", methods=["POST"])
@ta_bp.route("/job-tracking/sessions/current/switch-task", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def job_tracking_switch_job():
    data = request.json or {}
    category_id = data.get("category_id")
    role_id = data.get("role_id")
    if not category_id or not role_id:
        return jsonify({"error": "category_id and role_id required"}), 400
    idempotency_key = (
        (data.get("idempotency_key") or "").strip()
        or (request.headers.get("Idempotency-Key") or "").strip()
    )
    if not idempotency_key:
        return jsonify(
            {
                "error": "idempotency_key required "
                "(body.idempotency_key or Idempotency-Key header)"
            }
        ), 400
    if len(idempotency_key) > 64:
        return jsonify({"error": "idempotency_key must be at most 64 characters"}), 400
    conn = get_db()
    try:
        from backend.category_role_tracking_settings import is_category_role_tracking_enabled
        from backend.shift_job_tracking import (
            IdempotencyConflictError,
            start_category_role_segment,
        )

        if not is_category_role_tracking_enabled(conn, _tenant_id()):
            return jsonify(
                {"error": "Category & Role Tracking is disabled for this organization"}
            ), 403
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
        change_source = "switch" if old_seg else "assignment_selected_after_enable"
        seg = start_category_role_segment(
            conn,
            int(sess["id"]),
            _tenant_id(),
            int(g.ta_user["id"]),
            int(category_id),
            int(role_id),
            change_source=change_source,
            idempotency_key=idempotency_key,
        )
        # Build response payload before commit so the HTTP response does not wait
        # on post-commit reads. Commit is the last DB step before return.
        tracking = enrich_session_job_tracking(conn, sess, g.ta_user["id"])
        if not seg.get("replayed") and not seg.get("noop"):
            write_audit(
                conn,
                g.ta_user["id"],
                "shift_task_segment",
                seg.get("id"),
                change_source
                if change_source == "assignment_selected_after_enable"
                else "task_changed",
                old={
                    "category_id": old_seg.get("category_id") if old_seg else None,
                    "role_id": old_seg.get("role_id") if old_seg else None,
                    "display_label": old_seg.get("display_label") if old_seg else None,
                },
                new={
                    "category_id": category_id,
                    "role_id": role_id,
                    "display_label": seg.get("display_label"),
                    "shift_session_id": sess["id"],
                    "change_source": change_source,
                    "idempotency_key": idempotency_key,
                },
            )
        conn.commit()
        return jsonify(
            {
                "segment": seg,
                "task_tracking": tracking,
                "job_tracking": tracking,
                "replayed": bool(seg.get("replayed")),
                "noop": bool(seg.get("noop")),
                "unchanged": bool(seg.get("unchanged") or seg.get("noop") or seg.get("replayed")),
            }
        )
    except IdempotencyConflictError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e), "code": "idempotency_conflict"}), 409
    except ValueError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 400
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
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
            return jsonify({"session": None, "job_tracking": None, "task_tracking": None})
        tracking = enrich_session_job_tracking(conn, sess, g.ta_user["id"])
        return jsonify({"session": sess, "task_tracking": tracking, "job_tracking": tracking})
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
            category_id=int(request.args["category_id"]) if request.args.get("category_id") else None,
            role_id=int(request.args["role_id"]) if request.args.get("role_id") else None,
            task_id=int(request.args["task_id"]) if request.args.get("task_id") else None,
        )
        return jsonify(rows)
    finally:
        conn.close()


# Keep legacy job-names endpoints as thin wrappers so older UI doesn't hard-crash
@ta_bp.route("/job-tracking/job-names", methods=["GET"])
@require_auth
@require_any_perm("ta.clock", "ta.monitor", "ta.settings")
def job_tracking_list_names_legacy():
    conn = get_db()
    try:
        _ensure_seeded(conn)
        c = conn.cursor(dictionary=True)
        from backend.shift_job_tracking import list_job_names

        return jsonify(list_job_names(c, _tenant_id()))
    finally:
        conn.close()


# --- Employee Mobile PIN Access (Stage A) ---


@ta_bp.route("/users/<int:user_id>/mobile-pin-access", methods=["GET"])
@require_auth
@require_any_perm("users.view", "users.edit", "ta.settings")
def employee_mobile_pin_access_get(user_id: int):
    from backend.employee_mobile_pin_access import manager_mobile_pin_access_payload

    conn = get_db()
    try:
        oid = _tenant_id()
        c = conn.cursor(dictionary=True)
        payload = manager_mobile_pin_access_payload(c, oid, int(user_id))
        conn.commit()
        return jsonify(payload)
    except LookupError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/mobile-pin-access", methods=["PUT"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def employee_mobile_pin_access_put(user_id: int):
    from backend.employee_mobile_pin_access import (
        PEOPLE_MOBILE_PIN_ACCESS_KEYS,
        manager_mobile_pin_access_payload,
        save_employee_mobile_pin_access,
    )

    data = request.json or {}
    conn = get_db()
    try:
        oid = _tenant_id()
        actor = int(g.ta_user["id"])

        def _audit(actor_id, entity_type, entity_id, action, old=None, new=None, organization_id=None):
            write_audit(
                conn,
                actor_id,
                entity_type,
                entity_id,
                action,
                old=old,
                new=new,
                organization_id=organization_id if organization_id is not None else oid,
            )

        grants = {k: data.get(k) for k in PEOPLE_MOBILE_PIN_ACCESS_KEYS}
        c = conn.cursor(dictionary=True)
        save_employee_mobile_pin_access(
            c,
            oid,
            int(user_id),
            grants=grants,
            actor_user_id=actor,
            write_audit_fn=_audit,
        )
        payload = manager_mobile_pin_access_payload(c, oid, int(user_id))
        conn.commit()
        return jsonify(payload)
    except LookupError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
