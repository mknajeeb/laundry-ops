# Shift Analysis & Lifecycle — Business Logic Review (Current State)

Review-only snapshot from `rinse_bag_lifecycle_status.py`, `rinse_shift_analysis.py`, `rinse_shift_operational_exceptions.py`, `rinse_bag_gaming_performance.py`, settings modules, and `docs/RINSE_BAG_LIFECYCLE_STATUS.md`.

**Status:** Documentation only — no code, dashboard, staff performance, or UI changes implied by this file.

---

## 1. Lifecycle statuses (`current_lifecycle_status`)

Single forward progression per bag. Derived from scan timeline + optional portal presence + evaluation time. **Separate from checkout and folding scoring.**

| Status | Friendly label | Typical meaning | Dashboard group |
|--------|----------------|-----------------|-----------------|
| `ASSIGNED_NOT_SENT_TO_VENDOR` | Assigned — not sent | Rinse assigned bag; `ready_for_vendor` presence; no sent-to-vendor scan | Early lifecycle |
| `SENT_TO_VENDOR` | Sent to vendor | `at_vendor` presence or in portal queue; no post-anchor weight yet | Early lifecycle |
| `PENDING_WEIGHING` | Pending weighing | Sent-to-vendor anchor exists; no weight-entry after anchor | Pending Weighing |
| `WEIGHED_NOT_STARTED` | Weighed — not started | Weight after anchor; no further events after weight | Weighed / Not Started |
| `SORTED_READY_FOR_WASH` | Sorted — ready for wash | Events after weight; no start-cleaning yet | Sorted / Ready |
| `LOAD_WASHER` | Load washer | start-cleaning through last ready-washer / washer-settings | Wash / Dry |
| `IN_WASHING` | In washing | After load-washer end; expected end = load end + `washing_minutes` | Wash / Dry |
| `LOAD_DRYER` | Load dryer | Drying scan timestamp (instantaneous) | Wash / Dry |
| `IN_DRYING` | In drying | Drying purpose seen; expected end = dry + `drying_minutes` | Wash / Dry |
| `FOLDED_COMPLETED` | Folded / completed | CLEAN rack scan | Folded |
| `SENT_TO_RINSE` | Sent to Rinse | Missing from next portal scrape after CLEAN, **or** external/non-employee scan after CLEAN | Sent to Rinse |
| `UNKNOWN` | Unknown lifecycle | Fallback when rules cannot classify | Unknown lifecycle |

**Completed (dashboard):** `FOLDED_COMPLETED`, `SENT_TO_RINSE`  
**Pending:** all others among active WF staging bags

**Key rules**

- Anchor = first `sent-to-vendor` scan; only post-anchor events count for processing lifecycle.
- Ghost purpose: exact `cleaning` only (ignored for timing).
- `SENT_TO_RINSE` lifecycle **≠** facility checkout `logistics_status = SENT_TO_RINSE`.

**Portal presence (implemented, not dashboard-wired yet)**

| Input | Effect |
|-------|--------|
| `ready_for_vendor_presence` | Can yield `ASSIGNED_NOT_SENT_TO_VENDOR` (no scans) |
| `at_vendor_presence` | Can yield `SENT_TO_VENDOR` (no sent-to-vendor scan yet) |
| `missing_from_next_portal_scrape` | Can yield lifecycle `SENT_TO_RINSE` after CLEAN |

**Separate channel — facility checkout (`checkout_status`, not lifecycle)**

| Value | Meaning |
|-------|---------|
| `NOT_CHECKED_OUT` | Still at facility |
| `CHECKED_OUT` | Checked out via `/checkout` |
| `CHECKOUT_NEEDS_REVIEW` | Checked out without CLEAN rack |

---

## 2. Processing stages (performance / gaming — not lifecycle status)

> **⚠️ PENDING REVISION — NOT FINAL**
>
> This section documents **current implemented code** in `rinse_bag_gaming_performance.py`. It **conflicts** with the newer lifecycle rules in §1 and must **not** be treated as approved business logic until revised and signed off.
>
> **Do not implement dashboard, staff performance, or UI changes based on this section until revision is complete.**

Two layers for **employee timing & productivity**, distinct from `current_lifecycle_status`.

### Pending revision — conflict with lifecycle rules

**Current code (Layer 1 — bag-level stages):**

| Stage | Current start → end (implemented) |
|-------|-----------------------------------|
| **Weighing** | Last cleaning-related purpose before weight-entry → weight-entry |
| **Sorting** | weight-entry (or first cleaning-related after weight) → sorting end marker |

This uses **cleaning-related purpose** anchors and does **not** require post–sent-to-vendor evaluation for weight-entry. That contradicts lifecycle §1, which anchors processing on the sent-to-vendor sequence and treats ghost vs valid purposes differently.

**Correct direction — pending final approval (not yet implemented):**

| Rule | Intended meaning |
|------|------------------|
| `purpose = cleaning` | **Only** ghost purpose (ignored for timing) |
| `purpose = start-cleaning` | Valid purpose (not ghost) |
| Rack contains `CLEAN` | Completed (folded) |
| `weight-entry` | Evaluated **after** sent-to-vendor anchor |
| Processing stages | Anchored to the **lifecycle sequence**, not cleaning-related purpose heuristics |

Until this revision is approved and coded, Layer 1 timings in production code may disagree with lifecycle status for the same bag.

### Layer 1 — Bag-level stages (`rinse_bag_gaming_performance.py`) — *as implemented today*

| Stage | Start | End | Detection |
|-------|-------|-----|-----------|
| **Weighing** | Last cleaning-related purpose before weight-entry | weight-entry | Purpose labels only |
| **Sorting** | weight-entry (or first cleaning-related after weight) | Last workitem/issue/bulk, split-load, add-photos, or start-cleaning | Purpose labels only |
| **Wash / load** | start-cleaning | drying | Purpose labels only |
| **Folding** | Existing folding engine | CLEAN rack / folding rules | Rack + folding exception rules |

Stage outcome: `COMPLETED` or `EXCEPTION` per stage.

See also: `docs/RINSE_BAG_GAMING_PERFORMANCE.md`.

### Layer 2 — Shift / person gaming (`rinse_shift_gaming_performance.py`)

Activities (selectable on dashboard): **weighing**, **sorting**, **wash_load**, **folding**

Per bag × activity slice: assigned user, duration, `needs_review`, review reasons (e.g. ambiguous operator).

**Note:** Layer 2 inherits Layer 1 stage boundaries. When Layer 1 is revised, Layer 2 assignment and shift-window metrics must be updated accordingly.

### Lifecycle vs processing — intentional split

| Concept | Module | Used for |
|---------|--------|----------|
| Lifecycle status | `rinse_bag_lifecycle_status` | Where is the bag in production pipeline? |
| Processing stages | `rinse_bag_gaming_performance` | How long did each step take? Who did it? |
| Folding performance | `rinse_bag_folding` | Scoring, exceptions, leaderboard |

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

### D. Gaming stage exceptions (weighing / sorting / wash-load only)

| Code | Stage |
|------|-------|
| `WEIGHT_ENTRY_MISSING` | Weighing |
| `WEIGHING_START_SCAN_MISSING` | Weighing |
| `WEIGHING_DURATION_INVALID` | Weighing |
| `MISSING_SORTING_END` | Sorting |
| `INVALID_SORTING_TIMESTAMPS` | Sorting |
| `START_CLEANING_MISSING` | Wash/load |
| `DRYING_PURPOSE_MISSING` | Wash/load |
| `WASH_LOAD_DURATION_INVALID` | Wash/load |
| `WASH_LOAD_DURATION_TOO_SHORT` | Wash/load |
| `WASH_LOAD_DURATION_TOO_LONG` | Wash/load |

---

## 5. Settings & parameters (tenant-scoped `system_settings`)

### Processing & lifecycle timing (`/performance/settings` → ProcessingSettingsPanel)

| Key | Default | Used for |
|-----|---------|----------|
| `processing_weigh_seconds_per_bag` | 30s | Processing productivity estimates |
| `processing_sort_seconds_per_bag` | 180s | Processing productivity estimates |
| `processing_wash_seconds_per_bag` | 120s | Processing productivity estimates |
| `processing_dry_seconds_per_bag` | 120s | Processing productivity estimates |
| `washing_minutes` | 30 | Lifecycle `IN_WASHING` expected duration |
| `drying_minutes` | 40 | Lifecycle `IN_DRYING` expected duration |
| `reject_after_create_issue_minutes` | 45 | Lifecycle `ORDER_REJECTED_FULL` time gate |
| `reject_no_start_cleaning_minutes` | 30 | Operational reject after sorting (legacy module) |

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

## Open review items (for business sign-off)

| Topic | Question |
|-------|----------|
| **Processing/gaming stages** | Approve lifecycle-anchored Layer 1 revision (§2 pending direction) before dashboard or staff-performance work |
| Early lifecycle | Should `ASSIGNED_NOT_SENT_TO_VENDOR` / `SENT_TO_VENDOR` appear on main dashboard KPIs or detail-only? |
| Dual exception systems | Lifecycle vs operational evaluator overlap — consolidate or keep both? |
| Checkout naming | `logistics_status = SENT_TO_RINSE` vs lifecycle `SENT_TO_RINSE` — rename checkout channel? |
| Presence → dashboard | When to wire `rinse_cleaner_ticket_presence` into pending counts? |
| Employee performance | Processing vs folding vs combined — separate API rows needed? |
| `UNKNOWN` lifecycle | When should it appear vs hidden in “Unknown lifecycle” column? |
| Transition metrics | Use `portal_status_first_seen_at` / `previous_portal_status` for “assigned but not sent” duration? |

---

*Last updated: 2026-05-24 — review snapshot; processing/gaming stage logic marked pending revision.*
