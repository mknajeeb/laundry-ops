"""Management Hub — WF Folder Performance APIs (compartment: Performance)."""

from __future__ import annotations

from datetime import date

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.management_wf_folder_attribution import (
    move_bag_attribution,
    reset_bag_attribution,
)
from backend.management_wf_folder_performance import (
    DEFAULT_LAST_N_SESSIONS,
    build_day_folder_performance,
    build_folder_performance_dashboard,
    find_bag_attribution_context,
    get_session_orders,
    list_move_destinations,
)
from backend.rinse_performance_approvals import (
    exclude_session_publication,
    include_session_publication,
    override_published_rate,
    unapprove_session,
)
from backend.rinse_performance_folder_publisher import (
    approve_folder_day,
    approve_folder_session,
    attach_publication_status_to_day,
    get_folder_benchmark,
    invalidate_folder_approvals_for_date,
    put_folder_benchmark,
)
from backend.rinse_performance_roles import ROLE_FOLDER, role_is_publishable
from backend.rinse_scan_time import json_safe_rinse

HUB_READ_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})
HUB_WRITE_ROLES = frozenset({"ADMIN", "OPS", "MANAGER", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _role_set(me: dict) -> set[str]:
    raw = me.get("roles") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x]
    return {str(r).upper() for r in raw}


def _actor(me: dict) -> tuple[int | None, str | None]:
    actor_id = me.get("id") if isinstance(me, dict) else None
    actor_name = None
    if isinstance(me, dict):
        actor_name = (
            me.get("name")
            or me.get("display_name")
            or me.get("email")
            or me.get("username")
        )
    return actor_id, str(actor_name) if actor_name else None


def _annotate_dashboard(cursor, oid: int, payload: dict, selected: date) -> dict:
    """Attach publication status only — no fingerprint reconcile on GET.

    Reconcile-on-GET previously invalidated every approval after Approve because
    list payloads strip nested orders while approve fingerprints included them.
    Fingerprint no longer depends on orders; reconcile remains on mutation paths.
    """
    day = payload
    attach_publication_status_to_day(cursor, oid, day)
    payload["folder_benchmark_lbs_hr"] = get_folder_benchmark(cursor, oid)
    return payload


def register_management_wf_folder_performance_routes(
    app,
    *,
    require_user,
    user_org_id,
    parse_date_value,
) -> None:
    def _selected_date_et(raw: str | None = None):
        value = (raw if raw is not None else (request.args.get("date_et") or "")).strip()
        if value:
            try:
                selected = parse_date_value(value)
            except (TypeError, ValueError):
                return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        else:
            selected = business_today()
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date_et; use YYYY-MM-DD"}), 400)
        return selected, None

    def _parse_optional_date(raw: str | None):
        value = str(raw or "").strip()
        if not value:
            return None, None
        try:
            selected = parse_date_value(value)
        except (TypeError, ValueError):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        return selected, None

    @app.route("/api/management/performance/wf-folder", methods=["GET"])
    def management_wf_folder_performance():
        """Summary-first Folder Performance dashboard (Performance compartment only)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            compare = (request.args.get("compare") or "today").strip().lower()
            try:
                last_n = int(request.args.get("last_n") or DEFAULT_LAST_N_SESSIONS)
            except (TypeError, ValueError):
                last_n = DEFAULT_LAST_N_SESSIONS
            custom_start, err_cs = _parse_optional_date(request.args.get("start_et"))
            if err_cs:
                return err_cs
            custom_end, err_ce = _parse_optional_date(request.args.get("end_et"))
            if err_ce:
                return err_ce
            # Baseline delta is optional — default on for Today UX, skippable for speed.
            include_baseline = str(
                request.args.get("include_baseline")
                or request.args.get("include_baseline_delta")
                or "1"
            ).strip().lower() not in {"0", "false", "no"}
            payload = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare=compare,
                last_n=last_n,
                custom_start=custom_start,
                custom_end=custom_end,
                include_baseline_delta=include_baseline,
            )
            payload = _annotate_dashboard(cursor, oid, payload, selected)
            try:
                conn.commit()
            except Exception:
                pass
            return jsonify(json_safe_rinse(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/sessions/<session_id>/approve",
        methods=["POST"],
    )
    def management_performance_approve_session(role_key: str, session_id: str):
        """Role-generic approve route — Phase 1 FOLDER only."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if not role_is_publishable(rk) or rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            actor_id, actor_name = _actor(me)
            # Fast path: already-rendered session card → skip full-day rebuild.
            session_card = body.get("session") if isinstance(body.get("session"), dict) else None
            if session_card is not None:
                session_card = dict(session_card)
                session_card["session_id"] = str(session_id).strip()
            out = approve_folder_session(
                cursor,
                oid,
                selected_date_et=selected,
                session_id=session_id,
                actor_user_id=actor_id,
                actor_name=actor_name,
                session=session_card,
            )
            conn.commit()
            status = 200 if out.get("ok") else 400
            return jsonify(json_safe_rinse(out)), status
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/days/<date_et>/approve",
        methods=["POST"],
    )
    def management_performance_approve_day(role_key: str, date_et: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if not role_is_publishable(rk) or rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            selected, err = _selected_date_et(date_et)
            if err:
                return err
            actor_id, actor_name = _actor(me)
            out = approve_folder_day(
                cursor,
                oid,
                selected_date_et=selected,
                actor_user_id=actor_id,
                actor_name=actor_name,
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/sessions/<session_id>/unapprove",
        methods=["POST"],
    )
    def management_performance_unapprove_session(role_key: str, session_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            actor_id, actor_name = _actor(me)
            out = unapprove_session(
                cursor,
                oid,
                role_key=rk,
                session_id=session_id,
                actor_user_id=actor_id,
                actor_name=actor_name,
                reason="manual_unapprove",
            )
            conn.commit()
            return jsonify(json_safe_rinse(out))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/sessions/<session_id>/override",
        methods=["POST"],
    )
    def management_performance_override_session(role_key: str, session_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if not role_is_publishable(rk) or rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            try:
                rate = float(body.get("published_metric_value"))
            except (TypeError, ValueError):
                return jsonify({"error": "published_metric_value required"}), 400
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            actor_id, actor_name = _actor(me)
            snap = None
            session_card = body.get("session") if isinstance(body.get("session"), dict) else None
            if body.get("approve_if_needed"):
                from backend.rinse_performance_folder_publisher import (
                    _find_session,
                    session_card_to_snapshot,
                )

                if session_card is not None:
                    sess = dict(session_card)
                    sess["session_id"] = str(session_id).strip()
                    snap = session_card_to_snapshot(sess, business_date_et=selected)
                else:
                    day = build_day_folder_performance(
                        cursor, oid, selected_date_et=selected, attach_customers=False
                    )
                    sess = _find_session(day, session_id)
                    if sess:
                        snap = session_card_to_snapshot(sess, business_date_et=selected)
            out = override_published_rate(
                cursor,
                oid,
                role_key=rk,
                session_id=session_id,
                published_metric_value=rate,
                reason=(body.get("reason") or body.get("note") or None),
                actor_user_id=actor_id,
                actor_name=actor_name,
                approve_if_needed=bool(body.get("approve_if_needed")),
                snapshot=snap,
            )
            conn.commit()
            status = 200 if out.get("ok") else 400
            return jsonify(json_safe_rinse(out)), status
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/sessions/<session_id>/exclude",
        methods=["POST"],
    )
    def management_performance_exclude_session(role_key: str, session_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            actor_id, actor_name = _actor(me)
            out = exclude_session_publication(
                cursor,
                oid,
                role_key=rk,
                session_id=session_id,
                reason=(body.get("reason") or body.get("note") or None),
                actor_user_id=actor_id,
                actor_name=actor_name,
            )
            conn.commit()
            status = 200 if out.get("ok") else 400
            return jsonify(json_safe_rinse(out)), status
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/<role_key>/sessions/<session_id>/include",
        methods=["POST"],
    )
    def management_performance_include_session(role_key: str, session_id: str):
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            rk = str(role_key or "").strip().upper()
            if rk != ROLE_FOLDER:
                return jsonify({"error": f"role_key {rk!r} is not publishable"}), 400
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            actor_id, actor_name = _actor(me)
            out = include_session_publication(
                cursor,
                oid,
                role_key=rk,
                session_id=session_id,
                actor_user_id=actor_id,
                actor_name=actor_name,
                reason=(body.get("reason") or None),
            )
            conn.commit()
            status = 200 if out.get("ok") else 400
            return jsonify(json_safe_rinse(out)), status
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/FOLDER/benchmark", methods=["GET", "PUT"])
    def management_folder_benchmark():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            oid = int(user_org_id(me))
            if request.method == "GET":
                if not (_role_set(me) & HUB_READ_ROLES):
                    return jsonify({"error": "Forbidden"}), 403
                return jsonify(
                    {
                        "role_key": ROLE_FOLDER,
                        "lbs_per_hour_target": get_folder_benchmark(cursor, oid),
                        "benchmark_setting_key": "rinse_folding_lbs_per_hour_target",
                    }
                )
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            body = request.get_json(silent=True) or {}
            raw = body.get("lbs_per_hour_target", body.get("benchmark"))
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return jsonify({"error": "lbs_per_hour_target required"}), 400
            if value <= 0 or value > 500:
                return jsonify({"error": "lbs_per_hour_target out of range"}), 400
            out = put_folder_benchmark(cursor, oid, value)
            conn.commit()
            return jsonify(json_safe_rinse({"ok": True, "role_key": ROLE_FOLDER, **out}))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route(
        "/api/management/performance/wf-folder/sessions/<session_id>/orders",
        methods=["GET"],
    )
    def management_wf_folder_session_orders(session_id: str):
        """Lazy session order drill-down — no full scan chronology."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            payload = get_session_orders(
                cursor,
                oid,
                selected_date_et=selected,
                session_id=session_id,
            )
            if payload.get("error") == "session_not_found":
                return jsonify(json_safe_rinse(payload)), 404
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/unmapped", methods=["GET"])
    def management_wf_folder_unmapped():
        """Folder Performance exception queues (Needs Attribution + Outside Session)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            day = build_day_folder_performance(
                cursor,
                oid,
                selected_date_et=selected,
                attach_customers=True,
            )
            return jsonify(
                json_safe_rinse(
                    {
                        "selected_date_et": selected.isoformat(),
                        "needs_attribution_count": day.get("needs_attribution_count")
                        or 0,
                        "needs_attribution_orders": day.get("needs_attribution_orders")
                        or [],
                        "outside_folder_session_count": day.get(
                            "outside_folder_session_count"
                        )
                        or 0,
                        "outside_folder_session_orders": day.get(
                            "outside_folder_session_orders"
                        )
                        or [],
                        "unmapped_count": day.get("unmapped_count") or 0,
                        "orders": day.get("unmapped_orders") or [],
                    }
                )
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/destinations", methods=["GET"])
    def management_wf_folder_destinations():
        """Move picker: mapped users with activity on the selected ET day only."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_READ_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            selected, err = _selected_date_et()
            if err:
                return err
            payload = list_move_destinations(
                cursor, oid, selected_date_et=selected
            )
            return jsonify(json_safe_rinse(payload))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/attribution/move", methods=["POST"])
    def management_wf_folder_attribution_move():
        """Move one or many orders to a destination employee/session (auditable)."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            bag_ids_raw = body.get("bag_ids") or body.get("bag_id")
            if isinstance(bag_ids_raw, str):
                bag_ids = [bag_ids_raw]
            elif isinstance(bag_ids_raw, list):
                bag_ids = [str(b) for b in bag_ids_raw if b]
            else:
                bag_ids = []
            bag_ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
            if not bag_ids:
                return jsonify({"error": "bag_ids required"}), 400
            to_employee = (body.get("to_employee") or body.get("employee") or "").strip()
            if not to_employee:
                return jsonify({"error": "to_employee required"}), 400
            to_session_id = body.get("to_session_id") or body.get("session_id")
            to_segment_id = body.get("to_segment_id") or body.get("segment_id")
            try:
                seg_id = (
                    int(to_segment_id)
                    if to_segment_id is not None and to_segment_id != ""
                    else None
                )
            except (TypeError, ValueError):
                seg_id = None
            note = body.get("note")
            actor_name = None
            if isinstance(me, dict):
                actor_name = (
                    me.get("name")
                    or me.get("display_name")
                    or me.get("email")
                    or me.get("username")
                )
            actor_id = me.get("id") if isinstance(me, dict) else None

            day = build_day_folder_performance(
                cursor, oid, selected_date_et=selected, attach_customers=False
            )
            results = []
            for bid in bag_ids:
                ctx = find_bag_attribution_context(day, bid)
                if not ctx:
                    results.append({"bag_id": bid, "ok": False, "error": "bag_not_found"})
                    continue
                original = (
                    ctx.get("original_scanner")
                    or ctx.get("original_employee_name")
                    or ctx.get("credited_employee")
                    or ctx.get("employee")
                    or "Unknown"
                )
                row = move_bag_attribution(
                    cursor,
                    oid,
                    bag_id=bid,
                    selected_date_et=selected,
                    original_employee_name=str(original),
                    original_scanner_name=str(
                        ctx.get("original_scanner") or original
                    ),
                    original_completion_et=ctx.get("completion_time")
                    or ctx.get("completion_timestamp")
                    or ctx.get("completion_time_et"),
                    from_employee_name=ctx.get("effective_employee")
                    or ctx.get("credited_employee")
                    or ctx.get("employee"),
                    from_session_id=ctx.get("session_id"),
                    to_employee_name=to_employee,
                    to_session_id=to_session_id,
                    to_segment_id=seg_id,
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                    note=note,
                )
                results.append({"ok": True, **row})
            conn.commit()

            # Recalculate immediately after reassignment
            refreshed = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare="today",
                include_baseline_delta=False,
            )
            # Attribution changes Folder credit → invalidate published snapshots for the day
            try:
                invalidate_folder_approvals_for_date(
                    cursor,
                    oid,
                    selected_date_et=selected,
                    reason="attribution_move",
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                )
                conn.commit()
            except Exception:
                pass
            refreshed = _annotate_dashboard(cursor, oid, refreshed, selected)
            try:
                conn.commit()
            except Exception:
                pass
            return jsonify(
                json_safe_rinse(
                    {
                        "ok": True,
                        "moved": sum(1 for r in results if r.get("ok")),
                        "results": results,
                        "dashboard": refreshed,
                    }
                )
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/management/performance/wf-folder/attribution/reset", methods=["POST"])
    def management_wf_folder_attribution_reset():
        """Reset override(s) back to original scanner attribution."""
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            if not (_role_set(me) & HUB_WRITE_ROLES):
                return jsonify({"error": "Forbidden"}), 403
            oid = int(user_org_id(me))
            body = request.get_json(silent=True) or {}
            selected, err = _selected_date_et(
                body.get("date_et") or body.get("selected_date_et")
            )
            if err:
                return err
            bag_ids_raw = body.get("bag_ids") or body.get("bag_id")
            if isinstance(bag_ids_raw, str):
                bag_ids = [bag_ids_raw]
            elif isinstance(bag_ids_raw, list):
                bag_ids = [str(b) for b in bag_ids_raw if b]
            else:
                bag_ids = []
            bag_ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
            if not bag_ids:
                return jsonify({"error": "bag_ids required"}), 400
            actor_id, actor_name = _actor(me)
            results = []
            for bid in bag_ids:
                row = reset_bag_attribution(
                    cursor,
                    oid,
                    bag_id=bid,
                    selected_date_et=selected,
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                    note=body.get("note"),
                )
                results.append({"ok": True, **row})
            conn.commit()
            refreshed = build_folder_performance_dashboard(
                cursor,
                oid,
                date_et=selected,
                compare="today",
                include_baseline_delta=False,
            )
            try:
                invalidate_folder_approvals_for_date(
                    cursor,
                    oid,
                    selected_date_et=selected,
                    reason="attribution_reset",
                    actor_user_id=actor_id,
                    actor_name=str(actor_name) if actor_name else None,
                )
                conn.commit()
            except Exception:
                pass
            refreshed = _annotate_dashboard(cursor, oid, refreshed, selected)
            try:
                conn.commit()
            except Exception:
                pass
            return jsonify(
                json_safe_rinse(
                    {
                        "ok": True,
                        "reset": sum(1 for r in results if r.get("reset")),
                        "results": results,
                        "dashboard": refreshed,
                    }
                )
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            cursor.close()
            conn.close()
