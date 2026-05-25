# Scheduled Rinse scrape (multi-tenant, Azure Container Apps)

Runs **outside** `laundryops-api`. One ACA job processes **multiple organizations sequentially** (v1: no parallel scrapes).

Manual upload in the UI is unchanged.

## Multi-tenant design

| Concern | Behavior |
|---------|----------|
| **Which orgs run** | `RINSE_SCHEDULED_ORG_IDS` — comma-separated, e.g. `3` now, `1,3` later |
| **Vendor mapping** | `RINSE_WASHPRO_ORG_IDS`, `RINSE_VEEWASH_ORG_IDS` (same as API; see `backend/rinse_vendor_config.py`) |
| **Auth + .env** | Per vendor folder on Azure Files: `tenants/veewash/`, `tenants/washpro/` |
| **Scrape output + logs** | Per org under `runs/org_<id>_<slug>/` — never mixed between tenants |
| **DB lock** | Per `organization_id` (`GET_LOCK` + `rinse_scrape_runs`) — VeeWash running does not block Washpro |
| **Auto-confirm** | Per org: confirm only if that org’s batch has `NEEDS_ATTENTION = 0` |
| **History** | `rinse_scrape_runs` row per org per execution (`organization_id`, `tenant_slug`, counts, `imported_batch_id`, …) |

### v1 deployment (now)

- Enable **only** `RINSE_SCHEDULED_ORG_IDS=3` (VeeWash).
- Prepare `tenants/washpro/` on the file share if you want, but **do not** add `1` to scheduled IDs until VeeWash is stable for at least one full day.

### Future

```bash
RINSE_SCHEDULED_ORG_IDS=1,3
RINSE_WASHPRO_ORG_IDS=1
RINSE_VEEWASH_ORG_IDS=3
RINSE_WASHPRO_STORAGE_STATE=/data/rinse-scrape/tenants/washpro/rinse-auth.json
RINSE_VEEWASH_STORAGE_STATE=/data/rinse-scrape/tenants/veewash/rinse-auth.json
```

## Enable (single job, all tenants)

| Variable | v1 example | Notes |
|----------|------------|--------|
| `RINSE_SCHEDULED_SCRAPE_ENABLED` | `1` | Master gate |
| `RINSE_SCHEDULED_ORG_IDS` | `3` | Comma-separated org IDs |
| `RINSE_VEEWASH_ORG_IDS` | `3` | Org → `veewash` vendor |
| `RINSE_WASHPRO_ORG_IDS` | *(omit v1)* | Add `1` when enabling Washpro |
| `RINSE_VEEWASH_STORAGE_STATE` | `/data/rinse-scrape/tenants/veewash/rinse-auth.json` | |
| `RINSE_VEEWASH_TICKETS_URL` | *(from veewash `.env`)* | |
| `RINSE_SCRAPE_DATA_ROOT` | `/data/rinse-scrape` | Azure Files mount |
| `MYSQL_*` | *(same as API)* | |
| `RINSE_SCRAPE_TIMEOUT_SEC` | `1800` | Per subprocess **per org** |
| `RINSE_SCRAPE_STALE_MINUTES` | `120` | Per-org stale lock |

## Azure Files layout

```
/data/rinse-scrape/
  tenants/
    veewash/
      .env
      rinse-auth.json
    washpro/              # optional until Washpro enabled
      .env
      rinse-auth.json
  runs/
    org_3_veewash/
      2026-05-24_143000_scheduled/
        portal.csv
        scan-events-tickets.csv
        scan-events-events.csv
        orchestrator.log
    org_1_washpro/        # future
      ...
```

Each `tenants/<vendor>/.env` must use **absolute** paths, e.g. `RINSE_STORAGE_STATE=/data/rinse-scrape/tenants/veewash/rinse-auth.json`.

## Local test

```bash
export RINSE_SCHEDULED_SCRAPE_ENABLED=1
export RINSE_SCHEDULED_ORG_IDS=3
export RINSE_VEEWASH_ORG_IDS=3
export RINSE_SCRAPE_DATA_ROOT=./data/rinse-scrape

python3 -m backend.jobs.run_scheduled_rinse_scrape --dry-run
python3 -m backend.jobs.run_scheduled_rinse_scrape --organization-id 3
```

Exit codes: `0` success, `1` any failed org, `3` any `needs_attention` (and no failures).

## Auto-confirm (per tenant)

| Outcome | `rinse_scrape_runs.status` |
|---------|----------------------------|
| 0 NEEDS_ATTENTION | `success` (batch confirmed for that org) |
| NEEDS_ATTENTION > 0 | `needs_attention` (that org’s draft only) |
| Empty CSV / all rejected / scrape error | `failed` |
| That org’s prior run still active | `skipped` |

## History query

```sql
SELECT id, organization_id, tenant_slug, rinse_vendor, status,
       started_at, finished_at, duration_seconds,
       portal_rows_count, scan_events_count, imported_batch_id,
       error_message, log_path
FROM rinse_scrape_runs
ORDER BY started_at DESC
LIMIT 20;
```

## Deploy

See **[RINSE_SCHEDULED_SCRAPE_AZURE_DEPLOY.md](./RINSE_SCHEDULED_SCRAPE_AZURE_DEPLOY.md)** for exact `az` commands.

## Rollback

1. `az containerapp job update … --trigger-type Manual` (or `RINSE_SCHEDULED_SCRAPE_ENABLED=0`).
2. Manual dual-CSV upload remains available.
3. Keep `rinse_scrape_runs` for audit.
