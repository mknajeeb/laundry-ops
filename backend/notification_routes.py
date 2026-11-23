"""Tenant notification admin API (groups, event routing, test dispatch)."""

from __future__ import annotations

from flask import jsonify, request


def _notification_org_id(me):
    """
    Require a real tenant organization_id. Prevents rows being written with organization_id=0
    when the session has no org (breaks lists and member joins).
    """
    raw = me.get("organization_id")
    if raw is None:
        return None, jsonify(
            {
                "error": (
                    "No organization on this session. Use a tenant user (assigned to an organization) "
                    "and open Notifications from the tenant app, not platform-only mode."
                ),
            },
        ), 400
    try:
        oid = int(raw)
    except (TypeError, ValueError):
        return None, jsonify({"error": "Invalid organization"}), 400
    if oid < 1:
        return None, jsonify({"error": "Invalid organization"}), 400
    return oid, None, None


def register_notification_routes(app):
    """Register on app; lazy-imports app helpers to avoid circular imports."""

    @app.route("/auth/notifications/groups", methods=["GET"])
    def notif_groups_list():
        from backend.app import get_db, require_admin, json_safe
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_groups"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                """
                SELECT id, organization_id, name, description, created_at, updated_at
                FROM notification_groups WHERE organization_id = %s ORDER BY name
                """,
                (oid,),
            )
            return jsonify({"groups": [json_safe(r) for r in cursor.fetchall() or []]})
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/groups", methods=["POST"])
    def notif_groups_create():
        from backend.app import get_db, require_admin
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_groups"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            body = request.json or {}
            name = (body.get("name") or "").strip()
            if not name:
                return jsonify({"error": "name is required"}), 400
            desc = (body.get("description") or "").strip() or None
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                """
                INSERT INTO notification_groups (organization_id, name, description)
                VALUES (%s,%s,%s)
                """,
                (oid, name[:128], desc[:512] if desc else None),
            )
            conn.commit()
            return jsonify({"id": cursor.lastrowid, "ok": True})
        except Exception as e:
            conn.rollback()
            if "Duplicate" in str(e) or "uq_notif_grp_org_name" in str(e):
                return jsonify({"error": "A group with this name already exists"}), 409
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/groups/<int:group_id>", methods=["PUT", "DELETE"])
    def notif_groups_one(group_id: int):
        from backend.app import get_db, require_admin
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_groups"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                "SELECT id FROM notification_groups WHERE id=%s AND organization_id=%s",
                (group_id, oid),
            )
            if not cursor.fetchone():
                return jsonify({"error": "Not found"}), 404
            if request.method == "DELETE":
                cursor.execute("DELETE FROM notification_groups WHERE id=%s AND organization_id=%s", (group_id, oid))
                conn.commit()
                return jsonify({"ok": True})
            body = request.json or {}
            name = (body.get("name") or "").strip()
            desc = body.get("description")
            if name:
                cursor.execute(
                    "UPDATE notification_groups SET name=%s, description=%s WHERE id=%s AND organization_id=%s",
                    (name[:128], (desc or "").strip()[:512] if desc is not None else None, group_id, oid),
                )
            elif desc is not None:
                cursor.execute(
                    "UPDATE notification_groups SET description=%s WHERE id=%s AND organization_id=%s",
                    ((desc or "").strip()[:512], group_id, oid),
                )
            conn.commit()
            return jsonify({"ok": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/groups/<int:group_id>/members", methods=["GET", "PUT"])
    def notif_groups_members(group_id: int):
        from backend.app import get_db, require_admin, json_safe
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_group_members"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                "SELECT id FROM notification_groups WHERE id=%s AND organization_id=%s",
                (group_id, oid),
            )
            if not cursor.fetchone():
                return jsonify({"error": "Not found"}), 404
            if request.method == "GET":
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.display_name
                    FROM notification_group_members m
                    JOIN users u ON u.id = m.user_id
                    WHERE m.group_id = %s AND u.organization_id = %s
                    ORDER BY u.display_name, u.username
                    """,
                    (group_id, oid),
                )
                return jsonify({"members": [json_safe(r) for r in cursor.fetchall() or []]})
            body = request.json or {}
            ids = body.get("user_ids") or []
            if not isinstance(ids, list):
                return jsonify({"error": "user_ids must be an array"}), 400
            clean = []
            for x in ids:
                try:
                    clean.append(int(x))
                except (TypeError, ValueError):
                    continue
            cursor.execute("DELETE FROM notification_group_members WHERE group_id=%s", (group_id,))
            for uid in clean:
                cursor.execute(
                    "SELECT 1 FROM users WHERE id=%s AND organization_id=%s LIMIT 1",
                    (uid, oid),
                )
                if cursor.fetchone():
                    cursor.execute(
                        "INSERT IGNORE INTO notification_group_members (group_id, user_id) VALUES (%s,%s)",
                        (group_id, uid),
                    )
            conn.commit()
            return jsonify({"ok": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/events", methods=["GET"])
    def notif_events_list():
        from backend.app import get_db, require_admin, json_safe
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_event_definitions"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                """
                SELECT id, organization_id, event_key, display_name, description, is_active, created_at, updated_at
                FROM notification_event_definitions WHERE organization_id = %s ORDER BY display_name
                """,
                (oid,),
            )
            return jsonify({"events": [json_safe(r) for r in cursor.fetchall() or []]})
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/events", methods=["POST"])
    def notif_events_create():
        from backend.app import get_db, require_admin
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_event_definitions"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            body = request.json or {}
            ek = (body.get("event_key") or "").strip().lower().replace(" ", "_")
            dn = (body.get("display_name") or "").strip()
            if not ek or not dn:
                return jsonify({"error": "event_key and display_name are required"}), 400
            desc = (body.get("description") or "").strip() or None
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                """
                INSERT INTO notification_event_definitions
                  (organization_id, event_key, display_name, description, is_active)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (oid, ek[:64], dn[:160], desc[:1024] if desc else None, 1 if body.get("is_active", True) else 0),
            )
            conn.commit()
            return jsonify({"id": cursor.lastrowid, "ok": True})
        except Exception as e:
            conn.rollback()
            if "Duplicate" in str(e) or "uq_notif_evt_org_key" in str(e):
                return jsonify({"error": "event_key already exists for this organization"}), 409
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/events/<int:event_id>", methods=["PUT", "DELETE"])
    def notif_events_one(event_id: int):
        from backend.app import get_db, require_admin
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_event_definitions"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                "SELECT id FROM notification_event_definitions WHERE id=%s AND organization_id=%s",
                (event_id, oid),
            )
            if not cursor.fetchone():
                return jsonify({"error": "Not found"}), 404
            if request.method == "DELETE":
                cursor.execute(
                    "DELETE FROM notification_event_definitions WHERE id=%s AND organization_id=%s",
                    (event_id, oid),
                )
                conn.commit()
                return jsonify({"ok": True})
            body = request.json or {}
            sets = []
            args: list = []
            if "display_name" in body:
                sets.append("display_name=%s")
                args.append((body.get("display_name") or "").strip()[:160])
            if "description" in body:
                sets.append("description=%s")
                d = (body.get("description") or "").strip()
                args.append(d[:1024] if d else None)
            if "is_active" in body:
                sets.append("is_active=%s")
                args.append(1 if body.get("is_active") else 0)
            if sets:
                args.extend([event_id, oid])
                cursor.execute(
                    f"UPDATE notification_event_definitions SET {', '.join(sets)} WHERE id=%s AND organization_id=%s",
                    args,
                )
            conn.commit()
            return jsonify({"ok": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/events/<int:event_id>/audiences", methods=["GET", "PUT"])
    def notif_events_audiences(event_id: int):
        from backend.app import get_db, require_admin, json_safe
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_event_audiences"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            cursor.execute(
                "SELECT id, event_key FROM notification_event_definitions WHERE id=%s AND organization_id=%s",
                (event_id, oid),
            )
            ev = cursor.fetchone()
            if not ev:
                return jsonify({"error": "Not found"}), 404
            if request.method == "GET":
                cursor.execute(
                    """
                    SELECT id, target_type, target_id, rule_kind, created_at
                    FROM notification_event_audiences
                    WHERE event_definition_id = %s AND organization_id = %s
                    ORDER BY rule_kind, target_type, target_id
                    """,
                    (event_id, oid),
                )
                return jsonify({"audiences": [json_safe(r) for r in cursor.fetchall() or []]})
            body = request.json or {}
            inc = body.get("includes") or []
            exc = body.get("excludes") or []
            cursor.execute(
                "DELETE FROM notification_event_audiences WHERE event_definition_id=%s AND organization_id=%s",
                (event_id, oid),
            )

            def add_rows(kind: str, items):
                for it in items or []:
                    tt = (it.get("type") or it.get("target_type") or "").strip().lower()
                    tid = it.get("id") or it.get("target_id")
                    if tt not in ("user", "group") or tid is None:
                        continue
                    try:
                        tid = int(tid)
                    except (TypeError, ValueError):
                        continue
                    if tt == "user":
                        if tid != -1:
                            cursor.execute(
                                "SELECT 1 FROM users WHERE id=%s AND organization_id=%s LIMIT 1",
                                (tid, oid),
                            )
                            if not cursor.fetchone():
                                continue
                    else:
                        cursor.execute(
                            "SELECT 1 FROM notification_groups WHERE id=%s AND organization_id=%s LIMIT 1",
                            (tid, oid),
                        )
                        if not cursor.fetchone():
                            continue
                    cursor.execute(
                        """
                        INSERT INTO notification_event_audiences
                          (event_definition_id, organization_id, target_type, target_id, rule_kind)
                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        (event_id, oid, tt, tid, kind),
                    )

            add_rows("include", inc)
            add_rows("exclude", exc)
            conn.commit()
            return jsonify({"ok": True})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/dispatch", methods=["POST"])
    def notif_dispatch():
        """Trigger a notification for an event_key (admin / server automation)."""
        from backend.app import get_db, require_admin
        from backend.notification_service import dispatch_notification_event
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            if not table_exists(cursor, "notification_event_definitions"):
                return jsonify({"error": "Run backend/sql/notification_module_v1.sql"}), 503
            body = request.json or {}
            ek = (body.get("event_key") or "").strip()
            title = (body.get("title") or "").strip() or "Notification"
            msg = (body.get("body") or body.get("message") or "").strip() or ""
            if not ek:
                return jsonify({"error": "event_key is required"}), 400
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            data = body.get("data") if isinstance(body.get("data"), dict) else None
            ch = body.get("channels")
            if ch is not None and not isinstance(ch, list):
                return jsonify({"error": "channels must be an array"}), 400
            out = dispatch_notification_event(
                cursor,
                organization_id=oid,
                event_key=ek,
                title=title[:200],
                body=msg[:2000],
                data=data,
                channels=ch,
            )
            conn.commit()
            return jsonify(out)
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/test-self", methods=["POST"])
    def notif_test_self():
        """One push to the signed-in reviewer's own devices. Does not notify anyone else."""
        from backend.app import get_db, require_user
        from backend.lost_found_rules import pin_issues_open_path
        from backend.management_pin_access import holds_pin_management_role
        from backend.notification_service import log_delivery
        from backend.onesignal_client import external_user_id, public_web_url, send_push_to_external_user_ids
        from backend.ta_helpers import table_exists

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_user(cursor)
            if err is not None:
                return err, st
            roles = me.get("roles") or []
            if not holds_pin_management_role(roles):
                return jsonify({"error": "Forbidden"}), 403
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            uid = int(me.get("user_id") or me.get("id") or 0)
            if uid < 1:
                return jsonify({"error": "Forbidden"}), 403
            slug = ""
            brand = "VeeWash"
            if table_exists(cursor, "organizations"):
                cursor.execute(
                    "SELECT slug, display_name FROM organizations WHERE id=%s LIMIT 1",
                    (oid,),
                )
                org = cursor.fetchone() or {}
                slug = str(org.get("slug") or "").strip().lower()
                brand = str(org.get("display_name") or "").strip() or brand
            open_path = pin_issues_open_path(slug, 0).split("?")[0]
            if slug:
                open_path = f"/pin/{slug}?next=/pin-issues"
            title = f"{brand} — Test"
            body = "This device can receive issue alerts. Tap to open Issues."
            ok, detail = send_push_to_external_user_ids(
                [external_user_id(oid, uid)],
                title,
                body,
                data={"type": "notification.test_self", "open_path": open_path},
                url=public_web_url(open_path),
                idempotency_key=None,
            )
            status = "sent" if ok else ("no_subscription" if detail and "no_subscribed" in detail else "failed")
            log_delivery(
                cursor,
                organization_id=oid,
                event_key="notification.test_self",
                user_id=uid,
                channel="push",
                status=status,
                detail=None if ok else detail,
                payload={"open_path": open_path},
            )
            conn.commit()
            return jsonify({"ok": ok, "status": status, "detail": detail, "open_path": open_path})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/management", methods=["GET"])
    def notif_management_catalog():
        from backend.app import get_db, require_admin
        from backend.notification_assignments import ensure_assignment_tables, management_catalog

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            ensure_assignment_tables(cursor)
            payload = management_catalog(cursor, oid)
            conn.commit()
            return jsonify(payload)
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/management/users", methods=["GET"])
    def notif_management_users():
        from backend.app import get_db, require_admin
        from backend.notification_assignments import search_active_users

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            return jsonify({"users": search_active_users(cursor, oid, request.args.get("q") or "")})
        finally:
            cursor.close()
            conn.close()

    @app.route("/auth/notifications/management/<event_key>", methods=["PUT"])
    def notif_management_save(event_key: str):
        from backend.app import get_db, require_admin
        from backend.notification_assignments import (
            NotificationAssignmentError,
            ensure_assignment_tables,
            save_management_assignment,
        )

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, st = require_admin(cursor)
            if err is not None:
                return err, st
            oid, oerr, ost = _notification_org_id(me)
            if oerr is not None:
                return oerr, ost
            body = request.json or {}
            ensure_assignment_tables(cursor)
            saved = save_management_assignment(
                cursor,
                organization_id=oid,
                event_key=event_key,
                user_ids=body.get("user_ids") or [],
                enabled=bool(body.get("enabled", True)),
                actor_user_id=int(me["user_id"]),
            )
            conn.commit()
            return jsonify({"ok": True, "event_key": event_key, "user_ids": saved})
        except NotificationAssignmentError as ex:
            conn.rollback()
            status = 404 if ex.code == "unknown_category" else 400
            return jsonify({"error": ex.code}), status
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
