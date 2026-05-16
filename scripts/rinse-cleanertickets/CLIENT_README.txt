RINSE LOCAL CSV SCRAPER — Laundry Ops
=====================================

This package runs on YOUR computer (Mac or Windows). It does NOT scrape from the
Laundry Ops server (that is too slow for daily use).

Workflow:
  Your PC  →  local scraper  →  portal-format CSV  →  upload in Laundry Ops
  →  draft upload batch  →  review and confirm

WashPro and VeeWash use DIFFERENT Rinse logins. Use the correct scripts for each.


MAC — FIRST TIME
----------------
1. Unzip this folder (rinse-cleanertickets).
2. Open Terminal in this folder.
3. Run:
     npm install
     npx playwright install chromium
4. Double-click ONE of:
     save-washpro-session.command   (WashPro Rinse account)
     save-veewash-session.command   (VeeWash Rinse account)
5. Log in to Rinse in the browser window; open the cleaner-tickets list.
6. Return to Terminal and press Enter when done.
7. Repeat step 4–6 for the OTHER vendor if you use both.


MAC — EVERY DAY
---------------
1. Double-click:
     run-washpro-portal-csv.command   OR   run-veewash-portal-csv.command
2. Wait for the scrape to finish (several minutes is normal).
3. Upload the CSV shown at the end from:
     tenants/washpro/TODAY/   or   tenants/veewash/TODAY/
4. In Laundry Ops: Upload Orders → Rinse / CSV → choose that file → Upload CSV.


WINDOWS — FIRST TIME
--------------------
1. Install Node.js LTS from https://nodejs.org/ (check "Add to PATH").
2. Unzip this folder.
3. Open Command Prompt in this folder (cd path\to\rinse-cleanertickets).
4. Run:
     npm install
     npx playwright install chromium
5. Double-click ONE of:
     save-washpro-session.cmd
     save-veewash-session.cmd
6. Log in to Rinse; press Enter in the Command Prompt window when done.
7. Repeat for the other vendor if needed.


WINDOWS — EVERY DAY
-------------------
1. Double-click:
     run-washpro-portal-csv.cmd   OR   run-veewash-portal-csv.cmd
2. Upload the CSV from:
     tenants\washpro\TODAY\   or   tenants\veewash\TODAY\
3. In Laundry Ops: Upload Orders → Rinse / CSV → Upload CSV.


CSV FORMAT
----------
Output uses RINSE_CSV_LAYOUT=portal (required). Header includes:
Date, Estd. Delivery, Customer, # WF LBS, # HD, # WF ITEMS, Weight, Notes,
USE OXIC, Use Hypo, USE FAB, Low DRY, NO SCEN, Extra Scen, Service Type,
Sub-Service, Bag ID


TROUBLESHOOTING
---------------
- "Session not found" → run the matching save-*-session script again.
- Wrong customers on CSV → you used the other vendor's run script.
- Login page during scrape → session expired; save session again.
- node not found (Windows) → install Node LTS and open a new Command Prompt.

Do not share rinse-auth.json or .env files — they contain login cookies.
