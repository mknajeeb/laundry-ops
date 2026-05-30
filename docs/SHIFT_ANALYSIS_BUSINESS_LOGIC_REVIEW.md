# Shift Analysis & Lifecycle — Business Logic Review

Review snapshot for business sign-off before implementation. Source modules: `rinse_bag_lifecycle_status.py`, `rinse_shift_analysis.py`, `rinse_bag_gaming_performance.py`, settings modules.

**Status:** Documentation only — no code, dashboard, staff performance, or UI changes implied by this file.

**Related:** [`SHIFT_ANALYSIS_STAGE_TIMING_MODEL_REVIEW.md`](./SHIFT_ANALYSIS_STAGE_TIMING_MODEL_REVIEW.md) (detailed stage/timing model)

---

## 1. Lifecycle statuses (`current_lifecycle_status`)

Single forward progression per bag. Derived from scan timeline + optional portal presence + evaluation time. **Separate from checkout, folding scoring, and performance-only task stages.**

> **Important:** `LOAD_WASHER` and `LOAD_DRYER` are **not** lifecycle statuses. They are **performance/task stages only** (see §2). Current code in `rinse_bag_lifecycle_status.py` still emits them as lifecycle values — **to be removed on implementation**.

### Approved lifecycle status list (10 values)

| Status | Friendly label | Typical meaning | Dashboard group |
|--------|----------------|-----------------|-----------------|
| `ASSIGNED_NOT_SENT_TO_VENDOR` | Assigned — not sent | Rinse assigned bag; `ready_for_vendor` presence; not yet sent | Early lifecycle |
| `SENT_TO_VENDOR` | Sent to vendor | `at_vendor` presence or sent-to-vendor; no post-anchor weight yet | Early lifecycle |
| `PENDING_WEIGHING` | Pending weighing | Sent-to-vendor / at_vendor anchor; no post-anchor weight-entry yet | Pending Weighing |
| `WEIGHED_NOT_STARTED` | Weighed — not started | Valid post-anchor weight; no further non-ghost events after weight | Weighed / Not Started |
| `SORTED_READY_FOR_WASH` | Sorted — ready for wash | Events after weight; no `start-cleaning` yet | Sorted / Ready |
| `IN_WASHING` | In washing | After load-washer **performance** step completes; until `drying` seen | Wash / Dry |
| `IN_DRYING` | In drying | `drying` purpose seen; until CLEAN rack | Wash / Dry |
| `FOLDED_COMPLETED` | Folded / completed | CLEAN rack scan (case-insensitive contains) | Folded |
| `SENT_TO_RINSE` | Sent to Rinse | Missing from next portal scrape after CLEAN, **or** external/non-employee scan after CLEAN | Sent to Rinse |
| `UNKNOWN` | Unknown lifecycle | Fallback when rules cannot classify | Unknown lifecycle |

**Not lifecycle statuses (performance only):** `LOAD_WASHER`, `LOAD_DRYER`

**Completed (dashboard):** `FOLDED_COMPLETED`, `SENT_TO_RINSE`  
**Pending:** all other lifecycle statuses among active WF staging bags

### Lifecycle transition rules

| Transition | Rule |
|------------|------|
| Anchor | First `sent-to-vendor` scan (or `at_vendor` presence when scan missing). Only **post-anchor** events count. |
| Ghost purpose (lifecycle) | Exact normalized `purpose = cleaning` only — **ignored** for lifecycle progression and sorting |
| Valid weight | **First `weight-entry` after anchor** — ignore pre-anchor weight scans |
| Sorting window | First non-ghost purpose after valid weight → last non-ghost purpose **before** `start-cleaning` |
| `start-cleaning` | Ends sorting; **not** part of sorting |
| `IN_WASHING` | Starts after **load-washer performance end** (latest `ready-washer` / `washer-settings` after `start-cleaning`). Stays until `drying`. Expected end = load end + **Wash Time** (`wash_time_minutes`, default **30**) |
| `IN_DRYING` | Starts at `drying` purpose. Stays until CLEAN rack. Expected end = drying + **Dryer Time** (`dryer_time_minutes`, default **45**) |
| `FOLDED_COMPLETED` | CLEAN rack — case-insensitive **contains** match (e.g. `CLEAN`, `CLEAN-01`, `FINAL CLEAN`, `ABC-CLEAN-XYZ`) |
| Checkout vs lifecycle | `logistics_status = SENT_TO_RINSE` (facility checkout) **≠** lifecycle `SENT_TO_RINSE` |

### Portal presence (implemented, not dashboard-wired yet)

| Input | Effect |
|-------|--------|
| `ready_for_vendor_presence` | Can yield `ASSIGNED_NOT_SENT_TO_VENDOR` |
| `at_vendor_presence` | Can yield `SENT_TO_VENDOR` when no sent-to-vendor scan yet |
| `missing_from_next_portal_scrape` | Can yield lifecycle `SENT_TO_RINSE` after CLEAN |

### Facility checkout (`checkout_status`, not lifecycle)

| Value | Meaning |
|-------|---------|
| `NOT_CHECKED_OUT` | Still at facility |
| `CHECKED_OUT` | Checked out via `/checkout` |
| `CHECKOUT_NEEDS_REVIEW` | Checked out without CLEAN rack |

---

## 2. Performance stages (not `current_lifecycle_status`)

Performance/task stages measure **operator time and productivity**. They may overlap lifecycle milestones but are **not** stored as `current_lifecycle_status`.

### Lifecycle vs performance — dual role of `purpose = cleaning`

| Context | `purpose = cleaning` |
|---------|------------------------|
| **Lifecycle** | Ghost — ignored |
| **Sorting** | Ghost — ignored |
| **Weighing performance only** | **Valid start marker** — start of operator weigh task |

### Approved performance stages

| Stage | Start | End | Notes |
|-------|-------|-----|-------|
| **Incoming wait** | `ready_for_vendor` `portal_status_first_seen_at` | `at_vendor` `portal_status_first_seen_at` or sent-to-vendor | Portal timing |
| **Pending weighing** (queue) | sent-to-vendor / at_vendor anchor | First post-anchor `weight-entry` | Wait time, not operator task |
| **Weighing** (operator task) | **`purpose = cleaning`** (before valid weight) | Post-anchor **`weight-entry`** | Operator = weight-entry assignee. Exception if weight without prior `cleaning`: `WEIGHING_START_CLEANING_MISSING` or relabeled `WEIGHING_START_SCAN_MISSING` |
| **Sorting / prep** | First non-ghost purpose after valid post-anchor weight | Last non-ghost purpose before `start-cleaning` | workitem/issue/split-load/add-photos = **operational markers inside** sorting, not sole end |
| **Waiting for washer** | Sorting end | `start-cleaning` | Queue wait (performance) |
| **LOAD_WASHER** | `start-cleaning` | Latest `ready-washer` or `washer-settings` after start | **Performance only** — not lifecycle status |
| **IN_WASHING** | Load-washer performance end | `drying` (or expected end) | Also a **lifecycle status** while machine runs |
| **LOAD_DRYER** | `drying` | `drying` (instantaneous) | **Performance only** — tracks who triggered dryer load; duration 0 |
| **IN_DRYING** | `drying` | CLEAN rack (or expected end) | Also a **lifecycle status** |
| **Folding performance** | FOLDING rack (existing module) | CLEAN rack | **Separate** from lifecycle `FOLDED_COMPLETED` |
| **Post-completion handoff** | CLEAN rack | Portal absence / external scan / sent-to-rinse signal | Maps to lifecycle `SENT_TO_RINSE` |

### Current code (still to change)

`rinse_bag_gaming_performance.py` still uses cleaning-**related** purpose heuristics and does not split lifecycle vs performance stages. See conflicts in stage timing review doc.

### Layer 2 — Shift / person gaming (`rinse_shift_gaming_performance.py`)

Inherits Layer 1 boundaries. Must remap when performance stages are implemented. **No dashboard/staff-performance UI until backend aligned.**

### Module ownership

| Concept | Module | Used for |
|---------|--------|----------|
| Lifecycle status | `rinse_bag_lifecycle_status.py` | Where is the bag in the pipeline? |
| Performance stages | `rinse_bag_gaming_performance.py` (to revise) | Task durations, operator assignment |
| Folding scoring | `rinse_bag_folding.py` | Leaderboard, exceptions, scoring |

---

## 3. Operational flags (scan timeline — not exceptions)

From `operational_flags_from_timeline()` on visible (non-ghost) events. **Informational counts**, not lifecycle status.

| Flag | Meaning |
|------|---------|
| `has_create_issue` | At least one create-issue scan |
| `has_create_workitem` | At least one create-workitem scan |
| `has_create_bulk_workitem` | At least one create-bulk-workitem scan |
| `has_workitem` | Any purpose containing “workitem” |
| `create_issue_count` | Count of create-issue events |
| `create_workitem_count` | Count of create-workitem events |
| `create_bulk_workitem_count` | Count of bulk workitem events |
| `workitem_count` | Count of all workitem-related purposes |

**Shift Analysis operational stats** (aggregated over pending WF bags, separate evaluator):

| Stat key | Label |
|----------|-------|
| `bags_with_issues` | Bags with issues |
| `bags_with_workitems` | Bags with workitems |
| `bags_with_bulk_workitems` | Bags with bulk workitems |
| `total_issue_events` | Total issue events |
| `total_workitem_events` | Total workitem events |
| `total_bulk_workitem_events` | Total bulk workitem events |

---

## 4. Exception flags

Three families — do not merge in UI without clear labeling.

### A. Lifecycle exception flags (`exception_flags[]` on lifecycle derive)

| Code | Label | Trigger (summary) |
|------|-------|-------------------|
| `ORDER_REJECTED_FULL` | Rejected full order | create-issue + no start-cleaning within `reject_after_create_issue_minutes` (time-gated) |
| `COMPLETED_WITHOUT_FINAL_CLEAN_SCAN` | Completed without final scan | processed-by-vendor without later CLEAN rack |
| `NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN` | External scan after CLEAN | Non-mapped user scan after CLEAN |
| `CHECKOUT_WITHOUT_CLEAN_RACK` | Checked out without CLEAN scan | Facility checkout without CLEAN rack |

Also sets `needs_review` when external scan after CLEAN or checkout needs review.

### B. Shift operational exceptions (`rinse_shift_operational_exceptions.py`)

Legacy/parallel evaluator for dashboard operational section (may overlap lifecycle codes):

| Code | Label |
|------|-------|
| `ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT` | Rejected — no washing started within limit |
| `ORDER_REJECTED_FULL` | Order rejected — washing not started after create-issue |
| `COMPLETED_WITHOUT_FINAL_CLEAN_SCAN` | Completed without final scan |
| `NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN` | External scan after CLEAN — review |
| `CHECKOUT_WITHOUT_CLEAN_RACK` | Checked out without CLEAN rack scan |

### C. Folding performance exceptions (`rinse_bag_folding.py` — scoring)

| Code | Typical rule source |
|------|---------------------|
| `MISSING_SCAN_EVENTS` | No scans |
| `MISSING_FOLDING` | No folding scan |
| `MISSING_CLEAN` | No CLEAN rack |
| `CLEAN_BEFORE_FOLDING` | Clean before folding start |
| `INVALID_TIMESTAMPS` | Bad timestamps |
| `MISSING_ASSIGNED_USER` | No operator |
| `MULTIPLE_FOLDING_SCANS` | Multiple folding scans (configurable warning vs exception) |
| `FOLDING_DURATION_TOO_SHORT` | Below min duration |
| `FOLDING_DURATION_TOO_LONG` | Above max duration |
| `OVERLAP_OR_INVALID_TIMING` | Overlap / invalid timing |
| `MULTIPLE_CLEAN_SCANS` | Multiple CLEAN scans (configurable) |

### D. Gaming / performance stage exceptions

| Code | Stage | Notes |
|------|-------|-------|
| `WEIGHT_ENTRY_MISSING` | Weighing | No post-anchor weight-entry |
| `WEIGHING_START_SCAN_MISSING` | Weighing | Relabel meaning: missing **`purpose = cleaning`** before weight (or use `WEIGHING_START_CLEANING_MISSING`) |
| `WEIGHING_START_CLEANING_MISSING` | Weighing | **Proposed** — weight-entry without prior `cleaning` purpose for weigh task |
| `WEIGHING_DURATION_INVALID` | Weighing | Bad timestamps |
| `MISSING_SORTING_END` | Sorting | No boundary before start-cleaning |
| `INVALID_SORTING_TIMESTAMPS` | Sorting | Bad timestamps |
| `START_CLEANING_MISSING` | Wash performance | No start-cleaning when expected |
| `DRYING_PURPOSE_MISSING` | Wash/dry performance | Legacy combined wash/load |
| `WASH_LOAD_DURATION_*` | Wash performance | Legacy combined stage — split on implementation |

---

## 5. Settings & parameters (tenant-scoped `system_settings`)

### Processing & lifecycle timing (`/performance/settings` → ProcessingSettingsPanel)

| Business label | Setting key (target) | Current code key | Default | Used for |
|----------------|----------------------|------------------|---------|----------|
| **Wash Time** | `wash_time_minutes` | `washing_minutes` | **30** min | Lifecycle `IN_WASHING` expected duration; load-washer performance end → expected wash complete |
| **Dryer Time** | `dryer_time_minutes` | `drying_minutes` | **45** min | Lifecycle `IN_DRYING` expected duration |
| — | `processing_weigh_seconds_per_bag` | (same) | 30s | Productivity estimates |
| — | `processing_sort_seconds_per_bag` | (same) | 180s | Productivity estimates |
| — | `processing_wash_seconds_per_bag` | (same) | 120s | Productivity estimates |
| — | `processing_dry_seconds_per_bag` | (same) | 120s | Productivity estimates |
| — | `reject_after_create_issue_minutes` | (same) | 45 | Sorting reject time gate |
| — | `reject_no_start_cleaning_minutes` | (same) | 30 | Operational reject (legacy module) |

**Implementation note:** On code change, either rename keys to `wash_time_minutes` / `dryer_time_minutes` **or** keep internal `washing_minutes` / `drying_minutes` with UI labels **Wash Time** / **Dryer Time**. Values must remain **tenant-configurable** — do not hardcode 30/45 in business logic. Current code default for drying is **40** — update to **45** on implementation.

### Folding benchmarks (`FoldingBenchmarksPanel`)

| Key | Default |
|-----|---------|
| `rinse_folding_bags_per_hour_target` | 2.5 |
| `rinse_folding_lbs_per_hour_target` | 40.0 |
| `rinse_folding_minutes_per_bag_target` | 24.0 |
| `rinse_folding_issue_free_percent_target` | 98.0 |
| `rinse_folding_week_start_day` | MONDAY |

### Folding exception rules (`FoldingExceptionRulesPanel`)

| Rule | Default |
|------|---------|
| `rule_missing_clean` | on |
| `rule_missing_folding` | on |
| `rule_clean_before_folding` | on |
| `rule_min_duration_enabled` | on (10 min) |
| `rule_max_duration_enabled` | on (240 min) |
| `multiple_clean_scans_behavior` | warning earliest |
| `multiple_folding_scans_behavior` | warning earliest |
| `rule_overlap_invalid_timing` | on |

### Tenant feature flags (`tenant_feature_flags_json`)

| Flag | Default | Purpose |
|------|---------|---------|
| `enable_manual_upload` | true | Manual CSV workflows |
| `enable_checkout` | true | Facility checkout |
| `enable_lifecycle_dashboard` | false | Lifecycle dashboard rollout |
| `enable_ready_for_vendor_scrape` | false | Portal presence scrape |
| `enable_shift_user_performance` | false | Staff performance UI |

### Other ops (not on performance settings page)

| Key | Purpose |
|-----|---------|
| `upload_batch_require_portal_and_scan_events` | Require dual CSV on upload |
| `daily_operational_reset_*` | Checkout history archive |

---

## 6. Metrics currently calculated

### A. Lifecycle pending (`get_pending_bag_status` — Shift Analysis)

Per **Rush / Non-Rush / Combined**:

| Metric | Source |
|--------|--------|
| `total`, `completed`, `pending` | Lifecycle completed vs not |
| `needs_review` | Lifecycle `needs_review` |
| `with_exceptions` | Non-empty `exception_flags` |
| `by_lifecycle_status` | Count per raw status |
| `by_lifecycle_group` | Pending Weighing, Weighed/Not Started, Sorted/Ready, Wash/Dry, Folded, Sent to Rinse, Early, Unknown |
| Checkout rush summary | `checkout_pending`, `checked_out`, `checkout_needs_review` |
| `legacy_buckets` | Old 3-bucket debug (not_weighed, weighed_not_washed, in_washing) |

**Note:** Portal presence is **not** yet fed into shift-analysis pending aggregation (only in order-detail / direct lifecycle calls).

### B. Team & labor summary

| Field | Scope |
|-------|-------|
| `clocked_labor_hours` | TA clock |
| `processing_labor_hours` / `folding_labor_hours` | Activity estimates |
| `total_bags_processed` / `total_bags_completed` | Processing vs folding completion |
| `total_lbs_processed` / `total_lbs_folded` | Weights |
| `processing_bags_per_hour` / `folding_bags_per_hour` | Rates |

### C. Scoring subset

| Field | Meaning |
|-------|---------|
| `scoring_bags` / `scoring_lbs` | In-scoring folding only |
| `scoring_quality_percent` | Issue-free % |
| `excluded_records` | Not in scoring (exceptions/rules) |

### D. Speed block

| Team | Metrics |
|------|---------|
| Processing | bags/hr, lbs/hr, min/bag, people, labor hrs |
| Folding | bags/hr, lbs/hr, min/bag, people, labor hrs |
| Combined | labor hrs, people (rates null) |

### E. Employee rows (currently folding-leaderboard sourced)

| Column | Source |
|--------|--------|
| Activity hrs, bags, lbs, bags/hr, lbs/hr | Leaderboard + clock |
| Exceptions / needs review | Exception count |

Processing/folding/combined tabs are UI-only; backend employee list is still folding-centric.

### F. Operational dashboard block

Per-bag profiles + aggregated stats (issues, workitems, rejects, missing clean scan).

### G. Folding leaderboard / TV (separate from Shift Analysis)

Bags, lbs, rates, exception counts, issue-free %, period bag summary (included vs excluded from scoring).

### H. Portal presence (new — admin/backfill only)

Rows found/inserted/updated; per-bag `first_seen_at`, `portal_status_first_seen_at`, `portal_status_changed_at`, `previous_portal_status`.

**Not yet:** transition-time metrics (ready→at_vendor duration) in any dashboard.

---

## Open review items

| Topic | Status |
|-------|--------|
| Lifecycle vs performance split (`LOAD_WASHER` / `LOAD_DRYER`) | **Decided** — performance only; remove from `current_lifecycle_status` on implementation |
| Weighing performance (`cleaning` → weight-entry) | **Decided** — see §2 dual-role table |
| Sorting boundaries | **Decided** — lifecycle end before `start-cleaning` |
| Folding lifecycle vs scoring | **Decided** — CLEAN = lifecycle; FOLDING→CLEAN = scoring module |
| Wash / dryer time settings | **Decided** — Wash Time 30, Dryer Time 45, tenant-configurable |
| Early lifecycle on dashboard KPIs | Open |
| Dual exception systems (lifecycle vs operational) | Open |
| Checkout naming vs lifecycle `SENT_TO_RINSE` | Open |
| Presence → dashboard aggregation | Open |
| Employee performance activity mapping | Open |
| `UNKNOWN` lifecycle display | Open |

---

*Last updated: 2026-05-24 — final status/stage corrections documented; implementation pending.*
