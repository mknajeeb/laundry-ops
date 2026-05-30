# Shift Analysis — Stage / Timing Model Review

> **Stage / Timing Model — Pending Business Approval**
>
> **Core model finalized** (lifecycle list, performance stages, weighing/sorting/folding rules, wash/dryer settings). Remaining open questions in §4. **Do not implement until docs signed off and coding explicitly requested.**
>
> **Major conflict with current code:** `rinse_bag_lifecycle_status.py` still uses `LOAD_WASHER` / `LOAD_DRYER` as lifecycle statuses; `rinse_bag_gaming_performance.py` still uses cleaning-**related** purpose heuristics. See §2.

**Status:** Documentation only — no code, dashboard, settings UI, or frontend changes implied by this file.

**Related:** [`SHIFT_ANALYSIS_BUSINESS_LOGIC_REVIEW.md`](./SHIFT_ANALYSIS_BUSINESS_LOGIC_REVIEW.md)

---

## Final rules

| Rule | Meaning |
|------|---------|
| Lifecycle statuses | **10 values only** — no `LOAD_WASHER` or `LOAD_DRYER` as `current_lifecycle_status` |
| Performance stages | Include `LOAD_WASHER`, `LOAD_DRYER`, queue/wait stages, operator tasks |
| Ghost purpose (lifecycle + sorting) | Exact normalized `purpose = cleaning` only — ignored |
| Weighing performance exception | **`purpose = cleaning` is weighing start** (not ghost for this stage) |
| Valid weight | First `weight-entry` **after** sent-to-vendor / at_vendor anchor |
| Sorting end | Last non-ghost purpose **before** `start-cleaning`; `start-cleaning` is boundary, not part of sorting |
| Lifecycle completion | Rack **contains** `CLEAN` (case-insensitive) → `FOLDED_COMPLETED` |
| Folding scoring | Separate — existing `FOLDING` → `CLEAN` module |

---

## Business decisions recorded

| ID | Decision |
|----|----------|
| **Q1** | **Keep both.** Pending weighing = queue/wait. Weighing = **separate operator task**: start = **`purpose = cleaning`**, end = post-anchor **`weight-entry`**, operator = weight-entry assignee. |
| **Q2** | Sorting end = **lifecycle boundary** (last non-ghost before `start-cleaning`). workitem/issue/split-load/add-photos = **operational markers inside** sorting, not sole end. |
| **Q3** | **Keep separate.** Lifecycle = **CLEAN** rack. Folding performance = **FOLDING → CLEAN** (`rinse_bag_folding.py`). |
| **Lifecycle vs LOAD_*** | **`LOAD_WASHER` / `LOAD_DRYER` are performance stages only** — not lifecycle statuses. |
| **IN_WASHING / IN_DRYING** | Lifecycle statuses while machine runs; expected durations from tenant **Wash Time** / **Dryer Time** settings. |

### Dual role of `purpose = cleaning`

```text
Lifecycle + sorting:  purpose = cleaning → ghost (ignored)
Weighing performance: purpose = cleaning → START of weigh task
                      weight-entry (post-anchor) → END
Exception if weight-entry without prior cleaning purpose for that task
```

---

## 1. Lifecycle statuses (10) vs performance stages

### Lifecycle statuses — `current_lifecycle_status` only

```text
ASSIGNED_NOT_SENT_TO_VENDOR
SENT_TO_VENDOR
PENDING_WEIGHING
WEIGHED_NOT_STARTED
SORTED_READY_FOR_WASH
IN_WASHING
IN_DRYING
FOLDED_COMPLETED
SENT_TO_RINSE
UNKNOWN
```

**Removed from lifecycle (performance only):** `LOAD_WASHER`, `LOAD_DRYER`

| Lifecycle status | Enters when | Exits when |
|------------------|-------------|------------|
| `IN_WASHING` | Load-washer **performance** step complete (latest ready-washer / washer-settings after start-cleaning) | `drying` purpose seen |
| `IN_DRYING` | `drying` purpose | CLEAN rack scan |
| `FOLDED_COMPLETED` | CLEAN rack (contains match) | — (or → `SENT_TO_RINSE`) |

Expected durations while in progress:

| Status | Expected end | Setting | Default |
|--------|--------------|---------|---------|
| `IN_WASHING` | load-washer perf end + **Wash Time** | `wash_time_minutes` (or `washing_minutes` in code today) | **30** min |
| `IN_DRYING` | drying ts + **Dryer Time** | `dryer_time_minutes` (or `drying_minutes` in code today) | **45** min |

---

## 2. Performance stage model (11 stages)

### Stages 1–5

| Field | **1. Incoming wait** | **2. Pending weighing** | **3. Weighing** | **4. Sorting / prep** | **5. Waiting for washer** |
|-------|----------------------|---------------------------|-----------------|----------------------|---------------------------|
| **Lifecycle status?** | Detail only | `PENDING_WEIGHING` | Milestone at weight; not a lifecycle status | `SORTED_READY_FOR_WASH` | Sub-stage of sorted (not lifecycle status) |
| **Start** | `ready_for_vendor` `portal_status_first_seen_at` | sent-to-vendor / at_vendor anchor | **`purpose = cleaning`** (before valid weight) | First non-ghost purpose after post-anchor weight | Sorting end |
| **End** | at_vendor `portal_status_first_seen_at` or sent-to-vendor | Post-anchor `weight-entry` | Post-anchor `weight-entry` | Last non-ghost before `start-cleaning` | `start-cleaning` |
| **`cleaning` ghost?** | N/A | Ignored for lifecycle timeline | **Used as weigh start** (performance exception to ghost rule) | Ghost — skipped | Ghost |
| **Operator** | None | None (queue) | weight-entry assignee | First/last scan operators in window | start-cleaning or unassigned wait |
| **Duration** | portal end − start | weight − anchor | weight − cleaning | sorting end − start | start-cleaning − sorting end |
| **Exceptions** | Missing portal rows | No post-anchor weight | `WEIGHING_START_CLEANING_MISSING` / relabeled `WEIGHING_START_SCAN_MISSING` | Reject gate after create-issue | Max wait threshold (optional) |

### Stages 6–11

| Field | **6. LOAD_WASHER** | **7. IN_WASHING** | **8. LOAD_DRYER** | **9. IN_DRYING** | **10. Folding perf.** | **11. Post-completion** |
|-------|-------------------|-------------------|-------------------|------------------|----------------------|-------------------------|
| **Lifecycle status?** | **No — performance only** | **Yes — `IN_WASHING`** | **No — performance only** | **Yes — `IN_DRYING`** | **No — scoring module** | **`SENT_TO_RINSE`** |
| **Start** | `start-cleaning` | Load-washer perf end | `drying` | `drying` | FOLDING rack (folding module) | CLEAN rack |
| **End** | Latest ready-washer / washer-settings after start | `drying` (or expected) | `drying` (instant) | CLEAN rack (or expected) | CLEAN rack | Portal / external handoff |
| **Duration** | load end − start-cleaning | drying − load end (or expected + Wash Time) | **0** (instant task) | clean − drying (or expected + Dryer Time) | FOLDING → CLEAN rules | handoff − clean |
| **Operator** | start-cleaning / load-end user | Machine (unattended) | Drying scan operator | Machine until fold | Folding assignee | External / system |

### Anchor summary

```text
Incoming wait:
  ready_for_vendor portal_status_first_seen_at → at_vendor or sent-to-vendor

Pending weighing (queue):
  sent-to-vendor / at_vendor → first weight-entry AFTER anchor

Weighing (operator task):
  purpose = cleaning → post-anchor weight-entry
  Operator = weight-entry assignee
  Exception if cleaning start missing

Sorting / prep:
  first non-ghost after valid weight → last non-ghost before start-cleaning
  workitem / issue / split-load / add-photos = markers inside sorting

Waiting for washer:
  sorting end → start-cleaning

LOAD_WASHER (performance only):
  start-cleaning → latest ready-washer or washer-settings after start-cleaning

IN_WASHING (lifecycle + timing):
  load-washer perf end → drying
  Expected end = load end + Wash Time (default 30 min, tenant setting)

LOAD_DRYER (performance only):
  drying → drying (duration 0; tracks operator)

IN_DRYING (lifecycle + timing):
  drying → CLEAN rack
  Expected end = drying + Dryer Time (default 45 min, tenant setting)

Lifecycle completion:
  CLEAN rack contains match → FOLDED_COMPLETED
  Examples: CLEAN, CLEAN-01, FINAL CLEAN, ABC-CLEAN-XYZ

Folding performance (separate):
  FOLDING rack → CLEAN rack (rinse_bag_folding.py)

Post-completion handoff:
  CLEAN → missing from portal / external scan / sent-to-rinse
```

---

## 3. Conflicts with current code

| Area | Current code | Target model | Severity |
|------|--------------|--------------|----------|
| **`LOAD_WASHER` / `LOAD_DRYER` lifecycle** | Emitted as `current_lifecycle_status` in `rinse_bag_lifecycle_status.py` | **Remove** from lifecycle; keep as performance stages only | **High** |
| **Weighing start** | `is_cleaning_related_purpose()` (broad) | Exact **`purpose = cleaning`** only; post-anchor weight | **High** |
| **Weighing vs pending weighing** | Not split | Two stages: queue + operator task | **High** |
| **Sent-to-vendor anchor** | Gaming uses any weight-entry | Post-anchor weight only | **High** |
| **Sorting end** | Gaming uses workitem/issue priority end | Last non-ghost before start-cleaning | **Medium** |
| **Wash/load combined** | Single `start-cleaning → drying` stage | Split LOAD_WASHER, IN_WASHING, LOAD_DRYER, IN_DRYING | **High** |
| **Dryer time default** | `DEFAULT_DRYING_MINUTES = 40` | Business default **45** (`dryer_time_minutes`) | **Low** — settings change |
| **Setting key names** | `washing_minutes`, `drying_minutes` | Prefer `wash_time_minutes` / `dryer_time_minutes` or relabel in UI only | **Low** |
| **Shift Layer 2** | 4 activities on old boundaries | Remap after Layer 1 | **High** |
| **Docs** | `RINSE_BAG_GAMING_PERFORMANCE.md` outdated | Update on implementation | Doc debt |

---

## 4. Settings / parameters

| Business label | Target key | Current key | Default | Notes |
|----------------|------------|-------------|---------|-------|
| **Wash Time** | `wash_time_minutes` | `washing_minutes` | **30** | Tenant-configurable; drives `IN_WASHING` expected end |
| **Dryer Time** | `dryer_time_minutes` | `drying_minutes` | **45** | Tenant-configurable; drives `IN_DRYING` expected end; code today defaults **40** |
| Processing weigh/sort/wash/dry seconds | (unchanged) | (same) | 30/180/120/120 | Productivity estimates |
| `reject_after_create_issue_minutes` | (unchanged) | (same) | 45 | Sorting reject |
| Optional grace / max wait thresholds | TBD | — | — | Incoming wait, pending weigh, wait-for-washer |

**Do not hardcode** 30 or 45 in stage logic — read from tenant settings.

---

## 5. Open business questions

### Resolved

Q1–Q3, lifecycle vs LOAD_WASHER/LOAD_DRYER, weighing cleaning start, sorting boundary, folding separation, wash/dryer time defaults — see [Business decisions recorded](#business-decisions-recorded).

### Still open

| ID | Question |
|----|----------|
| Q4 | Incoming wait without portal data — exclude, fallback, or estimate? |
| Q5 | `at_vendor` presence = anchor when sent-to-vendor scan missing? (likely yes — confirm) |
| Q6 | Show expected wash/dry end on dashboard or internal only? |
| Q7 | LOAD_DRYER stays zero-duration performance stage? (likely yes — confirm) |
| Q8 | Staff-performance activity checkbox mapping to new stages |
| Q9 | Rename checkout `logistics_status` vs lifecycle `SENT_TO_RINSE` |
| Q10 | `ORDER_REJECTED_FULL` — freeze stages / exclude from performance denominators? |
| Q11 | Rename setting keys vs UI labels only for wash/dryer time |

---

## 6. Recommended implementation sequence

1. **Remove** `LOAD_WASHER` / `LOAD_DRYER` from `current_lifecycle_status` derivation; map to `IN_WASHING` / `IN_DRYING` with performance sub-detail.
2. **Shared stage primitives** — anchor, ghost filter, valid weight, sorting bounds, presence inputs.
3. **Revise** `rinse_bag_gaming_performance.py` — split stages; weighing = cleaning → post-anchor weight; sorting = lifecycle bounds.
4. **Settings** — `dryer_time_minutes` default 45; UI labels Wash Time / Dryer Time; optional key rename.
5. **Tests** — lifecycle regression; performance stage fixtures; weighing exception without cleaning.
6. **Revise Layer 2** shift gaming; backend APIs; then dashboard (paused frontend untouched until then).

---

## Files out of scope until implementation requested

```text
backend/rinse_bag_gaming_performance.py
backend/rinse_shift_gaming_performance.py
backend/rinse_bag_lifecycle_status.py
frontend/src/pages/ShiftAnalysisDashboardPage.jsx
frontend/src/pages/PerformanceSettingsPage.jsx
frontend/src/utils/shiftAnalysisLabels.js
```

---

*Last updated: 2026-05-24 — final status/stage corrections; implementation pending.*
