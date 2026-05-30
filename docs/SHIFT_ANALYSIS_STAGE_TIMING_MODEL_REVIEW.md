# Shift Analysis — Stage / Timing Model Review

> **Stage / Timing Model — Pending Business Approval**
>
> This document is for business sign-off **before** any implementation. Do not treat as implemented behavior.
>
> **Major conflict confirmed:** Current gaming/performance logic still uses **cleaning-related purpose anchors**. Final lifecycle direction uses **post–sent-to-vendor anchor** and **exact lifecycle sequence**. Until approved and coded, `rinse_bag_gaming_performance.py` may disagree with `rinse_bag_lifecycle_status.py` for the same bag.

**Status:** Documentation only — no code, dashboard, settings UI, or frontend changes implied by this file.

**Related:** [`SHIFT_ANALYSIS_BUSINESS_LOGIC_REVIEW.md`](./SHIFT_ANALYSIS_BUSINESS_LOGIC_REVIEW.md) (§2 processing stages marked pending revision)

---

## Final rules (approved direction, not yet fully implemented in gaming)

| Rule | Meaning |
|------|---------|
| Ghost purpose | Only exact normalized `purpose = cleaning` is ignored |
| Valid cleaning | `purpose = start-cleaning` is valid (not ghost) |
| Completed | Rack name contains `CLEAN` (case-insensitive) |
| Weight entry | Evaluated **after** sent-to-vendor anchor |
| Stage anchors | Processing stages follow **lifecycle sequence**, not cleaning-related heuristics |

---

## 1. Proposed 11-stage timing model

### Stages 1–5

| Field | **1. Incoming wait** | **2. Pending weighing** | **3. Weighing** | **4. Sorting / prep** | **5. Waiting for washer** |
|-------|----------------------|---------------------------|-----------------|----------------------|---------------------------|
| **Business meaning** | Bag assigned in Rinse portal but not yet physically at vendor / not yet sent | Bag at vendor (or sent) but not yet weighed after anchor | Operator task time to weigh the bag (if distinct from queue wait) | Post-weight prep: sort, workitems, photos, split-load, etc., until wash starts | Idle queue between prep complete and washer load |
| **Start event** | `portal_status_first_seen_at` when `portal_status = ready_for_vendor` | Earlier of: first `sent-to-vendor` scan **or** `at_vendor` `portal_status_first_seen_at` | **TBD:** same as pending-weighing end, **or** a distinct prep scan before scale | First **non-ghost** purpose scan strictly after post-anchor `weight-entry` | Sorting/prep end timestamp |
| **End event** | `at_vendor` `portal_status_first_seen_at` **or** first `sent-to-vendor` scan (whichever completes handoff) | First post-anchor `weight-entry` | `weight-entry` (post-anchor) | Last **non-ghost** purpose scan strictly before `start-cleaning` | `start-cleaning` |
| **Purpose/rack markers** | Portal presence only (`ready_for_vendor`, `at_vendor`); optional `sent-to-vendor` scan | `sent-to-vendor`, `weight-entry` | `weight-entry` only | Any non-ghost purpose; excludes exact `cleaning` | `start-cleaning` as boundary only |
| **`cleaning` ghost ignored?** | N/A (no scan timeline) | Yes — ghost `cleaning` dropped from anchored timeline | Yes — **never** use `cleaning` as weighing start | Yes — ghost `cleaning` skipped; `start-cleaning` is **valid** and is sorting **end boundary**, not part of sorting | Yes |
| **Assigned operator** | None (portal/system wait) | None unless business assigns “receiving” role | **weight-entry** operator | Start operator = first post-weight scan user; end operator = last pre–start-cleaning scan user; flag if differ | **start-cleaning** operator (load initiator) or unassigned wait |
| **Duration formula** | `end − start` (portal timestamps) | `weight_entry_ts − max(anchor_ts, at_vendor_ts)` | `weight_entry_ts − weighing_start_ts` (if separate task) | `sorting_end_ts − sorting_start_ts` | `start_cleaning_ts − sorting_end_ts` |
| **Transition / waiting meaning** | Rinse assignment → physical arrival / send scan | Arrival → scale available / operator picks up bag | Active weigh task vs queue wait (see **Q1**) | Active prep work | Physical/logistical gap before wash |
| **Exceptions / needs-review** | Missing `ready_for_vendor` row; `at_vendor` without ever `ready_for_vendor`; portal scrape lag | No post-anchor weight; weight before anchor (ignore or flag); presence without scans | `WEIGHT_ENTRY_MISSING`; duration invalid; **remove** `WEIGHING_START_SCAN_MISSING` tied to cleaning-related | No events after weight but before wash (→ `WEIGHED_NOT_STARTED`); missing `start-cleaning` with long stall; create-issue → reject gate | Excessive wait vs threshold; negative duration if timestamps out of order |
| **Settings / thresholds** | Portal scrape interval tolerance; max incoming wait alert | — | Optional min/max weigh task seconds | `reject_after_create_issue_minutes`; optional max sorting duration | Optional max wait-for-washer minutes |
| **Lifecycle / performance / both** | **Lifecycle** (new timing detail); optional **performance** for vendor SLA | **Both** — maps to `PENDING_WEIGHING` | **Performance** primarily; lifecycle uses weight as milestone only | **Both** — maps to `SORTED_READY_FOR_WASH` | **Performance** + lifecycle sub-stage detail (not a separate lifecycle status today) |
| **Open questions** | Use `first_seen_at` vs `portal_status_first_seen_at`? Count days when bag never reaches vendor? | Is `at_vendor` presence equivalent to anchor when scan missing? | **Q1** (see below) | **Q2** (see below) | Should this appear on dashboard as its own KPI? |

### Stages 6–11

| Field | **6. Load washer** | **7. In washing** | **8. Load dryer** | **9. In drying** | **10. Folding / completion** | **11. Post-completion handoff** |
|-------|-------------------|-------------------|-------------------|------------------|-------------------------------|----------------------------------|
| **Business meaning** | Physical load + washer program setup | Machine wash cycle | Transfer to dryer (instantaneous) | Dryer cycle until ready to fold | Fold + rack to CLEAN | Bag leaves facility / returns to Rinse |
| **Start event** | `start-cleaning` | Latest `ready-washer` or `washer-settings` after `start-cleaning` (load-washer end) | `drying` purpose timestamp | `drying` purpose timestamp | **TBD:** `drying` end or first **FOLDING** rack scan | First **CLEAN** rack scan |
| **End event** | Latest `ready-washer` or `washer-settings` after start | `drying` purpose (first after load end) | Same as start (point-in-time) | First **CLEAN** rack scan | **CLEAN** rack scan | `missing_from_next_portal_scrape` **or** external/non-mapped scan after CLEAN **or** explicit sent-to-rinse signal |
| **Purpose/rack markers** | `start-cleaning`, `ready-washer`, `washer-settings` | `drying` | `drying` | rack contains `CLEAN` | **FOLDING** rack (folding module) + **CLEAN** rack (lifecycle) | Portal absence, external user scan, lifecycle `SENT_TO_RINSE` |
| **`cleaning` ghost ignored?** | Yes | Yes | Yes | Yes | Yes | Yes |
| **Assigned operator** | `start-cleaning` user; load-end user if different → needs-review | Unattended (machine) — no person unless mapped to load-end operator | Drying scan operator | Unattended until fold | Folding module `assigned_user_name` | External scanner or system (portal) |
| **Duration formula** | `load_end_ts − start_cleaning_ts` | If drying seen: `drying_ts − load_end_ts`; else **expected** `load_end_ts + washing_minutes` | `0` (instant) | If CLEAN seen: `clean_ts − drying_ts`; else **expected** `drying_ts + drying_minutes` | `clean_ts − folding_start_ts` (folding rules) or `clean_ts − drying_ts` (lifecycle-only) | `handoff_ts − clean_ts` |
| **Transition / waiting meaning** | Active loading/setup | Machine running | Instant state change | Machine running → ready for fold | Active fold labor | Outbound logistics / Rinse pickup |
| **Exceptions / needs-review** | Missing load-end while in `LOAD_WASHER`; duration bounds | Wash exceeds `washing_minutes` + grace | — | Dry exceeds `drying_minutes` + grace | Full folding exception set (`MISSING_FOLDING`, duration min/max, etc.) | `NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN`; `COMPLETED_WITHOUT_FINAL_CLEAN_SCAN`; checkout without CLEAN |
| **Settings / thresholds** | Optional min/max load-washer seconds | `washing_minutes` (+ optional grace) | — | `drying_minutes` (+ optional grace) | Folding exception rules panel (min/max duration, multiple scans) | Mapped internal users list; portal scrape cadence |
| **Lifecycle / performance / both** | **Both** — `LOAD_WASHER` | **Both** — `IN_WASHING` | **Both** — `LOAD_DRYER` | **Both** — `IN_DRYING` | **Lifecycle:** CLEAN = `FOLDED_COMPLETED`; **Performance:** folding scoring module | **Lifecycle** — `SENT_TO_RINSE`; separate from checkout `logistics_status` |
| **Open questions** | Single vs multiple ready-washer scans? | Show expected vs actual on dashboard? | Keep as zero-duration stage? | Same | **Q3** (see below) | Relationship to facility checkout channel? |

### Proposed anchor summary

```text
Incoming wait:
  ready_for_vendor portal_status_first_seen_at → at_vendor portal_status_first_seen_at or sent-to-vendor

Pending weighing:
  sent-to-vendor / at_vendor → first weight-entry after sent-to-vendor

Weighing:
  TBD — separate operator task vs same window as pending weighing (Q1)
  Do not use purpose = cleaning

Sorting / prep:
  first valid non-ghost purpose after weight-entry → last valid non-ghost purpose before start-cleaning

Waiting for washer:
  sorting/prep end → start-cleaning

Load washer:
  start-cleaning → latest ready-washer or washer-settings after start-cleaning

In washing:
  load washer end → drying
  If drying not yet seen: expected end = load washer end + washing_minutes

Load dryer:
  drying timestamp → drying timestamp (instantaneous)

In drying:
  drying → CLEAN rack
  If CLEAN not yet seen: expected end = drying + drying_minutes

Folding / completion:
  drying or folding start source → CLEAN rack (Q3)

Post-completion handoff:
  CLEAN rack → missing from next portal scrape / external scan after CLEAN / sent-to-rinse signal
```

---

## 2. Conflicts with current code

| Area | Current behavior | Proposed model | Severity |
|------|------------------|----------------|----------|
| **Weighing start** (`rinse_bag_gaming_performance.py`) | `last cleaning-related purpose before weight-entry` via `is_cleaning_related_purpose()` (includes `start-cleaning`, not just ghost) | No cleaning-related heuristic; anchor at sent-to-vendor; optional separate task duration | **High** |
| **Sent-to-vendor anchor** | Gaming evaluates full timeline; first `weight-entry` anywhere | Only post-anchor `weight-entry` counts | **High** |
| **Ghost vs valid cleaning** | Gaming uses broad `is_cleaning_related_purpose`; lifecycle uses exact `cleaning` ghost only | Only exact `cleaning` ghosted; `start-cleaning` valid | **High** |
| **Sorting start** | `weight-entry` or first cleaning-related after weight | First non-ghost scan after post-anchor weight | **Medium** |
| **Sorting end** | Priority: last workitem/issue/bulk → split-load → add-photos → start-cleaning | Last non-ghost before `start-cleaning` (lifecycle `_sorting_bounds_after_weight` style) | **Medium** |
| **Stage granularity** | Gaming: 4 stages (weigh, sort, wash/load, fold) | 11 stages including waits + split wash/dry | **High** |
| **Wash/load combined** | `start-cleaning → drying` single duration | Split: load washer, in washing, load dryer, in drying | **Medium** |
| **Incoming wait** | Not timed; presence flags exist but no duration in lifecycle | Portal `portal_status_first_seen_at` windows | **New** |
| **Waiting for washer** | Implicit inside `SORTED_READY_FOR_WASH` | Explicit performance stage | **New** |
| **Folding** | `rinse_bag_folding.py`: FOLDING rack → CLEAN | Overlaps lifecycle CLEAN with folding scoring | **Medium** |
| **Shift Layer 2** (`rinse_shift_gaming_performance.py`) | 4 activities inherit Layer 1 boundaries | Must map to new stages / activity groupings | **High** — blocked on Layer 1 |
| **Shift analysis pending** | Lifecycle counts; presence not in aggregation | Incoming wait needs presence in pipeline | **Medium** |
| **Docs** | `RINSE_BAG_GAMING_PERFORMANCE.md` still documents cleaning-related weighing/sorting | Contradicts approved direction | **Doc debt** |

**Already aligned in lifecycle module (`rinse_bag_lifecycle_status.py`):** post-anchor timeline, ghost `cleaning` only, load-washer bounds, in-washing/in-drying expected ends, CLEAN = completed, sent-to-rinse rules.

**Old gaming wording to retire:**

```text
Weighing start = last cleaning-related purpose before weight-entry
Sorting start = weight-entry or first cleaning-related after weight
```

---

## 3. Settings / parameters required

| Setting | Exists today? | Needed for |
|---------|---------------|------------|
| `washing_minutes` | Yes | In washing expected end |
| `drying_minutes` | Yes | In drying expected end |
| `reject_after_create_issue_minutes` | Yes | Sorting/prep reject exception |
| `reject_no_start_cleaning_minutes` | Yes (operational module) | Waiting-for-washer stall / legacy reject |
| `processing_weigh_seconds_per_bag` | Yes | Team productivity estimates |
| `processing_sort_seconds_per_bag` | Yes | Team productivity estimates |
| `processing_wash_seconds_per_bag` | Yes | Team productivity estimates |
| `processing_dry_seconds_per_bag` | Yes | Team productivity estimates |
| Wash-load min/max seconds | Code supports `WashLoadLimits`; may not be in UI | Load washer / in-washing duration exceptions |
| **New:** max incoming wait minutes | No | Incoming wait SLA alert |
| **New:** max pending weighing minutes | No | Queue KPI |
| **New:** max wait-for-washer minutes | No | Waiting-for-washer KPI |
| **New:** washing/drying grace minutes | No | Overdue in-wash / in-dry without hard exception |
| **New:** weighing task vs queue mode | No | Resolves Q1 |
| Portal presence timestamps | DB columns exist (`portal_status_first_seen_at`, etc.) | Incoming wait, pending weighing when scan missing |
| Mapped internal users | Used in lifecycle | Post-completion external-scan detection |
| Folding exception rules | Yes | Folding/completion stage only |

---

## 4. Open business questions

### Priority questions (must resolve before implementation)

| ID | Question |
|----|----------|
| **Q1** | Is weighing a **separate operator task**, or the **same window as pending-weighing queue time**? |
| **Q2** | Should sorting end use the **lifecycle boundary** (last non-ghost before `start-cleaning`), or **old gaming end markers** (workitem/issue/bulk priority)? |
| **Q3** | Should folding/completion use **lifecycle CLEAN only**, or **existing FOLDING → CLEAN scoring logic** (`rinse_bag_folding.py`)? |

### Additional questions

| ID | Question |
|----|----------|
| Q4 | Incoming wait without portal data: fall back to first scan only, exclude from timing, or estimate from batch upload time? |
| Q5 | Is `at_vendor` presence equivalent to sent-to-vendor anchor when scan is missing? |
| Q6 | Display expected end on dashboard for IN_WASHING / IN_DRYING, or internal only? |
| Q7 | Keep load dryer as zero-duration stage, or merge into in-drying for performance? |
| Q8 | Remap staff-performance checkboxes from 4 activities to stage groups (e.g. “prep” = pending weigh + weigh + sort)? |
| Q9 | Rename or relabel facility `logistics_status = SENT_TO_RINSE` vs lifecycle `SENT_TO_RINSE` before UI work? |
| Q10 | Does `ORDER_REJECTED_FULL` freeze stage progression and exclude bags from performance denominators? |

---

## 5. Recommended implementation sequence

1. **Business sign-off** on this document (especially **Q1–Q3**).
2. **Shared stage primitives** — single source for lifecycle + performance: anchor resolution, ghost filtering, per-stage bound helpers, presence inputs.
3. **Revise Layer 1** (`rinse_bag_gaming_performance.py`) — replace cleaning-related heuristics; align sorting with lifecycle bounds; split wash/dry; add wait stages.
4. **Wire presence** — pass `portal_status_first_seen_at` / transition fields into stage builder for incoming wait + pending weighing.
5. **Tests** — bag fixtures per stage; regression vs lifecycle status; edge cases (ghost cleaning, pre-anchor weight, presence-only bags).
6. **Update docs** — `RINSE_BAG_GAMING_PERFORMANCE.md`; finalize §2 in `SHIFT_ANALYSIS_BUSINESS_LOGIC_REVIEW.md`.
7. **Revise Layer 2** (`rinse_shift_gaming_performance.py`) — activity mapping to new stages; shift-window metrics.
8. **Backend APIs** — expose stage timings in shift-analysis payload (no dashboard UI yet).
9. **Dashboard / settings / labels** — only after steps 1–8. Paused frontend files remain untouched until business approval.

---

## Files explicitly out of scope until sign-off

Do not change until this model is approved and implementation begins:

```text
backend/rinse_bag_gaming_performance.py
backend/rinse_shift_gaming_performance.py
backend/rinse_bag_lifecycle_status.py
frontend/src/pages/ShiftAnalysisDashboardPage.jsx
frontend/src/pages/PerformanceSettingsPage.jsx
frontend/src/utils/shiftAnalysisLabels.js
```

---

*Last updated: 2026-05-24 — pending business approval; no implementation.*
