# Rinse bag lifecycle status engine

Module: `backend/rinse_bag_lifecycle_status.py`

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
purpose = cleaning  -> ghost / ignore
rack contains CLEAN -> folded/completed
purpose = start-cleaning -> valid wash signal
```

---

## Sent-to-vendor anchor

```text
lifecycle_anchor_time = first sent-to-vendor timestamp
```

Only events **on or after** the anchor are used for processing lifecycle.

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
| `LOAD_WASHER` | start-cleaning until last ready-washer/washer-settings |
| `IN_WASHING` | after LOAD_WASHER end |
| `LOAD_DRYER` | (detail) drying timestamp |
| `IN_DRYING` | drying purpose seen |
| `FOLDED_COMPLETED` | CLEAN rack scan |
| `SENT_TO_RINSE` | missing from next portal scrape after CLEAN, or external/non-employee scan after CLEAN |

---

## Sorting after weight

```text
sorting_start = first non-ghost purpose after post-anchor weight-entry
sorting_end   = last non-ghost purpose before start-cleaning
                (or last after weight if no start-cleaning)
```

---

## LOAD_WASHER / IN_WASHING

```text
LOAD_WASHER start = start-cleaning
LOAD_WASHER end   = last ready-washer OR washer-settings after start-cleaning

IN_WASHING starts after LOAD_WASHER end
IN_WASHING expected end = load_washer_end + washing_minutes (configurable)
```

---

## LOAD_DRYER / IN_DRYING

```text
LOAD_DRYER start/end = drying timestamp (instantaneous)

IN_DRYING starts at drying
IN_DRYING expected end = drying + drying_minutes (configurable)
```

---

## Settings (`system_settings`)

| Key | Default | Label |
|-----|---------|-------|
| `washing_minutes` | 30 | Default washing duration minutes |
| `drying_minutes` | 40 | Default drying duration minutes |
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
