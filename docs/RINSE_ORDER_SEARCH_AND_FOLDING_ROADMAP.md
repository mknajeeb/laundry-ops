# Rinse / LaundryOps — Order search, folding, and sync roadmap

Assessment as of implementation planning (org-scoped, multi-tenant ready).

## 1. What is currently implemented

| Area | Status | Where |
|------|--------|--------|
| Timezone API (ET ISO offset) | **Done** (commit `99b31a4`) | `backend/rinse_scan_time.py`, Rinse routes use `json_safe_rinse` |
| Portal absence guard (`reached_max_pages`) | **Done** (uncommitted or separate) | `backend/rinse_portal_scrape_meta.py`, `scrape.mjs` meta |
| Scheduled scrape pipeline | **Done** | ACA job, `rinse_scheduled_scrape.py`, `rinse_scrape_runs` |
| Single-bag admin lookup | **Partial** | `/rinse/bags/<id>/detail` (admin), `RinseBagLookupPage` — not full archive search |
| Leaderboard scoring | **Partial** | Only `status=CALCULATED`, `excluded_from_performance=0`, completed registry |
| EXCEPTION in leaderboard | **Excluded** | `aggregate_folding_leaderboard`, TV, team stats SQL |
| Multiple folding scans | **Done** | `MULTIPLE_FOLDING_SCANS` → `STATUS_EXCEPTION` (excluded from leaderboard) |
| Duration &lt; 10 min | **Done** | `FOLDING_DURATION_TOO_SHORT` → `STATUS_EXCEPTION` |
| Excluded folding users table | **Done** | `rinse_folding_excluded_users` + `/rinse/folding/excluded-users` |
| Exception review queue | **Partial** | Existing exceptions list + overrides; dedicated review UI TBD |
| Folding dashboard “anchor date” | **Relabeled** | “Folding work date (period anchor)” in UI |
| Scheduled sync admin status UI | **Done** | `/rinse/scheduled-scrape/status` + `/rinse/scheduled-sync` page |
| Order search archive | **Done (MVP)** | `/rinse/order-search` API + UI |

## 2. Files / tables that will change

### Phase 1 (timezone + sync status)
- `backend/rinse_scrape_status.py` (new)
- `backend/app.py` or `backend/rinse_admin_routes.py` — `GET /rinse/scheduled-scrape/status`
- `frontend/src/pages/RinseScheduledSyncPage.jsx` (new)
- `frontend/src/constants/tenantNav.js`, `App.jsx`, `api.js`
- `docs/RINSE_SCHEDULED_E2E_LOGIC.md` (timing note)

### Phase 2 (order search)
- `backend/rinse_order_search.py` (new)
- `backend/app.py` — `/rinse/order-search`, `/rinse/order-search/<bag_id>`
- `frontend/src/pages/RinseOrderSearchPage.jsx` (new)
- Reuses: `rinse_bag_registry`, `upload_batch_rows`, `orders_staging`, `rinse_folding_performance`, `rinse_scrape_runs`

### Phase 3 (folding exceptions)
- `backend/rinse_bag_folding.py` — new exception codes
- `backend/rinse_folding_registry.py` — review/approve, exception-by-user report
- `frontend` — exceptions review queue, user exception report
- Optional: `rinse_folding_exception_reviews` table

### Phase 4 (excluded users + filters)
- `backend/sql/rinse_folding_excluded_users_v1.sql` (new table)
- `backend/rinse_folding_excluded_users.py` (new)
- Leaderboard/TV SQL joins exclude list
- Dashboard filter rename + `date_clean` / `work_date` / `completed_at` params

## 3. Migrations needed

| Migration | Phase | Required? |
|-----------|-------|-----------|
| `rinse_scrape_runs` | Done | Already deployed |
| `upload_batches.portal_scrape_meta`, `full_snapshot` | Done | Optional SQL file exists |
| `rinse_folding_excluded_users` | 4 | **Yes** for per-tenant user exclude list |
| `rinse_folding_exception_reviews` | 3 | **Optional** — can use overrides + `excluded_from_performance` first |

No migration required for Phase 1–2 if using existing tables only.

## 4. Phased delivery (recommended)

| Phase | Scope | Risk |
|-------|--------|------|
| **1** | Timezone (done) + Scheduled Rinse Sync status panel | Low |
| **2** | `/rinse/order-search` archive API + UI | Medium |
| **3** | Exception rules + review queue + by-user report | Medium |
| **4** | Excluded users + dashboard filter labels/fields | Low–medium |

Do **not** re-import CSVs or recompute folding for timezone-only deploy.

## 5. Scheduled scraper timing (business)

- Cron is **UTC** (`*/30 * * * *`), not Eastern.
- **Data last updated** = last successful run `finished_at` (and batch `confirmed_at`), **not** `started_at`.
- Typical run: start → scrape (~minutes) → draft → auto-confirm → finalize → completion/folding recompute.
- Example: start 6:42 PM, duration 12 min → app data fresh ~6:54 PM.
