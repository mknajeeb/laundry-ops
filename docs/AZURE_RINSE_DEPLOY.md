# Azure: Rinse import / export and API deploy

## Deploy application code

From your laptop (repo root):

```bash
git status
git add backend frontend scripts docs .github startup.sh
git commit -m "Rinse: async import jobs, scrape tuning, Azure env docs"
git push origin main
```

Then in **GitHub → Actions**, wait for:

- **laundryops-api** (or your workflow name) → Azure Web App deploy
- **Azure Static Web Apps** (frontend)

The MySQL table `rinse_import_jobs` is **created automatically** the first time an admin starts an async import. You do not have to run `backend/sql/rinse_import_jobs.sql` unless your team requires a pre-provisioned schema.

---

## Azure Web App (`laundryops-api`) — Application settings

Set these under **Configuration → Application settings** (add if missing). Values are examples; adjust to your org.

### Feature gate and Rinse session

| Name | Value | Notes |
|------|--------|--------|
| `RINSE_BAG_EXPORT_ENABLED` | `1` | Required for **Download bag IDs CSV** and **Import from Rinse**. |
| `RINSE_TICKETS_URL` | `https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1` | Must match the list you want (query string preserved; `page=` is overwritten by the scraper). |
| `RINSE_STORAGE_STATE` | `/home/site/wwwroot/scripts/rinse-cleanertickets/rinse-auth.json` | Typical path after you upload `rinse-auth.json` next to the scraper. Use an **absolute** path. |
| `NODE_BIN` | `/home/site/node-v20.18.0-linux-x64/bin/node` | Set if `node` is not on default `PATH` for the gunicorn process. |

### Timeouts and pagination (fix 900s scrape kill and huge queues)

| Name | Value | Notes |
|------|--------|--------|
| `RINSE_SCRAPE_TIMEOUT_SEC` | `1800` | Subprocess cap for `scrape.mjs` (60–7200). Raise if you increase pages and the queue is large. |
| `RINSE_IMPORT_MAX_PAGES` | *(omit or e.g. `25`)* | If set, **draft import** uses this page cap. If omitted, import uses **`RINSE_MAX_PAGES`** (below), then default `10`. |
| `RINSE_MAX_PAGES` | `20` | **Bag CSV export** and **draft import** (when `RINSE_IMPORT_MAX_PAGES` is not set). Your screenshot value `25` applies to import after this behavior. |
| `RINSE_PAGE_SETTLE_MS` | *(omit)* | Import sets `2200` internally unless you set this globally (then it wins). |
| `GUNICORN_TIMEOUT` | `1200` | In **startup** / App settings; worker must stay alive for long requests (bag export is still synchronous). |
| `WORKERS` | `2` | Default in `startup.sh`. Async import runs in a **thread**; DB holds job state so polling works across workers. |

### Optional startup speed (Playwright on API)

| Name | Value | Notes |
|------|--------|--------|
| `LAUNDRYOPS_SKIP_RINSE_STARTUP` | `1` | Skips npm/playwright at **container boot**; first **import** may still install deps — allow time or warm once without skip. |

### Database (already required for the app)

| Name | Example | Notes |
|------|---------|--------|
| `MYSQL_HOST` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | *(your Azure MySQL)* | Same as today; async jobs store status in MySQL. |

### Frontend (Static Web App build)

| Name | Value | Notes |
|------|--------|--------|
| `VITE_API_BASE` | `https://your-api.azurewebsites.net` | **Build-time** for the React app. Set this in **GitHub Actions** (secret/env for the SWA build) or your Static Web App pipeline — **not** on the API Web App unless you also inject it into the frontend build. Putting it only under `laundryops-api` does nothing for the deployed SPA. |

---

## API routes (reference)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/admin/rinse/import-upload-batch/jobs` | Start async import → **202** + `{ job_id, poll_url }`. |
| `GET` | `/admin/rinse/import-upload-batch/jobs/<job_id>` | Poll until `status` is `succeeded` or `failed`. |
| `POST` | `/admin/rinse/import-upload-batch` | Legacy **synchronous** import (long single HTTP request). |

Upload UI uses **jobs + poll** so the browser does not sit on one request for the whole Playwright run.

---

## After deploy

1. **Restart** the Web App once so new settings and code load.
2. Confirm **`GET /admin/rinse/bag-export/config`** returns `"ready": true` when logged in as admin.
3. Run **Import from Rinse** on Upload; status line should advance from `queued` → `running` → `succeeded` or `failed`.
