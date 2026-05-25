"""Tests for Rinse upload batch Option C retention (no MySQL)."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_upload_batch_retention import (
    batch_date_eligible_for_retention,
    evaluate_batch_for_heavy_row_purge,
    resolve_upload_batch_date_range,
    retention_cutoff_batch_date,
)
from backend.rinse_scrape_status import list_scrape_runs_for_et_range


def test_retention_cutoff_batch_date():
    today = date(2026, 5, 21)
    assert retention_cutoff_batch_date(today, 3) == date(2026, 5, 18)


def test_batch_date_eligible_rejects_today():
    today = date(2026, 5, 21)
    cutoff = date(2026, 5, 18)
    ok, reason = batch_date_eligible_for_retention(today, today=today, cutoff=cutoff)
    assert ok is False
    assert "today" in (reason or "").lower()


def test_evaluate_skips_draft_and_latest_success():
    batch = {"batch_id": 99, "batch_date": date(2026, 5, 10), "state": "DRAFT"}
    v = evaluate_batch_for_heavy_row_purge(
        batch,
        organization_id=3,
        today=date(2026, 5, 21),
        cutoff=date(2026, 5, 18),
        latest_success_batch_id=99,
    )
    assert v["eligible"] is False
    assert any("DRAFT" in r for r in v["skip_reasons"])
    assert any("latest successful" in r for r in v["skip_reasons"])


def test_evaluate_confirmed_old_batch_eligible():
    batch = {"batch_id": 50, "batch_date": date(2026, 5, 10), "state": "CONFIRMED"}
    v = evaluate_batch_for_heavy_row_purge(
        batch,
        organization_id=3,
        today=date(2026, 5, 21),
        cutoff=date(2026, 5, 18),
        latest_success_batch_id=99,
    )
    assert v["eligible"] is True


def test_resolve_upload_batch_date_range_last_3_days():
    with patch("backend.rinse_upload_batch_retention.today_et", return_value=date(2026, 5, 21)):
        fd, td = resolve_upload_batch_date_range(range_preset="last_3_days")
    assert fd == date(2026, 5, 19)
    assert td == date(2026, 5, 21)


def test_resolve_upload_batch_date_range_today():
    with patch("backend.rinse_upload_batch_retention.today_et", return_value=date(2026, 5, 21)):
        fd, td = resolve_upload_batch_date_range(range_preset="today")
    assert fd == td == date(2026, 5, 21)


def test_list_scrape_runs_uses_et_utc_bounds():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    with patch("backend.rinse_scrape_status.table_exists", return_value=True), patch(
        "backend.rinse_upload_batch_retention.et_date_range_to_utc_bounds",
        return_value=("START", "END"),
    ) as bounds:
        out = list_scrape_runs_for_et_range(
            cursor, 3, from_date=date(2026, 5, 21), to_date=date(2026, 5, 21)
        )
    assert out == []
    bounds.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "started_at >=" in sql
    args = cursor.execute.call_args[0][1]
    assert args == (3, "START", "END")


def test_plan_dry_run_skips_needs_attention(monkeypatch):
    from backend import rinse_upload_batch_retention as mod

    batch = {
        "batch_id": 10,
        "batch_date": date(2026, 5, 1),
        "state": "CONFIRMED",
        "raw_rows_purged_at": None,
    }
    cursor = MagicMock()
    monkeypatch.setattr(mod, "_fetch_candidate_batches", lambda c, o: [batch])
    monkeypatch.setattr(mod, "get_latest_successful_imported_batch_id", lambda c, o: None)
    monkeypatch.setattr(mod, "today_et", lambda: date(2026, 5, 21))
    monkeypatch.setattr(
        mod,
        "_count_batch_rows",
        lambda c, bid: {
            "total_rows": 2,
            "accepted_rows": 0,
            "rejected_rows": 0,
            "attention_rows": 2,
            "deleted_rows": 0,
        },
    )
    monkeypatch.setattr(mod, "_count_batch_scan_events", lambda c, bid, o: 5)
    monkeypatch.setattr(mod, "_plan_scrape_run_retention", lambda c, o, b: {"retain": [], "trim_heavy_fields": []})

    plan = mod.plan_heavy_row_purge(cursor, 3, older_than_days=3)
    assert plan["totals"]["batches"] == 0
    assert plan["skipped_batches"][0]["batch_id"] == 10
