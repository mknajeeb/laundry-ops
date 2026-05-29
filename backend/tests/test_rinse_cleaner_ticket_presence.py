"""Tests for rinse_cleaner_ticket_presence (portal ready_for_vendor / at_vendor)."""

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
            elif "INSERT INTO rinse_cleaner_ticket_presence" in s:
                org, bag_id = int(args[0]), str(args[1])
                store[(org, bag_id)] = {
                    "organization_id": org,
                    "bag_id": bag_id,
                    "portal_status": args[2],
                    "active": 1,
                    "source_batch_id": args[6],
                    "customer_name": args[7],
                }
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "portal_status" in s:
                org, bag_id = int(args[8]), str(args[9])
                key = (org, bag_id)
                if key in store:
                    store[key].update(
                        {
                            "portal_status": args[0],
                            "active": 1,
                            "source_batch_id": args[2],
                            "customer_name": args[3],
                        }
                    )
            elif "UPDATE rinse_cleaner_ticket_presence" in s and "active=0" in s:
                org, bag_id = int(args[1]), str(args[2])
                key = (org, bag_id)
                if key in store:
                    store[key]["active"] = 0
            elif "INSERT INTO rinse_cleaner_ticket_presence_runs" in s:
                pass

        cursor.execute.side_effect = execute
        cursor._store = store
        return cursor

    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_ready_for_vendor_inserted_per_org(self, _table_exists):
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

    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_at_vendor_updates_same_bag(self, _table_exists):
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

    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_transition_ready_to_at_vendor_flags(self, _table_exists):
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

    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_tenant_a_not_visible_for_tenant_b(self, _table_exists):
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

    @patch("backend.rinse_cleaner_ticket_presence.table_exists", return_value=True)
    def test_mark_missing_deactivates_absent_rows(self, _table_exists):
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


class TestLifecycleIntegration:
    def test_assigned_from_ready_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X1", ready_for_vendor_presence=True)
        assert out["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR

    def test_sent_to_vendor_from_at_vendor_presence(self):
        out = derive_bag_lifecycle_status([], bag_id="X2", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SENT_TO_VENDOR
