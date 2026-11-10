"""The supervisor register reads both issue stores without merging them."""

from backend.issues_register import compose_register, status_group


def test_employee_and_customer_issues_stay_distinct_and_count_together():
    payload = compose_register(
        [
            {
                "id": 4,
                "issue_category": "MISSING",
                "issue_subtype": "BAG",
                "status": "open",
                "reported_at_et": "2026-11-10 09:00:00",
                "customer_name_snapshot": "Ada Lovelace",
                "bag_id": "B1",
                "primary_employee_name": "Alex",
                "description": "Bag missing",
            }
        ],
        [
            {
                "id": 6,
                "report_category": "orphan",
                "status": "new",
                "reported_at_display": "2026-11-10 11:15:00 ET",
                "business_date": "2026-11-10",
                "employee_name": "Sarah Kamran",
                "location_label": "Floor",
                "notes": "blue shirt",
                "photos": [{"id": 1}],
            }
        ],
    )
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["open"] == 2
    assert payload["summary"]["by_source"] == {"rinse": 1, "employee": 1}
    keys = [row["key"] for row in payload["rows"]]
    assert keys == ["employee:6", "rinse:4"]
    employee = payload["rows"][0]
    assert employee["photo_count"] == 1
    assert employee["category_label"] == "Found Item"


def test_status_card_counts_ignore_the_status_filter():
    payload = compose_register(
        [{"id": 1, "issue_category": "DAMAGE", "status": "resolved", "reported_at_et": "2026-11-09 08:00:00"}],
        [
            {"id": 2, "report_category": "redry", "status": "under_review", "reported_at": "2026-11-10 08:00:00", "redry_flags": {"mesh_bag": True}},
            {"id": 3, "report_category": "equipment", "status": "new", "reported_at": "2026-11-10 07:00:00"},
        ],
        status_group_filter="open",
    )
    assert payload["total"] == 1
    assert payload["rows"][0]["category"] == "equipment"
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["open"] == 1
    assert payload["summary"]["review"] == 1
    assert payload["summary"]["resolved"] == 1


def test_source_and_search_filters_do_not_mix_records():
    payload = compose_register(
        [{"id": 9, "issue_category": "FOUND", "status": "investigating", "customer_name_snapshot": "North", "reported_at_et": "2026-11-10 01:00:00"}],
        [{"id": 8, "report_category": "equipment", "status": "new", "location_label": "Washer 4", "notes": "North", "reported_at": "2026-11-10 02:00:00"}],
        source="employee",
        q="washer",
    )
    assert payload["total"] == 1
    assert payload["rows"][0]["key"] == "employee:8"
    assert status_group("rinse", "investigating") == "review"
    assert status_group("employee", "stored") == "resolved"
