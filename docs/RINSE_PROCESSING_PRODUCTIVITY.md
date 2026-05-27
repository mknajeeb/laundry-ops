# Processing productivity role — implementation plan

**Status:** Proposed — **awaiting approval** before implementation commit.  
**Scope:** New **Processing** role alongside **Folding**; no changes to folding recompute, exception rules, or payroll WIP.

---

## Purpose

| Role | Who | Signal |
|------|-----|--------|
| **Folding** | Folder | `rinse_folding_performance` (FOLDING → CLEAN interval) |
| **Processing** | Sort / weigh / wash / dry (pre-fold) | `rinse_bag_scan_events` where **purpose = start-cleaning** |

Management questions are separate:

- **Folding:** bags/lbs per **clocked hour** while folding (existing / Phase 4B).
- **Processing:** bags/lbs per **clocked hour** while processing + estimated minutes per bag from configurable assumptions.

---

## Hard boundaries

| In scope | Out of scope |
|----------|----------------|
| Read `rinse_bag_scan_events`, `rinse_bag_registry`, `shift_sessions` | Change `evaluate_folding_performance_for_bag`, folding recompute |
| Read `rinse_folding_user_map` (reuse) | Infer wash/dry completion from other purposes |
| `system_settings` keys for processing seconds | Folding exception rules, quality issues (4C) |
| New `/rinse/processing/*` routes + UI section | Payroll WIP files |

---

## Data: start-cleaning identification

Reuse the same normalization as upload logic (`rinse_scan_events_logic.apply_scan_event_logic`):

```text
purpose_norm = lowercase, collapse whitespace, strip trailing "last <word>"
is_start_cleaning = "start-cleaning" in purpose_norm
```

**Implementation:** `backend/rinse_scan_purpose.py`

- `normalize_scan_purpose(raw: str) -> str`
- `is_start_cleaning_purpose(raw: str) -> bool`

**SQL load (indexed filter + Python verify):**

```sql
SELECT e.id, e.bag_id, e.user_name, e.purpose, e.scanned_at_parsed, e.scan_index,
       r.name_clean, r.weight_num
FROM rinse_bag_scan_events e
LEFT JOIN rinse_bag_registry r
  ON r.organization_id = e.organization_id AND r.bag_id = e.bag_id
WHERE e.organization_id = %s
  AND e.scanned_at_parsed >= %s
  AND e.scanned_at_parsed < %s   -- exclusive end of range (ET)
  AND LOWER(e.purpose) LIKE '%start-cleaning%'
```

Post-fetch: drop rows where `is_start_cleaning_purpose(purpose)` is false (handles odd casing / “last scan” suffix).

**ET date range:** `scanned_at_parsed` is naive ET wall time. Filter with `period_datetime_bounds_et` + exclusive end (`naive_et_day_end_exclusive(period_end + 1 day)`). Assign **work date** = `scanned_at_parsed.date()` for grouping.

---

## Dedupe rule (default)

**One processing bag per `(organization_id, bag_id, user_name)` in the requested date range.**

If multiple start-cleaning scans exist for the same bag/user in range:

- Keep the **earliest** `scanned_at_parsed` (tie-break `scan_index`, `id`).
- Others are omitted from counts; optional `duplicate_scan_ignored: true` on the kept row’s metadata for audit.

**Setting (future-proof, default off):** `processing_allow_duplicate_scans_per_bag` — not required for v1; document as always dedupe.

**Test #2:** duplicate scans → single bag in totals.

---

## Estimated processing time (configurable)

**Storage:** `system_settings` (same pattern as `rinse_folding_settings.py`).

| Key | Default (seconds) |
|-----|-------------------|
| `processing_weigh_seconds_per_bag` | 30 |
| `processing_sort_seconds_per_bag` | 180 |
| `processing_wash_seconds_per_bag` | 120 |
| `processing_dry_seconds_per_bag` | 120 |

**Total default:** 450 s = **7 min 30 sec** per bag.

**Module:** `backend/rinse_processing_settings.py`

- `get_processing_settings(cursor, org) -> dict` (seconds + computed `total_seconds_per_bag`, `total_minutes_per_bag`)
- `put_processing_settings(cursor, org, payload) -> dict`

**Per record:**

```text
estimated_processing_seconds = sum of four configured components
estimated_processing_minutes   = seconds / 60
```

**Bag-level aggregates:**

```text
total_estimated_processing_seconds = sum(estimated_processing_seconds) over deduped bags
estimated_processing_hours         = total_estimated_processing_seconds / 3600
bags_per_estimated_processing_hour = total_bags / estimated_processing_hours
lbs_per_estimated_processing_hour  = total_lbs / estimated_processing_hours
avg_estimated_minutes_per_bag      = total_estimated_processing_seconds / 60 / total_bags
```

---

## Clock-hour logic (mapped users)

**Reuse:** `rinse_folding_user_map` → `user_id` → `shift_sessions` (same as Folding 4A).

**Do not modify** `rinse_folding_user_productivity.py` in v1. **Copy/adapt** read-only helpers into `rinse_processing_productivity.py`:

- `_load_shift_sessions`, `_shift_effective_clock_out`, overlap clip to period
- Active shift end = last Rinse sync or current ET (same labels)

**Bag-in-shift rule (Processing-specific):**

```text
scan_time = start_cleaning scanned_at_parsed
included in shift if clock_in <= scan_time <= effective_clock_out
```

(No folding_start_at / folding_end_at.)

**Unmapped user:**

- `clocked_productivity.available = false`
- Message: *"No employee clock mapping for this Rinse user."*
- Bag-level stats still returned

**Team / all-users:** Sum clocked hours per mapped user; sum bags/lbs from deduped processing records (per-user attribution, no cross-user bag dedupe at team level).

---

## API

### `GET /rinse/processing/productivity`

| Query | Notes |
|-------|--------|
| `date_start`, `date_end` | Required ET calendar range |
| `user_name` | Optional; omit for **all users** |
| `shift_id` | Optional (specific user + mapped) |
| `shift_filter` | `all` \| `active` \| `completed` |
| `include_unmapped` | default `true` — include users with scans but no map in `users[]` |

**Response shape:**

```json
{
  "role": "processing",
  "date_start": "2026-05-24",
  "date_end": "2026-05-24",
  "timezone": "America/New_York",
  "settings": {
    "processing_weigh_seconds_per_bag": 30,
    "processing_sort_seconds_per_bag": 180,
    "processing_wash_seconds_per_bag": 120,
    "processing_dry_seconds_per_bag": 120,
    "total_seconds_per_bag": 450,
    "total_minutes_per_bag": 7.5
  },
  "summary_all_users": {
    "clocked_hours": 40.0,
    "total_bags": 200,
    "total_lbs": 3000.0,
    "bags_per_clocked_hour": 5.0,
    "lbs_per_clocked_hour": 75.0,
    "total_estimated_processing_minutes": 1500.0,
    "estimated_processing_hours": 25.0,
    "bags_per_estimated_processing_hour": 8.0,
    "lbs_per_estimated_processing_hour": 120.0
  },
  "users": [
    {
      "user_name": "Alex",
      "employee_mapping": { "mapped": true, "user_id": 5 },
      "clocked_productivity": { "available": true, "summary": {}, "shifts": [] },
      "bag_level": { "summary": {} },
      "records": []
    }
  ],
  "records": []
}
```

When `user_name` is set: top-level `records` = that user’s rows; `users` may be a single-element list or omitted (prefer single user block + `records` for table).

**Record object:**

| Field | Source |
|-------|--------|
| `bag_id`, `customer`, `weight_lbs` | Registry |
| `start_cleaning_at` | Scan time |
| `scan_user_name` | `user_name` on event |
| `scan_event_id` | `rinse_bag_scan_events.id` |
| `estimated_processing_minutes` | Settings sum |
| `shift_linked` | Overlaps any shift in period |
| `included_in_processing_count` | `true` (v1; reserved) |
| `order_detail_path` / `timeline_bag_id` | UI builds links to existing order drawer |

### `GET /rinse/processing/settings`

Returns seconds + derived minutes for display.

### `PUT /rinse/processing/settings`

Admin; body accepts seconds fields; validates `>= 0`.

**Routes file:** `backend/rinse_processing_routes.py` — register blueprint in `app.py` next to folding routes.

**Permissions:** Same as folding productivity (`rinse` read / admin for PUT settings).

---

## Backend modules (new files only)

| File | Responsibility |
|------|----------------|
| `rinse_scan_purpose.py` | Purpose normalization + `is_start_cleaning` |
| `rinse_processing_settings.py` | Tenant settings get/put |
| `rinse_processing_productivity.py` | Load scans, dedupe, aggregates, clock overlap |
| `rinse_processing_routes.py` | HTTP handlers |
| `tests/test_rinse_processing_productivity.py` | Tests 1–8 |
| `tests/test_rinse_processing_routes.py` | Test 9 (links in JSON / route smoke) |

**Optional shared refactor (defer):** `rinse_clock_sessions.py` extracted from folding — **not in v1** to avoid touching folding.

---

## Frontend

### Employee Productivity — role switch

**Component:** `EmployeeProductivitySection.jsx` (new wrapper on dashboard)

| Control | Behavior |
|---------|----------|
| Role | **Folding** \| **Processing** |
| View | All users / Specific user (Processing: same as Phase 4B plan) |
| Date range | Existing `FoldingDateRangeFilter` |

- **Folding** → existing `FoldingEmployeeProductivityPanel` (unchanged behavior).
- **Processing** → new `ProcessingEmployeeProductivityPanel.jsx`.

### Processing panel sections

1. **Clock-level** (if mapped): Processing bags, Processing lbs, bags/lbs per clocked hour, clocked hours, shifts.
2. **Bag-level:** totals, estimated processing minutes/hours, bags/lbs per estimated processing hour, avg min/bag.
3. **Record table** with columns from spec; actions: Order detail, Scan timeline (existing drawer callbacks).

**Labels (required):** Never say “Folding” in Processing section. Use *Processing bags*, *Processing lbs*, *Estimated processing minutes*, *Estimated processing hours*, *Bags per clocked hour*, etc.

### Maintenance

`FoldingMaintenancePanel.jsx` → add subsection **Processing time assumptions** (`ProcessingSettingsPanel.jsx`):

- Weigh / sort / wash / dry — UI in minutes+seconds, API in seconds.
- Show computed total per bag (7:30 default).

**API client:** `frontend/src/api.js` — `getProcessingProductivity`, `getProcessingSettings`, `putProcessingSettings`.

---

## Tests (mapped to your list)

| # | Test | Module |
|---|------|--------|
| 1 | start-cleaning scans count as processing bags | `test_rinse_processing_productivity.py` |
| 2 | Duplicate start-cleaning same bag/user/range → one bag | same |
| 3 | ET range excludes prior-day scans | same |
| 4 | Estimated time uses configurable seconds | same + settings |
| 5 | Clock-hour stats use `shift_sessions` | same (mock shifts) |
| 6 | Unmapped → bag stats, no clock summary | same |
| 7 | Mapped → clock summary present | same |
| 8 | PUT settings changes estimated minutes | settings test |
| 9 | Record includes `bag_id` for order/timeline links | route/record shape test |

---

## Implementation steps (single focused commit after approval)

1. `rinse_scan_purpose.py` + unit tests for normalization edge cases.
2. `rinse_processing_settings.py` + GET/PUT routes.
3. `rinse_processing_productivity.py` — load, dedupe, aggregates, clock overlap.
4. `rinse_processing_routes.py` — productivity endpoint.
5. `test_rinse_processing_productivity.py` (tests 1–8).
6. Frontend: API helpers, `ProcessingSettingsPanel`, `ProcessingEmployeeProductivityPanel`, `EmployeeProductivitySection` wrapper on dashboard.
7. Doc cross-link from [RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md](./RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md) — add Processing as parallel role.

**Estimated size:** ~800–1200 LOC backend+frontend+tests (no new DB tables).

---

## Open decisions (defaults)

| Question | Proposal |
|----------|------------|
| Dedupe | Earliest start-cleaning per bag/user/range |
| Weight source | `rinse_bag_registry.weight_num`; null if missing |
| All-users API | Omit `user_name` on same endpoint |
| Map table name | Keep `rinse_folding_user_map` (shared); UI label “Rinse user → employee” |
| Processing exceptions | None in v1; no `included_in_processing_count` toggles yet |
| Index | v1 relies on `(organization_id, scanned_at_parsed)` + purpose LIKE; add composite index later if slow |

---

## What we will not do in this commit

- Payroll / accrual / tax files
- Changes to `rinse_bag_folding.py`, `rinse_folding_registry` recompute, exception rules
- Folding dashboard behavior changes (except wrapping productivity in role toggle)
- Persisted `rinse_processing_performance` table (compute-on-read v1)
- Wash/dry purpose inference

---

## Approval

Reply **approved** (or note changes to dedupe/weight/API shape) to proceed with implementation in one focused commit.
