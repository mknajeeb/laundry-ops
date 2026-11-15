"""HTTP routes for the supervisor portal. Authorization is checked here."""

from __future__ import annotations

from datetime import date, timedelta

from flask import jsonify, request

from backend.business_time import business_today
from backend.db import get_db
from backend.supervisor_portal.adjustments import validate_adjustment
from backend.supervisor_portal.permissions import can, role_set, strip_rinse_summary
from backend.supervisor_portal.quality import incident_totals, normalize_incident, week_start
from backend.supervisor_portal.scoring import draft_policy, refuse_activation
from backend.supervisor_portal.service import assemble_supervisor_day
from backend.supervisor_portal.store import (
    MIGRATION,
    MigrationRequired,
    add_issue_type,
    assignment_items,
    create_assignments,
    get_assignment,
    insert_adjustment,
    insert_scoring_target,
    insert_weight_version,
    install_starter_issue_types,
    list_adjustments,
    list_assignments,
    list_incidents,
    list_issue_types,
    list_primary_roles,
    list_training_templates,
    list_weight_versions,
    published_weight_version,
    read_flags,
    reverse_adjustment,
    save_incident,
    save_training_template,
    scoring_target_for,
    set_primary_role,
    set_progress,
    stamp_approval_sources,
    training_due_count,
    update_assignment_status,
    void_incident,
)
from backend.supervisor_portal.training import checklist_ready, completion_ratio, next_status, normalize_template


def register_supervisor_portal_routes(app, *, require_user, user_org_id, parse_date_value) -> None:
    def _date_arg(name: str = "date"):
        raw = (request.args.get(name) or (request.get_json(silent=True) or {}).get(name) or "").strip()
        if not raw:
            return business_today(), None
        try:
            selected = parse_date_value(raw)
        except (TypeError, ValueError):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        if not isinstance(selected, date):
            return None, (jsonify({"error": "Invalid date; use YYYY-MM-DD"}), 400)
        return selected, None

    def _open():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            conn.close()
            return None
        org = user_org_id(me)
        if not org:
            conn.close()
            return None
        return conn, cursor, me, int(org)

    def _guard(action: str):
        opened = _open()
        if opened is None:
            # _open already closed after an auth failure. Re-run to return the original response.
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            try:
                me, err_resp, err_code = require_user(cursor)
                if err_resp:
                    return None, err_resp, err_code
                if not user_org_id(me):
                    return None, jsonify({"error": "Organization required"}), 400
            finally:
                conn.close()
            return None, jsonify({"error": "Unauthorized"}), 401
        conn, cursor, me, org = opened
        if not can(role_set(me), action):
            conn.close()
            return None, jsonify({"error": "Forbidden"}), 403
        if not read_flags(cursor, org).get("supervisor_portal"):
            conn.close()
            return None, jsonify({"error": "Supervisor portal is not enabled"}), 403
        return (conn, cursor, me, org), None, None

    def _actor(me: dict) -> dict:
        return {
            "id": me.get("id") or me.get("user_id"),
            "name": me.get("name") or me.get("display_name") or me.get("email") or me.get("username"),
        }

    def _portal_day(cursor, org: int, selected: date) -> dict:
        from backend.management_wf_folder_performance import build_day_folder_performance
        from backend.rinse_performance_auto_approve import auto_approve_enabled
        from backend.rinse_performance_folder_publisher import (
            attach_publication_status_to_day,
            get_folder_benchmark,
        )
        from backend.rinse_step1_productivity_fast import load_completed_productivity_day_bags

        completed = load_completed_productivity_day_bags(
            cursor, org, selected, include_hd=False, rush_filter="all"
        )
        completed = [
            row
            for row in completed
            if str(row.get("service_type") or row.get("service_bucket") or "").upper() == "WF"
        ]
        day = build_day_folder_performance(
            cursor, org, selected_date_et=selected, attach_customers=False
        )
        attach_publication_status_to_day(cursor, org, day)
        stamp_approval_sources(cursor, org, day)
        week = week_start(selected)
        incidents = list_incidents(cursor, org, week)
        points = incident_totals(incidents).get("employee_points") or {}
        payload = assemble_supervisor_day(
            selected_date=selected,
            completed=completed,
            day=day,
            adjustments=list_adjustments(cursor, org, selected),
            auto_approval_threshold=get_folder_benchmark(cursor, org),
            scoring_target=scoring_target_for(cursor, org, "FOLDER", selected),
            auto_approve_enabled=auto_approve_enabled(cursor, org),
            quality_points_by_employee=points,
        )
        payload["quality"] = {
            "week_start": week.isoformat(),
            **{key: value for key, value in incident_totals(incidents).items()},
        }
        payload["training_due"] = training_due_count(cursor, org, selected)
        payload["scoring"] = draft_policy()
        payload["flags"] = read_flags(cursor, org)
        return payload

    def _quality_for_window(cursor, org: int, start: date, end: date) -> dict:
        incidents = []
        seen = set()
        monday = week_start(start)
        while monday <= end:
            for row in list_incidents(cursor, org, monday):
                key = row.get("id") or row.get("incident_key")
                if key in seen:
                    continue
                seen.add(key)
                incidents.append(row)
            monday += timedelta(days=7)
        return {"period_start": start.isoformat(), "period_end": end.isoformat(), **incident_totals(incidents)}

    def _load_period(org: int, selected: date, period: str) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from backend.supervisor_portal.period import aggregate_period, iter_dates, period_bounds

        start, end = period_bounds(selected, period)
        dates = iter_dates(start, end)
        key = str(period or "day").strip().lower()
        if key not in {"week", "month"}:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            try:
                payload = _portal_day(cursor, org, selected)
            finally:
                conn.close()
            payload["period"] = "day"
            payload["period_start"] = selected.isoformat()
            payload["period_end"] = selected.isoformat()
            return payload

        def _one(day: date) -> dict:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            try:
                built = _portal_day(cursor, org, day)
                built["employees"] = [
                    {field: value for field, value in employee.items() if field != "sessions"}
                    for employee in built.get("employees") or []
                ]
                recon = dict(built.get("reconciliation") or {})
                recon["bags"] = []
                built["reconciliation"] = recon
                return built
            except Exception as exc:
                return {"date_et": day.isoformat(), "error": str(exc)}
            finally:
                conn.close()

        built_days = []
        workers = min(3, len(dates))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_one, day) for day in dates]
            for future in as_completed(futures):
                built_days.append(future.result())
        built_days.sort(key=lambda row: str(row.get("date_et") or ""))
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            quality = _quality_for_window(cursor, org, start, end)
            flags = read_flags(cursor, org)
            due = training_due_count(cursor, org, end)
        finally:
            conn.close()
        combined = aggregate_period(built_days, quality=quality)
        combined.update(
            {
                "period": key,
                "date_et": selected.isoformat(),
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "timezone": "America/New_York",
                "scoring": draft_policy(),
                "flags": flags,
                "training_due": due,
                "below_target": [row["employee"] for row in combined["employees"] if row.get("below_target")],
                "pending_session_count": sum(int(day.get("pending_session_count") or 0) for day in built_days if not day.get("error")),
                "folding_role": {"role_key": "FOLDER", "label": "Folding", "measurable": True},
            }
        )
        return combined

    @app.route("/api/supervisor/day", methods=["GET"])
    def supervisor_day():
        opened, err, code = _guard("view_portal")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            selected, date_err = _date_arg()
            if date_err:
                return date_err
            period = (request.args.get("period") or "day").strip().lower()
            access = {
                "configure": can(role_set(me), "configure_targets"),
                "adjust": can(role_set(me), "adjust_session"),
            }
        finally:
            conn.close()
        try:
            payload = _load_period(org, selected, period)
            payload["access"] = access
            return jsonify(payload)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503

    @app.route("/api/supervisor/overview", methods=["GET"])
    def supervisor_overview():
        opened, err, code = _guard("view_portal")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            selected, date_err = _date_arg()
            if date_err:
                return date_err
            payload = _portal_day(cursor, org, selected)
            tasks = _task_metrics(cursor, org, selected)
            follow_ups = []
            if payload["reconciliation"]["unaccounted"]:
                follow_ups.append({"kind": "reconciliation", "label": "Completed bags are unaccounted"})
            if payload["below_target"]:
                follow_ups.append(
                    {"kind": "performance", "label": f"{len(payload['below_target'])} employees below target"}
                )
            if payload["pending_session_count"]:
                follow_ups.append(
                    {"kind": "approval", "label": f"{payload['pending_session_count']} sessions still pending"}
                )
            if payload.get("training_due"):
                follow_ups.append({"kind": "training", "label": f"{payload['training_due']} training assignments overdue"})
            pending_verify = int((tasks.get("pending_verification") or 0))
            if pending_verify:
                follow_ups.append({"kind": "tasks", "label": f"{pending_verify} tasks awaiting verification"})
            return jsonify(
                {
                    "date_et": payload["date_et"],
                    "timezone": payload["timezone"],
                    "volume": payload["volume"],
                    "reconciliation": {
                        "total_completed": payload["reconciliation"]["total_completed"],
                        "total_accounted": payload["reconciliation"]["total_accounted"],
                        "unaccounted": payload["reconciliation"]["unaccounted"],
                        "categories": payload["reconciliation"]["categories"],
                        "invariant_holds": payload["reconciliation"]["invariant_holds"],
                    },
                    "approved_productivity": payload["approved_productivity"],
                    "below_target": payload["below_target"],
                    "pending_session_count": payload["pending_session_count"],
                    "team": payload["team"],
                    "quality": payload["quality"],
                    "training_due": payload["training_due"],
                    "tasks": tasks,
                    "follow_ups": follow_ups,
                    "employees_working": len(payload["employees"]),
                    "scoring": payload["scoring"],
                }
            )
        finally:
            conn.close()

    @app.route("/api/supervisor/rinse-summary", methods=["GET"])
    def supervisor_rinse_summary():
        opened, err, code = _guard("view_rinse_aggregate")
        if err:
            return err, code
        conn, cursor, _me, org = opened
        try:
            selected, date_err = _date_arg()
            if date_err:
                return date_err
            payload = _portal_day(cursor, org, selected)
            folding = payload["folding_role"]
            payload["role_performance"] = [
                {
                    "role_key": folding["role_key"],
                    "label": folding["label"],
                    "measurable": True,
                    "unit": "lb/hr",
                    "team_average": payload["team"]["average_lbs_per_hour"],
                    "team_median": payload["team"]["median_lbs_per_hour"],
                    "target": payload["achievement_target_lbs_per_hour"],
                }
            ]
            return jsonify(strip_rinse_summary(payload))
        finally:
            conn.close()

    @app.route("/api/supervisor/adjustments", methods=["POST"])
    def supervisor_adjustment_create():
        opened, err, code = _guard("adjust_session")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            selected, date_err = _date_arg("date")
            if date_err:
                return date_err
            if body.get("date"):
                selected = parse_date_value(str(body.get("date"))[:10])
            day = _portal_day(cursor, org, selected)
            session = _find_session(day, body.get("session_id"))
            payload = validate_adjustment(body, session)
            actor = _actor(me)
            linked = _apply_existing_approval(cursor, org, selected, payload, session, actor)
            if linked is not None and not linked.get("ok", True):
                return jsonify(linked), 400
            saved = insert_adjustment(cursor, org, selected, payload, actor)
            conn.commit()
            saved["linked_approval"] = linked
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/adjustments/<int:adjustment_id>/reverse", methods=["POST"])
    def supervisor_adjustment_reverse(adjustment_id: int):
        opened, err, code = _guard("adjust_session")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            result = reverse_adjustment(
                cursor,
                org,
                adjustment_id,
                actor_id=_actor(me).get("id"),
                reason=str(body.get("reason") or ""),
            )
            if result.get("ok"):
                conn.commit()
            status = 200 if result.get("ok") else 404
            return jsonify(result), status
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/targets", methods=["POST"])
    def supervisor_target_create():
        opened, err, code = _guard("configure_targets")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            saved = insert_scoring_target(cursor, org, body, actor_id=_actor(me).get("id"))
            conn.commit()
            saved["auto_approval_unchanged"] = True
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/primary-roles", methods=["GET", "POST"])
    def supervisor_primary_roles():
        action = "configure_targets" if request.method == "POST" else "view_portal"
        opened, err, code = _guard(action)
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            if request.method == "GET":
                user_id = int(request.args.get("user_id") or 0)
                return jsonify({"history": list_primary_roles(cursor, org, user_id)})
            body = request.get_json(silent=True) or {}
            saved = set_primary_role(cursor, org, body, actor_id=_actor(me).get("id"))
            conn.commit()
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/roles", methods=["GET"])
    def supervisor_roles():
        from backend.supervisor_portal.role_measurement import measure_captured, role_readiness

        opened, err, code = _guard("view_portal")
        if err:
            return err, code
        conn, cursor, _me, org = opened
        from backend.supervisor_portal.store import scoring_target_for
        from backend.business_time import business_today

        rows = role_readiness()
        today = business_today()
        for row in rows:
            target = scoring_target_for(cursor, org, row["role_key"], today)
            row["target"] = None if target is None else float(target)
            row["target_unit"] = row.get("unit") if target is not None else None
        conn.close()
        probe = request.args.get("probe")
        if probe:
            measured = measure_captured(
                probe,
                {
                    "eligible_hours": request.args.get("eligible_hours"),
                    "output_quantity": request.args.get("output_quantity"),
                },
            )
            return jsonify({"roles": rows, "probe": measured, "scoring_active": False})
        return jsonify({"roles": rows, "scoring_active": False})

    @app.route("/api/supervisor/quality/types", methods=["GET", "POST"])
    def supervisor_quality_types():
        action = "configure_issue_types" if request.method == "POST" else "view_portal"
        opened, err, code = _guard(action)
        if err:
            return err, code
        conn, cursor, _me, org = opened
        try:
            if request.method == "GET":
                return jsonify({"types": list_issue_types(cursor, org)})
            body = request.get_json(silent=True) or {}
            if body.get("install_starter"):
                install_starter_issue_types(cursor, org)
            else:
                add_issue_type(cursor, org, code=str(body.get("code") or ""), label=str(body.get("label") or ""))
            conn.commit()
            return jsonify({"types": list_issue_types(cursor, org)})
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/quality/weights", methods=["GET", "POST"])
    def supervisor_quality_weights():
        action = "configure_weights" if request.method == "POST" else "view_portal"
        opened, err, code = _guard(action)
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            if request.method == "GET":
                from backend.supervisor_portal.quality import ILLUSTRATIVE_SEVERITY, ILLUSTRATIVE_WEIGHTS

                return jsonify(
                    {
                        "versions": list_weight_versions(cursor, org),
                        "illustrative_weights": ILLUSTRATIVE_WEIGHTS,
                        "illustrative_severity": ILLUSTRATIVE_SEVERITY,
                        "illustrative_only": True,
                    }
                )
            body = request.get_json(silent=True) or {}
            blocked = refuse_activation(body)
            if blocked:
                return jsonify({"error": blocked}), 409
            saved = insert_weight_version(cursor, org, body, actor_id=_actor(me).get("id"))
            conn.commit()
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/quality/week", methods=["GET"])
    def supervisor_quality_week():
        opened, err, code = _guard("view_portal")
        if err:
            return err, code
        conn, cursor, _me, org = opened
        try:
            selected, date_err = _date_arg()
            if date_err:
                return date_err
            incidents = list_incidents(cursor, org, selected)
            return jsonify(
                {
                    "week_start": week_start(selected).isoformat(),
                    "incidents": incidents,
                    "totals": incident_totals(incidents),
                    "types": list_issue_types(cursor, org),
                }
            )
        finally:
            conn.close()

    @app.route("/api/supervisor/quality/assignments", methods=["POST"])
    def supervisor_quality_assign():
        opened, err, code = _guard("assign_quality")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            selected = parse_date_value(str(body.get("week") or body.get("date") or business_today().isoformat())[:10])
            incident = normalize_incident(body, week=selected)
            version = published_weight_version(cursor, org, selected)
            saved = save_incident(cursor, org, incident, actor_id=_actor(me).get("id"), version=version)
            conn.commit()
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/quality/assignments/<int:incident_id>/reverse", methods=["POST"])
    def supervisor_quality_reverse(incident_id: int):
        opened, err, code = _guard("assign_quality")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            result = void_incident(
                cursor, org, incident_id, actor_id=_actor(me).get("id"), reason=str(body.get("reason") or "")
            )
            conn.commit()
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/scoring/policy", methods=["GET", "POST"])
    def supervisor_scoring_policy():
        if request.method == "POST":
            opened, err, code = _guard("configure_targets")
            if err:
                return err, code
            conn, cursor, _me, _org = opened
            conn.close()
            blocked = refuse_activation(request.get_json(silent=True) or {})
            return jsonify({"error": blocked or "scoring_formula_not_authorized", "policy": draft_policy()}), 409
        opened, err, code = _guard("view_portal")
        if err:
            return err, code
        conn, _cursor, _me, _org = opened
        conn.close()
        return jsonify(draft_policy())

    @app.route("/api/supervisor/training/templates", methods=["GET", "POST"])
    def supervisor_training_templates():
        action = "configure_training_template" if request.method == "POST" else "view_portal"
        opened, err, code = _guard(action)
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            if request.method == "GET":
                return jsonify({"templates": list_training_templates(cursor, org)})
            body = normalize_template(request.get_json(silent=True) or {})
            saved = save_training_template(cursor, org, body, actor_id=_actor(me).get("id"))
            conn.commit()
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/training/assignments", methods=["GET", "POST"])
    def supervisor_training_assignments():
        action = "assign_training" if request.method == "POST" else "view_portal"
        opened, err, code = _guard(action)
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            if request.method == "GET":
                trainee = request.args.get("trainee_user_id")
                rows = list_assignments(
                    cursor, org, trainee_user_id=int(trainee) if trainee else None
                )
                return jsonify({"assignments": rows, "completion_ratio": completion_ratio(rows)})
            saved = create_assignments(
                cursor, org, request.get_json(silent=True) or {}, actor_id=_actor(me).get("id")
            )
            conn.commit()
            return jsonify(saved)
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/supervisor/training/mine", methods=["GET"])
    def supervisor_training_mine():
        opened, err, code = _guard("view_own_training")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            uid = int(me.get("id") or me.get("user_id") or 0)
            rows = list_assignments(cursor, org, trainee_user_id=uid, mine_only=True)
            return jsonify({"assignments": rows})
        finally:
            conn.close()

    @app.route("/api/supervisor/training/assignments/<int:assignment_id>/progress", methods=["POST"])
    def supervisor_training_progress(assignment_id: int):
        opened, err, code = _guard("view_own_training")
        if err:
            return err, code
        conn, cursor, me, org = opened
        try:
            body = request.get_json(silent=True) or {}
            assignment = get_assignment(cursor, org, assignment_id)
            if not assignment:
                return jsonify({"error": "Assignment not found"}), 404
            actor_id = int(me.get("id") or me.get("user_id") or 0)
            trainee_id = int(assignment.get("trainee_user_id") or 0)
            supervisor = can(role_set(me), "verify_training")
            if actor_id != trainee_id and not supervisor:
                return jsonify({"error": "Forbidden"}), 403
            if body.get("item_id"):
                set_progress(
                    cursor,
                    assignment_id,
                    int(body["item_id"]),
                    done=bool(body.get("done", True)),
                    actor_id=actor_id,
                )
            items = assignment_items(cursor, assignment_id)
            ready = checklist_ready(
                [{"id": item["id"], "required": bool(item.get("required_step"))} for item in items],
                {item["id"]: bool(item.get("done")) for item in items},
            )
            requested = str(body.get("status") or "")
            status = assignment.get("status")
            if requested:
                status = next_status(
                    str(assignment.get("status") or "assigned"),
                    requested,
                    checklist_complete=ready,
                    practical_required=bool(assignment.get("practical_required")),
                    competency_result=body.get("competency_result") or assignment.get("competency_result"),
                    actor_is_trainee=actor_id == trainee_id,
                    actor_is_supervisor=supervisor,
                    actor_is_subject=actor_id == trainee_id,
                )
                update_assignment_status(
                    cursor,
                    org,
                    assignment_id,
                    status=status,
                    competency_result=body.get("competency_result"),
                    actor_id=actor_id,
                    notes=body.get("notes") if supervisor else None,
                )
            conn.commit()
            return jsonify({"ok": True, "status": status, "checklist_complete": ready, "items": items})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()

    def _pin_session():
        body = request.get_json(silent=True) or {}
        token = body.get("hub_token") or request.headers.get("X-Pin-Hub-Token") or ""
        from backend.employee_pin_hub import verify_hub_session_token

        try:
            return verify_hub_session_token(str(token)), body, None
        except ValueError as exc:
            return None, body, (jsonify({"error": str(exc)}), 401)

    def _pin_assignment_payload(cursor, assignment: dict) -> dict:
        items = assignment_items(cursor, int(assignment["id"]))
        ready = checklist_ready(
            [{"id": item["id"], "required": bool(item.get("required_step"))} for item in items],
            {item["id"]: bool(item.get("done")) for item in items},
        )
        public = {
            "id": assignment.get("id"),
            "title": assignment.get("title"),
            "status": assignment.get("status"),
            "instructions": assignment.get("instructions"),
            "practical_required": bool(assignment.get("practical_required")),
            "competency_result": assignment.get("competency_result"),
            "due_on": assignment.get("due_on").isoformat() if hasattr(assignment.get("due_on"), "isoformat") else assignment.get("due_on"),
            "checklist_complete": ready,
            "items": [
                {
                    "id": item.get("id"),
                    "label": item.get("label") or item.get("instruction"),
                    "instruction": item.get("instruction"),
                    "required": bool(item.get("required_step")),
                    "done": bool(item.get("done")),
                }
                for item in items
            ],
        }
        return public

    @app.route("/api/public/attendance/pin-training", methods=["POST"])
    def pin_training_list():
        session, _body, err = _pin_session()
        if err:
            return err
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if not read_flags(cursor, int(session["organization_id"])).get("supervisor_portal"):
                return jsonify({"error": "Supervisor portal is not enabled"}), 403
            rows = list_assignments(
                cursor,
                int(session["organization_id"]),
                trainee_user_id=int(session["employee_id"]),
                mine_only=True,
            )
            return jsonify({"assignments": [_pin_assignment_payload(cursor, row) for row in rows]})
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        finally:
            conn.close()

    @app.route("/api/public/attendance/pin-training/progress", methods=["POST"])
    def pin_training_progress():
        session, body, err = _pin_session()
        if err:
            return err
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            if not read_flags(cursor, int(session["organization_id"])).get("supervisor_portal"):
                return jsonify({"error": "Supervisor portal is not enabled"}), 403
            assignment_id = int(body.get("assignment_id") or 0)
            assignment = get_assignment(cursor, int(session["organization_id"]), assignment_id)
            if not assignment or int(assignment.get("trainee_user_id") or 0) != int(session["employee_id"]):
                return jsonify({"error": "Assignment not found"}), 404
            actor_id = int(session["employee_id"])
            if body.get("item_id"):
                set_progress(
                    cursor,
                    assignment_id,
                    int(body["item_id"]),
                    done=bool(body.get("done", True)),
                    actor_id=actor_id,
                )
            items = assignment_items(cursor, assignment_id)
            ready = checklist_ready(
                [{"id": item["id"], "required": bool(item.get("required_step"))} for item in items],
                {item["id"]: bool(item.get("done")) for item in items},
            )
            requested = str(body.get("status") or "")
            status = assignment.get("status")
            if requested:
                status = next_status(
                    str(assignment.get("status") or "assigned"),
                    requested,
                    checklist_complete=ready,
                    practical_required=bool(assignment.get("practical_required")),
                    competency_result=assignment.get("competency_result"),
                    actor_is_trainee=True,
                    actor_is_supervisor=False,
                    actor_is_subject=True,
                )
                update_assignment_status(
                    cursor,
                    int(session["organization_id"]),
                    assignment_id,
                    status=status,
                    competency_result=None,
                    actor_id=actor_id,
                    notes=None,
                )
            conn.commit()
            fresh = get_assignment(cursor, int(session["organization_id"]), assignment_id) or assignment
            return jsonify({"ok": True, "assignment": _pin_assignment_payload(cursor, fresh)})
        except MigrationRequired as exc:
            return jsonify({"error": str(exc), "migration": MIGRATION}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.close()


def _find_session(day: dict, session_id) -> dict | None:
    wanted = str(session_id or "")
    if not wanted:
        return None
    for employee in day.get("employees") or []:
        for session in employee.get("sessions") or []:
            if str(session.get("session_id") or "") == wanted:
                found = dict(session)
                found["employee"] = employee.get("employee")
                found["user_id"] = employee.get("user_id")
                found["performance_hours"] = session.get("original_hours")
                found["total_pre_lbs"] = session.get("original_lbs")
                found["lbs_per_hour"] = session.get("original_rate")
                found["start_time"] = session.get("start_time")
                found["end_time"] = session.get("end_time")
                return found
    return None


def _apply_existing_approval(cursor, org: int, selected: date, payload: dict, session: dict | None, actor: dict):
    kind = payload.get("kind")
    if kind not in {"exclude", "session_manual_rate"}:
        return None
    if not session:
        return {"ok": False, "error": "Session was not on this business day"}
    from backend.rinse_performance_approvals import exclude_session_publication, override_published_rate
    from backend.rinse_performance_folder_publisher import session_card_to_snapshot
    from backend.rinse_performance_roles import ROLE_FOLDER

    snapshot = session_card_to_snapshot(session, business_date_et=selected)
    if kind == "exclude":
        return exclude_session_publication(
            cursor,
            org,
            role_key=ROLE_FOLDER,
            session_id=str(payload["session_id"]),
            reason=payload.get("reason"),
            actor_user_id=actor.get("id"),
            actor_name=actor.get("name"),
            snapshot=snapshot,
        )
    return override_published_rate(
        cursor,
        org,
        role_key=ROLE_FOLDER,
        session_id=str(payload["session_id"]),
        published_metric_value=float(payload["manual_rate"]),
        reason=payload.get("reason"),
        actor_user_id=actor.get("id"),
        actor_name=actor.get("name"),
        approve_if_needed=True,
        snapshot=snapshot,
    )


def _task_metrics(cursor, org: int, selected: date) -> dict:
    try:
        from backend.cleaning_task_activity import dashboard_summary

        payload = dashboard_summary(cursor, org, business_date=selected)
        metrics = dict(payload.get("metrics") or {})
        metrics["source"] = "cleaning_task_activity.dashboard_summary"
        return metrics
    except Exception:
        return {"unavailable": True, "source": "cleaning_task_activity.dashboard_summary"}
