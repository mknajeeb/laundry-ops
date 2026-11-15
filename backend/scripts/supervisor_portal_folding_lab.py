#!/usr/bin/env python3
"""Sanitized folding day for the isolated supervisor portal.

Synthetic bags only. They are not a VeeWash historical result.
Refuses any host other than local MySQL.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MYSQL_HOST"] = "127.0.0.1"
os.environ["MYSQL_PORT"] = "3308"
os.environ["MYSQL_USER"] = "root"
os.environ["MYSQL_PASSWORD"] = "local-only"
os.environ["MYSQL_DATABASE"] = "supervisor_portal_isolated"
os.environ["FLASK_SECRET_KEY"] = "supervisor-local-isolated"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = ""

if "azure" in os.environ["MYSQL_HOST"] or os.environ["MYSQL_DATABASE"] == "laundryapp":
    raise SystemExit("Refusing production")

sys.path.insert(0, str(ROOT))

import mysql.connector

DAY = date(2026, 11, 16)
NEXT = date(2026, 11, 17)
ORG = 1


def connect():
    return mysql.connector.connect(
        host="127.0.0.1",
        port=3308,
        user="root",
        password="local-only",
        database="supervisor_portal_isolated",
        autocommit=True,
    )


def apply_sql(cursor, path: Path) -> None:
    buff: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        buff.append(line)
        if line.rstrip().endswith(";"):
            cursor.execute("\n".join(buff))
            buff = []


def ensure_lab_tables(cursor) -> None:
    apply_sql(cursor, ROOT / "backend/sql/rinse_bag_scan_events_v1.sql")
    apply_sql(cursor, ROOT / "backend/sql/rinse_order_instances_v1.sql")
    apply_sql(cursor, ROOT / "backend/sql/rinse_folding_user_map_v1.sql")
    apply_sql(cursor, ROOT / "backend/sql/rinse_step1_corrections_v1.sql")
    apply_sql(cursor, ROOT / "backend/sql/supervisor_portal_v1.sql")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_sessions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          clock_in_at DATETIME NOT NULL,
          clock_out_at DATETIME NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'completed'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_job_segments (
          id INT AUTO_INCREMENT PRIMARY KEY,
          shift_session_id INT NOT NULL,
          user_id INT NULL,
          category_id INT NULL,
          role_id INT NULL,
          category_role_id INT NULL,
          category_code VARCHAR(64) NULL,
          role_code VARCHAR(64) NULL,
          category_name_snapshot VARCHAR(128) NULL,
          role_name_snapshot VARCHAR(128) NULL,
          started_at DATETIME NOT NULL,
          ended_at DATETIME NULL,
          INDEX idx_sjs_session (shift_session_id, started_at)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
          organization_id INT NOT NULL,
          skey VARCHAR(128) NOT NULL,
          svalue TEXT NOT NULL,
          PRIMARY KEY (organization_id, skey)
        )
        """
    )
    for column, definition in (
        ("weight_lbs", "DECIMAL(10,2) NULL"),
        ("weight_role", "VARCHAR(16) NULL"),
        ("weight_source", "VARCHAR(64) NULL"),
        ("weight_observed_at", "DATETIME NULL"),
        ("weight_attach_reason", "VARCHAR(128) NULL"),
        ("weight_presence_run_id", "BIGINT NULL"),
        ("weight_presence_run_row_id", "BIGINT NULL"),
        ("weight_attach_batch_id", "BIGINT NULL"),
    ):
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = 'rinse_bag_scan_events' AND column_name = %s
            """,
            (column,),
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE rinse_bag_scan_events ADD COLUMN {column} {definition}")


def clear_lab(cursor) -> None:
    cursor.execute("DELETE FROM rinse_shift_monitor_day_bags WHERE organization_id=%s", (ORG,))
    for table in (
        "rinse_bag_scan_events",
        "rinse_order_instances",
        "rinse_step1_corrections",
        "rinse_folding_user_map",
        "rinse_performance_approval_events",
        "rinse_performance_session_approvals",
        "supervisor_session_adjustments",
        "shift_job_segments",
        "shift_sessions",
    ):
        cursor.execute("SHOW TABLES LIKE %s", (table,))
        if cursor.fetchone():
            cursor.execute(f"DELETE FROM {table}")


def insert_day_bag(cursor, day: date, bag: str, employee: str | None, pounds: float, when: str) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_shift_monitor_day_bags (
          organization_id, shift_date_et, bag_id, service_type, effective_status,
          canonical_completion_status, canonical_completion_timestamp, canonical_completion_employee,
          pre_weight_lbs, weight_lbs, productivity_employee_name, productivity_completed_at,
          productivity_weight_lbs, productivity_credit_eligible
        ) VALUES (%s, %s, %s, 'WF', 'completed', 'completed', %s, %s, %s, %s, %s, %s, %s, 1)
        """,
        (ORG, day, bag, when, employee, pounds, pounds, employee, when, pounds),
    )


def insert_oi(cursor, bag: str, anchor: str) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_order_instances (
          organization_id, bag_id, service_type, cycle_anchor_at
        ) VALUES (%s, %s, 'WF', %s)
        """,
        (ORG, bag, anchor),
    )


def insert_scan(cursor, bag: str, purpose: str, when: str, user: str | None, pounds: float | None, source: str | None) -> None:
    cursor.execute(
        """
        INSERT INTO rinse_bag_scan_events (
          organization_id, bag_id, purpose, scanned_at_parsed, user_name,
          weight_lbs, weight_source, rack
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            ORG,
            bag,
            purpose,
            when,
            user,
            pounds,
            source,
            "Rinse Zipvan" if purpose == "sent-to-vendor" else None,
        ),
    )


def seed(cursor) -> None:
    ensure_lab_tables(cursor)
    clear_lab(cursor)
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, 'rinse_folding_lbs_per_hour_target', '40')
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (ORG,),
    )
    for name, user_id in (("Ada Folder", 4), ("Bea Folder", 5)):
        cursor.execute(
            """
            INSERT INTO rinse_folding_user_map (organization_id, rinse_user_name, user_id, active)
            VALUES (%s, %s, %s, 1)
            """,
            (ORG, name, user_id),
        )
    cursor.execute(
        """
        INSERT INTO shift_sessions (organization_id, user_id, clock_in_at, clock_out_at, status)
        VALUES (%s, 4, '2026-11-16 08:00:00', '2026-11-16 16:00:00', 'completed')
        """,
        (ORG,),
    )
    ada_shift = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO shift_sessions (organization_id, user_id, clock_in_at, clock_out_at, status)
        VALUES (%s, 5, '2026-11-16 08:00:00', '2026-11-16 14:00:00', 'completed')
        """,
        (ORG,),
    )
    bea_shift = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO shift_sessions (organization_id, user_id, clock_in_at, clock_out_at, status)
        VALUES (%s, 5, '2026-11-17 09:00:00', '2026-11-17 11:00:00', 'completed')
        """,
        (ORG,),
    )
    bea_next = cursor.lastrowid
    segments = [
        (ada_shift, 4, "RINSE_WF", "FOLDER", "Rinse WF", "Folding", "2026-11-16 08:00:00", "2026-11-16 12:00:00"),
        (ada_shift, 4, "RINSE_WF", "SORT", "Rinse WF", "Sorting", "2026-11-16 12:00:00", "2026-11-16 13:00:00"),
        (bea_shift, 5, "RINSE_WF", "FOLDER", "Rinse WF", "Folding", "2026-11-16 08:00:00", "2026-11-16 10:00:00"),
        (bea_shift, 5, "RINSE_WF", "FOLDER", "Rinse WF", "Folding", "2026-11-16 10:00:00", "2026-11-16 12:00:00"),
        (bea_next, 5, "RINSE_WF", "FOLDER", "Rinse WF", "Folding", "2026-11-17 09:00:00", "2026-11-17 11:00:00"),
    ]
    for row in segments:
        cursor.execute(
            """
            INSERT INTO shift_job_segments (
              shift_session_id, user_id, category_code, role_code,
              category_name_snapshot, role_name_snapshot, started_at, ended_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            row,
        )

    def chain(bag, day, employee, pre_at, fold_at, post_at, pre, source, day_pounds):
        insert_day_bag(cursor, date.fromisoformat(day), bag, employee, day_pounds, fold_at)
        insert_oi(cursor, bag, f"{day} 06:00:00")
        insert_scan(cursor, bag, "sent-to-vendor", f"{day} 06:00:00", "Driver", None, None)
        if pre is not None and pre_at:
            insert_scan(cursor, bag, "weight-entry", pre_at, employee, pre, source)
        insert_scan(cursor, bag, "garments-reviewed", fold_at, employee, None, None)
        insert_scan(cursor, bag, "processed-by-vendor", post_at, employee, None, None)

    chain("LAB-A1", "2026-11-16", "Ada Folder", "2026-11-16 08:20:00", "2026-11-16 08:30:00", "2026-11-16 08:40:00", 20.0, "rinse_preclean_info", 20.0)
    chain("LAB-A2", "2026-11-16", "Ada Folder", "2026-11-16 09:00:00", "2026-11-16 09:10:00", "2026-11-16 09:20:00", 22.0, "rinse_preclean_info", 22.0)
    # No authoritative preclean PRE. The manager correction supplies 18.5.
    chain("LAB-CORR", "2026-11-16", "Ada Folder", None, "2026-11-16 09:40:00", "2026-11-16 09:50:00", None, None, 40.0)
    cursor.execute(
        """
        INSERT INTO rinse_step1_corrections (
          organization_id, bag_id, action, reason_text, new_values, created_at
        ) VALUES (%s, 'LAB-CORR', 'correct_weight', 'Sanitized lab correction', %s, '2026-11-16 09:45:00')
        """,
        (ORG, json.dumps({"corrected_pre_weight_lbs": 18.5})),
    )
    chain("LAB-B1", "2026-11-16", "Bea Folder", "2026-11-16 08:30:00", "2026-11-16 08:40:00", "2026-11-16 08:50:00", 30.0, "rinse_preclean_info", 30.0)
    chain("LAB-B2", "2026-11-16", "Bea Folder", "2026-11-16 10:10:00", "2026-11-16 10:20:00", "2026-11-16 10:30:00", 15.0, "rinse_preclean_info", 15.0)
    chain("LAB-OUT", "2026-11-16", "Ada Folder", "2026-11-16 13:20:00", "2026-11-16 13:30:00", "2026-11-16 13:40:00", 11.0, "rinse_preclean_info", 11.0)
    chain("LAB-UNMAP", "2026-11-16", None, "2026-11-16 10:50:00", "2026-11-16 11:00:00", "2026-11-16 11:10:00", 9.0, "rinse_preclean_info", 9.0)
    cursor.execute(
        "UPDATE rinse_bag_scan_events SET user_name='Unknown' WHERE bag_id='LAB-UNMAP' AND purpose <> 'sent-to-vendor'"
    )
    # Completed bag whose lifecycle has no garments-reviewed scan.
    insert_day_bag(cursor, DAY, "LAB-MISS", None, 8.0, "2026-11-16 12:15:00")
    insert_oi(cursor, "LAB-MISS", "2026-11-16 06:00:00")
    insert_scan(cursor, "LAB-MISS", "sent-to-vendor", "2026-11-16 06:00:00", "Driver", None, None)
    insert_scan(cursor, "LAB-MISS", "processed-by-vendor", "2026-11-16 12:15:00", "Ada Folder", None, None)
    chain("LAB-N17", "2026-11-17", "Bea Folder", "2026-11-17 09:20:00", "2026-11-17 09:30:00", "2026-11-17 09:40:00", 10.0, "rinse_preclean_info", 10.0)


def publish(cursor) -> None:
    from backend.management_wf_folder_performance import build_day_folder_performance
    from backend.rinse_performance_approvals import ensure_rinse_performance_approval_tables

    ensure_rinse_performance_approval_tables(cursor)
    day = build_day_folder_performance(cursor, ORG, selected_date_et=DAY, attach_customers=False)
    next_day = build_day_folder_performance(cursor, ORG, selected_date_et=NEXT, attach_customers=False)

    def sessions_for(payload, employee):
        for emp in payload.get("employees") or []:
            if emp.get("employee") == employee:
                return emp.get("sessions") or []
        return []

    ada = sessions_for(day, "Ada Folder")
    bea = sessions_for(day, "Bea Folder")
    bea_next = sessions_for(next_day, "Bea Folder")
    print("ADA SESSIONS", [(s.get("session_id"), s.get("start_time"), s.get("end_time"), s.get("orders_completed"), s.get("total_pre_lbs")) for s in ada])
    print("BEA SESSIONS", [(s.get("session_id"), s.get("start_time"), s.get("end_time"), s.get("orders_completed"), s.get("total_pre_lbs")) for s in bea])
    print("BEA NEXT", [(s.get("session_id"), s.get("orders_completed"), s.get("total_pre_lbs")) for s in bea_next])
    print("OUTSIDE", len(day.get("outside_folder_session_orders") or []), "UNMAPPED", len(day.get("needs_attribution_orders") or []))

    def approval(session, employee, user_id, status, day_value):
        if not session:
            return
        cursor.execute(
            """
            INSERT INTO rinse_performance_session_approvals (
              organization_id, business_date_et, role_key, session_id, employee_user_id, employee_name,
              metric_key, metric_unit, published_numerator, published_denominator, published_metric_value,
              content_fingerprint, invalidated_at, invalidated_reason, excluded_at, excluded_reason
            ) VALUES (%s, %s, 'FOLDER', %s, %s, %s, 'lbs_per_hour', 'lb/hr', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ORG,
                day_value,
                session.get("session_id"),
                user_id,
                employee,
                session.get("total_pre_lbs") or 0,
                session.get("performance_hours") or session.get("session_hours") or 0,
                session.get("lbs_per_hour") or 0,
                "lab-fingerprint",
                "2026-11-16 18:00:00" if status == "reversed" else None,
                "Approval reversed in the lab" if status == "reversed" else None,
                "2026-11-16 18:05:00" if status == "excluded" else None,
                "Session excluded in the lab" if status == "excluded" else None,
            ),
        )
        action = {"approved": "APPROVE", "reversed": "INVALIDATE", "excluded": "EXCLUDE"}[status]
        cursor.execute(
            """
            INSERT INTO rinse_performance_approval_events (
              organization_id, role_key, session_id, business_date_et, action, actor_user_id, actor_name, reason
            ) VALUES (%s, 'FOLDER', %s, %s, %s, 3, 'Local Supervisor', %s)
            """,
            (ORG, session.get("session_id"), day_value, action, action),
        )

    ada_fold = next((s for s in ada if str(s.get("start_time") or "").startswith("2026-11-16 08")), None)
    bea_pending = next((s for s in bea if str(s.get("start_time") or "").startswith("2026-11-16 08")), None)
    bea_excluded = next((s for s in bea if str(s.get("start_time") or "").startswith("2026-11-16 10")), None)
    approval(ada_fold, "Ada Folder", 4, "approved", DAY)
    approval(bea_pending, "Bea Folder", 5, "reversed", DAY)
    approval(bea_excluded, "Bea Folder", 5, "excluded", DAY)
    if ada_fold:
        cursor.execute(
            """
            INSERT INTO supervisor_session_adjustments (
              organization_id, business_date_et, session_id, employee_user_id, employee_name,
              kind, eligible_hours, reason, actor_user_id, actor_name, reversed_at, reversed_by, reversal_reason
            ) VALUES (%s, %s, %s, 4, 'Ada Folder', 'eligible_duration', 1, 'Tried to shorten the session', 3, 'Local Supervisor',
                      '2026-11-16 19:00:00', 3, 'Reversed; original hours stand')
            """,
            (ORG, DAY, ada_fold.get("session_id")),
        )


def report() -> None:
    from backend.management_wf_folder_performance import build_day_folder_performance
    from backend.rinse_performance_folder_publisher import attach_publication_status_to_day, get_folder_benchmark
    from backend.rinse_step1_productivity_fast import load_completed_productivity_day_bags
    from backend.supervisor_portal.period import aggregate_period
    from backend.supervisor_portal.service import assemble_supervisor_day
    from backend.supervisor_portal.store import list_adjustments

    conn = connect()
    cursor = conn.cursor(dictionary=True)
    payloads = []
    for selected in (DAY, NEXT):
        completed = [
            row
            for row in load_completed_productivity_day_bags(cursor, ORG, selected, include_hd=False, rush_filter="all")
            if str(row.get("service_type") or "").upper() == "WF"
        ]
        day = build_day_folder_performance(cursor, ORG, selected_date_et=selected, attach_customers=False)
        attach_publication_status_to_day(cursor, ORG, day)
        payload = assemble_supervisor_day(
            selected_date=selected,
            completed=completed,
            day=day,
            adjustments=list_adjustments(cursor, ORG, selected),
            auto_approval_threshold=get_folder_benchmark(cursor, ORG),
            scoring_target=None,
            auto_approve_enabled=False,
        )
        payloads.append(payload)
        print(
            selected.isoformat(),
            "completed",
            payload["reconciliation"]["total_completed"],
            "categories",
            payload["reconciliation"]["categories"],
            "approved",
            payload["approved_productivity"]["approved_pounds"],
            payload["approved_productivity"]["approved_hours"],
            payload["approved_productivity"]["approved_lbs_per_hour"],
            "pending",
            payload["approved_productivity"]["pending_pounds"],
            payload["approved_productivity"]["pending_hours"],
        )
        for emp in payload["employees"]:
            print(
                " ",
                emp["employee"],
                "bags",
                emp["bags"],
                "lb",
                emp["pounds"],
                "h",
                emp["eligible_hours"],
                "rate",
                emp["reported_rate"],
                "pending_lb",
                emp["pending_pounds"],
                "pending_h",
                emp["pending_hours"],
            )
    week = aggregate_period(payloads)
    print(
        "WEEK",
        week["approved_productivity"]["approved_pounds"],
        week["approved_productivity"]["approved_hours"],
        week["approved_productivity"]["approved_lbs_per_hour"],
        "pending",
        week["approved_productivity"]["pending_pounds"],
        week["reconciliation"]["categories"],
    )
    conn.close()


def main() -> None:
    conn = connect()
    cursor = conn.cursor()
    seed(cursor)
    conn.close()
    dict_conn = connect()
    publish(dict_conn.cursor(dictionary=True))
    dict_conn.close()
    report()


if __name__ == "__main__":
    main()
