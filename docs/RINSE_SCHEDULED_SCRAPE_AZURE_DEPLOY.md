# Azure deploy: scheduled Rinse scraper (multi-tenant)

**One ACA job** processes every org in `RINSE_SCHEDULED_ORG_IDS` **sequentially** (v1: no parallel scrapes). Per-org locks and per-org output folders keep tenants isolated.

## Verified organizations (production `laundryapp`)

| Org id | slug | Rinse vendor (typical) | v1 scheduled? |
|--------|------|------------------------|---------------|
| 1 | washpro | `washpro` | **No** — enable after VeeWash stable ≥1 day |
| 2 | washmate | — | No |
| **3** | **veewash** | `veewash` | **Yes** |
| 4 | platform | — | No |

**v1:** `RINSE_SCHEDULED_ORG_IDS=3` only.

**Later:** `RINSE_SCHEDULED_ORG_IDS=1,3` (Washpro + VeeWash) with both `tenants/washpro/` and `tenants/veewash/` on the file share.

---

## Multi-tenant checklist

| # | Requirement | How |
|---|-------------|-----|
| 1 | Multiple org IDs | `RINSE_SCHEDULED_ORG_IDS=3` → `1,3` |
| 2 | Per-tenant config | `tenants/<vendor>/.env` + `rinse-auth.json` on Azure Files |
| 3 | Separate CSVs/logs | `runs/org_<id>_<slug>/…` per run (not shared) |
| 4 | Per-org DB lock | `GET_LOCK(rinse_scrape_org_<id>)` + `rinse_scrape_runs` per org |
| 5 | Sequential v1 | Loop in `run_all_scheduled_scrapes` — one org at a time |
| 6 | Per-org auto-confirm | Each org: confirm only if its `NEEDS_ATTENTION = 0` |
| 7 | History by tenant | `rinse_scrape_runs.organization_id`, `tenant_slug`, counts, `imported_batch_id`, `error_message` |

---

## Variables (set once per shell)

```bash
cd /Users/kamisb./laundry_app

export AZ_RG="mkn_resgrp_centralus"
export AZ_LOCATION="centralus"

export ACR_NAME="laundryopsacr"              # globally unique; change if taken
export ACA_ENV="laundryops-aca-env"
export ACA_JOB="rinse-scrape-scheduled"      # one job for all tenants
export ACA_STORAGE_NAME="rinse-scrape-files"

export STORAGE_ACCOUNT="laundryopsstorage01"
export FILE_SHARE="rinse-scrape-data"

export IMAGE_NAME="laundryops-rinse-scheduler"
export IMAGE_TAG="v1"
```

---

## 0. Register Azure providers (once)

```bash
az account set --subscription "$(az account show --query id -o tsv)"

az provider register -n Microsoft.App --wait
az provider register -n Microsoft.OperationalInsights --wait
```

---

## 1. Build and push image (ACR)

```bash
az acr create \
  --resource-group "$AZ_RG" \
  --name "$ACR_NAME" \
  --sku Basic \
  --location "$AZ_LOCATION"

az acr build \
  --resource-group "$AZ_RG" \
  --registry "$ACR_NAME" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --file Dockerfile.rinse-scheduler \
  .

export ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
export FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
```

---

## 2. Azure Files: multi-tenant folder layout

```bash
az storage share create \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$FILE_SHARE" \
  --quota 20

export SHARE_ROOT="$(mktemp -d)"

# --- VeeWash (enabled v1) ---
mkdir -p "${SHARE_ROOT}/tenants/veewash"
cp scripts/rinse-tenants/veewash/.env "${SHARE_ROOT}/tenants/veewash/.env" 2>/dev/null \
  || cp scripts/rinse-tenants/veewash/.env.example "${SHARE_ROOT}/tenants/veewash/.env"
cp /path/to/veewash-rinse-auth.json "${SHARE_ROOT}/tenants/veewash/rinse-auth.json"

# Edit: absolute RINSE_STORAGE_STATE inside container
nano "${SHARE_ROOT}/tenants/veewash/.env"
```

**Required in `tenants/veewash/.env`:**

```env
RINSE_STORAGE_STATE=/data/rinse-scrape/tenants/veewash/rinse-auth.json
RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1
RINSE_MAX_PAGES=20
```

```bash
# --- Washpro (prepare now; do NOT add org 1 to RINSE_SCHEDULED_ORG_IDS until VeeWash is stable) ---
mkdir -p "${SHARE_ROOT}/tenants/washpro"
cp scripts/rinse-tenants/washpro/.env.example "${SHARE_ROOT}/tenants/washpro/.env"
# When ready: save-session.sh on Mac, copy rinse-auth.json, set RINSE_STORAGE_STATE=/data/rinse-scrape/tenants/washpro/rinse-auth.json

az storage file upload-batch \
  --account-name "$STORAGE_ACCOUNT" \
  --source "${SHARE_ROOT}" \
  --destination "$FILE_SHARE"

export STORAGE_KEY="$(az storage account keys list \
  --resource-group "$AZ_RG" \
  --account-name "$STORAGE_ACCOUNT" \
  --query '[0].value' -o tsv)"
```

| Purpose | Share path | Container path |
|---------|------------|----------------|
| VeeWash config | `tenants/veewash/.env` | `/data/rinse-scrape/tenants/veewash/.env` |
| VeeWash session | `tenants/veewash/rinse-auth.json` | `/data/rinse-scrape/tenants/veewash/rinse-auth.json` |
| Washpro config (later) | `tenants/washpro/.env` | `/data/rinse-scrape/tenants/washpro/.env` |
| Washpro session (later) | `tenants/washpro/rinse-auth.json` | `/data/rinse-scrape/tenants/washpro/rinse-auth.json` |
| VeeWash run audit | `runs/org_3_veewash/…` | `/data/rinse-scrape/runs/org_3_veewash/…` |

---

## 3. Container Apps environment + file mount

```bash
export LOG_WS="laundryops-aca-logs"
az monitor log-analytics workspace create \
  --resource-group "$AZ_RG" \
  --workspace-name "$LOG_WS" \
  --location "$AZ_LOCATION" 2>/dev/null || true

export LOG_WS_ID="$(az monitor log-analytics workspace show -g "$AZ_RG" -n "$LOG_WS" --query customerId -o tsv)"
export LOG_WS_KEY="$(az monitor log-analytics workspace get-shared-keys -g "$AZ_RG" -n "$LOG_WS" --query primarySharedKey -o tsv)"

az containerapp env create \
  --name "$ACA_ENV" \
  --resource-group "$AZ_RG" \
  --location "$AZ_LOCATION" \
  --logs-workspace-id "$LOG_WS_ID" \
  --logs-workspace-key "$LOG_WS_KEY"

az containerapp env storage set \
  --name "$ACA_ENV" \
  --resource-group "$AZ_RG" \
  --storage-name "$ACA_STORAGE_NAME" \
  --azure-file-account-name "$STORAGE_ACCOUNT" \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name "$FILE_SHARE" \
  --access-mode ReadWrite
```

---

## 4. Environment variables (job container)

Load MySQL from local `.env` (same as `laundryops-api`):

```bash
set -a && source .env && set +a
export TICKETS_URL="$(grep '^RINSE_TICKETS_URL=' "${SHARE_ROOT}/tenants/veewash/.env" | cut -d= -f2-)"
```

### v1 — VeeWash only

| Variable | Value |
|----------|--------|
| `RINSE_SCHEDULED_SCRAPE_ENABLED` | `1` |
| `RINSE_SCHEDULED_ORG_IDS` | **`3`** |
| `RINSE_VEEWASH_ORG_IDS` | `3` |
| `RINSE_SCRAPE_DATA_ROOT` | `/data/rinse-scrape` |
| `RINSE_VEEWASH_STORAGE_STATE` | `/data/rinse-scrape/tenants/veewash/rinse-auth.json` |
| `RINSE_VEEWASH_TICKETS_URL` | *(from veewash `.env`)* |
| `MYSQL_HOST` | *(from `.env`)* |
| `MYSQL_PORT` | `3306` |
| `MYSQL_USER` | *(from `.env`)* |
| `MYSQL_PASSWORD` | `secretref:mysql-password` |
| `MYSQL_DATABASE` | `laundryapp` |
| `RINSE_SCRAPE_TIMEOUT_SEC` | `1800` |
| `RINSE_SCRAPE_STALE_MINUTES` | `120` |
| `PLAYWRIGHT_BROWSERS_PATH` | `/ms-playwright` |

**Do not set** `RINSE_WASHPRO_ORG_IDS` or `RINSE_SCHEDULED_ORG_IDS=1` until VeeWash is stable.

### Future — Washpro + VeeWash

| Variable | Value |
|----------|--------|
| `RINSE_SCHEDULED_ORG_IDS` | `1,3` |
| `RINSE_WASHPRO_ORG_IDS` | `1` |
| `RINSE_VEEWASH_ORG_IDS` | `3` |
| `RINSE_WASHPRO_STORAGE_STATE` | `/data/rinse-scrape/tenants/washpro/rinse-auth.json` |
| `RINSE_WASHPRO_TICKETS_URL` | *(washpro Rinse list URL)* |

MySQL firewall: allow Azure services on `mkncentralussrv1.mysql.database.azure.com`.

---

## 5. Create job (Manual trigger first)

```bash
export ACR_PASSWORD="$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv)"

cat > /tmp/rinse-scrape-job.yaml <<EOF
properties:
  configuration:
    triggerType: Manual
    replicaTimeout: 3600
    replicaRetryLimit: 0
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_NAME}
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: ${ACR_PASSWORD}
      - name: mysql-password
        value: ${MYSQL_PASSWORD}
  template:
    volumes:
      - name: rinse-data
        storageType: AzureFile
        storageName: ${ACA_STORAGE_NAME}
    containers:
      - name: rinse-scheduler
        image: ${FULL_IMAGE}
        resources:
          cpu: 1.0
          memory: 2Gi
        volumeMounts:
          - volumeName: rinse-data
            mountPath: /data/rinse-scrape
        env:
          - name: RINSE_SCHEDULED_SCRAPE_ENABLED
            value: "1"
          - name: RINSE_SCHEDULED_ORG_IDS
            value: "3"
          - name: RINSE_VEEWASH_ORG_IDS
            value: "3"
          - name: RINSE_SCRAPE_DATA_ROOT
            value: "/data/rinse-scrape"
          - name: RINSE_VEEWASH_STORAGE_STATE
            value: "/data/rinse-scrape/tenants/veewash/rinse-auth.json"
          - name: RINSE_VEEWASH_TICKETS_URL
            value: "${TICKETS_URL}"
          - name: MYSQL_HOST
            value: "${MYSQL_HOST}"
          - name: MYSQL_PORT
            value: "3306"
          - name: MYSQL_USER
            value: "${MYSQL_USER}"
          - name: MYSQL_PASSWORD
            secretRef: mysql-password
          - name: MYSQL_DATABASE
            value: "laundryapp"
          - name: RINSE_SCRAPE_TIMEOUT_SEC
            value: "1800"
          - name: RINSE_SCRAPE_STALE_MINUTES
            value: "120"
          - name: PLAYWRIGHT_BROWSERS_PATH
            value: "/ms-playwright"
EOF

az containerapp job create \
  --name "$ACA_JOB" \
  --resource-group "$AZ_RG" \
  --environment "$ACA_ENV" \
  --yaml /tmp/rinse-scrape-job.yaml
```

---

## 6. Manual test (before `*/30` schedule)

```bash
az containerapp job start --name "$ACA_JOB" --resource-group "$AZ_RG"

az containerapp job execution list --name "$ACA_JOB" --resource-group "$AZ_RG" -o table

EXEC="$(az containerapp job execution list -n "$ACA_JOB" -g "$AZ_RG" --query '[0].name' -o tsv)"

az containerapp job logs show \
  --name "$ACA_JOB" \
  --resource-group "$AZ_RG" \
  --execution "$EXEC" \
  --container rinse-scheduler \
  --follow
```

Expect log lines: `rinse scheduled scrape: 1 organization(s) sequential — [3]` then `organization 3 (1/1)`.

**Local:**

```bash
export RINSE_SCHEDULED_SCRAPE_ENABLED=1
export RINSE_SCHEDULED_ORG_IDS=3
export RINSE_VEEWASH_ORG_IDS=3
export RINSE_SCRAPE_DATA_ROOT=./data/rinse-scrape
set -a && source .env && set +a
python3 -m backend.jobs.run_scheduled_rinse_scrape --organization-id 3
```

---

## 7. Enable schedule (after manual success)

```bash
az containerapp job update \
  --name "$ACA_JOB" \
  --resource-group "$AZ_RG" \
  --trigger-type Schedule \
  --cron-expression "*/5 * * * *"
# Poll every 5 minutes UTC. App enforces completion-driven cadence:
# next scrape is eligible only after previous finished_at + 30 minutes
# (RINSE_SCRAPE_POST_RUN_COOLDOWN_MINUTES). No catch-up queue; lock prevents overlap.
```

Cron is **UTC**. Overlap: if org 3’s scrape exceeds 30 minutes, the next trigger may start but org 3 will **`skipped`** (per-org lock); other orgs can still run when added.

---

## 8. Verify import + auto-confirm (per tenant)

```sql
-- All tenants, newest first
SELECT id, organization_id, tenant_slug, rinse_vendor, status,
       started_at, finished_at, duration_seconds,
       portal_rows_count, scan_events_count, imported_batch_id,
       error_message, log_path
FROM rinse_scrape_runs
ORDER BY started_at DESC
LIMIT 20;

-- VeeWash only
SELECT * FROM rinse_scrape_runs WHERE organization_id = 3 ORDER BY started_at DESC LIMIT 5;

SELECT id, batch_date, state, confirmed_at
FROM upload_batches
WHERE organization_id = 3
ORDER BY id DESC
LIMIT 5;
```

| `rinse_scrape_runs.status` | Meaning |
|----------------------------|---------|
| `success` | Scraped + imported + **auto-confirmed** for that org |
| `needs_attention` | Draft `imported_batch_id` left for **that org** in UI |
| `failed` | No confirm; check `error_message` + `log_path` |
| `skipped` | That org’s previous run still active |

**File log:** `runs/org_3_veewash/<date>_<time>_scheduled/orchestrator.log` on the share.

---

## 9. Disable quickly (rollback)

```bash
# Stop cron; manual executions still possible
az containerapp job update \
  --name "$ACA_JOB" \
  --resource-group "$AZ_RG" \
  --trigger-type Manual
```

Or set `RINSE_SCHEDULED_SCRAPE_ENABLED=0` on the job env.

Manual UI upload is unchanged. `rinse_scrape_runs` history remains.

---

## 10. Enable Washpro later (after VeeWash ≥1 day clean)

1. `save-session.sh` for washpro → upload `tenants/washpro/rinse-auth.json`.
2. Update job env:
   - `RINSE_SCHEDULED_ORG_IDS=1,3`
   - `RINSE_WASHPRO_ORG_IDS=1`
   - `RINSE_WASHPRO_STORAGE_STATE=/data/rinse-scrape/tenants/washpro/rinse-auth.json`
   - `RINSE_WASHPRO_TICKETS_URL=…`
3. Manual test: `az containerapp job start …` and confirm **two** sequential blocks in logs (`organization 3`, then `organization 1` — order follows list in `RINSE_SCHEDULED_ORG_IDS`).
