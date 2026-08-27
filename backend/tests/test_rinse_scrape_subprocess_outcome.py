"""Subprocess outcome classification tests for portal scrape instrumentation."""

from __future__ import annotations

import time
from pathlib import Path

from backend.rinse_scrape_subprocess_outcome import (
    FAILURE_PAGE_NAVIGATION_HANG,
    FAILURE_PLAYWRIGHT_HANG,
    FAILURE_STALL_NO_PROGRESS,
    classify_subprocess_failure,
)


def test_run_bash_script_records_stall_outcome(monkeypatch, tmp_path):
    from backend.rinse_scheduled_scrape import _TeeLog, _run_bash_script

    script = tmp_path / "silent.sh"
    script.write_text("#!/bin/bash\nwhile true; do sleep 1; done\n")
    script.chmod(0o755)

    monkeypatch.setattr("backend.rinse_scheduled_scrape.stall_seconds", lambda: 1)
    monkeypatch.setattr(
        "backend.rinse_scrape_runs.scrape_run_heartbeat_interval_sec",
        lambda: 3600,
    )

    outcomes: list[dict] = []
    log = _TeeLog(tmp_path / "log.txt")
    t0 = time.monotonic()
    rc = _run_bash_script(script, {}, log, timeout_sec=120, outcome_out=outcomes)
    elapsed = time.monotonic() - t0

    assert rc == -2
    assert outcomes
    assert outcomes[0]["failure_class"] in {
        FAILURE_STALL_NO_PROGRESS,
        FAILURE_PLAYWRIGHT_HANG,
    }
    assert elapsed < 10


def test_classify_enrich_portal_diag_expand_hang():
    lines = [
        "Page 3: https://www.rinse.com/cleanertickets/?page=3",
        "[portal-diag] op=expandRowAndReadBag ticket=12 tr=14/30 action_timeout_ms=15000",
        "  ticket 12 (list tr 14/30): expanding… Tue 8/26 Customer",
    ]
    out = classify_subprocess_failure(
        returncode=-2,
        stalled=True,
        last_log_lines=lines,
        elapsed_sec=1200.0,
    )
    assert out["failure_class"] == FAILURE_PLAYWRIGHT_HANG
    assert out["last_playwright_operation"] == "expandRowAndReadBag"
    assert out["ticket_index"] == "12"
    assert out["row_hint"] == "14/30"
    assert out["portal_diag"]["op"] == "expandRowAndReadBag"


def test_classify_enrich_portal_diag_page_goto():
    lines = [
        "[portal-diag] op=page.goto page=2 url=https://www.rinse.com/cleanertickets/?page=2 waitUntil=domcontentloaded",
    ]
    out = classify_subprocess_failure(
        returncode=-2,
        stalled=True,
        last_log_lines=lines,
        elapsed_sec=90.0,
    )
    assert out["failure_class"] == FAILURE_PAGE_NAVIGATION_HANG
    assert out["last_playwright_operation"] == "page.goto"
    assert out["page_num"] == "2"
    assert "cleanertickets" in out["page_url"]
