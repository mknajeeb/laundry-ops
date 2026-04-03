"""Tenant notification admin API (groups, event routing, test dispatch)."""

from __future__ import annotations

from flask import jsonify, request


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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
            oid = int(me.get("organization_id") or 0)
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
