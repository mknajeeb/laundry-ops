"""Tests for rinse_cleaner_ticket_presence (portal ready_for_vendor / at_vendor)."""

from contextlib import ExitStack
from datetime import date, datetime
from functools import wraps
from unittest.mock import MagicMock, patch

from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    SENT_TO_RINSE,
    SENT_TO_VENDOR,
    derive_bag_lifecycle_status,
)
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    PRESENCE_RUSH_UNKNOWN,
    _presence_effective_rush,
    apply_presence_scrape,
    build_tickets_url_for_portal_status,
    get_presence_flags,
    load_wf_presence_incoming_rows,
)
from backend.rinse_portal_csv import parse_rush_flag_from_portal_cells


class TestRushParsing:
    def test_rush_from_estimated_delivery_text(self):
        assert parse_rush_flag_from_portal_cells(["Mon 06/01/2026 ⚡ RUSH"]) == "RUSH"

    def test_unknown_when_no_rush_hint(self):
        assert parse_rush_flag_from_portal_cells(["Mon 06/01/2026"]) is None

    def test_presence_effective_rush_unknown_without_signal(self):
        row = {"rush_flag": None, "estimated_delivery_date": None, "raw_row_json": {}}
        assert _presence_effective_rush(row, date(2026, 6, 1)) == PRESENCE_RUSH_UNKNOWN

    def test_presence_effective_rush_from_estimated_delivery_date(self):
        row = {
            "rush_flag": None,
            "estimated_delivery_date": date(2026, 6, 3),
            "raw_row_json": {},
        }
        assert _presence_effective_rush(row, date(2026, 6, 4)) == "RUSH"
        assert _presence_effective_rush(row, date(2026, 6, 3)) == "NON-RUSH"

    def test_presence_future_delivery_not_rush(self):
        row = {
            "rush_flag": "RUSH",
            "estimated_delivery_date": date(2026, 6, 11),
            "raw_row_json": {},
        }
        assert _presence_effective_rush(row, date(2026, 6, 9)) == "NON-RUSH"

    def test_presence_effective_rush_from_raw_json_text(self):
        row = {
            "rush_flag": None,
            "estimated_delivery_date": date(2026, 6, 2),
            "raw_row_json": {"estimated_delivery_text": "Mon 06/01/2026 ⚡ RUSH"},
        }
        assert _presence_effective_rush(row, date(2026, 6, 1)) == "RUSH"


class TestTicketsUrlBuilder:
    _FULL_PARAM_KEYS = (
        "q",
        "estimated_delivery_date_start",
        "estimated_delivery_date_end",
        "status",
        "speed",
        "transactionality",
        "service_types",
        "extra_qc",
        "rfd",
        "corporate_account",
        "vip",
        "assembled",
        "bagged",
        "steps_in_cleaning_process",
        "has_post_clean_weight",
        "pickup_date_start",
        "pickup_date_end",
        "ship_to_vendor_date_start",
        "ship_to_vendor_date_end",
        "receive_from_vendor_date_start",
        "receive_from_vendor_date_end",
        "page",
    )

    def test_replaces_status_param_with_full_filter(self):
        base = "https://www.rinse.com/cleanertickets/?status=at_vendor&page=1"
        url = build_tickets_url_for_portal_status(base, PORTAL_STATUS_READY)
        assert "status=ready_for_vendor" in url
        assert "status=at_vendor" not in url
        for key in self._FULL_PARAM_KEYS:
            assert f"{key}=" in url, f"missing param {key}"
        assert "service_types=" in url
        assert "service_type=" not in url

    def test_short_base_expanded_to_full_filter(self):
        url = build_tickets_url_for_portal_status(
            "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1",
            PORTAL_STATUS_READY,
        )
        assert "status=ready_for_vendor" in url
        assert "service_types=" in url
        assert "estimated_delivery_date_start=" in url

    def test_page_number(self):
        url = build_tickets_url_for_portal_status(
            "https://www.rinse.com/cleanertickets/?page=1",
            PORTAL_STATUS_AT_VENDOR,
            page=3,
        )
        assert "page=3" in url
        assert "status=at_vendor" in url


_APPLY_PATCHES = [
    patch(
        "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
        side_effect=lambda cursor, org, bags, **kw: (set(bags), []),
    ),
    patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True),
    patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns"),
    patch("backend.rinse_cleaner_ticket_presence.ensure_presence_run_rows_table"),
    patch("backend.rinse_cleaner_ticket_presence.ensure_presence_run_processing_columns"),
    patch("backend.rinse_cleaner_ticket_presence.ensure_weight_observation_migration_archive"),
    patch("backend.rinse_presence_snapshot_retention.prune_presence_run_snapshots", return_value={}),
]


def _with_apply_patches(fn):
    """Apply evidence-first scrape stubs without injecting mock args into the test."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with ExitStack() as stack:
            for p in _APPLY_PATCHES:
                stack.enter_context(p)
            return fn(*args, **kwargs)

    return wrapper


class TestPresenceApplyDryRun:
    def _mock_cursor_with_table(self):
        cursor = MagicMock()
        store: dict[tuple[int, str], dict] = {}
        cursor.lastrowid = 1
        run_rows: dict[tuple[int, str], dict] = {}

        def execute(sql, args=None):
            args = args or ()
            s = " ".join(str(sql).split())
            if "CREATE TABLE" in s or s.startswith("ALTER TABLE"):
                return
            if "FROM rinse_cleaner_ticket_presence_runs" in s and "ORDER BY started_at" in s:
                cursor.fetchall.return_value = []
                return
            if "SELECT evidence_processing_json FROM rinse_cleaner_ticket_presence_runs" in s:
                cursor.fetchone.return_value = {"evidence_processing_json": {}}
                return
            if (
                "FROM rinse_cleaner_ticket_presence_run_rows" in s
                and "WHERE presence_run_id=%s AND bag_id=%s" in s
            ):
                key = (int(args[0]), str(args[1]))
                cursor.fetchone.return_value = run_rows.get(key)
                return
            if "INSERT INTO rinse_cleaner_ticket_presence_run_rows" in s:
                run_id, org, batch_id, ps, bag_id = (
                    int(args[0]),
                    int(args[1]),
                    str(args[2]),
                    str(args[3]),
                    str(args[4]),
                )
                cursor.lastrowid = int(getattr(cursor, "lastrowid", 0) or 0) + 1
                run_rows[(run_id, bag_id)] = {
                    "id": cursor.lastrowid,
                    "presence_run_id": run_id,
                    "organization_id": org,
                    "source_batch_id": batch_id,
                    "portal_status": ps,
                    "bag_id": bag_id,
                    "customer_name": args[5],
                    "estimated_delivery_date": args[6],
                    "rush_flag": args[7],
                    "service_type": args[8],
                    "weight_num": args[9],
                    "weight_raw": args[10],
                    "wf_lbs_num": args[11],
                    "wf_lbs_raw": args[12],
                    "hd_count_num": args[13],
                    "hd_count_raw": args[14],
                    "wf_items_num": args[15],
                    "wf_items_raw": args[16],
                    "observed_at": args[17],
                    "source_row_seq": args[18],
                    "rinse_vendor": args[20] if len(args) > 20 else None,
                }
                return
            if "UPDATE rinse_cleaner_ticket_presence_runs" in s:
                return
            if "SELECT COUNT(*) AS active_rows" in s:
                cursor.fetchone.return_value = {"active_rows": len(store)}
                return
            if (
                "SELECT bag_id FROM rinse_cleaner_ticket_presence" in s
                and "portal_status=%s" in s
                and "active=1" in s
            ):
                org, ps = int(args[0]), str(args[1])
                cursor.fetchall.return_value = [
                    {"bag_id": bid}
                    for (o, bid), row in store.items()
                    if o == org and row.get("portal_status") == ps and row.get("active") == 1
                ]
            elif "FROM rinse_cleaner_ticket_presence" in s and "LIMIT 1" in s:
                if args and len(args) >= 2:
                    key = (int(args[0]), str(args[1]))
                    cursor.fetchone.return_value = store.get(key)
            elif "INSERT INTO rinse_cleaner_ticket_presence_runs" in s:
                cursor._next_run_id = int(getattr(cursor, "_next_run_id", 41)) + 1
                cursor.lastrowid = cursor._next_run_id
            elif "INSERT INTO rinse_cleaner_ticket_presence " in s or (
                "INSERT INTO rinse_cleaner_ticket_presence\n" in str(sql)
            ) or "INSERT INTO rinse_cleaner_ticket_presence (" in s:
                org, bag_id = int(args[0]), str(args[1])
                store[(org, bag_id)] = {
                    "organization_id": org,
                    "bag_id": bag_id,
                    "portal_status": args[2],
                    "previous_portal_status": None,
                    "active": 1,
                    "first_seen_at": args[3],
                    "last_seen_at": args[4],
                    "portal_status_first_seen_at": args[5],
                    "portal_status_changed_at": args[6],
                    "source_batch_id": args[7],
                    "customer_name": args[8],
                }
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "active=0" in s:
                org, bag_id = int(args[1]), str(args[2])
                key = (org, bag_id)
                if key in store:
                    store[key]["active"] = 0
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "previous_portal_status" in s:
                org, bag_id = int(args[11]), str(args[12])
                key = (org, bag_id)
                if key in store:
                    store[key].update(
                        {
                            "portal_status": args[0],
                            "previous_portal_status": args[1],
                            "last_seen_at": args[2],
                            "portal_status_first_seen_at": args[3],
                            "portal_status_changed_at": args[4],
                        }
                    )
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "SET active=1, last_seen_at" in s:
                org, bag_id = int(args[7]), str(args[8])
                key = (org, bag_id)
                if key in store:
                    store[key]["last_seen_at"] = args[0]
                    store[key]["active"] = 1

        cursor.execute.side_effect = execute
        cursor._store = store
        cursor._run_rows = run_rows
        return cursor

    @_with_apply_patches
    def test_ready_for_vendor_inserted_per_org(self):
        cursor = self._mock_cursor_with_table()
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG100", "customer_name": "Alice"}],
            source_batch_id="batch1",
            dry_run=False,
        )
        assert stats["rows_inserted"] == 1
        assert stats["board_applied"] is True
        assert cursor._store[(10, "BAG100")]["portal_status"] == PORTAL_STATUS_READY

    @_with_apply_patches
    def test_at_vendor_updates_same_bag(self):
        cursor = self._mock_cursor_with_table()
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG200", "customer_name": "Bob"}],
            source_batch_id="batch1",
            dry_run=False,
        )
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            rows=[{"bag_id": "BAG200", "customer_name": "Bob"}],
            source_batch_id="batch2",
            dry_run=False,
        )
        assert stats["rows_updated"] == 1
        assert cursor._store[(10, "BAG200")]["portal_status"] == PORTAL_STATUS_AT_VENDOR

    @_with_apply_patches
    def test_transition_ready_to_at_vendor_flags(self):
        cursor = self._mock_cursor_with_table()
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG300"}],
            dry_run=False,
        )
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            rows=[{"bag_id": "BAG300"}],
            dry_run=False,
        )
        ready, at_vendor = get_presence_flags(cursor, 10, "BAG300")
        assert ready is False
        assert at_vendor is True

    @_with_apply_patches
    def test_tenant_a_not_visible_for_tenant_b(self):
        cursor = self._mock_cursor_with_table()
        apply_presence_scrape(
            cursor,
            1,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG400"}],
            dry_run=False,
        )
        ready_a, _ = get_presence_flags(cursor, 1, "BAG400")
        ready_b, _ = get_presence_flags(cursor, 2, "BAG400")
        assert ready_a is True
        assert ready_b is False

    @_with_apply_patches
    def test_mark_missing_deactivates_absent_rows(self):
        cursor = self._mock_cursor_with_table()
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG500"}, {"bag_id": "BAG501"}],
            dry_run=False,
        )
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG500"}],
            mark_missing=True,
            dry_run=False,
        )
        assert stats["rows_missing"] == 1
        assert cursor._store[(10, "BAG501")]["active"] == 0


class TestPortalStatusTransitions:
    @_with_apply_patches
    @patch("backend.rinse_cleaner_ticket_presence._utc_now")
    def test_transition_preserves_first_seen_and_sets_status_timestamps(self, mock_now):
        t1 = datetime(2026, 5, 29, 9, 0, 0)
        t2 = datetime(2026, 5, 29, 10, 20, 0)
        current = {"t": t1}
        mock_now.side_effect = lambda: current["t"]

        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "BAG900"}],
            dry_run=False,
        )
        row = cursor._store[(10, "BAG900")]
        assert row["first_seen_at"] == t1
        assert row["portal_status_first_seen_at"] == t1
        assert row["portal_status_changed_at"] == t1
        assert row.get("previous_portal_status") is None

        current["t"] = t2
        apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            rows=[{"bag_id": "BAG900"}],
            dry_run=False,
        )
        row = cursor._store[(10, "BAG900")]
        assert row["first_seen_at"] == t1
        assert row["last_seen_at"] == t2
        assert row["portal_status"] == PORTAL_STATUS_AT_VENDOR
        assert row["previous_portal_status"] == PORTAL_STATUS_READY
        assert row["portal_status_first_seen_at"] == t2
        assert row["portal_status_changed_at"] == t2


class TestLoadWfPresenceIncomingRows:
    def test_workitem_before_anchor_not_applicable_here(self):
        from backend.rinse_cleaner_ticket_presence import load_incoming_unassigned_presence_rows

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "bag_id": "PRE1",
                "portal_status": PORTAL_STATUS_READY,
                "customer_name": "Pre vendor",
                "estimated_delivery_date": date(2026, 5, 31),
                "rush_flag": None,
                "service_type": "WF",
                "portal_status_first_seen_at": datetime(2026, 5, 28, 21, 22),
                "last_seen_at": datetime(2026, 5, 28, 21, 22),
                "raw_row_json": None,
            }
        ]
        with patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True):
            rows, meta = load_incoming_unassigned_presence_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
        assert len(rows) == 1
        assert rows[0]["record_scope"] == "incoming"
        assert meta["incoming_wf"] == 1
        assert meta["incoming_non_rush"] == 1
        assert rows[0]["effective_rush"] == "NON-RUSH"

    def test_hd_included_in_incoming(self):
        from backend.rinse_cleaner_ticket_presence import load_incoming_unassigned_presence_rows

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "bag_id": "HDX",
                "portal_status": PORTAL_STATUS_READY,
                "customer_name": "HD",
                "estimated_delivery_date": date(2026, 5, 31),
                "rush_flag": None,
                "service_type": "HD",
                "portal_status_first_seen_at": datetime(2026, 5, 30, 9, 0),
                "last_seen_at": datetime(2026, 5, 30, 9, 0),
                "raw_row_json": None,
            }
        ]
        with patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True):
            rows, meta = load_incoming_unassigned_presence_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
        assert len(rows) == 1
        assert meta["incoming_hd"] == 1

    def test_unknown_service_in_incoming_not_wf_lifecycle(self):
        from backend.rinse_cleaner_ticket_presence import (
            load_incoming_unassigned_presence_rows,
            load_wf_presence_incoming_rows,
        )

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "bag_id": "UNK1",
                "portal_status": PORTAL_STATUS_READY,
                "customer_name": "Unknown svc",
                "estimated_delivery_date": date(2026, 5, 31),
                "rush_flag": "RUSH",
                "service_type": None,
                "portal_status_first_seen_at": datetime(2026, 5, 30, 9, 0),
                "last_seen_at": datetime(2026, 5, 30, 9, 0),
                "raw_row_json": None,
            }
        ]
        with patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True):
            rows, meta = load_incoming_unassigned_presence_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
            wf_rows, wf_meta = load_wf_presence_incoming_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
        assert len(rows) == 1
        assert meta["incoming_unknown_service"] == 1
        assert wf_rows == []


class TestLifecycleIntegration:
    def test_assigned_from_ready_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X1", ready_for_vendor_presence=True)
        assert out["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR

    def test_sent_to_vendor_from_at_vendor_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X2", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SENT_TO_VENDOR

    def test_sent_to_rinse_no_checkout_shows_not_recorded(self):
        events = [
            {
                "purpose": "",
                "scanned_at_parsed": datetime(2026, 5, 28, 12, 0),
                "rack": "CLEAN",
                "user_name": "Alex",
                "scan_index": 1,
                "id": 1,
            },
        ]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="STR1",
            missing_from_next_portal_scrape=True,
            mapped_internal_users=["Alex"],
        )
        assert out["current_lifecycle_status"] == SENT_TO_RINSE


class TestPresenceRunSnapshotPersistence:
    @_with_apply_patches
    @patch("backend.rinse_cleaner_ticket_presence.persist_presence_run_snapshot_rows")
    @patch("backend.rinse_cleaner_ticket_presence.record_presence_scrape_run", return_value=42)
    def test_at_vendor_scrape_persists_immutable_snapshot(
        self,
        mock_record_run,
        mock_persist_snapshot,
    ):
        mock_persist_snapshot.return_value = {"written": 2, "skipped_identical": 0, "identities": []}
        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        rows = [
            {"bag_id": "BAG900", "customer_name": "Carol", "service_type": "WF"},
            {"bag_id": "BAG901", "customer_name": "Dan", "service_type": "HD"},
        ]
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            rows=rows,
            source_batch_id="batch-av",
            dry_run=False,
            scrape_meta={"rinse_vendor": "veewash"},
        )
        assert stats["rows_found"] == 2
        mock_record_run.assert_called_once()
        mock_persist_snapshot.assert_called_once()
        kw = mock_persist_snapshot.call_args.kwargs
        assert kw["presence_run_id"] == 42
        assert kw["portal_status"] == PORTAL_STATUS_AT_VENDOR
        assert kw["source_batch_id"] == "batch-av"
        assert kw["rinse_vendor"] == "veewash"
        assert [r["bag_id"] for r in kw["rows"]] == ["BAG900", "BAG901"]
        assert kw["rows"][0]["service_type"] == "WF"
        assert "weight_num" in kw["rows"][0]
        assert stats.get("board_applied") is True

    @_with_apply_patches
    @patch(
        "backend.rinse_cleaner_ticket_presence.persist_presence_run_snapshot_rows",
        return_value={"written": 3, "skipped_identical": 0, "identities": []},
    )
    @patch("backend.rinse_cleaner_ticket_presence.record_presence_scrape_run", return_value=7)
    def test_ready_for_vendor_scrape_persists_immutable_snapshot(
        self,
        mock_record_run,
        mock_persist_snapshot,
    ):
        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "RFV1"}, {"bag_id": "RFV2"}, {"bag_id": "RFV3"}],
            source_batch_id="batch-rfv",
            dry_run=False,
        )
        assert stats["rows_found"] == 3
        mock_record_run.assert_called_once()
        mock_persist_snapshot.assert_called_once()
        assert mock_persist_snapshot.call_args.kwargs["portal_status"] == PORTAL_STATUS_READY
        assert mock_persist_snapshot.call_args.kwargs["presence_run_id"] == 7
        assert len(mock_persist_snapshot.call_args.kwargs["rows"]) == 3
        assert stats["snapshot_rows_persisted"] == 3

    @_with_apply_patches
    @patch("backend.rinse_cleaner_ticket_presence.persist_presence_run_snapshot_rows")
    @patch("backend.rinse_cleaner_ticket_presence.record_presence_scrape_run", return_value=1)
    def test_dry_run_does_not_persist_snapshot(
        self,
        mock_record_run,
        mock_persist_snapshot,
    ):
        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        stats = apply_presence_scrape(
            cursor,
            10,
            portal_status=PORTAL_STATUS_AT_VENDOR,
            rows=[{"bag_id": "BAGDRY"}],
            dry_run=True,
        )
        assert stats["rows_found"] == 1
        mock_record_run.assert_not_called()
        mock_persist_snapshot.assert_not_called()
        assert "snapshot_rows_persisted" not in stats


class TestPresenceCrossOrgGuard:
    def test_apply_presence_scrape_passes_credential_sourced_to_owner_filter(self):
        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        with ExitStack() as stack:
            for p in _APPLY_PATCHES:
                # Skip the allow-all filter; use a rejecting one below.
                if "filter_bag_ids_for_operational_write" in str(p.attribute):
                    continue
                stack.enter_context(p)
            mock_filter = stack.enter_context(
                patch(
                    "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
                    return_value=(
                        {"VEEONLY1"},
                        [{"bag_id": "DVE92G8WAL", "reason": "operational_owner_mismatch"}],
                    ),
                )
            )
            stats = apply_presence_scrape(
                cursor,
                3,
                portal_status=PORTAL_STATUS_AT_VENDOR,
                rows=[
                    {"bag_id": "DVE92G8WAL", "customer_name": "X"},
                    {"bag_id": "VEEONLY1", "customer_name": "Y"},
                ],
                dry_run=False,
                mark_missing=False,
                run_type="manual",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                status="success",
            )
        mock_filter.assert_called_once()
        assert mock_filter.call_args.kwargs.get("credential_sourced") is True
        assert stats["rows_found"] == 1
        assert any(e.get("bag_id") == "DVE92G8WAL" for e in stats["errors"])
        assert stats["cross_org_presence_excluded"][0]["bag_id"] == "DVE92G8WAL"

    def test_apply_presence_scrape_accepts_washpro_owned_bag_via_credential(self):
        from backend.rinse_bag_operational_owner import (
            CanonicalOwner,
            SOURCE_CREDENTIAL,
            SOURCE_REGISTRY,
        )

        cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
        with ExitStack() as stack:
            for p in _APPLY_PATCHES:
                if "filter_bag_ids_for_operational_write" in str(p.attribute):
                    continue
                stack.enter_context(p)
            stack.enter_context(
                patch(
                    "backend.rinse_cleaner_ticket_presence.persist_presence_run_snapshot_rows",
                    return_value={"written": 1, "skipped_identical": 0, "identities": []},
                )
            )
            stack.enter_context(
                patch("backend.rinse_cleaner_ticket_presence.record_presence_scrape_run", return_value=99)
            )
            stack.enter_context(
                patch(
                    "backend.rinse_bag_operational_owner.operational_owner_gate_enabled",
                    return_value=True,
                )
            )
            mock_resolve = stack.enter_context(
                patch("backend.rinse_bag_operational_owner.resolve_canonical_owner")
            )
            mock_assign_cred = stack.enter_context(
                patch("backend.rinse_bag_operational_owner.assign_owner_from_credential")
            )
            mock_resolve.return_value = CanonicalOwner(
                bag_id="7AX67OZWFN",
                owner_organization_id=1,
                owner_rinse_vendor="washpro",
                assigned_at=datetime(2026, 6, 1),
                assignment_source=SOURCE_REGISTRY,
            )
            mock_assign_cred.return_value = CanonicalOwner(
                bag_id="7AX67OZWFN",
                owner_organization_id=3,
                owner_rinse_vendor="veewash",
                assigned_at=datetime(2026, 6, 16),
                assignment_source=SOURCE_CREDENTIAL,
            )
            stats = apply_presence_scrape(
                cursor,
                3,
                portal_status=PORTAL_STATUS_READY,
                rows=[
                    {
                        "bag_id": "7AX67OZWFN",
                        "customer_name": "Jeenie Yoon",
                        "service_type": "WF",
                    }
                ],
                dry_run=False,
                scrape_meta={"rinse_vendor": "veewash"},
            )
        assert stats["rows_found"] == 1
        assert not stats["errors"]
        mock_assign_cred.assert_called_once()


class TestParsePresenceEmptyCsv:
    def test_header_only_csv_returns_empty_rows(self, tmp_path):
        from backend.rinse_cleaner_ticket_presence import parse_presence_rows_from_portal_csv

        csv_path = tmp_path / "empty.csv"
        csv_path.write_text(
            "Date,Estd. Delivery,Customer,# WF LBS,# HD,# WF ITEMS,Weight,Notes,Special Instructions,"
            "USE OXIC,Use Hypo,USE FAB,Low DRY,NO SCEN,Extra Scen,Service Type,Sub-Service,Bag ID\n",
            encoding="utf-8",
        )
        assert parse_presence_rows_from_portal_csv(str(csv_path)) == []


class TestPortalCsvSpecialInstructions:
    def test_portal_csv_maps_supply_interpretation(self, tmp_path):
        from backend.rinse_portal_csv import portal_csv_to_orders_df

        csv_path = tmp_path / "portal.csv"
        csv_path.write_text(
            "Date,Customer,Weight,Notes,Bag ID,Service Type,Sub-Service,# WF LBS,# HD,# WF ITEMS,"
            "Special Instructions,USE OXIC,Use Hypo,USE FAB\n"
            "Mon 06/08/2026,Test Customer,10 LBS,,BAG123ABC,Wash & Fold,,10,,,"
            "USE FABRIC SOFTENER,,,X\n",
            encoding="utf-8",
        )
        df = portal_csv_to_orders_df(str(csv_path))
        assert len(df) == 1
        assert df.iloc[0]["supply_interpretation"] == "Soap + softener"
        assert not df.iloc[0]["special_instruction_review"]
