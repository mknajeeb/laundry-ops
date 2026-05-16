# Rinse scan events export (extension — not production scrape)

This is a **separate** Playwright script from **`scrape.mjs`** (bag IDs / portal daily upload CSV).  
**Do not change `scrape.mjs`** for this feature; production bag export and import stay as they are.

## What it does

For each cleaner-ticket row on the Rinse list (same pagination / session as the bag scraper):

1. Expands the ticket.
2. Reads the **Scans** table: **Rack**, **Time Scanned**, **User**, **Purpose** (plus **Last Location** / **Last Scan** badges when present).
3. Writes one CSV row **per scan event**, with ticket context (`bag_id`, customer snippet, list page URL).

## One-time setup

Same as the bag scraper (shared `.env` and `rinse-auth.json`):

```bash
cd scripts/rinse-cleanertickets
npm install
npx playwright install chromium
cp .env.example .env
npm run save-session
```

## Run locally

```bash
bash run-local-scan-events.sh
bash run-local-scan-events.sh 3          # first 3 list pages only
bash run-local-scan-events.sh 3 --apply  # scrape + Python enrich
```

Windows: `run-local-scan-events.cmd`  
Mac double-click: copy `run-local-scan-events.sh` to `run-local-scan-events.command` (same pattern as portal CSV).

Output default: **`scan-events-YYYY-MM-DD.csv`** in this folder, or set:

```env
OUTPUT_SCAN_EVENTS_CSV=/absolute/path/scan-events.csv
```

Optional:

```env
RINSE_SCAN_TABLE_SETTLE_MS=600
RINSE_SCAN_INCLUDE_EMPTY_TICKETS=1
HEADED=1
```

## Apply logic (Python, local)

From **repo root**:

```bash
python3 -m backend.rinse_scan_events_cli apply --csv scripts/rinse-cleanertickets/scan-events-2026-05-11.csv
python3 -m backend.rinse_scan_events_cli summary --csv path/to/scan-events.csv
```

`backend/rinse_scan_events_logic.py` adds parsed timestamps, normalized purpose, and flags (`is_latest_scan_in_ticket`, `is_cleaning_start`, etc.). **Extend that file** for new rules — not `scrape.mjs`.

## Files

| File | Role |
|------|------|
| `scrape.mjs` | **Production** — bag / portal CSV (unchanged) |
| `scrape-scan-events.mjs` | **New** — scan events CSV |
| `rinse-playwright-lib.mjs` | Shared helpers for scan-events only |
| `backend/rinse_scan_events_logic.py` | Post-process rules |
| `backend/rinse_scan_events_cli.py` | Local CLI |

## npm scripts

```bash
npm run scrape:scan-events
npm run scrape:scan-events:headed
```

## Terms

Use only if allowed by Rinse’s terms and your vendor agreement.
