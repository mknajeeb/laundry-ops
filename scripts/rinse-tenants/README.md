# Moved: use `rinse-cleanertickets/tenants/` (Mac user package)

Per-vendor folders and interactive WashPro / VeeWash prompts now live in:

**`scripts/rinse-cleanertickets/`**

- `tenants/washpro/` and `tenants/veewash/`
- `run-local-portal-csv.command` — asks vendor, writes to `tenants/<vendor>/TODAY/`
- `save-session.command` — save login per vendor

See **`USER_LOCAL_SCRAPE.md`** in that folder.

The old `rinse-tenants/washpro` scripts are optional; the user zip should be built from `rinse-cleanertickets` only.
