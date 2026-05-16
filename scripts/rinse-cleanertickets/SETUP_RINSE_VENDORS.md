# WashPro + VeeWash — two Rinse accounts (production + local users)

WASHPRO and VEEWASH use **different Rinse logins**. Everything is split by vendor.

---

## A) Production API (Azure / `python run.py`)

Set in **repo-root `.env`** (Flask reads this — not `scripts/rinse-cleanertickets/.env`).

### 1. Map each Washpro organization → vendor

```env
RINSE_BAG_EXPORT_ENABLED=1

# organization.id in MySQL (comma-separated)
RINSE_WASHPRO_ORG_IDS=1
RINSE_VEEWASH_ORG_IDS=2

# optional: match by organizations.slug
# RINSE_WASHPRO_ORG_SLUGS=washpro
# RINSE_VEEWASH_ORG_SLUGS=veewash
```

When a user imports from Rinse, the API picks **washpro** or **veewash** from their `organization_id`.

### 2. Credentials per vendor (on the server)

```env
RINSE_WASHPRO_STORAGE_STATE=/home/site/rinse-tenants/washpro/rinse-auth.json
RINSE_VEEWASH_STORAGE_STATE=/home/site/rinse-tenants/veewash/rinse-auth.json

RINSE_WASHPRO_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1
RINSE_VEEWASH_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1

# Optional if save-session was done on server:
# RINSE_WASHPRO_EMAIL=...
# RINSE_WASHPRO_PASSWORD=...
# RINSE_VEEWASH_EMAIL=...
# RINSE_VEEWASH_PASSWORD=...
```

### 3. Upload session files (Kudu / SSH)

On the API host, create and upload Playwright auth JSON **once per vendor** (after logging in on the server or copy from a Mac save-session):

```
/home/site/rinse-tenants/washpro/rinse-auth.json
/home/site/rinse-tenants/veewash/rinse-auth.json
```

Or under the repo after deploy:

```
scripts/rinse-cleanertickets/tenants/washpro/rinse-auth.json
scripts/rinse-cleanertickets/tenants/veewash/rinse-auth.json
```

(point `RINSE_*_STORAGE_STATE` at the path you use)

Restart the API after changing `.env`.

---

## B) Mac users (double-click package)

### One-time

```bash
cd rinse-cleanertickets
cp .env.example .env
cp tenants/washpro/.env.example tenants/washpro/.env
cp tenants/veewash/.env.example tenants/veewash/.env
# Edit each tenants/*/.env — tickets URL; email/password only if needed

npm install
npx playwright install chromium
```

1. Double-click **`save-session.command`** → **WashPro** → log in → Enter  
2. Double-click **`save-session.command`** again → **VeeWash** → log in → Enter  

### Each scrape

- Double-click **`run-local-portal-csv.command`** → pick vendor → CSV in `tenants/<vendor>/TODAY/`

---

## C) Windows users

### One-time

1. Install Node LTS from https://nodejs.org/  
2. Open **Command Prompt** in `rinse-cleanertickets`  
3. `copy tenants\washpro\.env.example tenants\washpro\.env`  
4. `copy tenants\veewash\.env.example tenants\veewash\.env`  
5. Edit both `.env` files (tickets URL)  
6. `npm install`  
7. `npx playwright install chromium`  
8. Double-click **`save-session.cmd`** → pick **WashPro** → log in → Enter  
9. Double-click **`save-session.cmd`** again → **VeeWash**  

### Each scrape

- Double-click **`run-local-portal-csv.cmd`** → pick vendor → CSV under `tenants\<vendor>\TODAY\`

---

## Folder layout

```
tenants/
  washpro/
    .env              ← WASHPRO email/URL (password optional)
    rinse-auth.json   ← WASHPRO session
    TODAY/            ← CSV output
    ARCHIVE/
  veewash/
    .env
    rinse-auth.json
    TODAY/
    ARCHIVE/
```

---

## Zip for users

Zip **`rinse-cleanertickets`** including `tenants/washpro/.env.example` and `tenants/veewash/.env.example`.  
**Exclude:** `.env`, `tenants/*/.env`, `rinse-auth.json`, `tenants/*/rinse-auth.json`, CSVs, `node_modules` (optional include).
