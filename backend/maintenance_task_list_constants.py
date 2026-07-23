"""Constants and default seed for Maintenance Task List."""

from __future__ import annotations

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
# Legacy alias — treat as completed when reading older rows.
STATUS_SUBMITTED = "submitted"
STATUS_NOT_STARTED = "not_started"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_SUBMITTED})

FREQUENCY_DAILY = "daily"
FREQUENCY_WEEKLY = "weekly"
FREQUENCY_AS_NEEDED = "as_needed"

FREQUENCIES = frozenset({FREQUENCY_DAILY, FREQUENCY_WEEKLY, FREQUENCY_AS_NEEDED})

# Actions recorded on maintenance_task_list_events (+ mirrored to audit_log when available).
EVENT_LIST_CREATED = "list_created"
EVENT_TASK_CHECKED = "task_checked"
EVENT_TASK_UNCHECKED = "task_unchecked"
EVENT_PROGRESS_SAVED = "progress_saved"
EVENT_LIST_SUBMITTED = "list_submitted"
EVENT_LIST_REOPENED = "list_reopened"
EVENT_MANAGER_CORRECTION = "manager_correction"
EVENT_NOTES_CHANGED = "notes_changed"
EVENT_DEFINITION_CREATED = "definition_created"
EVENT_DEFINITION_UPDATED = "definition_updated"
EVENT_DEFINITION_REORDERED = "definition_reordered"

PIN_SESSION_SALT = "maintenance-task-list-pin"
PIN_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60

DEFAULT_TASK_DEFINITIONS = (
    {
        "task_key": "empty_dehumidifier_buckets",
        "name": "Empty dehumidifier buckets",
        "description": "Empty water from all dehumidifier buckets.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 10,
    },
    {
        "task_key": "empty_ac_water_bucket",
        "name": "Empty A/C water bucket",
        "description": "Empty the air conditioner water collection bucket.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 20,
    },
    {
        "task_key": "clean_lint_trays",
        "name": "Clean lint trays on all dryers",
        "description": "Clean lint trays on every dryer.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 30,
    },
    {
        "task_key": "cash_up_register",
        "name": "Cash up register",
        "description": "Cash up the front register.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 40,
    },
    {
        "task_key": "ensure_washers_dryers_empty",
        "name": "Ensure all washers and dryers are empty",
        "description": "Confirm every washer and dryer is empty.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 50,
    },
    {
        "task_key": "move_unfolded_orders_to_office",
        "name": "Move all unfolded orders to the office area",
        "description": "Move remaining unfolded orders to the office area.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 60,
    },
    {
        "task_key": "dropoff_bag_images_whatsapp",
        "name": "Ensure all Drop-Off bag images are sent on WhatsApp",
        "description": "Confirm Drop-Off bag images were sent on WhatsApp.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 70,
    },
    {
        "task_key": "dhs_volume_sheet_whatsapp",
        "name": "Ensure the DHS volume sheet is sent on WhatsApp",
        "description": "Confirm the DHS volume sheet was sent on WhatsApp.",
        "frequency": FREQUENCY_DAILY,
        "is_required": True,
        "require_note_if_incomplete": True,
        "display_order": 80,
    },
)
