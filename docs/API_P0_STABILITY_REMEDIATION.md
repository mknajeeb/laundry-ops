# VeeWash Production API — P0 Stability Remediation

**Status:** Validated on `fix/api-p0-stability`. **Not deployed. Azure settings not modified. No service restart. No production data writes.**  
**STOP for final deployment authorization.**

Related RCA: Oct 30 16:40–17:00 UTC hang (gunicorn worker starvation + MySQL connection pressure).

---

## Exact proposed configuration

### Gunicorn (App Service startup / app settings)

| Setting | Current prod | Proposed | Notes |
|---|---|---|---|
| Worker class | sync (implicit) | **sync** (explicit) | Keep sync for P0; gthread needs a separate pool redesign |
| `WORKERS` | unset → **2** | **3** | Spare capacity so one stuck request cannot freeze `/health/live` + PIN |
| `GUNICORN_TIMEOUT` | **1200** | **120** | Stuck workers recycled in 2 minutes, not 20 |
| `GUNICORN_GRACEFUL_TIMEOUT` | unset | **30** | Finish in-flight work briefly on reload/restart |
| `GUNICORN_KEEPALIVE` | unset (gunicorn default 2) | **5** | Modest keep-alive; avoid holding workers on idle sockets |

Gunicorn defaults in `startup.sh` match this table when those env vars are unset. Pool defaults live in `backend/db.py`.

### MySQL pool (per gunicorn worker process)

| Setting | Current | Proposed | Notes |
|---|---|---|---|
| `MYSQL_POOL_SIZE` | unset → **32** (cap) | **8** | Code default changed to 8 |
| `MYSQL_CONNECT_TIMEOUT` | unset (connector default) | **8** seconds | TCP/auth handshake only, including reconnect of a dead pooled socket |
| `MYSQL_POOL_ACQUIRE_TIMEOUT` | missing (queue pop does not wait) | **5** seconds | Wait for a free connection in this process, then `PoolError`. Independent of the handshake timeout |

**Budget vs live `@@GLOBAL.max_connections=171`** (read-only check, 2026-10-30; `max_user_connections=0`, so the global cap is the only limit):

| Consumer | Connections | Notes |
|---|---|---|
| API after this change, 1 instance | **24** | 3 sync workers × pool 8. Pool opens all 8 at process start |
| API today (same check) | **56** idle on one client address | App Service outbound address. Old default is 32 per worker; this is that pool, not a second fleet |
| ACA `rinse-scrape-scheduled`, current image, 1 replica | **up to 32** | This commit does not rebuild the job image. Job code still uses the old pool default until that image is deployed. Job env does not set `MYSQL_POOL_SIZE` |
| ACA overlap (successor replica) | **+32** | Reserve only. Normal shape is one replica |
| `azure_superuser` | **4** observed | Counts toward 171 |
| Ops / one-off scripts / this read | **1–10** | Each process that imports `backend.db` opens its own pool |
| **Steady total after API-only deploy** | **~70** | 24 + 32 + 4 + 10 |
| **Hard ceiling** | **171** | `Connection_errors_max_connections=7` and `Max_used_connections=172` since server start (~37.7 days). The cap has already been hit |

Do **not** raise `WORKERS` without lowering `MYSQL_POOL_SIZE` so `WORKERS × MYSQL_POOL_SIZE ≤ 40` on a single instance. A second API instance at 3×8 adds another 24 and still fits; do not scale out until `Threads_connected` is observed after this change. Do not leave a deployment slot on the old pool (about 2×32) running beside production.

### Azure App Service health check (config only — not applied)

| Setting | Proposed value |
|---|---|
| Health check path | **`/health/live`** |
| Unhealthy threshold | Azure default `WEBSITE_HEALTHCHECK_MAXPINGFAILURES=10` |

**Why not `/health`:** `/health` returns **503** when `EXPECTED_RELEASE_SHA` disagrees with runtime stamps. Azure treats any non-2xx as a failed ping. Pointing `healthCheckPath` at `/health` can mark the instance unhealthy for the whole deploy-stamp window.

**Why `/health/live` is safe for Azure Health check** ([Monitor instances](https://learn.microsoft.com/en-us/azure/app-service/monitor-instances-health-check)):

- The route returns **200** `{"status":"alive"}` and does not call MySQL, revision stamps, auth, or the daily-reset job.
- There is no `before_request` hook and no HTTPS redirect in the Flask app. Health check does not follow 302/307; a redirect on this path would look unhealthy.
- Azure pings about once a minute. A ping that does not finish within **one minute** counts as failed. Default `WEBSITE_HEALTHCHECK_MAXPINGFAILURES` is **10** (about 10 minutes) before the instance is removed from the load balancer. Replacement of an instance that stays unhealthy is capped (about one per hour, three per day).
- A DB outage or stamp mismatch cannot fail this path, so it cannot create a recycle loop by itself.
- All three sync workers busy for longer than the one-minute ping can fail a ping. Worker timeout **120** recycles a stuck worker. Ten consecutive failures are required before load-balancer removal. That is recovery from a wedged process, not a loop caused by `/health/live`.
- With one instance, Azure does not pull the only instance out of rotation; it replaces it only after it stays unhealthy for about an hour.

### Related App Setting (ops decision)

| Setting | Current | Recommendation |
|---|---|---|
| `RINSE_BAG_EXPORT_ENABLED` | `1` on the API | Set to **`0` on the API only**. Do **not** change the ACA job env. |

---

## Long-running work (must stay off API workers)

| Workload | Handling |
|---|---|
| Scheduled Rinse scrape and its CSV artifacts | ACA job `rinse-scrape-scheduled`. Does not read the API process env. Default `RINSE_AV_SINGLE_PASS` is ON, so the job does not consult `RINSE_BAG_EXPORT_ENABLED`. Manual Refresh Both Syncs returns 202 and starts that job |
| API `POST /admin/rinse/bag-export` and sync/async import | Stop when `RINSE_BAG_EXPORT_ENABLED=0` on the API. Those handlers run Playwright for minutes and cannot survive a 120s worker timeout |
| `POST /api/rinse/sync/targeted-pending-refresh` | No UI caller. Still runs local Playwright (default cap 3600s) on the API. A 120s worker timeout will kill that request. Scheduled targeted refresh inside the ACA job is unchanged. Do not call this route after the timeout drop |
| PIN, attendance punch, Task Dashboard, payroll list/approve, one-batch paystub HTML | Stay on the API. No Playwright. Bulk approve is one open-break lookup per record (cap 2000) then a single `UPDATE`. A normal payroll week finishes well under 120s |

---

## Code changes in this branch

1. `startup.sh` — safer gunicorn defaults + graceful-timeout / keep-alive / explicit sync class  
2. `backend/db.py` — default pool 8, handshake timeout, separate pool-acquire wait (default 5s), exhaustion logging, `pool_config_snapshot()`  
3. `backend/app.py` — add `GET /health/live`; document that Azure must not use `/health` for healthCheckPath  
4. Tests — `test_db_pool_config.py`, `test_health_liveness.py`  
5. This runbook

**Out of scope (intentionally):** payroll formulas, attendance business logic, Task Management features, Azure portal changes, deploys.

---

## Monitoring / alerts (configure after code deploy; not applied now)

| Alert | Signal | Suggested threshold |
|---|---|---|
| API latency | Azure `AverageResponseTime` | **> 5s for 2 minutes** |
| HTTP 5xx | Azure `Http5xx` | **> 5 in 5 minutes** |
| MySQL connections | Azure MySQL `active_connections` | **> 120** (≈70% of 171) |
| Pool exhaustion | App logs `mysql_pool_exhausted` | **any occurrence** |
| Worker timeouts | Gunicorn critical log / worker boot storms | **> 2 worker kills in 10 minutes** |
| PIN availability | Synthetic `POST` PIN path or App Insights failure rate | spike in 5xx/timeouts on PIN routes |

---

## Deployment plan (do not execute until a separate authorization)

Apply on the **production** API slot only. Do not change the ACA job, do not restart until step 4, and do not write production data as part of this rollout.

1. Deploy the API build from the `fix/api-p0-stability` commit. Do not enable Health check yet.  
2. Confirm the ACA job `rinse-scrape-scheduled` still does **not** have `RINSE_BAG_EXPORT_ENABLED=0`. Leave `RINSE_SCHEDULED_SCRAPE_ENABLED=1` and `RINSE_AV_SINGLE_PASS` unset (default single-pass ON).  
3. Set these App Settings together on `laundryops-api`:

   | Name | Value |
   |---|---|
   | `WORKERS` | `3` |
   | `GUNICORN_TIMEOUT` | `120` |
   | `GUNICORN_GRACEFUL_TIMEOUT` | `30` |
   | `GUNICORN_KEEPALIVE` | `5` |
   | `MYSQL_POOL_SIZE` | `8` |
   | `MYSQL_CONNECT_TIMEOUT` | `8` |
   | `MYSQL_POOL_ACQUIRE_TIMEOUT` | `5` |
   | `RINSE_BAG_EXPORT_ENABLED` | `0` |

   Leave `RINSE_SCRAPE_REMOTE_ONLY=1`. Do not copy `RINSE_BAG_EXPORT_ENABLED=0` onto the Container Apps job.  
4. Restart the API **once**.  
5. Smoke before Health check: `GET /health/live` is **200** in under 1 second; `GET /health` may be 200 or 503 and must not be the health-check path.  
6. Portal: App Service → Monitoring → Health check → Enable → Path **`/health/live`**. Leave `WEBSITE_HEALTHCHECK_MAXPINGFAILURES` at the default **10** unless a later incident says otherwise.  
7. Smoke: PIN login, Task Dashboard load, one payroll read-only page, attendance kiosk read. Confirm a scheduled scrape log still advances on the ACA job (do not start an extra job execution just to test).  
8. Watch for 30 minutes: Average response time, HTTP 5xx, MySQL `active_connections` (alert above **120**), log line `mysql_pool_exhausted`, gunicorn worker boot storms.

## Rollback plan

1. Restore API App Settings: `GUNICORN_TIMEOUT=1200`, `RINSE_BAG_EXPORT_ENABLED=1`, and remove `WORKERS`, `GUNICORN_GRACEFUL_TIMEOUT`, `GUNICORN_KEEPALIVE`, `MYSQL_POOL_SIZE`, `MYSQL_CONNECT_TIMEOUT`, and `MYSQL_POOL_ACQUIRE_TIMEOUT` if they were unset before this change.  
2. Health check path may stay `/health/live` (it does not depend on the old timeout). Clear it only if the path itself is failing.  
3. Redeploy the previous API SHA if the code must be reverted.  
4. One restart. Do not loop restarts. Do not change the ACA job during rollback.

---

## Validation (2026-10-30, no deploy)

| Check | Result |
|---|---|
| 1. Pool acquire wait, separate from handshake | **Pass, after this patch.** mysql-connector 9.x `get_connection()` uses `queue.get(block=False)`. `MYSQL_CONNECT_TIMEOUT` only sets `connection_timeout`. `get_db()` now waits up to `MYSQL_POOL_ACQUIRE_TIMEOUT` (default 5s) and then raises `PoolError` |
| 2. Total connections under 171 | **Pass for one API instance.** Live `max_connections=171`. Steady budget after this API deploy is about 70, including the current ACA image at up to 32. See the budget table. The server has already refused 7 connections since startup; this change lowers the API's idle pool |
| 3. `/health/live` has no blocking dependencies | **Pass.** Handler returns 200 JSON only. Tests reject any `get_db` or revision-stamp call |
| 4. Health check will not recycle on DB or stamp skew | **Pass**, if the path is `/health/live` and not `/health`. See the health-check section |
| 5. Scheduled scrape/exports with API flag `0` | **Pass**, if the flag is changed only on the API. The job is a different process. Single-pass (default) writes portal and scan-event CSVs without `export_enabled()`. Legacy triple-scrape (`RINSE_AV_SINGLE_PASS=0`) does check that flag **in the job env** |
| 6. 120s worker timeout vs work that must stay on the API | **Pass for PIN, attendance, Task Dashboard, and payroll reads/approve/paystubs.** **Residual:** API Playwright routes listed above. Disable bag export/import on the API. Do not call targeted-pending-refresh on the API |
| 7. Regression tests | **221 passed, 3 failed.** Failures are pre-existing on this branch in PIN hub feature-order and `ensure_employee_mobile_pin_access_tables` call counts. Pool, `/health/live`, attendance PIN punch, payroll, and Task Dashboard tests passed. Scheduler was disabled for the run (`DAILY_OPERATIONAL_RESET_EMBEDDED_SCHEDULER=0`) so tests did not open a live reset job |
| 8. Azure steps | This document. Not applied |

## Operational risks

| Risk | Mitigation |
|---|---|
| Sync bag export or API import killed at 120s | `RINSE_BAG_EXPORT_ENABLED=0` on the API only |
| Targeted-pending-refresh on the API killed at 120s | No UI caller. Leave it unused; ACA scheduled path still runs targeted refresh |
| Setting the export flag to 0 on the ACA job | Do not. That is a different env. Required only if single-pass is turned off |
| 3×8 pool too small under burst | `get_db()` waits 5s, then logs `mysql_pool_exhausted`. Raise pool to 10–12 only if `active_connections` stays under 120 |
| Dead socket reconnect holds the process pool lock | Bounded by `MYSQL_CONNECT_TIMEOUT` (8s), not by the acquire wait |
| Health check recycle loop | Use `/health/live` only. Enable it after the route returns 200 |
| Second instance or old deployment slot | Adds another full pool. Confirm `Threads_connected` before scaling |
| PIN / payroll regressions | No business logic in those modules changed |

---

## GO / NO-GO

| Gate | Status |
|---|---|
| Patch isolated from Task Management feature work | **GO** (this branch) |
| DB pool math under 171 | **GO** (3×8=24) |
| Health path safe under DB degradation | **GO** (`/health/live`) |
| Azure config applied | **NO-GO — not authorized** |
| Production deploy | **NO-GO — stop for final deployment authorization** |

**Assessment:** Code on this branch is ready to commit. **Do not deploy, do not change Azure, do not restart.**
