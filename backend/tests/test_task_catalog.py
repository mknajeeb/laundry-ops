"""Task categories + definition config."""

from __future__ import annotations

from backend.task_catalog import (
    COMPLETION_INPUT,
    VERIFY_NONE,
    task_definition_from_role,
    validate_completion_input,
    TaskCatalogError,
)
import pytest


def test_task_definition_defaults_cleaning_to_intra_day():
    defn = task_definition_from_role(
        {
            "code": "floor_cleaning",
            "name": "Floor Cleaning",
            "uses_time_slots": False,
            "active": True,
        },
        categories_by_code={"intra_day": {"id": 2, "name": "Intra-Day", "code": "intra_day"}},
    )
    assert defn["category_code"] == "intra_day"
    assert defn["timer_enabled"] is True
    assert defn["verification_required"] is True
    assert defn["verification_method"] == "supervisor"


def test_no_verification_clears_required():
    defn = task_definition_from_role(
        {
            "code": "custom_supply_check",
            "name": "Supply Check",
            "task_category_code": "inventory",
            "verification_method": VERIFY_NONE,
            "verification_required": 1,
            "timer_enabled": 0,
            "completion_type": COMPLETION_INPUT,
            "input_schema_json": '[{"id":"qty","type":"number","label":"Qty","required":true}]',
        },
        categories_by_code={"inventory": {"id": 4, "name": "Inventory", "code": "inventory"}},
    )
    assert defn["verification_required"] is False
    assert defn["verification_method"] == VERIFY_NONE
    assert defn["timer_enabled"] is False
    assert defn["completion_type"] == COMPLETION_INPUT


def test_validate_completion_input_number():
    defn = {
        "completion_type": COMPLETION_INPUT,
        "input_schema": [{"id": "gallons", "type": "number", "label": "Gallons", "required": True}],
    }
    out = validate_completion_input(defn, {"values": {"gallons": "8"}})
    assert out["values"]["gallons"] == 8
    with pytest.raises(TaskCatalogError, match="Missing required"):
        validate_completion_input(defn, {"values": {}})
    zero = {
        "completion_type": COMPLETION_INPUT,
        "input_schema": [{"id": "count", "type": "number", "label": "Unprocessed WF bags", "required": True, "min": 0}],
    }
    assert validate_completion_input(zero, {"values": {"count": 0}})["values"]["count"] == 0
    with pytest.raises(TaskCatalogError, match="cannot be less than"):
        validate_completion_input(zero, {"values": {"count": -1}})


def test_conditional_machine_numbers_and_hidden_fields():
    defn = {
        "completion_type": COMPLETION_INPUT,
        "input_schema": [
            {
                "id": "result",
                "type": "choice",
                "label": "New machines out of order?",
                "required": True,
                "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes"}],
            },
            {
                "id": "machines",
                "type": "machine_numbers",
                "label": "Machine Number(s)",
                "required": True,
                "show_when": {"field": "result", "in": ["yes"]},
                "required_when": {"field": "result", "in": ["yes"]},
            },
            {
                "id": "issue",
                "type": "text",
                "label": "Issue Description",
                "required": True,
                "show_when": {"field": "result", "in": ["yes"]},
                "required_when": {"field": "result", "in": ["yes"]},
            },
        ],
    }
    quiet = validate_completion_input(defn, {"values": {"result": "no", "machines": "12"}})
    assert quiet["values"] == {"result": "no"}
    with pytest.raises(TaskCatalogError, match="Machine Number"):
        validate_completion_input(defn, {"values": {"result": "yes"}})
    done = validate_completion_input(
        defn, {"values": {"result": "yes", "machines": "08, 12, 08", "issue": "Not draining"}}
    )
    assert done["values"]["machines"] == ["08", "12"]
    assert done["values"]["issue"] == "Not draining"


def test_lost_and_found_photos_required_only_above_zero():
    defn = {
        "completion_type": COMPLETION_INPUT,
        "input_schema": [
            {"id": "count", "type": "number", "label": "Lost & Found count", "required": True, "min": 0},
            {
                "id": "photos",
                "type": "photo",
                "label": "Lost & Found photos",
                "required": False,
                "show_when": {"field": "count", "gt": 0},
                "required_when": {"field": "count", "gt": 0},
            },
        ],
    }
    assert validate_completion_input(defn, {"values": {"count": 0}})["values"]["count"] == 0
    with pytest.raises(TaskCatalogError, match="photos"):
        validate_completion_input(defn, {"values": {"count": 2}})
