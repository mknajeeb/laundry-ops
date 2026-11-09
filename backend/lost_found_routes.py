"""PIN and supervisor routes for Lost & Found.

PIN writes use the existing attendance PIN / hub session gate and stay inside
that organization. Desktop reads and status changes use the signed-in user's
organization only.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from flask import Response, jsonify, request

from backend.attendance_pin_break import _gate_common
from backend.attendance_pin_punch import _employee_display_name
from backend.business_time import business_today
from backend.lost_found import (
    account_item,
    add_box_photo,
    add_item_photo,
    change_status,
    designated_redry_pockets,
    find_client_item,
    get_item,
    get_photo_row,
    list_found_items,
    list_issue_employees,
    search_issue_reports,
    location_choices,
    notify_found_item,
    reconciliation_view,
    report_found_item,
    save_designated_redry_pockets,
)
from backend.lost_found_photos import (
    discard_found_item_image,
    read_found_item_image,
    save_found_item_image,
)
from backend.lost_found_rules import ACTIVITY_CODE, LostFoundError
from backend.management_pin_access import HUB_ROLES, role_set


def _day(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _form_or_json() -> dict[str, Any]:
    if request.method == "GET":
        return {key: request.args.get(key) for key in request.args}
    if request.files or request.form:
        return {key: request.form.get(key) for key in request.form}
    return dict(request.get_json(silent=True) or {})


def _photo_files() -> list:
    files = []
    for key in ("photos", "photo", "file"):
        files.extend(request.files.getlist(key))
    return [fh for fh in files if fh and getattr(fh, "filename", None)]


def register_lost_found_routes(
    app,
    *,
    require_user: Callable,
    user_org_id: Callable,
    fetch_user_roles: Callable,
    get_request_ip: Callable,
):
    def _pin(action: str):
        from backend.db import get_db

        data = _form_or_json()
        org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
        pin = data.get("pin")
        hub_token = str(data.get("hub_token") or "").strip() or None
        conn = get_db()
        ctx, err = _gate_common(
            conn,
            org_slug,
            pin,
            hub_token,
            fetch_user_roles,
            get_request_ip(),
            action_prefix=action,
        )
        if err:
            return None, conn, err
        return ctx, conn, None

    def _close(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _fail(conn, exc: LostFoundError):
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": exc.message, "code": exc.code, "blockers": exc.blockers}), exc.status

    def _supervisor(cursor):
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return None, None, (err_resp, err_code)
        if not (role_set(me) & HUB_ROLES):
            return None, None, (jsonify({"error": "Forbidden"}), 403)
        try:
            oid = int(user_org_id(me))
        except (TypeError, ValueError):
            return None, None, (jsonify({"error": "Forbidden"}), 403)
        return me, oid, None

    @app.route("/api/public/attendance/pin-lost-found/locations", methods=["POST"])
    def pin_lost_found_locations():
        ctx, conn, err = _pin("lost_found_locations")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        try:
            return jsonify({"ok": True, **location_choices(cursor, int(ctx["org_id"]))})
        finally:
            _close(conn)

    @app.route("/api/public/attendance/pin-lost-found/report", methods=["POST"])
    def pin_lost_found_report():
        ctx, conn, err = _pin("lost_found_report")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        stored_photos: list[dict[str, str]] = []
        try:
            try:
                conn.autocommit = False
            except Exception:
                pass
            data = _form_or_json()
            photos = _photo_files()
            client_request_id = str(data.get("client_request_id") or "").strip()
            if not client_request_id:
                raise LostFoundError("A client request id is required.", code="client_request_required")
            existing = find_client_item(cursor, int(ctx["org_id"]), client_request_id)
            if existing is None:
                if not photos:
                    raise LostFoundError("At least one photo is required.", code="photo_required")
                for handle in photos:
                    raw = handle.read()
                    stored_photos.append(
                        save_found_item_image(int(ctx["org_id"]), raw, handle.filename or "photo.jpg")
                    )
            facility_name = None
            try:
                cursor.execute(
                    "SELECT display_name FROM organizations WHERE id=%s LIMIT 1",
                    (int(ctx["org_id"]),),
                )
                org_row = cursor.fetchone() or {}
                facility_name = (org_row.get("display_name") if isinstance(org_row, dict) else None) or None
            except Exception:
                facility_name = None
            session = ctx.get("session") or {}
            item, created = report_found_item(
                cursor,
                organization_id=int(ctx["org_id"]),
                client_request_id=client_request_id,
                user_id=int(ctx["user_id"]),
                reporter_name=_employee_display_name(ctx["matched"]),
                facility_name=facility_name,
                shift_session_id=session.get("id"),
                business_date=business_today(),
                location_kind=str(data.get("location_kind") or ""),
                location_number=data.get("location_number"),
                location_detail=data.get("location_detail"),
                notes=data.get("notes"),
                report_category=str(data.get("report_category") or "orphan"),
                redry_flags={
                    "missing_ticket": data.get("redry_missing_ticket"),
                    "mesh_bag": data.get("redry_mesh_bag"),
                    "wrong_pocket": data.get("redry_wrong_pocket"),
                },
            )
            if created:
                for stored in stored_photos:
                    add_item_photo(
                        cursor,
                        organization_id=int(ctx["org_id"]),
                        found_item_id=int(item["id"]),
                        user_id=int(ctx["user_id"]),
                        stored=stored,
                    )
                fresh = get_item(cursor, int(ctx["org_id"]), int(item["id"]))
                from backend.lost_found import _hydrate

                item = _hydrate(cursor, int(ctx["org_id"]), [fresh])[0]
                notify_found_item(cursor, int(ctx["org_id"]), item)
            else:
                for stored in stored_photos:
                    discard_found_item_image(stored)
                stored_photos = []
            conn.commit()
            return jsonify({"ok": True, "created": created, "item": item})
        except LostFoundError as exc:
            for stored in stored_photos:
                discard_found_item_image(stored)
            return _fail(conn, exc)
        except ValueError as exc:
            for stored in stored_photos:
                discard_found_item_image(stored)
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(exc), "code": "photo_invalid"}), 400
        except Exception:
            for stored in stored_photos:
                discard_found_item_image(stored)
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not save the found item."}), 500
        finally:
            _close(conn)

    @app.route("/api/public/attendance/pin-lost-found/reconciliation", methods=["POST"])
    def pin_lost_found_reconciliation():
        ctx, conn, err = _pin("lost_found_reconciliation")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        try:
            payload = reconciliation_view(cursor, int(ctx["org_id"]), business_today())
            conn.commit()
            return jsonify({"ok": True, "activity_code": ACTIVITY_CODE, **payload})
        except LostFoundError as exc:
            return _fail(conn, exc)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not load Lost & Found."}), 500
        finally:
            _close(conn)

    @app.route("/api/public/attendance/pin-lost-found/account", methods=["POST"])
    def pin_lost_found_account():
        ctx, conn, err = _pin("lost_found_account")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        try:
            data = request.json or {}
            payload = account_item(
                cursor,
                organization_id=int(ctx["org_id"]),
                business_date=business_today(),
                item_id=int(data.get("item_id")),
                actor_user_id=int(ctx["user_id"]),
                actor_name=_employee_display_name(ctx["matched"]),
                action=str(data.get("action") or ""),
                status=data.get("status"),
                order_reference=data.get("order_reference"),
                comment=data.get("comment"),
                reason=data.get("reason"),
            )
            conn.commit()
            return jsonify({"ok": True, **payload})
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "item_id is required"}), 400
        except LostFoundError as exc:
            return _fail(conn, exc)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not update the found item."}), 500
        finally:
            _close(conn)

    @app.route("/api/public/attendance/pin-lost-found/box-photo", methods=["POST"])
    def pin_lost_found_box_photo():
        ctx, conn, err = _pin("lost_found_box_photo")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        try:
            photos = _photo_files()
            if not photos:
                raise LostFoundError("A box photo is required.", code="box_photo_required")
            handle = photos[0]
            stored = save_found_item_image(int(ctx["org_id"]), handle.read(), handle.filename or "box.jpg")
            payload = add_box_photo(
                cursor,
                organization_id=int(ctx["org_id"]),
                business_date=business_today(),
                user_id=int(ctx["user_id"]),
                stored=stored,
            )
            conn.commit()
            return jsonify({"ok": True, **payload})
        except LostFoundError as exc:
            return _fail(conn, exc)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "code": "photo_invalid"}), 400
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Could not save the box photo."}), 500
        finally:
            _close(conn)

    @app.route("/api/public/attendance/pin-lost-found/photos/<int:photo_id>", methods=["GET"])
    def pin_lost_found_photo(photo_id: int):
        ctx, conn, err = _pin("lost_found_photo")
        if err:
            body, status = err
            _close(conn)
            return jsonify(body), status
        cursor = conn.cursor(dictionary=True)
        try:
            row = get_photo_row(cursor, int(ctx["org_id"]), int(photo_id))
            if not row:
                return jsonify({"error": "Photo not found"}), 404
            data, content_type = read_found_item_image(row["blob_name"], int(ctx["org_id"]))
            return Response(data, mimetype=content_type)
        except ValueError:
            return jsonify({"error": "Photo not found"}), 404
        finally:
            _close(conn)

    @app.route("/api/lost-found/redry-pockets", methods=["GET", "POST"])
    def lost_found_redry_pockets():
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            if request.method == "POST":
                data = request.json or {}
                saved = save_designated_redry_pockets(cursor, oid, data.get("pockets") or [])
                conn.commit()
                return jsonify({"ok": True, "pockets": saved})
            return jsonify({"ok": True, "pockets": designated_redry_pockets(cursor, oid)})
        except LostFoundError as exc:
            return _fail(conn, exc)
        finally:
            _close(conn)

    @app.route("/api/me/ui-locale", methods=["GET", "POST"])
    def ui_locale_preference():
        """Persist the signed-in user's English/Spanish choice. Local storage remains the fallback."""
        from backend.db import get_db
        from backend.ta_helpers import table_has_column

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err_resp, err_code = require_user(cursor)
            if err_resp:
                return err_resp, err_code
            user_id = int(me.get("user_id") or me.get("id") or 0)
            if not table_has_column(cursor, "users", "ui_locale"):
                return jsonify({"ok": True, "locale": None, "persisted": False})
            if request.method == "POST":
                locale = str((request.json or {}).get("locale") or "").strip().lower()
                if locale not in {"en", "es"}:
                    return jsonify({"ok": False, "error": "Choose English or Spanish."}), 400
                cursor.execute("UPDATE users SET ui_locale=%s WHERE id=%s", (locale, user_id))
                conn.commit()
                return jsonify({"ok": True, "locale": locale, "persisted": True})
            cursor.execute("SELECT ui_locale FROM users WHERE id=%s LIMIT 1", (user_id,))
            row = cursor.fetchone() or {}
            locale = str(row.get("ui_locale") or "").strip().lower()
            return jsonify({"ok": True, "locale": locale if locale in {"en", "es"} else None, "persisted": True})
        finally:
            _close(conn)

    @app.route("/api/lost-found", methods=["GET"])
    def lost_found_list():
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            selected = _day(request.args.get("date")) or business_today()
            date_from = _day(request.args.get("date_from")) or selected
            date_to = _day(request.args.get("date_to")) or date_from
            if date_to < date_from:
                date_from, date_to = date_to, date_from
            employee_raw = str(request.args.get("employee_id") or "").strip()
            try:
                employee_id = int(employee_raw) if employee_raw else None
            except ValueError:
                employee_id = None
            try:
                page = int(request.args.get("page") or 1)
            except ValueError:
                page = 1
            try:
                page_size = int(request.args.get("page_size") or 25)
            except ValueError:
                page_size = 25
            found = search_issue_reports(
                cursor,
                oid,
                date_from=date_from,
                date_to=date_to,
                employee_id=employee_id,
                category=request.args.get("category"),
                status=request.args.get("status"),
                location=request.args.get("location"),
                page=page,
                page_size=page_size,
            )
            employees = []
            try:
                employees = list_issue_employees(cursor, oid)
            except Exception:
                employees = []
            return jsonify({
                "ok": True,
                "business_date": business_today().isoformat(),
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "activity_code": ACTIVITY_CODE,
                "employees": employees,
                **found,
            })
        finally:
            _close(conn)

    @app.route("/api/lost-found/<int:item_id>", methods=["GET"])
    def lost_found_detail(item_id: int):
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            row = get_item(cursor, oid, int(item_id))
            if not row:
                return jsonify({"error": "Not found"}), 404
            from backend.lost_found import _hydrate

            return jsonify({"ok": True, "item": _hydrate(cursor, oid, [row])[0]})
        finally:
            _close(conn)

    @app.route("/api/lost-found/<int:item_id>/status", methods=["POST"])
    def lost_found_status(item_id: int):
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            data = request.json or {}
            item = change_status(
                cursor,
                organization_id=oid,
                item_id=int(item_id),
                actor_user_id=int(me.get("user_id") or me.get("id") or 0),
                actor_name=(me.get("display_name") or me.get("name") or me.get("username")),
                status=str(data.get("status") or ""),
                order_reference=data.get("order_reference"),
                comment=data.get("comment"),
                reason=data.get("reason"),
            )
            conn.commit()
            return jsonify({"ok": True, "item": item})
        except LostFoundError as exc:
            return _fail(conn, exc)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({"error": "Could not update status."}), 500
        finally:
            _close(conn)

    @app.route("/api/lost-found/reconciliation", methods=["GET"])
    def lost_found_reconciliation_desktop():
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            selected = _day(request.args.get("date")) or business_today()
            payload = reconciliation_view(cursor, oid, selected)
            conn.commit()
            return jsonify({"ok": True, **payload})
        except LostFoundError as exc:
            return _fail(conn, exc)
        finally:
            _close(conn)

    @app.route("/api/lost-found/photos/<int:photo_id>", methods=["GET"])
    def lost_found_photo(photo_id: int):
        from backend.db import get_db

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            _me, oid, denied = _supervisor(cursor)
            if denied:
                resp, code = denied
                return resp, code
            row = get_photo_row(cursor, oid, int(photo_id))
            if not row:
                return jsonify({"error": "Photo not found"}), 404
            data, content_type = read_found_item_image(row["blob_name"], oid)
            headers = {}
            if str(request.args.get("download") or "") == "1":
                headers["Content-Disposition"] = f'attachment; filename="issue-photo-{int(photo_id)}.jpg"'
            return Response(data, mimetype=content_type, headers=headers)
        except ValueError:
            return jsonify({"error": "Photo not found"}), 404
        finally:
            _close(conn)
