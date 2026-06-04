# Payroll Planning Layer — Production Deploy Report

**Deploy date (UTC):** 2026-06-04  
**Deployed commit:** `e971a39` (merge of `feature/payroll-planning-layer` → `main`)  
**Prior production commit:** `63aedf0`

## Pre-flight confirmations

| Check | Result |
|-------|--------|
| Branch before merge | `feature/payroll-planning-layer` |
| `main` = production deploy branch | Yes |
| Production database | `laundryapp` on `mkncentralussrv1` |
| API / frontend healthy pre-deploy | API 200, SWA 200 |
| Payroll batch / payout / approved-hours **not** in this deploy | Yes — planning layer only |
| Scope | Scheduling profile, planner, roster share, funding forecast |

## Production backup

| Field | Value |
|-------|--------|
| **On-demand backup name** | `customer-20260604t231104-d30cc70e-5a85-4b5c-bf09-8c36765c45cf-payroll-planning-20260604` |
| **Completed (UTC)** | 2026-06-04T23:11:08Z |
| **Type** | FULL (Customer) |
| **Server** | `mkncentralussrv1` / `mkn_resgrp_centralus` |
| **Rollback** | Azure Portal → MySQL flexible server → Backups → restore to new server or point-in-time |

Latest automatic backup before deploy: `daily-20260603t234032-…` (2026-06-03).

## Migration status

| File | Result |
|------|--------|
| `payroll_schedule_v1.sql` | Applied via script |
| `payroll_schedule_v2.sql` | SQL `ADD COLUMN IF NOT EXISTS` not supported on Azure MySQL 8; columns/tables applied via `ensure_payroll_schedule_v2()` |
| `payroll_roster_share_v1.sql` | Applied via script |
| `payroll_calendar_settings_v1.sql` | SQL apply failed (COMMENT semicolon in splitter); table created via `ensure_payroll_calendar_settings()` |

**Additive only:** no `DROP TABLE` in these four files. FK `ON DELETE CASCADE` only on new planning tables.

**Tables verified present:** `payroll_schedule_entries`, `payroll_worker_profiles`, `payroll_roster_share_links`, `payroll_calendar_settings`, `payroll_schedule_change_log`, etc.

## Deploy

- **Git:** `git push origin main` → GitHub Actions deploy API + Static Web App.
- **URLs:** https://zealous-bay-0fb502610.4.azurestaticapps.net · https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net

## Access control

- **API:** `ta.monitor` or `ta.settings` on `/api/ta/payroll/schedule/*`, funding forecast, roster share admin routes.
- **UI:** Payroll → Scheduling visible when `canTime` (same permissions or ADMIN).
- **Public roster:** Only when admin creates a link; no auto-created links.

## Not deployed

- Payroll batch generation workflow changes
- Accountant approval / payout export
- Pay stubs / W-2 / 1099 year-end
- Approved-hours batch workflow

## Rollback

| Layer | Action |
|-------|--------|
| **Frontend** | Redeploy SWA from commit `63aedf0` or revert merge on `main` |
| **Backend** | Redeploy API from `63aedf0` |
| **Database** | Keep additive tables; old app ignores them. Restore backup only if data corruption. |
| **Roster links** | Revoke test links in app |

## Post-deploy smoke test (manual)

Admin login required for steps 1–9. See instruction §7–9 in deploy request.

## Controlled testing

- Use 1–2 test employees only; do not bulk-edit real profiles.
- Revoke test roster links after security check.
