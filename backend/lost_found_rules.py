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


def validate_status_change(
    status: Any,
    *,
    order_reference: Any = None,
    comment: Any = None,
    reason: Any = None,
) -> dict[str, Any]:
    code = str(status or "").strip().lower()
    if code not in STATUSES:
        raise LostFoundError("Unknown Lost & Found status.", code="invalid_status")
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
    """Today's reports (any status) plus earlier unresolved items."""
    day = as_day(business_date)
    reported = as_day(item.get("business_date"))
    status = str(item.get("status") or "")
    if reported == day:
        return True
    return status in CARRY_FORWARD_STATUSES and reported < day


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
