# Folding productivity — 3 reporting modes (Phase 4A)

**Status:** Plan only — not implemented yet.

## Non-negotiable constraints

Phase 4A is **read-only reporting** on top of existing `rinse_folding_performance` data.

**Do not change:**

- How `folding_start_at` is chosen (scan evaluation / recompute)
- How `folding_end_at` is chosen
- `evaluate_folding_performance_for_bag`, exception rules apply/recompute
- `included_in_scoring` / `scoring_status` derivation (except existing admin overrides)
- Leaderboard scoring SQL predicates

**Source of truth for bag timing:** stored `folding_start_at`, `folding_end_at`, `duration_seconds` on each performance row.

New code may **only** aggregate, sequence, gap-calculate, and compare those rows against different **denominators**.

---

## Three modes (clearly separated)

| Mode | Name | Question answered | Denominator for “per hour” rates |
|------|------|-------------------|--------------------------------|
| **A** | Bag-wise folding stats | How fast did each bag fold? | Sum of `duration_seconds` → **per folding hour** |
| **B** | Bag-span work window | How productive was the span from first bag start to last bag end? | `work_window_minutes` → **per work-window hour** |
| **C** | Clock-hour stats | How productive vs paid/clocked time? | `clocked_minutes` from `shift_sessions` → **per clocked hour** |

Never label all three as generic “bags/hr” without naming the denominator.

---

## Mode A — Bag-wise folding stats

**Purpose:** Actual folding performance per bag using stored intervals.

**Data:** `rinse_folding_performance` (+ registry join for customer/weight), filtered by user + ET date range.

**Fields (existing only):**

- `folding_start_at`, `folding_end_at`, `duration_seconds`
- `status`, `exception_code`, `included_in_scoring`, `scoring_status`
- `weight_lbs`, `bag_id`, `assigned_user_name`

**Summary metrics:**

| Metric | Definition |
|--------|------------|
| `total_bags` | All completed performance rows in range |
| `scoring_bags` | `included_in_scoring = 1` (same predicate as leaderboard) |
| `exception_bags` | Not in scoring (exceptions + excluded) |
| `total_lbs` / `scoring_lbs` | Sum weight, all vs scoring subset |
| `total_folding_minutes` | Sum `duration_seconds` / 60 (all bags with duration) |
| `avg_minutes_per_bag` | `total_folding_minutes / total_bags` (bags with duration) |
| `bags_per_folding_hour` | `total_bags / (total_folding_minutes/60)` |
| `lbs_per_folding_hour` | `total_lbs / (total_folding_minutes/60)` |
| `total_gap_minutes` | Sum of gaps between consecutive bags (see below) |

**Gap (Mode A):** Between bag *i* end and bag *i+1* start, ordered by `folding_start_at` (then `folding_end_at`, `bag_id`):

- `gap_seconds = folding_start_at[i+1] - folding_end_at[i]` (0 if overlap)

**Sequence table columns:**

`#`, bag ID, customer, folding start (ET), folding end (ET), duration, gap since previous, weight, status, exception/warning, included in scoring.

**Refactor note:** Evolve current `build_user_folding_sequence` into Mode A builder; split totals vs scoring vs exception counts explicitly.

---

## Mode B — Bag-span work window (reporting only)

**Purpose:** Operational span for the day: first recorded bag folding start → last recorded bag folding end.

**Not** “clean rack / scan purpose window” in 4A. Do **not** read `rinse_bag_scan_events` to set window boundaries in this phase.

**Data:** Same performance rows as Mode A for user + date(s).

**Window (per user per ET calendar day, or across multi-day range as one span — see API note below):**

```
work_window_start = MIN(folding_start_at)   -- existing stored values
work_window_end   = MAX(folding_end_at)     -- existing stored values
work_window_minutes = (work_window_end - work_window_start) in minutes
```

**Bags in window:** All performance rows for that user in the date filter (same set as Mode A).

**Inside-window aggregates:**

| Metric | Definition |
|--------|------------|
| `folding_minutes` | Sum of `duration_seconds` / 60 (all bags in set) |
| `gap_minutes` | Sum of inter-bag gaps (same formula as Mode A, on sorted bags) |
| `idle_minutes` | `max(0, work_window_minutes - folding_minutes - gap_minutes)` — labeled “unattributed time in span” |
| `bags_per_work_window_hour` | `total_bags / (work_window_minutes/60)` |
| `lbs_per_work_window_hour` | `total_lbs / (work_window_minutes/60)` |
| `bags_per_folding_hour` | Same as Mode A (sum of durations) — show side-by-side for comparison |

**UI copy:** *“Work span: first bag folding start → last bag folding end (from stored bag records). Not paid shift time. Not scan-based.”*

**Multi-day ranges:** Prefer **per-day** Mode B summaries when `date_start != date_end`, plus optional rolled-up span across all days (document which is shown).

**Future (out of 4A):** Optional Mode B2 using raw scan events for first/last production scan — separate phase, no change to bag timings.

---

## Mode C — Clock-in / clock-out stats

**Purpose:** Productivity vs `shift_sessions` clock time.

**Still uses existing bag rows** for bag counts, lbs, folding minutes, gaps — only the **denominator** is clock time.

**Prerequisite:** `rinse_folding_user_map` (org, `rinse_user_name`, `user_id`, `active`).

**Shift selection:** `shift_sessions` overlapping ET date range for mapped `user_id` + `organization_id`.

| Field | Source |
|-------|--------|
| `clock_in_at`, `clock_out_at` | `shift_sessions` |
| Active shift (`clock_out_at` NULL) | Effective end = `min(now_et, last_rinse_scrape_at)` with label *“Active shift estimate through last sync / current ET”* |

**Bags in shift:** Performance rows where `[folding_start_at, folding_end_at]` overlaps `[clock_in, effective_clock_out]` (inclusive overlap rule in implementation).

**Summary:**

- `clocked_minutes`, `bags_in_shift`, `scoring_bags_in_shift`, `exception_bags_in_shift`
- `folding_minutes_in_shift`, `gap_minutes_in_shift`
- `non_folding_minutes_in_shift` = `clocked_minutes - folding_minutes_in_shift` (gap optional sub-breakdown)
- `bags_per_clocked_hour`, `lbs_per_clocked_hour`
- `bags_per_folding_hour` (in shift subset)

**Timeline events:** Clock in → bag start/end entries → gaps → clock out (read-only display).

**Unmapped Rinse user:** Mode A + B returned; Mode C `available: false`, reason `no_employee_mapping`.

---

## API (read-only)

### `GET /rinse/folding/user-productivity`

Query: `user_name`, `date_start`, `date_end`, `date_field` (default `folding_work_date`).

Response:

```json
{
  "user_name": "...",
  "date_start": "...",
  "date_end": "...",
  "timezone": "America/New_York",
  "employee_mapping": { "mapped": true, "user_id": 12, "display_name": "..." },

  "mode_a_bag_wise": { "summary": {}, "rows": [] },
  "mode_b_work_span": { "summary": {}, "by_day": [], "rows": [] },
  "mode_c_clock_hours": { "available": true, "summary": {}, "shifts": [], "timeline": [] }
}
```

No POST endpoints that mutate performance timing. Mapping CRUD is separate admin surface.

### Admin mapping (Phase 4A or 4A.1)

- `GET/PUT/DELETE /rinse/folding/user-mappings`

---

## UI — Folding Dashboard

**Component:** `FoldingEmployeeProductivityPanel` (tabs), replaces/extends `FoldingUserSequencePanel`.

| Tab | Title | Subtitle denominator |
|-----|-------|----------------------|
| 1 | Bag-wise performance | Per **folding hour** (sum of bag durations) |
| 2 | Work-span performance | Per **work-window hour** (first bag start → last bag end) |
| 3 | Clock-hour performance | Per **clocked hour** (shift_sessions) |

Each tab: summary cards + same bag sequence table (Mode A rows; Mode B/C annotate overlap where useful).

**Maintenance:** Rinse user → employee mapping table (admin).

---

## Implementation modules (no changes to recompute path)

| Module | Responsibility |
|--------|----------------|
| `rinse_folding_bag_wise.py` | Mode A summary + sorted rows + gaps |
| `rinse_folding_work_span.py` | Mode B MIN/MAX start/end + idle math |
| `rinse_folding_clock_productivity.py` | Mode C shifts + overlap + timeline |
| `rinse_folding_user_map.py` | Mapping CRUD |
| `rinse_folding_user_productivity.py` | Orchestrator + route |

**Explicitly out of scope for 4A:** edits to `rinse_bag_folding.py`, `apply_folding_performance_for_bag`, exception rules evaluation order (already done separately).

---

## Tests

1. Mode A rates use `duration_seconds` sum only.
2. Mode B `work_window_start` = MIN(`folding_start_at`), end = MAX(`folding_end_at`) from performance rows — no scan queries.
3. Mode C uses `shift_sessions` for clock minutes only; bags unchanged.
4. Active shift uses last sync/current ET + estimate label.
5. Inter-bag gap = next `folding_start_at` − prev `folding_end_at`.
6. `total_bags` includes exceptions.
7. `scoring_bags` uses `included_in_scoring` / leaderboard predicate.
8. Unmapped user: A + B ok, C unavailable.
9. Mapping enables Mode C.
10. Sub-10-min bag: visible in A/B rows; not in scoring counts; leaderboard predicate excludes.

---

## Jennifer / 2-minute verification

Diagnostic block on productivity response (or admin query):

- List bags for user with `duration_seconds < 600` OR `exception_code = FOLDING_DURATION_TOO_SHORT`
- Report `included_in_scoring`, `in_leaderboard` (derived), stored start/end unchanged

Expected: EXCEPTION, `FOLDING_DURATION_TOO_SHORT`, `included_in_scoring = 0`, appears in history tabs, not in scoring totals.

---

## Deferred (post–4A)

- Scan-based work window (rack/purpose first→last production scan)
- Changing folding start/end selection
- Cross-bag same-user overlap detection as exceptions
