import os
import re
import math
import uuid
import base64
import json
import hashlib
import secrets
import pandas as pd
from datetime import datetime, date, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash
from urllib.parse import urlparse
from pathlib import Path

# Load repo-root `.env` first so Flask sees the same vars no matter the process cwd (e.g. `RINSE_BAG_EXPORT_ENABLED`
# must live here for local admin Rinse routes — not only in `scripts/rinse-cleanertickets/.env`, which Node uses).
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

try:
    from azure.storage.blob import (
        BlobServiceClient,
        BlobSasPermissions,
        ContentSettings,
        generate_blob_sas,
    )
except Exception:
    BlobServiceClient = None
    BlobSasPermissions = None
    ContentSettings = None
    generate_blob_sas = None

from etl.transform_orders import transform_orders

from backend.db import get_db
from backend.org_branding_urls import rewrite_org_logo_url_for_client
from backend.payroll_identity import (
    ensure_payroll_profile_for_washpro,
    fetch_payroll_profile_row,
    payroll_profiles_active,
)
from backend.ta_helpers import hash_password, json_safe, verify_password
from backend.notification_routes import register_notification_routes
from backend.rinse_export_routes import register_rinse_export_routes
from backend.rinse_folding_routes import register_rinse_folding_routes
from backend.ta_routes import (
    _build_permission_hierarchy,
    _sanitize_role_code,
    effective_washpro_permission_keys,
    register_ta_routes,
    write_audit,
)
from backend.daily_reset_scheduler import start_daily_reset_scheduler
from backend.ops_ui_flags import get_ops_ui_flags, put_ops_ui_flags


# ---------------------------------------------------
# Flask App Setup
# ---------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-for-production")


def _cors_max_age_sec() -> int:
    """Cache CORS preflight in browsers (cuts OPTIONS+XHR pairs for repeated API polls)."""
    try:
        n = int((os.getenv("CORS_MAX_AGE_SEC") or "600").strip())
    except ValueError:
        n = 600
    return max(0, min(86400, n))


def _cors_origins_config():
    """
    Comma-separated list in CORS_ALLOWED_ORIGINS (or CORS_ORIGINS), e.g.
    https://zealous-bay-0fb502610.4.azurestaticapps.net,http://localhost:5173
    If unset, allow all origins (may fail in some browsers when the API errors before Flask runs).
    """
    raw = (os.getenv("CORS_ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS") or "").strip()
    if not raw:
        return "*"
    parts = [o.strip() for o in raw.split(",") if o.strip()]
    return parts if parts else "*"


CORS(
    app,
    resources={r"/*": {"origins": _cors_origins_config()}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    max_age=_cors_max_age_sec(),
)

register_ta_routes(app)
register_notification_routes(app)
register_rinse_export_routes(app)

start_daily_reset_scheduler(app)


@app.route("/health", methods=["GET"])
def health():
    """Liveness probe; does not touch the database."""
    return jsonify({"status": "ok"}), 200


def _trigger_daily_operational_reset_if_needed(conn, tenant_oid: int):
    """Lazy catch-up on first tenant API hit after a new Eastern day (trigger=lazy only; midnight job is embedded)."""
    try:
        from backend.checkout_history import maybe_run_daily_operational_reset

        return maybe_run_daily_operational_reset(conn, int(tenant_oid))
    except Exception as e:
        app.logger.exception("daily_operational_reset failed: %s", e)
        return None


@app.route("/internal/jobs/daily-operational-reset", methods=["POST"])
def internal_daily_operational_reset_job():
    """
    Manual / cloud-cron trigger: same pass as the embedded 00:05 America/New_York scheduler
    (all tenants with daily reset enabled). Secure with DAILY_OPERATIONAL_RESET_CRON_SECRET
    and header X-Daily-Operational-Reset-Cron-Secret. Optional if you rely only on the embedded job.
    """
    secret = (os.getenv("DAILY_OPERATIONAL_RESET_CRON_SECRET") or "").strip()
    if not secret:
        return jsonify({"error": "DAILY_OPERATIONAL_RESET_CRON_SECRET is not configured"}), 503
    if (request.headers.get("X-Daily-Operational-Reset-Cron-Secret") or "").strip() != secret:
        return jsonify({"error": "forbidden"}), 403
    from backend.checkout_history import run_daily_operational_reset_scheduled_pass

    conn = get_db()
    try:
        out = run_daily_operational_reset_scheduled_pass(conn)
        return jsonify(out)
    finally:
        conn.close()


@app.route("/internal/jobs/change-jobs", methods=["POST"])
def internal_run_change_jobs():
    """
    Run batch jobs (document compliance reminders, status updates, optional profile deactivation).
    Secure with env CHANGE_JOBS_SECRET and header X-Change-Jobs-Secret on POST.
    Query dry_run=1 to simulate without writes or push.
    """
    from backend.hr_compliance import run_document_compliance_tick

    secret = (os.getenv("CHANGE_JOBS_SECRET") or "").strip()
    if not secret:
        return jsonify({"error": "CHANGE_JOBS_SECRET is not configured"}), 503
    if (request.headers.get("X-Change-Jobs-Secret") or "").strip() != secret:
        return jsonify({"error": "forbidden"}), 403
    dry = (request.args.get("dry_run") or "").strip().lower() in ("1", "true", "yes")
    conn = get_db()
    try:
        out = run_document_compliance_tick(conn, dry_run=dry)
        return jsonify(out)
    finally:
        conn.close()


# Local org logo uploads when Azure Blob is not configured (dev / small deployments).
_ORG_LOGO_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.(png|jpg|jpeg|webp|gif)$", re.I)


def _local_org_logo_root():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "instance", "org_logos"))
    os.makedirs(root, exist_ok=True)
    return root


def _public_api_base_for_uploads():
    """Base URL for saved logo links (browser must reach the Flask host)."""
    b = (os.getenv("PUBLIC_API_BASE") or "").strip().rstrip("/")
    if b:
        return b
    try:
        ru = (request.url_root or "").strip().rstrip("/")
        if ru:
            return ru
    except Exception:
        pass
    return "http://127.0.0.1:8000"


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def parse_date_value(value):

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    value = str(value).strip()

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        pass

    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").date()
    except Exception:
        pass

    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        pass

    raise ValueError(f"Could not parse date: {value}")


def normalize_weight(value):

    if pd.isna(value):
        return None

    try:
        return round(float(value), 2)
    except Exception:
        return None


def build_fingerprint(name_clean, weight_num, service_type):

    name_part = (name_clean or "").strip().upper()
    weight_part = "" if weight_num is None else f"{round(float(weight_num), 2):.2f}"
    service_part = (service_type or "").strip().upper()

    return f"{name_part}|{weight_part}|{service_part}"


def normalize_name(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().split())


def normalize_measure_by_service(weight_num, service_type):
    service = (service_type or "").strip().upper()
    if weight_num is None:
        # For HD, blank and 0 are operationally treated the same.
        return "0" if service == "HD" else ""

    try:
        n = float(weight_num)
    except Exception:
        return ""

    if service == "HD":
        return str(int(round(n)))

    return f"{round(n, 2):.2f}"


def normalize_date_key(date_value):
    if date_value is None or date_value == "":
        return ""
    if isinstance(date_value, datetime):
        return date_value.date().isoformat()
    if isinstance(date_value, date):
        return date_value.isoformat()
    try:
        return parse_date_value(date_value).isoformat()
    except Exception:
        return str(date_value).strip()


def build_identity_key(name_clean, weight_num, service_type, date_clean):
    return "|".join([
        normalize_name(name_clean),
        normalize_measure_by_service(weight_num, service_type),
        (service_type or "").strip().upper(),
        normalize_date_key(date_clean)
    ])


def haversine_meters(lat1, lon1, lat2, lon2):
    radius_m = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_m * c


def payroll_cycle_for(dt_value):
    if isinstance(dt_value, datetime):
        d = dt_value.date()
    elif isinstance(dt_value, date):
        d = dt_value
    else:
        d = parse_date_value(dt_value)

    week_start = d - timedelta(days=d.weekday())  # Monday
    week_end = week_start + timedelta(days=6)     # Sunday
    week_num = int(week_start.strftime("%W")) + 1
    cycle_code = f"{week_start.year}-W{week_num:02d}"
    return {
        "cycle_code": cycle_code,
        "week_start": week_start,
        "week_end": week_end,
        "week_num": week_num,
    }


def ensure_attendance_monitor_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_discrepancies (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT NOT NULL,
            discrepancy_type VARCHAR(60) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
            start_time DATETIME NOT NULL,
            end_time DATETIME NULL,
            duration_minutes INT NULL,
            payroll_cycle_code VARCHAR(20) NULL,
            payroll_week_start DATE NULL,
            payroll_week_end DATE NULL,
            last_exit_time DATETIME NULL,
            resolution_action VARCHAR(60) NULL,
            notes VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL,
            INDEX idx_att_dis_emp (employee_id),
            INDEX idx_att_dis_status (status),
            INDEX idx_att_dis_cycle (payroll_cycle_code)
        )
    """)


def resolve_employee_for_user(cursor, user_row):
    if not user_row:
        return None

    # Optional explicit mapping if column exists.
    if table_has_column(cursor, "users", "employee_id"):
        cursor.execute(
            """
            SELECT u.employee_id
            FROM users u
            WHERE u.id = %s
            LIMIT 1
            """,
            (user_row["user_id"],)
        )
        mapped = cursor.fetchone()
        if mapped and mapped.get("employee_id"):
            cursor.execute(
                """
                SELECT id, name
                FROM employees
                WHERE id = %s
                LIMIT 1
                """,
                (int(mapped["employee_id"]),)
            )
            emp = cursor.fetchone()
            if emp:
                return emp

    # Fallback: display_name -> employees.name exact match.
    display_name = (user_row.get("display_name") or "").strip()
    username = (user_row.get("username") or "").strip()
    names_to_try = [n for n in [display_name, username] if n]

    for nm in names_to_try:
        cursor.execute(
            """
            SELECT id, name
            FROM employees
            WHERE UPPER(TRIM(name)) = UPPER(TRIM(%s))
            AND active = TRUE
            ORDER BY id
            LIMIT 1
            """,
            (nm,)
        )
        emp = cursor.fetchone()
        if emp:
            return emp

    # Fallback: first+last token prefix match for names like
    # "Gloria Hoyos" -> "Gloria Hoyos Aguilar".
    for nm in names_to_try:
        parts = [p for p in nm.split() if p]
        if len(parts) >= 2:
            first_last = f"{parts[0]} {parts[1]}"
            cursor.execute(
                """
                SELECT id, name
                FROM employees
                WHERE UPPER(TRIM(name)) LIKE CONCAT(UPPER(TRIM(%s)), '%%')
                AND active = TRUE
                ORDER BY id
                LIMIT 1
                """,
                (first_last,)
            )
            emp = cursor.fetchone()
            if emp:
                return emp

    return None


def ensure_employee_profiles_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee_profiles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            employee_id INT NULL,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(120) NOT NULL,
            employment_type VARCHAR(30) NOT NULL DEFAULT 'WASHPRO_W2',
            address_line1 VARCHAR(255) NULL,
            address_line2 VARCHAR(255) NULL,
            city VARCHAR(100) NULL,
            state VARCHAR(50) NULL,
            zip_code VARCHAR(20) NULL,
            tax_id_type VARCHAR(10) NULL,
            tax_id_value VARCHAR(30) NULL,
            pay_rate DECIMAL(10,2) NULL DEFAULT 0,
            overtime_rate DECIMAL(10,2) NULL DEFAULT 0,
            spread_of_time_rate DECIMAL(10,2) NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL,
            UNIQUE KEY uq_employee_profiles_emp_id (employee_id),
            INDEX idx_employee_profiles_name (last_name, first_name),
            INDEX idx_employee_profiles_type (employment_type)
        )
    """)

    # Backward-compatible schema upgrades if table existed with older shape.
    if not table_has_column(cursor, "employee_profiles", "employee_id"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN employee_id INT NULL")
    if not table_has_column(cursor, "employee_profiles", "first_name"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN first_name VARCHAR(100) NOT NULL DEFAULT ''")
    if not table_has_column(cursor, "employee_profiles", "last_name"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN last_name VARCHAR(120) NOT NULL DEFAULT ''")
    if not table_has_column(cursor, "employee_profiles", "employment_type"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN employment_type VARCHAR(30) NOT NULL DEFAULT 'WASHPRO_W2'")
    if not table_has_column(cursor, "employee_profiles", "address_line1"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN address_line1 VARCHAR(255) NULL")
    if not table_has_column(cursor, "employee_profiles", "address_line2"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN address_line2 VARCHAR(255) NULL")
    if not table_has_column(cursor, "employee_profiles", "city"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN city VARCHAR(100) NULL")
    if not table_has_column(cursor, "employee_profiles", "state"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN state VARCHAR(50) NULL")
    if not table_has_column(cursor, "employee_profiles", "zip_code"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN zip_code VARCHAR(20) NULL")
    if not table_has_column(cursor, "employee_profiles", "tax_id_type"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN tax_id_type VARCHAR(10) NULL")
    if not table_has_column(cursor, "employee_profiles", "tax_id_value"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN tax_id_value VARCHAR(30) NULL")
    if not table_has_column(cursor, "employee_profiles", "pay_rate"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN pay_rate DECIMAL(10,2) NULL DEFAULT 0")
    if not table_has_column(cursor, "employee_profiles", "overtime_rate"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN overtime_rate DECIMAL(10,2) NULL DEFAULT 0")
    if not table_has_column(cursor, "employee_profiles", "spread_of_time_rate"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN spread_of_time_rate DECIMAL(10,2) NULL DEFAULT 0")
    if not table_has_column(cursor, "employee_profiles", "active"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE")
    if not table_has_column(cursor, "employee_profiles", "created_at"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")
    if not table_has_column(cursor, "employee_profiles", "updated_at"):
        cursor.execute("ALTER TABLE employee_profiles ADD COLUMN updated_at DATETIME NULL")


def fetch_today_events_for_employee(cursor, employee_id):
    cursor.execute(
        """
        SELECT id, event_type, event_time
        FROM attendance_events
        WHERE employee_id = %s
          AND DATE(event_time) = CURDATE()
        ORDER BY event_time ASC, id ASC
        """,
        (employee_id,)
    )
    return cursor.fetchall()


def compute_work_state_from_events(events, now_dt=None):
    now_dt = now_dt or datetime.now()
    total_seconds = 0
    clock_anchor = None
    break_start = None
    is_clocked_in = False
    on_break = False

    for ev in events:
        e_type = (ev.get("event_type") or "").upper()
        e_time = ev.get("event_time")
        if not isinstance(e_time, datetime):
            continue

        if e_type == "CLOCK_IN":
            is_clocked_in = True
            on_break = False
            break_start = None
            clock_anchor = e_time
        elif e_type == "BREAK_START" and is_clocked_in and not on_break:
            if clock_anchor:
                total_seconds += max(0, (e_time - clock_anchor).total_seconds())
            on_break = True
            break_start = e_time
            clock_anchor = None
        elif e_type == "BREAK_END" and is_clocked_in and on_break:
            on_break = False
            break_start = None
            clock_anchor = e_time
        elif e_type == "CLOCK_OUT" and is_clocked_in:
            if not on_break and clock_anchor:
                total_seconds += max(0, (e_time - clock_anchor).total_seconds())
            is_clocked_in = False
            on_break = False
            break_start = None
            clock_anchor = None

    if is_clocked_in and not on_break and clock_anchor:
        total_seconds += max(0, (now_dt - clock_anchor).total_seconds())

    worked_minutes = int(total_seconds // 60)
    return {
        "is_clocked_in": is_clocked_in,
        "on_break": on_break,
        "worked_minutes": worked_minutes,
    }


def close_open_discrepancy(cursor, employee_id, end_time, resolution_action=None, notes=None):
    cursor.execute(
        """
        SELECT id, start_time, notes
        FROM attendance_discrepancies
        WHERE employee_id = %s
          AND status = 'OPEN'
        ORDER BY id DESC
        LIMIT 1
        """,
        (employee_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    start_time = row.get("start_time")
    duration = None
    if isinstance(start_time, datetime) and isinstance(end_time, datetime):
        duration = int(max(0, (end_time - start_time).total_seconds() // 60))

    merged_notes = row.get("notes")
    if notes:
        merged_notes = (f"{merged_notes} | {notes}" if merged_notes else notes)[:255]

    cursor.execute(
        """
        UPDATE attendance_discrepancies
        SET
            status = 'CLOSED',
            end_time = %s,
            duration_minutes = %s,
            resolution_action = %s,
            notes = %s,
            updated_at = NOW()
        WHERE id = %s
        """,
        (end_time, duration, resolution_action, merged_notes, row["id"])
    )
    return row["id"]


def open_exit_discrepancy_if_needed(cursor, employee_id, exit_time, last_exit_time=None):
    cursor.execute(
        """
        SELECT id
        FROM attendance_discrepancies
        WHERE employee_id = %s
          AND status = 'OPEN'
        ORDER BY id DESC
        LIMIT 1
        """,
        (employee_id,)
    )
    if cursor.fetchone():
        return None

    pc = payroll_cycle_for(exit_time)
    cursor.execute(
        """
        INSERT INTO attendance_discrepancies
        (
            employee_id,
            discrepancy_type,
            status,
            start_time,
            payroll_cycle_code,
            payroll_week_start,
            payroll_week_end,
            last_exit_time,
            notes
        )
        VALUES (%s, 'OUTSIDE_GEOFENCE_UNCLOSED', 'OPEN', %s, %s, %s, %s, %s, %s)
        """,
        (
            employee_id,
            exit_time,
            pc["cycle_code"],
            pc["week_start"],
            pc["week_end"],
            last_exit_time,
            "Exited geofence while clocked in without break/clock-out",
        )
    )
    return cursor.lastrowid


def auto_clock_out_stale_users(cursor):
    ensure_attendance_monitor_tables(cursor)

    cursor.execute("""
        SELECT ae.employee_id, ae.event_time AS clock_in_time
        FROM attendance_events ae
        JOIN (
            SELECT employee_id, MAX(id) AS max_id
            FROM attendance_events
            WHERE event_type IN ('CLOCK_IN', 'CLOCK_OUT')
            GROUP BY employee_id
        ) x ON x.max_id = ae.id
        WHERE ae.event_type = 'CLOCK_IN'
          AND DATE(ae.event_time) < CURDATE()
    """)
    stale_rows = cursor.fetchall()
    if not stale_rows:
        return 0

    geofence = fetch_active_geofence(cursor)
    if not geofence:
        return 0

    inserted = 0
    for row in stale_rows:
        employee_id = row["employee_id"]
        clock_in_time = row["clock_in_time"]
        clock_day = clock_in_time.date()
        end_of_day = datetime.combine(clock_day, datetime.max.time()).replace(microsecond=0)

        cursor.execute(
            """
            SELECT MAX(created_at) AS last_exit_time
            FROM geofence_alerts
            WHERE employee_id = %s
              AND transition_type = 'EXIT'
              AND DATE(created_at) = %s
            """,
            (employee_id, clock_day)
        )
        exit_row = cursor.fetchone() or {}
        last_exit_time = exit_row.get("last_exit_time")
        auto_out_time = last_exit_time if isinstance(last_exit_time, datetime) else end_of_day

        cursor.execute(
            """
            SELECT latitude, longitude
            FROM employee_geo_presence
            WHERE employee_id = %s
            LIMIT 1
            """,
            (employee_id,)
        )
        p = cursor.fetchone() or {}
        lat = float(p.get("latitude") or geofence["latitude"])
        lon = float(p.get("longitude") or geofence["longitude"])
        distance_m = haversine_meters(lat, lon, float(geofence["latitude"]), float(geofence["longitude"]))

        cursor.execute(
            """
            INSERT INTO attendance_events
            (
                employee_id,
                event_type,
                event_time,
                device_time,
                latitude,
                longitude,
                within_geofence,
                distance_m,
                geofence_id,
                notes,
                personal_bags
            )
            VALUES (%s, 'CLOCK_OUT', %s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                employee_id,
                auto_out_time,
                auto_out_time.isoformat(),
                lat,
                lon,
                False,
                round(distance_m, 2),
                geofence["id"],
                "AUTO_CLOCK_OUT",
            )
        )

        pc = payroll_cycle_for(clock_day)
        cursor.execute(
            """
            INSERT INTO attendance_discrepancies
            (
                employee_id,
                discrepancy_type,
                status,
                start_time,
                end_time,
                duration_minutes,
                payroll_cycle_code,
                payroll_week_start,
                payroll_week_end,
                last_exit_time,
                resolution_action,
                notes
            )
            VALUES (%s, 'FORGOT_CLOCK_OUT', 'CLOSED', %s, %s, %s, %s, %s, %s, %s, 'AUTO', %s)
            """,
            (
                employee_id,
                clock_in_time,
                auto_out_time,
                int(max(0, (auto_out_time - clock_in_time).total_seconds() // 60)),
                pc["cycle_code"],
                pc["week_start"],
                pc["week_end"],
                last_exit_time,
                f"Auto clock-out at day end; last exit: {last_exit_time.isoformat() if isinstance(last_exit_time, datetime) else 'none'}",
            )
        )

        close_open_discrepancy(cursor, employee_id, auto_out_time, "AUTO_CLOCK_OUT", "Auto closed on stale shift")
        inserted += 1

    return inserted


def fetch_active_geofence(cursor):
    cursor.execute("""
        SELECT
            id,
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_at
        FROM geofence_settings
        WHERE active = TRUE
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
    """)

    geofence = cursor.fetchone()

    if geofence:
        return geofence

    cursor.execute("""
        SELECT
            id,
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_at
        FROM geofence_settings
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
    """)

    return cursor.fetchone()


def sync_maintenance_geofence_to_ta_geofences(
    conn, organization_id: int, label: str, latitude: float, longitude: float, radius_m: int, active: bool
):
    """
    Maintenance → Geofence tab writes `geofence_settings` (legacy, single-tenant).
    Time clock + payroll use `geofences` (per organization_id). Mirror the save so
    clock-in finds a tenant geofence without a separate Attendance setup step.
    """
    c = conn.cursor()
    if not table_exists(c, "geofences") or not table_has_column(c, "geofences", "organization_id"):
        return
    name = (label or "Work site").strip()[:255] or "Work site"
    oid = int(organization_id)
    rad = max(1, int(radius_m))
    act = 1 if active else 0
    desc = "Synced from Maintenance → Geofence tab."
    c.execute(
        "SELECT id FROM geofences WHERE organization_id=%s AND name=%s LIMIT 1",
        (oid, name),
    )
    row = c.fetchone()
    if row:
        gid = int(row[0])
        c.execute(
            """
            UPDATE geofences
            SET latitude=%s, longitude=%s, radius_meters=%s, active=%s, location_description=%s
            WHERE id=%s AND organization_id=%s
            """,
            (latitude, longitude, rad, act, desc, gid, oid),
        )
    else:
        c.execute(
            """
            INSERT INTO geofences (organization_id, name, location_description, latitude, longitude, radius_meters, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (oid, name, desc, latitude, longitude, rad, act),
        )


def get_upload_conflicts_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_conflicts LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_conflicts LIKE 'conflict_id'")
    has_conflict_id = cursor.fetchone()
    if has_conflict_id:
        return "conflict_id"

    raise ValueError("upload_conflicts table must include 'id' or 'conflict_id' primary key")


def get_upload_batches_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_batches LIKE 'batch_id'")
    has_batch_id = cursor.fetchone()
    if has_batch_id:
        return "batch_id"

    raise ValueError("upload_batches table must include 'id' or 'batch_id' primary key")


def get_upload_batch_rows_pk(cursor):
    cursor.execute("SHOW COLUMNS FROM upload_batch_rows LIKE 'id'")
    has_id = cursor.fetchone()
    if has_id:
        return "id"

    cursor.execute("SHOW COLUMNS FROM upload_batch_rows LIKE 'row_id'")
    has_row_id = cursor.fetchone()
    if has_row_id:
        return "row_id"

    raise ValueError("upload_batch_rows table must include 'id' or 'row_id' primary key")


def table_has_column(cursor, table_name, col_name):
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (col_name,))
    return cursor.fetchone() is not None


def table_exists(cursor, table_name):
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def delete_identity_rows(
    cursor,
    table_name,
    rows,
    name_col,
    weight_col,
    service_col,
    date_col,
    organization_id=None,
):
    if not rows:
        return 0

    has_org = (
        organization_id is not None
        and table_has_column(cursor, table_name, "organization_id")
    )
    deleted = 0
    for row in rows:
        sql = f"""
                DELETE FROM {table_name}
                WHERE UPPER(TRIM({name_col})) = UPPER(TRIM(%s))
                  AND {service_col} = %s
                  AND (({weight_col} IS NULL AND %s IS NULL) OR {weight_col} = %s)
                  AND {date_col} = %s
            """
        args = [
            row.get("name_clean"),
            row.get("service_type"),
            row.get("weight_num"),
            row.get("weight_num"),
            row.get("date_clean"),
        ]
        if has_org:
            sql += " AND organization_id = %s"
            args.append(int(organization_id))
        cursor.execute(sql, tuple(args))
        deleted += cursor.rowcount or 0

    return deleted


def get_bearer_token():
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def current_user_from_token(cursor):
    token = get_bearer_token()
    if not token:
        return None

    has_u_org = table_has_column(cursor, "users", "organization_id")
    has_orgs = table_exists(cursor, "organizations")
    if has_u_org and has_orgs:
        logo_sql = _org_logo_select_sql(cursor)
        cursor.execute(
            f"""
            SELECT
                s.id AS session_id,
                s.user_id,
                s.token,
                s.expires_at,
                s.revoked,
                u.username,
                u.display_name,
                u.active,
                u.organization_id,
                o.slug AS organization_slug,
                o.display_name AS organization_name,
                {logo_sql}
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE s.token = %s
            LIMIT 1
            """,
            (token,),
        )
    elif has_u_org:
        cursor.execute("""
            SELECT
                s.id AS session_id,
                s.user_id,
                s.token,
                s.expires_at,
                s.revoked,
                u.username,
                u.display_name,
                u.active,
                u.organization_id,
                NULL AS organization_slug,
                NULL AS organization_name
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = %s
            LIMIT 1
        """, (token,))
    else:
        cursor.execute("""
            SELECT
                s.id AS session_id,
                s.user_id,
                s.token,
                s.expires_at,
                s.revoked,
                u.username,
                u.display_name,
                u.active,
                NULL AS organization_id,
                NULL AS organization_slug,
                NULL AS organization_name
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = %s
            LIMIT 1
        """, (token,))
    row = cursor.fetchone()
    if not row:
        return None
    if row.get("revoked"):
        return None
    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.utcnow():
        return None
    if not as_bool(row.get("active"), default=False):
        return None
    return row


def fetch_user_roles(cursor, user_id):
    cursor.execute("""
        SELECT r.code
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
    """, (user_id,))
    return [str(r["code"]).upper() for r in cursor.fetchall()]


def require_admin(cursor):
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    roles = fetch_user_roles(cursor, me["user_id"])
    rs = {str(r).upper() for r in roles}
    if "ADMIN" not in rs and not (rs & {"SUPER_ADMIN", "PLATFORM_ADMIN"}):
        return None, jsonify({"error": "Forbidden"}), 403
    me["roles"] = roles
    return me, None, None


def require_admin_or_perm(conn, cursor, perm_key: str):
    """
    Tenant ADMIN / SUPER_ADMIN / PLATFORM_ADMIN, OR a Washpro role permission
    (e.g. upload.create for Rinse portal scrape → draft).

    Pass the same MySQL `conn` used for `cursor` — do not rely on `cursor.connection`
    (unset on some mysql.connector cursor types → false 403).
    Permission keys match GET /ta/bootstrap `permissions` (see effective_washpro_permission_keys).
    """
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    roles = fetch_user_roles(cursor, me["user_id"])
    rs = {str(r).upper() for r in roles}
    if "ADMIN" in rs or (rs & {"SUPER_ADMIN", "PLATFORM_ADMIN"}):
        me["roles"] = roles
        return me, None, None
    if conn is None:
        return None, jsonify({"error": "Forbidden"}), 403
    try:
        uid = int(me["user_id"])
    except (TypeError, ValueError):
        return None, jsonify({"error": "Forbidden"}), 403

    if perm_key in effective_washpro_permission_keys(conn, uid):
        me["roles"] = roles
        return me, None, None
    return None, jsonify({"error": "Forbidden"}), 403


TENANT_MODULE_KEYS = frozenset(
    (
        "home",
        "dashboard",
        "orders",
        "checkout",
        "upload",
        "discrepancies",
        "inventory",
        "clock",
        "issues",
        "production",
        "scoreboard",
        "maintenance",
        "people",
        "payroll",
        "organization",
        "permissions",
        "notifications",
    )
)

TENANT_PORTAL_ROLES = frozenset(
    ("ADMIN", "OPS", "FRONT_DESK", "OPERATIONS", "SUPERVISOR", "PAYROLL_ADMIN", "FINANCE")
)


def _role_is_platform_template(meta):
    """Platform role packages use organization_id = 0; legacy rows may have NULL."""
    if not meta:
        return False
    oid = meta.get("organization_id")
    if oid is None:
        return True
    try:
        return int(oid) == 0
    except (TypeError, ValueError):
        return False


def require_super_admin(cursor):
    """Super / platform operator: manage tenants and entitlements (SUPER_ADMIN or legacy PLATFORM_ADMIN)."""
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    roles = fetch_user_roles(cursor, me["user_id"])
    rs = {str(r).upper() for r in roles}
    if "SUPER_ADMIN" not in rs and "PLATFORM_ADMIN" not in rs:
        return None, jsonify({"error": "Forbidden"}), 403
    me["roles"] = roles
    return me, None, None


def _platform_resolve_role_ids(cursor, org_id, role_codes):
    """Resolve Washpro role codes to role ids (platform templates org_id=0 + tenant roles)."""
    codes = []
    seen = set()
    for r in role_codes or []:
        c = str(r).upper().strip()
        if not c or c in seen:
            continue
        seen.add(c)
        codes.append(c)
    if not codes:
        return []
    ph = ",".join(["%s"] * len(codes))
    if table_has_column(cursor, "roles", "organization_id"):
        cursor.execute(
            f"""
            SELECT id, code, organization_id FROM roles
            WHERE UPPER(TRIM(code)) IN ({ph})
              AND (organization_id = 0 OR organization_id = %s)
            ORDER BY organization_id DESC
            """,
            tuple(codes) + (int(org_id),),
        )
        rows = cursor.fetchall() or []
    else:
        cursor.execute(
            f"SELECT id, code FROM roles WHERE UPPER(TRIM(code)) IN ({ph})",
            tuple(codes),
        )
        rows = cursor.fetchall() or []
    pick = {}
    for r in rows:
        k = str(r["code"]).upper().strip()
        if k not in pick:
            pick[k] = int(r["id"])
    missing = [c for c in codes if c not in pick]
    if missing:
        return None
    return [pick[c] for c in codes]


def _tenant_resolve_washpro_role_ids(cursor, org_id, role_codes):
    """
    Map Washpro role codes to role IDs for tenant user create/update.
    Includes platform template roles (organization_id=0) and the tenant org's roles.
    Prefers a tenant row over a template when the same code exists in both.
    Returns (role_ids, None) or (None, missing_codes).
    """
    codes = []
    seen = set()
    for r in role_codes or []:
        c = str(r).upper().strip()
        if not c or c in seen:
            continue
        seen.add(c)
        codes.append(c)
    if not codes:
        return [], None
    ph = ",".join(["%s"] * len(codes))
    if table_has_column(cursor, "roles", "organization_id"):
        cursor.execute(
            f"""
            SELECT id, code, organization_id FROM roles
            WHERE UPPER(TRIM(code)) IN ({ph})
              AND (organization_id = 0 OR organization_id = %s)
            ORDER BY organization_id DESC
            """,
            tuple(codes) + (int(org_id or 1),),
        )
        rows = cursor.fetchall() or []
    else:
        cursor.execute(
            f"SELECT id, code FROM roles WHERE UPPER(TRIM(code)) IN ({ph})",
            tuple(codes),
        )
        rows = cursor.fetchall() or []
    pick = {}
    for r in rows:
        k = str(r["code"]).upper().strip()
        if k not in pick:
            pick[k] = int(r["id"])
    missing = [c for c in codes if c not in pick]
    if missing:
        return None, missing
    return [pick[c] for c in codes], None


def auth_platform_user_bundle(cursor, conn, user_id):
    """Super-admin read model aligned with the unified profile UI."""
    cursor.execute(
        """
        SELECT id, username, display_name, active, organization_id, created_at, updated_at
        FROM users WHERE id=%s LIMIT 1
        """,
        (int(user_id),),
    )
    w = cursor.fetchone()
    if not w:
        return None
    w = dict(w)
    w["roles"] = fetch_user_roles(cursor, user_id)
    out = {
        "washpro": json_safe(w),
        "payroll": None,
        "geofence_ids": [],
        "primary_geofence_id": None,
        "employment_assignments": [],
        "entity_tags": [],
    }
    if payroll_profiles_active(conn):
        pr = fetch_payroll_profile_row(conn, int(user_id))
        if pr:
            pr = dict(pr)
            pr.pop("password_hash", None)
            out["payroll"] = json_safe(pr)
    cursor.execute(
        "SELECT geofence_id, is_primary FROM user_geofences WHERE user_id=%s",
        (int(user_id),),
    )
    gfs = cursor.fetchall() or []
    out["geofence_ids"] = [g["geofence_id"] for g in gfs]
    out["primary_geofence_id"] = next(
        (g["geofence_id"] for g in gfs if g.get("is_primary")), None
    )
    cursor.execute(
        """
        SELECT employment_category_id, effective_from, effective_to
        FROM user_employment_categories WHERE user_id=%s
        """,
        (int(user_id),),
    )
    out["employment_assignments"] = cursor.fetchall() or []
    if table_exists(cursor, "user_entity_tags"):
        cursor.execute(
            """
            SELECT entity_type, entity_key, label
            FROM user_entity_tags
            WHERE user_id=%s
            ORDER BY entity_type, entity_key
            """,
            (int(user_id),),
        )
        out["entity_tags"] = cursor.fetchall() or []
    geo_org = int(w.get("organization_id") or 1)
    if table_exists(cursor, "geofences"):
        cursor.execute(
            """
            SELECT id, name, active FROM geofences
            WHERE organization_id=%s
            ORDER BY name
            """,
            (geo_org,),
        )
        out["geofences_catalog"] = cursor.fetchall() or []
    else:
        out["geofences_catalog"] = []
    if table_exists(cursor, "employment_categories"):
        cursor.execute(
            """
            SELECT id, name FROM employment_categories
            WHERE organization_id=%s
            ORDER BY name
            """,
            (geo_org,),
        )
        out["employment_categories_catalog"] = cursor.fetchall() or []
    else:
        out["employment_categories_catalog"] = []
    if table_has_column(cursor, "roles", "organization_id"):
        cursor.execute(
            """
            SELECT id, code, name FROM roles
            WHERE organization_id IN (0, %s)
            ORDER BY organization_id, name
            """,
            (geo_org,),
        )
        out["roles_catalog"] = cursor.fetchall() or []
    else:
        cursor.execute("SELECT id, code, name FROM roles ORDER BY name")
        out["roles_catalog"] = cursor.fetchall() or []
    return out


def normalize_organization_slug(raw):
    """Match frontend LoginPage slug rules: lowercase [a-z0-9-], max 64."""
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    try:
        from urllib.parse import unquote

        s = unquote(s)
    except Exception:
        pass
    s = re.sub(r"[^a-z0-9-]", "", s)[:64]
    return s


def bootstrap_organization_supporting_rows(cursor, conn, org_id: int, slug: str):
    """Minimum rows so payroll period settings exist per tenant when that table is org-scoped."""
    if table_exists(cursor, "payroll_period_settings") and table_has_column(
        cursor, "payroll_period_settings", "organization_id"
    ):
        prefix = "".join(c for c in (slug or "").upper() if c.isalnum())[:8] or "ORG"
        cursor.execute(
            """
            INSERT IGNORE INTO payroll_period_settings (organization_id, week_starts_on, ref_prefix)
            VALUES (%s, 0, %s)
            """,
            (int(org_id), prefix[:16]),
        )
        conn.commit()


def _default_tenant_modules():
    return {k: True for k in TENANT_MODULE_KEYS}


def load_tenant_modules_map(cursor, org_id):
    """Nav/feature toggles per tenant; empty table means all modules on."""
    if not table_exists(cursor, "tenant_entitlements"):
        return _default_tenant_modules()
    cursor.execute(
        "SELECT module_key, enabled FROM tenant_entitlements WHERE organization_id = %s",
        (int(org_id),),
    )
    rows = cursor.fetchall() or []
    if not rows:
        return _default_tenant_modules()
    out = _default_tenant_modules()
    for row in rows:
        k = str(row.get("module_key") or "").strip()
        if k in TENANT_MODULE_KEYS:
            out[k] = bool(row.get("enabled"))
    return out


def _organizations_public_columns_sql(cursor):
    parts = ["id", "slug", "display_name", "active"]
    if table_has_column(cursor, "organizations", "logo_url"):
        parts.append("logo_url")
    for col in ("address", "phone", "email"):
        if table_has_column(cursor, "organizations", col):
            parts.append(col)
    for col in (
        "employer_legal_name",
        "employer_street",
        "employer_apt",
        "employer_city",
        "employer_state",
        "employer_zip",
        "employer_ein",
    ):
        if table_has_column(cursor, "organizations", col):
            parts.append(col)
    return ", ".join(parts)


def require_user(cursor):
    me = current_user_from_token(cursor)
    if not me:
        return None, jsonify({"error": "Unauthorized"}), 401
    me["roles"] = fetch_user_roles(cursor, me["user_id"])
    return me, None, None


def user_org_id(me):
    """Tenant id for Washpro operational data; aligns with users.organization_id."""
    return int(me.get("organization_id") or 1)


def order_belongs_to_user_org(cursor, order_id, oid):
    if not table_has_column(cursor, "orders_staging", "organization_id"):
        return True
    cursor.execute(
        "SELECT id FROM orders_staging WHERE id = %s AND organization_id = %s LIMIT 1",
        (int(order_id), int(oid)),
    )
    return cursor.fetchone() is not None


def upload_batch_belongs_to_user_org(cursor, batch_id, oid):
    if not table_has_column(cursor, "upload_batches", "organization_id"):
        return True
    pk = get_upload_batches_pk(cursor)
    cursor.execute(
        f"SELECT {pk} AS id FROM upload_batches WHERE {pk} = %s AND organization_id = %s LIMIT 1",
        (int(batch_id), int(oid)),
    )
    return cursor.fetchone() is not None


def _org_logo_select_sql(cursor):
    if table_exists(cursor, "organizations") and table_has_column(cursor, "organizations", "logo_url"):
        return "o.logo_url AS organization_logo_url"
    return "NULL AS organization_logo_url"


def ensure_process_submissions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_process_submissions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL UNIQUE,
            user_id INT NULL,
            username VARCHAR(100) NULL,
            ticket_image_base64 LONGTEXT NULL,
            ticket_file_name VARCHAR(255) NULL,
            ticket_blob_url VARCHAR(1024) NULL,
            ticket_blob_name VARCHAR(512) NULL,
            ticket_storage VARCHAR(20) NULL,
            ticket_size_bytes INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL
        )
    """)
    if not table_has_column(cursor, "order_process_submissions", "order_id"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN order_id INT NOT NULL")
    if not table_has_column(cursor, "order_process_submissions", "user_id"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN user_id INT NULL")
    if not table_has_column(cursor, "order_process_submissions", "username"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN username VARCHAR(100) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_image_base64"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_image_base64 LONGTEXT NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_file_name"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_file_name VARCHAR(255) NULL")
    if not table_has_column(cursor, "order_process_submissions", "created_at"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")
    if not table_has_column(cursor, "order_process_submissions", "updated_at"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN updated_at DATETIME NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_blob_url"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_blob_url VARCHAR(1024) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_blob_name"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_blob_name VARCHAR(512) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_storage"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_storage VARCHAR(20) NULL")
    if not table_has_column(cursor, "order_process_submissions", "ticket_size_bytes"):
        cursor.execute("ALTER TABLE order_process_submissions ADD COLUMN ticket_size_bytes INT NULL")
    cursor.execute("""
        SELECT COUNT(1) AS c
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'order_process_submissions'
          AND INDEX_NAME = 'ux_order_process_submissions_order_id'
    """)
    has_idx = (cursor.fetchone() or {}).get("c", 0)
    if not has_idx:
        cursor.execute("CREATE UNIQUE INDEX ux_order_process_submissions_order_id ON order_process_submissions(order_id)")


def ensure_order_processing_exceptions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_processing_exceptions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL UNIQUE,
            user_id INT NULL,
            username VARCHAR(100) NULL,
            service_type VARCHAR(10) NULL,
            original_measure DECIMAL(8,2) NULL,
            submitted_measure DECIMAL(8,2) NULL,
            difference_measure DECIMAL(8,2) NULL,
            date_clean DATE NULL,
            batch_date DATE NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL
        )
    """)
    if not table_has_column(cursor, "order_processing_exceptions", "order_id"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN order_id INT NOT NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "user_id"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN user_id INT NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "username"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN username VARCHAR(100) NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "service_type"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN service_type VARCHAR(10) NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "original_measure"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN original_measure DECIMAL(8,2) NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "submitted_measure"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN submitted_measure DECIMAL(8,2) NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "difference_measure"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN difference_measure DECIMAL(8,2) NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "date_clean"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN date_clean DATE NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "batch_date"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN batch_date DATE NULL")
    if not table_has_column(cursor, "order_processing_exceptions", "created_at"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")
    if not table_has_column(cursor, "order_processing_exceptions", "updated_at"):
        cursor.execute("ALTER TABLE order_processing_exceptions ADD COLUMN updated_at DATETIME NULL")
    cursor.execute("""
        SELECT COUNT(1) AS c
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'order_processing_exceptions'
          AND INDEX_NAME = 'ux_order_processing_exceptions_order_id'
    """)
    has_idx = (cursor.fetchone() or {}).get("c", 0)
    if not has_idx:
        cursor.execute("CREATE UNIQUE INDEX ux_order_processing_exceptions_order_id ON order_processing_exceptions(order_id)")


def ticket_retention_days():
    try:
        days = int(os.getenv("ORDER_TICKET_RETENTION_DAYS", "60"))
    except Exception:
        days = 60
    return max(1, min(days, 365))


def ticket_storage_mode():
    mode = str(os.getenv("ORDER_TICKET_STORAGE_MODE", "") or "").strip().lower()
    if mode in {"blob", "db"}:
        return mode
    return "blob" if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else "db"


def _blob_container_name():
    return str(os.getenv("ORDER_TICKET_CONTAINER", "order-tickets") or "order-tickets").strip()


def _blob_service_client():
    """
    Return a BlobServiceClient or None. Malformed connection strings (e.g. missing
    AccountName=) must not raise — otherwise every org-logo GET returns 500.
    """
    conn_str = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn_str or BlobServiceClient is None:
        return None
    try:
        return BlobServiceClient.from_connection_string(conn_str)
    except Exception as e:
        try:
            app.logger.warning(
                "AZURE_STORAGE_CONNECTION_STRING is set but invalid (org logos / tickets will skip blob): %s",
                e,
            )
        except Exception:
            pass
        return None


def _ensure_blob_container():
    client = _blob_service_client()
    if client is None:
        return None
    container = _blob_container_name()
    cc = client.get_container_client(container)
    try:
        cc.create_container()
    except Exception:
        pass
    return cc


def _infer_content_type(file_name):
    name = str(file_name or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _blob_name_from_url(url):
    try:
        parsed = urlparse(url or "")
        path = parsed.path or ""
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return None
        # /container/blob/path -> remove container segment
        return "/".join(parts[1:])
    except Exception:
        return None


def save_ticket_image(ticket_image_base64, ticket_file_name, order_id):
    if not ticket_image_base64:
        return None

    data = base64.b64decode(ticket_image_base64)
    size = len(data)

    if ticket_storage_mode() == "blob":
        try:
            cc = _ensure_blob_container()
            if cc is not None:
                now = datetime.utcnow()
                blob_name = f"orders/{now.strftime('%Y/%m/%d')}/{order_id}_{uuid.uuid4().hex}_{ticket_file_name or 'ticket.jpg'}"
                bc = cc.get_blob_client(blob_name)
                kwargs = {}
                if ContentSettings is not None:
                    kwargs["content_settings"] = ContentSettings(content_type=_infer_content_type(ticket_file_name))
                bc.upload_blob(data, overwrite=True, **kwargs)
                return {
                    "ticket_storage": "blob",
                    "ticket_blob_url": bc.url,
                    "ticket_blob_name": blob_name,
                    "ticket_image_base64": None,
                    "ticket_size_bytes": size,
                }
        except Exception:
            # Fallback to DB storage if blob config/upload is unavailable.
            pass

    return {
        "ticket_storage": "db",
        "ticket_blob_url": None,
        "ticket_blob_name": None,
        "ticket_image_base64": ticket_image_base64,
        "ticket_size_bytes": size,
    }


def build_ticket_read_url(blob_name, blob_url):
    if not blob_name:
        return blob_url
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str or generate_blob_sas is None or BlobSasPermissions is None:
        return blob_url
    try:
        client = _blob_service_client()
        if client is None:
            return blob_url
        account_name = client.account_name
        cred = client.credential
        account_key = getattr(cred, "account_key", None)
        if not account_key:
            return blob_url
        token = generate_blob_sas(
            account_name=account_name,
            container_name=_blob_container_name(),
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=30),
        )
        if not token:
            return blob_url
        return f"https://{account_name}.blob.core.windows.net/{_blob_container_name()}/{blob_name}?{token}"
    except Exception:
        return blob_url


def delete_ticket_blob(blob_name=None, blob_url=None):
    cc = _ensure_blob_container()
    if cc is None:
        return
    name = blob_name or _blob_name_from_url(blob_url)
    if not name:
        return
    try:
        cc.get_blob_client(name).delete_blob(delete_snapshots="include")
    except Exception:
        pass


def prune_old_ticket_images(cursor):
    days = ticket_retention_days()
    cursor.execute("""
        SELECT id, ticket_blob_name, ticket_blob_url
        FROM order_process_submissions
        WHERE
            (ticket_image_base64 IS NOT NULL OR ticket_blob_url IS NOT NULL)
            AND COALESCE(updated_at, created_at) < (NOW() - INTERVAL %s DAY)
    """, (days,))
    old_rows = cursor.fetchall() or []
    for r in old_rows:
        delete_ticket_blob(r.get("ticket_blob_name"), r.get("ticket_blob_url"))

    cursor.execute("""
        UPDATE order_process_submissions
        SET
            ticket_image_base64 = NULL,
            ticket_file_name = NULL,
            ticket_blob_url = NULL,
            ticket_blob_name = NULL,
            ticket_storage = NULL,
            ticket_size_bytes = NULL,
            updated_at = NOW()
        WHERE
            (ticket_image_base64 IS NOT NULL OR ticket_blob_url IS NOT NULL)
            AND COALESCE(updated_at, created_at) < (NOW() - INTERVAL %s DAY)
    """, (days,))


def upload_batches_time_col(cursor):
    if table_has_column(cursor, "upload_batches", "created_at"):
        return "created_at"
    if table_has_column(cursor, "upload_batches", "uploaded_at"):
        return "uploaded_at"
    return None


def orders_status_capabilities(cursor):
    return {
        "has_logistics": table_has_column(cursor, "orders_staging", "logistics_status"),
        "has_processing": table_has_column(cursor, "orders_staging", "processing_status"),
        "has_status": table_has_column(cursor, "orders_staging", "status"),
        "has_ticket_id": table_has_column(cursor, "orders_staging", "ticket_id"),
    }


def ensure_ticket_id_columns(cursor):
    if table_exists(cursor, "orders_staging") and not table_has_column(cursor, "orders_staging", "ticket_id"):
        cursor.execute("ALTER TABLE orders_staging ADD COLUMN ticket_id VARCHAR(120) NULL")
    if table_exists(cursor, "orders_final") and not table_has_column(cursor, "orders_final", "ticket_id"):
        cursor.execute("ALTER TABLE orders_final ADD COLUMN ticket_id VARCHAR(120) NULL")


def ensure_upload_batch_rows_ticket_id(cursor):
    """Rinse bag / ticket id on draft upload rows (optional column; added on first use)."""
    if not table_exists(cursor, "upload_batch_rows"):
        return
    if not table_has_column(cursor, "upload_batch_rows", "ticket_id"):
        cursor.execute("ALTER TABLE upload_batch_rows ADD COLUMN ticket_id VARCHAR(120) NULL")


def orders_logistics_select_sql(cap):
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(
                    logistics_status,
                    CASE
                        WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                        WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                        ELSE 'AT_WASHPRO'
                    END
                ) AS logistics_status
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') AS logistics_status"

    if cap["has_status"]:
        return """
            CASE
                WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                ELSE 'AT_WASHPRO'
            END AS logistics_status
        """

    return "'AT_WASHPRO' AS logistics_status"


def orders_processing_select_sql(cap):
    if cap["has_processing"]:
        if cap["has_status"]:
            return """
                COALESCE(
                    processing_status,
                    CASE WHEN status = 'PROCESSED' THEN 'PROCESSED' ELSE 'PENDING' END
                ) AS processing_status
            """
        return "COALESCE(processing_status, 'PENDING') AS processing_status"

    if cap["has_status"]:
        return "CASE WHEN status = 'PROCESSED' THEN 'PROCESSED' ELSE 'PENDING' END AS processing_status"

    return "'PENDING' AS processing_status"


def where_active_at_washpro_sql(cap):
    if cap["has_logistics"]:
        if cap["has_status"]:
            return """
                COALESCE(logistics_status, CASE
                    WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
                    WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
                    ELSE 'AT_WASHPRO'
                END) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
            """
        return "COALESCE(logistics_status, 'AT_WASHPRO') NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')"
    if cap["has_status"]:
        return "status NOT IN ('CHECKED_OUT', 'FORCED_CHECKOUT')"
    return "1 = 1"


def where_not_sent_or_forced_sql(cap):
    return where_active_at_washpro_sql(cap)


# ---------------------------------------------------
# Get Active Orders
# ---------------------------------------------------

@app.route("/orders", methods=["GET"])
def get_orders():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        oid = user_org_id(me)
        _trigger_daily_operational_reset_if_needed(conn, oid)
        cap = orders_status_capabilities(cursor)
        from backend.order_gaming_flow import ensure_order_gaming_flow_columns, gaming_select_fragment

        ensure_order_gaming_flow_columns(cursor)
        gaming_sql = gaming_select_fragment(cursor)
        has_batch_date = table_has_column(cursor, "orders_staging", "batch_date")
        has_created_at = table_has_column(cursor, "orders_staging", "created_at")
        has_rush_type_col = table_has_column(cursor, "orders_staging", "rush_type")
        _date_rush_sql = "CASE WHEN o.date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
        rush_type_sql = (
            f"COALESCE(NULLIF(TRIM(o.rush_type), ''), {_date_rush_sql})"
            if has_rush_type_col
            else _date_rush_sql
        )
        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        active_where = where_active_at_washpro_sql(cap)
        include_all = as_bool(request.args.get("include_all"), default=False)
        where_clause = "1 = 1" if include_all else active_where
        exec_params = []
        if table_has_column(cursor, "orders_staging", "organization_id"):
            where_clause = f"({where_clause}) AND o.organization_id = %s"
            exec_params.append(oid)
        has_submissions = table_exists(cursor, "order_process_submissions")
        submission_select = ""
        submission_join = ""
        if has_submissions:
            has_ops_order_id = table_has_column(cursor, "order_process_submissions", "order_id")
            has_ops_user_id = table_has_column(cursor, "order_process_submissions", "user_id")
            has_ops_username = table_has_column(cursor, "order_process_submissions", "username")
            has_ops_updated_at = table_has_column(cursor, "order_process_submissions", "updated_at")
            has_ops_ticket_blob_url = table_has_column(cursor, "order_process_submissions", "ticket_blob_url")
            has_ops_ticket_b64 = table_has_column(cursor, "order_process_submissions", "ticket_image_base64")
            has_ops_ticket_file_name = table_has_column(cursor, "order_process_submissions", "ticket_file_name")
            has_ops_id = table_has_column(cursor, "order_process_submissions", "id")

            has_ticket_expr_parts = []
            if has_ops_ticket_blob_url:
                has_ticket_expr_parts.append("(ops.ticket_blob_url IS NOT NULL AND ops.ticket_blob_url <> '')")
            if has_ops_ticket_b64:
                has_ticket_expr_parts.append("(ops.ticket_image_base64 IS NOT NULL AND ops.ticket_image_base64 <> '')")
            has_ticket_expr = " OR ".join(has_ticket_expr_parts) if has_ticket_expr_parts else "FALSE"

            if has_ops_order_id:
                submission_select = f"""
                    , {"ops.user_id" if has_ops_user_id else "NULL"} AS processed_by_user_id
                    , {"ops.username" if has_ops_username else "NULL"} AS processed_by_username
                    , {"ops.updated_at" if has_ops_updated_at else "NULL"} AS processed_at
                    , CASE
                        WHEN ({has_ticket_expr})
                        THEN 1 ELSE 0
                      END AS has_ticket_image
                    , {"ops.ticket_file_name" if has_ops_ticket_file_name else "NULL"} AS ticket_file_name
                    , {"ops.id" if has_ops_id else "NULL"} AS ticket_id
                """
                submission_join = "LEFT JOIN order_process_submissions ops ON ops.order_id = o.id"
            else:
                # Keep endpoint stable even if submission table exists but is missing order_id.
                submission_select = """
                    , NULL AS processed_by_user_id
                    , NULL AS processed_by_username
                    , NULL AS processed_at
                    , 0 AS has_ticket_image
                    , NULL AS ticket_file_name
                    , NULL AS ticket_id
                """
                submission_join = ""

        cursor.execute(f"""

            SELECT
                o.id,
                o.date_clean,
                o.name_clean,
                o.weight_num,
                o.service_type,
                {"o.batch_date" if has_batch_date else "NULL"} AS batch_date,
                {"o.ticket_id" if cap["has_ticket_id"] else "NULL"} AS ticket_id,

                {rush_type_sql} AS rush_type,

                {logistics_sql},
                {processing_sql},
                {"o.status" if cap["has_status"] else "NULL"} AS status,
                {"o.created_at" if has_created_at else "NULL"} AS created_at
                {gaming_sql}
                {submission_select}

            FROM orders_staging o
            {submission_join}
            WHERE {where_clause}

            ORDER BY o.date_clean ASC, o.id ASC

        """, tuple(exec_params))

        orders = cursor.fetchall()

        return jsonify(orders)
    except Exception as e:
        # Keep API responses JSON so frontend can surface a useful message.
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


@app.route("/orders/lookup_scan", methods=["POST"])
def orders_lookup_scan_route():
    """Match Rinse QR payload and/or printed name + service type to live staging orders (still at Washpro)."""
    from backend.order_lookup_scan import run_order_lookup_scan

    data = request.get_json(silent=True) or {}
    qr_text = str(data.get("qr_text") or "").strip()
    name_hint = str(data.get("name_hint") or "").strip()
    service_hint = str(data.get("service_hint") or "").strip()
    if not qr_text and not name_hint and not service_hint:
        return jsonify({"error": "Provide qr_text and/or name_hint and/or service_hint"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        active_where = where_active_at_washpro_sql(cap)
        matches = run_order_lookup_scan(cursor, tenant_oid, active_where, cap, data)
        return jsonify({"matches": [json_safe(m) for m in matches]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Checkout Single Order
# ---------------------------------------------------

@app.route("/checkout", methods=["POST"])
def checkout_order():

    data = request.json or {}
    order_id = data.get("order_id")
    employee = (data.get("employee") or "").strip() or "Unknown"

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)

        has_org = table_has_column(cursor, "orders_staging", "organization_id")
        sel_sql = f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                {logistics_sql},
                status
            FROM orders_staging
            WHERE id = %s
        """
        sel_args = [order_id]
        if has_org:
            sel_sql += " AND organization_id = %s"
            sel_args.append(oid)
        cursor.execute(sel_sql, tuple(sel_args))

        order = cursor.fetchone()

        if not order:
            return jsonify({"error": "Order not found"}), 404

        if (order.get("logistics_status") or "").upper() in ["SENT_TO_RINSE", "CHECKED_OUT"]:
            return jsonify({"error": "Order already checked out"}), 409

        cursor.execute("""
            INSERT INTO checkout_log
            (
                order_id,
                name,
                weight,
                service,
                rush_date,
                employee
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            order["id"],
            order["name_clean"],
            order["weight_num"],
            order["service_type"],
            order["date_clean"],
            employee
        ))

        set_parts = []
        if cap["has_logistics"]:
            set_parts.append("logistics_status = 'SENT_TO_RINSE'")
        if cap["has_status"]:
            set_parts.append("status = 'CHECKED_OUT'")
        if not set_parts:
            set_parts.append("status = 'CHECKED_OUT'")

        upd_sql = f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """
        upd_args = [order_id]
        if has_org:
            upd_sql += " AND organization_id = %s"
            upd_args.append(oid)
        cursor.execute(upd_sql, tuple(upd_args))

        conn.commit()
        return jsonify({"status": "checked_out", "order_id": order_id})

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Checkout Bulk Orders
# ---------------------------------------------------

@app.route("/checkout_bulk", methods=["POST"])
def checkout_bulk():

    data = request.json or {}
    order_ids = data.get("order_ids") or []
    employee = (data.get("employee") or "").strip() or "Unknown"

    if not isinstance(order_ids, list) or not order_ids:
        return jsonify({"error": "order_ids must be a non-empty array"}), 400

    # Ensure stable ordering and avoid duplicates
    order_ids = list(dict.fromkeys(order_ids))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)

        format_strings = ",".join(["%s"] * len(order_ids))
        bulk_sql = f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                {logistics_sql},
                status
            FROM orders_staging
            WHERE id IN ({format_strings})
        """
        bulk_args = list(order_ids)
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        if has_staging_org:
            bulk_sql += " AND organization_id = %s"
            bulk_args.append(tenant_oid)
        cursor.execute(bulk_sql, tuple(bulk_args))

        rows = cursor.fetchall()
        rows_by_id = {row["id"]: row for row in rows}

        not_found = []
        already_checked_out = []
        checkout_candidates = []

        for req_id in order_ids:
            row = rows_by_id.get(req_id)

            if not row:
                not_found.append(req_id)
                continue

            if (row.get("logistics_status") or "").upper() in ["SENT_TO_RINSE", "CHECKED_OUT"]:
                already_checked_out.append(req_id)
                continue

            checkout_candidates.append(row)

        for order in checkout_candidates:
            cursor.execute("""
                INSERT INTO checkout_log
                (
                    order_id,
                    name,
                    weight,
                    service,
                    rush_date,
                    employee
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                order["id"],
                order["name_clean"],
                order["weight_num"],
                order["service_type"],
                order["date_clean"],
                employee
            ))

        if checkout_candidates:
            checkout_ids = [row["id"] for row in checkout_candidates]
            update_strings = ",".join(["%s"] * len(checkout_ids))
            set_parts = []
            if cap["has_logistics"]:
                set_parts.append("logistics_status = 'SENT_TO_RINSE'")
            if cap["has_status"]:
                set_parts.append("status = 'CHECKED_OUT'")
            if not set_parts:
                set_parts.append("status = 'CHECKED_OUT'")

            upd_bulk = f"""
                UPDATE orders_staging
                SET {", ".join(set_parts)}
                WHERE id IN ({update_strings})
            """
            upd_bulk_args = list(checkout_ids)
            if has_staging_org:
                upd_bulk += " AND organization_id = %s"
                upd_bulk_args.append(tenant_oid)
            cursor.execute(upd_bulk, tuple(upd_bulk_args))

        conn.commit()

        return jsonify({
            "status": "bulk_checkout_complete",
            "requested": len(order_ids),
            "checked_out": len(checkout_candidates),
            "not_found": not_found,
            "already_checked_out": already_checked_out
        })

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Get Checkout Log
# ---------------------------------------------------

@app.route("/checkout_log", methods=["GET"])
def get_checkout_log():

    checkout_date = (request.args.get("date") or "").strip()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_ticket_id_columns(cursor)
        has_ticket_id = table_has_column(cursor, "orders_staging", "ticket_id")
        tid_sel = ", o.ticket_id" if has_ticket_id else ""
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        join_sql = ""
        if has_staging_org:
            join_sql = "INNER JOIN orders_staging o ON o.id = c.order_id AND o.organization_id = %s"

        if checkout_date:
            if has_staging_org:
                cursor.execute(f"""
                    SELECT
                        c.id,
                        c.order_id,
                        c.name,
                        c.weight,
                        c.service,
                        c.rush_date,
                        c.checkout_time,
                        c.employee
                        {tid_sel}
                    FROM checkout_log c
                    {join_sql}
                    WHERE DATE(c.checkout_time) = %s
                    ORDER BY c.checkout_time DESC, c.id DESC
                """, (tenant_oid, checkout_date))
            else:
                if has_ticket_id:
                    cursor.execute(f"""
                        SELECT
                            c.id,
                            c.order_id,
                            c.name,
                            c.weight,
                            c.service,
                            c.rush_date,
                            c.checkout_time,
                            c.employee,
                            o.ticket_id
                        FROM checkout_log c
                        LEFT JOIN orders_staging o ON o.id = c.order_id
                        WHERE DATE(c.checkout_time) = %s
                        ORDER BY c.checkout_time DESC, c.id DESC
                    """, (checkout_date,))
                else:
                    cursor.execute("""
                        SELECT
                            id,
                            order_id,
                            name,
                            weight,
                            service,
                            rush_date,
                            checkout_time,
                            employee
                        FROM checkout_log
                        WHERE DATE(checkout_time) = %s
                        ORDER BY checkout_time DESC, id DESC
                    """, (checkout_date,))
        else:
            # Default: recent checkouts (not server-today only — that hid undo after midnight / TZ skew).
            if has_staging_org:
                cursor.execute(f"""
                    SELECT
                        c.id,
                        c.order_id,
                        c.name,
                        c.weight,
                        c.service,
                        c.rush_date,
                        c.checkout_time,
                        c.employee
                        {tid_sel}
                    FROM checkout_log c
                    {join_sql}
                    WHERE c.checkout_time >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                    ORDER BY c.checkout_time DESC, c.id DESC
                    LIMIT 200
                """, (tenant_oid,))
            else:
                if has_ticket_id:
                    cursor.execute("""
                        SELECT
                            c.id,
                            c.order_id,
                            c.name,
                            c.weight,
                            c.service,
                            c.rush_date,
                            c.checkout_time,
                            c.employee,
                            o.ticket_id
                        FROM checkout_log c
                        LEFT JOIN orders_staging o ON o.id = c.order_id
                        WHERE c.checkout_time >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                        ORDER BY c.checkout_time DESC, c.id DESC
                        LIMIT 200
                    """)
                else:
                    cursor.execute("""
                        SELECT
                            id,
                            order_id,
                            name,
                            weight,
                            service,
                            rush_date,
                            checkout_time,
                            employee
                        FROM checkout_log
                        WHERE checkout_time >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                        ORDER BY checkout_time DESC, id DESC
                        LIMIT 200
                    """)

        return jsonify(cursor.fetchall())

    finally:

        cursor.close()
        conn.close()


@app.route("/maintenance/daily-operational-reset", methods=["GET", "PUT"])
def daily_operational_reset_maintenance():
    """Admin: enable/disable EST daily archive + clean slate for upload/checkout/staging."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_admin(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        from backend.checkout_history import (
            ensure_checkout_history_schema,
            get_daily_reset_settings,
            set_daily_reset_enabled,
            set_daily_reset_trigger,
        )

        ensure_checkout_history_schema(cursor)
        if request.method == "GET":
            return jsonify(get_daily_reset_settings(cursor, tenant_oid))
        data = request.json or {}
        en = data.get("enabled")
        if en is None and "trigger" not in data:
            return jsonify({"error": "enabled and/or trigger is required"}), 400
        if en is not None:
            set_daily_reset_enabled(cursor, tenant_oid, as_bool(en, False))
        if "trigger" in data:
            set_daily_reset_trigger(cursor, tenant_oid, str(data.get("trigger") or "lazy"))
        conn.commit()
        return jsonify(get_daily_reset_settings(cursor, tenant_oid))
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/ops-ui-flags", methods=["GET", "PUT"])
def maintenance_ops_ui_flags():
    """Tenant: master switches for bag QR scan, browse list, and dryer QR on orders/checkout."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if request.method == "GET":
            return jsonify(get_ops_ui_flags(cursor, tenant_oid))
        _, err_a, code_a = require_admin(cursor)
        if err_a:
            return err_a, code_a
        data = request.json or {}
        put_ops_ui_flags(cursor, tenant_oid, data)
        conn.commit()
        return jsonify(get_ops_ui_flags(cursor, tenant_oid))
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/checkout_history/snapshots", methods=["GET"])
def checkout_history_snapshots_list():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if not table_exists(cursor, "checkout_history_snapshots"):
            return jsonify([])
        cursor.execute(
            """
            SELECT id, organization_id, business_date, archived_at,
                   staging_count, checkout_log_count, upload_batch_count, upload_batch_row_count
            FROM checkout_history_snapshots
            WHERE organization_id=%s
            ORDER BY business_date DESC, id DESC
            LIMIT 120
            """,
            (tenant_oid,),
        )
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/checkout_history/snapshots/<int:snapshot_id>/orders", methods=["GET"])
def checkout_history_snapshot_orders(snapshot_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cursor.execute(
            """
            SELECT id FROM checkout_history_snapshots
            WHERE id=%s AND organization_id=%s
            LIMIT 1
            """,
            (snapshot_id, tenant_oid),
        )
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        cursor.execute(
            """
            SELECT * FROM checkout_history_orders
            WHERE snapshot_id=%s
            ORDER BY id ASC
            """,
            (snapshot_id,),
        )
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/checkout_history/snapshots/<int:snapshot_id>/checkouts", methods=["GET"])
def checkout_history_snapshot_checkouts(snapshot_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cursor.execute(
            """
            SELECT id FROM checkout_history_snapshots
            WHERE id=%s AND organization_id=%s
            LIMIT 1
            """,
            (snapshot_id, tenant_oid),
        )
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        cursor.execute(
            """
            SELECT * FROM checkout_history_checkouts
            WHERE snapshot_id=%s
            ORDER BY checkout_time DESC, id DESC
            """,
            (snapshot_id,),
        )
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Undo Checkout (Mistake Recovery)
# ---------------------------------------------------

@app.route("/checkout_undo", methods=["POST"])
def checkout_undo():

    data = request.json or {}
    order_id = data.get("order_id")

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        cap = orders_status_capabilities(cursor)
        sel_undo = "SELECT id, status FROM orders_staging WHERE id = %s"
        sel_args = [order_id]
        if has_staging_org:
            sel_undo += " AND organization_id = %s"
            sel_args.append(tenant_oid)
        cursor.execute(sel_undo, tuple(sel_args))
        order_row = cursor.fetchone()

        if not order_row:
            return jsonify({"error": "Order not found"}), 404

        cursor.execute("""
            SELECT id
            FROM checkout_log
            WHERE order_id = %s
            ORDER BY checkout_time DESC, id DESC
            LIMIT 1
        """, (order_id,))
        log_row = cursor.fetchone()

        if log_row:
            cursor.execute(
                "DELETE FROM checkout_log WHERE id = %s",
                (log_row["id"],)
            )

        set_parts = []
        if cap["has_logistics"]:
            set_parts.append("logistics_status = 'AT_WASHPRO'")
        if cap["has_status"]:
            set_parts.append("status = 'PROCESSED'")
        if not set_parts:
            set_parts.append("status = 'PROCESSED'")

        upd_undo = f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """
        upd_undo_args = [order_id]
        if has_staging_org:
            upd_undo += " AND organization_id = %s"
            upd_undo_args.append(tenant_oid)
        cursor.execute(upd_undo, tuple(upd_undo_args))

        conn.commit()
        return jsonify({"status": "checkout_undone", "order_id": order_id})

    except Exception as e:

        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Get Final Orders
# ---------------------------------------------------

@app.route("/orders/final", methods=["GET"])
def get_final_orders():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        has_final_org = table_exists(cursor, "orders_final") and table_has_column(
            cursor, "orders_final", "organization_id"
        )
        sql_final = """
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                cleaned_by,
                cleaned_at,
                created_at

            FROM orders_final
        """
        args_final = []
        if has_final_org:
            sql_final += " WHERE organization_id = %s"
            args_final.append(tenant_oid)
        sql_final += " ORDER BY cleaned_at DESC, id DESC"
        cursor.execute(sql_final, tuple(args_final))

        rows = cursor.fetchall()

        return jsonify(rows)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Update Order
# ---------------------------------------------------

@app.route("/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_admin_or_perm(conn, cursor, "orders.update")
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_ticket_id_columns(cursor)
        has_ticket_id = table_has_column(cursor, "orders_staging", "ticket_id")

        sel_sql = """
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type
                {ticket_select}
            FROM orders_staging
            WHERE id = %s
        """.format(ticket_select=", ticket_id" if has_ticket_id else "")
        sel_args = [order_id]
        if table_has_column(cursor, "orders_staging", "organization_id"):
            sel_sql += " AND organization_id = %s"
            sel_args.append(tenant_oid)
        cursor.execute(sel_sql, tuple(sel_args))

        existing = cursor.fetchone()

        if not existing:
            return jsonify({"error": "Order not found"}), 404

        date_clean = (
            parse_date_value(data.get("date_clean"))
            if data.get("date_clean") not in [None, ""]
            else existing["date_clean"]
        )

        name_clean = (
            data.get("name_clean")
            if data.get("name_clean") not in [None, ""]
            else existing["name_clean"]
        )

        weight_num = (
            normalize_weight(data.get("weight_num"))
            if data.get("weight_num") not in [None, ""]
            else existing["weight_num"]
        )

        service_type = (
            data.get("service_type")
            if data.get("service_type") not in [None, ""]
            else existing["service_type"]
        )
        ticket_id = (
            str(data.get("ticket_id")).strip()
            if has_ticket_id and data.get("ticket_id") not in [None, ""]
            else (existing.get("ticket_id") if has_ticket_id else None)
        )
        if has_ticket_id and ticket_id == "":
            ticket_id = None

        if has_ticket_id:
            upd_sql = """
                UPDATE orders_staging
                SET
                    date_clean = %s,
                    name_clean = %s,
                    weight_num = %s,
                    service_type = %s,
                    ticket_id = %s
                WHERE id = %s
            """
            upd_args = [date_clean, name_clean, weight_num, service_type, ticket_id, order_id]
            if table_has_column(cursor, "orders_staging", "organization_id"):
                upd_sql += " AND organization_id = %s"
                upd_args.append(tenant_oid)
            cursor.execute(upd_sql, tuple(upd_args))
        else:
            upd_sql = """
                UPDATE orders_staging
                SET
                    date_clean = %s,
                    name_clean = %s,
                    weight_num = %s,
                    service_type = %s
                WHERE id = %s
            """
            upd_args = [date_clean, name_clean, weight_num, service_type, order_id]
            if table_has_column(cursor, "orders_staging", "organization_id"):
                upd_sql += " AND organization_id = %s"
                upd_args.append(tenant_oid)
            cursor.execute(upd_sql, tuple(upd_args))

        conn.commit()

        return jsonify({"status": "updated"})

    except Exception as e:

        conn.rollback()

        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Delete Order
# ---------------------------------------------------

@app.route("/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):

    conn = get_db()
    cursor = conn.cursor()

    try:
        me, err_resp, err_code = require_admin_or_perm(conn, cursor, "orders.delete")
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        del_sql = "DELETE FROM orders_staging WHERE id = %s"
        del_args = [order_id]
        if table_has_column(cursor, "orders_staging", "organization_id"):
            del_sql += " AND organization_id = %s"
            del_args.append(tenant_oid)
        cursor.execute(del_sql, tuple(del_args))

        conn.commit()

        return jsonify({"status": "deleted"})

    except Exception as e:

        conn.rollback()

        return jsonify({"error": str(e)}), 500

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Self Processing + Ticket Upload
# ---------------------------------------------------

@app.route("/orders/<int:order_id>/submit_processed", methods=["POST"])
def submit_processed_order(order_id):

    data = request.json or {}
    ticket_image_base64 = data.get("ticket_image_base64")
    ticket_file_name = data.get("ticket_file_name")
    ticket_id = str(data.get("ticket_id") or "").strip()
    weight_num = data.get("weight_num")
    parsed_weight = normalize_weight(weight_num) if weight_num not in [None, ""] else None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_process_submissions_table(cursor)
        ensure_order_processing_exceptions_table(cursor)
        ensure_ticket_id_columns(cursor)
        prune_old_ticket_images(cursor)
        cap = orders_status_capabilities(cursor)
        from backend.order_gaming_flow import ensure_order_gaming_flow_columns

        ensure_order_gaming_flow_columns(cursor)
        g_sel = ", gaming_flow_status" if table_has_column(cursor, "orders_staging", "gaming_flow_status") else ""

        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        sub_sql = f"""
            SELECT
                id,
                date_clean,
                batch_date,
                service_type,
                weight_num,
                {logistics_sql},
                {processing_sql},
                status
                {g_sel}
            FROM orders_staging
            WHERE id = %s
        """
        sub_args = [order_id]
        if table_has_column(cursor, "orders_staging", "organization_id"):
            sub_sql += " AND organization_id = %s"
            sub_args.append(tenant_oid)
        sub_sql += " LIMIT 1"
        cursor.execute(sub_sql, tuple(sub_args))
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Order not found"}), 404

        if table_has_column(cursor, "orders_staging", "gaming_flow_status"):
            if (row.get("gaming_flow_status") or "").upper() == "ACTIVE":
                return jsonify({"error": "Finish or cancel dryer assignment before submitting"}), 409

        logistics_status = (row.get("logistics_status") or "").upper()
        if logistics_status in ["SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"]:
            return jsonify({"error": "Order already sent/checked out"}), 409

        service_type = (row.get("service_type") or "").strip().upper()
        if parsed_weight is not None and service_type == "HD":
            if abs(parsed_weight - round(parsed_weight)) > 1e-9:
                return jsonify({"error": "HD count must be a whole number"}), 400

        if parsed_weight is None:
            return jsonify({"error": "Weight/count is required"}), 400
        if not ticket_image_base64:
            return jsonify({"error": "Ticket photo is required"}), 400

        set_parts = []
        if cap["has_processing"]:
            set_parts.append("processing_status = 'PROCESSED'")
        if cap["has_status"]:
            current = (row.get("status") or "").upper()
            if current not in ["CHECKED_OUT", "SENT_TO_RINSE", "FORCED_CHECKOUT", "FORCE_CHECKOUT"]:
                set_parts.append("status = 'PROCESSED'")
        if not set_parts:
            set_parts.append("status = 'PROCESSED'")

        set_parts.append("weight_num = %s")
        if cap.get("has_ticket_id", False) and ticket_id:
            set_parts.append("ticket_id = %s")

        update_vals = []
        update_vals.append(parsed_weight)
        if cap.get("has_ticket_id", False) and ticket_id:
            update_vals.append(ticket_id)
        update_vals.append(order_id)

        upd_sql = f"""
            UPDATE orders_staging
            SET {", ".join(set_parts)}
            WHERE id = %s
        """
        if table_has_column(cursor, "orders_staging", "organization_id"):
            upd_sql += " AND organization_id = %s"
            update_vals.append(tenant_oid)
        cursor.execute(upd_sql, tuple(update_vals))

        original_measure = row.get("weight_num")
        if service_type == "HD":
            original_val = float(int(round(float(original_measure or 0))))
            submitted_val = float(int(round(parsed_weight)))
        else:
            original_val = round(float(original_measure or 0), 2)
            submitted_val = round(float(parsed_weight), 2)
        diff_val = round(submitted_val - original_val, 2)

        if abs(diff_val) > 0:
            cursor.execute("""
                INSERT INTO order_processing_exceptions
                (
                    order_id,
                    user_id,
                    username,
                    service_type,
                    original_measure,
                    submitted_measure,
                    difference_measure,
                    date_clean,
                    batch_date,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    user_id = VALUES(user_id),
                    username = VALUES(username),
                    service_type = VALUES(service_type),
                    original_measure = VALUES(original_measure),
                    submitted_measure = VALUES(submitted_measure),
                    difference_measure = VALUES(difference_measure),
                    date_clean = VALUES(date_clean),
                    batch_date = VALUES(batch_date),
                    updated_at = NOW()
            """, (
                order_id,
                me["user_id"],
                me.get("username"),
                service_type,
                original_val,
                submitted_val,
                diff_val,
                row.get("date_clean"),
                row.get("batch_date"),
            ))
        else:
            cursor.execute("DELETE FROM order_processing_exceptions WHERE order_id = %s", (order_id,))

        cursor.execute("SELECT ticket_blob_name, ticket_blob_url FROM order_process_submissions WHERE order_id = %s LIMIT 1", (order_id,))
        prev = cursor.fetchone() or {}
        ticket_payload = save_ticket_image(ticket_image_base64, ticket_file_name, order_id) if ticket_image_base64 else None

        cursor.execute("""
            INSERT INTO order_process_submissions
            (
                order_id,
                user_id,
                username,
                ticket_image_base64,
                ticket_file_name,
                ticket_blob_url,
                ticket_blob_name,
                ticket_storage,
                ticket_size_bytes,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                username = VALUES(username),
                ticket_image_base64 = IFNULL(VALUES(ticket_image_base64), ticket_image_base64),
                ticket_file_name = IFNULL(VALUES(ticket_file_name), ticket_file_name),
                ticket_blob_url = IFNULL(VALUES(ticket_blob_url), ticket_blob_url),
                ticket_blob_name = IFNULL(VALUES(ticket_blob_name), ticket_blob_name),
                ticket_storage = IFNULL(VALUES(ticket_storage), ticket_storage),
                ticket_size_bytes = IFNULL(VALUES(ticket_size_bytes), ticket_size_bytes),
                updated_at = NOW()
        """, (
            order_id,
            me["user_id"],
            me.get("username"),
            ticket_payload["ticket_image_base64"] if ticket_payload else None,
            ticket_file_name,
            ticket_payload["ticket_blob_url"] if ticket_payload else None,
            ticket_payload["ticket_blob_name"] if ticket_payload else None,
            ticket_payload["ticket_storage"] if ticket_payload else None,
            ticket_payload["ticket_size_bytes"] if ticket_payload else None,
        ))

        if ticket_payload and prev.get("ticket_blob_name") and prev.get("ticket_blob_name") != ticket_payload.get("ticket_blob_name"):
            delete_ticket_blob(prev.get("ticket_blob_name"), prev.get("ticket_blob_url"))

        conn.commit()
        return jsonify({"status": "processed_submitted", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/gaming/session", methods=["GET"])
def order_gaming_session(order_id):
    from backend.order_gaming_flow import ensure_order_gaming_flow_columns, get_session_for_user

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        ensure_order_gaming_flow_columns(cursor)
        payload, code = get_session_for_user(cursor, me, tenant_oid, int(order_id), cap)
        return jsonify(payload), code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/gaming/start", methods=["POST"])
def order_gaming_start(order_id):
    from backend.order_gaming_flow import ensure_order_gaming_flow_columns, start_session

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        ensure_order_gaming_flow_columns(cursor)
        payload, code = start_session(
            cursor, conn, me, tenant_oid, int(order_id), request.get_json(silent=True) or {}, cap
        )
        return jsonify(payload), code
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/gaming/scan", methods=["POST"])
def order_gaming_scan(order_id):
    from backend.order_gaming_flow import ensure_order_gaming_flow_columns, scan_dryer

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        ensure_order_gaming_flow_columns(cursor)
        payload, code = scan_dryer(
            cursor, conn, me, tenant_oid, int(order_id), request.get_json(silent=True) or {}, cap
        )
        return jsonify(payload), code
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/gaming/complete", methods=["POST"])
def order_gaming_complete(order_id):
    from backend.order_gaming_flow import complete_ticket, ensure_order_gaming_flow_columns

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        ensure_order_gaming_flow_columns(cursor)
        payload, code = complete_ticket(
            cursor,
            conn,
            me,
            tenant_oid,
            int(order_id),
            request.get_json(silent=True) or {},
            cap,
            save_ticket_image,
        )
        return jsonify(payload), code
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/gaming/cancel", methods=["POST"])
def order_gaming_cancel(order_id):
    from backend.order_gaming_flow import cancel_session, ensure_order_gaming_flow_columns

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)
        ensure_order_gaming_flow_columns(cursor)
        payload, code = cancel_session(
            cursor, conn, me, tenant_oid, int(order_id), request.get_json(silent=True) or {}, cap
        )
        return jsonify(payload), code
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["POST"])
def add_order_ticket(order_id):

    data = request.json or {}
    ticket_image_base64 = data.get("ticket_image_base64")
    ticket_file_name = data.get("ticket_file_name")

    if not ticket_image_base64:
        return jsonify({"error": "ticket_image_base64 is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)
        if not order_belongs_to_user_org(cursor, order_id, tenant_oid):
            return jsonify({"error": "Order not found"}), 404

        cursor.execute("SELECT ticket_blob_name, ticket_blob_url FROM order_process_submissions WHERE order_id = %s LIMIT 1", (order_id,))
        prev = cursor.fetchone() or {}
        ticket_payload = save_ticket_image(ticket_image_base64, ticket_file_name, order_id)

        cursor.execute("""
            INSERT INTO order_process_submissions
            (
                order_id,
                user_id,
                username,
                ticket_image_base64,
                ticket_file_name,
                ticket_blob_url,
                ticket_blob_name,
                ticket_storage,
                ticket_size_bytes,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                username = VALUES(username),
                ticket_image_base64 = VALUES(ticket_image_base64),
                ticket_file_name = VALUES(ticket_file_name),
                ticket_blob_url = VALUES(ticket_blob_url),
                ticket_blob_name = VALUES(ticket_blob_name),
                ticket_storage = VALUES(ticket_storage),
                ticket_size_bytes = VALUES(ticket_size_bytes),
                updated_at = NOW()
        """, (
            order_id,
            me["user_id"],
            me.get("username"),
            ticket_payload["ticket_image_base64"],
            ticket_file_name,
            ticket_payload["ticket_blob_url"],
            ticket_payload["ticket_blob_name"],
            ticket_payload["ticket_storage"],
            ticket_payload["ticket_size_bytes"],
        ))

        if prev.get("ticket_blob_name") and prev.get("ticket_blob_name") != ticket_payload.get("ticket_blob_name"):
            delete_ticket_blob(prev.get("ticket_blob_name"), prev.get("ticket_blob_url"))

        conn.commit()
        return jsonify({"status": "ticket_saved", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["GET"])
def get_order_ticket(order_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)
        if not order_belongs_to_user_org(cursor, order_id, tenant_oid):
            return jsonify({"error": "Order not found"}), 404
        cursor.execute("""
            SELECT
                id,
                order_id,
                user_id,
                username,
                ticket_image_base64,
                ticket_file_name,
                ticket_blob_url,
                ticket_blob_name,
                ticket_storage,
                ticket_size_bytes,
                created_at,
                updated_at
            FROM order_process_submissions
            WHERE order_id = %s
            LIMIT 1
        """, (order_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Ticket not found"}), 404

        roles = fetch_user_roles(cursor, me["user_id"])
        is_admin = "ADMIN" in roles
        owner = int(row.get("user_id") or 0) == int(me["user_id"])
        if not is_admin and not owner:
            return jsonify({"error": "Forbidden"}), 403

        row["ticket_image_url"] = build_ticket_read_url(row.get("ticket_blob_name"), row.get("ticket_blob_url"))
        row["has_ticket_image"] = 1 if row.get("ticket_image_base64") or row.get("ticket_blob_url") else 0
        return jsonify(row)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/<int:order_id>/ticket", methods=["DELETE"])
def delete_order_ticket(order_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        ensure_process_submissions_table(cursor)
        if not order_belongs_to_user_org(cursor, order_id, tenant_oid):
            return jsonify({"error": "Order not found"}), 404
        cursor.execute("""
            SELECT id, user_id, ticket_blob_name, ticket_blob_url
            FROM order_process_submissions
            WHERE order_id = %s
            LIMIT 1
        """, (order_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Ticket not found"}), 404

        roles = fetch_user_roles(cursor, me["user_id"])
        is_admin = "ADMIN" in roles
        owner = int(row.get("user_id") or 0) == int(me["user_id"])
        if not is_admin and not owner:
            return jsonify({"error": "Forbidden"}), 403

        cursor.execute("""
            UPDATE order_process_submissions
            SET
                ticket_image_base64 = NULL,
                ticket_file_name = NULL,
                ticket_blob_url = NULL,
                ticket_blob_name = NULL,
                ticket_storage = NULL,
                ticket_size_bytes = NULL,
                updated_at = NOW()
            WHERE order_id = %s
        """, (order_id,))
        delete_ticket_blob(row.get("ticket_blob_name"), row.get("ticket_blob_url"))
        conn.commit()
        return jsonify({"status": "ticket_deleted", "order_id": order_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/order_tickets", methods=["GET"])
def list_order_tickets():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        roles = fetch_user_roles(cursor, me["user_id"])
        if "ADMIN" not in roles:
            return jsonify({"error": "Forbidden"}), 403

        ensure_process_submissions_table(cursor)
        prune_old_ticket_images(cursor)

        try:
            limit = int(request.args.get("limit", 200))
        except Exception:
            limit = 200
        limit = max(1, min(limit, 1000))

        tenant_oid = user_org_id(me)
        join_tickets = "LEFT JOIN orders_staging o ON o.id = s.order_id"
        ticket_params = [limit]
        if table_has_column(cursor, "orders_staging", "organization_id"):
            join_tickets = join_tickets + " AND o.organization_id = %s"
            ticket_params = [tenant_oid, limit]

        cursor.execute(f"""
            SELECT
                s.id,
                s.order_id,
                s.user_id,
                s.username,
                s.ticket_file_name,
                s.ticket_blob_url,
                s.ticket_blob_name,
                s.ticket_storage,
                s.ticket_size_bytes,
                CASE
                    WHEN (s.ticket_blob_url IS NOT NULL AND s.ticket_blob_url <> '')
                      OR (s.ticket_image_base64 IS NOT NULL AND s.ticket_image_base64 <> '')
                    THEN 1 ELSE 0
                END AS has_ticket_image,
                s.created_at,
                s.updated_at,
                o.name_clean,
                o.date_clean,
                o.service_type,
                o.weight_num
            FROM order_process_submissions s
            {join_tickets}
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC
            LIMIT %s
        """, tuple(ticket_params))

        rows = cursor.fetchall() or []
        for r in rows:
            r["ticket_image_url"] = build_ticket_read_url(r.get("ticket_blob_name"), r.get("ticket_blob_url"))
        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/orders/discrepancies", methods=["GET"])
def list_processing_discrepancies():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        roles = fetch_user_roles(cursor, me["user_id"])
        if "ADMIN" not in roles and "OPS" not in roles:
            return jsonify({"error": "Forbidden"}), 403

        ensure_order_processing_exceptions_table(cursor)
        cap = orders_status_capabilities(cursor)
        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        tenant_oid = user_org_id(me)
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")

        where_parts = ["1 = 1"]
        vals = []

        batch_date = request.args.get("batch_date")
        if batch_date:
            where_parts.append("e.batch_date = %s")
            vals.append(batch_date)

        try:
            limit = int(request.args.get("limit", 200))
        except Exception:
            limit = 200
        limit = max(1, min(limit, 1000))

        where_sql = " AND ".join(where_parts)
        join_exceptions = "LEFT JOIN orders_staging o ON o.id = e.order_id"
        if has_staging_org:
            join_exceptions = "INNER JOIN orders_staging o ON o.id = e.order_id AND o.organization_id = %s"

        exists_inner = """
            AND EXISTS (
                SELECT 1
                FROM upload_batches b
                WHERE b.batch_date = o.batch_date
                AND UPPER(COALESCE(b.state, '')) IN ('CONFIRMED', 'CLOSED')
        """
        if has_ub_org:
            exists_inner += "\n                AND b.organization_id = %s"
        exists_inner += "\n            )"

        sent_pending_where = f"""
            ({processing_sql}) = 'PENDING'
            AND ({logistics_sql}) IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT', 'FORCED_CHECKOUT')
            {exists_inner}
        """
        if has_staging_org:
            sent_pending_where = "o.organization_id = %s AND " + sent_pending_where
        if batch_date:
            sent_pending_where += " AND o.batch_date = %s"

        disc_params = []
        if has_staging_org:
            disc_params.append(tenant_oid)
        disc_params.extend(vals)
        if has_staging_org:
            disc_params.append(tenant_oid)
        if has_ub_org:
            disc_params.append(tenant_oid)
        if batch_date:
            disc_params.append(batch_date)
        disc_params.append(limit)

        cursor.execute(f"""
            SELECT *
            FROM (
                SELECT
                    CONCAT('EX-', e.id) AS id,
                    e.order_id,
                    e.username,
                    e.service_type,
                    e.original_measure,
                    e.submitted_measure,
                    e.difference_measure,
                    e.date_clean,
                    e.batch_date,
                    e.created_at,
                    o.name_clean,
                    'MEASURE_MISMATCH' AS discrepancy_type,
                    'WEIGHT_OR_COUNT_MISMATCH' AS reason
                FROM order_processing_exceptions e
                {join_exceptions}
                WHERE {where_sql}

                UNION ALL

                SELECT
                    CONCAT('SP-', o.id) AS id,
                    o.id AS order_id,
                    NULL AS username,
                    o.service_type,
                    o.weight_num AS original_measure,
                    NULL AS submitted_measure,
                    NULL AS difference_measure,
                    o.date_clean,
                    o.batch_date,
                    NOW() AS created_at,
                    o.name_clean,
                    'UNPROCESSED_SENT' AS discrepancy_type,
                    CONCAT('UNPROCESSED_', {logistics_sql}) AS reason
                FROM orders_staging o
                WHERE {sent_pending_where}
            ) x
            ORDER BY x.created_at DESC, x.order_id DESC
            LIMIT %s
        """, tuple(disc_params))

        return jsonify(cursor.fetchall() or [])

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------

@app.route("/dashboard", methods=["GET"])
def dashboard():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        _trigger_daily_operational_reset_if_needed(conn, tenant_oid)
        cap = orders_status_capabilities(cursor)
        active_where = where_active_at_washpro_sql(cap)
        dash_where = active_where
        dash_params = []
        if table_has_column(cursor, "orders_staging", "organization_id"):
            dash_where = f"({active_where}) AND organization_id = %s"
            dash_params.append(tenant_oid)

        has_dash_rush = table_has_column(cursor, "orders_staging", "rush_type")
        _dash_eff = (
            "COALESCE(NULLIF(TRIM(rush_type), ''), CASE WHEN date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END)"
            if has_dash_rush
            else "CASE WHEN date_clean < CURDATE() THEN 'RUSH' ELSE 'NON-RUSH' END"
        )

        cursor.execute(f"""

            SELECT

                COUNT(*) AS total_orders,
                MAX(batch_date) AS batch_date,
                DAYNAME(MAX(batch_date)) AS batch_day,

                SUM(service_type = 'WF') AS wf_total,
                SUM(service_type = 'HD') AS hd_total,

                SUM(service_type = 'WF' AND ({_dash_eff}) = 'RUSH') AS wf_rush,
                SUM(service_type = 'WF' AND ({_dash_eff}) <> 'RUSH') AS wf_non_rush,

                SUM(service_type = 'HD' AND ({_dash_eff}) = 'RUSH') AS hd_rush,
                SUM(service_type = 'HD' AND ({_dash_eff}) <> 'RUSH') AS hd_non_rush

            FROM orders_staging
            WHERE {dash_where}

        """, tuple(dash_params))

        stats = cursor.fetchone()

        if stats:
            for k, v in stats.items():
                if v is None:
                    # Keep batch_date / batch_day null when there are no staging rows (COUNT = 0).
                    if k in ("batch_date", "batch_day"):
                        stats[k] = None
                    else:
                        stats[k] = 0

        return jsonify(stats)

    finally:

        cursor.close()
        conn.close()


# ---------------------------------------------------
# Upload Orders
# ---------------------------------------------------

def summarize_batch_rows(cursor, batch_id, row_pk):
    cursor.execute(f"""
        SELECT
            COUNT(*) AS total_rows,
            SUM(row_status IN ('ACCEPTED', 'OVERRIDDEN')) AS accepted_rows,
            SUM(row_status = 'REJECTED_DUPLICATE') AS rejected_rows,
            SUM(row_status = 'NEEDS_ATTENTION') AS attention_rows,
            SUM(row_status = 'DELETED') AS deleted_rows
        FROM upload_batch_rows
        WHERE upload_batch_id = %s
    """, (batch_id,))
    summary = cursor.fetchone() or {}
    for key in ["total_rows", "accepted_rows", "rejected_rows", "attention_rows", "deleted_rows"]:
        if summary.get(key) is None:
            summary[key] = 0
    return summary


def commit_draft_upload_batch_from_orders_df(
    conn,
    cursor,
    tenant_oid,
    batch_date,
    orders_df,
    file_name: str,
) -> dict:
    """
    Insert upload_batches + upload_batch_rows from a transformed orders DataFrame
    (same columns as transform_orders() final output). Normalizes weights, commits, returns payload dict.
    """
    from backend.rinse_combined_upload import (
        commit_draft_upload_batch_from_orders_df as _commit_draft,
    )

    return _commit_draft(
        conn, cursor, tenant_oid, batch_date, orders_df, file_name
    )



@app.route("/upload_orders", methods=["POST"])
def upload_orders():

    conn = None
    cursor = None

    try:

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        os.makedirs("uploads", exist_ok=True)

        filepath = os.path.join("uploads", file.filename)

        file.save(filepath)

        df = pd.read_excel(filepath, header=None)

        orders_df, summary_df, ops_summary = transform_orders(df)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)

        requested_batch_date = request.form.get("batch_date")
        batch_date = parse_date_value(requested_batch_date) if requested_batch_date else date.today()

        payload = commit_draft_upload_batch_from_orders_df(
            conn, cursor, tenant_oid, batch_date, orders_df, file.filename
        )

        return jsonify(
            {
                **payload,
                "summary_rows": 0 if summary_df is None else len(summary_df),
            }
        )

    except Exception as e:

        if conn:
            conn.rollback()

        print("UPLOAD ERROR:", str(e))

        return jsonify({

            "status": "error",
            "message": str(e)

        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


@app.route("/upload_orders_portal_csv", methods=["POST"])
def upload_orders_portal_csv():
    """
    Upload a Rinse portal-style CSV (e.g. from scripts/rinse-cleanertickets scrape with
    RINSE_CSV_LAYOUT=portal). Uses backend.rinse_portal_csv.portal_csv_to_orders_df — not
    pd.read_excel + etl.transform_orders (that path stays on /upload_orders).
    """
    conn = None
    cursor = None
    filepath = None
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        orig_name = (file.filename or "").strip()
        if not orig_name.lower().endswith(".csv"):
            return jsonify({"error": "Expected a .csv file (Rinse portal export)."}), 400

        os.makedirs("uploads", exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{orig_name}"
        filepath = os.path.join("uploads", safe_name)
        file.save(filepath)

        from backend.rinse_portal_csv import portal_csv_to_orders_df

        orders_df = portal_csv_to_orders_df(filepath)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)

        from backend.rinse_combined_upload import dual_csv_required_error
        from backend.upload_batch_requirements import upload_batch_require_both_csv

        if upload_batch_require_both_csv(cursor, tenant_oid):
            body, code = dual_csv_required_error()
            return jsonify(body), code

        requested_batch_date = request.form.get("batch_date")
        batch_date = parse_date_value(requested_batch_date) if requested_batch_date else date.today()

        payload = commit_draft_upload_batch_from_orders_df(
            conn, cursor, tenant_oid, batch_date, orders_df, orig_name
        )

        return jsonify(
            {
                **payload,
                "summary_rows": len(orders_df),
                "source": "upload_portal_csv",
            }
        )

    except ValueError as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 400

    except Exception as e:
        if conn:
            conn.rollback()
        print("UPLOAD PORTAL CSV ERROR:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        if filepath:
            try:
                os.unlink(filepath)
            except OSError:
                pass


@app.route("/upload_orders_rinse_dual_csv", methods=["POST"])
def upload_orders_rinse_dual_csv():
    """
    Combined portal + scan-events CSV upload in one transaction.
    Scan-events are merged and completion recomputed before portal row classification.
    """
    conn = None
    cursor = None
    portal_path = None
    events_path = None
    try:
        portal_file = request.files.get("portal_csv")
        events_file = request.files.get("scan_events_csv")
        if not portal_file or portal_file.filename == "":
            return jsonify({"error": "portal_csv file is required"}), 400
        if not events_file or events_file.filename == "":
            return jsonify({"error": "scan_events_csv file is required"}), 400

        portal_name = (portal_file.filename or "").strip()
        events_name = (events_file.filename or "").strip()
        if not portal_name.lower().endswith(".csv"):
            return jsonify({"error": "portal_csv must be a .csv file"}), 400
        if not events_name.lower().endswith(".csv"):
            return jsonify({"error": "scan_events_csv must be a .csv file"}), 400

        os.makedirs("uploads", exist_ok=True)
        portal_path = os.path.join("uploads", f"{uuid.uuid4().hex}_{portal_name}")
        events_path = os.path.join("uploads", f"{uuid.uuid4().hex}_{events_name}")
        portal_file.save(portal_path)
        events_file.save(events_path)

        from backend.rinse_portal_csv import portal_csv_to_orders_df
        from backend.rinse_scan_events_upload import parse_scan_events_csv

        orders_df = portal_csv_to_orders_df(portal_path)
        events_df, warnings = parse_scan_events_csv(events_path)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)

        requested_batch_date = request.form.get("batch_date")
        batch_date = parse_date_value(requested_batch_date) if requested_batch_date else date.today()

        from backend.rinse_combined_upload import commit_rinse_combined_upload

        payload = commit_rinse_combined_upload(
            conn,
            cursor,
            tenant_oid,
            batch_date,
            portal_name,
            orders_df,
            events_name,
            events_df,
        )
        if warnings:
            payload["warnings"] = warnings
        return jsonify(payload)

    except ValueError as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 400

    except Exception as e:
        if conn:
            conn.rollback()
        print("UPLOAD RINSE DUAL CSV ERROR:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        for path in (portal_path, events_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


@app.route("/rinse/bags", methods=["GET"])
def list_rinse_bags():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        status = (request.args.get("status") or "").strip().upper() or None
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        from backend.rinse_bag_registry import list_registry_rows

        rows = list_registry_rows(
            cursor, tenant_oid, status=status, limit=limit, offset=offset
        )
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/rinse/bags/<bag_id>", methods=["GET"])
def get_rinse_bag(bag_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        from backend.rinse_bag_completion import normalize_bag_id
        from backend.rinse_bag_registry import get_registry_row

        bid = normalize_bag_id(bag_id)
        if not bid:
            return jsonify({"error": "Invalid bag id"}), 400
        row = get_registry_row(cursor, tenant_oid, bid)
        if not row:
            return jsonify({"error": "Bag not found"}), 404
        return jsonify(row)
    finally:
        cursor.close()
        conn.close()


@app.route("/rinse/bags/<bag_id>/recompute-completion", methods=["POST"])
def recompute_rinse_bag_completion(bag_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        _, err_a, code_a = require_admin(cursor)
        if err_a:
            return err_a, code_a
        tenant_oid = user_org_id(me)
        from backend.rinse_bag_completion import normalize_bag_id
        from backend.rinse_bag_upload import recompute_bag_completion_with_audit

        bid = normalize_bag_id(bag_id)
        if not bid:
            return jsonify({"error": "Invalid bag id"}), 400
        from backend.rinse_bag_registry import get_registry_row

        if not get_registry_row(cursor, tenant_oid, bid):
            return jsonify({"error": "Bag not found"}), 404
        payload = recompute_bag_completion_with_audit(cursor, tenant_oid, bid)
        conn.commit()
        return jsonify(payload)
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/rinse/bags/<bag_id>/detail", methods=["GET"])
def get_rinse_bag_detail(bag_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        _, err_a, code_a = require_admin(cursor)
        if err_a:
            return err_a, code_a
        tenant_oid = user_org_id(me)
        from backend.rinse_bag_completion import normalize_bag_id
        from backend.rinse_bag_upload import get_bag_admin_detail

        bid = normalize_bag_id(bag_id)
        if not bid:
            return jsonify({"error": "Invalid bag id"}), 400
        cap = orders_status_capabilities(cursor)
        detail = get_bag_admin_detail(
            cursor,
            tenant_oid,
            bid,
            active_where_sql=where_not_sent_or_forced_sql(cap),
            has_staging_org=table_has_column(cursor, "orders_staging", "organization_id"),
            has_ticket_id_col=cap.get("has_ticket_id", False),
            upload_batch_row_pk=get_upload_batch_rows_pk(cursor),
        )
        if not detail:
            return jsonify({"error": "Bag not found"}), 404
        return jsonify(detail)
    finally:
        cursor.close()
        conn.close()


@app.route("/rinse/bags/<bag_id>/scan-events", methods=["GET"])
def list_rinse_bag_scan_events(bag_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        from backend.rinse_bag_completion import normalize_bag_id
        from backend.rinse_bag_registry import list_scan_events_for_bag

        bid = normalize_bag_id(bag_id)
        if not bid:
            return jsonify({"error": "Invalid bag id"}), 400
        try:
            limit = int(request.args.get("limit", 500))
        except (TypeError, ValueError):
            limit = 500
        rows = list_scan_events_for_bag(cursor, tenant_oid, bid, limit=limit)
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rinse-scan-events", methods=["POST"])
def upload_batch_rinse_scan_events(batch_id: int):
    """
    Optional: upload Rinse scan-events CSV (Bag ID + scan columns only).
    Does not modify upload_batch_rows or create orders.
    """
    conn = None
    cursor = None
    filepath = None
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        orig_name = (file.filename or "").strip()
        if not orig_name.lower().endswith(".csv"):
            return jsonify({"error": "Expected a .csv file (Rinse scan-events export)."}), 400

        os.makedirs("uploads", exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{orig_name}"
        filepath = os.path.join("uploads", safe_name)
        file.save(filepath)

        from backend.rinse_scan_events_upload import (
            commit_scan_events_for_batch,
            parse_scan_events_csv,
        )

        events_df, warnings = parse_scan_events_csv(filepath)

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)

        from backend.rinse_combined_upload import dual_csv_required_error
        from backend.upload_batch_requirements import upload_batch_require_both_csv

        if upload_batch_require_both_csv(cursor, tenant_oid):
            body, code = dual_csv_required_error()
            return jsonify(body), code

        if not upload_batch_belongs_to_user_org(cursor, batch_id, tenant_oid):
            return jsonify({"error": "Upload batch not found for your organization."}), 404

        if table_has_column(cursor, "upload_batches", "state"):
            pk = get_upload_batches_pk(cursor)
            cursor.execute(
                f"SELECT state FROM upload_batches WHERE {pk} = %s LIMIT 1",
                (batch_id,),
            )
            batch_row = cursor.fetchone()
            batch_state = (batch_row or {}).get("state", "DRAFT")
            if str(batch_state or "").upper() not in ("DRAFT",):
                return jsonify(
                    {
                        "error": "Scan-events can only be uploaded to a draft batch.",
                        "batch_state": batch_state,
                    }
                ), 409

        batch_payload = commit_scan_events_for_batch(
            cursor,
            tenant_oid,
            batch_id,
            events_df,
            orig_name,
            replace_existing=True,
        )

        from backend.rinse_bag_registry import (
            merge_scan_events_from_upload,
            recompute_completion_for_bags,
        )

        merge_payload = merge_scan_events_from_upload(
            cursor,
            tenant_oid,
            batch_id,
            events_df,
            orig_name,
        )
        completion_payload = recompute_completion_for_bags(
            cursor,
            tenant_oid,
            merge_payload.get("bag_ids") or [],
        )
        from backend.rinse_folding_registry import recompute_folding_after_upload

        folding_payload = recompute_folding_after_upload(
            cursor,
            tenant_oid,
            merge_payload.get("bag_ids") or [],
        )
        conn.commit()

        return jsonify(
            {
                "status": "ok",
                "upload_batch_id": batch_id,
                "source": "upload_rinse_scan_events_csv",
                "warnings": warnings,
                **batch_payload,
                "persistent_merge": merge_payload,
                "completion": completion_payload,
                "folding": folding_payload,
            }
        )

    except ValueError as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 400

    except Exception as e:
        if conn:
            conn.rollback()
        print("UPLOAD RINSE SCAN EVENTS ERROR:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        if filepath:
            try:
                os.unlink(filepath)
            except OSError:
                pass


# ---------------------------------------------------
# Create Manual Order
# ---------------------------------------------------

@app.route("/orders/create_manual", methods=["POST"])
def create_manual_order():

    data = request.json or {}

    try:

        date_clean = parse_date_value(data.get("date_clean"))
        name_clean = (data.get("name_clean") or "").strip()
        weight_num = normalize_weight(data.get("weight_num"))
        service_type = (data.get("service_type") or "").strip()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()

        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400

        batch_date = date.today()

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        cap = orders_status_capabilities(cursor)

        cols = [
            "date_clean",
            "name_clean",
            "weight_num",
            "service_type",
            "rush_type",
            "batch_date",
        ]
        vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
        args = [date_clean, name_clean, weight_num, service_type, rush_type, batch_date]

        if table_has_column(cursor, "orders_staging", "organization_id"):
            cols = ["organization_id"] + cols
            vals = ["%s"] + vals
            args = [tenant_oid] + args

        if cap["has_logistics"]:
            cols.append("logistics_status")
            vals.append("%s")
            args.append("AT_WASHPRO")
        if cap["has_processing"]:
            cols.append("processing_status")
            vals.append("%s")
            args.append("PENDING")
        if cap["has_status"]:
            cols.append("status")
            vals.append("%s")
            args.append("PENDING")

        cursor.execute(f"""
            INSERT INTO orders_staging
            ({", ".join(cols)})
            VALUES ({", ".join(vals)})
        """, tuple(args))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"status": "created"})

    except Exception as e:

        return jsonify({"error": str(e)}), 500
    
# ---------------------------------------------------
# Employees API
# ---------------------------------------------------


@app.route("/employees", methods=["GET"])
def get_employees():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    ensure_employee_profiles_table(cursor)

    cursor.execute("""

        SELECT id, name, role
        FROM employees
        WHERE active = TRUE
        ORDER BY name

    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(rows)


@app.route("/employees/profiles", methods=["GET"])
def get_employee_profiles():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_employee_profiles_table(cursor)
        cursor.execute("""
            SELECT
                ep.id,
                ep.employee_id,
                ep.first_name,
                ep.last_name,
                ep.employment_type,
                ep.address_line1,
                ep.address_line2,
                ep.city,
                ep.state,
                ep.zip_code,
                ep.tax_id_type,
                ep.tax_id_value,
                ep.pay_rate,
                ep.overtime_rate,
                ep.spread_of_time_rate,
                ep.active,
                ep.created_at,
                ep.updated_at,
                e.name AS employee_name
            FROM employee_profiles ep
            LEFT JOIN employees e ON e.id = ep.employee_id
            ORDER BY ep.last_name, ep.first_name, ep.id
        """)
        rows = cursor.fetchall()
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/employees/profiles", methods=["POST"])
def create_employee_profile():

    data = request.json or {}
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    employment_type = (data.get("employment_type") or "WASHPRO_W2").strip().upper()
    tax_id_type = (data.get("tax_id_type") or "").strip().upper() or None

    if not first_name or not last_name:
        return jsonify({"error": "first_name and last_name are required"}), 400

    allowed_types = {"WASHPRO_W2", "WASHPRO_1099", "WASHMATE_1099"}
    if employment_type not in allowed_types:
        return jsonify({"error": "employment_type must be WASHPRO_W2, WASHPRO_1099, or WASHMATE_1099"}), 400

    if tax_id_type and tax_id_type not in {"SSN", "ITIN"}:
        return jsonify({"error": "tax_id_type must be SSN or ITIN"}), 400

    def _money(v):
        if v in [None, ""]:
            return 0
        return round(float(v), 2)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_employee_profiles_table(cursor)
        cursor.execute("""
            INSERT INTO employee_profiles
            (
                employee_id,
                first_name,
                last_name,
                employment_type,
                address_line1,
                address_line2,
                city,
                state,
                zip_code,
                tax_id_type,
                tax_id_value,
                pay_rate,
                overtime_rate,
                spread_of_time_rate,
                active,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            data.get("employee_id"),
            first_name,
            last_name,
            employment_type,
            data.get("address_line1"),
            data.get("address_line2"),
            data.get("city"),
            data.get("state"),
            data.get("zip_code"),
            tax_id_type,
            data.get("tax_id_value"),
            _money(data.get("pay_rate")),
            _money(data.get("overtime_rate")),
            _money(data.get("spread_of_time_rate")),
            bool(data.get("active", True))
        ))
        conn.commit()
        return jsonify({"status": "created", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/employees/profiles/<int:profile_id>", methods=["PUT"])
def update_employee_profile(profile_id):

    data = request.json or {}
    employment_type = (data.get("employment_type") or "WASHPRO_W2").strip().upper()
    tax_id_type = (data.get("tax_id_type") or "").strip().upper() or None

    allowed_types = {"WASHPRO_W2", "WASHPRO_1099", "WASHMATE_1099"}
    if employment_type not in allowed_types:
        return jsonify({"error": "employment_type must be WASHPRO_W2, WASHPRO_1099, or WASHMATE_1099"}), 400

    if tax_id_type and tax_id_type not in {"SSN", "ITIN"}:
        return jsonify({"error": "tax_id_type must be SSN or ITIN"}), 400

    def _money(v):
        if v in [None, ""]:
            return 0
        return round(float(v), 2)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_employee_profiles_table(cursor)
        cursor.execute("SELECT id FROM employee_profiles WHERE id = %s", (profile_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Profile not found"}), 404

        cursor.execute("""
            UPDATE employee_profiles
            SET
                employee_id = %s,
                first_name = %s,
                last_name = %s,
                employment_type = %s,
                address_line1 = %s,
                address_line2 = %s,
                city = %s,
                state = %s,
                zip_code = %s,
                tax_id_type = %s,
                tax_id_value = %s,
                pay_rate = %s,
                overtime_rate = %s,
                spread_of_time_rate = %s,
                active = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (
            data.get("employee_id"),
            (data.get("first_name") or "").strip(),
            (data.get("last_name") or "").strip(),
            employment_type,
            data.get("address_line1"),
            data.get("address_line2"),
            data.get("city"),
            data.get("state"),
            data.get("zip_code"),
            tax_id_type,
            data.get("tax_id_value"),
            _money(data.get("pay_rate")),
            _money(data.get("overtime_rate")),
            _money(data.get("spread_of_time_rate")),
            bool(data.get("active", True)),
            profile_id
        ))
        conn.commit()
        return jsonify({"status": "updated"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ---------------------------------------------------
# Issue Dropdown API
# ---------------------------------------------------


@app.route("/issues", methods=["GET"])
def get_issues():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, issue_name
        FROM issue_types
        ORDER BY issue_name
    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(rows)

# ---------------------------------------------------
# Start Folder Shift
# ---------------------------------------------------


@app.route("/folder_shift/start", methods=["POST"])
def start_shift():

    data = request.json

    employee_id = data["employee_id"]
    start_time = data["start_time"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""

        INSERT INTO folder_shifts
        (employee_id, shift_date, shift_start_time)

        VALUES (%s, CURDATE(), %s)

    """, (employee_id, start_time))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "shift_started"})

# ---------------------------------------------------
# Get Current Shift
# ---------------------------------------------------

@app.route("/folder_shift/current", methods=["GET"])
def current_shift():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""

        SELECT *
        FROM folder_shifts
        WHERE shift_date = CURDATE()
        ORDER BY id DESC
        LIMIT 1

    """)

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify(row)

# ---------------------------------------------------
# Enter Folding Record
# ---------------------------------------------------


@app.route("/order_processing", methods=["POST"])
def process_order():

    data = request.json or {}

    order_id = data.get("order_id")
    washer_id = data.get("washer_employee_id")
    folder_id = data.get("folder_employee_id")
    end_time = data.get("fold_end_time")
    pieces = data.get("pieces")
    issue = data.get("issue_type")
    rinse_case = data.get("rinse_case_id")
    processing_date = data.get("processing_date")

    if order_id in [None, ""]:
        return jsonify({"error": "order_id is required"}), 400
    if washer_id in [None, ""] or folder_id in [None, ""]:
        return jsonify({"error": "washer_employee_id and folder_employee_id are required"}), 400

    try:
        order_id = int(order_id)
        washer_id = int(washer_id)
        folder_id = int(folder_id)
    except Exception:
        return jsonify({"error": "order_id, washer_employee_id, folder_employee_id must be numeric"}), 400

    if pieces in [None, ""]:
        pieces = None
    else:
        try:
            pieces = int(pieces)
        except Exception:
            return jsonify({"error": "pieces must be numeric"}), 400

    end_dt = None
    if end_time not in [None, ""]:
        # Accept ISO datetime, HH:MM (24h), or HH:MM AM/PM with optional processing_date.
        raw_end_time = str(end_time).strip()
        if processing_date not in [None, ""]:
            try:
                d = parse_date_value(processing_date)
                try:
                    t = datetime.strptime(raw_end_time, "%I:%M %p").time()
                except Exception:
                    t = datetime.strptime(raw_end_time, "%H:%M").time()
                end_dt = datetime.combine(d, t)
            except Exception:
                end_dt = None
        if end_dt is None:
            try:
                end_dt = datetime.fromisoformat(raw_end_time)
            except Exception:
                end_dt = None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    me, err_resp, err_code = require_user(cursor)
    if err_resp:
        return err_resp, err_code
    tenant_oid = user_org_id(me)
    if not order_belongs_to_user_org(cursor, order_id, tenant_oid):
        return jsonify({"error": "Order not found"}), 404
    cap = orders_status_capabilities(cursor)

    cursor.execute("""

        INSERT INTO order_processing
        (
            order_id,
            washer_employee_id,
            folder_employee_id,
            fold_end_time,
            pieces,
            issue_type,
            rinse_case_id
        )

        VALUES (%s,%s,%s,%s,%s,%s,%s)

    """, (
        order_id,
        washer_id,
        folder_id,
        end_dt,
        pieces,
        issue,
        rinse_case
    ))

    set_parts = []
    if cap["has_processing"]:
        set_parts.append("processing_status='PROCESSED'")
    if cap["has_status"]:
        set_parts.append("status='PROCESSED'")
    if not set_parts:
        set_parts.append("status='PROCESSED'")

    upd_proc = f"""
        UPDATE orders_staging
        SET {", ".join(set_parts)}
        WHERE id=%s
    """
    upd_args = [order_id]
    if table_has_column(cursor, "orders_staging", "organization_id"):
        upd_proc += " AND organization_id = %s"
        upd_args.append(tenant_oid)
    cursor.execute(upd_proc, tuple(upd_args))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status":"recorded"})

# ---------------------------------------------------
# Scoreboard API
# ---------------------------------------------------

@app.route("/scoreboard", methods=["GET"])
def scoreboard():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if table_has_column(cursor, "orders_staging", "organization_id"):
            cursor.execute("""
                SELECT
                    e.name,
                    COUNT(*) AS bags
                FROM order_processing p
                INNER JOIN orders_staging o ON o.id = p.order_id AND o.organization_id = %s
                JOIN employees e ON p.folder_employee_id = e.id
                WHERE DATE(p.created_at) = CURDATE()
                GROUP BY e.id
                ORDER BY bags DESC
            """, (tenant_oid,))
        else:
            cursor.execute("""
                SELECT
                    e.name,
                    COUNT(*) AS bags
                FROM order_processing p
                JOIN employees e ON p.folder_employee_id = e.id
                WHERE DATE(p.created_at) = CURDATE()
                GROUP BY e.id
                ORDER BY bags DESC
            """)

        rows = cursor.fetchall()

        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()

# ---------------------------------------------------
# Maintenance APIs
# ---------------------------------------------------

@app.route("/issues/add", methods=["POST"])
def add_issue():

    data=request.json

    conn=get_db()
    cursor=conn.cursor()

    cursor.execute("""

    INSERT INTO issue_types(issue_name)
    VALUES(%s)

    """,(data["issue_name"],))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status":"added"})


# ---------------------------------------------------
# Geofence Config APIs
# ---------------------------------------------------

@app.route("/geofence/config", methods=["GET"])
def get_geofence_config():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"configured": False, "geofence": None})

        return jsonify({"configured": True, "geofence": geofence})

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Auth / RBAC APIs
# ---------------------------------------------------

@app.route("/auth/attendance-pin-unlock", methods=["POST"])
def attendance_pin_unlock():
    """Shared-tablet lock screen: unlock with org slug + employee payroll PIN (non-admin users only)."""
    data = request.json or {}
    org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
    pin_raw = data.get("pin")
    pin = str(pin_raw).strip() if pin_raw is not None else ""

    if not org_slug or not pin:
        return jsonify({"error": "organization_slug and pin are required"}), 400
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 10:
        return jsonify({"error": "Invalid PIN"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db()
        if not payroll_profiles_active(conn):
            return jsonify({"error": "PIN unlock is not available"}), 503
        cursor = conn.cursor(dictionary=True)
        if not table_has_column(cursor, "payroll_profiles", "attendance_pin_hash"):
            return jsonify({"error": "PIN unlock is not available"}), 503
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "PIN unlock is not available"}), 503

        has_u_org = table_has_column(cursor, "users", "organization_id")
        logo_sql = _org_logo_select_sql(cursor)
        cursor.execute(
            f"""
            SELECT u.id, u.username, u.display_name, u.active, u.organization_id,
                   o.slug AS organization_slug, o.display_name AS organization_name,
                   {logo_sql},
                   pp.attendance_pin_hash
            FROM payroll_profiles pp
            INNER JOIN users u ON u.id = pp.user_id
            INNER JOIN organizations o ON o.id = u.organization_id AND o.active = 1
            WHERE LOWER(o.slug) = %s
              AND u.active = 1
              AND pp.attendance_pin_hash IS NOT NULL
            """,
            (org_slug,),
        )
        rows = cursor.fetchall() or []

        matched = None
        matched_roles = None
        for row in rows:
            h = row.get("attendance_pin_hash")
            if not h or not verify_password(str(h), pin):
                continue
            roles = fetch_user_roles(cursor, row["id"])
            rs = {str(r).upper() for r in roles}
            if rs & {"ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"}:
                continue
            matched = row
            matched_roles = roles
            break

        if not matched:
            return jsonify({"error": "Invalid PIN"}), 401

        if matched.get("organization_logo_url"):
            matched["organization_logo_url"] = rewrite_org_logo_url_for_client(
                matched.get("organization_logo_url")
            )

        token = uuid.uuid4().hex
        expires_at = datetime.utcnow() + timedelta(hours=12)
        cursor.execute(
            """
            INSERT INTO auth_sessions
            (user_id, token, expires_at, revoked, created_at, last_seen_at)
            VALUES (%s, %s, %s, FALSE, NOW(), NOW())
            """,
            (matched["id"], token, expires_at),
        )

        conn.commit()

        payload_user = {
            "id": matched["id"],
            "username": matched["username"],
            "display_name": matched.get("display_name") or matched["username"],
            "roles": matched_roles or [],
        }
        if has_u_org and matched.get("organization_id") is not None:
            payload_user["organization_id"] = int(matched["organization_id"])
            if matched.get("organization_slug"):
                payload_user["organization_slug"] = matched["organization_slug"]
            if matched.get("organization_name"):
                payload_user["organization_name"] = matched["organization_name"]
            if matched.get("organization_logo_url"):
                payload_user["organization_logo_url"] = matched["organization_logo_url"]

        return jsonify({"token": token, "user": payload_user})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        has_u_org = table_has_column(cursor, "users", "organization_id")
        has_orgs = table_exists(cursor, "organizations")
        user = None
        org_slug = ""
        if not has_u_org:
            cursor.execute("""
                SELECT id, username, password_hash, display_name, active
                FROM users
                WHERE username = %s
                LIMIT 1
            """, (username,))
            user = cursor.fetchone()
        else:
            org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
            # Slug "platform" is overloaded: (1) a real tenant may use slug `platform`; (2) bookmark
            # /login/platform historically meant "log in as any SUPER_ADMIN/PLATFORM_ADMIN by username".
            # Prefer tenant match first so org-scoped users (e.g. superadmin in tenant "platform") work.
            if org_slug == "platform" and has_orgs:
                logo_sql = _org_logo_select_sql(cursor)
                cursor.execute(
                    f"""
                    SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                           o.slug AS organization_slug, o.display_name AS organization_name,
                           {logo_sql}
                    FROM users u
                    JOIN organizations o ON o.id = u.organization_id AND o.active = 1
                    WHERE u.username = %s AND LOWER(o.slug) = %s
                    LIMIT 1
                    """,
                    (username, org_slug),
                )
                user = cursor.fetchone()
                if not user and table_exists(cursor, "user_roles"):
                    cursor.execute(
                        f"""
                        SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                               o.slug AS organization_slug, o.display_name AS organization_name,
                               {logo_sql}
                        FROM users u
                        LEFT JOIN organizations o ON o.id = u.organization_id
                        WHERE u.username = %s AND u.active = 1
                          AND EXISTS (
                              SELECT 1 FROM user_roles ur
                              INNER JOIN roles r ON r.id = ur.role_id
                              WHERE ur.user_id = u.id
                                AND UPPER(r.code) IN ('SUPER_ADMIN', 'PLATFORM_ADMIN')
                          )
                        """,
                        (username,),
                    )
                    plat_rows = cursor.fetchall() or []
                    if len(plat_rows) > 1:
                        return jsonify(
                            {
                                "error": "Several platform logins share this username. Use your team login URL instead (e.g. /login/your-tenant).",
                            }
                        ), 400
                    user = plat_rows[0] if plat_rows else None
            elif org_slug and has_orgs:
                logo_sql = _org_logo_select_sql(cursor)
                cursor.execute(
                    f"""
                    SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                           o.slug AS organization_slug, o.display_name AS organization_name,
                           {logo_sql}
                    FROM users u
                    JOIN organizations o ON o.id = u.organization_id AND o.active = 1
                    WHERE u.username = %s AND LOWER(o.slug) = %s
                    LIMIT 1
                    """,
                    (username, org_slug),
                )
                user = cursor.fetchone()
            else:
                cursor.execute("""
                    SELECT id, username, password_hash, display_name, active, organization_id
                    FROM users
                    WHERE username = %s
                """, (username,))
                rows = cursor.fetchall()
                if len(rows) > 1:
                    if has_orgs:
                        cursor.execute("""
                            SELECT o.slug, o.display_name
                            FROM users u
                            JOIN organizations o ON o.id = u.organization_id
                            WHERE u.username = %s AND u.active = 1
                        """, (username,))
                        org_opts = cursor.fetchall()
                    else:
                        org_opts = []
                    return jsonify({
                        "error": "organization_slug is required for this username",
                        "organizations": [{"slug": r["slug"], "display_name": r["display_name"]} for r in org_opts],
                    }), 400
                user = rows[0] if rows else None
                if user and has_orgs and not org_slug:
                    if table_has_column(cursor, "organizations", "logo_url"):
                        cursor.execute(
                            "SELECT slug, display_name, logo_url FROM organizations WHERE id = %s LIMIT 1",
                            (user["organization_id"],),
                        )
                    else:
                        cursor.execute(
                            "SELECT slug, display_name FROM organizations WHERE id = %s LIMIT 1",
                            (user["organization_id"],),
                        )
                    o = cursor.fetchone()
                    if o:
                        user["organization_slug"] = o.get("slug")
                        user["organization_name"] = o.get("display_name")
                        if o.get("logo_url"):
                            user["organization_logo_url"] = rewrite_org_logo_url_for_client(
                                o.get("logo_url")
                            )

        if not user or not as_bool(user.get("active"), default=False):
            if not user and org_slug and has_orgs and has_u_org:
                cursor.execute(
                    """
                    SELECT 1 AS ok
                    FROM users u
                    INNER JOIN organizations o ON o.id = u.organization_id
                    WHERE u.username = %s AND LOWER(o.slug) = %s AND o.active = 0
                    LIMIT 1
                    """,
                    (username, org_slug),
                )
                if cursor.fetchone():
                    return jsonify(
                        {
                            "error": "This organization has been deactivated. Ask a platform administrator to restore it.",
                        }
                    ), 403
            return jsonify({"error": "Invalid credentials"}), 401

        stored_hash = user.get("password_hash") or ""
        password_ok = False

        # Backward compatibility: allow legacy plain-text rows and migrate to hash.
        if stored_hash.startswith(("pbkdf2:", "scrypt:")):
            try:
                password_ok = check_password_hash(stored_hash, password)
            except Exception:
                password_ok = False
        else:
            password_ok = (stored_hash == password)
            if password_ok:
                new_hash = generate_password_hash(password)
                if table_has_column(cursor, "users", "updated_at"):
                    cursor.execute(
                        """
                        UPDATE users
                        SET password_hash = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (new_hash, user["id"]),
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (new_hash, user["id"]),
                    )

        if not password_ok:
            return jsonify({"error": "Invalid credentials"}), 401

        token = uuid.uuid4().hex
        expires_at = datetime.utcnow() + timedelta(hours=12)
        cursor.execute("""
            INSERT INTO auth_sessions
            (user_id, token, expires_at, revoked, created_at, last_seen_at)
            VALUES (%s, %s, %s, FALSE, NOW(), NOW())
        """, (user["id"], token, expires_at))

        roles = fetch_user_roles(cursor, user["id"])
        conn.commit()
        payload_user = {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "roles": roles,
        }
        if has_u_org and user.get("organization_id") is not None:
            payload_user["organization_id"] = int(user["organization_id"])
            if user.get("organization_slug"):
                payload_user["organization_slug"] = user["organization_slug"]
            if user.get("organization_name"):
                payload_user["organization_name"] = user["organization_name"]
            if user.get("organization_logo_url"):
                payload_user["organization_logo_url"] = user["organization_logo_url"]
        return jsonify({
            "token": token,
            "user": payload_user,
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _auth_lookup_user_row_for_slug(cursor, username, org_slug):
    """Resolve an active Washpro user by username and tenant slug (same rules as login, before password check)."""
    has_u_org = table_has_column(cursor, "users", "organization_id")
    has_orgs = table_exists(cursor, "organizations")
    user = None
    if not has_u_org:
        cursor.execute(
            """
            SELECT id, username, password_hash, display_name, active
            FROM users WHERE username = %s LIMIT 1
            """,
            (username,),
        )
        user = cursor.fetchone()
    else:
        org_slug = (org_slug or "").strip().lower()
        if org_slug == "platform" and has_orgs:
            logo_sql = _org_logo_select_sql(cursor)
            cursor.execute(
                f"""
                SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                       o.slug AS organization_slug, o.display_name AS organization_name,
                       {logo_sql}
                FROM users u
                JOIN organizations o ON o.id = u.organization_id AND o.active = 1
                WHERE u.username = %s AND LOWER(o.slug) = %s
                LIMIT 1
                """,
                (username, org_slug),
            )
            user = cursor.fetchone()
            if not user and table_exists(cursor, "user_roles"):
                cursor.execute(
                    f"""
                    SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                           o.slug AS organization_slug, o.display_name AS organization_name,
                           {logo_sql}
                    FROM users u
                    LEFT JOIN organizations o ON o.id = u.organization_id
                    WHERE u.username = %s AND u.active = 1
                      AND EXISTS (
                          SELECT 1 FROM user_roles ur
                          INNER JOIN roles r ON r.id = ur.role_id
                          WHERE ur.user_id = u.id
                            AND UPPER(r.code) IN ('SUPER_ADMIN', 'PLATFORM_ADMIN')
                      )
                    """,
                    (username,),
                )
                plat_rows = cursor.fetchall() or []
                if len(plat_rows) != 1:
                    user = None
                else:
                    user = plat_rows[0]
        elif org_slug and has_orgs:
            logo_sql = _org_logo_select_sql(cursor)
            cursor.execute(
                f"""
                SELECT u.id, u.username, u.password_hash, u.display_name, u.active, u.organization_id,
                       o.slug AS organization_slug, o.display_name AS organization_name,
                       {logo_sql}
                FROM users u
                JOIN organizations o ON o.id = u.organization_id AND o.active = 1
                WHERE u.username = %s AND LOWER(o.slug) = %s
                LIMIT 1
                """,
                (username, org_slug),
            )
            user = cursor.fetchone()
        else:
            cursor.execute(
                """
                SELECT id, username, password_hash, display_name, active, organization_id
                FROM users WHERE username = %s
                """,
                (username,),
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                user = None
            else:
                user = rows[0]
    if not user or not as_bool(user.get("active"), default=False):
        return None
    return user


def ensure_password_reset_tokens_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          user_id INT NOT NULL,
          token_hash CHAR(64) NOT NULL,
          expires_at DATETIME NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          consumed_at DATETIME NULL,
          INDEX idx_lookup (token_hash, expires_at),
          INDEX idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@app.route("/auth/public/change-password", methods=["POST"])
def auth_public_change_password():
    """Change password when not logged in (requires current password)."""
    data = request.json or {}
    username = (data.get("username") or "").strip()
    org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
    cur_pw = data.get("current_password") or data.get("current") or ""
    new_pw = data.get("new_password") or data.get("password") or ""
    if not username or not cur_pw or not new_pw:
        return jsonify({"error": "username, current_password, and new_password are required"}), 400
    if len(str(new_pw)) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        has_u_org = table_has_column(cursor, "users", "organization_id")
        has_orgs = table_exists(cursor, "organizations")
        if has_u_org and has_orgs and not org_slug:
            return jsonify({"error": "organization_slug is required"}), 400
        user = _auth_lookup_user_row_for_slug(cursor, username, org_slug)
        if not user:
            return jsonify({"error": "Invalid credentials"}), 401
        stored_hash = user.get("password_hash") or ""
        ok = False
        if stored_hash.startswith(("pbkdf2:", "scrypt:")):
            try:
                ok = check_password_hash(stored_hash, cur_pw)
            except Exception:
                ok = False
        else:
            ok = stored_hash == cur_pw
        if not ok:
            return jsonify({"error": "Invalid credentials"}), 401
        new_hash = generate_password_hash(new_pw)
        if table_has_column(cursor, "users", "updated_at"):
            cursor.execute(
                "UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s",
                (new_hash, int(user["id"])),
            )
        else:
            cursor.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (new_hash, int(user["id"])),
            )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/password-reset/request", methods=["POST"])
def auth_password_reset_request():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    org_slug = (data.get("organization_slug") or data.get("organization") or "").strip().lower()
    if not username:
        return jsonify({"error": "username is required"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        has_u_org = table_has_column(cursor, "users", "organization_id")
        has_orgs = table_exists(cursor, "organizations")
        if has_u_org and has_orgs and not org_slug:
            return jsonify({"error": "organization_slug is required"}), 400
        user = _auth_lookup_user_row_for_slug(cursor, username, org_slug)
        msg = {
            "ok": True,
            "message": "If an account matched, you will receive reset instructions when email delivery is configured.",
        }
        if not user:
            return jsonify(msg)
        ensure_password_reset_tokens_table(cursor)
        raw = secrets.token_urlsafe(32)
        th = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        exp = datetime.utcnow() + timedelta(hours=1)
        cursor.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (int(user["id"]), th, exp),
        )
        conn.commit()
        if os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
            msg["dev_reset_token"] = raw
        return jsonify(msg)
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/password-reset/complete", methods=["POST"])
def auth_password_reset_complete():
    data = request.json or {}
    raw = (data.get("token") or "").strip()
    new_pw = data.get("new_password") or data.get("password") or ""
    if not raw or not new_pw:
        return jsonify({"error": "token and new_password are required"}), 400
    if len(str(new_pw)) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400
    th = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_password_reset_tokens_table(cursor)
        cursor.execute(
            """
            SELECT id, user_id FROM password_reset_tokens
            WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > NOW()
            LIMIT 1
            """,
            (th,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Invalid or expired token"}), 400
        new_hash = generate_password_hash(new_pw)
        uid = int(row["user_id"])
        if table_has_column(cursor, "users", "updated_at"):
            cursor.execute(
                "UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s",
                (new_hash, uid),
            )
        else:
            cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, uid))
        cursor.execute(
            "UPDATE password_reset_tokens SET consumed_at = NOW() WHERE id = %s",
            (int(row["id"]),),
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/me/notification-preferences", methods=["GET", "PUT"])
def auth_me_notification_preferences():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me = current_user_from_token(cursor)
        if not me:
            return jsonify({"error": "Unauthorized"}), 401
        uid = int(me["user_id"])
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_notification_preferences (
              user_id INT NOT NULL PRIMARY KEY,
              email_out TINYINT(1) NOT NULL DEFAULT 1,
              email_in TINYINT(1) NOT NULL DEFAULT 0,
              push_out TINYINT(1) NOT NULL DEFAULT 1,
              push_in TINYINT(1) NOT NULL DEFAULT 0,
              sms_out TINYINT(1) NOT NULL DEFAULT 1,
              sms_in TINYINT(1) NOT NULL DEFAULT 0,
              whatsapp_out TINYINT(1) NOT NULL DEFAULT 0,
              whatsapp_in TINYINT(1) NOT NULL DEFAULT 0,
              updated_at DATETIME NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        if table_exists(cursor, "user_notification_preferences"):
            if table_has_column(cursor, "user_notification_preferences", "sms_out") and not table_has_column(
                cursor, "user_notification_preferences", "whatsapp_out"
            ):
                try:
                    cursor.execute(
                        "ALTER TABLE user_notification_preferences ADD COLUMN whatsapp_out TINYINT(1) NOT NULL DEFAULT 0"
                    )
                    cursor.execute(
                        "ALTER TABLE user_notification_preferences ADD COLUMN whatsapp_in TINYINT(1) NOT NULL DEFAULT 0"
                    )
                    cursor.execute(
                        """
                        UPDATE user_notification_preferences
                        SET whatsapp_out = COALESCE(sms_out, 0), whatsapp_in = COALESCE(sms_in, 0)
                        """
                    )
                except Exception:
                    pass
            if table_has_column(cursor, "user_notification_preferences", "whatsapp_out") and not table_has_column(
                cursor, "user_notification_preferences", "sms_out"
            ):
                try:
                    cursor.execute(
                        "ALTER TABLE user_notification_preferences ADD COLUMN sms_out TINYINT(1) NOT NULL DEFAULT 1 AFTER push_in"
                    )
                    cursor.execute(
                        "ALTER TABLE user_notification_preferences ADD COLUMN sms_in TINYINT(1) NOT NULL DEFAULT 0 AFTER sms_out"
                    )
                except Exception:
                    pass
        if request.method == "GET":
            if not table_has_column(cursor, "user_notification_preferences", "whatsapp_out"):
                cursor.execute(
                    """
                    SELECT email_out, email_in, push_out, push_in
                    FROM user_notification_preferences WHERE user_id = %s
                    """,
                    (uid,),
                )
                row = cursor.fetchone()
                if not row:
                    return jsonify(
                        {
                            "email_out": True,
                            "email_in": False,
                            "push_out": True,
                            "push_in": False,
                            "whatsapp_out": False,
                            "whatsapp_in": False,
                        }
                    )
                out = json_safe(row)
                out["whatsapp_out"] = False
                out["whatsapp_in"] = False
                return jsonify(out)
            has_sms = table_has_column(cursor, "user_notification_preferences", "sms_out")
            sel = (
                "email_out, email_in, push_out, push_in, sms_out, sms_in, whatsapp_out, whatsapp_in"
                if has_sms
                else "email_out, email_in, push_out, push_in, whatsapp_out, whatsapp_in"
            )
            cursor.execute(
                f"SELECT {sel} FROM user_notification_preferences WHERE user_id = %s",
                (uid,),
            )
            row = cursor.fetchone()
            if not row:
                base = {
                    "email_out": True,
                    "email_in": False,
                    "push_out": True,
                    "push_in": False,
                    "whatsapp_out": False,
                    "whatsapp_in": False,
                }
                if has_sms:
                    base["sms_out"] = True
                    base["sms_in"] = False
                return jsonify(base)
            return jsonify(json_safe(row))
        body = request.json or {}
        if not table_has_column(cursor, "user_notification_preferences", "whatsapp_out"):
            return jsonify({"error": "notification preferences schema is upgrading; retry shortly"}), 503
        has_sms = table_has_column(cursor, "user_notification_preferences", "sms_out")
        wa_out = body.get("whatsapp_out")
        if wa_out is None and not has_sms and "sms_out" in body:
            wa_out = body.get("sms_out")
        wa_in = body.get("whatsapp_in")
        if wa_in is None and not has_sms and "sms_in" in body:
            wa_in = body.get("sms_in")
        if has_sms:
            cursor.execute(
                """
                INSERT INTO user_notification_preferences
                  (user_id, email_out, email_in, push_out, push_in, sms_out, sms_in, whatsapp_out, whatsapp_in, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                ON DUPLICATE KEY UPDATE
                  email_out = VALUES(email_out),
                  email_in = VALUES(email_in),
                  push_out = VALUES(push_out),
                  push_in = VALUES(push_in),
                  sms_out = VALUES(sms_out),
                  sms_in = VALUES(sms_in),
                  whatsapp_out = VALUES(whatsapp_out),
                  whatsapp_in = VALUES(whatsapp_in),
                  updated_at = NOW()
                """,
                (
                    uid,
                    1 if body.get("email_out", True) else 0,
                    1 if body.get("email_in") else 0,
                    1 if body.get("push_out", True) else 0,
                    1 if body.get("push_in") else 0,
                    1 if body.get("sms_out", True) else 0,
                    1 if body.get("sms_in") else 0,
                    1 if wa_out else 0,
                    1 if wa_in else 0,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_notification_preferences
                  (user_id, email_out, email_in, push_out, push_in, whatsapp_out, whatsapp_in, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
                ON DUPLICATE KEY UPDATE
                  email_out = VALUES(email_out),
                  email_in = VALUES(email_in),
                  push_out = VALUES(push_out),
                  push_in = VALUES(push_in),
                  whatsapp_out = VALUES(whatsapp_out),
                  whatsapp_in = VALUES(whatsapp_in),
                  updated_at = NOW()
                """,
                (
                    uid,
                    1 if body.get("email_out", True) else 0,
                    1 if body.get("email_in") else 0,
                    1 if body.get("push_out", True) else 0,
                    1 if body.get("push_in") else 0,
                    1 if wa_out else 0,
                    1 if wa_in else 0,
                ),
            )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/notify/webhook/sms", methods=["POST"])
def notify_webhook_sms_inbound_stub():
    """Legacy inbound SMS hook (unused if you standardize on WhatsApp + push)."""
    payload = request.get_json(silent=True) or {}
    app.logger.info("notify.sms.inbound stub: keys=%s", list(payload.keys())[:12])
    return jsonify({"ok": True, "received": True})


@app.route("/api/notify/webhook/whatsapp", methods=["POST"])
def notify_webhook_whatsapp_inbound_stub():
    """Inbound WhatsApp (Meta Cloud API or Twilio WhatsApp): verify signature in production; stub logs only."""
    payload = request.get_json(silent=True) or {}
    app.logger.info("notify.whatsapp.inbound stub: keys=%s", list(payload.keys())[:12])
    return jsonify({"ok": True, "received": True})


@app.route("/auth/me", methods=["GET"])
def auth_me():
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        me = current_user_from_token(cursor)
        if not me:
            return jsonify({"error": "Unauthorized"}), 401
        roles = fetch_user_roles(cursor, me["user_id"])
        cursor.execute("UPDATE auth_sessions SET last_seen_at = NOW() WHERE id = %s", (me["session_id"],))
        conn.commit()
        out = {
            "id": me["user_id"],
            "username": me["username"],
            "display_name": me.get("display_name") or me["username"],
            "roles": roles,
        }
        rs = {str(r).upper() for r in roles}
        tenant_portal = bool(rs & TENANT_PORTAL_ROLES)
        if me.get("organization_id") is not None:
            oid = int(me["organization_id"])
            out["organization_id"] = oid
            if tenant_portal:
                out["tenant_modules"] = load_tenant_modules_map(cursor, oid)
        if me.get("organization_slug"):
            out["organization_slug"] = me["organization_slug"]
        if me.get("organization_name"):
            out["organization_name"] = me["organization_name"]
        if me.get("organization_logo_url"):
            out["organization_logo_url"] = rewrite_org_logo_url_for_client(
                me["organization_logo_url"]
            )
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.route("/auth/me/password", methods=["PUT"])
def auth_me_password_put():
    data = request.json or {}
    current_pw = data.get("current_password") or data.get("current") or ""
    new_pw = data.get("new_password") or data.get("password") or ""
    if not current_pw or not new_pw:
        return jsonify({"error": "current_password and new_password are required"}), 400
    if len(str(new_pw)) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me = current_user_from_token(cursor)
        if not me:
            return jsonify({"error": "Unauthorized"}), 401
        cursor.execute(
            "SELECT id, password_hash FROM users WHERE id=%s LIMIT 1",
            (int(me["user_id"]),),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        stored_hash = row.get("password_hash") or ""
        ok = False
        if stored_hash.startswith(("pbkdf2:", "scrypt:")):
            try:
                ok = check_password_hash(stored_hash, current_pw)
            except Exception:
                ok = False
        else:
            ok = stored_hash == current_pw
        if stored_hash and not ok:
            return jsonify({"error": "Current password is incorrect"}), 400
        if not stored_hash and current_pw:
            return jsonify({"error": "Current password is incorrect"}), 400
        new_hash = generate_password_hash(new_pw)
        if table_has_column(cursor, "users", "updated_at"):
            cursor.execute(
                "UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s",
                (new_hash, int(me["user_id"])),
            )
        else:
            cursor.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (new_hash, int(me["user_id"])),
            )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


def _is_safe_logo_url(url: str) -> bool:
    if not url or len(url) > 768:
        return False
    u = url.strip().lower()
    if u.startswith("https://"):
        return True
    if u.startswith("http://localhost") or u.startswith("http://127.0.0.1"):
        return True
    return False


@app.route("/api/public/organization/branding", methods=["GET"])
def public_organization_branding():
    """Public tenant branding for the login screen (slug is not secret)."""
    slug = (request.args.get("slug") or "").strip().lower()
    if not slug:
        return jsonify({"error": "slug is required"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "Organizations not configured"}), 503
        if table_has_column(cursor, "organizations", "logo_url"):
            cursor.execute(
                """
                SELECT slug, display_name, logo_url
                FROM organizations
                WHERE LOWER(slug) = %s AND active = 1
                LIMIT 1
                """,
                (slug,),
            )
        else:
            cursor.execute(
                """
                SELECT slug, display_name
                FROM organizations
                WHERE LOWER(slug) = %s AND active = 1
                LIMIT 1
                """,
                (slug,),
            )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Unknown organization"}), 404
        out = {"slug": row["slug"], "display_name": row["display_name"]}
        if "logo_url" in row:
            out["logo_url"] = rewrite_org_logo_url_for_client(row.get("logo_url"))
        return jsonify(out)
    finally:
        cursor.close()
        conn.close()


@app.route("/api/public/organization/active-clock-ins", methods=["GET"])
def public_organization_active_clock_ins():
    """Shared kiosk lock screen: who is clocked in now (names only; slug is not secret)."""
    slug = (request.args.get("slug") or "").strip().lower()
    if not slug:
        return jsonify({"error": "slug is required"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if not table_exists(cursor, "organizations"):
            return jsonify({"people": []})
        cursor.execute(
            """
            SELECT id FROM organizations
            WHERE LOWER(slug) = %s AND active = 1
            LIMIT 1
            """,
            (slug,),
        )
        org = cursor.fetchone()
        if not org:
            return jsonify({"error": "Unknown organization"}), 404
        oid = int(org["id"])
        if not table_exists(cursor, "shift_sessions") or not table_has_column(
            cursor, "shift_sessions", "organization_id"
        ):
            return jsonify({"people": []})

        open_break_sql = """
            EXISTS (
              SELECT 1 FROM shift_breaks b
              WHERE b.shift_session_id = s.id AND b.break_end_at IS NULL
            )
        """

        if payroll_profiles_active(conn):
            cursor.execute(
                f"""
                SELECT s.user_id, s.clock_in_at,
                  TRIM(CONCAT(COALESCE(pp.first_name,''), ' ', COALESCE(pp.last_name,''))) AS name_parts,
                  u.display_name, u.username,
                  ({open_break_sql}) AS on_break
                FROM shift_sessions s
                INNER JOIN users u ON u.id = s.user_id
                LEFT JOIN payroll_profiles pp ON pp.user_id = s.user_id
                WHERE s.organization_id = %s AND s.status = 'active'
                ORDER BY s.clock_in_at ASC
                """,
                (oid,),
            )
        else:
            ta_join = ""
            if table_exists(cursor, "ta_users") and table_has_column(cursor, "ta_users", "washpro_user_id"):
                ta_join = "LEFT JOIN ta_users t ON t.washpro_user_id = u.id"
                name_expr = (
                    "TRIM(CONCAT(COALESCE(t.first_name,''), ' ', COALESCE(t.last_name,''))) AS name_parts"
                )
            else:
                name_expr = "'' AS name_parts"
            cursor.execute(
                f"""
                SELECT s.user_id, s.clock_in_at,
                  {name_expr},
                  u.display_name, u.username,
                  ({open_break_sql}) AS on_break
                FROM shift_sessions s
                INNER JOIN users u ON u.id = s.user_id
                {ta_join}
                WHERE s.organization_id = %s AND s.status = 'active'
                ORDER BY s.clock_in_at ASC
                """,
                (oid,),
            )

        rows = cursor.fetchall() or []
        people = []
        for r in rows:
            raw = (r.get("name_parts") or "").strip()
            disp = raw if raw else (r.get("display_name") or r.get("username") or "User")
            people.append(
                {
                    "user_id": int(r["user_id"]),
                    "display_name": disp.strip() or "User",
                    "clock_in_at": json_safe(r.get("clock_in_at")),
                    "on_break": bool(r.get("on_break")),
                }
            )
        return jsonify({"people": people})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/organization", methods=["GET"])
def auth_organization_get():
    """Tenant administrator: profile for own organization only (not super-admin shell)."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, code = require_admin(cursor)
        if err:
            return err, code
        oid = me.get("organization_id")
        if not oid or not table_exists(cursor, "organizations"):
            return jsonify({"error": "No organization"}), 400
        sel = _organizations_public_columns_sql(cursor)
        cursor.execute(f"SELECT {sel} FROM organizations WHERE id = %s LIMIT 1", (int(oid),))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        payload = dict(row)
        if payload.get("logo_url"):
            payload["logo_url"] = rewrite_org_logo_url_for_client(payload["logo_url"])
        return jsonify(payload)
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/organization", methods=["PUT"])
def auth_organization_put():
    data = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, code = require_admin(cursor)
        if err:
            return err, code
        oid = me.get("organization_id")
        if not oid:
            return jsonify({"error": "No organization"}), 400
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "Organizations not configured"}), 503
        display_name = (data.get("display_name") or "").strip()
        logo_url = data.get("logo_url")
        fields = []
        vals = []
        if "display_name" in data and display_name:
            fields.append("display_name=%s")
            vals.append(display_name[:200])
        if logo_url is not None:
            if not table_has_column(cursor, "organizations", "logo_url"):
                return jsonify({"error": "Run backend/sql/organizations_branding_v1.sql"}), 400
            logo_url = str(logo_url).strip()
            if logo_url:
                if not _is_safe_logo_url(logo_url):
                    return jsonify(
                        {"error": "logo_url must be https:// or http://localhost (dev)"}
                    ), 400
            fields.append("logo_url=%s")
            vals.append(logo_url if logo_url else None)
        address = data.get("address")
        if address is not None and table_has_column(cursor, "organizations", "address"):
            fields.append("address=%s")
            vals.append(str(address).strip()[:4000] or None)
        phone = data.get("phone")
        if phone is not None and table_has_column(cursor, "organizations", "phone"):
            fields.append("phone=%s")
            vals.append(str(phone).strip()[:64] or None)
        email = data.get("email")
        if email is not None and table_has_column(cursor, "organizations", "email"):
            em = str(email).strip()[:255]
            fields.append("email=%s")
            vals.append(em or None)
        for json_key, col, maxlen in (
            ("employer_legal_name", "employer_legal_name", 255),
            ("employer_street", "employer_street", 255),
            ("employer_apt", "employer_apt", 64),
            ("employer_city", "employer_city", 128),
            ("employer_state", "employer_state", 32),
            ("employer_zip", "employer_zip", 20),
            ("employer_ein", "employer_ein", 32),
        ):
            if json_key in data and table_has_column(cursor, "organizations", col):
                raw = data.get(json_key)
                if raw is None:
                    fields.append(f"{col}=%s")
                    vals.append(None)
                else:
                    fields.append(f"{col}=%s")
                    vals.append(str(raw).strip()[:maxlen] or None)
        if not fields:
            return jsonify({"error": "No fields to update"}), 400
        vals.append(int(oid))
        cursor.execute(
            f"UPDATE organizations SET {', '.join(fields)} WHERE id=%s AND active=1",
            vals,
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/organization/logo", methods=["POST"])
def auth_organization_logo_upload():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, code = require_admin(cursor)
        if err:
            return err, code
        oid = me.get("organization_id")
        if not oid:
            return jsonify({"error": "No organization"}), 400
        if not table_exists(cursor, "organizations") or not table_has_column(
            cursor, "organizations", "logo_url"
        ):
            return jsonify({"error": "Run backend/sql/organizations_branding_v1.sql"}), 400
        if "file" not in request.files:
            return jsonify({"error": "file field required"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"error": "Empty file"}), 400
        raw = f.read()
        if len(raw) > 2 * 1024 * 1024:
            return jsonify({"error": "File too large (max 2 MB)"}), 400
        ext = (f.filename.rsplit(".", 1)[-1] if "." in f.filename else "").lower()
        if ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
            return jsonify({"error": "Allowed types: png, jpg, jpeg, webp, gif"}), 400
        ct = _infer_content_type(f.filename)
        url = None
        blob_err = None
        # Do not gate on ORDER_TICKET_STORAGE_MODE: tickets may use "db" while org logos still use Blob.
        if os.getenv("AZURE_STORAGE_CONNECTION_STRING") and BlobServiceClient is not None:
            try:
                cc = _ensure_blob_container()
                if cc is not None:
                    blob_name = f"org-logos/{int(oid)}/{uuid.uuid4().hex}.{ext}"
                    bc = cc.get_blob_client(blob_name)
                    kwargs = {}
                    if ContentSettings is not None:
                        kwargs["content_settings"] = ContentSettings(content_type=ct)
                    bc.upload_blob(raw, overwrite=True, **kwargs)
                    url = bc.url
            except Exception as ex:
                blob_err = str(ex)[:500]
        loc_err = None
        if not url:
            try:
                org_dir = os.path.join(_local_org_logo_root(), str(int(oid)))
                os.makedirs(org_dir, exist_ok=True)
                fn = f"{uuid.uuid4().hex}.{ext}"
                fp = os.path.join(org_dir, fn)
                with open(fp, "wb") as out:
                    out.write(raw)
                base = _public_api_base_for_uploads()
                url = f"{base}/media/org-logos/{int(oid)}/{fn}"
            except Exception as loc_ex:
                loc_err = str(loc_ex)[:300]
        if not url:
            msg = (
                "Could not store logo. For Azure: check AZURE_STORAGE_CONNECTION_STRING and container access. "
                "For local dev: set PUBLIC_API_BASE to your API URL, or set logo_url manually via Organization."
            )
            if blob_err:
                msg = f"{msg} Azure error: {blob_err}"
            elif loc_err:
                msg = f"{msg} Local error: {loc_err}"
            return jsonify({"error": msg}), 503
        cursor.execute(
            "UPDATE organizations SET logo_url=%s WHERE id=%s AND active=1",
            (url, int(oid)),
        )
        conn.commit()
        return jsonify({"ok": True, "logo_url": url})
    finally:
        cursor.close()
        conn.close()


@app.route("/media/org-logos/<int:org_id>/<path:filename>", methods=["GET"])
def serve_local_org_logo(org_id, filename):
    """Public read: local instance/org_logos, or same path in Azure Blob if disk was wiped (deploy)."""
    safe = os.path.basename(filename)
    if not _ORG_LOGO_FILENAME_RE.match(safe):
        return jsonify({"error": "Not found"}), 404
    root = os.path.join(_local_org_logo_root(), str(int(org_id)))
    fp = os.path.join(root, safe)
    if os.path.isfile(fp):
        return send_from_directory(root, safe, max_age=86400)
    cc = _ensure_blob_container()
    if cc is not None:
        blob_name = f"org-logos/{int(org_id)}/{safe}"
        try:
            bc = cc.get_blob_client(blob_name)
            data = bc.download_blob().readall()
            ct = _infer_content_type(safe)
            return Response(
                data,
                mimetype=ct,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except Exception:
            pass
    return jsonify({"error": "Not found"}), 404


@app.route("/auth/platform/organizations", methods=["GET"])
def auth_platform_organizations_list():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "organizations"):
            return jsonify({"organizations": []})
        sel = _organizations_public_columns_sql(cursor)
        cursor.execute(f"SELECT {sel} FROM organizations ORDER BY id ASC")
        rows = cursor.fetchall() or []
        for r in rows:
            if r.get("logo_url"):
                r["logo_url"] = rewrite_org_logo_url_for_client(r["logo_url"])
        return jsonify({"organizations": rows})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations", methods=["POST"])
def auth_platform_organizations_create():
    data = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "Organizations not configured"}), 503
        slug = normalize_organization_slug(data.get("slug"))
        display_name = (data.get("display_name") or "").strip()
        if not slug:
            return jsonify({"error": "slug is required (letters, digits, hyphen)"}), 400
        if not display_name:
            return jsonify({"error": "display_name is required"}), 400
        display_name = display_name[:200]
        cursor.execute(
            "SELECT id FROM organizations WHERE slug = %s LIMIT 1",
            (slug,),
        )
        if cursor.fetchone():
            return jsonify({"error": "An organization with this slug already exists"}), 409
        cursor.execute(
            """
            INSERT INTO organizations (slug, display_name, active)
            VALUES (%s, %s, 1)
            """,
            (slug, display_name),
        )
        conn.commit()
        new_id = cursor.lastrowid
        bootstrap_organization_supporting_rows(cursor, conn, int(new_id), slug)
        sel = _organizations_public_columns_sql(cursor)
        cursor.execute(f"SELECT {sel} FROM organizations WHERE id = %s LIMIT 1", (int(new_id),))
        row = cursor.fetchone()
        org_payload = dict(row) if row else row
        if org_payload and org_payload.get("logo_url"):
            org_payload["logo_url"] = rewrite_org_logo_url_for_client(org_payload["logo_url"])
        return jsonify({"organization": org_payload}), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations/<int:org_id>", methods=["PUT"])
def auth_platform_organizations_update(org_id):
    """Super admin: tenant record (not slug). Includes contact fields for onboarding."""
    data = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "Organizations not configured"}), 503
        cursor.execute("SELECT id FROM organizations WHERE id = %s LIMIT 1", (int(org_id),))
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        display_name = data.get("display_name")
        active = data.get("active")
        fields = []
        vals = []
        if display_name is not None:
            dn = str(display_name).strip()[:200]
            if not dn:
                return jsonify({"error": "display_name cannot be empty"}), 400
            fields.append("display_name=%s")
            vals.append(dn)
        if active is not None:
            fields.append("active=%s")
            vals.append(1 if bool(active) else 0)
        if data.get("address") is not None and table_has_column(cursor, "organizations", "address"):
            fields.append("address=%s")
            vals.append(str(data.get("address") or "").strip()[:4000] or None)
        if data.get("phone") is not None and table_has_column(cursor, "organizations", "phone"):
            fields.append("phone=%s")
            vals.append(str(data.get("phone") or "").strip()[:64] or None)
        if data.get("email") is not None and table_has_column(cursor, "organizations", "email"):
            fields.append("email=%s")
            vals.append(str(data.get("email") or "").strip()[:255] or None)
        if data.get("logo_url") is not None and table_has_column(cursor, "organizations", "logo_url"):
            logo_url = str(data.get("logo_url") or "").strip()
            if logo_url and not _is_safe_logo_url(logo_url):
                return jsonify(
                    {"error": "logo_url must be https:// or http://localhost (dev)"}
                ), 400
            fields.append("logo_url=%s")
            vals.append(logo_url if logo_url else None)
        if not fields:
            return jsonify({"error": "No fields to update"}), 400
        vals.append(int(org_id))
        cursor.execute(
            f"UPDATE organizations SET {', '.join(fields)} WHERE id = %s",
            vals,
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations/<int:org_id>", methods=["DELETE"])
def auth_platform_organizations_deactivate(org_id):
    """Soft-off a tenant (active=0). Logins for that org stop; data is retained."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "organizations"):
            return jsonify({"error": "Organizations not configured"}), 503
        cursor.execute("SELECT id, slug FROM organizations WHERE id = %s LIMIT 1", (int(org_id),))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        cursor.execute(
            "UPDATE organizations SET active = 0 WHERE id = %s",
            (int(org_id),),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations/<int:org_id>/logo", methods=["POST"])
def auth_platform_organization_logo_upload(org_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "organizations") or not table_has_column(
            cursor, "organizations", "logo_url"
        ):
            return jsonify({"error": "Run backend/sql/organizations_branding_v1.sql"}), 400
        cursor.execute("SELECT id FROM organizations WHERE id=%s LIMIT 1", (int(org_id),))
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        if "file" not in request.files:
            return jsonify({"error": "file field required"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"error": "Empty file"}), 400
        raw = f.read()
        if len(raw) > 2 * 1024 * 1024:
            return jsonify({"error": "File too large (max 2 MB)"}), 400
        ext = (f.filename.rsplit(".", 1)[-1] if "." in f.filename else "").lower()
        if ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
            return jsonify({"error": "Allowed types: png, jpg, jpeg, webp, gif"}), 400
        ct = _infer_content_type(f.filename)
        url = None
        blob_err = None
        if os.getenv("AZURE_STORAGE_CONNECTION_STRING") and BlobServiceClient is not None:
            try:
                cc = _ensure_blob_container()
                if cc is not None:
                    blob_name = f"org-logos/{int(org_id)}/{uuid.uuid4().hex}.{ext}"
                    bc = cc.get_blob_client(blob_name)
                    kwargs = {}
                    if ContentSettings is not None:
                        kwargs["content_settings"] = ContentSettings(content_type=ct)
                    bc.upload_blob(raw, overwrite=True, **kwargs)
                    url = bc.url
            except Exception as ex:
                blob_err = str(ex)[:500]
        if not url:
            try:
                org_dir = os.path.join(_local_org_logo_root(), str(int(org_id)))
                os.makedirs(org_dir, exist_ok=True)
                fn = f"{uuid.uuid4().hex}.{ext}"
                fp = os.path.join(org_dir, fn)
                with open(fp, "wb") as out:
                    out.write(raw)
                base = _public_api_base_for_uploads()
                url = f"{base}/media/org-logos/{int(org_id)}/{fn}"
            except Exception as loc_ex:
                msg = (
                    "Could not store logo. For Azure: verify AZURE_STORAGE_CONNECTION_STRING and container name; "
                    "for local files set PUBLIC_API_BASE to your API origin (e.g. http://127.0.0.1:8000)."
                )
                if blob_err:
                    msg = f"{msg} Azure error: {blob_err}"
                else:
                    msg = f"{msg} Local error: {str(loc_ex)[:300]}"
                return jsonify({"error": msg}), 503
        cursor.execute(
            "UPDATE organizations SET logo_url=%s WHERE id=%s",
            (url, int(org_id)),
        )
        conn.commit()
        return jsonify({"ok": True, "logo_url": url})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations/<int:org_id>/entitlements", methods=["GET"])
def auth_platform_entitlements_get(org_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        cursor.execute("SELECT id FROM organizations WHERE id = %s LIMIT 1", (int(org_id),))
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        return jsonify({"modules": load_tenant_modules_map(cursor, org_id)})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/organizations/<int:org_id>/entitlements", methods=["PUT"])
def auth_platform_entitlements_put(org_id):
    body = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_exists(cursor, "tenant_entitlements"):
            return jsonify({"error": "Run backend/sql/super_admin_entitlements_v1.sql"}), 503
        cursor.execute("SELECT id FROM organizations WHERE id = %s LIMIT 1", (int(org_id),))
        if not cursor.fetchone():
            return jsonify({"error": "Not found"}), 404
        modules = body.get("modules")
        if not isinstance(modules, dict):
            return jsonify({"error": "modules object required"}), 400
        for key, val in modules.items():
            k = str(key or "").strip()
            if k not in TENANT_MODULE_KEYS:
                return jsonify({"error": f"Unknown module_key: {k}"}), 400
            en = 1 if bool(val) else 0
            cursor.execute(
                """
                INSERT INTO tenant_entitlements (organization_id, module_key, enabled)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE enabled = VALUES(enabled)
                """,
                (int(org_id), k, en),
            )
        conn.commit()
        return jsonify({"ok": True, "modules": load_tenant_modules_map(cursor, org_id)})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/permission-matrix", methods=["GET"])
def auth_platform_permission_matrix():
    """SUPER_ADMIN: permission catalog + roles with organization_id = 0 (platform templates)."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if table_has_column(cursor, "permissions", "route_key"):
            cursor.execute(
                """
                SELECT id, perm_key, description, route_key, route_label,
                       section_key, section_label, resource_key, resource_label,
                       action_key, sort_order
                FROM permissions
                ORDER BY route_key, section_key, resource_key, sort_order, perm_key
                """
            )
        else:
            cursor.execute("SELECT id, perm_key, description FROM permissions ORDER BY perm_key")
        perms = [json_safe(x) for x in cursor.fetchall()]
        for p in perms:
            if not p.get("route_key"):
                pk = p.get("perm_key") or ""
                bits = pk.split(".")
                p["route_key"] = bits[0] if bits else "general"
                p["route_label"] = p["route_key"].replace("_", " ").title()
                p["section_key"] = bits[1] if len(bits) > 1 else ""
                p["section_label"] = (
                    p["section_key"].replace("_", " ").title() if p["section_key"] else "General"
                )
                p["resource_key"] = ""
                p["resource_label"] = ""
                p["action_key"] = bits[-1] if len(bits) > 1 else "view"
                p["sort_order"] = 0
        hierarchy = _build_permission_hierarchy(perms)
        if not table_has_column(cursor, "roles", "organization_id"):
            return jsonify({"error": "Multitenancy roles not configured"}), 503
        cursor.execute(
            """
            SELECT id, code, name, organization_id, is_system
            FROM roles
            WHERE organization_id = 0 OR organization_id IS NULL
            ORDER BY is_system DESC, code
            """
        )
        roles = cursor.fetchall()
        role_ids = [int(r["id"]) for r in roles]
        role_map = {}
        if role_ids:
            ph = ",".join(["%s"] * len(role_ids))
            cursor.execute(
                f"""
                SELECT rp.role_id, p.perm_key
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                WHERE rp.role_id IN ({ph})
                """,
                role_ids,
            )
            for row in cursor.fetchall():
                role_map.setdefault(row["role_id"], []).append(row["perm_key"])
        return jsonify(
            {
                "permissions": perms,
                "hierarchy": hierarchy,
                "roles": [json_safe(x) for x in roles],
                "role_permissions": {str(k): v for k, v in role_map.items()},
            }
        )
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/roles", methods=["POST"])
def auth_platform_roles_create():
    data = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_has_column(cursor, "roles", "organization_id"):
            return jsonify({"error": "Multitenancy roles not configured"}), 503
        rcode = _sanitize_role_code(data.get("code") or "")
        name = (data.get("name") or "").strip() or rcode.replace("_", " ").title()
        cursor.execute(
            """
            SELECT id FROM roles
            WHERE (organization_id = 0 OR organization_id IS NULL) AND code = %s
            LIMIT 1
            """,
            (rcode,),
        )
        if cursor.fetchone():
            return jsonify({"error": "Role code already exists for platform templates"}), 409
        cursor.execute(
            """
            INSERT INTO roles (organization_id, code, name, is_system)
            VALUES (0, %s, %s, 0)
            """,
            (rcode, name),
        )
        conn.commit()
        rid = cursor.lastrowid
        return jsonify({"ok": True, "id": rid, "code": rcode, "name": name})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/roles/<int:role_id>", methods=["DELETE"])
def auth_platform_roles_delete(role_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_has_column(cursor, "roles", "organization_id"):
            return jsonify({"error": "Multitenancy roles not configured"}), 503
        cursor.execute(
            "SELECT id, code, organization_id, is_system FROM roles WHERE id = %s",
            (int(role_id),),
        )
        meta = cursor.fetchone()
        if not meta:
            return jsonify({"error": "Role not found"}), 404
        if not _role_is_platform_template(meta):
            return jsonify(
                {"error": "Not a platform template role (tenant-scoped roles are edited per tenant)"}
            ), 403
        if as_bool(meta.get("is_system"), default=False):
            return jsonify({"error": "Cannot delete system roles"}), 403
        if table_exists(cursor, "ta_users") and table_has_column(cursor, "ta_users", "role_id"):
            cursor.execute("SELECT COUNT(*) AS n FROM ta_users WHERE role_id=%s", (role_id,))
            n = (cursor.fetchone() or {}).get("n", 0) or 0
            if n:
                return jsonify({"error": f"Role is assigned to {n} TA user(s); reassign first"}), 409
        if table_exists(cursor, "user_roles"):
            cursor.execute("SELECT COUNT(*) AS n FROM user_roles WHERE role_id=%s", (role_id,))
            n = (cursor.fetchone() or {}).get("n", 0) or 0
            if n:
                return jsonify({"error": f"Role is assigned to {n} login(s); reassign first"}), 409
        cursor.execute("DELETE FROM roles WHERE id=%s", (role_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/roles/<int:role_id>/permissions", methods=["PUT"])
def auth_platform_role_permissions_put(role_id):
    data = request.json or {}
    keys = data.get("permission_keys")
    if not isinstance(keys, list):
        return jsonify({"error": "permission_keys array required"}), 400
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    c2 = None
    try:
        _, err, code = require_super_admin(cursor)
        if err:
            return err, code
        if not table_has_column(cursor, "roles", "organization_id"):
            return jsonify({"error": "Multitenancy roles not configured"}), 503
        cursor.execute(
            "SELECT id, organization_id FROM roles WHERE id=%s",
            (int(role_id),),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Role not found"}), 404
        if not _role_is_platform_template(row):
            return jsonify(
                {"error": "Not a platform template role (tenant-scoped roles are edited per tenant)"}
            ), 403
        c2 = conn.cursor()
        c2.execute("DELETE FROM role_permissions WHERE role_id=%s", (role_id,))
        for key in keys:
            cursor.execute("SELECT id FROM permissions WHERE perm_key=%s", (key,))
            prow = cursor.fetchone()
            if prow:
                c2.execute(
                    "INSERT IGNORE INTO role_permissions (role_id, permission_id) VALUES (%s,%s)",
                    (role_id, prow["id"]),
                )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        if c2 is not None:
            try:
                c2.close()
            except Exception:
                pass
        cursor.close()
        conn.close()


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    token = get_bearer_token()
    if not token:
        return jsonify({"status": "ok"})
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE auth_sessions SET revoked = TRUE WHERE token = %s", (token,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/roles", methods=["GET"])
def auth_roles():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, status_code = require_admin(cursor)
        if err:
            return err, status_code
        if table_has_column(cursor, "roles", "organization_id"):
            oid_raw = me.get("organization_id")
            if oid_raw is not None and str(oid_raw).strip() != "":
                oid = int(oid_raw)
                cursor.execute(
                    """
                    SELECT id, code, name FROM roles
                    WHERE organization_id = 0 OR organization_id = %s
                    ORDER BY code
                    """,
                    (oid,),
                )
            else:
                cursor.execute("SELECT id, code, name FROM roles ORDER BY code")
        else:
            cursor.execute("SELECT id, code, name FROM roles ORDER BY code")
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/users", methods=["GET", "POST"])
def auth_users():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, status_code = require_admin(cursor)
        if err:
            return err, status_code

        if request.method == "GET":
            if table_has_column(cursor, "users", "organization_id"):
                cursor.execute("""
                    SELECT id, username, display_name, active, created_at, organization_id
                    FROM users
                    WHERE organization_id = %s
                    ORDER BY username
                """, (int(me.get("organization_id") or 1),))
            else:
                cursor.execute("""
                    SELECT id, username, display_name, active, created_at
                    FROM users
                    ORDER BY username
                """)
            users = cursor.fetchall()
            for u in users:
                u["roles"] = fetch_user_roles(cursor, u["id"])
            return jsonify(users)

        data = request.json or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        display_name = (data.get("display_name") or "").strip() or username
        active = bool(data.get("active", True))
        role_codes = [str(r).upper() for r in (data.get("roles") or [])]
        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400

        password_hash = generate_password_hash(password)
        if table_has_column(cursor, "users", "organization_id"):
            oid = int(me.get("organization_id") or 1)
            cursor.execute("""
                INSERT INTO users
                (organization_id, username, password_hash, display_name, active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (oid, username, password_hash, display_name, active))
        else:
            cursor.execute("""
                INSERT INTO users
                (username, password_hash, display_name, active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
            """, (username, password_hash, display_name, active))
        user_id = cursor.lastrowid

        if role_codes:
            tenant_oid = int(me.get("organization_id") or 1) if table_has_column(cursor, "users", "organization_id") else 1
            role_ids, missing = _tenant_resolve_washpro_role_ids(cursor, tenant_oid, role_codes)
            if missing:
                conn.rollback()
                return jsonify({"error": "Unknown role(s): " + ", ".join(missing)}), 400
            for rid in role_ids:
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)", (user_id, rid))

        conn.commit()
        return jsonify({"status": "created", "user_id": user_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/users/<int:user_id>", methods=["GET", "PUT", "DELETE"])
def auth_user_detail(user_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, status_code = require_admin(cursor)
        if err:
            return err, status_code

        if request.method == "GET":
            cursor.execute(
                """
                SELECT id, username, display_name, active, created_at, organization_id, updated_at
                FROM users WHERE id=%s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404
            if table_has_column(cursor, "users", "organization_id"):
                if int(row.get("organization_id") or 0) != int(me.get("organization_id") or 1):
                    return jsonify({"error": "Not found"}), 404
            row["roles"] = fetch_user_roles(cursor, user_id)
            cursor.execute(
                "SELECT geofence_id, is_primary FROM user_geofences WHERE user_id=%s",
                (user_id,),
            )
            gfs = cursor.fetchall() or []
            row["geofence_ids"] = [g["geofence_id"] for g in gfs]
            row["primary_geofence_id"] = next(
                (g["geofence_id"] for g in gfs if g.get("is_primary")), None
            )
            cursor.execute(
                """
                SELECT employment_category_id, effective_from, effective_to
                FROM user_employment_categories WHERE user_id=%s
                """,
                (user_id,),
            )
            row["employment_assignments"] = cursor.fetchall() or []
            if table_exists(cursor, "user_entity_tags"):
                cursor.execute(
                    """
                    SELECT entity_type, entity_key, label
                    FROM user_entity_tags
                    WHERE user_id=%s
                    ORDER BY entity_type, entity_key
                    """,
                    (user_id,),
                )
                row["entity_tags"] = cursor.fetchall() or []
            else:
                row["entity_tags"] = []
            return jsonify(json_safe(row))

        if request.method == "DELETE":
            if me["user_id"] == user_id:
                return jsonify({"error": "Cannot delete your own account"}), 400
            cursor.execute("SELECT id, organization_id FROM users WHERE id=%s", (user_id,))
            victim = cursor.fetchone()
            if not victim:
                return jsonify({"error": "Not found"}), 404
            if table_has_column(cursor, "users", "organization_id"):
                if int(victim.get("organization_id") or 0) != int(me.get("organization_id") or 1):
                    return jsonify({"error": "Not found"}), 404
            # Legacy DBs only: unified payroll uses payroll_profiles.user_id → ON DELETE CASCADE.
            if table_exists(cursor, "ta_users"):
                cursor.execute(
                    "UPDATE ta_users SET washpro_user_id=NULL WHERE washpro_user_id=%s",
                    (user_id,),
                )
            cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
            conn.commit()
            return jsonify({"status": "deleted"})

        data = request.json or {}
        username = (data.get("username") or "").strip()
        display_name = (data.get("display_name") or "").strip()
        active = bool(data.get("active", True))
        password = data.get("password") or ""
        role_codes = [str(r).upper() for r in (data.get("roles") or [])]

        cursor.execute("SELECT id, organization_id FROM users WHERE id=%s", (user_id,))
        target = cursor.fetchone()
        if not target:
            return jsonify({"error": "Not found"}), 404
        if table_has_column(cursor, "users", "organization_id"):
            if int(target.get("organization_id") or 0) != int(me.get("organization_id") or 1):
                return jsonify({"error": "Not found"}), 404
        if not username:
            return jsonify({"error": "username is required"}), 400

        if table_has_column(cursor, "users", "organization_id"):
            cursor.execute(
                "SELECT id FROM users WHERE username=%s AND id!=%s AND organization_id=%s",
                (username, user_id, int(me.get("organization_id") or 1)),
            )
        else:
            cursor.execute(
                "SELECT id FROM users WHERE username=%s AND id!=%s",
                (username, user_id),
            )
        if cursor.fetchone():
            return jsonify({"error": "username already taken"}), 400

        set_parts = [
            "username=%s",
            "display_name=%s",
            "active=%s",
            "updated_at=NOW()",
        ]
        vals = [username, display_name or username, active]
        if password:
            set_parts.append("password_hash=%s")
            vals.append(generate_password_hash(password))
        vals.append(user_id)
        cursor.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id=%s",
            vals,
        )

        cursor.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
        if role_codes:
            tenant_oid = int(me.get("organization_id") or 1) if table_has_column(cursor, "users", "organization_id") else 1
            role_ids, missing = _tenant_resolve_washpro_role_ids(cursor, tenant_oid, role_codes)
            if missing:
                conn.rollback()
                return jsonify({"error": "Unknown role(s): " + ", ".join(missing)}), 400
            for rid in role_ids:
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                    (user_id, rid),
                )

        conn.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/users", methods=["GET"])
def auth_platform_users_search():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        me, err, code = require_super_admin(cursor)
        if err:
            return err, code
        q = (request.args.get("q") or "").strip()
        if not q:
            cursor.execute(
                """
                SELECT id, username, display_name, active, organization_id
                FROM users
                ORDER BY id DESC
                LIMIT 50
                """
            )
        else:
            like = f"%{q}%"
            cursor.execute(
                """
                SELECT id, username, display_name, active, organization_id
                FROM users
                WHERE username LIKE %s OR display_name LIKE %s OR CAST(id AS CHAR) LIKE %s
                ORDER BY id DESC
                LIMIT 50
                """,
                (like, like, like),
            )
        return jsonify(json_safe(cursor.fetchall() or []))
    finally:
        cursor.close()
        conn.close()


@app.route("/auth/platform/users/<int:user_id>", methods=["GET", "PUT"])
def auth_platform_user_detail(user_id):
    if request.method == "GET":
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        try:
            me, err, code = require_super_admin(cursor)
            if err:
                return err, code
            bundle = auth_platform_user_bundle(cursor, conn, user_id)
            if not bundle:
                return jsonify({"error": "Not found"}), 404
            return jsonify(json_safe(bundle))
        finally:
            cursor.close()
            conn.close()

    return _auth_platform_users_put_transaction(user_id)


def _auth_platform_users_put_transaction(user_id):
    data = request.json or {}
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    c_plain = conn.cursor()
    try:
        me, err, code = require_super_admin(cursor)
        if err:
            return err, code
        actor_id = int(me["user_id"])

        conn.autocommit = False
        cursor.execute(
            "SELECT id, username, display_name, active, organization_id FROM users WHERE id=%s FOR UPDATE",
            (user_id,),
        )
        urow = cursor.fetchone()
        if not urow:
            conn.rollback()
            conn.autocommit = True
            return jsonify({"error": "Not found"}), 404

        eff_org = int(urow.get("organization_id") or 1)

        if "organization_id" in data and data["organization_id"] is not None:
            new_oid = int(data["organization_id"])
            cursor.execute("SELECT id FROM organizations WHERE id=%s LIMIT 1", (new_oid,))
            if not cursor.fetchone():
                conn.rollback()
                conn.autocommit = True
                return jsonify({"error": "organization not found"}), 400
            c_plain.execute(
                "UPDATE users SET organization_id=%s, updated_at=NOW() WHERE id=%s",
                (new_oid, user_id),
            )
            eff_org = new_oid
            if table_exists(cursor, "user_entity_tags"):
                c_plain.execute(
                    "UPDATE user_entity_tags SET organization_id=%s WHERE user_id=%s",
                    (new_oid, user_id),
                )

        if "washpro" in data and isinstance(data["washpro"], dict):
            w = data["washpro"]
            username = (w.get("username") or "").strip()
            display_name = (w.get("display_name") or "").strip()
            active = bool(w.get("active", True)) if "active" in w else bool(urow.get("active", True))
            password = (w.get("password") or "").strip()
            if username:
                if table_has_column(cursor, "users", "organization_id"):
                    cursor.execute(
                        """
                        SELECT id FROM users
                        WHERE username=%s AND id!=%s AND organization_id=%s
                        """,
                        (username, user_id, eff_org),
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM users WHERE username=%s AND id!=%s",
                        (username, user_id),
                    )
                if cursor.fetchone():
                    conn.rollback()
                    conn.autocommit = True
                    return jsonify({"error": "username already taken"}), 400
            set_parts = []
            vals = []
            if username:
                set_parts.extend(["username=%s", "display_name=%s", "active=%s", "updated_at=NOW()"])
                vals.extend([username, display_name or username, 1 if active else 0])
            elif "display_name" in w or "active" in w:
                if "display_name" in w:
                    set_parts.append("display_name=%s")
                    vals.append(display_name or urow.get("username"))
                if "active" in w:
                    set_parts.append("active=%s")
                    vals.append(1 if active else 0)
                set_parts.append("updated_at=NOW()")
            if password:
                if not set_parts:
                    set_parts.append("updated_at=NOW()")
                set_parts.append("password_hash=%s")
                vals.append(generate_password_hash(password))
            if set_parts:
                vals.append(user_id)
                c_plain.execute(
                    f"UPDATE users SET {', '.join(set_parts)} WHERE id=%s",
                    vals,
                )
            if "roles" in w:
                role_codes = [str(r).upper() for r in (w.get("roles") or [])]
                rids = _platform_resolve_role_ids(cursor, eff_org, role_codes)
                if rids is None:
                    conn.rollback()
                    conn.autocommit = True
                    return jsonify({"error": "Unknown role code in roles list"}), 400
                c_plain.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
                for rid in rids:
                    c_plain.execute(
                        "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                        (user_id, int(rid)),
                    )

        if payroll_profiles_active(conn) and "payroll" in data and isinstance(data["payroll"], dict):
            p = data["payroll"]
            cursor.execute("SELECT * FROM payroll_profiles WHERE user_id=%s", (user_id,))
            old = cursor.fetchone()
            if not old:
                cursor.execute(
                    "SELECT username, display_name FROM users WHERE id=%s",
                    (user_id,),
                )
                uw = cursor.fetchone()
                ensure_payroll_profile_for_washpro(
                    conn,
                    {
                        "user_id": user_id,
                        "username": (uw or {}).get("username") or "",
                        "display_name": (uw or {}).get("display_name") or "",
                    },
                )
                cursor.execute("SELECT * FROM payroll_profiles WHERE user_id=%s", (user_id,))
                old = cursor.fetchone()
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
                if json_k in p:
                    v = p[json_k]
                    if col in ("rehired", "active"):
                        v = 1 if v else 0
                    fields.append(f"{col}=%s")
                    vals.append(v)
            if "rehire_parent_id" in p:
                v = p["rehire_parent_id"]
                if v in (None, ""):
                    v = None
                else:
                    v = int(v)
                    if v == user_id:
                        conn.rollback()
                        conn.autocommit = True
                        return jsonify({"error": "rehire parent cannot be the same user"}), 400
                    if v is not None:
                        cursor.execute(
                            """
                            SELECT pp.user_id FROM payroll_profiles pp
                            JOIN users u ON u.id = pp.user_id
                            WHERE pp.user_id=%s AND u.organization_id=%s
                            """,
                            (v, eff_org),
                        )
                        if not cursor.fetchone():
                            conn.rollback()
                            conn.autocommit = True
                            return jsonify({"error": "rehire_parent not found"}), 400
                fields.append("rehire_parent_user_id=%s")
                vals.append(v)
            if p.get("password"):
                fields.append("password_hash=%s")
                vals.append(hash_password(p["password"]))
            wp_roles_in_payload = isinstance(data.get("washpro"), dict) and "roles" in data["washpro"]
            if "role_id" in p and p["role_id"] is not None and not wp_roles_in_payload:
                c_plain.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
                c_plain.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (%s,%s)",
                    (user_id, int(p["role_id"])),
                )
            if fields:
                vals.append(user_id)
                c_plain.execute(
                    f"UPDATE payroll_profiles SET {', '.join(fields)} WHERE user_id=%s",
                    vals,
                )

        if "geofence_ids" in data:
            ids = data.get("geofence_ids") or []
            primary_id = data.get("primary_geofence_id")
            for gid in ids:
                cursor.execute(
                    "SELECT 1 FROM geofences WHERE id=%s AND organization_id=%s",
                    (int(gid), eff_org),
                )
                if not cursor.fetchone():
                    conn.rollback()
                    conn.autocommit = True
                    return jsonify({"error": "Invalid geofence"}), 400
            c_plain.execute("DELETE FROM user_geofences WHERE user_id=%s", (user_id,))
            for gid in ids:
                gid_int = int(gid)
                is_p = (
                    1
                    if primary_id is not None and gid_int == int(primary_id)
                    else 0
                )
                c_plain.execute(
                    "INSERT INTO user_geofences (user_id, geofence_id, is_primary) VALUES (%s,%s,%s)",
                    (user_id, gid_int, is_p),
                )

        if "employment_assignments" in data:
            rows = data.get("employment_assignments") or []
            for r in rows:
                cid = int(r["employment_category_id"])
                cursor.execute(
                    "SELECT 1 FROM employment_categories WHERE id=%s AND organization_id=%s",
                    (cid, eff_org),
                )
                if not cursor.fetchone():
                    conn.rollback()
                    conn.autocommit = True
                    return jsonify({"error": "Invalid employment category"}), 400
            c_plain.execute("DELETE FROM user_employment_categories WHERE user_id=%s", (user_id,))
            for r in rows:
                c_plain.execute(
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

        if "entity_tags" in data and table_exists(cursor, "user_entity_tags"):
            tags = data.get("entity_tags")
            if not isinstance(tags, list):
                conn.rollback()
                conn.autocommit = True
                return jsonify({"error": "entity_tags must be an array"}), 400
            c_plain.execute("DELETE FROM user_entity_tags WHERE user_id=%s", (user_id,))
            for t in tags:
                if not isinstance(t, dict):
                    continue
                et = str(t.get("entity_type") or "").strip()[:64]
                ek = str(t.get("entity_key") or "").strip()[:128]
                if not et or not ek:
                    conn.rollback()
                    conn.autocommit = True
                    return jsonify({"error": "Each entity tag needs entity_type and entity_key"}), 400
                lab = str(t.get("label") or "").strip()[:255] or None
                c_plain.execute(
                    """
                    INSERT INTO user_entity_tags (organization_id, user_id, entity_type, entity_key, label)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (eff_org, int(user_id), et, ek, lab),
                )

        write_audit(
            conn,
            actor_id,
            "platform_user",
            user_id,
            "update",
            new=data,
            organization_id=eff_org,
        )
        conn.commit()
        conn.autocommit = True
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        conn.autocommit = True
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            c_plain.close()
        except Exception:
            pass
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Maintenance APIs
# ---------------------------------------------------

@app.route("/maintenance/tasks", methods=["GET", "POST", "PUT", "DELETE"])
def maintenance_tasks_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT id, task_code, task_name, category, active, created_at, updated_at
                FROM maintenance_tasks
                ORDER BY task_name
            """)
            return jsonify(cursor.fetchall())

        if request.method == "DELETE":
            task_id = request.args.get("id")
            if task_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            cursor.execute("DELETE FROM maintenance_tasks WHERE id = %s", (int(task_id),))
            conn.commit()
            return jsonify({"status": "deleted"})

        data = request.json or {}
        task_code = (data.get("task_code") or "").strip().upper()
        task_name = (data.get("task_name") or "").strip()
        category = (data.get("category") or "CLEANING").strip().upper()
        active = bool(data.get("active", True))

        if request.method == "PUT":
            task_id = data.get("id")
            if task_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            if not task_code or not task_name:
                return jsonify({"error": "task_code and task_name are required"}), 400
            cursor.execute("""
                UPDATE maintenance_tasks
                SET task_code = %s, task_name = %s, category = %s, active = %s, updated_at = NOW()
                WHERE id = %s
            """, (task_code, task_name, category, active, int(task_id)))
            conn.commit()
            return jsonify({"status": "updated"})

        if not task_code or not task_name:
            return jsonify({"error": "task_code and task_name are required"}), 400

        cursor.execute("""
            INSERT INTO maintenance_tasks
            (task_code, task_name, category, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
        """, (task_code, task_name, category, active))
        conn.commit()
        return jsonify({"status": "created", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/assignments", methods=["GET", "POST", "PUT", "DELETE"])
def maintenance_assignments_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            status = (request.args.get("status") or "").strip().upper()
            where = ""
            args = []
            if status:
                where = "WHERE a.status = %s"
                args.append(status)
            cursor.execute(f"""
                SELECT
                    a.id,
                    a.task_id,
                    t.task_name,
                    a.assigned_to_employee_id,
                    a.assigned_to_name,
                    a.due_date,
                    a.frequency_type,
                    a.frequency_interval,
                    a.weekdays_csv,
                    a.status,
                    a.notes,
                    a.created_at
                FROM maintenance_assignments a
                JOIN maintenance_tasks t ON t.id = a.task_id
                {where}
                ORDER BY a.due_date ASC, a.id ASC
            """, tuple(args))
            return jsonify(cursor.fetchall())

        if request.method == "DELETE":
            assignment_id = request.args.get("id")
            if assignment_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            cursor.execute("DELETE FROM maintenance_assignments WHERE id = %s", (int(assignment_id),))
            conn.commit()
            return jsonify({"status": "deleted"})

        data = request.json or {}
        task_id = data.get("task_id")
        assigned_to_employee_id = data.get("assigned_to_employee_id")
        assigned_to_name = (data.get("assigned_to_name") or "").strip() or None
        due_date = parse_date_value(data.get("due_date"))
        frequency_type = (data.get("frequency_type") or "ONE_TIME").strip().upper()
        frequency_interval = int(data.get("frequency_interval") or 1)
        weekdays_csv = (data.get("weekdays_csv") or "").strip() or None
        status_value = (data.get("status") or "ASSIGNED").strip().upper()
        notes = (data.get("notes") or "").strip() or None
        created_by = (data.get("created_by") or "admin").strip()

        if request.method == "PUT":
            assignment_id = data.get("id")
            if assignment_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            if task_id in [None, ""] or due_date is None:
                return jsonify({"error": "task_id and due_date are required"}), 400

            cursor.execute("""
                UPDATE maintenance_assignments
                SET
                  task_id = %s,
                  assigned_to_employee_id = %s,
                  assigned_to_name = %s,
                  due_date = %s,
                  frequency_type = %s,
                  frequency_interval = %s,
                  weekdays_csv = %s,
                  status = %s,
                  notes = %s,
                  updated_at = NOW()
                WHERE id = %s
            """, (
                int(task_id),
                int(assigned_to_employee_id) if assigned_to_employee_id not in [None, ""] else None,
                assigned_to_name,
                due_date,
                frequency_type,
                frequency_interval,
                weekdays_csv,
                status_value,
                notes,
                int(assignment_id)
            ))
            conn.commit()
            return jsonify({"status": "updated"})

        if task_id in [None, ""] or due_date is None:
            return jsonify({"error": "task_id and due_date are required"}), 400

        cursor.execute("""
            INSERT INTO maintenance_assignments
            (
              task_id, assigned_to_employee_id, assigned_to_name, due_date,
              frequency_type, frequency_interval, weekdays_csv, status, notes, created_by, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ASSIGNED', %s, %s, NOW(), NOW())
        """, (
            int(task_id),
            int(assigned_to_employee_id) if assigned_to_employee_id not in [None, ""] else None,
            assigned_to_name,
            due_date,
            frequency_type,
            frequency_interval,
            weekdays_csv,
            notes,
            created_by
        ))
        conn.commit()
        return jsonify({"status": "assigned", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/logs", methods=["GET", "POST", "PUT", "DELETE"])
def maintenance_logs_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT
                    l.id,
                    l.assignment_id,
                    l.task_id,
                    t.task_name,
                    l.performed_by_employee_id,
                    l.performed_by_name,
                    l.performed_date,
                    l.start_time,
                    l.end_time,
                    l.pit1_done,
                    l.pit2_done,
                    l.big_pit_done,
                    l.washer_no,
                    l.notes,
                    l.source_type,
                    l.created_at
                FROM maintenance_logs l
                JOIN maintenance_tasks t ON t.id = l.task_id
                ORDER BY l.performed_date DESC, l.id DESC
                LIMIT 500
            """)
            return jsonify(cursor.fetchall())

        if request.method == "DELETE":
            log_id = request.args.get("id")
            if log_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            cursor.execute("DELETE FROM maintenance_logs WHERE id = %s", (int(log_id),))
            conn.commit()
            return jsonify({"status": "deleted"})

        data = request.json or {}
        assignment_id = data.get("assignment_id")
        task_id = data.get("task_id")
        if task_id in [None, ""]:
            return jsonify({"error": "task_id is required"}), 400

        performed_by_employee_id = data.get("performed_by_employee_id")
        performed_by_name = (data.get("performed_by_name") or "").strip()
        performed_date = parse_date_value(data.get("performed_date")) or date.today()
        start_time_raw = (data.get("start_time") or "").strip()
        end_time_raw = (data.get("end_time") or "").strip()
        notes = (data.get("notes") or "").strip() or None
        washer_no = (data.get("washer_no") or "").strip() or None
        source_type = (data.get("source_type") or ("ASSIGNED" if assignment_id else "ADHOC")).strip().upper()

        if not performed_by_name:
            return jsonify({"error": "performed_by_name is required"}), 400

        def parse_dt(s):
            if not s:
                return None
            try:
                t = datetime.strptime(s, "%I:%M %p").time()
                return datetime.combine(performed_date, t)
            except Exception:
                pass
            try:
                t = datetime.strptime(s, "%H:%M").time()
                return datetime.combine(performed_date, t)
            except Exception:
                pass
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

        start_dt = parse_dt(start_time_raw)
        end_dt = parse_dt(end_time_raw)

        if request.method == "PUT":
            log_id = data.get("id")
            if log_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400

            cursor.execute("""
                UPDATE maintenance_logs
                SET
                  assignment_id = %s,
                  task_id = %s,
                  performed_by_employee_id = %s,
                  performed_by_name = %s,
                  performed_date = %s,
                  start_time = %s,
                  end_time = %s,
                  pit1_done = %s,
                  pit2_done = %s,
                  big_pit_done = %s,
                  washer_no = %s,
                  notes = %s,
                  source_type = %s
                WHERE id = %s
            """, (
                int(assignment_id) if assignment_id not in [None, ""] else None,
                int(task_id),
                int(performed_by_employee_id) if performed_by_employee_id not in [None, ""] else None,
                performed_by_name,
                performed_date,
                start_dt,
                end_dt,
                bool(data.get("pit1_done", False)),
                bool(data.get("pit2_done", False)),
                bool(data.get("big_pit_done", False)),
                washer_no,
                notes,
                source_type,
                int(log_id)
            ))
            conn.commit()
            return jsonify({"status": "updated"})

        cursor.execute("""
            INSERT INTO maintenance_logs
            (
              assignment_id, task_id, performed_by_employee_id, performed_by_name, performed_date,
              start_time, end_time, pit1_done, pit2_done, big_pit_done, washer_no, notes, source_type, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            int(assignment_id) if assignment_id not in [None, ""] else None,
            int(task_id),
            int(performed_by_employee_id) if performed_by_employee_id not in [None, ""] else None,
            performed_by_name,
            performed_date,
            start_dt,
            end_dt,
            bool(data.get("pit1_done", False)),
            bool(data.get("pit2_done", False)),
            bool(data.get("big_pit_done", False)),
            washer_no,
            notes,
            source_type
        ))

        if assignment_id not in [None, ""]:
            cursor.execute("UPDATE maintenance_assignments SET status = 'COMPLETED', updated_at = NOW() WHERE id = %s", (int(assignment_id),))

        conn.commit()
        return jsonify({"status": "logged", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/maintenance/agenda", methods=["GET"])
def maintenance_agenda_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                a.id AS assignment_id,
                a.task_id,
                t.task_name,
                a.assigned_to_employee_id,
                a.assigned_to_name,
                a.due_date,
                a.status,
                CASE
                    WHEN a.status = 'COMPLETED' THEN 'DONE'
                    WHEN a.due_date < CURDATE() THEN 'OVERDUE'
                    WHEN a.due_date = CURDATE() THEN 'DUE_TODAY'
                    ELSE 'UPCOMING'
                END AS agenda_state
            FROM maintenance_assignments a
            JOIN maintenance_tasks t ON t.id = a.task_id
            ORDER BY a.due_date ASC, a.id ASC
            LIMIT 500
        """)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Inventory APIs
# ---------------------------------------------------

@app.route("/inventory/items", methods=["GET", "POST", "PUT", "DELETE"])
def inventory_items_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT
                    id, item_name, category, vendor_name, unit_label,
                    reorder_threshold, on_hand_qty, active, created_at, updated_at
                FROM inventory_items
                ORDER BY category, item_name
            """)
            return jsonify(cursor.fetchall())

        if request.method == "PUT":
            data = request.json or {}
            item_id = data.get("id")
            if item_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400

            item_name = (data.get("item_name") or "").strip()
            category = (data.get("category") or "SUPPLY").strip().upper()
            vendor_name = (data.get("vendor_name") or "").strip() or None
            unit_label = (data.get("unit_label") or "unit").strip()
            reorder_threshold = float(data.get("reorder_threshold") or 0)
            on_hand_qty = float(data.get("on_hand_qty") or 0)
            active = bool(data.get("active", True))
            if not item_name:
                return jsonify({"error": "item_name is required"}), 400

            cursor.execute("""
                UPDATE inventory_items
                SET item_name = %s,
                    category = %s,
                    vendor_name = %s,
                    unit_label = %s,
                    reorder_threshold = %s,
                    on_hand_qty = %s,
                    active = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                item_name, category, vendor_name, unit_label,
                reorder_threshold, on_hand_qty, active, int(item_id)
            ))
            conn.commit()
            return jsonify({"status": "updated"})

        if request.method == "DELETE":
            item_id = request.args.get("id")
            if item_id in [None, ""]:
                return jsonify({"error": "id is required"}), 400
            cursor.execute(
                "UPDATE inventory_items SET active = FALSE, updated_at = NOW() WHERE id = %s",
                (int(item_id),)
            )
            conn.commit()
            return jsonify({"status": "removed"})

        data = request.json or {}
        item_name = (data.get("item_name") or "").strip()
        category = (data.get("category") or "SUPPLY").strip().upper()
        vendor_name = (data.get("vendor_name") or "").strip() or None
        unit_label = (data.get("unit_label") or "unit").strip()
        reorder_threshold = float(data.get("reorder_threshold") or 0)
        on_hand_qty = float(data.get("on_hand_qty") or 0)
        active = bool(data.get("active", True))
        if not item_name:
            return jsonify({"error": "item_name is required"}), 400
        cursor.execute("""
            INSERT INTO inventory_items
            (item_name, category, vendor_name, unit_label, reorder_threshold, on_hand_qty, active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (item_name, category, vendor_name, unit_label, reorder_threshold, on_hand_qty, active))
        conn.commit()
        return jsonify({"status": "created", "id": cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


def ensure_inventory_extensions(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_purchase_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            item_id INT NOT NULL,
            requested_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
            ordered_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
            requested_by VARCHAR(100) NULL,
            ordered_by VARCHAR(100) NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ORDERED',
            notes VARCHAR(255) NULL,
            requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ordered_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_settings (
            setting_key VARCHAR(100) PRIMARY KEY,
            setting_value VARCHAR(255) NULL,
            updated_by VARCHAR(100) NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


@app.route("/inventory/counts", methods=["POST"])
def inventory_count_api():
    data = request.json or {}
    item_id = data.get("item_id")
    counted_qty = data.get("counted_qty")
    counted_by = (data.get("counted_by") or "").strip() or "system"
    notes = (data.get("notes") or "").strip() or None

    if item_id in [None, ""] or counted_qty in [None, ""]:
        return jsonify({"error": "item_id and counted_qty are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO inventory_counts
            (item_id, counted_qty, counted_by, counted_at, notes)
            VALUES (%s, %s, %s, NOW(), %s)
        """, (int(item_id), float(counted_qty), counted_by, notes))

        cursor.execute("""
            UPDATE inventory_items
            SET on_hand_qty = %s, updated_at = NOW()
            WHERE id = %s
        """, (float(counted_qty), int(item_id)))

        conn.commit()
        return jsonify({"status": "count_saved"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/counts/bulk", methods=["POST"])
def inventory_counts_bulk_api():
    data = request.json or {}
    rows = data.get("rows") or []
    counted_by = (data.get("counted_by") or "").strip() or "system"
    notes = (data.get("notes") or "").strip() or None

    if not isinstance(rows, list) or len(rows) == 0:
        return jsonify({"error": "rows is required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        saved = 0
        for row in rows:
            item_id = row.get("item_id")
            counted_qty = row.get("counted_qty")
            if item_id in [None, ""] or counted_qty in [None, ""]:
                continue
            cursor.execute("""
                INSERT INTO inventory_counts
                (item_id, counted_qty, counted_by, counted_at, notes)
                VALUES (%s, %s, %s, NOW(), %s)
            """, (int(item_id), float(counted_qty), counted_by, notes))
            cursor.execute("""
                UPDATE inventory_items
                SET on_hand_qty = %s, updated_at = NOW()
                WHERE id = %s
            """, (float(counted_qty), int(item_id)))
            saved += 1

        conn.commit()
        return jsonify({"status": "saved", "rows_saved": saved})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/bag_sales", methods=["GET", "POST"])
def inventory_bag_sales_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT id, sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at
                FROM bag_sales
                ORDER BY sale_date DESC, id DESC
                LIMIT 500
            """)
            return jsonify(cursor.fetchall())

        data = request.json or {}
        sale_date = parse_date_value(data.get("sale_date")) or date.today()
        customer_name = (data.get("customer_name") or "").strip()
        sale_type = (data.get("sale_type") or "DROP_OFF").strip().upper()
        qty = int(data.get("qty") or 0)
        amount_paid = (data.get("amount_paid") or "").strip() or None
        entered_by = (data.get("entered_by") or "").strip() or None
        if not customer_name or qty <= 0:
            return jsonify({"error": "customer_name and qty>0 are required"}), 400

        cursor.execute("""
            INSERT INTO bag_sales
            (sale_date, customer_name, sale_type, qty, amount_paid, entered_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (sale_date, customer_name, sale_type, qty, amount_paid, entered_by))

        # Auto-decrement first active BAG item (if configured).
        cursor.execute("""
            SELECT id, on_hand_qty
            FROM inventory_items
            WHERE category = 'BAG' AND active = TRUE
            ORDER BY id ASC
            LIMIT 1
        """)
        bag_item = cursor.fetchone()
        if bag_item:
            next_qty = float(bag_item["on_hand_qty"] or 0) - float(qty)
            cursor.execute(
                "UPDATE inventory_items SET on_hand_qty = %s, updated_at = NOW() WHERE id = %s",
                (next_qty, bag_item["id"]),
            )

        conn.commit()
        return jsonify({"status": "sale_saved"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/reorder", methods=["POST"])
def inventory_reorder_api():
    data = request.json or {}
    lines = data.get("lines") or []
    ordered_by = (data.get("ordered_by") or "").strip() or "manager"
    notes = (data.get("notes") or "").strip() or None

    if not isinstance(lines, list) or len(lines) == 0:
        return jsonify({"error": "lines is required"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_inventory_extensions(cursor)
        affected = 0
        for line in lines:
            item_id = line.get("item_id")
            requested_qty = line.get("requested_qty")
            if item_id in [None, ""] or requested_qty in [None, ""]:
                continue
            requested_qty = float(requested_qty)
            if requested_qty <= 0:
                continue

            cursor.execute("SELECT id, on_hand_qty FROM inventory_items WHERE id = %s LIMIT 1", (int(item_id),))
            item = cursor.fetchone()
            if not item:
                continue

            new_qty = float(item.get("on_hand_qty") or 0) + requested_qty
            cursor.execute("""
                UPDATE inventory_items
                SET on_hand_qty = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_qty, int(item_id)))

            cursor.execute("""
                INSERT INTO inventory_purchase_orders
                (item_id, requested_qty, ordered_qty, requested_by, ordered_by, status, notes, requested_at, ordered_at, created_at)
                VALUES (%s, %s, %s, %s, %s, 'ORDERED', %s, NOW(), NOW(), NOW())
            """, (int(item_id), requested_qty, requested_qty, ordered_by, ordered_by, notes))
            affected += 1

        conn.commit()
        return jsonify({"status": "ordered", "lines": affected})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/bag_price", methods=["GET", "POST"])
def inventory_bag_price_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_inventory_extensions(cursor)
        if request.method == "GET":
            cursor.execute("SELECT setting_value, updated_by, updated_at FROM inventory_settings WHERE setting_key = 'bag_default_price' LIMIT 1")
            row = cursor.fetchone() or {}
            return jsonify({
                "bag_default_price": float(row.get("setting_value") or 0),
                "updated_by": row.get("updated_by"),
                "updated_at": row.get("updated_at"),
            })

        data = request.json or {}
        price = data.get("bag_default_price")
        updated_by = (data.get("updated_by") or "").strip() or "manager"
        try:
            price = round(float(price), 2)
        except Exception:
            return jsonify({"error": "bag_default_price must be numeric"}), 400

        cursor.execute("""
            INSERT INTO inventory_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES ('bag_default_price', %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value),
                updated_by = VALUES(updated_by),
                updated_at = NOW()
        """, (str(price), updated_by))
        conn.commit()
        return jsonify({"status": "updated", "bag_default_price": price})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/report", methods=["GET"])
def inventory_report_api():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_inventory_extensions(cursor)
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        item_id = request.args.get("item_id")
        limit = request.args.get("limit", 250)
        try:
            limit = max(50, min(int(limit), 1000))
        except Exception:
            limit = 250

        cursor.execute("""
            SELECT
                i.id,
                i.item_name,
                i.category,
                i.unit_label,
                i.on_hand_qty,
                i.reorder_threshold,
                COALESCE(SUM(po.ordered_qty), 0) AS total_ordered_qty
            FROM inventory_items i
            LEFT JOIN inventory_purchase_orders po
              ON po.item_id = i.id
            WHERE i.active = TRUE
            GROUP BY i.id, i.item_name, i.category, i.unit_label, i.on_hand_qty, i.reorder_threshold
            ORDER BY i.category, i.item_name
        """)
        items = cursor.fetchall()

        cursor.execute("""
            SELECT
                COALESCE(SUM(qty), 0) AS total_bags_sold,
                COALESCE(SUM(CASE WHEN amount_paid REGEXP '^[0-9]+(\\.[0-9]+)?$' THEN CAST(amount_paid AS DECIMAL(10,2)) ELSE 0 END), 0) AS bags_sales_amount
            FROM bag_sales
        """)
        bag_totals = cursor.fetchone() or {}

        where_count = []
        params_count = []
        if start_date:
            where_count.append("DATE(c.counted_at) >= %s")
            params_count.append(start_date)
        if end_date:
            where_count.append("DATE(c.counted_at) <= %s")
            params_count.append(end_date)
        if item_id:
            where_count.append("c.item_id = %s")
            params_count.append(int(item_id))

        count_where_sql = f"WHERE {' AND '.join(where_count)}" if where_count else ""

        where_po = []
        params_po = []
        if start_date:
            where_po.append("DATE(po.requested_at) >= %s")
            params_po.append(start_date)
        if end_date:
            where_po.append("DATE(po.requested_at) <= %s")
            params_po.append(end_date)
        if item_id:
            where_po.append("po.item_id = %s")
            params_po.append(int(item_id))
        po_where_sql = f"WHERE {' AND '.join(where_po)}" if where_po else ""

        where_sales = []
        params_sales = []
        if start_date:
            where_sales.append("bs.sale_date >= %s")
            params_sales.append(start_date)
        if end_date:
            where_sales.append("bs.sale_date <= %s")
            params_sales.append(end_date)
        sales_where_sql = f"WHERE {' AND '.join(where_sales)}" if where_sales else ""

        cursor.execute(f"""
            SELECT
                c.id,
                'WEEKLY_COUNT' AS activity_type,
                c.counted_at AS activity_at,
                DATE(c.counted_at) AS activity_date,
                c.counted_by AS actor,
                i.id AS item_id,
                i.item_name,
                c.counted_qty AS qty,
                NULL AS extra_value,
                c.notes
            FROM inventory_counts c
            JOIN inventory_items i ON i.id = c.item_id
            {count_where_sql}
            ORDER BY c.counted_at DESC
            LIMIT {limit}
        """, tuple(params_count))
        count_activity = cursor.fetchall()

        cursor.execute(f"""
            SELECT
                po.id,
                'PURCHASE_ORDER' AS activity_type,
                po.requested_at AS activity_at,
                DATE(po.requested_at) AS activity_date,
                po.ordered_by AS actor,
                i.id AS item_id,
                i.item_name,
                po.ordered_qty AS qty,
                po.status AS extra_value,
                po.notes
            FROM inventory_purchase_orders po
            JOIN inventory_items i ON i.id = po.item_id
            {po_where_sql}
            ORDER BY po.requested_at DESC
            LIMIT {limit}
        """, tuple(params_po))
        po_activity = cursor.fetchall()

        cursor.execute(f"""
            SELECT
                bs.id,
                'BAG_SALE' AS activity_type,
                bs.created_at AS activity_at,
                bs.sale_date AS activity_date,
                bs.entered_by AS actor,
                NULL AS item_id,
                'Bag Sale' AS item_name,
                bs.qty AS qty,
                bs.customer_name AS extra_value,
                CONCAT('amount_paid=', COALESCE(bs.amount_paid, '')) AS notes
            FROM bag_sales bs
            {sales_where_sql}
            ORDER BY bs.created_at DESC
            LIMIT {limit}
        """, tuple(params_sales))
        bag_activity = cursor.fetchall()

        activity = sorted(
            (count_activity + po_activity + bag_activity),
            key=lambda r: r.get("activity_at") or datetime.min,
            reverse=True
        )[:limit]

        cursor.execute("""
            SELECT
                MAX(c.counted_at) AS counted_at,
                SUBSTRING_INDEX(
                    GROUP_CONCAT(c.counted_by ORDER BY c.counted_at DESC SEPARATOR ','),
                    ',',
                    1
                ) AS counted_by
            FROM inventory_counts c
        """)
        latest_count = cursor.fetchone() or {}

        return jsonify({
            "items": items,
            "bag_totals": bag_totals,
            "latest_count": latest_count,
            "activity": activity,
        })
    finally:
        cursor.close()
        conn.close()


@app.route("/inventory/low_stock", methods=["GET"])
def inventory_low_stock():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                id, item_name, category, vendor_name, unit_label, on_hand_qty, reorder_threshold
            FROM inventory_items
            WHERE active = TRUE
              AND on_hand_qty <= reorder_threshold
            ORDER BY category, item_name
        """)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/geofence/config", methods=["POST", "DELETE"])
def save_geofence_config():

    if request.method == "DELETE":
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE geofence_settings SET active = FALSE")
            conn.commit()
            return jsonify({"status": "cleared"})
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()

    data = request.json or {}

    label = (data.get("label") or "").strip() or "Primary"
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    radius_m = data.get("radius_m")
    updated_by = (data.get("updated_by") or "").strip() or "admin"
    active = bool(data.get("active", True))

    try:
        latitude = float(latitude)
        longitude = float(longitude)
        radius_m = int(radius_m)
    except Exception:
        return jsonify({"error": "latitude, longitude, radius_m are required numeric values"}), 400

    if radius_m <= 0:
        return jsonify({"error": "radius_m must be > 0"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        if active:
            cursor.execute("UPDATE geofence_settings SET active = FALSE")

        cursor.execute("""
            INSERT INTO geofence_settings
            (
                label,
                latitude,
                longitude,
                radius_m,
                active,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            label,
            latitude,
            longitude,
            radius_m,
            active,
            updated_by
        ))

        conn.commit()

        cur_u = conn.cursor(dictionary=True)
        me, err_user, _ = require_user(cur_u)
        if not err_user and me and me.get("organization_id") is not None:
            try:
                sync_maintenance_geofence_to_ta_geofences(
                    conn,
                    user_org_id(me),
                    label,
                    latitude,
                    longitude,
                    radius_m,
                    active,
                )
                conn.commit()
            except Exception as sync_e:
                app.logger.exception("sync_maintenance_geofence_to_ta_geofences: %s", sync_e)

        return jsonify({"status": "saved"})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Attendance / Clock APIs
# ---------------------------------------------------

@app.route("/attendance/punch", methods=["POST"])
def attendance_punch():

    data = request.json or {}

    employee_id = data.get("employee_id")
    event_type = (data.get("event_type") or "").strip().upper()
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    notes = (data.get("notes") or "").strip() or None
    personal_bags = data.get("personal_bags")
    device_time = data.get("device_time")

    allowed_events = {
        "CLOCK_IN",
        "CLOCK_OUT",
        "BREAK_START",
        "BREAK_END",
        "RINSE_SHIFT_START",
        "RINSE_SHIFT_END"
    }

    if event_type not in allowed_events:
        return jsonify({"error": "Invalid event_type"}), 400

    if employee_id in [None, ""]:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        employee_id = int(employee_id)
        latitude = float(latitude)
        longitude = float(longitude)
    except Exception:
        return jsonify({"error": "employee_id, latitude, longitude must be numeric"}), 400

    if personal_bags in [None, ""]:
        personal_bags = None
    else:
        try:
            personal_bags = int(personal_bags)
        except Exception:
            return jsonify({"error": "personal_bags must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_attendance_monitor_tables(cursor)
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"error": "No geofence configured"}), 400

        distance_m = haversine_meters(
            latitude,
            longitude,
            float(geofence["latitude"]),
            float(geofence["longitude"])
        )
        within_geofence = distance_m <= float(geofence["radius_m"])

        if not within_geofence:
            return jsonify({
                "error": "Outside geofence",
                "distance_m": round(distance_m, 2),
                "radius_m": geofence["radius_m"]
            }), 403

        cursor.execute("""
            INSERT INTO attendance_events
            (
                employee_id,
                event_type,
                event_time,
                device_time,
                latitude,
                longitude,
                within_geofence,
                distance_m,
                geofence_id,
                notes,
                personal_bags
            )
            VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            employee_id,
            event_type,
            device_time,
            latitude,
            longitude,
            within_geofence,
            round(distance_m, 2),
            geofence["id"],
            notes,
            personal_bags
        ))

        if event_type in {"BREAK_START", "CLOCK_OUT"}:
            close_open_discrepancy(
                cursor,
                employee_id,
                datetime.now(),
                "BREAK_OR_CLOCK_OUT",
                f"Closed by {event_type}"
            )

        # Update latest known presence for near-real-time monitoring
        cursor.execute("""
            INSERT INTO employee_geo_presence
            (
                employee_id,
                is_inside,
                latitude,
                longitude,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                is_inside = VALUES(is_inside),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                last_seen_at = VALUES(last_seen_at)
        """, (
            employee_id,
            within_geofence,
            latitude,
            longitude
        ))

        conn.commit()

        return jsonify({
            "status": "recorded",
            "event_type": event_type,
            "within_geofence": within_geofence,
            "distance_m": round(distance_m, 2),
            "radius_m": geofence["radius_m"]
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/location_ping", methods=["POST"])
def attendance_location_ping():

    data = request.json or {}
    employee_id = data.get("employee_id")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if employee_id in [None, ""] or latitude in [None, ""] or longitude in [None, ""]:
        return jsonify({"error": "employee_id, latitude, longitude are required"}), 400

    try:
        employee_id = int(employee_id)
        latitude = float(latitude)
        longitude = float(longitude)
    except Exception:
        return jsonify({"error": "employee_id, latitude, longitude must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_attendance_monitor_tables(cursor)
        geofence = fetch_active_geofence(cursor)

        if not geofence:
            return jsonify({"error": "No geofence configured"}), 400

        distance_m = haversine_meters(
            latitude,
            longitude,
            float(geofence["latitude"]),
            float(geofence["longitude"])
        )
        is_inside = distance_m <= float(geofence["radius_m"])

        cursor.execute("""
            SELECT is_inside
            FROM employee_geo_presence
            WHERE employee_id = %s
        """, (employee_id,))
        prev_row = cursor.fetchone()
        previous_inside = None if not prev_row else bool(prev_row["is_inside"])

        cursor.execute("""
            INSERT INTO employee_geo_presence
            (
                employee_id,
                is_inside,
                latitude,
                longitude,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                is_inside = VALUES(is_inside),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                last_seen_at = VALUES(last_seen_at)
        """, (
            employee_id,
            is_inside,
            latitude,
            longitude
        ))

        transition = None

        if previous_inside is not None and previous_inside != is_inside:
            transition = "ENTER" if is_inside else "EXIT"

            cursor.execute("""
                INSERT INTO geofence_alerts
                (
                    employee_id,
                    transition_type,
                    geofence_id,
                    latitude,
                    longitude,
                    distance_m,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (
                employee_id,
                transition,
                geofence["id"],
                latitude,
                longitude,
                round(distance_m, 2)
            ))

            # Discrepancy tracking:
            # If employee exits while clocked in and not on break, open discrepancy.
            cursor.execute(
                """
                SELECT event_type
                FROM attendance_events
                WHERE employee_id = %s
                  AND DATE(event_time) = CURDATE()
                ORDER BY event_time DESC, id DESC
                LIMIT 1
                """,
                (employee_id,)
            )
            ev = cursor.fetchone() or {}
            latest_event = (ev.get("event_type") or "").upper()

            if transition == "EXIT":
                if latest_event in {"CLOCK_IN", "BREAK_END", "RINSE_SHIFT_START", "RINSE_SHIFT_END"}:
                    open_exit_discrepancy_if_needed(
                        cursor,
                        employee_id,
                        datetime.now(),
                        datetime.now()
                    )
            else:
                close_open_discrepancy(
                    cursor,
                    employee_id,
                    datetime.now(),
                    "GEOFENCE_REENTER",
                    "Re-entered geofence"
                )

        conn.commit()

        return jsonify({
            "status": "ok",
            "is_inside": is_inside,
            "transition": transition,
            "distance_m": round(distance_m, 2),
            "radius_m": geofence["radius_m"]
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/alerts", methods=["GET"])
def attendance_alerts():

    since_id = request.args.get("since_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        if since_id not in [None, ""]:
            cursor.execute("""
                SELECT
                    a.id,
                    a.employee_id,
                    e.name AS employee_name,
                    a.transition_type,
                    a.distance_m,
                    a.created_at
                FROM geofence_alerts a
                LEFT JOIN employees e
                ON e.id = a.employee_id
                WHERE a.id > %s
                ORDER BY a.id ASC
                LIMIT 200
            """, (int(since_id),))
        else:
            cursor.execute("""
                SELECT
                    a.id,
                    a.employee_id,
                    e.name AS employee_name,
                    a.transition_type,
                    a.distance_m,
                    a.created_at
                FROM geofence_alerts a
                LEFT JOIN employees e
                ON e.id = a.employee_id
                ORDER BY a.id DESC
                LIMIT 200
            """)

        return jsonify(cursor.fetchall())

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/live", methods=["GET"])
def attendance_live():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        auto_inserted = auto_clock_out_stale_users(cursor)
        if auto_inserted:
            conn.commit()
        cursor.execute("""
            SELECT
                t.employee_id,
                e.name,
                t.last_event,
                p.is_inside,
                p.last_seen_at
            FROM
            (
                SELECT
                    employee_id,
                    SUBSTRING_INDEX(
                        GROUP_CONCAT(event_type ORDER BY event_time DESC, id DESC),
                        ',',
                        1
                    ) AS last_event
                FROM attendance_events
                WHERE DATE(event_time) = CURDATE()
                AND event_type IN ('CLOCK_IN', 'CLOCK_OUT')
                GROUP BY employee_id
            ) t
            LEFT JOIN employees e
            ON e.id = t.employee_id
            LEFT JOIN employee_geo_presence p
            ON p.employee_id = t.employee_id
            ORDER BY e.name
        """)

        rows = cursor.fetchall()

        at_work = [
            row for row in rows
            if (row.get("last_event") or "").upper() == "CLOCK_IN"
        ]

        return jsonify({
            "at_work_count": len(at_work),
            "at_work": at_work,
            "all_today": rows
        })

    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/my_state", methods=["GET"])
def attendance_my_state():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_attendance_monitor_tables(cursor)
        auto_inserted = auto_clock_out_stale_users(cursor)
        if auto_inserted:
            conn.commit()

        emp = resolve_employee_for_user(cursor, me)
        if not emp:
            return jsonify({"error": "No employee record mapped for this user"}), 400

        employee_id = int(emp["id"])
        events = fetch_today_events_for_employee(cursor, employee_id)
        work_state = compute_work_state_from_events(events)

        cursor.execute(
            """
            SELECT id, discrepancy_type, status, start_time, end_time, duration_minutes, notes
            FROM attendance_discrepancies
            WHERE employee_id = %s
              AND (
                status = 'OPEN'
                OR DATE(start_time) = CURDATE()
                OR DATE(IFNULL(end_time, start_time)) = CURDATE()
              )
            ORDER BY id DESC
            LIMIT 30
            """,
            (employee_id,)
        )
        discrepancies = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS at_work_count
            FROM (
                SELECT
                    employee_id,
                    SUBSTRING_INDEX(
                        GROUP_CONCAT(event_type ORDER BY event_time DESC, id DESC),
                        ',',
                        1
                    ) AS last_event
                FROM attendance_events
                WHERE DATE(event_time) = CURDATE()
                  AND event_type IN ('CLOCK_IN', 'CLOCK_OUT')
                GROUP BY employee_id
            ) x
            WHERE UPPER(last_event) = 'CLOCK_IN'
            """
        )
        at_work_count = (cursor.fetchone() or {}).get("at_work_count", 0)

        now_local = datetime.now()
        pc = payroll_cycle_for(now_local)
        worked_h = int(work_state["worked_minutes"] // 60)
        worked_m = int(work_state["worked_minutes"] % 60)

        return jsonify({
            "employee_id": employee_id,
            "employee_name": emp["name"],
            "now": now_local.isoformat(),
            "today_label": now_local.strftime("%A, %b %d, %Y"),
            "is_clocked_in": work_state["is_clocked_in"],
            "on_break": work_state["on_break"],
            "worked_minutes": work_state["worked_minutes"],
            "worked_label": f"{worked_h} hr {worked_m} min",
            "at_work_count": at_work_count,
            "payroll_cycle": {
                "code": pc["cycle_code"],
                "week_start": pc["week_start"].isoformat(),
                "week_end": pc["week_end"].isoformat(),
                "week_number": pc["week_num"],
            },
            "events_today": events,
            "discrepancies": discrepancies,
        })
    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/my_punch", methods=["POST"])
def attendance_my_punch():
    data = request.json or {}
    event_type = (data.get("event_type") or "").strip().upper()
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    notes = (data.get("notes") or "").strip() or None
    personal_bags = data.get("personal_bags")
    device_time = data.get("device_time")

    allowed_events = {
        "CLOCK_IN",
        "CLOCK_OUT",
        "BREAK_START",
        "BREAK_END",
        "RINSE_SHIFT_START",
        "RINSE_SHIFT_END"
    }
    if event_type not in allowed_events:
        return jsonify({"error": "Invalid event_type"}), 400

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except Exception:
        return jsonify({"error": "latitude and longitude are required numeric values"}), 400

    if personal_bags in [None, ""]:
        personal_bags = None
    else:
        try:
            personal_bags = int(personal_bags)
        except Exception:
            return jsonify({"error": "personal_bags must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code

        ensure_attendance_monitor_tables(cursor)
        emp = resolve_employee_for_user(cursor, me)
        if not emp:
            return jsonify({"error": "No employee record mapped for this user"}), 400

        geofence = fetch_active_geofence(cursor)
        if not geofence:
            return jsonify({"error": "No geofence configured"}), 400

        distance_m = haversine_meters(
            latitude,
            longitude,
            float(geofence["latitude"]),
            float(geofence["longitude"])
        )
        within_geofence = distance_m <= float(geofence["radius_m"])

        if not within_geofence:
            return jsonify({
                "error": "Outside geofence",
                "distance_m": round(distance_m, 2),
                "radius_m": geofence["radius_m"]
            }), 403

        employee_id = int(emp["id"])
        cursor.execute(
            """
            INSERT INTO attendance_events
            (
                employee_id,
                event_type,
                event_time,
                device_time,
                latitude,
                longitude,
                within_geofence,
                distance_m,
                geofence_id,
                notes,
                personal_bags
            )
            VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                employee_id,
                event_type,
                device_time,
                latitude,
                longitude,
                within_geofence,
                round(distance_m, 2),
                geofence["id"],
                notes,
                personal_bags,
            )
        )

        cursor.execute(
            """
            INSERT INTO employee_geo_presence
            (
                employee_id,
                is_inside,
                latitude,
                longitude,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                is_inside = VALUES(is_inside),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                last_seen_at = VALUES(last_seen_at)
            """,
            (employee_id, within_geofence, latitude, longitude)
        )

        if event_type in {"BREAK_START", "CLOCK_OUT"}:
            close_open_discrepancy(
                cursor,
                employee_id,
                datetime.now(),
                "BREAK_OR_CLOCK_OUT",
                f"Closed by {event_type}"
            )

        conn.commit()
        return jsonify({
            "status": "recorded",
            "event_type": event_type,
            "employee_id": employee_id,
            "employee_name": emp["name"],
            "distance_m": round(distance_m, 2),
            "radius_m": geofence["radius_m"],
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/payroll_monitor", methods=["GET"])
def attendance_payroll_monitor():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        if "ADMIN" not in me.get("roles", []) and "OPS" not in me.get("roles", []):
            return jsonify({"error": "Forbidden"}), 403

        ensure_attendance_monitor_tables(cursor)
        auto_inserted = auto_clock_out_stale_users(cursor)
        if auto_inserted:
            conn.commit()

        cycle_date = request.args.get("cycle_date")
        base_date = parse_date_value(cycle_date) if cycle_date else datetime.now().date()
        pc = payroll_cycle_for(base_date)

        cursor.execute(
            """
            SELECT
                COUNT(*) AS at_work_count
            FROM (
                SELECT
                    employee_id,
                    SUBSTRING_INDEX(
                        GROUP_CONCAT(event_type ORDER BY event_time DESC, id DESC),
                        ',',
                        1
                    ) AS last_event
                FROM attendance_events
                WHERE DATE(event_time) = CURDATE()
                  AND event_type IN ('CLOCK_IN', 'CLOCK_OUT')
                GROUP BY employee_id
            ) x
            WHERE UPPER(last_event) = 'CLOCK_IN'
            """
        )
        at_work_count = (cursor.fetchone() or {}).get("at_work_count", 0)

        cursor.execute(
            """
            SELECT DATE(event_time) AS d, COUNT(DISTINCT employee_id) AS workers
            FROM attendance_events
            WHERE event_type = 'CLOCK_IN'
              AND DATE(event_time) BETWEEN %s AND %s
            GROUP BY DATE(event_time)
            ORDER BY d
            """,
            (pc["week_start"], pc["week_end"])
        )
        this_week = cursor.fetchall()

        prev_start = pc["week_start"] - timedelta(days=7)
        prev_end = pc["week_end"] - timedelta(days=7)
        cursor.execute(
            """
            SELECT DATE(event_time) AS d, COUNT(DISTINCT employee_id) AS workers
            FROM attendance_events
            WHERE event_type = 'CLOCK_IN'
              AND DATE(event_time) BETWEEN %s AND %s
            GROUP BY DATE(event_time)
            ORDER BY d
            """,
            (prev_start, prev_end)
        )
        prev_week = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                d.id,
                d.employee_id,
                e.name AS employee_name,
                d.discrepancy_type,
                d.status,
                d.start_time,
                d.end_time,
                d.duration_minutes,
                d.last_exit_time,
                d.resolution_action,
                d.notes
            FROM attendance_discrepancies d
            LEFT JOIN employees e ON e.id = d.employee_id
            WHERE d.payroll_week_start = %s
              AND d.payroll_week_end = %s
            ORDER BY d.status ASC, d.start_time DESC
            LIMIT 500
            """,
            (pc["week_start"], pc["week_end"])
        )
        discrepancies = cursor.fetchall()

        return jsonify({
            "payroll_cycle": {
                "code": pc["cycle_code"],
                "week_start": pc["week_start"].isoformat(),
                "week_end": pc["week_end"].isoformat(),
                "week_number": pc["week_num"],
            },
            "at_work_count": at_work_count,
            "worked_this_week": this_week,
            "worked_previous_week": prev_week,
            "discrepancies": discrepancies,
        })
    finally:
        cursor.close()
        conn.close()


@app.route("/attendance/events_today", methods=["GET"])
def attendance_events_today():

    employee_id = request.args.get("employee_id")

    if employee_id in [None, ""]:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        employee_id = int(employee_id)
    except Exception:
        return jsonify({"error": "employee_id must be numeric"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                id,
                employee_id,
                event_type,
                event_time,
                notes,
                personal_bags
            FROM attendance_events
            WHERE employee_id = %s
            AND DATE(event_time) = CURDATE()
            ORDER BY event_time DESC, id DESC
        """, (employee_id,))

        rows = cursor.fetchall()
        return jsonify(rows)

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Batch Review APIs
# ---------------------------------------------------

@app.route("/upload_batches/current", methods=["GET"])
def get_current_upload_batch():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        _trigger_daily_operational_reset_if_needed(conn, tenant_oid)
        pk_col = get_upload_batches_pk(cursor)
        selected_cols = [
            f"{pk_col} AS id",
            "file_name",
            "batch_date",
            "orders_loaded",
        ]

        if table_has_column(cursor, "upload_batches", "state"):
            selected_cols.append("state")
        else:
            selected_cols.append("'DRAFT' AS state")

        # Pick whichever time columns exist in this environment.
        if table_has_column(cursor, "upload_batches", "created_at"):
            selected_cols.append("created_at")
        elif table_has_column(cursor, "upload_batches", "uploaded_at"):
            selected_cols.append("uploaded_at AS created_at")
        else:
            selected_cols.append("NULL AS created_at")

        if table_has_column(cursor, "upload_batches", "updated_at"):
            selected_cols.append("updated_at")
        else:
            selected_cols.append("NULL AS updated_at")

        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            selected_cols.append("confirmed_at")
        else:
            selected_cols.append("NULL AS confirmed_at")

        if table_has_column(cursor, "upload_batches", "closed_at"):
            selected_cols.append("closed_at")
        else:
            selected_cols.append("NULL AS closed_at")

        cur_where = ""
        cur_args = []
        if table_has_column(cursor, "upload_batches", "organization_id"):
            cur_where = "WHERE organization_id = %s"
            cur_args.append(tenant_oid)
        cursor.execute(f"""
            SELECT
                {", ".join(selected_cols)}
            FROM upload_batches
            {cur_where}
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT 1
        """, tuple(cur_args))
        row = cursor.fetchone()
        if not row:
            return jsonify(None)

        row_pk = get_upload_batch_rows_pk(cursor)
        summary = summarize_batch_rows(cursor, row["id"], row_pk)
        row["summary"] = summary
        try:
            from backend.upload_batch_requirements import batch_upload_files_status

            row["upload_files"] = batch_upload_files_status(cursor, row["id"], tenant_oid)
            row["scan_events_count"] = row["upload_files"].get("scan_events_count", 0)
        except Exception:
            row["scan_events_count"] = 0
            row["upload_files"] = None
        return jsonify(row)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches", methods=["GET"])
def list_upload_batches():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        pk_col = get_upload_batches_pk(cursor)
        limit = request.args.get("limit", default=20, type=int) or 20
        limit = max(1, min(limit, 100))

        selected_cols = [
            f"{pk_col} AS id",
            "file_name",
            "batch_date",
            "orders_loaded",
        ]

        if table_has_column(cursor, "upload_batches", "state"):
            selected_cols.append("state")
        else:
            selected_cols.append("'DRAFT' AS state")

        if table_has_column(cursor, "upload_batches", "created_at"):
            selected_cols.append("created_at")
        elif table_has_column(cursor, "upload_batches", "uploaded_at"):
            selected_cols.append("uploaded_at AS created_at")
        else:
            selected_cols.append("NULL AS created_at")

        if table_has_column(cursor, "upload_batches", "updated_at"):
            selected_cols.append("updated_at")
        else:
            selected_cols.append("NULL AS updated_at")

        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            selected_cols.append("confirmed_at")
        else:
            selected_cols.append("NULL AS confirmed_at")

        if table_has_column(cursor, "upload_batches", "closed_at"):
            selected_cols.append("closed_at")
        else:
            selected_cols.append("NULL AS closed_at")

        list_where = ""
        list_args = []
        if table_has_column(cursor, "upload_batches", "organization_id"):
            list_where = "WHERE organization_id = %s"
            list_args.append(tenant_oid)
        list_args.append(limit)
        cursor.execute(f"""
            SELECT
                {", ".join(selected_cols)}
            FROM upload_batches
            {list_where}
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT %s
        """, tuple(list_args))
        rows = cursor.fetchall() or []

        row_pk = get_upload_batch_rows_pk(cursor)
        for row in rows:
            row["summary"] = summarize_batch_rows(cursor, row["id"], row_pk)

        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/current/reset", methods=["POST"])
def reset_current_draft_batch():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        pk_col = get_upload_batches_pk(cursor)
        where_parts = []
        if table_has_column(cursor, "upload_batches", "state"):
            where_parts.append("state = 'DRAFT'")
        if table_has_column(cursor, "upload_batches", "organization_id"):
            where_parts.append("organization_id = %s")
        where_state = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        reset_args = []
        if table_has_column(cursor, "upload_batches", "organization_id"):
            reset_args.append(tenant_oid)

        cursor.execute(f"""
            SELECT {pk_col} AS id, state
            FROM upload_batches
            {where_state}
            ORDER BY batch_date DESC, {pk_col} DESC
            LIMIT 1
        """, tuple(reset_args))
        batch = cursor.fetchone()

        if not batch:
            return jsonify({
                "status": "nothing_to_reset",
                "message": "No draft batch available."
            })

        batch_id = batch["id"]
        row_pk = get_upload_batch_rows_pk(cursor)
        summary = summarize_batch_rows(cursor, batch_id, row_pk)

        from backend.upload_batch_cleanup import delete_upload_batch_cascade

        ub_org = tenant_oid if table_has_column(cursor, "upload_batches", "organization_id") else None
        deleted = delete_upload_batch_cascade(
            cursor, batch_id, organization_id=ub_org
        )

        conn.commit()
        return jsonify({
            "status": "draft_reset",
            "batch_id": batch_id,
            "deleted_row_count": summary.get("total_rows", 0),
            "upload_batch_scan_events_deleted": deleted.get(
                "upload_batch_scan_events", 0
            ),
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/reset_all", methods=["POST"])
def reset_all_upload_batches():

    data = request.json or {}
    cascade_data = as_bool(data.get("cascade_data"), True)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_admin(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        row_pk = get_upload_batch_rows_pk(cursor)
        batch_pk = get_upload_batches_pk(cursor)
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_final_org = table_exists(cursor, "orders_final") and table_has_column(
            cursor, "orders_final", "organization_id"
        )

        if has_ub_org:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS cnt FROM upload_batch_rows
                WHERE upload_batch_id IN (
                    SELECT {batch_pk} FROM upload_batches WHERE organization_id = %s
                )
                """,
                (tenant_oid,),
            )
            rows_before = (cursor.fetchone() or {}).get("cnt", 0) or 0
            cursor.execute(
                f"SELECT COUNT(*) AS cnt FROM upload_batches WHERE organization_id = %s",
                (tenant_oid,),
            )
            batches_before = (cursor.fetchone() or {}).get("cnt", 0) or 0
            from backend.upload_batch_cleanup import (
                delete_upload_batches_for_organization,
            )

            batch_delete_counts = delete_upload_batches_for_organization(
                cursor, tenant_oid
            )
            scan_audit_deleted = batch_delete_counts.get(
                "upload_batch_scan_events", 0
            )
        else:
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM upload_batch_rows")
            rows_before = (cursor.fetchone() or {}).get("cnt", 0) or 0
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM upload_batches")
            batches_before = (cursor.fetchone() or {}).get("cnt", 0) or 0
            from backend.upload_batch_cleanup import delete_all_upload_batches_global

            batch_delete_counts = delete_all_upload_batches_global(cursor)
            scan_audit_deleted = batch_delete_counts.get(
                "upload_batch_scan_events", 0
            )

        cascade_deleted = {
            "orders_staging": 0,
            "orders_final": 0,
            "checkout_log": 0,
            "order_processing": 0,
        }
        if cascade_data:
            if has_staging_org:
                if table_exists(cursor, "order_processing"):
                    cursor.execute(
                        """
                        DELETE FROM order_processing
                        WHERE order_id IN (
                            SELECT id FROM orders_staging WHERE organization_id = %s
                        )
                        """,
                        (tenant_oid,),
                    )
                    cascade_deleted["order_processing"] = cursor.rowcount or 0
                if table_exists(cursor, "checkout_log"):
                    cursor.execute(
                        """
                        DELETE FROM checkout_log
                        WHERE order_id IN (
                            SELECT id FROM orders_staging WHERE organization_id = %s
                        )
                        """,
                        (tenant_oid,),
                    )
                    cascade_deleted["checkout_log"] = cursor.rowcount or 0
                if has_final_org:
                    cursor.execute(
                        "SELECT COUNT(*) AS cnt FROM orders_final WHERE organization_id = %s",
                        (tenant_oid,),
                    )
                    before = (cursor.fetchone() or {}).get("cnt", 0) or 0
                    cursor.execute(
                        "DELETE FROM orders_final WHERE organization_id = %s",
                        (tenant_oid,),
                    )
                    cascade_deleted["orders_final"] = before
                cursor.execute(
                    "SELECT COUNT(*) AS cnt FROM orders_staging WHERE organization_id = %s",
                    (tenant_oid,),
                )
                before = (cursor.fetchone() or {}).get("cnt", 0) or 0
                cursor.execute(
                    "DELETE FROM orders_staging WHERE organization_id = %s",
                    (tenant_oid,),
                )
                cascade_deleted["orders_staging"] = before
            else:
                for table_name in ["order_processing", "checkout_log", "orders_final", "orders_staging"]:
                    if table_exists(cursor, table_name):
                        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
                        before = (cursor.fetchone() or {}).get("cnt", 0) or 0
                        cursor.execute(f"DELETE FROM {table_name}")
                        cascade_deleted[table_name] = before

        # Reset auto-increment where possible for cleaner testing
        try:
            cursor.execute("ALTER TABLE upload_batch_rows AUTO_INCREMENT = 1")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE upload_batches AUTO_INCREMENT = 1")
        except Exception:
            pass

        conn.commit()
        return jsonify({
            "status": "reset_complete",
            "deleted_rows": rows_before,
            "deleted_batches": batches_before,
            "upload_batch_scan_events_deleted": scan_audit_deleted,
            "cascade_data": cascade_data,
            "cascade_deleted": cascade_deleted,
            "row_pk": row_pk,
            "batch_pk": batch_pk
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/delete", methods=["POST"])
def delete_upload_batch(batch_id):

    data = request.json or {}
    cascade_data = as_bool(data.get("cascade_data"), True)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        batch_pk = get_upload_batches_pk(cursor)
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
        bdel = f"""
            SELECT {batch_pk} AS id, state, batch_date
            FROM upload_batches
            WHERE {batch_pk} = %s
        """
        bargs = [batch_id]
        if has_ub_org:
            bdel += " AND organization_id = %s"
            bargs.append(tenant_oid)
        cursor.execute(bdel, tuple(bargs))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404

        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
        """, (batch_id,))
        row_count = (cursor.fetchone() or {}).get("cnt", 0) or 0

        cascade_deleted = {
            "orders_staging": 0,
            "orders_final": 0,
            "checkout_log": 0,
            "order_processing": 0,
        }
        if cascade_data:
            cursor.execute("""
                SELECT
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                  AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
            """, (batch_id,))
            identity_rows = cursor.fetchall()

            staging_ids = []
            if table_exists(cursor, "orders_staging"):
                has_staging_batch_date = table_has_column(cursor, "orders_staging", "batch_date")
                batch_day = batch.get("batch_date")
                if has_staging_batch_date and batch_day is not None:
                    sid_sql = "SELECT id FROM orders_staging WHERE batch_date = %s"
                    sid_args = [batch_day]
                    if table_has_column(cursor, "orders_staging", "organization_id"):
                        sid_sql += " AND organization_id = %s"
                        sid_args.append(tenant_oid)
                    cursor.execute(sid_sql, tuple(sid_args))
                    staging_ids = [int(r["id"]) for r in (cursor.fetchall() or [])]

                    if staging_ids and table_exists(cursor, "order_processing"):
                        placeholders = ", ".join(["%s"] * len(staging_ids))
                        cursor.execute(
                            f"DELETE FROM order_processing WHERE order_id IN ({placeholders})",
                            tuple(staging_ids),
                        )
                        cascade_deleted["order_processing"] = cursor.rowcount or 0

                    del_st = "DELETE FROM orders_staging WHERE batch_date = %s"
                    del_args = [batch_day]
                    if table_has_column(cursor, "orders_staging", "organization_id"):
                        del_st += " AND organization_id = %s"
                        del_args.append(tenant_oid)
                    cursor.execute(del_st, tuple(del_args))
                    cascade_deleted["orders_staging"] = cursor.rowcount or 0
                else:
                    for row in identity_rows:
                        sel_st = """
                            SELECT id
                            FROM orders_staging
                            WHERE UPPER(TRIM(name_clean)) = UPPER(TRIM(%s))
                              AND service_type = %s
                              AND ((weight_num IS NULL AND %s IS NULL) OR weight_num = %s)
                              AND date_clean = %s
                        """
                        st_args = [
                            row.get("name_clean"),
                            row.get("service_type"),
                            row.get("weight_num"),
                            row.get("weight_num"),
                            row.get("date_clean"),
                        ]
                        if table_has_column(cursor, "orders_staging", "organization_id"):
                            sel_st += " AND organization_id = %s"
                            st_args.append(tenant_oid)
                        cursor.execute(sel_st, tuple(st_args))
                        staging_ids.extend([r["id"] for r in cursor.fetchall()])

                    cascade_deleted["orders_staging"] = delete_identity_rows(
                        cursor,
                        "orders_staging",
                        identity_rows,
                        "name_clean",
                        "weight_num",
                        "service_type",
                        "date_clean",
                        tenant_oid,
                    )

            if table_exists(cursor, "orders_final"):
                has_date_clean_final = table_has_column(cursor, "orders_final", "date_clean")
                if has_date_clean_final:
                    cascade_deleted["orders_final"] = delete_identity_rows(
                        cursor,
                        "orders_final",
                        identity_rows,
                        "name_clean",
                        "weight_num",
                        "service_type",
                        "date_clean",
                        tenant_oid,
                    )

            if table_exists(cursor, "checkout_log"):
                for row in identity_rows:
                    cursor.execute("""
                        DELETE FROM checkout_log
                        WHERE UPPER(TRIM(name)) = UPPER(TRIM(%s))
                          AND service = %s
                          AND ((weight IS NULL AND %s IS NULL) OR weight = %s)
                          AND rush_date = %s
                    """, (
                        row.get("name_clean"),
                        row.get("service_type"),
                        row.get("weight_num"),
                        row.get("weight_num"),
                        row.get("date_clean"),
                    ))
                    cascade_deleted["checkout_log"] += cursor.rowcount or 0

            if (
                staging_ids
                and table_exists(cursor, "order_processing")
                and not (
                    table_exists(cursor, "orders_staging")
                    and table_has_column(cursor, "orders_staging", "batch_date")
                    and batch.get("batch_date") is not None
                )
            ):
                placeholders = ", ".join(["%s"] * len(staging_ids))
                cursor.execute(
                    f"DELETE FROM order_processing WHERE order_id IN ({placeholders})",
                    tuple(staging_ids),
                )
                cascade_deleted["order_processing"] += cursor.rowcount or 0

        from backend.upload_batch_cleanup import delete_upload_batch_cascade

        ub_org = tenant_oid if has_ub_org else None
        deleted = delete_upload_batch_cascade(
            cursor, batch_id, organization_id=ub_org
        )
        scan_audit_deleted = deleted.get("upload_batch_scan_events", 0)

        conn.commit()
        return jsonify({
            "status": "batch_deleted",
            "batch_id": batch_id,
            "deleted_rows": row_count,
            "upload_batch_scan_events_deleted": scan_audit_deleted,
            "cascade_data": cascade_data,
            "cascade_deleted": cascade_deleted,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows", methods=["GET"])
def get_upload_batch_rows(batch_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    row_status = (request.args.get("row_status") or "").strip().upper()

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if not upload_batch_belongs_to_user_org(cursor, batch_id, tenant_oid):
            return jsonify({"error": "Batch not found"}), 404
        row_pk = get_upload_batch_rows_pk(cursor)
        ubr_tid_sel = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
        if row_status:
            cursor.execute(f"""
                SELECT
                    {row_pk} AS id,
                    upload_batch_id,
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    row_status,
                    reason,
                    created_at,
                    updated_at
                    {ubr_tid_sel}
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                AND row_status = %s
                ORDER BY {row_pk} ASC
            """, (batch_id, row_status))
        else:
            cursor.execute(f"""
                SELECT
                    {row_pk} AS id,
                    upload_batch_id,
                    date_clean,
                    name_clean,
                    weight_num,
                    service_type,
                    rush_type,
                    row_status,
                    reason,
                    created_at,
                    updated_at
                    {ubr_tid_sel}
                FROM upload_batch_rows
                WHERE upload_batch_id = %s
                ORDER BY {row_pk} ASC
            """, (batch_id,))

        rows = cursor.fetchall() or []
        from backend.rinse_bag_upload import enrich_upload_batch_rows_with_registry

        rows = enrich_upload_batch_rows_with_registry(cursor, tenant_oid, rows)
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/<int:row_id>/override", methods=["POST"])
def override_upload_batch_row(batch_id, row_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_admin_or_perm(conn, cursor, "upload.rows.edit")
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if not upload_batch_belongs_to_user_org(cursor, batch_id, tenant_oid):
            return jsonify({"error": "Batch not found"}), 404
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)

        cursor.execute(f"""
            SELECT {pk_col} AS id, batch_date, state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        cursor.execute(f"""
            SELECT {row_pk} AS id
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (batch_id, row_id))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({"error": "Batch row not found"}), 404

        date_clean = parse_date_value(data.get("date_clean")) if data.get("date_clean") not in [None, ""] else None
        name_clean = (data.get("name_clean") or "").strip()
        service_type = (data.get("service_type") or "").strip().upper()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()
        weight_num = normalize_weight(data.get("weight_num"))

        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400
        if service_type not in ["WF", "HD"]:
            return jsonify({"error": "service_type must be WF or HD"}), 400
        if rush_type not in ["RUSH", "NON-RUSH"]:
            return jsonify({"error": "rush_type must be RUSH or NON-RUSH"}), 400

        requested_row_status = (data.get("row_status") or "").strip().upper()
        requested_reason = (data.get("reason") or "").strip()

        reason = "OVERRIDDEN_BY_USER"
        row_status = "OVERRIDDEN"
        if date_clean and date_clean < batch["batch_date"]:
            row_status = "NEEDS_ATTENTION"
            reason = "OLDER_THAN_BATCH_DATE"

        allowed_manual_statuses = {
            "ACCEPTED",
            "OVERRIDDEN",
            "NEEDS_ATTENTION",
            "REJECTED_DUPLICATE",
            "DELETED",
        }
        if requested_row_status:
            if requested_row_status not in allowed_manual_statuses:
                return jsonify({"error": "row_status is invalid"}), 400
            row_status = requested_row_status

        if requested_reason:
            reason = requested_reason

        cursor.execute(f"""
            UPDATE upload_batch_rows
            SET
                date_clean = %s,
                name_clean = %s,
                weight_num = %s,
                service_type = %s,
                rush_type = %s,
                row_status = %s,
                reason = %s,
                updated_at = NOW()
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            row_status,
            reason,
            batch_id,
            row_id
        ))

        conn.commit()
        return jsonify({"status": "row_updated", "row_id": row_id, "row_status": row_status})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/<int:row_id>/delete", methods=["POST"])
def delete_upload_batch_row(batch_id, row_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_admin_or_perm(conn, cursor, "upload.rows.delete")
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if not upload_batch_belongs_to_user_org(cursor, batch_id, tenant_oid):
            return jsonify({"error": "Batch not found"}), 404
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)
        cursor.execute(f"""
            SELECT state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        cursor.execute(f"""
            UPDATE upload_batch_rows
            SET row_status = 'DELETED', reason = 'DELETED_BY_USER', updated_at = NOW()
            WHERE upload_batch_id = %s
            AND {row_pk} = %s
        """, (batch_id, row_id))
        conn.commit()
        return jsonify({"status": "row_deleted", "row_id": row_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/rows/add", methods=["POST"])
def add_upload_batch_row(batch_id):

    data = request.json or {}

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        if not upload_batch_belongs_to_user_org(cursor, batch_id, tenant_oid):
            return jsonify({"error": "Batch not found"}), 404
        pk_col = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)

        cursor.execute(f"""
            SELECT {pk_col} AS id, batch_date, state
            FROM upload_batches
            WHERE {pk_col} = %s
        """, (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"error": "Batch is already confirmed"}), 409

        date_clean = parse_date_value(data.get("date_clean")) if data.get("date_clean") not in [None, ""] else None
        name_clean = (data.get("name_clean") or "").strip()
        service_type = (data.get("service_type") or "").strip().upper()
        rush_type = (data.get("rush_type") or "NON-RUSH").strip().upper()
        weight_num = normalize_weight(data.get("weight_num"))

        if not date_clean:
            return jsonify({"error": "date_clean is required"}), 400
        if not name_clean:
            return jsonify({"error": "name_clean is required"}), 400
        if service_type not in ["WF", "HD"]:
            return jsonify({"error": "service_type must be WF or HD"}), 400
        if rush_type not in ["RUSH", "NON-RUSH"]:
            return jsonify({"error": "rush_type must be RUSH or NON-RUSH"}), 400

        row_status = "OVERRIDDEN"
        reason = "ADDED_BY_USER"
        if date_clean < batch["batch_date"]:
            row_status = "NEEDS_ATTENTION"
            reason = "OLDER_THAN_BATCH_DATE"

        cursor.execute("""
            INSERT INTO upload_batch_rows
            (
                upload_batch_id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                row_status,
                reason,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (
            batch_id,
            date_clean,
            name_clean,
            weight_num,
            service_type,
            rush_type,
            row_status,
            reason
        ))
        new_row_id = cursor.lastrowid
        conn.commit()
        return jsonify({"status": "row_added", "row_id": new_row_id, "row_status": row_status})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_batches/<int:batch_id>/confirm", methods=["POST"])
def confirm_upload_batch(batch_id):

    data = request.json or {}
    force_confirm = bool(data.get("force_confirm"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        batch_pk = get_upload_batches_pk(cursor)
        row_pk = get_upload_batch_rows_pk(cursor)
        ensure_ticket_id_columns(cursor)
        ensure_upload_batch_rows_ticket_id(cursor)
        cap = orders_status_capabilities(cursor)
        has_staging_org = table_has_column(cursor, "orders_staging", "organization_id")
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
        has_final_org = table_exists(cursor, "orders_final") and table_has_column(
            cursor, "orders_final", "organization_id"
        )

        bq = f"""
            SELECT {batch_pk} AS id, batch_date, state
            FROM upload_batches
            WHERE {batch_pk} = %s
        """
        barg = [batch_id]
        if has_ub_org:
            bq += " AND organization_id = %s"
            barg.append(tenant_oid)
        cursor.execute(bq, tuple(barg))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if (batch.get("state") or "").upper() == "CONFIRMED":
            return jsonify({"status": "already_confirmed"}), 200

        from backend.upload_batch_requirements import validate_batch_confirm_dual_csv

        dual_block = validate_batch_confirm_dual_csv(cursor, batch_id, tenant_oid)
        if dual_block:
            return jsonify(dual_block), 409

        cursor.execute(f"""
            SELECT COUNT(*) AS attention_count
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status = 'NEEDS_ATTENTION'
        """, (batch_id,))
        attention_count = (cursor.fetchone() or {}).get("attention_count", 0) or 0
        if attention_count > 0 and not force_confirm:
            return jsonify({
                "error": "Batch has NEEDS_ATTENTION rows",
                "attention_count": attention_count
            }), 409

        ubr_tid_sel = ", ticket_id" if table_has_column(cursor, "upload_batch_rows", "ticket_id") else ""
        cursor.execute(f"""
            SELECT
                {row_pk} AS id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type
                {ubr_tid_sel}
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status IN ('ACCEPTED', 'OVERRIDDEN')
        """, (batch_id,))
        accepted_rows = list(cursor.fetchall() or [])

        from backend.rinse_bag_completion import normalize_bag_id
        from backend.rinse_bag_upload import (
            find_active_staging_by_ticket_id,
            update_staging_from_upload_row,
        )

        active_where = where_not_sent_or_forced_sql(cap)

        # Safety guard: do not let a fully rejected draft mutate live staging/final.
        if len(accepted_rows) == 0:
            from backend.upload_batch_requirements import batch_upload_files_status

            ufs = batch_upload_files_status(cursor, batch_id, tenant_oid)
            if ufs.get("has_scan_events") and not ufs.get("require_both_csv"):
                pass  # override: scan-events-only batch (no order rows to apply)
            else:
                return jsonify({
                    "error": "Batch has no ACCEPTED/OVERRIDDEN rows. Nothing to apply.",
                    "accepted_count": 0
                }), 409

        uploaded_identity_keys = set()
        for row in accepted_rows:
            uploaded_identity_keys.add(
                build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            )

        logistics_sql = orders_logistics_select_sql(cap)
        processing_sql = orders_processing_select_sql(cap)
        not_sent_where = where_not_sent_or_forced_sql(cap)

        stag_sql = f"""
            SELECT
                id,
                date_clean,
                name_clean,
                weight_num,
                service_type,
                rush_type,
                {logistics_sql},
                {processing_sql},
                status,
                batch_date
            FROM orders_staging
            WHERE {not_sent_where}
            AND (
                batch_date IS NULL
                OR batch_date < %s
            )
        """
        stag_args = [batch["batch_date"]]
        if has_staging_org:
            stag_sql += " AND organization_id = %s"
            stag_args.append(tenant_oid)
        cursor.execute(stag_sql, tuple(stag_args))
        staging_rows = cursor.fetchall()

        forced_pending = 0
        moved_to_final = 0
        for row in staging_rows:
            identity_key = build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            if identity_key in uploaded_identity_keys:
                continue

            row_processing = (row.get("processing_status") or row.get("status") or "").upper()
            if row_processing == "PROCESSED":
                if has_final_org:
                    cursor.execute("""
                        INSERT INTO orders_final
                        (
                            organization_id,
                            date_clean,
                            name_clean,
                            weight_num,
                            service_type,
                            rush_type,
                            cleaned_by,
                            cleaned_at,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        tenant_oid,
                        row["date_clean"],
                        row["name_clean"],
                        row["weight_num"],
                        row["service_type"],
                        row["rush_type"],
                        "SYSTEM_FORCE"
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO orders_final
                        (
                            date_clean,
                            name_clean,
                            weight_num,
                            service_type,
                            rush_type,
                            cleaned_by,
                            cleaned_at,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        row["date_clean"],
                        row["name_clean"],
                        row["weight_num"],
                        row["service_type"],
                        row["rush_type"],
                        "SYSTEM_FORCE"
                    ))
                del_sql = "DELETE FROM orders_staging WHERE id = %s"
                del_args = [row["id"]]
                if has_staging_org:
                    del_sql += " AND organization_id = %s"
                    del_args.append(tenant_oid)
                cursor.execute(del_sql, tuple(del_args))
                moved_to_final += 1
            else:
                set_parts = []
                if cap["has_logistics"]:
                    set_parts.append("logistics_status = 'FORCE_CHECKOUT'")
                if cap["has_status"]:
                    set_parts.append("status = 'FORCED_CHECKOUT'")
                if not set_parts:
                    set_parts.append("status = 'FORCED_CHECKOUT'")

                upd_sql = f"""
                    UPDATE orders_staging
                    SET {", ".join(set_parts)}
                    WHERE id = %s
                """
                upd_args = [row["id"]]
                if has_staging_org:
                    upd_sql += " AND organization_id = %s"
                    upd_args.append(tenant_oid)
                cursor.execute(upd_sql, tuple(upd_args))
                forced_pending += 1

        cur_sql = f"""
            SELECT date_clean, name_clean, weight_num, service_type
            FROM orders_staging
            WHERE {not_sent_where}
        """
        cur_args = []
        if has_staging_org:
            cur_sql += " AND organization_id = %s"
            cur_args.append(tenant_oid)
        cursor.execute(cur_sql, tuple(cur_args))
        current_staging_rows = cursor.fetchall()
        existing_identity_before_insert = set(
            build_identity_key(r["name_clean"], r["weight_num"], r["service_type"], r["date_clean"])
            for r in current_staging_rows
        )

        inserted = 0
        staging_updated = 0
        for row in accepted_rows:
            tid = normalize_bag_id(row.get("ticket_id")) if row.get("ticket_id") else ""
            if tid and cap.get("has_ticket_id"):
                existing_staging = find_active_staging_by_ticket_id(
                    cursor,
                    tenant_oid,
                    tid,
                    active_where,
                    has_staging_org=has_staging_org,
                    has_ticket_id_col=True,
                )
                if existing_staging:
                    update_staging_from_upload_row(
                        cursor,
                        int(existing_staging["id"]),
                        row,
                        batch["batch_date"],
                        cap,
                        organization_id=tenant_oid,
                        has_staging_org=has_staging_org,
                    )
                    staging_updated += 1
                    cursor.execute(
                        """
                        UPDATE rinse_bag_registry
                        SET last_staging_order_id = %s, updated_at = NOW()
                        WHERE organization_id = %s AND bag_id = %s
                        """,
                        (int(existing_staging["id"]), tenant_oid, tid),
                    )
                    uploaded_identity_keys.add(
                        build_identity_key(
                            row["name_clean"],
                            row["weight_num"],
                            row["service_type"],
                            row["date_clean"],
                        )
                    )
                    continue

            identity_key = build_identity_key(row["name_clean"], row["weight_num"], row["service_type"], row["date_clean"])
            if identity_key in existing_identity_before_insert:
                continue

            cols = [
                "date_clean",
                "name_clean",
                "weight_num",
                "service_type",
                "rush_type",
                "batch_date",
            ]
            vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
            args = [
                row["date_clean"],
                row["name_clean"],
                row["weight_num"],
                row["service_type"],
                row["rush_type"],
                batch["batch_date"],
            ]

            if has_staging_org:
                cols = ["organization_id"] + cols
                vals = ["%s"] + vals
                args = [tenant_oid] + args

            if cap["has_logistics"]:
                cols.append("logistics_status")
                vals.append("%s")
                args.append("AT_WASHPRO")
            if cap["has_processing"]:
                cols.append("processing_status")
                vals.append("%s")
                args.append("PENDING")
            if cap.get("has_status"):
                cols.append("status")
                vals.append("%s")
                args.append("PENDING")

            if cap.get("has_ticket_id") and tid:
                cols.append("ticket_id")
                vals.append("%s")
                args.append(tid[:120])

            cursor.execute(f"""
                INSERT INTO orders_staging
                ({", ".join(cols)})
                VALUES ({", ".join(vals)})
            """, tuple(args))
            new_staging_id = cursor.lastrowid
            inserted += 1
            if tid:
                cursor.execute(
                    """
                    UPDATE rinse_bag_registry
                    SET last_staging_order_id = %s, updated_at = NOW()
                    WHERE organization_id = %s AND bag_id = %s
                    """,
                    (int(new_staging_id), tenant_oid, tid),
                )
            uploaded_identity_keys.add(identity_key)
            existing_identity_before_insert.add(identity_key)

        set_parts = ["state = 'CONFIRMED'"] if table_has_column(cursor, "upload_batches", "state") else []
        if table_has_column(cursor, "upload_batches", "confirmed_at"):
            set_parts.append("confirmed_at = NOW()")
        if table_has_column(cursor, "upload_batches", "closed_at"):
            set_parts.append("closed_at = NOW()")
        if table_has_column(cursor, "upload_batches", "updated_at"):
            set_parts.append("updated_at = NOW()")

        if set_parts:
            cursor.execute(f"""
                UPDATE upload_batches
                SET {", ".join(set_parts)}
                WHERE {batch_pk} = %s
            """, (batch_id,))

        conn.commit()
        return jsonify({
            "status": "batch_confirmed",
            "batch_id": batch_id,
            "inserted_to_staging": inserted,
            "staging_updated_by_bag_id": staging_updated,
            "forced_checkout_pending": forced_pending,
            "moved_to_final": moved_to_final,
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Upload Conflict Review APIs (legacy)
# ---------------------------------------------------

@app.route("/upload_conflicts", methods=["GET"])
def get_upload_conflicts():

    batch_id = request.args.get("batch_id")
    status = (request.args.get("status") or "PENDING").strip().upper()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        pk_col = get_upload_conflicts_pk(cursor)
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
        join_ub = ""
        if has_ub_org:
            join_ub = "INNER JOIN upload_batches ub ON ub.id = c.upload_batch_id AND ub.organization_id = %s"
        if batch_id not in [None, ""]:
            if has_ub_org:
                cursor.execute(f"""
                    SELECT
                        c.{pk_col} AS id,
                        c.upload_batch_id,
                        c.name_clean,
                        c.weight_num,
                        c.service_type,
                        c.date_clean,
                        c.rush_type,
                        c.reason,
                        c.status,
                        c.created_at
                    FROM upload_conflicts c
                    {join_ub}
                    WHERE c.upload_batch_id = %s
                    AND c.status = %s
                    ORDER BY c.{pk_col} ASC
                """, (tenant_oid, int(batch_id), status))
            else:
                cursor.execute("""
                    SELECT
                        {pk} AS id,
                        upload_batch_id,
                        name_clean,
                        weight_num,
                        service_type,
                        date_clean,
                        rush_type,
                        reason,
                        status,
                        created_at
                    FROM upload_conflicts
                    WHERE upload_batch_id = %s
                    AND status = %s
                    ORDER BY {pk} ASC
                """.format(pk=pk_col), (int(batch_id), status))
        else:
            if has_ub_org:
                cursor.execute(f"""
                    SELECT
                        c.{pk_col} AS id,
                        c.upload_batch_id,
                        c.name_clean,
                        c.weight_num,
                        c.service_type,
                        c.date_clean,
                        c.rush_type,
                        c.reason,
                        c.status,
                        c.created_at
                    FROM upload_conflicts c
                    {join_ub}
                    WHERE c.status = %s
                    ORDER BY c.{pk_col} ASC
                    LIMIT 500
                """, (tenant_oid, status))
            else:
                cursor.execute("""
                    SELECT
                        {pk} AS id,
                        upload_batch_id,
                        name_clean,
                        weight_num,
                        service_type,
                        date_clean,
                        rush_type,
                        reason,
                        status,
                        created_at
                    FROM upload_conflicts
                    WHERE status = %s
                    ORDER BY {pk} ASC
                    LIMIT 500
                """.format(pk=pk_col), (status,))

        return jsonify(cursor.fetchall())

    finally:
        cursor.close()
        conn.close()


@app.route("/upload_conflicts/override", methods=["POST"])
def override_upload_conflicts():

    data = request.json or {}
    conflict_ids = data.get("conflict_ids") or []
    overridden_by = (data.get("overridden_by") or "").strip() or "admin"

    if not isinstance(conflict_ids, list) or not conflict_ids:
        return jsonify({"error": "conflict_ids must be a non-empty array"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        me, err_resp, err_code = require_user(cursor)
        if err_resp:
            return err_resp, err_code
        tenant_oid = user_org_id(me)
        pk_col = get_upload_conflicts_pk(cursor)
        cap = orders_status_capabilities(cursor)
        placeholders = ",".join(["%s"] * len(conflict_ids))
        has_ub_org = table_has_column(cursor, "upload_batches", "organization_id")
        if has_ub_org:
            cursor.execute(f"""
                SELECT
                    c.{pk_col} AS id,
                    c.name_clean,
                    c.weight_num,
                    c.service_type,
                    c.date_clean,
                    c.rush_type,
                    c.upload_batch_id
                FROM upload_conflicts c
                INNER JOIN upload_batches ub ON ub.id = c.upload_batch_id AND ub.organization_id = %s
                WHERE c.{pk_col} IN ({placeholders})
                AND c.status = 'PENDING'
            """, (tenant_oid,) + tuple(conflict_ids))
        else:
            cursor.execute(f"""
                SELECT
                    {pk_col} AS id,
                    name_clean,
                    weight_num,
                    service_type,
                    date_clean,
                    rush_type,
                    upload_batch_id
                FROM upload_conflicts
                WHERE {pk_col} IN ({placeholders})
                AND status = 'PENDING'
            """, tuple(conflict_ids))
        rows = cursor.fetchall()

        inserted = 0
        today_batch_date = date.today()

        for row in rows:
            cols = [
                "date_clean",
                "name_clean",
                "weight_num",
                "service_type",
                "rush_type",
                "batch_date",
            ]
            vals = ["%s", "%s", "%s", "%s", "%s", "%s"]
            args = [
                row["date_clean"],
                row["name_clean"],
                row["weight_num"],
                row["service_type"],
                row["rush_type"],
                today_batch_date,
            ]

            if table_has_column(cursor, "orders_staging", "organization_id"):
                cols = ["organization_id"] + cols
                vals = ["%s"] + vals
                args = [tenant_oid] + args

            if cap["has_logistics"]:
                cols.append("logistics_status")
                vals.append("%s")
                args.append("AT_WASHPRO")
            if cap["has_processing"]:
                cols.append("processing_status")
                vals.append("%s")
                args.append("PENDING")
            if cap["has_status"]:
                cols.append("status")
                vals.append("%s")
                args.append("PENDING")

            cursor.execute(f"""
                INSERT INTO orders_staging
                ({", ".join(cols)})
                VALUES ({", ".join(vals)})
            """, tuple(args))
            inserted += 1

            cursor.execute("""
                UPDATE upload_conflicts
                SET
                    status = 'OVERRIDDEN',
                    overridden_by = %s,
                    overridden_at = NOW()
                WHERE {pk} = %s
            """.format(pk=pk_col), (
                overridden_by,
                row["id"]
            ))

        conn.commit()

        return jsonify({
            "status": "overridden",
            "requested": len(conflict_ids),
            "overridden": inserted
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# CleanCloud Integration APIs
# ---------------------------------------------------

def ensure_cleancloud_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleancloud_webhook_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_id VARCHAR(120) NULL,
            event_type VARCHAR(80) NULL,
            payload_json LONGTEXT NOT NULL,
            process_status VARCHAR(20) NOT NULL DEFAULT 'RECEIVED',
            error_message VARCHAR(500) NULL,
            received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME NULL,
            updated_at DATETIME NULL,
            UNIQUE KEY ux_cleancloud_event_id (event_id),
            INDEX idx_cleancloud_event_type (event_type),
            INDEX idx_cleancloud_received_at (received_at)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleancloud_customers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            cleancloud_customer_id VARCHAR(120) NOT NULL,
            first_name VARCHAR(120) NULL,
            last_name VARCHAR(120) NULL,
            full_name VARCHAR(255) NULL,
            phone VARCHAR(60) NULL,
            email VARCHAR(255) NULL,
            status VARCHAR(60) NULL,
            address_line1 VARCHAR(255) NULL,
            address_line2 VARCHAR(255) NULL,
            city VARCHAR(120) NULL,
            state VARCHAR(120) NULL,
            postal_code VARCHAR(40) NULL,
            country VARCHAR(120) NULL,
            raw_json LONGTEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL,
            last_seen_at DATETIME NULL,
            UNIQUE KEY ux_cleancloud_customer_id (cleancloud_customer_id),
            INDEX idx_cleancloud_customer_name (full_name),
            INDEX idx_cleancloud_customer_phone (phone),
            INDEX idx_cleancloud_customer_email (email)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleancloud_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            cleancloud_order_id VARCHAR(120) NOT NULL,
            cleancloud_customer_id VARCHAR(120) NULL,
            order_status VARCHAR(80) NULL,
            payment_status VARCHAR(80) NULL,
            service_type VARCHAR(120) NULL,
            pickup_date DATETIME NULL,
            delivery_date DATETIME NULL,
            total_amount DECIMAL(10,2) NULL,
            currency VARCHAR(10) NULL,
            cleaned_by VARCHAR(150) NULL,
            picked_up_by VARCHAR(150) NULL,
            delivered_by VARCHAR(150) NULL,
            ticket_number VARCHAR(120) NULL,
            raw_json LONGTEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL,
            last_seen_at DATETIME NULL,
            UNIQUE KEY ux_cleancloud_order_id (cleancloud_order_id),
            INDEX idx_cleancloud_order_status (order_status),
            INDEX idx_cleancloud_order_customer (cleancloud_customer_id),
            INDEX idx_cleancloud_order_delivery (delivery_date)
        )
    """)


def _cleancloud_secret_is_valid():
    expected = (os.getenv("CLEANCLOUD_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return True

    candidate = (
        request.headers.get("X-CleanCloud-Secret")
        or request.headers.get("X-Webhook-Secret")
        or request.args.get("secret")
        or ""
    ).strip()
    return candidate == expected


def _safe_json_text(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"raw": str(value)}, ensure_ascii=False)


def _get_nested(data, path, default=None):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _parse_cleancloud_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    text = str(value).strip()
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]:
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%m/%d/%Y"}:
                return datetime.combine(parsed.date(), datetime.min.time())
            return parsed
        except Exception:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _cleancloud_event_records(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("events"), list):
            return [e for e in payload["events"] if isinstance(e, dict)]
        return [payload]
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    return []


def _extract_customer_obj(record):
    if not isinstance(record, dict):
        return None
    customer = record.get("customer")
    if isinstance(customer, dict):
        return customer
    if any(k in record for k in ["customer_id", "first_name", "last_name", "email", "phone"]):
        return record
    return None


def _extract_order_obj(record):
    if not isinstance(record, dict):
        return None
    order = record.get("order")
    if isinstance(order, dict):
        return order
    if any(k in record for k in ["order_id", "status", "payment_status", "delivery_date", "pickup_date"]):
        return record
    return None


def _upsert_cleancloud_customer(cursor, customer_obj):
    if not isinstance(customer_obj, dict):
        return None

    customer_id = (
        customer_obj.get("id")
        or customer_obj.get("customer_id")
        or customer_obj.get("customerId")
    )
    if not customer_id:
        return None

    first_name = customer_obj.get("first_name") or customer_obj.get("firstname")
    last_name = customer_obj.get("last_name") or customer_obj.get("lastname")
    full_name = (
        customer_obj.get("full_name")
        or customer_obj.get("name")
        or " ".join([x for x in [first_name, last_name] if x]).strip()
        or None
    )

    cursor.execute("""
        INSERT INTO cleancloud_customers
        (
            cleancloud_customer_id,
            first_name,
            last_name,
            full_name,
            phone,
            email,
            status,
            address_line1,
            address_line2,
            city,
            state,
            postal_code,
            country,
            raw_json,
            last_seen_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            full_name = VALUES(full_name),
            phone = VALUES(phone),
            email = VALUES(email),
            status = VALUES(status),
            address_line1 = VALUES(address_line1),
            address_line2 = VALUES(address_line2),
            city = VALUES(city),
            state = VALUES(state),
            postal_code = VALUES(postal_code),
            country = VALUES(country),
            raw_json = VALUES(raw_json),
            last_seen_at = NOW(),
            updated_at = NOW()
    """, (
        str(customer_id),
        first_name,
        last_name,
        full_name,
        customer_obj.get("phone") or customer_obj.get("mobile"),
        customer_obj.get("email"),
        customer_obj.get("status"),
        customer_obj.get("address_line1") or customer_obj.get("address1"),
        customer_obj.get("address_line2") or customer_obj.get("address2"),
        customer_obj.get("city"),
        customer_obj.get("state"),
        customer_obj.get("postal_code") or customer_obj.get("postcode") or customer_obj.get("zip"),
        customer_obj.get("country"),
        _safe_json_text(customer_obj),
    ))

    return str(customer_id)


def _upsert_cleancloud_order(cursor, order_obj, customer_id_hint=None):
    if not isinstance(order_obj, dict):
        return None

    order_id = (
        order_obj.get("id")
        or order_obj.get("order_id")
        or order_obj.get("orderId")
    )
    if not order_id:
        return None

    customer_id = (
        order_obj.get("customer_id")
        or order_obj.get("customerId")
        or _get_nested(order_obj, ["customer", "id"])
        or customer_id_hint
    )

    total_amount_raw = (
        order_obj.get("total_amount")
        or order_obj.get("amount")
        or order_obj.get("total")
    )
    total_amount = None
    if total_amount_raw not in [None, ""]:
        try:
            total_amount = round(float(total_amount_raw), 2)
        except Exception:
            total_amount = None

    cursor.execute("""
        INSERT INTO cleancloud_orders
        (
            cleancloud_order_id,
            cleancloud_customer_id,
            order_status,
            payment_status,
            service_type,
            pickup_date,
            delivery_date,
            total_amount,
            currency,
            cleaned_by,
            picked_up_by,
            delivered_by,
            ticket_number,
            raw_json,
            last_seen_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            cleancloud_customer_id = VALUES(cleancloud_customer_id),
            order_status = VALUES(order_status),
            payment_status = VALUES(payment_status),
            service_type = VALUES(service_type),
            pickup_date = VALUES(pickup_date),
            delivery_date = VALUES(delivery_date),
            total_amount = VALUES(total_amount),
            currency = VALUES(currency),
            cleaned_by = VALUES(cleaned_by),
            picked_up_by = VALUES(picked_up_by),
            delivered_by = VALUES(delivered_by),
            ticket_number = VALUES(ticket_number),
            raw_json = VALUES(raw_json),
            last_seen_at = NOW(),
            updated_at = NOW()
    """, (
        str(order_id),
        str(customer_id) if customer_id not in [None, ""] else None,
        order_obj.get("status") or order_obj.get("order_status"),
        order_obj.get("payment_status") or order_obj.get("paymentStatus"),
        order_obj.get("service_type") or order_obj.get("service"),
        _parse_cleancloud_datetime(order_obj.get("pickup_date") or order_obj.get("pickupDate")),
        _parse_cleancloud_datetime(order_obj.get("delivery_date") or order_obj.get("deliveryDate") or order_obj.get("due_date")),
        total_amount,
        order_obj.get("currency"),
        order_obj.get("cleaned_by") or order_obj.get("cleaner_name"),
        order_obj.get("picked_up_by") or order_obj.get("pickup_driver"),
        order_obj.get("delivered_by") or order_obj.get("delivery_driver"),
        order_obj.get("ticket_number") or order_obj.get("ticket_id"),
        _safe_json_text(order_obj),
    ))

    return str(order_id)


@app.route("/integrations/cleancloud/webhook", methods=["POST"])
def cleancloud_webhook():
    if not _cleancloud_secret_is_valid():
        return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict(flat=True)

    events = _cleancloud_event_records(payload)
    if not events:
        return jsonify({"error": "No event payload received"}), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        ensure_cleancloud_tables(cursor)

        inserted = 0
        processed = 0
        duplicate = 0

        for record in events:
            event_type = (
                record.get("event")
                or record.get("event_type")
                or record.get("type")
                or "unknown"
            )
            event_id = (
                record.get("event_id")
                or record.get("id")
                or request.headers.get("X-Webhook-Event-Id")
            )
            payload_text = _safe_json_text(record)

            row_id = None
            if event_id:
                cursor.execute(
                    "SELECT id FROM cleancloud_webhook_events WHERE event_id = %s LIMIT 1",
                    (str(event_id),)
                )
                already = cursor.fetchone()
                cursor.execute("""
                    INSERT INTO cleancloud_webhook_events
                    (
                        event_id,
                        event_type,
                        payload_json,
                        process_status,
                        received_at
                    )
                    VALUES (%s, %s, %s, 'RECEIVED', NOW())
                    ON DUPLICATE KEY UPDATE
                        event_type = VALUES(event_type),
                        payload_json = VALUES(payload_json),
                        updated_at = NOW()
                """, (
                    str(event_id),
                    str(event_type),
                    payload_text
                ))
                cursor.execute("SELECT id FROM cleancloud_webhook_events WHERE event_id = %s LIMIT 1", (str(event_id),))
                existing = cursor.fetchone()
                row_id = existing["id"] if existing else None
                if already:
                    duplicate += 1
                else:
                    inserted += 1
            else:
                cursor.execute("""
                    INSERT INTO cleancloud_webhook_events
                    (
                        event_id,
                        event_type,
                        payload_json,
                        process_status,
                        received_at
                    )
                    VALUES (NULL, %s, %s, 'RECEIVED', NOW())
                """, (
                    str(event_type),
                    payload_text
                ))
                row_id = cursor.lastrowid
                inserted += 1

            try:
                customer_obj = _extract_customer_obj(record)
                order_obj = _extract_order_obj(record)
                customer_id = _upsert_cleancloud_customer(cursor, customer_obj)
                _upsert_cleancloud_order(cursor, order_obj, customer_id_hint=customer_id)

                cursor.execute("""
                    UPDATE cleancloud_webhook_events
                    SET process_status = 'PROCESSED',
                        processed_at = NOW(),
                        updated_at = NOW(),
                        error_message = NULL
                    WHERE id = %s
                """, (row_id,))
                processed += 1
            except Exception as process_ex:
                cursor.execute("""
                    UPDATE cleancloud_webhook_events
                    SET process_status = 'ERROR',
                        updated_at = NOW(),
                        error_message = %s
                    WHERE id = %s
                """, (str(process_ex)[:500], row_id))

        conn.commit()

        return jsonify({
            "status": "ok",
            "received": len(events),
            "inserted": inserted,
            "processed": processed,
            "duplicate_event_ids": duplicate
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/integrations/cleancloud/events", methods=["GET"])
def cleancloud_events():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_cleancloud_tables(cursor)
        limit = request.args.get("limit", 100)
        try:
            limit = max(1, min(500, int(limit)))
        except Exception:
            limit = 100

        cursor.execute(f"""
            SELECT
                id,
                event_id,
                event_type,
                process_status,
                error_message,
                received_at,
                processed_at
            FROM cleancloud_webhook_events
            ORDER BY id DESC
            LIMIT {limit}
        """)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/integrations/cleancloud/customers", methods=["GET"])
def cleancloud_customers():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_cleancloud_tables(cursor)
        limit = request.args.get("limit", 200)
        try:
            limit = max(1, min(1000, int(limit)))
        except Exception:
            limit = 200

        search = (request.args.get("search") or "").strip()
        where_sql = ""
        args = []
        if search:
            where_sql = """
                WHERE
                    full_name LIKE %s
                    OR phone LIKE %s
                    OR email LIKE %s
                    OR cleancloud_customer_id LIKE %s
            """
            like = f"%{search}%"
            args.extend([like, like, like, like])

        cursor.execute(f"""
            SELECT
                cleancloud_customer_id,
                full_name,
                first_name,
                last_name,
                phone,
                email,
                status,
                city,
                state,
                postal_code,
                last_seen_at
            FROM cleancloud_customers
            {where_sql}
            ORDER BY id DESC
            LIMIT {limit}
        """, tuple(args))
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/integrations/cleancloud/orders", methods=["GET"])
def cleancloud_orders():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_cleancloud_tables(cursor)
        limit = request.args.get("limit", 200)
        try:
            limit = max(1, min(1000, int(limit)))
        except Exception:
            limit = 200

        status_filter = (request.args.get("status") or "").strip()
        where_sql = ""
        args = []
        if status_filter:
            where_sql = "WHERE order_status = %s"
            args.append(status_filter)

        cursor.execute(f"""
            SELECT
                cleancloud_order_id,
                cleancloud_customer_id,
                order_status,
                payment_status,
                service_type,
                pickup_date,
                delivery_date,
                total_amount,
                currency,
                cleaned_by,
                picked_up_by,
                delivered_by,
                ticket_number,
                last_seen_at
            FROM cleancloud_orders
            {where_sql}
            ORDER BY id DESC
            LIMIT {limit}
        """, tuple(args))
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route("/integrations/cleancloud/health", methods=["GET"])
def cleancloud_health():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_cleancloud_tables(cursor)
        cursor.execute("SELECT COUNT(*) AS c FROM cleancloud_webhook_events")
        events = (cursor.fetchone() or {}).get("c", 0)
        cursor.execute("SELECT COUNT(*) AS c FROM cleancloud_customers")
        customers = (cursor.fetchone() or {}).get("c", 0)
        cursor.execute("SELECT COUNT(*) AS c FROM cleancloud_orders")
        orders = (cursor.fetchone() or {}).get("c", 0)

        cursor.execute("""
            SELECT id, event_type, process_status, received_at, processed_at
            FROM cleancloud_webhook_events
            ORDER BY id DESC
            LIMIT 1
        """)
        last_event = cursor.fetchone()

        return jsonify({
            "status": "ok",
            "tables_ready": True,
            "webhook_events": events,
            "customers": customers,
            "orders": orders,
            "last_event": last_event,
        })
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------
# Root Health Endpoint
# ---------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "LaundryOps API",
        "status": "running"
    })


@app.route("/health/db", methods=["GET"])
def health_db():
    """Returns 200 + {\"ok\": true} if MySQL is reachable; 503 with error text otherwise."""
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


register_rinse_folding_routes(
    app,
    require_user=require_user,
    require_admin=require_admin,
    user_org_id=user_org_id,
    parse_date_value=parse_date_value,
)
