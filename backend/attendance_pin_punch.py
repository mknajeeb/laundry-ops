"""
Stateless attendance kiosk: org slug + 4-digit PIN → clock in/out on shift_sessions.
No auth_sessions; does not return Bearer tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from flask import Request, request

from backend.db import get_db
from backend.hr_compliance import clock_in_blocked_by_expired_documents
from backend.payroll_identity import eastern_now_naive, payroll_profiles_active
from backend.ta_helpers import as_bool, hash_password, table_exists, table_has_column, verify_password

logger = logging.getLogger(__name__)

INVALID_PIN_MESSAGE = "Invalid PIN. Please try again."
KIOSK_DISABLED_MESSAGE = "Attendance kiosk is not enabled for this company."
COMPLIANCE_BLOCK_MESSAGE = "Clock-in not allowed. Please contact manager."
OPEN_BREAK_MESSAGE = "Please end your break before clocking out."

PIN_LEN_KIOSK = 4
RATE_LIMIT_WINDOW_MINUTES = 15
RATE_LIMIT_MAX_FAILURES = 10

ADMIN_ROLE_CODES = frozenset({"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def get_request_ip(req: Optional[Request] = None) -> str:
    r = req or request
    xff = (r.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if xff:
        return xff[:64]
    return (r.remote_addr or "unknown")[:64]


def ensure_auth_pin_attempts_table(conn) -> bool:
    c = conn.cursor()
    if table_exists(c, "auth_pin_attempts"):
        return True
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_pin_attempts (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              ip_address VARCHAR(64) NULL,
              user_id INT NULL,
              success TINYINT(1) NOT NULL DEFAULT 0,
              action VARCHAR(32) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_pin_attempts_org_ip_created (organization_id, ip_address, created_at),
              KEY idx_pin_attempts_org_created (organization_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.commit()
        return True
    except Exception:
        logger.exception("ensure_auth_pin_attempts_table failed")
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def record_pin_attempt(
    conn,
    organization_id: int,
    ip_address: str,
    success: bool,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
) -> None:
    if not ensure_auth_pin_attempts_table(conn):
        return
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO auth_pin_attempts (organization_id, ip_address, user_id, success, action)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (int(organization_id), ip_address[:64] if ip_address else None, user_id, 1 if success else 0, action),
    )


def is_rate_limited(conn, organization_id: int, ip_address: str) -> bool:
    if not ensure_auth_pin_attempts_table(conn):
        return False
    since = datetime.utcnow() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*) FROM auth_pin_attempts
        WHERE organization_id = %s
          AND (ip_address = %s OR (%s IS NULL AND ip_address IS NULL))
          AND success = 0
          AND created_at >= %s
        """,
        (int(organization_id), ip_address, ip_address, since),
    )
    row = c.fetchone()
    n = int(row[0]) if row else 0
    return n >= RATE_LIMIT_MAX_FAILURES


def _employee_display_name(row: dict) -> str:
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    if first or last:
        return f"{first} {last}".strip()
    return (row.get("display_name") or row.get("username") or "Employee").strip()


def _employee_first_name(row: dict) -> str:
    first = (row.get("first_name") or "").strip()
    if first:
        return first
    full = _employee_display_name(row)
    return full.split()[0] if full else "there"


def _format_clock_time_est(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None):
                dt = dt.replace(tzinfo=None)
        except Exception:
            return str(dt)
    try:
        return dt.strftime("%-I:%M %p")
    except ValueError:
        h = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h}:{dt.minute:02d} {ampm}"


def fetch_organization_by_slug(conn, org_slug: str) -> Optional[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "organizations"):
        return None
    c.execute(
        """
        SELECT id, slug, display_name, active
        FROM organizations
        WHERE LOWER(slug) = %s AND active = 1
        LIMIT 1
        """,
        (org_slug,),
    )
    return c.fetchone()


def list_organizations_for_attendance(conn) -> list[dict]:
    c = conn.cursor(dictionary=True)
    if not table_exists(c, "organizations"):
        return []
    if table_has_column(c, "organizations", "logo_url"):
        c.execute(
            """
            SELECT id, slug, display_name, logo_url
            FROM organizations
            WHERE active = 1
            ORDER BY display_name ASC, slug ASC
            """
        )
    else:
        c.execute(
            """
            SELECT id, slug, display_name
            FROM organizations
            WHERE active = 1
            ORDER BY display_name ASC, slug ASC
            """
        )
    return c.fetchall() or []


def shared_device_attendance_enabled(conn, organization_id: int) -> bool:
    from backend.ta_routes import load_clock_payroll_ui

    ui = load_clock_payroll_ui(conn, int(organization_id))
    return as_bool((ui.get("clock") or {}).get("shared_device_attendance"), False)


def resolve_user_by_attendance_pin(
    conn, organization_id: int, pin: str, fetch_roles_fn
) -> Optional[dict]:
    """Return matched user row dict or None. Excludes admin roles."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT u.id, u.username, u.display_name, u.active, u.organization_id,
               pp.attendance_pin_hash, pp.first_name, pp.last_name,
               pp.termination_date
        FROM payroll_profiles pp
        INNER JOIN users u ON u.id = pp.user_id
        WHERE u.organization_id = %s
          AND u.active = 1
          AND pp.attendance_pin_hash IS NOT NULL
        """,
        (int(organization_id),),
    )
    rows = c.fetchall() or []
    matched = None
    for row in rows:
        h = row.get("attendance_pin_hash")
        if not h or not verify_password(str(h), pin):
            continue
        roles = fetch_roles_fn(c, row["id"])
        rs = {str(r).upper() for r in roles}
        if rs & ADMIN_ROLE_CODES:
            continue
        if row.get("termination_date"):
            continue
        if matched is not None:
            logger.warning(
                "duplicate attendance PIN match org=%s users=%s,%s",
                organization_id,
                matched["id"],
                row["id"],
            )
            return None
        matched = row
        matched["_roles"] = roles
    return matched


def _active_shift(conn, user_id: int) -> Optional[dict]:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM shift_sessions
        WHERE user_id=%s AND status='active'
        ORDER BY id DESC LIMIT 1
        """,
        (int(user_id),),
    )
    return c.fetchone()


def kiosk_clock_in(conn, user_id: int, organization_id: int) -> tuple[Optional[dict], Optional[str], int]:
    """Returns (session_row, error_message, http_status)."""
    from backend.ta_routes import (
        effective_clock_geofences,
        fetch_user_row,
        get_or_create_payroll_cycle,
        table_has_column,
        write_audit,
        _tenant_fallback_geofence_id,
    )

    u = fetch_user_row(conn, user_id)
    if not u or not u.get("active"):
        return None, INVALID_PIN_MESSAGE, 401
    if u.get("termination_date"):
        return None, INVALID_PIN_MESSAGE, 401

    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT id FROM shift_sessions WHERE user_id=%s AND status='active'",
        (user_id,),
    )
    if c.fetchone():
        return None, "Already clocked in", 400

    if clock_in_blocked_by_expired_documents(conn, user_id, organization_id):
        return None, COMPLIANCE_BLOCK_MESSAGE, 403

    gfs = effective_clock_geofences(conn, user_id, organization_id)
    geofence_id_for_session = None
    if gfs:
        geofence_id_for_session = int(gfs[0]["id"])
    else:
        fid = _tenant_fallback_geofence_id(conn, organization_id)
        if not fid:
            logger.error("pin punch clock-in: no geofence org=%s", organization_id)
            return None, KIOSK_DISABLED_MESSAGE, 503
        geofence_id_for_session = fid

    c.execute(
        """
        SELECT employment_category_id FROM user_employment_categories
        WHERE user_id=%s AND effective_from <= CURDATE()
          AND (effective_to IS NULL OR effective_to >= CURDATE())
        ORDER BY effective_from DESC LIMIT 1
        """,
        (user_id,),
    )
    row = c.fetchone()
    employment_category_id = row["employment_category_id"] if row else None

    now = eastern_now_naive()
    pc_id = get_or_create_payroll_cycle(conn, now, organization_id)

    chk = conn.cursor()
    has_plb = table_has_column(chk, "shift_sessions", "personal_laundry_bags")
    plb_val = 0 if has_plb else None

    c2 = conn.cursor()
    if has_plb:
        c2.execute(
            """
            INSERT INTO shift_sessions (
              user_id, organization_id, payroll_cycle_id, geofence_id, employment_category_id,
              clock_in_at, clock_in_lat, clock_in_lng, status, personal_laundry_bags
            ) VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,'active',%s)
            """,
            (
                user_id,
                organization_id,
                pc_id,
                geofence_id_for_session,
                employment_category_id,
                now,
                plb_val,
            ),
        )
    else:
        c2.execute(
            """
            INSERT INTO shift_sessions (
              user_id, organization_id, payroll_cycle_id, geofence_id, employment_category_id,
              clock_in_at, clock_in_lat, clock_in_lng, status
            ) VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,'active')
            """,
            (
                user_id,
                organization_id,
                pc_id,
                geofence_id_for_session,
                employment_category_id,
                now,
            ),
        )
    sid = c2.lastrowid
    write_audit(
        conn,
        user_id,
        "shift_session",
        sid,
        "pin_clock_in",
        new={"clock_in_at": now.isoformat(), "geofence_id": geofence_id_for_session},
        organization_id=organization_id,
    )
    from backend.ta_routes import fetch_session

    return fetch_session(conn, sid), None, 201


def kiosk_clock_out(conn, user_id: int, organization_id: int) -> tuple[Optional[dict], Optional[str], int]:
    from backend.ta_routes import (
        fetch_session,
        get_open_break,
        sum_break_seconds,
        write_audit,
        _parse_mysql_dt,
    )

    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM shift_sessions
        WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1
        """,
        (user_id,),
    )
    sess = c.fetchone()
    if not sess:
        return None, "No active session", 400

    if get_open_break(conn, sess["id"]):
        return None, OPEN_BREAK_MESSAGE, 403

    br = sum_break_seconds(conn, sess["id"])
    now = eastern_now_naive()
    clock_in = _parse_mysql_dt(sess.get("clock_in_at"))
    if not clock_in:
        return None, "Invalid session", 500
    elapsed = (now - clock_in).total_seconds()
    net = int(elapsed) - br

    c2 = conn.cursor()
    c2.execute(
        """
        UPDATE shift_sessions
        SET clock_out_at=%s, clock_out_lat=NULL, clock_out_lng=NULL,
            status='completed', total_break_seconds=%s, net_work_seconds=%s
        WHERE id=%s
        """,
        (now, br, net, sess["id"]),
    )
    write_audit(
        conn,
        user_id,
        "shift_session",
        sess["id"],
        "pin_clock_out",
        old={"session_id": sess["id"]},
        new={"clock_out_at": now.isoformat(), "net_work_seconds": net},
        organization_id=organization_id,
    )
    return fetch_session(conn, sess["id"]), None, 200


def build_success_payload(
    user_row: dict, action: str, session_row: dict
) -> dict[str, Any]:
    name = _employee_display_name(user_row)
    first = _employee_first_name(user_row)
    now = eastern_now_naive()
    if action == "CLOCK_IN":
        clocked_at = session_row.get("clock_in_at") or now
        message = f"You are clocked in. Have a great shift, {first}."
    else:
        clocked_at = session_row.get("clock_out_at") or now
        t = _format_clock_time_est(clocked_at)
        message = f"You are clocked out. Shift ended at {t}."
    return {
        "ok": True,
        "employee_name": name,
        "employee_first_name": first,
        "action": action,
        "clocked_at": clocked_at.isoformat() if hasattr(clocked_at, "isoformat") else str(clocked_at),
        "message": message,
        "session_id": session_row.get("id"),
    }


def perform_pin_punch(
    conn,
    organization_slug: str,
    pin: str,
    fetch_roles_fn,
    ip_address: str,
) -> tuple[dict, int]:
    """
    Main entry. Returns (json_body, http_status).
    Never includes token or employee name on failure.
    """
    org_slug = (organization_slug or "").strip().lower()
    pin_clean = str(pin or "").strip()

    if not org_slug or not pin_clean:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400
    if not pin_clean.isdigit() or len(pin_clean) != PIN_LEN_KIOSK:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 400

    if not payroll_profiles_active(conn):
        return {"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503

    org = fetch_organization_by_slug(conn, org_slug)
    if not org:
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    org_id = int(org["id"])

    if not shared_device_attendance_enabled(conn, org_id):
        return {"ok": False, "error": KIOSK_DISABLED_MESSAGE}, 503

    if is_rate_limited(conn, org_id, ip_address):
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 429

    matched = resolve_user_by_attendance_pin(conn, org_id, pin_clean, fetch_roles_fn)
    if not matched:
        record_pin_attempt(conn, org_id, ip_address, success=False, action="pin_punch_fail")
        conn.commit()
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 401

    user_id = int(matched["id"])
    active = _active_shift(conn, user_id)

    try:
        if active:
            sess, err, status = kiosk_clock_out(conn, user_id, org_id)
            action = "CLOCK_OUT"
        else:
            sess, err, status = kiosk_clock_in(conn, user_id, org_id)
            action = "CLOCK_IN"

        if err:
            record_pin_attempt(
                conn, org_id, ip_address, success=False, user_id=user_id, action=action
            )
            conn.commit()
            if err == INVALID_PIN_MESSAGE:
                return {"ok": False, "error": INVALID_PIN_MESSAGE}, status
            return {"ok": False, "error": err}, status

        record_pin_attempt(
            conn, org_id, ip_address, success=True, user_id=user_id, action=action
        )
        conn.commit()
        body = build_success_payload(matched, action, sess or {})
        return body, 200
    except Exception:
        logger.exception("pin punch failed user=%s org=%s", user_id, org_id)
        try:
            conn.rollback()
        except Exception:
            pass
        record_pin_attempt(conn, org_id, ip_address, success=False, user_id=user_id)
        try:
            conn.commit()
        except Exception:
            pass
        return {"ok": False, "error": INVALID_PIN_MESSAGE}, 500


def pin_already_used_in_org(conn, organization_id: int, pin: str, exclude_user_id: int) -> bool:
    """True if another user in the org already has this PIN (for admin set validation tests)."""
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pp.user_id, pp.attendance_pin_hash
        FROM payroll_profiles pp
        JOIN users u ON u.id = pp.user_id
        WHERE u.organization_id = %s AND pp.user_id != %s AND pp.attendance_pin_hash IS NOT NULL
        """,
        (int(organization_id), int(exclude_user_id)),
    )
    for ow in c.fetchall() or []:
        h = ow.get("attendance_pin_hash")
        if h and verify_password(str(h), pin):
            return True
    return False
