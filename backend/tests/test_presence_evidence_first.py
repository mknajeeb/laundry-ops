"""Evidence-first presence scrape + immutable run rows + retention + interval attach."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    PresenceRunRowConflictError,
    apply_presence_scrape,
    parse_presence_rows_from_portal_csv,
    persist_presence_run_snapshot_rows,
)
from backend.rinse_presence_snapshot_retention import (
    RETENTION_POLICY,
    prune_presence_run_snapshots,
)
from backend.rinse_scan_weight_enrichment import (
    WEIGHT_ROLE_POST,
    WEIGHT_ROLE_PRE,
    WEIGHT_ROLE_RECHECK,
    attach_observations_to_weight_events,
    restore_weight_enrichment,
)
from backend.tests import test_rinse_cleaner_ticket_presence as _presence_tests
from backend.tests import test_scan_weight_enrichment as _weight_tests

_with_apply_patches = _presence_tests._with_apply_patches
_mock_cursor = lambda: _presence_tests.TestPresenceApplyDryRun()._mock_cursor_with_table()
BAG = _weight_tests.BAG
ORG = _weight_tests.ORG
T0 = _weight_tests.T0
T1 = _weight_tests.T1
T2 = _weight_tests.T2
T3 = _weight_tests.T3
_FakeCursor = _weight_tests._FakeCursor
_row = _weight_tests._row


_CSV_HEADER = (
    "Date,Estd. Delivery,Customer,# WF LBS,# HD,# WF ITEMS,Weight,Notes,Special Instructions,"
    "USE OXIC,Use Hypo,USE FAB,Low DRY,NO SCEN,Extra Scen,Service Type,Sub-Service,Bag ID\n"
)


class TestWeightNumSurvivesParse:
    def test_weight_column_parses_to_weight_num(self, tmp_path):
        csv_path = tmp_path / "weights.csv"
        # 18 portal columns; Weight alone drives Weight_Num when # WF LBS is blank.
        csv_path.write_text(
            _CSV_HEADER
            + "Mon 07/20/2026,Tue 07/21/2026,Alice,,,,12.5 LBS,,,,,,,,,Wash & Fold,,BAGWT001\n"
            + "Mon 07/20/2026,Tue 07/21/2026,Bob,,,,0,,,,,,,,,Wash & Fold,,BAGWT000\n"
            + "Mon 07/20/2026,Tue 07/21/2026,Carol,,,,,,,,,,,,,Wash & Fold,,BAGWTBLK\n",
            encoding="utf-8",
        )
        rows = parse_presence_rows_from_portal_csv(str(csv_path))
        by_bag = {r["bag_id"]: r for r in rows}
        assert by_bag["BAGWT001"]["weight_num"] == 12.5
        assert by_bag["BAGWT001"]["weight_raw"] == "12.5 LBS"
        assert by_bag["BAGWT000"]["weight_num"] == 0.0
        assert by_bag["BAGWTBLK"]["weight_num"] is None


class TestEvidenceBeforeBoard:
    @_with_apply_patches
    @patch("backend.rinse_cleaner_ticket_presence.persist_presence_run_snapshot_rows")
    @patch("backend.rinse_cleaner_ticket_presence.record_presence_scrape_run", return_value=55)
    def test_record_and_persist_before_board_insert(self, mock_record, mock_persist):
        mock_persist.return_value = {"written": 1, "skipped_identical": 0, "identities": []}
        cursor = _mock_cursor()
        order: list[str] = []

        def _record(*a, **k):
            order.append("record")
            return 55

        def _persist(*a, **k):
            order.append("persist")
            return {"written": 1, "skipped_identical": 0, "identities": []}

        mock_record.side_effect = _record
        mock_persist.side_effect = _persist

        orig_execute = cursor.execute.side_effect

        def execute(sql, args=None):
            s = " ".join(str(sql).split())
            if "INSERT INTO rinse_cleaner_ticket_presence " in s or (
                "INSERT INTO rinse_cleaner_ticket_presence (" in s
            ):
                order.append("board_insert")
            return orig_execute(sql, args)

        cursor.execute.side_effect = execute

        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "EVID1", "customer_name": "Eve"}],
            source_batch_id="batch-e",
            dry_run=False,
        )
        assert stats["board_applied"] is True
        assert order[:2] == ["record", "persist"]
        assert "board_insert" in order
        assert order.index("record") < order.index("board_insert")
        assert order.index("persist") < order.index("board_insert")


class TestInvalidScrapeSkipsBoard:
    @_with_apply_patches
    def test_invalid_scrape_leaves_board_unchanged(self):
        cursor = _mock_cursor()
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "KEEP1", "customer_name": "Keep"}],
            dry_run=False,
        )
        assert (10, "KEEP1") in cursor._store

        with patch(
            "backend.rinse_cleaner_ticket_presence._evaluate_presence_completeness_guard",
            return_value={
                "allow_mark_missing": False,
                "trustworthy": False,
                "reason": "row_count_drop",
            },
        ):
            before = {k: dict(v) for k, v in cursor._store.items()}
            stats = apply_presence_scrape(
                cursor,
                10,
                portal_status=PORTAL_STATUS_READY,
                rows=[{"bag_id": "NEWBAD", "customer_name": "Bad"}],
                mark_missing=True,
                dry_run=False,
            )
        assert stats["board_applied"] is False
        assert stats.get("board_update_skipped") is True
        assert (10, "NEWBAD") not in cursor._store
        assert cursor._store[(10, "KEEP1")]["active"] == 1
        assert cursor._store == before


class TestImmutableRunRows:
    def test_material_conflict_raises(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": 1,
            "presence_run_id": 1,
            "organization_id": 3,
            "source_batch_id": "b1",
            "portal_status": PORTAL_STATUS_AT_VENDOR,
            "bag_id": "VEEONLY1",
            "customer_name": "Old",
            "estimated_delivery_date": None,
            "rush_flag": None,
            "service_type": "WF",
            "weight_num": 10.0,
            "weight_raw": "10",
            "wf_lbs_num": None,
            "wf_lbs_raw": None,
            "hd_count_num": None,
            "hd_count_raw": None,
            "wf_items_num": None,
            "wf_items_raw": None,
            "observed_at": datetime(2026, 7, 23, 12, 0),
            "source_row_seq": 1,
            "rinse_vendor": "veewash",
        }
        with patch("backend.rinse_cleaner_ticket_presence.ensure_presence_run_rows_table"):
            with pytest.raises(PresenceRunRowConflictError):
                persist_presence_run_snapshot_rows(
                    cursor,
                    3,
                    presence_run_id=1,
                    portal_status=PORTAL_STATUS_AT_VENDOR,
                    source_batch_id="b1",
                    rows=[
                        {
                            "bag_id": "VEEONLY1",
                            "customer_name": "New",
                            "service_type": "WF",
                            "weight_num": 11.0,
                            "weight_raw": "11",
                        }
                    ],
                    rinse_vendor="veewash",
                    observed_at=datetime(2026, 7, 23, 12, 0),
                )

    def test_identical_retry_is_noop(self):
        existing = {
            "id": 9,
            "presence_run_id": 1,
            "organization_id": 3,
            "source_batch_id": "b1",
            "portal_status": PORTAL_STATUS_AT_VENDOR,
            "bag_id": "SAME1",
            "customer_name": "Sam",
            "estimated_delivery_date": None,
            "rush_flag": None,
            "service_type": "WF",
            "weight_num": 10.0,
            "weight_raw": "10",
            "wf_lbs_num": None,
            "wf_lbs_raw": None,
            "hd_count_num": None,
            "hd_count_raw": None,
            "wf_items_num": None,
            "wf_items_raw": None,
            "observed_at": datetime(2026, 7, 23, 12, 0),
            "source_row_seq": 1,
            "rinse_vendor": "veewash",
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        with patch("backend.rinse_cleaner_ticket_presence.ensure_presence_run_rows_table"):
            out = persist_presence_run_snapshot_rows(
                cursor,
                3,
                presence_run_id=1,
                portal_status=PORTAL_STATUS_AT_VENDOR,
                source_batch_id="b1",
                rows=[
                    {
                        "bag_id": "SAME1",
                        "customer_name": "Sam",
                        "service_type": "WF",
                        "weight_num": 10.0,
                        "weight_raw": "10",
                    }
                ],
                rinse_vendor="veewash",
                observed_at=datetime(2026, 7, 23, 12, 0),
            )
        assert out["written"] == 0
        assert out["skipped_identical"] == 1
        insert_calls = [
            c
            for c in cursor.execute.call_args_list
            if "INSERT INTO rinse_cleaner_ticket_presence_run_rows" in " ".join(str(c.args[0]).split())
        ]
        assert insert_calls == []


class TestRetentionRetainAll:
    def test_prune_deletes_nothing_after_many_runs(self):
        runs = [
            {
                "id": 200 + i,
                "organization_id": 3,
                "portal_status": PORTAL_STATUS_AT_VENDOR,
                "status": "success",
                "finished_at": datetime(2026, 7, 20, 12, i),
                "errors_json": None,
                "scrape_meta_json": {"rinse_vendor": "veewash"},
            }
            for i in range(12)
        ]
        cursor = MagicMock()
        with patch(
            "backend.rinse_presence_snapshot_retention.table_exists", return_value=True
        ), patch(
            "backend.rinse_presence_snapshot_retention._list_successful_presence_runs",
            return_value=runs,
        ):
            out = prune_presence_run_snapshots(
                cursor, 3, portal_status=PORTAL_STATUS_AT_VENDOR, rinse_vendor="veewash"
            )
        assert out["policy"] == RETENTION_POLICY
        assert out["deleted_run_rows"] == 0
        assert out["deleted_runs"] == 0
        assert out["kept_run_ids"] == list(range(200, 212))
        assert out["pruned_run_ids"] == []


class TestIntervalAttachEvidence:
    def test_pre_then_post_same_numeric_from_different_obs(self):
        events = [
            _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
            _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
        ]
        cur = _FakeCursor([dict(e) for e in events])
        observations = [
            {"weight_num": 23.6, "observed_at": T1, "presence_run_id": 1, "presence_run_row_id": 11},
            {"weight_num": 23.6, "observed_at": T3, "presence_run_id": 2, "presence_run_row_id": 22},
        ]
        result = attach_observations_to_weight_events(
            cur, ORG, BAG, observations=observations, events=events, dry_run=False
        )
        assert result["updated_count"] == 2
        assert cur.scan_events[0]["weight_lbs"] == 23.6
        assert cur.scan_events[0]["weight_role"] == WEIGHT_ROLE_PRE
        assert cur.scan_events[1]["weight_lbs"] == 23.6
        assert cur.scan_events[1]["weight_role"] == WEIGHT_ROLE_POST

    def test_one_observation_does_not_fill_twice(self):
        events = [
            _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
            _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
        ]
        cur = _FakeCursor([dict(e) for e in events])
        observations = [
            {"weight_num": 23.6, "observed_at": T1, "presence_run_id": 1, "presence_run_row_id": 11},
        ]
        result = attach_observations_to_weight_events(
            cur, ORG, BAG, observations=observations, events=events, dry_run=False
        )
        assert result["updated_count"] == 1
        assert cur.scan_events[0]["weight_lbs"] == 23.6
        assert cur.scan_events[1]["weight_lbs"] is None

    def test_later_obs_cannot_backfill_pre(self):
        events = [
            _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
            _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
        ]
        cur = _FakeCursor([dict(e) for e in events])
        observations = [
            {"weight_num": 22.6, "observed_at": T2, "presence_run_id": 1, "presence_run_row_id": 1},
        ]
        result = attach_observations_to_weight_events(
            cur, ORG, BAG, observations=observations, events=events, dry_run=False
        )
        assert result["updated_count"] == 1
        assert cur.scan_events[0]["weight_lbs"] is None
        assert cur.scan_events[1]["weight_lbs"] == 22.6
        assert cur.scan_events[1]["weight_role"] == WEIGHT_ROLE_POST

    def test_third_event_is_weight_recheck(self):
        events = [
            _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
            _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
            _row(3, BAG, T2, weight_lbs=None, dedupe_key="dkC"),
        ]
        cur = _FakeCursor([dict(e) for e in events])
        observations = [
            {"weight_num": 10.0, "observed_at": T0, "presence_run_id": 1, "presence_run_row_id": 1},
            {"weight_num": 20.0, "observed_at": T1, "presence_run_id": 2, "presence_run_row_id": 2},
            {"weight_num": 30.0, "observed_at": T3, "presence_run_id": 3, "presence_run_row_id": 3},
        ]
        result = attach_observations_to_weight_events(
            cur, ORG, BAG, observations=observations, events=events, dry_run=False
        )
        roles = [a["weight_role"] for a in result["attached"]]
        assert roles == [WEIGHT_ROLE_PRE, WEIGHT_ROLE_POST, WEIGHT_ROLE_RECHECK]
        assert cur.scan_events[2]["weight_role"] == WEIGHT_ROLE_RECHECK


class TestTimelineRestoreUnmatched:
    def test_restore_reports_unmatched(self):
        cur = _FakeCursor([_row(1, BAG, T0, weight_lbs=None, dedupe_key="dkOther")])
        preserved = {
            (BAG, "dkMissing"): {
                "weight_lbs": 13.2,
                "weight_source": "presence_run_weight_num",
                "weight_role": WEIGHT_ROLE_PRE,
            }
        }
        restored = restore_weight_enrichment(cur, ORG, preserved)
        assert restored["updated"] == 0
        assert len(restored["unmatched"]) == 1
        assert restored["unmatched"][0]["reason"] == "dedupe_key_not_found"
        assert restored["unmatched"][0]["weight_lbs"] == 13.2
