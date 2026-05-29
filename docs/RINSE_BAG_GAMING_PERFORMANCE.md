# Wash & Fold bag gaming / performance time logic

Two layers:

1. **Bag-level stage timing** — per-bag durations for weighing, sorting, wash/load, folding
2. **Person/shift-level gaming** — aggregation by clocked shift, user, and selected activities

**Modules:**

- `backend/rinse_bag_gaming_performance.py` — Layer 1 + bag activity slices
- `backend/rinse_shift_gaming_performance.py` — Layer 2 shift aggregation

---

## Purpose-based vs rack-based

| Stage | Detection |
|-------|-----------|
| Weighing | **Purpose labels only** |
| Sorting | **Purpose labels only** |
| Wash/load | **Purpose labels only** |
| Folding | **Existing logic as-is** (may use rack-based rules today) |

Do not use rack name/type for weighing, sorting, or wash/load.

---

## Layer 1: Bag-level stage timing

### Cleaning-related purpose

Helper: `is_cleaning_related_purpose()` — normalized purpose contains `"clean"`, excluding `weight-entry`, `drying`, `split-load`, `add-photos`, `create-workitem`, `create-issue`.

### Weighing

```text
weighing_start = last cleaning-related purpose event before weight-entry
weighing_end   = weight-entry purpose
weighing_time  = weight_entry_time − last_cleaning_purpose_before_weight_entry
```

Exceptions: `WEIGHT_ENTRY_MISSING`, `WEIGHING_START_SCAN_MISSING`, `WEIGHING_DURATION_INVALID`

### Sorting

```text
sorting_start = weight-entry by default

If a cleaning-related purpose exists after weight-entry and before the first sorting-phase end marker:
    sorting_start = first such cleaning-related purpose after weight-entry
```

Sorting end priority (after sorting start):

1. **Last** `create-workitem`, `create-issue`, or `create-bulk-workitem`
2. `split-load`
3. `add-photos`
4. `start-cleaning`, then other cleaning-related purpose fallback

Workitem/issue are end markers only, not exceptions.

### Wash / load

```text
wash_load_start = start-cleaning purpose
wash_load_end   = drying purpose
wash_load_time  = drying − start-cleaning
```

Exceptions: `START_CLEANING_MISSING`, `DRYING_PURPOSE_MISSING`, duration invalid/too short/too long.

### Folding

Use `evaluate_folding_performance_for_bag` **as-is**. Do not change folding rules in this module.

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

- `backend/tests/test_rinse_bag_gaming_performance.py` — Layer 1
- `backend/tests/test_rinse_shift_gaming_performance.py` — Layer 2 (scenarios A/B/C, wash end logic, folding)
