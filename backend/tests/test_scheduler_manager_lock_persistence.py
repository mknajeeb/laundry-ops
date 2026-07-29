"""Scheduler and API must share manager-lock day-bag persistence."""

from __future__ import annotations

import inspect

from backend.rinse_step1_scrape_refresh import refresh_step1_after_scrape
from backend.rinse_veewash_shift_day import (
    _day_bag_manager_lock_upsert_sql,
    _sync_day_header_from_persisted_bags,
    persist_day_snapshot,
)


def test_scheduler_refresh_uses_shared_persist_day_snapshot():
    src = inspect.getsource(refresh_step1_after_scrape)
    assert "backfill_day_from_live" in src


def test_backfill_and_persist_share_manager_lock_upsert():
    from backend.rinse_veewash_shift_day import backfill_day_from_live

    src = inspect.getsource(backfill_day_from_live)
    assert "persist_day_snapshot" in src
    sql = _day_bag_manager_lock_upsert_sql()
    compact = " ".join(sql.split())
    assert "rinse_shift_monitor_day_bags.manager_edit_version > 0" in compact
    assert "incoming.effective_status" in compact
    assert "effective_status=VALUES(effective_status)" not in sql
    assert callable(_sync_day_header_from_persisted_bags)
    assert callable(persist_day_snapshot)


def test_scheduled_job_module_imports_shared_shift_day_persist_path():
    from backend import rinse_scheduled_scrape as sched
    from backend.jobs import run_scheduled_rinse_scrape as job

    sched_src = inspect.getsource(sched)
    assert "refresh_step1_after_scrape" in sched_src or "_refresh_open_step1_day_after_scrape" in sched_src
    job_src = inspect.getsource(job)
    assert "load_release_revision_stamps" in job_src
    assert "scheduler_release_revision" in job_src


def test_dockerfile_bakes_release_revision_and_git_sha_args():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2] / "Dockerfile.rinse-scheduler"
    ).read_text(encoding="utf-8")
    assert "ARG GIT_SHA" in text
    assert "release_revision.json" in text
    assert "EXPECTED_RELEASE_SHA" in text
    assert "backend.jobs.run_scheduled_rinse_scrape" in text
