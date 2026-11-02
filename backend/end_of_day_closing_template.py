"""Initial End of Day Closing checklist.

This is configuration data for the Task Management editor.
PIN, review, and dashboard read the saved Activity, not this module.
"""

from __future__ import annotations

from typing import Any


def _choice(field_id: str, label: str, options: list[tuple[str, str]], *, required: bool = True) -> dict[str, Any]:
    return {
        "id": field_id,
        "type": "choice",
        "label": label,
        "required": required,
        "options": [{"value": value, "label": text} for value, text in options],
    }


def _show(field_id: str, values: list[str]) -> dict[str, Any]:
    return {"field": field_id, "in": values}


def _item(
    code: str,
    name: str,
    section: str,
    section_order: int,
    instructions: str,
    *,
    schema: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "task_code": code,
        "task_name": name,
        "section_label": section,
        "section_order": section_order,
        "instructions": instructions,
        "required": True,
        "active": True,
        "responsibility_mode": "team",
        "responsibility_user_ids": [],
        "input_schema": schema or [],
    }


def _remarks(show_when: dict[str, Any], *, required: bool = False) -> dict[str, Any]:
    field: dict[str, Any] = {
        "id": "remarks",
        "type": "text",
        "label": "Remarks",
        "required": required,
        "show_when": show_when,
    }
    if required:
        field["required_when"] = show_when
    return field


_PASS_ISSUE = [("pass", "Pass"), ("issue", "Issue")]
_OK_LOW_OUT = [("ok", "OK"), ("low", "Low"), ("out", "Out")]


def end_of_day_closing_payload() -> dict[str, Any]:
    machines = "Machines"
    facility = "Facility Cleaning"
    organization = "Organization"
    supplies = "Equipment & Supplies"
    lost = "Lost & Found"
    pending = "Pending Orders"
    handover = "Handover"
    items = [
        _item(
            "eod_dryer_lint",
            "Clean dryer lint trays & gaskets",
            machines,
            10,
            "Remove lint from every dryer tray. Sweep a finger along the door gasket to remove trapped lint and debris.",
        ),
        _item(
            "eod_wipe_washers",
            "Wipe washers",
            machines,
            10,
            "Wipe washer exteriors, doors, gaskets, and detergent compartments.",
        ),
        _item(
            "eod_hot_water",
            "Hot-water cleaning cycle",
            machines,
            10,
            "Run a hot-water cleaning cycle where necessary. If Done, enter the washer machine number(s).",
            schema=[
                _choice("cycle", "Hot-water cleaning cycle", [("not_needed", "Not Needed"), ("done", "Done")]),
                {
                    "id": "machines",
                    "type": "machine_numbers",
                    "label": "Machine Number(s)",
                    "required": True,
                    "show_when": _show("cycle", ["done"]),
                    "required_when": _show("cycle", ["done"]),
                },
            ],
        ),
        _item(
            "eod_dehumidifiers",
            "Empty dehumidifiers",
            machines,
            10,
            "Empty all dehumidifier water buckets.",
        ),
        _item(
            "eod_ticket_holders",
            "Check magnetic ticket holders",
            machines,
            10,
            "Confirm every machine has its magnetic ticket holder.",
            schema=[
                _choice("result", "Check magnetic ticket holders", _PASS_ISSUE),
                _remarks(_show("result", ["issue"])),
            ],
        ),
        _item(
            "eod_machines_down",
            "New machines out of order?",
            machines,
            10,
            "If Yes, enter machine number(s) and describe the issue.",
            schema=[
                _choice("result", "New machines out of order?", [("no", "No"), ("yes", "Yes")]),
                {
                    "id": "machines",
                    "type": "machine_numbers",
                    "label": "Machine Number(s)",
                    "required": True,
                    "show_when": _show("result", ["yes"]),
                    "required_when": _show("result", ["yes"]),
                },
                {
                    "id": "issue",
                    "type": "text",
                    "label": "Issue Description",
                    "required": True,
                    "show_when": _show("result", ["yes"]),
                    "required_when": _show("result", ["yes"]),
                },
            ],
        ),
        _item(
            "eod_garbage",
            "Empty garbage & replace liners",
            facility,
            20,
            "Empty garbage and replace liners in restrooms, office, production floor, and break room.",
        ),
        _item(
            "eod_sweep",
            "Sweep floors",
            facility,
            20,
            "Sweep the production floor, including corners and accessible areas around equipment.",
        ),
        _item(
            "eod_mop",
            "Mop floors",
            facility,
            20,
            "Mop the production floor and address visible spills.",
        ),
        _item(
            "eod_restrooms",
            "Clean restrooms",
            facility,
            20,
            "Clean and sanitize restroom fixtures, surfaces, and floors.",
        ),
        _item(
            "eod_counters",
            "Wipe counters",
            facility,
            20,
            "Dust and wipe the counter and work surfaces.",
        ),
        _item(
            "eod_baker",
            "Organize Baker shelves",
            organization,
            30,
            "Organize the Baker shelves at the front.",
        ),
        _item(
            "eod_carts",
            "Organize carts",
            organization,
            30,
            "Arrange carts under folding stations and in the sorting area.",
        ),
        _item(
            "eod_caddy",
            "Clean detergent caddy",
            organization,
            30,
            "Clean the detergent caddy and remove residue.",
        ),
        _item(
            "eod_detergents",
            "Prepare detergents",
            organization,
            30,
            "Place Tide, Downy, and OxiClean on the caddy for the morning shift.",
        ),
        _item(
            "eod_test_ticket",
            "Print test ticket",
            supplies,
            40,
            "Print a test ticket and confirm it prints correctly.",
            schema=[
                _choice("result", "Print test ticket", _PASS_ISSUE),
                _remarks(_show("result", ["issue"])),
            ],
        ),
        _item(
            "eod_scale",
            "Check weighing scale",
            supplies,
            40,
            "Confirm the scale reads zero and is set to pounds (lb).",
            schema=[
                _choice("result", "Check weighing scale", _PASS_ISSUE),
                _remarks(_show("result", ["issue"])),
            ],
        ),
        _item(
            "eod_bags",
            "Check poly & orange bags",
            supplies,
            40,
            "Check that both types of bags are available.",
            schema=[
                _choice("poly", "Poly bags", _OK_LOW_OUT),
                _choice("orange", "Orange bags", _OK_LOW_OUT),
                {
                    "id": "remarks",
                    "type": "text",
                    "label": "Remarks",
                    "required": False,
                    "show_when": {
                        "any": [_show("poly", ["low", "out"]), _show("orange", ["low", "out"])]
                    },
                },
            ],
        ),
        _item(
            "eod_gloves",
            "Check gloves",
            supplies,
            40,
            "Check glove availability.",
            schema=[
                _choice("result", "Check gloves", _OK_LOW_OUT),
                _remarks({"any": [_show("result", ["low", "out"])]}),
            ],
        ),
        _item(
            "eod_lost_clear",
            "Clear today's Lost & Found",
            lost,
            50,
            "Document today's Rinse and drop-off found items, then place them in the designated secure location.",
            schema=[
                _choice("result", "Clear today's Lost & Found", [("done", "Done"), ("none", "None")]),
            ],
        ),
        _item(
            "eod_lost_count",
            "Lost & Found count",
            lost,
            50,
            "Enter the total number of items found today. Add photos when the count is greater than zero. Do not discard found items.",
            schema=[
                {
                    "id": "count",
                    "type": "number",
                    "label": "Lost & Found count",
                    "required": True,
                    "min": 0,
                },
                {
                    "id": "photos",
                    "type": "photo",
                    "label": "Lost & Found photos",
                    "required": False,
                    "show_when": {"field": "count", "gt": 0},
                    "required_when": {"field": "count", "gt": 0},
                },
            ],
        ),
        _item(
            "eod_wf_bags",
            "Unprocessed WF bags",
            pending,
            60,
            "Count all unprocessed Wash & Fold bags remaining at closing. This does not change customer orders.",
            schema=[{"id": "count", "type": "number", "label": "Unprocessed WF bags", "required": True, "min": 0}],
        ),
        _item(
            "eod_hd_bags",
            "Unprocessed HD bags",
            pending,
            60,
            "Count all unprocessed Hang Dry bags remaining at closing. This does not change customer orders.",
            schema=[{"id": "count", "type": "number", "label": "Unprocessed HD bags", "required": True, "min": 0}],
        ),
        _item(
            "eod_other_issues",
            "Other issues?",
            handover,
            70,
            "Report any unfinished work, equipment problems, or other issues for the next shift. Reporting an issue does not mark it resolved.",
            schema=[
                _choice("result", "Other issues?", [("no", "No"), ("yes", "Yes")]),
                {
                    "id": "remarks",
                    "type": "text",
                    "label": "Remarks",
                    "required": True,
                    "show_when": _show("result", ["yes"]),
                    "required_when": _show("result", ["yes"]),
                },
                {
                    "id": "photo",
                    "type": "photo",
                    "label": "Photo",
                    "required": False,
                    "show_when": _show("result", ["yes"]),
                },
            ],
        ),
    ]
    for index, item in enumerate(items):
        item["display_order"] = (index + 1) * 10
    return {
        "name": "End of Day Closing",
        "code": "end_of_day_closing",
        "category_code": "end_of_day",
        "instructions": "Complete facility cleaning, equipment checks, organization, and preparation for the next shift.",
        "active": True,
        "display_order": 30,
        "verification_inherits": False,
        "verification_required": True,
        "verification_method": "supervisor",
        "verification_timing": "same_shift",
        "require_checklist_before_completion": True,
        "items": items,
    }


# Routine washer, dryer, and floor cleaning now live on Intra-Day Activity Groups.
# This proposal is not loaded by the editor and is not saved as a live activity.
PROPOSED_REMOVED_ROUTINE_CODES = frozenset({"eod_dryer_lint", "eod_wipe_washers", "eod_sweep"})


def proposed_end_of_day_closing_payload() -> dict[str, Any]:
    payload = end_of_day_closing_payload()
    kept = [
        item
        for item in payload["items"]
        if item.get("task_code") not in PROPOSED_REMOVED_ROUTINE_CODES
    ]
    for index, item in enumerate(kept):
        item["display_order"] = (index + 1) * 10
    return {
        **payload,
        "instructions": (
            "Closing checks, supplies, lost and found, pending orders, and handover. "
            "Washer wiping, dryer lint, and floor sweeping are Intra-Day activities."
        ),
        "items": kept,
        "proposal_only": True,
        "removed_routine_codes": sorted(PROPOSED_REMOVED_ROUTINE_CODES),
    }
