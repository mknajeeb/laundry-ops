# Rinse cleaner tickets — Bag ID helper

Expands rows on the Rinse **Cleaner tickets** table and reads **`Bag: XXXXX`** text (your QR / bag source data).

## Before you run this

- Use only if you are **authorized** to access this data and your use complies with **Rinse’s terms** and your agreement with them.
- Prefer an **official export or API** from Rinse if they offer one.
- This script drives a real browser session (login + clicks). It can break if Rinse changes their HTML.

## Setup

```bash
cd scripts/rinse-cleanertickets
npm install
npx playwright install chromium
```

## Configure

Copy `.env.example` to `.env` and set:

- `RINSE_EMAIL` / `RINSE_PASSWORD` — portal login (or log in once manually with `HEADED=1` and save storage — see script).
- `RINSE_TICKETS_URL` — full URL, e.g. `https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1`

Optional: edit **selectors** at the top of `scrape.mjs` if your page layout differs.

## Run

```bash
# See the browser (debug login / captcha)
HEADED=1 npm run scrape

# Headless after login works
npm run scrape
```

Output: `bag-ids.csv` in this folder (columns: `page`, `row_index`, `customer_snippet`, `bag_id`, `raw_line`).

## Faster path (no scraping)

In Chrome: **F12 → Network**, expand one ticket row, filter **Fetch/XHR** and look for a JSON response that already contains the bag code. If you find it, you can often replay that request with your session cookie instead of clicking every row — ask your dev to wire that into your app if Rinse allows it.
