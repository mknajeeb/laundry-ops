"""Strict HD admission evidence + idempotent insert regressions."""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.hd_ship_window_admission import resolve_hd_ship_window_membership
from backend.management_rinse_hd import (
    STATUS_PENDING_WASH,
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    _ensure_admitted_production_row,
    _is_duplicate_hd_production_key,
    _load_active_admitted_bag_ids,
    _load_hd_discovery_bag_ids,
    admit_discovered_hd_bags,
    has_positive_hd_admission_evidence,
    hd_count_field_present,
    hd_row_eligible_for_admission,
)
from backend.rinse_ship_window_tickets_urls import build_ship_window_tickets_url


def _hang_dry_meta(start: str = "2026-09-09", end: str = "2026-09-10") -> dict:
    url = build_ship_window_tickets_url(
        service_types="hang_dry",
        date_start=date.fromisoformat(start),
        date_end=date.fromisoformat(end),
    )
    return {
        "tickets_sources": [
            {
                "label": "hang_dry",
                "service_types": "hang_dry",
                "ship_to_vendor_date_start": start,
                "ship_to_vendor_date_end": end,
                "url": url,
            },
            {
                "label": "wash_and_fold",
                "service_types": "wash_and_fold",
                "ship_to_vendor_date_start": start,
                "ship_to_vendor_date_end": end,
            },
        ],
        "completeness_guard": {"trustworthy": True},
    }


class _Dup1062(Exception):
    errno = 1062

    def __str__(self) -> str:
        return "1062 (23000): Duplicate entry '3-2026-09-10-BEKNJ2F333' for key 'uq_hd_day_bag_prod'"


def test_a_classified_hd_weight_zero_hd_count_null_not_admitted():
    row = {
        "bag_id": "EZRB438WCY",
        "service_type": "HD",
        "weight_raw": "0",
        "hd_count_raw": None,
        "hd_count_num": None,
        "raw_row_json": {"service_type": "HD", "weight_raw": "0", "hd_count_raw": None},
    }
    assert hd_count_field_present(None) is False
    assert has_positive_hd_admission_evidence(row) is False
    assert hd_row_eligible_for_admission(row, has_authoritative_wf=True) is False


def test_b_classified_hd_with_hd_count_zero_admitted():
    row = {
        "bag_id": "28WV1QS4F9",
        "service_type": "HD",
        "hd_count_raw": "0.0",
        "hd_count_num": 0.0,
        "raw_row_json": {"hd_count_raw": "0.0", "hd_count_num": 0.0},
    }
    assert hd_count_field_present(0) is True
    assert hd_count_field_present(0.0) is True
    assert hd_count_field_present("0.0") is True
    assert has_positive_hd_admission_evidence(row) is True
    assert hd_row_eligible_for_admission(row, has_authoritative_wf=False) is True


def test_c_genuine_positive_hd_count_admitted():
    row = {"bag_id": "HDITEMS", "service_type": "HD", "hd_count_raw": "3"}
    assert has_positive_hd_admission_evidence(row) is True
    assert hd_row_eligible_for_admission(row) is True


def test_d_unknown_or_missing_evidence_fails_closed():
    assert has_positive_hd_admission_evidence({"service_type": "HD"}) is False
    assert has_positive_hd_admission_evidence({"service_type": None}) is False
    assert has_positive_hd_admission_evidence({"service_type": "HD", "hd_count_raw": ""}) is False
    assert has_positive_hd_admission_evidence({"active": 1, "weight_raw": "0"}) is False
    assert hd_row_eligible_for_admission({}) is False


def test_e_wf_oi_cannot_bleed_without_hd_count():
    row = {
        "bag_id": "BEKNJ2F333",
        "service_type": "HD",
        "hd_count_raw": None,
        "raw_row_json": {"service_type": "HD", "hd_count_num": None},
    }
    assert hd_row_eligible_for_admission(row, has_authoritative_wf=True) is False


def test_e_live_discovery_excludes_classified_hd_without_hd_count():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [
            {
                "bag_id": "BEKNJ2F333",
                "service_type": "HD",
                "hd_count_raw": None,
                "raw_row_json": {"service_type": "HD", "hd_count_raw": None, "weight_raw": "0"},
            },
            {
                "bag_id": "28WV1QS4F9",
                "service_type": "HD",
                "hd_count_raw": "0.0",
                "raw_row_json": {"hd_count_raw": "0.0"},
            },
        ],
        [{"bag_id": "BEKNJ2F333", "service_type": "WF"}],
        [{"bag_id": "BEKNJ2F333", "service_type": "WF"}],
    ]
    with patch("backend.management_rinse_hd.table_exists", return_value=True), patch(
        "backend.management_rinse_hd.table_has_column", return_value=True
    ):
        ids = _load_hd_discovery_bag_ids(cur, 3)
    assert ids == {"28WV1QS4F9"}
    assert "BEKNJ2F333" not in ids
    assert "EZRB438WCY" not in ids


def test_f_reset_admission_rejects_classified_hd_without_hd_count():
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split())
        if "FROM rinse_cleaner_ticket_presence_runs" in s:
            cursor.fetchall.return_value = [
                {
                    "id": 7399,
                    "status": "success",
                    "scrape_meta_json": json.dumps(_hang_dry_meta()),
                    "source_batch_id": "mix",
                    "rows_found": 144,
                    "started_at": None,
                    "finished_at": None,
                }
            ]
        elif "FROM rinse_cleaner_ticket_presence_run_rows" in s:
            cursor.fetchall.return_value = [
                {"bag_id": "28WV1QS4F9", "service_type": "HD", "hd_count_raw": "0.0"},
                {
                    "bag_id": "EZRB438WCY",
                    "service_type": "HD",
                    "hd_count_raw": None,
                    "hd_count_num": None,
                    "weight_raw": "0",
                },
                {"bag_id": "WFONLY", "service_type": "WF", "hd_count_raw": None},
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
    assert out["bag_ids"] == ["28WV1QS4F9"]
    assert "EZRB438WCY" not in out["bag_ids"]
    assert "WFONLY" not in out["bag_ids"]


def test_g_live_management_hd_admits_only_discovery_ids():
    from backend.management_rinse_hd import build_rinse_hd_day

    cursor = MagicMock()
    with (
        patch("backend.management_rinse_hd.table_exists", return_value=True),
        patch("backend.management_rinse_hd.ensure_management_hd_columns"),
        patch(
            "backend.hd_workflow_extensions.hd_workflow_cutoff",
            return_value=(date(2026, 8, 21), None),
        ),
        patch("backend.management_rinse_hd._load_hd_service_hints", return_value={}),
        patch(
            "backend.management_rinse_hd._load_hd_discovery_bag_ids",
            return_value={"28WV1QS4F9"},
        ),
        patch(
            "backend.management_rinse_hd.admit_discovered_hd_bags",
            return_value={"admitted_new": 1, "already_admitted": 0, "bag_ids": ["28WV1QS4F9"]},
        ) as admit,
        patch("backend.management_rinse_hd._load_active_admitted_bag_ids", return_value=set()),
        patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
        patch("backend.management_rinse_hd._load_production_by_bag", return_value={}),
        patch("backend.management_rinse_hd._load_user_maps", return_value={}),
        patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
    ):
        build_rinse_hd_day(cursor, 3, date(2026, 9, 10), status="all")
    admit.assert_called_once()
    admitted = set(admit.call_args[0][3])
    assert admitted == {"28WV1QS4F9"}
    assert "EZRB438WCY" not in admitted
    assert "BEKNJ2F333" not in admitted


def test_g_hints_without_hd_count_are_filtered():
    from backend.management_rinse_hd import _load_hd_service_hints

    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [{"bag_id": "HINTWF", "service_type": "HD", "shift_date_et": date(2026, 9, 10)}],
        [{"bag_id": "HINTWF", "service_type": "HD", "raw_row_json": {"hd_count_raw": None}}],
    ]
    with patch("backend.management_rinse_hd.table_exists", return_value=True), patch(
        "backend.management_rinse_hd.table_has_column", return_value=True
    ), patch(
        "backend.management_rinse_hd.HD_WORKFLOW_ACTIVATION_DATE", date(2026, 8, 21)
    ):
        hints = _load_hd_service_hints(cursor, 3, date(2026, 9, 10))
    assert hints == {}


def test_h_repeated_admission_is_idempotent():
    cursor = MagicMock()
    existing = {
        "id": 9,
        "bag_id": "KEEP1",
        "workflow_status": STATUS_PENDING_WASH,
        "operations_date_et": date(2026, 9, 9),
        "admitted_at": datetime(2026, 9, 9, 11, 11),
    }
    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd.table_exists", return_value=True
    ), patch(
        "backend.management_rinse_hd.table_has_column", return_value=True
    ), patch(
        "backend.management_rinse_hd._load_production_by_bag",
        side_effect=[{}, {"KEEP1": existing}, {"KEEP1": existing}],
    ):
        first = admit_discovered_hd_bags(cursor, 3, date(2026, 9, 9), ["KEEP1"])
        second = admit_discovered_hd_bags(cursor, 3, date(2026, 9, 9), ["KEEP1"])
    assert first["admitted_new"] == 1
    assert second["admitted_new"] == 0
    assert second["already_admitted"] == 1


def test_i_concurrent_duplicate_admission_does_not_raise_1062():
    existing = {
        "id": 155,
        "bag_id": "BEKNJ2F333",
        "workflow_status": STATUS_PENDING_WASH,
        "operations_date_et": date(2026, 9, 10),
        "admitted_at": datetime(2026, 9, 10, 18, 22, 35),
    }

    def execute(sql, params=None):
        if "INSERT INTO hd_day_bag_production" in str(sql):
            raise _Dup1062()

    cursor = MagicMock()
    cursor.execute.side_effect = execute
    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd._load_production_by_bag",
        side_effect=[{}, {"BEKNJ2F333": existing}],
    ):
        out = _ensure_admitted_production_row(
            cursor,
            org=3,
            bid="BEKNJ2F333",
            admission_date_et=date(2026, 9, 10),
        )
    assert out["created"] is False
    assert out["row"]["id"] == 155
    assert _is_duplicate_hd_production_key(_Dup1062()) is True


def test_i_non_duplicate_integrity_error_is_not_swallowed():
    class _Other(Exception):
        errno = 1452

        def __str__(self) -> str:
            return "Cannot add or update a child row"

    def execute(sql, params=None):
        if "INSERT INTO hd_day_bag_production" in str(sql):
            raise _Other()

    cursor = MagicMock()
    cursor.execute.side_effect = execute
    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd._load_production_by_bag", return_value={}
    ):
        try:
            _ensure_admitted_production_row(
                cursor, org=3, bid="X", admission_date_et=date(2026, 9, 10)
            )
        except _Other:
            return
        raise AssertionError("expected non-duplicate integrity error to propagate")


def test_j_existing_valid_hd_carry_forward_unchanged():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": "28WV1QS4F9",
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
    assert ids == {"28WV1QS4F9"}
    assert WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED in cursor.execute.call_args.args[1]


def test_k_wf_lifecycle_not_imported_by_admission_helpers():
    import backend.hd_ship_window_admission as ship
    import backend.management_rinse_hd as hd

    ship_src = open(ship.__file__).read()
    hd_src = open(hd.__file__).read()
    assert "classify_service" not in ship_src
    assert "get_canonical_wf_workload" not in ship_src
    assert "rinse_wf_service_cycle" not in ship_src
    assert "from etl.transform_orders import classify_service" not in hd_src
    assert "def classify_service" not in hd_src
