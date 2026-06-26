"""
Rinse bag completion from scan-events.

Business rule: COMPLETED when any scan-event rack contains "Clean" (first such scan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

INTERNAL_USER_TERMS: tuple[str, ...] = (
    "training account",
    "staff",
    "veewash",
    "washpro",
)

COMPLETION_INCOMPLETE = "INCOMPLETE"
COMPLETION_COMPLETED = "COMPLETED"
COMPLETION_REJECTED = "REJECTED"

REASON_NO_CLEAN_SCAN = "NO_CLEAN_SCAN"
REASON_CLEAN_RACK_SCANNED = "CLEAN_RACK_SCANNED"
TRIGGER_CLEAN_RACK = "CLEAN_RACK"

# Legacy registry / upload reasons (older rows)
REASON_POST_CLEAN_RACK_AND_USER = "POST_CLEAN_RACK_AND_USER"
REASON_CLEAN_WITHOUT_QUALIFYING_LATER = "CLEAN_WITHOUT_QUALIFYING_LATER_SCAN"
REASON_WORKFLOW_THEN_CLEAN = REASON_POST_CLEAN_RACK_AND_USER
REASON_CLEAN_WITHOUT_PRIOR_WORKFLOW = REASON_CLEAN_WITHOUT_QUALIFYING_LATER
REASON_POST_CLEAN_ONLY_INTERNAL_ON_CLEAN_RACK = REASON_CLEAN_WITHOUT_QUALIFYING_LATER
REASON_POST_CLEAN_RACK_OR_USER = REASON_POST_CLEAN_RACK_AND_USER
TRIGGER_RACK_NOT_CLEAN = "RACK_NOT_CLEAN"
TRIGGER_USER_NOT_INTERNAL = "USER_NOT_INTERNAL"
TRIGGER_BOTH = "BOTH"
TRIGGER_PRIOR_WORKFLOW_BEFORE_CLEAN = "PRIOR_WORKFLOW_BEFORE_CLEAN"

REASON_ALREADY_COMPLETED = "ALREADY_COMPLETED"
REASON_ALREADY_COMPLETED_AT_CONFIRM = "ALREADY_COMPLETED_AT_CONFIRM"
REASON_RACK_SCAN_AFTER_CLEAN = "RACK_SCAN_AFTER_CLEAN"
REASON_COMPLETED_NEEDS_CHECKOUT = "COMPLETED_NEEDS_CHECKOUT"
REASON_UPDATED_EXISTING_BAG = "UPDATED_EXISTING_BAG"
REASON_OK = "OK"
REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD = "MISSING_FROM_LATEST_PORTAL_UPLOAD"
REASON_MISSING_FROM_LATEST_PORTAL_SCRAPE = "MISSING_FROM_LATEST_PORTAL_SCRAPE"

TRIGGER_KIND_PORTAL_ABSENCE = "PORTAL_ABSENCE"
TRIGGER_KIND_PORTAL_SCRAPE_ABSENCE_REJECT = "PORTAL_SCRAPE_ABSENCE_REJECT"
ROW_ACCEPTED = "ACCEPTED"
ROW_REJECTED = "REJECTED_DUPLICATE"


def classify_portal_upload_row(
    *,
    ticket_id: str | None,
    was_completed_before_upload: bool,
    has_active_staging: bool,
    row_date_before_batch: bool,
) -> tuple[str, str]:
    """
    Draft upload row_status + reason when ticket_id controls identity.

    was_completed_before_upload: registry was COMPLETED before this upload began
    (frozen pre-upload snapshot — not completion from scan-events in this upload).
    """
    tid = normalize_bag_id(ticket_id)
    if not tid:
        raise ValueError("classify_portal_upload_row requires ticket_id")

    if was_completed_before_upload:
        return ROW_REJECTED, REASON_ALREADY_COMPLETED

    if row_date_before_batch:
        return "NEEDS_ATTENTION", "OLDER_THAN_BATCH_DATE"

    if has_active_staging:
        return ROW_ACCEPTED, REASON_UPDATED_EXISTING_BAG

    return ROW_ACCEPTED, REASON_OK


def confirm_staging_action(
    *,
    ticket_id: str | None,
    was_completed_before_upload: bool,
    has_active_staging: bool,
) -> str:
    """Returns: BLOCK | UPDATE_STAGING | INSERT_STAGING | USE_IDENTITY_PATH"""
    tid = normalize_bag_id(ticket_id)
    if not tid:
        return "USE_IDENTITY_PATH"
    if was_completed_before_upload:
        return "BLOCK"
    if has_active_staging:
        return "UPDATE_STAGING"
    return "INSERT_STAGING"


def normalize_bag_id(value: Any) -> str:
    """
    Canonical Bag ID / ticket_id: trim, uppercase, leading token (min 4 chars).

    Internal underscores and hyphens are preserved (e.g. BAG_1234, BAG-1234).
    Portal descriptions after whitespace or '(' are stripped (e.g. ABCD12 (Wash & Fold)).
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    head = re.split(r"[\s(]", s, maxsplit=1)[0].strip()
    if not head:
        return ""
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_-]{3,})", head, re.I)
    if not m:
        return ""
    token = m.group(1).upper().rstrip("_-")
    return token if len(token) >= 4 else ""


def rack_contains_clean(rack: Any) -> bool:
    return "clean" in str(rack or "").lower()


def user_is_internal(user: Any) -> bool:
    u = str(user or "").lower()
    if not u.strip():
        return False
    return any(term in u for term in INTERNAL_USER_TERMS)


def usable_user_name(user: Any) -> bool:
    return bool(str(user or "").strip())


def _parsed_scan_datetime(ev: Mapping[str, Any]) -> datetime:
    ts = ev.get("scanned_at_parsed")
    if isinstance(ts, datetime):
        return ts
    if ts is not None and str(ts) not in ("", "NaT", "None"):
        try:
            import pandas as pd

            p = pd.Timestamp(ts)
            if not pd.isna(p):
                return p.to_pydatetime()
        except Exception:
            pass
    return datetime.min


def _scan_index_num(ev: Mapping[str, Any]) -> int:
    idx = ev.get("scan_index")
    try:
        return int(float(str(idx).strip())) if idx not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def _event_id_num(ev: Mapping[str, Any]) -> int:
    raw = ev.get("id")
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _progressive_timeline_sort_key(ev: Mapping[str, Any]) -> tuple:
    """Oldest → newest: scanned_at_parsed, scan_index, id."""
    return (_parsed_scan_datetime(ev), _scan_index_num(ev), _event_id_num(ev))


def _dedupe_events_by_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate DB/join rows that share the same event id."""
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        eid = _event_id_num(ev)
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        out.append(ev)
    return out


def order_events_for_completion(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Canonical timeline for completion (dedupe by id, then stable sort)."""
    records = events_from_records(list(events))
    return sorted(_dedupe_events_by_id(records), key=_progressive_timeline_sort_key)


def events_from_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        out.append(
            {
                "id": r.get("id"),
                "rack": r.get("rack") if "rack" in r else r.get("Rack"),
                "user": r.get("user_name")
                if "user_name" in r
                else r.get("User"),
                "scanned_at_parsed": r.get("scanned_at_parsed"),
                "scan_index": r.get("scan_index")
                if "scan_index" in r
                else r.get("Scan Index"),
                "purpose": r.get("purpose")
                if "purpose" in r
                else r.get("Purpose"),
            }
        )
    return out


def _event_id_from_mapping(ev: Mapping[str, Any]) -> int | None:
    raw = ev.get("id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CompletionResult:
    completion_status: str
    completion_reason: str | None
    first_clean_scan_at: datetime | None
    first_clean_scan_event_id: int | None
    trigger_scan_at: datetime | None
    trigger_scan_event_id: int | None
    trigger_kind: str | None

    def to_registry_update(self) -> dict[str, Any]:
        return {
            "completion_status": self.completion_status,
            "completion_reason": self.completion_reason,
            "completed_at": self.trigger_scan_at if self.completion_status == COMPLETION_COMPLETED else None,
            "first_clean_scan_at": self.first_clean_scan_at,
            "first_clean_scan_event_id": self.first_clean_scan_event_id,
            "trigger_scan_at": self.trigger_scan_at,
            "trigger_scan_event_id": self.trigger_scan_event_id,
            "trigger_kind": self.trigger_kind,
        }


def evaluate_bag_completion(
    events: Iterable[Mapping[str, Any]],
) -> CompletionResult:
    """
    COMPLETED on first scan whose rack contains "Clean" (case-insensitive substring).

    Examples: Clean, VeeWash Clean, Washpro Clean, Clean 1.
    No later scan is required.
    """
    ordered = order_events_for_completion(events)
    if not ordered:
        return CompletionResult(
            completion_status=COMPLETION_INCOMPLETE,
            completion_reason=REASON_NO_CLEAN_SCAN,
            first_clean_scan_at=None,
            first_clean_scan_event_id=None,
            trigger_scan_at=None,
            trigger_scan_event_id=None,
            trigger_kind=None,
        )

    for ev in ordered:
        if not rack_contains_clean(ev.get("rack")):
            continue
        clean_at = _parsed_scan_datetime(ev)
        if clean_at == datetime.min:
            clean_at = None
        clean_event_id = _event_id_from_mapping(ev)
        return CompletionResult(
            completion_status=COMPLETION_COMPLETED,
            completion_reason=REASON_CLEAN_RACK_SCANNED,
            first_clean_scan_at=clean_at,
            first_clean_scan_event_id=clean_event_id,
            trigger_scan_at=clean_at,
            trigger_scan_event_id=clean_event_id,
            trigger_kind=TRIGGER_CLEAN_RACK,
        )

    return CompletionResult(
        completion_status=COMPLETION_INCOMPLETE,
        completion_reason=REASON_NO_CLEAN_SCAN,
        first_clean_scan_at=None,
        first_clean_scan_event_id=None,
        trigger_scan_at=None,
        trigger_scan_event_id=None,
        trigger_kind=None,
    )


def completion_result_references_persisted_events(
    result: CompletionResult,
    ordered_events: Sequence[Mapping[str, Any]],
) -> bool:
    """COMPLETED must reference the first persisted Clean rack scan in the timeline."""
    if result.completion_status != COMPLETION_COMPLETED:
        return True
    if result.completion_reason != REASON_CLEAN_RACK_SCANNED:
        return True
    ordered = order_events_for_completion(ordered_events)
    for ev in ordered:
        if rack_contains_clean(ev.get("rack")):
            if result.first_clean_scan_event_id is None:
                return True
            return _event_id_num(ev) == int(result.first_clean_scan_event_id)
    return False
