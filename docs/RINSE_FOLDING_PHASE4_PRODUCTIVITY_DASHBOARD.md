# Phase 4 — Folding productivity dashboard (clock-first design)

**Status:** Approved design — implementation split into **4B**, **4C**, **4D**.  
**Supersedes:** [RINSE_FOLDING_PRODUCTIVITY_3_MODES.md](./RINSE_FOLDING_PRODUCTIVITY_3_MODES.md) for dashboard UX and management metrics.

**Do not mix with payroll WIP** (accrual, tax engine, payout batches, etc.). Folding productivity changes stay in `rinse_folding_*`, folding dashboard components, and dedicated quality-issue modules.

---

## Main principle

The dashboard answers a **management productivity** question first:

> When this employee was **clocked in**, how many orders/bags and pounds did they process, and at what average **per clocked hour**?

Bag-wise / gaming detail is **second level** — same underlying `rinse_folding_performance` rows, different denominators and override controls.

| Metric family | Denominator | Source |
|---------------|-------------|--------|
| **Productivity (primary)** | Clocked hours | `shift_sessions` via `rinse_folding_user_map` |
| **Gaming / scoring (secondary)** | Sum of bag `duration_seconds` (“folding hours”) | Stored performance rows only |
| **Exception rate** | Bags processed (all completed in range) | `exception_code` / `included_in_scoring` on performance rows |
| **Quality score** | Reported order issues (not scan exceptions) | `rinse_order_quality_issues` + issue types |

**Never** use work-span (first bag start → last bag end) as the primary management view. It is sequence-based, unreliable when scan gaps exist, and is **not** paid time.

---

## Non-negotiable boundaries (all phases)

**Do not change:**

- `folding_start_at` / `folding_end_at` selection (`evaluate_folding_performance_for_bag`, recompute, exception rules)
- Scan parsing, registry, upload/staging/checkout
- Clock-in/out recording in `shift_sessions` (read-only for folding dashboard)

**Record-level gaming include/exclude** (`scoring_override`, `included_in_scoring`) may only affect scoring/gaming aggregates — not stored bag timings, clock time, or scan data.

---

## Current baseline (after Phase 4A revision)

| Delivered | Notes |
|-----------|--------|
| `GET /rinse/folding/user-productivity` | Per **specific** Rinse user: `clocked_productivity` + `gaming_scoring` |
| `rinse_folding_user_map` | Rinse name → `users.id` for clocked mode |
| `FoldingEmployeeProductivityPanel` | Tabs: Clocked productivity \| Gaming/scoring; scoring override on records |
| Work-span | **Removed** from API payload and UI |
| Dashboard user filter | Employee analysis / productivity requires **selected user** — no **All users** team view yet |

**Gap vs this design:** top-level All users / Specific user filter, team aggregation API, four dashboard sections (Productivity / Gaming / Exceptions / Quality), quality issue system, maintenance screens.

---

## Part 1 — Top-level filter (dashboard + employee productivity)

**Location:** Top of **Folding Dashboard** and **Employee Productivity** block (shared state).

| Control | Behavior |
|---------|----------|
| Date range | ET `date_start` / `date_end`; default **today** or current week (Mon–Sun) — reuse `FoldingDateRangeFilter` |
| View | `all_users` \| `specific_user` |
| User dropdown | Enabled when `specific_user`; options from folding users in period (+ mapped employees) |

**Default:** `all_users` + today (or selected ET range).

| View | Primary content |
|------|-----------------|
| **All users** | Team clock-hour summary cards + **user comparison table** (one row per Rinse/mapped user) |
| **Specific user** | That user’s clock-hour cards + shift list + bag-wise/gaming section + record table |

Unmapped Rinse users: show bag-wise + exception stats; clocked section `available: false` with link to **User mapping** maintenance.

---

## Part 2 — Primary stats (clock-wise)

### All users (team)

| Card / metric | Definition |
|---------------|------------|
| Total clocked hours | Sum of overlapping `shift_sessions` net work time in range (mapped users only; document double-count policy if shifts overlap — prefer sum per user then aggregate) |
| Total bags / orders | Completed registry + performance rows in range (dedupe by `bag_id` for team total or sum per-user — **document: sum per user, no cross-user dedupe**) |
| Total lbs | Sum `weight_lbs` on those rows |
| Bags per clocked hour | `total_bags / total_clocked_hours` |
| Lbs per clocked hour | `total_lbs / total_clocked_hours` |
| Scoring bags | `included_in_scoring = 1` |
| Exception bags | Not in scoring |
| Issue-adjusted quality | Phase 4C — team rollup when available |

**User comparison table columns:** user name, mapped?, clocked hours, bags, lbs, bags/hr (clock), lbs/hr (clock), scoring bags, exception bags, exception rate %, quality score (4C), issue count (4C).

### Specific user

| Card / metric | Definition |
|---------------|------------|
| Shifts | List from `shift_sessions` (clock in/out, active estimate label) |
| Total clocked hours | Sum overlap in range (or selected shift) |
| Bags / lbs during clocked time | Performance rows overlapping shift window(s) — **existing overlap rule**, no recompute |
| Bags per clocked hour | `bags / clocked_hours` |
| Lbs per clocked hour | `lbs / clocked_hours` |
| Scoring / exception bags | Same predicates as leaderboard |
| Issue count / quality score | 4C |

**Clocked hours source:** `shift_sessions` (`clock_in_at`, `clock_out_at`, optional `net_work_seconds` if populated; else `clock_out - clock_in - breaks`). Active shift: effective end = last Rinse sync or current ET (existing 4A behavior).

**Bags source:** `rinse_folding_performance` joined to completed `rinse_bag_registry` — **read stored** `folding_start_at`, `folding_end_at`, `duration_seconds`, `weight_lbs`, `included_in_scoring`, `exception_code`, `warning_codes`.

---

## Part 3 — Second level: bag-wise / gaming

Below clock-wise section, always labeled **“Gaming / bag-wise (folding-hour denominator)”**.

### Summary cards

| Metric | Definition |
|--------|------------|
| Total bags folded | All completed performance rows in date filter |
| Scoring bags | `included_in_scoring` |
| Excluded / exception bags | Not in scoring |
| Total lbs / scoring lbs | Weight sums |
| Avg minutes per scoring bag | `sum(duration_seconds scoring) / 60 / scoring_bags` |
| Bags per folding hour | `total_bags / (sum(duration_seconds)/3600)` |
| Lbs per folding hour | `total_lbs / folding_hours` |

### Record table (every bag)

| Column | Source |
|--------|--------|
| Bag ID, customer, weight | Registry + performance |
| Folding start / end, duration | Stored performance |
| Exception / warning | `exception_code` + `warning_codes` (primary + secondary UI) |
| In scoring | `included_in_scoring` |
| Scoring override | `scoring_override` + label |
| Actions | Include in gaming / Exclude from gaming / Clear override (admin) |
| Note / audit | Override history / review note if present |

**Optional diagnostic (not primary):** inter-bag gap minutes on sequence — label *“Sequence gap (diagnostic only — not paid time)”*. No work-span rate cards.

---

## Part 4 — Work-span: dropped as primary

- **Not** a dashboard tab or primary KPI.
- If retained later: collapsible diagnostic under Gaming, per-day only, copy: *“Sequence span: first stored folding start → last stored folding end. Not clock time. Not used for management score.”*
- **Out of 4B** unless explicitly added as hidden diagnostic.

---

## Part 5 — Redefine “Quality” vs “Exception rate”

| Term | Meaning | Data |
|------|---------|------|
| **Exception rate** (or **Scan/process exception rate**) | Share of bags failing folding **scan/process rules** | `rinse_folding_performance`: `status`, `exception_code`, rules |
| **Quality** | Real **order/customer issues** reported later (ReClean, damage, etc.) | New quality issue tables |

Do **not** label exception % as “quality” anywhere in UI.

---

## Part 6 — Quality issue system (Phase 4C / 4D)

### A. Issue type settings — `rinse_quality_issue_types`

| Column | Notes |
|--------|--------|
| `id` | PK |
| `organization_id` | Tenant |
| `code` | Stable key, e.g. `RECLEAN` |
| `label` | Display |
| `active` | |
| `weight` | Penalty points (decimal) |
| `affects_quality_score` | bool |
| `created_at`, `updated_at` | |

**Defaults (seed per org):** `RECLEAN`, `DAMAGE`, `MISSING_ITEM`, `WRONG_ITEM`, `CUSTOMER_COMPLAINT`, `OTHER`.

### B. Order issue log — `rinse_order_quality_issues`

| Column | Notes |
|--------|--------|
| `id` | PK |
| `organization_id` | |
| `bag_id` | FK to registry |
| `assigned_user_name` | Snapshot from performance at save time |
| `user_id` | Nullable; from map if available |
| `issue_type_id` | FK |
| `issue_date` | When problem occurred (optional, date) |
| `reported_at` | When logged in system — **use for lookback window** |
| `notes` | |
| `created_by_user_id` | Admin |
| `voided_at` / `voided_by_user_id` | Soft void; excluded from score |
| `created_at`, `updated_at` | |

**Attribution rule:** On create, resolve `assigned_user_name` from current `rinse_folding_performance.assigned_user_name` for that bag (or explicit override with audit). Store snapshot so later reassignments do not rewrite history.

### C. Settings — `system_settings` or `rinse_folding_settings`

| Key | Default |
|-----|---------|
| `quality_issue_lookback_weeks` | `4` |

Alternative `quality_issue_lookback_days` — weeks preferred for ops communication.

---

## Part 7 — Quality score formula (proposal — confirm before broad rollout)

**Lookback:** Issues where `voided_at IS NULL` and `reported_at >= now - lookback_weeks` (user preference: **reported_at** drives “current accountability” on dashboard).

**Per user** (Rinse name or mapped `user_id`):

```
weighted_points = SUM(issue_type.weight) for active issues in lookback affecting score
issue_count     = COUNT(*) same filter
processed_bags  = completed bags in lookback window attributed to user (folding_work_date or reported_at window — use same date range as dashboard for consistency)

quality_score   = MAX(0, 100 - weighted_points)
```

**Also show (transparent):**

| Display | Purpose |
|---------|---------|
| Issue count | Raw volume |
| Weighted issue points | Explains deductions |
| Quality score | Single number (100 − points) |
| Issues per 100 scoring bags | `issue_count / scoring_bags * 100` (optional rate) |
| Breakdown by issue type | Bar/table |

**Alternative (phase 2 tweak):** Cap penalty per bag (`min(weight, cap)`). Defer unless requested.

**Team rollup (all users):** Sum issues and bags across users; show team score as average of user scores or weighted by bags — **prefer weighted by scoring bags** for fairness.

---

## Part 8 — Dashboard layout (four sections)

For **each user row** (all-users table) and **specific user** page, use stacked sections:

### A. Productivity (primary — expanded by default)

Clocked hours, bags/lbs, bags per clocked hour, lbs per clocked hour.

### B. Gaming / scoring (secondary)

Bag-wise totals, folding-hour rates, link to record table.

### C. Exceptions

| Metric | Formula |
|--------|---------|
| Exception count | Bags not in scoring (or `status = EXCEPTION`) |
| Exception rate | `exception_bags / total_bags` (%) |
| Top reasons | Group by `exception_code` (+ warning_codes in tooltip) |

### D. Quality issues (4C+)

Issue count, weighted points, quality score, type breakdown, “last N weeks” label from setting.

---

## Part 9 — Quality issue entry UI (Phase 4D)

**Screen:** Maintenance → **Order Quality Issues**

| Feature | |
|---------|--|
| Search bag/order | Reuse order search / bag ID |
| Select issue type, notes, issue date | |
| Save | Creates log + attribution |
| Void | Mistake correction |
| Linked user/order | Read-only summary |
| History on Order Search drawer | List issues for `bag_id` |
| History on user dashboard | Filter issues by user |

---

## Part 10 — Parameters / maintenance menu

| Area | Location |
|------|----------|
| Exception rules | Existing `FoldingExceptionRulesPanel` (unchanged ownership) |
| Issue types + weights | New **Quality issue types** panel |
| Lookback weeks | Quality settings |
| Rinse → employee map | Existing `FoldingUserMappingPanel` |

---

## Implementation phases

### Phase 4B — Clock-hour dashboard + All users / specific user + bag-wise gaming

**Goal:** Management-first dashboard without quality tables yet.

#### Backend

| Item | Detail |
|------|--------|
| `GET /rinse/folding/team-productivity` | `date_start`, `date_end`, `date_field` → team summary + `users[]` rows |
| Extend `user-productivity` | Ensure response sections match: `productivity` (clock), `gaming_scoring`, `exceptions` (counts + breakdown) |
| Team clocked hours | Aggregate `shift_sessions` for all **active mappings** in org |
| Per-user row | Clocked + bag metrics; `mapped`, `clocked_available` |
| Bag overlap | Reuse `_bag_overlaps_shift` / existing 4A logic |
| Exceptions block | `exception_count`, `exception_rate`, `exception_by_code` |

#### Frontend

| Item | Detail |
|------|--------|
| Top filter bar | View: All users / Specific user + user dropdown |
| All users | Team cards + comparison table; click row → specific user |
| Specific user | Section A clock cards + shifts; Section B gaming; Section C exceptions; record table with overrides |
| Remove / hide | Work-span tab; any “quality %” from scan exceptions |
| Labels | Every rate shows denominator: “per clocked hour” vs “per folding hour” |

#### Tests (4B)

1. Clock-hour dashboard uses `shift_sessions` (mocked).
2. All-users aggregates clocked hours, bags, lbs.
3. Specific-user filters by `user_name` + date range.
4. Bag-wise scoring excludes exceptions unless override included.
5. Exception rate from folding exceptions only (not quality).
6. Unmapped user: gaming + exceptions ok; clock unavailable.

**Files (expected):**  
`backend/rinse_folding_team_productivity.py`, extend `rinse_folding_user_productivity.py`, `rinse_folding_routes.py`, `FoldingEmployeeProductivityPanel.jsx`, `RinseFoldingDashboardPage.jsx`, tests `test_rinse_folding_team_productivity.py`.

---

### Phase 4C — Quality issue types + logging + user quality score

**Goal:** Data model + APIs + score on user/team payload; minimal UI (inline on dashboard).

#### Backend

| Item | Detail |
|------|--------|
| SQL migrations | `rinse_quality_issue_types`, `rinse_order_quality_issues` |
| Seed defaults | Per org on first access |
| CRUD APIs | Types (admin), issues create/void/list |
| `GET .../quality-summary` | Or embed in team/user productivity: score + breakdown |
| Attribution | On create, pull folder from performance row |
| Lookback | Filter by `reported_at` |

#### Frontend (minimal in 4C)

- Quality section D on dashboard (read-only): score, counts, breakdown.
- No full maintenance screen yet (can use API/admin script).

#### Tests (4C)

7. Quality issue creates order-linked record.
8. Issue attributed to processed/folding user.
9. Issue affects score within lookback (`reported_at`).
10. Issue older than lookback excluded.
11. Issue type weights affect score.
12. Void removes from score.

---

### Phase 4D — Quality maintenance UI + Order Search integration

**Goal:** Operational entry and history surfaces.

| Item | Detail |
|------|--------|
| `OrderQualityIssuesPanel` | Search, add, void, list |
| Settings UI | Types, weights, lookback |
| Order Search drawer | Issue history tab |
| User dashboard | Per-user issue list |
| Audit | `created_by`, `voided_by`, timestamps |

#### Tests (4D)

13. Order Search detail shows issue history (API + component test or route test).

(Add REST tests for void + list filters.)

---

## API sketch (4B)

### `GET /rinse/folding/team-productivity`

```json
{
  "date_start": "2026-05-24",
  "date_end": "2026-05-24",
  "timezone": "America/New_York",
  "team": {
    "clocked_hours": 42.5,
    "total_bags": 310,
    "total_lbs": 4200.5,
    "bags_per_clocked_hour": 7.29,
    "lbs_per_clocked_hour": 98.8,
    "scoring_bags": 280,
    "exception_bags": 30,
    "exception_rate": 0.097
  },
  "users": [
    {
      "user_name": "Jennifer",
      "mapped": true,
      "user_id": 12,
      "clocked_available": true,
      "productivity": { "clocked_hours": 8.0, "total_bags": 55, "...": "..." },
      "gaming_scoring": { "summary": {}, "avg_minutes_per_scoring_bag": 12.1 },
      "exceptions": { "exception_count": 4, "exception_rate": 0.073, "by_code": {} }
    }
  ]
}
```

### `GET /rinse/folding/user-productivity` (aligned shape)

```json
{
  "user_name": "Jennifer",
  "employee_mapping": {},
  "productivity": { "available": true, "summary": {}, "shifts": [] },
  "gaming_scoring": { "summary": {}, "rows": [] },
  "exceptions": { "exception_count": 0, "exception_rate": 0, "by_code": {} },
  "quality": { "available": false }
}
```

Rename `clocked_productivity` → `productivity` in 4B for clarity (keep alias one release if needed).

---

## Test matrix (full list → phase)

| # | Test | Phase |
|---|------|-------|
| 1 | Clock-hour uses `shift_sessions` | 4B |
| 2 | All-users aggregates clocked hours, bags, lbs | 4B |
| 3 | Specific-user filters correctly | 4B |
| 4 | Bag-wise scoring excludes exceptions unless override | 4B |
| 5 | Exception rate from folding exceptions | 4B |
| 6 | Unmapped user clock unavailable | 4B |
| 7 | Quality issue creates order-linked record | 4C |
| 8 | Issue attributed to folding user | 4C |
| 9 | Lookback by `reported_at` | 4C |
| 10 | Issue drops out after lookback | 4C |
| 11 | Weights affect score | 4C |
| 12 | Void removes from score | 4C |
| 13 | Order Search shows issue history | 4D |

---

## Migration notes from old 3-mode doc

| Old mode | New role |
|----------|----------|
| Mode A — Bag-wise | **Gaming / scoring** section (folding-hour denominator) |
| Mode B — Work-span | **Dropped** (diagnostic only if ever revived) |
| Mode C — Clock hours | **Productivity** section (primary) |

---

## Recommended implementation order

1. **4B** — Unblocks managers immediately; no new tables.
2. **4C** — Quality schema + score in API; dashboard section D read-only.
3. **4D** — Entry UI + Order Search + maintenance parameters.

**Parallel constraint:** Exception-rules recompute/WIP and payroll WIP stay in separate PRs/commits from 4B–4D.

---

## Open decisions (defaults chosen)

| Question | Recommendation |
|----------|----------------|
| Lookback anchor | **`reported_at`** (visibility when issue entered) |
| Team bag dedupe | Sum per user (same bag only attributed to one folder) |
| Quality score formula | `100 - sum(weights)` in lookback; show components |
| Rename API keys | `productivity` + `gaming_scoring` in 4B |

Confirm lookback formula with stakeholders before 4C ships to production scorecards tied to compensation.
