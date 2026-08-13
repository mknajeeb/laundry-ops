"""Tests for Folder scan chronology (one session per bag cycle)."""

from datetime import date, datetime

from backend.rinse_folder_chronology import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_MISSING_START,
    STATUS_INCOMPLETE_OPEN,
    build_folder_chronology_summary,
    extract_folder_session_for_bag,
    is_folder_start_event,
)
from backend.rinse_scan_chronology import (
    DURATION_STAGES,
    VALID_STAGES,
    merge_stage_sessions_to_activities,
)


def _ev(purpose, at, *, rack="", scan_index=1, ev_id=1, user="Folder Emp", weight_lbs=None):
    row = {
        "id": ev_id,
        "bag_id": "BAG1",
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }
    if weight_lbs is not None:
        row["weight_lbs"] = weight_lbs
    return row


class TestFolderStartContract:
    def test_complete_cleaning_on_folding_is_start(self):
        assert is_folder_start_event(
            _ev("complete-cleaning", datetime(2026, 8, 13, 8, 2), rack="Folding-4-VW")
        )

    def test_complete_cleaning_on_dryer_is_not_start(self):
        assert not is_folder_start_event(
            _ev("complete-cleaning", datetime(2026, 8, 13, 8, 2), rack="D6-30-VW")
        )

    def test_drying_on_folding_is_not_start(self):
        assert not is_folder_start_event(
            _ev("drying", datetime(2026, 8, 13, 8, 5), rack="Folding-8-VW")
        )

    def test_garments_reviewed_is_start(self):
        assert is_folder_start_event(
            _ev("garments-reviewed", datetime(2026, 8, 13, 8, 5))
        )


class TestFolderSessionExtraction:
    def test_representative_evelin_sequence(self):
        # Mirrors 3H1SYUNX9J: CC@Folding → GR → AP → Clean
        events = [
            _ev("sent-to-vendor", datetime(2026, 8, 13, 0, 48), rack="VeeWash Dirty", ev_id=1),
            _ev("start-cleaning", datetime(2026, 8, 13, 6, 13), rack="W28-20-VW", user="Yessenia", ev_id=2),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 13, 8, 2),
                rack="Folding-4-VW",
                user="Evelin (VeeWash)",
                ev_id=3,
            ),
            _ev("garments-reviewed", datetime(2026, 8, 13, 8, 24), user="Evelin (VeeWash)", ev_id=4),
            _ev("assembly-printed-ct", datetime(2026, 8, 13, 8, 27), user="Evelin (VeeWash)", ev_id=5),
            _ev(
                "move-bag Last Scan",
                datetime(2026, 8, 13, 8, 28),
                rack="VeeWash Clean",
                user="Evelin (VeeWash)",
                ev_id=6,
            ),
            _ev(
                "weight-entry",
                datetime(2026, 8, 13, 8, 28),
                user="Evelin (VeeWash)",
                ev_id=7,
                weight_lbs=17.2,
            ),
        ]
        sess = extract_folder_session_for_bag(
            "3H1SYUNX9J", events, selected_date_et=date(2026, 8, 13)
        )
        assert sess is not None
        assert sess["status"] == STATUS_COMPLETE
        assert sess["employee"] == "Evelin (VeeWash)"
        assert sess["folder_start_et"] == datetime(2026, 8, 13, 8, 2)
        assert sess["folder_end_et"] == datetime(2026, 8, 13, 8, 28)
        assert sess["duration_seconds"] == 26 * 60
        assert sess["weight_lbs"] == 17.2
        assert sess["start_event_purpose"] == "complete-cleaning"
        assert "clean" in (sess["end_rack"] or "").lower()

    def test_amna_gr_and_cc_same_minute_one_session(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 8, 13, 0, 47), rack="VeeWash Dirty", ev_id=1),
            _ev("garments-reviewed", datetime(2026, 8, 13, 8, 5), user="Amna (Veewash)", ev_id=2, scan_index=1),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 13, 8, 5),
                rack="Folding-8-VW",
                user="Amna (Veewash)",
                ev_id=3,
                scan_index=2,
            ),
            _ev(
                "drying",
                datetime(2026, 8, 13, 8, 5),
                rack="Folding-8-VW",
                user="Amna (Veewash)",
                ev_id=4,
                scan_index=3,
            ),
            _ev("assembly-printed-ct", datetime(2026, 8, 13, 8, 27), user="Amna (Veewash)", ev_id=5),
            _ev(
                "move-bag Last Scan",
                datetime(2026, 8, 13, 8, 28),
                rack="VeeWash Clean",
                user="Amna (Veewash)",
                ev_id=6,
            ),
        ]
        sess = extract_folder_session_for_bag(
            "3UI1I9GUEC", events, selected_date_et=date(2026, 8, 13)
        )
        assert sess["status"] == STATUS_COMPLETE
        assert sess["employee"] == "Amna (Veewash)"
        # Earliest start marker (garments-reviewed before CC by scan_index/id)
        assert sess["folder_start_et"] == datetime(2026, 8, 13, 8, 5)
        assert sess["start_event_purpose"] == "garments-reviewed"
        assert sess["folder_end_et"] == datetime(2026, 8, 13, 8, 28)

    def test_open_session_without_clean(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 8, 13, 1, 0), rack="VeeWash Dirty", ev_id=1),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 13, 9, 0),
                rack="Folding-4-VW",
                user="Tarannum (Veewash)",
                ev_id=2,
            ),
        ]
        sess = extract_folder_session_for_bag("OPEN1", events, selected_date_et=date(2026, 8, 13))
        assert sess["status"] == STATUS_INCOMPLETE_OPEN
        assert sess["folder_end_et"] is None
        assert sess["employee"] == "Tarannum (Veewash)"
        assert sess["duration_seconds"] is None

    def test_missing_start_keeps_clean_end(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 8, 13, 1, 0), rack="VeeWash Dirty", ev_id=1),
            _ev(
                "move-bag",
                datetime(2026, 8, 13, 10, 0),
                rack="VeeWash Clean",
                user="Jennifer (VeeWash)",
                ev_id=2,
            ),
        ]
        sess = extract_folder_session_for_bag("MISS1", events, selected_date_et=date(2026, 8, 13))
        assert sess["status"] == STATUS_INCOMPLETE_MISSING_START
        assert sess["folder_start_et"] is None
        assert sess["folder_end_et"] == datetime(2026, 8, 13, 10, 0)
        assert sess["employee"] == "Jennifer (VeeWash)"

    def test_prior_cycle_clean_does_not_contaminate(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 8, 10, 8, 0), rack="VeeWash Dirty", ev_id=1),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 10, 12, 0),
                rack="Folding-4-VW",
                user="Old",
                ev_id=2,
            ),
            _ev("move-bag", datetime(2026, 8, 10, 12, 30), rack="VeeWash Clean", user="Old", ev_id=3),
            _ev("sent-to-vendor", datetime(2026, 8, 13, 1, 0), rack="VeeWash Dirty", ev_id=4),
            _ev(
                "complete-cleaning",
                datetime(2026, 8, 13, 9, 0),
                rack="Folding-8-VW",
                user="Amna (Veewash)",
                ev_id=5,
            ),
            _ev(
                "move-bag",
                datetime(2026, 8, 13, 9, 20),
                rack="VeeWash Clean",
                user="Amna (Veewash)",
                ev_id=6,
            ),
        ]
        sess = extract_folder_session_for_bag("CYCLE", events, selected_date_et=date(2026, 8, 13))
        assert sess["employee"] == "Amna (Veewash)"
        assert sess["folder_start_et"] == datetime(2026, 8, 13, 9, 0)
        assert sess["folder_end_et"] == datetime(2026, 8, 13, 9, 20)

    def test_summary_counts(self):
        rows = [
            {
                "folder_start_et": datetime(2026, 8, 13, 8, 0),
                "folder_end_et": datetime(2026, 8, 13, 8, 20),
                "duration_seconds": 1200,
                "status": STATUS_COMPLETE,
                "gap_until_next_seconds": 60,
            },
            {
                "folder_start_et": datetime(2026, 8, 13, 9, 0),
                "folder_end_et": None,
                "duration_seconds": None,
                "status": STATUS_INCOMPLETE_OPEN,
                "gap_until_next_seconds": None,
            },
        ]
        summary = build_folder_chronology_summary(rows)
        assert summary["total_sessions"] == 2
        assert summary["complete_sessions"] == 1
        assert summary["incomplete_sessions"] == 1
        assert summary["total_folder_seconds"] == 1200


class TestFolderWiredIntoScanChronology:
    def test_folder_is_valid_duration_stage(self):
        assert "folder" in VALID_STAGES
        assert "folder" in DURATION_STAGES

    def test_user_activity_merges_folder(self):
        activities = merge_stage_sessions_to_activities(
            folder_sessions=[
                {
                    "start_et": datetime(2026, 8, 13, 8, 2),
                    "end_et": datetime(2026, 8, 13, 8, 28),
                    "duration_seconds": 1560,
                    "bag_id": "3H1SYUNX9J",
                    "employee": "Evelin (VeeWash)",
                    "confidence": "exact",
                    "source": "complete-cleaning@Folding-4-VW → move-bag@VeeWash Clean",
                    "status": "complete",
                    "start_event_purpose": "complete-cleaning",
                    "end_event_purpose": "move-bag",
                    "end_rack": "VeeWash Clean",
                }
            ],
        )
        assert len(activities) == 1
        assert activities[0]["activity_type"] == "folder"
        assert activities[0]["activity_label"] == "Folder"
        assert activities[0]["bag_id"] == "3H1SYUNX9J"
