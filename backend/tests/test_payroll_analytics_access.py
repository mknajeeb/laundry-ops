"""Payroll analytics-only role: summary allowed, employee detail APIs forbidden."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


RESTRICTED_PAYROLL_PATHS = (
    "/payroll/time-records",
    "/payroll/worker-payments",
    "/payroll/payout-batches",
    "/payroll/payout-batches/<int:batch_id>",
    "/payroll/payout-batches/accountant-queue",
    "/payroll/payout-batches/<int:batch_id>/details",
    "/payroll/payout-batches/<int:batch_id>/finalize-details",
    "/payroll/payout-batches/<int:batch_id>/paystub/<int:line_id>",
    "/payroll/payout-batches/<int:batch_id>/paystubs",
    "/payroll/payout-batches/<int:batch_id>/payment-receipt/<int:line_id>",
    "/payroll/payout-batches/<int:batch_id>/vendor-receipt/<int:line_id>",
    "/payroll/paystub-archive",
    "/payroll/paystub-archive/meta",
    "/payroll/workers",
    "/payroll/tax-settings",
)


def test_analytics_perm_sql_is_idempotent_and_narrow():
    sql = _read("backend/sql/payroll_analytics_dashboard_perm_v1.sql")
    assert "payroll.analytics.view" in sql
    assert "INSERT IGNORE" in sql
    assert "users.view" not in sql
    assert "payroll.update" not in sql


def test_seed_script_password_from_env_only_never_prints_password():
    src = _read("backend/scripts/create_payroll_dashboard_user.py")
    assert "PAYROLL_DASHBOARD_PASSWORD" in src
    assert 'add_argument(\n        "--password"' not in src
    assert 'add_argument("--password"' not in src
    assert "generate_password_hash" in src
    assert "password_reset_required=true" in src
    assert "issue_password_reset_token" in src
    # Must not echo the env password variable contents.
    assert "print(password)" not in src
    assert "print(f\"{password" not in src
    assert "args.password" not in src
    assert "DASHBOARD_PERMISSION_KEYS" in src
    assert "payroll.analytics.view" in src
    assert "users.view" not in src.split("DASHBOARD_PERMISSION_KEYS")[1].split(")")[0]


def test_report_routes_allow_analytics_perm_and_gate_employee_detail():
    routes = _read("backend/ta_routes.py")
    for fn in (
        "def payroll_report():",
        "def payroll_report_meta():",
        "def payroll_report_export_xlsx():",
        "def payroll_report_export_pdf():",
    ):
        assert fn in routes
        head = routes.split(fn)[0][-500:]
        assert "payroll.analytics.view" in head
    assert "_can_view_employee_payroll_detail" in routes
    assert "You do not have permission to view employee payroll details." in routes
    # Employee filter without detail permission must 403.
    report_body = routes.split("def payroll_report():")[1].split("def payroll_report_meta")[0]
    assert 'kwargs.get("user_id") and not can_detail' in report_body
    assert "return jsonify(_EMPLOYEE_PAYROLL_DETAIL_FORBIDDEN), 403" in report_body


def test_restricted_payroll_endpoints_do_not_allow_analytics_perm_alone():
    routes = _read("backend/ta_routes.py")
    for path in RESTRICTED_PAYROLL_PATHS:
        assert path in routes, f"missing route path {path}"
        # Prefer decorator neighborhood before the next def.
        idx = routes.find(path)
        chunk = routes[max(0, idx - 120) : idx + 700]
        if path.startswith("/payroll/report"):
            continue
        # Employee/batch endpoints must not grant payroll.analytics.view.
        deco = chunk.split("def ")[0]
        assert "payroll.analytics.view" not in deco, path


def test_frontend_route_allows_payroll_analytics_role():
    app = _read("frontend/src/App.jsx")
    block = app.split('path="/payroll"')[1][:900]
    assert "PAYROLL_ANALYTICS" in block
    assert "payroll.analytics.view" in block
    assert "payroll.view" in block


def test_management_page_blocks_employee_tabs_for_dashboard_only():
    page = _read("frontend/src/pages/PayrollManagementPage.jsx")
    assert "dashboardOnly" in page
    assert "You do not have permission to view employee payroll details." in page
    assert 'isPayrollAnalyticsRole = rolesUpper.includes("PAYROLL_ANALYTICS")' in page


def test_summary_exports_strip_employee_detail_payload():
    from backend.payroll_report import build_payroll_report_html, build_payroll_report_xlsx

    report = {
        "report_heading": "Payroll Period: 2026-07-06 – 2026-07-12",
        "date_match_rule": "test",
        "filters": {"report_type": "payroll_period", "include_employee_detail": False},
        "rows": [],
        "groups": [],
        "summary": {
            "gross_pay": 100.0,
            "total_payroll_cost": 110.0,
            "unique_employees": 3,
            "worker_count": 3,
        },
        "totals": {},
        "analytics": {
            "kpis": [],
            "category_breakdown": [
                {
                    "label": "W-2",
                    "worker_category": "w2",
                    "head_count": 1,
                    "regular_hours": 40,
                    "ot_hours": 0,
                    "regular_earnings": 680,
                    "ot_earnings": 0,
                    "other_earnings": 0,
                    "gross_pay": 680,
                    "employer_taxes": 50,
                    "total_payroll_cost": 730,
                    "avg_pay_rate": 17,
                    "avg_cost_per_hour": 18.25,
                    "base_earnings": 680,
                    "ot_premium": 0,
                }
            ],
            "workforce_totals": {
                "regular_hours": 40,
                "ot_hours": 0,
                "regular_earnings": 680,
                "ot_earnings": 0,
                "other_earnings": 0,
                "gross_pay": 680,
                "employer_taxes": 50,
                "total_payroll_cost": 730,
                "avg_pay_rate": 17,
                "avg_cost_per_hour": 18.25,
                "base_earnings": 680,
                "ot_premium": 0,
                "head_count": 1,
            },
            "period_comparison": [],
            "employee_summaries_by_category": {},
            "groups": [],
            "access": {"can_view_employee_detail": False},
        },
        "dashboard_only": True,
        "analytics_only_export": True,
        "employee_detail_restricted": True,
        "employee_detail_message": (
            "You do not have permission to view employee payroll details."
        ),
    }
    xlsx = build_payroll_report_xlsx(report)
    assert isinstance(xlsx, (bytes, bytearray)) and len(xlsx) > 100
    # openpyxl binary must not contain a known employee identity string.
    assert b"Secret Worker" not in xlsx
    assert b"blake.rinse" not in xlsx.lower()

    html = build_payroll_report_html(report)
    assert "Secret Worker" not in html
    assert "@veewash.com" not in html
    assert "paystub/" not in html.lower()
    assert "receipt" not in html.lower() or "Workers:" in html
