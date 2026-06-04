"""Tests for partner roster share links."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_roster_share import (
    create_share_link,
    get_public_roster,
    revoke_share_link,
    verify_roster_pin,
)


def _link_row(**overrides):
    base = {
        "id": 1,
        "organization_id": 10,
        "token": "abc123securetoken",
        "title": "Partner Roster",
        "date_start": "2026-05-19",
        "date_end": "2026-05-25",
        "published_only": 1,
        "active": 1,
        "revoked_at": None,
        "expires_at": None,
        "password_hash": None,
        "geofence_id": None,
        "include_shift_ids": None,
        "include_work_stream_ids": None,
        "include_role_ids": None,
        "show_phone": 0,
        "show_worker_category": 0,
        "show_internal_notes": 0,
        "show_performance": 0,
        "mode": "live",
    }
    base.update(overrides)
    return base


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
def test_public_roster_invalid_token(mock_fetch, _ensure):
    mock_fetch.return_value = None
    conn = MagicMock()
    with pytest.raises(ValueError, match="invalid"):
        get_public_roster(conn, "bad-token")


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
def test_public_roster_revoked(mock_fetch, _ensure):
    mock_fetch.return_value = _link_row(revoked_at=datetime.utcnow(), active=0)
    conn = MagicMock()
    with pytest.raises(ValueError, match="revoked"):
        get_public_roster(conn, "abc123securetoken")


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
def test_public_roster_expired(mock_fetch, _ensure):
    mock_fetch.return_value = _link_row(expires_at=datetime.utcnow() - timedelta(hours=1))
    conn = MagicMock()
    with pytest.raises(ValueError, match="expired"):
        get_public_roster(conn, "abc123securetoken")


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
def test_public_roster_requires_pin(mock_fetch, _ensure):
    mock_fetch.return_value = _link_row(password_hash="hashed")
    conn = MagicMock()
    out = get_public_roster(conn, "abc123securetoken")
    assert out["requires_pin"] is True
    assert "PIN" in out.get("message", "")


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
@patch("backend.payroll_roster_share.verify_password", return_value=False)
def test_public_roster_wrong_pin(mock_verify, mock_fetch, _ensure):
    mock_fetch.return_value = _link_row(password_hash="hashed")
    conn = MagicMock()
    out = get_public_roster(conn, "abc123securetoken", pin="0000")
    assert out["requires_pin"] is True


@patch("backend.payroll_roster_share.ensure_roster_share_tables")
@patch("backend.payroll_roster_share._fetch_link_by_token")
@patch("backend.payroll_roster_share._log_access")
def test_public_roster_published_only_query(mock_log, mock_fetch, _ensure):
    mock_fetch.return_value = _link_row(published_only=1)
    conn = MagicMock()
    c = conn.cursor.return_value
    c.fetchone.side_effect = [{"display_name": "Test Org", "slug": "test"}, None]
    c.fetchall.return_value = []
    out = get_public_roster(conn, "abc123securetoken")
    assert out["read_only"] is True
    assert "grouped_by_date" in out
    sql = c.execute.call_args_list[-1][0][0]
    assert "publish_status='published'" in sql
    assert "hourly_rate" not in sql.lower()
    assert "estimated_cost" not in sql.lower()


@patch("backend.payroll_roster_share.get_share_link", return_value={"id": 5, "token": "tok"})
@patch("backend.payroll_roster_share.secrets.token_urlsafe", return_value="x" * 43)
@patch("backend.payroll_roster_share.ensure_roster_share_tables")
def test_create_share_link_uses_secure_token(_ensure, mock_token, mock_get):
    conn = MagicMock()
    ins = conn.cursor.return_value
    ins.lastrowid = 5
    create_share_link(
        conn,
        10,
        {"date_start": "2026-05-19", "date_end": "2026-05-25"},
        created_by=1,
    )
    mock_token.assert_called_once_with(32)
    insert_sql = ins.execute.call_args[0][0]
    assert "INSERT INTO payroll_roster_share_links" in insert_sql


@patch("backend.payroll_roster_share.update_share_link")
def test_revoke_share_link(mock_update):
    conn = MagicMock()
    revoke_share_link(conn, 10, 3)
    mock_update.assert_called_once_with(conn, 10, 3, {"revoke": True})


@patch("backend.payroll_roster_share._fetch_link_by_token")
def test_verify_roster_pin_no_hash(mock_fetch):
    mock_fetch.return_value = _link_row(password_hash=None)
    assert verify_roster_pin(MagicMock(), "tok", "1234") is False
