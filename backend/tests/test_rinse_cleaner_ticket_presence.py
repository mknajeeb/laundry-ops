"""Tests for rinse_cleaner_ticket_presence (portal ready_for_vendor / at_vendor)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    SENT_TO_VENDOR,
    derive_bag_lifecycle_status,
)
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    apply_presence_scrape,
    build_tickets_url_for_portal_status,
    get_presence_flags,
)


class TestTicketsUrlBuilder:
    def test_replaces_status_param(self):
        base = "https://www.rinse.com/cleanertickets/?status=at_vendor&page=1"
        url = build_tickets_url_for_portal_status(base, PORTAL_STATUS_READY)
        assert "status=ready_for_vendor" in url
        assert "status=at_vendor" not in url

    def test_adds_status_when_missing(self):
        url = build_tickets_url_for_portal_status(
            "https://www.rinse.com/cleanertickets/?page=1", PORTAL_STATUS_AT_VENDOR
        )
        assert "status=at_vendor" in url


class TestPresenceApplyDryRun:
    def _mock_cursor_with_table(self):
        cursor = MagicMock()
        store: dict[tuple[int, str], dict] = {}

        def execute(sql, args=None):
            s = " ".join(sql.split())
            if "CREATE TABLE" in s:
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
                pass
            elif "INSERT INTO rinse_cleaner_ticket_presence" in s:
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
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "portal_status" not in s:
                org, bag_id = int(args[7]), str(args[8])
                key = (org, bag_id)
                if key in store:
                    store[key]["last_seen_at"] = args[0]

        cursor.execute.side_effect = execute
        cursor._store = store
        return cursor

    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_ready_for_vendor_inserted_per_org(self, _table_exists, _transition_cols):
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
        assert cursor._store[(10, "BAG100")]["portal_status"] == PORTAL_STATUS_READY

    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_at_vendor_updates_same_bag(self, _table_exists, _transition_cols):
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

    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_transition_ready_to_at_vendor_flags(self, _table_exists, _transition_cols):
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

    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_tenant_a_not_visible_for_tenant_b(self, _table_exists, _transition_cols):
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

    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_mark_missing_deactivates_absent_rows(self, _table_exists, _transition_cols):
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
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_transition_columns")
    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    @patch("backend.rinse_cleaner_ticket_presence._utc_now")
    def test_transition_preserves_first_seen_and_sets_status_timestamps(self, mock_now, _table_exists, _transition_cols):
        from datetime import datetime

        t1 = datetime(2026, 5, 29, 9, 0, 0)
        t2 = datetime(2026, 5, 29, 10, 20, 0)
        mock_now.side_effect = [t1, t2]

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
        from backend.rinse_cleaner_ticket_presence import load_wf_presence_incoming_rows

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
            }
        ]
        with patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True):
            rows, meta = load_wf_presence_incoming_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
        assert len(rows) == 1
        assert rows[0]["ready_for_vendor_presence"] is True
        assert meta["wf_ready_for_vendor_presence"] == 1

    def test_hd_excluded(self):
        from datetime import date

        from backend.rinse_cleaner_ticket_presence import load_wf_presence_incoming_rows

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
            }
        ]
        with patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True):
            rows, meta = load_wf_presence_incoming_rows(
                cursor, 3, target_date=date(2026, 5, 31), exclude_bag_ids=set()
            )
        assert rows == []
        assert meta["hd_presence_excluded"] == 1


class TestLifecycleIntegration:
    def test_assigned_from_ready_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X1", ready_for_vendor_presence=True)
        assert out["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR

    def test_sent_to_vendor_from_at_vendor_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X2", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SENT_TO_VENDOR
