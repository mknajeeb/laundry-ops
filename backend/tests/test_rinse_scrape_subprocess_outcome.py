"""Subprocess outcome classification tests for portal scrape instrumentation."""

from __future__ import annotations

import time
from pathlib import Path

from backend.rinse_scrape_subprocess_outcome import (
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
