# Wash & Fold bag gaming / performance time logic

Two layers:

1. **Bag-level stage timing** — per-bag durations for weighing, sorting, wash/load, folding
2. **Person/shift-level gaming** — aggregation by clocked shift, user, and selected activities

**Modules:**

- `backend/rinse_bag_stage_bounds.py` — shared anchor, ghost filter, stage bounds
- `backend/rinse_bag_gaming_performance.py` — Layer 1 + bag activity slices
- `backend/rinse_shift_gaming_performance.py` — Layer 2 shift aggregation

---

## Purpose-based vs rack-based

| Stage | Detection |
|-------|-----------|
| Weighing | **Exact `cleaning` purpose** → first post-anchor `weight-entry` |
| Sorting | **Purpose labels only** (lifecycle bounds) |
| Wash/load stages | **Purpose labels only** |
| Folding | **Existing logic as-is** (`evaluate_folding_performance_for_bag`) |

Do not use rack name/type for weighing, sorting, or wash/load.

---

## Sent-to-vendor anchor

Same as lifecycle: first `sent-to-vendor` timestamp. Events before anchor are ignored for performance bounds.

---

## Layer 1: Bag-level stage timing

### Weighing (performance only)

```text
weighing_start = exact normalized purpose cleaning (before anchor OK)
weighing_end   = first weight-entry on or after sent-to-vendor anchor
weighing_time  = weight_entry_time − cleaning_purpose_time
```

Do **not** use broad `is_cleaning_related_purpose()` for weighing.

Exceptions: `WEIGHT_ENTRY_MISSING`, `WEIGHING_START_SCAN_MISSING` / `WEIGHING_START_CLEANING_MISSING`, `WEIGHING_DURATION_INVALID`

### Sorting

```text
sorting_start = first non-ghost purpose after post-anchor weight-entry
sorting_end   = last non-ghost purpose before start-cleaning
```

Only exact `purpose = cleaning` is ghosted. Workitem, issue, split-load, and add-photos remain inside sorting.

Exceptions: `MISSING_SORTING_END`, `INVALID_SORTING_TIMESTAMPS`

### LOAD_WASHER (performance only)

```text
LOAD_WASHER start = start-cleaning
LOAD_WASHER end   = latest ready-washer OR washer-settings after start-cleaning
```

Not emitted as `current_lifecycle_status`.

### IN_WASHING (performance)

```text
IN_WASHING start = LOAD_WASHER end if available, else start-cleaning
IN_WASHING end   = drying if available
expected end     = start + washing_minutes (default 30)
```

### LOAD_DRYER (performance only)

```text
LOAD_DRYER start = drying
LOAD_DRYER end   = drying
duration         = 0
```

Not emitted as `current_lifecycle_status`.

### IN_DRYING (performance)

```text
IN_DRYING start = drying
IN_DRYING end   = CLEAN rack if available
expected end    = drying + drying_minutes (default 45)
```

### Legacy wash/load

```text
wash_load_start = start-cleaning
wash_load_end   = drying
wash_load_time  = drying − start-cleaning
```

Kept for backward-compatible reporting.

### Folding

Use `evaluate_folding_performance_for_bag` **as-is**. Lifecycle `FOLDED_COMPLETED` uses CLEAN rack contains; folding scoring is unchanged.

---

## Layer 2: Person + shift-level gaming

Answers, for each person in a clocked shift:

```text
How many bags did this person process (for selected activities)?
Which activities did they perform?
How long from first activity start to last activity end in the shift?
```

Works when one person does everything or when different people split weighing, sorting, wash/load, and folding.

### Activity assignment (by purpose event operator)

| Activity | Assigned user | Review flag |
|----------|----------------|-------------|
| Weighing | **weight-entry** operator | Start vs end operator differ |
| Sorting | **sorting end-marker** operator | Start vs end operator differ |
| Wash/load | **start-cleaning** operator | Drying operator differs |
| Folding | Existing folding `assigned_user_name` | Missing user / incomplete stage |

Mismatched operators are flagged in `needs_review` but still assigned and counted in shift metrics.
Missing user → `needs_review` without assignment.

### Selectable activities

Per person/shift, select which activities count toward gaming:

```text
[ ] Weighing
[ ] Sorting
[ ] Wash/load
[ ] Folding
```

Output includes **per-activity metrics** and **combined metrics** for the selected set.

### Shift window (not sum of bag durations)

For each selected activity:

```text
activity_first_start = first relevant timestamp for that person after clock-in
activity_last_end    = last relevant timestamp for that person before clock-out
activity_shift_time  = activity_last_end − activity_first_start
```

**Weighing:** first `weighing_start`, last `weight-entry` by person  
**Sorting:** first `sorting_start`, last `sorting_end` by person  
**Wash/load:** first `start-cleaning` by person; last `drying` **or** `start-cleaning` by person  
**Folding:** existing folding start/end for assigned user

**Combined (multiple checkboxes):**

```text
combined_first_start = earliest first_start across selected activities
combined_last_end    = latest last_end across selected activities
combined_shift_time  = combined_last_end − combined_first_start
distinct_bag_count   = distinct bags touched across selected activities
```

### Output shape

`evaluate_person_shift_gaming(...)` returns:

```json
{
  "user_id": "...",
  "user_name": "...",
  "shift_id": "...",
  "clock_in": "...",
  "clock_out": "...",
  "selected_activities": ["weighing", "sorting", "wash_load"],
  "activity_metrics": { "...": { "bag_count", "first_start_time", "last_end_time", "duration_seconds" } },
  "combined_metrics": { "distinct_bag_count", "first_start_time", "last_end_time", "duration_seconds" },
  "indicators": { "create_workitem_count", "create_issue_count", "bags_with_workitems", "bags_with_issues" },
  "needs_review": []
}
```

---

## Tests

- `backend/tests/test_rinse_bag_lifecycle_status.py` — lifecycle (no LOAD_WASHER/LOAD_DRYER in status)
- `backend/tests/test_rinse_bag_gaming_performance.py` — Layer 1 stage bounds
- `backend/tests/test_rinse_shift_gaming_performance.py` — Layer 2 (scenarios A/B/C, wash end logic, folding)
