# Rinse scheduled scrape → LaundryOps E2E logic

Production behavior as implemented in this repo, with **organization_id = 3** (`tenant_slug = veewash`) as the reference tenant. Section 12 uses live production counts from the latest successful scheduled run.

---

## Tenant-specific vs shared

| Tenant-specific | Shared (all orgs) |
|-----------------|-------------------|
| `RINSE_SCHEDULED_ORG_IDS` entry (`3` for VeeWash) | ACA job `rinse-scrape-scheduled`, image `laundryops-rinse-scheduler` |
| `resolve_rinse_vendor()` → `veewash` scripts | `backend/rinse_scheduled_scrape.py`, `commit_rinse_combined_upload`, `confirm_upload_batch_core`, `finalize_rinse_after_batch_confirm` |
| Azure Files: `tenants/veewash/.env`, `rinse-auth.json` | Node scrapers `scripts/rinse-cleanertickets/scrape.mjs`, `scrape-scan-events.mjs` |
| Per-org run folders `runs/org_3_veewash/...` | MySQL tables (`rinse_scrape_runs`, `upload_batches`, `rinse_bag_registry`, …) |
| Per-org `GET_LOCK(rinse_scrape_org_3)` | Completion rule, folding math, confirm/finalize code paths |
| `RINSE_VEEWASH_ORG_IDS`, `RINSE_VEEWASH_STORAGE_STATE`, tickets URL in veewash `.env` | Manual UI upload uses the same confirm core |

Washpro (`organization_id = 1`) uses the same pipeline when added to `RINSE_SCHEDULED_ORG_IDS` with `tenants/washpro/` auth.

---

## 1. Scheduled scraper logic

### How the ACA job starts

- **Azure Container Apps job:** `rinse-scrape-scheduled` in resource group `mkn_resgrp_centralus`.
- **Schedule:** cron `*/30 * * * *` in **UTC** (not Eastern).
- **Container command:** `python -m backend.jobs.run_scheduled_rinse_scrape` (`Dockerfile.rinse-scheduler` `CMD`).
- **Entry module:** `backend/jobs/run_scheduled_rinse_scrape.py` → `run_all_scheduled_scrapes()` in `backend/rinse_scheduled_scrape.py`.

### Image / command

| Item | Value |
|------|--------|
| Image | `laundryopsacr.azurecr.io/laundryops-rinse-scheduler:v4` (see `Dockerfile.rinse-scheduler`) |
| Working dir | `/app` (repo copied: `backend/`, `scripts/rinse-cleanertickets/`, `scripts/rinse-tenants/`) |
| Playwright | `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, Chromium installed at build |
| Python | venv `/opt/laundry_venv` |

Per org, bash wrappers run Node:

- `scripts/rinse-tenants/veewash/run-production-scrape.sh` → `node scrape.mjs` (portal CSV)
- `scripts/rinse-tenants/veewash/run-scan-events.sh` → `node scrape-scan-events.mjs` (tickets + events CSVs)

Both source `scripts/rinse-tenants/_tenant-env.sh`, which loads tenant `.env` and sets `RINSE_STORAGE_STATE`.

### Environment variables (job + tenant)

| Variable | Role |
|----------|------|
| `RINSE_SCHEDULED_SCRAPE_ENABLED=1` | Master gate; job exits if unset |
| `RINSE_SCHEDULED_ORG_IDS` | Comma/semicolon/space list of org IDs processed **sequentially** (v1: `3`) |
| `RINSE_VEEWASH_ORG_IDS` | Legacy fallback if `RINSE_SCHEDULED_ORG_IDS` empty; maps org 3 → vendor `veewash` |
| `RINSE_SCRAPE_DATA_ROOT` | Mount root, e.g. `/data/rinse-scrape` on Azure Files share `rinse-scrape-data` |
| `RINSE_VEEWASH_STORAGE_STATE` | Absolute path to `rinse-auth.json` on the volume |
| `MYSQL_*` | Same DB as API |
| `RINSE_SCRAPE_TIMEOUT_SEC` | Subprocess timeout per bash script (default 1800s) |
| `RINSE_SCRAPE_STALE_MINUTES` | Stale `running` rows cleared before lock (default 120) |
| `RINSE_MAX_PAGES` | Portal + scan-events page cap (orchestrator default 20 if unset; veewash `.env` on share often `20`) |
| Tenant `.env` | `RINSE_TICKETS_URL`, email/password optional, layout, selectors |

Orchestrator also sets per run: `OUTPUT_CSV`, `OUTPUT_SCAN_TICKETS_CSV`, `OUTPUT_SCAN_EVENTS_CSV`, `RINSE_TENANT_DATA_DIR`, `RINSE_CSV_LAYOUT=portal`.

### `RINSE_SCHEDULED_ORG_IDS`

- Parsed by `parse_scheduled_org_ids()` in `rinse_scheduled_scrape.py`.
- Example v1: `3` only (VeeWash).
- Future: `1,3` runs org 1 then org 3 in one job execution; **each org has its own lock and run folder**.

### One org vs multiple orgs

- `run_all_scheduled_scrapes()` loops org IDs in order.
- Failure in one org sets exit code `1` but later orgs still run unless the process is killed.
- `needs_attention` for any org sets exit code `3` if no hard failures.

### Where `.env` and `rinse-auth.json` are read

1. **Server/ACA:** `RINSE_TENANT_DATA_DIR` → `{RINSE_SCRAPE_DATA_ROOT}/tenants/veewash/` (see `_tenant-env.sh`).
2. **Local dev:** `scripts/rinse-cleanertickets/tenants/veewash/` unless `RINSE_TENANT_DATA_DIR` overrides.
3. **Auth file:** `RINSE_STORAGE_STATE` from `.env`, resolved to absolute path under tenant dir.

### Output files and logs

Under `{RINSE_SCRAPE_DATA_ROOT}/runs/org_3_veewash/{YYYY-MM-DD}_{HHMMSS}_scheduled/`:

| File | Source |
|------|--------|
| `portal.csv` | `scrape.mjs` |
| `scan-events-tickets.csv` | `scrape-scan-events.mjs` (ticket list export) |
| `scan-events-events.csv` | `scrape-scan-events.mjs` (per-bag scan timeline) |
| `orchestrator.log` | Python `_TeeLog` + subprocess stdout/stderr |

`rinse_scrape_runs.log_path` stores this log path; CSV paths stored on finish (note: `scan_events_csv_path` column currently receives tickets path in `finish_scrape_run` call — events path is in `scan_events_events_path`).

### Overlap / locking

`backend/rinse_scrape_runs.py`:

1. Marks stale `status='running'` older than `RINSE_SCRAPE_STALE_MINUTES` as `failed`.
2. If another `running` row exists for the org → **skip** (`insert_skipped_scrape_run`, no scrape).
3. `GET_LOCK('rinse_scrape_org_<id>', 0)` — non-blocking; failure → skip.
4. `insert_scrape_run` → `status='running'`.
5. `finally`: `finish_scrape_run` + `RELEASE_LOCK`.

Different orgs use different lock names; VeeWash and Washpro can run in parallel only if scheduled in separate job instances — **one job processes orgs sequentially**.

### `rinse_scrape_runs` row lifecycle

| When | What |
|------|------|
| Lock not acquired | `insert_skipped_scrape_run` — immediate `skipped` row |
| Lock acquired | `insert_scrape_run` — `running` |
| Pipeline end | `finish_scrape_run` updates final status |

Table DDL: `backend/sql/rinse_scrape_runs_v1.sql`, ensured in `ensure_rinse_scrape_runs_table()`.

### Run `status` values

| status | Meaning |
|--------|---------|
| `running` | In progress (should be brief; stale cleanup applies) |
| `success` | Scrape + draft import OK; **auto-confirm ran** (0 `NEEDS_ATTENTION`) |
| `needs_attention` | Draft created; **not** auto-confirmed (`NEEDS_ATTENTION` > 0) |
| `failed` | Scrape/import/confirm error, empty CSV, or all portal rows rejected |
| `skipped` | Lock held or prior run still `running` |

`imported_batch_id` = `upload_batches.batch_id` when draft was created (even if confirm failed before commit — on failure transaction rolls back but finish still records last attempted batch id if set).

---

## 2. Scrape logic

### Portal CSV (`scrape.mjs`)

- **URL:** `RINSE_TICKETS_URL` or default `https://www.rinse.com/cleanertickets/?page=1`.
- **Login:** `rinse-auth.json` via `RINSE_STORAGE_STATE`, or `RINSE_EMAIL` / `RINSE_PASSWORD`.
- **Pagination:** `page` from `RINSE_PAGE_START` (default 1) for up to `RINSE_MAX_PAGES` iterations; builds `urlForPage(baseUrl, p)`.
- **Stop early:** empty table, pagination redirect/wrap, duplicate page fingerprint, duplicate bag-id signature.
- **Layout:** `RINSE_CSV_LAYOUT=portal` (Excel-style columns + Bag ID) for scheduled runs.
- **Session expired:** `isLikelyLoginPage()` → stderr message, **exit code 3**, no CSV.

### Scan-events (`scrape-scan-events.mjs`)

- Same cleaner-tickets base URL; expands each ticket row and exports scan columns.
- **Outputs:** tickets CSV (bag list) + events CSV (Bag ID, Scan Index, Rack, Time Scanned, User, …).
- **Pagination:** same `RINSE_PAGE_START` / `RINSE_MAX_PAGES` loop over list pages.
- Scheduled orchestrator requires **events** file `scan-events-events.csv` with ≥ 1 data row.

### `RINSE_MAX_PAGES`

- Hard cap per run (max 500 in script); orchestrator passes **20** by default for ACA if not in process env.
- Does not guarantee that many pages exist — stopping rules apply first.
- Increasing pages increases runtime (risk vs 30-minute cron).

### Zero rows / missing files (orchestrator)

| Condition | Result |
|-----------|--------|
| Portal subprocess non-zero | `failed`, rollback |
| Portal file missing or 0 data rows | `RuntimeError` → `failed` |
| Portal parses to 0 order rows | `failed` |
| Scan-events subprocess non-zero | `failed` |
| Scan-events file missing or 0 data rows | `failed` |
| Scan-events parse warnings only | Draft may still proceed |

Empty scan-events on **confirm** blocked by `validate_batch_confirm_dual_csv` (dual CSV required for Rinse combined uploads).

---

## 3. Upload batch creation logic

### Functions and tables

| Step | Code | Table |
|------|------|-------|
| Dual commit | `commit_rinse_combined_upload()` — `backend/rinse_combined_upload.py` | |
| Draft shell | `create_draft_upload_batch_shell()` | `upload_batches` (`state=DRAFT`) |
| Portal rows | `insert_upload_batch_rows_from_orders_df()` | `upload_batch_rows` |
| Scan audit | `commit_scan_events_for_batch()` — `backend/rinse_scan_events_upload.py` | `upload_batch_scan_events` |

**Important:** Draft does **not** write `rinse_bag_scan_events` or recompute completion. Docstring on `commit_rinse_combined_upload` that mentions pre-classification recompute is **outdated**; confirm path owns persistence.

### Parsing

- **Portal:** `portal_csv_to_orders_df()` — `backend/rinse_portal_csv.py` → columns `Date_Clean`, `Name_Clean`, `ticket_id`, etc.
- **Scan-events:** `parse_scan_events_csv()` — validates `Bag ID` + scan columns, normalizes times.

### `commit_rinse_combined_upload` order

1. `snapshot_pre_upload_completed_bag_ids()` — registry `COMPLETED` **before** any writes in this transaction.
2. Create `upload_batches` draft (`batch_date` = America/New_York “today” for scheduled).
3. Insert `upload_batch_rows` from portal dataframe.
4. Replace `upload_batch_scan_events` for batch (`DELETE` then `INSERT`).
5. `conn.commit()` — returns `batch_id`, row counts, `finalize_on_confirm: true`.

### Persistent scan-events (on confirm only)

`finalize_rinse_after_batch_confirm()` → `merge_scan_events_from_upload()` — `backend/rinse_bag_registry.py`:

- Table: `rinse_bag_scan_events`
- Upsert key: `(organization_id, bag_id, dedupe_key)` from `compute_scan_event_dedupe_key()`
- Re-uploading the **same** logical scan updates metadata; does **not** duplicate rows
- Rows without parseable `Time Scanned` are skipped at merge time

Draft table `upload_batch_scan_events` is replaced on each draft commit for that batch (`replace_existing=True`); re-scraping creates a **new** batch id with a fresh audit copy.

---

## 4. Row classification logic

Classification at draft insert: `classify_portal_upload_row()` — `backend/rinse_bag_completion.py`, called from `insert_upload_batch_rows_from_orders_df()`.

### Pre-upload completed snapshot

`fetch_pre_existing_completed_bag_ids()` reads `rinse_bag_registry` where `completion_status = 'COMPLETED'` for portal bag IDs **before** insert. Completion discovered from scan-events **during the same upload** is **not** in this set.

### Portal rows with `ticket_id` (bag-controlled)

| row_status | reason | When |
|------------|--------|------|
| `ACCEPTED` | `OK` | Not completed before upload; no active staging; date ≥ batch_date |
| `ACCEPTED` | `UPDATED_EXISTING_BAG` | Active staging exists for same `ticket_id` |
| `REJECTED_DUPLICATE` | `ALREADY_COMPLETED` | Registry was `COMPLETED` **before** this upload started |
| `NEEDS_ATTENTION` | `OLDER_THAN_BATCH_DATE` | `date_clean` < `upload_batches.batch_date` |

**Confirmed:** A bag that becomes `COMPLETED` during confirm (clean rack in merged scan-events) **stays `ACCEPTED`** on its portal row. Rejection uses only the pre-upload snapshot.

### Portal rows without bag id (identity path)

Uses `build_identity_key(name, weight, service, date)` vs `orders_final` / prior batches:

| row_status | reason | When |
|------------|--------|------|
| `ACCEPTED` | `OK` | New identity |
| `NEEDS_ATTENTION` | `OLDER_THAN_BATCH_DATE` | Date before batch_date |
| `REJECTED_DUPLICATE` | `ALREADY_IN_FINAL` | Identity in final orders |
| `REJECTED_DUPLICATE` | *(from index)* | e.g. prior batch duplicate reasons in `existing_identity_reasons` |

### UI-only row statuses (`backend/app.py` upload routes)

| row_status | reason | When |
|------------|--------|------|
| `OVERRIDDEN` | `OVERRIDDEN_BY_USER` | Admin override |
| `NEEDS_ATTENTION` | *(varies)* | Manual flag |
| `DELETED` | `OVERRIDDEN` / soft-delete paths | User removed row from batch |

---

## 5. Auto-confirm logic

### When scheduled scraper auto-confirms

After draft commit, `run_scheduled_scrape_for_org()`:

- If `accepted` portal rows **< 1** → rollback, `failed` (“All portal rows rejected”).
- If `NEEDS_ATTENTION` count **> 0** → commit draft, `rinse_scrape_runs.status = needs_attention`, **no confirm**.
- If `NEEDS_ATTENTION = 0` → `confirm_upload_batch_core(cursor, org_id, batch_id, force_confirm=False)`.

### Outcomes

| Case | Scrape run status | Batch state |
|------|-------------------|-------------|
| `NEEDS_ATTENTION = 0`, confirm OK | `success` | `CONFIRMED` |
| `NEEDS_ATTENTION > 0` | `needs_attention` | `DRAFT` |
| All rejected at draft | `failed` | rolled back |
| Confirm raises `UploadBatchConfirmError` | `failed` | rolled back |

All-rejected example: 70 portal lines, 42 `ALREADY_COMPLETED`, 28 accepted → still confirms if 0 needs_attention (production batch 121).

### Confirm failure

Exception → rollback entire scrape transaction attempt; `finish_scrape_run` records `failed` + error message.

### Code path vs manual UI

**Same function:** `confirm_upload_batch_core()` in `backend/upload_batch_confirm.py`.

- Scheduled: `rinse_scheduled_scrape.py`
- UI: `POST` confirm route `confirm_upload_batch()` in `backend/app.py` (wraps same core; may pass `force_confirm=True` for admin)

Both call `finalize_rinse_after_batch_confirm()` after staging updates.

---

## 6. `orders_staging` / Checkout logic

### When staging rows are inserted

On confirm, for each `ACCEPTED` / `OVERRIDDEN` portal row (`upload_batch_confirm.py`):

1. If `ticket_id` and active staging exists → `update_staging_from_upload_row()` (UPDATE).
2. Else if identity not already in staging → `INSERT` with `batch_date`, `AT_WASHPRO` / `PENDING`, optional `ticket_id`.

### Same customer, multiple bags

- Checkout groups by **normalized customer name** for display; each staging row is separate keyed by `ticket_id` when present.
- Multiple active rows for one name are allowed (different `ticket_id`).

### What appears in Checkout / Rush

**API:** `GET /orders` — `get_orders()` in `backend/app.py`.

**Active filter:** `where_active_at_washpro_sql(cap)` — excludes `logistics_status` in `SENT_TO_RINSE`, `FORCE_CHECKOUT`, `CHECKED_OUT` (with legacy `status` mapping).

**Checkout UI** (`CheckoutPage.jsx`): further filters client-side the same way; loads `getOrders({ include_all: true })` then drops sent/checked-out.

**Registry `completion_status` does not hide Checkout rows.** An incomplete bag can still be in staging; completed registry bags are usually rejected on **next** portal upload (`ALREADY_COMPLETED`), not removed from checkout automatically unless staff checks out or force-checkout logic runs.

### Rush vs Non-Rush

- DB: `orders_staging.rush_type` if column exists.
- Else derived: `date_clean < CURDATE()` → `RUSH`, else `NON-RUSH`.
- Upload sets `RUSH` when portal row date equals `batch_date` or CSV says RUSH.
- UI tabs filter `rushOf(row)` on `rush_type` / `rush_date`.

### Search in UI

Client-side on loaded active rows: `name_clean`, display name, `ticket_id`, `id`, `service_type`, weight (`CheckoutPage.jsx` `searchFilteredRows`).

### SQL: order active in Checkout (org 3)

```sql
SET @org_id = 3;
SET @bag_id = 'PUT_BAG_ID_HERE';

SELECT o.id, o.ticket_id, o.name_clean, o.date_clean, o.batch_date,
       o.logistics_status, o.processing_status, o.status, o.rush_type
FROM orders_staging o
WHERE o.organization_id = @org_id
  AND o.ticket_id = @bag_id
  AND COALESCE(o.logistics_status,
        CASE WHEN o.status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
             WHEN o.status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
             ELSE 'AT_WASHPRO' END)
      NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT');
```

### When an order leaves Checkout

- Successful checkout → logistics `SENT_TO_RINSE` / status `CHECKED_OUT`.
- Confirm may **force-checkout** older staging rows not in the new upload identity set (`FORCE_CHECKOUT` / move processed to `orders_final`).
- Registry completion alone does not remove staging.

---

## 7. Completion registry logic

### Tables / functions

| Artifact | Location |
|----------|----------|
| Registry | `rinse_bag_registry` — `ensure_rinse_bag_registry_table()` |
| Scans | `rinse_bag_scan_events` |
| Recompute | `recompute_completion_for_bags()` → `apply_completion_to_registry()` |
| Rule | `evaluate_bag_completion()` — `backend/rinse_bag_completion.py` |

### When recompute runs

Only on **batch confirm** inside `finalize_rinse_after_batch_confirm()` for bag ids union of: merged scan-events bags, accepted portal ticket ids, portal-absence completions.

### Current COMPLETED rule

**First** scan (time-ordered) whose rack contains `"clean"` (case-insensitive) → `COMPLETED` / `CLEAN_RACK_SCANNED` / `trigger_kind = CLEAN_RACK`.

**Old rule removed from evaluation:** “clean rack plus later qualifying scan” — constants like `POST_CLEAN_RACK_AND_USER` remain for **legacy rows** only.

### INCOMPLETE

No clean rack scan in persisted events → `INCOMPLETE` / `NO_CLEAN_SCAN`.

### `completion_reason` values (active + legacy)

| reason | Meaning |
|--------|---------|
| `CLEAN_RACK_SCANNED` | Current completion trigger |
| `NO_CLEAN_SCAN` | Incomplete |
| `MISSING_FROM_LATEST_PORTAL_UPLOAD` | Portal absence rule on confirm |
| `POST_CLEAN_RACK_AND_USER`, `CLEAN_WITHOUT_QUALIFYING_LATER_SCAN`, … | Legacy only on old rows |

### `completed_at` / `date_clean` / `weight_num`

- `completed_at` / `trigger_scan_at`: from first clean scan event (`CompletionResult.to_registry_update()`).
- `date_clean`, `weight_num`, `name_clean`, `service_type`, `rush_type`: updated from portal on confirm via `upsert_registry_from_portal_row()` for **non-completed** bags; completed bags only touch `last_seen_upload_batch_id` / `last_seen_at` on portal snapshot.

### Registry before update

`apply_completion_to_registry()` inserts `(organization_id, bag_id)` if missing, then UPDATEs completion fields.

### Idempotency

Re-running recompute on unchanged `rinse_bag_scan_events` yields the same status/reason. INCOMPLETE recomputes delete stale `rinse_folding_performance` for that bag.

---

## 8. Missing-from-latest-portal-upload rule

**Implemented.**

| Item | Detail |
|------|--------|
| File | `backend/rinse_portal_absence_completion.py` |
| Function | `complete_bags_missing_from_latest_portal()` |
| Called from | `finalize_rinse_after_batch_confirm()` — `backend/rinse_upload_finalize.py` |

**Behavior on confirm:**

1. `upload_batch_is_full_snapshot_portal()` must be true (accepted portal rows with ticket ids; optional `upload_batches.full_snapshot` column if present).
2. Candidates: incomplete registry bags + active staging `ticket_id`s for tenant.
3. Any candidate **not** in current upload bag id set → `mark_registry_completed_portal_absence()` → `COMPLETED` / `MISSING_FROM_LATEST_PORTAL_UPLOAD`.

**Safety:**

- Runs only on **confirm**, not draft.
- Skipped when `not_full_snapshot_or_scan_events_only` or no ticket ids in portal rows.
- Does not run for scan-events-only batches without portal order rows.
- **Skipped when portal scrape hit `RINSE_MAX_PAGES`** (`reached_max_pages: true` in `portal.csv.meta.json` from `scrape.mjs`) — reason `partial_portal_scrape_max_pages`; logs a warning. Prevents falsely completing bags missing only because the page cap cut off the export.

**Portal scrape metadata** (`scripts/rinse-cleanertickets/scrape.mjs` writes `<portal.csv>.meta.json`):

| Field | Meaning |
|-------|---------|
| `stopped_reason` | e.g. `no_next_page_ui`, `duplicate_bag_set`, `max_pages_reached` |
| `reached_max_pages` | `true` only when loop exhausted `RINSE_MAX_PAGES` without natural stop |
| `pages_scraped` | Pages processed |

Stored on `upload_batches.portal_scrape_meta` at draft import (`backend/rinse_portal_scrape_meta.py`). Manual UI upload has no meta → `full_snapshot=1` (unchanged).

---

## 9. Folding performance logic

### When it runs

`finalize_rinse_after_batch_confirm()` → `recompute_folding_after_upload()` — `backend/rinse_folding_registry.py`.

Scheduled scraper triggers this **automatically** after successful auto-confirm (same as manual confirm).

### Scope

`collect_completed_bag_ids_for_folding()` — only bags with registry `COMPLETED` among candidates touched by confirm. Incomplete bags are skipped; existing folding rows for bags that fell back to INCOMPLETE are deleted.

### Tables

| Table | Purpose |
|-------|---------|
| `rinse_folding_performance` | One row per `(organization_id, bag_id)` — `CALCULATED` or `EXCEPTION` |
| `rinse_folding_performance_overrides` | Admin field overrides |

Logic: `evaluate_folding_performance_for_bag()` — `backend/rinse_bag_folding.py`.

### Exception codes

| Code | Meaning |
|------|---------|
| `MISSING_SCAN_EVENTS` | No events for bag |
| `MISSING_FOLDING` | No folding rack scan |
| `MISSING_CLEAN` | No clean rack scan |
| `CLEAN_BEFORE_FOLDING` | Timeline order invalid |
| `INVALID_TIMESTAMPS` | Unparseable times |
| `MISSING_ASSIGNED_USER` | Cannot attribute folder |

### Impact

| Area | Affected? |
|------|-----------|
| Auto-confirm | No (unless you add such a gate — not today) |
| Checkout / staging | No |
| Upload row status | No |
| Folding dashboard / TV | Yes — APIs read `rinse_folding_performance` (`backend/rinse_folding_routes.py`, aggregates in `rinse_folding_registry.py`) |

TV page: confirmed folding data = rows with `status = 'CALCULATED'` (exceptions excluded from leaderboard totals).

---

## 10. Exception semantics (separate concepts)

| Concept | Stored in | Blocks auto-confirm? | Checkout? | Folding leaderboard? | Resolution |
|---------|-----------|----------------------|-----------|----------------------|------------|
| Upload `NEEDS_ATTENTION` | `upload_batch_rows` | **Yes** | N/A until confirm | No | Fix dates/rows; manual confirm or next scrape |
| Registry incomplete | `rinse_bag_registry.completion_reason` e.g. `NO_CLEAN_SCAN` | No | No — staging independent | No CALCULATED folding | Wait for clean scan; re-upload scan-events + confirm |
| Folding `EXCEPTION` | `rinse_folding_performance.exception_code` | No | No | Excluded from KPIs | Fix scans/users; admin recompute |
| Scraper job failure | `rinse_scrape_runs.error_message` | N/A | No | No | Refresh `rinse-auth.json`; check Rinse UI/selectors |
| Checkout issue | `orders_staging` logistics/status | No | Yes | No | Process checkout or force-checkout |

---

## 11. Trace one bag (org 3)

```sql
SET @org_id = 3;
SET @bag_id = 'PUT_BAG_ID_HERE';

-- Registry
SELECT * FROM rinse_bag_registry
WHERE organization_id = @org_id AND bag_id = @bag_id;

-- Active checkout staging
SELECT * FROM orders_staging
WHERE organization_id = @org_id AND ticket_id = @bag_id
  AND COALESCE(logistics_status,
        CASE WHEN status = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
             WHEN status = 'FORCED_CHECKOUT' THEN 'FORCE_CHECKOUT'
             ELSE 'AT_WASHPRO' END)
      NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT');

-- Upload history for bag
SELECT b.batch_id, b.batch_date, b.state, b.confirmed_at, b.file_name,
       r.row_status, r.reason, r.date_clean, r.name_clean
FROM upload_batch_rows r
JOIN upload_batches b ON b.batch_id = r.upload_batch_id
WHERE b.organization_id = @org_id
  AND r.ticket_id = @bag_id
ORDER BY b.batch_id DESC;

-- Persistent scan timeline
SELECT id, rack, user_name, time_scanned_raw, scanned_at_parsed,
       scan_index, source_upload_batch_id, created_at
FROM rinse_bag_scan_events
WHERE organization_id = @org_id AND bag_id = @bag_id
ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC;

-- Folding
SELECT * FROM rinse_folding_performance
WHERE organization_id = @org_id AND bag_id = @bag_id;

-- Latest scrape run that imported a batch touching this bag (via batch rows)
SELECT sr.id, sr.status, sr.started_at, sr.finished_at, sr.imported_batch_id,
       sr.portal_rows_count, sr.scan_events_count
FROM rinse_scrape_runs sr
WHERE sr.organization_id = @org_id
  AND sr.imported_batch_id IN (
    SELECT r.upload_batch_id FROM upload_batch_rows r
    WHERE r.ticket_id = @bag_id
  )
ORDER BY sr.id DESC
LIMIT 5;
```

---

## 12. Latest successful scheduled run (org 3, production)

**Run:** `rinse_scrape_runs.id = 5` — `success`, `imported_batch_id = 121`, portal 70 / scan-events 1545, duration 875s, finished ~2026-05-24 22:15 UTC.

**Batch 121:** `CONFIRMED`, `batch_date = 2026-05-24`, 70 portal lines processed.

| Metric | Count |
|--------|------:|
| `upload_batch_rows` total | 70 |
| Accepted (`ACCEPTED`/`OVERRIDDEN`) | 28 |
| Rejected (`REJECTED_DUPLICATE` / `ALREADY_COMPLETED`) | 42 |
| `NEEDS_ATTENTION` | 0 |
| `upload_batch_scan_events` (draft audit) | 1545 |
| `rinse_bag_scan_events` sourced from batch 121 | 1545 events, 70 bags |

**Registry (28 accepted portal bag ids only):**

| completion_status | reason | count |
|-------------------|--------|------:|
| INCOMPLETE | NO_CLEAN_SCAN | 19 |
| COMPLETED | CLEAN_RACK_SCANNED | 9 |

**Checkout:** 25 active staging rows matching those bag ids (some bags may share staging semantics or updates without ticket match — verify per bag with section 11).

**Folding (same 28 bags):** 9 `CALCULATED`, 0 `EXCEPTION` (incomplete bags have no folding row).

---

## 13. Risks and edge cases

| Risk | Notes |
|------|--------|
| Rinse session expiry | Scraper exit 3; job `failed` until `rinse-auth.json` refreshed on Files |
| DOM / selector drift | Empty table stop; partial CSV; monitor `orchestrator.log` |
| Run duration vs 30m cron | ~15 min observed; overlap skipped via lock; stale run cleanup at 120m |
| `NEEDS_ATTENTION` drafts | Accumulate if old-date rows; block auto-confirm |
| Legacy registry reasons | Do not infer current rule from old `completion_reason` |
| Duplicate scan-events | Mitigated by `dedupe_key`; rows without time skipped |
| Bad auto-confirm | Only when `NEEDS_ATTENTION=0`; all-rejected fails; partial portal still confirms accepted subset |
| Partial portal CSV | `RINSE_MAX_PAGES` too low → absence rule may over-complete missing bags |
| Portal absence rule | **Live** — ensure full snapshot before relying on it |

---

## 14. Plain-English summary

| Term | Meaning for staff |
|------|-------------------|
| **Completed** | Rinse scan history shows the bag hit a **Clean** rack (or admin portal-absence rule marked it done). |
| **In checkout** | Order is still at Washpro in `orders_staging` — not sent to Rinse / not checked out. |
| **Rejected (upload)** | Portal row skipped because bag was **already completed before this upload** — not an error in checkout. |
| **Exception** | Depends on context: upload row needs review, folding data unusable, or scraper job failed. |

**When something looks wrong:** check `rinse_scrape_runs` for the org → batch id → bag trace SQL (section 11) → scan timeline for Clean rack → staging logistics status for checkout.

---

## Quick reference: main files

| Area | Path |
|------|------|
| Orchestrator | `backend/rinse_scheduled_scrape.py` |
| CLI job | `backend/jobs/run_scheduled_rinse_scrape.py` |
| Run history / lock | `backend/rinse_scrape_runs.py` |
| Combined upload | `backend/rinse_combined_upload.py` |
| Confirm | `backend/upload_batch_confirm.py` |
| Finalize | `backend/rinse_upload_finalize.py` |
| Completion | `backend/rinse_bag_completion.py` |
| Registry / scans | `backend/rinse_bag_registry.py` |
| Portal absence | `backend/rinse_portal_absence_completion.py` |
| Folding | `backend/rinse_bag_folding.py`, `backend/rinse_folding_registry.py` |
| Portal scraper | `scripts/rinse-cleanertickets/scrape.mjs` |
| Scan-events scraper | `scripts/rinse-cleanertickets/scrape-scan-events.mjs` |
| VeeWash wrappers | `scripts/rinse-tenants/veewash/run-production-scrape.sh`, `run-scan-events.sh` |
| Deploy notes | `docs/RINSE_SCHEDULED_SCRAPE.md`, `docs/RINSE_SCHEDULED_SCRAPE_AZURE_DEPLOY.md` |
