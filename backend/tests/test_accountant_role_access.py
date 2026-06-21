"""Verify ACCOUNTANT role seed and read-only access expectations."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_accountant_sql_grants_only_users_view():
    sql = _read("backend/sql/accountant_role_v1.sql")
    assert re.search(r"perm_key\s*=\s*'users\.view'", sql)
    assert re.search(r"perm_key\s*<>\s*'users\.view'", sql)
    grant_block = sql.split("INSERT IGNORE INTO role_permissions")[1].split("DELETE rp")[0]
    assert "users.view" in grant_block
    for forbidden in ("users.edit", "ta.settings", "ta.monitor", "finance.payments"):
        assert forbidden not in grant_block


def test_finance_role_unchanged_in_schema():
    schema = _read("backend/schema_ta.sql")
    m = re.search(
        r"-- Finance\s+INSERT INTO role_permissions.*?SELECT 5, id FROM permissions WHERE perm_key IN \(([^)]+)\)",
        schema,
        re.DOTALL,
    )
    assert m, "FINANCE role_permissions block missing"
    perms = m.group(1)
    assert "users.view" in perms
    assert "ta.monitor" in perms
    assert "ta.reports" in perms
    assert "finance.payments" in perms
    assert "users.edit" not in perms


def test_payroll_route_includes_accountant_role():
    app = _read("frontend/src/App.jsx")
    assert '"ACCOUNTANT"' in app
    assert 'path="/payroll"' in app
    payroll_block = app.split('path="/payroll"')[1][:800]
    assert "ACCOUNTANT" in payroll_block


def test_accountant_only_sees_accountant_tab_logic():
    page = _read("frontend/src/pages/PayrollManagementPage.jsx")
    assert 'isAccountantRole = rolesUpper.includes("ACCOUNTANT")' in page
    assert "canContractors = hasPerm(\"users.edit\")" in page
    assert 'key: "accountant_payroll"' in page
    assert 'key: "accountant_reports"' in page
    assert 'key: "accountant_documents"' not in page
    assert "readOnlyAccountant" in page


def test_upload_gated_on_users_edit():
    panel = _read("frontend/src/components/AccountantW2DocumentsPanel.jsx")
    assert 'canUpload = hasPerm("users.edit")' in panel
    assert "canUpload && doc.allowUpload" in panel
    assert "deleteTaUserDocument" in panel


def test_direct_deposit_uses_veewash_branding():
    form = _read("frontend/src/payroll/DirectDepositFormPrint.jsx")
    assert "VEEWASH_BRAND" in form
    assert "vw-ddf-hero" in form
    assert "ContractorPrintLogo" in form


def test_direct_deposit_prefill_resolves_i9_ssn():
    form = _read("frontend/src/payroll/DirectDepositFormPrint.jsx")
    assert "resolveDirectDepositSsnDisplay" in form
    assert "i9.ssn" in form
    assert "resolveDirectDepositSsnDisplay(payroll, work)" in form
    assert '"Full"' in form


def test_direct_deposit_download_uses_pdf():
    panel = _read("frontend/src/components/AccountantW2DocumentsPanel.jsx")
    assert "downloadPrintDocumentPdf" in panel
    assert "direct-deposit-${slug}.pdf" in panel


def test_veewash_logo_public_asset_present():
    logo = ROOT / "frontend" / "public" / "assets" / "veewash-logo.png"
    assert logo.is_file()
    assert logo.stat().st_size > 1000


def test_paystub_html_includes_embedded_logo():
    from backend.veewash_branding import veewash_logo_img_html

    assert 'data:image/png;base64,' in veewash_logo_img_html()


def test_w2_doc_catalog_upload_only_except_direct_deposit():
    catalog = _read("frontend/src/payroll/accountantW2DocCatalog.js")
    assert "kind: \"hr_form\"" not in catalog
    assert "kind: \"generated\"" in catalog
    assert catalog.count("kind: \"uploaded\"") == 3
    assert "hiring_documents" in catalog
    assert "LEGACY_HIRING_DOC_CODES" in catalog


def test_document_post_requires_users_edit_in_routes():
    routes = _read("backend/ta_routes.py")
    block = routes.split("def user_document_records(user_id):")[1].split("def user_document_record_item")[0]
    assert "request.method == \"GET\"" in block
    assert 'user_has_perm(conn, g.ta_user["id"], "users.view")' in block
    assert 'user_has_perm(conn, g.ta_user["id"], "users.edit")' in block


def test_document_file_endpoint_requires_auth_and_view():
    routes = _read("backend/ta_routes.py")
    block = routes.split("def user_document_record_file(user_id, record_id):")[1].split(
        '@ta_bp.route("/admin/document-compliance-policy"'
    )[0]
    assert "@require_auth" in routes.split("def user_document_record_file")[0][-120:]
    assert 'user_has_perm(conn, g.ta_user["id"], "users.view")' in block
    assert 'user_has_perm(conn, g.ta_user["id"], "users.edit")' in block
    assert "read_employee_document_bytes" in block


def test_accountant_panel_uses_authenticated_document_file_api():
    panel = _read("frontend/src/components/AccountantW2DocumentsPanel.jsx")
    assert "getTaUserDocumentFile" in panel
    assert "blob.core.windows.net" not in panel
    assert "openUploadedView(selected.id, doc.rec)" in panel


def test_accountant_documents_has_system_users_category():
    panel = _read("frontend/src/components/AccountantW2DocumentsPanel.jsx")
    users = _read("frontend/src/payroll/accountantDocumentUsers.js")
    assert "ACCOUNTANT_DOC_CATEGORY_OPTIONS" in panel
    assert 'value: "system_users"' in users
    assert "Alliance Business Consultant" in users or "alliance business consultant" in users
    assert "New VeeWash Admin" in users or "new veewash admin" in users
    assert "filterAccountantDocumentUsers" in panel
    assert "isW2EmployeeForDocuments" in users
