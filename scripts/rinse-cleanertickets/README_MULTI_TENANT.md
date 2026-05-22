# Scraping multiple Rinse vendors (WASHPRO vs VEEWASH)

Rinse does **not** use one login for all brands. Each vendor account (WASHPRO, VEEWASH) has its **own email/password** and **own browser session**. The scraper only sees whichever account is in your `rinse-auth*.json` file.

## One-time setup per tenant

```bash
cd scripts/rinse-cleanertickets

cp .env.washpro.example .env.washpro
cp .env.veewash.example .env.veewash
```

Edit each file if your ticket list URL or filters differ (copy the URL from the browser **while logged in as that vendor**).

Save a session **per tenant** (browser opens — log in with that vendor’s Rinse email, MFA if needed):

```bash
chmod +x use-rinse-tenant.sh

./use-rinse-tenant.sh washpro npm run save-session
# → creates rinse-auth-washpro.json

./use-rinse-tenant.sh veewash npm run save-session
# → creates rinse-auth-veewash.json
```

## Run scrapes

**WASHPRO — production CSV:**

```bash
./use-rinse-tenant.sh washpro bash run-local-production-scrape.sh 1
```

**VEEWASH — production CSV:**

```bash
./use-rinse-tenant.sh veewash bash run-local-production-scrape.sh 1
```

**Scan-events (tickets + events files):**

```bash
./use-rinse-tenant.sh washpro bash run-local-scan-events.sh 1
./use-rinse-tenant.sh veewash bash run-local-scan-events.sh 1
```

Outputs are named per tenant in `.env.washpro` / `.env.veewash` (e.g. `bag-ids-washpro.csv`, `bag-ids-veewash.csv`).

## What to change between tenants

| Setting | Purpose |
|---------|---------|
| `RINSE_STORAGE_STATE` | **Required** — separate `rinse-auth-washpro.json` vs `rinse-auth-veewash.json` |
| `RINSE_TICKETS_URL` | Ticket list URL (often same pattern; confirm while logged in as that vendor) |
| `RINSE_EMAIL` / `RINSE_PASSWORD` | Only if you skip save-session (MFA usually blocks this) |
| `OUTPUT_CSV` / `OUTPUT_SCAN_*` | So files do not overwrite the other tenant |

## Washpro app (upload batch)

Production import on the API uses **one** scrape env on the server (`scripts/rinse-cleanertickets/.env` or Azure app settings). To import VEEWASH vs WASHPRO in the app you need either:

- Different API hosts / deployment slots with different `RINSE_STORAGE_STATE` and credentials, or  
- Run import while the server `.env` points at the correct tenant’s auth file.

Local scraping always uses `use-rinse-tenant.sh` as above.

## Wrong tenant symptoms

- Empty table, login page, or another vendor’s customers → session file is for the **other** account; re-run `save-session` for that tenant.
