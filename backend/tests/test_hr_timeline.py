"""Tests for HR Timeline discipline framework."""

from unittest.mock import MagicMock, patch

import pytest

from backend.hr_timeline import (
    create_discipline_email_timeline_entry,
    create_hr_timeline_entry,
    hr_timeline_meta,
    render_discipline_email_template,
)


def test_hr_timeline_meta_includes_management_note():
    meta = hr_timeline_meta()
    ids = [t["id"] for t in meta["entry_types"]]
    assert "management_note" in ids
    assert "offer_letter" in ids
    assert any(t["label"] == "Management Note" for t in meta["entry_types"])
    assert any(t["label"] == "Offer Letter" for t in meta["entry_types"])


def test_coaching_late_arrival_second_is_warning_not_separation():
    rendered = render_discipline_email_template(
        "coaching_late_arrival",
        worker_lane="employee_w2",
        fields={"worker_name": "Jane"},
    )
    body = rendered["body"].lower()
    assert "formal warning" in body
    assert "second late" in body
    assert "immediate separation" not in body
    assert rendered["entry_type"] == "coaching"


def test_warning_template_maps_to_warning_type():
    rendered = render_discipline_email_template(
        "warning_pattern_tardiness",
        worker_lane="employee_w2",
        fields={"worker_name": "Jane"},
    )
    assert rendered["entry_type"] == "warning"
    assert "formal warning" in rendered["body"].lower()


def test_contractor_wording_avoids_termination():
    rendered = render_discipline_email_template(
        "separation_attendance",
        worker_lane="contractor_1099",
        fields={"worker_name": "Alex", "issue_summary": "pattern of tardiness"},
    )
    body = rendered["body"].lower()
    assert "stopping future assignments" in body
    assert "termination" not in body
    assert "disciplinary action" not in body


def test_create_timeline_entry_management_note():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.lastrowid = 42
    with patch("backend.hr_timeline.table_exists", return_value=True), patch(
        "backend.hr_timeline.get_hr_timeline_entry",
        return_value={
            "id": 42,
            "entry_type": "management_note",
            "category": "General",
            "description": "Observed strong teamwork.",
            "entry_date": "2026-06-21",
        },
    ):
        row = create_hr_timeline_entry(
            conn,
            1,
            9,
            {
                "entry_type": "management_note",
                "category": "General",
                "description": "Observed strong teamwork.",
                "entry_date": "2026-06-21",
            },
            actor_id=3,
        )
    assert row["entry_type"] == "management_note"


def test_create_discipline_email_timeline_entry():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.lastrowid = 99
    with patch("backend.hr_timeline.table_exists", return_value=True), patch(
        "backend.hr_timeline.get_hr_timeline_entry",
        return_value={
            "id": 99,
            "entry_type": "coaching",
            "email_template_id": "coaching_late_arrival",
        },
    ):
        result = create_discipline_email_timeline_entry(
            conn,
            1,
            9,
            {"template_id": "coaching_late_arrival", "worker_lane": "employee_w2", "fields": {}},
            actor_id=3,
        )
    assert result["email"]["template_id"] == "coaching_late_arrival"
    assert result["entry"]["entry_type"] == "coaching"
