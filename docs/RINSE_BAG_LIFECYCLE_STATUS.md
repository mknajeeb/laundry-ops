# Rinse bag lifecycle status engine

Module: `backend/rinse_bag_lifecycle_status.py`

Shared timeline helpers: `backend/rinse_bag_stage_bounds.py`

Lifecycle status is **separate** from `operational_flags` and `exception_flags`.

---

## Ghost purpose rule

Only exact normalized purpose **`cleaning`** is ignored in lifecycle/timing.

Do **not** ghost:

- `start-cleaning`
- `ready-washer`, `washer-settings`
- `drying`, `weight-entry`, `sent-to-vendor`
- `create-issue`, purposes containing `workitem`
- `split-load`, `add-photos`

**CLEAN rack** (case-insensitive contains) is still the completion signal for `FOLDED_COMPLETED`.

```text
purpose = cleaning  -> ghost / ignore (lifecycle + sorting only)
rack contains CLEAN -> folded/completed
purpose = start-cleaning -> valid wash signal
```

Weighing **performance** uses exact `purpose = cleaning` as task start (see gaming doc).

---

## Sent-to-vendor anchor

```text
lifecycle_anchor_time = first sent-to-vendor timestamp
```

Only events **on or after** the anchor are used for processing lifecycle and performance bounds.

`weight-entry` **before** sent-to-vendor is ignored.

---

## Status list (forward progression)

| Status | Summary |
|--------|---------|
| `ASSIGNED_NOT_SENT_TO_VENDOR` | `ready_for_vendor_presence`, not in queue |
| `SENT_TO_VENDOR` | `at_vendor_presence` without sent-to-vendor scan yet |
| `PENDING_WEIGHING` | sent-to-vendor, no weight after anchor |
| `WEIGHED_NOT_STARTED` | weight after anchor, no events after weight |
| `SORTED_READY_FOR_WASH` | events after weight, no start-cleaning |
| `IN_WASHING` | start-cleaning seen, no drying yet |
| `IN_DRYING` | drying purpose seen, no CLEAN rack yet |
| `FOLDED_COMPLETED` | CLEAN rack scan |
| `SENT_TO_RINSE` | missing from next portal scrape after CLEAN, or external/non-employee scan after CLEAN |
| `UNKNOWN` | fallback |

**Not lifecycle statuses** (performance / `stage_detail` only):

- `LOAD_WASHER` — start-cleaning until last ready-washer/washer-settings
- `LOAD_DRYER` — drying timestamp (instantaneous)

---

## Sorting after weight (lifecycle boundary)

```text
sorting_start = first non-ghost purpose after post-anchor weight-entry
sorting_end   = last non-ghost purpose before start-cleaning
                (or last after weight if no start-cleaning)
```

Workitem, issue, split-load, and add-photos remain operational markers **inside** sorting.

---

## IN_WASHING / IN_DRYING lifecycle

```text
IN_WASHING: start-cleaning with no drying yet
            (stage_detail may include LOAD_WASHER performance bounds)

IN_WASHING expected end = load_washer_end or start-cleaning + washing_minutes

IN_DRYING: drying with no CLEAN rack yet
           (stage_detail may include LOAD_DRYER performance bounds)

IN_DRYING expected end = drying + drying_minutes
```

---

## Settings (`system_settings`)

| Key | Default | Label |
|-----|---------|-------|
| `washing_minutes` | 30 | Default washing duration minutes |
| `drying_minutes` | 45 | Default drying duration minutes |
| `reject_after_create_issue_minutes` | 45 | Reject if washing not started within limit after create-issue (time-gated at evaluation) |
| `reject_no_start_cleaning_minutes` | 30 | Legacy sorting-end reject (operational module) |

---

## Exception flags (not lifecycle status)

- `ORDER_REJECTED_FULL` — create-issue exists, evaluation time is past `create_issue_time + reject_after_create_issue_minutes`, and no start-cleaning within that window (or start-cleaning occurred after the window)
- `COMPLETED_WITHOUT_FINAL_CLEAN_SCAN` — processed-by-vendor without later CLEAN rack
- `NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN` — external operator after CLEAN rack
- `CHECKOUT_WITHOUT_CLEAN_RACK` — facility checkout without a CLEAN rack scan (does not change lifecycle status)

`derive_bag_lifecycle_status(..., evaluation_time=...)` accepts an optional evaluation timestamp (defaults to latest event time, then UTC now). Reject detail is in `stage_detail.reject_after_create_issue` when create-issue exists.

---

## Facility checkout (separate from lifecycle)

Checkout answers: **Did we check this Rush bag out of the facility?**

It does **not** set `current_lifecycle_status`. Use `checkout_status`:

```text
NOT_CHECKED_OUT
CHECKED_OUT
CHECKOUT_NEEDS_REVIEW   (checked out without CLEAN rack)
```

`logistics_status` from staging (`SENT_TO_RINSE`, `CHECKED_OUT`, `FORCE_CHECKOUT`) feeds `checkout_status` only.

Example when checkout and lifecycle diverge:

```json
{
  "current_lifecycle_status": "FOLDED_COMPLETED",
  "checkout_status": "CHECKED_OUT"
}
```

---

## Lifecycle SENT_TO_RINSE sources

```text
1. Bag missing from next portal scrape after CLEAN rack
2. External/non-employee scan after CLEAN rack
```

Do **not** use checkout/logistics alone as lifecycle truth.

---

## Portal presence (future)

Engine accepts:

- `ready_for_vendor_presence`
- `at_vendor_presence`
- `missing_from_next_portal_scrape`

Future table: `rinse_cleaner_ticket_presence` (`ready_for_vendor` | `at_vendor`).
