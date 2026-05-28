# Folding Performance Dashboard / TV — V2 requirements & phased plan

Org-scoped (VeeWash org 3 first). **Usable UI required** on every phase — not API-only drops.

## Current state (baseline)

| Area | Exists today | Gap vs requirements |
|------|----------------|---------------------|
| Date filter | Week/month toggle + optional custom range on **employee analysis only**; week/month leaderboard/TV use **single anchor date** | Confusing “anchor”; TV/dashboard not unified; no **Today** quick button; default not always Mon–Sun week |
| Excluded users | Table `rinse_folding_excluded_users`, `GET`/`POST` `/rinse/folding/excluded-users`, SQL exclude in leaderboard | **No maintenance UI**; no DELETE; no user dropdown from folding data |
| Folding records | Basic table on dashboard; `GET /rinse/folding/performance` with `start_date`/`end_date`, `user_name`, `status` | **No search** (bag, customer, duration, rates, reviewed, exception code filters) |
| Exceptions | Simple list + override dialog; `GET /rinse/folding/exceptions` (limited filters) | **Not a review queue**; no reviewed/approved workflow; no plain-English reason; no bulk filters |
| Exception rules | Hardcoded `MIN_FOLDING_DURATION_SECONDS = 600` in `rinse_bag_folding.py` | **Not configurable**; no max duration; no per-rule toggles |
| Performance monitoring | Benchmarks in `rinse_folding_settings.py` (bags/hr, lbs/hr, min/bag, quality %) | **No** separate performance flags; no heavy-bag rules; exceptions mixed with underperformance |
| User-wise report | `GET /rinse/folding/employee-analysis` (partial metrics) | Missing exception %, flag counts, reviewed/unreviewed, drill-down tabs |
| TV | `RinseFoldingTvPage` — week/month + `date: today` | No custom range; same anchor confusion |
| Scoring model | `status`: `CALCULATED` \| `EXCEPTION`; `excluded_from_performance` on override | No **`APPROVED`**; approved exceptions still `EXCEPTION` + manual exclude flag |
| Audit | `rinse_folding_performance_overrides` history on override | No dedicated “approve exception” / “mark reviewed” audit events |

**Key files today**

- Backend: `backend/rinse_bag_folding.py`, `backend/rinse_folding_registry.py`, `backend/rinse_folding_routes.py`, `backend/rinse_folding_settings.py`, `backend/rinse_folding_excluded_users.py`
- Frontend: `frontend/src/pages/RinseFoldingDashboardPage.jsx`, `frontend/src/pages/RinseFoldingTvPage.jsx`, `frontend/src/utils/foldingFormat.js`, `frontend/src/api.js`
- Tests: `backend/tests/test_rinse_bag_folding.py`, `backend/tests/test_rinse_folding_registry.py`, `backend/tests/test_rinse_folding_routes.py`

---

## Design principles

1. **One date-range model** shared by dashboard, TV, records, exceptions, employee report (`date_start`, `date_end`, `date_field`).
2. **Two outcome lanes**
   - **Data quality exception** (`EXCEPTION`) — untrusted for gaming unless **approved**.
   - **Performance flag** — valid record, manager attention; **still counts in leaderboard** unless manually excluded.
3. **Gaming inclusion rule**

   ```text
   included_in_scoring =
     status = CALCULATED
     OR (status = APPROVED)   -- admin approved former exception
     AND NOT user in excluded_users
     AND NOT excluded_from_performance (manual bag exclude)
   ```

4. **Raw data always visible** — excluded users and exceptions remain queryable in admin/audit views with filters.

---

## Phase 1 — Date range + records search (UI + API)

**Goal:** Remove anchor wording; default **current week Mon–Sun**; single-day = `start = end`.

### Backend

| Change | Detail |
|--------|--------|
| `GET /rinse/folding/leaderboard` | Add `date_start`, `date_end`, `date_field` (`folding_work_date` \| `date_clean` \| `completed_at`). Keep `period`+`date` as deprecated aliases mapping to range. |
| `GET /rinse/folding/employee-analysis` | Already supports custom range — align param names with leaderboard. |
| `GET /rinse/folding/performance` | Extend `list_folding_performance_rows()` with: `bag_id`, `name_clean` (LIKE), `q` (bag or customer), `duration_min`/`duration_max`, `weight_min`/`weight_max`, `bags_per_hour_min`/`max` (computed or filter post-query), `exception_code`, `reviewed` (bool), `included_in_scoring` (bool), `date_field` for range on `work_date` / join `date_clean` / registry `completed_at`. Return `{ rows, total, limit, offset }`. |
| Shared helper | `backend/rinse_folding_period.py` — `default_week_range(anchor, week_start_day)`, `parse_range_params(request)`, `sql_date_column(date_field)`. |

### Frontend

| Change | Detail |
|--------|--------|
| `frontend/src/components/folding/FoldingDateRangeFilter.jsx` | Start/end dates; buttons **Today**, **This week**, **This month**, **Custom**; optional `date_field` select with clear labels. |
| `RinseFoldingDashboardPage.jsx` | Replace anchor `TextField`; pass same range to leaderboard, records, exceptions, employee sections. |
| `RinseFoldingTvPage.jsx` | Week / month / custom range using same helper (no anchor). |
| `api.js` | Normalize params: `date_start`, `date_end`, `date_field`. |

### Labels (required copy)

- **Folding work date range** (`date_field=folding_work_date` → `rinse_folding_performance.work_date`)
- **Cleaning / processing date range** (`date_field=date_clean` → registry `date_clean`)
- **Completed date range** (`date_field=completed_at` → registry `completed_at`)

### Tests (Phase 1)

- Custom `date_start`/`date_end` returns correct rows for each `date_field`.
- Single-day range (`start = end`) works.
- Leaderboard totals match sum of included CALCULATED rows in range.
- Records search: bag ID, user, status filters.

**Deploy:** No DB migration. No mandatory backfill.

---

## Phase 2 — Excluded users maintenance UI

**Goal:** “Excluded from gaming / leaderboard” under **Performance settings → Maintenance**.

### Backend

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/rinse/folding/excluded-users` | GET | List excluded (exists) |
| `/rinse/folding/excluded-users` | POST | Add (exists) |
| `/rinse/folding/excluded-users` | **DELETE** | Remove by `user_name` or `id` |
| `/rinse/folding/users` | GET | Distinct `assigned_user_name` from `rinse_folding_performance` + recent scan events (for dropdown) |

Ensure `aggregate_folding_leaderboard`, `aggregate_team_folding_stats`, TV path all use `sql_exclude_scoring_users_clause` (already partially done).

### Frontend

| UI | Detail |
|----|--------|
| `FoldingMaintenancePanel.jsx` | Section under dashboard settings: dropdown of users, **Add to excluded**, table of excluded with **Remove** / reason / created_at. |
| Records / employee tables | Show badge **Excluded from gaming** but do not hide rows (audit visibility). |

### Tests (Phase 2)

- Excluded user absent from leaderboard and TV payload.
- Excluded user still returned by `GET /rinse/folding/performance?user_name=...`.
- DELETE removes user from exclude list; user reappears on leaderboard.

---

## Phase 3 — Exception review queue + configurable exception rules

**Goal:** Exceptions are actionable, not just a count.

### DB migration (`rinse_folding_performance_v2.sql`)

Add to `rinse_folding_performance` (or sidecar table if preferred):

| Column | Purpose |
|--------|---------|
| `reviewed_at` | NULL = unreviewed |
| `reviewed_by_user_id` | |
| `scoring_status` | `CALCULATED` \| `EXCEPTION` \| `APPROVED` \| `EXCLUDED` (replaces ambiguous use of `status`+`excluded_from_performance` over time) |
| `included_in_scoring` | Generated/stored boolean for fast queries |
| `exception_review_note` | Short admin note |

Keep `status` + `exception_code` for backward compatibility during transition; recompute sets `scoring_status`.

**Settings** (extend `system_settings` via `rinse_folding_settings.py`):

| Key | Default |
|-----|---------|
| `rinse_folding_min_duration_minutes` | 10 |
| `rinse_folding_max_duration_minutes` | 240 |
| `rinse_folding_rule_multiple_folding_scans` | 1 |
| `rinse_folding_rule_missing_clean` | 1 |
| `rinse_folding_rule_missing_folding` | 1 |

Wire `evaluate_folding_performance_for_bag()` to read settings instead of `MIN_FOLDING_DURATION_SECONDS` constant.

### Backend APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /rinse/folding/exceptions/search` | Full filter set (user, bag, customer, code, date range, reviewed, approved, duration bounds) + pagination |
| `POST /rinse/folding/exceptions/<bag_id>/approve` | Set `APPROVED`, `included_in_scoring=1`, keep `exception_code` for audit |
| `POST /rinse/folding/exceptions/<bag_id>/exclude` | Exclude from gaming (bag-level) |
| `POST /rinse/folding/exceptions/<bag_id>/reviewed` | Set `reviewed_at` without changing scoring |
| `PUT /rinse/folding/settings/exception-rules` | Thresholds + toggles |
| `GET /rinse/folding/settings/exception-rules` | |

Override endpoint remains for reassign / time override; audit via existing `rinse_folding_performance_overrides` + new action types.

### Frontend

| UI | Detail |
|----|--------|
| **Route or tab:** `/rinse/folding-exceptions` or dashboard tab **Folding Exceptions Review** | Filter bar + data grid |
| Row columns | Bag, customer, employee, weight, start/end, duration, code, **plain English reason** (`foldingFormat.exceptionLabel(code)`), reviewed chip |
| Actions | Approve, Exclude from gaming, Reassign, Override times, Admin note, Mark reviewed |
| Links | **Timeline** (existing drawer), **Order detail** (`/rinse/order-search/<bag_id>`) |

### Tests (Phase 3)

- Configurable min duration (e.g. 15 min) produces exception.
- Configurable max duration produces exception when enabled.
- Multiple folding scans → exception when toggle on.
- Approve → `included_in_scoring` true; appears in leaderboard aggregate.
- Unapproved exception → not in leaderboard.
- Mark reviewed sets `reviewed_at` only.

---

## Phase 4 — Performance flags + user-wise report

**Goal:** Management monitoring separate from data exceptions.

### Data model

| Field | Purpose |
|-------|---------|
| `performance_flag_code` | e.g. `BELOW_BAGS_PER_HOUR`, `BELOW_LBS_PER_HOUR`, `SLOW_HEAVY_BAG`, `OVER_MAX_MINUTES_PER_BAG` |
| `performance_flag_detail` | JSON or text (threshold snapshot) |

Computed at recompute or on-read from benchmarks + row metrics. **Does not change `scoring_status` to EXCEPTION.**

### Settings (manager thresholds)

Extend `PUT /rinse/folding/benchmarks` or new `PUT /rinse/folding/settings/monitoring`:

- `bags_per_hour_target` (2.5)
- `lbs_per_hour_target` (40)
- `issue_free_percent_target` (98)
- `minutes_per_bag_target` (24)
- `heavy_bag_weight_lbs` (e.g. 30)
- `heavy_bag_max_minutes` (e.g. 35)
- Underperformance thresholds (optional overrides)

### Backend

| Endpoint | Purpose |
|----------|---------|
| `GET /rinse/folding/employee-report` | Per-user: bags, lbs, hours, bags/hr, lbs/hr, quality %, exception count/%, **flag count**, below-target count, reviewed/unreviewed exception counts |
| `GET /rinse/folding/flags/search` | Performance flags only, filterable |

### Frontend

| UI | Detail |
|----|--------|
| Dashboard sections | **Data Exceptions** (count, unreviewed) vs **Performance Flags** (count, top codes) — separate summary cards |
| **Employee performance** tab | Sortable table; click row → drawer with sub-tabs: Records \| Exceptions \| Flags \| Trend (daily buckets) |

### Tests (Phase 4)

- Slow heavy bag → `performance_flag` set; still `included_in_scoring` if CALCULATED.
- Below bags/hr → flag; still on leaderboard.
- User-wise report counts match filtered rows.

---

## Phase 5 — Backfill org 3 (dry-run / apply)

**Goal:** Apply new rules to existing data without surprise prod writes.

### Script

Extend `scripts/repair_veewash_rinse_data_current_rules.py` or add `scripts/recompute_folding_org_rules.py`:

```bash
python scripts/recompute_folding_org_rules.py --org 3 --date-start YYYY-MM-DD --date-end YYYY-MM-DD --dry-run
python scripts/recompute_folding_org_rules.py --org 3 --date-start ... --date-end ... --apply
```

Steps:

1. Load exception-rule settings from DB.
2. Recompute `rinse_folding_performance` for completed bags in range.
3. Re-apply `scoring_status` / `included_in_scoring` / flags.
4. Report: CALCULATED vs EXCEPTION vs APPROVED deltas; flag counts; excluded users skipped from leaderboard simulation.

**Do not** change scan timestamps.

---

## API summary (target end state)

| Concern | Parameters / endpoints |
|---------|-------------------------|
| Date range | `date_start`, `date_end`, `date_field` on all aggregate/list endpoints |
| Records | `GET /rinse/folding/performance/search` (or extended GET with full filters + `total`) |
| Exceptions | `GET /rinse/folding/exceptions/search` |
| Excluded users | GET / POST / DELETE + `GET /rinse/folding/users` |
| Settings | `GET/PUT /rinse/folding/benchmarks`, `GET/PUT /rinse/folding/settings/exception-rules`, `GET/PUT .../monitoring` |
| Actions | `.../approve`, `.../reviewed`, `.../override` (existing) |

---

## Test matrix (full list — map to phases)

| Test | Phase |
|------|-------|
| Custom date range returns correct rows | 1 |
| Single-day range works | 1 |
| Excluded user not in leaderboard/TV | 2 |
| Excluded user raw records visible | 2 |
| Multiple folding scans → exception (toggle) | 3 |
| Too-short duration uses configurable threshold | 3 |
| Too-long duration uses configurable threshold | 3 |
| Approved exception counts in gaming | 3 |
| Unapproved exception does not count | 3 |
| Performance flag does not auto-exclude from gaming | 4 |
| User-wise exception report counts | 4 |
| Records search by bag/user/status | 1 |
| Exceptions search by user/reason | 3 |

---

## Suggested implementation order & effort

| Phase | User-visible outcome | Relative effort |
|-------|----------------------|-----------------|
| **1** | Clear date ranges everywhere + searchable records | Medium (1–2 PRs) |
| **2** | Maintenance UI for excluded users | Small (1 PR) |
| **3** | Exception review queue + configurable rules + APPROVED | Large (2–3 PRs + migration) |
| **4** | Performance flags + employee drill-down | Large (2 PRs) |
| **5** | Org 3 backfill with dry-run | Small (script + ops) |

**Recommendation:** Ship **1 + 2** together for immediate UX win; then **3** (highest operational value); then **4**; run **5** after **3** rules exist in DB.

---

## Out of scope (this roadmap)

- Washpro / other orgs until VeeWash validated
- Changing Rinse scan-event timezone behavior
- Auto-approving exceptions without admin action
- Deleting folding performance rows (audit retention)

---

## Acceptance checklist (VeeWash)

- [ ] Dashboard default opens to **current week Mon–Sun** with labeled date range
- [ ] TV uses same week/month/custom logic; excluded users hidden from ranks
- [ ] Training Account (or similar) excludable via Maintenance UI
- [ ] Manager can search bag `6QUX3NWKDA` in records
- [ ] Manager can review exceptions, approve one, see it on leaderboard
- [ ] Min folding duration configurable (default 10 min)
- [ ] Dry-run backfill shows counts; apply only after approval
