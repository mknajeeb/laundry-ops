# Run Rinse portal scrape on your Mac (WashPro + VeeWash)

Each vendor has a **separate Rinse login**. The Mac scripts ask **WashPro or VeeWash** and keep files apart under `tenants/`.

## Folder layout (after you run)

```
rinse-cleanertickets/
  tenants/
    washpro/
      rinse-auth.json      ← session (WashPro login)
      TODAY/               ← latest CSV(s)
      ARCHIVE/             ← older TODAY files
    veewash/
      rinse-auth.json      ← session (VeeWash login)
      TODAY/
      ARCHIVE/
```

## One-time setup

1. Install **Node.js LTS** from [nodejs.org](https://nodejs.org/).
2. Open **Terminal** in this folder (`rinse-cleanertickets`).

```bash
cp .env.example .env
cp tenants/washpro/.env.example tenants/washpro/.env
cp tenants/veewash/.env.example tenants/veewash/.env
```

Edit **`tenants/washpro/.env`** and **`tenants/veewash/.env`** — each vendor’s **`RINSE_TICKETS_URL`** (and email/password only if you skip save-session).  
Shared **`.env`** can hold pagination defaults; **credentials are per vendor folder**.

```bash
npm install
npx playwright install chromium
```

**Save login once per vendor** (browser opens; log in with that vendor’s email, MFA if needed, press Enter in Terminal):

- Double-click **`save-session.command`** → choose **WashPro**, then again for **VeeWash**.

Or:

```bash
bash save-session.sh
```

## Scrape (portal CSV for Washpro upload)

**Double-click `run-local-portal-csv.command`**

1. Dialog or prompt: **WashPro** or **VeeWash**
2. Scrape runs
3. New file: `tenants/<vendor>/TODAY/Rinse-YYYY-MM-DD-vN.csv`

Quick test (3 list pages):

```bash
bash run-local-portal-csv.sh 3
```

Skip the prompt (scripting):

```bash
RINSE_VENDOR=veewash bash run-local-portal-csv.sh
```

## Scan events (optional — tickets + events CSVs)

Double-click **`run-local-scan-events.command`** (same vendor prompt).

Files go in `tenants/<vendor>/scan-events-YYYY-MM-DD-tickets.csv` and `…-events.csv`.

## Upload in Washpro

Open the CSV from **`tenants/washpro/TODAY/`** or **`tenants/veewash/TODAY/`** depending on which business you imported.

## Rebuild the zip for users

From repo root, zip **`scripts/rinse-cleanertickets`** (include `node_modules` if users are offline, or omit and they run `npm install` once).  
Do **not** include `.env`, `rinse-auth.json`, or `tenants/*/rinse-auth.json`.

## Problems?

- **Wrong customers on CSV** — you picked the other vendor; re-run and choose the correct one, or re-run `save-session.command` for that vendor.
- **No session** — run `save-session.command` for that vendor first.
- **Double-click `.sh` opens TextEdit** — use the **`.command`** files only on Mac.

Use only if allowed by Rinse’s terms and your company policy.
