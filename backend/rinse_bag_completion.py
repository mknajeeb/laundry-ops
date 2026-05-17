"""
Rinse bag completion from scan-events (progressive timeline: exit CLEAN rack).
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

REASON_NO_CLEAN_SCAN = "NO_CLEAN_SCAN"
REASON_POST_CLEAN_RACK_AND_USER = "POST_CLEAN_RACK_AND_USER"
REASON_CLEAN_WITHOUT_QUALIFYING_LATER = "CLEAN_WITHOUT_QUALIFYING_LATER_SCAN"

# Legacy aliases (older registry rows / docs)
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
REASON_UPDATED_EXISTING_BAG = "UPDATED_EXISTING_BAG"
REASON_OK = "OK"
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
    (not completion inferred from scan-events merged in the same upload).
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
    Canonical Bag ID / ticket_id: leading alphanumeric (4+), uppercased.
    Matches portal_csv._ticket_id_from_bag and scan-events CSV Bag ID.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    m = re.match(r"^([A-Z0-9]{4,})", s, re.I)
    return m.group(1).upper() if m else ""


def rack_contains_clean(rack: Any) -> bool:
    return "clean" in str(rack or "").lower()


def user_is_internal(user: Any) -> bool:
    u = str(user or "").lower()
    if not u.strip():
        return False
    return any(term in u for term in INTERNAL_USER_TERMS)


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


def _progressive_timeline_sort_key(ev: Mapping[str, Any]) -> tuple:
    """Oldest → newest by scanned_at_parsed; scan_index only breaks ties."""
    return (_parsed_scan_datetime(ev), _scan_index_num(ev))


def qualifying_post_clean_scan(rack: Any, user: Any) -> bool:
    """After CLEAN: non-Clean rack AND non-internal user (both required)."""
    return not rack_contains_clean(rack) and not user_is_internal(user)


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
            }
        )
    return out


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
    Progressive timeline (scanned_at_parsed ASC; scan_index tie-break only).

    Find the first CLEAN rack scan, then look at later scans only.
    COMPLETED when a later scan has a non-Clean rack AND a non-internal user.
    completed_at / trigger point at that qualifying later scan.
    """
    ordered = sorted(events_from_records(list(events)), key=_progressive_timeline_sort_key)
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

    first_clean_idx = None
    for i, ev in enumerate(ordered):
        if rack_contains_clean(ev.get("rack")):
            first_clean_idx = i
            break

    if first_clean_idx is None:
        return CompletionResult(
            completion_status=COMPLETION_INCOMPLETE,
            completion_reason=REASON_NO_CLEAN_SCAN,
            first_clean_scan_at=None,
            first_clean_scan_event_id=None,
            trigger_scan_at=None,
            trigger_scan_event_id=None,
            trigger_kind=None,
        )

    first_clean = ordered[first_clean_idx]
    first_clean_at = _parsed_scan_datetime(first_clean)
    if first_clean_at == datetime.min:
        first_clean_at = None

    fc_event_id = first_clean.get("id")
    try:
        fc_event_id_int = int(fc_event_id) if fc_event_id is not None else None
    except (TypeError, ValueError):
        fc_event_id_int = None

    for ev in ordered[first_clean_idx + 1 :]:
        rack = ev.get("rack")
        user = ev.get("user")
        if not qualifying_post_clean_scan(rack, user):
            continue

        trigger_at = _parsed_scan_datetime(ev)
        if trigger_at == datetime.min:
            trigger_at = None
        try:
            trigger_id = int(ev.get("id")) if ev.get("id") is not None else None
        except (TypeError, ValueError):
            trigger_id = None

        return CompletionResult(
            completion_status=COMPLETION_COMPLETED,
            completion_reason=REASON_POST_CLEAN_RACK_AND_USER,
            first_clean_scan_at=first_clean_at,
            first_clean_scan_event_id=fc_event_id_int,
            trigger_scan_at=trigger_at,
            trigger_scan_event_id=trigger_id,
            trigger_kind=TRIGGER_BOTH,
        )

    return CompletionResult(
        completion_status=COMPLETION_INCOMPLETE,
        completion_reason=REASON_CLEAN_WITHOUT_QUALIFYING_LATER,
        first_clean_scan_at=first_clean_at,
        first_clean_scan_event_id=fc_event_id_int,
        trigger_scan_at=None,
        trigger_scan_event_id=None,
        trigger_kind=None,
    )
