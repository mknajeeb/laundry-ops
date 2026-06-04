# Payroll Planning Layer — Staging / Test Deploy

**Do not deploy to production (`main` push) until QA sign-off.**

## Production restriction (confirmed)

| Rule | Status |
|------|--------|
| No production App Service deploy from this runbook | Use **staging slot** or local dev only |
| No production migration without `PAYROLL_PLANNING_ALLOW_MIGRATE=1` + explicit approval | Script blocks `laundryapp` by default |
| No production partner roster links | Create links only on staging DB |
| `main` CI still deploys production | **Do not merge to `main` yet** |

## URLs

| Environment | Frontend | API |
|-------------|----------|-----|
| Production (unchanged until merge) | https://zealous-bay-0fb502610.4.azurestaticapps.net | https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net |
| Staging slot (after workflow) | Use SWA **PR preview** or local `npm run dev` with `VITE_API_BASE` → staging API | https://laundryops-api-staging.azurewebsites.net (if slot exists) |
| Local dev | http://localhost:5173 | http://127.0.0.1:8000 (proxy) |

## Branch and commit

```bash
git checkout -b feature/payroll-planning-layer
# commit payroll planning files only
git push -u origin feature/payroll-planning-layer
```

GitHub Actions: **Deploy payroll planning to staging slot** (`.github/workflows/deploy-payroll-planning-staging.yml`).

Open a **PR to `main`** for Static Web App preview build (frontend only; set PR build `VITE_API_BASE` to staging API if testing full stack).

## Migration order (staging DB only)

1. Backup staging database.
2. Run:

```bash
export PAYROLL_PLANNING_ALLOW_MIGRATE=1   # only when targeting staging/test DB
./scripts/apply_payroll_planning_mysql.sh
```

Files applied in order:

1. `backend/sql/payroll_schedule_v1.sql`
2. `backend/sql/payroll_schedule_v2.sql`
3. `backend/sql/payroll_roster_share_v1.sql`
4. `backend/sql/payroll_calendar_settings_v1.sql`

Migrations are **additive** (`CREATE TABLE IF NOT EXISTS`, `ALTER` add columns). No `DROP` of operational tables.

Tables created/extended include: `payroll_schedule_org_settings`, `payroll_schedule_entries`, `payroll_worker_profiles`, availability/skills tables, `payroll_schedule_coverage_targets`, `payroll_schedule_change_log`, `payroll_roster_share_links`, `payroll_calendar_settings`.

**Note:** First API use also runs `ensure_payroll_schedule_tables` / `ensure_payroll_schedule_v2` if SQL was skipped.

## Sample workers (staging)

```bash
PAYROLL_PLANNING_ALLOW_MIGRATE=1 python3 scripts/seed_payroll_planning_staging_workers.py --org-id YOUR_ORG_ID
PAYROLL_PLANNING_ALLOW_MIGRATE=1 python3 scripts/seed_payroll_planning_staging_workers.py --org-id YOUR_ORG_ID --dry-run
```

Emails: `planning-w2-alice@staging.local`, … `planning-wrongloc-jake@staging.local` (see script).

## Routes to test

| Screen | Route |
|--------|-------|
| Employee profile → Scheduling tab | `/employees/:userId` |
| People list | `/employees` |
| Payroll → Scheduling | Payroll hub → **Scheduling** tab |
| Funding forecast | Same page (forecast card) |
| Public partner roster | `/roster/:token` |

## User testing checklist

See `docs/PAYROLL_PLANNING_QA_REPORT.md` and `docs/SCHEDULING_QA.md`.

## Rollback

1. **Code:** redeploy previous build to staging slot (or stop using feature branch).
2. **DB:** new tables can remain empty; no destructive DDL. To remove: drop planning tables only on **staging** after backup (not required for rollback of code).
3. **Roster links:** revoke in app or `UPDATE payroll_roster_share_links SET revoked_at=NOW()`.

## Security (staging)

Automated tests cover: no public rates/costs/forecast; token/PIN/revoke/expired. Re-verify on staging after creating a real share link.
