"""Day-scoped operational events: Francis attribution and wash/dry loads."""

from datetime import datetime

from backend.rinse_operational_day import build_operational_views
from backend.rinse_sorting_session import compute_sorting_session

DAY = datetime(2026, 9, 18).date()
NOW = datetime(2026, 9, 19, 15, 0)

FRANCIS = 16
HARRELL = 20
MALCOLM = 21
SINGH = 30


def _ev(bag, purpose, ts, user, rack=None):
    return {
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "rack": rack,
        "id": 1,
        "scan_index": 1,
    }


def _segments():
    return [
        {
            "user_id": FRANCIS,
            "display_name": "Francis",
            "role_code": "SORT",
            "category_code": "RINSE_WF",
            "started_at": datetime(2026, 9, 18, 5, 25, 31),
            "ended_at": datetime(2026, 9, 18, 13, 6, 20),
        },
        {
            "user_id": FRANCIS,
            "display_name": "Francis",
            "role_code": "OPERATOR",
            "category_code": "RINSE_WF",
            "started_at": datetime(2026, 9, 18, 13, 6, 20),
            "ended_at": datetime(2026, 9, 18, 13, 34, 27),
        },
        {
            "user_id": HARRELL,
            "display_name": "Harrell France",
            "role_code": "SORT",
            "category_code": "RINSE_WF",
            "started_at": datetime(2026, 9, 18, 14, 0, 0),
            "ended_at": datetime(2026, 9, 18, 18, 0, 0),
        },
        {
            "user_id": SINGH,
            "display_name": "Singh",
            "role_code": "OPERATOR",
            "category_code": "RINSE_WF",
            "started_at": datetime(2026, 9, 18, 8, 0, 0),
            "ended_at": datetime(2026, 9, 18, 16, 0, 0),
        },
    ]


def _names():
    return {
        "francis (veewash)": (FRANCIS, "Francis"),
        "francis": (FRANCIS, "Francis"),
        "harrell france": (HARRELL, "Harrell France"),
        "malcolm barbee": (MALCOLM, "Malcolm Barbee"),
        "singh": (SINGH, "Singh"),
    }


def test_francis_sort_is_morning_add_photos_not_later_workitems():
    events = [
        _ev("3NPDJ9G47S", "sent-to-vendor", datetime(2026, 9, 18, 5, 40), "Portal"),
        _ev("3NPDJ9G47S", "weight-entry", datetime(2026, 9, 18, 6, 10), "Francis (Veewash)", None),
        _ev("3NPDJ9G47S", "cleaning", datetime(2026, 9, 18, 6, 37), "Francis (Veewash)"),
        _ev("3NPDJ9G47S", "add-photos", datetime(2026, 9, 18, 6, 40), "Francis (Veewash)"),
        _ev("3NPDJ9G47S", "workitems-added", datetime(2026, 9, 18, 17, 39), "Harrell France"),
        _ev("BKRU6OAI9X", "workitems-added", datetime(2026, 9, 18, 17, 57), "Harrell France"),
        _ev("AQ9AT9DE14", "workitems-added", datetime(2026, 9, 18, 18, 14), "Harrell France"),
        _ev("B5Z6ASQJQE", "workitems-added", datetime(2026, 9, 18, 18, 17), "Malcolm Barbee"),
        _ev("2W1YTAU464", "workitems-added", datetime(2026, 9, 18, 18, 20), "Malcolm Barbee"),
    ]
    # Give the chain bags their own sort completion so they are real rows,
    # still not Francis.
    events.extend(
        [
            _ev("BKRU6OAI9X", "sent-to-vendor", datetime(2026, 9, 18, 14, 10), "Portal"),
            _ev("BKRU6OAI9X", "add-photos", datetime(2026, 9, 18, 15, 1), "Harrell France"),
        ]
    )
    views = build_operational_views(
        events=events,
        segments=_segments(),
        name_index=_names(),
        selected_date_et=DAY,
        now=NOW,
    )
    francis_sort = [r for r in views["sorting"] if r["employee"] == "Francis"]
    assert [r["bag_id"] for r in francis_sort] == ["3NPDJ9G47S"]
    assert francis_sort[0]["sort_time_et"] == datetime(2026, 9, 18, 6, 40)
    evening = datetime(2026, 9, 18, 13, 35)
    assert all(r["sort_time_et"] < evening for r in francis_sort)
    assert all(r["time_et"] < evening for r in views["weighing"] if r["employee"] == "Francis")
    for bag in ("3NPDJ9G47S", "BKRU6OAI9X", "AQ9AT9DE14", "B5Z6ASQJQE", "2W1YTAU464"):
        owned = [
            r
            for r in views["sorting"] + views["wash_dry"]
            if r["bag_id"] == bag and r.get("employee") == "Francis"
        ]
        assert all(
            (r.get("sort_time_et") or r.get("time_et") or r.get("timestamp_et")) < evening
            for r in owned
        )


def test_cross_user_workitems_do_not_extend_sort_end():
    anchor = datetime(2026, 9, 18, 5, 40)
    weight = _ev("3NPDJ9G47S", "weight-entry", datetime(2026, 9, 18, 6, 10), "Francis (Veewash)")
    photos = _ev("3NPDJ9G47S", "add-photos", datetime(2026, 9, 18, 6, 40), "Francis (Veewash)")
    later = _ev("3NPDJ9G47S", "workitems-added", datetime(2026, 9, 18, 17, 39), "Harrell France")
    timeline = [
        _ev("3NPDJ9G47S", "sent-to-vendor", anchor, "Portal"),
        weight,
        photos,
        later,
    ]
    session = compute_sorting_session(
        timeline,
        timeline,
        weight_ev=weight,
        weight_ts=weight["scanned_at_parsed"],
        add_photos_ev=photos,
    )
    assert session is not None
    assert session.sort_end_et != datetime(2026, 9, 18, 17, 39)
    assert session.end_event_purpose != "workitems-added"
    assert session.employee == "Francis (Veewash)"


def test_same_minute_different_racks_stay_separate_loads():
    minute = datetime(2026, 9, 18, 10, 15)
    events = [
        _ev("B5Z6ASQJQE", "start-cleaning", minute, "Singh", "W24-30-VW"),
        _ev("B5Z6ASQJQE", "start-cleaning", minute, "Singh", "W26-30-VW"),
        _ev("B5Z6ASQJQE", "drying", datetime(2026, 9, 18, 11, 0), "Singh", "D4-50-VW"),
        _ev("B5Z6ASQJQE", "drying", datetime(2026, 9, 18, 11, 0), "Singh", "D8-35-VW"),
    ]
    views = build_operational_views(
        events=events,
        segments=_segments(),
        name_index=_names(),
        selected_date_et=DAY,
        now=NOW,
    )
    assert len(views["washer_loads"]) == 2
    assert {r["washer_rack"] for r in views["washer_loads"]} == {"W24-30-VW", "W26-30-VW"}
    assert len({r["bag_id"] for r in views["washer_loads"]}) == 1
    assert len(views["dryer_loads"]) == 2
    assert len(views["wash_dry"]) == 2
    assert views["wash_dry"][0]["washer_rack"] != views["wash_dry"][1]["washer_rack"]


def test_neighbor_scan_does_not_assign_francis():
    events = [
        _ev("AQ9AT9DE14", "sent-to-vendor", datetime(2026, 9, 18, 16, 0), "Portal"),
        _ev("AQ9AT9DE14", "add-photos", datetime(2026, 9, 18, 17, 39), "Harrell France"),
    ]
    views = build_operational_views(
        events=events,
        segments=_segments(),
        name_index=_names(),
        selected_date_et=DAY,
        now=NOW,
    )
    assert all(r["employee"] != "Francis" for r in views["sorting"])
    assert views["sorting"][0]["employee"] == "Harrell France"
    assert views["sorting"][0]["sort_time_et"] == datetime(2026, 9, 18, 17, 39)
