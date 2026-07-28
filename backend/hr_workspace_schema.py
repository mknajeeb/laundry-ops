"""DDL helpers for People / payroll workspace: org_hr_lookup + payroll_profiles extension columns."""

from __future__ import annotations

# If you add columns here, bump _PEOPLE_WORKSPACE_ENSURE_VERSION in backend/ta_routes.py
# so running workers re-apply ALTER once per organization.
WORKSPACE_PAYROLL_EXTRA = [
    ("dept_code", "VARCHAR(64) NULL"),
    ("job_title_code", "VARCHAR(64) NULL"),
    ("employment_status_code", "VARCHAR(64) NULL"),
    ("language_code", "VARCHAR(64) NULL"),
    ("laundry_experience", "TINYINT(1) NULL"),
    ("clock_geofence_exempt", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("clock_in_gate_exempt", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("attendance_pin_hash", "VARCHAR(255) NULL COMMENT 'Werkzeug hash; shared-device PIN unlock'"),
    (
        "attendance_pin_last4",
        "VARCHAR(4) NULL COMMENT 'Plain last-4 for kiosk lookup; verify via attendance_pin_hash'",
    ),
]

# Excludes attendance_pin_hash — set only via plaintext `attendance_pin` in API (hashed server-side).
WORKSPACE_PAYROLL_EXTRA_KEYS = tuple(
    x[0] for x in WORKSPACE_PAYROLL_EXTRA if x[0] != "attendance_pin_hash"
)


def ensure_people_workspace_schema(cursor) -> None:
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "org_hr_lookup"):
        cursor.execute(
            """
            CREATE TABLE org_hr_lookup (
              id INT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              category VARCHAR(32) NOT NULL,
              code VARCHAR(64) NOT NULL,
              label VARCHAR(255) NOT NULL,
              sort_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uq_org_hr_lookup (organization_id, category, code),
              KEY ix_org_hr_lookup_org_cat (organization_id, category, active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, "payroll_profiles"):
        return
    for col, ddl in WORKSPACE_PAYROLL_EXTRA:
        if table_has_column(cursor, "payroll_profiles", col):
            continue
        cursor.execute(f"ALTER TABLE payroll_profiles ADD COLUMN {col} {ddl}")


def seed_org_hr_lookups_if_empty(cursor, organization_id: int) -> None:
    defaults = [
        ("department", "OPS", "Operations", 10),
        ("department", "PRODUCTION", "Production", 20),
        ("department", "FRONT", "Front desk", 30),
        ("job_title", "ATTENDANT", "Attendant", 10),
        ("job_title", "SUPERVISOR", "Supervisor", 20),
        ("job_title", "MANAGER", "Manager", 30),
        ("employment_status", "ACTIVE", "Active", 10),
        ("employment_status", "TERMINATED", "Terminated", 20),
        ("employment_status", "REHIRED", "Rehired", 30),
        ("language_pref", "en", "English", 10),
        ("language_pref", "es", "Spanish", 20),
    ]
    for cat, code, label, sort in defaults:
        cursor.execute(
            "SELECT 1 FROM org_hr_lookup WHERE organization_id=%s AND category=%s AND code=%s LIMIT 1",
            (organization_id, cat, code),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            "INSERT INTO org_hr_lookup (organization_id, category, code, label, sort_order, active) VALUES (%s,%s,%s,%s,%s,1)",
            (organization_id, cat, code, label, sort),
        )


def seed_worker_categories_if_missing(cursor, organization_id: int) -> None:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, "employment_categories"):
        return
    specs = [
        ("EC_W2", "W-2 Employee"),
        ("EC_1099", "1099 Contractor"),
        ("EC_TEMP", "Temporary / seasonal"),
        ("EC_SYSTEM", "System user (not on payroll)"),
    ]
    for code, name in specs:
        cursor.execute(
            "SELECT id FROM employment_categories WHERE organization_id=%s AND code=%s LIMIT 1",
            (organization_id, code),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            "INSERT INTO employment_categories (organization_id, code, name, active) VALUES (%s,%s,%s,1)",
            (organization_id, code, name),
        )
