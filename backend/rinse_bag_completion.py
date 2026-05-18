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
REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD = "MISSING_FROM_LATEST_PORTAL_UPLOAD"

TRIGGER_KIND_PORTAL_ABSENCE = "PORTAL_ABSENCE"
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


def _same_event_id(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    a_id = a.get("id")
    b_id = b.get("id")
    if a_id is None or b_id is None:
        return False
    try:
        return int(a_id) == int(b_id)
    except (TypeError, ValueError):
        return False


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


def _is_valid_post_clean_trigger(
    clean_ev: Mapping[str, Any],
    trigger_ev: Mapping[str, Any],
    *,
    clean_position: int,
    trigger_position: int,
) -> bool:
    """Clean row cannot trigger; trigger must be strictly later in timeline order."""
    if trigger_position <= clean_position:
        return False
    if _same_event_id(clean_ev, trigger_ev):
        return False
    if rack_contains_clean(trigger_ev.get("rack")):
        return False
    if not qualifying_post_clean_scan(trigger_ev.get("rack"), trigger_ev.get("user")):
        return False
    return True


def _rack_is_meaningful(rack: Any) -> bool:
    s = str(rack or "").strip().lower()
    if not s:
        return False
    if s in ("none", "(none)", "null", "n/a", "na"):
        return False
    return True


def qualifying_post_clean_scan(rack: Any, user: Any) -> bool:
    """After CLEAN: meaningful non-Clean rack AND named external user (both required)."""
    if not _rack_is_meaningful(rack) or rack_contains_clean(rack):
        return False
    if not usable_user_name(user) or user_is_internal(user):
        return False
    return True


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
    Progressive timeline: scanned_at_parsed ASC, scan_index ASC, id ASC.

    Find the first CLEAN rack scan, then only rows at a strictly greater timeline
    position may trigger completion. The Clean row itself can never be the trigger.
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

    incomplete_after_clean = CompletionResult(
        completion_status=COMPLETION_INCOMPLETE,
        completion_reason=REASON_CLEAN_WITHOUT_QUALIFYING_LATER,
        first_clean_scan_at=first_clean_at,
        first_clean_scan_event_id=fc_event_id_int,
        trigger_scan_at=None,
        trigger_scan_event_id=None,
        trigger_kind=None,
    )

    for trigger_pos, ev in enumerate(ordered[first_clean_idx + 1 :], start=first_clean_idx + 1):
        if not _is_valid_post_clean_trigger(
            first_clean,
            ev,
            clean_position=first_clean_idx,
            trigger_position=trigger_pos,
        ):
            continue

        trigger_at = _parsed_scan_datetime(ev)
        if trigger_at == datetime.min:
            trigger_at = None
        try:
            trigger_id = int(ev.get("id")) if ev.get("id") is not None else None
        except (TypeError, ValueError):
            trigger_id = None

        if trigger_id is not None and fc_event_id_int is not None and trigger_id == fc_event_id_int:
            continue

        return CompletionResult(
            completion_status=COMPLETION_COMPLETED,
            completion_reason=REASON_POST_CLEAN_RACK_AND_USER,
            first_clean_scan_at=first_clean_at,
            first_clean_scan_event_id=fc_event_id_int,
            trigger_scan_at=trigger_at,
            trigger_scan_event_id=trigger_id,
            trigger_kind=TRIGGER_BOTH,
        )

    return incomplete_after_clean


def completion_result_references_persisted_events(
    result: CompletionResult,
    ordered_events: Sequence[Mapping[str, Any]],
) -> bool:
    """
    COMPLETED rows must reference a trigger event that exists after the clean row
    in the same timeline used for evaluation (guards stale registry / phantom triggers).
    """
    if result.completion_status != COMPLETION_COMPLETED:
        return True
    ordered = order_events_for_completion(ordered_events)
    clean_pos = None
    for i, ev in enumerate(ordered):
        if result.first_clean_scan_event_id is not None and _event_id_num(ev) == int(
            result.first_clean_scan_event_id
        ):
            clean_pos = i
            break
    if clean_pos is None:
        for i, ev in enumerate(ordered):
            if rack_contains_clean(ev.get("rack")):
                clean_pos = i
                break
    if clean_pos is None:
        return False
    clean_ev = ordered[clean_pos]
    trigger_pos = None
    if result.trigger_scan_event_id is not None:
        for i, ev in enumerate(ordered):
            if _event_id_num(ev) == int(result.trigger_scan_event_id):
                trigger_pos = i
                break
    if trigger_pos is None:
        return False
    return _is_valid_post_clean_trigger(
        clean_ev,
        ordered[trigger_pos],
        clean_position=clean_pos,
        trigger_position=trigger_pos,
    )
