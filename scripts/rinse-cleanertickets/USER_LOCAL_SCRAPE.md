# Run Rinse portal scrape on your computer (outside Washpro)

Use this when you want the CSV on your machine first, then upload it in **Washpro → Upload Orders → Rinse / CSV → Upload CSV** (portal CSV).

## What you need once

1. **Node.js LTS** — install from [https://nodejs.org/](https://nodejs.org/) (Windows: check “Add to PATH”; Mac: use the installer).  
2. This folder **`rinse-cleanertickets`** (from your IT team or repo), containing `scrape.mjs`, `package.json`, and the helper scripts below.

## One-time setup (Mac and Windows)

Open a terminal **in this folder** (`rinse-cleanertickets`).

```bash
cp .env.example .env
```

Edit **`.env`** (Notepad on Windows, TextEdit/VS Code on Mac):

- **`RINSE_TICKETS_URL`** — your Rinse cleaner-tickets list URL (same filters you use in the browser).
- **`RINSE_STORAGE_STATE=./rinse-auth.json`**

Then save a login session **once**:

```bash
npm install
npx playwright install chromium
npm run save-session
```

A browser window opens: log in to Rinse (and MFA if asked), then return to the terminal and press Enter. This creates **`rinse-auth.json`** in this folder.

---

## Mac

**Double‑click:** use **`run-local-portal-csv.command`** — macOS opens **Terminal** and runs the scrape.  
(If you double‑click **`run-local-portal-csv.sh`**, it usually opens as **text** in TextEdit — that is normal; use the **`.command`** file or Terminal below.)

First time macOS may say the file can’t be opened: **right‑click → Open** once, then confirm.

**From Terminal** (same as double‑click):

```bash
cd /path/to/rinse-cleanertickets
bash run-local-portal-csv.sh
```

Quick test (only **3 list pages**):

```bash
bash run-local-portal-csv.sh 3
```

---

## Windows (Command Prompt)

1. Open **Command Prompt** (not PowerShell required).
2. `cd` to this folder, e.g.  
   `cd C:\Users\You\Desktop\rinse-cleanertickets`
3. Run:

```cmd
run-local-portal-csv.cmd
```

Quick test (3 list pages):

```cmd
run-local-portal-csv.cmd 3
```

You can also **double‑click** `run-local-portal-csv.cmd` after setup (the window stays open at the end).

---

## After the run

- A **CSV** is written in this folder (name from **`OUTPUT_CSV`** in `.env`, or a default like `bag-ids-YYYY-MM-DD.csv`).
- In Washpro: **Upload Orders** → **Rinse / CSV** → choose that file → **Upload CSV** → work the draft as usual.

## Problems?

- **“node is not recognized”** — install Node LTS and open a **new** terminal.  
- **Login errors** — run `npm run save-session` again and refresh `rinse-auth.json`.  
- **Slow after many rows** — normal on large queues; use a small page cap (`3`) to test first.
- **Scrape never stops / jumps back to page 1** — pagination “next” detection used to treat unrelated buttons (or evaluation errors) as “has another page.” The script now only trusts real `?page=N` links by default. If your list **stops after page 1** but Rinse still has more pages, set in `.env`: `RINSE_PAGINATION_LOOSE=1` (restores the old, looser checks).

Use only if allowed by Rinse’s terms and your company policy.
