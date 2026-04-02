import json
from datetime import datetime, timedelta
from functools import wraps

import mysql.connector
from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.db import get_db
from backend.payroll_identity import (
    ensure_payroll_profile_for_washpro,
    fetch_payroll_profile_row,
    get_or_create_payroll_cycle_unified,
    get_payroll_period_settings,
    payroll_profiles_active,
    set_payroll_period_settings,
    user_has_perm_washpro,
)
from backend.ta_helpers import (
    as_bool,
    haversine_meters,
    hash_password,
    json_safe,
    verify_password,
)

ta_bp = Blueprint("ta_api", __name__)


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="laundry-ta-auth")


def create_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def parse_token(token: str) -> dict:
    return _serializer().loads(token, max_age=60 * 60 * 24 * 7)


def get_setting(conn, organization_id: int, key: str, default=None):
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s",
        (int(organization_id), key),
    )
    r = c.fetchone()
    return r["svalue"] if r else default


def set_setting(conn, organization_id: int, key: str, value: str):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def _tenant_id():
    return int(g.ta_user.get("organization_id") or 1)


def _user_belongs_to_tenant(conn, user_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    c.execute("SELECT organization_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
    row = c.fetchone()
    if not row:
        return False
    return int(row.get("organization_id") or 1) == _tenant_id()


def user_has_perm(conn, user_id: int, perm_key: str) -> bool:
    if payroll_profiles_active(conn):
        return user_has_perm_washpro(conn, user_id, perm_key)
    c = conn.cursor()
    c.execute(
        """
        SELECT 1 FROM ta_users u
        JOIN role_permissions rp ON rp.role_id = u.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE u.id = %s AND p.perm_key = %s
        LIMIT 1
        """,
        (user_id, perm_key),
    )
    return c.fetchone() is not None


def fetch_user_row(conn, user_id: int):
    if payroll_profiles_active(conn):
        return fetch_payroll_profile_row(conn, int(user_id))
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT u.*, r.code AS role_code, r.name AS role_name
        FROM ta_users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = %s
        """,
        (user_id,),
    )
    u = c.fetchone()
    if u is not None and "organization_id" not in u:
        u["organization_id"] = 1
    return u


def _ta_users_table_exists(conn) -> bool:
    c = conn.cursor()
    c.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'ta_users'
        LIMIT 1
        """
    )
    return c.fetchone() is not None


def _washpro_session_row(conn, token: str):
    """Validate main-app auth_sessions token (Washpro login)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT s.user_id, s.revoked, s.expires_at,
               u.username, u.display_name, u.active
        FROM auth_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = %s
        LIMIT 1
        """,
        (token,),
    )
    row = c.fetchone()
    if not row or row.get("revoked"):
        return None
    exp = row.get("expires_at")
    if isinstance(exp, datetime) and exp < datetime.utcnow():
        return None
    if not as_bool(row.get("active"), default=False):
        return None
    return row


def _pick_default_ta_role_id(conn, washpro_user_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT r.code FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        """,
        (washpro_user_id,),
    )
    codes = {str(x["code"]).upper() for x in c.fetchall()}
    # Must match real rows in `roles` (see maintenance_inventory_auth.sql: ADMIN, OPS, FRONT_DESK).
    target = "OPS"
    if "ADMIN" in codes:
        target = "ADMIN"
    elif "FRONT_DESK" in codes:
        target = "FRONT_DESK"
    elif "OPS" in codes:
        target = "OPS"
    c.execute("SELECT id FROM roles WHERE code=%s LIMIT 1", (target,))
    r = c.fetchone()
    if r:
        return r["id"]
    c.execute(
        """
        SELECT r.id FROM roles r
        JOIN role_permissions rp ON rp.role_id = r.id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.perm_key = 'ta.clock'
        ORDER BY r.id LIMIT 1
        """
    )
    r = c.fetchone()
    return r["id"] if r else None


def _ensure_ta_user_for_washpro(conn, wp: dict):
    """Link Washpro login to a ta_users row (auto-create on first TA API use)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT * FROM ta_users WHERE washpro_user_id=%s LIMIT 1",
        (wp["user_id"],),
    )
    existing = c.fetchone()
    if existing:
        return existing
    role_id = _pick_default_ta_role_id(conn, wp["user_id"])
    if not role_id:
        return None
    username = (wp.get("username") or "user").strip() or "user"
    display = (wp.get("display_name") or username).strip()
    parts = display.split(None, 1)
    first = (parts[0] or username)[:128]
    last = (parts[1] if len(parts) > 1 else "")[:128] or first
    email = f"{username.lower()}.{wp['user_id']}@washpro.local"
    ph = hash_password("unused-washpro-sso-" + str(wp["user_id"]))
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ta_users (
              washpro_user_id, employee_id, first_name, last_name, email, hire_date,
              active, role_id, password_hash
            ) VALUES (%s,%s,%s,%s,%s,CURDATE(),1,%s,%s)
            """,
            (
                wp["user_id"],
                f"WP{wp['user_id']}",
                first,
                last,
                email,
                role_id,
                ph,
            ),
        )
        uid = cur.lastrowid
        conn.commit()
        return fetch_user_row(conn, uid)
    except Exception:
        conn.rollback()
        c.execute(
            "SELECT * FROM ta_users WHERE washpro_user_id=%s LIMIT 1",
            (wp["user_id"],),
        )
        return c.fetchone()


def resolve_user_from_token():
    """
    Accepts (1) legacy TA signed JWT, or (2) Washpro session token (same Bearer as /auth/login).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None

    # 1) Legacy TA token (itsdangerous) — uid is ta_users.id before migration, Washpro users.id after
    try:
        data = parse_token(token)
        uid = data.get("uid")
        if uid:
            conn = get_db()
            try:
                if not payroll_profiles_active(conn) and not _ta_users_table_exists(conn):
                    return None
                u = fetch_user_row(conn, int(uid))
                if u and as_bool(u.get("active"), default=False):
                    u.pop("password_hash", None)
                    return u
            finally:
                conn.close()
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        pass

    # 2) Washpro app session (hex token from auth_sessions)
    conn = get_db()
    try:
        if not payroll_profiles_active(conn) and not _ta_users_table_exists(conn):
            return None
        wp = _washpro_session_row(conn, token)
        if not wp:
            return None
        if payroll_profiles_active(conn):
            u = ensure_payroll_profile_for_washpro(conn, wp)
        else:
            u = _ensure_ta_user_for_washpro(conn, wp)
        if not u or not as_bool(u.get("active"), default=False):
            return None
        u.pop("password_hash", None)
        return u
    except Exception:
        return None
    finally:
        conn.close()


def write_audit(conn, actor_id, entity_type, entity_id, action, old=None, new=None, remarks=None):
    org_id = 1
    try:
        org_id = int(g.ta_user.get("organization_id") or 1)
    except Exception:
        pass
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO audit_log (organization_id, actor_user_id, entity_type, entity_id, action, old_value, new_value, remarks)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            org_id,
            actor_id,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            action,
            json.dumps(old) if old is not None else None,
            json.dumps(new) if new is not None else None,
            remarks,
        ),
    )


def get_or_create_payroll_cycle(conn, at: datetime, organization_id: int) -> int:
    return get_or_create_payroll_cycle_unified(conn, at, organization_id)


def get_primary_geofence(conn, user_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT g.*, ug.is_primary
        FROM user_geofences ug
        JOIN geofences g ON g.id = ug.geofence_id
        JOIN users u ON u.id = ug.user_id
        WHERE ug.user_id=%s AND ug.is_primary=1 AND g.active=1
          AND g.organization_id = u.organization_id
        LIMIT 1
        """,
        (user_id,),
    )
    return c.fetchone()


def sum_break_seconds(conn, shift_id: int) -> int:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT break_start_at, break_end_at FROM shift_breaks WHERE shift_session_id=%s
        """,
        (shift_id,),
    )
    total = 0
    for row in c.fetchall():
        start = row["break_start_at"]
        end = row["break_end_at"]
        if start and end:
            total += int((end - start).total_seconds())
    return total


def get_open_break(conn, shift_id: int):
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM shift_breaks
        WHERE shift_session_id=%s AND break_end_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (shift_id,),
    )
    return c.fetchone()


def maybe_auto_close_shift(conn, sess: dict, user_id: int, organization_id: int):
    max_h = float(get_setting(conn, organization_id, "max_shift_hours", "14"))
    clock_in = sess["clock_in_at"]
    if isinstance(clock_in, str):
        clock_in = datetime.fromisoformat(str(clock_in).replace("Z", "+00:00"))
    if clock_in.tzinfo:
        clock_in = clock_in.replace(tzinfo=None)
    now = datetime.now()
    elapsed = (now - clock_in).total_seconds()
    if elapsed <= max_h * 3600:
        return None

    br = sum_break_seconds(conn, sess["id"])
    net = int(elapsed) - br
    c = conn.cursor()
    c.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, status='auto_closed', total_break_seconds=%s, net_work_seconds=%s
        WHERE id=%s
        """,
        (now, br, net, sess["id"]),
    )
    c.execute(
        """
        INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message, severity)
        VALUES (%s,%s,'max_shift_exceeded',%s,'error')
        """,
        (sess["id"], user_id, f"Shift exceeded {max_h} hours; auto clock-out."),
    )
    return fetch_session(conn, sess["id"])


def fetch_session(conn, sid: int):
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
    return c.fetchone()


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = resolve_user_from_token()
        if not u:
            return jsonify({"error": "Unauthorized"}), 401
        g.ta_user = u
        return f(*args, **kwargs)

    return wrapper


def require_perm(perm_key: str):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            conn = get_db()
            try:
                if not user_has_perm(conn, g.ta_user["id"], perm_key):
                    return jsonify({"error": "Forbidden"}), 403
            finally:
                conn.close()
            return f(*args, **kwargs)

        return wrapper

    return deco


def require_any_perm(*perm_keys: str):
    """Allow the request if the TA user has any of the listed permissions."""

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            conn = get_db()
            try:
                ok = any(
                    user_has_perm(conn, g.ta_user["id"], k) for k in perm_keys
                )
                if not ok:
                    return jsonify({"error": "Forbidden"}), 403
            finally:
                conn.close()
            return f(*args, **kwargs)

        return wrapper

    return deco


# --- Auth ---


@ta_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT pp.*, u.id AS washpro_user_id
                FROM payroll_profiles pp
                JOIN users u ON u.id = pp.user_id
                WHERE LOWER(pp.email)=%s
                LIMIT 1
                """,
                (email,),
            )
            row = c.fetchone()
            if not row or not as_bool(row.get("active"), default=False):
                return jsonify({"error": "Invalid credentials"}), 401
            if not verify_password(row["password_hash"], password):
                return jsonify({"error": "Invalid credentials"}), 401
            uid = int(row["washpro_user_id"])
            u = fetch_payroll_profile_row(conn, uid)
            u.pop("password_hash", None)
            token = create_token(uid)
            conn.commit()
            return jsonify({"token": token, "user": json_safe(u)})
        c.execute(
            """
            SELECT u.*, r.code AS role_code, r.name AS role_name
            FROM ta_users u JOIN roles r ON r.id = u.role_id
            WHERE LOWER(u.email)=%s
            """,
            (email,),
        )
        u = c.fetchone()
        if not u or not u.get("active"):
            return jsonify({"error": "Invalid credentials"}), 401
        if not verify_password(u["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        u.pop("password_hash", None)
        token = create_token(u["id"])
        conn.commit()
        return jsonify({"token": token, "user": json_safe(u)})
    finally:
        conn.close()


@ta_bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT DISTINCT p.perm_key
                FROM user_roles ur
                JOIN role_permissions rp ON rp.role_id = ur.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE ur.user_id = %s
                ORDER BY p.perm_key
                """,
                (g.ta_user["id"],),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
        else:
            c.execute(
                """
                SELECT p.perm_key FROM ta_users u
                JOIN role_permissions rp ON rp.role_id = u.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE u.id=%s
                """,
                (g.ta_user["id"],),
            )
            perms = [r["perm_key"] for r in c.fetchall()]
        u = fetch_user_row(conn, g.ta_user["id"])
        u.pop("password_hash", None)
        return jsonify({"user": json_safe(u), "permissions": perms})
    finally:
        conn.close()


# --- Geofence / me ---


@ta_bp.route("/me/geofence", methods=["GET"])
@require_auth
def my_geofence():
    conn = get_db()
    try:
        gfn = get_primary_geofence(conn, g.ta_user["id"])
        if not gfn:
            return jsonify({"error": "No primary geofence assigned"}), 400
        return jsonify(json_safe(gfn))
    finally:
        conn.close()


# --- Clock ---


@ta_bp.route("/sessions/current", methods=["GET"])
@require_auth
@require_perm("ta.clock")
def sessions_current():
    lat = request.args.get("latitude")
    lng = request.args.get("longitude")
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
        inside = None
        if sess:
            closed = maybe_auto_close_shift(conn, sess, g.ta_user["id"], _tenant_id())
            if closed:
                conn.commit()
                sess = None
            else:
                sess = fetch_session(conn, sess["id"])
                ob = get_open_break(conn, sess["id"])
                sess["open_break"] = json_safe(ob) if ob else None
                clock_in = sess["clock_in_at"]
                if isinstance(clock_in, str):
                    clock_in = datetime.fromisoformat(str(clock_in).replace("Z", "+00:00"))
                if clock_in and getattr(clock_in, "tzinfo", None):
                    clock_in = clock_in.replace(tzinfo=None)
                now_ts = datetime.now()
                br_done = sum_break_seconds(conn, sess["id"])
                break_live = br_done
                if ob:
                    bs = ob["break_start_at"]
                    if isinstance(bs, str):
                        bs = datetime.fromisoformat(str(bs).replace("Z", "+00:00"))
                    if bs and getattr(bs, "tzinfo", None):
                        bs = bs.replace(tzinfo=None)
                    if bs:
                        break_live += int((now_ts - bs).total_seconds())
                elapsed = int((now_ts - clock_in).total_seconds()) if clock_in else 0
                sess["elapsed_work_seconds"] = max(0, elapsed - break_live)
                gfn = get_primary_geofence(conn, g.ta_user["id"])
                if lat and lng and gfn:
                    dist = haversine_meters(
                        float(lat), float(lng), float(gfn["latitude"]), float(gfn["longitude"])
                    )
                    inside = dist <= float(gfn["radius_meters"])
                    if inside is False:
                        c.execute(
                            """
                            INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message)
                            VALUES (%s,%s,'outside_geofence',%s)
                            """,
                            (
                                sess["id"],
                                g.ta_user["id"],
                                f"Location ping outside geofence (~{int(dist)}m).",
                            ),
                        )
                sess["geofence_inside"] = inside
                sess["primary_geofence"] = json_safe(gfn) if gfn else None

        op = get_operational_state(conn, g.ta_user["id"], sess, geofence_inside=inside)
        conn.commit()
        return jsonify({"session": json_safe(sess), "operational": op})
    finally:
        conn.close()


def get_operational_state(conn, user_id: int, sess, geofence_inside=None):
    if not sess:
        return {"allowed": False, "reasons": ["not_clocked_in"]}
    ob = get_open_break(conn, sess["id"])
    if ob:
        return {"allowed": False, "reasons": ["on_break"]}
    gfn = get_primary_geofence(conn, user_id)
    if not gfn:
        return {"allowed": False, "reasons": ["no_geofence"]}
    if geofence_inside is False:
        return {"allowed": False, "reasons": ["outside_geofence"]}
    return {"allowed": True, "reasons": []}


@ta_bp.route("/sessions/clock-in", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def clock_in():
    data = request.json or {}
    lat = data.get("latitude")
    lng = data.get("longitude")
    employment_category_id = data.get("employment_category_id")

    if lat is None or lng is None:
        return jsonify({"error": "latitude and longitude required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        u = fetch_user_row(conn, g.ta_user["id"])
        if not u["active"]:
            return jsonify({"error": "User inactive"}), 400
        if u.get("termination_date"):
            return jsonify({"error": "Employment terminated"}), 400

        c.execute(
            "SELECT id FROM shift_sessions WHERE user_id=%s AND status='active'",
            (g.ta_user["id"],),
        )
        if c.fetchone():
            return jsonify({"error": "Already clocked in"}), 400

        gfn = get_primary_geofence(conn, g.ta_user["id"])
        if not gfn:
            return jsonify({"error": "Assign a primary geofence before clock-in"}), 400

        dist = haversine_meters(
            float(lat), float(lng), float(gfn["latitude"]), float(gfn["longitude"])
        )
        if dist > float(gfn["radius_meters"]):
            return jsonify(
                {
                    "error": "Outside active geofence",
                    "distance_meters": round(dist, 1),
                    "radius_meters": float(gfn["radius_meters"]),
                }
            ), 400

        if employment_category_id:
            c.execute(
                """
                SELECT 1 FROM employment_categories
                WHERE id=%s AND organization_id=%s
                """,
                (employment_category_id, _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category"}), 400
            c.execute(
                """
                SELECT 1 FROM user_employment_categories
                WHERE user_id=%s AND employment_category_id=%s
                  AND effective_from <= CURDATE()
                  AND (effective_to IS NULL OR effective_to >= CURDATE())
                """,
                (g.ta_user["id"], employment_category_id),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category for user"}), 400
        else:
            c.execute(
                """
                SELECT employment_category_id FROM user_employment_categories
                WHERE user_id=%s AND effective_from <= CURDATE()
                  AND (effective_to IS NULL OR effective_to >= CURDATE())
                ORDER BY effective_from DESC LIMIT 1
                """,
                (g.ta_user["id"],),
            )
            row = c.fetchone()
            employment_category_id = row["employment_category_id"] if row else None

        now = datetime.now()
        pc_id = get_or_create_payroll_cycle(conn, now, _tenant_id())

        c2 = conn.cursor()
        c2.execute(
            """
            INSERT INTO shift_sessions (
              user_id, organization_id, payroll_cycle_id, geofence_id, employment_category_id,
              clock_in_at, clock_in_lat, clock_in_lng, status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')
            """,
            (
                g.ta_user["id"],
                _tenant_id(),
                pc_id,
                gfn["id"],
                employment_category_id,
                now,
                float(lat),
                float(lng),
            ),
        )
        sid = c2.lastrowid
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "clock_in",
            new={"clock_in_at": now.isoformat()},
        )
        conn.commit()
        sess = fetch_session(conn, sid)
        return jsonify(json_safe(sess)), 201
    finally:
        conn.close()


@ta_bp.route("/sessions/clock-out", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def clock_out():
    data = request.json or {}
    lat = data.get("latitude")
    lng = data.get("longitude")

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400

        if get_open_break(conn, sess["id"]):
            return jsonify({"error": "End break before clocking out"}), 400

        br = sum_break_seconds(conn, sess["id"])
        now = datetime.now()
        clock_in = sess["clock_in_at"]
        if isinstance(clock_in, str):
            clock_in = datetime.fromisoformat(str(clock_in).replace("Z", "+00:00"))
        if clock_in.tzinfo:
            clock_in = clock_in.replace(tzinfo=None)
        elapsed = (now - clock_in).total_seconds()
        net = int(elapsed) - br

        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE shift_sessions
            SET clock_out_at=%s, clock_out_lat=%s, clock_out_lng=%s,
                status='completed', total_break_seconds=%s, net_work_seconds=%s
            WHERE id=%s
            """,
            (
                now,
                float(lat) if lat is not None else None,
                float(lng) if lng is not None else None,
                br,
                net,
                sess["id"],
            ),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sess["id"],
            "clock_out",
            old={"session_id": sess["id"]},
            new={"clock_out_at": now.isoformat(), "net_work_seconds": net},
        )
        conn.commit()
        out = fetch_session(conn, sess["id"])
        return jsonify(
            {
                "session": json_safe(out),
                "summary": {
                    "clock_in_at": json_safe(out["clock_in_at"]),
                    "clock_out_at": json_safe(out["clock_out_at"]),
                    "total_break_seconds": br,
                    "net_work_seconds": net,
                },
            }
        )
    finally:
        conn.close()


@ta_bp.route("/sessions/break/start", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def break_start():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400
        if get_open_break(conn, sess["id"]):
            return jsonify({"error": "Break already in progress"}), 400

        now = datetime.now()
        c2 = conn.cursor()
        c2.execute(
            """
            INSERT INTO shift_breaks (shift_session_id, break_start_at)
            VALUES (%s,%s)
            """,
            (sess["id"], now),
        )
        conn.commit()
        b = get_open_break(conn, sess["id"])
        return jsonify(json_safe(b)), 201
    finally:
        conn.close()


@ta_bp.route("/sessions/break/end", methods=["POST"])
@require_auth
@require_perm("ta.clock")
def break_end():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_sessions
            WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
            """,
            (g.ta_user["id"],),
        )
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "No active session"}), 400
        ob = get_open_break(conn, sess["id"])
        if not ob:
            return jsonify({"error": "No active break"}), 400

        now = datetime.now()
        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE shift_breaks SET break_end_at=%s WHERE id=%s
            """,
            (now, ob["id"]),
        )
        conn.commit()
        c.execute("SELECT * FROM shift_breaks WHERE id=%s", (ob["id"],))
        return jsonify(json_safe(c.fetchone()))
    finally:
        conn.close()


# --- Users ---


@ta_bp.route("/users", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings")
def users_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT pp.user_id FROM payroll_profiles pp
                JOIN users u ON u.id = pp.user_id
                WHERE u.organization_id = %s
                ORDER BY pp.last_name, pp.first_name
                """,
                (_tenant_id(),),
            )
            out = []
            for row in c.fetchall():
                r = fetch_payroll_profile_row(conn, int(row["user_id"]))
                if not r:
                    continue
                c2 = conn.cursor(dictionary=True)
                c2.execute(
                    """
                    SELECT GROUP_CONCAT(DISTINCT r.code ORDER BY r.code SEPARATOR ',') AS role_codes
                    FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = %s
                    """,
                    (row["user_id"],),
                )
                rc = c2.fetchone() or {}
                r["role_codes"] = rc.get("role_codes")
                r.pop("password_hash", None)
                out.append(r)
            return jsonify([json_safe(r) for r in out])
        c.execute(
            """
            SELECT u.*, r.code AS role_code, r.name AS role_name
            FROM ta_users u JOIN roles r ON r.id = u.role_id
            ORDER BY u.last_name, u.first_name
            """
        )
        rows = c.fetchall()
        for r in rows:
            r.pop("password_hash", None)
        return jsonify([json_safe(r) for r in rows])
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def users_get(user_id):
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            u = fetch_payroll_profile_row(conn, user_id)
            if not u:
                return jsonify({"error": "Not found"}), 404
            if int(u.get("organization_id") or 1) != _tenant_id():
                return jsonify({"error": "Not found"}), 404
            u.pop("password_hash", None)
            pid = u.get("rehire_parent_user_id")
            if pid:
                c.execute(
                    """
                    SELECT user_id AS id, employee_id, first_name, last_name, email, active, termination_date
                    FROM payroll_profiles WHERE user_id=%s
                    """,
                    (pid,),
                )
                u["rehire_parent"] = c.fetchone()
                u["rehire_parent_id"] = pid
            else:
                u["rehire_parent"] = None
                u["rehire_parent_id"] = None
            try:
                c.execute(
                    """
                    SELECT user_id AS id, employee_id, first_name, last_name, email, active, hire_date
                    FROM payroll_profiles WHERE rehire_parent_user_id=%s ORDER BY user_id
                    """,
                    (user_id,),
                )
                u["rehire_successors"] = c.fetchall()
            except mysql.connector.Error:
                u["rehire_successors"] = []
        else:
            c.execute(
                """
                SELECT u.*, r.code AS role_code, r.name AS role_name
                FROM ta_users u JOIN roles r ON r.id = u.role_id
                WHERE u.id=%s
                """,
                (user_id,),
            )
            u = c.fetchone()
            if not u:
                return jsonify({"error": "Not found"}), 404
            u.pop("password_hash", None)
            if u.get("rehire_parent_id"):
                c.execute(
                    """
                    SELECT id, employee_id, first_name, last_name, email, active, termination_date
                    FROM ta_users WHERE id=%s
                    """,
                    (u["rehire_parent_id"],),
                )
                u["rehire_parent"] = c.fetchone()
            else:
                u["rehire_parent"] = None
            try:
                c.execute(
                    """
                    SELECT id, employee_id, first_name, last_name, email, active, hire_date
                    FROM ta_users WHERE rehire_parent_id=%s ORDER BY id
                    """,
                    (user_id,),
                )
                u["rehire_successors"] = c.fetchall()
            except mysql.connector.Error:
                u["rehire_successors"] = []
        c.execute(
            "SELECT geofence_id, is_primary FROM user_geofences WHERE user_id=%s",
            (user_id,),
        )
        gfs = c.fetchall()
        u["geofence_ids"] = [g["geofence_id"] for g in gfs]
        primary = next((g["geofence_id"] for g in gfs if g["is_primary"]), None)
        u["primary_geofence_id"] = primary
        c.execute(
            """
            SELECT employment_category_id, effective_from, effective_to
            FROM user_employment_categories WHERE user_id=%s
            """,
            (user_id,),
        )
        u["employment_assignments"] = c.fetchall()
        return jsonify(json_safe(u))
    finally:
        conn.close()


@ta_bp.route("/users", methods=["POST"])
@require_auth
@require_perm("users.add")
def users_create():
    data = request.json or {}
    conn = get_db()
    try:
        if payroll_profiles_active(conn):
            required = ["washpro_user_id", "first_name", "last_name", "email", "password"]
            for k in required:
                if not data.get(k):
                    return jsonify({"error": f"Missing {k}"}), 400
            wid = int(data["washpro_user_id"])
            ph = hash_password(data["password"])
            c = conn.cursor(dictionary=True)
            c.execute("SELECT id, organization_id FROM users WHERE id=%s", (wid,))
            uw = c.fetchone()
            if not uw:
                return jsonify({"error": "Washpro user not found"}), 404
            if int(uw.get("organization_id") or 1) != _tenant_id():
                return jsonify({"error": "Washpro user is not in your organization"}), 400
            c.execute("SELECT 1 FROM payroll_profiles WHERE user_id=%s", (wid,))
            if c.fetchone():
                return jsonify({"error": "Payroll profile already exists for this user"}), 400
            rp = data.get("rehireParentUserId") or data.get("rehire_parent_user_id")
            if rp in (None, ""):
                rp = None
            else:
                rp = int(rp)
                c.execute(
                    """
                    SELECT pp.user_id FROM payroll_profiles pp
                    JOIN users u ON u.id = pp.user_id
                    WHERE pp.user_id=%s AND u.organization_id=%s
                    """,
                    (rp, _tenant_id()),
                )
                if not c.fetchone():
                    return jsonify({"error": "rehire_parent not found"}), 400
            c2 = conn.cursor()
            c2.execute(
                """
                INSERT INTO payroll_profiles (
                  user_id, employee_id, first_name, last_name, address, email, mobile, itin_ssn,
                  hire_date, termination_date, rehired, active, rehire_parent_user_id, prior_employee_id, password_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    wid,
                    data.get("employee_id"),
                    data["first_name"],
                    data["last_name"],
                    data.get("address"),
                    data["email"].strip().lower(),
                    data.get("mobile"),
                    data.get("itin_ssn"),
                    data.get("hire_date"),
                    data.get("termination_date"),
                    1 if data.get("rehired") else 0,
                    1 if data.get("active", True) else 0,
                    rp,
                    data.get("prior_employee_id"),
                    ph,
                ),
            )
            if data.get("role_id"):
                c2.execute("DELETE FROM user_roles WHERE user_id=%s", (wid,))
                c2.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                    (wid, int(data["role_id"])),
                )
            write_audit(conn, g.ta_user["id"], "user", wid, "create", new={"email": data["email"]})
            conn.commit()
            return jsonify({"id": wid}), 201

        required = ["first_name", "last_name", "email", "role_id", "password"]
        for k in required:
            if not data.get(k):
                return jsonify({"error": f"Missing {k}"}), 400

        ph = hash_password(data["password"])
        c = conn.cursor(dictionary=True)
        rp = data.get("rehire_parent_id")
        if rp is not None and str(rp).strip() != "":
            rp = int(rp)
        else:
            rp = None
        if rp is not None:
            c.execute("SELECT id FROM ta_users WHERE id=%s", (rp,))
            if not c.fetchone():
                return jsonify({"error": "rehire_parent_id not found"}), 400
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO ta_users (
              employee_id, first_name, last_name, address, email, mobile, itin_ssn,
              hire_date, termination_date, rehired, active, role_id,
              rehire_parent_id, prior_employee_id, password_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("employee_id"),
                data["first_name"],
                data["last_name"],
                data.get("address"),
                data["email"].strip().lower(),
                data.get("mobile"),
                data.get("itin_ssn"),
                data.get("hire_date"),
                data.get("termination_date"),
                1 if data.get("rehired") else 0,
                1 if data.get("active", True) else 0,
                int(data["role_id"]),
                rp,
                data.get("prior_employee_id"),
                ph,
            ),
        )
        uid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "user", uid, "create", new={"email": data["email"]})
        conn.commit()
        return jsonify({"id": uid}), 201
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def users_update(user_id):
    data = request.json or {}
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute("SELECT * FROM payroll_profiles WHERE user_id=%s", (user_id,))
            old = c.fetchone()
            if not old:
                return jsonify({"error": "Not found"}), 404
            if not _user_belongs_to_tenant(conn, user_id):
                return jsonify({"error": "Not found"}), 404

            fields = []
            vals = []
            mapping = [
                ("employee_id", "employee_id"),
                ("first_name", "first_name"),
                ("last_name", "last_name"),
                ("address", "address"),
                ("email", "email"),
                ("mobile", "mobile"),
                ("itin_ssn", "itin_ssn"),
                ("hire_date", "hire_date"),
                ("termination_date", "termination_date"),
                ("rehired", "rehired"),
                ("active", "active"),
                ("prior_employee_id", "prior_employee_id"),
            ]
            for json_k, col in mapping:
                if json_k in data:
                    v = data[json_k]
                    if col in ("rehired", "active"):
                        v = 1 if v else 0
                    fields.append(f"{col}=%s")
                    vals.append(v)
            if "rehire_parent_id" in data:
                v = data["rehire_parent_id"]
                if v in (None, ""):
                    v = None
                else:
                    v = int(v)
                if v is not None and v == user_id:
                    return jsonify({"error": "rehire parent cannot be the same user"}), 400
                if v is not None:
                    c.execute(
                        """
                        SELECT pp.user_id FROM payroll_profiles pp
                        JOIN users u ON u.id = pp.user_id
                        WHERE pp.user_id=%s AND u.organization_id=%s
                        """,
                        (v, _tenant_id()),
                    )
                    if not c.fetchone():
                        return jsonify({"error": "rehire_parent not found"}), 400
                fields.append("rehire_parent_user_id=%s")
                vals.append(v)
            if data.get("password"):
                fields.append("password_hash=%s")
                vals.append(hash_password(data["password"]))

            if fields:
                vals.append(user_id)
                c2 = conn.cursor()
                c2.execute(f"UPDATE payroll_profiles SET {', '.join(fields)} WHERE user_id=%s", vals)
            if "role_id" in data and data["role_id"] is not None:
                c.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
                c.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                    (user_id, int(data["role_id"])),
                )
            write_audit(conn, g.ta_user["id"], "user", user_id, "update", old={"id": old["user_id"]}, new=data)
            conn.commit()
            return jsonify({"ok": True})

        c.execute("SELECT * FROM ta_users WHERE id=%s", (user_id,))
        old = c.fetchone()
        if not old:
            return jsonify({"error": "Not found"}), 404

        fields = []
        vals = []
        mapping = [
            ("employee_id", "employee_id"),
            ("first_name", "first_name"),
            ("last_name", "last_name"),
            ("address", "address"),
            ("email", "email"),
            ("mobile", "mobile"),
            ("itin_ssn", "itin_ssn"),
            ("hire_date", "hire_date"),
            ("termination_date", "termination_date"),
            ("rehired", "rehired"),
            ("active", "active"),
            ("role_id", "role_id"),
            ("prior_employee_id", "prior_employee_id"),
        ]
        for json_k, col in mapping:
            if json_k in data:
                v = data[json_k]
                if col in ("rehired", "active"):
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if "rehire_parent_id" in data:
            v = data["rehire_parent_id"]
            if v in (None, ""):
                v = None
            else:
                v = int(v)
            if v is not None and v == user_id:
                return jsonify({"error": "rehire_parent_id cannot be the same user"}), 400
            if v is not None:
                c.execute("SELECT id FROM ta_users WHERE id=%s", (v,))
                if not c.fetchone():
                    return jsonify({"error": "rehire_parent_id not found"}), 400
            fields.append("rehire_parent_id=%s")
            vals.append(v)
        if data.get("password"):
            fields.append("password_hash=%s")
            vals.append(hash_password(data["password"]))

        if fields:
            vals.append(user_id)
            c2 = conn.cursor()
            c2.execute(f"UPDATE ta_users SET {', '.join(fields)} WHERE id=%s", vals)
        write_audit(conn, g.ta_user["id"], "user", user_id, "update", old={"id": old["id"]}, new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/geofences", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def user_geofences(user_id):
    data = request.json or {}
    ids = data.get("geofence_ids") or []
    primary_id = data.get("primary_geofence_id")

    conn = get_db()
    try:
        if payroll_profiles_active(conn) and not _user_belongs_to_tenant(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        c = conn.cursor()
        for gid in ids:
            c.execute(
                "SELECT 1 FROM geofences WHERE id=%s AND organization_id=%s",
                (int(gid), _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid geofence"}), 400
        c.execute("DELETE FROM user_geofences WHERE user_id=%s", (user_id,))
        for gid in ids:
            is_p = 1 if gid == primary_id else 0
            c.execute(
                "INSERT INTO user_geofences (user_id, geofence_id, is_primary) VALUES (%s,%s,%s)",
                (user_id, int(gid), is_p),
            )
        write_audit(
            conn,
            g.ta_user["id"],
            "user_geofences",
            user_id,
            "replace",
            new={"geofence_ids": ids, "primary": primary_id},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/users/<int:user_id>/employment-categories", methods=["PUT"])
@require_auth
@require_perm("users.edit")
def user_employment_cats(user_id):
    data = request.json or {}
    rows = data.get("assignments") or []
    conn = get_db()
    try:
        if payroll_profiles_active(conn) and not _user_belongs_to_tenant(conn, user_id):
            return jsonify({"error": "Not found"}), 404
        c = conn.cursor()
        for r in rows:
            cid = int(r["employment_category_id"])
            c.execute(
                "SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s",
                (cid, _tenant_id()),
            )
            if not c.fetchone():
                return jsonify({"error": "Invalid employment category"}), 400
        c.execute("DELETE FROM user_employment_categories WHERE user_id=%s", (user_id,))
        for r in rows:
            c.execute(
                """
                INSERT INTO user_employment_categories (user_id, employment_category_id, effective_from, effective_to)
                VALUES (%s,%s,%s,%s)
                """,
                (
                    user_id,
                    int(r["employment_category_id"]),
                    r["effective_from"],
                    r.get("effective_to"),
                ),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- Geofences CRUD ---


@ta_bp.route("/geofences", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def geofences_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM geofences WHERE organization_id=%s ORDER BY name",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/geofences", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def geofences_create():
    data = request.json or {}
    for k in ("name", "latitude", "longitude", "radius_meters"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO geofences (organization_id, name, location_description, latitude, longitude, radius_meters, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                _tenant_id(),
                data["name"],
                data.get("location_description"),
                float(data["latitude"]),
                float(data["longitude"]),
                int(data["radius_meters"]),
                1 if data.get("active", True) else 0,
            ),
        )
        gid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "geofence", gid, "create", new=data)
        conn.commit()
        return jsonify({"id": gid}), 201
    finally:
        conn.close()


@ta_bp.route("/geofences/<int:gid>", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def geofences_update(gid):
    data = request.json or {}
    conn = get_db()
    try:
        fields = []
        vals = []
        for col in (
            "name",
            "location_description",
            "latitude",
            "longitude",
            "radius_meters",
            "active",
        ):
            if col in data:
                v = data[col]
                if col == "active":
                    v = 1 if v else 0
                fields.append(f"{col}=%s")
                vals.append(v)
        if not fields:
            return jsonify({"error": "No fields"}), 400
        vals.extend([gid, _tenant_id()])
        c = conn.cursor()
        c.execute(
            f"UPDATE geofences SET {', '.join(fields)} WHERE id=%s AND organization_id=%s",
            vals,
        )
        write_audit(conn, g.ta_user["id"], "geofence", gid, "update", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- Employment categories & rates ---


@ta_bp.route("/employment-categories", methods=["GET"])
@require_auth
def employment_categories_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM employment_categories WHERE organization_id=%s ORDER BY name",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/employment-categories", methods=["POST"])
@require_auth
@require_perm("ta.settings")
def employment_categories_create():
    data = request.json or {}
    if not data.get("name") or not data.get("code"):
        return jsonify({"error": "name and code required"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO employment_categories (organization_id, code, name, active)
            VALUES (%s,%s,%s,%s)
            """,
            (
                _tenant_id(),
                data["code"],
                data["name"],
                1 if data.get("active", True) else 0,
            ),
        )
        cid = c.lastrowid
        conn.commit()
        return jsonify({"id": cid}), 201
    finally:
        conn.close()


@ta_bp.route("/user-rates", methods=["GET"])
@require_auth
@require_any_perm("users.view", "ta.settings", "users.edit")
def user_rates_list():
    uid = request.args.get("user_id")
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if uid:
            c.execute(
                """
                SELECT ur.*, ec.name AS category_name, ec.code AS category_code
                FROM user_rates ur
                JOIN employment_categories ec ON ec.id = ur.employment_category_id
                JOIN users u ON u.id = ur.user_id
                WHERE ur.user_id=%s AND u.organization_id=%s
                ORDER BY ur.effective_date DESC
                """,
                (int(uid), _tenant_id()),
            )
        else:
            if payroll_profiles_active(conn):
                c.execute(
                    """
                    SELECT ur.*, ec.name AS category_name, pp.email AS user_email
                    FROM user_rates ur
                    JOIN employment_categories ec ON ec.id = ur.employment_category_id
                    JOIN payroll_profiles pp ON pp.user_id = ur.user_id
                    JOIN users u ON u.id = ur.user_id
                    WHERE u.organization_id=%s
                    ORDER BY ur.effective_date DESC
                    LIMIT 500
                    """,
                    (_tenant_id(),),
                )
            else:
                c.execute(
                    """
                    SELECT ur.*, ec.name AS category_name, u.email AS user_email
                    FROM user_rates ur
                    JOIN employment_categories ec ON ec.id = ur.employment_category_id
                    JOIN ta_users u ON u.id = ur.user_id
                    ORDER BY ur.effective_date DESC
                    LIMIT 500
                    """
                )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/user-rates", methods=["POST"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def user_rates_create():
    data = request.json or {}
    for k in ("user_id", "employment_category_id", "hourly_rate", "effective_date"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        if payroll_profiles_active(conn):
            if not _user_belongs_to_tenant(conn, int(data["user_id"])):
                return jsonify({"error": "Invalid user"}), 400
        c.execute(
            """
            SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s
            """,
            (int(data["employment_category_id"]), _tenant_id()),
        )
        if not c.fetchone():
            return jsonify({"error": "Invalid employment category"}), 400
        c.execute(
            """
            INSERT INTO user_rates (user_id, employment_category_id, hourly_rate, effective_date, end_date, role_job_function)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                int(data["user_id"]),
                int(data["employment_category_id"]),
                float(data["hourly_rate"]),
                data["effective_date"],
                data.get("end_date"),
                data.get("role_job_function"),
            ),
        )
        rid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "user_rate", rid, "create", new=data)
        conn.commit()
        return jsonify({"id": rid}), 201
    finally:
        conn.close()


# --- Monitor ---


@ta_bp.route("/monitor/sessions", methods=["GET"])
@require_auth
@require_perm("ta.monitor")
def monitor_sessions():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            q = """
            SELECT s.*, pp.email, pp.first_name, pp.last_name, g.name AS geofence_name,
                   pc.cycle_ref, ec.name AS category_name
            FROM shift_sessions s
            JOIN payroll_profiles pp ON pp.user_id = s.user_id
            JOIN geofences g ON g.id = s.geofence_id
            JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
            LEFT JOIN employment_categories ec ON ec.id = s.employment_category_id
            WHERE s.organization_id=%s
            """
        else:
            q = """
            SELECT s.*, u.email, u.first_name, u.last_name, g.name AS geofence_name,
                   pc.cycle_ref, ec.name AS category_name
            FROM shift_sessions s
            JOIN ta_users u ON u.id = s.user_id
            JOIN geofences g ON g.id = s.geofence_id
            JOIN payroll_cycles pc ON pc.id = s.payroll_cycle_id
            LEFT JOIN employment_categories ec ON ec.id = s.employment_category_id
            WHERE s.organization_id=%s
            """
        params = [_tenant_id()]
        if request.args.get("payroll_cycle_id"):
            q += " AND s.payroll_cycle_id=%s"
            params.append(int(request.args["payroll_cycle_id"]))
        if request.args.get("user_id"):
            q += " AND s.user_id=%s"
            params.append(int(request.args["user_id"]))
        if request.args.get("from_date"):
            q += " AND DATE(s.clock_in_at) >= %s"
            params.append(request.args["from_date"])
        if request.args.get("to_date"):
            q += " AND DATE(s.clock_in_at) <= %s"
            params.append(request.args["to_date"])
        if request.args.get("geofence_id"):
            q += " AND s.geofence_id=%s"
            params.append(int(request.args["geofence_id"]))
        q += " ORDER BY s.clock_in_at DESC LIMIT 500"
        c.execute(q, params)
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/sessions/<int:sid>/force-clock-out", methods=["POST"])
@require_auth
@require_perm("ta.override")
def force_clock_out(sid):
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        sess = c.fetchone()
        if not sess or sess["status"] != "active":
            return jsonify({"error": "No active session"}), 400

        if get_open_break(conn, sid):
            return jsonify({"error": "User is on break; end break first"}), 400

        br = sum_break_seconds(conn, sid)
        now = datetime.now()
        clock_in = sess["clock_in_at"]
        if isinstance(clock_in, str):
            clock_in = datetime.fromisoformat(str(clock_in).replace("Z", "+00:00"))
        if clock_in.tzinfo:
            clock_in = clock_in.replace(tzinfo=None)
        elapsed = (now - clock_in).total_seconds()
        net = int(elapsed) - br

        c2 = conn.cursor()
        c2.execute(
            """
            UPDATE shift_sessions
            SET clock_out_at=%s, status='completed', total_break_seconds=%s,
                net_work_seconds=%s, manual_override=1
            WHERE id=%s
            """,
            (now, br, net, sid),
        )
        c2.execute(
            """
            INSERT INTO shift_exceptions (shift_session_id, user_id, exception_type, message)
            VALUES (%s,%s,'manual_force_clock_out',%s)
            """,
            (sid, sess["user_id"], remarks),
        )
        write_audit(
            conn,
            g.ta_user["id"],
            "shift_session",
            sid,
            "force_clock_out",
            remarks=remarks,
        )
        conn.commit()
        return jsonify(json_safe(fetch_session(conn, sid)))
    finally:
        conn.close()


@ta_bp.route("/sessions/<int:sid>/adjust-times", methods=["POST"])
@require_auth
@require_perm("ta.override")
def adjust_times(sid):
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400

    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        sess = c.fetchone()
        if not sess:
            return jsonify({"error": "Not found"}), 400

        cin = data.get("clock_in_at")
        cout = data.get("clock_out_at")
        if cin:
            c.execute("UPDATE shift_sessions SET clock_in_at=%s, manual_override=1 WHERE id=%s", (cin, sid))
        if cout:
            c.execute("UPDATE shift_sessions SET clock_out_at=%s, manual_override=1 WHERE id=%s", (cout, sid))

        c.execute("SELECT * FROM shift_sessions WHERE id=%s", (sid,))
        s2 = c.fetchone()
        br = sum_break_seconds(conn, sid)
        if s2["clock_in_at"] and s2["clock_out_at"]:
            ci, co = s2["clock_in_at"], s2["clock_out_at"]
            if isinstance(ci, str):
                ci = datetime.fromisoformat(str(ci).replace("Z", "+00:00"))
            if isinstance(co, str):
                co = datetime.fromisoformat(str(co).replace("Z", "+00:00"))
            if ci.tzinfo:
                ci = ci.replace(tzinfo=None)
            if co.tzinfo:
                co = co.replace(tzinfo=None)
            net = int((co - ci).total_seconds()) - br
            c.execute(
                "UPDATE shift_sessions SET total_break_seconds=%s, net_work_seconds=%s WHERE id=%s",
                (br, net, sid),
            )

        write_audit(conn, g.ta_user["id"], "shift_session", sid, "adjust_times", new=data, remarks=remarks)
        conn.commit()
        return jsonify(json_safe(fetch_session(conn, sid)))
    finally:
        conn.close()


@ta_bp.route("/adjustments", methods=["POST"])
@require_auth
@require_perm("ta.override")
def create_adjustment():
    data = request.json or {}
    remarks = (data.get("remarks") or "").strip()
    if not remarks:
        return jsonify({"error": "remarks required"}), 400
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "user_id required"}), 400

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO payroll_adjustments (
              shift_session_id, payroll_cycle_id, user_id, adjustment_type,
              amount_cents, slack_minutes, remarks, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("shift_session_id"),
                data.get("payroll_cycle_id"),
                int(uid),
                data.get("adjustment_type", "manual"),
                int(data.get("amount_cents") or 0),
                int(data.get("slack_minutes") or 0),
                remarks,
                g.ta_user["id"],
            ),
        )
        aid = c.lastrowid
        write_audit(conn, g.ta_user["id"], "payroll_adjustment", aid, "create", new=data, remarks=remarks)
        conn.commit()
        return jsonify({"id": aid}), 201
    finally:
        conn.close()


@ta_bp.route("/exceptions", methods=["GET"])
@require_auth
@require_perm("ta.monitor")
def list_exceptions():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            """
            SELECT * FROM shift_exceptions
            ORDER BY created_at DESC LIMIT 200
            """
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payroll-cycles", methods=["GET"])
@require_auth
@require_any_perm("ta.monitor", "ta.settings")
def payroll_cycles_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM payroll_cycles WHERE organization_id=%s ORDER BY week_start_date DESC LIMIT 52",
            (_tenant_id(),),
        )
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/settings", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def settings_get():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT skey, svalue FROM system_settings WHERE organization_id=%s",
            (_tenant_id(),),
        )
        return jsonify({r["skey"]: r["svalue"] for r in c.fetchall()})
    finally:
        conn.close()


@ta_bp.route("/settings", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def settings_put():
    data = request.json or {}
    conn = get_db()
    try:
        for k, v in data.items():
            set_setting(conn, _tenant_id(), k, str(v))
        write_audit(conn, g.ta_user["id"], "system_settings", 0, "update", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/audit-log", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def audit_log_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        if payroll_profiles_active(conn):
            c.execute(
                """
                SELECT a.*, pp.email AS actor_email
                FROM audit_log a
                LEFT JOIN payroll_profiles pp ON pp.user_id = a.actor_user_id
                WHERE a.organization_id = %s
                ORDER BY a.id DESC LIMIT 200
                """,
                (_tenant_id(),),
            )
        else:
            c.execute(
                """
                SELECT a.*, u.email AS actor_email
                FROM audit_log a
                LEFT JOIN ta_users u ON u.id = a.actor_user_id
                WHERE a.organization_id = %s
                ORDER BY a.id DESC LIMIT 200
                """,
                (_tenant_id(),),
            )
        rows = c.fetchall()
        return jsonify([json_safe(r) for r in rows])
    finally:
        conn.close()


@ta_bp.route("/roles", methods=["GET"])
@require_auth
def roles_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT id, code, name FROM roles ORDER BY name")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payment-methods", methods=["GET"])
@require_auth
@require_perm("finance.payments")
def payment_methods_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM payment_methods WHERE active=1 ORDER BY name")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


@ta_bp.route("/payments", methods=["POST"])
@require_auth
@require_perm("finance.payments")
def payments_upsert():
    data = request.json or {}
    for k in ("payroll_cycle_id", "user_id", "payment_status"):
        if data.get(k) is None:
            return jsonify({"error": f"Missing {k}"}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO payroll_payments (payroll_cycle_id, user_id, payment_status, paid_date, payment_method_id, remarks, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              payment_status=VALUES(payment_status),
              paid_date=VALUES(paid_date),
              payment_method_id=VALUES(payment_method_id),
              remarks=VALUES(remarks),
              created_by=VALUES(created_by)
            """,
            (
                int(data["payroll_cycle_id"]),
                int(data["user_id"]),
                data["payment_status"],
                data.get("paid_date"),
                data.get("payment_method_id"),
                data.get("remarks"),
                g.ta_user["id"],
            ),
        )
        write_audit(conn, g.ta_user["id"], "payroll_payment", data["user_id"], "upsert", new=data)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/bag-count", methods=["POST"])
@require_auth
@require_perm("ta.override")
def bag_count_increment():
    data = request.json or {}
    uid = data.get("user_id")
    pc_id = data.get("payroll_cycle_id")
    delta = int(data.get("delta", 1))
    if not uid or not pc_id:
        return jsonify({"error": "user_id and payroll_cycle_id required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM bag_count_summary WHERE user_id=%s AND payroll_cycle_id=%s",
            (int(uid), int(pc_id)),
        )
        row = c.fetchone()
        if row:
            new_c = row["bag_count"] + delta
            c2 = conn.cursor()
            c2.execute(
                "UPDATE bag_count_summary SET bag_count=%s WHERE id=%s",
                (new_c, row["id"]),
            )
        else:
            c2 = conn.cursor()
            c2.execute(
                "INSERT INTO bag_count_summary (user_id, payroll_cycle_id, bag_count) VALUES (%s,%s,%s)",
                (int(uid), int(pc_id), max(0, delta)),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@ta_bp.route("/bag-rates", methods=["GET"])
@require_auth
@require_any_perm("users.edit", "ta.settings")
def bag_rates_list():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT * FROM bag_rate_maintenance ORDER BY effective_from DESC")
        return jsonify([json_safe(r) for r in c.fetchall()])
    finally:
        conn.close()


# --- Admin: payroll period (week anchor + cycle ref prefix) ---


@ta_bp.route("/admin/payroll-period", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def admin_payroll_period_get():
    conn = get_db()
    try:
        row = get_payroll_period_settings(conn, _tenant_id())
        if not row:
            return jsonify(
                {
                    "week_starts_on": 0,
                    "ref_prefix": "PC",
                    "note": "Run organizations_multitenancy_v1.sql (payroll_period_settings per org).",
                }
            )
        return jsonify(json_safe(row))
    finally:
        conn.close()


@ta_bp.route("/admin/payroll-period", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def admin_payroll_period_put():
    data = request.json or {}
    ws = data.get("week_starts_on", 0)
    try:
        ws = int(ws)
    except (TypeError, ValueError):
        return jsonify({"error": "week_starts_on must be 0-6"}), 400
    if ws < 0 or ws > 6:
        return jsonify({"error": "week_starts_on must be 0-6 (Mon-Sun)"}), 400
    prefix = (data.get("ref_prefix") or "PC").strip()[:16] or "PC"
    conn = get_db()
    try:
        set_payroll_period_settings(conn, _tenant_id(), ws, prefix)
        conn.commit()
        return jsonify({"ok": True, "week_starts_on": ws, "ref_prefix": prefix})
    finally:
        conn.close()


# --- Admin: role ↔ permission matrix (Washpro TA permissions catalog) ---


@ta_bp.route("/admin/permission-matrix", methods=["GET"])
@require_auth
@require_perm("ta.settings")
def admin_permission_matrix():
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT id, perm_key, description FROM permissions ORDER BY perm_key")
        perms = c.fetchall()
        c.execute("SELECT id, code, name FROM roles ORDER BY code")
        roles = c.fetchall()
        c.execute(
            """
            SELECT rp.role_id, p.perm_key
            FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            """
        )
        role_map = {}
        for row in c.fetchall():
            role_map.setdefault(row["role_id"], []).append(row["perm_key"])
        return jsonify(
            {
                "permissions": [json_safe(x) for x in perms],
                "roles": [json_safe(x) for x in roles],
                "role_permissions": {str(k): v for k, v in role_map.items()},
            }
        )
    finally:
        conn.close()


@ta_bp.route("/admin/roles/<int:role_id>/permissions", methods=["PUT"])
@require_auth
@require_perm("ta.settings")
def admin_role_permissions_put(role_id):
    data = request.json or {}
    keys = data.get("permission_keys")
    if not isinstance(keys, list):
        return jsonify({"error": "permission_keys array required"}), 400
    conn = get_db()
    try:
        c = conn.cursor(dictionary=True)
        c.execute("SELECT id FROM roles WHERE id=%s", (role_id,))
        if not c.fetchone():
            return jsonify({"error": "Role not found"}), 404
        c2 = conn.cursor()
        c2.execute("DELETE FROM role_permissions WHERE role_id=%s", (role_id,))
        for key in keys:
            c.execute("SELECT id FROM permissions WHERE perm_key=%s", (key,))
            prow = c.fetchone()
            if prow:
                c2.execute(
                    "INSERT IGNORE INTO role_permissions (role_id, permission_id) VALUES (%s,%s)",
                    (role_id, prow["id"]),
                )
        write_audit(
            conn,
            g.ta_user["id"],
            "role_permissions",
            role_id,
            "replace",
            new={"permission_keys": keys},
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


def register_ta_routes(app):
    app.register_blueprint(ta_bp, url_prefix="/api/ta")
