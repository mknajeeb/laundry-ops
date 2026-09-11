"""Tests: HD reset re-admission uses current ship-window membership, not stale active presence."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from backend.hd_ship_window_admission import (
    admit_hd_reset_from_ship_window,
    hang_dry_ship_window_from_scrape_meta,
    quarantine_hd_stale_reset_admissions,
    resolve_hd_ship_window_membership,
)
from backend.management_rinse_hd import (
    STATUS_PENDING_WASH,
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    _load_active_admitted_bag_ids,
)
from backend.rinse_ship_window_tickets_urls import build_ship_window_tickets_url


def _meta(ship_start: str, ship_end: str, *, trustworthy: bool = True) -> dict:
    url = build_ship_window_tickets_url(
        service_types="hang_dry",
        date_start=date.fromisoformat(ship_start),
        date_end=date.fromisoformat(ship_end),
    )
    return {
        "source_mode": "ship_to_vendor_window",
        "absence_capable": False,
        "tickets_sources": [
            {
                "label": "hang_dry",
                "service_types": "hang_dry",
                "ship_to_vendor_date_start": ship_start,
                "ship_to_vendor_date_end": ship_end,
                "url": url,
            }
        ],
        "completeness_guard": {
            "trustworthy": trustworthy,
            "allow_mark_missing": False,
        },
    }


def test_hang_dry_ship_window_from_meta_and_url():
    meta = _meta("2026-09-09", "2026-09-10")
    assert hang_dry_ship_window_from_scrape_meta(meta) == (
        date(2026, 9, 9),
        date(2026, 9, 10),
    )
    # URL-only provenance still works
    url_only = {
        "tickets_sources": [
            {
                "label": "hang_dry",
                "url": meta["tickets_sources"][0]["url"],
            }
        ]
    }
    assert hang_dry_ship_window_from_scrape_meta(url_only) == (
        date(2026, 9, 9),
        date(2026, 9, 10),
    )


def test_edd_mismatch_does_not_affect_ship_window_membership_resolution():
    """EDD is display-only; membership is ship-window run_rows."""
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = [
                {
                    "id": 100,
                    "status": "success",
                    "started_at": None,
                    "finished_at": None,
                    "source_batch_id": "b1",
                    "scrape_meta_json": json.dumps(_meta("2026-09-09", "2026-09-10")),
                    "rows_found": 6,
                }
            ]
        elif "FROM rinse_cleaner_ticket_presence_run_rows" in s:
            # Skylar EDD Sep11 / Rain EDD Sep13 still in ship-window set
            cursor.fetchall.return_value = [
                {"bag_id": "BLXFDA5KUV", "service_type": "HD", "hd_count_raw": "0.0"},
                {"bag_id": "28WV1QS4F9", "service_type": "HD", "hd_count_raw": "0.0"},
                {"bag_id": "7J0K1VM6WS", "service_type": "HD", "hd_count_raw": "0.0"},
            ]
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.hd_ship_window_admission.table_exists", return_value=True):
        out = resolve_hd_ship_window_membership(
            cursor,
            3,
            ship_start=date(2026, 9, 9),
            ship_end=date(2026, 9, 10),
            require_trustworthy=True,
        )
    assert out["ok"] is True
    assert set(out["bag_ids"]) == {"BLXFDA5KUV", "28WV1QS4F9", "7J0K1VM6WS"}


def test_stale_active_presence_not_eligible_for_reset_re_admission():
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = [
                {
                    "id": 200,
                    "status": "success",
                    "scrape_meta_json": json.dumps(_meta("2026-09-09", "2026-09-10")),
                    "source_batch_id": "cur",
                    "rows_found": 2,
                    "started_at": None,
                    "finished_at": None,
                }
            ]
        elif "FROM rinse_cleaner_ticket_presence_run_rows" in s:
            cursor.fetchall.return_value = [
                {"bag_id": "LIVE1", "service_type": "HD", "hd_count_raw": "0.0"},
                {"bag_id": "LIVE2", "service_type": "HD", "hd_count_raw": "0.0"},
            ]
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.hd_ship_window_admission.table_exists", return_value=True), patch(
        "backend.hd_ship_window_admission.active_hd_presence_bag_ids",
        return_value={"LIVE1", "LIVE2", "STALE1", "STALE2"},
    ), patch(
        "backend.hd_ship_window_admission.admit_discovered_hd_bags",
        return_value={
            "admitted_new": 2,
            "already_admitted": 0,
            "skipped_quarantined": 0,
            "bag_ids": ["LIVE1", "LIVE2"],
        },
    ) as admit:
        out = admit_hd_reset_from_ship_window(
            cursor,
            3,
            date(2026, 9, 9),
            ship_start=date(2026, 9, 9),
            ship_end=date(2026, 9, 10),
            require_trustworthy=True,
        )
    assert out["ok"] is True
    assert set(out["bag_ids"]) == {"LIVE1", "LIVE2"}
    assert set(out["skipped_stale_active_ids"]) == {"STALE1", "STALE2"}
    admit.assert_called_once()
    admitted_arg = admit.call_args.args[3]
    assert set(admitted_arg) == {"LIVE1", "LIVE2"}
    assert "STALE1" not in admitted_arg


def test_current_successful_ship_window_presence_is_eligible():
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = [
                {
                    "id": 50,
                    "status": "success",
                    "scrape_meta_json": json.dumps(_meta("2026-09-09", "2026-09-10")),
                    "source_batch_id": "ok",
                    "rows_found": 1,
                    "started_at": None,
                    "finished_at": None,
                }
            ]
        elif "FROM rinse_cleaner_ticket_presence_run_rows" in s:
            cursor.fetchall.return_value = [
                {"bag_id": "OKBAG", "service_type": "HD", "hd_count_raw": "0.0"}
            ]
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.hd_ship_window_admission.table_exists", return_value=True):
        out = resolve_hd_ship_window_membership(
            cursor,
            3,
            ship_start=date(2026, 9, 9),
            ship_end=date(2026, 9, 10),
            require_trustworthy=True,
        )
    assert out["ok"] is True
    assert out["bag_ids"] == ["OKBAG"]
    assert out["trustworthy"] is True


def test_anomalous_current_scrape_fails_closed_for_reset_admission():
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = [
                {
                    "id": 300,
                    "status": "anomalous",
                    "scrape_meta_json": json.dumps(
                        _meta("2026-09-09", "2026-09-10", trustworthy=False)
                    ),
                    "source_batch_id": "bad",
                    "rows_found": 6,
                    "started_at": None,
                    "finished_at": None,
                }
            ]
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.hd_ship_window_admission.table_exists", return_value=True), patch(
        "backend.hd_ship_window_admission.active_hd_presence_bag_ids",
        return_value={"STALE1", "LIVE1"},
    ), patch("backend.hd_ship_window_admission.admit_discovered_hd_bags") as admit:
        out = admit_hd_reset_from_ship_window(
            cursor,
            3,
            date(2026, 9, 9),
            ship_start=date(2026, 9, 9),
            ship_end=date(2026, 9, 10),
            require_trustworthy=True,
        )
    assert out["ok"] is False
    assert out["admitted_new"] == 0
    assert out["bag_ids"] == []
    assert out["error"] == "current_ship_window_scrape_not_trustworthy"
    assert set(out["skipped_stale_active_ids"]) == {"STALE1", "LIVE1"}
    admit.assert_not_called()


def test_repair_union_includes_intermittent_ship_window_bags():
    cursor = MagicMock()
    runs = [
        {
            "id": 2,
            "status": "anomalous",
            "scrape_meta_json": json.dumps(_meta("2026-09-09", "2026-09-10", trustworthy=False)),
            "source_batch_id": "a",
            "rows_found": 5,
            "started_at": None,
            "finished_at": None,
        },
        {
            "id": 1,
            "status": "anomalous",
            "scrape_meta_json": json.dumps(_meta("2026-09-09", "2026-09-10", trustworthy=False)),
            "source_batch_id": "b",
            "rows_found": 6,
            "started_at": None,
            "finished_at": None,
        },
    ]

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = runs
        elif "FROM rinse_cleaner_ticket_presence_run_rows" in s:
            rid = int(params[1])
            if rid == 2:
                cursor.fetchall.return_value = [
                    {"bag_id": "A", "service_type": "HD", "hd_count_raw": "0.0"},
                    {"bag_id": "B", "service_type": "HD", "hd_count_raw": "0.0"},
                ]
            else:
                cursor.fetchall.return_value = [
                    {"bag_id": "A", "service_type": "HD", "hd_count_raw": "0.0"},
                    {"bag_id": "B", "service_type": "HD", "hd_count_raw": "0.0"},
                    {"bag_id": "C", "service_type": "HD", "hd_count_raw": "0.0"},
                ]
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute
    with patch("backend.hd_ship_window_admission.table_exists", return_value=True):
        out = resolve_hd_ship_window_membership(
            cursor,
            3,
            ship_start=date(2026, 9, 9),
            ship_end=date(2026, 9, 10),
            require_trustworthy=False,
            union_recent_captures=True,
        )
    assert out["ok"] is True
    assert set(out["bag_ids"]) == {"A", "B", "C"}
    assert out["union_recent_captures"] is True


def test_incomplete_carry_forward_still_works_after_valid_admission():
    """Quarantined stale rows stay out; valid incomplete admits still carry forward."""
    cursor = MagicMock()
    # SQL excludes PRE_ACTIVATION_EXCLUDED — fetchall only returns non-quarantined rows.
    cursor.fetchall.return_value = [
        {
            "bag_id": "KEEP1",
            "workflow_status": STATUS_PENDING_WASH,
            "management_completed_at": None,
            "operations_date_et": date(2026, 9, 9),
            "washed_at": None,
            "folded_at": None,
        },
    ]
    with patch("backend.management_rinse_hd.table_exists", return_value=True), patch(
        "backend.management_rinse_hd.ensure_management_hd_columns"
    ):
        ids = _load_active_admitted_bag_ids(
            cursor, 3, date(2026, 9, 10), activation=date(2026, 9, 9)
        )
    assert ids == {"KEEP1"}
    # Sep 10 selected date still includes Sep 9 incomplete admit (carry-forward).
    assert cursor.execute.call_args.args[1][0] == 3
    assert WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED in cursor.execute.call_args.args[1]


def test_quarantine_helper_marks_pre_activation_excluded():
    cursor = MagicMock()
    row = {
        "id": 9,
        "bag_id": "STALE1",
        "workflow_status": STATUS_PENDING_WASH,
        "operations_date_et": date(2026, 9, 9),
        "version": 1,
    }
    with patch(
        "backend.management_rinse_hd._load_production_by_bag",
        return_value={"STALE1": row},
    ), patch("backend.hd_ship_window_admission.table_exists", return_value=True), patch(
        "backend.hd_workflow_extensions._quarantine_row"
    ) as q:
        out = quarantine_hd_stale_reset_admissions(cursor, 3, ["STALE1"])
    assert out["quarantined"] == 1
    assert out["bag_ids"] == ["STALE1"]
    q.assert_called_once_with(cursor, 9)


def test_wf_unaffected_by_hd_ship_window_helpers():
    """Smoke: helpers do not import or call WF workload derivation."""
    import backend.hd_ship_window_admission as mod

    src = open(mod.__file__).read()
    assert "get_canonical_wf_workload" not in src
    assert "rinse_wf_service_cycle" not in src
    assert "admit_discovered_hd_bags" in src
