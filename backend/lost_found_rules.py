"""Pure Lost & Found rules.

Timestamps passed in here are naive America/New_York wall times, the same
clock used by task activities. Compare them only with each other.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

ACTIVITY_CODE = "custom_lost_found_reconciliation"
NOTIFY_EVENT_KEY = "lost_found.item_reported"

LOCATION_WASHER = "washer"
LOCATION_DRYER = "dryer"
LOCATION_FOLDING_TABLE = "folding_table"
LOCATION_FLOOR = "floor"
LOCATION_CART = "cart"
LOCATION_OTHER = "other"

LOCATION_KINDS = frozenset(
    {
        LOCATION_WASHER,
        LOCATION_DRYER,
        LOCATION_FOLDING_TABLE,
        LOCATION_FLOOR,
        LOCATION_CART,
        LOCATION_OTHER,
    }
)
NUMBER_REQUIRED = frozenset({LOCATION_WASHER, LOCATION_DRYER, LOCATION_FOLDING_TABLE})
NUMBER_OPTIONAL = frozenset({LOCATION_CART})

STATUS_NEW = "new"
STATUS_UNDER_REVIEW = "under_review"
STATUS_RETURNED = "returned"
STATUS_STORED = "stored"
STATUS_RESOLVED = "resolved"
STATUSES = frozenset(
    {STATUS_NEW, STATUS_UNDER_REVIEW, STATUS_RETURNED, STATUS_STORED, STATUS_RESOLVED}
)
CATEGORY_ORPHAN = "orphan"
CATEGORY_REDRY = "redry"
CATEGORY_EQUIPMENT = "equipment"
REPORT_CATEGORIES = frozenset({CATEGORY_ORPHAN, CATEGORY_REDRY, CATEGORY_EQUIPMENT})
REDRY_STATUSES = frozenset({STATUS_NEW, STATUS_UNDER_REVIEW, STATUS_RESOLVED})
EQUIPMENT_STATUSES = REDRY_STATUSES
EQUIPMENT_WASHER = "washer"
EQUIPMENT_DRYER = "dryer"
EQUIPMENT_DEHUMIDIFIER = "dehumidifier"
EQUIPMENT_OTHER = "other"
EQUIPMENT_TYPES = frozenset(
    {EQUIPMENT_WASHER, EQUIPMENT_DRYER, EQUIPMENT_DEHUMIDIFIER, EQUIPMENT_OTHER}
)
REDRY_FLAG_MISSING_TICKET = "missing_ticket"
REDRY_FLAG_MESH_BAG = "mesh_bag"
REDRY_FLAG_WRONG_POCKET = "wrong_pocket"
REDRY_FLAGS = (
    REDRY_FLAG_MISSING_TICKET,
    REDRY_FLAG_MESH_BAG,
    REDRY_FLAG_WRONG_POCKET,
)
CARRY_FORWARD_STATUSES = frozenset({STATUS_NEW, STATUS_UNDER_REVIEW, STATUS_STORED})

LOCATION_LABELS = {
    LOCATION_WASHER: "Washer",
    LOCATION_DRYER: "Dryer",
    LOCATION_FOLDING_TABLE: "Folding Table",
    LOCATION_FLOOR: "Floor",
    LOCATION_CART: "Cart",
    LOCATION_OTHER: "Other",
}


class LostFoundError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "invalid",
        blockers: Optional[list] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.blockers = blockers or []


def as_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, microsecond=0)
    text = str(value).strip().replace("T", " ")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def as_day(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def format_et_report(value: Any) -> str | None:
    """Operator display: ET primary, UTC clock in parentheses."""
    parsed = as_dt(value)
    if parsed is None:
        return None
    aware = parsed.replace(tzinfo=ET)
    utc = aware.astimezone(timezone.utc)
    return f"{parsed.strftime('%Y-%m-%d %H:%M:%S')} ET ({utc.strftime('%H:%M:%S')} UTC)"


def format_et_desktop(value: Any) -> str | None:
    """Desktop clock: Eastern wall time only. No UTC text."""
    parsed = as_dt(value)
    if parsed is None:
        return None
    hour = parsed.hour % 12 or 12
    suffix = "AM" if parsed.hour < 12 else "PM"
    return f"{parsed.strftime('%Y-%m-%d')} {hour}:{parsed.strftime('%M')} {suffix} ET"


def et_calendar_date(value: datetime) -> date:
    """Eastern calendar day for an aware instant. Naive values are ET wall times."""
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(ET).date()


def machine_token(raw: Any) -> str:
    """Compare W12, D12, and 12 as the same employee-facing number."""
    token = _clean_token(raw, limit=40)
    if len(token) >= 2 and token[0].upper() in {"W", "D", "F"} and token[1:].isdigit():
        return str(int(token[1:]))
    if token.isdigit():
        return str(int(token))
    return token


def _clean_token(raw: Any, *, limit: int) -> str:
    return " ".join(str(raw or "").split())[:limit]


def validate_location(kind: Any, number: Any = None, detail: Any = None) -> dict[str, Any]:
    """Exact location saved with the original report."""
    code = str(kind or "").strip().lower()
    if code not in LOCATION_KINDS:
        raise LostFoundError("Choose where the item was found.", code="invalid_location")
    token = _clean_token(number, limit=40)
    note = _clean_token(detail, limit=160)
    if code in NUMBER_REQUIRED and not token:
        label = LOCATION_LABELS[code]
        raise LostFoundError(f"{label} number is required.", code="location_number_required")
    if code == LOCATION_OTHER and len(note) < 2:
        raise LostFoundError(
            "Describe the location in a few words.",
            code="location_detail_required",
        )
    if code not in NUMBER_REQUIRED | NUMBER_OPTIONAL:
        token = ""
    if code != LOCATION_OTHER:
        note = ""
    title = LOCATION_LABELS[code]
    if code == LOCATION_OTHER:
        label = note
    elif token:
        label = f"{title} {token}"
    else:
        label = title
    return {
        "location_kind": code,
        "location_number": token or None,
        "location_detail": note or None,
        "location_label": label[:200],
    }


def _as_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def report_category_of(item: Mapping[str, Any] | None) -> str:
    code = str((item or {}).get("report_category") or CATEGORY_ORPHAN).strip().lower()
    return code if code in REPORT_CATEGORIES else CATEGORY_ORPHAN


def matched_identifier(token: str, allowed: Sequence[Any] | None, *, code: str) -> str:
    """Return the configured number, matching a bare number to a stored prefix.

    An empty list means this organization has not published numbers, so the
    submitted text is kept.
    """
    cleaned = _clean_token(token, limit=40)
    choices = []
    for value in allowed or []:
        choice = _clean_token(value, limit=40)
        if choice and choice not in choices:
            choices.append(choice)
    if not choices:
        return cleaned
    wanted = machine_token(cleaned)
    for choice in choices:
        if cleaned == choice or machine_token(choice) == wanted:
            return choice
    raise LostFoundError("Choose one of the configured numbers.", code=code)


def require_configured_identifier(token: str, allowed: Sequence[Any] | None, *, code: str) -> None:
    """Restrict a number only when this organization published a list."""
    matched_identifier(token, allowed, code=code)


def validate_redry(
    flags: Mapping[str, Any] | None,
    pocket: Any,
    *,
    bag_number: Any = None,
    allowed_pockets: Sequence[Any] | None = None,
    allowed_dryers: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """A Re-Dry report carries exactly one reason.

    Older rows may still store more than one flag. This check applies to
    new submissions only. A mesh bag number is never required. Wrong-pocket
    reports must use a manager-designated pocket when that list exists.
    """
    selected = {name: _as_flag((flags or {}).get(name)) for name in REDRY_FLAGS}
    chosen = [name for name, on in selected.items() if on]
    if not chosen:
        raise LostFoundError(
            "Select one Re-Dry reason.",
            code="redry_flag_required",
        )
    if len(chosen) != 1:
        raise LostFoundError(
            "Select only one Re-Dry reason.",
            code="redry_one_reason",
        )
    bag = _clean_token(bag_number, limit=40)
    if selected[REDRY_FLAG_WRONG_POCKET]:
        token = _clean_token(pocket, limit=40)
        if not token:
            raise LostFoundError("Dryer number is required.", code="location_number_required")
        if allowed_pockets:
            token = matched_identifier(token, allowed_pockets, code="pocket_not_designated")
        elif allowed_dryers:
            token = matched_identifier(token, allowed_dryers, code="identifier_not_configured")
        location = validate_location(LOCATION_DRYER, token, None)
    else:
        location = {
            "location_kind": LOCATION_DRYER,
            "location_number": None,
            "location_detail": None,
            "location_label": "Re-Dry",
        }
    location["location_detail"] = bag or None
    location["redry_bag_number"] = bag or None
    return {**selected, **location}


def validate_equipment(
    kind: Any,
    identifier: Any = None,
    detail: Any = None,
    *,
    allowed: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """A malfunction report. Not a physical Lost & Found item."""
    code = str(kind or "").strip().lower()
    if code not in EQUIPMENT_TYPES:
        raise LostFoundError("Choose the equipment type.", code="invalid_equipment")
    token = _clean_token(identifier, limit=40)
    note = _clean_token(detail, limit=160)
    if code == EQUIPMENT_OTHER:
        if len(note) < 2:
            raise LostFoundError("Name the equipment in a few words.", code="equipment_name_required")
    elif not token:
        raise LostFoundError("An equipment number is required.", code="identifier_required")
    if token and allowed:
        token = matched_identifier(token, allowed, code="identifier_not_configured")
    titles = {
        EQUIPMENT_WASHER: "Washer",
        EQUIPMENT_DRYER: "Dryer",
        EQUIPMENT_DEHUMIDIFIER: "Dehumidifier",
        EQUIPMENT_OTHER: note or "Other",
    }
    title = titles[code]
    if code == EQUIPMENT_OTHER:
        label = f"{note} {token}".strip() if token else note
    elif token:
        label = f"{title} {token}"
    else:
        label = title
    return {
        "location_kind": code,
        "location_number": token or None,
        "location_detail": note or None,
        "location_label": label[:200],
        "missing_ticket": False,
        "mesh_bag": False,
        "wrong_pocket": False,
    }


def validate_status_change(
    status: Any,
    *,
    order_reference: Any = None,
    comment: Any = None,
    reason: Any = None,
    report_category: str = CATEGORY_ORPHAN,
) -> dict[str, Any]:
    code = str(status or "").strip().lower()
    category = report_category if report_category in REPORT_CATEGORIES else CATEGORY_ORPHAN
    if category == CATEGORY_REDRY:
        allowed = REDRY_STATUSES
    elif category == CATEGORY_EQUIPMENT:
        allowed = EQUIPMENT_STATUSES
    else:
        allowed = STATUSES
    if code not in allowed:
        raise LostFoundError("That status is not used for this report.", code="invalid_status")
    order_ref = _clean_token(order_reference, limit=80)
    note = _clean_token(comment, limit=1000)
    why = _clean_token(reason, limit=500)
    if code == STATUS_RETURNED:
        if not order_ref:
            raise LostFoundError(
                "An order reference is required when marking Returned.",
                code="order_reference_required",
            )
        if len(note) < 2:
            raise LostFoundError(
                "A comment is required when marking Returned.",
                code="comment_required",
            )
    if code == STATUS_RESOLVED and len(why) < 3:
        raise LostFoundError(
            "A reason is required when marking Resolved.",
            code="reason_required",
        )
    if code != STATUS_RETURNED:
        order_ref = order_ref or ""
    if code != STATUS_RESOLVED:
        why = "" if code != STATUS_RESOLVED else why
    return {
        "status": code,
        "order_reference": order_ref or None,
        "status_comment": note or None,
        "resolved_reason": why or None,
    }


def item_in_reconciliation_scope(item: Mapping[str, Any], business_date: Any) -> bool:
    """Today's orphan reports plus earlier unresolved orphan items.

    Re-Dry reports are operational violations, not physical Lost & Found items.
    """
    if report_category_of(item) in {CATEGORY_REDRY, CATEGORY_EQUIPMENT}:
        return False
    day = as_day(business_date)
    reported = as_day(item.get("business_date"))
    status = str(item.get("status") or "")
    if reported == day:
        return True
    return status in CARRY_FORWARD_STATUSES and reported < day


def item_in_redry_scope(item: Mapping[str, Any], business_date: Any) -> bool:
    """Today's Re-Dry reports, plus older ones that are not yet resolved."""
    if report_category_of(item) != CATEGORY_REDRY:
        return False
    day = as_day(business_date)
    reported = as_day(item.get("business_date"))
    status = str(item.get("status") or "")
    if reported == day:
        return True
    return status != STATUS_RESOLVED and reported < day


def item_in_equipment_scope(item: Mapping[str, Any], business_date: Any) -> bool:
    """Today's equipment reports, plus older ones still open. Not a Lost & Found blocker."""
    if report_category_of(item) != CATEGORY_EQUIPMENT:
        return False
    day = as_day(business_date)
    reported = as_day(item.get("business_date"))
    status = str(item.get("status") or "")
    if reported == day:
        return True
    return status != STATUS_RESOLVED and reported < day


def item_in_completion_scope(item: Mapping[str, Any], business_date: Any) -> bool:
    """Orphan reconciliation plus today's Re-Dry reports. Older Re-Dry stays visible only."""
    if item_in_reconciliation_scope(item, business_date):
        return True
    return report_category_of(item) == CATEGORY_REDRY and as_day(item.get("business_date")) == as_day(
        business_date
    )


def select_reconciliation_items(
    items: Sequence[Mapping[str, Any]],
    business_date: Any,
) -> list[Mapping[str, Any]]:
    return [item for item in items if item_in_reconciliation_scope(item, business_date)]


def reconciliation_blockers(
    items: Sequence[Mapping[str, Any]],
    accounts_by_item: Mapping[Any, Mapping[str, Any]],
    *,
    box_photo: Mapping[str, Any] | None,
    started_at: Any,
) -> list[dict[str, Any]]:
    """Each in-scope report must be confirmed or escalated. Stored items need a box photo."""
    blockers: list[dict[str, Any]] = []
    start = as_dt(started_at)
    stored_changes: list[datetime] = []
    has_stored = False
    for item in items:
        item_id = item.get("id")
        label = str(item.get("location_label") or f"Item {item_id}")
        account = accounts_by_item.get(item_id) or accounts_by_item.get(str(item_id))
        revision = int(item.get("revision") or 1)
        reported = as_dt(item.get("reported_at"))
        if not account or int(account.get("revision") or 0) != revision:
            blockers.append(
                {
                    "code": "unaccounted",
                    "item_id": item_id,
                    "message": f"Account for {label} or escalate it before finishing.",
                }
            )
        elif start is not None and reported is not None and reported > start:
            accounted = as_dt(account.get("accounted_at"))
            if accounted is None or accounted < reported:
                blockers.append(
                    {
                        "code": "unaccounted",
                        "item_id": item_id,
                        "message": f"{label} was reported after reconciliation started and still needs to be included.",
                    }
                )
        if str(item.get("status") or "") == STATUS_STORED:
            has_stored = True
            changed = as_dt(item.get("status_changed_at")) or reported
            if changed is not None:
                stored_changes.append(changed)
    if has_stored:
        latest = max(stored_changes) if stored_changes else None
        captured = as_dt((box_photo or {}).get("captured_at")) if box_photo else None
        if box_photo is None or captured is None:
            blockers.append(
                {
                    "code": "box_photo_required",
                    "item_id": None,
                    "message": "Take a photo of the items placed in the Lost & Found box.",
                }
            )
        elif latest is not None and captured < latest:
            blockers.append(
                {
                    "code": "box_photo_stale",
                    "item_id": None,
                    "message": "Take a new Lost & Found box photo after the latest stored item.",
                }
            )
    return blockers


def snapshot_is_current(
    snapshot: Mapping[str, Any] | None,
    items: Sequence[Mapping[str, Any]],
    *,
    box_photo_id: Any,
) -> list[dict[str, Any]]:
    """Approval stays blocked when a report arrives or changes after the snapshot."""
    if not snapshot:
        return [
            {
                "code": "snapshot_missing",
                "item_id": None,
                "message": "Lost & Found reconciliation has no snapshot yet.",
            }
        ]
    saved = {
        int(row.get("id")): int(row.get("revision") or 0)
        for row in (snapshot.get("items") or [])
        if row.get("id") is not None
    }
    blockers: list[dict[str, Any]] = []
    live_ids: set[int] = set()
    stored = False
    for item in items:
        item_id = int(item["id"])
        live_ids.add(item_id)
        revision = int(item.get("revision") or 1)
        if saved.get(item_id) != revision:
            blockers.append(
                {
                    "code": "snapshot_stale",
                    "item_id": item_id,
                    "message": "A found item changed after this reconciliation was submitted. Reject it so the closing employee can include the update.",
                }
            )
        if str(item.get("status") or "") == STATUS_STORED:
            stored = True
    for saved_id in saved:
        if saved_id not in live_ids:
            blockers.append(
                {
                    "code": "snapshot_stale",
                    "item_id": saved_id,
                    "message": "The reconciliation snapshot no longer matches the found items for this day.",
                }
            )
    if stored:
        current_photo = int(box_photo_id) if box_photo_id not in (None, "") else None
        saved_photo = snapshot.get("box_photo_id")
        saved_photo = int(saved_photo) if saved_photo not in (None, "") else None
        if current_photo is None or current_photo != saved_photo:
            blockers.append(
                {
                    "code": "box_photo_stale",
                    "item_id": None,
                    "message": "The Lost & Found box photo changed after submission.",
                }
            )
    return blockers
