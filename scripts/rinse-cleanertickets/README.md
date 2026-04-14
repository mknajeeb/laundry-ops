# Rinse cleaner tickets — nightly Bag ID export

Expands rows on the Rinse **Cleaner tickets** list and reads **`Bag: XXXXX (Wash & Fold)`** so you get the same **bag / QR source** your team copies by hand. The script walks **multiple `page=` URLs** and writes **one CSV** per run.

## Rules

- Use only if you are **allowed** under Rinse’s terms and your vendor agreement.
- Prefer an **official export or API** from Rinse if they add one.

## One-time setup

```bash
cd scripts/rinse-cleanertickets
npm install
npx playwright install chromium
cp .env.example .env
```

Edit **`.env`**:

- **`RINSE_TICKETS_URL`** — same filters you use at night (status, etc.). The `page=` value is replaced automatically.
- **`RINSE_PAGE_START`** / **`RINSE_MAX_PAGES`** — how many list pages to walk (stops early if a page has **no table rows**).
- **`RINSE_PAGE_SETTLE_MS`** — wait after each `page.goto` before reading the table (default **3500**). Lower on a fast host if stable; import uses **2200** unless you set this globally on the API.
- **`RINSE_NAV_TIMEOUT_MS`** — max wait per `page.goto` (default **120000**). Raise on Azure if `www.rinse.com` is slow or blocked from the datacenter; max **300000**.
- **`OUTPUT_CSV`** — optional; default is `bag-ids-YYYY-MM-DD.csv` in this folder.

## Save login once (recommended for every night)

Password + MFA in a **headless** cron job is painful. Log in **once** in a visible browser and save cookies:

```bash
npm run save-session
```

In the window: log in (MFA), open Cleaner tickets once. Return to the terminal and **press Enter**. This creates **`rinse-auth.json`**.

Then in **`.env`**:

```env
RINSE_STORAGE_STATE=./rinse-auth.json
```

Remove or leave blank **`RINSE_PASSWORD`** if you only use storage state. When Rinse logs you out, run **`npm run save-session`** again.

## Run export (all pages in range)

```bash
npm run scrape
```

With a visible browser for debugging:

```bash
HEADED=1 npm run scrape
```

**CSV columns:** `page` (full list URL for that row), `row_index`, `customer_snippet`, `bag_id`, `raw_line`  
Feed that file into your existing **transform → orders** pipeline (same as manual copy).

## Production — “Download bag IDs CSV from Rinse” (Upload page)

Admins can trigger **`POST /admin/rinse/bag-export`** from **Upload → Rinse — bag ID export**. The **Python API process** runs `node scrape.mjs` in this folder (same as CLI).

**On the API host you must:**

1. Install **Node.js** and add it to `PATH`, or set **`NODE_BIN`** to the full `node` path.
2. From this directory: **`npm install`** and **`npx playwright install chromium`** (Chromium must exist where Node runs).
3. Create **`scripts/rinse-cleanertickets/.env`** (or export vars in the process environment) with **`RINSE_TICKETS_URL`**, pagination, and either **`RINSE_STORAGE_STATE`** (path to `rinse-auth.json` on that machine) or email/password if Rinse allows unattended login.
4. Set **`RINSE_BAG_EXPORT_ENABLED=1`** on the API server (feature gate).
5. **Draft “Import from Rinse”** uses **`RINSE_IMPORT_MAX_PAGES`** (default **10**) and a shorter page settle unless you override **`RINSE_PAGE_SETTLE_MS`**. Set **`RINSE_SCRAPE_TIMEOUT_SEC`** (up to **7200**) if you raise pages or the queue is large.
6. Raise HTTP timeouts: the scrape can run many minutes — configure **Gunicorn/uwsgi** and your **reverse proxy** (`proxy_read_timeout`, etc.) for long requests, or the connection will drop before the CSV returns. Scheduling later can move this off the request thread.

If any step is missing, **`GET /admin/rinse/bag-export/config`** returns hints the UI shows on the Upload page.

## Run every day automatically

### macOS / Linux (`cron`)

1. Use an **absolute** path in `.env` for `OUTPUT_CSV` (e.g. `/Users/washpro/data/rinse-inbox/bags.csv`).
2. Ensure `PATH` includes `node` and run from the script directory:

```cron
# 11:15 PM every day (server local time)
15 23 * * * cd /ABS/PATH/TO/laundry_app/scripts/rinse-cleanertickets && /usr/local/bin/npm run scrape >> /tmp/rinse-scrape.log 2>&1
```

Find Node: `which node` — use that full path if `npm` is not in cron’s PATH, e.g.:

```cron
15 23 * * * cd /ABS/PATH/TO/laundry_app/scripts/rinse-cleanertickets && /Users/you/.nvm/versions/node/v22.0.0/bin/node scrape.mjs >> /tmp/rinse-scrape.log 2>&1
```

### Windows (Task Scheduler)

- **Action:** Start a program  
- **Program:** full path to `node.exe`  
- **Arguments:** `scrape.mjs`  
- **Start in:** `C:\path\to\laundry_app\scripts\rinse-cleanertickets`  
- **Trigger:** Daily at your chosen time.

### If session expires

Rerun **`npm run save-session`** and confirm **`rinse-auth.json`** is still referenced in `.env`.

## If selectors break

Open DevTools on a ticket row, find the main table’s **`tbody > tr`**, and update **`SELECTORS.bodyRows`** at the top of **`scrape.mjs`**.

## Faster alternative (developer)

In **Network** while expanding one row: if a **JSON** response already includes the bag id, calling that API with a valid session is more stable than DOM scraping — only if Rinse permits it.
