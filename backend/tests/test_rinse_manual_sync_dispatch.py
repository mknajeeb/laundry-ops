"""Tests for manual sync ACA dispatch (no Playwright in API worker)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.rinse_aca_job_trigger import (
    AcaJobStartResult,
    aca_job_trigger_configured,
    build_job_start_template,
    remote_only_user_message,
    start_rinse_scrape_aca_job,
)
from backend.rinse_manual_sync_dispatch import dispatch_manual_rinse_sync


class TestAcaJobTrigger:
    def test_build_job_start_template_scopes_org(self):
        tpl = build_job_start_template(3, run_type="manual")
        args = tpl["template"]["containers"][0]["args"]
        assert "--organization-id" in args
        assert "3" in args
        assert "--run-type" in args
        assert "manual" in args

    @patch.dict(
        "os.environ",
        {
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "RINSE_ACA_JOB_RESOURCE_GROUP": "rg-test",
            "RINSE_ACA_JOB_NAME": "rinse-scrape-scheduled",
        },
        clear=False,
    )
    def test_aca_job_trigger_configured(self):
        assert aca_job_trigger_configured() is True

    @patch("backend.rinse_aca_job_trigger._get_management_token", return_value="token")
    @patch("backend.rinse_aca_job_trigger.urllib.request.urlopen")
    @patch.dict(
        "os.environ",
        {
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "RINSE_ACA_JOB_RESOURCE_GROUP": "rg-test",
            "RINSE_ACA_JOB_NAME": "rinse-scrape-scheduled",
        },
        clear=False,
    )
    def test_start_rinse_scrape_aca_job_success(self, mock_urlopen, _token):
        resp = MagicMock()
        resp.read.return_value = b'{"name": "rinse-scrape-scheduled-exec1"}'
        resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = resp

        out = start_rinse_scrape_aca_job(3, run_type="manual")
        assert out.ok is True
        assert out.execution_name == "rinse-scrape-scheduled-exec1"


class TestManualSyncDispatch:
    @patch("backend.rinse_manual_sync_dispatch.start_rinse_scrape_aca_job")
    @patch("backend.rinse_manual_sync_dispatch.aca_job_trigger_configured", return_value=True)
    @patch("backend.rinse_manual_sync_dispatch.is_scrape_cycle_running", return_value=(False, None))
    def test_dispatch_triggers_aca_job(self, _running, _configured, mock_start):
        mock_start.return_value = AcaJobStartResult(ok=True, execution_name="exec-1")
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        result = dispatch_manual_rinse_sync(conn, 3)
        assert result.overall_status == "queued"
        assert result.http_status == 202
        assert result.aca_execution_name == "exec-1"
        mock_start.assert_called_once_with(3, run_type="manual")

    @patch("backend.rinse_manual_sync_dispatch.manual_sync_must_not_run_local_playwright", return_value=True)
    @patch("backend.rinse_manual_sync_dispatch.aca_job_trigger_configured", return_value=False)
    @patch("backend.rinse_manual_sync_dispatch.is_scrape_cycle_running", return_value=(False, None))
    def test_dispatch_fail_fast_when_remote_only(self, _running, _aca, _remote):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        result = dispatch_manual_rinse_sync(conn, 3)
        assert result.http_status == 503
        assert remote_only_user_message() in (result.message or "")

    @patch("backend.rinse_manual_sync_dispatch.is_scrape_cycle_running", return_value=(True, "run 9"))
    def test_dispatch_already_running(self, _running):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        result = dispatch_manual_rinse_sync(conn, 3)
        assert result.http_status == 409
        assert result.overall_status == "ALREADY_RUNNING"
