# Rinse scan events export (extension — not production scrape)

Separate from **`scrape.mjs`**. Production bag import is unchanged.

## Output (two files, no redundant portal data on events)

| File | Contents |
|------|----------|
| **`scan-events-YYYY-MM-DD-tickets.csv`** | Same 16 columns as production portal scrape (one row per bag) |
| **`scan-events-YYYY-MM-DD-events.csv`** | **`Bag ID`** (unique alphanumeric code) + scan columns only |

Join: events `Bag ID` = prefix of tickets `Bag ID` column (e.g. `9D498298XU` ↔ `9D498298XU (Hang Dry)`).

```env
OUTPUT_SCAN_TICKETS_CSV=/path/to/tickets.csv
OUTPUT_SCAN_EVENTS_CSV=/path/to/events.csv
```

## Run locally

```bash
bash run-local-scan-events.sh
bash run-local-scan-events.sh 3
bash run-local-scan-events.sh 3 --apply
```

## Compare to production scrape (same pages)

Use the **same** `RINSE_MAX_PAGES` on both runs, then diff tickets files:

```bash
cd scripts/rinse-cleanertickets
bash run-local-production-scrape.sh 1
bash run-local-scan-events.sh 1
diff -u bag-ids-production-compare-$(date +%Y-%m-%d).csv scan-events-$(date +%Y-%m-%d)-tickets.csv
```

Or npm:

```bash
RINSE_MAX_PAGES=1 OUTPUT_CSV=./bag-ids-production-compare.csv npm run scrape:portal
RINSE_MAX_PAGES=1 npm run scrape:scan-events
diff -u bag-ids-production-compare.csv scan-events-$(date +%Y-%m-%d)-tickets.csv
```

## Python (repo root)

```bash
python3 -m backend.rinse_scan_events_cli apply --csv scripts/rinse-cleanertickets/scan-events-2026-05-16-events.csv
python3 -m backend.rinse_scan_events_cli portal-orders --tickets scripts/rinse-cleanertickets/scan-events-2026-05-16-tickets.csv
```

- **Tickets** → `portal_csv_to_orders_df` (production upload massage)
- **Events** → `apply_scan_event_logic` (scan rules only)
